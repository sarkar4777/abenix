"""The gateway's way out, as a TCP relay that can lose coverage on command.

Stands in for the cellular modem or site router between a gateway and
Abenix. A cut closes every open connection and refuses new ones until it ends.

    python -m abenix_edge.sim.uplink   UPLINK_TARGET=abenix-api.abenix:8000, listens on 18000, control on 18001
    curl -XPOST localhost:18001/cut?seconds=120     curl localhost:18001/state
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

LOG = logging.getLogger("uplink")


class Uplink:
    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port
        self.cut_until = 0.0
        self.cut_started = 0.0
        self.open: set[asyncio.StreamWriter] = set()
        self.refused = 0
        self.cuts: list[dict] = []

    @property
    def down(self) -> bool:
        return time.time() < self.cut_until

    async def relay(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if self.down:
            self.refused += 1
            writer.close()
            return
        try:
            ur, uw = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), 5
            )
        except (OSError, asyncio.TimeoutError):
            writer.close()
            return
        self.open.update((writer, uw))

        async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
            try:
                while not r.at_eof():
                    data = await r.read(65536)
                    if not data or self.down:
                        break
                    w.write(data)
                    await w.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                w.close()

        await asyncio.gather(pipe(reader, uw), pipe(ur, writer))
        self.open.discard(writer)
        self.open.discard(uw)

    def cut(self, seconds: float) -> dict:
        self.cut_started = time.time()
        self.cut_until = self.cut_started + seconds
        for w in list(self.open):
            w.close()
        self.open.clear()
        rec = {"started": self.cut_started, "until": self.cut_until, "seconds": seconds}
        self.cuts.append(rec)
        LOG.info("uplink cut for %.0f s", seconds)
        return rec

    async def control(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = (await reader.readline()).decode("latin-1")
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass
            parts = line.split()
            path = parts[1] if len(parts) > 1 else "/"
            if parts and parts[0] == "POST" and path.startswith("/cut"):
                secs = 120.0
                if "seconds=" in path:
                    secs = float(path.split("seconds=", 1)[1].split("&")[0])
                body = self.cut(secs)
            elif parts and parts[0] == "POST" and path.startswith("/restore"):
                self.cut_until = 0
                body = {"restored": True}
            else:
                body = {
                    "down": self.down,
                    "cut_until": self.cut_until,
                    "refused": self.refused,
                    "cuts": self.cuts[-5:],
                }
            raw = json.dumps(body).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(raw)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + raw
            )
            await writer.drain()
        finally:
            writer.close()


async def main() -> None:
    target = os.environ.get("UPLINK_TARGET", "localhost:8000")
    host, _, port = target.rpartition(":")
    up = Uplink(host, int(port))
    s1 = await asyncio.start_server(
        up.relay, "0.0.0.0", int(os.environ.get("UPLINK_PORT", "18000"))
    )
    s2 = await asyncio.start_server(
        up.control, "0.0.0.0", int(os.environ.get("UPLINK_CONTROL_PORT", "18001"))
    )
    LOG.info("uplink relaying to %s", target)
    async with s1, s2:
        await asyncio.gather(s1.serve_forever(), s2.serve_forever())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(main())
