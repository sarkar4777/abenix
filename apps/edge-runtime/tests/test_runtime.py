"""Smoke test — boot runtime in-process, push a sample bundle, execute."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tarfile
import time
from pathlib import Path

import httpx
import pytest
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime as edge_runtime  # noqa: E402


def _make_bundle(slug: str, key: rsa.RSAPrivateKey) -> bytes:
    manifest = {
        "name": "Smoke Agent",
        "slug": slug,
        "version": "0.1.0",
        "model": "claude-sonnet-4-5-20250929",
        "temperature": 0.2,
        "max_iterations": 3,
        "max_tokens": 256,
        "tools": ["current_time", "mqtt_publish"],
        "edge_constraints": {
            "max_payload_bytes": 4096,
            "max_runtime_seconds": 5,
            "mqtt_subscribe": [],
            "mqtt_publish": ["alerts.smoke"],
        },
    }
    inner = io.BytesIO()
    mtime = int(time.time())
    with tarfile.open(fileobj=inner, mode="w") as tar:
        for name, data in [
            ("agent.yaml", yaml.safe_dump(manifest, sort_keys=True).encode()),
            ("system_prompt.md", b"You are a smoke-test agent."),
        ]:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = mtime
            tar.addfile(info, io.BytesIO(data))
    raw = inner.getvalue()
    sig = key.sign(
        raw,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    out = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as src:
        with tarfile.open(fileobj=out, mode="w") as dst:
            for m in src.getmembers():
                f = src.extractfile(m)
                d = f.read() if f else b""
                info = tarfile.TarInfo(name=m.name)
                info.size = len(d)
                info.mtime = m.mtime
                dst.addfile(info, io.BytesIO(d))
            sig_info = tarfile.TarInfo(name="signature.sig")
            sig_info.size = len(sig)
            sig_info.mtime = mtime
            dst.addfile(sig_info, io.BytesIO(sig))
    return out.getvalue()


@pytest.mark.asyncio
async def test_runtime_boots_loads_executes(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(pub_pem)

    os.environ["GATEWAY_ID"] = "smoke-001"
    os.environ["BUNDLE_DIR"] = str(tmp_path / "agents")
    os.environ["SIGNING_PUBKEY_PATH"] = str(pub_path)
    os.environ["MQTT_URL"] = ""
    os.environ["PLATFORM_TOKEN"] = ""
    os.environ.pop("ANTHROPIC_API_KEY", None)

    cfg = edge_runtime.Config()
    registry = edge_runtime.Registry(cfg)

    server_task = asyncio.create_task(edge_runtime.http_server(cfg, registry, 8088))
    await asyncio.sleep(0.3)

    bundle = _make_bundle("smoke-agent", key)

    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get("http://127.0.0.1:8088/health")
        assert r.status_code == 200
        assert r.json()["agents"] == 0

        r = await client.post(
            "http://127.0.0.1:8088/agents/smoke-agent/bundle",
            content=bundle,
            headers={"Content-Type": "application/x-tar"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["loaded"]["slug"] == "smoke-agent"

        r = await client.get("http://127.0.0.1:8088/agents")
        assert r.status_code == 200
        agents = r.json()["agents"]
        assert any(a["slug"] == "smoke-agent" for a in agents)

        r = await client.post(
            "http://127.0.0.1:8088/agents/smoke-agent/execute",
            json={"message": "hi"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["slug"] == "smoke-agent"
        assert "result" in body
        assert isinstance(body["duration_ms"], int)

    server_task.cancel()
    try:
        await server_task
    except (asyncio.CancelledError, Exception):
        pass


def test_invalid_signature_rejected(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    bundle = _make_bundle("bad-agent", key)
    pub_pem = other.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(pub_pem)

    os.environ["BUNDLE_DIR"] = str(tmp_path / "a2")
    os.environ["SIGNING_PUBKEY_PATH"] = str(pub_path)
    cfg = edge_runtime.Config()
    registry = edge_runtime.Registry(cfg)
    with pytest.raises(edge_runtime.BundleError):
        registry.install_bundle(bundle)
