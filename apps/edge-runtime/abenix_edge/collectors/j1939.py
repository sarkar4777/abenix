"""SAE J1939 on a CAN bus: identifiers, address claim, transport protocol and the common PGNs.

Pure functions and small state machines, no I/O, so the bus collector and the
tests drive them the same way.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Callable

REQUEST = 59904  # 0xEA00
ADDRESS_CLAIMED = 60928  # 0xEE00
TP_CM = 60416  # 0xEC00
TP_DT = 60160  # 0xEB00
ACKM = 59392  # 0xE800
GLOBAL = 0xFF
NULL_ADDR = 0xFE
BAM, RTS, CTS, EOMA, ABORT = 32, 16, 17, 19, 255
TP_TIMEOUT_S = 0.75

# J1939 preferred addresses, so a part reads "engine" and not "sa0"
SA_NAMES = {
    0: "engine",
    1: "engine2",
    2: "turbocharger",
    3: "transmission",
    4: "transmission2",
    5: "shift_console",
    11: "brakes",
    15: "retarder",
    16: "retarder_driveline",
    17: "cruise_control",
    19: "steering",
    21: "retarder_exhaust",
    23: "instruments",
    25: "climate",
    28: "body",
    33: "body_controller",
    36: "lighting",
    37: "cab_controller",
    39: "clutch",
    40: "chassis",
    42: "hydraulics",
    43: "hitch",
    49: "cab",
    61: "exhaust_aftertreatment",
    71: "tire_pressure",
    74: "payload",
    140: "telematics",
    234: "telematics",
    249: "service_tool",
    250: "service_tool2",
}


def parse_id(arb_id: int) -> tuple[int, int, int, int]:
    """(priority, pgn, source address, destination address) of a 29-bit identifier."""
    prio = (arb_id >> 26) & 0x7
    dp = (arb_id >> 24) & 0x3
    pf = (arb_id >> 16) & 0xFF
    ps = (arb_id >> 8) & 0xFF
    sa = arb_id & 0xFF
    if pf < 240:
        return prio, (dp << 16) | (pf << 8), sa, ps
    return prio, (dp << 16) | (pf << 8) | ps, sa, GLOBAL


def make_id(pgn: int, sa: int, da: int = GLOBAL, prio: int = 6) -> int:
    pf = (pgn >> 8) & 0xFF
    dp = (pgn >> 16) & 0x3
    ps = da if pf < 240 else pgn & 0xFF
    return (prio & 7) << 26 | dp << 24 | pf << 16 | ps << 8 | (sa & 0xFF)


def make_name(
    identity: int,
    function: int,
    manufacturer: int = 2047,
    industry_group: int = 0,
    arbitrary: bool = True,
    ecu_instance: int = 0,
) -> int:
    return (
        (1 if arbitrary else 0) << 63
        | (industry_group & 7) << 60
        | (function & 0xFF) << 40
        | (ecu_instance & 7) << 32
        | (manufacturer & 0x7FF) << 21
        | (identity & 0x1FFFFF)
    )


def name_fields(name: int) -> dict[str, int | bool]:
    return {
        "arbitrary": bool(name >> 63 & 1),
        "industry_group": name >> 60 & 7,
        "function": name >> 40 & 0xFF,
        "ecu_instance": name >> 32 & 7,
        "manufacturer": name >> 21 & 0x7FF,
        "identity": name & 0x1FFFFF,
    }


class AddressTable:
    """Who holds which address, from the address claims seen on the bus."""

    def __init__(self, names: dict[int, str] | None = None) -> None:
        self.claims: dict[int, int] = {}
        self.overrides = dict(names or {})

    def on_claim(self, sa: int, data: bytes) -> int:
        name = int.from_bytes(bytes(data[:8]).ljust(8, b"\0"), "little")
        self.claims[sa] = name
        return name

    def part(self, sa: int) -> str:
        if sa in self.overrides:
            return self.overrides[sa]
        return SA_NAMES.get(sa, f"sa{sa}")


class Claimer:
    """Our own address: claims a preferred one and moves on when a lower NAME takes it."""

    def __init__(self, name: int, preferred: int = 249) -> None:
        self.name = name
        self.address = preferred
        self.claimed = False
        self.cannot_claim = False

    def claim_frame(self) -> tuple[int, bytes]:
        sa = NULL_ADDR if self.cannot_claim else self.address
        return make_id(ADDRESS_CLAIMED, sa, GLOBAL, 6), self.name.to_bytes(8, "little")

    def on_claim(self, sa: int, other_name: int) -> tuple[int, bytes] | None:
        """Another node claimed sa. Returns the frame to send, our claim again or a new one."""
        if sa != self.address or other_name == self.name:
            return None
        if self.name < other_name:
            # ours wins, say so again
            return self.claim_frame()
        if self.name >> 63 & 1:
            for a in range(128, 248):
                if a != sa:
                    self.address = a
                    return self.claim_frame()
        self.cannot_claim = True
        return self.claim_frame()


@dataclass
class _Session:
    pgn: int
    size: int
    packets: int
    started: float
    data: bytearray = field(default_factory=bytearray)
    got: set[int] = field(default_factory=set)
    bam: bool = True


class Transport:
    """Reassembles TP.BAM and TP.CM RTS/CTS messages. Answers RTS sent to us with CTS and EndOfMsgAck."""

    def __init__(self, own_address: Callable[[], int | None] | None = None) -> None:
        self.sessions: dict[tuple[int, int], _Session] = {}
        self.own = own_address or (lambda: None)
        self.completed = 0
        self.timeouts = 0
        self.aborts = 0

    def feed(
        self, pgn: int, sa: int, da: int, data: bytes, now: float
    ) -> tuple[list[tuple[int, int, int, bytes]], list[tuple[int, bytes]]]:
        """(complete messages as (pgn, sa, da, payload), frames to send)."""
        done: list[tuple[int, int, int, bytes]] = []
        out: list[tuple[int, bytes]] = []
        self._expire(now)
        if pgn == TP_CM and len(data) >= 8:
            ctl = data[0]
            tpgn = data[5] | data[6] << 8 | data[7] << 16
            if ctl in (BAM, RTS):
                size = data[1] | data[2] << 8
                packets = data[3]
                self.sessions[(sa, da)] = _Session(
                    tpgn, size, packets, now, bam=ctl == BAM
                )
                me = self.own()
                if ctl == RTS and me is not None and da == me:
                    cts = bytes(
                        [CTS, packets, 1, 0xFF, 0xFF, data[5], data[6], data[7]]
                    )
                    out.append((make_id(TP_CM, me, sa, 7), cts))
            elif ctl == ABORT:
                if self.sessions.pop((sa, da), None) is not None:
                    self.aborts += 1
        elif pgn == TP_DT and len(data) >= 2:
            s = self.sessions.get((sa, da))
            if s is not None:
                n = data[0]
                if 1 <= n <= s.packets and n not in s.got:
                    s.got.add(n)
                    need = n * 7
                    if len(s.data) < need:
                        s.data.extend(b"\xff" * (need - len(s.data)))
                    s.data[(n - 1) * 7 : n * 7] = bytes(data[1:8]).ljust(7, b"\xff")
                    s.started = now
                if len(s.got) == s.packets:
                    del self.sessions[(sa, da)]
                    self.completed += 1
                    done.append((s.pgn, sa, da, bytes(s.data[: s.size])))
                    me = self.own()
                    if not s.bam and me is not None and da == me:
                        eoma = bytes(
                            [EOMA, s.size & 0xFF, s.size >> 8, s.packets, 0xFF]
                        ) + s.pgn.to_bytes(3, "little")
                        out.append((make_id(TP_CM, me, sa, 7), eoma))
        return done, out

    def _expire(self, now: float) -> None:
        for k, s in list(self.sessions.items()):
            if now - s.started > TP_TIMEOUT_S:
                del self.sessions[k]
                self.timeouts += 1


def request_frame(pgn: int, sa: int, da: int = GLOBAL) -> tuple[int, bytes]:
    return make_id(REQUEST, sa, da, 6), pgn.to_bytes(3, "little")


def bam_frames(pgn: int, sa: int, payload: bytes) -> list[tuple[int, bytes]]:
    """A long message to everyone with TP.BAM, for the simulator and the tests."""
    packets = (len(payload) + 6) // 7
    cm = bytes(
        [BAM, len(payload) & 0xFF, len(payload) >> 8, packets, 0xFF]
    ) + pgn.to_bytes(3, "little")
    frames = [(make_id(TP_CM, sa, GLOBAL, 7), cm)]
    for i in range(packets):
        part = payload[i * 7 : i * 7 + 7].ljust(7, b"\xff")
        frames.append((make_id(TP_DT, sa, GLOBAL, 7), bytes([i + 1]) + part))
    return frames


# decoders for the PGNs most engines, trucks and machines send


def _u8(d: bytes, i: int) -> int | None:
    v = d[i] if len(d) > i else 0xFF
    return None if v >= 0xFB else v


def _u16(d: bytes, i: int) -> int | None:
    if len(d) < i + 2:
        return None
    v = d[i] | d[i + 1] << 8
    return None if v >= 0xFB00 else v


def _u32(d: bytes, i: int) -> int | None:
    if len(d) < i + 4:
        return None
    v = struct.unpack_from("<I", d, i)[0]
    return None if v >= 0xFB000000 else v


Signal = tuple[str, Any, str | None]


def _sig(
    out: list[Signal],
    name: str,
    raw: int | None,
    scale: float,
    offset: float,
    unit: str | None,
) -> None:
    if raw is not None:
        out.append((name, round(raw * scale + offset, 6), unit))


def eec1(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Engine/Torque_pct", _u8(d, 2), 1, -125, "%")
    _sig(o, "Engine/Speed_rpm", _u16(d, 3), 0.125, 0, "rpm")
    return o


def eec2(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Engine/Pedal_pct", _u8(d, 1), 0.4, 0, "%")
    _sig(o, "Engine/Load_pct", _u8(d, 2), 1, 0, "%")
    return o


def etc2(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Transmission/SelectedGear", _u8(d, 0), 1, -125, None)
    _sig(o, "Transmission/CurrentGear", _u8(d, 3), 1, -125, None)
    return o


def et1(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Engine/CoolantTemp_C", _u8(d, 0), 1, -40, "C")
    _sig(o, "Engine/FuelTemp_C", _u8(d, 1), 1, -40, "C")
    _sig(o, "Engine/OilTemp_C", _u16(d, 2), 0.03125, -273, "C")
    return o


def eflp1(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Engine/OilPressure_kPa", _u8(d, 3), 4, 0, "kPa")
    return o


def lfe1(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Engine/FuelRate_lph", _u16(d, 0), 0.05, 0, "L/h")
    _sig(o, "Engine/FuelEconomy_kmpl", _u16(d, 2), 1 / 512, 0, "km/L")
    return o


def ccvs1(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Vehicle/Speed_kmh", _u16(d, 1), 1 / 256, 0, "km/h")
    return o


def hours(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Engine/Hours_h", _u32(d, 0), 0.05, 0, "h")
    return o


def vd(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Vehicle/Odometer_km", _u32(d, 4), 0.125, 0, "km")
    return o


def vdhr(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Vehicle/Odometer_km", _u32(d, 0), 0.005, 0, "km")
    return o


def at1t1i(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Aftertreatment/DEFLevel_pct", _u8(d, 0), 0.4, 0, "%")
    _sig(o, "Aftertreatment/DEFTemp_C", _u8(d, 1), 1, -40, "C")
    return o


def vi(d: bytes) -> list[Signal]:
    vin = bytes(d).split(b"*", 1)[0].decode("ascii", "replace").strip()
    return [("Vehicle/VIN", vin, None)] if vin else []


def vp(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "GNSS/Lat_deg", _u32(d, 0), 1e-7, -210, "deg")
    _sig(o, "GNSS/Lon_deg", _u32(d, 4), 1e-7, -210, "deg")
    return o


def vds(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "GNSS/Heading_deg", _u16(d, 0), 1 / 128, 0, "deg")
    _sig(o, "GNSS/Speed_kmh", _u16(d, 2), 1 / 256, 0, "km/h")
    _sig(o, "GNSS/Pitch_deg", _u16(d, 4), 1 / 128, -200, "deg")
    _sig(o, "GNSS/Altitude_m", _u16(d, 6), 0.125, -2500, "m")
    return o


def amb(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Ambient/AirTemp_C", _u16(d, 3), 0.03125, -273, "C")
    return o


def vep1(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Electrical/BatteryVoltage_V", _u16(d, 4), 0.05, 0, "V")
    return o


def dd(d: bytes) -> list[Signal]:
    o: list[Signal] = []
    _sig(o, "Fuel/Level_pct", _u8(d, 1), 0.4, 0, "%")
    return o


def dm1(d: bytes) -> list[Signal]:
    """Active diagnostic trouble codes: the lamps, how many are active, and the first one."""
    if len(d) < 2:
        return []
    lamps = d[0]
    dtcs = []
    for i in range(2, len(d) - 3, 4):
        b = d[i : i + 4]
        spn = b[0] | b[1] << 8 | (b[2] >> 5) << 16
        fmi = b[2] & 0x1F
        oc = b[3] & 0x7F
        if spn == 0 and fmi == 0:
            continue
        if spn == 0x7FFFF:
            continue
        dtcs.append({"spn": spn, "fmi": fmi, "count": oc})
    o: list[Signal] = [
        ("Diagnostics/ActiveCodes", len(dtcs), None),
        ("Diagnostics/MalfunctionLamp", (lamps >> 6 & 3) == 1, None),
        ("Diagnostics/RedStopLamp", (lamps >> 4 & 3) == 1, None),
        ("Diagnostics/AmberWarningLamp", (lamps >> 2 & 3) == 1, None),
        ("Diagnostics/ProtectLamp", (lamps & 3) == 1, None),
    ]
    # always sent, so the list clears when the codes do
    o.append(("Diagnostics/Codes", dtcs, None))
    return o


PGN_DECODERS: dict[int, tuple[str, Callable[[bytes], list[Signal]]]] = {
    61444: ("EEC1", eec1),
    61443: ("EEC2", eec2),
    61445: ("ETC2", etc2),
    65262: ("ET1", et1),
    65263: ("EFL/P1", eflp1),
    65266: ("LFE1", lfe1),
    65265: ("CCVS1", ccvs1),
    65253: ("HOURS", hours),
    65248: ("VD", vd),
    65217: ("VDHR", vdhr),
    65110: ("AT1T1I", at1t1i),
    65260: ("VI", vi),
    65267: ("VP", vp),
    65256: ("VDS", vds),
    65269: ("AMB", amb),
    65271: ("VEP1", vep1),
    65276: ("DD", dd),
    65226: ("DM1", dm1),
}


def decode(pgn: int, data: bytes) -> list[Signal]:
    hit = PGN_DECODERS.get(pgn)
    return hit[1](data) if hit else []


def pgn_of_frame_id(frame_id: int, extended: bool) -> int | None:
    """The PGN a DBC message describes, for J1939 DBCs whose ids carry a fixed source address."""
    if not extended:
        return None
    return parse_id(frame_id)[1]
