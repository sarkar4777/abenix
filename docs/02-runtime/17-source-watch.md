# Source Watch: watched sources, snapshots and changes

> How Abenix fetches the pages, files and feeds a tenant relies on, keeps an immutable copy of each version, records what changed and tells agents and subscribers about it.

---

## What a watched source is

A watched source is a URL the tenant wants checked on a schedule. Each source has:

| Field | Meaning |
|---|---|
| `name` | Unique within the tenant |
| `url` | `http://` or `https://` only |
| `kind` | `html`, `pdf`, `xlsx`, `csv`, `json` or `rss` |
| `cadence_minutes` | How often to check. 5 minutes to 31 days, default 1440 |
| `selector` | Optional. What part to watch, see below |
| `headers` | Optional plain request headers, up to 20 |
| `credentials_key` | Optional. One of `SOURCE_AUTH_1` to `SOURCE_AUTH_5` |
| `jurisdiction`, `tags` | Labels for filtering. Up to 20 tags of 64 characters |
| `risk_tier` | `low`, `medium`, `high` or `critical`. Carried on the event and tool output |
| `ingest_to_kb` | Optional knowledge base that gets each new version |
| `active` | Off when paused by a person or after repeated failures |

Open **Build -> Source Watch** (`/sources`) to add, check, pause and inspect sources. **Add source** previews the document before saving. **Allowlist and limits** holds the tenant settings. Each source has its own page with its changes, snapshots and a **Check now** button.

## How a check runs

The API's scheduler runs the `watch_sources` job every 30 seconds, starting 60 seconds after the process starts.

1. It claims up to 25 active sources whose `next_check_at` has passed, with `FOR UPDATE SKIP LOCKED`, and moves each one's next check forward by its cadence. Several API replicas can run the job without checking the same source twice.
2. Claimed sources are checked in parallel, up to `SOURCE_WATCH_CONCURRENCY` at a time.
3. Each check fetches and normalises with no database transaction open, then records the result under a row lock.

A check ends in one of these statuses, kept in `last_status`:

| Status | Meaning |
|---|---|
| `baseline` | First snapshot, or the reader version changed. Kept as the new reference. No change is recorded |
| `changed` | The readable content differs from the current snapshot. A change is recorded and an event sent |
| `unchanged` | Same bytes, or different bytes with the same readable text |
| `not_modified` | The site answered 304 to a conditional request |
| `error` | The fetch or the reading failed. `last_error` says why |
| `stopped` | A kill switch covers the source |

The sources list also shows a health of `new`, `ok`, `failing`, `paused` or `stopped`.

### Failures and pausing

Each failed check adds to `consecutive_failures`. A successful check resets it. When it reaches the tenant's `pause_after_failures`, the source is paused with a reason naming the last error. Failures to store the snapshot are the platform's fault and do not count. Resuming a source clears the count and schedules a check straight away.

### Conditional requests

Once a source has a snapshot, checks send `If-None-Match` and `If-Modified-Since` from the last response. Changing the URL, kind, selector, headers or credential clears both and schedules a check now. Changing only the cadence reschedules from the last check.

## Fetching and SSRF rules

Every request, and every redirect hop, is checked before it is sent:

- The scheme must be `http` or `https` and the URL must name a host.
- User names and passwords in the URL are refused. Use a source credential.
- The host must be on the tenant's allowlist, when the allowlist is not empty.
- The host is resolved at fetch time. If any address is private, loopback, link-local, multicast, reserved or unspecified, the request is refused. IPv4-mapped IPv6 addresses are checked as IPv4. IP literals get the same check.

`SOURCE_WATCH_ALLOW_PRIVATE_TARGETS` turns the address check off. The allowlist still applies.

Other fetch rules:

- Requests go out as `Abenix-SourceWatch/1.0`.
- Redirects are followed by hand, at most 5.
- Credential headers are sent only to the source's own host. They are dropped on a redirect to any other host.
- One request at a time per host, spaced by `SOURCE_WATCH_HOST_INTERVAL_SECONDS`.
- Bodies over `SOURCE_WATCH_MAX_BYTES` are refused, from `Content-Length` or while streaming.
- Each request times out after `SOURCE_WATCH_TIMEOUT_SECONDS`, connect after at most 10 seconds. A whole fetch is cut off at twice the timeout plus 15 seconds.
- HTTP 400 and above is an error.
- Only these response headers are kept: `content-type`, `content-length`, `etag`, `last-modified`, `date`, `cache-control`, `expires`, `server`, `content-language`.

Plain headers on a source are checked on save. Names must be simple header names, values at most 2,000 characters with no line breaks. `Authorization`, `Cookie`, `Proxy-Authorization` and `X-Api-Key` are refused as plain headers and must go in a credential. `Host` and `Content-Length` are never sent from a source's headers.

## The allowlist

**Allowlist and limits** on the Source Watch page, or `PUT /api/sources/settings`, sets per tenant:

| Setting | Default | Notes |
|---|---|---|
| `host_allowlist` | empty | Host names such as `europa.eu`. An entry covers the host and its subdomains. A leading `*.` is dropped. Up to 500 entries |
| `pause_after_failures` | `SOURCE_WATCH_PAUSE_AFTER` | 1 to 100 |

An empty allowlist allows any public host. The settings live in the tenant's settings under `source_watch`. Changes are written to the audit log as `sources.settings_updated`.

## Credentials

Five tenant secrets, `SOURCE_AUTH_1` to `SOURCE_AUTH_5`, are declared as config fields on the `source_check` tool, in the group "Source Watch". An admin sets them under **Admin -> Tool Configuration -> Source Watch**. A source names one in `credentials_key`. Any other key name is refused.

The stored value becomes a request header:

| Value looks like | Sent as |
|---|---|
| `X-Api-Key: abc` (a header name other than Bearer, Basic or Token, then a colon) | That header |
| A value with a space, such as `Basic dXNlcjpwdw==` | `Authorization: <value>` |
| Anything else | `Authorization: Bearer <value>` |

A source whose credential is not set fails its check with a message saying so. `GET /api/sources/settings` reports which keys are set, never their values.

## Selectors

| Kind | Selector |
|---|---|
| `html` | A CSS subset: tag, `#id`, `.class`, `[attr]`, `[attr=value]`, descendants and comma lists. `>` is read as a descendant |
| `json` | A JSON pointer such as `/data/items` |
| `xlsx` | A sheet name |
| others | No selector. One is refused on save |

An HTML selector that matches nothing adds a note to the snapshot rather than failing.

## Normalisation

Every document is turned into plain text, plus rows for tabular kinds, so formatting noise does not show as a change. All kinds collapse whitespace and runs of blank lines, and drop NUL characters. The reader version is `sw-1` and is stored on each snapshot.

| Kind | What is kept |
|---|---|
| `html` | Visible text. Drops scripts, styles, nav, footer, aside, forms, iframes, buttons and similar, plus elements with a navigation, banner, contentinfo, search or menu role, `aria-hidden="true"` or `hidden`. Headings become `#` lines, list items `- `, table cells are joined with ` \| `, image alt text is kept. The title comes from `<title>` |
| `pdf` | Text per page under `[page N]`, read with pypdf. The title comes from the PDF metadata |
| `csv` | Rows. The delimiter is sniffed from `,` `;` tab and `\|` |
| `xlsx` | Rows per sheet, read from the workbook XML. Booleans become `TRUE` or `FALSE` and `5.0` becomes `5` |
| `json` | The document, or the part the pointer selects, written back with sorted keys and two-space indent. Key order and spacing never show as changes |
| `rss` | RSS or Atom items as rows of id, title, published, link and summary. HTML in titles and summaries is stripped and summaries are cut to 1,000 characters. Feeds that declare XML entities are refused |

Text is decoded using the charset from the response, a byte-order mark or a `<meta charset>`, then UTF-8. Table rows lose trailing empty cells and are capped at 50,000 per table.

`POST /api/sources/preview` runs the fetch and normalisation without saving anything. It returns the detected kind, the first 20,000 characters of text and the first 25 rows of the first table.

## Snapshots

A snapshot is stored only when the bytes differ from the current snapshot. Its row holds the URL after redirects, the SHA-256 of the bytes and of the normalised text, the content type, size, HTTP status, kept headers, fetch time, reader version, title, notes, the text and, for `csv`, `xlsx` and `rss`, the rows.

- The raw bytes go to object storage at `sources/<tenant>/raw/<sha[:2]>/<sha>` and the text at `sources/<tenant>/text/<sha[:2]>/<sha>.txt`. A blob that already exists is not written again.
- Up to 2,000,000 characters of text are kept on the row. Longer texts are marked `text_truncated` and the full text is read from storage with `?full=true`.
- Rows are kept on the row only when they fit in 8,000,000 characters of JSON. Otherwise the diff falls back to text.
- A snapshot is unique per source and SHA-256. If a document goes back to an earlier version, the earlier snapshot is reused and the change points at it.

Snapshots are immutable. A database trigger, `source_snapshots_immutable`, refuses any update to a snapshot row. Deleting a source deletes its snapshots and changes with it. The stored blobs are not removed.

The raw download is sent as an attachment with `Content-Security-Policy: sandbox`, `X-Content-Type-Options: nosniff` and `X-Content-SHA256`. It returns 410 if the blob is gone from storage.

## Diffing

A change is recorded only when the readable content differs. Same bytes, or new bytes with the same text under the same reader version, count as unchanged. A new reader version starts a new baseline instead of reporting a change.

**Text** gets a line diff with three lines of context per hunk, capped at 4,000 lines.

**Tables** are compared sheet by sheet. When the header row is the same and the first column is filled and unique on both sides, it is used as a key and the diff lists rows added, removed and changed, with the columns that changed. Otherwise rows are compared as a multiset, so rows that only moved are not changes. Each list is capped at 2,000 rows per sheet. Added and removed sheets are listed.

Each change carries a one-line summary, the stats and a `materiality_hint` of `high`, `medium` or `low`. The hint is a rough first sort for reviewers, not a judgement.

| Kind | High | Medium | Low |
|---|---|---|---|
| Text | Over 200 changed lines, or at least 6 that are over a quarter of all lines | A changed line has a digit or a word such as shall, must, deadline, penalty, effective, amend, threshold, rate, fee, fine, applies | Anything else |
| Table | A sheet added or removed, or at least 6 rows moved that are over a quarter of all rows | Any row changed or removed, or more than one row added | At most one row added |

## The `source.changed` event

When a change is recorded, `source.changed` is emitted in the same transaction, through the platform event bus. It is not sent for a baseline. Subscribe to it like any other event, see [19-outbound-events](19-outbound-events.md).

| Field | Meaning |
|---|---|
| `source_id`, `name`, `url`, `kind` | The source |
| `jurisdiction`, `tags`, `risk_tier` | The source's labels |
| `change_id` | The recorded change, for `source_diff` or `GET /api/sources/changes/{id}` |
| `snapshot_id` | The new snapshot |
| `previous_snapshot_id` | The snapshot it was compared with |
| `content_sha256` | SHA-256 of the new bytes |
| `fetched_at` | When it was fetched, ISO 8601 |
| `change_summary` | The one-line summary |
| `materiality_hint` | `high`, `medium` or `low` |
| `stats` | The numeric and text stats of the diff |

## Knowledge base ingestion

When `ingest_to_kb` is set, every `baseline` and `changed` snapshot is added to that knowledge base as a text document, through the same processing path as an upload. The text starts with the title, source name, URL, retrieval time, snapshot id and SHA-256. The file is named `<source name> (<fetched at>, <sha 12>).txt`.

Each new document is a new version of the previous one from the same source. The older one is marked not current and superseded by the new one. Pointing the source at a different knowledge base starts a new version chain.

The person saving the source must be able to add documents to that knowledge base. A failed ingestion does not fail the check. The check outcome carries `kb_error` instead.

## Permissions

| Action | Needs |
|---|---|
| List sources, read sources, snapshots, changes and settings | Signed in to the tenant |
| Add, edit, delete, pause, resume, check now, preview, validate a URL | `sources.manage` |
| Change the allowlist and pause threshold | `risk.manage` |

Creators hold `sources.manage` by default and admins hold everything. Users do not. Add, edit, delete, pause and resume are written to the audit log as `source.created`, `source.updated`, `source.deleted`, `source.paused` and `source.resumed`.

`source` is a kill switch scope. A stopped source records `stopped` on its scheduled checks and moves on to its next slot. **Check now** returns 409 with `KILL_SWITCH`. The `source_check` tool refuses it.

## Agent tools

Agents read watched sources through four tools. Each reads only the current tenant's sources. A source can be named by id or by its exact name.

| Tool | Tier | Does |
|---|---|---|
| `source_list` | low | Lists sources with status, last checked, last changed and how many changes were recorded. Filters by `query`, `jurisdiction`, `tag` and `changed_since` |
| `source_snapshot_get` | low | Reads a snapshot's text, the latest by default, with a citation. Pages with `offset` and `max_chars` (500 to 60,000, default 20,000). `find` starts the page 300 characters before the first match |
| `source_diff` | low | Shows a change by `change_id`, or a source's latest change and up to 10 earlier ones. Lines added and removed, or rows per sheet, capped by `max_lines` (10 to 2,000, default 400). Cites both snapshots |
| `source_check` | medium | Asks for a check now and waits up to `wait_seconds` (5 to 120, default 60). Returns the status, and for a change its `change_id` and summary. Refuses paused and stopped sources |

`source_check` sets the source's next check to now and polls every two seconds until the scheduler has run it. If the wait runs out it returns `queued`.

Each citation holds the source, URL, title, retrieval time, SHA-256 and snapshot id, plus a `cite_as` line such as `Carrier tariff page, https://..., retrieved 2026-03-01 (snapshot sha256 3f2a9c1b7d4e)`. Agents should quote from snapshots, which do not change, rather than the live page.

The tools open their own small database pool, sized by `SOURCE_DB_POOL` and `SOURCE_DB_OVERFLOW`.

## REST

All paths are under `/api/sources`.

| Method | Path | Does |
|---|---|---|
| GET | `/api/sources` | Lists sources with snapshot and change counts and the latest change. `q` matches name, URL or jurisdiction |
| POST | `/api/sources` | Adds a source. 409 if the name is taken. The first check is due straight away |
| GET | `/api/sources/{id}` | One source with counts and the knowledge base name |
| PATCH | `/api/sources/{id}` | Changes fields. Validated like a new source |
| DELETE | `/api/sources/{id}` | Deletes the source, its snapshots and changes |
| POST | `/api/sources/{id}/pause` | Pauses, with an optional `reason` |
| POST | `/api/sources/{id}/resume` | Resumes and schedules a check now |
| POST | `/api/sources/{id}/check-now` | Runs a check and returns the outcome. Works on a paused source. 504 if it runs past twice the timeout plus 45 seconds |
| GET | `/api/sources/{id}/snapshots` | Snapshots, newest first, up to 500, each with the change it led to |
| GET | `/api/sources/{id}/changes` | Changes for one source, newest first, up to 500 |
| GET | `/api/sources/changes` | Recent changes across the tenant, up to 200 |
| GET | `/api/sources/changes/{change_id}` | One change with its full diff and both snapshots |
| GET | `/api/sources/snapshots/{snapshot_id}` | A snapshot with its text and rows. `full=true` reads the full text from storage |
| GET | `/api/sources/snapshots/{snapshot_id}/raw` | The bytes as fetched |
| POST | `/api/sources/preview` | Fetches and normalises a URL without saving |
| POST | `/api/sources/validate-url` | Says whether a URL may be fetched and suggests a kind |
| GET | `/api/sources/settings` | Tenant settings, which credentials are set, the limits and the kinds |
| PUT | `/api/sources/settings` | Sets the allowlist and pause threshold |

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `SOURCE_WATCH_MAX_BYTES` | 26214400 (25 MiB) | Largest document fetched. At least 1024 |
| `SOURCE_WATCH_TIMEOUT_SECONDS` | 30 | Per-request timeout |
| `SOURCE_WATCH_HOST_INTERVAL_SECONDS` | 2 | Gap between requests to one host |
| `SOURCE_WATCH_PAUSE_AFTER` | 5 | Default failures in a row before a source is paused |
| `SOURCE_WATCH_CONCURRENCY` | 8 | Checks run at once per scheduler tick |
| `SOURCE_WATCH_ALLOW_PRIVATE_TARGETS` | off | `1`, `true` or `yes` allows private addresses |
| `SOURCE_WATCH_LOCAL_ROOT` | unset | Local root for snapshot blobs. Falls back to `OBJECT_STORAGE_LOCAL_ROOT`, then `/data`. Only used when `STORAGE_BACKEND` is `local` |
| `SOURCE_DB_POOL` | 3 | Agent tool database pool size |
| `SOURCE_DB_OVERFLOW` | 3 | Agent tool database pool overflow |

Snapshot blobs use the platform object storage, so `STORAGE_BACKEND` and its settings decide where they go.

## Source map

| What | Where |
|---|---|
| **Fetch, check, record, KB ingestion** | [`apps/api/app/services/source_watch.py`](../../apps/api/app/services/source_watch.py) |
| **REST router** | [`apps/api/app/routers/sources.py`](../../apps/api/app/routers/sources.py) |
| **Normalisation** | [`apps/agent-runtime/engine/sources/normalize.py`](../../apps/agent-runtime/engine/sources/normalize.py) |
| **Diff, summary, materiality hint** | [`apps/agent-runtime/engine/sources/diff.py`](../../apps/agent-runtime/engine/sources/diff.py) |
| **Tool database pool** | [`apps/agent-runtime/engine/sources/db.py`](../../apps/agent-runtime/engine/sources/db.py) |
| **Agent tools** | [`apps/agent-runtime/engine/tools/source_tools.py`](../../apps/agent-runtime/engine/tools/source_tools.py) |
| **Models** | [`packages/db/models/source_watch.py`](../../packages/db/models/source_watch.py) |
| **Migration and immutability trigger** | [`packages/db/alembic/versions/25f2dd065d53_source_watch.py`](../../packages/db/alembic/versions/25f2dd065d53_source_watch.py) |
| **Scheduler job** | [`apps/api/app/core/scheduler.py`](../../apps/api/app/core/scheduler.py), `watch_sources` |
| **Event catalog** | [`apps/api/app/services/events.py`](../../apps/api/app/services/events.py), `source.changed` |
| **Capability** | [`apps/api/app/core/capabilities.py`](../../apps/api/app/core/capabilities.py), `sources.manage` |
| **UI** | [`apps/web/src/app/(app)/sources/`](../../apps/web/src/app/(app)/sources/) and [`apps/web/src/components/sources/`](../../apps/web/src/components/sources/) |
