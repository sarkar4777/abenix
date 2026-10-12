"""Testbed simulators: small apps that speak real protocols to real brokers.

python sim.py <role>, roles: payments sensors logistics fleet meter prices pusher load
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import struct
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("sim")
POISON = asyncio.Event()
SENT = {"n": 0, "errors": 0}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def now_ms() -> int:
    return int(time.time() * 1000)


async def control_server() -> None:
    """GET /healthz and POST /poison on :8081, the testbed script talks to it."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode(errors="replace")
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass
            if line.startswith("POST /poison"):
                POISON.set()
                body = "one malformed message queued\n"
            else:
                body = json.dumps({"ok": True, "sent": SENT["n"], "errors": SENT["errors"]}) + "\n"
            writer.write(
                f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}".encode()
            )
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "0.0.0.0", int(env("CONTROL_PORT", "8081")))
    async with server:
        await server.serve_forever()


async def backoff_sleep(attempt: int) -> None:
    await asyncio.sleep(min(30.0, 0.5 * 2 ** min(attempt, 6)) * random.uniform(0.5, 1.0))


def take_poison() -> bool:
    if POISON.is_set():
        POISON.clear()
        return True
    return False


# Kafka


def kafka_kwargs() -> dict:
    kw: dict = {"bootstrap_servers": env("KAFKA_BOOTSTRAP", "redpanda:9092")}
    if env("KAFKA_USER"):
        kw.update(
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism=env("KAFKA_MECHANISM", "SCRAM-SHA-256"),
            sasl_plain_username=env("KAFKA_USER"),
            sasl_plain_password=env("KAFKA_PASSWORD"),
        )
    return kw


async def ensure_topics(topics: dict[str, int]) -> None:
    from aiokafka.admin import AIOKafkaAdminClient, NewTopic

    for attempt in range(1000):
        admin = AIOKafkaAdminClient(**kafka_kwargs())
        try:
            await admin.start()
            have = set(await admin.list_topics())
            new = [NewTopic(t, p, 1) for t, p in topics.items() if t not in have]
            if new:
                await admin.create_topics(new)
                log.info("created topics %s", [t.name for t in new])
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("waiting for Kafka at %s: %s", env("KAFKA_BOOTSTRAP"), exc)
            await backoff_sleep(attempt)
        finally:
            await admin.close()


async def kafka_producer():
    from aiokafka import AIOKafkaProducer

    for attempt in range(1000):
        p = AIOKafkaProducer(linger_ms=20, acks="all", **kafka_kwargs())
        try:
            await p.start()
            return p
        except Exception as exc:  # noqa: BLE001
            await p.stop()
            log.warning("producer could not connect: %s", exc)
            await backoff_sleep(attempt)
    raise SystemExit(1)


async def kafka_commands(topic: str, on_command) -> None:
    """Log what the platform writes back, and act on it."""
    from aiokafka import AIOKafkaConsumer

    attempt = 0
    while True:
        c = AIOKafkaConsumer(
            topic,
            group_id=f"{env('ROLE')}-sim-commands",
            auto_offset_reset="latest",
            **kafka_kwargs(),
        )
        try:
            await c.start()
            attempt = 0
            async for m in c:
                log.info("command received on %s: %s", topic, m.value[:500].decode(errors="replace"))
                try:
                    await on_command(json.loads(m.value))
                except Exception as exc:  # noqa: BLE001
                    log.info("command ignored: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("command consumer: %s", exc)
            await backoff_sleep(attempt)
            attempt += 1
        finally:
            await c.stop()


async def send_retry(producer_ref: list, topic: str, value: bytes, key: bytes | None, headers=None) -> None:
    for attempt in range(1000):
        try:
            await producer_ref[0].send_and_wait(topic, value, key=key, headers=headers)
            SENT["n"] += 1
            return
        except Exception as exc:  # noqa: BLE001
            SENT["errors"] += 1
            log.warning("send to %s failed, retrying: %s", topic, exc)
            await backoff_sleep(attempt)
            if attempt >= 2:
                try:
                    await producer_ref[0].stop()
                except Exception:  # noqa: BLE001
                    pass
                producer_ref[0] = await kafka_producer()


MERCHANTS = [("store-eu-1", "eu-west", "EUR"), ("store-us-1", "us-east", "USD"), ("store-uk-1", "uk-south", "GBP")]
METHODS = ["card", "card", "card", "wallet", "bank_transfer"]


async def role_payments() -> None:
    topic, commands = env("TOPIC", "shop.orders"), env("COMMAND_TOPIC", "shop.commands")
    await ensure_topics({topic: 3, commands: 1})
    ref = [await kafka_producer()]
    open_orders: dict[str, dict] = {}
    rate = float(env("RATE", "5"))

    async def emit(kind: str, order: dict, **extra) -> None:
        body = {
            "event_id": str(uuid.uuid4()),
            "type": kind,
            "occurred_at": now_iso(),
            "order_id": order["order_id"],
            "customer_id": order["customer_id"],
            "merchant": order["merchant"],
            "region": order["region"],
            "amount": order["amount"],
            "currency": order["currency"],
            "payment_method": order["payment_method"],
            **extra,
        }
        headers = [("ce_type", kind.encode()), ("ce_source", b"payments-sim"), ("content-type", b"application/json")]
        await send_retry(ref, topic, json.dumps(body).encode(), order["order_id"].encode(), headers)

    async def on_command(cmd: dict) -> None:
        oid = str(cmd.get("order_id") or "")
        if cmd.get("action") == "refund" and oid:
            order = open_orders.get(oid) or {
                "order_id": oid, "customer_id": "cus_unknown", "merchant": "store-eu-1",
                "region": "eu-west", "amount": float(cmd.get("amount") or 0), "currency": "EUR",
                "payment_method": "card",
            }
            await emit("refund.issued", order, reason=str(cmd.get("reason") or "requested"))

    asyncio.create_task(kafka_commands(commands, on_command))
    log.info("payments: %s events/s on %s, commands on %s", rate, topic, commands)
    while True:
        if take_poison():
            await send_retry(ref, topic, b'{"type": "order.created", "amount": ', b"poison")
            log.info("sent one malformed message to %s", topic)
        m, region, cur = random.choice(MERCHANTS)
        order = {
            "order_id": f"ord_{uuid.uuid4().hex[:12]}",
            "customer_id": f"cus_{random.randint(1000, 9999)}",
            "merchant": m, "region": region, "currency": cur,
            "amount": round(random.lognormvariate(3.6, 0.8), 2),
            "payment_method": random.choice(METHODS),
            "step": 0,
        }
        open_orders[order["order_id"]] = order
        await emit("order.created", order, items=random.randint(1, 6))
        for oid in list(open_orders)[:-1]:
            o = open_orders[oid]
            if random.random() > 0.35:
                continue
            o["step"] += 1
            if o["step"] == 1:
                if random.random() < 0.04:
                    await emit("payment.failed", o, decline_code=random.choice(["insufficient_funds", "do_not_honor", "expired_card"]))
                    open_orders.pop(oid)
                else:
                    await emit("payment.authorized", o, auth_code=uuid.uuid4().hex[:6].upper())
            elif o["step"] == 2:
                await emit("payment.settled", o, fee=round(o["amount"] * 0.029 + 0.3, 2))
            elif o["step"] >= 3:
                await emit("order.shipped", o, carrier=random.choice(["DHL", "UPS", "PostNL"]))
                open_orders.pop(oid)
        while len(open_orders) > 500:
            open_orders.pop(next(iter(open_orders)))
        await asyncio.sleep(1.0 / max(rate, 0.1))


SENSOR_SCHEMA = {
    "type": "record",
    "name": "SensorReading",
    "namespace": "plant",
    "fields": [
        {"name": "plant", "type": "string"},
        {"name": "line", "type": "string"},
        {"name": "sensor_id", "type": "string"},
        {"name": "temperature_c", "type": "double"},
        {"name": "pressure_bar", "type": "double"},
        {"name": "vibration_mm_s", "type": "double"},
        {"name": "running", "type": "boolean"},
        {"name": "ts", "type": {"type": "long", "logicalType": "timestamp-millis"}},
    ],
}


async def role_sensors() -> None:
    import io

    from fastavro import parse_schema, schemaless_writer

    topic = env("TOPIC", "plant.sensors")
    await ensure_topics({topic: 3})
    ref = [await kafka_producer()]
    schema = parse_schema(SENSOR_SCHEMA)
    log.info("sensors: Avro schema %s", json.dumps(SENSOR_SCHEMA))
    sensors = [(f"line-{ln}", f"press-{ln}{s}") for ln in (1, 2) for s in "abc"]
    rate = float(env("RATE", "2"))
    t0 = time.time()
    while True:
        if take_poison():
            await send_retry(ref, topic, os.urandom(7), b"poison")
            log.info("sent one malformed Avro message to %s", topic)
        t = time.time() - t0
        for i, (line, sid) in enumerate(sensors):
            running = (int(t / 300) + i) % 7 != 0
            rec = {
                "plant": "rotterdam",
                "line": line,
                "sensor_id": sid,
                "temperature_c": round(62 + 8 * math.sin(t / 90 + i) + random.gauss(0, 0.4) - (0 if running else 30), 2),
                "pressure_bar": round((180 if running else 2) + random.gauss(0, 1.5), 2),
                "vibration_mm_s": round(abs((2.4 if running else 0.1) + random.gauss(0, 0.3)), 3),
                "running": running,
                "ts": now_ms(),
            }
            buf = io.BytesIO()
            schemaless_writer(buf, schema, rec)
            await send_retry(ref, topic, buf.getvalue(), sid.encode(), [("schema", b"plant.SensorReading")])
        await asyncio.sleep(1.0 / max(rate, 0.1))


async def role_load() -> None:
    """A one-off burst for throughput tests."""
    from aiokafka import AIOKafkaProducer

    topic = env("TOPIC", "load.events")
    count, rate = int(env("LOAD_COUNT", "100000")), float(env("LOAD_RATE", "5000"))
    devices = int(env("LOAD_DEVICES", "50"))
    await ensure_topics({topic: int(env("LOAD_PARTITIONS", "6"))})
    p = AIOKafkaProducer(linger_ms=10, acks=1, max_batch_size=262144, **kafka_kwargs())
    await p.start()
    start = time.time()
    try:
        for i in range(count):
            body = {"seq": i, "sent_ms": now_ms(), "device": f"dev-{i % devices:03d}", "value": round(random.random() * 100, 3)}
            await p.send(topic, json.dumps(body).encode(), key=body["device"].encode())
            ahead = (i + 1) / rate - (time.time() - start)
            if ahead > 0:
                await asyncio.sleep(ahead)
            if i and i % 10000 == 0:
                log.info("load: %d sent, %.0f/s", i, i / (time.time() - start))
        await p.flush()
    finally:
        await p.stop()
    took = time.time() - start
    log.info("load: done, %d messages in %.1fs, %.0f msgs/s to %s", count, took, count / took, topic)


# RabbitMQ


async def role_logistics() -> None:
    import aio_pika

    url = f"amqp://{env('AMQP_USER', 'guest')}:{env('AMQP_PASSWORD', 'guest')}@{env('AMQP_HOST', 'rabbitmq')}:5672/"
    for attempt in range(1000):
        try:
            conn = await aio_pika.connect_robust(url, client_properties={"connection_name": "logistics-sim"})
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("waiting for RabbitMQ: %s", type(exc).__name__)
            await backoff_sleep(attempt)
    ch = await conn.channel(publisher_confirms=True)
    ex = await ch.declare_exchange("logistics.events", aio_pika.ExchangeType.TOPIC, durable=True)
    q = await ch.declare_queue(
        "telemetry.shipments", durable=True,
        arguments={"x-max-length": 50000, "x-overflow": "drop-head"},
    )
    await q.bind(ex, "shipment.#")
    cex = await ch.declare_exchange("logistics.commands", aio_pika.ExchangeType.TOPIC, durable=True)
    cq = await ch.declare_queue("logistics.commands.sim", durable=True, arguments={"x-max-length": 1000})
    await cq.bind(cex, "#")

    async def on_cmd(msg: aio_pika.abc.AbstractIncomingMessage) -> None:
        async with msg.process():
            log.info("command received on %s: %s", msg.routing_key, msg.body[:500].decode(errors="replace"))

    await cq.consume(on_cmd)
    cities = [("Rotterdam", 51.92, 4.48), ("Antwerp", 51.22, 4.40), ("Hamburg", 53.55, 9.99), ("Duisburg", 51.43, 6.76), ("Lyon", 45.76, 4.84)]
    flow = ["label_created", "picked_up", "in_transit", "in_transit", "out_for_delivery", "delivered"]
    shipments: dict[str, dict] = {}
    rate = float(env("RATE", "3"))
    log.info("logistics: %s updates/s on exchange logistics.events, queue telemetry.shipments", rate)
    while True:
        if take_poison():
            await ex.publish(aio_pika.Message(b"<shipment status=broken", content_type="application/json"), routing_key="shipment.in_transit")
            log.info("sent one malformed shipment message")
        if len(shipments) < 30:
            sid = f"SHP{random.randint(100000, 999999)}"
            shipments[sid] = {"step": 0, "carrier": random.choice(["DHL", "DSV", "Kuehne+Nagel", "DB Schenker"]), "weight_kg": round(random.uniform(1, 900), 1), "city": random.choice(cities)}
        sid = random.choice(list(shipments))
        s = shipments[sid]
        status = "exception" if random.random() < 0.02 else flow[min(s["step"], len(flow) - 1)]
        s["step"] += 1
        city, lat, lon = s["city"] if random.random() > 0.3 else random.choice(cities)
        body = {
            "shipment_id": sid, "carrier": s["carrier"], "status": status,
            "location": {"city": city, "lat": round(lat + random.gauss(0, 0.05), 5), "lon": round(lon + random.gauss(0, 0.05), 5)},
            "weight_kg": s["weight_kg"], "eta_hours": max(0, 48 - 8 * s["step"]), "ts": now_iso(),
        }
        try:
            await ex.publish(
                aio_pika.Message(
                    json.dumps(body).encode(), content_type="application/json", message_id=str(uuid.uuid4()),
                    timestamp=datetime.now(timezone.utc), type="shipment.status", app_id="logistics-sim",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=f"shipment.{status}",
            )
            SENT["n"] += 1
        except Exception as exc:  # noqa: BLE001
            SENT["errors"] += 1
            log.warning("publish failed, the connection recovers on its own: %s", type(exc).__name__)
            await asyncio.sleep(2)
        if status in ("delivered", "exception"):
            shipments.pop(sid, None)
        await asyncio.sleep(1.0 / max(rate, 0.1))


# NATS


async def role_fleet() -> None:
    import nats
    from nats.js.api import StreamConfig

    async def disconnected() -> None:
        log.warning("NATS disconnected, reconnecting")

    async def reconnected() -> None:
        log.info("NATS reconnected")

    for attempt in range(1000):
        try:
            nc = await nats.connect(
                env("NATS_URL", "nats://nats:4222"), user=env("NATS_USER") or None, password=env("NATS_PASSWORD") or None,
                name="fleet-sim", max_reconnect_attempts=-1, reconnect_time_wait=1,
                disconnected_cb=disconnected, reconnected_cb=reconnected,
            )
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("waiting for NATS: %s", type(exc).__name__)
            await backoff_sleep(attempt)
    js = nc.jetstream()

    async def ensure_stream() -> None:
        cfg = StreamConfig(name="FLEET", subjects=["fleet.positions.>", "fleet.status.>"], max_age=3600, max_bytes=64 * 1024 * 1024, storage="file")
        try:
            await js.add_stream(cfg)
        except Exception:  # noqa: BLE001
            await js.update_stream(cfg)

    await ensure_stream()

    async def on_cmd(msg) -> None:
        log.info("command received on %s: %s", msg.subject, msg.data[:500].decode(errors="replace"))
        if msg.reply:
            await msg.respond(b'{"ok": true}')

    await nc.subscribe("fleet.commands.>", cb=on_cmd)
    vehicles = {
        f"TRK-{i:03d}": {"lat": 51.9 + random.uniform(-0.15, 0.15), "lon": 4.4 + random.uniform(-0.3, 0.3), "hdg": random.uniform(0, 360), "fuel": random.uniform(40, 100), "odo": random.uniform(20000, 300000), "region": random.choice(["nl-south", "nl-west"])}
        for i in range(1, int(env("VEHICLES", "20")) + 1)
    }
    period = float(env("PERIOD", "1"))
    log.info("fleet: %d vehicles every %ss on fleet.positions.<region>.<vehicle>", len(vehicles), period)
    while True:
        if take_poison():
            await js.publish("fleet.positions.nl-west.TRK-999", b"\x00\xffnot json")
            log.info("sent one malformed position")
        for vid, v in vehicles.items():
            speed = max(0.0, random.gauss(55, 20))
            v["hdg"] = (v["hdg"] + random.gauss(0, 8)) % 360
            d = speed / 3600 * period / 111
            v["lat"] += d * math.cos(math.radians(v["hdg"]))
            v["lon"] += d * math.sin(math.radians(v["hdg"])) / math.cos(math.radians(v["lat"]))
            v["fuel"] = v["fuel"] - 0.002 * speed if v["fuel"] > 8 else 100.0
            v["odo"] += speed * period / 3600
            body = {"vehicle_id": vid, "lat": round(v["lat"], 6), "lon": round(v["lon"], 6), "speed_kmh": round(speed, 1), "heading_deg": round(v["hdg"], 1), "fuel_pct": round(v["fuel"], 1), "odometer_km": round(v["odo"], 2), "ts": now_iso()}
            try:
                await js.publish(f"fleet.positions.{v['region']}.{vid}", json.dumps(body).encode(), headers={"Nats-Msg-Id": f"{vid}-{now_ms()}"})
                SENT["n"] += 1
            except Exception as exc:  # noqa: BLE001
                SENT["errors"] += 1
                log.warning("publish failed: %s", type(exc).__name__)
                await asyncio.sleep(1)
                try:
                    await ensure_stream()
                except Exception:  # noqa: BLE001
                    pass
                break
        await asyncio.sleep(period)


# Modbus TCP energy meter

METER_MAP = """holding registers, unit id 1, big-endian bytes
  0-1   voltage_v          float32  word order big (ABCD)
  2-3   current_a          float32
  4-5   active_power_kw    float32
  6-7   energy_kwh         uint32   scale 0.1
  8     frequency_hz       uint16   scale 0.01
  9     power_factor       int16    scale 0.001
  10    setpoint_kw        uint16   scale 0.1   writable
  11    temperature_c      int16    scale 0.1
  20-21 voltage_v          float32  word order little (CDAB)
  22-23 reactive_kvarh     int32
input registers 0-11 mirror holding 0-11
coil 0              breaker_closed  writable
discrete inputs 0   overload_alarm, 1 phase_loss"""


def f32(v: float, little_words: bool = False) -> list[int]:
    hi, lo = struct.unpack(">HH", struct.pack(">f", v))
    return [lo, hi] if little_words else [hi, lo]


def u32(v: int) -> list[int]:
    v &= 0xFFFFFFFF
    return [v >> 16, v & 0xFFFF]


def i16(v: int) -> int:
    return v & 0xFFFF


async def role_meter() -> None:
    from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
    from pymodbus.server import StartAsyncTcpServer

    dev = ModbusDeviceContext(
        di=ModbusSequentialDataBlock(1, [0] * 32),
        co=ModbusSequentialDataBlock(1, [1] * 32),
        hr=ModbusSequentialDataBlock(1, [0] * 64),
        ir=ModbusSequentialDataBlock(1, [0] * 64),
    )
    ctx = ModbusServerContext(devices={int(env("UNIT_ID", "1")): dev}, single=False)
    dev.setValues(3, 10, [500])
    log.info("meter: Modbus TCP on :%s\n%s", env("MODBUS_PORT", "5020"), METER_MAP)

    async def update() -> None:
        energy, kvarh, last_sp, t0 = 1234567.0, 0, 500, time.time()
        while True:
            t = time.time() - t0
            sp = dev.getValues(3, 10, 1)[0]
            if sp != last_sp:
                log.info("setpoint written: %.1f kW", sp / 10)
                last_sp = sp
            closed = bool(dev.getValues(1, 0, 1)[0])
            v = 230 + 3 * math.sin(t / 40) + random.gauss(0, 0.3)
            target = sp / 10 * (0.9 + 0.1 * math.sin(t / 25)) if closed else 0.0
            p = max(0.0, target + random.gauss(0, 0.2) if closed else 0.0)
            pf = 0.95 + 0.03 * math.sin(t / 60)
            i = p * 1000 / (math.sqrt(3) * 400 * pf) if p else 0.0
            energy += p / 3600 * 10
            kvarh += int(p * 0.3)
            temp = 31 + p / 10 + random.gauss(0, 0.2)
            regs = f32(v) + f32(i) + f32(p) + u32(int(energy)) + [int(round((50 + random.gauss(0, 0.02)) * 100)), i16(int(pf * 1000)), sp, i16(int(temp * 10))]
            dev.setValues(3, 0, regs)
            dev.setValues(4, 0, regs)
            dev.setValues(3, 20, f32(v, little_words=True) + u32(kvarh))
            dev.setValues(2, 0, [int(p > 60), 0])
            SENT["n"] += 1
            await asyncio.sleep(1)

    asyncio.create_task(update())
    await StartAsyncTcpServer(context=ctx, address=("0.0.0.0", int(env("MODBUS_PORT", "5020"))))


# WebSocket price ticks


async def role_prices() -> None:
    from websockets.asyncio.server import serve

    token = env("WS_TOKEN")
    symbols = {"BTC-USD": 64000.0, "ETH-USD": 3100.0, "EUR-USD": 1.08, "GBP-USD": 1.27, "AAPL": 228.0, "MSFT": 431.0, "BRENT": 82.0, "TTF-GAS": 34.0}
    clients: dict = {}

    def process_request(connection, request):
        if request.path.split("?")[0] not in ("/ticks", "/"):
            return connection.respond(404, "Unknown path, use /ticks\n")
        if token and request.headers.get("Authorization", "") != f"Bearer {token}":
            log.info("refused a connection with a missing or wrong token")
            return connection.respond(401, "Missing or wrong bearer token\n")
        return None

    async def handler(ws) -> None:
        clients[ws] = set(symbols)
        log.info("client connected, %d now", len(clients))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    await ws.send(json.dumps({"type": "error", "error": "send JSON"}))
                    continue
                if msg.get("op") == "subscribe":
                    want = {s for s in msg.get("symbols") or [] if s in symbols} or set(symbols)
                    clients[ws] = want
                    await ws.send(json.dumps({"type": "subscribed", "symbols": sorted(want)}))
                else:
                    log.info("command received: %s", str(raw)[:500])
                    await ws.send(json.dumps({"type": "ack", "received": msg, "ts": now_iso()}))
        finally:
            clients.pop(ws, None)
            log.info("client left, %d now", len(clients))

    async def ticker() -> None:
        hz = float(env("RATE", "10"))
        while True:
            sym = random.choice(list(symbols))
            px = symbols[sym] = max(0.01, symbols[sym] * (1 + random.gauss(0, 0.0006)))
            spread = px * 0.0002
            tick = json.dumps({"type": "tick", "symbol": sym, "bid": round(px - spread, 5), "ask": round(px + spread, 5), "last": round(px, 5), "volume": round(random.expovariate(1 / 3), 4), "ts": now_iso()})
            poison = take_poison()
            for ws, subs in list(clients.items()):
                try:
                    if poison:
                        await ws.send('{"type": "tick", "symbol": ')
                    if sym in subs:
                        await ws.send(tick)
                        SENT["n"] += 1
                except Exception:  # noqa: BLE001
                    pass
            if poison:
                log.info("sent one malformed tick")
            await asyncio.sleep(1.0 / max(hz, 0.1))

    asyncio.create_task(ticker())
    port = int(env("WS_PORT", "8765"))
    log.info("prices: ws://0.0.0.0:%d/ticks, token %s", port, "required" if token else "not required")
    async with serve(handler, "0.0.0.0", port, process_request=process_request, ping_interval=20, ping_timeout=20):
        await asyncio.Future()


# HTTP pusher


async def pusher_target(http, folder: Path) -> tuple[str, str]:
    """Where to post: the Secret files when an admin gave them, else what Abenix told the info service."""
    if (folder / "url").exists() and (folder / "token").exists():
        return (folder / "url").read_text().strip(), (folder / "token").read_text().strip()
    try:
        r = await http.get(f"{env('INFO_URL', 'http://testbed-info:8080')}/pusher")
        t = r.json() if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        t = {}
    if t.get("connection_id") and t.get("token"):
        base = env("ABENIX_API_URL", "http://abenix-api.abenix.svc.cluster.local:8000").rstrip("/")
        return f"{base}/api/telemetry/ingest/{t['connection_id']}", t["token"]
    return "", ""


async def role_pusher() -> None:
    import httpx

    folder = Path(env("PUSH_DIR", "/etc/pusher"))
    stations = [f"WS-{c}" for c in ("AMS", "RTM", "UTR", "EIN", "GRQ")]
    said_idle = 0.0
    period = float(env("PERIOD", "2"))
    url, token, checked = "", "", 0.0
    async with httpx.AsyncClient(timeout=10) as http:
        while True:
            if not token or time.time() - checked > 30:
                url, token = await pusher_target(http, folder)
                checked = time.time()
            if not url or not token:
                if time.time() - said_idle > 60:
                    log.info(
                        "idle: no http_push source yet. In Abenix use Try the testbed, "
                        "or run bash scripts/deploy.sh testbed-connect"
                    )
                    said_idle = time.time()
                await asyncio.sleep(10)
                continue
            lines = [
                json.dumps({"station": s, "temperature_c": round(12 + random.gauss(0, 3), 2), "humidity_pct": round(min(100, max(10, random.gauss(78, 8))), 1), "wind_ms": round(abs(random.gauss(6, 3)), 1), "pressure_hpa": round(random.gauss(1013, 6), 1), "ts": now_iso()})
                for s in stations
            ]
            if take_poison():
                lines.append('{"station": "WS-BAD", "temperature_c": ')
            body = ("\n".join(lines) + "\n").encode()
            try:
                r = await http.post(url, content=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-ndjson"})
                if r.status_code in (401, 403, 404):
                    log.warning("push refused with %s, asking for the target again", r.status_code)
                    token = ""
                elif r.status_code >= 300:
                    SENT["errors"] += 1
                    log.warning("push answered %s: %s", r.status_code, r.text[:200])
                else:
                    SENT["n"] += len(lines)
                    if SENT["n"] % 500 < len(lines):
                        log.info("pushed %d readings so far", SENT["n"])
            except Exception as exc:  # noqa: BLE001
                SENT["errors"] += 1
                log.warning("push failed: %s", type(exc).__name__)
            await asyncio.sleep(period)


# Testbed info: the ready-made connections Abenix adds with one click, and the pusher's target

PREFIX = "Testbed · "
METER_REGISTERS = "\n".join(
    [
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
    ]
)
# names say what OPC PLC really simulates, only the boiler's temperature is physical
OPC_NODES = "\n".join(
    [
        "ns=3;s=StepUp = Counters/StepUp",
        "ns=3;s=SlowDouble1 = Random/Slow1",
        "ns=3;s=SlowDouble2 = Random/Slow2",
        "ns=3;s=FastDouble1 = Random/Fast1",
        "ns=3;s=AlternatingBoolean = Signals/Toggle",
        "ns=3;s=BadSlowDouble1 = Random/SlowWithBadStatus",
        "ns=3;s=DipData = Anomaly/Dip",
        "ns=3;s=SpikeData = Anomaly/Spike",
        "ns=3;s=PositiveTrendData = Trend/Rising",
        "ns=3;s=NegativeTrendData = Trend/Falling",
        "ns=4;i=6211 = Boiler2/Temperature_C",
        "ns=4;i=6212 = Boiler2/HeaterOn",
        "ns=4;i=6214 = Boiler2/Overheated",
        "ns=4;i=6198 = Boiler2/DeviceHealth",
    ]
)
# node id: unit, for the nodes OPC PLC simulates as a physical quantity
OPC_PHYSICAL = {"ns=4;i=6211": "C"}


def testbed_sources() -> list[dict]:
    d = f"{env('NAMESPACE', 'abenix-testbed')}.svc.cluster.local"
    kafka = {
        "bootstrap_servers": f"redpanda.{d}:9092",
        "security_protocol": "SASL_PLAINTEXT",
        "sasl_mechanism": "SCRAM-SHA-256",
        "username": "abenix",
        "start_from": "latest",
    }
    return [
        {
            "name": PREFIX + "Kafka shop orders",
            "transport": "kafka",
            "config": kafka,
            "secrets": {"password": env("KAFKA_PASSWORD")},
            "subjects": ["shop.orders"],
            "decoder": "json",
            "mapping": {
                "group": "payments",
                "node": "$.merchant",
                "device": "$.region",
                "timestamp": {"path": "$.occurred_at", "format": "iso"},
                "event": {"name": "$.type"},
                "signals": {"include": ["amount"]},
                "writable": [
                    {
                        "signal": "Refund",
                        "target": {
                            "topic": "shop.commands",
                            "payload": '{"action": "refund", "order_id": {value}, "reason": "Abenix"}',
                        },
                    }
                ],
            },
        },
        {
            "name": PREFIX + "Kafka plant sensors (Avro)",
            "transport": "kafka",
            "config": kafka,
            "secrets": {"password": env("KAFKA_PASSWORD")},
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
            "name": PREFIX + "RabbitMQ shipments",
            "transport": "amqp",
            "config": {
                "host": f"rabbitmq.{d}",
                "port": 5672,
                "username": "abenix",
                "mode": "exchange",
                "exchange": "logistics.events",
                "exchange_type": "topic",
                "queue": "abenix.testbed-shipments",
                "queue_max_length": 100000,
                "prefetch": 500,
            },
            "secrets": {"password": env("RABBITMQ_PASSWORD")},
            "subjects": ["shipment.#"],
            "decoder": "json",
            # a shipment is an event at a hub, not a device: carriers x hubs stays a fixed set
            "mapping": {
                "group": "logistics",
                "node": "$.carrier",
                "device": "$.location.city",
                "timestamp": {"path": "$.ts", "format": "iso"},
                "event": {"name": "$.status"},
                "signals": {
                    "include": ["weight_kg", "eta_hours"],
                    "units": {"weight_kg": "kg", "eta_hours": "h"},
                },
                "writable": [
                    {
                        "signal": "Hold",
                        "target": {
                            "exchange": "logistics.commands",
                            "routing_key": "shipment.hold",
                            "payload": '{"shipment_id": {value}, "hold": true, "hub": "{device}"}',
                        },
                    }
                ],
                "offline_after_s": 600,
            },
        },
        {
            "name": PREFIX + "NATS fleet positions",
            "transport": "nats",
            "config": {
                "servers": f"nats://nats.{d}:4222",
                "username": "abenix",
                "mode": "jetstream",
                "stream": "FLEET",
                "deliver_policy": "new",
            },
            "secrets": {"password": env("NATS_PASSWORD")},
            "subjects": ["fleet.positions.>"],
            "decoder": "json",
            "mapping": {
                "group": "fleet",
                "node": "{subject.2}",
                "device": "$.vehicle_id",
                "timestamp": {"path": "$.ts", "format": "iso"},
                "signals": {
                    "exclude": ["vehicle_id", "ts"],
                    "units": {"speed_kmh": "km/h", "fuel_pct": "%", "odometer_km": "km", "heading_deg": "deg"},
                },
                "writable": [
                    {
                        "signal": "Command",
                        "target": {"subject": "fleet.commands.{device}", "payload": '{"action": {value}}'},
                    }
                ],
            },
        },
        {
            "name": PREFIX + "OPC UA PLC",
            "transport": "opcua",
            "config": {
                "endpoint": f"opc.tcp://opc-plc.{d}:50000",
                "username": "abenix",
                "security_policy": "None",
                "security_mode": "None",
                "asset": "plant/opc-plc",
                "nodes": OPC_NODES,
                "sampling_interval_ms": 500,
                "publishing_interval_ms": 1000,
            },
            "secrets": {"password": env("OPCUA_PASSWORD")},
            "decoder": "values",
            "mapping": {
                "signals": {"units": {"Boiler2/Temperature_C": "C"}},
                "writable": [{"signal": "Counters/StepUp", "target": {"node_id": "ns=3;s=StepUp"}}],
            },
        },
        {
            "name": PREFIX + "Modbus energy meter",
            "transport": "modbus_tcp",
            "config": {
                "host": f"meter.{d}",
                "port": 502,
                "unit_id": 1,
                "registers": METER_REGISTERS,
                "poll_interval_ms": 1000,
                "asset": "energy/meter-1",
            },
            "secrets": {},
            "decoder": "values",
            "mapping": {
                "writable": [
                    {"signal": "Setpoint_kW", "target": {"register": "Setpoint_kW"}},
                    {"signal": "BreakerClosed", "target": {"coil": "BreakerClosed"}},
                ]
            },
        },
        {
            "name": PREFIX + "WebSocket market prices",
            "transport": "websocket",
            "config": {
                "url": f"ws://prices.{d}:8765/ticks",
                "subject": "markets/prices",
                "subscribe_message": '{"op": "subscribe", "symbols": {subjects}}',
            },
            "secrets": {"auth_header": "Bearer " + env("WS_TOKEN")},
            "subjects": ["BTC-USD", "ETH-USD", "EUR-USD", "GBP-USD", "AAPL", "MSFT", "BRENT", "TTF-GAS"],
            "decoder": "json",
            "mapping": {
                "group": "markets",
                "node": "$.symbol",
                "device": "",
                "timestamp": {"path": "$.ts", "format": "iso"},
                "signals": {"include": ["bid", "ask", "last", "volume"]},
                "writable": [
                    {
                        "signal": "Order",
                        "target": {
                            "payload": '{"op": "order", "symbol": "{node}", "qty": {value}}',
                            "reply_contains": '"ack"',
                        },
                    }
                ],
            },
        },
        {
            "name": PREFIX + "HTTP push weather stations",
            "transport": "http_push",
            "config": {},
            "secrets": {},
            "decoder": "json_lines",
            "mapping": {
                "group": "weather",
                "node": "$.station",
                "device": "",
                "timestamp": {"path": "$.ts", "format": "iso"},
                "signals": {
                    "exclude": ["station", "ts"],
                    "units": {"temperature_c": "C", "humidity_pct": "%", "wind_ms": "m/s", "pressure_hpa": "hPa"},
                },
            },
        },
    ]


async def serve_http(port: int, route) -> None:
    """Enough HTTP/1.1 for a JSON service inside the cluster."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            lines = head.decode(errors="replace").split("\r\n")
            method, path = lines[0].split(" ")[:2]
            size = 0
            for h in lines[1:]:
                if h.lower().startswith("content-length:"):
                    size = min(int(h.split(":", 1)[1]), 65536)
            body = await reader.readexactly(size) if size else b""
            code, out = await route(method, path.split("?")[0], body)
            data = json.dumps(out).encode()
            writer.write(
                f"HTTP/1.1 {code} OK\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode()
                + data
            )
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "0.0.0.0", port)
    async with server:
        await server.serve_forever()


async def role_info() -> None:
    store = Path(env("DATA_DIR", "/data")) / "pusher.json"

    async def route(method: str, path: str, body: bytes):
        if path == "/healthz":
            return 200, {"ok": True}
        if path == "/sources" and method == "GET":
            return 200, {"namespace": env("NAMESPACE", "abenix-testbed"), "sources": testbed_sources()}
        if path == "/pusher" and method == "GET":
            return 200, json.loads(store.read_text()) if store.exists() else {}
        if path == "/pusher" and method == "POST":
            t = json.loads(body or b"{}")
            if not t.get("connection_id") or not t.get("token"):
                return 422, {"error": "connection_id and token are both needed"}
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(json.dumps({"connection_id": str(t["connection_id"]), "token": str(t["token"])}))
            log.info("the HTTP pusher now posts to connection %s", t["connection_id"])
            return 200, {"ok": True}
        return 404, {"error": "not found"}

    log.info("info: the testbed's ready-made connections on :8080/sources")
    await serve_http(int(env("INFO_PORT", "8080")), route)


ROLES = {
    "payments": role_payments,
    "sensors": role_sensors,
    "load": role_load,
    "logistics": role_logistics,
    "fleet": role_fleet,
    "meter": role_meter,
    "prices": role_prices,
    "pusher": role_pusher,
    "info": role_info,
}


async def main(role: str) -> None:
    os.environ["ROLE"] = role
    if role != "load":
        asyncio.create_task(control_server())
    await ROLES[role]()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("aiokafka").setLevel(logging.ERROR)
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    if len(sys.argv) < 2 or sys.argv[1] not in ROLES:
        print(f"usage: sim.py {{{'|'.join(ROLES)}}}")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
