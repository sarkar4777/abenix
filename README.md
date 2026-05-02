<p align="center">
  <img src="apps/web/public/logo.svg" alt="Abenix" width="100" height="100" />
</p>

<h1 align="center">Abenix</h1>

<h3 align="center">The open-source AI agent platform that thinks in graphs, not chunks.</h3>

<p align="center">
  <a href="#-quick-start"><strong>Quick start</strong></a> &nbsp;·&nbsp;
  <a href="#-what-makes-abenix-different"><strong>Why Abenix</strong></a> &nbsp;·&nbsp;
  <a href="#-showcase-apps"><strong>Showcase apps</strong></a> &nbsp;·&nbsp;
  <a href="#%EF%B8%8F-architecture"><strong>Architecture</strong></a> &nbsp;·&nbsp;
  <a href="#-deploy-anywhere"><strong>Deploy</strong></a> &nbsp;·&nbsp;
  <a href="#-contributing"><strong>Contribute</strong></a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-violet.svg" alt="MIT License" /></a>
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/node-20+-green.svg" alt="Node 20+" />
  <img src="https://img.shields.io/badge/postgres-16-blue.svg" alt="Postgres 16" />
  <img src="https://img.shields.io/badge/kubernetes-ready-326CE5.svg" alt="Kubernetes Ready" />
</p>

---

## TL;DR

Most AI agent platforms give your agents amnesia — they retrieve documents, forget context, and re-derive the world model on every turn.

**Abenix gives them a brain.** A typed graph that lives next to your knowledge base, agents that traverse it like a researcher follows citations, and a canvas where humans and agents shape it together.

<p align="center">
  <img src="docs/screenshots/01-dashboard.png" alt="Abenix Dashboard" width="100%" />
  <br/><em>The Abenix Dashboard — agents, executions, cost, and observability in one place</em>
</p>

> **Mostly Enterprise-ready.** Multi-tenant by design with hard SQL-level isolation. RBAC + per-resource sharing + actAs delegation for SaaS multiplexing. SHA-256-hashed API keys with per-key scopes + revocation. Pre-/post-LLM moderation with DLP redaction. Per-tenant + per-user budget caps. GDPR-friendly retention with hard purge. SOC 2 telemetry stack pre-wired (Prometheus + Grafana + structured failure codes + Slack/email fan-out). Helm chart deploys to AKS + minikube today; the same chart runs on EKS / GKE with a values override.

---

## ⚡ Quick start

Pick the path that matches what you want to do:

| Goal | Command | Time |
|---|---|---|
| **Localhost in ~60 s** — docker-compose for Postgres / Redis / Neo4j / NATS, then npm dev for api + web + 5 standalone apps | `bash scripts/dev-local.sh` | ~5 min first run |
| **Production-shape on your laptop** — full Helm chart on a local minikube cluster | `bash scripts/deploy.sh local` | ~10 min |
| **Minikube fast-demo** — auto-starts minikube and forwards every service to localhost | `bash scripts/dev-minikube.sh` | ~10 min |
| **AKS (Azure)** — provisions RG + ACR + AKS, builds + pushes images, helm-installs the stack, runs migrations + seeds + standalone-key reconcile | `bash scripts/deploy-azure.sh deploy` | ~25 min |
| **AKS port-forwards** — bring an already-deployed AKS cluster to `localhost:*` (firewall-safe) | `bash scripts/portforward-azure.sh` | <30 s |

```bash
git clone https://github.com/sarkar4777/abenix.git
cd abenix
cp .env.example .env       # local-dev defaults; fill in LLM keys
bash scripts/dev-local.sh
```

Open http://localhost:3000 and sign in.

### Required vs optional env vars

| Variable | Required? | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | one of three | Default agent model (Claude). Recommended. |
| `OPENAI_API_KEY` | one of three | OpenAI models + omni-moderation gate |
| `GOOGLE_API_KEY` (a.k.a. `GEMINI_API_KEY`) | one of three | Vision-on-PDF, audio/video, fallback |
| `TAVILY_API_KEY` | optional | `web_search` tool (set `SEARCH_PROVIDER=tavily`) |
| `BRAVE_SEARCH_API_KEY` / `SERPAPI_API_KEY` / `SERPER_API_KEY` | optional | Alternate search providers |
| `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | optional | S3 storage backend (`STORAGE_BACKEND=s3`) |
| `STORAGE_AZURE_CONNECTION_STRING` | optional | Azure Blob storage (`STORAGE_BACKEND=azure`) |
| `PINECONE_API_KEY` | optional | Hosted vector store (default is local pgvector) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | optional | `email_sender` agent tool + alert fan-out |
| `NEO4J_PASSWORD`, `NEO4J_URI` | only when overriding | Knowledge graph (default = embedded local) |

The full list lives in [`.env.example`](.env.example) — Postgres / Redis / Neo4j / NATS strings, CORS origins, all LLM provider keys, Stripe (optional), object storage, search providers, tool-specific keys (FRED, Alpha Vantage, ENTSO-E, EIA, NewsAPI, Mediastack), and the `SMTP_*` block. For Kubernetes deploys, set the same keys in [`infra/helm/abenix/values-*.yaml`](infra/helm/abenix/) under `secrets:` and `configMap:`.

### Demo credentials (one place — used everywhere)

| App | URL (local dev) | Credential |
|---|---|---|
| Abenix core | http://localhost:3000 | `admin@abenix.dev` / `Admin123456` |
| Saudi Tourism | http://localhost:3002 | `test@sauditourism.gov.sa` / `TestPass123!` |
| Industrial-IoT | http://localhost:3003 | uses platform login |
| ResolveAI | http://localhost:3004 | `agent@resolveai.local` / `agent123` |
| ClaimsIQ | http://localhost:3005 | uses platform login |
| the example app | http://localhost:3001 | `test@example_app.com` / `TestPass123!` |

Same accounts work on the AKS UAT cluster (`admin@abenix.dev` / `Admin123456`).

### Run the UAT probes

Every showcase app has a Playwright probe that drives the real UI, captures screenshots into `logs/uat/apps/<app>-screens/`, and writes a markdown report.

```bash
npx tsx scripts/uat-oraclenet-ui.ts        # 7-agent Decision Brief flow
npx tsx scripts/uat-sauditourism-ui.ts     # KPIs, NLQ chat, 5 reports, simulator
npx tsx scripts/uat-claimsiq-ui.ts         # FNOL → 6-stage adjudicate
npx tsx scripts/uat-industrial-iot-ui.ts   # pump + cold-chain code-asset deploys
npx tsx scripts/uat-resolveai-ui.ts        # 4 pipelines + SLA sweep + trends
npx tsx scripts/uat-example_app-ui.ts       # extraction + valuation + benchmark
```

For the all-in deploy gate (111 tests, sanity + deep + industrial), run `bash scripts/uat.sh`.

---

## 🥊 How is this different from n8n / Zapier / LangChain?

Short answer: **n8n is an advanced workflow tool with agents in the mix that learned to call an LLM. Abenix is a platform whose smallest unit is an agent.** The runtime, the knowledge model, the failure model, and the deployment shape are all sized for that.

n8n / Zapier / LangChain are excellent for *"when a Salesforce row changes, drop a Slack message and update HubSpot."* Use them when the problem is integration-shaped.

**Abenix earns its place when the problem is agent-shaped** — long-running reasoning, shared knowledge, real tenant isolation, audit-grade traceability, and a runtime you actually run inside your own cluster.

1. **The unit of deployment is an agent, not a workflow.** Every agent has its own pod pool, KEDA scaler, queue, budget cap, and telemetry channel. See [`infra/helm/abenix/templates/agent-runtime-pools.yaml`](infra/helm/abenix/templates/agent-runtime-pools.yaml) and the admin UI under `/admin/scaling`.
2. **Knowledge is graph + KB merged.** [Atlas](apps/web/src/app/(app)/atlas/page.tsx) is one ontology canvas; agents have four typed tools (`atlas_describe`, `atlas_query`, `atlas_traverse`, `atlas_search_grounded`) and answer multi-hop questions by graph traversal — not vector lottery. Postgres + Neo4j, no extra vector DB to operate.
3. **Multi-tenancy is real.** `tenant_id` on every row, [`ResourceShare`](packages/db/models/resource_share.py) for cross-tenant grants, [`actAs` delegation](packages/db/models/subject_policy.py) for SaaS multiplexing. The five showcase apps below all ride this exact path.
4. **Failures are first-class.** Structured failure-diff on every node crash → [Pipeline Surgeon](apps/api/app/routers/pipeline_healing.py) proposes a JSON-Patch (RFC 6902) you can review and apply from `/agents/{id}/healing`. Stable `failure_code` badges on `/executions`. A typed [workflow shell REPL](apps/web/src/app/(app)/agents/[id]/shell/page.tsx) — *"kubectl for pipelines"* — drives the same machinery.
5. **One Helm chart with observability inside.** [`infra/helm/abenix`](infra/helm/abenix/) deploys api + web + workers + per-agent-pool runtimes + Postgres + Redis + Neo4j + NATS + KEDA + Prometheus + Grafana + ingress. Every pod exposes `/metrics`. The [`/alerts`](apps/web/src/app/(app)/alerts/page.tsx) page groups by `failure_code`. Slack + email fan-out via env var.

**TL;DR:** if the problem is *"chain these APIs together with an LLM step,"* use n8n. If it's *"agents that share knowledge, scale per-pool, isolate by tenant, and ship as a self-hostable platform,"* try this.

---

## 🎯 Showcase apps

Five reference apps ship in this repo — each on top of Abenix via the same SDK + actAs pattern. All five auto-start with `bash scripts/dev-local.sh` and auto-deploy with `bash scripts/deploy-azure.sh deploy`.

| App | Lives at | Runs at (local) | Demo creds |
|---|---|---|---|
| [OracleNet](#1-oraclenet--decision-analysis) | `/oraclenet` inside Abenix web | `:3000/oraclenet` | platform login |
| [Saudi Tourism](#2-saudi-tourism--ksa-vision-2030-analytics) | `sauditourism/` | API `:8002` · Web `:3002` | `test@sauditourism.gov.sa` / `TestPass123!` |
| [ClaimsIQ](#3-claimsiq--insurance-claim-adjudication-java) | `claimsiq/` | `:3005` (one process) | platform login |
| [Industrial-IoT](#4-industrial-iot--predictive-maintenance--cold-chain) | `industrial-iot/` | API `:8003` · Web `:3003` | platform login |
| [ResolveAI](#5-resolveai--customer-resolution-case-management) | `resolveai/` | API `:8004` · Web `:3004` | `agent@resolveai.local` / `agent123` |

---

### 1. OracleNet — decision-analysis

**What it is.** An inline tool inside the main Abenix web app at [`/oraclenet`](apps/web/src/app/oraclenet/page.tsx). You type a strategic decision in plain English, OracleNet runs a 7-agent pipeline against it, and you get back a **Decision Brief** with 6 tabs (Summary · Stakeholders · Scenarios · Risks · Cascade · Provenance) plus a recommendation card and a confidence score.

**Business problem solved.** Big decisions usually fail because nobody seriously simulated who would oppose them, what the second-order effects were, and what an honest contrarian would say. OracleNet bakes those three voices into every brief.

**Pipeline.**

```mermaid
flowchart LR
    Q[Decision query] --> DP[Decision Parser]
    DP --> H[Historian]
    DP --> CS[Current State]
    DP --> SS[Stakeholder Sim]
    H --> SO[Second-Order]
    CS --> SO
    SS --> SO
    H --> CN[Contrarian]
    CS --> CN
    SS --> CN
    SO --> SY[Synthesizer]
    CN --> SY
    SY --> BRIEF[6-tab Decision Brief]

    classDef agent fill:#a855f7,stroke:#c084fc,color:#fff;
    classDef out fill:#10b981,stroke:#34d399,color:#fff;
    class DP,H,CS,SS,SO,CN,SY agent;
    class BRIEF out;
```

**Depth tri-state.** A `depth_router` Python node reads `context.depth` and prunes the DAG:

| Depth | Agents | What runs |
|---|---|---|
| `quick` | 3 | Decision Parser → Current State → Synthesizer |
| `standard` | 5 | + Historian + Stakeholder Sim |
| `deep` | 7 | + Second-Order + Contrarian |

Pruned agents are marked `status="skipped"`; downstream synthesizer template variables resolve to `[not available]` so the prompt stays valid.

**Tools + KB.** `web_search` (Tavily / Brave / SerpAPI), `kb_search` against the OracleNet collection (seeded by `seed_kb.py`), `atlas_traverse` for stakeholder maps, plus the seven agent seeds in [`packages/db/seeds/agents/oraclenet_*.yaml`](packages/db/seeds/agents/).

**Exports.** `POST /api/oraclenet/export?format=pdf|docx|markdown` returns a streaming download (PDF via reportlab, DOCX via python-docx). The UI exposes JSON / Markdown / PDF / DOCX / Copy buttons.

**Try it now (5 minutes).**

```bash
bash scripts/dev-local.sh                    # platform + 5 standalones
open http://localhost:3000/oraclenet         # already inside Abenix web
# Type: "Should our consumer-fintech startup pivot to B2B underwriting in Q3?"
# Pick depth: standard. Click Analyze.
# When the brief renders, click each of the 6 tabs, then Download PDF.
```

<p align="center">
  <img src="docs/screenshots/usecases/oraclenet-brief.png" alt="OracleNet brief" width="100%" />
  <br/><em>OracleNet Decision Brief — confidence + recommendation card, 6 tabs</em>
</p>

**Cluster.** `bash scripts/deploy-azure.sh deploy` — OracleNet ships inside the main web image, no separate service.

---

### 2. Saudi Tourism — KSA Vision-2030 analytics

**What it is.** A standalone analytics app for the Saudi Ministry of Tourism. Web on `:3002`, API on `:8002`. Ships with a green-and-white theme, an Arabic-friendly font stack, and 7 pages (Dashboard, Regional, Analytics, Chat NLQ, Reports, Simulations, Upload).

**Business problem solved.** Vision-2030 ministries need to track 100M-visitor targets, regional revenue attribution, and seasonal demand against the actual data they already have — without a year-long BI buildout.

**Agents (5).** `sauditourism-data-extractor` (CSV/XLSX → typed tables), `sauditourism-analytics` (KPI computation), `sauditourism-chat` (NLQ), `sauditourism-report-generator` (5 templates: executive, regional, segmentation, revenue, seasonal), `sauditourism-simulator` (5 presets: mega-event, off-peak push, sector mix shift, infra stress, currency shock).

**Tools + KB.** `tabular_query`, `chart_render`, `kb_search` against `sauditourism` collection seeded from [`packages/db/seeds/kb/`](packages/db/seeds/kb/). Test data is **baked into the API image** under `sauditourism/test-data/` — no manual seed required.

**Try it now.**

```bash
bash scripts/dev-local.sh
open http://localhost:3002
# Click "Try it now" on the landing page → auto-creates demo session
# Dashboard renders KPIs from baked test data
# Chat tab: ask "Which region grew the most in Q2?"
# Reports tab: pick "Regional Comparison Report" → PDF in ~30s
# Simulations tab: pick "Mega-event uplift" preset → projection chart
```

<p align="center">
  <img src="docs/screenshots/usecases/sauditourism-dashboard.png" alt="Saudi Tourism dashboard" width="100%" />
  <br/><em>Saudi Tourism dashboard — KPIs computed live from baked test data</em>
</p>

**Cluster.** `scripts/deploy-azure.sh deploy` builds + deploys `sauditourism-api` + `sauditourism-web` images, reconciles `SAUDITOURISM_ABENIX_API_KEY`, and exposes both behind the Abenix ingress under `/sauditourism/*`.

---

### 3. ClaimsIQ — insurance claim adjudication (Java)

**What it is.** A Java/Vaadin claim-adjudication showcase. Spring Boot 3 + Vaadin 24, served on a single port `:3005`. Demonstrates that **the Java SDK is feature-complete** — every adjudication delegates to Abenix via [`Abenix.execute(...)`](claimsiq/sdk/src/main/java/com/abenix/sdk/Abenix.java), and the live DAG view subscribes to `Abenix.watch(...)` over SSE.

**Business problem solved.** Claim shops want explainable adjudication — every decision must cite the policy clause it relied on, every fraud flag must show what triggered it, and every dollar amount must be auditable. Black-box LLM responses are unshippable.

**Pipeline.** 6-stage `claimsiq-adjudicate`:

```mermaid
flowchart LR
    F[FNOL Intake<br/>parse free-text + photos] --> P[Policy Match<br/>cite clauses]
    P --> D[Damage Assess<br/>vision on photos]
    D --> FR[Fraud Screen<br/>red-flag patterns]
    FR --> V[Valuator<br/>$ amount with sources]
    V --> DC[Claim Decider<br/>approve · partial · deny + rationale]

    classDef agent fill:#a855f7,stroke:#c084fc,color:#fff;
    class F,P,D,FR,V,DC agent;
```

**Tools + KB.** `kb_search` against the `claimsiq-policies` collection ([`seeds/kb/claimsiq-policies.yaml`](packages/db/seeds/kb/claimsiq-policies.yaml)) — clauses, exclusions, deductibles. Photos uploaded as base64 are routed to the vision-capable model. Live DAG snapshots stream over SSE so the user watches each stage flip from `pending` → `running` → `complete`.

**Try it now.**

```bash
bash scripts/dev-local.sh                    # auto-builds + starts ClaimsIQ
open http://localhost:3005/fnol
# Fill: "2026 Honda Civic, rear-end at intersection, third-party at fault"
# Upload one of the sample photos in claimsiq/app/src/main/resources/sample-photos/
# Submit → land on /claims/{id} → live DAG renders
# Final card shows: decision + amount + cited policy clauses + fraud score
```

<p align="center">
  <img src="docs/screenshots/usecases/claimsiq-final.png" alt="ClaimsIQ final adjudication" width="100%" />
  <br/><em>Final adjudication — decision, amount, cited clauses, live DAG</em>
</p>

**Cluster.** `scripts/deploy-azure.sh deploy` builds the bootJar, packages it as `claimsiq:latest`, and deploys it as a single-container service under `/claimsiq/*`.

---

### 4. Industrial-IoT — predictive maintenance + cold chain

**What it is.** A standalone showcase for two adjacent industrial domains. Web on `:3003`, API on `:8003`. Two showcase tabs:

- **Pump tab** — deploys two Code Assets (DSP feature extractor + RUL regressor), then streams 10 vibration windows through them; severity classifier triages each window; final output is a work-order draft for any window flagged `high`.
- **Cold Chain tab** — deploys one Code Asset (excursion corrector); streams 20 SFO→LAX waypoints; runs an excursion adjudicator against pharma SOP KB; final output is a partial-loss claim draft.

**Business problem solved.** Two of the highest-frequency industrial use cases (rotating-equipment maintenance, pharma cold-chain excursion handling) need ML inference + LLM reasoning + structured downstream artefacts (work orders, claim drafts) in the same flow. Industrial-IoT shows the Abenix [Code Runner](#code-runner--bring-your-own-repo) primitive carrying the ML weight while agents handle reasoning.

**Pipeline (Pump).**

```mermaid
flowchart LR
    SEED[10 vibration windows] --> DSP[code_asset:dsp_features]
    DSP --> RUL[code_asset:rul_predictor]
    RUL --> SEV{severity_router}
    SEV -->|low/med| LOG[log only]
    SEV -->|high| WO[work-order drafter]

    classDef code fill:#06b6d4,stroke:#22d3ee,color:#fff;
    classDef agent fill:#a855f7,stroke:#c084fc,color:#fff;
    class DSP,RUL code;
    class WO agent;
```

**Tools + KB.** `code_asset` (Python sandboxed jobs), `kb_search` against `industrial-iot-knowledge` ([`seeds/kb/industrial-iot-knowledge.yaml`](packages/db/seeds/kb/industrial-iot-knowledge.yaml)) — SOPs, FAA AC 120-78, GDP guidelines.

**Try it now.**

```bash
bash scripts/dev-local.sh
open http://localhost:3003
# Pump tab → click "Deploy DSP + RUL" (~20s — code-asset compile + register)
# Click "Stream 10 windows" → DAG animates; final window flagged high
# Cold Chain tab → click "Deploy Corrector"
# Click "Stream SFO→LAX" → 20 waypoints, 1 excursion, claim draft below
```

<p align="center">
  <img src="docs/screenshots/usecases/industrial-iot-pump.png" alt="Industrial-IoT pump tab" width="100%" />
  <br/><em>Industrial-IoT — pump tab after both code assets deployed</em>
</p>

**Cluster.** `scripts/deploy-azure.sh deploy` builds + deploys both images and seeds the KB.

---

### 5. ResolveAI — customer-resolution case management

**What it is.** A standalone customer-service ops surface. Web on `:3004`, API on `:8004`. Four pipelines run on the same case data:

| Pipeline | Trigger | Agents in order |
|---|---|---|
| **Inbound Resolution** | new case | Triage → Policy Research → Resolution Planner → Deflection Scorer → Tone → Action Executor |
| **SLA Sweep** | cron / button | scans open cases, escalates breaches |
| **Post-QA** | on case close | scores agent performance, drafts coaching note |
| **Trend Mining** | weekly / button | clusters resolved cases, surfaces emerging issues |

**Business problem solved.** Customer-service teams drown in repetitive triage; their highest-leverage moves (deflection, tone calibration, trend detection) get neglected because nobody has time. ResolveAI runs all four loops continuously while a human stays in approve / takeover mode.

**Tools + KB.** `kb_search` over `resolveai-policy` ([`seeds/kb/resolveai-policy.yaml`](packages/db/seeds/kb/resolveai-policy.yaml)) — refund tiers, escalation paths, tone guidelines. Persona + precedent collections are seeded on first deploy. Action Executor uses `webhook` and `email_sender` tools (latter requires `SMTP_*` env).

**Try it now.**

```bash
bash scripts/dev-local.sh
open http://localhost:3004
# Login as agent@resolveai.local / agent123
# Cases tab → "Try It Now" → 4 sample cases run inbound-resolution end-to-end
# Click any case → see the 6-step DAG with cited policy clauses
# SLA tab → "Run Sweep" → breaches escalate
# QA tab → "Run Post-QA" on a closed case → coaching note
# Trends tab → "Mine Trends" → cluster summary
```

<p align="center">
  <img src="docs/screenshots/usecases/resolveai-case.png" alt="ResolveAI case detail" width="100%" />
  <br/><em>ResolveAI — case detail with inbound-resolution DAG and cited policy</em>
</p>

**Cluster.** `scripts/deploy-azure.sh deploy` builds + deploys both images and seeds policy + persona + precedent collections.

---

### Other apps in the repo

[`example_app/`](example_app/) is a contract-intelligence standalone (Wave 1 + Wave 2 — extraction, valuation, benchmarking) that uses the same SDK + actAs pattern. It runs on ports `:8001` / `:3001` and is auto-started by `dev-local.sh` and `deploy-azure.sh`. Demo creds: `test@example_app.com` / `TestPass123!`. See [`example_app/README.md`](example_app/README.md).

---

## 🛠️ Phase A platform improvements

Five hardening landings over the last sprint that every showcase app benefits from:

| Landing | What changed |
|---|---|
| **Standalone API-key bootstrap is automatic** | [`scripts/seed-standalone-keys.sh`](scripts/seed-standalone-keys.sh) reconciles `*_ABENIX_API_KEY` rows in `api_keys` on every deploy. No more `kubectl patch secret` round-trips. Wired into `deploy-azure.sh deploy`, `deploy-azure.sh seed`, and `dev-local.sh`. |
| **SDK drift pre-flight (Phase 0)** | Every deploy + every `dev-local.sh` boot calls [`scripts/sync-sdks.sh --check`](scripts/sync-sdks.sh) — fails fast if any of the 5 vendored copies of `abenix_sdk` drifts from `packages/sdk/python`. `SKIP_SDK_SYNC_CHECK=1` to bypass (not recommended). |
| **`/api/agents/{slug}/self-check` endpoint** | Validates an agent's seed YAML, model availability, tool grants, and KB bindings without running it. Used by the deploy gate. Schema enforced by [`packages/db/seeds/agent_seed_schema.py`](packages/db/seeds/agent_seed_schema.py); lint by [`scripts/lint-agent-seeds.py`](scripts/lint-agent-seeds.py). |
| **`seed_kb.py` populates 6 KB collections on every deploy** | [`packages/db/seeds/seed_kb.py`](packages/db/seeds/seed_kb.py) reads everything in [`packages/db/seeds/kb/`](packages/db/seeds/kb/) (claimsiq-policies, industrial-iot-knowledge, resolveai-policy, plus oraclenet, sauditourism, example_app collections) and idempotently upserts them. |
| **Tools return structured warnings instead of silent empties** | Every tool now returns `{output, warnings: [...]}`; the runtime surfaces warnings into the execution trace. The `wait=True` server-side default for X-API-Key callers + the SDK's `Abenix.execute()` wait-for-completion default kill the silent-empty-output failure mode end-to-end. |

---

## ✨ What makes Abenix different

### Atlas — unified ontology + KB canvas

<p align="center">
  <img src="docs/screenshots/04-atlas-canvas.png" alt="Atlas canvas" width="100%" />
</p>

Other ontology tools (Protégé, Stardog, Neo4j Bloom) treat the schema and the documents as separate artefacts. Atlas collapses them: **one canvas, documents are nodes, concepts are nodes, edges are first-class.** Drop a document → multimodal extraction proposes nodes + edges with confidence scores. Type a sentence → cardinality inference. Time slider → every save snapshots the whole graph. Five starter ontologies ship in the box: FIBO Core, FIX Protocol, EMIR Reporting, ISDA Master Agreement, ETRM EOD.

### Knowledge Engine — graph-aware retrieval

| Question | Vanilla RAG | Abenix |
|---|---|---|
| "What caused the Q3 revenue drop?" | 3 similar paragraphs | `Q3 Report → mentions → supply chain delays → CAUSED_BY → chip shortage` |
| "Counterparties with > 5 unconfirmed trades in 7 days" | Cosine miss | Pattern walk over the typed graph, structured rows back |
| "Why is this contract risky?" | Generic clause text | Path from clause → similar past clauses → flagged outcomes |

Token cost typically drops **5–10×** because agents read curated evidence, not noisy near-neighbours.

### Pipelines + 85+ built-in tools

<p align="center">
  <img src="docs/screenshots/02-agent-builder.png" alt="Agent Builder" width="100%" />
</p>

A pipeline is a DAG of agents and tools. Switch nodes branch on output, loop nodes iterate, code-asset nodes execute sandboxed Python / Node / Go / Rust / Java / Ruby. Every step is logged, metered, and replayable. Tool families: web (search · scrape · structured extract), knowledge (search · ingest · graph-walk), code (execute · file-system), data (Postgres · S3 · CSV · Parquet), comms (Slack · email · webhook), productivity (Linear · Jira · Notion · GitHub), vision + audio, MCP. See the full [tool catalogue](apps/agent-runtime/engine/tools/).

### Multimodal end-to-end + self-healing + workflow shell

- **Multimodal** — drop a PDF, image, audio, video, DOCX, or text file anywhere Abenix accepts uploads; the platform routes the modality to the right provider (Claude/Gemini/GPT-4o for vision, Gemini for audio+video).
- **Self-healing** — node crashes capture a structured failure-diff; the [Pipeline Surgeon](apps/api/app/routers/pipeline_healing.py) proposes a JSON-Patch (RFC 6902) you Apply or Reject from `/agents/{id}/healing`. Never auto-applied; one-click rollback to `dsl_before`.
- **Talk-to-workflow shell** — 30+ verbs across five intents (INSPECT · MUTATE · EXECUTE · GOVERN · LEARN) drive every change through the same JSON-Patch ledger:
  ```bash
  > show failures
  > diff last last-2
  > swap-model extractor gemini-2.5-pro       # → draft patch, awaits approval
  > add-fallback extractor counterparty UNKNOWN
  > simulate fixture:weekend-batch
  ```
- **Per-agent pod scaling** — flip `agents.dedicated_mode = true` and the agent gets its own NATS subject, Deployment, and KEDA ScaledObject. `GET /api/admin/scaling/agents/{id}/cost-projection` shows shared / dedicated / peak before you flip.

---

## 🏗️ Architecture

```mermaid
flowchart TB
    USER[User / SDK] --> NEXT[Next.js web]
    USER --> FAPI[FastAPI]
    NEXT --> FAPI
    FAPI --> AUTH[Auth · RBAC · actAs] --> ROUT[Routers]
    ROUT -.publish.-> NATS[(NATS JetStream)]
    NATS -.consume.-> EXEC[Agent runtime]
    EXEC --> TOOLS[85+ tools] --> SAND[Sandbox]
    EXEC --> LLM[Anthropic · OpenAI · Google · MCP]
    ROUT --> PG[(Postgres 16 + pgvector)]
    ROUT --> REDIS[(Redis)]
    ROUT --> STOR[Object storage]
    EXEC --> PG
    FAPI -.metrics.-> PROM[Prometheus] --> GRAF[Grafana]
    EXEC -.metrics.-> PROM
    PROM --> ALERT[/alerts · Slack · email/]

    style NEXT fill:#06b6d4,stroke:#22d3ee,color:#fff
    style FAPI fill:#a855f7,stroke:#c084fc,color:#fff
    style EXEC fill:#10b981,stroke:#34d399,color:#fff
    style PG fill:#1e3a8a,stroke:#3b82f6,color:#fff
```

Three independently scalable tiers, one shared Postgres. The agent runtime scales horizontally per agent type via KEDA queue-depth scaling. Production traffic flows API → NATS → runtime; the API never executes agent code itself when `RUNTIME_MODE=remote`. Full operator guide (sizing tables, read replicas, pgvector → Pinecone migration, Redis cluster mode, multi-region) lives at `/help` under **Scale & operate**.

---

## 🔌 Build on top of Abenix

Three SDKs ship with the platform:

- **Python** — [`packages/sdk/python`](packages/sdk/python). Used by the example app, Saudi Tourism, Industrial-IoT, and ResolveAI in this repo. `Abenix.execute()` defaults to wait-for-completion via the new server-side tri-state.
- **TypeScript** — [`packages/sdk/js`](packages/sdk/js).
- **Java / JVM** — [`claimsiq/sdk`](claimsiq/sdk). Stdlib-only public surface. JDK 21 `HttpClient` for HTTP + SSE; Jackson is the only runtime dep besides SLF4J. [ClaimsIQ](claimsiq/) is the reference consumer.

```java
// From claimsiq/app/src/main/java/com/abenix/claimsiq/service/ClaimsService.java
try (Abenix forge = Abenix.builder()
        .baseUrl(System.getenv("ABENIX_API_URL"))
        .apiKey(System.getenv("CLAIMSIQ_ABENIX_API_KEY"))
        .actAs(new ActingSubject("claimsiq", userId, email, name))
        .build()) {
    ExecutionResult res = forge.execute("claimsiq-adjudicate",
        Map.of("claim_id", claimId, "claim_type", "auto"));
    System.out.println(res.output());
}
```

The `actAs` pattern lets your app pass the end-user identity through to Abenix so the platform's tenant isolation, RBAC, and audit log all attribute to the right user. Same wire format across all three SDKs (`X-Abenix-Subject` HTTP header).

---

## 📦 Deploy anywhere

### Local development

```bash
bash scripts/dev-local.sh                  # docker-compose + npm dev + 5 standalones
bash scripts/dev-local.sh --stop           # tear it all down
bash scripts/dev-local.sh --status         # health check every service
```

### Minikube — production architecture on your laptop

```bash
bash scripts/dev-minikube.sh               # auto-start minikube + forward every service
bash scripts/deploy.sh local               # full helm install on minikube
bash scripts/deploy.sh local --no-obs      # skip Prometheus + Grafana
```

### Azure AKS

```bash
bash scripts/deploy-azure.sh deploy                         # provision + build + deploy + seed + key-reconcile + smoke
bash scripts/deploy-azure.sh redeploy --only=api,web        # incremental rebuild + roll
bash scripts/deploy-azure.sh seed                           # reseed agents/users/KB + reconcile standalone keys
bash scripts/deploy-azure.sh seed-keys                      # one-shot standalone-key reconciliation
bash scripts/portforward-azure.sh                           # bring AKS services to localhost:*
bash scripts/portforward-azure.sh status                    # health check
bash scripts/portforward-azure.sh stop                      # tear down forwards
```

`deploy-azure.sh` handles ACR provisioning, image build + push, AKS `get-credentials`, helm install, KEDA install, neo4j password setup, agent + KB seeds, standalone-key reconciliation, and a smoke test. Idempotent — re-run any phase.

### Other clouds

```bash
helm install abenix ./infra/helm/abenix \
  -n abenix --create-namespace \
  --set image.tag=latest \
  --set ingress.host=abenix.your-domain.com
```

Tested on AKS, EKS, GKE, and bare metal.

---

## 🛡️ Enterprise readiness

| Concern | What ships |
|---|---|
| **Tenant isolation** | `tenant_id` on every row; cross-tenant reads return `404` (not `403`). Vector backends enforce the same filter at the index level. |
| **RBAC + multiplexing** | 3 roles (admin/creator/user) + per-feature flags via `/api/me/permissions`. `ResourceShare` for cross-team grants. **actAs** lets a SaaS app holding a platform key serve N end-users via `X-Abenix-Subject` per request. |
| **Auth** | Email+bcrypt; JWT with refresh; per-key scopes (`execute`, `read`, `write`, `can_delegate`); API keys SHA-256-hashed at rest. |
| **Moderation + DLP** | Pre-LLM gate on input + post-LLM gate on output. Actions: `block`, `redact`, `flag`, `allow`. Tenant-scoped, non-bypassable. |
| **Quotas + budgets** | Per-tenant + per-user monthly USD cap, executions/day, tokens/day. Overage returns `BUDGET_EXCEEDED`. |
| **Audit log + GDPR** | Every execution, tool call, KB query, atlas mutation, role change — tenant-scoped, integrity-hashed. Per-tenant data export, soft delete + scheduled hard purge, per-tenant retention windows. |
| **Observability** | Prometheus + Grafana bundled. Stable failure codes (`LLM_RATE_LIMIT`, `SANDBOX_TIMEOUT`, `MODERATION_BLOCKED`). `/alerts` page groups by code. Slack + email fan-out via env var. |
| **HA + self-host** | Stateless API + web tiers; per-pool runtimes with KEDA autoscaling; NATS for at-least-once + replay; stale-execution sweeper. One Helm chart on AKS / minikube / EKS / GKE. MIT license. |

<p align="center">
  <img src="docs/screenshots/08-alerts-page.png" alt="Alerts page" width="100%" />
</p>

---

## 🛠️ Tech stack

| Layer | Stack |
|---|---|
| Web | Next.js 14, React 18, Tailwind, React Flow, Mermaid, Framer Motion |
| API | FastAPI, SQLAlchemy 2 async, Alembic, asyncpg, Pydantic 2 |
| Runtime | Python 3.12, Celery, NATS, Docker / Podman sandbox |
| Data | Postgres 16 (with pgvector), Redis 7, Neo4j, Pinecone (optional), S3-compatible storage |
| Observability | Prometheus, Grafana, structlog, OpenTelemetry |
| Deploy | Helm, KEDA, Azure CLI / kubectl |

---

## 📚 Documentation

- **In-app help** — every running instance has `/help` with the full user guide
- **API reference** — every running instance has `/docs` (FastAPI Swagger)
- **Atlas API** — see [apps/api/app/routers/atlas.py](apps/api/app/routers/atlas.py)
- **Python SDK** — see [packages/sdk/python/README.md](packages/sdk/python/README.md)
- **Roadmap** — see [NEXT_PLANS.md](NEXT_PLANS.md)

---

## 🤝 Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for the quick start, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community guidelines.

Good first issues: new tools, new Atlas starter ontologies, new connectors.

---

## 🛡️ Security

Found a vulnerability? See [SECURITY.md](SECURITY.md). **Please don't open a public issue.**

---

## 📄 License

[MIT](LICENSE) — use it, fork it, ship products on top.

---

<p align="center">
  <em>Built by people who got tired of agents that forget.</em>
</p>
