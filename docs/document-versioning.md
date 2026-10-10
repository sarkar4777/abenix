# Document versioning

A knowledge base document can have versions. Each version is its own row in `documents`, linked by four columns on [`Document`](../packages/db/models/knowledge_base.py):

| Column | Meaning |
|---|---|
| `parent_document_id` | The first version of the chain. `NULL` on the first version itself |
| `version_number` | 1 for the first version, one higher for each replacement |
| `is_current` | `true` on the newest version only |
| `superseded_by` | On an old version, the id of the version that replaced it |

Two things create a new version: the replace call below, and Source Watch when it files a changed page into a knowledge base.

## Replace a document

The route is in [`apps/api/app/routers/knowledge_v2.py`](../apps/api/app/routers/knowledge_v2.py). The body names a file that is already in storage.

```
POST /api/knowledge/{kb_id}/documents/{doc_id}/replace
{
  "new_filename": "contract-v2.pdf",
  "new_storage_url": "<tenant>/kb/<kb>/<new-blob>",
  "new_file_type": "application/pdf",
  "new_file_size": 482917
}
```

The call adds a new row with the same `parent_document_id` and `version_number` one higher, and marks the old row `is_current = false` with `superseded_by` set to the new id. It answers 201:

```json
{"id": "<new id>", "version_number": 2, "parent_document_id": "<first version id>", "supersedes": "<old id>"}
```

The checks, in order:

- The collection must be in your tenant and readable by you, else 404. You need edit rights on it, else 403.
- The new file must already be uploaded to this collection, so its storage path sits under the tenant and collection prefix, else 400.
- Replacing a version that is already superseded answers 400. Replace the current head instead.

## What happens next

1. The new version is queued for processing like any upload: extraction, chunking and embedding.
2. Search and Cognify use the current version only. Vector search (pgvector and Pinecone) and graph search drop chunks and facts that come only from a superseded row, and a Cognify run skips superseded rows even when you name them. The old row stays as history.
3. The document list and the knowledge base detail return the current version only. Each row carries `version_number`, `is_current`, `parent_document_id` and `superseded_by`.

## View history

People who can edit the collection, and tenant admins, can see the old versions:

```
GET /api/knowledge/{kb_id}/documents/{doc_id}/versions
GET /api/knowledge-bases/{kb_id}/documents?include_history=true
```

The first returns the whole chain for one document, oldest first. The second returns every row in the collection, current or not. Anyone else gets 403.

To remove an old version for good, delete it with `DELETE /api/knowledge/{kb_id}/documents/{doc_id}`, which also removes its vectors.

## Source Watch

When a watched source has `ingest_to_kb` set, each baseline and changed snapshot becomes a new text document in that knowledge base, and a new version of the previous one from the same source. Like the replace call, Source Watch queues the new document for processing. See [Source Watch](02-runtime/17-source-watch.md#knowledge-base-ingestion).

## Atlas history

Replacing a document does not change any Atlas graph. To see a graph as it stood before a change, agents call `atlas_as_of`:

```
atlas_as_of(graph_id=..., as_of="2025-01-15T00:00:00Z")
```

If the graph has not changed since `as_of`, it reads the live rows. Otherwise it reads the newest snapshot saved at or before that time, and says so when there is none. See [06-atlas-knowledge-engine](01-architecture/06-atlas-knowledge-engine.md#agent-tools).

## Audit

Every replace writes an `activity_logs` row with the action `document.replaced` and the old id, new id and version number in its details. The table is append-only and hash-chained, see [07-governance](01-architecture/07-governance.md#tamper-evident-audit-log).

Erasing a person's data across stores is a separate path, see [GDPR cascade](02-runtime/15-v2-knowledge-enterprise.md#gdpr-cascade).

## Limits

- A chain has no version cap. A contract replaced 50 times has 50 rows.
- `superseded_by` is a single pointer, so branches are not modelled. For divergent versions, upload separate documents and scope them with document grants.

## Related

- [02-runtime/15-v2-knowledge-enterprise](02-runtime/15-v2-knowledge-enterprise.md#document-versioning), the developer reference
- [04-data-model/03-knowledge](04-data-model/03-knowledge.md), the `documents` columns
