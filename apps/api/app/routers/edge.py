"""Edge runtime API — gateway registration + bundle deployment."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Body, Depends, HTTPException, Path as PathParam, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services import edge_collectors as EC
from app.services.edge_compiler import (
    EdgeCompileError,
    compile_agent_bundle,
    load_signing_key,
    public_key_pem,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent  # noqa: E402
from models.edge_gateway import EdgeGateway  # noqa: E402
from models.user import User  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/edge", tags=["edge"])


_signing_key_cache: rsa.RSAPrivateKey | None = None
_dev_key_in_use = False
_dev_key_warned = False

_DEV_ENVIRONMENTS = {"dev", "development", "local", "test", "testing"}
_SIGNING_ALGORITHM = "RSA-PSS-SHA256 (MGF1-SHA256, salt 32)"
_MISSING_KEY_MSG = (
    "edge bundle signing is unavailable: EDGE_SIGNING_KEY_PEM is not set. "
    "Generate a key pair (see docs/06-deployment/05-edge-runtime.md) and "
    "set secrets.edgeSigningKeyPem on the chart. Dev keys are only minted "
    "when ENVIRONMENT is dev, local or test."
)


class EdgeSigningUnavailable(RuntimeError):
    """No usable signing key and the environment forbids minting one."""


def _is_dev_environment() -> bool:
    env = os.environ.get("ENVIRONMENT", "").strip().lower()
    if env:
        return env in _DEV_ENVIRONMENTS
    return bool(settings.debug)


def _dev_key_dir() -> Path:
    explicit = os.environ.get("EDGE_SIGNING_KEY_DIR", "").strip()
    if explicit:
        return Path(explicit)
    # Same shared data mount as uploads so API replicas see one key
    upload_dir = os.environ.get("UPLOAD_DIR", "").strip()
    base = Path(upload_dir).parent if upload_dir else Path("/data")
    return base / "edge"


def _write_private(path: Path, key: rsa.RSAPrivateKey) -> None:
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    tmp = path.with_suffix(".pem.tmp")
    tmp.write_bytes(pem)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _load_or_create_dev_key(priv_path: Path) -> rsa.RSAPrivateKey:
    global _dev_key_warned
    if not priv_path.exists():
        priv_path.parent.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        # Another replica may have won the race, keep whichever landed first
        if not priv_path.exists():
            _write_private(priv_path, key)
    key = load_signing_key(priv_path.read_bytes())
    pub_path = priv_path.with_name("signing_pub.pem")
    if not pub_path.exists():
        pub_path.write_text(public_key_pem(key), encoding="utf-8")
    if not _dev_key_warned:
        _dev_key_warned = True
        logger.warning(
            "edge_dev_signing_key path=%s generated dev key, not for shared or "
            "production clusters. Set EDGE_SIGNING_KEY_PEM to pin one.",
            priv_path,
        )
    return key


def _resolve_signing_key() -> rsa.RSAPrivateKey:
    """Return the bundle signing key, never minting one outside dev."""
    global _signing_key_cache, _dev_key_in_use
    if _signing_key_cache is not None:
        return _signing_key_cache

    pem = os.environ.get("EDGE_SIGNING_KEY_PEM", "").strip()
    if pem:
        _signing_key_cache = load_signing_key(pem)
        _dev_key_in_use = False
        return _signing_key_cache

    # Operator-mounted file, valid in any environment
    key_path = os.environ.get("EDGE_SIGNING_KEY_PATH", "").strip()
    if key_path and Path(key_path).exists():
        _signing_key_cache = load_signing_key(Path(key_path).read_bytes())
        _dev_key_in_use = False
        return _signing_key_cache

    if not _is_dev_environment():
        raise EdgeSigningUnavailable(_MISSING_KEY_MSG)

    priv_path = Path(key_path) if key_path else _dev_key_dir() / "signing_priv.pem"
    _signing_key_cache = _load_or_create_dev_key(priv_path)
    _dev_key_in_use = True
    return _signing_key_cache


def _signing_key_or_503() -> rsa.RSAPrivateKey:
    try:
        return _resolve_signing_key()
    except EdgeSigningUnavailable as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(503, f"edge signing key is unusable: {e}") from e


@router.on_event("startup")
async def _signing_key_startup_check() -> None:
    if os.environ.get("EDGE_ALLOW_UNSIGNED", "").lower() == "true":
        if _is_dev_environment():
            logger.warning(
                "EDGE_ALLOW_UNSIGNED=true, gateways may load unsigned bundles"
            )
        else:
            logger.error(
                "EDGE_ALLOW_UNSIGNED=true outside dev, unsigned bundles would be "
                "accepted, unset it"
            )
    try:
        _resolve_signing_key()
    except EdgeSigningUnavailable as e:
        logger.error("edge_signing_key_missing: %s compile/sign/mint return 503", e)
    except ValueError as e:
        logger.error("edge_signing_key_unusable: %s", e)


@router.get("/signing-key")
async def signing_key() -> JSONResponse:
    """Public verify key for gateways. The private half never leaves the API."""
    sk = _signing_key_or_503()
    return success(
        {
            "public_key_pem": public_key_pem(sk),
            "algorithm": _SIGNING_ALGORITHM,
            "dev_key": _dev_key_in_use,
        }
    )


ONLINE_GRACE_S = 60
ENROLL_TTL = timedelta(hours=24)
ENROLL_PREFIX = "etk_"
MANAGE_REFUSAL = (
    "Only people who can manage telemetry sources can change edge gateways. "
    "An admin can give you that under Admin, Permissions."
)


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def _live_status(g: EdgeGateway) -> str:
    """waiting, online, offline or revoked, worked out from the last heartbeat."""
    if g.revoked_at:
        return "revoked"
    roles = list(g.roles or ["agents"])
    if "collect" in roles and not g.enrolled_at:
        if g.enroll_expires_at and g.enroll_expires_at < datetime.now(timezone.utc):
            return "expired"
        return "waiting"
    hb = int((g.settings or {}).get("heartbeat_s") or 15)
    grace = max(ONLINE_GRACE_S, 3 * hb) if g.enrolled_at else 300
    seen = g.last_seen_at
    if seen and (datetime.now(timezone.utc) - seen).total_seconds() <= grace:
        return "online"
    return "offline"


def _serialize_gateway(g: EdgeGateway, full: bool = False) -> dict[str, Any]:
    health = dict(g.health or {})
    out = {
        "id": str(g.id),
        "gateway_id": g.gateway_id,
        "name": g.name,
        "description": g.description or "",
        "endpoint_url": g.endpoint_url,
        "status": _live_status(g),
        "roles": list(g.roles or ["agents"]),
        "deployed_agents": list(g.deployed_agents or []),
        "registered_at": _iso(g.registered_at),
        "last_seen_at": _iso(g.last_seen_at),
        "enrolled_at": _iso(g.enrolled_at),
        "enroll_expires_at": _iso(g.enroll_expires_at),
        "revoked_at": _iso(g.revoked_at),
        "first_data_at": _iso(g.first_data_at),
        "version": g.version,
        "platform": g.platform,
        "hostname": g.hostname,
        "config_version": g.config_version,
        "applied_version": g.applied_version,
        "config_pending": bool(g.enrolled_at) and g.applied_version != g.config_version,
        "telemetry_connection_id": (
            str(g.telemetry_connection_id) if g.telemetry_connection_id else None
        ),
        "collector_count": len(g.collectors or []),
        "buffer": health.get("buffer") or {},
        "uplink": health.get("uplink") or {},
        "collector_health": health.get("collectors") or [],
        "uptime_s": health.get("uptime_s"),
        "problem": health.get("problem"),
    }
    if full:
        out["collectors"] = [EC.masked(c) for c in (g.collectors or [])]
        out["settings"] = {
            **{f["key"]: f["default"] for f in EC.SETTINGS_FIELDS},
            **(g.settings or {}),
        }
    return out


@router.get("/runtime/download")
async def runtime_download() -> JSONResponse:
    variants = [
        {
            "name": "python",
            "label": "Python (reference)",
            "image": "agentforge/edge-runtime:1.1.0",
            "size_mb": 80,
            "helm_chart": "infra/helm/edge-runtime",
            "helm_install": (
                "helm install abenix-edge ./infra/helm/edge-runtime "
                "-n abenix-edge "
                "--set platform.url=$PLATFORM_URL "
                "--set platform.token=$EDGE_TOKEN "
                "--set gateway.id=$GW"
            ),
            "docker_run": (
                "docker run -d --name abenix-edge "
                "-e PLATFORM_URL=... -e PLATFORM_TOKEN=... "
                "agentforge/edge-runtime:1.1.0"
            ),
            "targets": ["x86_64-linux", "arm64-linux"],
            "deps": ["python3.12+"],
            "use_when": "default — best LLM SDK ergonomics; ~80 MB pod",
        },
        {
            "name": "rust",
            "label": "Rust (single static binary)",
            "image": "agentforge/edge-runtime-rust:1.1.0",
            "size_mb": 25,
            "helm_chart": "infra/helm/edge-runtime-rust",
            "helm_install": (
                "helm install abenix-edge-rust ./infra/helm/edge-runtime-rust "
                "-n abenix-edge "
                "--set platform.url=$PLATFORM_URL "
                "--set platform.token=$EDGE_TOKEN "
                "--set gateway.id=$GW"
            ),
            "docker_run": (
                "docker run -d --name abenix-edge-rust "
                "-e PLATFORM_URL=... -e PLATFORM_TOKEN=... "
                "agentforge/edge-runtime-rust:1.1.0"
            ),
            "targets": ["x86_64-linux", "arm64-linux", "armv7-linux"],
            "deps": [],
            "use_when": (
                "rugged industrial PCs (Moxa UC-8580, Siemens RUGGEDCOM, "
                "Beckhoff CX series) — no Python interpreter on the box"
            ),
        },
        {
            "name": "c",
            "label": "C (musl static)",
            "image": "agentforge/edge-runtime-c:1.1.0",
            "size_mb": 12,
            "helm_chart": "infra/helm/edge-runtime-c",
            "helm_install": (
                "helm install abenix-edge-c ./infra/helm/edge-runtime-c "
                "-n abenix-edge "
                "--set platform.url=$PLATFORM_URL "
                "--set platform.token=$EDGE_TOKEN "
                "--set gateway.id=$GW"
            ),
            "docker_run": (
                "docker run -d --name abenix-edge-c "
                "-e PLATFORM_URL=... -e PLATFORM_TOKEN=... "
                "agentforge/edge-runtime-c:1.1.0"
            ),
            "targets": ["armv7-linux", "arm64-linux", "x86_64-linux"],
            "deps": [
                "libmosquitto",
                "openssl",
                "libcurl",
                "libmicrohttpd",
                "json-c",
            ],
            "use_when": (
                "ultra-constrained gateways (Allen-Bradley CompactLogix, "
                "Phoenix Contact PLCnext, OpenWRT routers, ARM Cortex-A7 "
                "with 256-512MB RAM)"
            ),
        },
    ]
    return success({"variants": variants})


@router.post("/tokens/mint")
async def mint_edge_token(
    body: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Mint a platform API key the edge runtime can put in PLATFORM_TOKEN.

    Returns the RAW key once (it is never retrievable again — store it in the
    edge pod's helm value or k8s secret). The matching signing pubkey is
    returned too so the operator can configure the runtime to verify
    bundles end-to-end in one step.
    """
    import hashlib
    import secrets

    from models.api_key import ApiKey

    if not await _can_manage(db, user):
        return error(MANAGE_REFUSAL, 403, error_code="FORBIDDEN")
    # Refuse before minting a token nobody can pair with a verify key
    pubkey_pem = public_key_pem(_signing_key_or_503())

    name = (body.get("name") or f"edge-{secrets.token_hex(3)}").strip()
    raw = "af_" + secrets.token_urlsafe(40)
    key = ApiKey(
        user_id=user.id,
        tenant_id=user.tenant_id,
        name=name,
        key_prefix=raw[:8],
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes={
            "allowed_actions": ["can_delegate", "execute", "read", "edge.register"]
        },
        is_active=True,
    )
    db.add(key)
    await db.commit()

    return success(
        {
            "platform_token": raw,
            "platform_token_prefix": raw[:8] + "****" + raw[-4:],
            "key_id": str(key.id),
            "signing_pubkey_pem": pubkey_pem,
            "warning": (
                "Save the platform_token now — it will not be shown again. "
                "Drop the signing_pubkey_pem at /etc/edge/signing_pub.pem (or "
                "set SIGNING_PUBKEY_PEM) so the runtime verifies bundle signatures. "
                "GET /api/edge/signing-key serves the same key."
            ),
        }
    )


@router.post("/gateways/register")
async def register_gateway(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Register an edge gateway. Idempotent on `gateway_id`."""
    gateway_id = (body.get("gateway_id") or "").strip()
    if not gateway_id:
        return error("gateway_id is required", 400)
    name = (body.get("name") or gateway_id).strip()
    endpoint_url = (body.get("endpoint_url") or "").strip() or None

    res = await db.execute(
        select(EdgeGateway).where(EdgeGateway.gateway_id == gateway_id)
    )
    existing = res.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing:
        existing.name = name or existing.name
        existing.endpoint_url = endpoint_url or existing.endpoint_url
        existing.last_seen_at = now
        existing.status = "online"
        await db.commit()
        return success({"gateway": _serialize_gateway(existing), "created": False})

    g = EdgeGateway(
        tenant_id=user.tenant_id,
        gateway_id=gateway_id,
        name=name,
        endpoint_url=endpoint_url,
        status="online",
        deployed_agents=[],
        registered_at=now,
        last_seen_at=now,
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return success({"gateway": _serialize_gateway(g), "created": True})


@router.get("/gateways")
async def list_gateways(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    res = await db.execute(
        select(EdgeGateway)
        .where(EdgeGateway.tenant_id == user.tenant_id)
        .order_by(EdgeGateway.registered_at.desc())
    )
    rows = res.scalars().all()
    return success(
        {
            "gateways": [_serialize_gateway(g) for g in rows],
            "can_manage": await _can_manage(db, user),
        }
    )


async def _publish_to_mqtt(topic: str, payload: bytes) -> bool:
    """Best-effort publish via paho. Returns False if MQTT is unreachable."""
    mqtt_url = os.environ.get("MQTT_URL", "").strip()
    if not mqtt_url:
        return False
    try:
        import paho.mqtt.publish as publish

        host = mqtt_url.replace("mqtt://", "").split(":")[0] or "localhost"
        port = 1883
        if ":" in mqtt_url.replace("mqtt://", ""):
            port = int(mqtt_url.replace("mqtt://", "").split(":")[1].split("/")[0])
        publish.single(topic, payload=payload, hostname=host, port=port)
        return True
    except Exception as e:
        logger.warning("mqtt_publish_failed topic=%s err=%s", topic, e)
        return False


async def _push_bundle_http(endpoint_url: str, slug: str, bundle: bytes) -> bool:
    if not endpoint_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{endpoint_url.rstrip('/')}/agents/{slug}/bundle",
                content=bundle,
                headers={"Content-Type": "application/x-tar"},
            )
            return 200 <= r.status_code < 300
    except Exception as e:
        logger.warning("edge_http_push_failed endpoint=%s err=%s", endpoint_url, e)
        return False


@router.post("/gateways/{gateway_pk}/deploy")
async def deploy_to_gateway(
    gateway_pk: str = PathParam(...),
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Compile + sign + push a `.agent` bundle to a gateway.

    Tries MQTT first; falls back to HTTP POST against the gateway's endpoint.
    """
    if not await _can_manage(db, user):
        return error(MANAGE_REFUSAL, 403, error_code="FORBIDDEN")
    agent_id = (body.get("agent_id") or "").strip()
    if not agent_id:
        return error("agent_id is required", 400)

    res = await db.execute(
        select(EdgeGateway).where(EdgeGateway.id == uuid.UUID(gateway_pk))
    )
    g = res.scalar_one_or_none()
    if g is None or g.tenant_id != user.tenant_id:
        raise HTTPException(404, "gateway not found")

    res2 = await db.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = res2.scalar_one_or_none()
    if agent is None or agent.tenant_id != user.tenant_id:
        raise HTTPException(404, "agent not found")

    try:
        bundle, digest = await compile_agent_bundle(
            db=db,
            agent_id=str(agent.id),
            signing_key=_signing_key_or_503(),
        )
    except EdgeCompileError as e:
        return error(str(e), 400)

    topic = f"edge.{g.gateway_id}.deploy"
    pushed = await _publish_to_mqtt(topic, bundle)
    if not pushed:
        pushed = await _push_bundle_http(g.endpoint_url or "", agent.slug, bundle)

    deployed = list(g.deployed_agents or [])
    record = {
        "slug": agent.slug,
        "agent_id": str(agent.id),
        "digest": digest,
        "deployed_at": datetime.now(timezone.utc).isoformat(),
    }
    deployed = [d for d in deployed if d.get("slug") != agent.slug] + [record]
    await db.execute(
        update(EdgeGateway)
        .where(EdgeGateway.id == g.id)
        .values(deployed_agents=deployed, last_seen_at=datetime.now(timezone.utc))
    )
    await db.commit()

    return success(
        {
            "deployed": True,
            "transport": "mqtt" if pushed and os.environ.get("MQTT_URL") else "http",
            "bundle_digest": digest,
            "bundle_bytes": len(bundle),
            "topic": topic,
            "pushed": pushed,
        }
    )


@router.get("/gateways/{gateway_pk}/agents")
async def list_gateway_agents(
    gateway_pk: str = PathParam(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Proxy to the gateway's `/agents` endpoint."""
    res = await db.execute(
        select(EdgeGateway).where(EdgeGateway.id == uuid.UUID(gateway_pk))
    )
    g = res.scalar_one_or_none()
    if g is None or g.tenant_id != user.tenant_id:
        raise HTTPException(404, "gateway not found")

    if not g.endpoint_url:
        return success({"agents": list(g.deployed_agents or []), "source": "registry"})

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{g.endpoint_url.rstrip('/')}/agents")
            r.raise_for_status()
            data = r.json()
            return success({"agents": data.get("agents", []), "source": "gateway"})
    except Exception as e:
        logger.warning("edge_proxy_failed err=%s", e)
        return success(
            {"agents": list(g.deployed_agents or []), "source": "registry-fallback"}
        )


@router.delete("/gateways/{gateway_pk}")
async def delete_gateway(
    request: Request,
    gateway_pk: str = PathParam(...),
    remove_source: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Forget a gateway and revoke its key. Its readings stay in Telemetry unless remove_source."""
    if not await _can_manage(db, user):
        return error(MANAGE_REFUSAL, 403, error_code="FORBIDDEN")
    g = await _gateway_or_404(db, user, gateway_pk)
    await _revoke_key(db, g)
    conn_id = g.telemetry_connection_id
    removed = False
    if remove_source and conn_id:
        from models.telemetry import TelemetryConnection

        c = await db.get(TelemetryConnection, conn_id)
        if c is not None and c.tenant_id == user.tenant_id:
            await db.delete(c)
            removed = True
    await _audit(
        db, user, request, "edge.gateway.removed", g, {"removed_source": removed}
    )
    await db.delete(g)
    await db.commit()
    await _telemetry_changed()
    return success(
        {"deleted": True, "gateway_id": g.gateway_id, "removed_source": removed}
    )


@router.post("/agents/{agent_id}/compile")
async def compile_agent(
    agent_id: str = PathParam(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Compile an agent into a `.agent` bundle.

    Returns the bundle as `application/x-tar`. Bundle digest is provided in
    the `X-Bundle-Digest` header; a JSON sidecar is also delivered when the
    caller passes `?format=json`.
    """
    res = await db.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = res.scalar_one_or_none()
    if agent is None or agent.tenant_id != user.tenant_id:
        raise HTTPException(404, "agent not found")

    try:
        bundle, digest = await compile_agent_bundle(
            db=db, agent_id=str(agent.id), signing_key=_signing_key_or_503()
        )
    except EdgeCompileError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)

    return Response(
        content=bundle,
        media_type="application/x-tar",
        headers={
            "X-Bundle-Digest": digest,
            "X-Bundle-Slug": agent.slug,
            "Content-Disposition": f'attachment; filename="{agent.slug}.agent"',
            "X-Sidecar-JSON": json.dumps(
                {"digest": digest, "slug": agent.slug, "bytes": len(bundle)}
            ),
        },
    )


# Collect role: gateways that read buses, PLCs and sensors and send to Telemetry


async def _can_manage(db: AsyncSession, user: User) -> bool:
    from app.telemetry import access

    return await access.has(db, user, "telemetry.manage")


async def _can_view(db: AsyncSession, user: User) -> bool:
    from app.telemetry import access

    return await access.has(db, user, "telemetry.view")


async def _gateway_or_404(db: AsyncSession, user: User, gateway_pk: str) -> EdgeGateway:
    try:
        pk = uuid.UUID(gateway_pk)
    except ValueError:
        raise HTTPException(404, "gateway not found")
    g = await db.get(EdgeGateway, pk)
    if g is None or g.tenant_id != user.tenant_id:
        raise HTTPException(404, "gateway not found")
    return g


async def _audit(
    db: AsyncSession,
    user: User | None,
    request: Request | None,
    action: str,
    g: EdgeGateway,
    extra: dict[str, Any] | None = None,
) -> None:
    from app.core.audit import log_action

    uid = user.id if user is not None else g.created_by
    if uid is None:
        return
    try:
        await log_action(
            db,
            g.tenant_id,
            uid,
            action,
            {"name": g.name, "gateway_id": g.gateway_id, **(extra or {})},
            request,
            resource_type="edge_gateway",
            resource_id=str(g.id),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("edge_audit_failed action=%s err=%s", action, e)


async def _telemetry_changed() -> None:
    try:
        from app.routers.telemetry import _changed

        await _changed()
    except Exception as e:  # noqa: BLE001
        logger.warning("telemetry_changed_publish_failed err=%s", e)


async def _revoke_key(db: AsyncSession, g: EdgeGateway) -> None:
    if not g.key_id:
        return
    from models.telemetry import TelemetryDeviceKey

    k = await db.get(TelemetryDeviceKey, g.key_id)
    if k is not None and k.revoked_at is None:
        k.revoked_at = datetime.now(timezone.utc)


def _check_collectors(
    items: Any, old: list[dict[str, Any]] | None, tenant_id: Any
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    if not isinstance(items, list):
        return [], {"_": {"collectors": "collectors must be a list"}}
    if len(items) > EC.MAX_COLLECTORS:
        return [], {
            "_": {
                "collectors": f"A gateway runs at most {EC.MAX_COLLECTORS} collectors"
            }
        }
    prev = {str(c.get("id")): c for c in (old or [])}
    out: list[dict[str, Any]] = []
    problems: dict[str, dict[str, str]] = {}
    ids: set[str] = set()
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            problems[str(i)] = {"_": "Each collector is an object"}
            continue
        clean, p = EC.validate(raw)
        if clean["id"] in ids:
            clean["id"] = EC.new_id(clean.get("name") or clean["type"])
        ids.add(clean["id"])
        if p:
            problems[str(i)] = p
            continue
        out.append(EC.merge_secrets(clean, prev.get(clean["id"]), tenant_id))
    return out, problems


def _first_problem(problems: dict[str, dict[str, str]]) -> str:
    for p in problems.values():
        for v in p.values():
            return v
    return "Check the collector settings"


def _new_gateway_id(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "gateway").lower()).strip("-")[:40]
    return f"{base or 'gateway'}-{secrets.token_hex(2)}"


def _config_for(g: EdgeGateway) -> dict[str, Any]:
    st = {**{f["key"]: f["default"] for f in EC.SETTINGS_FIELDS}, **(g.settings or {})}
    return {
        "roles": list(g.roles or ["collect"]),
        "collectors": [EC.for_gateway(c, g.tenant_id) for c in (g.collectors or [])],
        "buffer": {"max_mb": st["buffer_max_mb"], "max_age_h": st["buffer_max_age_h"]},
        "uplink": {"gzip": bool(st["gzip"])},
        "heartbeat_s": st["heartbeat_s"],
        "self_metrics_s": int(st.get("self_metrics_s") or 10),
        "gateway_asset": {"group": st.get("gateway_group") or "edge"},
    }


@router.get("/collectors/catalog")
async def collector_catalog(user: User = Depends(get_current_user)) -> JSONResponse:
    """What a gateway can collect from, with every field, its help and an example."""
    return success(EC.catalog())


@router.post("/collectors/validate")
async def validate_collector(
    body: dict = Body(...), user: User = Depends(get_current_user)
) -> JSONResponse:
    """Checks one collector the way saving would, so the form can show problems as you type."""
    clean, problems = EC.validate(body.get("collector") or body)
    return success(
        {"ok": not problems, "problems": problems, "collector": EC.masked(clean)}
    )


@router.post("/dbc/check")
async def check_dbc(
    body: dict = Body(...), user: User = Depends(get_current_user)
) -> JSONResponse:
    text = str(body.get("dbc") or "")
    if not text.strip():
        return error("Pick a DBC file to check.", 422, error_code="VALIDATION_ERROR")
    if len(text) > EC.MAX_DBC:
        return error(
            "The DBC file is over 2 MB. Upload the file for this bus only.",
            413,
            error_code="PAYLOAD_TOO_LARGE",
        )
    problem = EC.dbc_problem(text)
    if problem:
        return success({"ok": False, "error": problem, "messages": [], "count": 0})
    return success({"ok": True, "error": None, **EC.dbc_summary(text)})


@router.post("/gateways")
async def create_gateway(
    request: Request,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """A gateway that collects, waiting for its first boot. The install command comes from /install."""
    if not await _can_manage(db, user):
        return error(MANAGE_REFUSAL, 403, error_code="FORBIDDEN")
    name = str(body.get("name") or "").strip()
    if not name or len(name) > 80:
        return error(
            "Give the gateway a name under 80 characters, such as Yard gateway or Truck 12.",
            422,
            error_code="VALIDATION_ERROR",
            details={"field": "name"},
        )
    roles = [
        r for r in (body.get("roles") or ["collect"]) if r in ("collect", "agents")
    ]
    if not roles:
        return error(
            "Pick what the gateway does: collect, run agents, or both.",
            422,
            error_code="VALIDATION_ERROR",
        )
    collectors, problems = _check_collectors(
        body.get("collectors") or [], None, user.tenant_id
    )
    if problems:
        return error(
            _first_problem(problems),
            422,
            error_code="VALIDATION_ERROR",
            details={"collectors": problems},
        )
    settings_in, sp = EC.clean_settings(body.get("settings") or {})
    if sp:
        return error(
            next(iter(sp.values())),
            422,
            error_code="VALIDATION_ERROR",
            details={"settings": sp},
        )
    now = datetime.now(timezone.utc)
    g = EdgeGateway(
        tenant_id=user.tenant_id,
        gateway_id=_new_gateway_id(name),
        name=name,
        description=str(body.get("description") or "")[:500],
        status="waiting",
        roles=roles,
        collectors=collectors,
        settings=settings_in,
        health={},
        deployed_agents=[],
        config_version=1,
        applied_version=0,
        registered_at=now,
        last_seen_at=now,
        created_by=user.id,
    )
    db.add(g)
    await db.flush()
    await _audit(
        db, user, request, "edge.gateway.created", g, {"collectors": len(collectors)}
    )
    await db.commit()
    await db.refresh(g)
    return success(_serialize_gateway(g, full=True), status_code=201)


@router.get("/gateways/{gateway_pk}")
async def get_gateway(
    gateway_pk: str = PathParam(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    if not await _can_view(db, user):
        return error(
            "You do not have access to edge gateways. Ask an admin for telemetry access.",
            403,
            error_code="FORBIDDEN",
        )
    g = await _gateway_or_404(db, user, gateway_pk)
    out = _serialize_gateway(g, full=True)
    out["assets"] = await _assets_of(g)
    out["can_manage"] = await _can_manage(db, user)
    return success(out)


async def _assets_of(g: EdgeGateway) -> list[dict[str, Any]]:
    """The assets this gateway's source has written, from the live device index."""
    if not g.telemetry_connection_id:
        return []
    try:
        from app.routers.telemetry import redis as tel_redis
        from app.telemetry import reads

        rows = await reads.all_devices(tel_redis(), g.tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("edge_assets_failed err=%s", e)
        return []
    cid = str(g.telemetry_connection_id)
    return [r for r in rows if str(r.get("connection_id") or "") == cid][:200]


@router.patch("/gateways/{gateway_pk}")
async def update_gateway(
    request: Request,
    gateway_pk: str = PathParam(...),
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Change the name, collectors or settings. The gateway picks changes up on its next heartbeat."""
    if not await _can_manage(db, user):
        return error(MANAGE_REFUSAL, 403, error_code="FORBIDDEN")
    g = await _gateway_or_404(db, user, gateway_pk)
    changed = False
    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name or len(name) > 80:
            return error(
                "Give the gateway a name under 80 characters.",
                422,
                error_code="VALIDATION_ERROR",
            )
        g.name = name
    if "description" in body:
        g.description = str(body.get("description") or "")[:500]
    if "roles" in body:
        roles = [r for r in (body.get("roles") or []) if r in ("collect", "agents")]
        if not roles:
            return error(
                "Pick what the gateway does: collect, run agents, or both.",
                422,
                error_code="VALIDATION_ERROR",
            )
        g.roles = roles
        changed = True
    if "collectors" in body:
        collectors, problems = _check_collectors(
            body["collectors"], list(g.collectors or []), user.tenant_id
        )
        if problems:
            return error(
                _first_problem(problems),
                422,
                error_code="VALIDATION_ERROR",
                details={"collectors": problems},
            )
        g.collectors = collectors
        changed = True
    if "settings" in body:
        st, sp = EC.clean_settings(
            {**(g.settings or {}), **(body.get("settings") or {})}
        )
        if sp:
            return error(
                next(iter(sp.values())),
                422,
                error_code="VALIDATION_ERROR",
                details={"settings": sp},
            )
        g.settings = st
        changed = True
    if changed:
        g.config_version = (g.config_version or 0) + 1
    await _audit(
        db,
        user,
        request,
        "edge.gateway.changed",
        g,
        {"config_version": g.config_version},
    )
    await db.commit()
    await db.refresh(g)
    return success(_serialize_gateway(g, full=True))


@router.post("/gateways/{gateway_pk}/install")
async def install_command(
    request: Request,
    gateway_pk: str = PathParam(...),
    body: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """A fresh one-time enrolment token and the commands that use it. An older unused token stops working."""
    if not await _can_manage(db, user):
        return error(MANAGE_REFUSAL, 403, error_code="FORBIDDEN")
    g = await _gateway_or_404(db, user, gateway_pk)
    urls = EC.platform_urls()
    url = str(body.get("platform_url") or (urls[0]["url"] if urls else ""))
    url = url.strip().rstrip("/")
    problem = EC.url_problem(url)
    if problem:
        return error(
            problem,
            422,
            error_code="VALIDATION_ERROR",
            details={"field": "platform_url"},
        )
    token = ENROLL_PREFIX + secrets.token_urlsafe(32)
    g.enroll_token_hash = hashlib.sha256(token.encode()).hexdigest()
    g.enroll_expires_at = datetime.now(timezone.utc) + ENROLL_TTL
    reenrol = bool(g.enrolled_at or g.revoked_at)
    if reenrol:
        # the box enrols again with this token, its old key stops at once
        await _revoke_key(db, g)
        g.enrolled_at = None
        g.revoked_at = None
        g.status = "waiting"
    await _audit(
        db, user, request, "edge.gateway.install_token", g, {"reenrol": reenrol}
    )
    await db.commit()
    await db.refresh(g)
    cmds = EC.install(g.gateway_id, url, token, list(g.collectors or []))
    return success(
        {
            "gateway": _serialize_gateway(g, full=True),
            "enroll_token": token,
            "expires_at": _iso(g.enroll_expires_at),
            "platform_urls": urls,
            **cmds,
        }
    )


@router.get("/install/urls")
async def install_urls(user: User = Depends(get_current_user)) -> JSONResponse:
    """Addresses a gateway might reach Abenix on, to pre-fill the install step."""
    return success({"platform_urls": EC.platform_urls(), "image": EC.image()})


@router.post("/gateways/{gateway_pk}/revoke")
async def revoke_gateway(
    request: Request,
    gateway_pk: str = PathParam(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Stops the gateway at once: its key is refused for sending and for heartbeats."""
    if not await _can_manage(db, user):
        return error(MANAGE_REFUSAL, 403, error_code="FORBIDDEN")
    g = await _gateway_or_404(db, user, gateway_pk)
    await _revoke_key(db, g)
    g.revoked_at = datetime.now(timezone.utc)
    g.enroll_token_hash = None
    g.status = "revoked"
    await _audit(db, user, request, "edge.gateway.revoked", g)
    await db.commit()
    await db.refresh(g)
    return success(_serialize_gateway(g, full=True))


def _bearer(request: Request) -> str:
    auth = (request.headers.get("authorization") or "").strip()
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


@router.post("/enroll")
async def enroll(
    request: Request,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """A gateway's first call, with the one-time token from its install command."""
    token = str(body.get("token") or "").strip()
    if not token.startswith(ENROLL_PREFIX):
        return error(
            "This is not an enrolment token. Copy the install command from the Edge page again.",
            401,
            error_code="UNAUTHORIZED",
        )
    digest = hashlib.sha256(token.encode()).hexdigest()
    g = (
        await db.execute(
            select(EdgeGateway).where(EdgeGateway.enroll_token_hash == digest)
        )
    ).scalar_one_or_none()
    if g is None:
        return error(
            "This enrolment token is not valid. It was used already or replaced by a newer "
            "install command. Make a new one on the Edge page.",
            401,
            error_code="UNAUTHORIZED",
        )
    if g.enroll_expires_at and g.enroll_expires_at < datetime.now(timezone.utc):
        return error(
            "This enrolment token expired. Make a new install command on the Edge page.",
            410,
            error_code="EXPIRED",
        )
    from app.telemetry.sources import ensure_edge_source

    src = await ensure_edge_source(
        db,
        g.tenant_id,
        g.gateway_id,
        name=g.name,
        created_by=g.created_by,
        group=None,
        decoder="values",
    )
    now = datetime.now(timezone.utc)
    g.telemetry_connection_id = uuid.UUID(src.connection_id)
    g.key_id = uuid.UUID(src.key_id)
    g.enrolled_at = now
    g.enroll_token_hash = None
    g.enroll_expires_at = None
    g.revoked_at = None
    g.status = "online"
    g.last_seen_at = now
    g.hostname = str(body.get("hostname") or "")[:255] or None
    g.platform = str(body.get("platform") or "")[:128] or None
    g.version = str(body.get("version") or "")[:64] or None
    g.applied_version = 0
    await _audit(
        db,
        None,
        request,
        "edge.gateway.enrolled",
        g,
        {"hostname": g.hostname, "source_created": src.created},
    )
    await db.commit()
    await _telemetry_changed()
    pubkey = ""
    if "agents" in (g.roles or []):
        try:
            pubkey = public_key_pem(_resolve_signing_key())
        except Exception:  # noqa: BLE001
            pubkey = ""
    return success(
        {
            "id": str(g.id),
            "gateway_id": g.gateway_id,
            "name": g.name,
            "key": src.key,
            "connection_id": src.connection_id,
            "ingest_url": src.ingest_url,
            "config": _config_for(g),
            "config_version": g.config_version,
            "signing_pubkey_pem": pubkey,
        }
    )


async def _gateway_for_key(
    db: AsyncSession, raw: str
) -> tuple[EdgeGateway | None, str | None]:
    from models.telemetry import TelemetryDeviceKey

    if not raw:
        return None, "Send the gateway key as Authorization: Bearer tgk_..."
    k = (
        await db.execute(
            select(TelemetryDeviceKey).where(
                TelemetryDeviceKey.key_hash == hashlib.sha256(raw.encode()).hexdigest()
            )
        )
    ).scalar_one_or_none()
    if k is None or k.kind != "gateway":
        return None, (
            "Abenix does not know this gateway key. Enrol the gateway again from the Edge page."
        )
    g = (
        await db.execute(
            select(EdgeGateway).where(
                EdgeGateway.tenant_id == k.tenant_id,
                EdgeGateway.gateway_id == k.device_id,
            )
        )
    ).scalar_one_or_none()
    if g is None:
        return None, (
            "This gateway was removed in Abenix. Add it again on the Edge page to bring it back."
        )
    if g.revoked_at is not None:
        return None, (
            "This gateway was revoked in Abenix. Re-enrol it from the Edge page to bring it back."
        )
    if k.revoked_at is not None or (g.key_id and g.key_id != k.id):
        return None, (
            "This gateway's key was revoked or replaced by a newer enrolment. "
            "Re-enrol it from the Edge page."
        )
    return g, None


def _trim(v: Any, depth: int = 0) -> Any:
    if depth > 6:
        return None
    if isinstance(v, str):
        return v[:500]
    if isinstance(v, list):
        return [_trim(x, depth + 1) for x in v[:64]]
    if isinstance(v, dict):
        return {str(k)[:64]: _trim(x, depth + 1) for k, x in list(v.items())[:64]}
    return v


@router.post("/heartbeat")
async def heartbeat(
    request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    """Health in, config out. Called by an enrolled gateway every few seconds with its key."""
    raw = await request.body()
    if len(raw) > 256 * 1024:
        return error(
            "The heartbeat is over 256 KB.", 413, error_code="PAYLOAD_TOO_LARGE"
        )
    g, why = await _gateway_for_key(db, _bearer(request))
    if g is None:
        return error(why or "Unknown gateway", 401, error_code="UNAUTHORIZED")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return error("The heartbeat is not JSON.", 422, error_code="VALIDATION_ERROR")
    now = datetime.now(timezone.utc)
    health = {
        k: _trim(body.get(k))
        for k in ("buffer", "uplink", "collectors", "uptime_s", "problem", "python")
    }
    health["received_at"] = now.isoformat()
    g.health = health
    g.last_seen_at = now
    g.status = "online"
    g.version = str(body.get("version") or g.version or "")[:64] or None
    g.platform = str(body.get("platform") or g.platform or "")[:128] or None
    g.hostname = str(body.get("hostname") or g.hostname or "")[:255] or None
    if body.get("endpoint_url"):
        g.endpoint_url = str(body["endpoint_url"])[:500]
    try:
        g.applied_version = int(body.get("applied_version") or 0)
    except (TypeError, ValueError):
        pass
    sent = int((health.get("buffer") or {}).get("sent") or 0)
    if g.first_data_at is None and sent > 0 and await _assets_of(g):
        g.first_data_at = now
    await db.commit()
    out: dict[str, Any] = {
        "config_version": g.config_version,
        "heartbeat_s": int((g.settings or {}).get("heartbeat_s") or 15),
    }
    if g.applied_version != g.config_version:
        out["config"] = _config_for(g)
    return success(out)
