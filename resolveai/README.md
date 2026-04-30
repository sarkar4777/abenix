# ResolveAI

Customer-service AI standalone app on top of Abenix.

**Design of record:** [`docs/RESOLVEAI_DESIGN.md`](../docs/RESOLVEAI_DESIGN.md)

Resolves tickets, cites the policy used, predicts CSAT, and surfaces
tomorrow's problem tonight — peer app to `example_app/` and
`sauditourism/`, thin by design.

## Anatomy

```
resolveai/
  api/                FastAPI on :8004 — owns the case-lifecycle tables,
                      delegates every reasoning call to Abenix via
                      the bundled SDK.
    main.py           Case ingest + SLA/QA/trend trigger endpoints.
    sdk/              Bundled copy of abenix_sdk (same as example_app/).
    Dockerfile
    requirements.txt
  web/                Next.js on :3004 — dashboard, cases queue, case
                      detail, live-agent console, admin.
  seeds/
    agents/*.yaml     Agent + pipeline seeds. Triage, Policy Research,
                      Resolution Planner, Inbound Resolution pipeline.
    kb/ontology.yaml  Policy + Case ontology for the Cognify extractor.
  e2e/                End-to-end Playwright suites.
```

## Ports (local dev via `start.sh` / docker-compose)

| Service         | Port |
|-----------------|------|
| resolveai-web   | 3004 |
| resolveai-api   | 8004 |

On minikube / Azure it's surfaced under `care.<cluster-ip>.nip.io` (see
`apps/api/app/routers/use_cases.py` → the `ResolveAI` entry). URLs are
resolved at runtime by the `/api/use-cases` endpoint — never hardcoded.

## Environment

| Variable                          | Purpose                                    |
|-----------------------------------|--------------------------------------------|
| `ABENIX_API_URL`              | Cluster-DNS URL of abenix-api          |
| `RESOLVEAI_ABENIX_API_KEY`    | Service-account `af_...` key               |
| `RESOLVEAI_PUBLIC_URL`            | Override for `/api/use-cases` (optional)   |
| `DATABASE_URL`                    | Postgres for resolveai-owned tables (phase 2) |

## What's in + what's phased

| Capability | Status |
|---|---|
| Ticket ingest → synchronous Inbound Resolution pipeline | Phase 1 ✅ |
| Policy citation round-trip (Triage → Policy Research → Planner) | Phase 1 ✅ |
| Cases dashboard + case-detail + timeline | Phase 1 ✅ |
| Moderation post-gate before auto-reply | Phase 1 ✅ (via pipeline node) |
| Deflection scoring + human handoff | Phase 2 (UI + Live Copilot) |
| SLA sweep trigger + Slack escalation | Phase 2 |
| Post-resolution CSAT prediction | Phase 2 |
| Voice escalation via meeting primitives | Phase 3 |
| Nightly Trend Miner + VoC dashboard | Phase 3 |

## Running locally

1. Abenix is running (port-forward or `start.sh`) and has a tenant
   with a `resolveai-*` API key.
2. Seed the agents + KB:
   ```bash
   cd packages/db/seeds
   python seed.py --path ../../resolveai/seeds/agents
   # Create a KB "ResolveAI Policies" → Projects → Ontology →
   # upload resolveai/seeds/kb/ontology.yaml
   ```
3. Start the backend:
   ```bash
   cd resolveai/api
   ABENIX_API_URL=http://localhost:8000 \
   RESOLVEAI_ABENIX_API_KEY=af_XXXX \
   PORT=8004 python main.py
   ```
4. Start the web:
   ```bash
   cd resolveai/web
   npm install
   npm run dev
   # Open http://localhost:3004
   ```
5. Click **Simulate a ticket** on /cases — watch the pipeline run.
