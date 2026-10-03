"""With networkPolicy.enabled the platform's own traffic still flows.

Renders the chart with helm and evaluates every NetworkPolicy the way the
cluster would: a flow passes when the source's egress and the destination's
ingress both allow it (or no policy of that type selects the pod).
"""

from __future__ import annotations

import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "infra/helm/abenix"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)

NS = "abenix"
API = {"app.kubernetes.io/name": "api", "app.kubernetes.io/instance": "abenix"}
WEB = {"app.kubernetes.io/name": "web", "app.kubernetes.io/instance": "abenix"}
WORKER = {"app.kubernetes.io/name": "worker", "app.kubernetes.io/instance": "abenix"}
COGNIFY = {
    "app.kubernetes.io/name": "abenix",
    "app.kubernetes.io/instance": "abenix",
    "app.kubernetes.io/component": "cognify-worker",
}
RUNTIME = {"app.kubernetes.io/name": "agent-runtime", "abenix.io/pool": "default"}
POSTGRES = {
    "app.kubernetes.io/name": "postgresql",
    "app.kubernetes.io/instance": "abenix",
    "app.kubernetes.io/component": "primary",
}
POSTGRES_READ = {**POSTGRES, "app.kubernetes.io/component": "read"}
REDIS = {
    "app.kubernetes.io/name": "redis",
    "app.kubernetes.io/instance": "abenix",
    "app.kubernetes.io/component": "master",
}
NEO4J = {"app.kubernetes.io/name": "neo4j", "app.kubernetes.io/instance": "abenix"}
NATS = {"app.kubernetes.io/name": "nats"}
RUNNER = {"app": "abenix-code-runner", "abenix.io/network": "none"}
REAPER = {"app.kubernetes.io/name": "code-runner-reaper"}
BACKUP = {
    "app.kubernetes.io/name": "abenix",
    "app.kubernetes.io/instance": "abenix",
    "app.kubernetes.io/component": "backup",
}
PROMETHEUS = {"app": "abenix-prometheus"}
ALERTMANAGER = {
    "app.kubernetes.io/name": "alertmanager",
    "app.kubernetes.io/instance": "abenix",
}
TEMPO = {"app": "abenix-tempo"}
STANDALONE = {"app": "contractiq-api"}

FLOWS = [
    (API, POSTGRES, 5432),
    (API, REDIS, 6379),
    (API, NEO4J, 7687),
    (API, NATS, 4222),
    (API, RUNTIME, 8001),
    (API, PROMETHEUS, 9090),
    (API, ALERTMANAGER, 9093),
    (API, TEMPO, 4317),
    (RUNTIME, POSTGRES, 5432),
    (RUNTIME, REDIS, 6379),
    (RUNTIME, NEO4J, 7687),
    (RUNTIME, NATS, 4222),
    (RUNTIME, API, 8000),
    (RUNTIME, TEMPO, 4317),
    (WORKER, POSTGRES, 5432),
    (WORKER, REDIS, 6379),
    (WORKER, NEO4J, 7687),
    (WORKER, API, 8000),
    (COGNIFY, POSTGRES, 5432),
    (COGNIFY, REDIS, 6379),
    (COGNIFY, NEO4J, 7687),
    (WEB, API, 8000),
    (RUNNER, API, 8000),
    (RUNNER, NATS, 4222),
    (REAPER, POSTGRES, 5432),
    (REAPER, REDIS, 6379),
    (BACKUP, POSTGRES, 5432),
    (POSTGRES_READ, POSTGRES, 5432),
    (PROMETHEUS, API, 8000),
    (PROMETHEUS, RUNTIME, 8001),
    (PROMETHEUS, NATS, 8222),
    (ALERTMANAGER, API, 8000),
    (STANDALONE, API, 8000),
]

BLOCKED = [
    (WEB, POSTGRES, 5432),
    (RUNNER, POSTGRES, 5432),
    (STANDALONE, REDIS, 6379),
    (API, {"app": "some-internal-service"}, 8080),
]


def _render(values_file: str, *sets: str) -> list[dict]:
    cmd = [
        "helm",
        "template",
        "abenix",
        str(CHART),
        "-n",
        NS,
        "-f",
        str(CHART / values_file),
    ]
    for s in ("networkPolicy.enabled=true", *sets):
        cmd += ["--set", s]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _selects(selector: dict, labels: dict) -> bool:
    for k, v in (selector.get("matchLabels") or {}).items():
        if labels.get(k) != v:
            return False
    for expr in selector.get("matchExpressions") or []:
        val = labels.get(expr["key"])
        if expr["operator"] == "In" and val not in expr["values"]:
            return False
        if expr["operator"] == "NotIn" and val in expr["values"]:
            return False
        if expr["operator"] == "Exists" and expr["key"] not in labels:
            return False
    return True


def _peer_matches(peer: dict, labels: dict) -> bool:
    if "ipBlock" in peer:
        return False
    # Every test pod lives in the release namespace
    return _selects(peer.get("podSelector") or {}, labels)


def _port_matches(rule: dict, port: int) -> bool:
    ports = rule.get("ports")
    return not ports or any(p.get("port") == port for p in ports)


def _allowed(policies, kind, pod, peer, port) -> bool:
    key = "egress" if kind == "Egress" else "ingress"
    side = "to" if kind == "Egress" else "from"
    applicable = [
        p
        for p in policies
        if kind in p["spec"].get("policyTypes", [])
        and _selects(p["spec"]["podSelector"], pod)
    ]
    if not applicable:
        return True
    for p in applicable:
        for rule in p["spec"].get(key) or []:
            peers = rule.get(side)
            if _port_matches(rule, port) and (
                not peers or any(_peer_matches(x, peer) for x in peers)
            ):
                return True
    return False


def _flow_ok(policies, src, dst, port) -> bool:
    return _allowed(policies, "Egress", src, dst, port) and _allowed(
        policies, "Ingress", dst, src, port
    )


@pytest.mark.parametrize(
    "values_file", ["values-local.yaml", "values-azure.yaml", "values-production.yaml"]
)
def test_platform_traffic_flows_with_policies_on(values_file):
    docs = _render(values_file, "scaling.queueBackend=nats")
    policies = [d for d in docs if d["kind"] == "NetworkPolicy"]
    names = Counter(p["metadata"]["name"] for p in policies)
    assert not [
        n for n, c in names.items() if c > 1
    ], f"duplicate NetworkPolicy names: {names}"
    broken = [
        (s, d, port) for s, d, port in FLOWS if not _flow_ok(policies, s, d, port)
    ]
    assert not broken, "\n".join(f"{s} -> {d}:{port}" for s, d, port in broken)


def test_production_keeps_the_data_stores_closed():
    # Production turns off bitnami's admit-all policies so these rules are the ones enforced
    docs = _render("values-production.yaml", "scaling.queueBackend=nats")
    policies = [d for d in docs if d["kind"] == "NetworkPolicy"]
    bitnami = {"abenix-postgresql", "abenix-postgresql-read", "abenix-redis"}
    assert not bitnami & {p["metadata"]["name"] for p in policies}
    leaks = [(s, d, port) for s, d, port in BLOCKED if _flow_ok(policies, s, d, port)]
    assert not leaks, "\n".join(f"{s} -> {d}:{port}" for s, d, port in leaks)


def test_kube_api_rule_only_when_configured():
    def api_policy(docs):
        return next(
            d
            for d in docs
            if d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "abenix-api"
        )

    plain = api_policy(_render("values-local.yaml"))
    assert not any(
        peer.get("ipBlock", {}).get("cidr") == "192.168.49.2/32"
        for r in plain["spec"]["egress"]
        for peer in r["to"]
    )
    with_api = api_policy(
        _render(
            "values-local.yaml", "networkPolicy.kubeApiServer.cidrs={192.168.49.2/32}"
        )
    )
    rule = next(
        r
        for r in with_api["spec"]["egress"]
        if any(p.get("ipBlock", {}).get("cidr") == "192.168.49.2/32" for p in r["to"])
    )
    assert {p["port"] for p in rule["ports"]} == {443, 6443, 8443}
