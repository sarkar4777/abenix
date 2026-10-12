# Telemetry testbed

Real brokers and small simulated apps, so every telemetry connector can be tried end to end
without outside systems. Everything runs in the `abenix-testbed` namespace and needs about
1.3 GB of memory.

```bash
bash scripts/deploy.sh testbed            # install or update, then add the Testbed connections to Abenix
bash scripts/deploy.sh testbed-connect    # add or refresh only the connections
bash scripts/deploy.sh testbed-forwards   # testbed ports on localhost, for running connectors from this machine
bash scripts/deploy.sh testbed-chaos nats # kill a broker pod and time its return
bash scripts/deploy.sh testbed-poison payments  # one malformed message, for the dead-letter ring
bash scripts/deploy.sh testbed-load 100000 5000 # Kafka burst to load.events
bash scripts/deploy.sh testbed-down       # remove the namespace, its data and its passwords
```

Re-running `testbed` is safe. Passwords are made once and kept in the `testbed-credentials`
Secret, so connections saved in Abenix keep working. The simulators share one image, built
from `sim/` and tagged by its content, so it is rebuilt only when the code changes.

## What runs

| Source | In-cluster address | Sign in | What it sends |
|---|---|---|---|
| Redpanda | `redpanda.abenix-testbed.svc.cluster.local:9092` | SASL_PLAINTEXT, SCRAM-SHA-256 user `abenix`, SCRAM-SHA-512 user `abenix512`, PLAIN works too | `shop.orders` JSON events from the payments sim (`order.created`, `payment.authorized`, `payment.settled`, `payment.failed`, `order.shipped`, `refund.issued`), `plant.sensors` schemaless Avro |
| RabbitMQ | `rabbitmq.abenix-testbed.svc.cluster.local:5672` | user `abenix`, may configure `abenix.*` and `telemetry.*` queues | shipment status on topic exchange `logistics.events`, routing keys `shipment.<status>`, also queued on `telemetry.shipments` |
| NATS | `nats://nats.abenix-testbed.svc.cluster.local:4222` | user `abenix` | vehicle positions on `fleet.positions.<region>.<vehicle>`, kept in JetStream stream `FLEET` |
| OPC PLC 2.15.10 | `opc.tcp://opc-plc.abenix-testbed.svc.cluster.local:50000` | user `abenix`, anonymous is off | `Objects/OpcPlc/Telemetry`: StepUp, slow and fast doubles, bad-status nodes, anomaly nodes |
| Modbus meter | `meter.abenix-testbed.svc.cluster.local:502`, unit 1 | none | energy meter registers, see below |
| WebSocket prices | `ws://prices.abenix-testbed.svc.cluster.local:8765/ticks` | header `Authorization: Bearer <ws-token>` | ticks for eight symbols, answers `{"op": "subscribe", "symbols": [...]}` and acknowledges anything else |
| HTTP pusher | posts to an Abenix `http_push` source | its token | NDJSON weather readings every 2 s |

Every password is a key of `testbed-credentials`: `kafka-password`, `rabbitmq-password`,
`nats-password`, `opcua-password`, `ws-token`. The user `restricted` with `restricted-password`
signs in to Kafka, RabbitMQ and NATS but may not read the data, for checking ACL errors.

Commands sent back from Abenix land in the sims and show in their logs:
`shop.commands` (a `refund` order makes a `refund.issued` event), exchange `logistics.commands`,
subjects `fleet.commands.>`, the meter's setpoint and breaker, WebSocket messages.

## Energy meter register map

Holding registers, big-endian bytes. Input registers 0 to 11 mirror holding 0 to 11.

| Register | Name | Type | Scale | Unit |
|---|---|---|---|---|
| 0-1 | Voltage | float32 | 1 | V |
| 2-3 | Current | float32 | 1 | A |
| 4-5 | Active power | float32 | 1 | kW |
| 6-7 | Energy | uint32 | 0.1 | kWh |
| 8 | Frequency | uint16 | 0.01 | Hz |
| 9 | Power factor | int16 | 0.001 | |
| 10 | Setpoint, writable | uint16 | 0.1 | kW |
| 11 | Temperature | int16 | 0.1 | C |
| 20-21 | Voltage, little word order | float32 | 1 | V |
| 22-23 | Reactive energy | int32 | 1 | kvarh |
| coil 0 | Breaker closed, writable | bool | | |
| discrete 0, 1 | Overload alarm, phase loss | bool | | |

Power follows the setpoint while the breaker is closed and drops to zero when it opens.

## The HTTP pusher

`testbed-connect` creates the `Testbed · Weather stations (HTTP push)` source and hands its
URL and token to the pusher. To point it somewhere else:

```bash
HTTP_PUSH_URL=http://abenix-api.abenix.svc.cluster.local:8000/api/telemetry/ingest/<id> \
HTTP_PUSH_TOKEN=<token> bash scripts/deploy.sh testbed
```

Without a URL and token the pusher idles and says so in its log once a minute.

## Throughput runs

`testbed-load <count> <rate>` starts a one-off Job that writes JSON
`{seq, sent_ms, device, value}` to `load.events` (6 partitions) and logs the rate it reached.
Point a Kafka connection at `load.events` and scale the ingest with
`TELEMETRY_INGEST_REPLICAS=2 bash scripts/deploy.sh chart`.
