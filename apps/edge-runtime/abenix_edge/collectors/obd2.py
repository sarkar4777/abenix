"""OBD-II mode 01 over CAN (ISO 15765-4): requests to 0x7DF, answers from 0x7E8 to 0x7EF."""

from __future__ import annotations

from typing import Any, Callable

FUNCTIONAL_11 = 0x7DF
FUNCTIONAL_29 = 0x18DB33F1


def _ab(d: bytes) -> tuple[int, int]:
    return d[0], d[1] if len(d) > 1 else 0


PIDS: dict[int, tuple[str, str | None, Callable[[bytes], Any]]] = {
    0x04: ("Engine/Load_pct", "%", lambda d: round(d[0] * 100 / 255, 2)),
    0x05: ("Engine/CoolantTemp_C", "C", lambda d: d[0] - 40),
    0x0B: ("Engine/IntakePressure_kPa", "kPa", lambda d: d[0]),
    0x0C: ("Engine/Speed_rpm", "rpm", lambda d: (256 * d[0] + d[1]) / 4),
    0x0D: ("Vehicle/Speed_kmh", "km/h", lambda d: d[0]),
    0x0F: ("Engine/IntakeTemp_C", "C", lambda d: d[0] - 40),
    0x10: ("Engine/AirFlow_gps", "g/s", lambda d: (256 * d[0] + d[1]) / 100),
    0x11: ("Engine/Throttle_pct", "%", lambda d: round(d[0] * 100 / 255, 2)),
    0x1F: ("Engine/RunTime_s", "s", lambda d: 256 * d[0] + d[1]),
    0x2F: ("Fuel/Level_pct", "%", lambda d: round(d[0] * 100 / 255, 2)),
    0x31: ("Vehicle/DistanceSinceClear_km", "km", lambda d: 256 * d[0] + d[1]),
    0x42: ("Electrical/ModuleVoltage_V", "V", lambda d: (256 * d[0] + d[1]) / 1000),
    0x46: ("Ambient/AirTemp_C", "C", lambda d: d[0] - 40),
    0x5C: ("Engine/OilTemp_C", "C", lambda d: d[0] - 40),
    0x5E: ("Engine/FuelRate_lph", "L/h", lambda d: (256 * d[0] + d[1]) / 20),
}
PID_BYTES = {
    0x04: 1,
    0x05: 1,
    0x0B: 1,
    0x0C: 2,
    0x0D: 1,
    0x0F: 1,
    0x10: 2,
    0x11: 1,
    0x1F: 2,
    0x2F: 1,
    0x31: 2,
    0x42: 2,
    0x46: 1,
    0x5C: 1,
    0x5E: 2,
}
DEFAULT_PIDS = (0x0C, 0x0D, 0x05, 0x2F, 0x04)


def parse_pids(text: Any) -> list[int]:
    """PIDs from "0C, 0D, 05" or a list. Unknown ones raise with the list of known ones."""
    if isinstance(text, (list, tuple)):
        items = [str(x) for x in text]
    else:
        items = [
            x for x in str(text or "").replace(";", ",").replace(" ", ",").split(",")
        ]
    out = []
    for s in items:
        s = s.strip().lower().removeprefix("0x")
        if not s:
            continue
        try:
            pid = int(s, 16)
        except ValueError:
            raise ValueError(
                f"{s!r} is not a PID, write them in hex such as 0C, 0D"
            ) from None
        if pid not in PIDS:
            known = ", ".join(f"{p:02X}" for p in sorted(PIDS))
            raise ValueError(
                f"PID {pid:02X} is not one Abenix Edge reads. Known PIDs: {known}"
            )
        if pid not in out:
            out.append(pid)
    return out or list(DEFAULT_PIDS)


def request(pid: int, extended: bool = False) -> tuple[int, bytes, bool]:
    arb = FUNCTIONAL_29 if extended else FUNCTIONAL_11
    return arb, bytes([0x02, 0x01, pid, 0x55, 0x55, 0x55, 0x55, 0x55]), extended


def is_response(arb_id: int, extended: bool) -> bool:
    if extended:
        return (arb_id & 0x1FFFFF00) == 0x18DAF100
    return 0x7E8 <= arb_id <= 0x7EF


def ecu_of(arb_id: int, extended: bool) -> str:
    n = (arb_id & 0xFF) if extended else arb_id - 0x7E8
    return "engine" if n in (0, 0x10) else f"ecu{n:X}"


def decode(data: bytes) -> tuple[int, str, Any, str | None] | None:
    """(pid, signal name, value, unit) from one single-frame mode 01 answer."""
    if len(data) < 3 or data[1] != 0x41:
        return None
    pid = data[2]
    hit = PIDS.get(pid)
    if hit is None:
        return None
    n = PID_BYTES.get(pid, 1)
    payload = bytes(data[3 : 3 + n])
    if len(payload) < n:
        return None
    name, unit, fn = hit
    return pid, name, fn(payload), unit


def answer(pid: int, value_bytes: bytes) -> bytes:
    """A mode 01 answer, for the simulator."""
    body = bytes([0x41, pid]) + value_bytes
    return bytes([len(body)]) + body.ljust(7, b"\x55")
