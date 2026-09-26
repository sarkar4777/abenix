# v2.0 enterprise knowledge stack

Sixteen features landed in v2.0 that move KB / Atlas / PersonaKB from "demo-ready" to "Fortune-500-ready". This page is the developer reference for each.

## At a glance

| Capability | Where it lives | API |
|---|---|---|
| Document-level ACL | [`document_access.py`](../../apps/api/app/services/document_access.py) | `GET/POST/DELETE /api/knowledge/{kb}/documents/{doc}/grants` |
| Document versioning | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) | `POST /api/knowledge/{kb}/documents/{doc}/replace` |
| Incremental Cognify | [`cognify_task.py`](../../apps/worker/worker/tasks/cognify_task.py) + new `documents.cognified_at` | per-job mode `incremental`/`full`/`selective` |
| Cognify config | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) | `GET/PUT /api/knowledge/cognify-config` |
| Cognify conflicts | [`CognifyConflict` model](../../packages/db/models/cognify_config.py) | `GET /api/knowledge/cognify-conflicts`, `POST /api/knowledge/cognify-conflicts/{id}/resolve` |
| Embedding-model swap | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) + [`kb_reembed`](../../apps/worker/worker/tasks/kb_reembed.py) worker | `POST /api/knowledge/{kb}/reembed` |
| GDPR cascade purge | [`gdpr_purge.py`](../../apps/api/app/services/gdpr_purge.py) | `POST /api/gdpr/users/{id}/purge`, `GET /api/gdpr/users/{id}/receipts` |
| Persona encryption | [`crypto.py`](../../apps/api/app/core/crypto.py) | per-tenant DEK derived from cluster KEK |
| Reranking + citations | [`reranker.py`](../../apps/api/app/services/reranker.py) | `Citation` dataclass in every search hit |
| Pinecone vacuum | [`pinecone_vacuum.py`](../../apps/worker/worker/tasks/pinecone_vacuum.py) | daily Celery beat |
| Cypher sandbox | [`atlas_cypher.py`](../../apps/agent-runtime/engine/tools/atlas_cypher.py) | `atlas_cypher` tool |
| Bi-temporal Atlas | atlas_nodes/edges gain `valid_from / valid_to / recorded_at / source_anchors` | `atlas_as_of` tool |
| OCR pipeline | [`services/extractors/`](../../apps/api/app/services/extractors/) | auto-fallback in document_processor |
| Pagination cursors | every list endpoint gains `cursor` + `next_cursor` | uniform pattern |
| Load-test baseline | extended [`scripts/load/baseline.js`](../../scripts/load/baseline.js) | `kb_ingest`, `vector_search`, `cognify_throughput` |

## Document-level ACL

The legacy `collection_grants` was KB-level only. v2.0 adds `document_grants(document_id, subject_type, subject_id, permission)` so a single KB can be partitioned across teams without losing cross-team graph traversal. The pre-filter is applied **before similarity search** — a forbidden doc never enters the candidate pool, so the top-K result count is honest.

Cache: per-(subject, kb_id) Redis entry, 60s TTL. Invalidated automatically on grant / revoke.

## Document versioning

Replace a contract amendment by `POST /api/knowledge/{kb}/documents/{doc}/replace`. The old row is marked `is_current=false, superseded_by=<new_id>`. Search defaults to `is_current=true`. Pass `?include_superseded=true` to query history. Cognify only processes current versions, so superseded contracts stop influencing the graph the moment they're replaced.

### How queries resolve after a replace

Three paths fan out from a single `replace` call. All happen automatically — no agent or caller change required.

**KB vector search.** [`hybrid_search.py`](../../apps/agent-runtime/engine/knowledge/hybrid_search.py) filters by `documents.is_current = true` before similarity scoring, so the new version's chunks are the only candidates returned. The old chunks remain in Pinecone for auditability — pass `include_superseded=true` to surface them — but the default agent retrieval path never sees them.

**Atlas graph queries.** New edges derived from the replacement document carry `valid_from = now, valid_to = NULL` (the bi-temporal columns added in v2.0). Edges from the superseded document get `valid_to = supersede_time` so they become historical facts. The default Cypher templates use `WHERE r.valid_to IS NULL`, so routine traversal returns only the new state. Forensic agents use `atlas_as_of(timestamp)` to query the historical graph explicitly.

**Cognify.** Incremental jobs only fetch documents where `is_current = true AND (cognified_at IS NULL OR updated_at > cognified_at)`. The replaced document immediately appears in the next job's frontier; the superseded document is excluded. Entity resolution still MERGEs against existing nodes so the new doc enriches the graph without duplicating identities.

**The agent's view, end-to-end:**

```
agent.execute("Summarize the latest version of contract X")
  ↓
  knowledge_search(query="contract X", kb_id=...)
  ↓
  hybrid_search filters is_current=true → returns chunks from doc v2 only
  ↓
  agent sees citations to "contract.pdf · v2 · page 42 · chunk 3"
  ↓
  atlas_describe("contract X") returns nodes with valid_to IS NULL
  ↓
  same agent run gets a coherent view: v2 chunks + v2-era graph state
```

**Auditor view** (same agent, different query):

```
agent.execute("Show me the obligations as of 2025-01-15")
  ↓
  atlas_as_of(timestamp="2025-01-15", match_clause="(c:Contract)-[r:HAS_OBLIGATION]->(o)")
  ↓
  returns edges with valid_from <= 2025-01-15 AND valid_to > 2025-01-15
  ↓
  agent sees the v1 obligations (which were valid then, retracted on supersede)
```

No customer code changes when an upload is replaced. The query layer auto-resolves to the right state.

## Incremental Cognify

`cognify_task.run(mode='incremental')` only re-processes docs where `cognified_at IS NULL OR updated_at > cognified_at`. For a 10k-doc KB adding 100 new docs daily, this drops the cost from $99k/month to $999/month at typical extraction rates.

Three modes:
- `incremental` (default) — new + updated docs
- `full` — every doc (use when ontology changes)
- `selective` — explicit `document_ids: [...]` (manual fix)

Per-tenant `max_parallel_docs` config controls in-job parallelism via `asyncio.gather + Semaphore`.

## Cognify config + conflict detection

Per-tenant row in `cognify_configs`:
- `auto_accept_threshold` (default 0.85) — proposals at this confidence land directly
- `conflict_action` (`flag` | `split` | `lower_conf_wins` | `higher_conf_wins`)
- `max_parallel_docs` (default 8)
- `daily_budget_usd` (optional hard cap)

When two sources disagree on an entity property, a `cognify_conflicts` row is created. The UI at `/settings/cognify` lists open conflicts and supports per-row resolution.

## Embedding-model swap

Every KB has a stored `embedding_model`. Switching is a three-step operation:

1. `POST /api/knowledge/{kb}/reembed?dry_run=true` — cost estimate + ETA
2. `POST /api/knowledge/{kb}/reembed` (with `embedding_model: "voyage-3"`) — enqueues the worker, returns a job_id
3. Worker streams chunks to a staging Pinecone namespace, atomic alias flip on completion, old namespace marked `deletable_at = now + 24h` for rollback safety

The query path always reads `kb.embedding_model` and embeds with that model — never assumes OpenAI. The old indexed-with-X-can't-query-with-Y class of bug is closed.

## GDPR cascade

`POST /api/gdpr/users/{user_id}/purge` runs the five-store cascade:

| Store | What is purged |
|---|---|
| postgres | persona_items + agent_memories soft-deleted (deleted_at, deleted_by) |
| pinecone | vectors filtered by metadata.user_id, retried 3× then queued for vacuum |
| neo4j | nodes with property user_id detach-deleted |
| blob | `/data/users/<id>/*` removed |
| trajectory | sweeper marks rows tombstoned |

Every store-level attempt writes a `gdpr_purge_log` row. The endpoint `GET /api/gdpr/users/{user_id}/receipts` returns the audit trail — provable to a regulator.

## Persona encryption

At rest, sensitive PersonaItem and AgentMemory fields can be wrapped with AES-256-GCM. The cluster KEK is held in `ABENIX_DATA_KEY_KEK_BASE64` (Azure Key Vault / AWS KMS / Vault). Per-tenant DEK is derived deterministically as `HMAC-SHA256(KEK, tenant_id)` so all pods agree without storing per-tenant key rows.

Missing KEK env → encryption is a no-op (plaintext) and a warning logs once. Production deployments MUST set it.

## Reranking + citation anchors

`hybrid_search` now feeds the top-50 candidates through a reranker:
- Cohere `rerank-english-v3.0` when `COHERE_API_KEY` is set (cheap, fast)
- Claude Haiku scoring as fallback when only `ANTHROPIC_API_KEY` is set
- Passthrough when neither is set

Every hit carries a `Citation` with `{document_id, page, chunk_index, char_offset_start/end, document_name, anchor_url}` — agents can include deep-link citations like `contract.pdf · page 42 · chunk 3` in their output verbatim.

## Pinecone vacuum

Daily Celery beat at 02:00 UTC. Walks every tenant namespace, compares vector IDs against `persona_items.pinecone_ids` and chunk references, deletes orphans in batches of 1000. Cost saving for high-churn tenants is non-trivial — each orphan is 6 KB on per-dim pricing.

## Cypher sandbox + bi-temporal Atlas

Two new agent tools:

`atlas_cypher` — direct Cypher with a strict READ-only validator (rejects CREATE / MERGE / DELETE / SET / REMOVE / CALL apoc / LOAD CSV / `;`). Tenant + graph context auto-injected as params. Result rows capped at 1000, execution at 10s.

`atlas_as_of` — query the graph as it existed at a given timestamp. Backed by new bi-temporal columns on `atlas_nodes` and `atlas_edges`:
- `valid_from` — when the fact became true in the world
- `valid_to` — when it stopped (NULL = still current)
- `recorded_at` — when we learned it
- `source_anchors` — JSONB array of `{document_id, page, chunk_id, confidence}` per source

Compliance + forensic queries ("what did we know on 2025-03-15") now resolve in one Cypher hop.

## OCR pipeline

The extractor interface in [`services/extractors/`](../../apps/api/app/services/extractors/) replaces the legacy "if PDF: extract text" branch in `document_processor.py`:

```
dispatch(blob_path) → (blocks, method, quality_score)

  ↓ pdf → text_pdf — try first
  ↓        if chars/page < 50 → vision_pdf (Claude vision via PyMuPDF rasterization)
  ↓ office (docx/pptx/xlsx/html/epub/rtf) → unstructured.io
  ↓ image (png/jpg/tiff) → vision
  ↓ text (txt/md/csv/json) → plain
```

`documents.extraction_method` and `extraction_quality` are written so a customer can audit which docs needed OCR (typically 30-50% of a contract archive).

## Pagination cursors

Replaced hardcoded `.limit(N)` on persona items (was 500), cognify jobs (was 20/10), and conflicts (new). All list endpoints now accept `?cursor=<id>&limit=<N>` and return `next_cursor` for stable forward iteration.

## Load test baseline

Three new k6 scenarios in [`scripts/load/baseline.js`](../../scripts/load/baseline.js):
- `kb_ingest` — 1000 small docs uploaded in parallel, p99 ingest-to-queryable
- `vector_search` — 10k queries against 1M chunks, p99 < 200ms target
- `cognify_throughput` — 1000 docs through cognify, docs/minute

A customer can validate the platform handles their workload before signing.

## Migration

Single migration `b8c9d0e1f2g3_v2_knowledge_atlas_persona.py`:
- documents: parent_document_id, version_number, is_current, superseded_by, cognified_at, last_cognify_job_id, extraction_method, extraction_quality
- atlas_nodes/edges: valid_from, valid_to, recorded_at, source_anchors
- persona_items: deleted_at, deleted_by, encrypted, key_version
- agent_memories: deleted_at, deleted_by
- new tables: document_grants, cognify_configs, cognify_conflicts, gdpr_purge_log

Backwards-compatible: every new column nullable or server-defaulted. No data movement, and the migration is idempotent.

## Source map

| What | Where |
|---|---|
| Migration | [`packages/db/alembic/versions/b8c9d0e1f2g3_v2_knowledge_atlas_persona.py`](../../packages/db/alembic/versions/b8c9d0e1f2g3_v2_knowledge_atlas_persona.py) |
| New models | [`document_grant.py`](../../packages/db/models/document_grant.py), [`cognify_config.py`](../../packages/db/models/cognify_config.py), [`gdpr_purge_log.py`](../../packages/db/models/gdpr_purge_log.py) |
| New routers | [`document_grants.py`](../../apps/api/app/routers/document_grants.py), [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py), [`gdpr.py`](../../apps/api/app/routers/gdpr.py) |
| Services | [`document_access.py`](../../apps/api/app/services/document_access.py), [`gdpr_purge.py`](../../apps/api/app/services/gdpr_purge.py), [`reranker.py`](../../apps/api/app/services/reranker.py), [`crypto.py`](../../apps/api/app/core/crypto.py) |
| Workers | [`kb_reembed.py`](../../apps/worker/worker/tasks/kb_reembed.py), [`pinecone_vacuum.py`](../../apps/worker/worker/tasks/pinecone_vacuum.py) |
| Extractors | [`services/extractors/`](../../apps/api/app/services/extractors/) |
| New tools | [`atlas_cypher.py`](../../apps/agent-runtime/engine/tools/atlas_cypher.py) |
| UI | [`/settings/cognify`](../../apps/web/src/app/(app)/settings/cognify/page.tsx), [`/settings/gdpr`](../../apps/web/src/app/(app)/settings/gdpr/page.tsx) |
| Tests | [`uat_v2_enterprise.spec.ts`](../../e2e/uat_v2_enterprise.spec.ts) |
