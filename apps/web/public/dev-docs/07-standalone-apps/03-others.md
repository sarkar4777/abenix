# The other verticals — Mideast Tourism, ResolveAI, Industrial-IoT, ClaimsIQ

> Brief overviews. Each follows the [thin-app pattern](00-pattern.md), and the structural notes for Wingman and E&C-Copilot apply. PharmaVigil has its own page, [05-pharmavigil](05-pharmavigil.md).

| App | Directory | Stack | Local ports | In-cluster services |
|---|---|---|---|---|
| Mideast Tourism | `mideasttourism/` | Next.js + FastAPI | 3002 web, 8002 api | `mideasttourism-web:3002`, `mideasttourism-api:8002` |
| Industrial-IoT | `industrial-iot/` | Next.js + FastAPI | 3003 web, 8003 api | `industrial-iot-web:3003`, `industrial-iot-api:8003` |
| ResolveAI | `resolveai/` | Next.js + FastAPI | 3004 web, 8004 api | `resolveai-web:3004`, `resolveai-api:8004` |
| ClaimsIQ | `claimsiq/` | Spring Boot + Vaadin, one process | 3005 | `claimsiq:3005` |

Each app has a `start.sh` for local dev and a `k8s/<app>.yaml` for the cluster. The web services are NodePort (30302, 30303, 30304, 30305) and the APIs are ClusterIP.

---

## Mideast Tourism

**Domain**: tourism analytics and planning for a regional ministry of tourism, built around a Gulf "Tourism Strategy 2030" (visitor arrivals, hotel occupancy, revenue by sector, satisfaction, event impact).

**Pages** (`mideasttourism/web/src/app/`): `/dashboard`, `/upload` (CSV and text datasets), `/regional`, `/analytics`, `/simulations`, `/chat`, `/reports`.

**Data**: [`mideasttourism/test-data/`](../../mideasttourism/test-data/) has 2024 arrivals, occupancy, revenue and satisfaction CSVs plus two strategy documents. Regions in the sample data: Dubai, Abu Dhabi, Sharjah, Northern Emirates, Doha, Lusail, Muscat, Nizwa, Salalah.

**Agents** (`packages/db/seeds/agents/st_*.yaml`):
- `st-analytics` — main analytics agent (multi-tool), behind `/analytics` and `/regional`
- `st-data-extractor` — parses uploaded datasets
- `st-report-generator` — report assembly
- `st-simulator` — what-if event modelling
- `st-chat` — chat over the data and the strategy documents

**KB**: `mideasttourism-knowledge` ([`packages/db/seeds/kb/mideasttourism-knowledge.yaml`](../../packages/db/seeds/kb/mideasttourism-knowledge.yaml)) holds the strategy documents `st-chat` searches.

**Theme**: green + white. Key: `MIDEASTTOURISM_ABENIX_API_KEY`. Subject type: `mideasttourism`.

---

## ResolveAI

**Domain**: customer-service resolution. Triage tickets, cite the policy used, plan the resolution, gate risky actions on a human, predict CSAT, and mine tomorrow's problems from today's cases.

**Pages** (`resolveai/web/src/app/`): `/` dashboard, `/cases` and `/cases/{id}`, `/live-console`, `/qa`, `/sla`, `/trends`, `/admin`, `/help`.

**Pipelines** (what the API calls):
- `resolveai-inbound-resolution` — triage → policy research → customer context → resolution plan → `human_approval` gate when the plan needs it → `moderation_vet` on the reply. Run on `POST /api/resolveai/cases`.
- `resolveai-post-qa` — QA review of a closed case
- `resolveai-sla-sweep` — sweep open cases for SLA breaches
- `resolveai-trend-mining` — cluster recent cases into trends

**Agents**: `resolveai-triage`, `-policy-research`, `-resolution-planner`, `-customer-context`, `-tone`, `-deflection`, `-action-executor`, `-qa-reviewer`, `-trend-miner`, `-live-copilot`.

Seeds: the source is [`resolveai/seeds/agents/`](../../resolveai/seeds/agents/). The platform loads the copies in `packages/db/seeds/agents/` (`01_triage_agent.yaml` … `10_live_copilot.yaml`, `96_` … `99_*_pipeline.yaml`). Keep the two in step.

**Approvals**: the resolution plan carries per-action `requires_approval` and an approval tier. Refund limits are set in the pipeline (auto up to $25, tier 1 up to $250, manager up to $5000). The action executor refuses an approval-required action without an approval token. Pending approvals show at `/api/resolveai/admin/pending-approvals`.

**KB**: `resolveai-policy` ([`packages/db/seeds/kb/resolveai-policy.yaml`](../../packages/db/seeds/kb/resolveai-policy.yaml)) plus the ontology in `resolveai/seeds/kb/ontology.yaml`.

Key: `RESOLVEAI_ABENIX_API_KEY`. Subject type: `resolveai`.

---

## Industrial-IoT

**Domain**: five industrial use cases on one page, each a platform pipeline with a live DAG view, plus edge deployment.

**UI**: one page with tabs (`industrial-iot/web/src/app/tabs/`):

| Tab | Pipeline | What it does |
|---|---|---|
| Pump Vibration | `iot-pump-pipeline` | FFT features → DSP analysis → diagnosis → remaining useful life → maintenance plan |
| Cold Chain | `iot-coldchain-pipeline` | Reconstruct a reefer temperature profile, adjudicate excursions, release / dispose / claim |
| Design Studio | `iot-valueedge-pipeline` | Offshore-wind site brief → 3 design scenarios → CapEx, CO2, IRR, LCOE → value engineering → compliance RFIs |
| Field Guide | `iot-fieldedge-pipeline` | Technician symptom → fleet history search → manual-grounded repair procedure |
| Alarm Desk | `iot-bedrocc-pipeline` | SCADA alarm classify → cascade noise filter → safe-reset advice behind an approval gate |
| Architecture | — | How the pieces fit |

**Agents**: 29 seeds in `packages/db/seeds/agents/iot_*.yaml`, 24 agents plus the 5 pipelines above. Slugs follow `iot-<usecase>-<role>`, for example `iot-pump-dsp-analyzer`, `iot-excursion-adjudicator`, `iot-bedrocc-safe-reset-advisor`.

**Code assets** (`industrial-iot/code-assets/`): `pump-dsp-correction` (Go), `cold-chain-corrector` (Go), `rul-estimator` (Python).

**ML model** (`industrial-iot/aimodels/`): `wind-turbine-failure-classifier`, registered by `seed_ml_models.py`. No agent seed calls it yet.

**KB**: `industrial-iot-knowledge` ([`packages/db/seeds/kb/industrial-iot-knowledge.yaml`](../../packages/db/seeds/kb/industrial-iot-knowledge.yaml)).

**Edge**: `POST /api/industrial-iot/edge/compile-and-deploy` compiles an agent bundle and deploys it to a registered edge gateway, and `POST /api/industrial-iot/edge/execute` runs a payload on it. The Pump tab uses this.

**Platform passthrough**: the API forwards `/api/code-assets`, `/api/agents` and `/api/connectors` to the platform with its own key so the browser never holds an Abenix credential. `/api/approvals` is deliberately not forwarded.

Key: `INDUSTRIALIOT_ABENIX_API_KEY`. Subject type: `industrial-iot`, subject id from `X-Forwarded-User`.

---

## ClaimsIQ

**Domain**: insurance first notice of loss (FNOL) through to a claim decision, with an adjuster review queue.

**Stack**: Java 21, Spring Boot 3 and Vaadin 24 in one process. It calls the platform through the Java SDK in [`claimsiq/sdk/`](../../claimsiq/sdk/), a Gradle subproject. See [03-sdk/03-java](../03-sdk/03-java.md).

**Views** (`claimsiq/app/src/main/java/com/abenix/claimsiq/ui/`): `/` dashboard, `/fnol`, `/claims`, `/claims/{id}`, `/review` (adjuster queue), `/review/{id}`, `/help`. The claim page shows the pipeline's live DAG.

**Pipeline** `claimsiq-adjudicate`: FNOL intake → policy match → damage assessment (multimodal, reads photos) → fraud screen → valuation → decision.

**Agents**: `claimsiq-fnol-intake`, `-policy-matcher`, `-damage-assessor`, `-fraud-screener`, `-valuator`, `-claim-decider`.

Seeds: source in [`claimsiq/seeds/agents/`](../../claimsiq/seeds/agents/). The platform loads the copies `packages/db/seeds/agents/cq_*.yaml`.

**KB**: `claimsiq-policies` ([`packages/db/seeds/kb/claimsiq-policies.yaml`](../../packages/db/seeds/kb/claimsiq-policies.yaml)).

Key: `CLAIMSIQ_ABENIX_API_KEY`. Subject type: `claimsiq`, with the claim id as subject id. Health: `/actuator/health/liveness`.

---

## Picking apart any of them

The fastest way to learn one:

1. Open the API entry point. `<app>/api/main.py` for the Python apps (larger ones split into `<app>/api/app/routers/`), `ClaimsService.java` for ClaimsIQ.
2. Read the agent and pipeline yamls it calls.
3. Open the page that interests you in `<app>/web/src/app/`.
4. Trace one request from the page → app API → SDK → platform agent → tools.

Once you have done this for one app, the others follow the same shape.

---

## See also

- [00-pattern](00-pattern.md) — the contract
- [01-wingman](01-wingman.md) — most evolved example
- [02-contractiq](02-contractiq.md) — E&C-Copilot, the largest app
- [05-pharmavigil](05-pharmavigil.md) — pipeline, code assets and one ML model
