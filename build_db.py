#!/usr/bin/env python3
"""
Build a SQLite database from FDA FAERS quarterly ASCII extracts.

Usage:
    python build_db.py --data-dir data/raw --db data/faers.db

Drop one or more quarters (DEMOyyQq, DRUGyyQq, REACyyQq, OUTCyyQq, RPSRyyQq,
THERyyQq, INDIyyQq .txt files) into --data-dir. Several quarters are merged and
only the latest version of each case is kept.

What it does
  1. Loads the '$'-delimited files and keeps the latest version of every case.
  2. Cleans / standardises: ages -> years, weight -> kg, sex, dates, drug names.
  3. Runs data-quality checks and stores them (dq_checks, review_flags).
  4. Computes PRR / ROR signal statistics (signals) and drug-level profiles.
  5. Writes everything to SQLite with indexes for fast dashboard queries.
"""
import argparse
import os
import re
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

from pv_signals import compute_signals, is_inherently_fatal

AGE_FACTOR = {"YR": 1.0, "DEC": 10.0, "MON": 1 / 12, "WK": 1 / 52.1775, "DY": 1 / 365.25, "HR": 1 / 8766}
AGE_BINS = [0, 2, 12, 18, 45, 65, 75, 121]
AGE_LABELS = ["0-1", "2-11", "12-17", "18-44", "45-64", "65-74", "75+"]
# FAERS AGE_GRP code -> plausible age range in years (used to find inconsistent records)
AGE_GRP_RANGE = {"N": (0, 0.1), "I": (0, 2), "C": (2, 12), "T": (12, 18), "A": (18, 65), "E": (65, 121)}
OUTC_MAP = {"DE": "death", "LT": "life_threatening", "HO": "hospitalised", "DS": "disability",
            "CA": "congenital_anomaly", "RI": "required_intervention", "OT": "other_serious"}
OCCP_MAP = {"MD": "Physician", "PH": "Pharmacist", "OT": "Other health professional",
            "LW": "Lawyer", "CN": "Consumer"}
UNSPECIFIED = {"", "UNKNOWN", "UNSPECIFIED", "NOT SPECIFIED", "UNK", "NONE", "NA", "N/A", "DRUG", "DRUGS"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------- loading
def find_files(data_dir, prefix):
    pat = re.compile(rf"^{prefix}(\d{{2}})Q([1-4]).*\.txt$", re.I)
    found, seen = [], set()
    for f in sorted(os.listdir(data_dir)):
        m = pat.match(f)
        if not m:
            continue
        quarter = f"20{m.group(1)}Q{m.group(2)}"
        if quarter in seen:  # e.g. OUTC20Q4.txt and OUTC20Q4_1.txt: keep only one copy
            log(f"  skipping {f} (another {prefix} file for {quarter} already used)")
            continue
        seen.add(quarter)
        found.append((os.path.join(data_dir, f), quarter))
    return found


def load(data_dir, prefix, usecols=None, required=True):
    files = find_files(data_dir, prefix)
    if not files:
        if required:
            sys.exit(f"ERROR: no {prefix}yyQq*.txt file found in {data_dir}")
        return None
    frames = []
    for path, quarter in files:
        log(f"  reading {os.path.basename(path)}")
        cols = (lambda c: c.strip().lower() in usecols) if usecols else None
        df = pd.read_csv(path, sep="$", dtype=str, encoding="latin-1", quoting=3,
                         low_memory=False, usecols=cols)
        df.columns = [c.strip().lower() for c in df.columns]
        df["quarter"] = quarter
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ----------------------------------------------------------------- helpers
def parse_full_date(s):
    """YYYYMMDD -> Timestamp; partial / invalid dates -> NaT."""
    s = s.where(s.str.len() == 8)
    return pd.to_datetime(s, format="%Y%m%d", errors="coerce")


def parse_month(s):
    s = s.where(s.str.len() >= 6).str[:6]
    return pd.to_datetime(s, format="%Y%m", errors="coerce")


def iso(ts):
    return ts.dt.strftime("%Y-%m-%d").where(ts.notna(), None)


def clean_drug_name(s):
    s = s.astype("string").str.upper().str.replace("\\", " / ", regex=False)
    s = s.str.replace(r"\s+", " ", regex=True).str.strip(" .,;")
    return s


def dq(rows, category, check, affected, total, severity, description):
    rows.append(dict(category=category, check_name=check, affected=int(affected), total=int(total),
                     pct=round(100 * affected / total, 2) if total else 0.0,
                     severity=severity, description=description))


# ----------------------------------------------------------------- cases
def build_cases(demo, outc, checks, flags):
    raw_rows = len(demo)
    d = demo.rename(columns={"gndr_cod": "sex", "i_f_cod": "i_f_code"}).copy()
    for col in ["sex", "age_grp", "age", "age_cod", "wt", "wt_cod", "event_dt", "occp_cod",
                "occr_country", "reporter_country", "mfr_sndr", "rept_cod", "i_f_code", "fda_dt"]:
        if col not in d:
            d[col] = np.nan
    d["primaryid"] = pd.to_numeric(d["primaryid"], errors="coerce")
    d["caseid"] = pd.to_numeric(d["caseid"], errors="coerce")
    d = d.dropna(subset=["primaryid", "caseid"])
    d["caseversion_n"] = pd.to_numeric(d["caseversion"], errors="coerce").fillna(0)
    d = d.sort_values(["caseid", "caseversion_n", "fda_dt"]).drop_duplicates("caseid", keep="last")
    n = len(d)
    dq(checks, "Duplicates", "Older case versions removed", raw_rows - n, raw_rows, "info",
       "Same CASEID appears in several versions/quarters; only the latest version is kept.")

    d["primaryid"] = d["primaryid"].astype("int64")
    d["caseid"] = d["caseid"].astype("int64")

    # --- dates
    d["fda_date"] = parse_full_date(d["fda_dt"])
    d["fda_week"] = d["fda_date"] - pd.to_timedelta(d["fda_date"].dt.dayofweek, unit="D")
    d["event_date"] = parse_full_date(d["event_dt"])
    d["event_month_ts"] = parse_month(d["event_dt"])
    d["event_month"] = d["event_month_ts"].dt.strftime("%Y-%m").where(d["event_month_ts"].notna(), None)

    # --- age (convert every unit to years)
    age_raw = pd.to_numeric(d["age"], errors="coerce")
    factor = d["age_cod"].map(AGE_FACTOR)
    age_years = age_raw * factor
    bad_range = age_years.notna() & ((age_years < 0) | (age_years > 120))
    unit_missing = age_raw.notna() & factor.isna()
    age_years = age_years.where(~bad_range)
    d["age_years"] = age_years.round(2)
    d["age_band"] = pd.cut(d["age_years"], AGE_BINS, labels=AGE_LABELS, right=False).astype("object")
    d["age_band"] = d["age_band"].where(d["age_years"].notna(), "Unknown")

    # --- weight (kg)
    wt = pd.to_numeric(d["wt"], errors="coerce")
    wt_kg = wt * d["wt_cod"].map({"KG": 1.0, "LBS": 0.45359237, "GMS": 0.001})
    wt_bad = wt_kg.notna() & ((wt_kg < 0.3) | (wt_kg > 400))
    d["weight_kg"] = wt_kg.where(~wt_bad).round(1)

    # --- categorical standardisation
    d["sex"] = d["sex"].map({"F": "Female", "M": "Male"}).fillna("Unknown")
    d["reporter_type"] = d["occp_cod"].map(OCCP_MAP).fillna("Unknown")
    d["occr_country"] = d["occr_country"].fillna("Unknown")
    d["reporter_country"] = d["reporter_country"].where(
        ~d["reporter_country"].isin(["COUNTRY NOT SPECIFIED"]), None)
    d["rept_type"] = d["rept_cod"].map({"EXP": "Expedited (15-day)", "PER": "Periodic",
                                        "DIR": "Direct (voluntary)"}).fillna("Other")

    # --- outcomes -> one 0/1 column per seriousness criterion
    o = outc[["primaryid", "outc_cod"]].copy()
    o["primaryid"] = pd.to_numeric(o["primaryid"], errors="coerce")
    o = o[o["outc_cod"].isin(OUTC_MAP) & o["primaryid"].notna()]
    o["primaryid"] = o["primaryid"].astype("int64")
    ox = pd.crosstab(o["primaryid"], o["outc_cod"]).clip(upper=1)
    ox = ox.reindex(columns=list(OUTC_MAP), fill_value=0).rename(columns=OUTC_MAP)
    d = d.merge(ox, left_on="primaryid", right_index=True, how="left")
    for col in OUTC_MAP.values():
        d[col] = d[col].fillna(0).astype(int)
    d["serious"] = (d[list(OUTC_MAP.values())].sum(axis=1) > 0).astype(int)

    # ---------- data-quality checks on cases
    # (label, column, core?) - core fields drive the analysis, so gaps there matter more
    for label, col, core in [("Age", "age_years", True), ("Sex", "sex", True), ("Event date", "event_dt", True),
                             ("Weight", "weight_kg", False), ("Reporter type", "occp_cod", False),
                             ("Age group code", "age_grp", False), ("Event country", "occr_country", False)]:
        s = d[col]
        miss = s.isna() | (s == "Unknown")
        sev = "high" if miss.mean() > 0.5 else "medium" if miss.mean() > 0.2 else "low"
        if not core:
            sev = "low" if sev != "low" else sev  # optional / redundant field
        dq(checks, "Missing values", f"{label} missing", miss.sum(), n, sev,
           f"Records with no usable {label.lower()}." + ("" if core else " (optional or redundant field)"))

    dq(checks, "Inconsistent records", "Age out of range (<0 or >120 y)", bad_range.sum(), n, "high",
       "Age value is impossible after converting to years (often a wrong unit code). Set to missing.")
    dq(checks, "Inconsistent records", "Age present but unit missing", unit_missing.sum(), n, "medium",
       "Cannot convert to years without a unit code. Set to missing.")
    dq(checks, "Inconsistent records", "Weight implausible (<0.3 kg or >400 kg)", wt_bad.sum(), n, "medium",
       "Weight is outside a plausible range after unit conversion. Set to missing.")
    dq(checks, "Inconsistent records", "Age not given in years (non-YR unit)",
       (d["age_cod"].notna() & (d["age_cod"] != "YR")).sum(), n, "info",
       "Decades, months, weeks, days and hours were converted to years.")

    ev_after = d["event_date"].notna() & d["fda_date"].notna() & (d["event_date"] > d["fda_date"])
    dq(checks, "Inconsistent records", "Event date after FDA receipt date", ev_after.sum(), n, "high",
       "An event cannot be reported before it happened; the dates need checking.")
    ev_old = d["event_date"].notna() & (d["event_date"].dt.year < 1950)
    dq(checks, "Inconsistent records", "Event date before 1950", ev_old.sum(), n, "medium",
       "Very old event dates are probably typing errors.")
    ev_len = d["event_dt"].str.len()
    dq(checks, "Inconsistent records", "Partial event date (year or year-month only)",
       ev_len.isin([4, 6]).sum(), n, "info", "Day (or month) is unknown; not used for exact timing.")
    bad_fmt = d["event_dt"].notna() & (ev_len == 8) & d["event_date"].isna()
    dq(checks, "Inconsistent records", "Event date malformed (e.g. month 13)", bad_fmt.sum(), n, "medium",
       "Eight-digit date that is not a real calendar date.")

    grp_mismatch = pd.Series(False, index=d.index)
    for code, (lo, hi) in AGE_GRP_RANGE.items():
        m = (d["age_grp"] == code) & d["age_years"].notna() & ((d["age_years"] < lo - 0.5) | (d["age_years"] >= hi + 0.5))
        grp_mismatch |= m
    dq(checks, "Inconsistent records", "Age group code disagrees with age", grp_mismatch.sum(), n, "medium",
       "AGE_GRP (e.g. 'Elderly') does not match the numeric age.")
    dq(checks, "Inconsistent records", "Sex coded UNK / NS",
       (demo["sex" if "sex" in demo else "gndr_cod"].isin(["UNK", "NS"])).sum(), raw_rows, "low",
       "Explicit 'unknown' or 'not specified' codes, treated the same as missing.")

    def add_flag(mask, kind, severity, detail):
        f = d.loc[mask, ["primaryid"]].copy()
        f["flag_type"], f["severity"], f["detail"] = kind, severity, detail
        flags.append(f)

    add_flag(bad_range, "AGE_IMPLAUSIBLE", "high", "Age outside 0-120 years after unit conversion")
    add_flag(unit_missing, "AGE_UNIT_MISSING", "medium", "Age given without unit code")
    add_flag(wt_bad, "WEIGHT_IMPLAUSIBLE", "medium", "Weight outside 0.3-400 kg")
    add_flag(ev_after, "EVENT_AFTER_FDA_RECEIPT", "high", "Event date later than FDA receipt date")
    add_flag(bad_fmt, "EVENT_DATE_MALFORMED", "medium", "Event date is not a valid calendar date")
    add_flag(grp_mismatch, "AGE_GROUP_MISMATCH", "medium", "AGE_GRP code does not match numeric age")
    return d


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--db", default="data/faers.db")
    ap.add_argument("--all-roles", action="store_true",
                    help="also keep concomitant/interacting drugs (bigger database)")
    ap.add_argument("--min-signal-cases", type=int, default=3)
    args = ap.parse_args()
    t0 = time.time()
    checks, flags = [], []

    log("Loading files ...")
    demo = load(args.data_dir, "DEMO")
    outc = load(args.data_dir, "OUTC", usecols={"primaryid", "outc_cod"})
    reac = load(args.data_dir, "REAC", usecols={"primaryid", "pt"})
    drug = load(args.data_dir, "DRUG", usecols={"primaryid", "drug_seq", "role_cod", "drugname", "prod_ai",
                                                "val_vbm", "route", "dose_amt", "dose_unit", "dose_form",
                                                "dose_freq", "dechal", "rechal"})
    ther = load(args.data_dir, "THER", usecols={"primaryid", "dsg_drug_seq", "start_dt"}, required=False)
    indi = load(args.data_dir, "INDI", usecols={"primaryid", "indi_drug_seq", "indi_pt"}, required=False)
    rpsr = load(args.data_dir, "RPSR", usecols={"primaryid", "rpsr_cod"}, required=False)

    log("Cleaning cases ...")
    cases = build_cases(demo, outc, checks, flags)
    n_cases = len(cases)
    valid_ids = set(cases["primaryid"])
    quarters = sorted(cases["quarter"].unique())
    del demo

    # ---------------- reactions
    log("Cleaning reactions ...")
    reac["primaryid"] = pd.to_numeric(reac["primaryid"], errors="coerce")
    reac = reac.dropna(subset=["primaryid", "pt"])
    reac["primaryid"] = reac["primaryid"].astype("int64")
    reac["pt"] = reac["pt"].str.strip()
    n_raw_r = len(reac)
    orphan_r = ~reac["primaryid"].isin(valid_ids)
    reac = reac[~orphan_r]
    dup_r = reac.duplicated(["primaryid", "pt"]).sum()
    reac = reac.drop_duplicates(["primaryid", "pt"])[["primaryid", "pt"]]
    dq(checks, "Duplicates", "Duplicate case-reaction pairs removed", dup_r, n_raw_r, "low",
       "The same MedDRA term repeated within one report.")
    dq(checks, "Referential integrity", "Reaction rows with no matching case (older versions)", orphan_r.sum(),
       n_raw_r, "info", "Belong to superseded case versions and are dropped.")
    n_react = reac.groupby("primaryid").size().rename("n_reactions")
    cases = cases.merge(n_react, left_on="primaryid", right_index=True, how="left")
    cases["n_reactions"] = cases["n_reactions"].fillna(0).astype(int)
    no_reac = cases["n_reactions"] == 0
    dq(checks, "Missing values", "Cases with no reaction term", no_reac.sum(), n_cases, "high",
       "A report without a reaction cannot be analysed.")
    f = cases.loc[no_reac, ["primaryid"]].copy()
    f["flag_type"], f["severity"], f["detail"] = "NO_REACTION_TERM", "high", "Report has no MedDRA reaction"
    flags.append(f)

    # ---------------- drugs
    log("Cleaning drugs ...")
    drug["primaryid"] = pd.to_numeric(drug["primaryid"], errors="coerce")
    drug = drug.dropna(subset=["primaryid"])
    drug["primaryid"] = drug["primaryid"].astype("int64")
    drug["drug_seq"] = pd.to_numeric(drug["drug_seq"], errors="coerce").fillna(0).astype("int32")
    n_raw_d = len(drug)
    orphan_d = ~drug["primaryid"].isin(valid_ids)
    drug = drug[~orphan_d]
    dq(checks, "Referential integrity", "Drug rows with no matching case", orphan_d.sum(), n_raw_d, "info",
       "Belong to superseded case versions and are dropped.")
    role_counts = drug["role_cod"].value_counts()
    if not args.all_roles:
        drug = drug[drug["role_cod"].isin(["PS", "SS"])]
    drug["drugname_clean"] = clean_drug_name(drug["drugname"])
    ai = clean_drug_name(drug["prod_ai"])
    ai = ai.where(~ai.isin(UNSPECIFIED))
    miss_ai = ai.isna()
    dq(checks, "Missing values", "Drug rows without an active-ingredient name", miss_ai.sum(), len(drug), "medium",
       "prod_ai is empty; the brand / verbatim name is used instead.")
    norm = ai.fillna(drug["drugname_clean"])
    norm = norm.where(~norm.isin(UNSPECIFIED) & norm.notna(), "UNSPECIFIED")
    drug["drug_norm"] = norm.astype(str)
    unspec = drug["drug_norm"] == "UNSPECIFIED"
    dq(checks, "Inconsistent records", "Drug name unspecified / unusable", unspec.sum(), len(drug), "medium",
       "Placeholder such as 'UNKNOWN'; excluded from drug-level analysis.")
    dq(checks, "Inconsistent records", "Verbatim (unvalidated) drug names", (drug["val_vbm"] == "2").sum(),
       len(drug), "low", "Name typed by reporter and not mapped to a validated trade name.")
    dq(checks, "Inconsistent records", "Same active ingredient written several ways",
       int(drug["drugname_clean"].nunique() - drug["drug_norm"].nunique()), int(drug["drugname_clean"].nunique()),
       "info", "Distinct brand/verbatim spellings collapsed into one active-ingredient name.")

    ps = drug[drug["role_cod"] == "PS"]
    n_ps = ps.groupby("primaryid").size()
    no_ps = ~cases["primaryid"].isin(n_ps.index)
    multi_ps = cases["primaryid"].isin(n_ps[n_ps > 1].index)
    dq(checks, "Missing values", "Cases with no primary-suspect drug", no_ps.sum(), n_cases, "medium",
       "No drug is marked as the primary suspect.")
    dq(checks, "Inconsistent records", "Cases with more than one primary-suspect drug", multi_ps.sum(), n_cases,
       "low", "Counted once for each drug in drug-level analysis.")
    f = cases.loc[no_ps, ["primaryid"]].copy()
    f["flag_type"], f["severity"], f["detail"] = "NO_PRIMARY_SUSPECT", "medium", "No primary-suspect drug"
    flags.append(f)
    ps_unspec = ps.loc[ps["drug_norm"] == "UNSPECIFIED", ["primaryid"]].drop_duplicates()
    ps_unspec["flag_type"], ps_unspec["severity"], ps_unspec["detail"] = (
        "PS_DRUG_UNSPECIFIED", "medium", "Primary-suspect drug name is a placeholder")
    flags.append(ps_unspec)

    # therapy start date -> time to onset ; first indication
    drug = drug.merge(cases[["primaryid", "event_date"]], on="primaryid", how="left")
    if ther is not None:
        log("Adding therapy dates ...")
        ther["primaryid"] = pd.to_numeric(ther["primaryid"], errors="coerce")
        ther["drug_seq"] = pd.to_numeric(ther["dsg_drug_seq"], errors="coerce")
        ther["start_date"] = parse_full_date(ther["start_dt"])
        first_start = (ther.dropna(subset=["primaryid", "drug_seq", "start_date"])
                       .groupby(["primaryid", "drug_seq"])["start_date"].min().reset_index())
        first_start["primaryid"] = first_start["primaryid"].astype("int64")
        first_start["drug_seq"] = first_start["drug_seq"].astype("int32")
        drug = drug.merge(first_start, on=["primaryid", "drug_seq"], how="left")
        tto = (drug["event_date"] - drug["start_date"]).dt.days
        neg = tto < 0
        sus = drug["role_cod"].isin(["PS", "SS"])
        dq(checks, "Inconsistent records", "Therapy started after the event (suspect drugs)",
           (neg & sus).sum(), int((sus & tto.notna()).sum()), "medium",
           "Start date later than event onset - possible restart or date error.")
        drug["tto_days"] = tto.where(~neg)
        del ther
    else:
        drug["tto_days"] = np.nan
    if indi is not None:
        log("Adding indications ...")
        indi["primaryid"] = pd.to_numeric(indi["primaryid"], errors="coerce")
        indi["drug_seq"] = pd.to_numeric(indi["indi_drug_seq"], errors="coerce")
        indi = indi.dropna(subset=["primaryid", "drug_seq", "indi_pt"])
        indi["primaryid"] = indi["primaryid"].astype("int64")
        indi["drug_seq"] = indi["drug_seq"].astype("int32")
        first_ind = indi.groupby(["primaryid", "drug_seq"], as_index=False)["indi_pt"].first()
        drug = drug.merge(first_ind.rename(columns={"indi_pt": "indication"}),
                          on=["primaryid", "drug_seq"], how="left")
        del indi
    else:
        drug["indication"] = None

    drug = drug[["primaryid", "drug_seq", "role_cod", "drug_norm", "drugname_clean", "route", "dose_amt",
                 "dose_unit", "dose_form", "dose_freq", "dechal", "rechal", "indication", "tto_days"]]
    drug = drug.rename(columns={"drugname_clean": "drugname"})
    drug["route"] = drug["route"].str.title()

    # ---------------- possible duplicate reports (different CASEID, same facts)
    log("Looking for possible duplicate reports ...")
    ps1 = ps.drop_duplicates("primaryid")[["primaryid", "drug_norm"]]
    k = cases.merge(ps1, on="primaryid")
    ok = (k["event_date"].notna() & k["age_years"].notna() & k["sex"].isin(["Female", "Male"])
          & (k["occr_country"] != "Unknown") & (k["drug_norm"] != "UNSPECIFIED"))
    k = k[ok]
    key = (k["event_date"].dt.strftime("%Y%m%d") + "|" + k["age_years"].round(1).astype(str) + "|" + k["sex"]
           + "|" + k["occr_country"] + "|" + k["drug_norm"])
    cnt = key.map(key.value_counts())
    dup = k.loc[cnt > 1, ["primaryid"]].copy()
    dq(checks, "Duplicates", "Possible duplicate reports (same event date, age, sex, country, drug)",
       len(dup), n_cases, "medium",
       "Different CASEIDs that share all these facts - often the same patient reported by two sources.")
    dup["flag_type"], dup["severity"], dup["detail"] = "POSSIBLE_DUPLICATE", "medium", \
        "Shares event date, age, sex, country and drug with another report"
    flags.append(dup)
    cases["possible_dup"] = cases["primaryid"].isin(dup["primaryid"]).astype(int)

    # ---------------- signals
    log("Computing PRR / ROR signals (this is the slow step) ...")
    sig = compute_signals(ps1.rename(columns={}), reac, cases[["primaryid", "death", "serious"]],
                          min_a=args.min_signal_cases)
    log(f"  {len(sig):,} drug-reaction pairs, {int(sig.evans_signal.sum()):,} meet the Evans criteria")

    # fatal cases that contain a strong clinical signal -> human review
    strong = sig[(sig.evans_signal == 1) & (sig.low_info == 0) & (sig.prr >= 5) & (sig.a >= 10)
                 & (sig.pct_fatal >= 50) & ~is_inherently_fatal(sig.pt)]
    death_ids = cases.loc[cases["death"] == 1, "primaryid"]
    fp = (ps1[ps1["primaryid"].isin(death_ids)].merge(reac[reac["primaryid"].isin(death_ids)], on="primaryid")
          .merge(strong[["drug_norm", "pt", "prr", "a"]], on=["drug_norm", "pt"]))
    fp = fp.sort_values("prr", ascending=False).drop_duplicates("primaryid")
    fp["flag_type"], fp["severity"] = "FATAL_CASE_WITH_SIGNAL", "high"
    fp["detail"] = fp["drug_norm"] + " + " + fp["pt"] + " (PRR " + fp["prr"].round(1).astype(str) + ", n=" + fp["a"].astype(str) + ")"
    flags.append(fp[["primaryid", "flag_type", "severity", "detail"]])
    dq(checks, "Safety review", "Fatal cases containing a strong drug-reaction signal", len(fp), n_cases, "high",
       "Death reported AND the primary-suspect drug + reaction pair has PRR>=5, n>=10 and >=50% fatal reports (generic and fatal-by-definition terms such as 'Completed suicide' excluded).")

    # ---------------- profiles
    log("Building drug profiles and weekly counts ...")
    prof = ps1.merge(cases[["primaryid", "death", "hospitalised", "life_threatening", "serious", "age_years",
                            "sex", "reporter_type", "occr_country", "n_reactions", "possible_dup"]], on="primaryid")
    prof = prof[prof["drug_norm"] != "UNSPECIFIED"]
    g = prof.groupby("drug_norm")
    profile = pd.DataFrame({
        "n_cases": g.size(),
        "pct_death": 100 * g["death"].mean(),
        "pct_hospitalised": 100 * g["hospitalised"].mean(),
        "pct_life_threat": 100 * g["life_threatening"].mean(),
        "pct_serious": 100 * g["serious"].mean(),
        "median_age": g["age_years"].median(),
        "pct_age_65plus": 100 * g["age_years"].apply(lambda s: (s >= 65).sum() / max(s.notna().sum(), 1)),
        "pct_female": 100 * g["sex"].apply(lambda s: (s == "Female").sum() / max((s != "Unknown").sum(), 1)),
        "pct_consumer": 100 * g["reporter_type"].apply(lambda s: (s == "Consumer").mean()),
        "pct_lawyer": 100 * g["reporter_type"].apply(lambda s: (s == "Lawyer").mean()),
        "n_countries": g["occr_country"].nunique(),
        "avg_reactions": g["n_reactions"].mean(),
        "pct_possible_dup": 100 * g["possible_dup"].mean(),
    }).round(2).reset_index()

    weekly = (ps1.merge(cases[["primaryid", "fda_week"]], on="primaryid").dropna(subset=["fda_week"])
              .query("drug_norm != 'UNSPECIFIED'")
              .groupby(["drug_norm", "fda_week"]).size().rename("n_cases").reset_index()
              .rename(columns={"fda_week": "week"}))
    weekly["week"] = iso(weekly["week"])

    names = (drug.groupby(["drug_norm", "drugname"]).size().rename("n").reset_index())
    names = names[names["drug_norm"] != "UNSPECIFIED"]

    # ---------------- write
    log(f"Writing SQLite database -> {args.db}")
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    if os.path.exists(args.db):
        os.remove(args.db)
    con = sqlite3.connect(args.db)

    out_cases = cases.copy()
    for c in ["fda_date", "event_date", "fda_week"]:
        out_cases[c] = iso(out_cases[c])
    keep = ["primaryid", "caseid", "caseversion", "quarter", "i_f_code", "rept_type", "fda_date", "fda_week",
            "event_date", "event_month", "age_years", "age_band", "age_grp", "sex", "weight_kg", "reporter_type",
            "reporter_country", "occr_country", "mfr_sndr", "n_reactions", "possible_dup", "serious"] + list(OUTC_MAP.values())
    out_cases[keep].to_sql("cases", con, index=False, chunksize=50000)
    reac.to_sql("reactions", con, index=False, chunksize=200000)
    drug.to_sql("drugs", con, index=False, chunksize=200000)
    profile.to_sql("drug_profile", con, index=False)
    weekly.to_sql("weekly_drug", con, index=False)
    names.to_sql("drug_names", con, index=False)
    sig.to_sql("signals", con, index=False, chunksize=100000)
    if rpsr is not None:
        rpsr["primaryid"] = pd.to_numeric(rpsr["primaryid"], errors="coerce")
        rpsr = rpsr[rpsr["primaryid"].isin(valid_ids)].dropna(subset=["primaryid"])
        rpsr["primaryid"] = rpsr["primaryid"].astype("int64")
        rpsr[["primaryid", "rpsr_cod"]].to_sql("report_sources", con, index=False)
    fl = pd.concat(flags, ignore_index=True)
    fl["primaryid"] = fl["primaryid"].astype("int64")
    fl.to_sql("review_flags", con, index=False, chunksize=100000)
    pd.DataFrame(checks).to_sql("dq_checks", con, index=False)
    meta = {"built_at": time.strftime("%Y-%m-%d %H:%M"), "quarters": ", ".join(quarters),
            "n_cases": str(n_cases), "source": "FDA FAERS quarterly ASCII extract",
            "roles_kept": "PS, SS, C, I" if args.all_roles else "PS, SS",
            "role_counts_raw": ", ".join(f"{k}={v}" for k, v in role_counts.items())}
    pd.DataFrame({"key": list(meta), "value": list(meta.values())}).to_sql("meta", con, index=False)

    log("Creating indexes ...")
    for stmt in [
        "CREATE UNIQUE INDEX ix_cases_pid ON cases(primaryid)",
        "CREATE INDEX ix_cases_week ON cases(fda_week)",
        "CREATE INDEX ix_reac_pid ON reactions(primaryid)",
        "CREATE INDEX ix_reac_pt ON reactions(pt)",
        "CREATE INDEX ix_drugs_pid ON drugs(primaryid)",
        "CREATE INDEX ix_drugs_norm ON drugs(drug_norm, role_cod)",
        "CREATE INDEX ix_sig_drug ON signals(drug_norm)",
        "CREATE INDEX ix_sig_pt ON signals(pt)",
        "CREATE INDEX ix_names ON drug_names(drugname)",
        "CREATE INDEX ix_weekly ON weekly_drug(drug_norm)",
        "CREATE INDEX ix_flags_type ON review_flags(flag_type)",
        "CREATE INDEX ix_flags_pid ON review_flags(primaryid)",
        "CREATE UNIQUE INDEX ix_prof ON drug_profile(drug_norm)",
    ]:
        con.execute(stmt)
    con.commit()
    con.execute("ANALYZE")  # table statistics: without them SQLite picks very slow join plans
    con.commit()
    con.execute("VACUUM")
    con.close()
    size = os.path.getsize(args.db) / 1e6
    log(f"Done in {time.time() - t0:.0f}s - {n_cases:,} cases, database size {size:.0f} MB")


if __name__ == "__main__":
    main()
