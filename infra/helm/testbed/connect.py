"""Adds the testbed's sources to Abenix as ready-made connections, through the public API.

Runs inside the api pod (deploy.sh testbed-connect sends it with the testbed
passwords as CREDS_B64 ahead of this text). Idempotent: an existing connection
with the same name is updated in place.
"""

import base64
import json
import os
import sys

import httpx

CREDS = {k: base64.b64decode(v).decode() for k, v in json.loads(base64.b64decode(CREDS_B64))["data"].items()}  # noqa: F821
NS = os.environ.get("TESTBED_NS", "abenix-testbed")
D = f"{NS}.svc.cluster.local"
PREFIX = "Testbed · "

SENSOR_SCHEMA = {
    "type": "record", "name": "SensorReading", "namespace": "plant",
    "fields": [
        {"name": "plant", "type": "string"}, {"name": "line", "type": "string"},
        {"name": "sensor_id", "type": "string"}, {"name": "temperature_c", "type": "double"},
        {"name": "pressure_bar", "type": "double"}, {"name": "vibration_mm_s", "type": "double"},
        {"name": "running", "type": "boolean"},
        {"name": "ts", "type": {"type": "long", "logicalType": "timestamp-millis"}},
    ],
}
METER_MAP = "\n".join([
    "Voltage_V, holding, 0, float32, 1, V",
    "Current_A, holding, 2, float32, 1, A",
    "Power_kW, holding, 4, float32, 1, kW",
    "Energy_kWh, holding, 6, uint32, 0.1, kWh",
    "Frequency_Hz, holding, 8, uint16, 0.01, Hz",
    "PowerFactor, holding, 9, int16, 0.001",
    "Setpoint_kW, holding, 10, uint16, 0.1, kW",
    "Temperature_C, holding, 11, int16, 0.1, C",
    "BreakerClosed, coil, 0",
    "OverloadAlarm, discrete, 0",
])
KAFKA = {
    "bootstrap_servers": f"redpanda.{D}:9092",
    "security_protocol": "SASL_PLAINTEXT",
    "sasl_mechanism": "SCRAM-SHA-256",
    "username": "abenix",
    "start_from": "latest",
}

SOURCES = [
    {
        "name": PREFIX + "Payments (Kafka)",
        "transport": "kafka",
        "config": dict(KAFKA),
        "secrets": {"password": CREDS["kafka-password"]},
        "subjects": ["shop.orders"],
        "decoder": "json",
        "mapping": {
            "group": "payments",
            "node": "$.merchant",
            "device": "$.region",
            "timestamp": {"path": "$.occurred_at", "format": "iso"},
            "event": {"name": "$.type"},
            "signals": {"include": ["amount"], "units": {"amount": "money"}},
            "writable": [{
                "signal": "Refund",
                "target": {"topic": "shop.commands", "payload": "{\"action\": \"refund\", \"order_id\": \"{value}\", \"reason\": \"Abenix\"}"},
            }],
        },
    },
    {
        "name": PREFIX + "Plant sensors (Kafka, Avro)",
        "transport": "kafka",
        "config": dict(KAFKA),
        "secrets": {"password": CREDS["kafka-password"]},
        "subjects": ["plant.sensors"],
        "decoder": "avro",
        "decoder_config": {"schema": json.dumps(SENSOR_SCHEMA)},
        "mapping": {
            "group": "plant",
            "node": "$.line",
            "device": "$.sensor_id",
            "timestamp": {"path": "$.ts", "format": "epoch_ms"},
            "signals": {
                "exclude": ["plant", "line", "sensor_id", "ts"],
                "units": {"temperature_c": "C", "pressure_bar": "bar", "vibration_mm_s": "mm/s"},
            },
        },
    },
    {
        "name": PREFIX + "Shipments (RabbitMQ)",
        "transport": "amqp",
        "config": {
            "host": f"rabbitmq.{D}", "port": 5672, "username": "abenix", "mode": "exchange",
            "exchange": "logistics.events", "exchange_type": "topic", "queue": "abenix.testbed-shipments",
            "queue_max_length": 100000, "prefetch": 500,
        },
        "secrets": {"password": CREDS["rabbitmq-password"]},
        "subjects": ["shipment.#"],
        "decoder": "json",
        "mapping": {
            "group": "logistics",
            "node": "$.carrier",
            "device": "$.shipment_id",
            "timestamp": {"path": "$.ts", "format": "iso"},
            "signals": {"exclude": ["shipment_id", "carrier", "ts", "location/city"], "flatten": True, "units": {"weight_kg": "kg", "eta_hours": "h"}},
            "writable": [{
                "signal": "Hold",
                "target": {"exchange": "logistics.commands", "routing_key": "shipment.hold", "payload": "{\"shipment_id\": \"{device}\", \"hold\": {value}}"},
            }],
            "offline_after_s": 600,
        },
    },
    {
        "name": PREFIX + "Fleet (NATS JetStream)",
        "transport": "nats",
        "config": {"servers": f"nats://nats.{D}:4222", "username": "abenix", "mode": "jetstream", "stream": "FLEET", "deliver_policy": "new"},
        "secrets": {"password": CREDS["nats-password"]},
        "subjects": ["fleet.positions.>"],
        "decoder": "json",
        "mapping": {
            "group": "fleet",
            "node": "{subject.2}",
            "device": "$.vehicle_id",
            "timestamp": {"path": "$.ts", "format": "iso"},
            "signals": {"exclude": ["vehicle_id", "ts"], "units": {"speed_kmh": "km/h", "fuel_pct": "%", "odometer_km": "km", "heading_deg": "deg"}},
            "writable": [{
                "signal": "Command",
                "target": {"subject": "fleet.commands.{device}", "payload": "{\"action\": \"{value}\"}"},
            }],
        },
    },
    {
        "name": PREFIX + "Line PLC (OPC UA)",
        "transport": "opcua",
        "config": {
            "endpoint": f"opc.tcp://opc-plc.{D}:50000", "username": "abenix",
            "security_policy": "None", "security_mode": "None", "asset": "plant/opc-plc",
            "nodes": "\n".join([
                "ns=3;s=StepUp = Counters/StepUp",
                "ns=3;s=SlowDouble1 = Line1/Temperature_C",
                "ns=3;s=SlowDouble2 = Line1/Pressure_bar",
                "ns=3;s=FastDouble1 = Line1/Vibration_mm_s",
                "ns=3;s=AlternatingBoolean = Line1/Running",
                "ns=3;s=BadSlowDouble1 = Line1/FlakySensor",
                "ns=3;s=DipData = Anomaly/Dip",
                "ns=3;s=SpikeData = Anomaly/Spike",
            ]),
            "sampling_interval_ms": 500, "publishing_interval_ms": 1000,
        },
        "secrets": {"password": CREDS["opcua-password"]},
        "decoder": "values",
        "mapping": {
            "signals": {"units": {"Line1/Temperature_C": "C", "Line1/Pressure_bar": "bar", "Line1/Vibration_mm_s": "mm/s"}},
            "writable": [{"signal": "Counters/StepUp", "target": {"node_id": "ns=3;s=StepUp"}}],
        },
    },
    {
        "name": PREFIX + "Energy meter (Modbus TCP)",
        "transport": "modbus_tcp",
        "config": {"host": f"meter.{D}", "port": 502, "unit_id": 1, "registers": METER_MAP, "poll_interval_ms": 1000, "asset": "energy/meter-1"},
        "secrets": {},
        "decoder": "values",
        "mapping": {
            "writable": [
                {"signal": "Setpoint_kW", "target": {"register": "Setpoint_kW"}},
                {"signal": "BreakerClosed", "target": {"coil": "BreakerClosed"}},
            ],
        },
    },
    {
        "name": PREFIX + "Market prices (WebSocket)",
        "transport": "websocket",
        "config": {
            "url": f"ws://prices.{D}:8765/ticks", "subject": "markets/prices",
            "subscribe_message": "{\"op\": \"subscribe\", \"symbols\": {subjects}}",
        },
        "secrets": {"auth_header": "Bearer " + CREDS["ws-token"]},
        "subjects": ["BTC-USD", "ETH-USD", "EUR-USD", "GBP-USD", "AAPL", "MSFT", "BRENT", "TTF-GAS"],
        "decoder": "json",
        "mapping": {
            "group": "markets",
            "node": "$.symbol",
            "device": "",
            "timestamp": {"path": "$.ts", "format": "iso"},
            "signals": {"include": ["bid", "ask", "last", "volume"]},
            "writable": [{
                "signal": "Order",
                "target": {"payload": "{\"op\": \"order\", \"symbol\": \"{node}\", \"qty\": {value}}", "reply_contains": "\"ack\""},
            }],
        },
    },
    {
        "name": PREFIX + "Weather stations (HTTP push)",
        "transport": "http_push",
        "config": {},
        "secrets": {},
        "decoder": "json_lines",
        "mapping": {
            "group": "weather",
            "node": "$.station",
            "device": "",
            "timestamp": {"path": "$.ts", "format": "iso"},
            "signals": {"exclude": ["station", "ts"], "units": {"temperature_c": "C", "humidity_pct": "%", "wind_ms": "m/s", "pressure_hpa": "hPa"}},
        },
    },
]


def main() -> int:
    c = httpx.Client(base_url="http://localhost:8000", timeout=60)
    login = c.post("/api/auth/login", json={"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    if login.status_code != 200:
        print(f"could not sign in as {os.environ['ADMIN_EMAIL']}: {login.status_code}")
        return 1
    auth = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
    have = {row["name"]: row for row in (c.get("/api/telemetry/connections", headers=auth).json().get("data") or [])}
    avail = {t["transport"] for t in (c.get("/api/telemetry/transports", headers=auth).json().get("data") or {}).get("transports", [])}
    bad = 0
    for src in SOURCES:
        if src["transport"] not in avail:
            print(f"skip {src['name']}: this Abenix has no {src['transport']} transport yet")
            continue
        body = {**src, "enabled": True}
        row = have.get(src["name"])
        if row is None:
            r = c.post("/api/telemetry/connections", json=body, headers=auth)
            verb = "added"
        else:
            body.pop("transport")
            r = c.patch(f"/api/telemetry/connections/{row['id']}", json=body, headers=auth)
            verb = "updated"
        if r.status_code >= 300:
            print(f"FAIL {src['name']}: {r.status_code} {r.text[:300]}")
            bad += 1
            continue
        data = r.json()["data"]
        if data.get("ingest_token"):
            # read by deploy.sh, which hands it to the HTTP pusher as a Secret
            print(f"PUSH {data['id']} {data['ingest_token']}")
        t = c.post(f"/api/telemetry/connections/{data['id']}/test", headers=auth).json().get("data") or {}
        state = "ok" if t.get("ok") else f"test said: {t.get('error')}"
        print(f"{verb} {src['name']} ({data['id']}), {t.get('messages', 0)} messages in the test, {state}")
    return 1 if bad else 0


sys.exit(main())
