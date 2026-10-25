"""
Drug Safety & Pharmacovigilance Intelligence Platform
Streamlit dashboard on top of the SQLite database built by build_db.py

    streamlit run app.py
"""
from __future__ import annotations

import inspect
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import openfda_client as ofda
import queries as Q
import report as report_mod
from pv_signals import INHERENTLY_FATAL_PTS, is_low_info, weekly_anomalies

st.set_page_config(page_title="Drug Safety & Pharmacovigilance Platform", page_icon="💊", layout="wide")

DB_PATH = os.environ.get("PV_DB", str(Path(__file__).resolve().parent / "data" / "faers.db"))
AGE_ORDER = ["0-1", "2-11", "12-17", "18-44", "45-64", "65-74", "75+", "Unknown"]
OUTCOME_LABELS = {"death": "Death", "life_threatening": "Life-threatening", "hospitalised": "Hospitalisation",
                  "disability": "Disability", "congenital_anomaly": "Congenital anomaly",
                  "required_intervention": "Intervention required", "other_serious": "Other serious"}
SEV_ICON = {"high": "🔴 high", "medium": "🟠 medium", "low": "🟡 low", "info": "⚪ info"}
PALETTE = px.colors.qualitative.Safe

# ----------------------------------------------------------------------------- plumbing
if not Path(DB_PATH).exists():
    st.error(f"Database not found at `{DB_PATH}`.")
    st.code("python build_db.py --data-dir data/raw --db data/faers.db", language="bash")
    st.info("Put the FAERS quarterly files (DEMO/DRUG/REAC/OUTC/RPSR/THER/INDI .txt) in `data/raw/` first. "
            "See README.md.")
    st.stop()


@st.cache_resource
def get_conn(path: str) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


@st.cache_data(show_spinner=False, max_entries=400)
def run(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, get_conn(DB_PATH), params=list(params))


def run_q(qp) -> pd.DataFrame:
    sql, params = qp
    return run(sql, tuple(params))


_DF_NEW = "width" in inspect.signature(st.dataframe).parameters
_PLOT_NEW = "width" in inspect.signature(st.plotly_chart).parameters


def show_df(df: pd.DataFrame, height: int | None = None, **kw):
    wide = {"width": "stretch"} if _DF_NEW else {"use_container_width": True}
    if height is not None:
        kw["height"] = height
    st.dataframe(df, hide_index=True, **wide, **kw)


def show_fig(fig: go.Figure, height: int | None = None):
    fig.update_layout(template="plotly_white", margin=dict(l=10, r=10, t=50, b=10),
                      **({"height": height} if height else {}))
    wide = {"width": "stretch"} if _PLOT_NEW else {"use_container_width": True}
    st.plotly_chart(fig, **wide)


def csv_button(df: pd.DataFrame, label: str, name: str, key: str):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"), file_name=name, mime="text/csv", key=key)


def pct(x, d=1):
    return "–" if x is None or pd.isna(x) else f"{x:.{d}f}%"


# ----------------------------------------------------------------------------- cached lookups
@st.cache_data(show_spinner=False)
def meta() -> dict:
    return dict(run(Q.META).values)


@st.cache_data(show_spinner=False)
def date_range() -> tuple[date, date]:
    ov = run(Q.OVERVIEW).iloc[0]
    # a handful of late-arriving old receipts stretch the range; use the 0.1th percentile start
    wk = run(Q.WEEKLY_ALL)
    full = wk[wk["n"] >= 0.1 * wk["n"].median()]
    lo = pd.to_datetime(full["week"].min()).date()
    hi = pd.to_datetime(ov["last_date"]).date()
    return lo, hi


@st.cache_data(show_spinner=False)
def full_weeks() -> set:
    wk = run(Q.WEEKLY_ALL)
    return set(wk.loc[wk["n"] >= 0.5 * wk["n"].median(), "week"])


@st.cache_data(show_spinner=False)
def drug_options(min_cases: int = 30) -> list:
    return run(Q.DRUG_LIST, (min_cases,))["drug_norm"].tolist()


@st.cache_data(show_spinner=False)
def filter_choices():
    countries = run(Q.CASES_BY("occr_country")).query("grp != 'Unknown'").head(40)["grp"].tolist()
    reporters = run(Q.CASES_BY("reporter_type"))["grp"].tolist()
    return countries, reporters


def filter_panel(prefix: str):
    """Shared filter widgets -> dict used to build the SQL selection."""
    countries, reporters = filter_choices()
    lo, hi = date_range()
    with st.expander("Filters (apply to all charts on this page)", expanded=False):
        c1, c2, c3 = st.columns(3)
        role_label = c1.radio("Drug role in the report", ["Primary suspect", "Primary or secondary suspect"],
                              key=f"{prefix}_role",
                              help="Primary suspect = the drug the reporter considers the most likely cause.")
        sexes = c1.multiselect("Sex", ["Female", "Male", "Unknown"], key=f"{prefix}_sex")
        bands = c2.multiselect("Age band (years)", AGE_ORDER, key=f"{prefix}_age")
        reporter = c2.multiselect("Reporter type", reporters, key=f"{prefix}_rep")
        ctry = c3.multiselect("Country where the event occurred", countries, key=f"{prefix}_ctry")
        serious = c3.checkbox("Serious outcomes only", key=f"{prefix}_ser")
        rng = st.date_input("Date FDA received the report", value=(lo, hi), min_value=lo, max_value=hi,
                            key=f"{prefix}_dates")
    roles = ("PS",) if role_label == "Primary suspect" else ("PS", "SS")
    d0, d1 = (rng[0], rng[1]) if isinstance(rng, (tuple, list)) and len(rng) == 2 else (lo, hi)
    return dict(roles=roles, sexes=sexes, bands=bands, reporters=reporter, countries=ctry, serious_only=serious,
                week_from=d0.isoformat() if d0 > lo else None,
                week_to=(d1 + timedelta(days=0)).isoformat() if d1 < hi else None)


def make_selection(drugs, f):
    return Q.selection(list(drugs), roles=f["roles"], sexes=f["sexes"] or None, bands=f["bands"] or None,
                       countries=f["countries"] or None, reporters=f["reporters"] or None,
                       serious_only=f["serious_only"], week_from=f["week_from"], week_to=f["week_to"])


def filters_active(f) -> bool:
    return any([f["sexes"], f["bands"], f["reporters"], f["countries"], f["serious_only"], f["week_from"], f["week_to"]])


# ----------------------------------------------------------------------------- page: overview
def page_overview():
    st.title("💊 Drug Safety & Pharmacovigilance Intelligence Platform")
    m = meta()
    st.caption(f"Source: FDA Adverse Event Reporting System (FAERS), quarter(s) **{m.get('quarters', '?')}** · "
               f"database built {m.get('built_at', '?')}. Reports show *suspected* reactions and do not prove causation.")
    ov = run(Q.OVERVIEW).iloc[0]
    n = int(ov["n_cases"])
    c = st.columns(5)
    c[0].metric("Unique cases", f"{n:,}")
    c[1].metric("Serious outcome", pct(100 * ov["serious"] / n))
    c[2].metric("Deaths reported", f"{int(ov['deaths']):,}", pct(100 * ov["deaths"] / n) + " of cases", delta_color="off")
    c[3].metric("Hospitalisations", f"{int(ov['hosp']):,}", pct(100 * ov["hosp"] / n) + " of cases", delta_color="off")
    c[4].metric("Countries", f"{int(ov['countries'])}")

    left, right = st.columns([3, 2])
    with left:
        wk = run(Q.WEEKLY_ALL)
        wk = wk[wk["n"] >= 0.1 * wk["n"].median()].copy()
        wk["coverage"] = np.where(wk["week"].isin(full_weeks()), "Full week", "Partial week")
        fig = px.bar(wk, x="week", y="n", color="coverage", title="Reports received by FDA, per week",
                     color_discrete_map={"Full week": "#0F766E", "Partial week": "#CBD5E1"},
                     labels={"week": "Week starting (Monday)", "n": "Reports"})
        show_fig(fig, 340)
    with right:
        ages = run(Q.CASES_BY("age_band"))
        ages["grp"] = pd.Categorical(ages["grp"], AGE_ORDER, ordered=True)
        ages = ages.sort_values("grp")
        fig = px.bar(ages, x="grp", y="n", title="Cases by age band (years)",
                     color=np.where(ages["grp"] == "Unknown", "Unknown", "Known"),
                     color_discrete_map={"Known": "#0F766E", "Unknown": "#CBD5E1"},
                     labels={"grp": "", "n": "Cases"})
        fig.update_layout(showlegend=False)
        show_fig(fig, 340)

    a, b = st.columns(2)
    with a:
        top = run(Q.TOP_PS_DRUGS, (15,)).sort_values("n_cases")
        fig = px.bar(top, x="n_cases", y="drug_norm", orientation="h", color="pct_lawyer",
                     color_continuous_scale="Teal", title="Most-reported drugs (primary suspect)",
                     labels={"n_cases": "Cases", "drug_norm": "", "pct_lawyer": "% reports from lawyers"},
                     hover_data={"pct_serious": ":.1f", "pct_death": ":.1f"})
        show_fig(fig, 460)
        st.caption("Darker bars = larger share of reports filed by lawyers (possible litigation-driven reporting).")
    with b:
        hide = st.checkbox("Hide non-specific terms (e.g. 'Drug ineffective', 'Off label use')", value=True, key="ov_hide")
        rx = run(Q.TOP_REACTIONS_ALL, (80,))
        if hide:
            rx = rx[~is_low_info(rx["pt"])]
        rx = rx.head(15).sort_values("n")
        fig = px.bar(rx, x="n", y="pt", orientation="h", title="Most-reported reactions (MedDRA preferred term)",
                     labels={"n": "Reports", "pt": ""}, color_discrete_sequence=["#B45309"])
        show_fig(fig, 410)

    d, e, f = st.columns(3)
    sx = run(Q.CASES_BY("sex"))
    with d:
        show_fig(px.pie(sx, names="grp", values="n", hole=0.5, title="Sex", color_discrete_sequence=PALETTE), 300)
    rp = run(Q.CASES_BY("reporter_type"))
    with e:
        show_fig(px.bar(rp, x="n", y="grp", orientation="h", title="Who reported", labels={"grp": "", "n": "Cases"},
                        color_discrete_sequence=["#0F766E"]), 300)
    ct = run(Q.CASES_BY("occr_country")).query("grp != 'Unknown'").head(10).sort_values("n")
    with f:
        show_fig(px.bar(ct, x="n", y="grp", orientation="h", title="Top countries (where event occurred)",
                        labels={"grp": "", "n": "Cases"}, color_discrete_sequence=["#475569"]), 300)


# ----------------------------------------------------------------------------- page: explorer
def kpi_row(oc: pd.Series, median_age):
    n = oc["n_cases"]
    cols = st.columns(6)
    cols[0].metric("Reports", f"{int(n):,}")
    cols[1].metric("Serious", pct(100 * oc["serious"] / n))
    cols[2].metric("Fatal", pct(100 * oc["death"] / n))
    cols[3].metric("Median age", "–" if pd.isna(median_age) else f"{median_age:.0f} y")
    cols[4].metric("Female*", pct(100 * oc["female"] / oc["sex_known"]) if oc["sex_known"] else "–")
    cols[5].metric("Consumer-reported", pct(100 * oc["consumer"] / n))
    st.caption("*of reports with known sex.")


def page_explorer():
    st.title("🔎 Drug Explorer")
    st.write("Search for a drug by generic or brand name, then explore its adverse-event reports.")
    term = st.text_input("Search generic or brand name", placeholder="e.g. adalimumab, Humira, atorvastatin, Zantac",
                         key="ex_search")
    if term.strip():
        hits = run(Q.DRUG_SEARCH, (f"%{term.strip().upper()}%", f"%{term.strip().upper()}%"))
        if hits.empty:
            st.warning("No drug matches. Try a shorter spelling or the generic name.")
            return
        options = hits["drug_norm"].tolist()
        names = dict(zip(hits["drug_norm"], hits["names"]))
        label = lambda d: f"{d}  ·  also reported as: {str(names[d])[:70]}"  # noqa: E731
    else:
        options = drug_options(50)
        label = lambda d: d  # noqa: E731
    default = options.index("ADALIMUMAB") if "ADALIMUMAB" in options else 0
    drug = st.selectbox("Drug (active ingredient)", options, index=default, format_func=label, key="ex_drug")
    f = filter_panel("ex")
    sel = make_selection([drug], f)

    oc = run_q(Q.outcomes(sel))
    if oc.empty or int(oc.iloc[0]["n_cases"]) == 0:
        st.warning("No reports match these filters.")
        return
    oc = oc.iloc[0]
    ages = run_q(Q.ages(sel))
    kpi_row(oc, ages["age_years"].median() if len(ages) else np.nan)
    if filters_active(f):
        st.info("Filters are active - numbers describe the filtered subset.")
    n_cases = int(oc["n_cases"])

    tabs = st.tabs(["Reactions", "Demographics", "Trends", "Outcomes & reporters", "Dosing & timing", "Case list"])

    with tabs[0]:
        c1, c2, c3 = st.columns([1, 1, 2])
        top_n = c1.slider("Reactions to show", 5, 40, 15, key="ex_topn")
        hide = c2.checkbox("Hide non-specific terms", value=True, key="ex_hide")
        metric = c3.radio("Measure", ["% of this drug's reports", "Number of reports"], horizontal=True, key="ex_metric")
        rx = run_q(Q.reactions(sel))
        rx["pct"] = 100 * rx["n"] / n_cases
        if hide:
            rx = rx[~is_low_info(rx["pt"])]
        top = rx.nlargest(top_n, "n")
        xcol = "pct" if metric.startswith("%") else "n"
        fig = px.bar(top.sort_values(xcol), x=xcol, y="pt", orientation="h", title=f"Top reactions reported with {drug.title()}",
                     labels={"pct": "% of reports", "n": "Reports", "pt": ""}, color_discrete_sequence=["#0F766E"],
                     hover_data={"n": True, "pct": ":.1f"})
        show_fig(fig, max(320, 22 * top_n + 100))
        if f["roles"] == ("PS",):
            sg = run("SELECT pt, a AS reports, prr, ror, ror_lcl, ror_ucl, chi2, pct_fatal, evans_signal FROM signals WHERE drug_norm = ?",
                     (drug,))
            tab = top[["pt", "n", "pct"]].merge(sg.drop(columns="reports"), on="pt", how="left")
            tab["screen"] = np.where(tab["evans_signal"] == 1, "⚑ flagged", "")
            tab = tab.rename(columns={"pt": "Reaction", "n": "Reports", "pct": "% of reports", "prr": "PRR",
                                      "ror": "ROR", "ror_lcl": "ROR lower 95%", "ror_ucl": "ROR upper 95%",
                                      "chi2": "Chi²", "pct_fatal": "% fatal"})
            show_df(tab[["Reaction", "Reports", "% of reports", "PRR", "ROR", "ROR lower 95%", "% fatal", "screen"]]
                    .round(2))
            st.caption("PRR/ROR compare this drug with *all other* primary-suspect drugs in the full dataset (filters above are "
                       "not applied to them). ⚑ = meets Evans criteria (n≥3, PRR≥2, χ²≥4) → a hypothesis for review, not proof.")
        else:
            st.caption("PRR / ROR are calculated for primary-suspect drugs only - switch the role filter to 'Primary suspect'.")

    with tabs[1]:
        a, b = st.columns(2)
        ag = run_q(Q.group_count(sel, "age_band"))
        ag["grp"] = pd.Categorical(ag["grp"], AGE_ORDER, ordered=True)
        ag = ag.sort_values("grp")
        known = ag[ag["grp"] != "Unknown"]
        with a:
            show_fig(px.bar(known, x="grp", y="n", title="Reports by age band (years)", labels={"grp": "", "n": "Reports"},
                            color_discrete_sequence=["#0F766E"]), 330)
            unk = int(ag.loc[ag["grp"] == "Unknown", "n"].sum())
            st.caption(f"Age unknown for {unk:,} reports ({100 * unk / n_cases:.0f}%).")
        with b:
            sx = run_q(Q.group_count(sel, "sex"))
            show_fig(px.pie(sx, names="grp", values="n", hole=0.5, title="Sex", color_discrete_sequence=PALETTE), 330)
        if len(ages) > 10:
            show_fig(px.histogram(ages, x="age_years", nbins=40, title="Age distribution (years, known ages)",
                                  labels={"age_years": "Age (years)"}, color_discrete_sequence=["#475569"]), 300)

    with tabs[2]:
        wk = run_q(Q.group_count(sel, "fda_week")).rename(columns={"grp": "week"})
        wk = wk[wk["week"].isin(full_weeks())] if st.checkbox("Hide partial first/last weeks", True, key="ex_partial") else wk
        if wk.empty:
            st.info("No weekly data for this selection.")
        else:
            show_fig(px.bar(wk.sort_values("week"), x="week", y="n", title="Reports received by FDA per week",
                            labels={"week": "Week starting", "n": "Reports"}, color_discrete_sequence=["#0F766E"]), 320)
        ev = run_q(Q.group_count(sel, "event_month")).rename(columns={"grp": "month"})
        if not ev.empty:
            years = sorted({m[:4] for m in ev["month"]})
            since = st.select_slider("Show event onset months since", options=years,
                                     value=years[max(0, len(years) - 3)], key="ex_since")
            ev = ev[ev["month"] >= f"{since}-01"].sort_values("month")
            show_fig(px.bar(ev, x="month", y="n", title="When the reaction began (event month, where reported)",
                            labels={"month": "Event month", "n": "Reports"}, color_discrete_sequence=["#B45309"]), 300)
            st.caption("Event dates are often missing or partial; many reports describe events from earlier years.")

    with tabs[3]:
        a, b = st.columns(2)
        out = pd.DataFrame({"Outcome": [OUTCOME_LABELS[k] for k in Q.OUTCOME_COLS],
                            "Reports": [int(oc[k]) for k in Q.OUTCOME_COLS]})
        out["% of reports"] = 100 * out["Reports"] / n_cases
        with a:
            show_fig(px.bar(out.sort_values("Reports"), x="% of reports", y="Outcome", orientation="h",
                            title="Seriousness criteria (a report can have several)", hover_data=["Reports"],
                            color_discrete_sequence=["#B91C1C"]), 330)
        rp = run_q(Q.group_count(sel, "reporter_type"))
        with b:
            show_fig(px.pie(rp, names="grp", values="n", hole=0.5, title="Who reported", color_discrete_sequence=PALETTE), 330)
        c, d = st.columns(2)
        ct = run_q(Q.group_count(sel, "occr_country")).query("grp != 'Unknown'").nlargest(10, "n").sort_values("n")
        with c:
            show_fig(px.bar(ct, x="n", y="grp", orientation="h", title="Top countries", labels={"grp": "", "n": "Reports"},
                            color_discrete_sequence=["#475569"]), 320)
        rt = run_q(Q.group_count(sel, "rept_type"))
        with d:
            show_fig(px.bar(rt, x="grp", y="n", title="Report type", labels={"grp": "", "n": "Reports"},
                            color_discrete_sequence=["#0F766E"]), 320)

    with tabs[4]:
        a, b = st.columns(2)
        ro = run_q(Q.drug_detail(sel, f["roles"], "route")).nlargest(8, "n").sort_values("n")
        with a:
            if ro.empty:
                st.info("No route information.")
            else:
                show_fig(px.bar(ro, x="n", y="grp", orientation="h", title="Route of administration",
                                labels={"grp": "", "n": "Reports"}, color_discrete_sequence=["#0F766E"]), 320)
        ind = run_q(Q.drug_detail(sel, f["roles"], "indication"))
        ind = ind[ind["grp"] != "Product used for unknown indication"].nlargest(10, "n").sort_values("n")
        with b:
            if ind.empty:
                st.info("No indication information.")
            else:
                show_fig(px.bar(ind, x="n", y="grp", orientation="h", title="Reported indication (why the drug was taken)",
                                labels={"grp": "", "n": "Reports"}, color_discrete_sequence=["#B45309"]), 320)
        tt = run_q(Q.time_to_onset(sel, f["roles"]))
        if len(tt) >= 20:
            bins = [-1, 0, 7, 30, 90, 365, 10 ** 6]
            labels = ["Same day", "1-7 days", "8-30 days", "31-90 days", "91-365 days", "Over 1 year"]
            tt["bucket"] = pd.cut(tt["tto_days"], bins, labels=labels)
            cnt = tt["bucket"].value_counts().reindex(labels).reset_index()
            cnt.columns = ["Time from start of therapy to event", "Reports"]
            show_fig(px.bar(cnt, x="Time from start of therapy to event", y="Reports",
                            title=f"Time to onset (median {tt['tto_days'].median():.0f} days, {len(tt):,} reports with both dates)",
                            color_discrete_sequence=["#475569"]), 320)
            st.caption("Only reports with a complete therapy-start date and event date. Early onset may suggest a "
                       "pharmacological effect; late onset may point to cumulative or unrelated causes.")
        else:
            st.info("Too few reports with both therapy-start and event dates to show time-to-onset.")

    with tabs[5]:
        limit = st.slider("Rows", 100, 2000, 500, step=100, key="ex_rows")
        cl = run_q(Q.case_list(sel, limit))
        st.write(f"Showing the {len(cl):,} most recent of {n_cases:,} matching reports.")
        show_df(cl, height=420)
        csv_button(cl, "⬇️ Download these rows (CSV)", f"{drug.replace(' ', '_')}_cases.csv", "ex_dl")


# ----------------------------------------------------------------------------- page: compare
def head_to_head(rx: pd.DataFrame, sizes: dict, d1: str, d2: str, min_reports: int = 10) -> pd.DataFrame:
    a = rx[rx["drug_norm"] == d1].set_index("pt")["n"].rename("a")
    c = rx[rx["drug_norm"] == d2].set_index("pt")["n"].rename("c")
    df = pd.concat([a, c], axis=1).fillna(0)
    n1, n2 = sizes[d1], sizes[d2]
    df["b"], df["d"] = n1 - df["a"], n2 - df["c"]
    df = df[(df["a"] + df["c"]) >= min_reports].copy()
    A, B, C, D = (df[k] + 0.5 for k in "abcd")
    df["ror"] = (A * D) / (B * C)
    se = np.sqrt(1 / A + 1 / B + 1 / C + 1 / D)
    df["lcl"], df["ucl"] = np.exp(np.log(df["ror"]) - 1.96 * se), np.exp(np.log(df["ror"]) + 1.96 * se)
    df["pct1"], df["pct2"] = 100 * df["a"] / n1, 100 * df["c"] / n2
    return df.reset_index().rename(columns={"index": "pt"})


def page_compare():
    st.title("⚖️ Compare Drugs")
    opts = drug_options(50)
    defaults = [d for d in ["ADALIMUMAB", "ETANERCEPT", "INFLIXIMAB"] if d in opts] or opts[:3]
    drugs = st.multiselect("Choose 2-6 drugs (type to search)", opts, default=defaults, max_selections=6, key="cmp_drugs")
    if len(drugs) < 2:
        st.info("Pick at least two drugs.")
        return
    f = filter_panel("cmp")
    sel = make_selection(drugs, f)
    oc = run_q(Q.outcomes(sel)).set_index("drug_norm").reindex(drugs)
    if oc["n_cases"].fillna(0).sum() == 0:
        st.warning("No reports match these filters.")
        return
    sizes = oc["n_cases"].fillna(0).astype(int).to_dict()
    ages = run_q(Q.ages(sel)).groupby("drug_norm")["age_years"].median()

    summary = pd.DataFrame({
        "Reports": oc["n_cases"],
        "Serious %": 100 * oc["serious"] / oc["n_cases"],
        "Fatal %": 100 * oc["death"] / oc["n_cases"],
        "Hospitalised %": 100 * oc["hospitalised"] / oc["n_cases"],
        "Life-threatening %": 100 * oc["life_threatening"] / oc["n_cases"],
        "Median age (y)": ages.reindex(drugs),
        "Aged 65+ %": 100 * oc["age65"] / oc["age_known"].replace(0, np.nan),
        "Female %": 100 * oc["female"] / oc["sex_known"].replace(0, np.nan),
        "Consumer-reported %": 100 * oc["consumer"] / oc["n_cases"],
        "Lawyer-reported %": 100 * oc["lawyer"] / oc["n_cases"],
    }).T.round(1)
    st.subheader("Side-by-side summary")
    show_df(summary.reset_index().rename(columns={"index": "Metric"}))
    if (oc["lawyer"].fillna(0) / oc["n_cases"].replace(0, np.nan) > 0.3).any():
        st.warning("At least one drug has >30% of reports from lawyers - possible litigation-stimulated reporting; "
                   "compare counts with care.")

    tabs = st.tabs(["Reactions", "Disproportionality (PRR)", "Head-to-head", "Demographics", "Trends"])
    rx = run_q(Q.reactions(sel))
    rx["pct"] = rx["n"] / rx["drug_norm"].map(sizes) * 100

    with tabs[0]:
        c1, c2 = st.columns(2)
        k = c1.slider("Top reactions per drug", 3, 15, 8, key="cmp_k")
        hide = c2.checkbox("Hide non-specific terms", True, key="cmp_hide")
        r2 = rx[~is_low_info(rx["pt"])] if hide else rx
        keep = set(r2.groupby("drug_norm", group_keys=False).apply(lambda g: g.nlargest(k, "n"))["pt"])
        r3 = r2[r2["pt"].isin(keep)]
        order = r3.groupby("pt")["pct"].max().sort_values().index.tolist()
        fig = px.bar(r3, x="pct", y="pt", color="drug_norm", barmode="group", orientation="h",
                     category_orders={"pt": order}, color_discrete_sequence=PALETTE,
                     labels={"pct": "% of that drug's reports", "pt": "", "drug_norm": "Drug"},
                     title="Most-reported reactions (share of each drug's reports)", hover_data={"n": True})
        show_fig(fig, max(400, 26 * len(order) + 120))

    with tabs[1]:
        if f["roles"] != ("PS",):
            st.info("PRR is calculated for primary-suspect drugs. Set the role filter to 'Primary suspect'.")
        else:
            ph = ",".join("?" * len(drugs))
            sg = run(f"SELECT drug_norm, pt, a, prr, evans_signal, low_info FROM signals WHERE drug_norm IN ({ph})", tuple(drugs))
            if sg.empty:
                st.info("No drug-reaction pair reaches 3 reports.")
            else:
                hide = st.checkbox("Hide non-specific terms", True, key="cmp_hide2")
                if hide:
                    sg = sg[sg["low_info"] == 0]
                kk = st.slider("Reactions per drug (ranked by reports)", 3, 15, 8, key="cmp_k2")
                pts = set(sg.groupby("drug_norm", group_keys=False).apply(lambda g: g.nlargest(kk, "a"))["pt"])
                piv = sg[sg["pt"].isin(pts)].pivot_table(index="pt", columns="drug_norm", values="prr")
                piv = piv.reindex(columns=drugs)
                z = np.log10(piv.clip(lower=0.1))
                fig = go.Figure(go.Heatmap(z=z.values, x=piv.columns, y=piv.index,
                                           text=piv.round(1).astype(str).replace("nan", "").values,
                                           texttemplate="%{text}", colorscale="Reds", colorbar=dict(title="log10 PRR"),
                                           hoverongaps=False))
                fig.update_layout(title="PRR: how much more often the drug is reported with each reaction than other drugs",
                                  yaxis=dict(autorange="reversed"))
                show_fig(fig, max(380, 26 * len(piv) + 140))
                st.caption("PRR ≥ 2 (with ≥3 reports) is the usual screening threshold. Blank = fewer than 3 reports.")

    with tabs[2]:
        if len(drugs) != 2:
            st.info("Head-to-head works with exactly two drugs - remove extras to use it.")
        else:
            d1, d2 = drugs
            h = head_to_head(rx, sizes, d1, d2, st.slider("Minimum combined reports per reaction", 5, 100, 20, key="cmp_min"))
            if st.checkbox("Hide non-specific terms", True, key="cmp_hide3"):
                h = h[~is_low_info(h["pt"])]
            st.write(f"Reporting odds ratio (ROR) of **{d1}** vs **{d2}**: values above 1 mean the reaction is reported "
                     f"relatively more often with {d1}.")
            cols = ["pt", "a", "c", "pct1", "pct2", "ror", "lcl", "ucl"]
            names = {"pt": "Reaction", "a": f"Reports {d1[:18]}", "c": f"Reports {d2[:18]}", "pct1": f"% {d1[:18]}",
                     "pct2": f"% {d2[:18]}", "ror": "ROR", "lcl": "Lower 95%", "ucl": "Upper 95%"}
            x, y = st.columns(2)
            more1 = h[h["lcl"] > 1].nlargest(15, "ror")[cols].rename(columns=names).round(2)
            more2 = h[h["ucl"] < 1].nsmallest(15, "ror")[cols].rename(columns=names).round(2)
            x.markdown(f"**More often with {d1}**")
            show_df(more1) if len(more1) else x.caption("None.")
            y.markdown(f"**More often with {d2}**")
            show_df(more2) if len(more2) else y.caption("None.")
            st.caption("Differences can reflect different patients, indications and reporter types, not only the drugs.")

    with tabs[3]:
        a, b = st.columns(2)
        ag = run_q(Q.group_count(sel, "age_band"))
        ag = ag[ag["grp"] != "Unknown"]
        ag["pct"] = 100 * ag["n"] / ag.groupby("drug_norm")["n"].transform("sum")
        ag["grp"] = pd.Categorical(ag["grp"], AGE_ORDER, ordered=True)
        with a:
            show_fig(px.bar(ag.sort_values("grp"), x="grp", y="pct", color="drug_norm", barmode="group",
                            color_discrete_sequence=PALETTE, title="Age distribution (% of reports with known age)",
                            labels={"grp": "Age band", "pct": "%", "drug_norm": "Drug"}), 360)
        sx = run_q(Q.group_count(sel, "sex"))
        sx = sx[sx["grp"] != "Unknown"]
        sx["pct"] = 100 * sx["n"] / sx.groupby("drug_norm")["n"].transform("sum")
        with b:
            show_fig(px.bar(sx, x="drug_norm", y="pct", color="grp", barmode="stack", title="Sex (% of reports with known sex)",
                            color_discrete_sequence=PALETTE, labels={"drug_norm": "", "pct": "%", "grp": "Sex"}), 360)
        om = pd.DataFrame({d: {OUTCOME_LABELS[k]: 100 * oc.loc[d, k] / oc.loc[d, "n_cases"] for k in Q.OUTCOME_COLS}
                           for d in drugs if sizes.get(d)}).reset_index().melt("index", var_name="Drug", value_name="pct")
        show_fig(px.bar(om, x="index", y="pct", color="Drug", barmode="group", color_discrete_sequence=PALETTE,
                        title="Seriousness criteria (% of reports)", labels={"index": "", "pct": "%"}), 360)

    with tabs[4]:
        wk = run_q(Q.group_count(sel, "fda_week")).rename(columns={"grp": "week"})
        if st.checkbox("Hide partial first/last weeks", True, key="cmp_partial"):
            wk = wk[wk["week"].isin(full_weeks())]
        scale = st.radio("Scale", ["Reports per week", "Index (peak week = 100)"], horizontal=True, key="cmp_scale")
        if scale.startswith("Index"):
            wk["n"] = 100 * wk["n"] / wk.groupby("drug_norm")["n"].transform("max")
        show_fig(px.line(wk.sort_values("week"), x="week", y="n", color="drug_norm", markers=True,
                         color_discrete_sequence=PALETTE, title="Reports received by FDA per week",
                         labels={"week": "Week starting", "n": "Reports" if scale.startswith("Reports") else "Index",
                                 "drug_norm": "Drug"}), 380)


# ----------------------------------------------------------------------------- page: signals
@st.cache_data(show_spinner=False)
def unusual_drugs(min_cases: int, contamination: float) -> pd.DataFrame:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    prof = run("SELECT * FROM drug_profile WHERE n_cases >= ?", (min_cases,)).reset_index(drop=True)
    feats = ["n_cases", "pct_death", "pct_hospitalised", "pct_life_threat", "pct_serious", "median_age", "pct_female",
             "pct_consumer", "pct_lawyer", "n_countries", "avg_reactions"]
    X = prof[feats].copy()
    X["n_cases"], X["n_countries"] = np.log10(X["n_cases"]), np.log1p(X["n_countries"])
    X = X.fillna(X.median())
    Z = StandardScaler().fit_transform(X)
    iso = IsolationForest(n_estimators=300, contamination=contamination, random_state=42).fit(Z)
    prof["anomaly_score"] = (-iso.score_samples(Z)).round(3)
    prof["flagged"] = iso.predict(Z) == -1
    nice = {"n_cases": "report volume", "pct_death": "% fatal", "pct_hospitalised": "% hospitalised",
            "pct_life_threat": "% life-threatening", "pct_serious": "% serious", "median_age": "median age",
            "pct_female": "% female", "pct_consumer": "% consumer reports", "pct_lawyer": "% lawyer reports",
            "n_countries": "no. of countries", "avg_reactions": "reactions per report"}
    why = []
    for i in range(len(prof)):
        idx = np.argsort(-np.abs(Z[i]))[:2]
        why.append("; ".join(f"{nice[feats[j]]} {'high' if Z[i][j] > 0 else 'low'}" for j in idx))
    prof["unusual_because"] = why
    return prof


def page_signals():
    st.title("🚩 Signal Detection")
    st.write("Statistical screening that points reviewers to drug-reaction pairs and trends that look unusual. "
             "A flag is a **hypothesis to check**, not evidence that the drug caused the reaction.")
    with st.expander("How the screening works"):
        st.markdown("""
For each primary-suspect drug **D** and reaction **R** we build a 2×2 table of cases:

| | reaction R | other reactions |
|---|---|---|
| drug D | a | b |
| all other drugs | c | d |

* **PRR** = [a/(a+b)] / [c/(c+d)] - how many times more often R is reported with D than with other drugs.
* **ROR** = (a·d)/(b·c) with a 95% confidence interval; a lower bound above 1 means the excess is unlikely to be chance.
* **Evans criteria** (screening standard): *a ≥ 3 and PRR ≥ 2 and χ² ≥ 4*.
* Non-specific terms (e.g. 'Drug ineffective', 'Off label use') are hidden by default because they describe product use, not a medical effect.
* Spontaneous reports are voluntary, incomplete and affected by publicity and litigation - always check the label and literature.
""")
    t1, t2, t3 = st.tabs(["Drug-reaction pairs (PRR / ROR)", "Unusual weekly trends", "Unusual drugs (Isolation Forest)"])

    with t1:
        c1, c2, c3, c4 = st.columns(4)
        min_a = c1.slider("Minimum reports (a)", 3, 200, 10, key="sg_a")
        min_prr = c2.slider("Minimum PRR", 1.0, 50.0, 3.0, step=0.5, key="sg_prr")
        min_fatal = c3.slider("Minimum % fatal", 0, 100, 0, step=5, key="sg_fatal")
        order = c4.selectbox("Sort by", ["PRR", "Reports", "% fatal", "ROR lower 95%"], key="sg_order")
        d1, d2, d3 = st.columns(3)
        dtxt = d1.text_input("Drug contains", key="sg_drug")
        ptxt = d2.text_input("Reaction contains", key="sg_pt")
        only = d3.checkbox("Only pairs meeting Evans criteria", True, key="sg_evans")
        hide = d3.checkbox("Hide non-specific terms", True, key="sg_hide")
        no_fatal_by_def = d3.checkbox("Hide fatal-by-definition terms", True, key="sg_nfd",
                                      help="e.g. 'Completed suicide' is always fatal, so % fatal is not informative.")
        where, params = ["a >= ?", "prr >= ?"], [min_a, min_prr]
        if only:
            where.append("evans_signal = 1")
        if hide:
            where.append("low_info = 0")
        if min_fatal:
            where.append("pct_fatal >= ?")
            params.append(min_fatal)
        if dtxt:
            where.append("drug_norm LIKE ?")
            params.append(f"%{dtxt.upper()}%")
        if ptxt:
            where.append("pt LIKE ?")
            params.append(f"%{ptxt}%")
        if no_fatal_by_def:
            where.append("lower(pt) NOT IN (%s)" % ",".join("?" * len(INHERENTLY_FATAL_PTS)))
            params += sorted(INHERENTLY_FATAL_PTS)
        col = {"PRR": "prr", "Reports": "a", "% fatal": "pct_fatal", "ROR lower 95%": "ror_lcl"}[order]
        total = int(run("SELECT COUNT(*) n FROM signals WHERE " + " AND ".join(where), tuple(params)).iloc[0, 0])
        sg = run(f"""SELECT drug_norm AS drug, pt AS reaction, a AS reports, b, c, d, prr, chi2, ror, ror_lcl, ror_ucl,
                     pct_fatal, pct_serious, evans_signal FROM signals WHERE {' AND '.join(where)}
                     ORDER BY {col} DESC LIMIT 3000""", tuple(params))
        st.write(f"**{total:,}** drug-reaction pairs match" + (" (showing the top 3,000)" if total > 3000 else "") + ".")
        if sg.empty:
            st.info("Nothing matches - relax a threshold.")
        else:
            pl = sg.head(1500).copy()
            pl["log2 PRR"] = np.log2(pl["prr"])
            fig = px.scatter(pl, x="log2 PRR", y="reports", color="pct_fatal", log_y=True, hover_name="reaction",
                             hover_data={"drug": True, "reports": True, "prr": ":.1f", "pct_fatal": ":.0f", "log2 PRR": False},
                             color_continuous_scale="YlOrRd", title="Each dot is a drug-reaction pair (top 1,500 shown)",
                             labels={"log2 PRR": "log2 PRR (higher = more disproportionate)", "reports": "Reports (log scale)",
                                     "pct_fatal": "% fatal"})
            fig.add_vline(x=1, line_dash="dot", line_color="#94A3B8")
            show_fig(fig, 420)
            disp = sg.rename(columns={"prr": "PRR", "chi2": "Chi²", "ror": "ROR", "ror_lcl": "ROR lower 95%",
                                      "ror_ucl": "ROR upper 95%", "pct_fatal": "% fatal", "pct_serious": "% serious"})
            disp["flag"] = np.where(disp["evans_signal"] == 1, "⚑", "")
            show_df(disp[["drug", "reaction", "reports", "PRR", "ROR", "ROR lower 95%", "% fatal", "% serious", "flag"]].round(2),
                    height=380)
            csv_button(sg, "⬇️ Download signal list (CSV)", "signals.csv", "sg_dl")

            st.markdown("#### Drill into one pair")
            top = sg.head(300)
            labels = [f"{r.drug} → {r.reaction}  (n={r.reports}, PRR {r.prr:.1f})" for r in top.itertuples()]
            pick = st.selectbox("Pair", range(len(top)), format_func=lambda i: labels[i], key="sg_pick")
            row = top.iloc[pick]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Reports (a)", f"{int(row['reports']):,}")
            m2.metric("PRR", f"{row['prr']:,.1f}")
            m3.metric("ROR (95% CI)", f"{row['ror']:,.1f}", f"{row['ror_lcl']:,.1f} - {row['ror_ucl']:,.1f}", delta_color="off")
            m4.metric("% fatal", pct(row["pct_fatal"]))
            tbl = pd.DataFrame({"": [row["drug"], "All other drugs"],
                                f"Reaction: {row['reaction']}": [int(row["reports"]), int(row["c"])],
                                "Other reactions": [int(row["b"]), int(row["d"])]})
            show_df(tbl)
            cs = run(Q.SIGNAL_CASES, (row["drug"], row["reaction"], 300))
            st.write(f"Underlying reports (fatal first, up to 300):")
            show_df(cs, height=300)
            csv_button(cs, "⬇️ Download these reports (CSV)", "signal_cases.csv", "sg_dl2")

    with t2:
        c1, c2, c3 = st.columns(3)
        min_total = c1.slider("Min total reports for a drug", 20, 500, 40, key="an_tot")
        min_week = c2.slider("Min reports in the flagged week", 5, 100, 10, key="an_week")
        zthr = c3.slider("Robust z-score threshold", 2.0, 10.0, 3.5, step=0.5, key="an_z")
        weekly = run(Q.WEEKLY_DRUG)
        an = weekly_anomalies(weekly, min_total, min_week, zthr)
        st.write(f"**{len(an):,}** drug-weeks look unusual compared with that drug's own typical week "
                 f"(partial weeks are excluded automatically).")
        if an.empty:
            st.info("No spikes at these thresholds.")
        else:
            show_df(an.rename(columns={"drug_norm": "drug", "n_cases": "reports", "baseline": "typical week",
                                       "x_typical": "× typical", "robust_z": "robust z"}).round(1), height=300)
            dpick = st.selectbox("Plot a drug", an["drug_norm"].drop_duplicates().tolist(), key="an_pick")
            s = weekly[weekly["drug_norm"] == dpick].sort_values("week")
            s = s[s["week"].isin(full_weeks())]
            flagged = set(an.loc[an["drug_norm"] == dpick, "week"])
            s["status"] = np.where(s["week"].isin(flagged), "Unusual", "Typical")
            show_fig(px.bar(s, x="week", y="n_cases", color="status", title=f"{dpick}: reports per week",
                            color_discrete_map={"Unusual": "#B91C1C", "Typical": "#94A3B8"},
                            labels={"week": "Week starting", "n_cases": "Reports"}), 320)
            st.caption("Spikes are often batch submissions (many old cases filed at once, e.g. by a manufacturer or "
                       "law firm). Check the submission source and the news before treating a spike as a new risk.")
            csv_button(an, "⬇️ Download flagged weeks (CSV)", "unusual_weeks.csv", "an_dl")

    with t3:
        try:
            import sklearn  # noqa: F401
        except ImportError:
            st.info("Install scikit-learn (`pip install scikit-learn`) to enable this optional machine-learning view.")
            return
        st.write("An **Isolation Forest** looks at each drug's overall profile (volume, % fatal, % hospitalised, age, sex mix, "
                 "who reports, number of countries, reactions per report) and highlights drugs whose profile differs most "
                 "from the rest. It does not say a drug is unsafe - it says the reporting pattern is unusual and worth a look.")
        c1, c2 = st.columns(2)
        minc = c1.slider("Min reports per drug", 50, 1000, 100, step=50, key="if_min")
        cont = c2.slider("Share of drugs to flag", 0.01, 0.10, 0.03, step=0.01, key="if_cont")
        prof = unusual_drugs(minc, cont)
        st.write(f"{len(prof):,} drugs analysed, {int(prof['flagged'].sum())} flagged.")
        xs = st.selectbox("X axis", ["pct_death", "pct_serious", "median_age", "pct_consumer", "pct_lawyer", "avg_reactions"],
                          key="if_x")
        fig = px.scatter(prof, x=xs, y="n_cases", log_y=True, color="flagged", hover_name="drug_norm",
                         color_discrete_map={True: "#B91C1C", False: "#94A3B8"},
                         hover_data={"unusual_because": True, "anomaly_score": True, "flagged": False},
                         title="Drug profiles (red = flagged as unusual)", labels={"n_cases": "Reports (log scale)"})
        show_fig(fig, 420)
        fl = prof[prof["flagged"]].sort_values("anomaly_score", ascending=False)
        show_df(fl[["drug_norm", "n_cases", "anomaly_score", "unusual_because", "pct_death", "pct_serious", "median_age",
                    "pct_lawyer"]].rename(columns={"drug_norm": "drug", "n_cases": "reports"}).round(1), height=320)
        csv_button(fl, "⬇️ Download flagged drugs (CSV)", "unusual_drugs.csv", "if_dl")


# ----------------------------------------------------------------------------- page: data quality
def page_quality():
    st.title("🧹 Data Quality")
    st.write("Checks for missing values, duplicates and inconsistent records, run when the database was built. "
             "Fixes are applied in the analysis tables; the original problem records remain listed for review.")
    dq = run(Q.DQ_CHECKS)
    dq_main = dq[dq["category"] != "Safety review"].copy()
    n_cases = int(run(Q.OVERVIEW).iloc[0]["n_cases"])
    c = st.columns(4)
    c[0].metric("Cases analysed", f"{n_cases:,}")
    c[1].metric("Checks run", f"{len(dq_main)}")
    c[2].metric("High-severity issues", f"{int((dq_main['severity'] == 'high').sum())}")
    dups = dq_main[dq_main["check_name"].str.startswith("Possible duplicate")]
    c[3].metric("Possible duplicate reports", f"{int(dups['affected'].sum()):,}" if len(dups) else "0")

    tabs = st.tabs(["Missing values", "Duplicates", "Inconsistent records", "All checks", "Sample bad records"])
    def chart(cat, title):
        d = dq_main[dq_main["category"] == cat].sort_values("pct")
        if d.empty:
            st.info("Nothing to show.")
            return
        fig = px.bar(d, x="pct", y="check_name", orientation="h", color="severity", title=title, hover_data=["affected", "total"],
                     color_discrete_map={"high": "#B91C1C", "medium": "#EA580C", "low": "#CA8A04", "info": "#94A3B8"},
                     labels={"pct": "% of records affected", "check_name": ""})
        show_fig(fig, max(260, 55 * len(d) + 100))
        t = d.sort_values("pct", ascending=False).copy()
        t["severity"] = t["severity"].map(SEV_ICON)
        show_df(t[["check_name", "affected", "total", "pct", "severity", "description"]].rename(
            columns={"check_name": "Check", "affected": "Records", "total": "Out of", "pct": "%", "description": "What it means"}))

    with tabs[0]:
        chart("Missing values", "Missing values")
    with tabs[1]:
        chart("Duplicates", "Duplicates")
    with tabs[2]:
        chart("Inconsistent records", "Inconsistent records")
    with tabs[3]:
        t = dq_main.copy()
        t["severity"] = t["severity"].map(SEV_ICON)
        show_df(t.rename(columns={"category": "Category", "check_name": "Check", "affected": "Records", "total": "Out of",
                                  "pct": "%", "severity": "Severity", "description": "What it means"}), height=520)
        csv_button(dq_main, "⬇️ Download data-quality log (CSV)", "data_quality_checks.csv", "dq_dl")
    with tabs[4]:
        fc = run(Q.FLAG_COUNTS)
        dqf = fc[fc["flag_type"] != "FATAL_CASE_WITH_SIGNAL"]
        pick = st.selectbox("Issue type", dqf["flag_type"].tolist(),
                            format_func=lambda x: f"{x}  ({int(dqf.loc[dqf.flag_type == x, 'n'].iloc[0]):,} records)", key="dq_flag")
        sample = run(Q.FLAG_SAMPLE, (pick, 500))
        show_df(sample, height=360)
        csv_button(sample, "⬇️ Download sample (CSV)", f"{pick.lower()}.csv", "dq_dl2")
    with st.expander("Cleaning rules applied"):
        st.markdown("""
* **Case versions:** only the latest version of each CASEID is kept.
* **Age:** converted to years from decades/months/weeks/days/hours; set to missing if negative, above 120 years or if the unit is missing.
* **Weight:** converted to kg; set to missing if outside 0.3-400 kg.
* **Sex:** `UNK`/`NS`/blank → *Unknown*.
* **Dates:** only complete 8-digit dates are used for timing; partial dates keep their year-month.
* **Drug names:** upper-cased and standardised to the *active ingredient* (`prod_ai`) when available, else the brand/verbatim name; placeholders ('UNKNOWN') are excluded from drug-level analysis.
* **Reactions:** repeated MedDRA terms within a report are removed.
* **Possible duplicates:** different cases with identical event date, age, sex, country and primary-suspect drug.
""")


# ----------------------------------------------------------------------------- page: review & report
@st.cache_data(show_spinner="Building report ...")
def cached_report() -> str:
    return report_mod.build_report_md(get_conn(DB_PATH))


def page_review():
    st.title("📝 Review & Report")
    t1, t2 = st.tabs(["Summary report", "Review queue"])
    with t1:
        md = cached_report()
        st.download_button("⬇️ Download report (Markdown)", md.encode("utf-8"), file_name="safety_review_report.md",
                           mime="text/markdown")
        st.markdown(md)
    with t2:
        fc = run(Q.FLAG_COUNTS)
        st.write("Every record or trend flagged for a human to look at. Start with the high-severity items.")
        show_df(fc.rename(columns={"flag_type": "Flag", "severity": "Severity", "n": "Records"}).assign(
            Severity=lambda d: d["Severity"].map(SEV_ICON)), height=240)
        c1, c2, c3 = st.columns([2, 1, 1])
        types = c1.multiselect("Flag types", fc["flag_type"].unique().tolist(),
                               default=["FATAL_CASE_WITH_SIGNAL"] if "FATAL_CASE_WITH_SIGNAL" in fc["flag_type"].values else None,
                               key="rq_types")
        sevs = c2.multiselect("Severity", ["high", "medium", "low"], default=["high", "medium"], key="rq_sev")
        lim = c3.slider("Max rows", 100, 5000, 1000, step=100, key="rq_lim")
        if types and sevs:
            sql = Q.REVIEW_QUEUE.format(types=",".join("?" * len(types)), sevs=",".join("?" * len(sevs)))
            rq = run(sql, tuple(types) + tuple(sevs) + (lim,))
            st.write(f"Showing {len(rq):,} records.")
            show_df(rq, height=420)
            csv_button(rq, "⬇️ Download review queue (CSV)", "review_queue.csv", "rq_dl")
        else:
            st.info("Choose at least one flag type and severity.")


# ----------------------------------------------------------------------------- page: openFDA
@st.cache_data(show_spinner="Asking openFDA ...", ttl=3600)
def live_fetch(drug: str, start: date, end: date, suspect_only: bool):
    return (ofda.total_reports(drug, start, end, suspect_only), ofda.seriousness_split(drug, start, end, suspect_only),
            ofda.top_reactions(drug, start, end, 25, suspect_only), ofda.weekly_reports(drug, start, end, suspect_only))


def page_openfda():
    st.title("🌐 Live openFDA (API extension)")
    st.write("Pull current reports for a drug straight from the public **openFDA drug adverse-event API** and compare them "
             "with the quarter loaded in the local database. Needs internet access; no key required for light use "
             "(set `OPENFDA_API_KEY` for more).")
    c1, c2, c3 = st.columns([2, 2, 1])
    drug = c1.text_input("Generic drug name", value="adalimumab", key="of_drug")
    lo, hi = date_range()
    rng = c2.date_input("Receive date range", value=(lo, hi), key="of_dates")
    suspect = c3.checkbox("Suspect drug only", True, key="of_sus")
    if not st.button("Fetch live data", type="primary", key="of_go"):
        st.caption("Default range = the quarter in your local database, so the two sources can be compared like-for-like.")
        return
    if not (isinstance(rng, (tuple, list)) and len(rng) == 2):
        st.warning("Pick a start and end date.")
        return
    try:
        total, ser, rx, wk = live_fetch(drug.strip(), rng[0], rng[1], suspect)
    except ofda.OpenFDAError as exc:
        st.error(str(exc))
        return
    if total == 0:
        st.warning("openFDA returned no reports for that name and period. Try the generic name (e.g. 'atorvastatin calcium').")
        return
    m = st.columns(3)
    m[0].metric("Live reports (openFDA)", f"{total:,}")
    m[1].metric("Serious", pct(100 * ser["serious"] / max(ser["serious"] + ser["not_serious"], 1)))
    m[2].metric("Distinct reaction terms (top 25 shown)", f"{len(rx)}")
    a, b = st.columns(2)
    with a:
        r = rx[~is_low_info(rx["pt"].str.capitalize())].head(15).sort_values("n")
        show_fig(px.bar(r, x="n", y="pt", orientation="h", title="Top reactions (live)", labels={"n": "Reports", "pt": ""},
                        color_discrete_sequence=["#0F766E"]), 420)
    with b:
        if len(wk):
            show_fig(px.bar(wk, x="week", y="n", title="Reports per week (live)", labels={"week": "Week starting", "n": "Reports"},
                            color_discrete_sequence=["#475569"]), 420)
    local = run("SELECT drug_norm FROM drug_profile WHERE drug_norm LIKE ? ORDER BY n_cases DESC LIMIT 1", (f"{drug.strip().upper()}%",))
    if len(local):
        ld = local.iloc[0, 0]
        lrx = run("SELECT r.pt, COUNT(*) AS n FROM drugs d JOIN reactions r ON r.primaryid=d.primaryid "
                  "WHERE d.drug_norm = ? AND d.role_cod = 'PS' GROUP BY r.pt ORDER BY n DESC LIMIT 60", (ld,))
        ln = int(run("SELECT n_cases FROM drug_profile WHERE drug_norm = ?", (ld,)).iloc[0, 0])
        cmp = pd.DataFrame({"pt": rx["pt"].str.upper(), "Live %": 100 * rx["n"] / total})
        lrx["pt"] = lrx["pt"].str.upper()
        lrx["Local %"] = 100 * lrx["n"] / ln
        both = cmp.merge(lrx[["pt", "Local %"]], on="pt", how="left").fillna(0).head(12)
        both = both.melt("pt", var_name="Source", value_name="% of reports")
        show_fig(px.bar(both, x="% of reports", y="pt", color="Source", barmode="group", orientation="h",
                        title=f"Live openFDA vs local database ({ld})", color_discrete_sequence=["#0F766E", "#B45309"],
                        labels={"pt": ""}), 460)
    st.caption("openFDA matches a report's drug fields as a flat list, so counts are approximate. "
               "Reaction terms are MedDRA preferred terms, the same vocabulary as the local data.")


# ----------------------------------------------------------------------------- router
PAGES = {
    "Overview": page_overview,
    "Drug Explorer": page_explorer,
    "Compare Drugs": page_compare,
    "Signal Detection": page_signals,
    "Data Quality": page_quality,
    "Review & Report": page_review,
    "Live openFDA (extension)": page_openfda,
}

with st.sidebar:
    st.header("💊 PV Intelligence")
    page = st.radio("Navigate", list(PAGES), key="nav", label_visibility="collapsed")
    st.divider()
    m = meta()
    st.caption(f"Data: FAERS {m.get('quarters', '')}\n\n{int(m.get('n_cases', 0)):,} cases")
    st.caption("⚠️ Spontaneous reports cannot establish that a drug caused a reaction. Use for hypothesis generation only.")

PAGES[page]()
