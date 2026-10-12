"""The gateway process: enrol once, then collect, buffer, send and report until stopped.

    ABENIX_URL            where Abenix is, such as https://abenix.example.com
    ABENIX_ENROLL_TOKEN   the one-time token from the Edge page, only needed the first time
    ABENIX_EDGE_DATA      the data folder for the buffer and the gateway key (/var/lib/abenix-edge)
    ABENIX_CA_FILE        a CA bundle when Abenix uses a private certificate
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from abenix_edge import VERSION
from abenix_edge.buffer import Buffer, Reading, now_ms
from abenix_edge.collectors import build
from abenix_edge.collectors.base import Collector, slug
from abenix_edge.uplink import Platform, Refused, Sender, State, machine_info

LOG = logging.getLogger("abenix-edge")


def spec_hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, default=str).encode()
    ).hexdigest()


class Manager:
    """Runs the collectors the platform configured, restarting only the ones that changed."""

    def __init__(self, gateway_id: str, sink: Any, data_dir: Path) -> None:
        self.gateway_id = gateway_id
        self.sink = sink
        self.data_dir = data_dir
        self.running: dict[str, tuple[Collector, asyncio.Event, asyncio.Task, str]] = {}
        self.failed: dict[str, dict[str, Any]] = {}

    async def apply(self, specs: list[dict[str, Any]]) -> None:
        want: dict[str, dict[str, Any]] = {}
        for s in specs:
            if s.get("enabled", True) is False:
                continue
            sid = str(s.get("id") or slug(s.get("name"), s.get("type") or "c"))
            want[sid] = {**s, "id": sid, "_data_dir": str(self.data_dir)}
        for sid in list(self.running):
            if sid not in want or spec_hash(want[sid]) != self.running[sid][3]:
                await self.stop_one(sid)
        self.failed = {k: v for k, v in self.failed.items() if k in want}
        for sid, s in want.items():
            if sid in self.running:
                continue
            try:
                c = build(s, self.sink, self.gateway_id)
            except Exception as exc:  # noqa: BLE001
                self.failed[sid] = {
                    "id": sid,
                    "type": s.get("type"),
                    "name": s.get("name") or sid,
                    "status": "error",
                    "error": str(exc),
                    "readings": 0,
                }
                LOG.warning("collector_config_rejected id=%s %s", sid, exc)
                continue
            self.failed.pop(sid, None)
            ev = asyncio.Event()
            task = asyncio.create_task(self._guard(c, ev))
            self.running[sid] = (c, ev, task, spec_hash(s))
            LOG.info(
                "collector_started id=%s type=%s subject=%s", sid, c.type, c.subject()
            )

    async def _guard(self, c: Collector, ev: asyncio.Event) -> None:
        while not ev.is_set():
            try:
                await c.run(ev)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOG.exception("collector_crashed id=%s", c.id)
                c.fail(f"The collector stopped on an error and restarts in 5 s: {exc}")
                try:
                    await asyncio.wait_for(ev.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

    async def stop_one(self, sid: str) -> None:
        c, ev, task, _ = self.running.pop(sid)
        ev.set()
        try:
            await asyncio.wait_for(task, timeout=10)
        except (
            asyncio.TimeoutError,
            asyncio.CancelledError,
            Exception,
        ):  # noqa: BLE001
            task.cancel()
        c.publish_latest()
        LOG.info("collector_stopped id=%s", sid)

    async def stop_all(self) -> None:
        for sid in list(self.running):
            await self.stop_one(sid)

    def health(self) -> list[dict[str, Any]]:
        return [c.health() for c, _, _, _ in self.running.values()] + list(
            self.failed.values()
        )


class Gateway:
    def __init__(self) -> None:
        self.url = (
            os.environ.get("ABENIX_URL") or os.environ.get("PLATFORM_URL") or ""
        ).strip()
        self.token = (os.environ.get("ABENIX_ENROLL_TOKEN") or "").strip()
        self.data_dir = Path(os.environ.get("ABENIX_EDGE_DATA", "/var/lib/abenix-edge"))
        self.ca_file = os.environ.get("ABENIX_CA_FILE") or None
        self.port = int(os.environ.get("PORT", "8080"))
        self.state = State(self.data_dir / "state.json")
        self.started = time.time()
        self.stop = asyncio.Event()
        self.config: dict[str, Any] = {}
        self.config_version = 0
        self.heartbeat_s = 15.0
        self.last_heartbeat_ok: float | None = None
        self.heartbeat_error: str | None = None
        self.self_seq = 0
        self.self_metrics_s = 10.0
        self.problem: str | None = None
        self.buffer: Buffer | None = None
        self.sender: Sender | None = None
        self.manager: Manager | None = None
        self.platform: Platform | None = None

    # readings land here from every collector thread

    def sink(self, rows: list[Reading]) -> None:
        if self.buffer is not None:
            self.buffer.add_many(rows)

    async def enroll(self) -> None:
        assert self.platform is not None
        attempt = 0
        while not self.stop.is_set():
            try:
                d = await self.platform.enroll(self.token)
            except Refused as exc:
                self.problem = f"Enrolment refused: {exc}"
                LOG.error(
                    "%s Make a new install command on the Edge page. Retrying in 60 s.",
                    self.problem,
                )
                await self._sleep(60)
                continue
            except ConnectionError as exc:
                attempt += 1
                self.problem = str(exc)
                LOG.warning("enroll_waiting %s", exc)
                await self._sleep(min(30, 2**attempt))
                continue
            self.state.update(
                platform_url=self.url,
                gateway_id=d["gateway_id"],
                gateway_pk=d.get("id"),
                name=d.get("name"),
                key=d["key"],
                connection_id=d["connection_id"],
                ingest_url=d["ingest_url"],
                signing_pubkey_pem=d.get("signing_pubkey_pem") or "",
                enrolled_at=int(time.time()),
                enrolled_with=hashlib.sha256(self.token.encode()).hexdigest(),
                config=d.get("config") or {},
                config_version=d.get("config_version") or 0,
            )
            self.problem = None
            LOG.info(
                "enrolled gateway_id=%s connection=%s",
                d["gateway_id"],
                d["connection_id"],
            )
            return

    async def _sleep(self, s: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=s)
        except asyncio.TimeoutError:
            pass

    async def apply_config(self, cfg: dict[str, Any], version: int) -> None:
        assert self.buffer and self.sender and self.manager
        buf = cfg.get("buffer") or {}
        self.buffer.configure(
            max_bytes=int(float(buf.get("max_mb") or 1024) * 1024 * 1024),
            max_age_s=int(float(buf.get("max_age_h") or 72) * 3600),
        )
        self.sender.configure(cfg.get("uplink") or {})
        self.heartbeat_s = float(cfg.get("heartbeat_s") or 15)
        self.self_metrics_s = float(cfg.get("self_metrics_s") or 10)
        await self.manager.apply(list(cfg.get("collectors") or []))
        self.config, self.config_version = cfg, version
        self.state.update(config=cfg, config_version=version)
        LOG.info(
            "config_applied version=%s collectors=%d",
            version,
            len(self.manager.running),
        )

    def health(self) -> dict[str, Any]:
        assert self.buffer and self.sender and self.manager
        return {
            "version": VERSION,
            **machine_info(),
            "uptime_s": int(time.time() - self.started),
            "applied_version": self.config_version,
            "buffer": self.buffer.stats(),
            "uplink": self.sender.health(),
            "collectors": self.manager.health(),
            "problem": self.problem,
            "endpoint_url": os.environ.get("ENDPOINT_URL") or None,
        }

    async def heartbeat_loop(self) -> None:
        assert self.platform is not None
        while not self.stop.is_set():
            try:
                d = await self.platform.heartbeat(
                    self.state.get("key"),
                    {"gateway_id": self.state.get("gateway_id"), **self.health()},
                )
                self.last_heartbeat_ok = time.time()
                self.heartbeat_error = None
                if self.sender and self.sender.status == "offline":
                    self.sender.retry_now.set()
                if self.problem and self.problem.startswith("Abenix refused"):
                    self.problem = None
                v = int(d.get("config_version") or 0)
                if d.get("config") is not None and v != self.config_version:
                    await self.apply_config(d["config"], v)
            except Refused as exc:
                self.heartbeat_error = str(exc)
                self.problem = f"Abenix refused this gateway: {exc}"
                LOG.error("heartbeat_refused %s", exc)
                if self.manager and "revoked" in str(exc).lower():
                    await self.manager.stop_all()
            except ConnectionError as exc:
                self.heartbeat_error = str(exc)
                LOG.warning("heartbeat_failed %s", exc)
            except Exception:  # noqa: BLE001
                LOG.exception("heartbeat_error")
            await self._sleep(self.heartbeat_s)

    async def writer_loop(self) -> None:
        assert self.buffer and self.sender
        tick = 0
        while not self.stop.is_set():
            await self._sleep(1.0)
            n = await asyncio.to_thread(self.buffer.flush)
            if n:
                self.sender.wake.set()
            tick += 1
            if tick % 60 == 0:
                await asyncio.to_thread(self.buffer.enforce_limits)
        await asyncio.to_thread(self.buffer.flush)

    async def self_metrics_loop(self) -> None:
        assert self.buffer
        self.self_seq = int(self.state.get("self_seq") or 0)
        g = slug((self.config.get("gateway_asset") or {}).get("group"), "edge")
        n = slug(self.state.get("gateway_id"), "gateway")
        while not self.stop.is_set():
            await self._sleep(self.self_metrics_s)
            st = self.buffer.stats()
            self.self_seq += 1
            ts = now_ms()
            subject = f"{g}/{n}/gateway"
            self.buffer.add_many(
                [
                    Reading(subject, "Edge/Seq", self.self_seq, ts),
                    Reading(subject, "Edge/BufferDepth", st["depth"], ts),
                    Reading(subject, "Edge/BufferAge_s", st["oldest_age_s"], ts, "s"),
                    Reading(
                        subject,
                        "Edge/Uptime_s",
                        int(time.time() - self.started),
                        ts,
                        "s",
                    ),
                ]
            )
            if self.self_seq % 10 == 0:
                self.state.update(self_seq=self.self_seq)

    async def status_server(self, port: int) -> None:
        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                line = await asyncio.wait_for(reader.readline(), 5)
                parts = line.decode("latin-1").split()
                while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                    pass
                path = parts[1] if len(parts) > 1 else "/"
                if path.startswith("/status"):
                    body = json.dumps(
                        self.health() if self.buffer else {"problem": self.problem},
                        default=str,
                    )
                    code = 200
                elif path.startswith("/health"):
                    ok = self.buffer is not None
                    body = json.dumps(
                        {"status": "ok" if ok else "enrolling", "problem": self.problem}
                    )
                    code = 200
                else:
                    body, code = json.dumps({"error": "not found"}), 404
                raw = body.encode()
                writer.write(
                    f"HTTP/1.1 {code} OK\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
                    f"Connection: close\r\n\r\n".encode() + raw
                )
                await writer.drain()
            except Exception:  # noqa: BLE001
                pass
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "0.0.0.0", port)
        async with server:
            await self.stop.wait()

    async def agents_role(self) -> None:
        """Runs agent bundles too when the platform gave this gateway the agents role."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import runtime

        os.environ.setdefault(
            "SIGNING_PUBKEY_PEM", self.state.get("signing_pubkey_pem") or ""
        )
        cfg = runtime.Config()
        try:
            runtime.check_startup(cfg)
        except SystemExit as exc:
            LOG.error("agents_role_off %s", exc)
            return
        registry = runtime.Registry(cfg)
        registry.reload_from_disk()
        await runtime.http_server(cfg, registry, self.port)

    async def run(self) -> int:
        if not self.url:
            LOG.error(
                "Set ABENIX_URL to your Abenix address, such as https://abenix.example.com"
            )
            return 2
        self.platform = Platform(self.url, self.ca_file)
        status_port = self.port
        status = asyncio.create_task(self.status_server(status_port))
        # a new install command on a box that enrolled before, such as after a revoke, enrols again
        fresh = bool(self.token) and hashlib.sha256(
            self.token.encode()
        ).hexdigest() != self.state.get("enrolled_with")
        if not self.state.enrolled or fresh:
            if not self.token:
                LOG.error(
                    "This gateway is not enrolled. Copy the install command from the Edge page in Abenix, "
                    "it carries ABENIX_ENROLL_TOKEN."
                )
                return 2
            await self.enroll()
            if self.stop.is_set():
                return 0
        gid = self.state.get("gateway_id")
        self.buffer = Buffer(self.data_dir / "buffer.db", gateway_id=gid)
        self.sender = Sender(self.platform, self.buffer, self.state)
        self.manager = Manager(gid, self.sink, self.data_dir)
        await self.apply_config(
            self.state.get("config") or {}, int(self.state.get("config_version") or 0)
        )
        tasks = [
            asyncio.create_task(self.writer_loop()),
            asyncio.create_task(self.sender.run(self.stop)),
            asyncio.create_task(self.heartbeat_loop()),
            asyncio.create_task(self.self_metrics_loop()),
        ]
        if "agents" in (self.config.get("roles") or []):
            status.cancel()
            tasks.append(asyncio.create_task(self.agents_role()))
            tasks.append(asyncio.create_task(self.status_server(status_port + 1)))
        LOG.info(
            "abenix_edge_running version=%s gateway_id=%s url=%s",
            VERSION,
            gid,
            self.url,
        )
        await self.stop.wait()
        await self.manager.stop_all()
        await asyncio.sleep(1.2)
        for t in tasks:
            t.cancel()
        self.buffer.flush()
        self.buffer.close()
        await self.platform.close()
        return 0


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    gw = Gateway()

    async def go() -> int:
        loop = asyncio.get_running_loop()
        for s in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(s, gw.stop.set)
            except NotImplementedError:
                pass
        return await gw.run()

    sys.exit(asyncio.run(go()))
