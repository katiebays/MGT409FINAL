# AI Infrastructure Risk Browser: design sketch

**One-line pitch:** An investor picks a company or a geography and gets back a sourced sentence like
*"A long-term Texas moratorium puts 51% of CoreWeave's 4,560 MW development pipeline at risk of delay;
its largest exposed counterparties are Meta and NVIDIA."*
This sentence comes from the prototype engine running on the real CSVs.

## 1. Three data layers, one join key

| Layer | Source | Grain | Join key |
|---|---|---|---|
| **Siting** | `US_data_centers_master.csv` (2,925 sites; 1,565 planned or under construction) | site | `state`, `county`, `developer`/`tenant` → entity |
| **Financing** | `ai-infrastructure-agreements.csv` (201 deals, 167 deal families, ~250 named parties) | deal → pairwise edges | `parties` → entity; `geography` → state |
| **Policy** | Crux tracker seed (34 policies, 16 local moratoria) + weekly LegiScan/news scout | event | `state` (+ county FIPS) |

The hub is an **entity registry** (`engine/entities.py`). It maps aliases to one company ("AWS", "Amazon.com", and "Amazon/AWS" all become Amazon), and it assigns each company a group and a ticker. Every layer links through it.

## 2. How to group companies

The grouping follows each company's role in the capital stack, from who pays to who builds to who funds:

| Group | Members (examples) | Role in a slowdown |
|---|---|---|
| Frontier lab | OpenAI, Anthropic, xAI | Ultimate demand; signs multi-year offtakes |
| Hyperscaler | MSFT, AMZN, GOOGL, META, ORCL | Self-builds *and* buys from neoclouds; very large pipelines |
| Neocloud | CoreWeave, Nebius, Crusoe, Lambda, Nscale, Fluidstack | Leveraged middle layer; most concentrated |
| Miner-turned-AI host | IREN, Applied Digital, TeraWulf, Cipher, Hut 8, Core Scientific | Powered land; highly concentrated in specific states |
| Chips & hardware | NVIDIA, AMD, Broadcom, TSMC | Vendor financing, backstops, equity (circularity) |
| Developer / landlord | Digital Realty, QTS, Vantage, Tract, Cloverleaf | Physical exposure, lease counterparty |
| Capital provider | SoftBank, Blackstone, Blue Owl, bank syndicates | Credit exposure to all of the above |
| Power | Constellation, Vistra, AEP, SB Energy | PPAs tied to specific sites |

A public/private flag sits on top of the groups, so the investor view can show **public tickers exposed through private hubs**. OpenAI and Crusoe are the clearest cases.

## 3. Surface 1: counterparty and concentration risk

For a selected company:
- **Book by counterparty.** Weighted $ per counterparty, its share of the book, the number of deals, and an HHI score.
- **Book by group.** For example, CoreWeave's book is 42% Meta, 21% NVIDIA, and 13% OpenAI (HHI about 2,400, which counts as concentrated).
- **Second degree.** What do my top counterparties depend on? Take CoreWeave → OpenAI → Oracle/SoftBank. That chain is the circular-financing story.
- **Loops.** These are short cycles through the company, such as NVIDIA ↔ OpenAI ↔ SB Energy, or NVIDIA → CoreWeave → NVIDIA. Each one gets flagged as circular.

**The critical modeling choice is that headline dollars are not additive.** The raw file lists Stargate at $500B, a NVIDIA manufacturing pledge at $500B, and many "up to" ceilings. Summing them naively gave NVIDIA a $2.8T book. The engine applies three corrections:
1. **Commitment tier.** *Firm* minimums (for example, "at least $X regardless of usage") count at 1.0, *ceilings* and facilities at 0.5, and *aspirational* headlines (intend, plan, framework) at 0.25.
2. **Family dedupe.** Only the latest row in each `family` counts. The caveat column already says which rows supersede earlier ones.
3. **Even split.** Multi-party deals and syndicates are split across counterparties, so one deal is not counted N times. Chip manufacturing pledges are excluded because they are supply chain, not deployment.

The regex version is a placeholder. The **Deal Extraction Agent** (below) does this properly: it records who pays whom, the committed vs. ceiling $, the US-state allocation, and what each row supersedes.

## 4. Surface 2: policy shock (direct and indirect)

Input: a scenario. That can be a set of states or counties, plus severity and duration, or a real policy event selected from the tracker.

- **Direct exposure** covers the company's own pipeline sites (planned or under construction, as developer or tenant) inside the restricted geography. It is reported as MW at risk, % of pipeline, and announced capex at risk.
- **Indirect exposure** covers the company's deals, where each deal's weighted $ is multiplied by a factor that depends on the deal:
  - If the deal's `geography` names the state, use the share of the deal's states that are restricted.
  - Otherwise, use the counterparty's pipeline share in the restricted geography. Example: OpenAI → Oracle deal × Oracle's Texas share.

Prototype output, Texas scenario (pipeline only, real data):

| Company | Pipeline MW | % in TX | Deal $ touched (weighted) |
|---|---|---|---|
| Crusoe | 7,826 | **93%** | $7.5B (Abilene JV with Oracle and Blue Owl) |
| Core Scientific | 2,451 | **95%** | $4.1B |
| IREN | 5,753 | 64% | $3.8B |
| CoreWeave | 4,560 | **51%** | $1.9B (Meta, Core Scientific, NVIDIA) |
| Amazon | 55,588 | 41% | none |
| OpenAI | 20,578 | 0% *own* | **$67B indirect** via Oracle and Amazon offtakes |
| Anthropic | 482 | 0% own | **$86B indirect** via Fluidstack and AWS |

The last two rows are the point of the product. A frontier lab has almost no sites of its own, yet a Texas moratorium hits it through its counterparties.

## 5. Keeping the data current (the agents)

```
 firm feeds ──► data/raw/*.csv (auto-refreshed) ──┐
                                                  ▼
                              [1] Deal Extraction Agent ── only new/changed rows (hash cache)
                                                  │        → edges.parquet (payer, payee, $firm, $ceiling, tier, states, supersedes)
 LegiScan API (weekly) ─┐                          │
 News RSS/GDELT (daily)─┼► [2] Policy Scout Agent ─┼──► policy_events.parquet (geo FIPS, type, status, severity, dates, source URL)
                        │      classify + geocode  │        └► review queue (human approves before it drives scenarios)
                        ┘                          ▼
                              Exposure engine (deterministic Python, no LLM)
                                                  │
                              [3] Analyst Agent ◄─┘  tools: counterparty(), policy_shock(), find_sites(), get_deal()
                                                     writes the investor sentence; every number must come from a tool call
```

- **Policy Scout.** Runs LegiScan `getSearch` on terms like "data center", "large load", and "moratorium" for each state, plus Google News RSS or GDELT queries such as `"data center" (moratorium OR rezoning OR "pause")`. It dedupes against existing events. The LLM fills a strict schema: is this a restriction, its type, the geography, the status, and the effective dates. Nothing is auto-promoted; new events land in a review queue.
- **Scheduling.** Use a weekly cron/Task Scheduler job (or a GitHub Action) for LegiScan and a daily job for news. Both write parquet; the app reads parquet.
- **Determinism boundary.** LLMs only *extract* and *narrate*. All exposure math is plain Python, so results are reproducible and auditable.

## 6. Course fit (MGT 409 final)

- **Agents (10 pts):** three agents with distinct jobs → diagram above. Trace one real run, e.g. "What happens to CoreWeave if Texas pauses?"
- **Tokenomics (8):** extraction runs once per new row with a hash cache, so a refresh costs only the delta. Measure tokens per row and per analyst question.
- **Safety (8):** (a) prompt injection through scraped bill or news text: scraped text is data in a schema-only extraction call that has no tools; (b) invented numbers: a validator rejects any analyst answer containing a $ or % that does not appear in the tool outputs, and a screenshot of a rejection is your evidence; (c) overspend: a token budget cap per run.
- **Data licensing:** `data/raw/` is gitignored. Ship a small sample, or anonymized/synthetic rows, in `data/sample/`, and explain how to switch in the README (the course requires this for big datasets anyway).

## 7. Known gaps (from the first pass)

- 1,374 of 2,865 non-canceled sites link to a registry entity. Most of the rest are small colocation operators and anonymous developers.
- The `tenant` field is sparse (114 rows), so lab and neocloud exposure leans on deals, not sites. Adding tenant data is the biggest accuracy win.
- Operating sites are excluded from "at risk." Expansion phases at operating campuses may still be exposed, so this needs a decision.
- Direction of money (who pays whom) is not modeled yet. That is the extraction agent's job.
- The policy seed comes from the Crux tracker mockup. Verify it before you cite any of it.
