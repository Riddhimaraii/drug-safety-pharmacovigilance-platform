"""
Signal-detection helpers for spontaneous adverse-event reports.

Disproportionality analysis compares how often a reaction is reported for one
drug against how often it is reported for all other drugs:

                       reaction R    other reactions
    drug D                  a              b
    all other drugs         c              d

    PRR  = [a / (a + b)] / [c / (c + d)]          Proportional Reporting Ratio
    ROR  = (a * d) / (b * c)                      Reporting Odds Ratio (+95% CI)
    chi2 = N (ad - bc)^2 / [(a+b)(c+d)(a+c)(b+d)]

A drug-reaction pair is flagged with the widely used Evans criteria:
    a >= 3  AND  PRR >= 2  AND  chi2 >= 4

IMPORTANT: a flag is a *hypothesis for human review*, not evidence of causality.
Spontaneous reporting is voluntary, incomplete and affected by media attention,
litigation, and the age of the product (stimulated reporting).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# MedDRA preferred terms that describe product use, lack of effect or are too
# generic to be a useful *safety* signal. They are kept in the data (and can be
# shown) but excluded from the default signal list.
LOW_INFO_PTS = {
    "death", "drug ineffective", "off label use", "condition aggravated",
    "disease progression", "malignant neoplasm progression", "underdose",
    "overdose", "drug interaction", "adverse event", "illness", "malaise",
    "feeling abnormal", "therapeutic response unexpected", "drug dependence",
    "treatment failure", "therapy non-responder", "no adverse event",
    "disease recurrence", "general physical health deterioration",
    "hospitalisation", "intentional overdose", "accidental overdose",
    "toxicity to various agents", "drug abuse", "drug use disorder", "poisoning",
    "accidental poisoning", "drug toxicity", "substance abuse", "drug withdrawal syndrome",
    "off label use", "product used for unknown indication",
}
# Terms that are fatal by definition: a high "% fatal" for them says nothing extra.
INHERENTLY_FATAL_PTS = {"completed suicide", "sudden death", "sudden cardiac death", "brain death",
                        "cardiac death", "death neonatal", "foetal death", "stillbirth"}
LOW_INFO_PREFIXES = (
    "product ", "device ", "incorrect ", "wrong ", "drug dose omission",
    "intentional product", "inappropriate schedule", "expired product",
    "poor quality", "accidental exposure", "therapeutic product",
    "circumstance or information capable", "medication error", "dose ",
    "drug administered", "drug dispensing", "prescribed ", "extra dose",
    "wrong drug", "treatment noncompliance", "inadequate ", "underdose",
)


def is_low_info(pt: pd.Series) -> pd.Series:
    """True for non-specific / product-use / administrative MedDRA terms."""
    s = pt.astype(str).str.lower()
    return s.isin(LOW_INFO_PTS) | s.str.startswith(LOW_INFO_PREFIXES)


def is_inherently_fatal(pt: pd.Series) -> pd.Series:
    return pt.astype(str).str.lower().isin(INHERENTLY_FATAL_PTS)


def compute_signals(
    ps: pd.DataFrame,
    reac: pd.DataFrame,
    outcomes: pd.DataFrame,
    min_a: int = 3,
) -> pd.DataFrame:
    """
    Disproportionality statistics for every (primary-suspect drug, reaction) pair.

    ps        : columns primaryid, drug_norm      (primary-suspect drug per case)
    reac      : columns primaryid, pt             (reactions per case)
    outcomes  : columns primaryid, death, serious (0/1 flags)
    """
    ps = ps[["primaryid", "drug_norm"]].drop_duplicates()
    ps = ps[ps["drug_norm"] != "UNSPECIFIED"]
    reac = reac[["primaryid", "pt"]].drop_duplicates()

    universe = np.intersect1d(ps["primaryid"].unique(), reac["primaryid"].unique())
    ps = ps[ps["primaryid"].isin(universe)]
    reac = reac[reac["primaryid"].isin(universe)]
    n_total = len(universe)

    n_drug = ps.groupby("drug_norm", observed=True)["primaryid"].nunique().rename("n_drug")
    n_pt = reac.groupby("pt", observed=True)["primaryid"].nunique().rename("n_pt")

    pairs = ps.merge(reac, on="primaryid")
    pairs = pairs.merge(outcomes[["primaryid", "death", "serious"]], on="primaryid", how="left")
    pairs[["death", "serious"]] = pairs[["death", "serious"]].fillna(0)

    agg = (
        pairs.groupby(["drug_norm", "pt"], observed=True)
        .agg(a=("primaryid", "size"), n_fatal=("death", "sum"), n_serious=("serious", "sum"))
        .reset_index()
    )
    agg = agg[agg["a"] >= min_a].copy()
    agg = agg.merge(n_drug, left_on="drug_norm", right_index=True)
    agg = agg.merge(n_pt, left_on="pt", right_index=True)

    a = agg["a"].to_numpy(dtype="float64")
    b = agg["n_drug"].to_numpy(dtype="float64") - a
    c = agg["n_pt"].to_numpy(dtype="float64") - a
    d = n_total - agg["n_drug"].to_numpy(dtype="float64") - agg["n_pt"].to_numpy(dtype="float64") + a

    # Haldane-Anscombe correction only where a cell is zero
    zero = (a == 0) | (b == 0) | (c == 0) | (d == 0)
    ac, bc, cc, dc = (np.where(zero, x + 0.5, x) for x in (a, b, c, d))

    prr = (ac / (ac + bc)) / (cc / (cc + dc))
    ror = (ac * dc) / (bc * cc)
    se = np.sqrt(1 / ac + 1 / bc + 1 / cc + 1 / dc)
    n = a + b + c + d
    with np.errstate(divide="ignore", invalid="ignore"):
        chi2 = n * (a * d - b * c) ** 2 / ((a + b) * (c + d) * (a + c) * (b + d))
    chi2 = np.nan_to_num(chi2)

    agg["b"], agg["c"], agg["d"], agg["N"] = b.astype(int), c.astype(int), d.astype(int), n_total
    agg["prr"] = prr
    agg["chi2"] = chi2
    agg["ror"] = ror
    agg["ror_lcl"] = np.exp(np.log(ror) - 1.96 * se)
    agg["ror_ucl"] = np.exp(np.log(ror) + 1.96 * se)
    agg["pct_fatal"] = 100 * agg["n_fatal"] / agg["a"]
    agg["pct_serious"] = 100 * agg["n_serious"] / agg["a"]
    agg["evans_signal"] = ((agg["a"] >= 3) & (agg["prr"] >= 2) & (agg["chi2"] >= 4)).astype(int)
    agg["ror_signal"] = ((agg["a"] >= 3) & (agg["ror_lcl"] > 1)).astype(int)
    agg["low_info"] = is_low_info(agg["pt"]).astype(int)
    return agg.sort_values(["evans_signal", "prr"], ascending=[False, False]).reset_index(drop=True)


def weekly_anomalies(
    weekly: pd.DataFrame,
    min_total: int = 40,
    min_week_count: int = 10,
    z_thr: float = 3.5,
) -> pd.DataFrame:
    """
    Flag unusual weekly report counts per drug using a robust z-score
    (median / MAD). Weeks that are only partly covered by the extract
    (first / last week of a quarter) are excluded automatically.

    weekly : columns drug_norm, week (ISO date string), n_cases
    """
    if weekly.empty:
        return pd.DataFrame(columns=["drug_norm", "week", "n_cases", "baseline", "x_typical", "robust_z"])
    piv = weekly.pivot_table(index="drug_norm", columns="week", values="n_cases",
                             aggfunc="sum", fill_value=0)
    totals = piv.sum(axis=0)
    full_weeks = totals[totals >= 0.5 * totals.median()].index
    piv = piv[full_weeks]
    piv = piv[piv.sum(axis=1) >= min_total]
    if piv.shape[1] < 5 or piv.empty:
        return pd.DataFrame(columns=["drug_norm", "week", "n_cases", "baseline", "x_typical", "robust_z"])

    med = piv.median(axis=1)
    mad = piv.sub(med, axis=0).abs().median(axis=1) * 1.4826
    scale = np.maximum(mad, np.sqrt(med.clip(lower=1)))  # never smaller than Poisson noise
    z = piv.sub(med, axis=0).div(scale, axis=0)

    out = (
        z.stack().rename("robust_z").reset_index()
        .merge(piv.stack().rename("n_cases").reset_index(), on=["drug_norm", "week"])
    )
    out["baseline"] = out["drug_norm"].map(med)
    out["x_typical"] = (out["n_cases"] / out["baseline"].clip(lower=1)).round(1)
    out = out[(out["robust_z"] >= z_thr) & (out["n_cases"] >= min_week_count)]
    return out.sort_values("robust_z", ascending=False).reset_index(drop=True)
