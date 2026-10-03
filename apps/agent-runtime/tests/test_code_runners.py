"""Warm code runners: naming, manifests, scaling plan, NATS fallback and the tool."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import code_runners as cr
from engine.tools import code_asset as ca
from engine.tools.base import ToolResult

RUNNER_PY = Path(__file__).resolve().parents[2] / "code-runner" / "runner.py"
TENANT = "11111111-2222-3333-4444-555555555555"
ASSET_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _runner_module():
    spec = importlib.util.spec_from_file_location("coderun_runner", RUNNER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _asset(**kw):
    a = {
        "id": ASSET_ID,
        "tenant_id": TENANT,
        "status": "ready",
        "version": 3,
        "storage_uri": "/data/code-assets/x.zip",
        "suggested_image": "python:3.12-slim",
        "suggested_build_command": "pip install -r requirements.txt",
        "suggested_run_command": "python main.py",
        "input_schema": None,
        "output_schema": None,
    }
    a.update(kw)
    return a


def _settings(**kw):
    s = cr.Settings(
        images={"python-3.12": "reg/code-runner-python:t"},
        nats_url="nats://x:4222",
        runner_nats_url="nats://x:4222",
        nats_secret="abenix-code-runner-nats",
        api_url="http://api:8000",
        min_warm=cr._parse_tier_map(""),
    )
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ── naming and parity with the runner ────────────────────────────────────────

IMAGES = [
    "python:3.12-slim",
    "python:3.11",
    "python3:3.10",
    "node:20-alpine",
    "node:18",
    "golang:1.22-alpine",
    "ruby:3.3-alpine",
    "eclipse-temurin:21-jdk",
    "docker.io/library/python:3.12-slim",
    "localhost:5000/abenix/node:20",
    "alpine:3.20",
    "busybox",
    "",
]


def test_pool_mapping_and_subject_match_the_runner_copy():
    runner = _runner_module()
    for img in IMAGES:
        assert cr.pool_for_image(img) == runner.pool_for_image(img), img
    for net in (False, True):
        assert cr.subject_for(TENANT, ASSET_ID, "v3-abc123", net) == runner.subject_for(
            TENANT, ASSET_ID, "v3-abc123", net
        )
    names = [
        ["proj/", "proj/main.py"],
        ["main.py", "lib/u.py"],
        ["a/x", "b/y"],
        ["proj/main.py", "__MACOSX/proj/._main.py"],
        ["proj"],
        [],
    ]
    for n in names:
        assert ca.single_root_prefix(n) == runner.single_root_prefix(n)


def test_pool_mapping():
    assert cr.pool_for_image("python:3.12-slim") == "python-3.12"
    assert cr.pool_for_image("node:20-alpine") == "node-20"
    assert cr.pool_for_image("golang:1.22-alpine") == "go-1.22"
    assert cr.pool_for_image("alpine:3.20") is None


def test_revision_follows_version_and_commands():
    r = cr.runner_revision(_asset())
    assert r.startswith("v3-") and len(r) == 9
    assert cr.runner_revision(_asset(version=4)) != r
    assert cr.runner_revision(_asset(suggested_run_command="python other.py")) != r
    assert cr.runner_revision(_asset()) == r


def test_runner_name_is_dns_safe_and_per_tenant_asset_version():
    rev = cr.runner_revision(_asset())
    n = cr.runner_name(TENANT, ASSET_ID, rev, False)
    assert n == f"coderun-11111111-aaaaaaaa-{rev}"
    assert cr.runner_name(TENANT, ASSET_ID, rev, True) == n + "-net"
    assert len(n) <= 63 and n == n.lower()
    assert cr.runner_name("", ASSET_ID, rev, False).startswith("coderun-system-")


def test_request_payload():
    spec = cr.spec_for(_asset(), TENANT, False, _settings())
    req = cr.build_request(spec, {"x": 1}, {"K": "v"}, 30, 512)
    assert set(req) == {
        "v",
        "id",
        "tenant_id",
        "asset_id",
        "revision",
        "input",
        "env",
        "timeout_s",
        "memory_mb",
    }
    assert req["revision"] == spec.revision and req["input"] == {"x": 1}
    assert spec.subject == f"code.{TENANT}.{ASSET_ID}.{spec.revision}"
    assert (
        spec.fetch_url == f"http://api:8000/api/code-assets/{ASSET_ID}/fetch?version=3"
    )


def test_no_spec_without_a_runner_image_for_the_pool():
    assert (
        cr.spec_for(_asset(suggested_image="golang:1.22"), TENANT, False, _settings())
        is None
    )


# ── manifests ────────────────────────────────────────────────────────────────


def _containers(dep):
    pod = dep["spec"]["template"]["spec"]
    return pod, {c["name"]: c for c in pod["initContainers"] + pod["containers"]}


def test_deployment_is_locked_down():
    s = _settings(runtime_class="gvisor")
    spec = cr.spec_for(_asset(), TENANT, False, s)
    dep = cr.build_deployment(spec, s, 1)
    pod, cs = _containers(dep)
    assert set(cs) == {"prepare", "exec", "gateway"}
    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["runtimeClassName"] == "gvisor"
    for c in cs.values():
        sc = c["securityContext"]
        assert sc["runAsNonRoot"] and sc["readOnlyRootFilesystem"]
        assert sc["allowPrivilegeEscalation"] is False
        assert sc["capabilities"] == {"drop": ["ALL"]}
        assert sc["runAsUser"] >= 10000
    assert cs["exec"]["securityContext"]["runAsUser"] == cr.tenant_uid(TENANT)
    assert cs["gateway"]["securityContext"]["runAsUser"] == cr.GATEWAY_UID
    ws = [m for m in cs["exec"]["volumeMounts"] if m["name"] == "ws"][0]
    assert ws["readOnly"] is True and ws["mountPath"] == "/ws"
    names = lambda c: {e["name"] for e in c["env"]}  # noqa: E731
    assert {"NATS_USER", "NATS_PASSWORD"} <= names(cs["gateway"])
    assert not {"NATS_USER", "NATS_PASSWORD", "NATS_URL"} & names(cs["exec"])
    assert "CODERUN_FETCH_TOKEN" in names(cs["prepare"])
    assert "CODERUN_FETCH_TOKEN" not in names(cs["exec"]) | names(cs["gateway"])
    labels = dep["spec"]["template"]["metadata"]["labels"]
    assert labels["app"] == cr.APP_LABEL and labels["abenix.io/network"] == "none"
    assert dep["spec"]["selector"]["matchLabels"] == {
        "abenix.io/code-runner": spec.name
    }
    net = cr.build_deployment(cr.spec_for(_asset(), TENANT, True, s), s, 1)
    assert net["spec"]["template"]["metadata"]["labels"]["abenix.io/network"] == "open"


def test_tenants_get_different_exec_uids():
    assert cr.tenant_uid(TENANT) == cr.tenant_uid(TENANT)
    assert cr.tenant_uid(TENANT) != cr.tenant_uid(
        "99999999-2222-3333-4444-555555555555"
    )
    assert 20000 <= cr.tenant_uid(TENANT) < 30000


def test_scaler_is_keda_on_runner_load_or_cpu_hpa():
    spec = cr.spec_for(_asset(), TENANT, False, _settings())
    keda = cr.build_scaler(
        spec, _settings(keda=True, prometheus_url="http://p:9090"), 0
    )
    assert keda["kind"] == "ScaledObject" and keda["spec"]["minReplicaCount"] == 0
    q = keda["spec"]["triggers"][0]["metadata"]["query"]
    assert f'runner="{spec.name}"' in q and "abenix_coderunner_load" in q
    hpa = cr.build_scaler(spec, _settings(), 1)
    assert hpa["kind"] == "HorizontalPodAutoscaler" and hpa["spec"]["minReplicas"] == 1


# ── min warm and the reaper plan ─────────────────────────────────────────────


def test_min_warm_from_tier_manifest_and_usage():
    s = _settings(hot_calls_per_hour=10)
    assert cr.min_warm_for({}, 0, s) == 0
    assert cr.min_warm_for({"risk_tier": "high"}, 0, s) == 1
    assert cr.min_warm_for({"risk_tier": "critical"}, 0, s) == 1
    assert cr.min_warm_for({"min_warm": 2}, 0, s) == 2
    assert cr.min_warm_for({}, 10, s) == 1
    assert cr.min_warm_for({"min_warm": 99}, 0, s) == s.max_replicas
    s2 = _settings(min_warm=cr._parse_tier_map("medium=2"))
    assert cr.min_warm_for({}, 0, s2) == 2


def _meta(asset, replicas=1, kicked=None, created=1000, token_exp=None):
    rev = cr.runner_revision(asset)
    return {
        "labels": {"abenix.io/revision": rev, "abenix.io/asset": asset["id"]},
        "annotations": {
            "abenix.io/kicked-at": str(kicked or created),
            "abenix.io/token-exp": str(token_exp or 10**12),
        },
        "created": created,
        "replicas": replicas,
    }


def test_plan_drains_then_deletes_superseded_versions(monkeypatch):
    monkeypatch.setattr(cr, "read_manifest", lambda uri: {})
    s = _settings(drain_seconds=120)
    old = _asset(version=2)
    meta = _meta(old)
    assert cr.plan_runner(meta, _asset(version=3), 1000, 0, 1060, s)[0] == "drain"
    assert cr.plan_runner(meta, _asset(version=3), 1000, 0, 1200, s)[0] == "delete"
    assert cr.plan_runner(meta, None, 1000, 0, 1200, s)[0] == "delete"
    assert (
        cr.plan_runner(meta, _asset(version=2, status="deleted"), 1000, 0, 1200, s)[0]
        == "delete"
    )


def test_plan_scales_idle_runners_to_zero_and_keeps_warm_tiers(monkeypatch):
    s = _settings(idle_seconds=900)
    a = _asset()
    monkeypatch.setattr(cr, "read_manifest", lambda uri: {})
    assert cr.plan_runner(_meta(a), a, 1000, 0, 1500, s) == ("keep", None)
    assert cr.plan_runner(_meta(a), a, 1000, 0, 2000, s) == ("scale", 0)
    assert cr.plan_runner(_meta(a, replicas=0), a, 1000, 0, 5000, s) == ("keep", None)
    monkeypatch.setattr(cr, "read_manifest", lambda uri: {"risk_tier": "high"})
    assert cr.plan_runner(_meta(a), a, 1000, 0, 9000, s) == ("keep", None)
    assert cr.plan_runner(_meta(a, replicas=0), a, 1000, 0, 9000, s) == ("scale", 1)


def test_plan_refreshes_fetch_tokens_before_they_expire(monkeypatch):
    monkeypatch.setattr(cr, "read_manifest", lambda uri: {})
    s = _settings(fetch_ttl=3600)
    a = _asset()
    assert cr.plan_runner(_meta(a, token_exp=1100), a, 1000, 0, 1050, s) == (
        "refresh",
        None,
    )


# ── NATS call path ───────────────────────────────────────────────────────────


class _NC:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.is_connected = True

    async def request(self, subject, data, timeout):
        self.sent.append((subject, json.loads(data), timeout))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return type("M", (), {"data": json.dumps(r).encode()})()


@pytest.fixture
def warm_env(monkeypatch):
    kicks = []

    async def fake_kick(spec, storage_uri=""):
        kicks.append(spec.name)
        return "created"

    async def no_use(*a, **k):
        return None

    monkeypatch.setattr(cr, "kick", fake_kick)
    monkeypatch.setattr(cr, "record_use", no_use)

    def install(replies):
        nc = _NC(replies)

        async def client(s):
            return nc

        monkeypatch.setattr(cr, "nats_client", client)
        return nc

    return install, kicks


async def _call(**kw):
    args = dict(
        asset=_asset(),
        tenant_id=TENANT,
        input_payload={"x": 1},
        env={"K": "v"},
        timeout_s=30,
        memory_mb=512,
        network=False,
        s=_settings(),
    )
    args.update(kw)
    return await cr.call_warm(**args)


async def test_no_responders_falls_back_and_kicks(warm_env):
    from nats.errors import NoRespondersError

    install, kicks = warm_env
    install([NoRespondersError()])
    out = await _call()
    await asyncio.sleep(0)
    assert out.resp is None and out.fallback and "warming" in out.reason
    assert kicks == [out.name]


async def test_timeout_does_not_fall_back(warm_env):
    from nats.errors import TimeoutError as NatsTimeout

    install, _ = warm_env
    install([NatsTimeout()])
    out = await _call()
    assert out.resp is None and not out.fallback


async def test_busy_runner_is_retried_once(warm_env):
    install, _ = warm_env
    nc = install(
        [
            {"ok": False, "refused": True, "reason": "busy"},
            {"ok": True, "exit_code": 0, "stdout": "{}", "duration_ms": 3},
        ]
    )
    out = await _call()
    assert out.resp["ok"] and len(nc.sent) == 2
    subject, payload, timeout = nc.sent[0]
    assert subject.startswith(f"code.{TENANT}.{ASSET_ID}.v3-")
    assert payload["env"] == {"K": "v"} and timeout == 50


async def test_not_configured_and_unknown_pool_fall_back():
    out = await _call(s=_settings(images={}))
    assert out.fallback and "not configured" in out.reason
    out = await _call(asset=_asset(suggested_image="golang:1.22"))
    assert out.fallback and "go-1.22" in out.reason
    out = await _call(s=_settings(nats_url=""))
    assert out.fallback and "NATS_URL" in out.reason


async def test_oversized_request_falls_back(warm_env):
    install, _ = warm_env
    install([])
    out = await _call(input_payload={"blob": "x" * 2000}, s=_settings(max_payload=1000))
    assert out.fallback and "too large" in out.reason


# ── the tool ─────────────────────────────────────────────────────────────────

JOB_LOGS = 'noise\n___ASSET_OUT_START___\n{"answer": 42}\n___ASSET_OUT_END___\n'


@pytest.fixture
def tool_env(monkeypatch, tmp_path):
    asset = _asset(storage_uri=str(tmp_path / "missing.zip"))
    calls = {"job": 0, "recorded": []}

    async def load(db, tenant, aid):
        return dict(asset)

    async def secrets(db, tenant, aid):
        return {"API_KEY": "s"}

    async def record(db, aid, inp, out, ok):
        calls["recorded"].append(out)

    async def gate_settings(self):
        return {
            "enabled": True,
            "allow_network": False,
            "allowed_images": {"python:3.12-slim"},
        }

    async def job_execute(self, args):
        calls["job"] += 1
        calls["job_args"] = args
        return ToolResult(
            content="ok",
            metadata={"backend": "kubernetes", "exit_code": 0, "logs": JOB_LOGS},
        )

    monkeypatch.setattr(ca, "_load_asset", load)
    monkeypatch.setattr(ca, "_collect_secrets", secrets)
    monkeypatch.setattr(ca, "_record_last_test", record)
    monkeypatch.setattr(ca.SandboxedJobTool, "_resolve_settings", gate_settings)
    monkeypatch.setattr(ca.SandboxedJobTool, "execute", job_execute)
    monkeypatch.setenv("CODE_RUNNER_IMAGES", json.dumps({"python-3.12": "img"}))
    monkeypatch.setenv("NATS_URL", "nats://x:4222")
    return calls


def _tool():
    return ca.CodeAssetTool(tenant_id=TENANT, db_url="postgresql+asyncpg://x/y")


async def test_tool_auto_falls_back_to_job_on_no_responders(
    tool_env, warm_env, monkeypatch
):
    from nats.errors import NoRespondersError

    install, kicks = warm_env
    install([NoRespondersError()])
    monkeypatch.setenv("CODE_RUNNER_MODE", "auto")
    res = await _tool()._execute_impl({"code_asset_id": ASSET_ID, "input": {"q": 1}})
    await asyncio.sleep(0)
    assert not res.is_error, res.content
    assert json.loads(res.content) == {
        "result": {"answer": 42},
        "schema_ok": True,
        "schema_error": "",
    }
    assert (
        res.metadata["runner"] == "job" and "warming" in res.metadata["runner_reason"]
    )
    assert tool_env["job"] == 1 and len(kicks) == 1


async def test_tool_warm_result_is_shaped_like_the_job_result(
    tool_env, warm_env, monkeypatch
):
    install, _ = warm_env
    nc = install(
        [
            {
                "ok": True,
                "exit_code": 0,
                "stdout": '{"answer": 42}\n',
                "duration_ms": 7,
                "cache": "hit",
                "mode": "process",
                "runner": "pod-1",
            }
        ]
    )
    monkeypatch.setenv("CODE_RUNNER_MODE", "auto")
    warm = await _tool()._execute_impl({"code_asset_id": ASSET_ID, "input": {"q": 1}})
    await asyncio.gather(*ca._BG)
    ca._LAST_TEST_AT.clear()
    monkeypatch.setenv("CODE_RUNNER_MODE", "job")
    job = await _tool()._execute_impl({"code_asset_id": ASSET_ID, "input": {"q": 1}})
    await asyncio.gather(*ca._BG)
    assert warm.content == job.content
    assert warm.metadata["runner"] == "warm" and job.metadata["runner"] == "job"
    assert warm.metadata["cache"] == "hit" and warm.metadata["runner_pod"] == "pod-1"
    assert warm.metadata["stdout"] == job.metadata["stdout"]
    for k in (
        "code_asset_id",
        "resolved_code_asset_id",
        "exit_code",
        "image",
        "schema_ok",
    ):
        assert warm.metadata[k] == job.metadata[k], k
    assert tool_env["job"] == 1 and len(nc.sent) == 1
    assert nc.sent[0][1]["env"] == {"API_KEY": "s"}
    assert tool_env["recorded"] == [{"answer": 42}, {"answer": 42}]


async def test_tool_warm_mode_returns_errors_instead_of_falling_back(
    tool_env, warm_env, monkeypatch
):
    from nats.errors import NoRespondersError

    install, _ = warm_env
    install([NoRespondersError()])
    monkeypatch.setenv("CODE_RUNNER_MODE", "warm")
    res = await _tool()._execute_impl({"code_asset_id": ASSET_ID, "input": {}})
    assert res.is_error and res.metadata["runner"] == "warm"
    assert tool_env["job"] == 0


async def test_tool_job_mode_never_touches_nats(tool_env, warm_env, monkeypatch):
    install, _ = warm_env
    nc = install([])
    monkeypatch.setenv("CODE_RUNNER_MODE", "job")
    res = await _tool()._execute_impl({"code_asset_id": ASSET_ID, "input": {}})
    assert not res.is_error and nc.sent == [] and tool_env["job"] == 1


async def test_tool_reply_timeout_is_an_error_not_a_second_run(
    tool_env, warm_env, monkeypatch
):
    from nats.errors import TimeoutError as NatsTimeout

    install, _ = warm_env
    install([NatsTimeout()])
    monkeypatch.setenv("CODE_RUNNER_MODE", "auto")
    res = await _tool()._execute_impl({"code_asset_id": ASSET_ID, "input": {}})
    assert res.is_error and tool_env["job"] == 0


async def test_tool_warm_failure_reports_exit_code(tool_env, warm_env, monkeypatch):
    install, _ = warm_env
    install(
        [
            {
                "ok": False,
                "exit_code": 3,
                "timed_out": False,
                "stdout": "",
                "stderr_tail": "Traceback: boom",
                "duration_ms": 4,
            }
        ]
    )
    monkeypatch.setenv("CODE_RUNNER_MODE", "auto")
    res = await _tool()._execute_impl({"code_asset_id": ASSET_ID, "input": {}})
    assert res.is_error and res.metadata["exit_code"] == 3
    assert "boom" in res.content and res.content.startswith(
        "Code asset execution failed:"
    )


async def test_tool_skips_warm_when_the_sandbox_gate_says_no(
    tool_env, warm_env, monkeypatch
):
    install, _ = warm_env
    nc = install([])

    async def closed(self):
        return {"enabled": True, "allow_network": False, "allowed_images": {"other"}}

    monkeypatch.setattr(ca.SandboxedJobTool, "_resolve_settings", closed)
    monkeypatch.setenv("CODE_RUNNER_MODE", "auto")
    res = await _tool()._execute_impl({"code_asset_id": ASSET_ID, "input": {}})
    assert nc.sent == [] and "allow-list" in res.metadata["runner_reason"]


# ── kubernetes apply ─────────────────────────────────────────────────────────


class _NotFound(Exception):
    status = 404


class _Api:
    def __init__(self):
        self.calls = []
        self.deployment = None

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a, k))
            if name == "read_namespaced_deployment":
                if self.deployment is None:
                    raise _NotFound()
                return self.deployment
            if name == "create_namespaced_deployment":
                body = a[1]
                self.deployment = SimpleNamespace(
                    metadata=SimpleNamespace(name=body["metadata"]["name"], uid="u-1"),
                    spec=SimpleNamespace(replicas=body["spec"]["replicas"]),
                )
                return self.deployment
            return None

        return call


def _fake_k8s(s):
    k = object.__new__(cr.K8s)
    api = _Api()
    k.apps = k.core = k.custom = k.autoscaling = api
    k.ns, k.s = "abenix", s
    return k, api


def test_ensure_creates_secret_deployment_and_owned_scaler():
    s = _settings(keda=True, prometheus_url="http://p:9090")
    k, api = _fake_k8s(s)
    spec = cr.spec_for(_asset(), TENANT, False, s)
    assert k.ensure(spec, "tok", 1) == "created"
    names = [c[0] for c in api.calls]
    assert names.index("create_namespaced_secret") < names.index(
        "create_namespaced_deployment"
    )
    so = [c for c in api.calls if c[0] == "create_namespaced_custom_object"][0][1][4]
    assert so["kind"] == "ScaledObject" and so["spec"]["minReplicaCount"] == 1
    assert so["metadata"]["ownerReferences"][0]["uid"] == "u-1"


def test_ensure_wakes_a_runner_at_zero():
    s = _settings(keda=True, prometheus_url="http://p:9090")
    k, api = _fake_k8s(s)
    spec = cr.spec_for(_asset(), TENANT, False, s)
    k.ensure(spec, "tok", 1)
    api.deployment.spec.replicas = 0
    api.calls.clear()
    assert k.ensure(spec, "tok2", 1) == "scaled"
    assert "patch_namespaced_custom_object" in [c[0] for c in api.calls]
    scale = [c for c in api.calls if c[0] == "patch_namespaced_deployment"][-1]
    assert scale[1][2]["spec"]["replicas"] == 1
