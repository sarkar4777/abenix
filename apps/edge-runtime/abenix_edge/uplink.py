"""Talking to Abenix: enrolment, the heartbeat that carries health out and config back, and the sender."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import platform
import random
import socket
import time
from pathlib import Path
from typing import Any

import httpx

from abenix_edge import VERSION
from abenix_edge.buffer import Buffer

LOG = logging.getLogger("abenix-edge")
VALUES_TYPE = "application/vnd.abenix.values+json"


class Refused(Exception):
    """Abenix said no in a way retrying will not fix. The message is plain words for the health view."""


class State:
    """What enrolment gave this gateway, kept on its data volume."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, k: str, default: Any = None) -> Any:
        return self.data.get(k, default)

    def update(self, **kw: Any) -> None:
        self.data.update(kw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def clear_key(self) -> None:
        for k in ("key", "connection_id", "ingest_url"):
            self.data.pop(k, None)
        self.update()

    @property
    def enrolled(self) -> bool:
        return bool(self.data.get("key") and self.data.get("gateway_id"))


def machine_info() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "platform": f"{platform.system().lower()}/{platform.machine().lower()}",
        "version": VERSION,
        "python": platform.python_version(),
    }


def _plain(r: httpx.Response) -> str:
    try:
        j = r.json()
        msg = (
            (j.get("error") or {}).get("message")
            if isinstance(j.get("error"), dict)
            else None
        )
        return msg or j.get("detail") or r.text[:300]
    except ValueError:
        return r.text[:300] or f"HTTP {r.status_code}"


def _network_plain(url: str, exc: Exception) -> str:
    s = str(exc) or type(exc).__name__
    if isinstance(exc, httpx.ConnectError):
        if "CERTIFICATE" in s.upper() or "SSL" in s.upper():
            return f"The TLS certificate of {url} is not trusted on this box. Mount your CA and set ABENIX_CA_FILE ({s})."
        return f"Could not reach Abenix at {url}. Check the address and that this box can get out to it ({s})."
    if isinstance(exc, httpx.TimeoutException):
        return f"Abenix at {url} did not answer in time. The link may be down or slow."
    return f"Talking to Abenix at {url} failed: {s}"


class Platform:
    def __init__(
        self, url: str, ca_file: str | None = None, transport: Any = None
    ) -> None:
        self.url = url.rstrip("/")
        verify: Any = ca_file if ca_file else True
        self.http = httpx.AsyncClient(
            base_url=self.url,
            transport=transport,
            timeout=httpx.Timeout(20.0, connect=8.0),
            verify=verify,
            headers={"User-Agent": f"abenix-edge/{VERSION}"},
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def enroll(self, token: str) -> dict[str, Any]:
        try:
            r = await self.http.post(
                "/api/edge/enroll", json={"token": token, **machine_info()}
            )
        except httpx.HTTPError as exc:
            raise ConnectionError(_network_plain(self.url, exc)) from None
        if r.status_code in (400, 401, 403, 404, 409, 410, 422):
            raise Refused(_plain(r))
        if r.status_code >= 300:
            raise ConnectionError(
                f"Abenix answered {r.status_code} to the enrolment: {_plain(r)}"
            )
        return r.json()["data"]

    async def heartbeat(self, key: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            r = await self.http.post(
                "/api/edge/heartbeat",
                json=body,
                headers={"Authorization": f"Bearer {key}"},
            )
        except httpx.HTTPError as exc:
            raise ConnectionError(_network_plain(self.url, exc)) from None
        if r.status_code in (401, 403, 404, 410):
            raise Refused(_plain(r))
        if r.status_code >= 300:
            raise ConnectionError(
                f"Abenix answered {r.status_code} to the heartbeat: {_plain(r)}"
            )
        return r.json()["data"]

    async def push(
        self,
        key: str,
        ingest_url: str,
        subject: str,
        body: bytes,
        idem: str,
        use_gzip: bool,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": VALUES_TYPE,
            "Idempotency-Key": idem,
            "X-Source": "abenix-edge",
        }
        if use_gzip:
            body = gzip.compress(body, 6)
            headers["Content-Encoding"] = "gzip"
        return await self.http.post(
            ingest_url, params={"subject": subject}, content=body, headers=headers
        )


class Sender:
    """Oldest first, one batch at a time, so Abenix sees each asset's readings in order."""

    def __init__(self, platform: Platform, buffer: Buffer, state: State) -> None:
        self.p = platform
        self.buf = buffer
        self.state = state
        self.gzip = False
        self.max_values = 5000
        self.max_bytes = 900_000
        self.status = "starting"
        self.error: str | None = None
        self.last_ok_at: float | None = None
        self.batches = 0
        self.retries = 0
        self.split = 0
        self.bytes_sent = 0
        self.wake = asyncio.Event()
        # set when a heartbeat gets through, so a waiting retry goes at once
        self.retry_now = asyncio.Event()
        self.paused_until = 0.0

    def health(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error": self.error,
            "last_ok_at": int(self.last_ok_at * 1000) if self.last_ok_at else None,
            "batches": self.batches,
            "retries": self.retries,
            "splits": self.split,
            "bytes_sent": self.bytes_sent,
            "gzip": self.gzip,
        }

    def configure(self, uplink: dict[str, Any]) -> None:
        self.gzip = bool(uplink.get("gzip", self.gzip))
        self.max_values = int(uplink.get("batch_max_values") or self.max_values)
        self.max_bytes = int(uplink.get("max_post_bytes") or self.max_bytes)

    async def run(self, stop: asyncio.Event) -> None:
        attempt = 0
        while not stop.is_set():
            self.retry_now.clear()
            key, url = self.state.get("key"), self.state.get("ingest_url")
            if not key or not url or time.time() < self.paused_until:
                await self._sleep(stop, 2.0)
                continue
            batch = await asyncio.to_thread(
                self.buf.next_batch, self.max_values, self.max_bytes
            )
            if batch is None:
                if self.status not in ("revoked", "disabled"):
                    self.status = "online" if self.last_ok_at else self.status
                self.wake.clear()
                await self._sleep(stop, 1.0, self.wake)
                continue
            body = batch.body()
            try:
                r = await self.p.push(
                    key, url, batch.subject, body, batch.key, self.gzip
                )
            except httpx.HTTPError as exc:
                attempt += 1
                self.retries += 1
                self.status, self.error = "offline", _network_plain(self.p.url, exc)
                await self._sleep(stop, self._backoff(attempt), self.retry_now)
                continue
            code = r.status_code
            if code in (200, 201, 202):
                await asyncio.to_thread(self.buf.ack, batch)
                attempt = 0
                self.batches += 1
                self.bytes_sent += len(body)
                self.last_ok_at = time.time()
                self.status, self.error = "online", None
                continue
            if code == 401:
                self.status = "revoked"
                self.error = (
                    "Abenix refused this gateway's key, it was revoked or replaced. Readings stay in the buffer. "
                    "Re-enrol the gateway from the Edge page to send them."
                )
                self.paused_until = time.time() + 60
                continue
            if code == 409:
                self.status = "disabled"
                self.error = "The source for this gateway is turned off in Abenix. Readings wait in the buffer until it is on."
                self.paused_until = time.time() + 30
                continue
            if code == 413:
                self.split += 1
                if not await asyncio.to_thread(self.buf.split, batch):
                    LOG.error(
                        "batch_rejected key=%s one reading is over the size limit",
                        batch.key,
                    )
                    await asyncio.to_thread(self.buf.reject, batch)
                continue
            if code == 400 and "ENCODING" in r.text.upper():
                self.error = "Abenix could not read the compressed batch, sending it uncompressed."
                self.gzip = False
                continue
            if code in (400, 415, 422):
                LOG.error(
                    "batch_rejected key=%s status=%s %s", batch.key, code, _plain(r)
                )
                self.error = f"Abenix would not take a batch ({_plain(r)}). It was set aside, see the gateway log."
                await asyncio.to_thread(self.buf.reject, batch)
                continue
            attempt += 1
            self.retries += 1
            self.status, self.error = (
                "offline",
                f"Abenix answered {code}, retrying: {_plain(r)}",
            )
            await self._sleep(stop, self._backoff(attempt), self.retry_now)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return random.uniform(0.5, min(15.0, 2 ** min(attempt, 4)))

    @staticmethod
    async def _sleep(
        stop: asyncio.Event, s: float, also: asyncio.Event | None = None
    ) -> None:
        waits = [asyncio.ensure_future(stop.wait())]
        if also is not None:
            waits.append(asyncio.ensure_future(also.wait()))
        try:
            await asyncio.wait(waits, timeout=s, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waits:
                w.cancel()
