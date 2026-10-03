"""Source Watch: fetch watched sources on their cadence, keep immutable snapshots, record and announce changes."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.sources import diff as D
from engine.sources import normalize as N

logger = logging.getLogger(__name__)

USER_AGENT = "Abenix-SourceWatch/1.0"
MAX_REDIRECTS = 5
INLINE_TEXT_LIMIT = 2_000_000
TABLES_JSON_LIMIT = 8_000_000
MIN_CADENCE_MINUTES = 5
MAX_CADENCE_MINUTES = 60 * 24 * 31
CLAIM_BATCH = 25
CREDENTIAL_KEYS = tuple(f"SOURCE_AUTH_{i}" for i in range(1, 6))
_KEPT_HEADERS = (
    "content-type",
    "content-length",
    "etag",
    "last-modified",
    "date",
    "cache-control",
    "expires",
    "server",
    "content-language",
)
_REDIRECTS = (301, 302, 303, 307, 308)


class SourceError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _env_int(name: str, default: int, floor: int = 1) -> int:
    try:
        return max(floor, int(os.environ.get(name, default)))
    except ValueError:
        return default


def max_bytes() -> int:
    return _env_int("SOURCE_WATCH_MAX_BYTES", 25 * 1024 * 1024, 1024)


def fetch_timeout() -> float:
    return float(_env_int("SOURCE_WATCH_TIMEOUT_SECONDS", 30))


def host_interval() -> float:
    try:
        return max(
            0.0, float(os.environ.get("SOURCE_WATCH_HOST_INTERVAL_SECONDS", "2"))
        )
    except ValueError:
        return 2.0


def default_pause_after() -> int:
    return _env_int("SOURCE_WATCH_PAUSE_AFTER", 5)


def concurrency() -> int:
    return _env_int("SOURCE_WATCH_CONCURRENCY", 8)


def private_allowed() -> bool:
    return os.environ.get("SOURCE_WATCH_ALLOW_PRIVATE_TARGETS", "").lower() in (
        "1",
        "true",
        "yes",
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# Tenant settings


def clean_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    hosts = []
    for h in raw.get("host_allowlist") or []:
        h = str(h).strip().lower().rstrip(".")
        if h.startswith("*."):
            h = h[2:]
        if h and h not in hosts:
            hosts.append(h)
    try:
        pause = int(raw.get("pause_after_failures") or default_pause_after())
    except (TypeError, ValueError):
        pause = default_pause_after()
    return {"host_allowlist": hosts, "pause_after_failures": min(100, max(1, pause))}


async def tenant_settings(db: AsyncSession, tenant_id: Any) -> dict[str, Any]:
    from models.tenant import Tenant

    raw = (
        await db.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    return clean_settings((raw or {}).get("source_watch"))


def host_allowed(host: str, allowlist: list[str]) -> bool:
    """An entry covers the host itself and its subdomains. An empty list allows any public host."""
    if not allowlist:
        return True
    host = host.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in allowlist)


def _bad_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def blocked_reason(url: str, allowlist: list[str] | None = None) -> str | None:
    """Why this URL must not be fetched, judged on the address it resolves to now."""
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return "The URL must start with http:// or https:// and name a host."
    if u.username or u.password:
        return "Put sign-in details in a source credential, not in the URL."
    host = u.hostname
    if not host_allowed(host, allowlist or []):
        return f"{host} is not on this tenant's source host allowlist."
    if private_allowed():
        return None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return (
            f"{host} is a private address, which sources may not reach."
            if _bad_ip(literal)
            else None
        )
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, u.port or (443 if u.scheme == "https" else 80)
        )
    except OSError as e:
        return f"The host {host} does not resolve: {e}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _bad_ip(ip):
            return f"{host} resolves to a private address ({ip}), which sources may not reach."
    return None


class _HostGate:
    """At most one request at a time per host, spaced by SOURCE_WATCH_HOST_INTERVAL_SECONDS."""

    def __init__(self) -> None:
        self._locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, host: str) -> asyncio.Lock:
        key = (id(asyncio.get_running_loop()), host)
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        await lock.acquire()
        gap = host_interval() - (time.monotonic() - self._last.get(host, 0.0))
        if gap > 0:
            await asyncio.sleep(gap)
        return lock

    def done(self, host: str, lock: asyncio.Lock) -> None:
        self._last[host] = time.monotonic()
        lock.release()


_gate = _HostGate()


@dataclass
class FetchResult:
    ok: bool
    status: int | None = None
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    final_url: str = ""
    not_modified: bool = False
    error: str = ""
    blocked: bool = False
    elapsed_ms: int = 0


async def credential_headers(tenant_id: Any, key: str | None) -> dict[str, str]:
    """Turn a stored source credential into a request header."""
    if not key:
        return {}
    if key not in CREDENTIAL_KEYS:
        raise SourceError(
            f"{key} is not a source credential. Use one of {', '.join(CREDENTIAL_KEYS)}."
        )
    from engine import credentials

    await credentials.ensure_fresh()
    value = credentials.get(key, tenant_id=str(tenant_id)).strip()
    if not value:
        raise SourceError(
            f"The credential {key} is not set. An admin can add it under Admin, Tool Configuration, Source Watch."
        )
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9-]{0,63}):\s*(.+)$", value)
    if m and m.group(1).lower() not in ("bearer", "basic", "token"):
        return {m.group(1): m.group(2)}
    if " " in value:
        return {"Authorization": value}
    return {"Authorization": f"Bearer {value}"}


def _friendly(e: Exception) -> str:
    import httpx

    t = fetch_timeout()
    if isinstance(e, httpx.ConnectTimeout):
        return "The site did not accept a connection in time."
    if isinstance(e, httpx.TimeoutException):
        return f"The site did not answer within {int(t)} seconds."
    if isinstance(e, httpx.ConnectError):
        return f"Could not connect to the site: {str(e)[:200] or type(e).__name__}"
    if isinstance(e, httpx.TooManyRedirects):
        return "The site redirected too many times."
    return f"{type(e).__name__}: {str(e)[:300]}"


async def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    secret_headers: dict[str, str] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    allowlist: list[str] | None = None,
    transport: Any = None,
) -> FetchResult:
    """GET a source with conditional headers, a size cap and an SSRF check on every redirect hop."""
    import httpx

    started = time.monotonic()
    base = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    for k, v in (headers or {}).items():
        if k and v is not None and k.lower() not in ("host", "content-length"):
            base[str(k)] = str(v)
    if etag:
        base["If-None-Match"] = etag
    if last_modified:
        base["If-Modified-Since"] = last_modified
    origin = (urlparse(url).hostname or "").lower()
    cap = max_bytes()
    current = url

    async def run() -> FetchResult:
        nonlocal current
        timeout = httpx.Timeout(fetch_timeout(), connect=min(10.0, fetch_timeout()))
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, transport=transport
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                reason = await blocked_reason(current, allowlist)
                if reason:
                    return FetchResult(
                        ok=False, error=reason, blocked=True, final_url=current
                    )
                host = (urlparse(current).hostname or "").lower()
                hdrs = dict(base)
                # sign-in headers never follow a redirect to another host
                if host == origin:
                    hdrs.update(secret_headers or {})
                lock = await _gate.wait(host)
                try:
                    async with client.stream("GET", current, headers=hdrs) as r:
                        if r.status_code in _REDIRECTS and r.headers.get("location"):
                            current = urljoin(current, r.headers["location"])
                            continue
                        kept = {
                            k: r.headers[k] for k in _KEPT_HEADERS if k in r.headers
                        }
                        ctype = r.headers.get("content-type", "")
                        if r.status_code == 304:
                            return FetchResult(
                                ok=True,
                                status=304,
                                not_modified=True,
                                headers=kept,
                                final_url=current,
                                content_type=ctype,
                            )
                        if r.status_code >= 400:
                            return FetchResult(
                                ok=False,
                                status=r.status_code,
                                error=f"The site answered HTTP {r.status_code} {r.reason_phrase}".strip()
                                + ".",
                                headers=kept,
                                final_url=current,
                            )
                        declared = r.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > cap:
                            return FetchResult(
                                ok=False,
                                status=r.status_code,
                                error=f"The document is {int(declared):,} bytes, over the {cap:,} byte limit.",
                                final_url=current,
                            )
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in r.aiter_bytes():
                            size += len(chunk)
                            if size > cap:
                                return FetchResult(
                                    ok=False,
                                    status=r.status_code,
                                    error=f"The document is over the {cap:,} byte limit.",
                                    final_url=current,
                                )
                            chunks.append(chunk)
                        return FetchResult(
                            ok=True,
                            status=r.status_code,
                            body=b"".join(chunks),
                            headers=kept,
                            content_type=ctype,
                            final_url=current,
                        )
                finally:
                    _gate.done(host, lock)
            return FetchResult(
                ok=False, error="The site redirected too many times.", final_url=current
            )

    try:
        res = await asyncio.wait_for(run(), timeout=fetch_timeout() * 2 + 15)
    except asyncio.TimeoutError:
        res = FetchResult(
            ok=False,
            error=f"The fetch took longer than {int(fetch_timeout() * 2 + 15)} seconds.",
            final_url=current,
        )
    except Exception as e:  # noqa: BLE001
        res = FetchResult(ok=False, error=_friendly(e), final_url=current)
    res.elapsed_ms = int((time.monotonic() - started) * 1000)
    return res


# Storage


def raw_key(tenant_id: Any, sha: str) -> str:
    return f"sources/{tenant_id}/raw/{sha[:2]}/{sha}"


def text_key(tenant_id: Any, sha: str) -> str:
    return f"sources/{tenant_id}/text/{sha[:2]}/{sha}.txt"


def get_source_storage():
    from app.core.object_storage import get_object_storage

    return get_object_storage(
        local_root=os.environ.get("SOURCE_WATCH_LOCAL_ROOT") or None
    )


async def store_blob(key: str, data: bytes, content_type: str) -> None:
    storage = get_source_storage()
    if not await storage.exists(key):
        await storage.put(key, data, content_type or "application/octet-stream")


# Checking


@dataclass
class Prepared:
    fetch: FetchResult | None = None
    sha: str = ""
    text_sha: str = ""
    normalized: N.Normalized | None = None
    error: str = ""
    # a fault on our side, which must not count toward pausing the source
    platform_error: bool = False


def _tables_or_none(tables: dict | None) -> dict | None:
    if tables is None:
        return None
    import json

    return tables if len(json.dumps(tables)) <= TABLES_JSON_LIMIT else None


async def prepare(spec: dict[str, Any], settings: dict[str, Any]) -> Prepared:
    """Fetch and normalise outside any transaction, and store the blobs."""
    try:
        secret = await credential_headers(
            spec["tenant_id"], spec.get("credentials_key")
        )
    except SourceError as e:
        return Prepared(error=e.message)
    res = await fetch(
        spec["url"],
        headers=spec.get("headers") or {},
        secret_headers=secret,
        etag=spec.get("etag") if spec.get("current_sha") else None,
        last_modified=spec.get("last_modified") if spec.get("current_sha") else None,
        allowlist=settings.get("host_allowlist") or [],
    )
    if not res.ok:
        return Prepared(fetch=res, error=res.error)
    if res.not_modified:
        return Prepared(fetch=res)
    sha = D.sha256(res.body)
    if sha == spec.get("current_sha"):
        return Prepared(fetch=res, sha=sha)
    try:
        norm = await asyncio.to_thread(
            N.normalize,
            spec["kind"],
            res.body,
            res.content_type,
            spec.get("selector") or "",
        )
    except N.NormalizeError as e:
        return Prepared(fetch=res, sha=sha, error=str(e))
    except Exception as e:  # noqa: BLE001
        return Prepared(
            fetch=res,
            sha=sha,
            error=f"The document could not be read as {spec['kind']}: {e}",
        )
    text_sha = D.sha256(norm.text)
    try:
        await store_blob(raw_key(spec["tenant_id"], sha), res.body, res.content_type)
        await store_blob(
            text_key(spec["tenant_id"], text_sha),
            norm.text.encode("utf-8"),
            "text/plain; charset=utf-8",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("source %s: snapshot storage failed: %s", spec.get("id"), e)
        return Prepared(
            fetch=res,
            sha=sha,
            error=f"The snapshot could not be stored: {e}",
            platform_error=True,
        )
    return Prepared(fetch=res, sha=sha, text_sha=text_sha, normalized=norm)


def spec_of(src: Any, current_sha: str | None) -> dict[str, Any]:
    return {
        "id": str(src.id),
        "tenant_id": str(src.tenant_id),
        "url": src.url,
        "kind": src.kind,
        "selector": src.selector,
        "headers": dict(src.headers or {}),
        "credentials_key": src.credentials_key,
        "etag": src.etag,
        "last_modified": src.last_modified,
        "current_sha": current_sha,
    }


async def stopped_reason(src: Any) -> str | None:
    from engine import governance

    await governance.ensure_fresh()
    try:
        governance.check(src.tenant_id, "source", str(src.id))
    except governance.Stopped as s:
        return s.message()
    return None


async def record(
    db: AsyncSession,
    src: Any,
    prep: Prepared,
    settings: dict[str, Any],
    *,
    now: datetime | None = None,
    emit: Callable | None = None,
) -> dict[str, Any]:
    """Apply one check's outcome to the locked source row, in the caller's transaction."""
    from models.source_watch import SourceChange, SourceSnapshot

    if emit is None:
        from app.services.events import emit as _emit

        emit = _emit
    now = now or now_utc()
    src.last_checked_at = now
    src.check_count = (src.check_count or 0) + 1
    src.next_check_at = now + timedelta(minutes=src.cadence_minutes or 1440)
    out: dict[str, Any] = {"source_id": str(src.id)}

    if prep.error:
        src.last_status = "error"
        src.last_error = prep.error[:2000]
        if not prep.platform_error:
            src.consecutive_failures = (src.consecutive_failures or 0) + 1
        limit = settings.get("pause_after_failures") or default_pause_after()
        if src.active and src.consecutive_failures >= limit:
            src.active = False
            src.paused_reason = (
                f"Paused after {src.consecutive_failures} failed checks in a row. "
                f"Last error: {prep.error[:300]}"
            )
        out.update(
            status="error",
            error=prep.error,
            consecutive_failures=src.consecutive_failures,
            paused=not src.active,
        )
        return out

    res = prep.fetch
    src.consecutive_failures = 0
    src.last_error = None
    if res is not None and not res.not_modified:
        src.etag = (res.headers.get("etag") or "")[:512] or None
        src.last_modified = (res.headers.get("last-modified") or "")[:128] or None
    if res is not None and res.not_modified:
        src.last_status = "not_modified"
        out.update(status="not_modified")
        return out

    current = (
        await db.get(SourceSnapshot, src.current_snapshot_id)
        if src.current_snapshot_id
        else None
    )
    if current is not None and current.content_sha256 == prep.sha:
        src.last_status = "unchanged"
        out.update(status="unchanged", snapshot_id=str(current.id))
        return out
    norm = prep.normalized
    if norm is None:
        src.last_status = "unchanged"
        out.update(status="unchanged")
        return out
    same_parser = current is not None and current.parser_version == N.PARSER_VERSION
    if same_parser and current.text_sha256 == prep.text_sha:
        src.last_status = "unchanged"
        out.update(
            status="unchanged",
            snapshot_id=str(current.id),
            note="The bytes changed but the readable content did not.",
        )
        return out

    snap = (
        await db.execute(
            select(SourceSnapshot).where(
                SourceSnapshot.source_id == src.id,
                SourceSnapshot.content_sha256 == prep.sha,
            )
        )
    ).scalar_one_or_none()
    created = False
    if snap is None:
        text = norm.text
        snap = SourceSnapshot(
            id=uuid.uuid4(),
            tenant_id=src.tenant_id,
            source_id=src.id,
            url=res.final_url if res else src.url,
            kind=src.kind,
            content_sha256=prep.sha,
            text_sha256=prep.text_sha,
            storage_key=raw_key(src.tenant_id, prep.sha),
            content_type=(res.content_type if res else "")[:255],
            bytes=len(res.body) if res else 0,
            http_status=(res.status if res else None) or 200,
            http_headers=res.headers if res else {},
            fetched_at=now,
            parser_version=N.PARSER_VERSION,
            title=(norm.title or None),
            normalized_text=text[:INLINE_TEXT_LIMIT],
            normalized_text_key=text_key(src.tenant_id, prep.text_sha),
            text_truncated=len(text) > INLINE_TEXT_LIMIT,
            tables=_tables_or_none(norm.tables),
            notes=list(norm.notes or []),
        )
        db.add(snap)
        await db.flush()
        created = True
    out.update(snapshot_id=str(snap.id), snapshot_created=created)

    if current is None or not same_parser:
        src.current_snapshot_id = snap.id
        src.last_status = "baseline"
        out.update(
            status="baseline",
            note=(
                "First snapshot, kept as the baseline for later changes."
                if current is None
                else "The reader was upgraded, so this snapshot is a new baseline."
            ),
        )
        return out

    d = D.compare(
        src.kind,
        current.normalized_text or "",
        snap.normalized_text or "",
        (
            current.tables
            if current.tables is not None and snap.tables is not None
            else None
        ),
        snap.tables if current.tables is not None and snap.tables is not None else None,
    )
    src.current_snapshot_id = snap.id
    if d is None:
        src.last_status = "unchanged"
        out.update(status="unchanged")
        return out
    summary = d.pop("summary")
    hint = d.pop("materiality_hint")
    stats = d.get("stats") or {}
    change = SourceChange(
        id=uuid.uuid4(),
        tenant_id=src.tenant_id,
        source_id=src.id,
        from_snapshot_id=current.id,
        to_snapshot_id=snap.id,
        detected_at=now,
        summary=summary,
        diff=d,
        stats=stats,
        materiality_hint=hint,
    )
    db.add(change)
    await db.flush()
    src.last_changed_at = now
    src.last_status = "changed"
    await emit(
        db,
        src.tenant_id,
        "source.changed",
        {
            "source_id": str(src.id),
            "name": src.name,
            "url": src.url,
            "kind": src.kind,
            "jurisdiction": src.jurisdiction,
            "tags": list(src.tags or []),
            "risk_tier": src.risk_tier,
            "change_id": str(change.id),
            "snapshot_id": str(snap.id),
            "previous_snapshot_id": str(current.id),
            "content_sha256": snap.content_sha256,
            "fetched_at": now.isoformat(),
            "change_summary": summary,
            "materiality_hint": hint,
            "stats": {
                k: v for k, v in stats.items() if isinstance(v, (int, float, str))
            },
        },
    )
    out.update(
        status="changed",
        change_id=str(change.id),
        summary=summary,
        materiality_hint=hint,
        stats=stats,
    )
    return out


async def check_source(
    source_id: Any,
    *,
    manual: bool = False,
    session_factory: Any = None,
) -> dict[str, Any]:
    """One full check: read, fetch and normalise with no transaction open, then record under a row lock."""
    from models.source_watch import SourceSnapshot, WatchSource

    if session_factory is None:
        from app.core.deps import async_session as session_factory
    sid = uuid.UUID(str(source_id))
    async with session_factory() as db:
        src = await db.get(WatchSource, sid)
        if src is None:
            return {"source_id": str(sid), "status": "missing"}
        if not src.active and not manual:
            return {"source_id": str(sid), "status": "paused"}
        stop = await stopped_reason(src)
        if stop:
            src.last_status = "stopped"
            src.last_error = stop
            if not manual:
                src.last_checked_at = now_utc()
                src.next_check_at = now_utc() + timedelta(
                    minutes=src.cadence_minutes or 1440
                )
            await db.commit()
            return {"source_id": str(sid), "status": "stopped", "error": stop}
        settings = await tenant_settings(db, src.tenant_id)
        current_sha = None
        if src.current_snapshot_id:
            current_sha = (
                await db.execute(
                    select(SourceSnapshot.content_sha256).where(
                        SourceSnapshot.id == src.current_snapshot_id
                    )
                )
            ).scalar_one_or_none()
        spec = spec_of(src, current_sha)
        kb_id = src.ingest_to_kb

    prep = await prepare(spec, settings)

    async with session_factory() as db:
        async with db.begin():
            src = (
                await db.execute(
                    select(WatchSource).where(WatchSource.id == sid).with_for_update()
                )
            ).scalar_one_or_none()
            if src is None:
                return {"source_id": str(sid), "status": "missing"}
            out = await record(db, src, prep, settings)
            kb_id = src.ingest_to_kb

    if (
        kb_id
        and out.get("snapshot_id")
        and out.get("status") in ("baseline", "changed")
    ):
        try:
            doc = await ingest_snapshot(
                sid, uuid.UUID(out["snapshot_id"]), session_factory
            )
            if doc:
                out["kb_document_id"] = doc
        except Exception as e:  # noqa: BLE001
            logger.warning("source %s: knowledge base ingestion failed: %s", sid, e)
            out["kb_error"] = str(e)[:300]
    return out


def due_claim_stmt(now: datetime, limit: int = CLAIM_BATCH):
    from models.source_watch import WatchSource

    return (
        select(WatchSource)
        .where(
            WatchSource.active.is_(True),
            WatchSource.next_check_at.isnot(None),
            WatchSource.next_check_at <= now,
        )
        .order_by(WatchSource.next_check_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


async def claim_due(
    db: AsyncSession, now: datetime, limit: int = CLAIM_BATCH
) -> list[uuid.UUID]:
    """Lease due sources for one cadence so no other replica takes them, in the caller's transaction."""
    rows = (await db.execute(due_claim_stmt(now, limit))).scalars().all()
    for s in rows:
        s.next_check_at = now + timedelta(minutes=s.cadence_minutes or 1440)
    return [s.id for s in rows]


async def run_due(session_factory: Any = None) -> int:
    if session_factory is None:
        from app.core.deps import async_session as session_factory
    async with session_factory() as db:
        async with db.begin():
            ids = await claim_due(db, now_utc())
    if not ids:
        return 0
    sem = asyncio.Semaphore(concurrency())

    async def one(sid: uuid.UUID) -> None:
        async with sem:
            try:
                await check_source(sid, session_factory=session_factory)
            except Exception:  # noqa: BLE001
                logger.exception("source check %s failed", sid)

    await asyncio.gather(*(one(i) for i in ids))
    return len(ids)


async def preview(
    tenant_id: Any,
    *,
    url: str,
    kind: str | None,
    selector: str | None,
    headers: dict[str, str] | None,
    credentials_key: str | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Fetch and normalise without saving anything, for the add form."""
    try:
        secret = await credential_headers(tenant_id, credentials_key)
    except SourceError as e:
        return {"ok": False, "error": e.message}
    res = await fetch(
        url,
        headers=headers or {},
        secret_headers=secret,
        allowlist=settings.get("host_allowlist") or [],
    )
    base = {
        "status": res.status,
        "final_url": res.final_url,
        "elapsed_ms": res.elapsed_ms,
        "content_type": res.content_type,
    }
    if not res.ok:
        return {"ok": False, "error": res.error, "blocked": res.blocked, **base}
    detected = N.guess_kind(res.content_type, res.final_url or url, res.body)
    use = (kind or detected).lower()
    try:
        norm = await asyncio.to_thread(
            N.normalize, use, res.body, res.content_type, selector or ""
        )
    except N.NormalizeError as e:
        return {
            "ok": False,
            "error": str(e),
            "detected_kind": detected,
            "kind": use,
            "bytes": len(res.body),
            **base,
        }
    lines = norm.text.count("\n") + 1 if norm.text else 0
    tables = None
    if norm.tables:
        name, rows = next(iter(norm.tables.items()))
        tables = {
            "name": name,
            "rows": rows[:25],
            "total_rows": len(rows),
            "sheets": list(norm.tables),
        }
    return {
        "ok": True,
        "kind": use,
        "detected_kind": detected,
        "bytes": len(res.body),
        "sha256": D.sha256(res.body),
        "title": norm.title,
        "text": norm.text[:20000],
        "text_chars": len(norm.text),
        "lines": lines,
        "notes": norm.notes,
        "table": tables,
        "etag": res.headers.get("etag"),
        "last_modified": res.headers.get("last-modified"),
        **base,
    }


# Knowledge base ingestion through the same path as an upload


def kb_text(src: Any, snap: Any) -> str:
    when = snap.fetched_at.isoformat() if snap.fetched_at else ""
    head = (
        f"Source: {src.name}\nURL: {snap.url}\nRetrieved: {when}\n"
        f"Snapshot: {snap.id} (sha256 {snap.content_sha256})\n"
    )
    if snap.title:
        head = f"Title: {snap.title}\n" + head
    return head + "\n" + (snap.normalized_text or "")


async def ingest_snapshot(
    source_id: uuid.UUID, snapshot_id: uuid.UUID, session_factory: Any
) -> str | None:
    from models.knowledge_base import Document, DocumentStatus, KBStatus, KnowledgeBase
    from models.source_watch import SourceSnapshot, WatchSource

    async with session_factory() as db:
        src = await db.get(WatchSource, source_id)
        snap = await db.get(SourceSnapshot, snapshot_id)
        if src is None or snap is None or not src.ingest_to_kb:
            return None
        kb = await db.get(KnowledgeBase, src.ingest_to_kb)
        if kb is None or kb.tenant_id != src.tenant_id:
            return None
        data = kb_text(src, snap).encode("utf-8")
        doc_id = uuid.uuid4()
        safe = f"{doc_id}.txt"
        try:
            from engine.storage import get_storage

            storage_url = await get_storage().upload(
                tenant_id=str(src.tenant_id),
                path=f"kb/{kb.id}/{safe}",
                data=data,
                content_type="text/plain",
            )
        except ImportError:
            from pathlib import Path

            from app.routers.knowledge import UPLOAD_DIR

            d = Path(UPLOAD_DIR) / str(src.tenant_id) / str(kb.id)
            d.mkdir(parents=True, exist_ok=True)
            (d / safe).write_bytes(data)
            storage_url = str(d / safe)
        stamp = (
            snap.fetched_at.strftime("%Y-%m-%d %H:%M UTC") if snap.fetched_at else ""
        )
        head = (
            await db.get(Document, src.kb_document_id) if src.kb_document_id else None
        )
        doc = Document(
            id=doc_id,
            kb_id=kb.id,
            filename=f"{src.name} ({stamp}, {snap.content_sha256[:12]}).txt"[:500],
            file_type="txt",
            file_size=len(data),
            chunk_count=0,
            status=DocumentStatus.PROCESSING,
            storage_url=storage_url,
        )
        if head is not None and head.kb_id == kb.id:
            doc.parent_document_id = head.parent_document_id or head.id
            doc.version_number = (head.version_number or 1) + 1
            head.is_current = False
            head.superseded_by = doc.id
        db.add(doc)
        src.kb_document_id = doc.id
        kb.status = KBStatus.PROCESSING
        await db.commit()
        chunk_size, chunk_overlap, kb_id = kb.chunk_size, kb.chunk_overlap, kb.id
        filename = doc.filename

    from app.routers.knowledge import _dispatch_processing

    _dispatch_processing(
        doc_id=str(doc_id),
        kb_id=str(kb_id),
        file_path=storage_url,
        filename=filename,
        file_type="txt",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    try:
        from app.services.kb_cache import invalidate_tenant_search_cache

        await invalidate_tenant_search_cache(str(src.tenant_id))
    except Exception:  # noqa: BLE001
        pass
    return str(doc_id)
