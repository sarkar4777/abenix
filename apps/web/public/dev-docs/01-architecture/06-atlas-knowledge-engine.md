# Atlas + Knowledge Engine

Two separate graph systems sit next to each other. They share a knowledge collection id but not a store.

- **Atlas** is the ontology canvas. Graphs, typed nodes and edges, snapshots and bindings to live data, all in Postgres tables. It ships five starter ontologies (FIBO Core, FIX Protocol, EMIR Reporting, ISDA Master Agreement, ETRM EOD Workflow).
- **Knowledge Engine (Cognify)** turns the documents of a knowledge collection into an entity graph in Neo4j. Each node is an `:Entity` keyed by `kb_id` and `canonical_name`. Hybrid search reads that graph next to the vector store.

An Atlas graph can be bound to a knowledge collection (`atlas_graphs.kb_id`), which lets the canvas show the collection's documents and lets agents reach both. Atlas never writes to Neo4j and Cognify never writes Atlas rows.

```mermaid
flowchart LR
  subgraph PG[Postgres]
    AG[atlas_graphs] --> AN[atlas_nodes]
    AG --> AE[atlas_edges]
    AG --> AS[atlas_snapshots]
    GE[graph_entities<br/>graph_relationships]
    CJ[cognify_jobs<br/>cognify_reports]
  end
  subgraph N4J[Neo4j]
    EN[":Entity {kb_id, canonical_name}"]
  end
  AG -. kb_id .-> KB[knowledge_collections]
  KB --> CP[Cognify pipeline]
  CP --> EN
  CP --> GE
  CP --> CJ
```

## Atlas

### Data model

| Table | Holds |
|---|---|
| `atlas_graphs` | One row per graph. Owner, name, optional `kb_id` binding, `version`, node and edge counts, `settings` |
| `atlas_nodes` | Label, `kind`, description, `properties` (JSONB), canvas position, optional `document_id`, `source`, `confidence`, tags, and the bi-temporal columns |
| `atlas_edges` | `from_node_id`, `to_node_id`, label, cardinality, `inverse_edge_id`, `is_directed`, `properties`, `source`, `confidence`, and the bi-temporal columns |
| `atlas_snapshots` | A JSONB copy of the graph per version, made automatically or by hand, for the time slider and restore |

Bi-temporal columns on nodes and edges:

| Column | Meaning |
|---|---|
| `valid_from` | When the fact became true in the world |
| `valid_to` | When it stopped being true. `NULL` means still current |
| `recorded_at` | When the platform learned it |
| `source_anchors` | JSONB list of supporting citations |

Models live in [`packages/db/models/atlas.py`](../../packages/db/models/atlas.py). Column detail is in [04-data-model/03-knowledge](../04-data-model/03-knowledge.md).

### REST

All under `/api/atlas` in [`routers/atlas.py`](../../apps/api/app/routers/atlas.py):

| Route | Does |
|---|---|
| `GET/POST /graphs`, `GET/PATCH/DELETE /graphs/{id}` | Graph CRUD |
| `POST/PATCH/DELETE /graphs/{id}/nodes...`, `/edges...` | Node and edge CRUD |
| `POST /graphs/{id}/parse-nl` | A sentence becomes a list of graph ops |
| `POST /graphs/{id}/extract` | A dropped document, image, audio, video or text becomes proposed nodes and edges, through a vision-capable model |
| `POST /graphs/{id}/apply` | Applies the ops from `parse-nl` or `extract` |
| `GET /graphs/{id}/suggestions` | Suggested additions |
| `GET/POST /graphs/{id}/snapshots`, `POST .../restore` | Snapshots and restore |
| `GET /graphs/{id}/export` | JSON-LD or plain JSON |
| `POST /graphs/{id}/bind-kb`, `/sync-kb`, `/persist-to-kb` | Bind a collection, project its documents onto the canvas as document nodes, write a dropped file into the bound collection |
| `POST /graphs/{id}/query` | Matches a small graph pattern |
| `PATCH /graphs/{id}/nodes/{node_id}/binding`, `GET .../instances` | Binds a node to a live source, such as a collection's documents, and lists its instances |
| `GET /starters`, `POST /graphs/{id}/import-starter` | The starter ontologies |
| `POST /graphs/{id}/relayout` | Recomputes the canvas layout |

### Agent tools

The four typed tools in [`engine/tools/atlas_tools.py`](../../apps/agent-runtime/engine/tools/atlas_tools.py) read the Atlas tables over their own small asyncpg pool on `DATABASE_URL`. They only see graphs in the run's tenant, and only the graphs the agent is granted when a list is set.

| Tool | Does |
|---|---|
| `atlas_describe` | A summary of a graph |
| `atlas_query` | Finds nodes and edges by label pattern |
| `atlas_traverse` | One hop out from a node along its edges |
| `atlas_search_grounded` | Text search over node labels and properties, optionally near a label |

All four return structured rows, not paragraphs. Their input schemas are in [02-runtime/02-tools](../02-runtime/02-tools.md).

`atlas_as_of` shows a graph as it stood at a past moment. It reads the newest `atlas_snapshots` row saved at or before that time, or the live graph when nothing changed since, honouring `valid_from` and `valid_to` on live rows. Inputs are `graph_id`, `as_of`, `label_like`, `kind` and `limit`.

### Adding a starter ontology

Starters are the `ATLAS_STARTERS` dict in [`routers/atlas.py`](../../apps/api/app/routers/atlas.py). Add an entry with a name, description, entity types and relationship types, and `GET /api/atlas/starters` lists it. The canvas "import starter" flow picks it up with no UI change. Add an e2e that imports it and checks the node types.

## Knowledge Engine (Cognify)

### Pipeline

`POST /api/knowledge-engines/{kb_id}/cognify` creates a `cognify_jobs` row and queues the worker task [`cognify_task.py`](../../apps/worker/worker/tasks/cognify_task.py), which runs `run_cognify` in [`engine/knowledge/cognify_pipeline.py`](../../apps/agent-runtime/engine/knowledge/cognify_pipeline.py). The body can name `doc_ids` to limit the run.

1. **Skip check.** If no document changed since the last completed run, the job ends early.
2. **Ontology prior.** The project's active ontology schema, when there is one, is passed to the extractor as a typing hint.
3. **Extract.** `entity_extractor.extract_from_document` asks the configured model for entities and relationships, one document at a time, flushing progress to the job row.
4. **Resolve.** `entity_resolver.resolve_entities` merges duplicates across documents and against entities already in the collection.
5. **Write the graph.** `graph_writer.write_entities` and `write_relationships` `MERGE` into Neo4j as `(:Entity {kb_id, canonical_name})` with typed relationships carrying `kb_id`, so reruns update instead of duplicating.
6. **Postgres metadata.** `graph_entities` and `graph_relationships` rows are upserted and the job gets a `cognify_reports` row: entities by type, top entities by mentions, relationship types.

If Neo4j is not reachable the job fails before extraction with "Neo4j is not available". `GET /api/knowledge-engines/{kb_id}/graph-stats` reports `neo4j_available`. Text extraction from uploaded files happens earlier, in the worker's `document_processor` through the extractors below, when documents are chunked and embedded.

### Reading the graph

| Reader | Uses |
|---|---|
| `hybrid_search.py` | Vector hits plus a graph expansion over `:Entity` nodes for the same `kb_id`, weighted by `graph_weight` and `graph_depth` |
| `knowledge_search` tool | Hybrid search for an agent with a granted collection |
| `graph_explorer` tool | Looks up an entity and its neighbours in Neo4j |
| `GET /api/knowledge-engines/{kb_id}/graph` | The graph for the UI |
| `memify_pipeline.py` | Adjusts the graph from usage signals and retrieval feedback |

Connection settings are `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` and `NEO4J_DATABASE`, read in [`engine/knowledge/neo4j_client.py`](../../apps/agent-runtime/engine/knowledge/neo4j_client.py). `graph_writer.delete_kb_graph` removes a collection's entities.

## v2.0 knowledge features

| Feature | State in code |
|---|---|
| Document versioning, `POST /api/knowledge/{kb}/documents/{doc}/replace` | Marks the old row `is_current = false` and `superseded_by` the new one. Only the current head can be replaced. See [document-versioning](../document-versioning.md) |
| Document grants, `document_grants(document_id, subject_type, subject_id, permission)` | A document with no grants is visible to everyone who can read the collection. The first grant restricts it to its grantees (users or agents), tenant admins, the collection creator and holders of WRITE or ADMIN on the collection. Search drops restricted documents before ranking and the document list hides them. Only collection editors add or remove grants. Rule in [`engine/knowledge/document_acl.py`](../../apps/agent-runtime/engine/knowledge/document_acl.py) |
| Cognify config, `GET/PUT /api/knowledge/cognify-config` | `auto_accept_threshold`, `conflict_action`, `max_parallel_docs`, `daily_budget_usd` per tenant. The pipeline enforces all four. Proposals below the threshold stay out of the graph and are counted in the job report |
| Cognify conflicts, `GET /api/knowledge/cognify-conflicts`, `POST .../{id}/resolve` | Written when sources disagree on an entity's type and `conflict_action` is `flag`. Resolving one writes the chosen type to the graph |
| Re-embed, `GET/POST /api/knowledge/{kb}/reembed` | GET returns the model, the allowed models and job progress. POST with `dry_run: true` estimates, without it queues `kb_reembed`, which re-reads and re-chunks every document, then switches the collection in one step. Nothing changes on failure |
| GDPR purge, `POST /api/gdpr/users/{id}/purge`, `GET .../receipts` | [`services/gdpr_purge.py`](../../apps/api/app/services/gdpr_purge.py) covers postgres, pinecone, neo4j, blob and trajectory and writes a `gdpr_purge_log` row per store with `affected_count`. The neo4j step deletes Cognify entities naming the person and their Postgres graph rows. See [15-v2-knowledge-enterprise](../02-runtime/15-v2-knowledge-enterprise.md#gdpr-cascade) |
| At-rest encryption | AES-256-GCM in [`core/crypto.py`](../../apps/api/app/core/crypto.py) under `ABENIX_DATA_KEY_KEK_BASE64`, with per-tenant keys derived by HMAC. It covers tool credentials, Slack and approval webhooks and MCP secrets. Persona items and agent memories are not encrypted yet. Without a KEK values are stored as entered. See [06-encryption-setup](../08-howto/06-encryption-setup.md) |
| Extractors, [`engine/knowledge/extractors/`](../../apps/agent-runtime/engine/knowledge/extractors/) | `text_pdf`, `vision_pdf` and `office` behind `dispatch.extract_document`, called by the worker on ingest. It records `extraction_method` and `extraction_quality` and chunks carry page numbers. Vision OCR needs PyMuPDF and `ANTHROPIC_API_KEY` on the worker |
| Reranker, [`engine/knowledge/reranker.py`](../../apps/agent-runtime/engine/knowledge/reranker.py) | Wired into search. Cohere when `COHERE_API_KEY` is set, the Haiku scorer only with `RERANKER_PROVIDER=llm`. Hits carry `metadata.citation` |
| Pinecone vacuum, [`worker/tasks/pinecone_vacuum.py`](../../apps/worker/worker/tasks/pinecone_vacuum.py) | Queued daily at 02:30 UTC by the API scheduler on the `documents` queue. Deletes namespaces of deleted collections, vectors past a document's chunk count and persona vectors of deleted items |

## Where to look in the code

- Atlas API: [`apps/api/app/routers/atlas.py`](../../apps/api/app/routers/atlas.py)
- Atlas tools: [`atlas_tools.py`](../../apps/agent-runtime/engine/tools/atlas_tools.py)
- Cognify API: [`knowledge_engine.py`](../../apps/api/app/routers/knowledge_engine.py), v2 routes in [`knowledge_v2.py`](../../apps/api/app/routers/knowledge_v2.py)
- Cognify pipeline and Neo4j: [`apps/agent-runtime/engine/knowledge/`](../../apps/agent-runtime/engine/knowledge/)
- Worker tasks: [`apps/worker/worker/tasks/`](../../apps/worker/worker/tasks/)
- Models: [`atlas.py`](../../packages/db/models/atlas.py), [`knowledge_engine.py`](../../packages/db/models/knowledge_engine.py), [`knowledge_base.py`](../../packages/db/models/knowledge_base.py), [`cognify_config.py`](../../packages/db/models/cognify_config.py), [`document_grant.py`](../../packages/db/models/document_grant.py), [`gdpr_purge_log.py`](../../packages/db/models/gdpr_purge_log.py)
- UI: `/atlas`, [`/settings/cognify`](../../apps/web/src/app/(app)/settings/cognify/page.tsx), [`/settings/gdpr`](../../apps/web/src/app/(app)/settings/gdpr/page.tsx)

## Related

- [02-runtime/02-tools](../02-runtime/02-tools.md), the atlas and knowledge tools with their schemas
- [02-runtime/15-v2-knowledge-enterprise](../02-runtime/15-v2-knowledge-enterprise.md)
- [04-data-model/03-knowledge](../04-data-model/03-knowledge.md)
- [document-versioning](../document-versioning.md)
