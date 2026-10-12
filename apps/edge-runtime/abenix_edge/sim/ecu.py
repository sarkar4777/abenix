"""Simulated ECUs on a socketcand bus, driven by one haul truck doing laps of a site route.

The engine claims address 0, the transmission 3. They send at J1939 repetition
rates, answer requests for address claim, engine hours and the VIN (over TP.BAM),
and send DM1 every second, with a low DEF warning now and then that clears once
the tank is topped up. The engine also answers OBD-II mode 01 on 0x7E8. A GPS on
TCP port 10110 sends NMEA RMC and GGA once a second along the same route.

    python -m abenix_edge.sim.ecu          CAN_HOST=localhost CAN_PORT=29536 CAN_CHANNEL=vcan0 SIM_SEED=7
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import struct
import threading
import time

import can

from abenix_edge.collectors import j1939 as J
from abenix_edge.collectors import obd2
from abenix_edge.sim.truck import Truck

LOG = logging.getLogger("ecu-sim")
VIN = os.environ.get("SIM_VIN", "YS2R4X20005399401")


def open_bus() -> can.BusABC:
    host = os.environ.get("CAN_HOST", "localhost")
    port = int(os.environ.get("CAN_PORT", "29536"))
    ch = os.environ.get("CAN_CHANNEL", "vcan0")
    for _ in range(120):
        try:
            return can.Bus(interface="socketcand", host=host, port=port, channel=ch)
        except (OSError, TimeoutError, can.CanError):
            time.sleep(0.5)
    raise RuntimeError(f"no socketcand bus at {host}:{port}")


# kept for callers that made a Plant, it is the truck now
Plant = Truck


class Ecu:
    def __init__(self, label: str, sa: int, function: int, plant: Truck) -> None:
        self.label = label
        self.sa = sa
        self.name = J.make_name(identity=4000 + sa, function=function, industry_group=0)
        self.plant = plant
        self.bus = open_bus()
        self.lock = threading.Lock()

    def send(self, arb: int, data: bytes, ext: bool = True) -> None:
        with self.lock:
            self.bus.send(
                can.Message(arbitration_id=arb, data=data, is_extended_id=ext)
            )

    def tx(self, pgn: int, data: bytes, prio: int = 6) -> None:
        self.send(J.make_id(pgn, self.sa, J.GLOBAL, prio), data)

    def bam(self, pgn: int, payload: bytes) -> None:
        for arb, data in J.bam_frames(pgn, self.sa, payload):
            self.send(arb, data)
            # J1939-21 asks for 50 to 200 ms between BAM packets
            time.sleep(0.05)

    def claim(self) -> None:
        self.send(
            J.make_id(J.ADDRESS_CLAIMED, self.sa), self.name.to_bytes(8, "little")
        )


def u8(v: float) -> int:
    return max(0, min(0xFA, int(round(v))))


def u16(v: float) -> bytes:
    return struct.pack("<H", max(0, min(0xFAFF, int(round(v)))))


def u32(v: float) -> bytes:
    return struct.pack("<I", max(0, min(0xFAFFFFFF, int(round(v)))))


def dm1(dtcs: list[tuple[int, int, int]]) -> bytes:
    """DM1: lamps, then four bytes per code. Amber with any active code, no codes is all zero."""
    lamps = 0x04 if dtcs else 0x00
    out = bytes([lamps, 0xFF])
    if not dtcs:
        return out + bytes([0, 0, 0, 0, 0xFF, 0xFF])
    for spn, fmi, oc in dtcs:
        out += bytes(
            [
                spn & 0xFF,
                (spn >> 8) & 0xFF,
                ((spn >> 16) & 0x7) << 5 | (fmi & 0x1F),
                oc & 0x7F,
            ]
        )
    return out


def engine(stop: threading.Event, plant: Truck) -> None:
    e = Ecu("engine", 0, 0, plant)
    e.claim()
    time.sleep(0.3)
    threading.Thread(target=responder, args=(e, stop), daemon=True).start()
    n = 0
    while not stop.is_set():
        n += 1
        s = plant.now()
        tq = 125 + s.torque_pct
        # EEC1 every 50 ms, the real rate is 10 to 20 ms
        e.tx(
            61444,
            bytes([0xF3, u8(tq), u8(tq), *u16(s.rpm / 0.125), 0x00, 0xFF, 0xFF]),
            3,
        )
        if n % 2 == 0:
            e.tx(
                61443,
                bytes(
                    [
                        0xFF,
                        u8(s.pedal_pct / 0.4),
                        u8(s.load_pct),
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                    ]
                ),
                3,
            )
            econ = min(60.0, s.speed * 3.6 / max(0.5, s.fuel_lph))
            e.tx(65266, u16(s.fuel_lph / 0.05) + u16(econ * 512) + b"\xff\xff\xff\xff")
            brake = 0x10 if s.braking else 0x00
            e.tx(
                65265,
                b"\xff"
                + u16(s.speed * 3.6 * 256)
                + bytes([brake, 0xFF, 0xFF, 0xFF, 0xFF]),
            )
        if n % 20 == 0:
            e.tx(
                65262,
                bytes([u8(s.coolant_c + 40), u8(s.coolant_c - 4 + 40)])
                + u16((s.oil_c + 273) / 0.03125)
                + b"\xff\xff\xff\xff",
            )
            e.tx(
                65263,
                bytes(
                    [
                        0xFF,
                        0xFF,
                        0xFF,
                        u8((180 + 0.17 * (s.rpm - 600)) / 4),
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                    ]
                ),
            )
            e.tx(65267, u32((s.lat + 210) / 1e-7) + u32((s.lon + 210) / 1e-7))
            grade = math.degrees(math.atan(s.grade_pct / 100))
            e.tx(
                65256,
                u16(s.heading * 128)
                + u16(s.speed * 3.6 * 256)
                + u16((grade + 200) * 128)
                + u16((s.altitude_m + 2500) / 0.125),
            )
            volts = 27.9 + (0.25 if s.rpm > 700 else -0.6) + 0.05 * math.sin(s.t / 7)
            e.tx(65271, b"\xff\xff\xff\xff" + u16(volts / 0.05) + b"\xff\xff")
            e.tx(
                65276,
                bytes(
                    [
                        0xFF,
                        u8(s.fuel_level_pct / 0.4),
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                    ]
                ),
            )
            e.tx(
                65110,
                bytes(
                    [
                        u8(s.def_level_pct / 0.4),
                        u8(24 + 40),
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                        0xFF,
                    ]
                ),
            )
            e.tx(65217, u32(s.odometer_km / 0.005) + u32(0))
            payload = dm1(s.dtcs)
            if len(payload) > 8:
                threading.Thread(
                    target=e.bam, args=(65226, payload), daemon=True
                ).start()
            else:
                e.tx(65226, payload)
        if n % 200 == 0:
            e.tx(65248, u32(0) + u32(s.odometer_km / 0.125))
        time.sleep(0.05)


def responder(e: Ecu, stop: threading.Event) -> None:
    rx = open_bus()
    while not stop.is_set():
        msg = rx.recv(0.5)
        if msg is None:
            continue
        if (
            not msg.is_extended_id
            and msg.arbitration_id == obd2.FUNCTIONAL_11
            and len(msg.data) >= 3
            and msg.data[1] == 0x01
        ):
            pid = msg.data[2]
            s = e.plant.now()
            vals = {
                0x0C: struct.pack(">H", int(s.rpm * 4)),
                0x0D: bytes([min(255, int(s.speed * 3.6))]),
                0x05: bytes([u8(s.coolant_c + 40)]),
                0x2F: bytes([min(255, int(s.fuel_level_pct * 255 / 100))]),
                0x04: bytes([min(255, int(s.load_pct * 255 / 100))]),
            }
            if pid in vals:
                e.send(0x7E8, obd2.answer(pid, vals[pid]), False)
            continue
        if not msg.is_extended_id:
            continue
        _, pgn, sa, da = J.parse_id(msg.arbitration_id)
        if pgn == J.REQUEST and da in (J.GLOBAL, e.sa) and len(msg.data) >= 3:
            want = msg.data[0] | msg.data[1] << 8 | msg.data[2] << 16
            if want == J.ADDRESS_CLAIMED:
                e.claim()
            elif want == 65253:
                e.tx(65253, u32(e.plant.now().hours / 0.05) + b"\xff\xff\xff\xff")
            elif want == 65260:
                threading.Thread(
                    target=e.bam, args=(65260, (VIN + "*").encode()), daemon=True
                ).start()


def transmission(stop: threading.Event, plant: Truck) -> None:
    t = Ecu("transmission", 3, 3, plant)
    t.claim()
    while not stop.is_set():
        s = plant.now()
        t.tx(
            61445,
            bytes(
                [
                    s.selected_gear + 125,
                    0xFF,
                    0xFF,
                    s.gear + 125,
                    0xFF,
                    0xFF,
                    0xFF,
                    0xFF,
                ]
            ),
        )
        time.sleep(0.1)


def nmea_line(body: str) -> str:
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return f"${body}*{cs:02X}\r\n"


async def gps(plant: Truck, port: int) -> None:
    async def client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                s = plant.now()
                lat, lon = s.lat, s.lon
                t = time.gmtime()
                hhmmss = time.strftime("%H%M%S", t)
                la = f"{int(abs(lat)):02d}{(abs(lat) % 1) * 60:07.4f}"
                lo = f"{int(abs(lon)):03d}{(abs(lon) % 1) * 60:07.4f}"
                ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
                kn = s.speed * 3.6 / 1.852
                day = time.strftime("%d%m%y", t)
                writer.write(
                    nmea_line(
                        f"GPRMC,{hhmmss}.00,A,{la},{ns},{lo},{ew},{kn:.1f},{s.heading:.1f},{day},,"
                    ).encode()
                )
                writer.write(
                    nmea_line(
                        f"GPGGA,{hhmmss}.00,{la},{ns},{lo},{ew},1,11,0.8,{s.altitude_m:.1f},M,47.0,M,,"
                    ).encode()
                )
                await writer.drain()
                await asyncio.sleep(1)
        except (ConnectionError, OSError):
            pass

    server = await asyncio.start_server(client, "0.0.0.0", port)
    async with server:
        await server.serve_forever()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    truck = Truck()
    stop = threading.Event()
    for fn in (engine, transmission):
        threading.Thread(target=fn, args=(stop, truck), daemon=True).start()
    LOG.info(
        "ecu sim on the bus: engine sa 0, transmission sa 3, OBD-II on 0x7E8, GPS on tcp 10110"
    )
    asyncio.run(gps(truck, int(os.environ.get("GPS_PORT", "10110"))))


if __name__ == "__main__":
    main()
