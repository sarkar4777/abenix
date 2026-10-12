"""Modbus TCP and RTU: polls a register map from a meter, drive or PLC.

The register map is one register a line, the same as the Modbus TCP source in Abenix:
    name, table, address, type[, scale[, unit[, word order[, byte order]]]]
    voltage_v, holding, 0, float32, 1, V
    energy_kwh, holding, 6, uint32, 0.1, kWh
    breaker_closed, coil, 0
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass
from typing import Any

from abenix_edge.collectors.base import Collector, retry_sleep

logging.getLogger("pymodbus").setLevel(logging.WARNING)

TABLES = {
    "holding": "holding",
    "hr": "holding",
    "4x": "holding",
    "input": "input",
    "ir": "input",
    "3x": "input",
    "coil": "coil",
    "coils": "coil",
    "co": "coil",
    "0x": "coil",
    "discrete": "discrete",
    "di": "discrete",
    "1x": "discrete",
}
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
    6: "the device is busy",
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
    unit: str | None = None
    word_order: str = "big"
    byte_order: str = "big"

    @property
    def count(self) -> int:
        return 1 if self.table in ("coil", "discrete") else WIDTH[self.type]


def parse_map(text: Any) -> list[Reg]:
    if isinstance(text, list):
        rows = text
    else:
        t = str(text or "").strip()
        if not t:
            raise ValueError(
                "Add at least one register, such as: voltage_v, holding, 0, float32, 1, V"
            )
        if t.startswith("["):
            try:
                rows = json.loads(t)
            except ValueError as exc:
                raise ValueError(f"The register map is not valid JSON: {exc}") from None
        else:
            rows = []
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
            for n, line in enumerate(t.splitlines(), 1):
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 3:
                    raise ValueError(
                        f"Line {n} needs at least name, table, address: {line[:60]}"
                    )
                rows.append({k: v for k, v in zip(keys, parts) if v != ""})
    out: list[Reg] = []
    seen: set[str] = set()
    for i, r in enumerate(rows, 1):
        name = str((r or {}).get("name") or "").strip()
        if not name:
            raise ValueError(f"Register {i} has no name")
        if name in seen:
            raise ValueError(f"Two registers are called {name}")
        seen.add(name)
        table = TABLES.get(str(r.get("table") or "holding").strip().lower())
        if not table:
            raise ValueError(
                f"{name}: the table must be holding, input, coil or discrete"
            )
        try:
            address = int(str(r.get("address")), 0)
        except (TypeError, ValueError):
            raise ValueError(
                f"{name}: the address must be a number from 0 to 65535"
            ) from None
        if not 0 <= address <= 65535:
            raise ValueError(f"{name}: the address must be from 0 to 65535")
        typ = (
            "bool"
            if table in ("coil", "discrete")
            else str(r.get("type") or "uint16").strip().lower()
        )
        if typ not in WIDTH:
            raise ValueError(f"{name}: the type must be one of {', '.join(WIDTH)}")
        wo = str(r.get("word_order") or "big").strip().lower()
        bo = str(r.get("byte_order") or "big").strip().lower()
        if wo not in ("big", "little") or bo not in ("big", "little"):
            raise ValueError(f"{name}: word and byte order are big or little")
        try:
            scale = float(r.get("scale")) if r.get("scale") not in (None, "") else 1.0
        except (TypeError, ValueError):
            raise ValueError(f"{name}: the scale must be a number") from None
        unit = str(r.get("unit") or "").strip() or None
        out.append(Reg(name, table, address, typ, scale, unit, wo, bo))
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
    if reg.scale != 1.0:
        v = round(v * reg.scale, 9)
    if isinstance(v, float) and v != v:
        return None
    return v


def blocks(regs: list[Reg]) -> list[tuple[str, int, int, list[Reg]]]:
    """Contiguous reads per table, so ten registers cost one request and not ten."""
    out: list[tuple[str, int, int, list[Reg]]] = []
    for table in ("holding", "input", "coil", "discrete"):
        rs = sorted((r for r in regs if r.table == table), key=lambda r: r.address)
        limit = MAX_BITS if table in ("coil", "discrete") else MAX_REGS
        cur: list[Reg] = []
        start = end = 0
        for r in rs:
            if cur and (r.address > end + 8 or r.address + r.count - start > limit):
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


class ModbusCollector(Collector):
    type = "modbus"
    label = "Modbus TCP or RTU"

    def __init__(self, spec: dict[str, Any], sink: Any, gateway_id: str) -> None:
        super().__init__(spec, sink, gateway_id)
        self.mode = spec.get("mode") or "tcp"
        self.unit_id = int(spec.get("unit_id") or 1)
        self.regs = parse_map(spec.get("registers"))
        self.blocks = blocks(self.regs)
        self.client: Any = None

    def where(self) -> str:
        if self.mode == "rtu":
            return f"{self.spec.get('serial_port') or '/dev/ttyUSB0'} at {self.spec.get('baudrate') or 9600} baud"
        return f"{self.spec.get('host')}:{self.spec.get('port') or 502}"

    def _client(self) -> Any:
        if self.mode == "rtu":
            from pymodbus.client import AsyncModbusSerialClient

            return AsyncModbusSerialClient(
                port=self.spec.get("serial_port") or "/dev/ttyUSB0",
                baudrate=int(self.spec.get("baudrate") or 9600),
                parity=str(self.spec.get("parity") or "N")[:1].upper(),
                stopbits=int(self.spec.get("stopbits") or 1),
                bytesize=8,
                timeout=float(self.spec.get("timeout_s") or 1.0),
                retries=1,
            )
        from pymodbus.client import AsyncModbusTcpClient

        return AsyncModbusTcpClient(
            self.spec.get("host") or "localhost",
            port=int(self.spec.get("port") or 502),
            timeout=float(self.spec.get("timeout_s") or 2.0),
            retries=1,
        )

    async def _read(self, table: str, start: int, count: int) -> list[int]:
        c = self.client
        fn = {
            "holding": c.read_holding_registers,
            "input": c.read_input_registers,
            "coil": c.read_coils,
            "discrete": c.read_discrete_inputs,
        }[table]
        try:
            rr = await fn(start, count=count, device_id=self.unit_id)
        except TypeError:
            rr = await fn(start, count=count, slave=self.unit_id)
        if rr.isError():
            code = getattr(rr, "exception_code", None)
            why = EXCEPTIONS.get(code, f"exception {code}")
            raise LookupError(f"{table} {start} to {start + count - 1}: {why}")
        if table in ("coil", "discrete"):
            return [int(b) for b in rr.bits[:count]]
        return list(rr.registers)

    async def poll_once(self) -> tuple[int, list[str]]:
        rows: list[tuple[str, Any, str | None, str]] = []
        problems: list[str] = []
        for table, start, count, regs in self.blocks:
            try:
                words = await self._read(table, start, count)
            except LookupError as exc:
                problems.append(str(exc))
                for r in regs:
                    rows.append((r.name, None, r.unit, "bad"))
                continue
            for r in regs:
                i = r.address - start
                rows.append((r.name, decode(r, words[i : i + r.count]), r.unit, "good"))
        self.emit_many(rows)
        return len([r for r in rows if r[1] is not None]), problems

    async def run(self, stop: asyncio.Event) -> None:
        attempt = 0
        while not stop.is_set():
            self.client = self._client()
            try:
                ok = await self.client.connect()
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                hint = (
                    "Check the serial port, the baud rate and that this container can open it (--device in Docker)."
                    if self.mode == "rtu"
                    else "Check the address and port, and that the device allows Modbus TCP from this box."
                )
                self.fail(
                    f"Could not reach the Modbus device at {self.where()}. {hint}"
                )
                self.client.close()
                attempt += 1
                await retry_sleep(stop, attempt)
                continue
            attempt = 0
            while not stop.is_set():
                t0 = time.monotonic()
                try:
                    n, problems = await self.poll_once()
                except Exception as exc:  # noqa: BLE001
                    self.fail(
                        f"The Modbus device at {self.where()} stopped answering: {exc}. Reconnecting."
                    )
                    break
                self.extra["last_poll_ms"] = round((time.monotonic() - t0) * 1000, 1)
                if problems:
                    self.fail(
                        f"Unit {self.unit_id} at {self.where()} refused some reads: "
                        + "; ".join(problems[:3]),
                        "running",
                    )
                elif n:
                    self.ok()
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=max(0.05, self.interval - (time.monotonic() - t0)),
                    )
                except asyncio.TimeoutError:
                    pass
            self.client.close()
            if not stop.is_set():
                attempt += 1
                await retry_sleep(stop, attempt)
