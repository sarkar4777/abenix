"""Modbus TCP: polls a register map from a meter, drive or PLC and writes registers and coils back."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass
from typing import Any

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException

from app.telemetry.connectors import _plain as P
from app.telemetry.connectors.base import (
    ConfigField,
    ConnectorError,
    Envelope,
    RunContext,
    SourceConnector,
)

logger = logging.getLogger(__name__)
# pymodbus logs every frame at debug, which floods the ingest log
logging.getLogger("pymodbus").setLevel(logging.WARNING)

CONTENT_TYPE = "application/vnd.abenix.values+json"
TABLES = {"holding": "hr", "input": "ir", "coil": "co", "discrete": "di"}
TABLE_ALIASES = {
    "holding": "holding",
    "hr": "holding",
    "h": "holding",
    "4x": "holding",
    "input": "input",
    "ir": "input",
    "i": "input",
    "3x": "input",
    "coil": "coil",
    "coils": "coil",
    "co": "coil",
    "c": "coil",
    "0x": "coil",
    "discrete": "discrete",
    "di": "discrete",
    "d": "discrete",
    "1x": "discrete",
}
# registers per type
WIDTH = {
    "int16": 1,
    "uint16": 1,
    "int32": 2,
    "uint32": 2,
    "float32": 2,
    "int64": 4,
    "uint64": 4,
    "float64": 4,
    "bool": 1,
}
FMT = {
    "int16": "h",
    "uint16": "H",
    "int32": "i",
    "uint32": "I",
    "float32": "f",
    "int64": "q",
    "uint64": "Q",
    "float64": "d",
}
EXCEPTIONS = {
    1: "the device does not support that function",
    2: "that address is not on the device",
    3: "the device would not take that value",
    4: "the device failed while answering",
    6: "the device is busy, try again",
    10: "the gateway has no path to that unit id",
    11: "the device behind the gateway did not answer, check the unit id",
}
MAX_REGS, MAX_BITS = 120, 1968


@dataclass(frozen=True)
class Reg:
    name: str
    table: str
    address: int
    type: str = "uint16"
    scale: float = 1.0
    offset: float = 0.0
    unit: str | None = None
    word_order: str = "big"
    byte_order: str = "big"
    writable: bool = False

    @property
    def count(self) -> int:
        return 1 if self.table in ("coil", "discrete") else WIDTH[self.type]


def parse_map(text: Any) -> list[Reg]:
    """The register map: a JSON list, or one register per line as
    name, table, address, type[, scale[, unit[, word order[, byte order]]]]"""
    if isinstance(text, list):
        rows = text
    else:
        t = str(text or "").strip()
        if not t:
            raise ConnectorError("Add at least one register to the register map")
        if t.startswith("["):
            try:
                rows = json.loads(t)
            except ValueError as exc:
                raise ConnectorError(
                    f"The register map is not valid JSON: {exc}"
                ) from None
        else:
            rows = []
            for n, line in enumerate(t.splitlines(), 1):
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 3:
                    raise ConnectorError(
                        f"Line {n} needs at least name, table, address: {line[:60]}"
                    )
                keys = [
                    "name",
                    "table",
                    "address",
                    "type",
                    "scale",
                    "unit",
                    "word_order",
                    "byte_order",
                ]
                rows.append({k: v for k, v in zip(keys, parts) if v != ""})
    out: list[Reg] = []
    names: set[str] = set()
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict) or not r.get("name"):
            raise ConnectorError(f"Register {i} has no name")
        name = str(r["name"]).strip()
        if name in names:
            raise ConnectorError(f"Two registers are called {name}")
        names.add(name)
        table = TABLE_ALIASES.get(str(r.get("table") or "holding").strip().lower())
        if not table:
            raise ConnectorError(
                f"{name}: the table must be holding, input, coil or discrete"
            )
        try:
            address = int(str(r.get("address")), 0)
        except (TypeError, ValueError):
            raise ConnectorError(
                f"{name}: the address must be a number from 0 to 65535"
            ) from None
        if not 0 <= address <= 65535:
            raise ConnectorError(f"{name}: the address must be from 0 to 65535")
        typ = (
            "bool"
            if table in ("coil", "discrete")
            else str(r.get("type") or "uint16").strip().lower()
        )
        if typ not in WIDTH:
            raise ConnectorError(
                f"{name}: the type must be one of int16, uint16, int32, uint32, float32, int64, uint64, float64, bool"
            )
        wo = str(r.get("word_order") or "big").strip().lower()
        bo = str(r.get("byte_order") or "big").strip().lower()
        if wo not in ("big", "little") or bo not in ("big", "little"):
            raise ConnectorError(f"{name}: word and byte order are big or little")
        try:
            scale = float(r.get("scale") if r.get("scale") not in (None, "") else 1.0)
            offset = float(r.get("offset") or 0.0)
        except (TypeError, ValueError):
            raise ConnectorError(f"{name}: scale and offset must be numbers") from None
        out.append(
            Reg(
                name,
                table,
                address,
                typ,
                scale,
                offset,
                (str(r["unit"]).strip() or None) if r.get("unit") else None,
                wo,
                bo,
                bool(r.get("writable")) or table in ("holding", "coil"),
            )
        )
    return out


def decode(reg: Reg, words: list[int]) -> Any:
    if reg.type == "bool":
        return bool(words[0])
    ws = list(words[: reg.count])
    if reg.word_order == "little":
        ws.reverse()
    raw = b"".join(struct.pack(">H", w & 0xFFFF) for w in ws)
    if reg.byte_order == "little":
        raw = b"".join(raw[i : i + 2][::-1] for i in range(0, len(raw), 2))
    v = struct.unpack(">" + FMT[reg.type], raw)[0]
    if reg.type.startswith("float") and v != v:
        return None
    if reg.scale != 1.0 or reg.offset:
        return round(v * reg.scale + reg.offset, 9)
    return v


def encode(reg: Reg, value: Any) -> list[int]:
    if reg.type == "bool":
        return [1 if value else 0]
    try:
        v = (float(value) - reg.offset) / (reg.scale or 1.0)
    except (TypeError, ValueError):
        raise ConnectorError(f"{reg.name} takes a number, not {value!r}") from None
    if not reg.type.startswith("float"):
        v = int(round(v))
    try:
        raw = struct.pack(">" + FMT[reg.type], v)
    except struct.error:
        raise ConnectorError(
            f"{value!r} is out of range for {reg.name}, which is {reg.type}"
        ) from None
    if reg.byte_order == "little":
        raw = b"".join(raw[i : i + 2][::-1] for i in range(0, len(raw), 2))
    ws = [struct.unpack(">H", raw[i : i + 2])[0] for i in range(0, len(raw), 2)]
    if reg.word_order == "little":
        ws.reverse()
    return ws


def blocks(regs: list[Reg]) -> list[tuple[str, int, int, list[Reg]]]:
    """Neighbouring registers read in one request: (table, start, count, registers)."""
    out: list[tuple[str, int, int, list[Reg]]] = []
    for table in ("holding", "input", "coil", "discrete"):
        rs = sorted((r for r in regs if r.table == table), key=lambda r: r.address)
        cap = MAX_BITS if table in ("coil", "discrete") else MAX_REGS
        cur: list[Reg] = []
        start = end = 0
        for r in rs:
            if cur and (r.address > end + 8 or r.address + r.count - start > cap):
                out.append((table, start, end - start, cur))
                cur = []
            if not cur:
                start = r.address
                end = r.address
            cur.append(r)
            end = max(end, r.address + r.count)
        if cur:
            out.append((table, start, end - start, cur))
    return out


def where_of(cfg: dict[str, Any]) -> str:
    return f"{(cfg.get('host') or '').strip() or 'the device'}:{P.as_int(cfg, 'port', 502)}"


def asset_of(cfg: dict[str, Any]) -> str:
    if (cfg.get("asset") or "").strip():
        return cfg["asset"].strip()
    host = (cfg.get("host") or "device").strip()
    # an IP keeps all of itself, a host name keeps its first label
    host = (
        host.replace(".", "-")
        if host.replace(".", "").isdigit()
        else host.split(".")[0]
    )
    return f"modbus/{host}-unit{P.as_int(cfg, 'unit_id', 1)}"


def make_client(
    cfg: dict[str, Any], *, timeout: float | None = None
) -> AsyncModbusTcpClient:
    host = (cfg.get("host") or "").strip()
    if not host:
        raise ConnectorError("Enter the device's host name or IP address")
    t = timeout if timeout is not None else P.as_int(cfg, "timeout_ms", 3000) / 1000
    return AsyncModbusTcpClient(
        host,
        port=P.as_int(cfg, "port", 502),
        timeout=t,
        retries=1,
        reconnect_delay=0,
        name="abenix",
    )


def words(exc: BaseException, cfg: dict[str, Any]) -> str:
    where = where_of(cfg)
    for e in P.walk(exc):
        if isinstance(e, ConnectorError):
            return str(e)
    net = P.network_words(exc, where, "Modbus device")
    if net:
        return net
    if isinstance(exc, (ConnectionException, ModbusIOException)):
        return f"No answer from the Modbus device at {where}. Check the address, the port (usually 502) and the unit id."
    return f"Modbus at {where} failed: {type(exc).__name__}: {exc}"[:500]


async def connect(client: AsyncModbusTcpClient, cfg: dict[str, Any]) -> None:
    ok = await client.connect()
    if not ok:
        host, port = (cfg.get("host") or "").strip(), P.as_int(cfg, "port", 502)
        raise ConnectorError(
            await P.probe_tcp(host, port, "Modbus device")
            or f"Could not connect to the Modbus device at {where_of(cfg)}"
        )


async def read_block(
    client: AsyncModbusTcpClient, table: str, start: int, count: int, unit: int
) -> list[int]:
    fn = {
        "holding": client.read_holding_registers,
        "input": client.read_input_registers,
        "coil": client.read_coils,
        "discrete": client.read_discrete_inputs,
    }[table]
    rr = await fn(start, count=count, device_id=unit)
    if rr.isError():
        code = getattr(rr, "exception_code", None)
        why = EXCEPTIONS.get(code, f"exception {code}")
        raise ConnectorError(
            f"Reading {table} {start}-{start + count - 1} on unit {unit}: {why}"
        )
    return (
        list(rr.bits[:count]) if table in ("coil", "discrete") else list(rr.registers)
    )


async def poll(
    client: AsyncModbusTcpClient, regs: list[Reg], unit: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """One pass over the map. A block that fails gives its registers bad quality, the rest still land."""
    values: list[dict[str, Any]] = []
    problems: list[str] = []
    for table, start, count, rs in blocks(regs):
        ts = P.now_ms()
        try:
            data = await read_block(client, table, start, count, unit)
        except ConnectorError as exc:
            problems.append(str(exc))
            values.extend(
                {
                    "name": r.name,
                    "value": None,
                    "quality": "bad",
                    "status": "read failed",
                    "ts": ts,
                    "unit": r.unit,
                }
                for r in rs
            )
            continue
        for r in rs:
            i = r.address - start
            val = decode(r, data[i : i + r.count])
            values.append(
                {
                    "name": r.name,
                    "value": val,
                    "quality": "good" if val is not None else "bad",
                    "status": "Good" if val is not None else "NaN",
                    "ts": ts,
                    "unit": r.unit,
                    "type": "bool" if r.type == "bool" else "number",
                    "node_id": f"{table}:{r.address}",
                }
            )
    return values, problems


class ModbusTcpConnector(SourceConnector):
    transport = "modbus_tcp"
    label = "Modbus TCP"
    description = (
        "Polls a meter, drive or PLC over Modbus TCP with a register map: holding and input registers, "
        "coils and discrete inputs, with type, scale, unit and byte and word order. Writes registers and coils back."
    )
    config_fields = (
        ConfigField(
            "host",
            "Device host",
            kind="string",
            required=True,
            group="Connection",
            description="Host name or IP address of the device or gateway. Example: meter.abenix-testbed.svc.cluster.local",
        ),
        ConfigField(
            "port",
            "Port",
            kind="int",
            group="Connection",
            default="502",
            description="Usually 502.",
        ),
        ConfigField(
            "unit_id",
            "Unit id",
            kind="int",
            group="Connection",
            default="1",
            description="The slave or unit id, 1 to 247. Behind a gateway it picks the device. Example: 1",
        ),
        ConfigField(
            "registers",
            "Register map",
            kind="string",
            required=True,
            group="Reading",
            description="One register per line: name, table, address, type, scale, unit, word order, byte order. Tables: holding, input, coil, discrete. Types: int16, uint16, int32, uint32, float32, bool. Example: Voltage_V, holding, 0, float32, 1, V, big",
        ),
        ConfigField(
            "poll_interval_ms",
            "Poll every (ms)",
            kind="int",
            group="Reading",
            default="1000",
            description="How often the whole map is read.",
        ),
        ConfigField(
            "timeout_ms",
            "Answer timeout (ms)",
            kind="int",
            group="Reading",
            default="3000",
            description="How long to wait for each answer.",
        ),
        ConfigField(
            "asset",
            "Asset path",
            kind="string",
            group="Reading",
            description="The subject the values arrive on, which becomes group/asset/part. Example: energy/meter-1. Empty means modbus/<host>-unit<id>.",
        ),
    )
    capabilities = {"receive": "poll", "write": True}
    scale_mode = "lease"
    default_decoder = "values"

    async def run(self, ctx: RunContext) -> None:
        cfg = ctx.config
        sup = P.Supervisor(ctx, lambda e: words(e, cfg), "modbus")
        subject = asset_of(cfg)

        async def once() -> None:
            regs = parse_map(cfg.get("registers"))
            unit = P.as_int(cfg, "unit_id", 1)
            period = max(0.05, P.as_int(cfg, "poll_interval_ms", 1000) / 1000)
            client = make_client(cfg)
            try:
                await connect(client, cfg)
                sup.connected()
                failed = 0
                while not ctx.stopping.is_set():
                    started = time.monotonic()
                    if not client.connected:
                        raise ConnectorError(
                            f"Lost the connection to the Modbus device at {where_of(cfg)}"
                        )
                    try:
                        values, problems = await poll(client, regs, unit)
                    except (
                        ConnectionException,
                        ModbusIOException,
                        asyncio.TimeoutError,
                        OSError,
                    ) as exc:
                        failed += 1
                        if failed >= 3:
                            raise
                        ctx.set_status("connected", words(exc, cfg))
                        values, problems = [], []
                    else:
                        failed = 0
                        ctx.set_status("connected", problems[0] if problems else None)
                    if values:
                        await ctx.emit(
                            Envelope(
                                connection_id=ctx.connection_id,
                                tenant=ctx.tenant,
                                subject=subject,
                                payload=json.dumps(
                                    {"ts": P.now_ms(), "values": values}
                                ).encode(),
                                headers={
                                    "content-type": CONTENT_TYPE,
                                    "modbus.unit_id": str(unit),
                                },
                                t_recv=time.time(),
                            )
                        )
                    if await P.sleep_or_stop(
                        ctx, period - (time.monotonic() - started)
                    ):
                        break
            finally:
                client.close()

        await sup.run(once)

    async def test(
        self, cfg: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        out = P.result()
        client = None
        try:
            regs = (
                parse_map(cfg.get("registers")) if (cfg.get("registers") or "") else []
            )
            client = make_client(cfg, timeout=2)
            await asyncio.wait_for(connect(client, cfg), 4)
            out["connected"] = True
            if regs:
                values, problems = await asyncio.wait_for(
                    poll(client, regs, P.as_int(cfg, "unit_id", 1)), 4
                )
                out["messages"] = 1
                out["subjects_seen"] = [asset_of(cfg)]
                out["sample"] = json.dumps({"values": values})[: P.SAMPLE_MAX]
                if problems:
                    out["error"] = problems[0]
                    return out
            out["ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["error"] = words(exc, cfg)
        finally:
            if client is not None:
                client.close()
        return out

    async def write(
        self,
        cfg: dict[str, Any],
        secrets: dict[str, Any],
        target: dict[str, Any],
        value: Any,
    ) -> dict[str, Any]:
        reg = target_reg(cfg, target)
        unit = int(target.get("unit_id") or P.as_int(cfg, "unit_id", 1))
        client = make_client(cfg)
        try:
            await connect(client, cfg)
            if reg.table == "coil":
                rr = await client.write_coil(
                    reg.address, bool(as_bool_value(value)), device_id=unit
                )
            else:
                ws = encode(reg, value)
                if len(ws) == 1 and not target.get("multiple"):
                    rr = await client.write_register(reg.address, ws[0], device_id=unit)
                else:
                    rr = await client.write_registers(reg.address, ws, device_id=unit)
            if rr.isError():
                code = getattr(rr, "exception_code", None)
                raise ConnectorError(
                    f"The device refused the write to {reg.name}: {EXCEPTIONS.get(code, f'exception {code}')}"
                )
        except ConnectorError:
            raise
        except (ModbusException, OSError, asyncio.TimeoutError) as exc:
            raise ConnectorError(words(exc, cfg)) from None
        finally:
            client.close()
        return {
            "published": True,
            "at": P.iso_now(),
            "register": reg.name,
            "table": reg.table,
            "address": reg.address,
        }


def as_bool_value(value: Any) -> bool:
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "on", "yes", "closed"):
            return True
        if low in ("false", "0", "off", "no", "open"):
            return False
        raise ConnectorError(f"A coil takes true or false, not {value!r}")
    return bool(value)


def target_reg(cfg: dict[str, Any], target: dict[str, Any]) -> Reg:
    """The register a command writes: a name from the map, or a table and address given outright."""
    regs = (
        {r.name: r for r in parse_map(cfg.get("registers"))}
        if (cfg.get("registers") or "")
        else {}
    )
    ref = (
        target.get("register")
        if target.get("register") not in (None, "")
        else target.get("coil")
    )
    if ref in (None, ""):
        raise ConnectorError(
            "The command has no register or coil to write. Set one on the writable signal."
        )
    if str(ref) in regs:
        reg = regs[str(ref)]
    else:
        table = (
            "coil"
            if target.get("coil") not in (None, "")
            else (target.get("table") or "holding")
        )
        reg = parse_map(
            [
                {
                    "name": str(ref),
                    "table": table,
                    "address": ref,
                    "type": target.get("type") or "uint16",
                    "scale": target.get("scale") or 1,
                    "word_order": target.get("word_order") or "big",
                    "byte_order": target.get("byte_order") or "big",
                }
            ]
        )[0]
    if reg.table not in ("holding", "coil"):
        raise ConnectorError(
            f"{reg.name} is an {reg.table} {'input' if reg.table == 'discrete' else 'register'}, which is read only"
        )
    return reg
