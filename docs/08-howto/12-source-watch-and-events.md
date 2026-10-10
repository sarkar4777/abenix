# How to watch a source and react when it changes

> Add a watched page or feed, let the platform keep immutable snapshots of it, and when it changes send a signed webhook to your service or start an agent. The same event subscriptions carry decision, approval, kill switch, run and eval events.

---

## How it flows

1. A scheduler job in the API checks due sources every 30 seconds. One check fetches the URL, normalises it to text or tables, and compares it with the last snapshot.
2. The first check keeps a baseline. A later check with the same content records `unchanged`. A different one stores a new snapshot and a change with its diff, then writes `source.changed` to the event outbox in the same transaction.
3. Every two seconds the dispatcher turns new outbox rows into one delivery per matching subscription, then sends them. A webhook gets a signed POST. An agent or pipeline target gets a run with the event as its context.

Snapshots never change, so an agent can quote and cite one long after the page moved on.

You need `sources.manage` to add sources and `events.manage` to subscribe. Creators and admins have both by default.

---

## Step 1. Add the source

In the UI, **Build -> Source Watch -> Add source**. The URL is validated as you type, and **Test fetch** shows the text the platform would keep.

Over REST, or `forge.sources.create(...)` in the Python SDK:

```bash
curl -s -X POST "$API/api/sources" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "Carrier tariff page",
    "url": "https://carrier.example.com/tariffs/2026",
    "kind": "html",
    "selector": "main article",
    "cadence_minutes": 360,
    "tags": ["freight"],
    "risk_tier": "medium"
  }'
```

| Field | Default | Notes |
|---|---|---|
| `kind` | `html` | `html`, `pdf`, `xlsx`, `csv`, `json` or `rss` |
| `selector` | none | A CSS selector for `html`, a JSON pointer such as `/data/items` for `json`. Also accepted for `xlsx`. Other kinds take none |
| `cadence_minutes` | 1440 | 5 minutes to 31 days |
| `headers` | `{}` | Up to 20 plain headers. `Authorization`, `Cookie`, `Proxy-Authorization` and `X-API-Key` are refused here |
| `credentials_key` | none | One of `SOURCE_AUTH_1` to `SOURCE_AUTH_5`, set by an admin under **Admin -> Tool Configuration -> Source Watch**. A bare token is sent as `Authorization: Bearer`, a value like `X-Api-Key: abc` as that header. Only sent to the source's own host |
| `ingest_to_kb` | none | A knowledge base id you can edit. The baseline and every changed snapshot are added to it as a document |
| `jurisdiction`, `tags`, `risk_tier` | `risk_tier` is `low` | Carried on the source and on its events. A subscription can filter on `jurisdiction` and `risk_tier`, not on `tags`, see below |

Useful calls before saving: `POST /api/sources/validate-url` with `{"url": ...}` says whether the URL may be fetched and suggests a kind, `POST /api/sources/preview` fetches once without saving.

A URL that resolves to a private, loopback or link-local address is refused, and so is one with a user name or password in it. An admin can restrict sources to a host allowlist and set how many failures in a row pause a source with `PUT /api/sources/settings` (`risk.manage`). `SOURCE_WATCH_ALLOW_PRIVATE_TARGETS=1` on the API lifts the private address check, for local testing only.

Check it once by hand:

```bash
curl -s -X POST "$API/api/sources/$SOURCE/check-now" -H "Authorization: Bearer $TOKEN"
```

`outcome.status` is `baseline`, `unchanged`, `not_modified`, `changed` or `error`. A kill switch on the source answers 409 with code `KILL_SWITCH`. Pause with `POST /api/sources/{id}/pause` and an optional `reason`, resume with `/resume`.

---

## Step 2. Subscribe to `source.changed`

### A webhook to your service

In the UI, **Admin -> Events -> New subscription**. Over REST:

```bash
curl -s -X POST "$API/api/webhooks" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "Tariff changes to pricing service",
    "events": ["source.changed"],
    "url": "https://pricing.example.com/hooks/abenix",
    "filter": {"source_id": "<source uuid>"}
  }'
```

The response carries `signing_secret` once. Store it, it is never shown again. With the SDK:

```python
sub = await forge.events.subscribe(
    ["source.changed"], url="https://pricing.example.com/hooks/abenix", name="Tariff changes"
)
secret = sub["signing_secret"]
```

`events` takes names from the catalogue or glob patterns, such as `decision.*`, or `*` for all. `GET /api/webhooks/catalog` lists them with sample payloads:

| Event | When |
|---|---|
| `execution.completed`, `execution.failed` | An agent or pipeline run finished |
| `approval.requested`, `approval.resolved` | Something waits for sign-off, or got it |
| `decision.proposed`, `decision.published`, `decision.retired` | A decision version moved |
| `kill_switch.set`, `kill_switch.cleared` | Something was stopped or resumed |
| `source.changed` | A watched source changed |
| `eval.completed` | An evaluation suite run finished |
| `action.proposed`, `action.executed`, `action.outcome_recorded` | A governed agent action was declared, ran, or had its outcome scored |
| `moderation.held`, `moderation.decided` | A moderation policy held content for review, or a person decided on it |
| `autonomy.recommended`, `autonomy.promoted`, `autonomy.demoted` | An agent's autonomy level is due to move, or moved |
| `lesson.captured`, `cluster.opened` | A lesson was captured, or lessons about one mistake were first grouped |
| `improvement.proposed`, `improvement.proved`, `improvement.released`, `improvement.rolled_back`, `improvement.kept` | A fix for an agent moved through proof, release and its watch period |

`filter` maps payload field paths to the value they must have, or a list of allowed values, for example `{"risk_tier": ["high", "critical"]}` or `{"decision_key": "freight.remote.surcharge"}`. Every key must match. The match is exact, so a field whose value is itself a list, such as `tags`, cannot be filtered on.

The webhook URL is checked when you save it. `localhost`, private and loopback IPs, and cluster-internal names such as `*.svc.cluster.local` are refused, unless the exact host name is listed in `EVENTS_ALLOWED_INTERNAL_HOSTS` (comma separated) on the API. On delivery the host is resolved again and a private answer is refused, unless the host is in that list or the API runs with `EVENTS_ALLOW_PRIVATE_TARGETS=1`.

### Or start an agent or pipeline

```bash
curl -s -X POST "$API/api/webhooks" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "events": ["source.changed"],
    "target_type": "agent",
    "target": {
      "agent_id": "<agent uuid>",
      "message": "{{data.name}} changed: {{data.change_summary}}. Read change {{data.change_id}} with source_diff and say whether our tariff rules need updating.",
      "context": {"change_id": "{{data.change_id}}"}
    }
  }'
```

`target_type` is `agent` or `pipeline` and must match what the id is. `{{...}}` placeholders read the envelope, so `{{type}}`, `{{data.change_id}}` and the like. The run gets the whole envelope as `context.event` plus the rendered `context` keys, and runs as the person who created the subscription. If that person is deactivated, deliveries fail with a message saying so. Give the agent `source_diff` and `source_snapshot_get` so it can read the change and cite the snapshots, and `decision_propose` if it should propose rule updates for people to approve.

---

## Step 3. Receive and verify the webhook

Each delivery is a POST with this body and headers:

```json
{
  "id": "evt_4182",
  "type": "source.changed",
  "tenant_id": "…",
  "occurred_at": "2026-03-02T06:00:04.112+00:00",
  "data": {
    "source_id": "…", "name": "Carrier tariff page", "url": "https://carrier.example.com/tariffs/2026",
    "kind": "html", "jurisdiction": null, "tags": ["freight"], "risk_tier": "medium",
    "change_id": "…", "snapshot_id": "…", "previous_snapshot_id": "…",
    "content_sha256": "…", "fetched_at": "…", "change_summary": "…", "materiality_hint": "…",
    "stats": {}
  }
}
```

| Header | Value |
|---|---|
| `X-Abenix-Event` | the event type |
| `X-Abenix-Delivery` | the envelope `id`, the same on every retry of one delivery. Use it to drop duplicates |
| `X-Abenix-Signature` | `sha256=` and the hex HMAC-SHA256 of the raw body, keyed with the signing secret |
| `User-Agent` | `Abenix-Events/1.0` |

Verify the signature over the raw bytes before parsing them. Both SDKs ship the check, `forge.events.verify_signature(secret, raw_body, signature)` in Python, a static method so `EventsClient.verify_signature` works without a client, and `await EventsClient.verifySignature(secret, rawBody, signature)` in TypeScript. Without the SDK:

```python
import hashlib, hmac, json
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI()
SECRET = "..."  # signing_secret from the subscription
seen: set[str] = set()

@app.post("/hooks/abenix")
async def hook(request: Request, x_abenix_signature: str = Header(""), x_abenix_delivery: str = Header("")):
    raw = await request.body()
    want = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, x_abenix_signature.strip()):
        raise HTTPException(401, "bad signature")
    if x_abenix_delivery in seen:
        return {"ok": True}
    seen.add(x_abenix_delivery)
    event = json.loads(raw)
    if event["type"] == "source.changed":
        print(event["data"]["name"], event["data"]["change_summary"])
    return {"ok": True}
```

```ts
import { createHmac, timingSafeEqual } from 'node:crypto';

export function verify(secret: string, rawBody: Buffer, header: string | undefined): boolean {
  const want = Buffer.from('sha256=' + createHmac('sha256', secret).update(rawBody).digest('hex'));
  const got = Buffer.from((header ?? '').trim());
  return want.length === got.length && timingSafeEqual(want, got);
}
```

Answer with any 2xx within 15 seconds. Anything else is retried after 10 seconds, then 20, 40 and so on, doubling each time. After 8 attempts, about 20 minutes, the delivery is `dead`. A subscription that fails 25 times in a row is paused with the last error as `disabled_reason`. `PUT /api/webhooks/{id}` with `{"is_active": true}` turns it back on.

---

## Step 4. Test, watch and replay deliveries

- `POST /api/webhooks/{id}/test` queues a sample of the first catalogue event the subscription matches, with `"test": true` in `data`. It goes out within seconds through the same signing and retry path.
- `GET /api/webhooks/{id}/deliveries?status=dead` lists deliveries, newest first, with status, attempts, response code and error.
- `POST /api/webhooks/deliveries/{delivery_id}/redeliver` sends one again with a fresh retry budget.

The SDK equivalents are `forge.events.test`, `forge.events.deliveries` and `forge.events.redeliver`.

When the API has `NATS_URL` set, every dispatched event is also published best effort on `abenix.events.<tenant_id>.<event_type>` for internal consumers that prefer a bus.

---

## Reading sources from an agent

| Tool | Tier | Does |
|---|---|---|
| `source_list` | low | The tenant's watched sources with their health |
| `source_snapshot_get` | low | The retained text of the latest or a given snapshot, with citation details |
| `source_diff` | low | What changed, by `change_id` or for a source's latest change |
| `source_check` | medium | Checks a source now and waits up to 120 seconds for the result |

---

## See also

- [02-runtime/17-source-watch](../02-runtime/17-source-watch.md), fetching, normalising and diffing in detail
- [02-runtime/19-outbound-events](../02-runtime/19-outbound-events.md), the outbox, the dispatcher and delivery states
- [05-testing](05-testing.md), `e2e/uat_source_watch.spec.ts`

---

## Source map

| What | Where |
|---|---|
| Source endpoints | [`apps/api/app/routers/sources.py`](../../apps/api/app/routers/sources.py), prefix `/api/sources` |
| Fetch, snapshot, change, `source.changed` | [`apps/api/app/services/source_watch.py`](../../apps/api/app/services/source_watch.py) |
| Subscription endpoints | [`apps/api/app/routers/webhook_config.py`](../../apps/api/app/routers/webhook_config.py), prefix `/api/webhooks` |
| Catalogue, outbox, fan-out, signing, delivery | [`apps/api/app/services/events.py`](../../apps/api/app/services/events.py) |
| Scheduler jobs `watch_sources` and `dispatch_events` | [`apps/api/app/core/scheduler.py`](../../apps/api/app/core/scheduler.py) |
| Agent tools | [`apps/agent-runtime/engine/tools/source_tools.py`](../../apps/agent-runtime/engine/tools/source_tools.py) |
| Unit tests | `tests/unit/test_source_watch.py`, `tests/unit/test_sources_api.py`, `tests/unit/test_events.py` |
