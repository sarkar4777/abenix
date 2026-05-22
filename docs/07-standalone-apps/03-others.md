# The other verticals — Saudi Tourism, ResolveAI, Industrial-IoT, ClaimsIQ

> Brief overviews. Each follows the [thin-app pattern](00-pattern.md) and the structural notes for Wingman + ContractIQ apply.

---

## Saudi Tourism

**Domain**: tourism analytics + planning for Saudi Vision 2030 (hotel occupancy, visa flows, event impact modelling, regional recommendations).

**Key features**:
- Visitor-flow heatmaps (Riyadh, Jeddah, AlUla, NEOM, Diriyah)
- Event-impact simulator
- Per-region report generator
- Hotel + airline capacity model

**Agents** (`packages/db/seeds/agents/st_*.yaml`):
- `st-analytics` — main analytics agent (multi-tool)
- `st-data-extractor` — pull from open datasets
- `st-report-generator` — PDF report assembly
- `st-simulator` — what-if event modelling
- `st-chat` — concierge-style chat for the home page

**Theme**: green + white. App at `sauditourism/`, ports 3002 (web) / 8002 (api).

---

## ResolveAI

**Domain**: customer-support automation. Triage tickets, route to right team, suggest replies, escalate to humans via approvals.

**Key features**:
- Inbox of incoming tickets
- Per-ticket classification (urgency, category, customer-tier)
- Suggested reply drafts (using customer's history + knowledge base)
- Auto-resolution for low-risk categories
- Human handoff via approval gates

**Agents** (`packages/db/seeds/agents/resolveai_*.yaml`):
- `resolveai-classifier` — ticket triage
- `resolveai-reply-drafter` — KB-grounded reply
- `resolveai-policy-checker` — pre-send compliance gate
- `resolveai-escalation-router` — choose human

**Compliance**: approval gates on refunds > policy threshold, on outbound to high-value accounts, on PII-containing replies.

App at `resolveai/`, ports 3008 (web) / 8008 (api).

---

## Industrial-IoT

**Domain**: equipment health, alarm desk, predictive maintenance, OPC-UA integration.

**Key features**:
- Live OPC-UA tag dashboards
- Alarm queue with RCA suggestions
- Predictive maintenance (RUL — remaining useful life)
- Cold-chain corrector for refrigerated logistics
- Sensor anomaly detection
- Two-way control via approvals (remote PLC reset)

**Agents** (`packages/db/seeds/agents/industrial-iot_*.yaml`):
- `iiot-alarm-triager` — classifies + routes alarms
- `iiot-rul-estimator` — RUL with confidence band
- `iiot-rca-helper` — fetches sensor history + suggests root cause
- `iiot-cold-chain-corrector` — drift detection on temperature logs
- `iiot-control-gate` — wraps every write tool with approvals

**ML models** (`industrial-iot/aimodels/`):
- `rul-estimator` (GradientBoosting)
- `cold-chain-corrector` (sklearn regressor)
- `pump-dsp-correction` (signal-processing model)
- `wind-turbine-failure-classifier` (random forest)

**Edge-aware**: the cold-chain + RUL agents can run on the edge runtime for low-latency on-device inference.

App at `industrial-iot/`, ports 3009 (web) / 8009 (api).

---

## ClaimsIQ

**Domain**: insurance claims triage + fraud detection.

**Key features**:
- Claims inbox (auto-ingested from upstream system)
- Per-claim risk score + fraud flags
- Document review (medical records, police reports)
- Settlement-amount recommender
- Adjuster handoff with full lineage

**Agents** (`packages/db/seeds/agents/claimsiq_*.yaml`):
- `claimsiq-intake` — pipeline that orchestrates the others
- `claimsiq-fraud-detector` — multi-signal fraud score
- `claimsiq-doc-extractor` — OCR + structured extraction from claim docs
- `claimsiq-settlement-recommender` — settlement amount + confidence
- `claimsiq-adjuster-handoff` — package + escalate

App at `claimsiq/`, ports 3010 (web) / 8010 (api).

---

## Picking apart any of them

All follow the structure in [00-pattern](00-pattern.md). The fastest way to learn one:

1. Open `<app>/api/main.py` — every endpoint maps to a page action.
2. Read the agent yamls in `packages/db/seeds/agents/<app>_*.yaml`.
3. Open the page that interests you in `<app>/web/src/app/`.
4. Trace one request from the page → vertical api → SDK → platform agent → tools.

Each end-to-end trace takes ~15 minutes. Once you've done it for one app you can pick any other up in under an hour.

---

## See also

- [00-pattern](00-pattern.md) — the contract
- [01-wingman](01-wingman.md) — most-evolved example
- [02-contractiq](02-contractiq.md) — heaviest KB + atlas user
