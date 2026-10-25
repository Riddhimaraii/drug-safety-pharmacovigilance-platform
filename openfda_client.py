"""
Thin client for the public openFDA drug-adverse-event API (no key needed for
light use; set OPENFDA_API_KEY for higher limits). https://open.fda.gov/apis/drug/event/

Caveat: openFDA treats a report's drug list as a flat bag of fields, so
'generic name = X AND characterization = suspect' can match a report where X is
concomitant and another drug is the suspect. Treat live counts as approximate.
"""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import requests

BASE = "https://api.fda.gov/drug/event.json"


class OpenFDAError(RuntimeError):
    pass


def _get(params: dict, timeout: int = 25) -> dict:
    key = os.environ.get("OPENFDA_API_KEY")
    if key:
        params = {**params, "api_key": key}
    try:
        r = requests.get(BASE, params=params, timeout=timeout)
    except requests.RequestException as exc:  # network down, DNS, timeout ...
        raise OpenFDAError(f"Could not reach api.fda.gov: {exc}") from exc
    if r.status_code == 404:  # openFDA returns 404 when nothing matches
        return {"results": [], "meta": {"results": {"total": 0}}}
    if r.status_code == 429:
        raise OpenFDAError("openFDA rate limit reached - wait a minute or set OPENFDA_API_KEY.")
    if not r.ok:
        raise OpenFDAError(f"openFDA returned HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def build_search(drug: str, start: date, end: date, suspect_only: bool = True) -> str:
    drug = drug.replace('"', "").strip()
    parts = [f'patient.drug.openfda.generic_name:"{drug}"']
    if suspect_only:
        parts.append("patient.drug.drugcharacterization:1")
    parts.append(f"receivedate:[{start:%Y%m%d} TO {end:%Y%m%d}]")
    return " AND ".join(parts)


def total_reports(drug, start, end, suspect_only=True) -> int:
    data = _get({"search": build_search(drug, start, end, suspect_only), "limit": 1})
    return int(data.get("meta", {}).get("results", {}).get("total", 0))


def top_reactions(drug, start, end, limit=25, suspect_only=True) -> pd.DataFrame:
    data = _get({"search": build_search(drug, start, end, suspect_only),
                 "count": "patient.reaction.reactionmeddrapt.exact", "limit": limit})
    df = pd.DataFrame(data.get("results", []))
    if df.empty:
        return pd.DataFrame(columns=["pt", "n"])
    return df.rename(columns={"term": "pt", "count": "n"})


def weekly_reports(drug, start, end, suspect_only=True) -> pd.DataFrame:
    data = _get({"search": build_search(drug, start, end, suspect_only), "count": "receivedate", "limit": 1000})
    df = pd.DataFrame(data.get("results", []))
    if df.empty:
        return pd.DataFrame(columns=["week", "n"])
    df["time"] = pd.to_datetime(df["time"], format="%Y%m%d")
    df["week"] = df["time"] - pd.to_timedelta(df["time"].dt.dayofweek, unit="D")
    return df.groupby("week", as_index=False)["count"].sum().rename(columns={"count": "n"})


def seriousness_split(drug, start, end, suspect_only=True) -> dict:
    data = _get({"search": build_search(drug, start, end, suspect_only), "count": "serious"})
    out = {"serious": 0, "not_serious": 0}
    for row in data.get("results", []):
        out["serious" if row["term"] == 1 else "not_serious"] = row["count"]
    return out
