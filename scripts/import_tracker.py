"""Import policy + moratorium records from an exported Crux Data Center Tracker HTML file.

Usage:  python scripts/import_tracker.py "path/to/Crux Data Center Tracker.html"

Writes data/policy/policies.csv (state/federal bills, rules, ordinances other than moratoria) and
data/policy/moratoria.csv (every moratorium, with coordinates), joining each row to the tracker's EXT
metadata (impact class, sources, two-source verification, pass-likelihood band). Re-run whenever a
fresh tracker export lands; the app reads only the CSVs.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "policy"


def grab(src: str, name: str):
    """Extract a JS array/object literal assigned to `name` (string-aware bracket matching)."""
    m = re.search(r"\b" + name + r"\s*=\s*([\[{])", src)
    open_, close_ = m.group(1), "]" if m.group(1) == "[" else "}"
    i, depth, in_str, esc = m.start(1), 0, False, False
    while True:
        c = src[i]
        if in_str:
            esc, in_str = (False, in_str) if esc else (c == "\\", c != '"')
        elif c == '"':
            in_str = True
        elif c == open_:
            depth += 1
        elif c == close_:
            depth -= 1
            if depth == 0:
                break
        i += 1
    return json.loads(re.sub(r",\s*([\]}])", r"\1", src[m.start(1):i + 1]))


def ext_fields(e):
    e = e or {}
    srcs = e.get("sources") or []
    official = next((s["url"] for s in srcs if not s.get("type", "").startswith("News")), None)
    band = e.get("pass_likelihood") or {}
    return {"impact": e.get("impact"), "verified_two_sources": e.get("verified_two_sources"),
            "has_official_source": official is not None, "source_url": official or (srcs[0]["url"] if srcs else None),
            "n_sources": len(srcs), "pass_band": band.get("band") if isinstance(band, dict) else None,
            "status_detail": e.get("status_detail"), "threshold": e.get("threshold")}


def main(path):
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    P, M, E = grab(src, "POLICIES"), grab(src, "MORATORIA"), grab(src, "EXT")
    pol = pd.DataFrame(P, columns=["policy_id", "level", "body", "state", "category", "status", "title", "date",
                                   "summary"])
    pol = pd.concat([pol, pd.DataFrame([ext_fields(E.get(i)) for i in pol.policy_id])], axis=1)
    pol["source"] = "Crux tracker export"
    mor = pd.DataFrame(M, columns=["policy_id", "jurisdiction", "state", "level", "status", "scope", "start", "end",
                                   "months", "pipeline_mw_cited", "lat", "lon", "summary"])
    # moratorium rows appear in POLICIES too; join their EXT metadata, then keep them only in moratoria.csv
    by_id = {p: E.get(p) for p in pol.policy_id}
    def ext_for(mid):
        base = mid[2:] if mid.startswith("M-") else mid
        return by_id.get(base) or by_id.get("S-" + base) or E.get(base)
    mor = pd.concat([mor, pd.DataFrame([ext_fields(ext_for(i)) for i in mor.policy_id])], axis=1)
    mor["source"] = "Crux tracker export"
    pol = pol[pol.category != "Moratorium"]
    OUT.mkdir(parents=True, exist_ok=True)
    pol.to_csv(OUT / "policies.csv", index=False)
    mor.to_csv(OUT / "moratoria.csv", index=False)
    print(f"policies.csv: {len(pol)} rows | moratoria.csv: {len(mor)} rows "
          f"({(mor.status == 'Active').sum()} active, {(mor.status == 'Proposed').sum()} proposed)")


if __name__ == "__main__":
    main(sys.argv[1])
