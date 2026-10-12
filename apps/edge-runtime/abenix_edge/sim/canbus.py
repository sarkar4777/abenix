"""A CAN bus in user space for tests and demos, served over the socketcand protocol (rawmode).

Every client is a controller on one bus. A frame occupies the bus for its bit
time at the bit rate, frames go out one after another, and each client gets
every frame but its own. A real socketcand daemon next to a real bus answers
the same commands, so Abenix Edge cannot tell the difference.

    python -m abenix_edge.sim.canbus      serves 0.0.0.0:29536, channel vcan0
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from abenix_edge.collectors.can_bus import frame_bits

LOG = logging.getLogger("canbus")
CHANNEL = os.environ.get("CAN_CHANNEL", "vcan0")
BITRATE = int(os.environ.get("CAN_BITRATE", "250000"))


class Bus:
    def __init__(self) -> None:
        self.clients: dict[int, asyncio.StreamWriter] = {}
        self.n = 0
        self.free_at = 0.0
        self.frames = 0
        self.busy: list[tuple[float, float]] = []

    def send(self, sender: int, cid: str, data: str) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        ext = len(cid) > 3
        dlc = len(data) // 2
        start = max(now, self.free_at)
        end = start + frame_bits(dlc, ext) / BITRATE
        self.free_at = end
        self.busy.append((start, end - start))
        line = f"< frame {cid} {time.time() + (end - now):.6f} {data} >".encode()
        loop.call_at(end, self._deliver, sender, line)

    def _deliver(self, sender: int, line: bytes) -> None:
        self.frames += 1
        for cid, w in list(self.clients.items()):
            if cid == sender:
                continue
            try:
                w.write(line)
            except (ConnectionError, RuntimeError):
                self.clients.pop(cid, None)

    def load_pct(self) -> float:
        now = asyncio.get_running_loop().time()
        self.busy = [b for b in self.busy if now - b[0] <= 1.0]
        return round(100 * sum(d for _, d in self.busy), 2)

    async def client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.n += 1
        me = self.n
        writer.write(b"< hi >")
        await writer.drain()
        buf = ""
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buf += chunk.decode("ascii", "replace")
                while True:
                    s, e = buf.find("<"), buf.find(">")
                    if s < 0 or e < 0:
                        break
                    cmd = buf[s + 1 : e].split()
                    buf = buf[e + 1 :]
                    if not cmd:
                        continue
                    if cmd[0] == "open":
                        writer.write(
                            b"< ok >"
                            if len(cmd) > 1 and cmd[1] == CHANNEL
                            else b"< error unknown channel >"
                        )
                        await writer.drain()
                    elif cmd[0] == "rawmode":
                        writer.write(b"< ok >")
                        await writer.drain()
                        # the client reads the reply alone before it parses frames
                        await asyncio.sleep(0.05)
                        self.clients[me] = writer
                    elif cmd[0] == "send" and len(cmd) >= 3:
                        dlc = int(cmd[2], 16)
                        data = "".join(f"{int(x, 16):02X}" for x in cmd[3 : 3 + dlc])
                        cid = cmd[1].upper()
                        self.send(
                            me, cid.zfill(8) if len(cid) > 3 else cid.zfill(3), data
                        )
                    elif cmd[0] == "echo":
                        writer.write(b"< echo >")
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.clients.pop(me, None)
            writer.close()


async def serve(host: str = "0.0.0.0", port: int = 29536) -> None:
    bus = Bus()
    server = await asyncio.start_server(bus.client, host, port)
    LOG.info(
        "canbus serving socketcand on %s:%d channel %s at %d bit/s",
        host,
        port,
        CHANNEL,
        BITRATE,
    )

    async def stats() -> None:
        while True:
            await asyncio.sleep(30)
            LOG.info(
                "canbus frames=%d load_pct=%.2f clients=%d",
                bus.frames,
                bus.load_pct(),
                len(bus.clients),
            )

    asyncio.create_task(stats())
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(
        serve(
            os.environ.get("CANBUS_LISTEN", "0.0.0.0"),
            int(os.environ.get("CANBUS_PORT", "29536")),
        )
    )
