"""A CAN bus: J1939 with address claim and transport protocol, OBD-II PIDs, or any bus with a DBC.

python-can opens the bus. socketcan reads a real interface (can0 from a PEAK,
Kvaser or built-in controller), socketcand reads a bus served over TCP, which
is how the in-cluster test bus and remote industrial PCs are reached.
"""

from __future__ import annotations

import asyncio
import threading
import time
import zlib
from typing import Any

from abenix_edge.collectors import j1939 as J
from abenix_edge.collectors import obd2
from abenix_edge.collectors.base import Collector, retry_sleep, slug

BITS_PER_EXT_FRAME = 67
BITS_PER_STD_FRAME = 47


def frame_bits(dlc: int, extended: bool) -> int:
    # nominal bits plus about 10 percent stuffing
    base = (BITS_PER_EXT_FRAME if extended else BITS_PER_STD_FRAME) + 8 * dlc
    return int(base * 1.1)


def load_dbc(text: str) -> Any:
    import cantools

    try:
        return cantools.database.load_string(text, "dbc", strict=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"The DBC file could not be read: {exc}") from None


def parse_parts(text: Any) -> dict[int, str]:
    """Source address to part name, from "0=engine, 3=transmission"."""
    out: dict[int, str] = {}
    if isinstance(text, dict):
        items = [f"{k}={v}" for k, v in text.items()]
    else:
        items = [x for x in str(text or "").replace(";", ",").split(",") if x.strip()]
    for it in items:
        if "=" not in it:
            raise ValueError(f"{it.strip()!r} should be address=part, such as 0=engine")
        a, p = it.split("=", 1)
        try:
            sa = int(a.strip(), 0)
        except ValueError:
            raise ValueError(
                f"{a.strip()!r} is not a source address, use 0 to 253"
            ) from None
        if not 0 <= sa <= 253:
            raise ValueError(f"Source address {sa} is outside 0 to 253")
        out[sa] = slug(p, f"sa{sa}")
    return out


def parse_pgns(text: Any) -> list[int]:
    out = []
    for it in str(text or "").replace(";", ",").replace(" ", ",").split(","):
        it = it.strip()
        if not it:
            continue
        try:
            out.append(int(it, 0))
        except ValueError:
            raise ValueError(
                f"{it!r} is not a PGN number, such as 65253 for engine hours"
            ) from None
    return out


def open_bus(spec: dict[str, Any]) -> Any:
    import can

    iface = spec.get("interface") or "socketcan"
    channel = spec.get("channel") or "can0"
    if iface == "socketcand":
        return can.Bus(
            interface="socketcand",
            host=spec.get("host") or "localhost",
            port=int(spec.get("port") or 29536),
            channel=channel,
        )
    if iface == "virtual":
        return can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
    return can.Bus(
        interface=iface, channel=channel, bitrate=int(spec.get("bitrate") or 250000)
    )


def plain_open_error(spec: dict[str, Any], exc: Exception) -> str:
    iface = spec.get("interface") or "socketcan"
    ch = spec.get("channel") or "can0"
    s = str(exc)
    if iface == "socketcand":
        where = f"{spec.get('host') or 'localhost'}:{spec.get('port') or 29536}"
        return (
            f"Could not reach the socketcand bus at {where} on channel {ch}. Check the address and "
            f"that socketcand is serving {ch} there ({s})."
        )
    if "No such device" in s or "19" in s.split(":")[0]:
        return (
            f"There is no CAN interface called {ch} on this box. Run ip link show to list them, "
            f"and bring it up with: sudo ip link set {ch} up type can bitrate {spec.get('bitrate') or 250000}"
        )
    if "Operation not permitted" in s or "Permission" in s:
        return (
            f"Not allowed to open {ch}. In Docker add --network host, and on Kubernetes use hostNetwork, "
            f"so the container can see the host's CAN interface ({s})."
        )
    return f"Could not open the CAN interface {ch} with {iface}: {s}"


class CanCollector(Collector):
    type = "can"
    label = "CAN bus (J1939, OBD-II, DBC)"

    def __init__(self, spec: dict[str, Any], sink: Any, gateway_id: str) -> None:
        super().__init__(spec, sink, gateway_id)
        self.protocol = spec.get("protocol") or "j1939"
        self.parts = J.AddressTable(parse_parts(spec.get("parts")))
        self.request_pgns = parse_pgns(spec.get("request_pgns"))
        self.request_every = float(spec.get("request_every_s") or 10)
        self.pids = (
            obd2.parse_pids(spec.get("obd_pids")) if self.protocol == "obd2" else []
        )
        self.obd_extended = bool(spec.get("obd_extended"))
        self.bitrate = int(spec.get("bitrate") or 250000)
        self.dbc = load_dbc(spec["dbc"]) if spec.get("dbc") else None
        self._dbc_by_pgn: dict[int, Any] = {}
        self._dbc_by_id: dict[int, Any] = {}
        if self.dbc is not None:
            for m in self.dbc.messages:
                self._dbc_by_id[m.frame_id] = m
                p = J.pgn_of_frame_id(m.frame_id, m.is_extended_frame)
                if p is not None:
                    self._dbc_by_pgn[p] = m
        self.claimer = J.Claimer(
            J.make_name(
                identity=zlib.crc32(f"{gateway_id}/{self.id}".encode()) & 0x1FFFFF,
                function=130,
                arbitrary=True,
            ),
            int(spec.get("own_address") or 249),
        )
        self.transport = J.Transport(
            lambda: self.claimer.address if self.claimer.claimed else None
        )
        self.frames = 0
        self.errors = 0
        self._bits: list[tuple[float, int]] = []
        self._bus: Any = None
        self._tx_lock = threading.Lock()

    # sending, under one lock since python-can buses are not thread safe for send

    def _send(self, arb: int, data: bytes, extended: bool = True) -> None:
        import can

        if self._bus is None:
            return
        with self._tx_lock:
            try:
                self._bus.send(
                    can.Message(arbitration_id=arb, data=data, is_extended_id=extended)
                )
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.fail(f"Could not send on the bus: {exc}", "running")

    # decoding

    def handle(self, arb: int, data: bytes, extended: bool, now: float) -> None:
        """One received frame. Public so the tests can feed frames without a bus."""
        self.frames += 1
        self._bits.append((now, frame_bits(len(data), extended)))
        if self.protocol == "obd2":
            if obd2.is_response(arb, extended):
                hit = obd2.decode(data)
                if hit:
                    _, name, value, unit = hit
                    self.update(obd2.ecu_of(arb, extended), name, value, unit)
            return
        if self.protocol == "dbc" or not extended:
            m = self._dbc_by_id.get(arb)
            if m is not None:
                self._dbc(
                    m, data, "bus" if not extended else self.parts.part(arb & 0xFF)
                )
            return
        _, pgn, sa, da = J.parse_id(arb)
        if pgn == J.ADDRESS_CLAIMED:
            name = self.parts.on_claim(sa, data)
            self.extra["ecus"] = {
                str(a): {
                    "part": self.parts.part(a),
                    "function": J.name_fields(n)["function"],
                }
                for a, n in self.parts.claims.items()
            }
            reply = self.claimer.on_claim(sa, name)
            if reply is not None:
                self._send(*reply)
            return
        if pgn == J.REQUEST and len(data) >= 3:
            want = data[0] | data[1] << 8 | data[2] << 16
            if (
                want == J.ADDRESS_CLAIMED
                and self.claimer.claimed
                and da in (J.GLOBAL, self.claimer.address)
            ):
                self._send(*self.claimer.claim_frame())
            return
        if pgn in (J.TP_CM, J.TP_DT):
            done, out = self.transport.feed(pgn, sa, da, data, now)
            for frame in out:
                self._send(*frame)
            for tpgn, tsa, _, payload in done:
                self._decode(tpgn, tsa, payload)
            self.extra["tp"] = {
                "completed": self.transport.completed,
                "timeouts": self.transport.timeouts,
                "aborts": self.transport.aborts,
            }
            return
        self._decode(pgn, sa, data)

    def _decode(self, pgn: int, sa: int, data: bytes) -> None:
        part = self.parts.part(sa)
        m = self._dbc_by_pgn.get(pgn)
        if m is not None:
            self._dbc(m, data, part)
            return
        for name, value, unit in J.decode(pgn, data):
            self.update(part, name, value, unit)

    def _dbc(self, m: Any, data: bytes, part: str) -> None:
        try:
            vals = m.decode(
                bytes(data).ljust(m.length, b"\xff"), decode_choices=False, scaling=True
            )
        except Exception:  # noqa: BLE001
            self.errors += 1
            return
        for sig_name, v in vals.items():
            sig = m.get_signal_by_name(sig_name)
            if (
                sig.maximum is not None
                and isinstance(v, (int, float))
                and v > sig.maximum
            ):
                # J1939 "not available" encodings land above the signal range
                continue
            self.update(part, f"{m.name}/{sig_name}", v, sig.unit or None)

    def bus_load(self) -> float:
        now = time.time()
        self._bits = [b for b in self._bits if now - b[0] <= 1.0]
        return round(100 * sum(b for _, b in self._bits) / self.bitrate, 2)

    # running

    def _rx_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            msg = self._bus.recv(0.5)
            if msg is None:
                continue
            if msg.is_error_frame:
                self.errors += 1
                continue
            self.handle(
                msg.arbitration_id, bytes(msg.data), msg.is_extended_id, time.time()
            )

    async def _requests(self, stop: asyncio.Event) -> None:
        if self.protocol == "j1939" and self.request_pgns:
            self._send(*self.claimer.claim_frame())
            await asyncio.sleep(0.25)
            self.claimer.claimed = not self.claimer.cannot_claim
        while not stop.is_set():
            if self.protocol == "obd2":
                for pid in self.pids:
                    arb, data, ext = obd2.request(pid, self.obd_extended)
                    self._send(arb, data, ext)
                    await asyncio.sleep(0.02)
                wait = self.interval
            elif self.request_pgns and self.claimer.claimed:
                for pgn in self.request_pgns:
                    self._send(*J.request_frame(pgn, self.claimer.address))
                wait = self.request_every
            else:
                wait = 5.0
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    async def _stats(self, stop: asyncio.Event) -> None:
        last = self.frames
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            fps = round((self.frames - last) / self.interval, 1)
            last = self.frames
            load = self.bus_load()
            self.extra.update(
                {
                    "frames": self.frames,
                    "frames_per_s": fps,
                    "bus_load_pct": load,
                    "bus_errors": self.errors,
                }
            )
            self.update("bus", "Bus/Load_pct", load, "%")
            self.update("bus", "Bus/Frames_per_s", fps, None)

    async def run(self, stop: asyncio.Event) -> None:
        attempt = 0
        while not stop.is_set():
            try:
                self._bus = await asyncio.to_thread(open_bus, self.spec)
            except Exception as exc:  # noqa: BLE001
                self.fail(plain_open_error(self.spec, exc))
                attempt += 1
                await retry_sleep(stop, attempt)
                continue
            attempt = 0
            self.ok()
            tstop = threading.Event()
            rx = asyncio.create_task(asyncio.to_thread(self._rx_loop, tstop))
            tasks = [
                asyncio.create_task(self.publisher(stop)),
                asyncio.create_task(self._requests(stop)),
                asyncio.create_task(self._stats(stop)),
            ]
            stopper = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait(
                [rx, stopper], return_when=asyncio.FIRST_COMPLETED
            )
            tstop.set()
            for t in tasks:
                t.cancel()
            stopper.cancel()
            if rx in done and rx.exception() is not None:
                self.fail(f"The CAN bus went away: {rx.exception()}. Reconnecting.")
            else:
                await asyncio.gather(rx, return_exceptions=True)
            try:
                self._bus.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._bus = None
            if not stop.is_set():
                attempt += 1
                await retry_sleep(stop, attempt)
