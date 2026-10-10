# v2.0 enterprise knowledge stack

The v2.0 release added access control, versioning, model swaps, purge and audit features to the knowledge base (KB), Atlas and PersonaKB. This page is the developer reference for each one.

## At a glance

| Capability | Where it lives | API |
|---|---|---|
| Document-level ACL | [`document_acl.py`](../../apps/agent-runtime/engine/knowledge/document_acl.py), [`document_access.py`](../../apps/api/app/services/document_access.py) | `GET/POST/DELETE /api/knowledge/{kb}/documents/{doc}/grants` |
| Document versioning | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) | `POST /api/knowledge/{kb}/documents/{doc}/replace` |
| Incremental Cognify | [`cognify_pipeline.py`](../../apps/agent-runtime/engine/knowledge/cognify_pipeline.py), [`cognify_task.py`](../../apps/worker/worker/tasks/cognify_task.py) | `POST /api/knowledge-engines/{kb}/cognify` |
| Cognify config | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) | `GET/PUT /api/knowledge/cognify-config` |
| Cognify conflicts | [`CognifyConflict` model](../../packages/db/models/cognify_config.py) | `GET /api/knowledge/cognify-conflicts`, `POST /api/knowledge/cognify-conflicts/{id}/resolve` |
| Embedding-model swap | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) + [`kb_reembed`](../../apps/worker/worker/tasks/kb_reembed.py) worker | `GET/POST /api/knowledge/{kb}/reembed` |
| GDPR cascade purge | [`gdpr_purge.py`](../../apps/api/app/services/gdpr_purge.py) | `POST /api/gdpr/users/{id}/purge`, `GET /api/gdpr/users/{id}/receipts` |
| Field encryption | [`crypto.py`](../../apps/api/app/core/crypto.py) | per-tenant DEK derived from cluster KEK |
| Reranking + citations | [`reranker.py`](../../apps/agent-runtime/engine/knowledge/reranker.py) | `metadata.citation` on every chunk hit |
| Pinecone vacuum | [`pinecone_vacuum.py`](../../apps/worker/worker/tasks/pinecone_vacuum.py) | queued daily at 02:30 UTC by the API scheduler |
| Atlas as-of | [`atlas_tools.py`](../../apps/agent-runtime/engine/tools/atlas_tools.py), reads `atlas_snapshots` | `atlas_as_of` tool |
| OCR pipeline | [`engine/knowledge/extractors/`](../../apps/agent-runtime/engine/knowledge/extractors/) | auto-fallback in document_processor |
| Conflict list cursor | [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py) | `cursor` + `next_cursor` on `GET /api/knowledge/cognify-conflicts` |

## Document-level ACL

`collection_grants` decide who can read a collection. `document_grants(document_id, subject_type, subject_id, permission, expires_at)` narrow one document inside it. The rule lives in [`document_acl.py`](../../apps/agent-runtime/engine/knowledge/document_acl.py), so the API and the runtime decide the same way.

- A document with no grants is visible to everyone who can read the collection.
- The first grant restricts it. From then on only holders of a live grant see it, plus tenant admins, the collection creator and users holding WRITE or ADMIN on the collection.
- A grantee is a user or an agent (`subject_type` is `user` or `agent`). There are no team or role subjects. An expired grant no longer counts, and the document stays restricted, so a lapsed grant never opens it to the whole collection.
- Collection grants for users take an optional `expires_at` too, and an expired one no longer grants read or write.
- Search drops restricted documents before ranking, in the vector, Pinecone and graph paths, so the top-K is drawn only from what the caller may read. The search response reports `hidden_documents`, and the search cache is keyed by the hidden set.
- `GET /api/knowledge-bases/{kb}/documents` leaves restricted documents out and returns `meta.hidden` with how many.
- Only collection editors can add or remove grants. Anyone else gets 403 "Only people who can edit this collection can share documents".

## Document versioning

`POST /api/knowledge/{kb}/documents/{doc}/replace` records a new version of a document. Upload the amended file to the same collection first, then call replace with it:

```json
{"new_filename": "contract-v2.pdf", "new_storage_url": "...", "new_file_type": "pdf", "new_file_size": 48213}
```

The call checks the collection is in the caller's tenant and that they can edit it (404 or 403), and that the new file sits under this tenant's and collection's storage prefix (400). It adds a new `documents` row whose `parent_document_id` points at the first version, with `version_number` one higher, marks the old row `is_current=false, superseded_by=<new_id>`, queues the new version for processing and answers 201 with the new id. Replacing a row that is already superseded is 400. The action is audited as `document.replaced`.

Search and Cognify use the current version only, so agents and callers need no change. Hybrid search drops superseded rows the same way it drops restricted ones, before ranking, and Cognify skips them. The document list shows the current version only. The old row stays as history, and editors and admins read it with `GET /api/knowledge/{kb}/documents/{doc}/versions` or `GET /api/knowledge-bases/{kb}/documents?include_history=true`.

Source Watch uses the same columns when it files a changed page into a collection. See [Source Watch](17-source-watch.md).

To see the Atlas graph as it stood before a change, agents use `atlas_as_of`, which reads saved snapshots. See [Atlas as-of](#atlas-as-of).

## Incremental Cognify

`POST /api/knowledge-engines/{kb}/cognify` queues a job on the worker's `cognify` queue. It takes every current `ready` document in the collection, or only the ones listed in `doc_ids`, plus optional `model`, `chunk_size` and `chunk_overlap`.

Jobs are incremental. If none of the chosen documents was created after the collection's `last_cognified_at`, the pipeline returns without calling a model. The worker then stores the job as `failed`, since it maps every result other than `complete` to `failed`. Otherwise every chosen document is processed. The `documents.cognified_at` and `last_cognify_job_id` columns exist but nothing writes them yet.

Within a job, documents are extracted in parallel up to the tenant's `max_parallel_docs`, through an `asyncio.Semaphore`.

## Cognify config + conflict detection

Per-tenant row in `cognify_configs`, edited at `/settings/cognify`. The pipeline reads it on every job.

| Setting | Default | What the pipeline does with it |
|---|---|---|
| `auto_accept_threshold` | 0.85 | Entity and relationship proposals below it are left out of the graph, along with relationships left dangling. The job report counts them as `entities_held_back` and `relationships_held_back` |
| `conflict_action` | `flag` | Applies when sources disagree on an entity's type. See below |
| `max_parallel_docs` | 8 | Documents processed at once within a job |
| `daily_budget_usd` | none | Once the tenant's Cognify spend for the UTC day reaches it, the job processes no more documents and says how many it skipped |

A budget of 0 stops every new job straight away with a message, which pauses Cognify until it is raised. A job no worker picks up within 15 minutes, or that runs for more than 6 hours, is closed as failed the next time its jobs are listed, so it no longer blocks Run Cognify.

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

`POST /api/gdpr/users/{user_id}/purge` runs the five-store cascade. Admins can purge anyone in their own tenant and other users can purge only themselves (403 otherwise). A user outside the caller's tenant is 404.

| Store | What is purged |
|---|---|
| postgres | The person's persona items soft-deleted, agent memories soft-deleted only for agents the person created, API keys deactivated and the user row scrubbed to a placeholder. Every message in the person's conversations, theirs and the replies, is replaced with `[erased]`, with their blocks, attachments and tool calls cleared, their conversation titles and previews are erased and any share link revoked, and the runs they started lose their input, output, tool calls, node results and trace. Conversations and runs stay linked to the scrubbed user row, so spend history stays whole. Audit rows keep the hash chain: the salted PII digest stays, while the salt, user id, IP and user agent go, so a row can no longer be tied to the person. Rows already erased by an earlier attempt are not counted again |
| pinecone | The person's persona vectors, by id from `persona_items.pinecone_ids`, in the tenant's persona namespace. Retried 3 times. Fails if vectors exist and `PINECONE_API_KEY` is not set |
| neo4j | Cognify entities that name the person across the tenant's collections: the email on any entity, the full name (two or more words) on person entities, by name or alias. The matching `graph_entities` and `graph_relationships` rows in Postgres go too. Fails if Neo4j is unreachable while such entities exist |
| blob | Code asset archives (every version) and ML model files the person uploaded, deleted on local disk and in object storage, everything under the person's own storage folder (`users/<id>/`), and their cloned voice at the voice provider, with the voice link on the user row cleared. Uploads still used by an agent or pipeline, shared, or deployed are kept and logged. The count is the files really deleted, plus one for a deleted voice |
| trajectory | Trajectory records written from the person's runs, matched by the run's execution id or a user id on the record, in the tenant's folder and the `shared` folder under `TRAJECTORY_DIR` (`/data/trajectories`) and the older `WINGMAN_TRAJECTORY_DIR` (`/data/wingman-trajectories`). The count is the records deleted |

Every store-level attempt writes a `gdpr_purge_log` row, with how many rows, vectors, files or records it really removed in `affected_count`. `GET /api/gdpr/users/{user_id}/receipts` returns the audit trail, with that count as `affected`. `/settings/gdpr` shows it in the **Removed** column.

## Field encryption

[`crypto.py`](../../apps/api/app/core/crypto.py) wraps a value with AES-256-GCM and stores it as `v1:<base64>`. The cluster KEK is a 32-byte key, base64 encoded, in `ABENIX_DATA_KEY_KEK_BASE64`. Keep it in a secret manager. The per-tenant DEK is `HMAC-SHA256(KEK, tenant_id)`, so every pod derives the same key and no key rows are stored.

It is used today for the tenant Slack webhook URL, the approval webhook secret, MCP connection secrets, tool credentials and held moderation text. PersonaItem and AgentMemory have `encrypted` and `key_version` columns, but nothing encrypts their content yet.

With no KEK set, or one that does not decode to 32 bytes, `encrypt` returns the plaintext unchanged. Set the KEK in production.

## Reranking + citation anchors

`hybrid_search` fetches extra candidates and reranks them when a reranker is on ([`reranker.py`](../../apps/agent-runtime/engine/knowledge/reranker.py)).

- Cohere `rerank-english-v3.0` runs when `COHERE_API_KEY` is set.
- The Claude Haiku scorer runs only with `RERANKER_PROVIDER=llm`, since it adds a model call to every search.
- Otherwise results keep their retrieval order. `RERANKER_PROVIDER=none` turns reranking off.

Every chunk hit carries `metadata.citation` with `document_id`, `document_name`, `page`, `chunk_index`, `char_offset_start`, `char_offset_end` and `anchor_url`, a label such as `contract.pdf · page 42 · chunk 3` that agents can cite.

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

## Conflict list cursor

`GET /api/knowledge/cognify-conflicts` takes `status` (default `open`), `limit` (default 50, at most 200) and `cursor`, and returns `items` plus `next_cursor`. Pass `next_cursor` back as `cursor` for the next page. Other list endpoints in this stack keep fixed limits. The cognify job list returns the latest 20.

## Migration

One migration, `b8c9d0e1f2g3_v2_knowledge_atlas_persona.py`, adds:
- documents: parent_document_id, version_number, is_current, superseded_by, cognified_at, last_cognify_job_id, extraction_method, extraction_quality
- atlas_nodes/edges: valid_from, valid_to, recorded_at, source_anchors
- persona_items: deleted_at, deleted_by, encrypted, key_version
- agent_memories: deleted_at, deleted_by
- new tables: document_grants, cognify_configs, cognify_conflicts, gdpr_purge_log

Every new column is nullable or has a server default, so existing rows need no data move.

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
