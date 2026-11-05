"""Secure defaults of the agents runtime: auth, bundle checks, code execution, time limits."""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import httpx
import pytest
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime as edge_runtime  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUB = (
    KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)
TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def manifest(slug="pump", **extra) -> dict:
    return {
        "name": "Pump",
        "slug": slug,
        "version": "0.1.0",
        "model": "claude-haiku-4-5",
        "temperature": 0.2,
        "max_iterations": 1,
        "max_tokens": 16,
        "tools": ["current_time"],
        "edge_constraints": {"max_payload_bytes": 4096, "max_runtime_seconds": 5},
        **extra,
    }


def tar_of(members: list[tarfile.TarInfo | tuple[str, bytes]]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for m in members:
            if isinstance(m, tarfile.TarInfo):
                tar.addfile(m)
            else:
                info = tarfile.TarInfo(name=m[0])
                info.size = len(m[1])
                tar.addfile(info, io.BytesIO(m[1]))
    return out.getvalue()


def signed(members: list, key: rsa.RSAPrivateKey = KEY) -> bytes:
    sig = key.sign(
        tar_of(members),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    return tar_of(members + [("signature.sig", sig)])


def bundle(slug="pump", prompt=b"v1", **extra) -> bytes:
    return signed(
        [
            ("agent.yaml", yaml.safe_dump(manifest(slug, **extra)).encode()),
            ("system_prompt.md", prompt),
        ]
    )


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in (
        "EDGE_ALLOW_UNSIGNED",
        "EDGE_ALLOW_NO_AUTH",
        "EDGE_ENABLE_CODE_EXECUTOR",
        "TENANT_ID",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_SUBSCRIPTION_TOKEN",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BUNDLE_DIR", str(tmp_path / "agents"))
    monkeypatch.setenv("SIGNING_PUBKEY_PEM", PUB)
    monkeypatch.setenv("EDGE_AUTH_TOKEN", TOKEN)
    return monkeypatch


def fresh() -> edge_runtime.Registry:
    return edge_runtime.Registry(edge_runtime.Config())


def test_no_auth_token_refuses_to_start(env):
    env.delenv("EDGE_AUTH_TOKEN")
    with pytest.raises(SystemExit, match="EDGE_AUTH_TOKEN"):
        edge_runtime.check_startup(edge_runtime.Config())
    env.setenv("EDGE_ALLOW_NO_AUTH", "TRUE")
    with pytest.raises(SystemExit, match="EDGE_AUTH_TOKEN"):
        edge_runtime.check_startup(edge_runtime.Config())
    env.setenv("EDGE_ALLOW_NO_AUTH", "true")
    edge_runtime.check_startup(edge_runtime.Config())


async def _serve(tmp_path, call):
    cfg = edge_runtime.Config()
    registry = edge_runtime.Registry(cfg)
    server = await asyncio.start_server(
        lambda r, w: edge_runtime._handle_request(r, w, cfg, registry), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=8.0
        ) as c:
            return await call(c, registry)
    finally:
        server.close()


def test_http_needs_the_token_and_health_stays_open(env, tmp_path):
    async def go(c, registry):
        assert (await c.get("/health")).status_code == 200
        assert (await c.get("/agents")).status_code == 200
        r = await c.post("/agents/pump/bundle", content=bundle())
        assert r.status_code == 401
        assert registry.list() == []
        r = await c.post(
            "/agents/pump/bundle",
            content=bundle(),
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401
        r = await c.post("/agents/pump/bundle", content=bundle(), headers=AUTH)
        assert r.status_code == 200, r.text
        assert (await c.post("/agents/pump/execute", json={})).status_code == 401
        r = await c.post("/agents/pump/execute", json={"message": "hi"}, headers=AUTH)
        assert r.status_code == 200 and r.json()["result"]["stub"] is True

    asyncio.run(_serve(tmp_path, go))


def test_url_slug_must_match_and_be_safe(env, tmp_path):
    async def go(c, registry):
        r = await c.post("/agents/other/bundle", content=bundle(), headers=AUTH)
        assert r.status_code == 400 and "other" in r.text
        for slug in ("..%2f..%2fetc", ".hidden", "a..b"):
            r = await c.post(f"/agents/{slug}/bundle", content=bundle(), headers=AUTH)
            assert r.status_code == 400, slug
        assert registry.list() == []

    asyncio.run(_serve(tmp_path, go))


@pytest.mark.parametrize(
    "slug", ["../../etc/cron.d/x", "/abs", "a/b", ".dot", "a..b", "a b", "x" * 96, ""]
)
def test_unsafe_manifest_slug_is_refused(env, tmp_path, slug):
    with pytest.raises(edge_runtime.BundleError, match="slug"):
        fresh().install_bundle(bundle(slug=slug))
    assert not list((tmp_path).rglob("system_prompt.md"))


@pytest.mark.parametrize("name", ["../evil", "/abs/evil", "a/../../evil", "a\\evil"])
def test_unsafe_member_path_is_refused(env, tmp_path, name):
    b = signed(
        [
            ("agent.yaml", yaml.safe_dump(manifest()).encode()),
            ("system_prompt.md", b"x"),
            (name, b"owned"),
        ]
    )
    with pytest.raises(edge_runtime.BundleError, match="unsafe path"):
        fresh().install_bundle(b)
    assert not list(tmp_path.rglob("evil"))


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_links_and_devices_are_refused(env, tmp_path, kind):
    link = tarfile.TarInfo("system_prompt.md")
    link.type = kind
    link.linkname = "/etc/passwd"
    b = signed([("agent.yaml", yaml.safe_dump(manifest()).encode()), link])
    with pytest.raises(edge_runtime.BundleError, match="link or device"):
        fresh().install_bundle(b)


def test_duplicate_entry_is_refused(env):
    y = yaml.safe_dump(manifest()).encode()
    b = signed([("agent.yaml", y), ("system_prompt.md", b"a"), ("agent.yaml", y)])
    with pytest.raises(edge_runtime.BundleError, match="duplicate"):
        fresh().install_bundle(b)


def test_gzip_and_oversize_are_refused(env):
    import gzip

    with pytest.raises(edge_runtime.BundleError, match="readable"):
        fresh().install_bundle(gzip.compress(bundle()))
    with pytest.raises(edge_runtime.BundleError, match="bytes"):
        fresh().install_bundle(b"\0" * (edge_runtime.MAX_BUNDLE_BYTES + 1))


def test_tampered_bundle_refused_and_old_version_keeps_serving(env, tmp_path):
    reg = fresh()
    first = reg.install_bundle(bundle(prompt=b"v1"))
    bad = bytearray(bundle(prompt=b"v2"))
    bad[bytes(bad).index(b"v2")] ^= 1
    with pytest.raises(edge_runtime.BundleError):
        reg.install_bundle(bytes(bad))
    assert reg.get("pump").digest == first.digest
    assert (tmp_path / "agents/pump/system_prompt.md").read_text() == "v1"
    assert [p.name for p in (tmp_path / "agents").iterdir()] == ["pump"]


def test_failed_swap_keeps_old_version(env, tmp_path, monkeypatch):
    reg = fresh()
    reg.install_bundle(bundle(prompt=b"v1"))
    real = Path.write_bytes

    def boom(self, data):
        if self.name == edge_runtime.SAVED_BUNDLE:
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", boom)
    with pytest.raises(OSError):
        reg.install_bundle(bundle(prompt=b"v2"))
    monkeypatch.undo()
    assert (tmp_path / "agents/pump/system_prompt.md").read_text() == "v1"
    assert [p.name for p in (tmp_path / "agents").iterdir()] == ["pump"]


def test_reload_verifies_the_saved_bundle(env, tmp_path):
    first = fresh().install_bundle(bundle())
    again = fresh()
    again.reload_from_disk()
    assert again.get("pump").digest == first.digest

    saved = tmp_path / "agents/pump" / edge_runtime.SAVED_BUNDLE
    raw = bytearray(saved.read_bytes())
    raw[raw.index(b"v1")] ^= 1
    saved.write_bytes(bytes(raw))
    tampered = fresh()
    tampered.reload_from_disk()
    assert tampered.get("pump") is None

    saved.unlink()
    unknown = fresh()
    unknown.reload_from_disk()
    assert unknown.get("pump") is None


def test_same_bundle_twice_is_a_no_op(env, tmp_path):
    reg = fresh()
    b = bundle()
    first = reg.install_bundle(b)
    marker = tmp_path / "agents/pump/marker"
    marker.write_text("kept")
    assert reg.install_bundle(b) is first
    assert marker.exists()


def _agent(reg, tools=("code_executor",), runtime_s=5):
    return reg.install_bundle(
        bundle(
            tools=list(tools),
            edge_constraints={
                "max_payload_bytes": 4096,
                "max_runtime_seconds": runtime_s,
            },
        )
    )


def test_params_code_is_off_by_default(env):
    reg = fresh()
    r = asyncio.run(
        edge_runtime.execute_agent(reg.cfg, _agent(reg), "", {"code": "print(6*7)"})
    )
    assert r["result"]["ok"] is False and "off" in r["result"]["error"]


def test_params_code_needs_the_tool(env):
    env.setenv("EDGE_ENABLE_CODE_EXECUTOR", "true")
    reg = fresh()
    r = asyncio.run(
        edge_runtime.execute_agent(
            reg.cfg, _agent(reg, ("current_time",)), "", {"code": "print(1)"}
        )
    )
    assert "whitelist" in r["result"]["error"]


def test_params_code_runs_scrubbed(env):
    env.setenv("EDGE_ENABLE_CODE_EXECUTOR", "true")
    env.setenv("ANTHROPIC_API_KEY", "leak-me")
    reg = fresh()
    code = "import os,json;print(json.dumps(dict(os.environ)))"
    r = asyncio.run(
        edge_runtime.execute_agent(reg.cfg, _agent(reg), "", {"code": code})
    )
    assert r["result"]["ok"], r
    seen = json.loads(r["result"]["stdout"])
    assert "leak-me" not in r["result"]["stdout"]
    assert TOKEN not in r["result"]["stdout"]
    assert {"PATH", "HOME"} <= set(seen)
    assert "ANTHROPIC_API_KEY" not in seen and "EDGE_AUTH_TOKEN" not in seen


def test_params_code_is_killed_at_the_limit(env):
    env.setenv("EDGE_ENABLE_CODE_EXECUTOR", "true")
    reg = fresh()
    code = "import os,time\nif os.fork()==0:\n time.sleep(30)\nelse:\n time.sleep(30)\n"
    r = asyncio.run(
        edge_runtime.execute_agent(
            reg.cfg, _agent(reg, runtime_s=1), "", {"code": code}
        )
    )
    assert r["result"]["ok"] is False
    assert r["duration_ms"] < 5000


def test_max_runtime_seconds_stops_a_slow_model(env):
    async def go():
        async def slow(reader, writer):
            await reader.readline()
            await asyncio.sleep(30)
            writer.close()

        server = await asyncio.start_server(slow, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        env.setenv("ANTHROPIC_API_KEY", "k")
        env.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{port}")
        reg = fresh()
        try:
            return await edge_runtime.execute_agent(
                reg.cfg, _agent(reg, ("current_time",), 1), "hi", {}
            )
        finally:
            server.close()

    r = asyncio.run(go())
    assert r["result"]["ok"] is False
    assert r["duration_ms"] < 5000


def test_subscription_token_uses_bearer_and_beta(env):
    assert edge_runtime._llm_headers(edge_runtime.Config()) is None
    env.setenv("CLAUDE_SUBSCRIPTION_TOKEN", "sub")
    h = edge_runtime._llm_headers(edge_runtime.Config())
    assert h["authorization"] == "Bearer sub" and h["anthropic-beta"]
    assert "x-api-key" not in h
    env.setenv("ANTHROPIC_API_KEY", "key")
    h = edge_runtime._llm_headers(edge_runtime.Config())
    assert h["x-api-key"] == "key" and "authorization" not in h


@pytest.mark.parametrize(
    "env_in,want",
    [
        ({"EDGE_MODE": "legacy", "ABENIX_URL": "http://x"}, "runtime"),
        ({"EDGE_MODE": "gateway", "PLATFORM_URL": "http://x"}, "abenix_edge.app"),
        ({"PLATFORM_URL": "http://x"}, "runtime"),
        ({"ABENIX_URL": "http://x"}, "abenix_edge.app"),
    ],
)
def test_entrypoint_mode(tmp_path, env_in, want):
    # stub modules show which main the entrypoint picked
    (tmp_path / "runtime.py").write_text("def main():\n    print('runtime')\n")
    (tmp_path / "abenix_edge").mkdir()
    (tmp_path / "abenix_edge/__init__.py").write_text("")
    (tmp_path / "abenix_edge/app.py").write_text(
        "def main():\n    print('abenix_edge.app')\n"
    )
    (tmp_path / "entrypoint.py").write_text((ROOT / "entrypoint.py").read_text())
    clean = {"PATH": os.environ["PATH"], "ABENIX_EDGE_DATA": str(tmp_path / "data")}
    out = subprocess.run(
        [sys.executable, str(tmp_path / "entrypoint.py")],
        env={**clean, **env_in},
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == want, out.stderr


def test_entrypoint_refuses_unknown_mode(tmp_path):
    out = subprocess.run(
        [sys.executable, str(ROOT / "entrypoint.py")],
        env={"PATH": os.environ["PATH"], "EDGE_MODE": "both"},
        capture_output=True,
        text=True,
    )
    assert out.returncode != 0 and "EDGE_MODE" in out.stderr


def test_local_collectors_merge(env, tmp_path):
    from abenix_edge.app import Gateway

    f = tmp_path / "local.json"
    f.write_text(json.dumps([{"id": "a"}, {"id": "b"}]))
    env.setenv("ABENIX_EDGE_COLLECTORS_FILE", str(f))
    env.setenv("ABENIX_EDGE_DATA", str(tmp_path / "data"))

    async def go():
        gw = Gateway()
        merged = gw.merged_collectors({"collectors": [{"id": "a", "from": "platform"}]})
        assert merged == [{"id": "a", "from": "platform"}, {"id": "b"}]
        f.write_text("{not json")
        assert gw.merged_collectors({"collectors": [{"id": "a"}]}) == [{"id": "a"}]
        assert "skipped" in gw.problem

    asyncio.run(go())
