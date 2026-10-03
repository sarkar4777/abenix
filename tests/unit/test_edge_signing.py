"""Edge bundle signing fails closed.

Outside dev the API must never mint a signing key. In dev the generated key
lives under the data dir so replicas and restarts agree. The manifest carries
tenant_id under the signature and a tenant-bound runtime refuses foreign bundles.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import logging
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

import app.routers.edge as edge
from app.services import edge_compiler

ROOT = Path(__file__).resolve().parents[2]


def _load_runtime():
    spec = importlib.util.spec_from_file_location(
        "abenix_edge_runtime", ROOT / "apps" / "edge-runtime" / "runtime.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _private_pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def signing_env(monkeypatch, tmp_path):
    """Clean key cache and env, data dir pointed at tmp_path."""
    monkeypatch.setattr(edge, "_signing_key_cache", None)
    monkeypatch.setattr(edge, "_dev_key_in_use", False)
    monkeypatch.setattr(edge, "_dev_key_warned", False)
    monkeypatch.delenv("EDGE_SIGNING_KEY_PEM", raising=False)
    monkeypatch.delenv("EDGE_SIGNING_KEY_PATH", raising=False)
    monkeypatch.delenv("UPLOAD_DIR", raising=False)
    monkeypatch.setenv("EDGE_SIGNING_KEY_DIR", str(tmp_path / "data" / "edge"))
    return monkeypatch


def test_prod_without_key_returns_503(signing_env, tmp_path):
    signing_env.setenv("ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as ei:
        edge._signing_key_or_503()
    assert ei.value.status_code == 503
    assert "EDGE_SIGNING_KEY_PEM" in ei.value.detail
    assert not (tmp_path / "data").exists()
    assert edge._signing_key_cache is None


@pytest.mark.parametrize("environment", ["staging", "production", "prod", "uat"])
def test_non_dev_environments_never_mint(signing_env, environment):
    signing_env.setenv("ENVIRONMENT", environment)
    with pytest.raises(edge.EdgeSigningUnavailable):
        edge._resolve_signing_key()


def test_debug_false_without_environment_is_prod(signing_env):
    signing_env.delenv("ENVIRONMENT", raising=False)
    signing_env.setattr(edge.settings, "debug", False)
    with pytest.raises(edge.EdgeSigningUnavailable):
        edge._resolve_signing_key()


def test_signing_key_endpoint_503_in_prod(signing_env):
    signing_env.setenv("ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(edge.signing_key())
    assert ei.value.status_code == 503


def test_dev_key_persisted_under_data_dir(signing_env, tmp_path, caplog):
    signing_env.setenv("ENVIRONMENT", "local")
    with caplog.at_level(logging.WARNING, logger="app.routers.edge"):
        first = edge._resolve_signing_key()
        edge._resolve_signing_key()
    priv = tmp_path / "data" / "edge" / "signing_priv.pem"
    pub = tmp_path / "data" / "edge" / "signing_pub.pem"
    assert priv.exists() and pub.exists()
    assert pub.read_text().startswith("-----BEGIN PUBLIC KEY-----")
    assert edge._dev_key_in_use is True
    dev_warnings = [
        r for r in caplog.records if "edge_dev_signing_key" in r.getMessage()
    ]
    assert len(dev_warnings) == 1
    assert dev_warnings[0].levelno == logging.WARNING

    # A restart or another replica loads the same key
    signing_env.setattr(edge, "_signing_key_cache", None)
    again = edge._resolve_signing_key()
    assert again.public_key().public_numbers() == first.public_key().public_numbers()
    assert (
        again.public_key().public_numbers()
        == serialization.load_pem_public_key(pub.read_bytes()).public_numbers()
    )


def test_dev_key_dir_follows_upload_dir(signing_env, tmp_path):
    signing_env.setenv("ENVIRONMENT", "development")
    signing_env.delenv("EDGE_SIGNING_KEY_DIR", raising=False)
    signing_env.setenv("UPLOAD_DIR", str(tmp_path / "shared" / "uploads"))
    edge._resolve_signing_key()
    assert (tmp_path / "shared" / "edge" / "signing_priv.pem").exists()


def test_prod_with_env_pem_signs_without_writing(signing_env, tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signing_env.setenv("ENVIRONMENT", "production")
    signing_env.setenv("EDGE_SIGNING_KEY_PEM", _private_pem(key))
    loaded = edge._signing_key_or_503()
    assert loaded.public_key().public_numbers() == key.public_key().public_numbers()
    assert edge._dev_key_in_use is False
    assert not (tmp_path / "data").exists()


def test_prod_with_mounted_key_path(signing_env, tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    mounted = tmp_path / "mnt" / "signing.pem"
    mounted.parent.mkdir()
    mounted.write_text(_private_pem(key))
    signing_env.setenv("ENVIRONMENT", "production")
    signing_env.setenv("EDGE_SIGNING_KEY_PATH", str(mounted))
    assert edge._resolve_signing_key().public_key().public_numbers() == (
        key.public_key().public_numbers()
    )
    assert edge._dev_key_in_use is False


def test_signing_key_endpoint_exposes_public_half_only(signing_env):
    signing_env.setenv("ENVIRONMENT", "local")
    resp = asyncio.run(edge.signing_key())
    body = json.loads(resp.body)["data"]
    assert body["public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")
    assert "PRIVATE" not in body["public_key_pem"]
    assert body["dev_key"] is True
    assert "RSA-PSS" in body["algorithm"]


def _agent(tenant_id: str):
    return SimpleNamespace(
        name="Pump Watch",
        slug="pump-watch",
        version="1.2.0",
        description="",
        tenant_id=tenant_id,
        system_prompt="watch the pump",
        model_config_={"edge_compatible": True, "tools": ["current_time"]},
    )


def test_manifest_carries_tenant_id():
    manifest = edge_compiler._manifest_from_agent(_agent("tenant-a"))
    assert manifest["tenant_id"] == "tenant-a"


def _compile(agent, key: rsa.RSAPrivateKey) -> bytes:
    manifest = edge_compiler._manifest_from_agent(agent)
    unsigned = edge_compiler._build_unsigned_tar(manifest, agent.system_prompt)
    return edge_compiler._append_signature(unsigned, edge_compiler._sign(unsigned, key))


def _retag_tenant(bundle: bytes, tenant_id: str) -> bytes:
    """Rewrite agent.yaml in place, keeping the original signature."""
    out = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as src:
        with tarfile.open(fileobj=out, mode="w") as dst:
            for m in src.getmembers():
                data = src.extractfile(m).read()
                if m.name == "agent.yaml":
                    doc = yaml.safe_load(data)
                    doc["tenant_id"] = tenant_id
                    data = yaml.safe_dump(doc, sort_keys=True).encode()
                info = tarfile.TarInfo(name=m.name)
                info.size = len(data)
                info.mtime = m.mtime
                dst.addfile(info, io.BytesIO(data))
    return out.getvalue()


@pytest.fixture
def runtime_env(monkeypatch, tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("BUNDLE_DIR", str(tmp_path / "agents"))
    monkeypatch.setenv("SIGNING_PUBKEY_PEM", edge_compiler.public_key_pem(key))
    monkeypatch.delenv("SIGNING_PUBKEY_PATH", raising=False)
    monkeypatch.delenv("EDGE_ALLOW_UNSIGNED", raising=False)
    monkeypatch.delenv("TENANT_ID", raising=False)
    return monkeypatch, key, _load_runtime()


def test_tenant_mismatch_rejected_by_runtime(runtime_env):
    monkeypatch, key, rt = runtime_env
    bundle = _compile(_agent("tenant-a"), key)

    monkeypatch.setenv("TENANT_ID", "tenant-b")
    registry = rt.Registry(rt.Config())
    with pytest.raises(rt.BundleError, match="tenant-b"):
        registry.install_bundle(bundle)
    assert registry.list() == []

    monkeypatch.setenv("TENANT_ID", "tenant-a")
    agent = rt.Registry(rt.Config()).install_bundle(bundle)
    assert agent.manifest["tenant_id"] == "tenant-a"


def test_signature_covers_tenant_id(runtime_env):
    monkeypatch, key, rt = runtime_env
    bundle = _compile(_agent("tenant-a"), key)
    forged = _retag_tenant(bundle, "tenant-b")

    monkeypatch.setenv("TENANT_ID", "tenant-b")
    registry = rt.Registry(rt.Config())
    with pytest.raises(rt.BundleError, match="bundle_signature_invalid"):
        registry.install_bundle(forged)


def _compile_signed(agent, key: rsa.RSAPrivateKey) -> bytes:
    manifest = edge_compiler._manifest_from_agent(agent)
    unsigned = edge_compiler._build_unsigned_tar(manifest, agent.system_prompt)
    return edge_compiler.sign_bundle(unsigned, key)


def test_signature_covers_bundle_minus_signature_entry():
    # The C gateway verifies by cutting signature.sig out of the received bytes
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bundle = _compile_signed(_agent("tenant-a"), key)
    start, end, data_start, size = edge_compiler.signature_span(bundle)
    assert size == 256 and end - start == 1024
    view = bundle[:start] + bundle[end:]
    key.public_key().verify(
        bundle[data_start : data_start + size],
        view,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
        assert [m.name for m in tar.getmembers()] == [
            "agent.yaml",
            "system_prompt.md",
            "signature.sig",
        ]


def test_runtime_loads_stripped_signature_bundle_and_rejects_tamper(runtime_env):
    monkeypatch, key, rt = runtime_env
    bundle = _compile_signed(_agent("tenant-a"), key)
    agent = rt.Registry(rt.Config()).install_bundle(bundle)
    assert agent.slug == "pump-watch"

    forged = _retag_tenant(bundle, "tenant-b")
    with pytest.raises(rt.BundleError, match="bundle_signature_invalid"):
        rt.Registry(rt.Config()).install_bundle(forged)
