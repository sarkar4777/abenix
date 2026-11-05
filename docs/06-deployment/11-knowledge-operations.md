# Knowledge operations

How large collections are re-embedded, deleted and erased, how to watch them, what limits a tenant, and how connectors keep a collection in step with its source. Backups have their own page, [disaster recovery](disaster-recovery.md#backups).

## Re-embedding

A job in `kb_reembed_jobs` runs in slices of `KB_REEMBED_SLICE_SECONDS`, 600 by default, and each slice queues the next, so no task time limit bounds the corpus.

| Stage | What happens | Search sees |
|---|---|---|
| Staging | Each document is re-chunked and embedded, one transaction per embedding batch, into rows with the next `embedding_generation`. Pinecone collections write to the namespace `<kb>.g<n>` | The old vectors |
| Flip | One row update on `knowledge_collections` sets the model and generation, after checking under lock that no document arrived unseen | The new vectors, at once |
| Cleaning | Old rows go in batches of `KB_REEMBED_DELETE_BATCH`, the old namespace goes, counts are written | The new vectors |

Pause stops after the document in hand. A crash, an outage or a spend limit leaves the job `paused` or `failed`, resume continues from the last finished document and pays only for the one that was in progress. Cancel removes what was staged and never touches search. A document that changes during a job is staged again before the flip. The scheduler resends any job with no heartbeat for `KB_JOB_STALE_MINUTES`, 15 by default.

Chunk metadata the owner stored, such as `policy_id`, now survives a re-embed.

## Deleting a collection

`DELETE /api/knowledge-bases/{id}` sets `deleted_at` and answers straight away. From that commit the collection is gone from every ORM read, search, the search cache and quota usage. A worker then removes it in phases, graph, vectors, chunks, documents and files, dependent rows, the collection itself. Every phase can repeat, and if Neo4j is down while it holds entities the job waits in `waiting` and the scheduler tries again. `GET /api/knowledge-bases/{id}/delete-status` shows progress and stays readable afterwards.

Stored files are removed for plain paths and `file://`, `s3://` and `az://` URIs.

## Erasing a person

The GDPR purge has a `knowledge` step that runs first.

- Documents the person uploaded go with their chunks in every generation, vectors, files, grants and Cognify results. A document with no recorded uploader counts as theirs in a collection they created, unless a connector brought it in. `documents.uploaded_by` records this from now on.
- Neo4j provenance comes first. Their document ids leave `source_doc_ids` on entities and relationships, and anything left with no source is deleted, in Neo4j and in the Postgres mirror. If Neo4j is unreachable and holds such entities the step fails and keeps the documents, so a repeat can finish it.
- Other people's documents that name the person by email or full name lose the matching chunks and their original file, since the file cannot be edited. `storage_url` becomes empty and `error_message` says why. This also matches anyone else with the same full name in that tenant, so check the receipt count.
- Pinecone text can only be read back from vector metadata, so mentions there are found by fetching every vector of the tenant's Pinecone collections. That is slow on a large tenant.
- What they searched for is erased from `kb_query_invocations` and `retrieval_feedback`.

## Limits per tenant

Set under Settings, Token Quotas, or `PUT /api/admin/knowledge-quotas`. Empty means no limit, zero means nothing more.

| Limit | Enforced at |
|---|---|
| `max_documents`, `max_storage_bytes` | Uploads, bulk and planned uploads, connector syncs, Source Watch, `knowledge_store` |
| `max_chunks` | Ingest once a document's chunk count is known, `knowledge_store` |
| `monthly_embedding_usd` | Before each embedding batch in ingest and re-embed. A re-embed pauses and says why |
| `monthly_cognify_usd` | When a Cognify job is requested. Spend is recorded when the job finishes, so one job can pass the limit |

An API refusal is 429 with `error_code` `KNOWLEDGE_QUOTA_EXCEEDED`. Embedding spend is an estimate at about four characters a token and list prices, since the providers' usage figures are not read. It resets on the 1st, UTC.

## Metrics

Workers serve Prometheus on `WORKER_METRICS_PORT`, 9108 in the chart. `monitoring.enabled` adds a PodMonitor and the Grafana dashboard `Abenix Knowledge Operations` from `infra/helm/abenix/dashboards`. Minikube observability scrapes the same port.

| Metric | Meaning |
|---|---|
| `abenix_kb_documents_processed_total{status}` | Ingest rate by outcome |
| `abenix_kb_chunks_ingested_total` | Chunks written |
| `abenix_kb_queue_depth{queue}` | Tasks waiting, read from the broker at scrape time |
| `abenix_kb_embed_failures_total{reason}` | Embedding calls that failed |
| `abenix_kb_cognify_jobs{status}`, `abenix_kb_cognify_documents_pending` | Cognify progress |
| `abenix_kb_reembed_jobs{status}`, `abenix_kb_reembed_chunks_done` | Re-embed progress |
| `abenix_kb_delete_jobs{status}` | Collection deletes |
| `abenix_kb_connector_sources{status}`, `abenix_kb_connector_items_failed` | Connector health |
| `abenix_kb_task_runs_total`, `abenix_kb_task_duration_seconds` | Every knowledge task |

Each worker pod reports the database gauges, so dashboards take `max`.

## Connectors

Add one on the collection's engine page or through `POST /api/knowledge-bases/{id}/connectors`. A sync runs in slices on the `documents` queue, the scheduler starts the due ones each minute.

| Source | Finds changes by | Finds deletes by | ACL captured | Tested against |
|---|---|---|---|---|
| S3 compatible | ETag per key | A finished listing that did not see the key | Object ACL when asked, S3 grantees are accounts so nothing maps to a person | MinIO |
| Azure Blob | ETag per blob | A finished listing | Container level only, Azure has no per person blob ACL | Azurite |
| SQL by query | Hash per row, or a watermark column | A finished listing, or an id pass with a watermark | An allowed emails column becomes grants | Postgres |
| Filesystem or NFS | Modified time and size | A finished walk | Owner, group and mode, stored only | A local folder |
| SharePoint and OneDrive | Graph delta token | Delta feed | Item permissions become grants | **A fake transport only, never called for real** |
| Confluence | Page version | A finished listing | Page read restrictions become grants. Space permissions are not read | **A fake transport only, never called for real** |
| Google Drive | Full listing, then the changes feed | Changes feed | File permissions become grants | **A fake transport only, never called for real** |

The first sync of a SaaS source is its real test. The screen says so on those three.

Behaviour shared by all of them.

- **Cursor per source.** Each page commits its results and its cursor together. A crash resumes at the page in hand. A paused source keeps its place.
- **Retries.** Timeouts, 429 and 5xx back off and honour `Retry-After`. A file that still fails is marked `failed` and tried on the next pass, and a delta source stays on its old token until then. A source that keeps failing waits longer each time, up to a day.
- **Deletes.** A pass that would remove more than `KB_CONNECTOR_MAX_DELETE_FRACTION`, 0.5 by default, of ten or more items, or all of them, removes nothing and waits for someone to confirm. That is usually a wrong prefix or an empty mount.
- **ACLs.** Restricted at the source means restricted here. Emails map to users in the tenant by address, the connector's creator always keeps access, and a group or an unknown address grants nobody, so a remote group's members cannot read until they have their own grant.
- **File types and sizes.** The same types as upload. Archives and other types are recorded as `skipped` with the reason. `KB_CONNECTOR_MAX_ITEM_BYTES` caps one item, 200 MB by default.
- **Backlog.** Listing waits when more than `KB_CONNECTOR_MAX_BACKLOG` of a collection's documents are still processing.
- **Credentials.** Secret fields go to `tenant_tool_credentials`, encrypted with the cluster key when `ABENIX_DATA_KEY_KEK_BASE64` is set. Without a key the screen warns that they are not.
- **Outbound rules.** Every HTTP call and redirect goes through `url_guard`. S3 endpoints and SQL hosts are checked before use. Private addresses need `KB_CONNECTORS_ALLOWED_HOSTS` or `CONNECTORS_ALLOW_PRIVATE_TARGETS`. boto3 and database drivers connect themselves, so a name that changes address after the check is not caught for those two.
- **SQL.** One statement, starting with `SELECT` or `WITH`, in a read only transaction on Postgres, MySQL and Oracle. MySQL, SQL Server and Oracle drivers beyond PyMySQL are not in the image, and only Postgres has run here.
- **Filesystem.** Off until an operator sets `KB_CONNECTOR_FS_ROOTS`, admins only, and links pointing out of the folder are ignored. Mount the share with `worker.extraVolumes` and `worker.extraVolumeMounts`.

An updated file keeps its document row and goes through ingest again, so its old chunks leave search while the new ones are written. Removing a connector keeps the documents it brought in.

## Archives

The worker extracts no archive formats. ZIP, TAR, GZ and similar are refused with a reason. DOCX, PPTX, XLSX, ODT and EPUB are zip containers, so before any parser opens one its directory is checked for traversal paths and against `ARCHIVE_MAX_ENTRIES` (20,000), `ARCHIVE_MAX_TOTAL_BYTES` (2 GiB) and `ARCHIVE_MAX_RATIO` (200 on parts over 10 MB). Source Watch workbooks and code asset archives use the same check, and a code asset tar with a link or device is refused.
