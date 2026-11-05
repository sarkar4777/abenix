"""The three edge charts render to what the runtimes need, and refuse what they cannot run."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHARTS = ["edge-runtime", "edge-runtime-rust", "edge-runtime-c"]
PEM = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----"
helm = shutil.which("helm")
needs_helm = pytest.mark.skipif(not helm, reason="helm is not installed")


def run(chart: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [helm, "template", "rel", str(ROOT / "infra/helm" / chart), *args],
        capture_output=True,
        text=True,
    )


def render(chart: str, *args: str) -> dict[str, dict]:
    out = run(chart, "--set-string", f"signing_pubkey={PEM}", *args)
    assert out.returncode == 0, out.stderr
    return {d["kind"]: d for d in yaml.safe_load_all(out.stdout) if d}


def env_of(docs: dict) -> dict[str, dict]:
    c = docs["StatefulSet"]["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e for e in c["env"]}


@needs_helm
@pytest.mark.parametrize("chart", CHARTS)
def test_lint_passes(chart):
    out = subprocess.run(
        [
            helm,
            "lint",
            str(ROOT / "infra/helm" / chart),
            "--set-string",
            f"signing_pubkey={PEM}",
        ],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr


@needs_helm
@pytest.mark.parametrize("chart", CHARTS)
def test_defaults_are_secure_and_local(chart):
    docs = render(chart)
    env = env_of(docs)
    assert env["EDGE_ALLOW_UNSIGNED"]["value"] == "false"
    assert env["EDGE_ALLOW_NO_AUTH"]["value"] == "false"
    assert env["EDGE_ENABLE_CODE_EXECUTOR"]["value"] == "false"
    assert env["EDGE_AUTH_TOKEN"]["valueFrom"]["secretKeyRef"]["key"] == "auth_token"
    assert len(docs["Secret"]["stringData"]["auth_token"]) >= 32
    image = docs["StatefulSet"]["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image.startswith("localhost:5000/abenix/") and "agentforge" not in image
    pod = docs["StatefulSet"]["spec"]["template"]["spec"]
    sec = pod["containers"][0]["securityContext"]
    assert sec["readOnlyRootFilesystem"] and not sec["allowPrivilegeEscalation"]
    assert {v["name"] for v in pod["volumes"]} >= {"tmp", "signing"}


@needs_helm
@pytest.mark.parametrize("chart", CHARTS)
def test_no_key_refused_unless_literally_allowed(chart):
    out = run(chart)
    assert out.returncode != 0 and "signing_pubkey is required" in out.stderr
    out = run(chart, "--set-string", "allow_unsigned=yes")
    assert out.returncode != 0
    ok = run(chart, "--set", "allow_unsigned=true")
    assert ok.returncode == 0, ok.stderr
    assert "EDGE_ALLOW_UNSIGNED" in ok.stdout


@needs_helm
@pytest.mark.parametrize("chart", CHARTS)
def test_values_reach_the_pod(chart):
    docs = render(
        chart,
        "--set",
        "mqtt_url=mqtt://b:1883",
        "--set",
        "tenant_id=t1",
        "--set",
        "auth_token=zzsecretzz",
        "--set",
        "code_executor_enabled=true",
        "--set",
        "anthropic_base_url=http://lan:8000",
    )
    env = env_of(docs)
    assert env["MQTT_URL"]["value"] == "mqtt://b:1883"
    assert env["TENANT_ID"]["value"] == "t1"
    assert env["EDGE_ENABLE_CODE_EXECUTOR"]["value"] == "true"
    assert env["ANTHROPIC_BASE_URL"]["value"] == "http://lan:8000"
    assert docs["Secret"]["stringData"]["auth_token"] == "zzsecretzz"
    assert "zzsecretzz" not in str(env)


@needs_helm
@pytest.mark.parametrize("chart", CHARTS)
def test_existing_llm_secret(chart):
    env = env_of(
        render(
            chart,
            "--set",
            "existing_llm_secret.name=abenix-secrets",
            "--set",
            "existing_llm_secret.api_key_key=ANTHROPIC_API_KEY",
        )
    )
    ref = env["ANTHROPIC_API_KEY"]["valueFrom"]["secretKeyRef"]
    assert ref == {
        "name": "abenix-secrets",
        "key": "ANTHROPIC_API_KEY",
        "optional": True,
    }
    assert (
        env["ANTHROPIC_AUTH_TOKEN"]["valueFrom"]["secretKeyRef"]["key"]
        == "anthropic_auth_token"
    )


@needs_helm
@pytest.mark.parametrize("chart", CHARTS)
def test_persistence_off_renders(chart):
    docs = render(chart, "--set", "persistence.enabled=false")
    sts = docs["StatefulSet"]["spec"]
    assert "volumeClaimTemplates" not in sts
    assert any(
        v["name"] == "bundles" and "emptyDir" in v
        for v in sts["template"]["spec"]["volumes"]
    )


@needs_helm
@pytest.mark.parametrize("chart", CHARTS)
def test_a_new_token_rolls_the_pod(chart):
    a = render(chart, "--set", "auth_token=one")["StatefulSet"]
    b = render(chart, "--set", "auth_token=two")["StatefulSet"]
    key = "checksum/config"
    assert (
        a["spec"]["template"]["metadata"]["annotations"][key]
        != b["spec"]["template"]["metadata"]["annotations"][key]
    )


@needs_helm
@pytest.mark.parametrize("chart", ["edge-runtime-rust", "edge-runtime-c"])
def test_small_runtimes_have_no_gateway_mode(chart):
    out = run(chart, "--set-string", f"signing_pubkey={PEM}", "--set", "mode=gateway")
    assert out.returncode != 0 and "infra/helm/edge-runtime" in out.stderr


@needs_helm
def test_unknown_mode_is_refused():
    out = run("edge-runtime", "--set", "mode=both")
    assert out.returncode != 0 and "mode must be" in out.stderr


@needs_helm
def test_legacy_mode_runs_the_runtime():
    env = env_of(render("edge-runtime"))
    assert env["EDGE_MODE"]["value"] == "legacy"
    assert "ABENIX_URL" not in env and "PLATFORM_URL" in env
    assert env["BUNDLE_DIR"]["value"] == "/var/edge/agents"


@needs_helm
def test_gateway_mode_runs_abenix_edge_with_a_persistent_buffer():
    out = run(
        "edge-runtime",
        "--set",
        "mode=gateway",
        "--set",
        "enroll_token=etk_x",
        "--set-json",
        'collectors=[{"id":"t","type":"file_tail","path":"/d/*.csv"}]',
        "--set-json",
        'extra_containers=[{"name":"sim","image":"x"}]',
    )
    assert out.returncode == 0, out.stderr
    docs = {d["kind"]: d for d in yaml.safe_load_all(out.stdout) if d}
    env = env_of(docs)
    assert env["EDGE_MODE"]["value"] == "gateway"
    assert (
        env["ABENIX_ENROLL_TOKEN"]["valueFrom"]["secretKeyRef"]["key"] == "enroll_token"
    )
    assert env["ABENIX_EDGE_DATA"]["value"] == "/var/lib/abenix-edge"
    assert env["BUNDLE_DIR"]["value"] == "/var/lib/abenix-edge/agents"
    assert env["ABENIX_EDGE_COLLECTORS_FILE"]["value"].endswith("collectors.json")
    assert "PLATFORM_TOKEN" not in env
    sts = docs["StatefulSet"]["spec"]
    assert sts["volumeClaimTemplates"][0]["metadata"]["name"] == "data"
    pod = sts["template"]["spec"]
    assert {"name": "data", "mountPath": "/var/lib/abenix-edge"} in pod["containers"][
        0
    ]["volumeMounts"]
    assert [c["name"] for c in pod["containers"]] == ["edge-runtime", "sim"]
    assert '"file_tail"' in docs["Secret"]["stringData"]["collectors.json"]
