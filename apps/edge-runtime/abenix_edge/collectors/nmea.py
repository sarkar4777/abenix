"""A GPS receiver speaking NMEA 0183, on a serial port or over TCP (gpsd's raw port, a cellular router)."""

from __future__ import annotations

import asyncio
import threading
from functools import reduce
from typing import Any

from abenix_edge.collectors.base import Collector, retry_sleep

KNOTS_TO_KMH = 1.852


def checksum_ok(line: str) -> bool:
    if "*" not in line:
        return True
    body, _, cs = line.lstrip("$!").partition("*")
    try:
        return reduce(lambda a, c: a ^ ord(c), body, 0) == int(cs[:2], 16)
    except ValueError:
        return False


def _deg(v: str, hemi: str) -> float | None:
    if not v:
        return None
    try:
        dot = v.index(".")
        deg = float(v[: dot - 2])
        minutes = float(v[dot - 2 :])
    except ValueError:
        return None
    out = deg + minutes / 60
    return round(-out if hemi in ("S", "W") else out, 7)


def _f(v: str) -> float | None:
    try:
        return float(v) if v else None
    except ValueError:
        return None


def parse(line: str) -> list[tuple[str, Any, str | None]]:
    """Signals from one sentence: RMC, GGA and VTG from any talker (GP, GN, GL, GA)."""
    line = line.strip()
    if not line.startswith("$") or not checksum_ok(line):
        return []
    fields = line.split("*", 1)[0].split(",")
    kind = fields[0][3:] if len(fields[0]) >= 6 else ""
    out: list[tuple[str, Any, str | None]] = []
    if kind == "RMC" and len(fields) >= 9:
        valid = fields[2] == "A"
        out.append(("GNSS/Valid", valid, None))
        if valid:
            out += [
                ("GNSS/Lat_deg", _deg(fields[3], fields[4]), "deg"),
                ("GNSS/Lon_deg", _deg(fields[5], fields[6]), "deg"),
            ]
            sp = _f(fields[7])
            out.append(
                (
                    "GNSS/Speed_kmh",
                    round(sp * KNOTS_TO_KMH, 2) if sp is not None else None,
                    "km/h",
                )
            )
            out.append(("GNSS/Course_deg", _f(fields[8]), "deg"))
    elif kind == "GGA" and len(fields) >= 10:
        fix = int(fields[6]) if fields[6].isdigit() else 0
        out.append(("GNSS/Fix", fix, None))
        out.append(
            ("GNSS/Satellites", int(fields[7]) if fields[7].isdigit() else None, None)
        )
        out.append(("GNSS/HDOP", _f(fields[8]), None))
        if fix:
            out += [
                ("GNSS/Lat_deg", _deg(fields[2], fields[3]), "deg"),
                ("GNSS/Lon_deg", _deg(fields[4], fields[5]), "deg"),
                ("GNSS/Altitude_m", _f(fields[9]), "m"),
            ]
    elif kind == "VTG" and len(fields) >= 8:
        out.append(("GNSS/Speed_kmh", _f(fields[7]), "km/h"))
    return [x for x in out if x[1] is not None]


class NmeaCollector(Collector):
    type = "nmea_gps"
    label = "GPS (NMEA 0183)"

    def where(self) -> str:
        return str(self.spec.get("port") or "/dev/ttyUSB0")

    def _serial_loop(self, stop: threading.Event) -> None:
        import serial

        with serial.Serial(
            self.where(), int(self.spec.get("baudrate") or 9600), timeout=1
        ) as s:
            self.ok()
            while not stop.is_set():
                raw = s.readline()
                if raw:
                    self.line(raw.decode("ascii", "replace"))

    def line(self, text: str) -> None:
        sigs = parse(text)
        if not sigs:
            return
        self.extra["sentences"] = self.extra.get("sentences", 0) + 1
        for name, v, unit in sigs:
            self.update(self.device, name, v, unit)

    async def _tcp(self, stop: asyncio.Event) -> None:
        host, _, port = self.where()[len("tcp://") :].partition(":")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port or 10110)), 10
        )
        self.ok()
        try:
            while not stop.is_set():
                raw = await asyncio.wait_for(reader.readline(), timeout=30)
                if not raw:
                    raise ConnectionError("the GPS closed the connection")
                self.line(raw.decode("ascii", "replace"))
        finally:
            writer.close()

    async def run(self, stop: asyncio.Event) -> None:
        pub = asyncio.create_task(self.publisher(stop))
        attempt = 0
        try:
            while not stop.is_set():
                try:
                    if self.where().startswith("tcp://"):
                        await self._tcp(stop)
                    else:
                        tstop = threading.Event()
                        task = asyncio.create_task(
                            asyncio.to_thread(self._serial_loop, tstop)
                        )
                        waiter = asyncio.create_task(stop.wait())
                        await asyncio.wait(
                            [task, waiter], return_when=asyncio.FIRST_COMPLETED
                        )
                        tstop.set()
                        waiter.cancel()
                        await task
                except asyncio.TimeoutError:
                    self.fail(
                        f"No NMEA sentences from {self.where()} for 30 s. Check the baud rate and that the receiver is on."
                    )
                except Exception as exc:  # noqa: BLE001
                    self.fail(
                        f"Could not read the GPS at {self.where()}: {exc}. Check the port name and, in Docker, "
                        "pass it in with --device."
                    )
                if not stop.is_set():
                    attempt += 1
                    await retry_sleep(stop, attempt)
        finally:
            pub.cancel()
