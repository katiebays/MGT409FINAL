"""Red-flag engine: deterministic, scored risk flags for one company across three lenses.

Every flag carries three separate scores:
  severity   (0-1)  how much is at stake, relative to the company's own pipeline or deal book
  likelihood (0-1)  how likely the bad outcome is, driven mainly by policy status
  confidence (0-100) how much to trust the estimate: evidence quality x inference-hop penalty
plus the reasons for the confidence score and the evidence IDs (site, deal, policy) behind it.
The LLM never computes any of this; it only narrates it.
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

from build import group_of
from entities import ALIAS, META
from exposure import G, counterparty, edges, restricted_share, site_links, sites

POLICY_DIR = Path(__file__).resolve().parents[1] / "data" / "policy"

# ---------- policy layer ----------
STATUS_LIKELIHOOD = {
    "Enacted": 0.9, "Active": 0.9, "In effect": 0.9, "Active program": 0.7,
    "Passed both chambers": 0.75, "In rulemaking": 0.6, "Proposed rule": 0.55, "Passed one chamber": 0.55,
    "In litigation": 0.5, "Announced": 0.5, "Out of committee": 0.45,
    "In committee": 0.4, "Pending": 0.4, "Proposed": 0.4, "Introduced": 0.35,
    "Vetoed": 0.15, "Failed": 0.1, "Rejected": 0.1, "Expired": 0.1, "Ended (stated end date)": 0.1,
}
PASS_BAND = {"Low": 0.2, "Medium": 0.45, "High": 0.7}  # tracker's model-drafted pass likelihood for open bills
OPEN = {"In committee", "Pending", "Proposed", "Introduced", "Out of committee", "Passed one chamber", "Announced"}
# Tracker impact class -> effect on a data-center pipeline
IMPACT_EFFECT = {"Halting": "delay", "Conditional halt": "delay", "De facto halt": "delay",
                 "Procedural": "compliance", "Study": "compliance", "Enabling": "favorable"}
COUNTY_LEVEL = re.compile(r"\b(?:County|Parish|Borough)$")
MORATORIUM_RADIUS_KM = 16  # city/town/township ordinances: sites within ~10 miles of the jurisdiction centroid
# What kind of damage a policy category does to a data center pipeline
CATEGORY_EFFECT = {
    "Moratorium": "delay", "Siting & zoning": "delay", "Water": "delay", "Permitting": "delay",
    "Large load tariff": "cost", "Interconnection": "cost", "Tax incentive": "cost",
    "Disclosure & reporting": "compliance",
}
FAVORABLE = re.compile(r"(?i)accelerat|fast-track|exemption extension|bonus depreciation|federal land")
SITE_CONF = {"Confirmed": 1.0, "Reported": 0.75, "Single source": 0.55, "Not yet checked": 0.35}
MW_BASIS_CONF = {"build-out (permits)": 1.0, "announced": 0.8, "estimated from size": 0.5}
TIER_CONF = {"firm": 1.0, "ceiling": 0.7, "aspirational": 0.4}
HOP_PENALTY = {0: 1.0, 1: 0.75, 2: 0.55}
def _likelihood(df):
    lk = df.status.map(STATUS_LIKELIHOOD).fillna(0.3)
    if "pass_band" in df:
        band = df.pass_band.map(PASS_BAND)
        lk = lk.where(~(df.status.isin(OPEN) & band.notna()), band)
    return lk


def _source_conf(df):
    """Evidence quality of a policy record: two-source verified > official source > news only."""
    conf = pd.Series(0.5, index=df.index)
    if "n_sources" in df:
        conf = conf.mask(df.n_sources.fillna(0) > 0, 0.6)
        conf = conf.mask(df.has_official_source.fillna(False).astype(bool), 0.75)
        conf = conf.mask(df.verified_two_sources.fillna(False).astype(bool), 0.9)
    return conf


def _source_reason(row):
    if row.get("verified_two_sources") is True:
        return "policy record verified by two sources"
    if row.get("has_official_source") is True:
        return "policy record has an official source"
    return "policy record sourced from news only" if row.get("n_sources", 0) else "policy record unsourced"


def load_policy():
    pol = pd.read_csv(POLICY_DIR / "policies.csv")
    mor = pd.read_csv(POLICY_DIR / "moratoria.csv")
    scout = POLICY_DIR / "scout_events.csv"  # written by the Policy Scout agent after human review
    if scout.exists():
        pol = pd.concat([pol, pd.read_csv(scout)], ignore_index=True)
    for df in (pol, mor):
        for c in ("verified_two_sources", "has_official_source"):
            if c in df:
                df[c] = df[c].map({True: True, "True": True}).fillna(False).astype(bool)
    pol["likelihood"] = _likelihood(pol)
    eff = pol.impact.map(IMPACT_EFFECT) if "impact" in pol else pd.Series(index=pol.index, dtype=object)
    pol["effect"] = eff.fillna(pol.category.map(CATEGORY_EFFECT)).fillna("other")
    pol["favorable"] = (pol.effect == "favorable") | pol.title.str.contains(FAVORABLE) | \
        pol.summary.fillna("").str.contains(FAVORABLE)
    pol["src_conf"] = _source_conf(pol)
    mor["likelihood"] = _likelihood(mor)
    mor["src_conf"] = _source_conf(mor)
    mor["county_level"] = mor.jurisdiction.str.contains(COUNTY_LEVEL)
    mor["county_key"] = mor.jurisdiction.str.replace(r"\s+(County|Parish|Borough)$", "", regex=True).str.lower()
    mor["statewide"] = (mor.level == "State") & mor.scope.fillna("").str.contains("Statewide")
    return pol, mor


def sites_in_moratorium(s, m):
    """Pipeline sites covered by one moratorium: statewide -> state; county -> county name; else radius."""
    if m.statewide:
        return s[s.state == m.state]
    if m.level == "State":  # local-option enabling bills don't cover sites by themselves
        return s.iloc[0:0]
    if m.county_level:
        return s[(s.state == m.state) & (s.county.fillna("").str.lower() == m.county_key)]
    lat, lon = np.radians(s.latitude), np.radians(s.longitude)
    d = 6371 * 2 * np.arcsin(np.sqrt(np.sin((lat - np.radians(m.lat)) / 2) ** 2 + np.cos(lat) * np.cos(
        np.radians(m.lat)) * np.sin((lon - np.radians(m.lon)) / 2) ** 2))
    return s[(s.state == m.state) & (d <= MORATORIUM_RADIUS_KM)]


POLICIES, MORATORIA = load_policy()


# ---------- helpers ----------
def resolve(name: str):
    """Fuzzy-resolve user text to a canonical entity name."""
    if not name:
        return None
    key = name.strip().lower()
    if key in ALIAS:
        return ALIAS[key]
    nodes = set(G.nodes) | set(site_links.entity)
    for n in nodes:
        if n.lower() == key:
            return n
    hits = [n for n in nodes if key in n.lower()] + [ALIAS[a] for a in ALIAS if key in a]
    return hits[0] if hits else None


def label(score):
    return "High" if score >= 70 else "Medium" if score >= 45 else "Low"


def site_confidence(df):
    """MW-weighted evidence quality of a set of sites, 0-1, with human-readable reasons."""
    if df.empty or df.mw.sum() == 0:
        return 0.4, ["no MW data on these sites"]
    w = df.mw / df.mw.sum()
    c = (w * df.confidence.map(SITE_CONF).fillna(0.35)).sum()
    b = (w * df.best_total_mw_basis.map(MW_BASIS_CONF).fillna(0.5)).sum()
    exact = (w * df.location_accuracy.str.startswith(("A", "CleanView")).astype(float)).sum()
    reasons = [f"{(w * (df.confidence == 'Confirmed')).sum():.0%} of MW confirmed",
               f"{(w * (df.best_total_mw_basis == 'build-out (permits)')).sum():.0%} of MW backed by permits",
               f"{exact:.0%} of MW at exact locations"]
    return 0.5 * c + 0.3 * b + 0.2 * exact, reasons


def company_sites(ent):
    s = site_links[(site_links.entity == ent) & site_links.pipeline]
    return s.merge(sites[["id", "confidence", "best_total_mw_basis", "location_accuracy", "operating_year",
                          "src_air_permit", "src_county", "latitude", "longitude"]], on="id", how="left")


def flag(lens, title, detail, severity, likelihood, conf, reasons, hops, evidence, kind="delay", at_stake=""):
    score = round(100 * conf * HOP_PENALTY[min(hops, 2)])
    if hops:
        reasons = reasons + [f"{hops} inference hop{'s' if hops > 1 else ''} (via counterparties)"]
    return {"lens": lens, "kind": kind, "title": title, "detail": detail, "at_stake": at_stake,
            "severity": round(float(severity), 3), "likelihood": round(float(likelihood), 3),
            "risk": round(float(severity) * float(likelihood), 3),
            "confidence": score, "confidence_label": label(score), "confidence_reasons": reasons,
            "evidence": evidence[:8]}


# ---------- lens 1: project delay ----------
def delay_flags(ent, s):
    out, tot = [], s.mw.sum()
    if tot == 0:
        return out
    # D1: state concentration
    by_state = s.groupby("state").mw.sum().sort_values(ascending=False)
    for st, mw in by_state.head(3).items():
        share = mw / tot
        if share < 0.25:
            continue
        restr = POLICIES[(POLICIES.state == st) & (POLICIES.effect == "delay") & ~POLICIES.favorable]
        lk = max([0.2] + list(restr.likelihood * 0.6))  # concentration alone is a modest delay risk
        conf, why = site_confidence(s[s.state == st])
        out.append(flag("Project delay", f"{share:.0%} of pipeline concentrated in {st}",
                        f"{mw:,.0f} of {tot:,.0f} MW planned/under construction sits in one state; "
                        f"{len(restr)} delay-type policy item(s) on file there.",
                        share, lk, conf, why, 0, s[s.state == st].id.tolist() + restr.policy_id.tolist(),
                        at_stake=f"{mw:,.0f} MW"))
    # D2: sites inside active/proposed moratoria
    for _, m in MORATORIA[MORATORIA.status.isin(["Active", "Proposed"]) & MORATORIA.state.isin(s.state)].iterrows():
        hit = sites_in_moratorium(s, m)
        if hit.empty:
            continue
        conf, why = site_confidence(hit)
        how = ("statewide" if m.statewide else "same county" if m.county_level
               else f"within {MORATORIUM_RADIUS_KM} km of {m.jurisdiction}")
        out.append(flag("Project delay", f"{m.status} moratorium: {m.jurisdiction}, {m.state}",
                        f"{len(hit)} pipeline site(s), {hit.mw.sum():,.0f} MW, covered ({how}) by a "
                        f"{m.status.lower()} moratorium. {m.scope}. {m.summary}",
                        hit.mw.sum() / tot, m.likelihood, conf * m.src_conf,
                        why + [_source_reason(m), f"site match: {how}"], 0,
                        hit.id.tolist() + [m.policy_id], at_stake=f"{hit.mw.sum():,.0f} MW"))
    # D3: thin evidence behind the pipeline (execution risk)
    thin = s[s.confidence.isin(["Not yet checked", "Single source"]) & s.src_air_permit.isna() & s.src_county.isna()]
    if thin.mw.sum() / tot >= 0.3:
        out.append(flag("Project delay", f"{thin.mw.sum() / tot:.0%} of pipeline MW has no permit or county record",
                        f"{len(thin)} sites ({thin.mw.sum():,.0f} MW) rest on announcements or tracker data only; "
                        "unpermitted projects slip most often.",
                        thin.mw.sum() / tot, 0.35, 0.65,
                        ["no permit/county source in the tracker", "absence of a record is not proof of no permit"], 0,
                        thin.id.tolist(), at_stake=f"{thin.mw.sum():,.0f} MW"))
    # D4: near-term promises not yet under construction
    yr = pd.to_numeric(s.operating_year, errors="coerce")
    late = s[(s.status == "Planned") & (yr <= 2027)]
    if late.mw.sum() / tot >= 0.1:
        conf, why = site_confidence(late)
        out.append(flag("Project delay", "Near-term capacity not yet under construction",
                        f"{len(late)} sites ({late.mw.sum():,.0f} MW) target operation by 2027 but are still 'Planned'.",
                        late.mw.sum() / tot, 0.55, conf, why, 0, late.id.tolist(), at_stake=f"{late.mw.sum():,.0f} MW"))
    return out


# ---------- lens 2: state policy activity ----------
def policy_flags(ent, s):
    out, tot = [], s.mw.sum()
    if tot == 0:
        return out
    by_state = s.groupby("state").mw.sum()
    for st, mw in by_state[by_state / tot >= 0.1].items():
        pol = POLICIES[(POLICIES.state == st) & ~POLICIES.favorable & (POLICIES.likelihood >= 0.3)]
        for _, p in pol.iterrows():
            where, hit_mw = st, mw
            if p.level == "Local":  # county ordinances only touch sites in that county
                cty = re.sub(r"\s+County$", "", str(p.body)).lower()
                hit_mw = s[(s.state == st) & s.county.fillna("").str.lower().str.contains(cty, regex=False)].mw.sum()
                where = f"{p.body}, {st}"
                if hit_mw == 0:
                    continue
            out.append(flag("State policy", f"{where}: {p.title}",
                            f"{p.status} {p.category.lower()} ({p.body}, {p.date}). {p.summary} "
                            f"Company has {hit_mw:,.0f} MW ({hit_mw / tot:.0%} of pipeline) in {where}.",
                            hit_mw / tot * (1.0 if p.effect == "delay" else 0.35), p.likelihood, p.src_conf,
                            [_source_reason(p), f"status '{p.status}'"
                             + (f", pass likelihood {p.pass_band}" if isinstance(p.get("pass_band"), str) else "")], 0,
                            [p.policy_id], kind=p.effect, at_stake=f"{hit_mw:,.0f} MW in {where}"))
    return out


# ---------- lens 3: counterparty ----------
def counterparty_flags(ent):
    out = []
    cp = counterparty(ent)
    if not cp or cp["total_usd"] == 0:
        return out
    t, tot = cp["table"], cp["total_usd"]
    mine = edges[(edges.a == ent) | (edges.b == ent)]
    tier_mix = mine.groupby("tier").usd.sum()
    tier_conf = float((tier_mix * pd.Series(TIER_CONF)).sum() / tier_mix.sum()) if tier_mix.sum() else 0.5
    # C1: concentration
    top = t.iloc[0]
    if top.share >= 0.3 or cp["hhi"] >= 2500:
        out.append(flag("Counterparty", f"{top.counterparty} is {top.share:.0%} of the deal book",
                        f"HHI {cp['hhi']:,.0f} across {len(G[ent])} counterparties; top three: "
                        + ", ".join(f"{r.counterparty} {r.share:.0%}" for r in t.head(3).itertuples()) + ".",
                        top.share, 0.3 if group_of(top.counterparty) == "Hyperscaler" else 0.45, tier_conf,
                        [f"deal book is {tier_mix.get('firm', 0) / tier_mix.sum():.0%} firm commitments by weighted $"],
                        0, G[ent][top.counterparty]["deals"], kind="credit",
                        at_stake=f"${top.usd / 1e9:,.1f}B weighted"))
    # C2: soft commitments
    soft = (tier_mix.get("ceiling", 0) + tier_mix.get("aspirational", 0)) / tier_mix.sum()
    if soft >= 0.6:
        out.append(flag("Counterparty", f"{soft:.0%} of deal value is ceilings or headlines, not firm minimums",
                        "Most contracted value is 'up to' or announced intent; it can shrink without a breach.",
                        soft * 0.4, 0.35, 0.85, ["tiers parsed from disclosure text (regex first pass)"], 0,
                        mine[mine.tier != "firm"].deal_id.unique().tolist(), kind="credit"))
    # C3: second-order geographic concentration of top counterparties
    for r in t.head(4).itertuples():
        cs = site_links[(site_links.entity == r.counterparty) & site_links.pipeline]
        if cs.mw.sum() == 0:
            continue
        st_share = cs.groupby("state").mw.sum() / cs.mw.sum()
        st, sh = st_share.idxmax(), st_share.max()
        if sh < 0.4:
            continue
        restr = POLICIES[(POLICIES.state == st) & ~POLICIES.favorable]
        conf, why = site_confidence(cs.merge(sites[["id", "confidence", "best_total_mw_basis", "location_accuracy"]],
                                             on="id"))
        out.append(flag("Counterparty", f"Counterparty {r.counterparty} has {sh:.0%} of its pipeline in {st}",
                        f"{ent}'s ${r.usd / 1e9:,.1f}B (weighted) with {r.counterparty} depends on capacity "
                        f"concentrated in {st}; {len(restr)} policy item(s) on file there.",
                        r.share * sh, max([0.2] + list(restr.likelihood * 0.5)), conf * tier_conf, why, 1,
                        G[ent][r.counterparty]["deals"] + restr.policy_id.tolist(), kind="delay",
                        at_stake=f"${r.usd * sh / 1e9:,.1f}B"))
    # C4: circular financing loops
    shown = 0
    for loop in cp["loops"]:
        if shown == 3:
            break
        if any(group_of(n) in ("Capital provider", "Other") for n in loop):
            continue  # lender syndicates create trivial loops; keep operating-company loops only
        deal_ids = [d for a, b in zip(loop, loop[1:] + loop[:1]) if G.has_edge(a, b) for d in G[a][b]["deals"]]
        cats = set(edges[edges.deal_id.isin(deal_ids)].category)
        if not ({"Equity investment", "Guarantee", "Financing"} & cats and
                {"Compute offtake", "Chip supply", "Lease"} & cats):
            continue  # only flag loops where money goes in as capital and comes back as revenue
        out.append(flag("Counterparty", "Circular loop: " + " → ".join(loop + [loop[0]]),
                        f"Capital ({', '.join(sorted(cats & {'Equity investment', 'Guarantee', 'Financing'}))}) and "
                        f"revenue ({', '.join(sorted(cats & {'Compute offtake', 'Chip supply', 'Lease'}))}) flow around "
                        "the same counterparties; a shock to one propagates to all.",
                        0.3, 0.3, 0.8, ["loop built only from disclosed agreements"], len(loop) - 2, deal_ids,
                        kind="credit"))
        shown += 1
    return out


def red_flags(company: str):
    ent = resolve(company)
    if not ent:
        return {"error": f"Unknown company '{company}'. Try one of: " + ", ".join(sorted(META)[:25])}
    s = company_sites(ent)
    flags = [f for f in delay_flags(ent, s) + policy_flags(ent, s) + counterparty_flags(ent) if f["severity"] >= 0.01]
    flags.sort(key=lambda f: -f["risk"])
    found = len(flags)
    flags = flags[:MAX_FLAGS]  # keep the report focused: top 10 by risk
    for i, f in enumerate(flags, 1):
        f["rank"] = i
    meta = META.get(ent, {})
    return {"company": ent, "group": group_of(ent), "ticker": meta.get("ticker"), "public": meta.get("public", False),
            "pipeline_mw": round(float(s.mw.sum())), "pipeline_sites": int(len(s)),
            "deal_book_usd_weighted": round(float(counterparty(ent)["total_usd"])) if ent in G else 0,
            "flags_found": found, "flags": flags}


MAX_FLAGS = 10


# ---------- hypothetical scenario ----------
REVENUE_PER_MW_YEAR = 10e6  # ASSUMPTION: ~$10M revenue per MW-year for leased AI capacity; editable


def scenario(company: str, states: list, months: int = 12, revenue_per_mw_year: float = REVENUE_PER_MW_YEAR):
    """Hypothetical: new construction is frozen in `states` for `months`. Extrapolated, so confidence is capped."""
    ent = resolve(company)
    if not ent:
        return {"error": f"Unknown company '{company}'"}
    states = [x.upper() for x in states]
    share, hit_mw, tot = restricted_share(ent, states)
    s = company_sites(ent)
    hit = s[s.state.isin(states)]
    deferred = hit_mw * revenue_per_mw_year * months / 12
    paths = []
    for _, e in edges[((edges.a == ent) | (edges.b == ent)) & (edges.usd > 0)].iterrows():
        cp = e.b if e.a == ent else e.a
        if set(e.states) & set(states):
            f, how, hops = len(set(e.states) & set(states)) / len(e.states), "deal sited in restricted state", 0
        else:
            f, _, _ = restricted_share(cp, states)
            how, hops = f"{cp}'s pipeline share in {','.join(states)}", 1
        if f:
            paths.append({"counterparty": cp, "deal_id": e.deal_id, "category": e.category, "tier": e.tier,
                          "usd_exposed": round(e.usd * f), "how": how, "hops": hops})
    paths.sort(key=lambda p: -p["usd_exposed"])
    conf, why = site_confidence(hit) if not hit.empty else (0.5, ["no own sites in scenario states"])
    return {"company": ent, "states": states, "months": months,
            "pipeline_mw": round(float(tot)), "mw_delayed": round(float(hit_mw)),
            "pct_pipeline_delayed": round(float(share or 0), 3),
            "sites_delayed": hit[["id", "project_name", "state", "county", "mw", "status"]].head(10).to_dict("records"),
            "deferred_revenue_usd": round(deferred),
            "assumption": f"${revenue_per_mw_year / 1e6:.0f}M revenue per MW-year, linear over {months} months",
            "deal_usd_exposed": round(sum(p["usd_exposed"] for p in paths)),
            "deal_paths": paths[:8],
            "confidence": round(100 * conf * 0.8), "confidence_label": label(100 * conf * 0.8),
            "confidence_reasons": why + ["hypothetical scenario: revenue impact is extrapolated (x0.8)"]}
