"""
SQL used by the dashboard. Every analysis starts from a *selection* CTE (`sel`)
that holds the (primaryid, drug_norm) pairs matching the user's drug + filters,
so charts for one drug or many drugs share the same SQL.
"""
from __future__ import annotations

GROUP_COLS = {"age_band", "sex", "reporter_type", "occr_country", "rept_type", "fda_week", "event_month", "quarter"}
OUTCOME_COLS = ["death", "life_threatening", "hospitalised", "disability",
                "congenital_anomaly", "required_intervention", "other_serious"]


def _in(values):
    return ",".join("?" * len(values))


def selection(drugs, roles=("PS",), sexes=None, bands=None, countries=None,
              reporters=None, serious_only=False, week_from=None, week_to=None):
    """Return (sql, params) for the CTE body: DISTINCT primaryid + drug_norm."""
    where = [f"d.drug_norm IN ({_in(drugs)})", f"d.role_cod IN ({_in(roles)})"]
    params = [*drugs, *roles]
    for col, vals in (("sex", sexes), ("age_band", bands), ("occr_country", countries),
                      ("reporter_type", reporters)):
        if vals:
            where.append(f"c.{col} IN ({_in(vals)})")
            params += list(vals)
    if serious_only:
        where.append("c.serious = 1")
    if week_from:
        where.append("c.fda_date >= ?")
        params.append(week_from)
    if week_to:
        where.append("c.fda_date <= ?")
        params.append(week_to)
    sql = ("SELECT DISTINCT d.primaryid, d.drug_norm FROM drugs d "
           "JOIN cases c ON c.primaryid = d.primaryid WHERE " + " AND ".join(where))
    return sql, params


def with_sel(sel, body):
    """Prefix a query with the selection CTE."""
    return f"WITH sel AS ({sel[0]}) {body}", list(sel[1])


# ---- selection-based analyses -------------------------------------------------
def reactions(sel):
    return with_sel(sel, """
        SELECT sel.drug_norm, r.pt, COUNT(*) AS n
        FROM sel JOIN reactions r ON r.primaryid = sel.primaryid
        GROUP BY sel.drug_norm, r.pt""")


def cohort_size(sel):
    return with_sel(sel, "SELECT drug_norm, COUNT(*) AS n_cases FROM sel GROUP BY drug_norm")


def group_count(sel, col):
    assert col in GROUP_COLS, col
    return with_sel(sel, f"""
        SELECT sel.drug_norm, c.{col} AS grp, COUNT(*) AS n
        FROM sel JOIN cases c ON c.primaryid = sel.primaryid
        WHERE c.{col} IS NOT NULL
        GROUP BY sel.drug_norm, c.{col}""")


def outcomes(sel):
    sums = ", ".join(f"SUM(c.{o}) AS {o}" for o in OUTCOME_COLS)
    return with_sel(sel, f"""
        SELECT sel.drug_norm, COUNT(*) AS n_cases, SUM(c.serious) AS serious, {sums},
               AVG(c.age_years) AS mean_age,
               SUM(CASE WHEN c.sex='Female' THEN 1 ELSE 0 END) AS female,
               SUM(CASE WHEN c.sex IN ('Female','Male') THEN 1 ELSE 0 END) AS sex_known,
               SUM(CASE WHEN c.age_years >= 65 THEN 1 ELSE 0 END) AS age65,
               SUM(CASE WHEN c.age_years IS NOT NULL THEN 1 ELSE 0 END) AS age_known,
               SUM(CASE WHEN c.reporter_type='Consumer' THEN 1 ELSE 0 END) AS consumer,
               SUM(CASE WHEN c.reporter_type='Lawyer' THEN 1 ELSE 0 END) AS lawyer
        FROM sel JOIN cases c ON c.primaryid = sel.primaryid
        GROUP BY sel.drug_norm""")


def ages(sel):
    return with_sel(sel, """
        SELECT sel.drug_norm, c.age_years FROM sel JOIN cases c ON c.primaryid = sel.primaryid
        WHERE c.age_years IS NOT NULL""")


def drug_detail(sel, roles, col):
    """route / indication / dose_form distribution for the selected drugs."""
    assert col in {"route", "indication", "dose_form"}
    params = list(roles)
    sql, p = with_sel(sel, f"""
        SELECT drug_norm, grp, COUNT(*) AS n FROM (
            SELECT DISTINCT sel.drug_norm, sel.primaryid, d.{col} AS grp
            FROM sel JOIN drugs d ON d.primaryid = sel.primaryid AND d.drug_norm = sel.drug_norm
                 AND d.role_cod IN ({_in(roles)})
            WHERE d.{col} IS NOT NULL)
        GROUP BY drug_norm, grp""")
    return sql, p + params


def time_to_onset(sel, roles):
    sql, p = with_sel(sel, f"""
        SELECT sel.drug_norm, d.tto_days FROM sel
        JOIN drugs d ON d.primaryid = sel.primaryid AND d.drug_norm = sel.drug_norm
             AND d.role_cod IN ({_in(roles)})
        WHERE d.tto_days IS NOT NULL""")
    return sql, p + list(roles)


def case_list(sel, limit=500):
    sql, p = with_sel(sel, """
        SELECT c.primaryid, c.caseid, sel.drug_norm AS drug, c.fda_date, c.event_date, c.age_years, c.sex,
               c.occr_country AS country, c.reporter_type, c.serious, c.death, c.n_reactions,
               (SELECT group_concat(pt, '; ') FROM reactions r WHERE r.primaryid = c.primaryid) AS reactions
        FROM sel JOIN cases c ON c.primaryid = sel.primaryid
        ORDER BY c.fda_date DESC, c.primaryid LIMIT ?""")
    return sql, p + [limit]


# ---- global queries --------------------------------------------------------------
META = "SELECT key, value FROM meta"
OVERVIEW = """
SELECT COUNT(*) AS n_cases, SUM(serious) AS serious, SUM(death) AS deaths,
       SUM(hospitalised) AS hosp, COUNT(DISTINCT occr_country) AS countries,
       MIN(fda_date) AS first_date, MAX(fda_date) AS last_date FROM cases"""
WEEKLY_ALL = "SELECT fda_week AS week, COUNT(*) AS n FROM cases WHERE fda_week IS NOT NULL GROUP BY fda_week ORDER BY 1"
CASES_BY = lambda col: f"SELECT {col} AS grp, COUNT(*) AS n FROM cases GROUP BY {col} ORDER BY n DESC"  # noqa: E731
TOP_PS_DRUGS = "SELECT * FROM drug_profile ORDER BY n_cases DESC LIMIT ?"
TOP_REACTIONS_ALL = """
SELECT r.pt, COUNT(*) AS n FROM reactions r GROUP BY r.pt ORDER BY n DESC LIMIT ?"""
DRUG_LIST = "SELECT drug_norm, n_cases FROM drug_profile WHERE n_cases >= ? ORDER BY n_cases DESC"
DRUG_SEARCH = """
SELECT n.drug_norm, SUM(n.n) AS n_rows, GROUP_CONCAT(DISTINCT n.drugname) AS names
FROM (SELECT drug_norm, drugname, n FROM drug_names
      WHERE drugname LIKE ? OR drug_norm LIKE ? ORDER BY n DESC) n
GROUP BY n.drug_norm ORDER BY n_rows DESC LIMIT 40"""
SIGNALS_FOR_DRUG = "SELECT * FROM signals WHERE drug_norm IN ({ph})"
DQ_CHECKS = "SELECT * FROM dq_checks"
FLAG_COUNTS = "SELECT flag_type, severity, COUNT(*) AS n FROM review_flags GROUP BY flag_type, severity ORDER BY n DESC"
FLAG_SAMPLE = """
SELECT f.primaryid, f.flag_type, f.severity, f.detail, c.fda_date, c.event_date, c.age_years, c.sex,
       c.occr_country AS country, c.reporter_type, c.death, c.serious
FROM review_flags f JOIN cases c ON c.primaryid = f.primaryid
WHERE f.flag_type = ? LIMIT ?"""
WEEKLY_DRUG = "SELECT drug_norm, week, n_cases FROM weekly_drug"

SIGNAL_CASES = """
SELECT c.primaryid, c.fda_date, c.event_date, c.age_years, c.sex, c.occr_country AS country,
       c.reporter_type, c.serious, c.death, c.possible_dup
FROM drugs d JOIN reactions r ON r.primaryid = d.primaryid JOIN cases c ON c.primaryid = d.primaryid
WHERE d.drug_norm = ? AND d.role_cod = 'PS' AND r.pt = ?
ORDER BY c.death DESC, c.fda_date DESC LIMIT ?"""
REVIEW_QUEUE = """
SELECT f.primaryid, f.flag_type, f.severity, f.detail, c.fda_date, c.age_years, c.sex,
       c.occr_country AS country, c.reporter_type, c.death, c.serious
FROM review_flags f JOIN cases c ON c.primaryid = f.primaryid
WHERE f.flag_type IN ({types}) AND f.severity IN ({sevs})
ORDER BY CASE f.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, f.flag_type, f.primaryid
LIMIT ?"""
