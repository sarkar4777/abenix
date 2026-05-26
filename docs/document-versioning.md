# Document versioning + how queries handle a replaced document

Abenix tracks every uploaded document as a version. Replacing a contract, manual, or report with a corrected version is one API call. Existing agents and queries automatically resolve to the new version — no code change anywhere.

## Replace a document

```
POST /api/knowledge/{kb_id}/documents/{doc_id}/replace
{
  "new_filename": "contract-v2.pdf",
  "new_storage_url": "/data/uploads/<kb>/<new-blob>",
  "new_file_type": "application/pdf",
  "new_file_size": 482917
}
```

The old document row is marked `is_current=false, superseded_by=<new_id>`. The new row becomes the current head with `version_number = old.version_number + 1`.

## What happens to existing queries

Three things resolve automatically:

### 1. Knowledge-base search

Agents asking `knowledge_search("contract X")` get chunks from the **new version only**. The search layer pre-filters by `is_current=true` before similarity scoring, so superseded chunks never enter the candidate pool. Citations returned to the agent point at the new file with page + chunk anchors.

If you need an explicit audit query against historical state, pass `include_superseded=true` to the search endpoint.

### 2. Atlas (knowledge graph)

Atlas uses **bi-temporal edges**. Every relationship in the graph has:

- `valid_from` — when the fact became true in the world
- `valid_to` — when it stopped being true (NULL = still true)

When you replace a document, Cognify re-runs against the new version and:

- Closes out edges derived from the old document (sets `valid_to = supersede_time`).
- Opens new edges from the new document (sets `valid_from = now, valid_to = NULL`).
- Merges entities by canonical name, so an existing "Counterparty Acme Corp" node is enriched, not duplicated.

Default Cypher queries the agents use already filter `WHERE r.valid_to IS NULL`. They see only the current state. Historical queries use the `atlas_as_of(timestamp)` tool:

```
atlas_as_of(graph_id=..., as_of="2025-01-15T00:00:00Z")
```

returns the graph as it existed on January 15th, before the replacement.

### 3. Cognify (graph builder)

The next Cognify job only processes documents where:

- `is_current = true`, AND
- `cognified_at IS NULL OR updated_at > cognified_at`

So the new version of a 10k-document KB doesn't re-process 10k docs — only the replaced one (and any other recent uploads). The superseded document is excluded from the frontier.

## What the agent sees, end to end

A line manager asks the agent **"What are the current termination clauses in contract Acme-2024?"**

1. Agent calls `knowledge_search(query="termination Acme-2024")`.
2. Hybrid search returns chunks from version 2 only.
3. Agent calls `atlas_describe(entity="Acme-2024")` to fetch related entities.
4. Atlas returns the v2-era termination obligation edges.
5. Agent composes the answer with citations like `Acme-2024.pdf · v2 · page 17 · chunk 4`.

The same agent, asked **"What were the termination clauses before the November amendment?"** uses `atlas_as_of("2024-10-15T00:00:00Z")` and gets the v1 edges that had `valid_to = "2024-11-01T..."` (closed when the supersede happened).

## Auditor + compliance workflow

Every replace operation writes an `activity_log` row tagged `document.replaced` with the old doc ID, new doc ID, and version number. The `activity_log` is append-only, so an auditor can reconstruct the timeline of any document.

The `/api/gdpr/users/{id}/receipts` endpoint covers the parallel right-to-erasure path — see [GDPR docs](sso.md) (same admin surface).

## Limits

- A document chain has no version cap. A contract amended 50 times has 50 rows.
- `superseded_by` is a single pointer — branched versions (forks) are not modeled. If you need divergent branches, create them as separate documents and use document grants to scope visibility.
- The Pinecone storage for superseded versions stays until GDPR or a manual delete on the KB. Cost amortizes well — only the active chunks are scored on every query.

## Related

- [`docs/02-runtime/15-v2-knowledge-enterprise.md`](02-runtime/15-v2-knowledge-enterprise.md) — the full developer reference
- [`docs/02-runtime/10-pipeline-healing-drift.md`](02-runtime/10-pipeline-healing-drift.md) — the Surgeon's view of pipeline-level versioning
