# Outbound events and webhooks

> How Abenix tells other systems that something happened: the event catalogue, the transactional outbox, subscriptions, signed webhook delivery, retries, replay and the NATS bus.

---

## Overview

Inbound triggers, where an outside call starts a run, are covered in [14-connectors-and-triggers.md](14-connectors-and-triggers.md). This page is the other direction.

1. A change and its event are written in one database transaction, into `event_outbox`.
2. A dispatcher job in the API turns each new outbox row into one delivery per matching subscription.
3. Each delivery is sent to a webhook URL, or starts an agent or pipeline run, and retried on failure.
4. The same events are also published to NATS for internal consumers.

An event exists exactly when the change it describes was committed. A rolled-back change emits nothing.

## Event catalogue

`GET /api/webhooks/catalog` returns this list with a sample payload for each type.

| Event | Emitted when | Emitted by |
|---|---|---|
| `execution.completed` | An agent or pipeline run's status changes to completed | Database trigger `executions_emit_event` on `executions` |
| `execution.failed` | A run's status changes to failed | Same trigger |
| `approval.requested` | An approval is created | `POST /api/approvals`, and proposing a decision version that needs sign-off |
| `approval.resolved` | A sign-off moves an approval out of pending | `routers/approvals.py` sign-off handler |
| `decision.proposed` | A decision version is proposed | `routers/decisions.py` |
| `decision.published` | A decision version comes into force | `routers/decisions.py` |
| `decision.retired` | A published version is retired | `routers/decisions.py` |
| `kill_switch.set` | A kill switch is set | `routers/governance.py` |
| `kill_switch.cleared` | A kill switch is resumed | `routers/governance.py` |
| `source.changed` | A watched source changed | `services/source_watch.py` |
| `eval.completed` | An evaluation suite run finished | `services/eval_runner.py` |

Notes:

- Execution events come from a trigger, `AFTER UPDATE OF status` on `executions`, so every code path that moves a run to completed or failed emits them. A row inserted already terminal, without a later status update, emits nothing. Nothing sets `cancelled` today, and it would emit nothing either.
- Approvals closed by the expiry sweep emit `approval.resolved` with `status: expired`, the same as a sign-off that settles one.
- The decision events and the `decision_publish` approvals behind them are covered in [Decision service](20-decision-service.md) and [the decisions how-to](../08-howto/09-decisions.md).
- `execution.started`, `agent.published` and `agent.updated` are still accepted on subscriptions created before the catalogue. Nothing emits them.

### Payload fields

| Event | `data` fields |
|---|---|
| `execution.completed`, `execution.failed` | `execution_id`, `agent_id`, `status`, `failure_code`, `duration_ms`, `cost`, `risk_tier`, `parent_execution_id` |
| `approval.requested` | `approval_id`, `title`, `gate_kind`, `required_signoffs` |
| `approval.resolved` | `approval_id`, `status` (`approved`, `denied`, `returned` or `expired`), `gate_kind`, `title` |
| `decision.proposed` | `decision_key`, `version`, `approvals_needed`, `approval_id` |
| `decision.published` | `decision_key`, `version`, `content_hash`, `valid_from`, `valid_to`, `superseded`, `closed` |
| `decision.retired` | `decision_key`, `version` |
| `kill_switch.set` | `scope`, `target`, `reason` |
| `kill_switch.cleared` | `scope`, `target` |
| `source.changed` | `source_id`, `name`, `url`, `kind`, `jurisdiction`, `tags`, `risk_tier`, `change_id`, `snapshot_id`, `previous_snapshot_id`, `content_sha256`, `fetched_at`, `change_summary`, `materiality_hint`, `stats` |
| `eval.completed` | `suite_id`, `run_id`, `agent_id`, `status`, `score`, `threshold`, `threshold_met`, `passed`, `failed`, `model`, `model_override`, `config_hash`, `triggered_by` |

## The envelope

Every delivery wraps the payload the same way.

```json
{
  "id": "evt_1842",
  "type": "decision.published",
  "tenant_id": "3f0c…",
  "occurred_at": "2026-10-03T09:14:02.118+00:00",
  "data": { "decision_key": "freight.remote.surcharge", "version": 4 }
}
```

- `id` is `evt_` plus the outbox row id. It is the same for every subscription that receives the event and for every retry of it. Use it to drop duplicates.
- Test sends use `evt_test_` plus 12 hex characters and add `"test": true` to `data`.

## Transactional outbox

`services/events.py` `emit(db, tenant_id, event_type, payload)` inserts a row into `event_outbox` inside the caller's transaction. It does not commit. The row lands when the caller commits.

| Column | Meaning |
|---|---|
| `id` | Bigint, ordered. Becomes the `evt_` id |
| `tenant_id` | Tenant the event belongs to |
| `event_type` | Catalogue type |
| `payload` | JSONB, becomes `data` |
| `occurred_at` | Insert time |
| `dispatched_at` | Set once fanned out. A partial index on `dispatched_at IS NULL` keeps the pending scan cheap |

The dispatcher runs in the API's scheduler every 2 seconds (`dispatch_events` job).

1. **Fan out.** Takes up to 500 undispatched rows with `FOR UPDATE SKIP LOCKED`, writes one `webhook_deliveries` row per matching active subscription with status `pending`, marks the outbox rows dispatched and commits.
2. **Deliver.** Takes up to 100 due deliveries with `FOR UPDATE OF d SKIP LOCKED`, pushes their `next_attempt_at` 60 seconds out as a lease, commits, sends them all concurrently outside any transaction, then records each outcome.

Row locks let every API replica run the job without sending twice. The lease means a pod that dies mid-send leaves the delivery to be picked up again after 60 seconds.

Active subscriptions are cached per process for 10 seconds. A change made on one pod reaches the others within that window.

## Subscriptions

A subscription is a row in `webhooks`.

| Field | Meaning |
|---|---|
| `name` | Label, up to 255 characters |
| `target_type` | `webhook` (default), `agent` or `pipeline` |
| `url` | Endpoint, for `webhook` targets |
| `target` | For `agent` and `pipeline` targets: `agent_id`, `message`, `context` |
| `events` | List of types or patterns. Defaults to `execution.completed` and `execution.failed` |
| `filter` | Payload conditions, all of which must hold |
| `signing_secret` | Generated for webhook targets |
| `is_active` | Paused when false |
| `consecutive_failures`, `failure_count`, `disabled_reason`, `last_delivery_at` | Health |
| `created_by` | The person runs are started as |

### Matching events

- `events` entries are exact types, `*` for everything, or shell-style patterns matched case-sensitively, such as `decision.*`. A pattern that matches no catalogue type is refused with 400.
- `filter` maps a dotted path into `data` to a value, or to a list of allowed values. `{"decision_key": "freight.remote.surcharge"}` or `{"status": ["failed"]}`. Nested objects as values are refused.

### Webhook targets

The URL is checked twice.

- **On save.** http or https only. A host listed in `EVENTS_ALLOWED_INTERNAL_HOSTS` passes. Otherwise it refuses `localhost`, `host.docker.internal`, `host.minikube.internal`, `metadata.google.internal`, `metadata`, `kubernetes`, `kubernetes.default.svc`, any host ending in `.cluster.local`, `.internal` or `.local`, private, loopback, link-local, multicast and unspecified IP literals, and integer-encoded IPs.
- **On every send.** The hostname is resolved and the send is refused if any address is private, loopback, link-local, multicast, reserved or unspecified. The refusal is recorded as the delivery's error and retried like any other failure. `EVENTS_ALLOW_PRIVATE_TARGETS` turns this check off. It does not relax the save-time check.

`EVENTS_ALLOWED_INTERNAL_HOSTS` (Helm `eventsAllowedInternalHosts`, empty by default) is a comma list of host names that skip the send-time address check, so a subscriber running inside the cluster can be reached without opening every private address. Names match exactly, ignoring case. There is no suffix or wildcard match, so a lookalike host does not get through. Saving a subscription honours the same list, so a listed name such as `receiver.abenix.svc.cluster.local` can be saved and reached. Hosts not on the list still get both checks.

### Agent and pipeline targets

Instead of an HTTP call, the delivery starts a run through the same `dispatch_execution` path inbound triggers use.

- `target.agent_id` must be in the caller's tenant. A pipeline id is refused for `agent` and the reverse.
- The run is started as the subscription's creator. If that person is gone or inactive the delivery fails with a message saying so.
- The run's input message is `target.message`, default `Event {{type}}: {{data}}`.
- The run's context is `{"event": <envelope>}` plus each `target.context` key, rendered.
- Success means the run was dispatched, not that it finished. The delivery row records the `execution_id`.

### Payload templates

`message` and `context` values use `{{ path }}` placeholders, resolved against the envelope by dotted path.

| Placeholder | Renders |
|---|---|
| `{{type}}` | `decision.published` |
| `{{data.decision_key}}` | The value as text |
| `{{data}}` | Objects and lists as JSON |
| `{{data.missing}}` | Empty string |

Placeholder names may contain letters, digits, `_` and `.`. Webhook targets get the envelope unchanged. Templates apply only to agent and pipeline targets.

## Signing

Each webhook subscription gets a secret from `secrets.token_urlsafe(32)` when it is created. The create response returns it once as `signing_secret`. No endpoint shows it again. A subscription switched to `webhook` later gets a new secret that is not returned, so delete and recreate it to get one you can read.

Request headers:

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `User-Agent` | `Abenix-Events/1.0` |
| `X-Abenix-Event` | Event type |
| `X-Abenix-Delivery` | Envelope `id` |
| `X-Abenix-Signature` | `sha256=` + hex HMAC-SHA256 |

The HMAC key is the secret's UTF-8 bytes. The message is the exact request body, which is `json.dumps(envelope, default=str)` with Python's default separators. Verify against the raw bytes you received, never a re-serialised copy. No timestamp is signed separately, so drop repeats by `X-Abenix-Delivery`.

### Receiver example

```python
import hashlib
import hmac
import json

from fastapi import FastAPI, HTTPException, Request

SECRET = "the signing_secret shown at creation"
seen: set[str] = set()
app = FastAPI()


@app.post("/abenix-events")
async def receive(request: Request):
    body = await request.body()
    expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Abenix-Signature", "")):
        raise HTTPException(401, "bad signature")
    delivery = request.headers["X-Abenix-Delivery"]
    if delivery in seen:
        return {"ok": True}
    seen.add(delivery)
    event = json.loads(body)
    print(event["type"], event["data"])
    return {"ok": True}
```

Reply with any status below 300 within 15 seconds. Anything else, including a redirect or a timeout, counts as a failure.

## Retries, dead letters and replay

Delivery states: `pending`, `retrying`, `delivered`, `dead`.

A failed attempt is retried after `min(3600, 10 * 2^(attempt - 1))` seconds.

| Failed attempt | Next try after |
|---|---|
| 1 | 10 s |
| 2 | 20 s |
| 3 | 40 s |
| 4 | 80 s |
| 5 | 160 s |
| 6 | 320 s |
| 7 | 640 s |
| 8 | None. Status becomes `dead` |

Each failure stores the status code and up to 300 characters of the response or exception in `error_message`. The response body is not stored on success.

**Auto-pause.** Every failed attempt adds one to the subscription's `consecutive_failures`. At 25 the subscription is paused and `disabled_reason` says why, with the last error. A success resets the counters. Resuming with `PUT {"is_active": true}` also resets them and clears the reason.

While paused, no new deliveries are created for it. Deliveries already queued fail with "The subscription is paused." and run out their retries.

**Dead letters** stay in `webhook_deliveries` with status `dead`. List them with `GET /api/webhooks/{id}/deliveries?status=dead`.

**Replay.** `POST /api/webhooks/deliveries/{delivery_id}/redeliver` sets the delivery back to `pending`, due now. It works on any delivery, including ones already delivered, and resends the same envelope and `evt_` id. The attempt counter goes back to zero, so a replay gets the full retry budget.

**Retention.** The `prune_events` job runs daily at 04:05 UTC. It deletes delivered rows older than 30 days and dispatched outbox rows older than 7 days. Dead and pending deliveries are kept.

## NATS bus

After each fan-out commit, the outbox rows are also published to NATS on

```
abenix.events.<tenant_id>.<event_type>
```

for example `abenix.events.3f0c….decision.published`. The message body is `{"id": <outbox id>, "type": ..., "data": ...}`. Here `id` is the bare integer, without the `evt_` prefix.

- Every event is published, whether or not any subscription matches.
- It is a plain best-effort publish. A failure is logged as a warning and does not affect webhook delivery.
- Test sends never reach the bus.
- With `NATS_URL` empty, publishing is skipped.

## REST API

All paths are under `/api/webhooks`. Responses use the usual `{"data", "error", "meta"}` wrapper.

| Method | Path | Needs | Does |
|---|---|---|---|
| `GET` | `/api/webhooks/catalog` | Signed in | Event types with description and sample |
| `GET` | `/api/webhooks` | Signed in | The tenant's subscriptions |
| `POST` | `/api/webhooks` | `events.manage` | Create. Returns `signing_secret` once for webhook targets. 201 |
| `PUT` | `/api/webhooks/{webhook_id}` | `events.manage` | Change any of `name`, `target_type`, `url`, `target`, `events`, `filter`, `is_active` |
| `DELETE` | `/api/webhooks/{webhook_id}` | `events.manage` | Delete. Its deliveries go with it |
| `POST` | `/api/webhooks/{webhook_id}/test` | `events.manage` | Queue a sample of the first catalogue type the subscription matches. Filters are not applied |
| `GET` | `/api/webhooks/{webhook_id}/deliveries` | Signed in | History, newest first. `limit` 1 to 100 (default 20), `offset`, `status` |
| `POST` | `/api/webhooks/deliveries/{delivery_id}/redeliver` | `events.manage` | Queue the delivery again |

Create example:

```json
{
  "name": "Rules published to compliance",
  "target_type": "webhook",
  "url": "https://hooks.example.com/abenix",
  "events": ["decision.published", "decision.retired"],
  "filter": {"decision_key": ["freight.remote.surcharge"]}
}
```

`events.manage` is held by creators and admins by default and can be granted through permission sets. See [Governance](../01-architecture/07-governance.md#capabilities-and-permission-sets). For the rest of the API see the [REST reference](../09-reference/00-rest-api.md).

The older approval webhook set by `PUT /api/approvals/webhooks` is separate. It is covered in [05-approvals-hitl.md](05-approvals-hitl.md).

## The Events page

**Admin -> Events** in the sidebar, also the **Events** tab under Settings. Both open `/settings/webhooks` and both show only to people with `events.manage`. Without it the page says an admin can grant it under Admin, Permissions.

- **New subscription** picks the target, events by group or one by one, and optional conditions. With one event picked it lists the fields that event carries.
- The secret is shown once after creating, with a copy button.
- Each subscription card has Send test, Pause or Resume, Delete, and its recent deliveries, refreshed every 4 seconds, with Redeliver on each.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `NATS_URL` | Empty in code. Helm sets `nats://<release>-nats:4222` | Bus to publish events to. Empty skips the bus |
| `NATS_USER` | Unset. Helm sets `abenix` | NATS user |
| `NATS_PASSWORD` | Unset. From the Helm secret | NATS password |
| `EVENTS_ALLOW_PRIVATE_TARGETS` | Unset | `1`, `true` or `yes` lets sends reach private addresses. For local development |
| `EVENTS_ALLOWED_INTERNAL_HOSTS` | Empty. Helm `eventsAllowedInternalHosts` | Comma list of exact host names a subscription may be saved with and a send may reach, even when cluster-internal or private |

Batch sizes, the 8 attempts, the 60 second lease, the 25-failure pause and the 10 second subscription cache are constants in `services/events.py`, not settings.

## Source map

| What | Where |
|---|---|
| **Catalogue, emit, fan-out, delivery, signing, NATS** | [`apps/api/app/services/events.py`](../../apps/api/app/services/events.py) |
| **Subscriptions REST router** | [`apps/api/app/routers/webhook_config.py`](../../apps/api/app/routers/webhook_config.py) |
| **Dispatch and prune jobs** | [`apps/api/app/core/scheduler.py`](../../apps/api/app/core/scheduler.py) — `dispatch_events`, `prune_events` |
| **Migration, outbox table and execution trigger** | [`packages/db/alembic/versions/fe18a43f0be1_event_outbox.py`](../../packages/db/alembic/versions/fe18a43f0be1_event_outbox.py) |
| **Outbox model** | [`packages/db/models/governance.py`](../../packages/db/models/governance.py) — `EventOutbox` |
| **Subscription model** | [`packages/db/models/webhook.py`](../../packages/db/models/webhook.py) |
| **Delivery model** | [`packages/db/models/webhook_delivery.py`](../../packages/db/models/webhook_delivery.py) |
| **`events.manage` capability** | [`apps/api/app/core/capabilities.py`](../../apps/api/app/core/capabilities.py) |
| **Events page** | [`apps/web/src/app/(app)/settings/webhooks/page.tsx`](../../apps/web/src/app/(app)/settings/webhooks/page.tsx) |
