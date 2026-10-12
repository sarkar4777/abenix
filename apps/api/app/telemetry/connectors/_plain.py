"""Shared bits for the stream connectors: plain-words errors, the reconnect loop, TLS and test results."""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import socket
import ssl
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Iterator

from app.telemetry.connectors.base import ConnectorError, RunContext, backoff

logger = logging.getLogger("app.telemetry.connectors")

SAMPLE_MAX = 2000


def result(**kw: Any) -> dict[str, Any]:
    out = {
        "ok": False,
        "connected": False,
        "messages": 0,
        "subjects_seen": [],
        "sample": None,
        "error": None,
    }
    out.update(kw)
    return out


def sample_of(payload: bytes) -> str:
    text = payload[:SAMPLE_MAX].decode("utf-8", errors="replace")
    return text + ("..." if len(payload) > SAMPLE_MAX else "")


def scrub(text: str, secrets: dict[str, Any] | None) -> str:
    """Takes any secret value out of a message before it is shown or logged."""
    for v in (secrets or {}).values():
        if isinstance(v, str) and len(v) >= 4:
            text = text.replace(v, "***")
    return text


def subjects_of(cfg: dict[str, Any], key: str = "subjects") -> list[str]:
    raw = cfg.get(key)
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.replace("\n", ",").split(",")
    return [str(s).strip() for s in raw if str(s or "").strip()]


def as_int(cfg: dict[str, Any], key: str, default: int) -> int:
    v = cfg.get(key)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ConnectorError(f"{key} must be a whole number, it is {v!r}") from None


def as_bool(cfg: dict[str, Any], key: str, default: bool) -> bool:
    v = cfg.get(key)
    if v in (None, ""):
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def is_refused(exc: BaseException) -> bool:
    if isinstance(exc, ConnectionRefusedError):
        return True
    return isinstance(exc, OSError) and exc.errno in (
        errno.ECONNREFUSED,
        10061,
    )


def walk(exc: BaseException) -> Iterator[BaseException]:
    """The exception and whatever caused it, the root cause is usually the useful one."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        if isinstance(cur, BaseExceptionGroup):
            for sub in cur.exceptions:
                yield from walk(sub)
        cur = cur.__cause__ or cur.__context__


def network_words(exc: BaseException, where: str, what: str) -> str | None:
    """DNS, refused, TLS and timeouts in plain words. None when it is none of those."""
    host = where.rsplit(":", 1)[0]
    for e in walk(exc):
        if isinstance(e, socket.gaierror) or (
            isinstance(e, OSError) and "getaddrinfo" in str(e).lower()
        ):
            return f"Could not find a host called {host}. Check the {what} address."
        if isinstance(
            e, ssl.SSLCertVerificationError
        ) or "certificate verify failed" in str(e):
            return (
                f"The {what} at {where} sent a certificate that is not trusted. "
                "Add the CA certificate that signed it, or check the host name matches the certificate."
            )
        if isinstance(e, ssl.SSLError):
            return (
                f"The secure connection to {where} failed. Check the {what} uses TLS on this port, "
                "or turn TLS off for a plain connection."
            )
        if is_refused(e):
            return f"Nothing answered at {where}. Check the port and that the {what} is running."
        if isinstance(e, (asyncio.TimeoutError, TimeoutError, socket.timeout)):
            return (
                f"No answer from {where} in time. Check the address, the port and any "
                "firewall between Abenix and it."
            )
        if isinstance(
            e, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)
        ):
            return f"The {what} at {where} closed the connection. It may be restarting, or it expects TLS."
        if isinstance(e, OSError) and e.errno in (
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
            10065,
            10051,
        ):
            return f"There is no route to {where}. Check the address and the network."
    return None


def ssl_context(
    cfg: dict[str, Any], secrets: dict[str, Any], *, verify_default: bool = True
) -> ssl.SSLContext:
    """A client TLS context from PEM text: CA, client certificate and key."""
    ctx = ssl.create_default_context()
    ca = (cfg.get("tls_ca") or "").strip()
    if ca:
        try:
            ctx.load_verify_locations(cadata=ca)
        except ssl.SSLError:
            raise ConnectorError("The CA certificate is not valid PEM text") from None
    if not as_bool(cfg, "tls_verify", verify_default):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    cert = (cfg.get("tls_cert") or "").strip()
    key = (secrets.get("tls_key") or "").strip()
    if cert or key:
        if not (cert and key):
            raise ConnectorError(
                "For a client certificate, give both the certificate and its private key"
            )
        with pem_files(cert, key) as (cpath, kpath):
            try:
                ctx.load_cert_chain(cpath, kpath)
            except ssl.SSLError:
                raise ConnectorError(
                    "The client certificate and key do not load. Check both are PEM and belong together."
                ) from None
    return ctx


@contextmanager
def pem_files(*texts: str) -> Iterator[list[str]]:
    """Writes PEM text to private temporary files for libraries that only take paths."""
    paths: list[str] = []
    try:
        for t in texts:
            fd, path = tempfile.mkstemp(suffix=".pem")
            with os.fdopen(fd, "w") as fh:
                fh.write(t)
            os.chmod(path, 0o600)
            paths.append(path)
        yield paths
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass


async def sleep_or_stop(ctx: RunContext, seconds: float) -> bool:
    """Sleeps, but wakes at once on stop. True when stopping."""
    try:
        await asyncio.wait_for(ctx.stopping.wait(), timeout=max(0.0, seconds))
    except asyncio.TimeoutError:
        pass
    return ctx.stopping.is_set()


class Supervisor:
    """The reconnect loop every connector shares: status, backoff with jitter, clean stop."""

    def __init__(
        self,
        ctx: RunContext,
        words: Callable[[BaseException], str],
        name: str,
        *,
        cap: float = 30.0,
    ) -> None:
        self.ctx = ctx
        self.words = words
        self.name = name
        self.cap = cap
        self.attempt = 0
        self.connected_at: float | None = None

    def connected(self) -> None:
        self.attempt = 0
        self.connected_at = time.time()
        self.ctx.set_status("connected", None)

    async def run(self, once: Callable[[], Awaitable[None]]) -> None:
        ctx = self.ctx
        while not ctx.stopping.is_set():
            ctx.set_status("connecting", ctx.last_error)
            try:
                await once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if ctx.stopping.is_set():
                    break
                msg = scrub(self.words(exc), ctx.secrets)
                ctx.set_status("error", msg)
                logger.warning("telemetry %s %s: %s", self.name, ctx.connection_id, msg)
            else:
                if ctx.stopping.is_set():
                    break
            # a session that held for a minute starts the backoff again from the bottom
            if self.connected_at and time.time() - self.connected_at > 60:
                self.attempt = 0
            self.connected_at = None
            delay = backoff(self.attempt, cap=self.cap)
            self.attempt += 1
            if await sleep_or_stop(ctx, delay):
                break
        ctx.set_status("disabled", None)


async def until_stopped(ctx: RunContext, *aws: Awaitable[Any]) -> None:
    """Waits for stop or for any of the awaitables to finish. Re-raises what failed."""
    stop = asyncio.ensure_future(ctx.stopping.wait())
    tasks = [asyncio.ensure_future(a) for a in aws]
    try:
        done, _ = await asyncio.wait(
            [stop, *tasks], return_when=asyncio.FIRST_COMPLETED
        )
        for t in done:
            if t is not stop and t.exception() is not None:
                raise t.exception()  # type: ignore[misc]
    finally:
        for t in [stop, *tasks]:
            if not t.done():
                t.cancel()
        for t in [stop, *tasks]:
            try:
                await t
            except BaseException:  # noqa: BLE001
                pass


def deadline_left(deadline: float) -> float:
    return max(0.05, deadline - time.monotonic())


def now_ms() -> int:
    return int(time.time() * 1000)


def host_port(text: str, default_port: int) -> tuple[str, int]:
    t = (text or "").strip()
    if "://" in t:
        t = t.split("://", 1)[1]
    t = t.split("/", 1)[0].rsplit("@", 1)[-1]
    if t.startswith("["):
        host, _, rest = t[1:].partition("]")
        port = rest.lstrip(":")
    elif t.count(":") == 1:
        host, port = t.split(":")
    else:
        host, port = t, ""
    try:
        return host, int(port) if port else default_port
    except ValueError:
        raise ConnectorError(f"The port in {text} must be a number") from None


async def probe_tcp(
    host: str, port: int, what: str, timeout: float = 3.0
) -> str | None:
    """Opens and closes a TCP connection. Plain words when that fails, None when it works."""
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except Exception as exc:  # noqa: BLE001
        return network_words(exc, f"{host}:{port}", what) or (
            f"Could not reach the {what} at {host}:{port}: {type(exc).__name__}"
        )
    w.close()
    try:
        await w.wait_closed()
    except Exception:  # noqa: BLE001
        pass
    return None


def payload_bytes(target: dict[str, Any], value: Any) -> bytes:
    """The bytes a command sends: the rendered payload when there is one, else the value as JSON."""
    import json

    body = target.get("payload")
    if body is None:
        body = value
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, str):
        return body.encode()
    return json.dumps(body, default=str).encode()


def iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
