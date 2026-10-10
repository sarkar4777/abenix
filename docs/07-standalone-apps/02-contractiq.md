# E&C-Copilot (ContractIQ) — energy contract intelligence

> Upload energy and metals contracts, extract every term, then price, risk-check and monitor the portfolio. The largest app in the repo: 48 agents, 9 ML models, 2 code assets. Ports 3001 (web) and 8001 (api).

The product name in the UI is **E&C-Copilot** (page title, sidebar, landing page). The code, directory, service names, agent slugs, tables and env vars still use the old name `contractiq`, so both names appear below.

---

## Domain

E&C-Copilot reads long commodity contracts (100-200 page PDFs or text) and turns them into structured, priced positions:
- Power Purchase Agreements (physical, virtual, CfD), gas supply, LNG and tolling agreements.
- Precious-metals contracts (doré intake, investment bars) checked against LBMA, LPPM, OECD and RJC rules.
- Commercial terms, assets, events, clauses and risk factors per contract, each cited back to a contract span.
- Forward curves, fair value, VaR/CVaR, stress tests, counterparty credit and KYC, renewals, force majeure and settlement checks across the portfolio.

Sample contracts live in [`contractiq/test-contracts/`](../../contractiq/test-contracts/).

---

## Layout

```
contractiq/
  api/            FastAPI on :8001. main.py, app/routers/ (one per area), app/models/
                  (contractiq_* tables), app/core/, sdk/ (vendored abenix_sdk)
  web/            Next.js on :3001. Pages under src/app/, nav in src/app/_sidebar_layout.tsx
  aimodels/       9 sklearn pkls + meta.json + build_*.py
  code-assets/    contractiq-risk-quant
  runtime/        post_processors/ loaded into the platform agent runtime
                  via POST_PROCESSOR_MODULES=contractiq.runtime.post_processors
  test-contracts/ sample PPAs, gas, LNG, tolling and metals contracts
  e2e/            app-local Playwright specs
  k8s/            contractiq.yaml (contractiq-api ClusterIP, contractiq-web NodePort 30301)
  start.sh        local dev launcher
```

The app shares the platform Postgres but owns only its `contractiq_*` tables, including its own `contractiq_users`. Users sign in to E&C-Copilot, not to Abenix.

---

## Pages

Grouped as in the sidebar.

| Group | Routes |
|---|---|
| Home | `/dashboard` |
| Trading & Forecasting | `/data-fabric`, `/forecaster` (offtake), `/workbench`, `/model-performance`, `/recommendations`, `/price-engine` |
| Commodities | `/commodities/forward?commodity=pipeline_gas`, `power`, `lng`, `carbon`, and `/metals` with `extract`, `compliance`, `disputes`, `loco`, `sourcing`, `refiners` |
| Contracts | `/contracts`, `/contracts/{id}`, `/upload`, `/clauses`, `/deal-clusters`, `/timeline`, `/compare` |
| Risk & Valuation | `/credit-risk`, `/credit-risk/kyc`, `/risk` (VaR/CVaR), `/valuation`, `/simulations`, `/insights/stress-test`, `/market` |
| Insights | `/insights` with `briefing`, `renewals`, `force-majeure`, `reconciliation`, `families`, `anomalies`, `version-diff`, `stress-test`, `hedge`, `benchmark` |
| Help | `/chat`, `/features`, `/help` |
| Admin | `/admin/rbac`, `/admin/market-sources`, `/admin/audit` |

`/` is the public landing page.

---

## Agents

48 seeds in `packages/db/seeds/agents/`, named `contractiq_*.yaml` and `ciq_*.yaml`. The main ones by area:

| Area | Slugs | Called from |
|---|---|---|
| Extraction | `contractiq-extractor`, `contractiq-deep-extractor`, `contractiq-functional-analysis` | `routers/contracts.py`, `routers/analysis.py` |
| Multi-pass pipeline | `contractiq-pipeline` (10 extractor nodes into one synthesis) | seeded and shown in `/help` and `/features` |
| Chat | `contractiq-chat` on a platform conversation thread with `app_slug="contractiq"` | `routers/analysis.py` |
| Insights | `contractiq-executive-briefing`, `-renewal-copilot`, `-force-majeure-monitor`, `-settlement-reconciler`, `-clause-anomaly`, `-version-diff`, `-stress-test`, `-hedge-advisor`, `-clause-benchmarker`, `-portfolio-valuator`, `-price-forecaster`, `-market-monitor`, `-top-monitor`, `-kyc-pdf-intake` | `routers/insights.py` |
| Risk | `contractiq-risk-calculator`, `-marginal-var-analyzer`, `-correlations` | `routers/risk.py` |
| Commodity fair value | `contractiq_power_fairvalue`, `_pipeline_gas_fairvalue`, `_lng_fairvalue`, `_crude_fairvalue`, `_refined_fairvalue`, `_coal_fairvalue`, `_carbon_fairvalue`, plus `_lng_thesis` and `_pipeline_gas_thesis` | `routers/commodities.py` |
| Metals | `contractiq-metals-extractor`, `-compliance-auditor`, `-dispute-scorer`, `-loco-analyzer`, `-sourcing-tracker`, `-refiner-watch` | `routers/metals.py` |
| Counterparty | `ciq-counterparty-refresher`, `ciq-financial-extractor`, `ciq-rating-fetcher`, `ciq-permit-checker` | `routers/quickwin.py` |
| Forecast + recommend | `ciq-offtake-forecaster`, `ciq-price-engine`, `ciq-recommendation-engine` | `routers/executions.py` |
| Other | `contractiq-whatif-analyzer`, `contractiq-endur-template-filler`, `contractiq-market-exposure`, `contractiq-market-simulator` | `whatif.py`, `templates.py`, `analysis.py` |

Note the mixed separators. The fair-value slugs use underscores. Copy slugs from the seed files, not from memory.

---

## ML models and code assets

`contractiq/aimodels/`, registered by `seed_ml_models.py`:

| Model | Purpose |
|---|---|
| `contractiq-clause-classifier` | Clause type, about 30 ETRM clause types |
| `contractiq-counterparty-default` | Logistic-regression probability of default from financial ratios |
| `contractiq-risk-tier-predictor` | Calibrated gradient boosting risk tier from 10 structural features |
| `contractiq-price-anomaly` | IsolationForest over contract prices |
| `price_fairvalue_power_hubs`, `price_fairvalue_gas_hubs` | Hub fair-value curves, each with an anomaly companion pkl |
| `offtake_industrial`, `offtake_residential`, `offtake_storage_cycling` | Offtake forecasts by customer profile |

Code asset in `contractiq/code-assets/`: `contractiq-risk-quant` (VaR and risk maths). The `/workbench` page explains predictions of the models above with the SDK call `ml_models.explain`, which runs in Abenix. See [Explanations](../02-runtime/12-ml-models.md#explanations).

---

## Knowledge and graph

- Uploaded contracts go into a per-subject knowledge collection (`forge.knowledge.ensure_subject_collection`). `/api/contractiq/cognify` builds the knowledge graph over them and `/api/contractiq/cognify-status` reports its size.
- The chat agent answers with `knowledge_search` over that collection.
- The six metals agents search the `contractiq-metals-standards` collection seeded from [`packages/db/seeds/kb/contractiq-metals-standards.yaml`](../../packages/db/seeds/kb/contractiq-metals-standards.yaml). It is a compliance team's crib on each standard, not the standard text.
- Market-data feeds are tool presets on the platform (`/admin/tool-presets`), read through the SDK. E&C-Copilot holds no third-party API keys.

---

## actAs and moderation

Each request builds `ActingSubject(subject_type="contractiq", subject_id=<user id>, email, display_name)` and passes it to the SDK, which sends it as the `X-Abenix-Subject` header. The platform audit log records every extraction, valuation and benchmark run against the E&C-Copilot user. The API key is `CONTRACTIQ_ABENIX_API_KEY` with the `can_delegate` scope.

Prompts built from contract text go through `vet_or_block` in `routers/moderation.py`, which runs the platform moderation gate before the text leaves the app.

---

## Where to look

- App: [`contractiq/`](../../contractiq/)
- Agent yamls: [`packages/db/seeds/agents/`](../../packages/db/seeds/agents/) (`contractiq_*.yaml`, `ciq_*.yaml`)
- ML models: [`contractiq/aimodels/`](../../contractiq/aimodels/)
- Sample contracts: [`contractiq/test-contracts/`](../../contractiq/test-contracts/)
- E2E: `e2e/uat_contractiq_*.spec.ts` in [`e2e/`](../../e2e/), plus [`contractiq/e2e/`](../../contractiq/e2e/)

---

## See also

- [00-pattern](00-pattern.md) — the thin-app contract
- [04-data-model/03-knowledge](../04-data-model/03-knowledge.md) — KB schema
- [02-runtime/12-ml-models](../02-runtime/12-ml-models.md) — how the pkls are served
