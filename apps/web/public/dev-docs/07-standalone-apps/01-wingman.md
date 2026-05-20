# Wingman — energy commodity trading

> The reference standalone app. ~10 pages, 14 agents, 4 corridors, 5 ML models. The most-evolved example of the thin-app pattern.

---

## Domain

Wingman is a trader workbench for LPG / refined-product commodity desks. The core question: **is this corridor's spread mispriced relative to fundamentals + freight + options?**

The four active corridors:
- USGC → NWE (US Gulf to NW Europe propane)
- USGC → FE (US Gulf to Far East)
- MEG → FE (Middle East Gulf to Far East)
- USGC → LATAM (US Gulf to Latam)

For each corridor + day the platform computes:
- **Observed spread** — destination spot − origin spot − freight (real-world arb residual, $/MT).
- **Fair-value spread** — BayesianRidge model prediction with credibility interval.
- **Verdict** — aligned / stretched / dislocated based on the residual z-score.
- **Drivers** — top 3 news headlines explaining the mispricing.

---

## Pages

| Route | Purpose | Backing agent |
|---|---|---|
| `/` Home | Today's signals (4 corridor cards), Mont Belvieu, WTI, Brent, FX, AIS | `wingman-market-brief` |
| `/copilot` Wingman Copilot | Free-form chat against a meta-agent | `wingman-desk-copilot` |
| `/workbench` Arbitrage Workbench | Deep arb math, hedge recipes, scenarios per corridor | `wingman-arb-analyzer` |
| `/mispricing` Price at Risk Lens | The headline page — corridor scan, fair value chart, drivers | `wingman-mispricing-extractor` |
| `/scenarios` Forward Scenarios | Probability-weighted forward curves with what-if sliders | `wingman-scenario-forecaster` |
| `/freight-lab` Market & Freight Lab | Baltic + Worldscale + vessel-class inspector | direct tools |
| `/inbox` Broker Inbox | Parsed broker emails → live offers | `wingman-broker-classifier` + `wingman-broker-parser` |
| `/ops` Operations Watch | AIS + ports + weather + outages | `wingman-ops-monitor` |
| `/lab` Strategy Lab | Backtester, VaR simulator | `wingman-backtester`, `wingman-var-simulator` |
| `/knowledge-graph` Atlas (Wingman lens) | Counterparty + vessel + event graph | `wingman-graph-query` |
| `/approvals` Approvals | HITL gate queue (platform passthrough) | platform `/approvals` |

---

## Agents catalogue

All in `packages/db/seeds/agents/wingman_*.yaml`:

| Slug | Purpose | LLM |
|---|---|---|
| `wingman-market-brief` | Pull today's spot/forward/freight + 5 news headlines for the home page | Haiku 4.5 |
| `wingman-mispricing-extractor` | The big one — corridor scan with 15-feature vector + Bayesian Ridge call | Haiku 4.5 |
| `wingman-scenario-forecaster` | 5 probability-weighted scenarios with cited drivers | Haiku 4.5 |
| `wingman-arb-analyzer` | Deep arb math + 9-leg hedge + vessel-class economics | Sonnet 4.6 |
| `wingman-ops-monitor` | AIS-density alerts, weather, port outages | Haiku 4.5 |
| `wingman-broker-classifier` | Intent classification on broker emails | sklearn classifier (not LLM) |
| `wingman-broker-parser` | Extract structured offer from a parsed broker email | Haiku 4.5 |
| `wingman-desk-copilot` | Meta-agent that fans out to specialists | Haiku 4.5 + invoke_agent |
| `wingman-backtester` | Reverse-test a strategy spec over history | Sonnet 4.6 |
| `wingman-var-simulator` | Monte-Carlo VaR on a position | Haiku 4.5 |
| `wingman-compliance-validator` | Pre-trade compliance gate | Haiku 4.5 |
| `wingman-graph-query` | Atlas Cypher queries via the graph_query tool | Haiku 4.5 |
| `wingman-strategy-encoder` | NL → backtest spec | Sonnet 4.6 |
| `wingman-brief-repair` | Retry / repair tool when market-brief output is malformed | Haiku 4.5 |

---

## ML models

5 pkls in `wingman/ml-models/`:

| Model | Type | Purpose |
|---|---|---|
| `wingman-mispricing-fairvalue` v1.3.0 | BayesianRidge | Corridor spread fair-value (15 features) |
| `wingman-mispricing-anomaly` v1.0.0 | IsolationForest | Anomaly score (9 features) |
| `wingman-scenario-prior` v1.0.0 | GaussianNB | Scenario probability prior (8 features) |
| `wingman-broker-intent-classifier` v1.0.0 | sklearn pipeline | Broker email intent classification |
| `wingman-freight-forecast` v1.0.0 | GradientBoosting | Next-week BLPG mid forecast (8 features) |

Training scripts live next to the pkls. Each has a `meta.json` with input_schema, output_schema, training metrics, feature names.

---

## Caching

`wingman/api/cache.py` — file-backed, per page:

| Page | Cache key | TTL |
|---|---|---|
| `/api/wingman/market-brief` | `snapshot` | 300s |
| `/api/wingman/signals` | per-corridor `mispricing/<id>` | 1800s |
| `/api/wingman/scenarios/<id>` | `<id>` | 1800s |
| `/api/wingman/analyze/<id>` | `<id>` | 1800s |
| `/api/wingman/ops` | `snapshot` | 3600s |

Cache rows live under `/data/wingman-cache/<page>/<key>.json` on a host-path PVC.

---

## Three-tier resolution for mispricing scans

Per the strict-architecture rules:

```mermaid
flowchart TB
  S[Scan request] --> A[Tier 1<br/>wingman-mispricing-extractor agent]
  A --> V{Sanity check?<br/>obs + fv finite + numeric}
  V -->|yes| Cache[Cache + return]
  V -->|no| E[Empty envelope]
  E -->|UI shows "no recent scan"| Done
  Cache --> Done
```

There is **no synthesis tier** — wingman-api carries no anchors, no hardcoded levels, no httpx shortcuts. Every number on screen came from the agent which sourced it from real tools (EIA, Yahoo, Baltic, Argus, options) plus the deployed sklearn fair-value model.

If the agent fails, the UI shows "No recent scan — open Price at Risk Lens to score." This is by design per [`feedback_no_fallback_synthesis`](../../). A closed/negative arb (e.g. -$95/MT USGC-NWE today) is a real market signal — the validator accepts any finite float, not just positives.

---

## Operations notes

- **Freight refresh** — `freight_baltic_blpg` curated mids live in [`apps/agent-runtime/engine/tools/freight_baltic_blpg.py`](../../apps/agent-runtime/engine/tools/freight_baltic_blpg.py) under `_BLPG_CURATED_DEFAULTS`. Refresh monthly from OPEC MOMR + Clarksons. Operator override via `BLPG_CURATED_PATH` JSON file.
- **Live Baltic** — set `BALTIC_API_URL` + `BALTIC_API_KEY` env vars on the agent-runtime pods to flip to a live subscription feed.
- **EIA** — `EIA_API_KEY` env (free signup). Tool: `eia_open_data`.
- **Tavily** — `TAVILY_API_KEY` env (paid. news search for drivers).
- **AIS** — `AISSTREAM_API_KEY` env (free tier ok for demo).
- **Model retrain** — quarterly. Regenerate with `python wingman/ml-models/build_mispricing_fairvalue.py`. commit + redeploy. Seed picks up the new version and deactivates the prior.

---

## Common debug paths

- "Scan returned obs=null fv=null" → agent failed sanity. Open `/executions/{id}` from /admin or the trace link. Look at the LLM response — usually a JSON parse failure or a tool returned nothing.
- "Freight is way too low" → check the curated values in `freight_baltic_blpg.py` are current. Live feed via env vars beats curation.
- "Cards show stale data" → `kubectl exec deploy/wingman-api -- rm -rf /data/wingman-cache/mispricing` then re-open the page.
- "Wrong sign on the arb" → the fair-value model might be pre-Hormuz. Re-train with current regime examples.

---

## See also

- [00-pattern](00-pattern.md) — the generic thin-app shape
- [02-runtime/02-tools](../02-runtime/02-tools.md) — the tools the agents call (eia_open_data, freight_baltic_blpg, options_data, ml_model)
- [08-howto/04-debugging](../08-howto/04-debugging.md) — broader debug techniques
