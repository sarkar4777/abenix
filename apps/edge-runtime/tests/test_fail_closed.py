"""Fail-closed loading: unsigned, unverifiable, tampered and foreign-tenant bundles."""

from __future__ import annotations

import io
import logging
import sys
import tarfile
import time
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime as edge_runtime  # noqa: E402


def _manifest(slug: str, tenant_id: str | None) -> dict:
    m = {
        "name": "Fail Closed Agent",
        "slug": slug,
        "version": "0.1.0",
        "model": "claude-sonnet-4-5-20250929",
        "temperature": 0.2,
        "max_iterations": 3,
        "max_tokens": 256,
        "tools": ["current_time"],
        "edge_constraints": {
            "max_payload_bytes": 4096,
            "max_runtime_seconds": 5,
            "mqtt_subscribe": [],
            "mqtt_publish": [],
        },
    }
    if tenant_id is not None:
        m["tenant_id"] = tenant_id
    return m


def _tar(members: list[tuple[str, bytes]]) -> bytes:
    out = io.BytesIO()
    mtime = int(time.time())
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = mtime
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _make_bundle(
    slug: str,
    key: rsa.RSAPrivateKey | None,
    tenant_id: str | None = None,
    prompt: bytes = b"You are a test agent.",
) -> bytes:
    members = [
        (
            "agent.yaml",
            yaml.safe_dump(_manifest(slug, tenant_id), sort_keys=True).encode(),
        ),
        ("system_prompt.md", prompt),
    ]
    raw = _tar(members)
    if key is None:
        return raw
    sig = key.sign(
        raw,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    return _tar(members + [("signature.sig", sig)])


def _pub_pem(key: rsa.RSAPrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


@pytest.fixture
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("BUNDLE_DIR", str(tmp_path / "agents"))
    monkeypatch.setenv("SIGNING_PUBKEY_PATH", str(tmp_path / "missing_pub.pem"))
    monkeypatch.delenv("SIGNING_PUBKEY_PEM", raising=False)
    monkeypatch.delenv("EDGE_ALLOW_UNSIGNED", raising=False)
    monkeypatch.delenv("TENANT_ID", raising=False)
    return monkeypatch


def test_unsigned_rejected_by_default(env, key):
    env.setenv("SIGNING_PUBKEY_PEM", _pub_pem(key))
    registry = edge_runtime.Registry(edge_runtime.Config())
    with pytest.raises(edge_runtime.BundleError, match="EDGE_ALLOW_UNSIGNED"):
        registry.install_bundle(_make_bundle("unsigned", None))
    assert registry.list() == []


def test_missing_pubkey_rejects_signed_bundle(env, key):
    registry = edge_runtime.Registry(edge_runtime.Config())
    with pytest.raises(edge_runtime.BundleError, match="no signing public key"):
        registry.install_bundle(_make_bundle("signed", key))


def test_missing_pubkey_is_a_startup_error(env):
    with pytest.raises(SystemExit) as ei:
        edge_runtime.check_startup(edge_runtime.Config())
    msg = str(ei.value)
    assert "SIGNING_PUBKEY_PEM" in msg
    assert "/api/edge/signing-key" in msg
    assert "EDGE_ALLOW_UNSIGNED" in msg


def test_pubkey_present_starts_quietly(env, key, caplog):
    env.setenv("SIGNING_PUBKEY_PEM", _pub_pem(key))
    with caplog.at_level(logging.WARNING, logger="edge-runtime"):
        edge_runtime.check_startup(edge_runtime.Config())
    assert "EDGE_ALLOW_UNSIGNED" not in caplog.text


def test_allow_unsigned_accepts_with_warning(env, caplog):
    env.setenv("EDGE_ALLOW_UNSIGNED", "true")
    cfg = edge_runtime.Config()
    with caplog.at_level(logging.WARNING, logger="edge-runtime"):
        edge_runtime.check_startup(cfg)
        registry = edge_runtime.Registry(cfg)
        agent = registry.install_bundle(_make_bundle("dev-agent", None))
    assert agent.slug == "dev-agent"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("EDGE_ALLOW_UNSIGNED=true" in r.getMessage() for r in warnings)
    assert any("UNSIGNED" in r.getMessage() for r in warnings)


def test_allow_unsigned_needs_literal_true(env):
    env.setenv("EDGE_ALLOW_UNSIGNED", "1")
    assert edge_runtime.Config().allow_unsigned is False
    env.setenv("EDGE_ALLOW_UNSIGNED", "yes")
    assert edge_runtime.Config().allow_unsigned is False
    env.setenv("EDGE_ALLOW_UNSIGNED", "TRUE")
    assert edge_runtime.Config().allow_unsigned is True


def test_allow_unsigned_still_rejects_bad_signature(env, key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    env.setenv("EDGE_ALLOW_UNSIGNED", "true")
    env.setenv("SIGNING_PUBKEY_PEM", _pub_pem(key))
    registry = edge_runtime.Registry(edge_runtime.Config())
    with pytest.raises(edge_runtime.BundleError, match="bundle_signature_invalid"):
        registry.install_bundle(_make_bundle("tampered", other))


def test_bad_signature_keeps_previous_bundle(env, key, caplog):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    env.setenv("SIGNING_PUBKEY_PEM", _pub_pem(key))
    registry = edge_runtime.Registry(edge_runtime.Config())

    good = registry.install_bundle(_make_bundle("pump", key, prompt=b"v1"))
    assert registry.get("pump").digest == good.digest

    with caplog.at_level(logging.ERROR, logger="edge-runtime"):
        with pytest.raises(edge_runtime.BundleError):
            registry.install_bundle(_make_bundle("pump", other, prompt=b"v2"))

    still = registry.get("pump")
    assert still is not None
    assert still.digest == good.digest
    assert still.system_prompt == "v1"
    assert (registry.cfg.bundle_dir / "pump" / "system_prompt.md").read_text() == "v1"
    assert any("bundle_rejected" in r.getMessage() for r in caplog.records)


def test_tenant_mismatch_rejected(env, key, caplog):
    env.setenv("SIGNING_PUBKEY_PEM", _pub_pem(key))
    env.setenv("TENANT_ID", "tenant-a")
    registry = edge_runtime.Registry(edge_runtime.Config())

    with caplog.at_level(logging.ERROR, logger="edge-runtime"):
        with pytest.raises(edge_runtime.BundleError, match="tenant-a"):
            registry.install_bundle(_make_bundle("foreign", key, tenant_id="tenant-b"))
        with pytest.raises(edge_runtime.BundleError, match="<none>"):
            registry.install_bundle(_make_bundle("legacy", key, tenant_id=None))
    assert registry.list() == []
    mismatch = [
        r.getMessage()
        for r in caplog.records
        if "bundle_tenant_mismatch" in r.getMessage()
    ]
    assert mismatch and "tenant-b" in mismatch[0] and "tenant-a" in mismatch[0]

    agent = registry.install_bundle(_make_bundle("own", key, tenant_id="tenant-a"))
    assert agent.slug == "own"


def test_no_tenant_binding_accepts_any_tenant(env, key):
    env.setenv("SIGNING_PUBKEY_PEM", _pub_pem(key))
    registry = edge_runtime.Registry(edge_runtime.Config())
    assert (
        registry.install_bundle(_make_bundle("any", key, tenant_id="whoever")).slug
        == "any"
    )


def test_reload_from_disk_skips_foreign_tenant(env, key):
    env.setenv("SIGNING_PUBKEY_PEM", _pub_pem(key))
    registry = edge_runtime.Registry(edge_runtime.Config())
    registry.install_bundle(_make_bundle("mine", key, tenant_id="tenant-a"))
    registry.install_bundle(_make_bundle("theirs", key, tenant_id="tenant-b"))

    env.setenv("TENANT_ID", "tenant-a")
    fresh = edge_runtime.Registry(edge_runtime.Config())
    fresh.reload_from_disk()
    assert fresh.get("mine") is not None
    assert fresh.get("theirs") is None
