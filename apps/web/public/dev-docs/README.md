# Abenix Developer Documentation

> A complete reference for architects and developers who want to understand the Abenix platform, extend it, add features, debug it, or build on top of its SDK.

These docs are written to be read **two ways**: on GitHub (the markdown renders Mermaid diagrams natively) or inside the app at `/dev-docs` (which adds a sidebar, in-page anchors, and full-text search).

---

## Where to start

| If you're … | Start here |
|---|---|
| **A new architect** trying to understand the whole system | [01-architecture/00-overview](01-architecture/00-overview.md) |
| **A backend developer** adding a feature | [02-runtime/00-agent-execution](02-runtime/00-agent-execution.md) |
| **A frontend developer** adding a page | [05-ui/00-app-shell](05-ui/00-app-shell.md) |
| **An ops engineer** deploying or debugging | [06-deployment/00-overview](06-deployment/00-overview.md) |
| **An SDK consumer** integrating from outside | [03-sdk/00-overview](03-sdk/00-overview.md) |
| **A product engineer** building a vertical app on top | [07-standalone-apps/00-pattern](07-standalone-apps/00-pattern.md) |
| **A debugger** trying to chase a bad scan / failed pipeline / silent agent | [08-howto/04-debugging](08-howto/04-debugging.md) |
| **You want the deep version** — every recurring pattern in one page | [01-architecture/05-architectural-patterns](01-architecture/05-architectural-patterns.md) |
| **You're orchestrating multiple agents** | [02-runtime/06-agent-to-agent](02-runtime/06-agent-to-agent.md) |
| **You're tuning scaling / queue depth / KEDA** | [02-runtime/08-queue-scaling](02-runtime/08-queue-scaling.md) |
| **You're debugging a stuck execution / pending approval** | [02-runtime/09-state-machines](02-runtime/09-state-machines.md) |

---

## Table of contents

### 1. Architecture
The big picture — what services exist, how they communicate, what guarantees they offer.

- [00 — System overview](01-architecture/00-overview.md)
- [01 — Tenants, RBAC, the actAs delegation chain](01-architecture/01-tenants-rbac.md)
- [02 — Request lifecycle (web → api → agent-runtime → tool → response)](01-architecture/02-request-lifecycle.md)
- [03 — Service inventory (api, web, worker, agent-runtime, edge, standalone apps)](01-architecture/03-services.md)
- [04 — Data stores (Postgres, Neo4j, Redis, S3, Kafka, NATS)](01-architecture/04-data-stores.md)
- [05 — Architectural patterns reference (45 patterns)](01-architecture/05-architectural-patterns.md)

### 2. Runtime
How an agent runs end-to-end, what a tool is, how pipelines work, how agents talk to each other, how state machines move.

- [00 — Agent execution loop](02-runtime/00-agent-execution.md)
- [01 — Pipelines + the DAG engine](02-runtime/01-pipelines.md)
- [02 — Tools framework — base class, registry, schemas](02-runtime/02-tools.md)
- [03 — MCP server integration](02-runtime/03-mcp.md)
- [04 — Streaming events + OpenTelemetry tracing](02-runtime/04-streaming-tracing.md)
- [05 — Approvals / HITL gates](02-runtime/05-approvals-hitl.md)
- [06 — Agent-to-agent communication (`invoke_agent` + root channels)](02-runtime/06-agent-to-agent.md)
- [07 — Pipeline data flow + template scoping](02-runtime/07-pipeline-data-flow.md)
- [08 — Queues, pools, and KEDA autoscaling](02-runtime/08-queue-scaling.md)
- [09 — State machines (executions, approvals, pipelines, idempotency)](02-runtime/09-state-machines.md)

### 3. SDK
The polyglot client surface — how external apps and standalone verticals talk to the platform.

- [00 — SDK design + the actAs pattern](03-sdk/00-overview.md)
- [01 — Python SDK](03-sdk/01-python.md)
- [02 — TypeScript SDK](03-sdk/02-typescript.md)
- [03 — Java SDK](03-sdk/03-java.md)

### 4. Data model
The shape of the database and how it maps to the runtime concepts.

- [00 — Entity-relationship overview (ERD)](04-data-model/00-overview.md)
- [01 — Agents, revisions, pipelines](04-data-model/01-agents.md)
- [02 — Executions, invocations, traces](04-data-model/02-executions.md)
- [03 — Knowledge bases, documents, atlas graph](04-data-model/03-knowledge.md)
- [04 — Resource sharing (the polymorphic table)](04-data-model/04-resource-shares.md)

### 5. UI
The Next.js app — layout, routing, state, design language.

- [00 — App shell, auth, routing](05-ui/00-app-shell.md)
- [01 — Agent Builder canvas](05-ui/01-builder-canvas.md)
- [02 — API client + error envelope + toast layer](05-ui/02-api-client.md)
- [03 — Page catalogue (every route + what it does + data sources)](05-ui/03-page-catalogue.md)

### 6. Deployment
From `git clone` to a running cluster.

- [00 — Deploy overview (local vs AKS)](06-deployment/00-overview.md)
- [01 — Image build pipeline](06-deployment/01-images.md)
- [02 — Helm chart structure](06-deployment/02-helm.md)
- [03 — Autoscaling with KEDA](06-deployment/03-keda.md)
- [04 — Observability stack (Prometheus, Grafana, Tempo)](06-deployment/04-observability.md)

### 7. Building apps on Abenix
How a third party builds a vertical app that uses Abenix as a remote platform. Includes references for the six example apps in this monorepo.

- [00 — Building an app on top of Abenix (read this first)](07-standalone-apps/00-pattern.md)
- [01 — Wingman (reference: energy trading)](07-standalone-apps/01-wingman.md)
- [02 — ContractIQ (reference: contract intelligence)](07-standalone-apps/02-contractiq.md)
- [03 — Mideast Tourism, ResolveAI, ClaimsIQ, Industrial-IoT (reference)](07-standalone-apps/03-others.md)

### 8. How-to (walkthroughs)
Concrete step-by-step guides for the most common developer tasks.

- [00 — Local development setup](08-howto/00-local-setup.md)
- [01 — Add a new tool](08-howto/01-add-a-tool.md)
- [02 — Add a new agent (yaml + seed + UI)](08-howto/02-add-an-agent.md)
- [03 — Add a new UI page](08-howto/03-add-a-page.md)
- [04 — Debugging (logs, traces, common failure modes)](08-howto/04-debugging.md)
- [05 — Writing and running tests (unit, e2e, UAT)](08-howto/05-testing.md)

### 9. Reference
Catalogues and tables you'll look up rather than read end-to-end.

- [00 — REST API reference](09-reference/00-rest-api.md)
- [01 — Environment variables](09-reference/01-env-vars.md)
- [02 — CLI cheatsheet (`deploy-azure.sh`, etc.)](09-reference/02-cli.md)
- [03 — Glossary](09-reference/03-glossary.md)

---

## Conventions used in these docs

- **Source-file callouts** look like [`apps/api/app/main.py:75`](../apps/api/app/main.py#L75) — clickable on GitHub, copyable everywhere else.
- **Diagrams** are Mermaid in fenced code blocks. GitHub renders them inline. the in-app viewer also renders them.
- **Code examples** are runnable as-is unless explicitly marked otherwise.
- **`> Why`** call-outs explain the *rationale* behind a design choice. Useful when the code looks weirder than necessary.
- **`> Trap`** call-outs flag known footguns. If something has bitten us in production it's here.

If you read these top-to-bottom you'll have a solid understanding of the system in ~3-4 hours. If you skim only the diagrams + the "Why" call-outs you'll have the mental model in ~30 minutes.
