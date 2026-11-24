"""Rule-based first pass: turn the two raw CSVs into (1) sites linked to entities and (2) a deal graph.

This is the deterministic baseline. In the app, an LLM extraction agent replaces the regex steps
(dollar amount, direction of money, superseded-vs-incremental, state allocation) and writes the
same columns, so everything downstream stays unchanged.
"""
import os
import re
from pathlib import Path

import pandas as pd

from entities import META, canon

DATA = Path(__file__).resolve().parents[1] / "data"
# DATA_MODE=full uses data/raw (full licensed CSVs, not in git); DATA_MODE=sample uses data/sample (committed).
# Default: full if data/raw has the CSVs, otherwise sample.
_mode = os.getenv("DATA_MODE", "").lower()
if _mode not in ("full", "sample"):
    _mode = "full" if (DATA / "raw" / "US_data_centers_master.csv").exists() else "sample"
DATA_MODE = _mode
RAW = DATA / ("raw" if DATA_MODE == "full" else "sample")
PIPELINE = {"Planned", "Under Construction"}

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}
# Longest names first so "West Virginia" wins over "Virginia"
_STATE_RE = re.compile(r"\b(" + "|".join(sorted(STATES, key=len, reverse=True)) + r")\b")
_MONEY_RE = re.compile(r"\$\s?([\d,.]+)\s*(trillion|billion|bn|million|mm|m)\b", re.I)
_MULT = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6}
_CITE = re.compile(r"\[\[cite:[^\]]+\]\]")


def clean(t):
    return _CITE.sub("", t).strip() if isinstance(t, str) else ""


def money(text):
    """Headline dollar figure = first $ amount mentioned (the column leads with the headline)."""
    m = _MONEY_RE.search(clean(text))
    if not m:
        return None
    return float(m.group(1).replace(",", "")) * _MULT[m.group(2).lower()]


def states_in(text):
    return sorted({STATES[s] for s in _STATE_RE.findall(clean(text))})


def split_names(s, seps=r"\s*[|;]\s*|\s*,\s*"):
    return [x for x in re.split(seps, s) if x] if isinstance(s, str) else []


def load_sites():
    d = pd.read_csv(RAW / "US_data_centers_master.csv", low_memory=False)
    d = d[d.status != "Canceled"].copy()
    d["mw"] = pd.to_numeric(d.best_total_mw, errors="coerce").fillna(0)
    d["capex"] = pd.to_numeric(d.investment_usd, errors="coerce")
    d["pipeline"] = d.status.isin(PIPELINE)
    links = []
    for _, r in d.iterrows():
        for role, col in (("developer", "developer"), ("tenant", "tenant")):
            for n in split_names(r[col]):
                c = canon(n)
                if c:
                    links.append({"site_id": r.id, "entity": c, "role": role})
    links = pd.DataFrame(links).drop_duplicates(["site_id", "entity"])
    return d, links


_FIRM = re.compile(r"(?i)\bat least\b|regardless of (actual )?usage|non-cancel|minimum (spend|purchase)|\bcommitted\b|\bcompleted\b|cash for")
_ASPIRE = re.compile(r"(?i)intend|\bplan(s|ned)?\b|framework|headline|proposed|target|expected to|option|potential|letter of intent|\bmou\b")
_SUPPLY = re.compile(r"(?i)produc|manufactur|packaging|fab\b|made chips")
# Weight applied to headline $ before it counts as "at risk": firm minimums count fully,
# ceilings ("up to", facilities) count half, aspirational headlines count a quarter.
TIER_WEIGHT = {"firm": 1.0, "ceiling": 0.5, "aspirational": 0.25}


def commitment_tier(row):
    text = clean(row.economics) + " " + clean(row.terms) + " " + clean(row.caveat)
    if _ASPIRE.search(clean(row.economics)) or row.category == "Strategic agreement":
        return "aspirational"
    if _FIRM.search(text):
        return "firm"
    return "ceiling"


def load_deals():
    a = pd.read_csv(RAW / "ai-infrastructure-agreements.csv", encoding="utf-8-sig")
    a = a[~a.lane.isin(["Pre-window context", "Unmapped aggregates"])].copy()
    # Chip/server manufacturing pledges are supply chain, not data-center deployment
    a = a[~(a.lane.eq("Chipmakers & strategic") & a.economics.fillna("").str.contains(_SUPPLY))].copy()
    a["usd"] = a.economics.map(money)
    a["tier"] = a.apply(commitment_tier, axis=1)
    a["usd_weighted"] = a.usd * a.tier.map(TIER_WEIGHT)
    a["deal_states"] = a.geography.map(states_in)
    # Same family = same underlying deal re-disclosed/amended. Keep the latest row for $ totals.
    a = a.sort_values("date")
    a["latest_in_family"] = ~a.duplicated("family", keep="last")
    edges = []
    for _, r in a.iterrows():
        parties = [canon(p) or p.strip() for p in r.parties.split("/")]
        parties = list(dict.fromkeys(p for p in parties if p))
        if len(parties) < 2:
            continue
        subject, others = parties[0], parties[1:]
        # Multi-party deals (syndicates, consortia): split evenly so the headline is counted once, not N times
        share = (r.usd_weighted / len(others)) if pd.notna(r.usd_weighted) else 0.0
        for o in others:
            edges.append({
                "deal_id": r.id, "date": r.date, "category": r.category, "lane": r.lane, "tier": r.tier,
                "a": subject, "b": o, "usd": share if r.latest_in_family else 0.0,
                "usd_headline": r.usd, "states": r.deal_states, "family": r.family,
                "title": clean(r.title), "caveat": clean(r.caveat),
            })
    return a, pd.DataFrame(edges)


def group_of(e):
    return META.get(e, {}).get("group", "Other")
