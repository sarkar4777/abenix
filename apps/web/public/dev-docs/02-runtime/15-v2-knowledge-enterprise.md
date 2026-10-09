# v2.0 enterprise knowledge stack

Sixteen features landed in v2.0 that move KB / Atlas / PersonaKB from "demo-ready" to "Fortune-500-ready". This page is the developer reference for each.

## At a glance

| Capability | Where it lives | API |
|---|---|---|
| Document-level ACL | [`document_acl.py`](../../apps/agent-runtime/engine/knowledge/document_acl.py), [`document_access.py`](../../apps/api/app/services/document_access.py) | `GET/POST/DELETE /api/knowledge/{kb}/documents/{doc}/grants` |
| Document versioning | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) | `POST /api/knowledge/{kb}/documents/{doc}/replace` |
| Incremental Cognify | [`cognify_task.py`](../../apps/worker/worker/tasks/cognify_task.py) + new `documents.cognified_at` | per-job mode `incremental`/`full`/`selective` |
| Cognify config | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) | `GET/PUT /api/knowledge/cognify-config` |
| Cognify conflicts | [`CognifyConflict` model](../../packages/db/models/cognify_config.py) | `GET /api/knowledge/cognify-conflicts`, `POST /api/knowledge/cognify-conflicts/{id}/resolve` |
| Embedding-model swap | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) + [`kb_reembed`](../../apps/worker/worker/tasks/kb_reembed.py) worker | `GET/POST /api/knowledge/{kb}/reembed` |
| GDPR cascade purge | [`gdpr_purge.py`](../../apps/api/app/services/gdpr_purge.py) | `POST /api/gdpr/users/{id}/purge`, `GET /api/gdpr/users/{id}/receipts` |
| Persona encryption | [`crypto.py`](../../apps/api/app/core/crypto.py) | per-tenant DEK derived from cluster KEK |
| Reranking + citations | [`reranker.py`](../../apps/agent-runtime/engine/knowledge/reranker.py) | `metadata.citation` on every chunk hit |
| Pinecone vacuum | [`pinecone_vacuum.py`](../../apps/worker/worker/tasks/pinecone_vacuum.py) | queued daily at 02:30 UTC by the API scheduler |
| Atlas as-of | [`atlas_tools.py`](../../apps/agent-runtime/engine/tools/atlas_tools.py), reads `atlas_snapshots` | `atlas_as_of` tool |
| OCR pipeline | [`engine/knowledge/extractors/`](../../apps/agent-runtime/engine/knowledge/extractors/) | auto-fallback in document_processor |
| Pagination cursors | every list endpoint gains `cursor` + `next_cursor` | uniform pattern |
| Load-test baseline | extended [`scripts/load/baseline.js`](../../scripts/load/baseline.js) | `kb_ingest`, `vector_search`, `cognify_throughput` |

## Document-level ACL

`collection_grants` decide who can read a collection. `document_grants(document_id, subject_type, subject_id, permission, expires_at)` narrow one document inside it. The rule lives in [`document_acl.py`](../../apps/agent-runtime/engine/knowledge/document_acl.py), so the API and the runtime decide the same way.

- A document with no live grants is visible to everyone who can read the collection.
- The first grant restricts it. From then on only its grantees see it, plus tenant admins, the collection creator and users holding WRITE or ADMIN on the collection.
- A grantee is a user or an agent (`subject_type` is `user` or `agent`). There are no team or role subjects. An expired grant no longer counts.
- Search drops restricted documents before ranking, in the vector, Pinecone and graph paths, so the top-K is drawn only from what the caller may read. The search response reports `hidden_documents`, and the search cache is keyed by the hidden set.
- `GET /api/knowledge-bases/{kb}/documents` leaves restricted documents out and returns `meta.hidden` with how many.
- Only collection editors can add or remove grants. Anyone else gets 403 "Only people who can edit this collection can share documents".

## Document versioning

Replace a contract amendment by `POST /api/knowledge/{kb}/documents/{doc}/replace`. The old row is marked `is_current=false, superseded_by=<new_id>`. Search defaults to `is_current=true`. Pass `?include_superseded=true` to query history. Cognify only processes current versions, so superseded contracts stop influencing the graph the moment they're replaced.

### How queries resolve after a replace

Three paths fan out from a single `replace` call. All happen automatically — no agent or caller change required.

**KB vector search.** [`hybrid_search.py`](../../apps/agent-runtime/engine/knowledge/hybrid_search.py) filters by `documents.is_current = true` before similarity scoring, so the new version's chunks are the only candidates returned. The old chunks remain in Pinecone for auditability — pass `include_superseded=true` to surface them — but the default agent retrieval path never sees them.

**Atlas graph queries.** A replace does not touch the Atlas graph. To see the graph as it stood before a change, agents use `atlas_as_of`, which reads saved snapshots, see [Atlas as-of](#atlas-as-of).

**Cognify.** Incremental jobs only fetch documents where `is_current = true AND (cognified_at IS NULL OR updated_at > cognified_at)`. The replaced document immediately appears in the next job's frontier, and the superseded document is excluded. Entity resolution still MERGEs against existing nodes so the new doc enriches the graph without duplicating identities.

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
  same agent run sees v2 chunks only
```

**Auditor view** (same agent, different query):

```
agent.execute("Show me the obligation concepts as of 2025-01-15")
  ↓
  atlas_as_of(as_of="2025-01-15", label_like="obligation")
  ↓
  newest snapshot saved at or before that date, or the live graph if nothing changed since
  ↓
  agent sees the obligation nodes and their edges as they stood then
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

Per-tenant row in `cognify_configs`, edited at `/settings/cognify`. The pipeline reads it on every job.

| Setting | Default | What the pipeline does with it |
|---|---|---|
| `auto_accept_threshold` | 0.85 | Entity and relationship proposals below it are left out of the graph, along with relationships left dangling. The job report counts them as `entities_held_back` and `relationships_held_back` |
| `conflict_action` | `flag` | Applies when sources disagree on an entity's type. See below |
| `max_parallel_docs` | 8 | Documents processed at once within a job |
| `daily_budget_usd` | none | Once the tenant's Cognify spend for the UTC day reaches it, the job processes no more documents and says how many it skipped |

When two sources give one entity different types, `conflict_action` decides.

| Value | Result |
|---|---|
| `flag` | Keeps the stored or majority type and records an open `cognify_conflicts` row |
| `higher_conf_wins` | Takes the type with the higher confidence |
| `lower_conf_wins` | Takes the type with the lower confidence |
| `split` | Keeps both as `Name (type)` variants linked by `VARIANT_OF` |

`/settings/cognify` lists open conflicts. Resolving one with one of the two values writes that type to the graph, in Postgres and in Neo4j. The job list shows `conflicts_recorded` per job.

## Embedding-model swap

Every collection has a stored `embedding_model`. Ingest and search both embed with it. The allowed models are in [`packages/db/embedding_models.py`](../../packages/db/embedding_models.py). Each yields 1536 floats, so a switch needs no schema change.

| Model | Notes |
|---|---|
| `text-embedding-3-small` | The default, follows `OPENAI_EMBEDDING_MODEL` |
| `text-embedding-3-large` | Requested at 1536 dimensions |
| `text-embedding-ada-002` | |
| `local-hashing-v1` | Built-in hashed embedder, no provider call, free |

1. `GET /api/knowledge/{kb}/reembed` returns the current model, the allowed models and the latest job's progress. Anyone who can read the collection can call it.
2. `POST /api/knowledge/{kb}/reembed` with `{"embedding_model": "...", "dry_run": true}` returns the chunk count, a cost estimate and an ETA. Admins only.
3. The same call without `dry_run` queues the worker and answers 202 with a `job_id`. An unknown model is 400. A job already queued or running is 409.

The worker re-reads every document from storage and re-chunks it with the collection's chunk settings, falling back to the indexed chunk text when the file is gone. It embeds with the new model and stages the result. Nothing live changes until every document is staged. Then the collection switches in one step and flips `embedding_model`. If anything fails before that, the collection keeps its old vectors and model. Progress is kept in Redis under `kb_reembed:<kb_id>`.

The KB engine page (`/knowledge/{id}/engine`) has an **Embedding model** panel showing the current model and job progress. Admins pick a model, see the estimate and start the swap there.

## GDPR cascade

`POST /api/gdpr/users/{user_id}/purge` runs the five-store cascade. It can only target a user in the caller's own tenant, anyone else is 404.

| Store | What is purged |
|---|---|
| postgres | The person's persona items soft-deleted, agent memories soft-deleted only for agents the person created, API keys deactivated and the user row scrubbed to a placeholder. Every message in the person's conversations, theirs and the replies, is replaced with `[erased]`, with their blocks, attachments and tool calls cleared, their conversation titles and previews are erased and any share link revoked, and the runs they started lose their input, output, tool calls, node results and trace. Conversations and runs stay linked to the scrubbed user row, so spend history stays whole. Audit rows keep the hash chain: the salted PII digest stays, while the salt, user id, IP and user agent go, so a row can no longer be tied to the person. Rows already erased by an earlier attempt are not counted again |
| pinecone | The person's persona vectors, by id from `persona_items.pinecone_ids`, in the tenant's persona namespace. Retried 3 times. Fails if vectors exist and `PINECONE_API_KEY` is not set |
| neo4j | Cognify entities that name the person across the tenant's collections: the email on any entity, the full name (two or more words) on person entities, by name or alias. The matching `graph_entities` and `graph_relationships` rows in Postgres go too. Fails if Neo4j is unreachable while such entities exist |
| blob | Code asset archives (every version) and ML model files the person uploaded, deleted on local disk and in object storage, everything under the person's own storage folder (`users/<id>/`), and their cloned voice at the voice provider, with the voice link on the user row cleared. Uploads still used by an agent or pipeline, shared, or deployed are kept and logged. The count is the files really deleted, plus one for a deleted voice |
| trajectory | Trajectory records written from the person's runs, matched by the run's execution id or a user id on the record, in the tenant's folder and the `shared` folder under `TRAJECTORY_DIR` (`/data/trajectories`) and the older `WINGMAN_TRAJECTORY_DIR` (`/data/wingman-trajectories`). The count is the records deleted |

Every store-level attempt writes a `gdpr_purge_log` row, with how many rows, vectors, files or records it really removed in `affected_count`. `GET /api/gdpr/users/{user_id}/receipts` returns the audit trail, with that count as `affected`. `/settings/gdpr` shows it in the **Removed** column.

## Persona encryption

At rest, sensitive PersonaItem and AgentMemory fields can be wrapped with AES-256-GCM. The cluster KEK is held in `ABENIX_DATA_KEY_KEK_BASE64` (Azure Key Vault / AWS KMS / Vault). Per-tenant DEK is derived deterministically as `HMAC-SHA256(KEK, tenant_id)` so all pods agree without storing per-tenant key rows.

Missing KEK env → encryption is a no-op (plaintext) and a warning logs once. Production deployments MUST set it.

## Reranking + citation anchors

`hybrid_search` fetches extra candidates and reranks them when a reranker is on ([`reranker.py`](../../apps/agent-runtime/engine/knowledge/reranker.py)).

- Cohere `rerank-english-v3.0` runs when `COHERE_API_KEY` is set.
- The Claude Haiku scorer runs only with `RERANKER_PROVIDER=llm`, since it adds a model call to every search.
- Otherwise results keep their retrieval order. `RERANKER_PROVIDER=none` turns reranking off.

Every chunk hit carries `metadata.citation` with `document_id`, `page`, `chunk_index`, `char_offset_start`, `char_offset_end`, `document_name` and an anchor, so agents can cite `contract.pdf · page 42 · chunk 3`.

## Pinecone vacuum

The API scheduler queues `worker.tasks.pinecone_vacuum.run` on the worker's `documents` queue daily at 02:30 UTC, from one replica. It deletes, in batches of 1000:

- every vector in the namespace of a collection that no longer exists
- a document's leftover vectors past its current chunk count, left when a re-processed document shrank
- persona vectors whose persona item is gone, soft-deleted or no longer lists them

Vectors with no `documents` row are kept, since `knowledge_store` writes vectors without one.

## Atlas as-of

`atlas_as_of` shows an Atlas graph as it stood at a past moment.

| Input | Meaning |
|---|---|
| `graph_id` | Optional. Defaults to the agent's primary atlas |
| `as_of` | ISO-8601 date or timestamp, UTC without an offset. Defaults to now |
| `label_like` | Only nodes whose label contains this text, plus their edges |
| `kind` | `concept`, `instance`, `document` or `property` |
| `limit` | Max nodes and max edges, default 100, up to 1000 |

When the graph has not changed since `as_of`, it reads the live graph, keeping only rows created by then and inside their `valid_from` and `valid_to`. Otherwise it reads the newest `atlas_snapshots` row saved at or before `as_of`. With no such snapshot, or a time before the graph existed, it returns `found: false` and why. The result says whether it came from `live` or a `snapshot`.

## OCR pipeline

The worker extracts text through [`engine/knowledge/extractors/`](../../apps/agent-runtime/engine/knowledge/extractors/):

```
extract_document(path, file_type) → (blocks, method, quality_score)

  ↓ pdf  → text_pdf first
  ↓        if chars/page < 50 → vision_pdf (pages rasterised with PyMuPDF, read by Claude)
  ↓ docx → unstructured, falling back to python-docx
  ↓ text (txt/md/csv/json) → plain
  ↓ anything else → read as text
```

Ingest records `documents.extraction_method` and `extraction_quality`. Blocks carry page numbers, so each chunk stores its `page` and citations can point at it. Vision OCR needs PyMuPDF and `ANTHROPIC_API_KEY` on the worker. Without them a scanned PDF yields little or no text. Uploads are still limited to PDF, DOCX, TXT, CSV, MD and JSON.

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
| Services | [`document_access.py`](../../apps/api/app/services/document_access.py), [`document_acl.py`](../../apps/agent-runtime/engine/knowledge/document_acl.py), [`gdpr_purge.py`](../../apps/api/app/services/gdpr_purge.py), [`reranker.py`](../../apps/agent-runtime/engine/knowledge/reranker.py), [`crypto.py`](../../apps/api/app/core/crypto.py), [`embedding_models.py`](../../packages/db/embedding_models.py) |
| Workers | [`kb_reembed.py`](../../apps/worker/worker/tasks/kb_reembed.py), [`pinecone_vacuum.py`](../../apps/worker/worker/tasks/pinecone_vacuum.py) |
| Extractors | [`engine/knowledge/extractors/`](../../apps/agent-runtime/engine/knowledge/extractors/) |
| Atlas as-of tool | [`atlas_tools.py`](../../apps/agent-runtime/engine/tools/atlas_tools.py) |
| UI | [`/settings/cognify`](../../apps/web/src/app/(app)/settings/cognify/page.tsx), [`/settings/gdpr`](../../apps/web/src/app/(app)/settings/gdpr/page.tsx), [`EmbeddingModelPanel.tsx`](../../apps/web/src/components/knowledge/EmbeddingModelPanel.tsx) |
| Tests | [`uat_v2_enterprise.spec.ts`](../../e2e/uat_v2_enterprise.spec.ts) |
