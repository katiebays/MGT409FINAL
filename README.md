# Data Centers Decoded

**An investor's risk browser for AI data-center infrastructure: siting × policy × financing.**

Pick a company — a hyperscaler, neocloud, frontier lab, chipmaker, miner-turned-AI-host — and the app tells you
where its biggest risk exposures lie, how much to trust each finding, and what happens under a hypothetical
policy shock ("what if Texas freezes new construction for 24 months?").

MGT 409 (AI for Managers) final project · Katie Bays · Repo: https://github.com/katiebays/MGT409FINAL · Report: `report.html` · Slides: `slides.html`

**No hosted app:** it runs locally from a fresh clone in about 5 minutes (below).

---

## Run it (about 5 minutes)

Requires Python 3.11+.

```powershell
git clone https://github.com/katiebays/MGT409FINAL.git
cd MGT409FINAL
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:8050**.

### API key

Put a `.env` file **in this folder or one folder up** (the app checks this folder first, then the parent). See
`.env.example`:

```
PORTKEY_API_KEY=...        # course key, tried first
OPENAI_API_KEY=...         # direct OpenAI key, used if Portkey is missing or rejects its key
OPENAI_MODEL=gpt-6-luna
```

The app tries Portkey first and falls back to OpenAI automatically if a key is rejected. With **no working key**
the app still runs in *offline mode*: the same risk tools answer with a templated summary instead of the LLM.

> Development note: the course's Yale Portkey key expired after the term, so the measured runs in the report
> used a personal OpenAI key with `gpt-6-luna`.

### Data: sample vs. full

| Mode | Folder | In git? | Contents |
|---|---|---|---|
| `sample` (default from a fresh clone) | `data/sample/` | yes | 1,554 sites: every site tied to a tracked company + 150 others; all 201 deals |
| `full` | `data/raw/` | no | 2,925 sites, 201 deals (licensed feeds) |

The app uses `full` automatically when `data/raw/US_data_centers_master.csv` exists, otherwise `sample`.
Force either with an environment variable:

```powershell
$env:DATA_MODE = "sample"; python app.py
$env:DATA_MODE = "full";   python app.py
```

Company-level red flags are identical in both modes (every company-linked site is in the sample); only the
all-companies map is thinner in `sample`.

Policy data (`data/policy/`) is committed: 882 local and state moratoria and 60 state/federal bills, rules and
directives, exported from the Crux Data Center Tracker (public sources, organized and classified).

---

## What it does

### 1. Red flags (chat + report)

Ask about a company in plain English. The analyst agent calls deterministic risk tools and returns ranked
flags across three lenses:

| Lens | Checks |
|---|---|
| **Project delay** | state concentration of the pipeline; sites inside active/proposed moratoria (county match, or within 16 km of a city/township); pipeline MW with no permit or county record; near-term capacity still only "Planned" |
| **State policy** | restrictive bills, rules and directives where the company builds, weighted by status and the tracker's pass-likelihood band |
| **Counterparty** | deal-book concentration (HHI); share of value that is ceilings/headlines vs. firm minimums; top counterparties' own geographic concentration; circular capital ↔ revenue loops |

Each flag carries three **separate** scores:

- **Severity**: share of the company's pipeline or deal book at stake
- **Likelihood**: driven by policy status (enacted > in rulemaking > in committee > news only)
- **Confidence (0–100)**: evidence quality (site confirmation, permit-backed MW, exact location, deal firmness,
  policy source verification), reduced for each counterparty "hop". *Low confidence means weak evidence, not low risk.*

Follow-ups run **scenarios**: `run_scenario(company, states, months)` returns MW delayed, extrapolated deferred
revenue (assumption shown and editable), and deal value exposed through counterparties.

### 2. Projects & policy map

- Projects by status (operating / under construction / planned), sized by MW, filterable by company
- 882 moratoria as markers; states shaded by a **policy pressure index**
  (likelihood × effect weight of restrictive items; supportive items never raise it)
- Click a state for its full policy record and who is building there
- **Policy proliferation** timeline: cumulative restrictive vs. cost vs. supportive actions over time

---

## How it is built

```
data/raw | data/sample        data/policy
  sites.csv  deals.csv          policies.csv  moratoria.csv
        │        │                     │
        ▼        ▼                     ▼
   engine/build.py  ──►  engine/exposure.py  ──►  engine/red_flags.py      (deterministic Python, no LLM)
   entity registry,      deal graph, HHI,        3 lenses, scores,
   commitment tiers      policy_shock()          scenario()
                                                       │ tools
                                                       ▼
                                            agent/analyst.py  (PydanticAI agent)
                                            grounding check · budget cap · offline fallback
                                                       │
                                                       ▼
                                   app.py (Dash) + views/map_view.py
```

**Design rule:** the LLM only *narrates*. All numbers come from Python tools.

### Safety

- **Grounding check.** Every $, %, MW and GW figure in an answer must match a number a tool returned (or the user
  typed). Otherwise the answer is sent back to the model once (`ModelRetry`), then withheld if it still fails.
- **Budget cap.** 8 requests, 8 tool calls and 60k tokens per question (`UsageLimits`).
- **Prompt-injection posture.** Bill, filing and news text reaches the model only as JSON tool data; the system
  prompt says never to follow instructions inside it. Large policy lists are capped before they reach the prompt.
- **No investment advice.** The agent describes exposures; it does not recommend buy/sell/hold.
- Every run is logged to `logs/runs.jsonl` (status, tools, tokens, grounding failures). This file is not committed.

### Commitment weighting (why headline $ are not added up)

Deal announcements mix firm minimums, "up to" ceilings and aspirational headlines, and the same deal is
often re-announced. The engine:

1. weights each deal by tier: firm × 1.0, ceiling × 0.5, aspirational × 0.25
2. counts only the latest row in each deal `family`
3. splits multi-party deals across counterparties
4. excludes chip-manufacturing pledges (supply chain, not deployment)

---

## Report, slides and evidence

- `report.html` and `slides.html` are self-contained (open by double-clicking; images embedded).
- Rebuild them from real runs: `python scripts/evaluate.py` (live benchmark, cost A/B and safety tests -> `logs/eval_results.json`),
  `python scripts/screenshots.py` (app must be running; uses installed Chrome via Playwright), then `python docs/build_docs.py`.
  These three scripts need `pip install playwright pillow` in addition to `requirements.txt`.

## Updating the data

- **Sites and deals:** drop refreshed CSVs into `data/raw/` with the same filenames and restart.
- **Policy:** export the tracker HTML and run
  `python scripts/import_tracker.py "path/to/Crux Data Center Tracker.html"`.
- **Planned:** a weekly Policy Scout agent (LegiScan search + news alerts) writes candidate events to
  `data/policy/scout_events.csv` after human review. The engine already reads that file if it exists.

## Project layout

```
app.py                 Dash app: header, Red flags view, chat callbacks
views/map_view.py      Projects & policy map
agent/analyst.py       PydanticAI analyst, tools, grounding check, provider fallback, run log
engine/entities.py     Entity registry: aliases, ecosystem group, ticker
engine/build.py        Load sites/deals, link to entities, commitment tiers, data-mode switch
engine/exposure.py     Deal graph, counterparty concentration, policy_shock()
engine/red_flags.py    Red-flag lenses, scoring, scenario()
scripts/import_tracker.py   Policy import from the tracker export
data/sample/  data/policy/  assets/style.css
DESIGN.md              Original design sketch
```

## Limits

- Deal $ and money direction come from regex parsing in this version. An LLM extraction agent (designed, not shipped)
  would pull out payer/payee, firm vs. ceiling $, and US-state allocation.
- 1,374 of 2,865 non-canceled sites link to a tracked company. The `tenant` field is sparse, so frontier-lab
  exposure leans on deals.
- Scenario revenue uses a single $/MW-year assumption.
- Operating sites are excluded from "at risk", even though their expansion phases may be exposed.
