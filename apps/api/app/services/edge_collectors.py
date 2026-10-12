"""Abenix Edge collectors: the catalog the UI builds its forms from, validation, and install commands.

The gateway side lives in apps/edge-runtime/abenix_edge. Types and field keys
here must match the collectors there.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
from typing import Any
from urllib.parse import urlparse

MASK = "********"
SLUG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TEMPLATE_SLUG = re.compile(r"^([A-Za-z0-9_-]|\{topic\.\d+\}){1,64}$")
CHANNEL = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")
NODE_ID = re.compile(r"^(ns=\d+;)?[isgb]=.+$")
MAX_DBC = 2 * 1024 * 1024
MAX_COLLECTORS = 32
OBD_PIDS = {
    0x04,
    0x05,
    0x0B,
    0x0C,
    0x0D,
    0x0F,
    0x10,
    0x11,
    0x1F,
    0x2F,
    0x31,
    0x42,
    0x46,
    0x5C,
    0x5E,
}


def F(key: str, label: str, kind: str = "string", **kw: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "kind": kind, "required": False, **kw}


CATALOG: list[dict[str, Any]] = [
    {
        "type": "can",
        "label": "Vehicle or machine CAN bus",
        "short": "J1939, OBD-II or any bus with a DBC file",
        "description": (
            "Reads the engine and machine data straight off the bus: J1939 on trucks, buses and "
            "construction machines, OBD-II on cars and vans, or any CAN bus you have a DBC file for. "
            "Needs a Linux box with a CAN interface, such as a PEAK or Kvaser USB adapter or a "
            "gateway with CAN built in."
        ),
        "category": "vehicle",
        "default_interval_s": 1,
        "asset_hint": {"group": "fleet", "node": "truck-12", "device": ""},
        "device_from_bus": True,
        "fields": [
            F(
                "interface",
                "How the bus is reached",
                "select",
                default="socketcan",
                options=[
                    {
                        "value": "socketcan",
                        "label": "A CAN interface on this box (socketcan)",
                    },
                    {
                        "value": "socketcand",
                        "label": "A bus served over the network (socketcand)",
                    },
                ],
                help="socketcan reads can0 on the box itself. socketcand reads a bus another computer serves, such as an industrial PC on the machine.",
            ),
            F(
                "channel",
                "CAN interface",
                default="can0",
                required=True,
                example="can0",
                help="The name ip link show lists for the CAN interface. vcan0 for a virtual bus.",
            ),
            F(
                "host",
                "socketcand address",
                required=True,
                example="10.0.4.20",
                show_if={"interface": "socketcand"},
                help="The computer serving the bus over socketcand.",
            ),
            F(
                "port",
                "socketcand port",
                "int",
                default=29536,
                min=1,
                max=65535,
                example="29536",
                show_if={"interface": "socketcand"},
            ),
            F(
                "bitrate",
                "Bit rate",
                "select",
                default="250000",
                options=[
                    {"value": "125000", "label": "125 kbit/s"},
                    {
                        "value": "250000",
                        "label": "250 kbit/s (J1939 trucks and machines)",
                    },
                    {
                        "value": "500000",
                        "label": "500 kbit/s (most cars, J1939 on newer machines)",
                    },
                    {"value": "1000000", "label": "1 Mbit/s"},
                ],
                help="Must match the bus. A wrong bit rate shows as bus errors and no readings.",
            ),
            F(
                "protocol",
                "What the bus speaks",
                "select",
                default="j1939",
                options=[
                    {
                        "value": "j1939",
                        "label": "J1939 (trucks, buses, machines, gensets)",
                    },
                    {
                        "value": "obd2",
                        "label": "OBD-II (cars and vans, through the diagnostic port)",
                    },
                    {
                        "value": "dbc",
                        "label": "Something else, decoded with my DBC file",
                    },
                ],
            ),
            F(
                "dbc",
                "DBC file",
                "file",
                accept=".dbc",
                show_if={"protocol": ["j1939", "dbc"]},
                required_if={"protocol": "dbc"},
                help="Optional for J1939: engine speed, temperatures, fuel, speed, position, hours and fault codes are read without one. Upload the maker's DBC to read their own messages too.",
            ),
            F(
                "parts",
                "Part names by source address",
                example="0=engine, 3=transmission, 11=brakes",
                show_if={"protocol": ["j1939", "dbc"]},
                help="Each ECU becomes a part of the asset. Standard J1939 addresses are named for you, list any you want to rename.",
            ),
            F(
                "request_pgns",
                "Ask for these PGNs",
                example="65253, 65260",
                show_if={"protocol": "j1939"},
                help="Some values are only sent when asked, such as engine hours (65253). Edge claims an address on the bus to ask.",
            ),
            F(
                "request_every_s",
                "Ask every (seconds)",
                "number",
                default=10,
                min=1,
                max=3600,
                show_if={"protocol": "j1939"},
            ),
            F(
                "own_address",
                "Edge's own address",
                "int",
                default=249,
                min=0,
                max=253,
                show_if={"protocol": "j1939"},
                help="Used only to ask for PGNs. 249 is the service tool address. Edge moves to a free one if another ECU wins it.",
            ),
            F(
                "obd_pids",
                "OBD-II PIDs",
                default="0C, 0D, 05, 2F, 04",
                example="0C, 0D, 05",
                show_if={"protocol": "obd2"},
                help="In hex. 0C engine speed, 0D vehicle speed, 05 coolant, 2F fuel level, 04 engine load, 5E fuel rate.",
            ),
            F(
                "obd_extended",
                "29-bit OBD-II ids",
                "bool",
                default=False,
                show_if={"protocol": "obd2"},
                help="Only for vehicles that answer on 18DAF1xx. Most use 11-bit ids.",
            ),
        ],
    },
    {
        "type": "modbus",
        "label": "Modbus TCP or RTU",
        "short": "Meters, drives, PLCs and gensets",
        "description": (
            "Polls registers from meters, drives, PLCs and gensets. TCP over the site network, or RTU "
            "over an RS-485 serial adapter on the box."
        ),
        "category": "plc",
        "default_interval_s": 1,
        "asset_hint": {"group": "plant", "node": "meter-1", "device": "main"},
        "fields": [
            F(
                "mode",
                "Connection",
                "select",
                default="tcp",
                options=[
                    {"value": "tcp", "label": "Modbus TCP (network)"},
                    {"value": "rtu", "label": "Modbus RTU (RS-485 serial)"},
                ],
            ),
            F(
                "host",
                "Device address",
                required=True,
                example="192.168.1.50",
                show_if={"mode": "tcp"},
            ),
            F(
                "port",
                "Port",
                "int",
                default=502,
                min=1,
                max=65535,
                show_if={"mode": "tcp"},
            ),
            F(
                "serial_port",
                "Serial port",
                required=True,
                example="/dev/ttyUSB0",
                show_if={"mode": "rtu"},
                help="The RS-485 adapter on the box. In Docker it is passed in with --device.",
            ),
            F(
                "baudrate",
                "Baud rate",
                "select",
                default="9600",
                show_if={"mode": "rtu"},
                options=[
                    {"value": v, "label": v}
                    for v in (
                        "1200",
                        "2400",
                        "4800",
                        "9600",
                        "19200",
                        "38400",
                        "57600",
                        "115200",
                    )
                ],
            ),
            F(
                "parity",
                "Parity",
                "select",
                default="N",
                show_if={"mode": "rtu"},
                options=[
                    {"value": "N", "label": "None"},
                    {"value": "E", "label": "Even"},
                    {"value": "O", "label": "Odd"},
                ],
            ),
            F(
                "stopbits",
                "Stop bits",
                "select",
                default="1",
                show_if={"mode": "rtu"},
                options=[{"value": "1", "label": "1"}, {"value": "2", "label": "2"}],
            ),
            F(
                "unit_id",
                "Unit id",
                "int",
                default=1,
                min=0,
                max=247,
                help="The slave id. Behind a gateway it picks the device.",
            ),
            F(
                "registers",
                "Register map",
                "text",
                required=True,
                rows=6,
                example="voltage_v, holding, 0, float32, 1, V\nenergy_kwh, holding, 6, uint32, 0.1, kWh\nbreaker_closed, coil, 0",
                help="One register a line: name, table, address, type, scale, unit, word order, byte order. Tables: holding, input, coil, discrete. Types: int16, uint16, int32, uint32, float32, int64, uint64, float64.",
            ),
            F("timeout_s", "Timeout (seconds)", "number", default=2, min=0.2, max=30),
        ],
    },
    {
        "type": "opcua",
        "label": "OPC UA",
        "short": "PLCs and SCADA servers that speak OPC UA",
        "description": "Subscribes to chosen nodes on a PLC or OPC UA server on the site network, with status codes kept as quality.",
        "category": "plc",
        "default_interval_s": 1,
        "asset_hint": {"group": "plant", "node": "line-2", "device": "plc"},
        "fields": [
            F(
                "endpoint",
                "Server address",
                "url",
                required=True,
                example="opc.tcp://192.168.1.10:4840",
                pattern="^opc\\.tcp://",
            ),
            F(
                "security_policy",
                "Security policy",
                "select",
                default="None",
                options=[
                    {"value": "None", "label": "None"},
                    {"value": "Basic256Sha256", "label": "Basic256Sha256"},
                ],
                help="With Basic256Sha256 Edge makes its own certificate. Trust it on the server once.",
            ),
            F(
                "security_mode",
                "Security mode",
                "select",
                default="None",
                options=[
                    {"value": "None", "label": "None"},
                    {"value": "Sign", "label": "Sign"},
                    {"value": "SignAndEncrypt", "label": "Sign and encrypt"},
                ],
            ),
            F("username", "User name", example="operator"),
            F("password", "Password", "secret"),
            F(
                "nodes",
                "Nodes",
                "text",
                required=True,
                rows=5,
                example="ns=2;s=Boiler.Temperature, Boiler/Temp_C, C\nns=2;i=10853, Line/Speed_mps, m/s",
                help="One node a line: node id, then the signal name and unit you want in Abenix.",
            ),
            F(
                "read_mode",
                "How to read",
                "select",
                default="subscribe",
                options=[
                    {
                        "value": "subscribe",
                        "label": "Subscribe, the server sends changes",
                    },
                    {"value": "poll", "label": "Poll every interval"},
                ],
            ),
        ],
    },
    {
        "type": "nmea_gps",
        "label": "GPS receiver (NMEA)",
        "short": "Position, speed and heading from a serial or network GPS",
        "description": "Reads NMEA 0183 sentences (RMC, GGA, VTG) from a USB or serial GPS, or from a router or gpsd that serves them over TCP.",
        "category": "vehicle",
        "default_interval_s": 1,
        "asset_hint": {"group": "fleet", "node": "van-3", "device": "gps"},
        "fields": [
            F(
                "port",
                "Serial port or TCP address",
                required=True,
                default="/dev/ttyUSB0",
                example="/dev/ttyACM0 or tcp://192.168.1.1:10110",
            ),
            F(
                "baudrate",
                "Baud rate",
                "select",
                default="9600",
                options=[
                    {"value": v, "label": v}
                    for v in ("4800", "9600", "38400", "115200")
                ],
                help="Most USB receivers use 9600, older marine ones 4800. Not used for TCP.",
            ),
        ],
    },
    {
        "type": "mqtt_bridge",
        "label": "Local MQTT broker",
        "short": "Sensors, Zigbee or BLE hubs already on a site broker",
        "description": (
            "Bridges a broker on the site network, such as Mosquitto behind a Zigbee or BLE hub, to Abenix "
            "through the gateway's buffer, so nothing is lost when the link drops."
        ),
        "category": "sensor",
        "default_interval_s": 1,
        "asset_hint": {"group": "site", "node": "{topic.1}", "device": "sensors"},
        "asset_templates": True,
        "fields": [
            F(
                "broker",
                "Broker address",
                "url",
                default="mqtt://localhost:1883",
                required=True,
                example="mqtt://192.168.1.5:1883",
                pattern="^mqtts?://",
            ),
            F(
                "topics",
                "Topics",
                "text",
                default="#",
                rows=3,
                example="zigbee2mqtt/+\nsensors/#",
                help="One a line. + is one level, # is everything below.",
            ),
            F(
                "username",
                "User name",
                example="edge",
                help="Leave empty when the broker takes anonymous clients.",
            ),
            F("password", "Password", "secret"),
        ],
    },
    {
        "type": "file_tail",
        "label": "File or CSV tail",
        "short": "Logs a machine, logger or program writes to disk",
        "description": "Follows CSV or JSON lines files as they grow. Every column or field becomes a signal. Restarts carry on where they stopped.",
        "category": "software",
        "default_interval_s": 2,
        "asset_hint": {"group": "plant", "node": "press-1", "device": "logger"},
        "fields": [
            F(
                "path",
                "File path",
                required=True,
                example="/data/plc/*.csv",
                help="A file or a pattern on the gateway. In Docker, mount its folder too.",
            ),
            F(
                "format",
                "Format",
                "select",
                default="csv",
                options=[
                    {"value": "csv", "label": "CSV with a header row"},
                    {"value": "jsonl", "label": "JSON lines"},
                ],
            ),
            F(
                "timestamp_column",
                "Time column",
                example="timestamp",
                help="Epoch or ISO 8601. Empty uses ts, timestamp or time when there is one, else the time it was read.",
            ),
            F("from_start", "Read what is already in the file", "bool", default=False),
        ],
    },
]
TYPES = {c["type"]: c for c in CATALOG}

SETTINGS_FIELDS = [
    F(
        "buffer_max_mb",
        "Buffer size (MB)",
        "int",
        default=1024,
        min=16,
        max=262144,
        help="Disk the gateway may use to hold readings while the link is down. The oldest go first when it is full.",
    ),
    F(
        "buffer_max_age_h",
        "Keep readings for (hours)",
        "int",
        default=72,
        min=1,
        max=720,
        help="Readings older than this are dropped from the buffer, sent or not.",
    ),
    F("gzip", "Compress uploads", "bool", default=True),
    F(
        "heartbeat_s",
        "Heartbeat every (seconds)",
        "int",
        default=15,
        min=5,
        max=300,
        help="How often the gateway reports health and picks up changes made here.",
    ),
    F(
        "self_metrics_s",
        "Gateway readings every (seconds)",
        "int",
        default=10,
        min=1,
        max=3600,
        help="The gateway sends its own buffer depth, buffer age, uptime and a counter as signals, so rules can watch it.",
    ),
]


def catalog() -> dict[str, Any]:
    return {
        "types": CATALOG,
        "settings": SETTINGS_FIELDS,
        "asset_help": (
            "Readings land in Telemetry under a group, an asset and a part. Use letters, digits, - and _ "
            "only, such as fleet / truck-12 / engine."
        ),
    }


def _shown(field: dict[str, Any], c: dict[str, Any]) -> bool:
    cond = field.get("show_if")
    if not cond:
        return True
    for k, want in cond.items():
        have = str(c.get(k) if c.get(k) is not None else _default(k, c))
        if isinstance(want, list):
            if have not in [str(w) for w in want]:
                return False
        elif have != str(want):
            return False
    return True


def _default(key: str, c: dict[str, Any]) -> Any:
    t = TYPES.get(str(c.get("type") or ""))
    for f in (t or {}).get("fields", []):
        if f["key"] == key:
            return f.get("default")
    return None


def _required(field: dict[str, Any], c: dict[str, Any]) -> bool:
    if field.get("required"):
        return True
    cond = field.get("required_if")
    if cond:
        return all(str(c.get(k) or _default(k, c)) == str(v) for k, v in cond.items())
    return False


def new_id(name: str) -> str:
    base = (
        re.sub(r"[^a-z0-9]+", "-", (name or "collector").lower()).strip("-")[:40]
        or "collector"
    )
    return f"{base}-{secrets.token_hex(2)}"


def validate(c: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """A clean collector and a map of field to problem in plain words. Empty problems means it is fine."""
    problems: dict[str, str] = {}
    t = TYPES.get(str(c.get("type") or ""))
    if t is None:
        return c, {
            "type": "Pick what this collector reads: "
            + ", ".join(x["label"] for x in CATALOG)
        }
    out: dict[str, Any] = {
        "type": t["type"],
        "id": str(c.get("id") or "").strip() or new_id(str(c.get("name") or t["type"])),
    }
    name = str(c.get("name") or "").strip()
    if not name:
        problems["name"] = (
            "Give it a name people will recognise, such as Truck 12 engine bus"
        )
    elif len(name) > 80:
        problems["name"] = "Keep the name under 80 characters"
    out["name"] = name
    out["enabled"] = c.get("enabled", True) is not False
    asset = c.get("asset") or {}
    clean_asset: dict[str, str] = {}
    pat = TEMPLATE_SLUG if t.get("asset_templates") else SLUG
    for part, label, need in (
        ("group", "Group", True),
        ("node", "Asset", True),
        ("device", "Part", False),
    ):
        v = str(asset.get(part) or "").strip()
        if not v:
            if need:
                problems[f"asset.{part}"] = (
                    f"{label} is needed, such as {t['asset_hint'].get(part) or 'engine'}"
                )
            continue
        if not pat.match(v):
            problems[f"asset.{part}"] = (
                f"{label} may use letters, digits, - and _ only, such as {t['asset_hint'].get(part) or 'engine'}"
            )
        clean_asset[part] = v
    out["asset"] = clean_asset
    try:
        iv = float(
            c.get("interval_s")
            if c.get("interval_s") not in (None, "")
            else t["default_interval_s"]
        )
        if not 0.1 <= iv <= 3600:
            raise ValueError
        out["interval_s"] = iv
    except (TypeError, ValueError):
        problems["interval_s"] = (
            "Send every must be a number of seconds from 0.1 to 3600, such as 1"
        )
    for f in t["fields"]:
        k = f["key"]
        v = c.get(k)
        if not _shown(f, {**c, "type": t["type"]}):
            continue
        empty = v is None or (isinstance(v, str) and not v.strip())
        if empty:
            if _required(f, {**c, "type": t["type"]}) and f["kind"] != "bool":
                ex = f.get("example") or f.get("default")
                problems[k] = f"{f['label']} is needed" + (
                    f", such as {str(ex).splitlines()[0]}" if ex else ""
                )
            elif f.get("default") is not None:
                out[k] = f["default"]
            continue
        kind = f["kind"]
        if kind in ("int", "number"):
            try:
                n = float(v)
                if kind == "int" and not n.is_integer():
                    raise ValueError
            except (TypeError, ValueError):
                problems[k] = (
                    f"{f['label']} must be a {'whole ' if kind == 'int' else ''}number"
                    + (
                        f", such as {f.get('example') or f.get('default')}"
                        if f.get("example") or f.get("default") is not None
                        else ""
                    )
                )
                continue
            if ("min" in f and n < f["min"]) or ("max" in f and n > f["max"]):
                problems[k] = (
                    f"{f['label']} must be from {f.get('min')} to {f.get('max')}"
                )
                continue
            out[k] = int(n) if kind == "int" else n
        elif kind == "bool":
            out[k] = v in (True, "true", "1", 1, "on")
        elif kind == "select":
            allowed = [str(o["value"]) for o in f.get("options", [])]
            if str(v) not in allowed:
                problems[k] = f"{f['label']} must be one of {', '.join(allowed)}"
                continue
            out[k] = str(v)
        else:
            s = str(v)
            if kind != "secret":
                s = s.strip() if kind not in ("text", "file") else s
            if f.get("pattern") and not re.search(f["pattern"], s):
                problems[k] = f"{f['label']} should look like {f.get('example')}"
                continue
            out[k] = s
    _type_checks(t["type"], out, problems)
    return out, problems


def _type_checks(t: str, c: dict[str, Any], problems: dict[str, str]) -> None:
    if t == "can":
        if "channel" in c and not CHANNEL.match(str(c["channel"])):
            problems["channel"] = "The interface name is short, such as can0 or vcan0"
        if c.get("dbc"):
            if len(c["dbc"]) > MAX_DBC:
                problems["dbc"] = (
                    "The DBC file is over 2 MB. Upload the file for this bus only."
                )
            else:
                err = dbc_problem(c["dbc"])
                if err:
                    problems["dbc"] = err
        if c.get("parts"):
            for it in str(c["parts"]).replace(";", ",").split(","):
                it = it.strip()
                if not it:
                    continue
                a, eq, p = it.partition("=")
                try:
                    sa = int(a.strip(), 0)
                except ValueError:
                    sa = -1
                if not eq or not 0 <= sa <= 253 or not SLUG.match(p.strip()):
                    problems["parts"] = (
                        f"{it!r} should be address=part, such as 0=engine, with addresses 0 to 253"
                    )
                    break
        if c.get("request_pgns"):
            for it in (
                str(c["request_pgns"]).replace(";", ",").replace(" ", ",").split(",")
            ):
                if it.strip() and not (
                    it.strip().isdigit() and 0 < int(it.strip()) < 262144
                ):
                    problems["request_pgns"] = (
                        f"{it.strip()!r} is not a PGN, such as 65253 for engine hours"
                    )
                    break
        if c.get("protocol") == "obd2" and c.get("obd_pids"):
            for it in str(c["obd_pids"]).replace(";", ",").replace(" ", ",").split(","):
                s = it.strip().lower().removeprefix("0x")
                if not s:
                    continue
                try:
                    ok = int(s, 16) in OBD_PIDS
                except ValueError:
                    ok = False
                if not ok:
                    problems["obd_pids"] = (
                        f"{it.strip()} is not a PID Edge reads. Use "
                        + ", ".join(f"{p:02X}" for p in sorted(OBD_PIDS))
                    )
                    break
    elif t == "modbus":
        if c.get("registers"):
            try:
                from app.telemetry.connectors.modbus_tcp import parse_map

                parse_map(c["registers"])
            except Exception as exc:  # noqa: BLE001
                problems["registers"] = str(exc)
        if (
            c.get("mode") == "rtu"
            and c.get("serial_port")
            and not str(c["serial_port"]).startswith("/dev/")
        ):
            problems["serial_port"] = (
                "A serial port is a device path, such as /dev/ttyUSB0"
            )
    elif t == "opcua":
        names: set[str] = set()
        for n, line in enumerate(str(c.get("nodes") or "").splitlines(), 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if not NODE_ID.match(parts[0]):
                problems["nodes"] = (
                    f"Line {n}: {parts[0]!r} is not an OPC UA node id, such as ns=3;s=Temperature"
                )
                break
            nm = parts[1] if len(parts) > 1 and parts[1] else parts[0]
            if nm in names:
                problems["nodes"] = f"Line {n}: two nodes are called {nm}"
                break
            names.add(nm)
        if (
            c.get("security_policy", "None") != "None"
            and c.get("security_mode", "None") == "None"
        ):
            problems["security_mode"] = (
                "With a security policy, pick Sign or Sign and encrypt"
            )
    elif t == "nmea_gps":
        p = str(c.get("port") or "")
        if p and not (p.startswith("/dev/") or re.match(r"^tcp://[^:/]+:\d+$", p)):
            problems["port"] = (
                "Use a serial port such as /dev/ttyUSB0, or tcp://host:port"
            )
    elif t == "file_tail":
        p = str(c.get("path") or "")
        if p and not p.startswith("/"):
            problems["path"] = (
                "Use the full path on the gateway, starting with /, such as /data/plc/*.csv"
            )


def dbc_problem(text: str) -> str | None:
    try:
        import cantools

        db = cantools.database.load_string(text, "dbc", strict=False)
    except Exception as exc:  # noqa: BLE001
        return f"The DBC file could not be read: {str(exc)[:200]}"
    if not db.messages:
        return "The DBC file has no messages in it"
    return None


def dbc_summary(text: str) -> dict[str, Any]:
    import cantools

    db = cantools.database.load_string(text, "dbc", strict=False)
    out = []
    for m in db.messages[:500]:
        pgn = None
        if m.is_extended_frame:
            pf = (m.frame_id >> 16) & 0xFF
            dp = (m.frame_id >> 24) & 0x3
            ps = (m.frame_id >> 8) & 0xFF
            pgn = (dp << 16) | (pf << 8) | (ps if pf >= 240 else 0)
        out.append(
            {
                "name": m.name,
                "frame_id": f"0x{m.frame_id:X}",
                "pgn": pgn,
                "signals": [
                    {"name": s.name, "unit": s.unit or ""} for s in m.signals[:64]
                ],
            }
        )
    return {"messages": out, "count": len(db.messages)}


def merge_secrets(
    new: dict[str, Any], old: dict[str, Any] | None, tenant_id: Any
) -> dict[str, Any]:
    """Encrypt secret fields. A masked value keeps what was stored."""
    from app.core import crypto

    t = TYPES.get(new.get("type") or "")
    if not t:
        return new
    for f in t["fields"]:
        if f["kind"] != "secret":
            continue
        k = f["key"]
        v = new.get(k)
        if v == MASK:
            if old and old.get(k):
                new[k] = old[k]
            else:
                new.pop(k, None)
        elif v:
            new[k] = crypto.encrypt(tenant_id, str(v))
        else:
            new.pop(k, None)
    return new


def masked(c: dict[str, Any]) -> dict[str, Any]:
    t = TYPES.get(c.get("type") or "")
    out = dict(c)
    for f in (t or {}).get("fields", []):
        if f["kind"] == "secret" and out.get(f["key"]):
            out[f["key"]] = MASK
    if out.get("dbc"):
        out["dbc_bytes"] = len(out["dbc"])
    return out


def for_gateway(c: dict[str, Any], tenant_id: Any) -> dict[str, Any]:
    from app.core import crypto

    t = TYPES.get(c.get("type") or "")
    out = dict(c)
    for f in (t or {}).get("fields", []):
        if f["kind"] == "secret" and out.get(f["key"]):
            out[f["key"]] = crypto.decrypt(tenant_id, out[f["key"]])
    return out


def clean_settings(s: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    out: dict[str, Any] = {}
    problems: dict[str, str] = {}
    for f in SETTINGS_FIELDS:
        v = s.get(f["key"], f["default"])
        if f["kind"] == "bool":
            out[f["key"]] = v in (True, "true", 1, "1", "on")
            continue
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            problems[f["key"]] = f"{f['label']} must be a whole number"
            continue
        if not f["min"] <= n <= f["max"]:
            problems[f["key"]] = f"{f['label']} must be from {f['min']} to {f['max']}"
            continue
        out[f["key"]] = n
    return out, problems


# install commands


def image(name: str = "edge-runtime") -> str:
    """The edge image for a variant, the same on the install step and the Edge page."""
    explicit = os.environ.get("EDGE_COLLECTOR_IMAGE", "").strip()
    if explicit and name == "edge-runtime":
        return explicit
    tag = os.environ.get("EDGE_IMAGE_TAG", "").strip() or "latest"
    # same registry as the platform's own images on this cluster
    ref = os.environ.get("ML_MODEL_SERVING_IMAGE", "").strip()
    if ref and "/" in ref:
        return ref.rsplit("/", 1)[0] + f"/{name}:{tag}"
    return f"ghcr.io/abenix/{name}:{tag}"


def platform_urls(
    public: str | None = None, request_base: str | None = None
) -> list[dict[str, str]]:
    """Addresses a gateway might use, the platform.public_api_url setting first, then this request's host."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, url: str | None) -> None:
        u = (url or "").strip().rstrip("/")
        if u and u not in seen and url_problem(u) is None:
            seen.add(u)
            out.append({"label": label, "url": u})

    add("The address people use", public)
    add("The address people use", os.environ.get("PUBLIC_API_BASE_URL"))
    add("The address this page reached", request_base)
    add(
        "From inside this Kubernetes cluster",
        os.environ.get("CODE_RUNNER_API_URL") or os.environ.get("INTERNAL_API_URL"),
    )
    return out


def url_problem(url: str) -> str | None:
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.netloc:
        return "Give the address the gateway uses to reach Abenix, such as https://abenix.example.com"
    return None


def needs(collectors: list[dict[str, Any]]) -> dict[str, Any]:
    host_net = any(
        c.get("type") == "can" and (c.get("interface") or "socketcan") == "socketcan"
        for c in collectors
    )
    devices = sorted(
        {
            str(c.get("serial_port") if c.get("type") == "modbus" else c.get("port"))
            for c in collectors
            if (
                c.get("type") == "modbus"
                and c.get("mode") == "rtu"
                and c.get("serial_port")
            )
            or (
                c.get("type") == "nmea_gps"
                and str(c.get("port") or "").startswith("/dev/")
            )
        }
    )
    folders = sorted(
        {
            os.path.dirname(str(c["path"]).split("*", 1)[0]) or "/"
            for c in collectors
            if c.get("type") == "file_tail" and c.get("path")
        }
    )
    return {"host_network": host_net, "devices": devices, "folders": folders}


def install(
    gateway_id: str, url: str, token: str, collectors: list[dict[str, Any]]
) -> dict[str, Any]:
    img = image()
    n = needs(collectors)
    q = shlex.quote
    name = f"abenix-edge-{gateway_id}"[:63]
    run = [
        "docker run -d",
        f"--name {q(name)}",
        "--restart unless-stopped",
        f"-e ABENIX_URL={q(url)}",
        f"-e ABENIX_ENROLL_TOKEN={q(token)}",
        f"-v {q(name)}-data:/var/lib/abenix-edge",
    ]
    if n["host_network"]:
        run.append("--network host")
    run += [f"--device {q(d)}" for d in n["devices"]]
    run += [f"-v {q(f)}:{q(f)}:ro" for f in n["folders"]]
    run.append(img)
    docker = " \\\n  ".join(run)

    svc = [
        "services:",
        "  abenix-edge:",
        f"    image: {img}",
        f"    container_name: {name}",
        "    restart: unless-stopped",
        "    environment:",
        f"      ABENIX_URL: {json.dumps(url)}",
        f"      ABENIX_ENROLL_TOKEN: {json.dumps(token)}",
        "    volumes:",
        "      - edge-data:/var/lib/abenix-edge",
    ]
    svc += [f"      - {f}:{f}:ro" for f in n["folders"]]
    if n["host_network"]:
        svc.append("    network_mode: host")
    if n["devices"]:
        svc.append("    devices:")
        svc += [f"      - {d}:{d}" for d in n["devices"]]
    svc += ["volumes:", "  edge-data: {}"]
    compose = "\n".join(svc) + "\n"

    k8s_name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:52]
    # the image runs as uid 1001, so the data volume must be writable by that group
    pod_extra = "      securityContext: {fsGroup: 1001}\n"
    if n["host_network"]:
        pod_extra += (
            "      hostNetwork: true\n      dnsPolicy: ClusterFirstWithHostNet\n"
        )
    vol_mounts = "            - {name: data, mountPath: /var/lib/abenix-edge}\n"
    vols = ""
    for i, f in enumerate(n["folders"]):
        vol_mounts += (
            f"            - {{name: files{i}, mountPath: {f}, readOnly: true}}\n"
        )
        vols += f"        - {{name: files{i}, hostPath: {{path: {f}}}}}\n"
    for i, d in enumerate(n["devices"]):
        vol_mounts += f"            - {{name: dev{i}, mountPath: {d}}}\n"
        vols += (
            f"        - {{name: dev{i}, hostPath: {{path: {d}, type: CharDevice}}}}\n"
        )
    sec_ctx = (
        "          securityContext: {privileged: true}  # serial devices need it without a device plugin\n"
        if n["devices"]
        else "          securityContext: {runAsNonRoot: true, allowPrivilegeEscalation: false}\n"
    )
    k8s = (
        f"""apiVersion: v1
kind: Namespace
metadata: {{name: abenix-edge}}
---
apiVersion: v1
kind: Secret
metadata: {{name: {k8s_name}, namespace: abenix-edge}}
stringData:
  ABENIX_URL: {json.dumps(url)}
  ABENIX_ENROLL_TOKEN: {json.dumps(token)}
---
apiVersion: apps/v1
kind: StatefulSet
metadata: {{name: {k8s_name}, namespace: abenix-edge, labels: {{app: abenix-edge}}}}
spec:
  serviceName: {k8s_name}
  replicas: 1
  selector: {{matchLabels: {{app: abenix-edge, gateway: {k8s_name}}}}}
  template:
    metadata: {{labels: {{app: abenix-edge, gateway: {k8s_name}}}}}
    spec:
{pod_extra}      containers:
        - name: edge
          image: {img}
          envFrom: [{{secretRef: {{name: {k8s_name}}}}}]
{sec_ctx}          ports: [{{name: status, containerPort: 8080}}]
          readinessProbe: {{httpGet: {{path: /health, port: 8080}}, periodSeconds: 10}}
          resources: {{requests: {{cpu: 50m, memory: 96Mi}}, limits: {{cpu: 500m, memory: 384Mi}}}}
          volumeMounts:
{vol_mounts}"""
        + (f"      volumes:\n{vols}" if vols else "")
        + """  volumeClaimTemplates:
    - metadata: {name: data}
      spec: {accessModes: [ReadWriteOnce], resources: {requests: {storage: 2Gi}}}
"""
    )

    docker_flags = ""
    if n["host_network"]:
        docker_flags += " --network host"
    docker_flags += "".join(f" --device {d}" for d in n["devices"])
    docker_flags += "".join(f" -v {f}:{f}:ro" for f in n["folders"])
    systemd = f"""# Linux IPC or Raspberry Pi (amd64 or arm64) with Docker installed: curl -fsSL https://get.docker.com | sh
sudo mkdir -p /etc/abenix-edge && sudo tee /etc/abenix-edge/env >/dev/null <<'EOF'
ABENIX_URL={url}
ABENIX_ENROLL_TOKEN={token}
EOF
sudo chmod 600 /etc/abenix-edge/env
sudo tee /etc/systemd/system/abenix-edge.service >/dev/null <<'EOF'
[Unit]
Description=Abenix Edge gateway
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Restart=always
RestartSec=5
ExecStartPre=-/usr/bin/docker rm -f abenix-edge
ExecStartPre=-/usr/bin/docker pull {img}
ExecStart=/usr/bin/docker run --rm --name abenix-edge --env-file /etc/abenix-edge/env -v abenix-edge-data:/var/lib/abenix-edge{docker_flags} {img}
ExecStop=/usr/bin/docker stop -t 20 abenix-edge

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now abenix-edge
"""
    can_setup = ""
    if n["host_network"]:
        chans = sorted(
            {
                str(c.get("channel") or "can0")
                for c in collectors
                if c.get("type") == "can"
            }
        )
        rates = {
            str(c.get("channel") or "can0"): c.get("bitrate") or "250000"
            for c in collectors
            if c.get("type") == "can"
        }
        can_setup = "\n".join(
            f"sudo ip link set {ch} up type can bitrate {rates[ch]}" for ch in chans
        )
    return {
        "image": img,
        "platform_url": url,
        "docker_run": docker,
        "compose": compose,
        "kubernetes": k8s,
        "systemd": systemd,
        "can_setup": can_setup,
        "needs": n,
        "arm64_note": (
            "The image is built for amd64 and arm64. On a Raspberry Pi use a 64-bit OS. To build it yourself: "
            "docker buildx build --platform linux/amd64,linux/arm64 -t <your registry>/abenix/edge-runtime:latest --push apps/edge-runtime"
        ),
    }
