# Knowledge at terabyte scale

How uploads, ingest and vector search behave once a collection stops being small, what to set, and how much hardware it takes.

## Uploads

| Size | Route | What happens |
|---|---|---|
| Up to 32 MB in the web app | `POST /upload` | Multipart. The parser spools to the API's temp directory and the file is hashed and copied from there |
| Many small files | `POST /upload-bulk` | The same per file, with its own answer for each one, up to `KB_BULK_MAX_FILES` |
| Large, local storage | `POST /uploads` then `PUT /uploads/{token}/content` | Raw body written straight to storage in blocks, nothing on the API disk |
| Large, S3 or Azure | `POST /uploads` then parts to storage then `POST /uploads/{token}/complete` | The bytes never pass through the API |

A file past `KB_DIRECT_UPLOAD_MIN_BYTES` on S3 or Azure gets the direct plan. The browser sends parts itself, so the bucket needs a CORS rule that allows `PUT` from your site and exposes the `ETag` header. Add a lifecycle rule that aborts incomplete multipart uploads after a few days, an abandoned upload otherwise keeps its parts.

`content_sha256` is unique per collection among current versions. A repeat of a stored file answers 200 with `duplicate: true` and costs nothing. A repeat of a file that failed answers `resumed: true` and goes on from its checkpoint. On a direct upload the API never sees the bytes, so the worker hashes the downloaded file, and a declared hash that does not match ends the document `FAILED`.

PPTX, XLSX, HTML and MSG read through `python-pptx`, `openpyxl`, the standard library and `olefile`, all in the worker image. `unstructured` is not needed for them.

## Ingest

A worker reads a document as a stream and holds about one window of text, `KB_CHUNK_WINDOW_CHARS`, plus the batches being embedded. Peak traced memory for the text path was 3.4 MB for a 24 MB file and 3.4 MB for a 103 MB file. PPTX loads the whole deck and vision extraction loads the whole file, so those two still follow file size.

Each batch is written in one transaction with `documents.ingest_checkpoint`. A rerun of any kind skips the chunks already stored and pays for none of them again.

| What happens | What the document does |
|---|---|
| Worker killed, for instance out of memory | Celery redelivers it, and it resumes. `ingest_attempts` counts starts since the last progress, past `KB_INGEST_MAX_ATTEMPTS` it ends `FAILED` and says why |
| A run reaches `KB_INGEST_SLICE_SECONDS` | Requeues itself at the checkpoint, so one huge file does not hold a worker past the task limit and a stopping pod finishes a slice inside its grace period |
| Provider answers 429 or 5xx | Waits. All workers pause for the `Retry-After`, a long wait goes back to the queue. After `KB_INGEST_MAX_WAIT_SECONDS` with no progress it ends `FAILED` with the chunks stored so far, upload it again to finish it |
| Provider refuses the key, 401, 403 or `insufficient_quota` | The only case that moves an empty collection to the hashing embedder. With vectors already stored it stops `DEGRADED` instead |
| Re-embed flips the collection mid document | Restarts at the new generation |

Embedding calls run `KB_EMBED_CONCURRENCY` at a time per task, and every worker draws from one token bucket in Redis, `KB_EMBED_RPM` and `KB_EMBED_TPM`. Set those to your provider tier. If Redis does not answer each process limits itself.

## Scaling workers

CPU says nothing about a worker that is waiting on an embedding provider. Set `worker.autoscaling.kind: keda` to scale on the length of the `documents` list in Redis, `worker.autoscaling.keda.listLength` per pod. It needs the KEDA operator. `worker.terminationGracePeriodSeconds` is longer than a slice, so a scale down finishes its work first. A pod killed outright waits for `CELERY_VISIBILITY_TIMEOUT`, six hours by default, before its message comes back.

Files from object storage are downloaded to `/tmp` while they are read, `worker.tmpSizeLimit` is the largest file a worker can take.

Throughput is capped by the provider long before the database. At the 1,000,000 tokens per minute of a first tier OpenAI account and 250 tokens a chunk, that is 4000 chunks a minute, about 4.6 GB of plain text a day. A terabyte of plain text is about 310 billion tokens, $6,250 at `text-embedding-3-small` list price, and needs around 217 million tokens a minute to finish in a day. Ask for a higher tier first.

## The chunks table

A new install hash partitions `chunks` by `collection_id` into `KB_CHUNK_PARTITIONS` partitions, 32 by default and fixed once created. A collection lives in one partition, so its reads, its index pages and its vacuum stay out of everyone else's way.

An existing table is left alone until you choose to move it. Run this during a quiet period.

```bash
DATABASE_URL=postgresql://... python scripts/kb-chunks-partition.py --partitions 32
# look around, then
DATABASE_URL=postgresql://... python scripts/kb-chunks-partition.py --drop-legacy
```

The copy and the index build touch only the new table. Writers wait during a short final catch up and readers do not wait at all. The old table stays as `chunks_legacy`. Swapping back means renaming the two tables by hand, and rows written since are lost. The script needs free disk for a second copy of the table and its index.

### Bulk loading a new collection

Create the collection with `index_mode: deferred`. Rows skip the shared HNSW, so a load runs at full `COPY` speed, and search stays correct with an exact scan. When the load is done, call `POST /api/knowledge-bases/{id}/index/build`. The worker builds one HNSW for that collection with `CREATE INDEX CONCURRENTLY`, and writes and search keep working during the build. The state goes `deferred`, `building`, `dedicated`. A collection that already has chunks cannot defer. An unpartitioned table refuses too, because its shared index would still charge for every row.

Parallel HNSW builds use `/dev/shm`. A build fails with `could not resize shared memory segment` when that is the 64 MB a container gets by default. Mount a memory backed volume there, as large as `maintenance_work_mem`. The chart's Postgres has one by default.

### Search

| Collection | How it is searched |
|---|---|
| Up to `KB_EXACT_SCAN_MAX_CHUNKS` | Exact scan. Full recall and no index needed |
| `deferred` or `building` | Exact scan, slow on a big load |
| Larger, pgvector 0.8 or newer | HNSW with iterative scan, so filters do not eat the page |
| Larger, older pgvector | HNSW with `hnsw.ef_search` raised per query |
| HNSW returned a short page, pgvector 0.8 or newer | A second pass that may walk `KB_HNSW_DEEP_SCAN_TUPLES` |
| Still short | Exact scan under `KB_EXACT_FALLBACK_TIMEOUT_MS`. If that runs out of time the response says so in `degraded` and is not cached |

A shared index holds several collections, and it walks the vectors closest to the query first. When those belong to another collection, a plain HNSW query filters every candidate out and answers nothing. That was seen live, a collection of 300,000 rows answered with no results behind a collection of 15,000 rows with closer vectors. The passes above exist for that shape, the numbers are below.

The search reads the version from `pg_extension`, and the API runs `ALTER EXTENSION vector UPDATE` at start so a newer image takes effect. `GET /api/knowledge-bases/{id}/index` shows the version in use. `infra/docker/Dockerfile.postgres-pgvector` is pinned to pgvector 0.8.7.

Search reads no ids it does not need. Hidden documents are counted and hashed in the database for the cache key, and up to `KB_HIDDEN_INLINE_MAX` ids travel. Past that the access rule runs in SQL. Past that cap graph results are left out and the response says so, because the graph filter needs the whole list.

Pinecone gets the same cap as a `$nin` list, `KB_PINECONE_NIN_MAX`. Past it nothing is listed, three times as many results are fetched and each returned document is checked against Postgres. Replacing a document stamps its vectors `superseded`, which the filter excludes. Vectors of documents replaced before this change are not stamped and rely on that check.

Each collection has `search_language` for keyword matching and for choosing the Cohere model, and `rerank_mode`, `auto` or `off`. New collections use `simple`, which works for every language and does no stemming. Collections that existed before the migration keep `english`. Reranking takes at most `KB_RERANK_MAX_CANDIDATES` results, `KB_RERANK_PER_MINUTE` calls per tenant and `KB_RERANK_TIMEOUT_SECONDS`, and past any of those the retrieval order stands.

Keyword search has no index, so on a big collection it stops at `KB_KEYWORD_TIMEOUT_MS`. If you rely on it, add one per partition in the matching language.

```sql
CREATE INDEX CONCURRENTLY ON chunks_p000 USING gin (to_tsvector('simple', content));
```

## Sizing

Measured on PostgreSQL 16 with pgvector 0.8.7 in a Docker container on an 18 core laptop, 1536 dimensions, synthetic clustered vectors and 800 characters of chunk text. Treat the rates as ratios between methods, your disks decide the absolute numbers.

| Measurement | Result |
|---|---|
| Row by row through HNSW, the old write path, 10,000 rows | 160 rows a second |
| `COPY` in batches of 100 through HNSW, 10,000 rows | 248 rows a second |
| `COPY` with the index deferred, 300,000 rows | 7,145 rows a second |
| HNSW build after a deferred load of 330,000 rows with `maintenance_work_mem` 1 GB, 4 workers | 193 seconds |
| The same kind of build that fits in memory, 200,000 rows with 2 GB | 37 seconds |
| Search on the 330,000 row collection, top 10 | p50 14.5 ms, p95 43 ms, recall 0.93. 30,000 rows were exact copies of others, and a tie counts as a miss, so this reads low |
| Same collection, filter hides 91 percent of the rows | p50 13 ms, p95 24 ms, recall 0.91, full pages |
| Exact scan of that collection while it was still deferred | p50 3.6 s, p95 6 s |
| 200 row collection in the same partition as the big one | p50 5 ms, recall 1.0 |
| 30,000 row collection in the same partition | p50 138 ms, recall 1.0 |
| Partition script, 200,200 rows | 88 seconds, writers waited 0.5 seconds |

The crowded shape, 300,000 rows far from the query behind 15,000 rows close to it, on one shared index, 40 queries each.

| Query | pgvector 0.8.7 unpartitioned | pgvector 0.8.7 partitioned | pgvector 0.7.4 unpartitioned |
|---|---|---|---|
| Old query, results out of 20 | 0.0 | 0.0 | 0.0 |
| Big collection, top 10 returned | 10 of 10, p50 1468 ms | 10 of 10, p50 860 ms | 10 of 10, p50 2192 ms |
| Big collection, top 50 returned | 50 of 50, p50 824 ms | 50 of 50, p50 789 ms | 50 of 50, p50 2134 ms |
| Big collection with a tenth of its rows hidden | 10 of 10, p50 806 ms | 10 of 10, p50 644 ms | 10 of 10, p50 1373 ms |
| Small collection, top 10 | 10 of 10, p50 86 ms | 10 of 10, p50 82 ms | 10 of 10, p50 122 ms |

Slow beside the small numbers above because the scan has to walk past the other collection first. A collection that big does better with its own index, which today means loading it with `index_mode: deferred`.

A row costs this much. Heap and TOAST grow by whatever your chunk text and metadata weigh after compression.

| Per chunk | `vector` | `halfvec` |
|---|---|---|
| Table with TOAST | 9.3 KB | 5.2 KB |
| HNSW, `m` 16 | 8.2 KB | 4.1 KB |
| Total | 17.5 KB | 9.3 KB |
| Recall at 10 on 100,000 rows, identical settings | 0.998 | 1.0 |
| p50 on 100,000 rows | 10.7 ms | 9 ms |

`halfvec` needs pgvector 0.7. Set `KB_VECTOR_STORAGE=halfvec` before the first start, or pass `--storage halfvec` to the partition script. It stores 16 bit floats, so recall held on this data but was not tested on real embeddings. Reducing dimensions through the provider is not offered, the column is fixed at 1536.

Working out chunks from source. Chunks are 1000 characters with 200 of overlap, so a chunk adds 800 characters of text. PDFs and office files commonly hold 10 to 20 percent text by size, plain text is all text.

| Source | Chunks | `vector` disk | `halfvec` disk | HNSW to keep in RAM, `vector` |
|---|---|---|---|---|
| 100 GB of PDFs at 15 percent text | 19 million | 330 GB | 175 GB | 155 GB |
| 1 TB of PDFs at 15 percent text | 190 million | 3.3 TB | 1.8 TB | 1.5 TB |
| 1 TB of plain text | 1.25 billion | 22 TB | 11.6 TB | 10 TB |

Those three rows are arithmetic from the per chunk numbers and were never loaded. The largest collection measured is 330,000 chunks, so test at your own size before you commit to one. Add WAL, vacuum head room and backups on top of the disk figures, and plan for twice the table size free during the partition script.

- Latency depends on HNSW staying in memory. Give `shared_buffers` plus page cache at least the index size of the collections you search often. A partition that is cold costs nothing, which is what partitioning buys.
- Build with `maintenance_work_mem` above 8.2 KB times the rows, about 2.5 GB per 300,000 rows, otherwise the build runs far slower, as the two build rows above show.
- Past about 100 million chunks in one Postgres node, this guide stops being evidence. Consider Pinecone for those collections.
- A worker holds about 115 MB per busy process on the text path. A 100 MB text file finished inside a 1 GiB container with a peak of 221 MB for the whole container, while the old code hit the limit on the same file and went round 27 kills with nothing stored. At the 1 GiB limit lower `CELERY_CONCURRENCY` from its default of 8 to about 6, or raise the limit.
- Redis holds one message per document, so bulk uploads do not need a bigger Redis.

Every run above came from a throwaway container with `--shm-size=6g`, `shared_buffers=2GB`, `maintenance_work_mem=2GB` unless the row says otherwise.

### Postgres settings in the chart

The image defaults are `shared_buffers` 128 MB and `maintenance_work_mem` 64 MB, which make an index build spill to disk and keep little of an index in memory. The chart sets these through `postgresql.primary.extendedConfiguration`, and they take effect at the next rollout of Postgres.

| Values file | Memory limit | `shared_buffers` | `effective_cache_size` | `maintenance_work_mem` | Parallel build workers |
|---|---|---|---|---|---|
| `values-local.yaml` | 2 GiB | 512 MB | 1 GB | 256 MB | 2 |
| `values-azure.yaml` | 1 GiB | 256 MB | 768 MB | 128 MB | default |
| `values.yaml` | 4 GiB | 1 GB | 3 GB | 1 GB | 2 |
| `values-production.yaml` | 8 GiB | 2 GB | 6 GB | 2 GB | 4 |

Keep `shared_buffers` near a quarter of the limit. A build holds up to `maintenance_work_mem` in memory backed `/dev/shm`, which counts against the pod, so keep the two together under the limit. These limits do not hold terabytes. Size the limit from the HNSW column in the table above for the collections you search often.

## Settings

| Variable | Default | What it does |
|---|---|---|
| `KB_MAX_UPLOAD_BYTES` | 20 GiB | Largest file. Keep `ingress.maxBodySize` above it |
| `KB_DIRECT_UPLOAD_MIN_BYTES` | 64 MiB | From this size a plan goes straight to S3 or Azure |
| `KB_BULK_MAX_FILES` | 200 | Files in one `upload-bulk` request |
| `KB_INGEST_BATCH_CHUNKS` | 100 | Chunks per embedding call and per checkpoint |
| `KB_EMBED_CONCURRENCY` | 4 | Embedding calls at once per task |
| `KB_CHUNK_WINDOW_CHARS` | 262144 | Text held while chunking |
| `KB_INGEST_SLICE_SECONDS` | 600 | Time before a run requeues itself |
| `KB_INGEST_MAX_ATTEMPTS` | 5 | Starts with no progress before `FAILED` |
| `KB_INGEST_MAX_WAIT_SECONDS` | 86400 | How long a document waits for a failing provider |
| `KB_EMBED_RPM` / `KB_EMBED_TPM` | 3000 / 1000000 | Shared budget for each provider |
| `KB_EMBED_INLINE_RETRIES` / `KB_EMBED_INLINE_WAIT_MAX` | 4 / 60 | Waits a worker sits through before going back to the queue |
| `KB_RATE_REDIS_URL` | `REDIS_URL`, then the broker | Where the bucket lives |
| `KB_CHUNK_PARTITIONS` | 32 | Partitions of a new table |
| `KB_VECTOR_STORAGE` | `vector` | `halfvec` on a new table, needs pgvector 0.7. The partition script takes `--storage halfvec` |
| `KB_EXACT_SCAN_MAX_CHUNKS` | 20000 | Largest collection searched exactly |
| `KB_HNSW_DEEP_SCAN_TUPLES` | 2000000 | How far the second pass goes after a short page |
| `KB_EXACT_FALLBACK_TIMEOUT_MS` | 30000 | Time limit of the exact scan after HNSW came back short |
| `KB_HNSW_EF_SEARCH` | 100 | Floor for `hnsw.ef_search`, it also grows with the page size |
| `KB_HNSW_MAX_SCAN_TUPLES` | 50000 | How far an iterative scan goes |
| `KB_HIDDEN_INLINE_MAX` | 1000 | Hidden ids sent with a query |
| `KB_PINECONE_NIN_MAX` | 1000 | Largest `$nin` list |
| `KB_RERANK_MAX_CANDIDATES` | 50 | Results sent to the reranker |
| `KB_RERANK_PER_MINUTE` | 60 | Rerank calls per tenant |
| `KB_RERANK_TIMEOUT_SECONDS` | 8 | Time before retrieval order stands |
| `KB_KEYWORD_TIMEOUT_MS` | 15000 | Time limit of a keyword search |
| `KB_INDEX_MAINTENANCE_WORK_MEM` / `KB_INDEX_PARALLEL_WORKERS` | what Postgres has / 4 | Used when building a deferred index |
