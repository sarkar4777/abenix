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

A replace does not change the Atlas graph. To see an Atlas graph as it stood before a change, agents call `atlas_as_of`:

```
atlas_as_of(graph_id=..., as_of="2025-01-15T00:00:00Z")
```

It reads the newest snapshot saved at or before that time, or the live graph when nothing has changed since. With no snapshot that old it says so instead of guessing.

### 3. Cognify (graph builder)

The next Cognify job only processes documents where:

- `is_current = true`, AND
- `cognified_at IS NULL OR updated_at > cognified_at`

So the new version of a 10k-document KB doesn't re-process 10k docs — only the replaced one (and any other recent uploads). The superseded document is excluded from the frontier.

## What the agent sees, end to end

A line manager asks the agent **"What are the current termination clauses in contract Acme-2024?"**

1. Agent calls `knowledge_search(query="termination Acme-2024")`.
2. Hybrid search returns chunks from version 2 only.
3. Agent composes the answer with citations like `Acme-2024.pdf · page 17 · chunk 4`, read from each hit's `metadata.citation`.

Asked how the contract ontology looked before the November amendment, the agent calls `atlas_as_of(as_of="2024-10-15T00:00:00Z")` and gets the Atlas graph from the newest snapshot saved by then.

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
