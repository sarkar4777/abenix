"""Compile an agent into a signed `.agent` bundle for edge deployment."""

from __future__ import annotations

import hashlib
import io
import logging
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent  # noqa: E402

logger = logging.getLogger(__name__)


EDGE_SAFE_TOOLS: set[str] = {
    "mqtt_publish",
    "mqtt_subscribe",
    "current_time",
    "windowed_state",
    "connector_call",
    "code_executor",
}

FORBIDDEN_TOOLS: set[str] = {
    "knowledge_search",
    "kb_query",
    "human_approval",
    "approval_gate",
    "agent_step",
}


class EdgeCompileError(ValueError):
    """Raised when an agent cannot be compiled for edge."""


def _tools_from_config(cfg: dict[str, Any]) -> list[str]:
    tools = cfg.get("tools") or []
    if isinstance(tools, list):
        return [str(t) for t in tools]
    return []


def _validate_tools(tools: list[str]) -> None:
    bad: list[str] = []
    for t in tools:
        if t.startswith("atlas_") or t.startswith("mcp_") or t.startswith("pipeline_"):
            bad.append(t)
            continue
        if t in FORBIDDEN_TOOLS:
            bad.append(t)
            continue
        if t not in EDGE_SAFE_TOOLS:
            bad.append(t)
    if bad:
        raise EdgeCompileError(f"agent uses non-edge-safe tools: {sorted(set(bad))}")


def _manifest_from_agent(agent: Agent) -> dict[str, Any]:
    cfg = agent.model_config_ or {}
    tools = _tools_from_config(cfg)
    _validate_tools(tools)

    edge_cfg = cfg.get("edge_constraints") or {}
    max_payload = int(edge_cfg.get("max_payload_bytes", 65536))
    max_runtime = int(edge_cfg.get("max_runtime_seconds", 30))
    mqtt_sub = list(edge_cfg.get("mqtt_subscribe") or [])
    mqtt_pub = list(edge_cfg.get("mqtt_publish") or [])

    return {
        "name": agent.name,
        "slug": agent.slug,
        # Signed with the rest of the tar, so a gateway can pin itself to one tenant
        "tenant_id": str(agent.tenant_id) if agent.tenant_id else "",
        "version": agent.version or "0.1.0",
        "model": cfg.get("model") or "claude-sonnet-4-5-20250929",
        "temperature": float(cfg.get("temperature", 0.7)),
        "max_iterations": int(cfg.get("max_iterations", 10)),
        "max_tokens": int(cfg.get("max_tokens", 4096)),
        "tools": tools,
        "edge_constraints": {
            "max_payload_bytes": max_payload,
            "max_runtime_seconds": max_runtime,
            "mqtt_subscribe": mqtt_sub,
            "mqtt_publish": mqtt_pub,
        },
        "description": agent.description or "",
        "system_prompt_path": "system_prompt.md",
    }


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mtime: int) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = mtime
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def _build_unsigned_tar(manifest: dict[str, Any], system_prompt: str) -> bytes:
    buf = io.BytesIO()
    mtime = int(time.time())
    with tarfile.open(fileobj=buf, mode="w") as tar:
        manifest_bytes = yaml.safe_dump(manifest, sort_keys=True).encode("utf-8")
        _add_bytes(tar, "agent.yaml", manifest_bytes, mtime)
        _add_bytes(tar, "system_prompt.md", system_prompt.encode("utf-8"), mtime)
    return buf.getvalue()


def _sign(payload: bytes, signing_key: rsa.RSAPrivateKey) -> bytes:
    return signing_key.sign(
        payload,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )


def _append_signature(tar_bytes: bytes, signature: bytes) -> bytes:
    buf = io.BytesIO(tar_bytes)
    out = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="r") as src:
        with tarfile.open(fileobj=out, mode="w") as dst:
            for member in src.getmembers():
                f = src.extractfile(member)
                data = f.read() if f else b""
                info = tarfile.TarInfo(name=member.name)
                info.size = len(data)
                info.mtime = member.mtime
                info.mode = member.mode or 0o644
                dst.addfile(info, io.BytesIO(data))
            sig_info = tarfile.TarInfo(name="signature.sig")
            sig_info.size = len(signature)
            sig_info.mtime = int(time.time())
            sig_info.mode = 0o644
            dst.addfile(sig_info, io.BytesIO(signature))
    return out.getvalue()


_TAR_BLOCK = 512


def signature_span(bundle: bytes) -> tuple[int, int, int, int] | None:
    """(header_start, entry_end, data_start, size) of signature.sig, or None."""
    off = 0
    while off + _TAR_BLOCK <= len(bundle):
        header = bundle[off : off + _TAR_BLOCK]
        if not any(header):
            return None
        name = header[:100].split(b"\0", 1)[0].decode("utf-8", "replace")
        raw_size = header[124:136].replace(b"\0", b" ").strip() or b"0"
        size = int(raw_size, 8)
        end = off + _TAR_BLOCK + -(-size // _TAR_BLOCK) * _TAR_BLOCK
        if name == "signature.sig":
            return off, end, off + _TAR_BLOCK, size
        off = end
    return None


def strip_signature(bundle: bytes) -> bytes:
    """The bundle bytes with the signature.sig entry cut out, which is what gets signed."""
    span = signature_span(bundle)
    if span is None:
        return bundle
    start, end, _, _ = span
    return bundle[:start] + bundle[end:]


def sign_bundle(unsigned: bytes, signing_key: rsa.RSAPrivateKey) -> bytes:
    """Append signature.sig, signing the final bytes minus that entry, the view every gateway verifies."""
    placeholder = bytes(signing_key.key_size // 8)
    framed = _append_signature(unsigned, placeholder)
    span = signature_span(framed)
    if span is None:
        raise EdgeCompileError("signature entry missing from bundle")
    _, _, data_start, size = span
    signature = _sign(strip_signature(framed), signing_key)
    if len(signature) != size:
        raise EdgeCompileError("signature length does not match the key size")
    return framed[:data_start] + signature + framed[data_start + size :]


def load_signing_key(pem: str | bytes) -> rsa.RSAPrivateKey:
    """Load a PEM-encoded RSA private key for signing bundles."""
    if isinstance(pem, str):
        pem = pem.encode("utf-8")
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise EdgeCompileError("signing key must be an RSA private key")
    return key


def public_key_pem(signing_key: rsa.RSAPrivateKey) -> str:
    """PEM (SubjectPublicKeyInfo) of the verify key gateways need."""
    return (
        signing_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )


async def compile_agent_bundle(
    db: AsyncSession,
    agent_id: str,
    signing_key: rsa.RSAPrivateKey,
) -> tuple[bytes, str]:
    """Compile + sign an agent into a `.agent` bundle.

    Returns (bundle_bytes, sha256_hex_of_full_bundle).
    """
    res = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = res.scalar_one_or_none()
    if agent is None:
        raise EdgeCompileError(f"agent {agent_id} not found")

    cfg = agent.model_config_ or {}
    if not cfg.get("edge_compatible"):
        raise EdgeCompileError(
            "agent is not marked edge_compatible — set in builder Advanced tab"
        )

    manifest = _manifest_from_agent(agent)
    system_prompt = agent.system_prompt or ""

    unsigned = _build_unsigned_tar(manifest, system_prompt)
    bundle = sign_bundle(unsigned, signing_key)
    digest = hashlib.sha256(bundle).hexdigest()

    logger.info(
        "edge_bundle_compiled agent=%s slug=%s digest=%s bytes=%d",
        agent_id,
        agent.slug,
        digest,
        len(bundle),
    )
    return bundle, digest
