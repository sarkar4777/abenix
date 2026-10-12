"""Keys for HTTP push sources, and the source an Abenix Edge gateway gets when it enrols.

A device key binds one asset id: whatever its messages say, their records are
written as that asset. A gateway key writes for many assets, limited to its
group and to the node patterns it is given.
"""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import io
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.telemetry.decoders.base import DecodeError, Record
from models.telemetry import TelemetryConnection, TelemetryDeviceKey

DEVICE_PREFIX = "tdk_"
GATEWAY_PREFIX = "tgk_"
BULK_MAX = 5000
HEADER_PREFIX = "x-abenix-"
H_KIND = "x-abenix-key-kind"
H_DEVICE = "x-abenix-device"
H_GROUP = "x-abenix-group"
H_NODES = "x-abenix-nodes"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_key(kind: str = "device") -> tuple[str, str, str]:
    """(raw key, display prefix, sha256). The raw key is shown once."""
    raw = (
        GATEWAY_PREFIX if kind == "gateway" else DEVICE_PREFIX
    ) + secrets.token_urlsafe(32)
    return raw, raw[:12], hash_key(raw)


def clean_device_id(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        raise ValueError("Every key needs a device id, the asset it writes as")
    if len(s) > 255 or any(c in s for c in "/#+\n\r\t"):
        raise ValueError(
            f"{s[:40]!r} cannot be a device id, it must be one name without / # or +"
        )
    return s


async def create_key(
    db: AsyncSession,
    conn: TelemetryConnection,
    *,
    device_id: str,
    kind: str = "device",
    group: str | None = None,
    allowed_nodes: list[str] | None = None,
    label: str = "",
    created_by: Any = None,
) -> tuple[TelemetryDeviceKey, str]:
    """A new key on an HTTP push source. Flushes, never commits."""
    if kind not in ("device", "gateway"):
        raise ValueError("kind is device or gateway")
    raw, prefix, digest = new_key(kind)
    k = TelemetryDeviceKey(
        id=uuid.uuid4(),
        tenant_id=conn.tenant_id,
        connection_id=conn.id,
        kind=kind,
        device_id=clean_device_id(device_id),
        group=(group or None),
        allowed_nodes=[str(p).strip() for p in (allowed_nodes or []) if str(p).strip()],
        label=(label or "")[:255],
        key_prefix=prefix,
        key_hash=digest,
        created_by=created_by,
    )
    db.add(k)
    await db.flush()
    return k, raw


def parse_csv(text: str) -> list[dict[str, str]]:
    """device_id with optional label and group columns. A header row is needed."""
    rows = list(csv.DictReader(io.StringIO(text.strip())))
    if not rows:
        raise ValueError(
            "The CSV has no rows. Start with a header row such as device_id,label"
        )
    if "device_id" not in (rows[0].keys() if rows else ()):
        raise ValueError("The CSV needs a device_id column")
    if len(rows) > BULK_MAX:
        raise ValueError(f"At most {BULK_MAX} keys at once")
    seen = set()
    out = []
    for i, r in enumerate(rows, 2):
        try:
            did = clean_device_id(r.get("device_id"))
        except ValueError as exc:
            raise ValueError(f"Row {i}: {exc}") from None
        if did in seen:
            raise ValueError(f"Row {i}: {did} is in the file twice")
        seen.add(did)
        out.append(
            {
                "device_id": did,
                "label": (r.get("label") or "").strip(),
                "group": (r.get("group") or "").strip(),
            }
        )
    return out


async def find_key(
    db: AsyncSession, raw: str, connection_id: Any
) -> TelemetryDeviceKey | None:
    if not raw.startswith((DEVICE_PREFIX, GATEWAY_PREFIX)):
        return None
    k = (
        await db.execute(
            select(TelemetryDeviceKey).where(
                TelemetryDeviceKey.key_hash == hash_key(raw)
            )
        )
    ).scalar_one_or_none()
    if (
        k is None
        or k.revoked_at is not None
        or str(k.connection_id) != str(connection_id)
    ):
        return None
    return k


_used: dict[str, float] = {}


async def touch(db: AsyncSession, k: TelemetryDeviceKey) -> None:
    """last_used_at, written at most once a minute per key."""
    import time

    now = time.monotonic()
    if now - _used.get(str(k.id), 0) < 60:
        return
    _used[str(k.id)] = now
    k.last_used_at = datetime.now(timezone.utc)
    await db.commit()


def identity_headers(k: TelemetryDeviceKey) -> dict[str, str]:
    h = {H_KIND: k.kind, H_DEVICE: k.device_id}
    if k.group:
        h[H_GROUP] = k.group
    if k.allowed_nodes:
        h[H_NODES] = json.dumps(list(k.allowed_nodes))
    return h


def enforce(headers: dict[str, str], records: list[Record]) -> list[Record]:
    """A device writes only as itself, a gateway only within its group and nodes."""
    kind = headers.get(H_KIND)
    if not kind:
        return records
    group = headers.get(H_GROUP)
    if kind == "device":
        dev = headers.get(H_DEVICE) or ""
        for r in records:
            if r.kind == "state":
                continue
            r.node = dev
            if group:
                r.group = group
        return records
    try:
        nodes = json.loads(headers.get(H_NODES) or "[]")
    except ValueError:
        nodes = []
    for r in records:
        if r.kind == "state":
            continue
        if group:
            r.group = group
        if nodes and not any(fnmatch.fnmatchcase(r.node, p) for p in nodes):
            raise DecodeError(
                f"The gateway key of {headers.get(H_DEVICE)} may not write for {r.node}. "
                "Add the asset to the key's allowed assets, or use that device's own key."
            )
    return records


def key_json(k: TelemetryDeviceKey) -> dict[str, Any]:
    return {
        "id": str(k.id),
        "connection_id": str(k.connection_id),
        "kind": k.kind,
        "device_id": k.device_id,
        "group": k.group,
        "allowed_nodes": list(k.allowed_nodes or []),
        "label": k.label,
        "key_prefix": k.key_prefix,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        "active": k.revoked_at is None,
    }


@dataclass
class EdgeSource:
    connection_id: str
    ingest_url: str
    key: str
    key_id: str
    created: bool


async def ensure_edge_source(
    db: AsyncSession,
    tenant_id: Any,
    gateway_id: str,
    *,
    name: str,
    created_by: Any = None,
    group: str | None = None,
    decoder: str = "values",
    mapping: dict[str, Any] | None = None,
    team_id: Any = None,
) -> EdgeSource:
    """The HTTP push source an Edge gateway sends to, made on first enrolment, and a fresh gateway key.

    Older gateway keys of this gateway on that source are revoked. Flushes, never commits.
    """
    gw = clean_device_id(gateway_id)
    src_name = f"Edge {name}"[:255]
    conn = (
        await db.execute(
            select(TelemetryConnection).where(
                TelemetryConnection.tenant_id == tenant_id,
                TelemetryConnection.transport == "http_push",
                TelemetryConnection.config["edge_gateway_id"].astext == gw,
            )
        )
    ).scalar_one_or_none()
    created = False
    if conn is None:
        taken = (
            await db.execute(
                select(TelemetryConnection.id).where(
                    TelemetryConnection.tenant_id == tenant_id,
                    TelemetryConnection.name == src_name,
                )
            )
        ).first()
        if taken is not None:
            src_name = f"{src_name} ({gw})"[:255]
        conn = TelemetryConnection(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=src_name,
            broker_url="",
            topics=[],
            raw_topics=[],
            protocol=decoder,
            enabled=True,
            shared_subscription=False,
            transport="http_push",
            config={"edge_gateway_id": gw, "subject": f"edge/{gw}"},
            secrets={},
            decoder=decoder,
            decoder_config={},
            mapping=dict(mapping or {}),
            strict=False,
            team_id=team_id,
            created_by=created_by,
        )
        db.add(conn)
        await db.flush()
        created = True
    else:
        now = datetime.now(timezone.utc)
        for old in (
            await db.execute(
                select(TelemetryDeviceKey).where(
                    TelemetryDeviceKey.connection_id == conn.id,
                    TelemetryDeviceKey.kind == "gateway",
                    TelemetryDeviceKey.device_id == gw,
                    TelemetryDeviceKey.revoked_at.is_(None),
                )
            )
        ).scalars():
            old.revoked_at = now
    k, raw = await create_key(
        db,
        conn,
        device_id=gw,
        kind="gateway",
        group=group,
        label=f"Edge gateway {name}"[:255],
        created_by=created_by,
    )
    return EdgeSource(
        connection_id=str(conn.id),
        ingest_url=f"/api/telemetry/ingest/{conn.id}",
        key=raw,
        key_id=str(k.id),
        created=created,
    )
