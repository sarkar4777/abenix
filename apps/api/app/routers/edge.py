"""Edge runtime API — gateway registration + bundle deployment."""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Body, Depends, HTTPException, Path as PathParam
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
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


def _serialize_gateway(g: EdgeGateway) -> dict[str, Any]:
    return {
        "id": str(g.id),
        "gateway_id": g.gateway_id,
        "name": g.name,
        "endpoint_url": g.endpoint_url,
        "status": g.status,
        "deployed_agents": list(g.deployed_agents or []),
        "registered_at": g.registered_at.isoformat() if g.registered_at else None,
        "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
    }


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
    return success({"gateways": [_serialize_gateway(g) for g in rows]})


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
    gateway_pk: str = PathParam(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Forget a gateway. The edge runtime re-registers on its next start."""
    try:
        pk = uuid.UUID(gateway_pk)
    except ValueError:
        raise HTTPException(404, "gateway not found")
    res = await db.execute(select(EdgeGateway).where(EdgeGateway.id == pk))
    g = res.scalar_one_or_none()
    if g is None or g.tenant_id != user.tenant_id:
        raise HTTPException(404, "gateway not found")
    await db.delete(g)
    await db.commit()
    return success({"deleted": True, "gateway_id": g.gateway_id})


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
