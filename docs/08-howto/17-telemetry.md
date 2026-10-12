# How to connect machines and streams

> Point Abenix at a broker, a Kafka topic, a PLC or any system that can POST, and every asset it reports shows up under **Monitor -> Telemetry** with its parts, live readings, history and raw frames. Sparkplug B machines keep their session rules. Agents read the same values with the `device_state` tool, and people or apps with the right permission send commands back.

---

## How it flows

Every source goes through the same three stages.

1. A **connector** (the transport) brings messages in: `mqtt`, `http_push`, `kafka`, `amqp`, `nats`, `websocket`, `opcua` or `modbus_tcp`. It hands each one on as an envelope with its subject (topic, routing key, node id), payload, headers and receive time.
2. A **decoder** reads the payload and the connection's **mapping** turns it into records: an asset (group, node, device), a kind (data, birth, death, state, frame or event) and readings with value, type, unit, time and quality.
3. The **store** keeps the latest value in Redis at once, history in TimescaleDB in batches every 250 ms, raw frames in a ring of the last 2,000 per asset, events in a ring of 500, and raises events and alerts.

The asset key is always `(group, node, device)`. The page calls them Group, Asset and Part. In Sparkplug B they are the group id, the edge node and the device.

The ingest (`abenix-telemetry-ingest`, the API image running `python -m app.telemetry.ingest`) is a long-running process. It picks up a new or changed source within a couple of seconds.

| Who | Can |
|---|---|
| Everyone (`telemetry.view`) | See assets, live readings, history, frames, sources, the inspector and dead letters |
| Admins and holders of `telemetry.manage` | Add, test, change and remove sources, keys and mappings, replay dead letters |
| Admins, the **Machine operators** set and API keys granted it (`telemetry.command`) | Send commands |

---

## Step 1. Add a source

`deploy.sh local` adds **Site broker**, MQTT to the in-cluster `abenix-mosquitto`, reading `spBv1.0/#` with the `sparkplug_b` decoder and raw CAN frames on `+/+/can/raw` with `can_frames`.

To add another, open **Monitor -> Telemetry -> Connections -> Add source**. The form is built from `GET /api/telemetry/transports`, each transport lists its fields and its default decoder. Over REST:

```bash
curl -s -X POST "$API/api/telemetry/connections" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "Payments",
    "transport": "kafka",
    "config": {"bootstrap_servers": "redpanda:9092"},
    "secrets": {"sasl_password": "..."},
    "subjects": ["payments.orders"],
    "decoder": "json",
    "mapping": {"event": {"name": "$.type"}}
  }'
```

| Field | Notes |
|---|---|
| `transport` | `mqtt` when left out. The rest of the fields come from the transport |
| `config` | The transport's settings. Fields of kind `secret` given here move to `secrets` |
| `secrets` | Encrypted with the data key and never returned, they read as `********`. Send `********` to keep one, `""` to clear it |
| `subjects` | Topics, routing keys, subjects or node ids. MQTT also takes `topics` and `raw_topics` |
| `decoder`, `decoder_config` | See step 3. `GET /api/telemetry/decoders` lists them |
| `mapping`, `strict` | See step 4 |
| `team_id` | A team, see step 8. None means the whole workspace |
| `shared_subscription` | MQTT only. Every ingest replica reads the broker with `$share/abenix/...` |

**Test** connects for up to five seconds and says what it saw, `{ok, connected, messages, subjects_seen, sample, error}`. A failure says what to fix, for example `Could not reach the broker at abenix-mosquitto:1883. Check the address and that the broker is running.`

Each connection row carries its live `status` (`connected`, `connecting`, `error` or `disabled`), `last_error`, `messages_per_second`, `last_message_at`, `clock_skew_ms`, the counters in `pipeline` and a `diagnosis`, see step 7.

---

## Step 2. Systems that POST: HTTP push

A source with transport `http_push` gets an address and a token when it is made. The token is shown once.

```bash
curl -s -X POST "$API/api/telemetry/ingest/$SOURCE?subject=fleet/vans" \
  -H "Authorization: Bearer tpk_..." \
  -H 'Content-Type: application/x-ndjson' \
  -H 'Idempotency-Key: batch-2026-10-11-0001' \
  --data-binary @readings.ndjson
# 202 {"accepted": true, "id": "1791720000000-0", "bytes": 4096}
```

- JSON, NDJSON, CSV and plain text are taken, and `Content-Encoding: gzip`. The body is capped at `telemetry.max_payload_bytes` (1 MB) before and after decompression.
- 202 means the batch is in a durable Redis stream that every ingest replica reads as one consumer group. An entry is acknowledged only once its records are stored, so a replica that dies leaves its work for another.
- `Idempotency-Key` (or `X-Message-Id`) drops a repeat within a day.
- Give the source a signing secret and every request needs `X-Abenix-Signature: sha256=<HMAC-SHA256 of the body>`.
- Rotate the token with `POST /api/telemetry/connections/{id}/token`.

**Device keys.** Instead of sharing the source token, give each device its own key from the source's **Keys** tab, one at a time or from a CSV with a `device_id` column. A key is shown once, kept as a hash, shows when it was last used and can be revoked. A device key binds its device id, so whatever the message says it is written as that asset. A gateway key (`kind: gateway`, used by Abenix Edge) writes for many assets, inside its group and the asset patterns it is given.

From the SDK: `forge.telemetry.ingest(source_id, readings, token="tdk_...")`.

---

## Step 3. Pick the decoder

| Decoder | For |
|---|---|
| `sparkplug_b` | Sparkplug B 3.0. Births, deaths, data and host state, with seq, bdSeq, aliases and rebirth |
| `json`, `json_lines`, `csv` | Most webhooks, apps and batch pushers |
| `influx_line` | Telegraf and InfluxDB line protocol |
| `protobuf` | Upload the `.proto`, or a descriptor set, and name the message type |
| `avro` | Give the schema. Confluent framing and container files work too |
| `msgpack`, `cbor` | Compact devices |
| `text_number` | A bare number, or `temp=21.5 hum=40` |
| `values` | Typed values as the OPC UA, Modbus and Abenix Edge senders send them, quality and unit included. A top-level `seq` numbers the batches, and a jump counts as a seq gap even when replicas share the source |
| `can_frames` | Raw CAN frames as JSON. Upload a DBC to also get named signals, J1939 is matched by PGN |

A source can read part of its subjects with another decoder, the way Site broker reads `+/+/can/raw` with `can_frames`.

**Sparkplug B rules.** Every message from a node but `NDEATH` carries `seq`, 0 to 255. A jump counts a `seq_gap`, raises `telemetry.seq_gap` and asks the node to be born again with `NCMD` `Node Control/Rebirth`, at most once every five seconds. A late `NDEATH` with an older `bdSeq` is ignored. A node birth resets its alias table. Data before any birth asks for a rebirth. A birth declares the device's whole signal set. A signal it leaves out drops from the live view and is marked retired with the birth time on the signals list, and its history stays. An offline time is when the death arrived, since an `NDEATH` is the will set at connect.

**CAN frames.** `[{"t": 1791720000123, "id": 217056256, "data": "F0FF7D401B0000FF", "dlc": 8}]`, `t` in epoch ms, `id` the CAN id, `data` hex. The last 2,000 per asset are kept and `data` comes back in lower case.

---

## Step 4. Map messages to assets and readings

The mapping is JSON on the connection. Edit it in the mapping editor, which previews live messages as you type.

```json
{
  "group": "{subject.0}",
  "node": "$.vehicle.id",
  "device": "gps",
  "records": "$.items",
  "timestamp": {"path": "$.ts", "format": "auto"},
  "signals": {
    "include": ["speed_kmh", "fuel"],
    "exclude": ["meta"],
    "flatten": true,
    "rename": {"fuel": "Fuel/Level_pct"},
    "units": {"fuel": "%"},
    "types": {"speed_kmh": "number"}
  },
  "event": {"name": "$.type"},
  "writable": [{"signal": "Setpoint", "target": {"topic": "plant/{node}/set", "payload": "{\"sp\": {value}}"}}],
  "offline_after_s": 120,
  "subject_separator": "/"
}
```

- **Templates** take `{subject}`, `{subject.N}`, `{header.X}`, `{$.path}`, or a bare `$.path`.
- **Subjects split** on `/` when they have one (MQTT, HTTP) and on `.` when they do not (Kafka, NATS, AMQP). `subject_separator` pins it to `/`, `.` or `none`. With no mapping the first segment is the group, the second the asset and the rest the part. `edge/site-a/10.0.0.5` gives `edge`, `site-a`, `10.0.0.5`.
- **Time** is read as epoch s, ms, us or ns or ISO 8601, `auto` tells them apart. Without one the receive time is used.
- **Events.** With `event` the whole message is kept as an event, such as `order.created` from a payments stream. Read them with `GET /api/telemetry/events/{group}/{node}`.
- **Filter.** `"filter": {"require": ["$.symbol"], "match": {"$.type": "tick"}, "exclude": {"$.type": ["subscribed", "heartbeat"]}}` leaves out control and heartbeat messages. They are counted as `skipped` with the reason, never sent to the dead letters, and the preview marks them skipped. Suggest proposes a `require` filter when a few messages in a sample batch lack the asset.
- **Strict.** With `strict` on and a `declared` list, a message with any other signal goes to the dead letters. Without it new signals register themselves, see `GET /api/telemetry/connections/{id}/signals`.
- **Offline.** A device from a source without births goes offline after a silence. By default that is ten of its own usual gaps between messages, at least 60 seconds and at most 15 minutes. Set `offline_after_s` in the mapping for one source, or `telemetry.default_offline_after_s` for all. When many go quiet at once, the first five each raise `telemetry.device_offline` and the rest come as one grouped event and alert a minute. After a restart the ingest checks every device left online straight away.
- **Stale.** A source without births marks each signal stale once it is older than `offline_after_s`, even while other signals keep the device online.
- **Offline.** Sources without deaths are online while they send. `offline_after_s` marks an asset offline after that much silence.

`POST /api/telemetry/mapping/suggest` proposes a first mapping from a sample. `POST /api/telemetry/connections/{id}/preview` runs a sample, or with `capture: true` the next live message, through a mapping and shows the records, the errors and how the subject was split. Nothing is stored.

**Time rules.** The latest value only moves forward in event time. A late reading still goes to history. The gap between event time and receive time is measured per source and shown as `clock_skew_ms`, flagged past 5 seconds.

---

## Step 5. Read assets and readings

| Call | Gives |
|---|---|
| `GET /api/telemetry/devices` | One row per asset (device `""`) and part: `online`, `last_seen`, `birth_at`, `msgs_per_sec` and `readings_per_sec` over the last 5 seconds, `seq_gaps`, `metric_count`, `connection_id`, `team_name`. Takes `q`, `group`, `node`, `status`, `team`, `limit`, `offset` |
| `GET /api/telemetry/devices/{group}/{node}` | The asset and each part with every reading as `{name, value, type, ts, quality, unit}`. `?device=engine` for one |
| `GET /api/telemetry/history?group=&node=&device=&metric=&from=-1h&step=10s` | Buckets `{t, avg, min, max, n}` per signal. Ranges past 6 hours read the 1 minute aggregate, past 14 days the 1 hour one |
| `GET /api/telemetry/frames/{group}/{node}?limit=200&since=` | Newest raw frames first |
| `GET /api/telemetry/health` | Ingest health, quota and sources |
| `GET /api/telemetry/stream` | Live changes, below |

The SDK has the same in Python and JavaScript: `forge.telemetry.devices()`, `.node(group, node)`, `.history(...)`, `.frames(group, node, limit)`, `.health()`.

**Live stream.** `GET /api/telemetry/stream?nodes=groundwork/ipc-ex1,groundwork/ipc-tc1` (or `?group=&node=&device=`) sends `event: device`, `event: metrics` (at most 10 a second per part, the latest values win), `event: event`, `event: health` about once a second and `: ping` every 15 seconds. One person can keep 8 live views open (`telemetry.sse.max_per_user`).

---

## Step 6. Send a command

```bash
curl -s -X POST "$API/api/telemetry/command" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"group":"groundwork","node":"ipc-ex1","device":"safety","signal":"Safety/Hold","value":true,
       "reason":"Person inside the swing radius","confirm_timeout_ms":1000,
       "confirm_signal":"Safety/Mode","confirm_value":"hold"}'
# {"published": true, "at": "...", "topic": "spBv1.0/groundwork/DCMD/ipc-ex1/safety", "confirmed": true, "confirm_ms": 46, ...}
```

- A Sparkplug source gets a `DCMD`, or an `NCMD` when `device` is empty, with the type the signal was born with. Any other source writes to the target its mapping declares under `writable`, with `{value}` as JSON and `{raw}`, `{group}`, `{node}`, `{device}` and `{signal}` filled in. `metric` is still taken in place of `signal`.
- `received_at`, `checks_ms` and `published_at` (epoch ms, cluster clock) split the time Abenix spent from the hop to the device. A Sparkplug command's payload `timestamp` is `published_at`.
- `published` means the source took it. `confirmed` is `true` once the device reports the value back, or `confirm_signal` reaches `confirm_value`, within `confirm_timeout_ms`, and `false` with a note when it did not. It is `null` when nothing was asked.
- `dry_run: true` returns the exact message without sending it.
- An offline asset answers 409 `NODE_OFFLINE` with when it went offline. A signal that cannot be written answers 422 `NOT_WRITABLE`. More than 20 commands a second to one asset answers 429 `RATE_LIMITED`.
- Every command is in the audit log as `telemetry.command` with who sent it, the reason and the value.

Commands never wait for an approval, because a safety hold has to go out at once. A command that needs a person to agree first is wrapped by the caller, for example in Earned Autonomy.

---

## Step 7. When data is not showing

Each source keeps counters on every replica, summed in its row as `pipeline`: `received`, `decoded`, `mapped`, `stored`, `dlq`, `dropped`, `throttled`, `duplicates`, `empty`, `decode_failed` and `mapping_failed`, with the last reason for each in `last_reasons`.

`GET /api/telemetry/connections/{id}/diagnose` and `GET /api/telemetry/diagnose?group=&node=` turn those into one answer, `{state, message, fix}`:

| state | Means |
|---|---|
| `disabled` | The source is turned off |
| `error`, `not_running`, `connecting` | The source cannot connect, or the ingest is not running |
| `no_messages` | Connected, nothing arrived on its subjects |
| `decode_failed`, `mapping_failed` | Messages arrive and fail, see the dead letters |
| `mapping_empty` | Messages decode but the mapping keeps no readings |
| `filtered` | Every message so far was left out by the mapping's filter |
| `throttled` | The workspace is over its messages a second |
| `dropping` | The source's queue overflowed |
| `not_shared` | The asset reports through a source of a team you are not in |
| `offline`, `unknown_asset`, `ok` | As they say |

The **inspector** (`GET /api/telemetry/connections/{id}/inspector`) keeps the last 500 messages with what each decoded to, every failure and a few successes a second. **Dead letters** (`/dlq`) keep the last 1,000 failures with the reason. After fixing the decoder or mapping, `POST /api/telemetry/connections/{id}/dlq/replay` runs them again and says which still fail.

---

## Step 8. Teams, sharing and limits

A source with no team belongs to the whole workspace. Give it a team (a permission set from **Admin -> Permissions**) and only that team's members, its creator and admins see it, its assets and their readings. Share it with someone outside the team from its **Share** button, `view` to see it and `use` to also command it. Sending a command needs `telemetry.command` and that access.

| Limit | Default | Past it |
|---|---|---|
| Sources | 20 | Adding one answers 429 `QUOTA_EXCEEDED` |
| Assets and parts | 5,000 | New ones are not added until some are forgotten |
| Messages a second | 20,000 | The rest of that second is skipped and counted |
| Days of history | 7 | Older rows are dropped |
| Message size | 1 MB | The message goes to the dead letters |

Set them under **Admin -> Settings -> Telemetry**, or for one workspace with `PUT /api/telemetry/quota`. Health shows `throttled` and a plain `throttle_reason` while a limit bites, and one busy workspace does not slow the others.

**Forget devices.** A feed that makes a device per shipment or per trip fills the device limit with things that will never report again. Forgetting a device removes its live state and frees its place, keeps its history, and a device that reports again simply comes back. It needs `telemetry.manage`.

- `DELETE /api/telemetry/devices/{group}/{node}?device=gps` forgets one part, leave `device` out to forget the whole asset with its parts. An online device answers 409 `DEVICE_ONLINE` unless you add `force=true`.
- `POST /api/telemetry/devices/forget` with `{"offline_for_s": 3600, "group": "logistics", "node_glob": "ship-*", "dry_run": true}` counts what would go and shows a sample. Without `dry_run` it forgets up to 2,000 a call and returns `remaining`.
- Devices offline for more than 30 days are forgotten on their own, set by `telemetry.forget_offline_after_days` (0 never).

---

## Link straight to a chart

- `/telemetry?group=G&node=N&device=D` opens one asset or part. Leave `device` out for the whole asset. `group` is optional when the node name is unique.
- `&signals=A,B,C` takes full metric names such as `Engine/Speed_rpm,Engine/CoolantTemp_C`, up to 6, as small charts on one time axis. Without it Abenix picks headline signals for the asset type and puts flat lines last.
- `&range=5m|15m|1h|6h|24h|7d`, `5m` by default.
- `&focus=charts` hides the help, the health strip and the values table, for screens and films. **Show the values too** brings the table back.
- Also `tab=assets|messages|sources`, `q`, `grp`, `status=online|offline`, `team`, `atype`, `tag`, `view=table`, `mview=problems|frames` and `source=<id>`.

For example `/telemetry?group=edge-demo&node=truck-7&device=engine&signals=Engine/Speed_rpm,Engine/CoolantTemp_C&range=15m&focus=charts`.

---

## For agents and rules

- `device_state` with `group`, `node`, optional `device` and a `metrics` filter such as `["Engine/", "Safety/Hold"]` returns the latest readings with their age and quality. Readings older than `TELEMETRY_STALE_SECONDS` (30) read as stale.
- `subscribed_feed` reads `group/node/device/signal`, for example `groundwork/ipc-ex1/engine/Engine/Speed_rpm`, refreshed once a second.
- Events `telemetry.device_online`, `telemetry.device_offline` and `telemetry.seq_gap` can start an agent or a pipeline, see [12-source-watch-and-events](12-source-watch-and-events.md). An asset going offline raises `TelemetryDeviceOffline` on the Alerts page.
- Code that must see every record as it is stored, such as signal rules, registers a `RecordEvaluator` in `app.telemetry.evaluators`. Its `observe()` runs on the ingest right after the store, synchronously, and must not block.
- `signal_history` with `group`, `node`, optional `device`, `signals` and a range like `-1h` to `now` returns bucketed history with a summary of first, last, min, max, mean and when the peak was.

### Name your assets

**Telemetry -> Assets** lists every asset and part that streams in, at first under its raw key as unregistered. Give each a name, a type (vehicle, machine, sensor, device or system), tags, a team, a location and details like VIN, plate, serial and model. **Import CSV** names many at once and shows what each row would do first. A part takes its type and tags from its asset.

### Act on streams with signal rules

**Telemetry -> Signal rules -> New rule** builds a rule in four parts:

1. **What to watch.** One asset, every asset of a type, or every asset with a tag, so new assets are covered as they arrive.
2. **When.** Above or below a limit, out of a range, changing too fast, silent for N seconds, a value, entering or leaving a zone drawn over GPS or site positions, or happening N times in a window. A clear margin keeps a reading hovering at the limit from firing again and again, and a quiet time spaces firings out.
3. **Then.** Raise an alert that clears by itself, tell people in Abenix, by email or on Slack, run an agent or pipeline with the firing as context, check a decision table, or send a command with the rule as the reason.
4. **Name and settings.**

The builder picks signals from what is streaming and replays the rule over the last 1, 6 or 24 hours before you save it. Each firing keeps what every step did. Every firing is also the `telemetry.rule_fired` event, and rules that run agents show on the Triggers page.

Rules run in the ingest as data arrives. A source read by one replica keeps rule state in memory. A shared source keeps it in Redis with a compare-and-set, so a stream split over replicas fires exactly as one would. A Redis guard per rule, asset and reading makes sure a firing is never sent twice, and holds the quiet time and a cap of 60 firings a minute per rule across replicas. Silence is checked once a second by one replica against the last-seen times in Redis.

**Busy installs: the rules pool.** With many rules or busy streams, rules can run in a separate deployment, `abenix-telemetry-rules` (Helm `telemetryRules.enabled`). The ingest then only matches readings against the rule index and appends them to one Redis stream per shard of workspaces. Each pool replica holds its shards through a lease, evaluates with the same state machines, and deletes an entry once its firings are out, so a replica that stops mid-batch is picked up by the next owner without a repeat. Rule state lives in Redis, so a shard moves between replicas without losing where a rule was. It costs one Redis hop, a few milliseconds before a rule decides. The platform default is `telemetry.rules_mode` (`inprocess` or `pool`), and an admin can choose for one workspace under **Signal rules -> Rules run**. With no pool replica up, rules stay in the ingest. KEDA scales the pool on the readings waiting, from `/scale` on port 8091.

---

## Scale

- **Replicas.** `telemetryIngest.replicaCount` or KEDA with `telemetryIngest.autoscaling`. A lease-mode source is held by one replica through a Redis lease renewed every 2 seconds that lapses after 6. Replicas place sources by rendezvous hashing, so a new replica takes its share and a dead one's sources move once its leases lapse. Shared-mode sources (`http_push`, Kafka consumer groups, MQTT `$share`) run on every replica.
- **Pools.** The ingest runs as pools, `default` for mqtt, http_push, kafka, amqp and nats and `industrial` for opcua, modbus_tcp and websocket, each its own deployment (`telemetryIngest.pools`). A replica only leases the transports of its pool, so a heavy client library in one pool cannot slow the other. Health lists the pools, and each connection shows the pool that serves it. Each replica also reports `cpu_wait_pct`, the share of time its loop was ready to run but the node gave it no CPU. A high value means a busy node, not slow ingest code. Raise the pool's CPU request or move it.
- **Back pressure.** Each source has a bounded queue (`TELEMETRY_QUEUE_MAX`, 20,000). Transports that can wait are paused while it is full. MQTT drops and counts. The ingest takes turns across sources, so one cannot starve another.
- **At least once.** Kafka offsets, AMQP and NATS acks and HTTP push entries are acknowledged only after the store flush. Repeats with the same message id are dropped for a day.
- **History.** `telemetry_samples` is a hypertable with 6 hour chunks, compressed after a day, with 1 minute and 1 hour continuous aggregates. A reading is written at most once a second (`telemetry.history_interval_ms`), live values are never thinned.
- **Viewers.** Each API process holds one Redis subscription per asset in view and hands each message to its viewers, so any API pod serves any viewer.

`bash scripts/telemetry-loadtest.sh t2` and `t7` run the load tests in the cluster as a Job. Numbers from a local minikube are in [06-deployment/load-test-baseline](../06-deployment/load-test-baseline.md#telemetry).

---

## See also

- [09-reference/00-rest-api](../09-reference/00-rest-api.md#machine-telemetry)
- [03-sdk/01-python](../03-sdk/01-python.md#telemetry)
- [09-reference/04-platform-settings](../09-reference/04-platform-settings.md#telemetry)
- [06-deployment/02-helm](../06-deployment/02-helm.md)
