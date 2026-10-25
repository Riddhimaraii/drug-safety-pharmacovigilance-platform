"""
Generate the plain-language safety review report (Markdown) from the database.

    python report.py --db data/faers.db --out REPORT.md

The dashboard's "Review & Report" page calls build_report_md() too, so the
file and the app always agree.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import date

import pandas as pd

from pv_signals import weekly_anomalies, is_inherently_fatal, is_low_info


def _q(con, sql, params=()):
    return pd.read_sql_query(sql, con, params=list(params))


def md_table(df: pd.DataFrame, floatfmt: str = "{:,.1f}") -> str:
    if df.empty:
        return "_None found._\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append(floatfmt.format(v))
            elif isinstance(v, int):
                cells.append(f"{v:,}")
            else:
                cells.append(str(v).replace("|", "/"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def build_report_md(con: sqlite3.Connection) -> str:
    meta = dict(_q(con, "SELECT key, value FROM meta").values)
    ov = _q(con, """SELECT COUNT(*) n, SUM(serious) serious, SUM(death) deaths, SUM(hospitalised) hosp,
                    MIN(fda_date) d0, MAX(fda_date) d1, COUNT(DISTINCT occr_country) countries FROM cases""").iloc[0]
    n = int(ov["n"])
    n_drugs = int(_q(con, "SELECT COUNT(*) n FROM drug_profile").iloc[0, 0])
    n_pt = int(_q(con, "SELECT COUNT(DISTINCT pt) n FROM reactions").iloc[0, 0])
    demo = _q(con, """SELECT SUM(sex='Female') f, SUM(sex='Male') m, AVG(age_years) mean_age,
                      SUM(age_years IS NOT NULL) age_known, SUM(age_years>=65) a65 FROM cases""").iloc[0]
    med_age = _q(con, "SELECT age_years FROM cases WHERE age_years IS NOT NULL")["age_years"].median()
    rep = _q(con, "SELECT reporter_type, COUNT(*) n FROM cases GROUP BY 1 ORDER BY n DESC")
    rep["share"] = 100 * rep["n"] / n
    wk = _q(con, "SELECT fda_week week, COUNT(*) n FROM cases WHERE fda_week IS NOT NULL GROUP BY 1 ORDER BY 1")
    full = wk[wk["n"] >= 0.5 * wk["n"].median()]

    top_drugs = _q(con, """SELECT drug_norm AS drug, n_cases AS reports, pct_serious AS "serious_%", pct_death AS "fatal_%",
                           median_age, pct_consumer AS "consumer_%", pct_lawyer AS "lawyer_%"
                           FROM drug_profile ORDER BY n_cases DESC LIMIT 10""")
    top_pts = _q(con, """SELECT r.pt AS reaction, COUNT(*) AS reports FROM reactions r
                         GROUP BY r.pt ORDER BY reports DESC LIMIT 60""")
    top_pts = top_pts[is_low_info(top_pts["reaction"]) == 0].head(10)

    stim = _q(con, """SELECT drug_norm AS drug, n_cases AS reports, pct_lawyer AS "lawyer_%", pct_consumer AS "consumer_%"
                      FROM drug_profile WHERE n_cases >= 300 AND pct_lawyer >= 30 ORDER BY n_cases DESC LIMIT 8""")
    sig_vol = _q(con, """SELECT drug_norm AS drug, pt AS reaction, a AS reports, prr AS PRR, ror_lcl AS "ROR_lower_95",
                     pct_fatal AS "fatal_%" FROM signals
                     WHERE evans_signal=1 AND low_info=0 AND a>=50 AND prr>=5 AND ror_lcl>1 ORDER BY a DESC LIMIT 12""")
    sig = _q(con, """SELECT drug_norm AS drug, pt AS reaction, a AS reports, prr AS PRR, ror_lcl AS "ROR_lower_95",
                     pct_fatal AS "fatal_%" FROM signals
                     WHERE evans_signal=1 AND low_info=0 AND a>=20 AND ror_lcl>1 ORDER BY prr DESC LIMIT 12""")
    sig_fatal = _q(con, """SELECT drug_norm, pt, a AS reports, prr AS PRR, pct_fatal AS "fatal_%"
                           FROM signals WHERE evans_signal=1 AND low_info=0 AND a>=20 AND pct_fatal>=50
                           ORDER BY a DESC LIMIT 60""")
    sig_fatal = sig_fatal[~is_inherently_fatal(sig_fatal["pt"])].head(10).rename(
        columns={"drug_norm": "drug", "pt": "reaction"})
    n_evans = int(_q(con, "SELECT COUNT(*) FROM signals WHERE evans_signal=1 AND low_info=0").iloc[0, 0])
    n_pairs = int(_q(con, "SELECT COUNT(*) FROM signals").iloc[0, 0])

    weekly = _q(con, "SELECT drug_norm, week, n_cases FROM weekly_drug")
    an = weekly_anomalies(weekly).head(10)
    an = an[["drug_norm", "week", "n_cases", "baseline", "x_typical"]].rename(
        columns={"drug_norm": "drug", "n_cases": "reports", "baseline": "typical_week", "x_typical": "times_typical"})

    dqc = _q(con, "SELECT category, check_name AS \"check\", affected, total, pct AS \"pct_%\", severity FROM dq_checks WHERE category <> 'Safety review'")
    dq_hi = dqc[dqc["severity"].isin(["high", "medium"])].sort_values("pct_%", ascending=False).head(10)
    flags = _q(con, "SELECT flag_type, severity, COUNT(*) AS cases FROM review_flags GROUP BY 1,2 ORDER BY cases DESC")

    L = []
    L.append(f"# Drug Safety & Pharmacovigilance Review\n")
    L.append(f"_Generated {date.today():%d %b %Y} from FDA FAERS quarterly data: {meta.get('quarters', '')}. "
             f"Database built {meta.get('built_at', '')}._\n")
    L.append("> **Purpose.** Summarise reporting patterns in spontaneous adverse-event reports and list "
             "drug-reaction pairs and records that deserve **human review**. Nothing here shows that a drug causes a reaction.\n")

    L.append("## 1. Dataset at a glance\n")
    L.append(f"- **{n:,}** unique cases (latest version of each case), received by FDA between "
             f"**{ov['d0']}** and **{ov['d1']}**; reaction terms: **{n_pt:,}** MedDRA preferred terms; "
             f"drugs (primary suspect, standardised to active ingredient): **{n_drugs:,}**.")
    L.append(f"- **{100 * ov['serious'] / n:.1f}%** of cases carry at least one serious outcome "
             f"({int(ov['deaths']):,} deaths = {100 * ov['deaths'] / n:.1f}%; {int(ov['hosp']):,} hospitalisations = "
             f"{100 * ov['hosp'] / n:.1f}%).")
    sex_known = demo["f"] + demo["m"]
    L.append(f"- Patients: {100 * demo['f'] / sex_known:.0f}% female among cases with known sex "
             f"({int(sex_known):,} of {n:,}); median age {med_age:.0f} years "
             f"({100 * demo['a65'] / demo['age_known']:.0f}% aged 65+, age known for {100 * demo['age_known'] / n:.0f}% of cases).")
    L.append(f"- Reporters: " + ", ".join(f"{r.reporter_type} {r.share:.0f}%" for r in rep.head(5).itertuples()) + ".\n")

    L.append("## 2. Key reporting patterns\n")
    if len(full):
        L.append(f"- **Volume:** {full['n'].min():,.0f}-{full['n'].max():,.0f} reports per full week "
                 f"(median {full['n'].median():,.0f}); first/last weeks of an extract are partial and are ignored for trend checks.")
    L.append("- **Most-reported primary-suspect drugs**\n")
    L.append(md_table(top_drugs))
    L.append("- **Most-reported reaction terms** (excluding non-specific terms such as 'Drug ineffective' / 'Off label use')\n")
    L.append(md_table(top_pts))
    if len(stim):
        L.append("- **Possible stimulated reporting.** These drugs have a large share of reports from lawyers, a pattern "
                 "often linked to litigation. Their report counts and PRRs may overstate real-world frequency.\n")
        L.append(md_table(stim))

    L.append("## 3. Drug-reaction pairs flagged for review\n")
    L.append(f"Of **{n_pairs:,}** drug-reaction pairs with at least 3 reports, **{n_evans:,}** meet the Evans screening "
             "criteria (n>=3, PRR>=2, chi-square>=4) after removing non-specific terms. Two views follow.\n")
    L.append("**a) Largest strong signals** - at least 50 reports, PRR>=5, 95% ROR lower bound above 1, ranked by number of reports:\n")
    L.append(md_table(sig_vol))
    L.append("**b) Most disproportionate pairs** - at least 20 reports, ranked by PRR (rare drug + rare reaction pairs rise to the top, "
             "so this view surfaces unusual and often highly specific effects):\n")
    L.append(md_table(sig))
    L.append("**c) Pairs where at least half of the reports are fatal** (n>=20, terms that are fatal by definition such as 'Completed suicide' removed):\n")
    L.append(md_table(sig_fatal))
    L.append("_How to read it:_ a high PRR means the reaction is reported far more often for this drug than for other drugs. "
             "Check each pair against the product label and literature before concluding anything - known, expected effects "
             "(for example an injection-site reaction for an injectable) will also score highly.\n")

    L.append("## 4. Unusual reporting trends\n")
    L.append("Weekly report counts were compared with each drug's own typical week (robust z-score >= 3.5, at least 10 reports in the week).\n")
    L.append(md_table(an) if len(an) else "_No drug showed an unusual weekly spike with these thresholds._\n")
    L.append("Sudden spikes often come from **batch submissions** (a manufacturer or law firm filing many old cases at once), "
             "so check the submission source before treating a spike as new safety information.\n")

    L.append("## 5. Data quality\n")
    L.append("Largest issues (high / medium severity):\n")
    L.append(md_table(dq_hi))
    L.append("Handling rules: only the latest version of each case is kept; ages converted to years and set to missing "
             "when outside 0-120; weights converted to kg and checked; drug names standardised to active ingredient; "
             "duplicate reaction terms removed; placeholders such as 'UNKNOWN' excluded from drug-level analysis.\n")

    L.append("## 6. Records and trends flagged for human review\n")
    L.append(md_table(flags))
    L.append("Priority order suggested: (1) fatal cases that contain a strong signal, (2) records with impossible values, "
             "(3) possible duplicates, (4) records missing a reaction or suspect drug.\n")

    L.append("## 7. Limitations\n")
    L.append("- Reports are voluntary and incomplete; the real number of patients exposed is unknown, so rates cannot be calculated.\n"
             "- A report does not prove the drug caused the event; underlying disease, other medicines and coincidence are common explanations.\n"
             "- Reporting is affected by publicity, litigation, drug age and regulatory requirements (stimulated reporting).\n"
             "- Age, sex, dates and outcomes are often missing, so some charts describe only a subset of cases.\n"
             "- Possible-duplicate detection is rule-based and will miss some duplicates and over-flag some separate patients.\n"
             "- One quarter of data limits trend analysis; load more quarters for longer trends.\n")
    L.append("## 8. Suggested next steps\n")
    L.append("1. Medical reviewers assess the top flagged pairs against label, literature and clinical plausibility.\n"
             "2. Request follow-up information (dates, dose, concomitant drugs, dechallenge/rechallenge) for fatal flagged cases.\n"
             "3. Confirm trend spikes with the company's own safety database and check for news, recalls or litigation notices.\n"
             "4. Fix upstream data-capture issues behind the largest data-quality gaps.\n"
             "5. Add more quarters and re-run to see whether signals persist.\n")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/faers.db")
    ap.add_argument("--out", default="REPORT.md")
    a = ap.parse_args()
    con = sqlite3.connect(a.db)
    text = build_report_md(con)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"Wrote {a.out} ({len(text):,} characters)")
