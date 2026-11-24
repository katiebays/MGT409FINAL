"""The two analysis surfaces.

1. counterparty(company)  -> who this company's deal book depends on, how concentrated, second-degree links, loops
2. policy_shock(states)   -> direct (own sites) and indirect (deal-linked) exposure to a geographic slowdown
"""
from collections import defaultdict

import networkx as nx
import pandas as pd

from build import group_of, load_deals, load_sites

sites, links = load_sites()
deals, edges = load_deals()
site_links = links.merge(sites[["id", "state", "county", "mw", "capex", "pipeline", "status", "project_name"]],
                         left_on="site_id", right_on="id")

G = nx.Graph()
for _, e in edges.iterrows():
    w = e.usd or 0
    if G.has_edge(e.a, e.b):
        G[e.a][e.b]["usd"] += w
        G[e.a][e.b]["deals"].append(e.deal_id)
    else:
        G.add_edge(e.a, e.b, usd=w, deals=[e.deal_id])


# ---------- Surface 1: counterparty / concentration ----------
def counterparty(company, top=10):
    if company not in G:
        return None
    rows = [{"counterparty": n, "group": group_of(n), "usd": G[company][n]["usd"],
             "n_deals": len(G[company][n]["deals"])} for n in G[company]]
    df = pd.DataFrame(rows).sort_values("usd", ascending=False)
    tot = df.usd.sum()
    df["share"] = df.usd / tot if tot else 0
    hhi = float((df.share ** 2).sum() * 10_000)
    by_group = df.groupby("group").usd.sum().sort_values(ascending=False)
    # Second degree: what do my top counterparties depend on?
    second = {}
    for cp in df.head(5).counterparty:
        nb = sorted(((n, G[cp][n]["usd"]) for n in G[cp] if n != company), key=lambda x: -x[1])[:4]
        second[cp] = nb
    # Circular financing: short cycles through this company (A->B->C->A)
    loops = [c for c in nx.cycle_basis(G.subgraph(nx.node_connected_component(G, company)))
             if company in c and 3 <= len(c) <= 4]
    return {"table": df.head(top), "total_usd": tot, "hhi": hhi, "by_group": by_group,
            "second_degree": second, "loops": loops[:8]}


# ---------- Surface 2: policy shock ----------
def restricted_share(entity, states):
    """Share of an entity's pipeline MW (planned + under construction) located in the restricted states."""
    s = site_links[(site_links.entity == entity) & site_links.pipeline]
    tot = s.mw.sum()
    if tot == 0:
        return None, 0.0, 0.0
    hit = s[s.state.isin(states)].mw.sum()
    return hit / tot, hit, tot


def policy_shock(states):
    states = set(states)
    out = []
    for ent in sorted(set(site_links.entity) | set(G.nodes)):
        share, hit_mw, tot_mw = restricted_share(ent, states)
        capex_hit = site_links[(site_links.entity == ent) & site_links.pipeline
                               & site_links.state.isin(states)].capex.sum()
        # Indirect: each deal $ x the restricted share of the infrastructure-side counterparty,
        # or 100% when the deal itself names a restricted state.
        ind, paths = 0.0, []
        if ent in G:
            for _, e in edges[(edges.a == ent) | (edges.b == ent)].iterrows():
                if not e.usd:
                    continue
                cp = e.b if e.a == ent else e.a
                if set(e.states) & states:
                    hit = set(e.states) & states
                    f, why = len(hit) / len(e.states), "deal sited in " + ",".join(sorted(hit))
                else:
                    f, _, _ = restricted_share(cp, states)
                    why = f"{cp} pipeline share"
                if f:
                    ind += e.usd * f
                    paths.append((cp, e.deal_id, e.category, e.usd * f, why))
        if hit_mw or ind:
            out.append({"entity": ent, "group": group_of(ent), "pipeline_mw": tot_mw, "mw_at_risk": hit_mw,
                        "pct_pipeline_at_risk": share, "direct_capex_at_risk": capex_hit,
                        "indirect_deal_usd_at_risk": ind,
                        "top_paths": sorted(paths, key=lambda p: -p[3])[:4]})
    return pd.DataFrame(out).sort_values("indirect_deal_usd_at_risk", ascending=False)


def sentence(row, label):
    """Turn one row into the investor-style sentence the dashboard leads with."""
    parts = []
    if row.pct_pipeline_at_risk and row.pipeline_mw:
        parts.append(f"puts {row.pct_pipeline_at_risk:.0%} of {row.entity}'s {row.pipeline_mw:,.0f} MW "
                     f"development pipeline ({row.mw_at_risk:,.0f} MW) at risk of delay")
    if row.indirect_deal_usd_at_risk:
        who = ", ".join(sorted({p[0] for p in row.top_paths}))
        parts.append(f"touches ~${row.indirect_deal_usd_at_risk/1e9:,.1f}B of deal value with {who}")
    return f"{label} " + " and ".join(parts) + "." if parts else ""
