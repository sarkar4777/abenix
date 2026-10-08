"""Cluster view: parsing, grouping, health verdict, caching, routes and RBAC."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import cluster_view as cv
from app.core.deps import get_current_user, get_db
from models.user import UserRole

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "infra/helm/abenix"
NOW = time.time()


def _ts(ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - ago))


def _node(name="n1", ready=True, pressure=(), cpu="4", mem="16Gi", taints=None):
    conds = [{"type": "Ready", "status": "True" if ready else "False"}]
    conds += [{"type": p, "status": "True"} for p in pressure]
    return {
        "metadata": {
            "name": name,
            "creationTimestamp": _ts(86400),
            "labels": {
                "node-role.kubernetes.io/control-plane": "",
                "kubernetes.azure.com/agentpool": "system",
            },
        },
        "spec": {"taints": taints or []},
        "status": {
            "capacity": {"cpu": cpu, "memory": mem, "pods": "110"},
            "allocatable": {"cpu": "3800m", "memory": "15Gi", "pods": "110"},
            "conditions": conds,
            "nodeInfo": {"kubeletVersion": "v1.30.1"},
        },
    }


def _pod(
    name,
    rs=None,
    sts=None,
    node="n1",
    ready=True,
    restarts=0,
    waiting=None,
    last=None,
    cpu_req="250m",
):
    owners = []
    labels = {}
    if rs:
        owners.append({"kind": "ReplicaSet", "name": rs})
        labels["pod-template-hash"] = rs.rsplit("-", 1)[1]
    if sts:
        owners.append({"kind": "StatefulSet", "name": sts})
    cs = {"name": "main", "ready": ready, "restartCount": restarts, "state": {}}
    if waiting:
        cs["state"] = {"waiting": {"reason": waiting}}
    if last:
        cs["lastState"] = {"terminated": last}
    return {
        "metadata": {
            "name": name,
            "ownerReferences": owners,
            "labels": labels,
            "creationTimestamp": _ts(3600),
        },
        "spec": {
            "nodeName": node,
            "containers": [
                {
                    "name": "main",
                    "resources": {"requests": {"cpu": cpu_req, "memory": "256Mi"}},
                }
            ],
        },
        "status": {"phase": "Running", "containerStatuses": [cs]},
    }


def _deploy(name, replicas=1, ready=1, updated=None, image="reg/abenix/api:abc123"):
    return {
        "metadata": {"name": name, "generation": 2, "creationTimestamp": _ts(7200)},
        "spec": {
            "replicas": replicas,
            "template": {"spec": {"containers": [{"name": "main", "image": image}]}},
        },
        "status": {
            "observedGeneration": 2,
            "readyReplicas": ready,
            "availableReplicas": ready,
            "updatedReplicas": replicas if updated is None else updated,
        },
    }


def test_parse_quantity_covers_k8s_suffixes():
    assert cv.parse_quantity("2") == 2
    assert cv.parse_quantity("250m") == 0.25
    assert cv.parse_quantity("1Gi") == 1024**3
    assert cv.parse_quantity("512Mi") == 512 * 1024**2
    assert cv.parse_quantity("123456789n") == pytest.approx(0.123456789)
    assert cv.parse_quantity("90k") == 90000
    assert cv.parse_quantity(None) == 0
    assert cv.parse_quantity("garbage") == 0


def test_image_tag():
    assert cv.image_tag("localhost:5000/abenix/api:50dc0306") == "50dc0306"
    assert cv.image_tag("nats:2.10-alpine") == "2.10-alpine"
    assert cv.image_tag("eclipse-mosquitto") == "latest"
    assert cv.image_tag("reg:5000/x@sha256:abcdef0123456789abcdef").startswith(
        "sha256:"
    )


@pytest.mark.parametrize(
    "name,group,critical",
    [
        ("abenix-api", "Core", True),
        ("abenix-web", "Core", True),
        ("abenix-worker", "Core", True),
        ("livekit-server", "Core", False),
        ("abenix-agent-runtime-default", "Runtime pools", True),
        ("abenix-agent-runtime-heavy", "Runtime pools", False),
        ("coderun-3524e84e-3a0e1a42-v4-c63420", "Runtime pools", False),
        ("abenix-postgresql", "Data", True),
        ("abenix-redis-master", "Data", True),
        ("abenix-nats", "Data", True),
        ("abenix-mosquitto", "Data", False),
        ("contractiq-api", "Apps", False),
        ("wingman-web", "Apps", False),
    ],
)
def test_classify_groups_services(name, group, critical):
    got = cv.classify(name, "abenix")
    assert got["group"] == group
    assert got["critical"] is critical


def test_nodes_carry_capacity_usage_pressure_and_pods():
    nodes = cv.build_nodes(
        [
            _node(
                pressure=("MemoryPressure",),
                taints=[{"key": "k", "effect": "NoSchedule"}],
            )
        ],
        [{"metadata": {"name": "n1"}, "usage": {"cpu": "1900m", "memory": "3Gi"}}],
        [
            _pod("api-abc12-x", rs="abenix-api-abc12"),
            _pod("pg-0", sts="abenix-postgresql"),
        ],
        NOW,
    )
    n = nodes[0]
    assert n["cpu_cores"] == 4 and n["cpu_allocatable_cores"] == 3.8
    assert n["cpu_pct"] == 50.0
    assert n["mem_used_bytes"] == 3 * 1024**3
    assert n["pressure"] == ["MemoryPressure"]
    assert n["pods_here"] == 2 and n["pods_capacity"] == 110
    assert n["cpu_requested_cores"] == 0.5
    assert n["roles"] == ["control-plane"] and n["pool"] == "system"
    assert n["taints"][0]["effect"] == "NoSchedule"
    assert n["kubelet_version"] == "v1.30.1"
    assert n["age_seconds"] >= 86000


def test_nodes_without_metrics_report_none_not_zero():
    n = cv.build_nodes([_node()], [], [], NOW)[0]
    assert n["cpu_used_cores"] is None and n["cpu_pct"] is None


def _workloads(deploys, pods, sts=(), scaling=None):
    return cv.build_workloads(
        list(deploys), list(sts), [], list(pods), [], scaling or {}, NOW, "abenix"
    )


def test_pods_map_to_their_workload_and_restarts_roll_up():
    oom = {"reason": "OOMKilled", "exitCode": 137, "finishedAt": _ts(120)}
    ws = _workloads(
        [_deploy("abenix-api"), _deploy("abenix-worker")],
        [
            _pod("abenix-api-7d9f-x1", rs="abenix-api-7d9f", restarts=3, last=oom),
            _pod("abenix-worker-55aa-y1", rs="abenix-worker-55aa"),
        ],
    )
    api = next(w for w in ws if w["name"] == "abenix-api")
    assert [p["name"] for p in api["pods"]] == ["abenix-api-7d9f-x1"]
    assert api["restarts"] == 3
    assert api["last_restart"]["reason"] == "OOMKilled"
    assert api["image_tag"] == "abc123"
    assert api["status"] == "healthy"


def test_workload_status_reads_plainly():
    ws = _workloads(
        [
            _deploy("abenix-api", replicas=1, ready=0),
            _deploy("abenix-web", replicas=2, ready=1),
            _deploy("coderun-a-b", replicas=0, ready=0),
            _deploy("abenix-worker", replicas=2, ready=1, updated=1),
        ],
        [
            _pod(
                "abenix-api-1a2b-z",
                rs="abenix-api-1a2b",
                ready=False,
                waiting="CrashLoopBackOff",
            )
        ],
    )
    by = {w["name"]: w for w in ws}
    assert by["abenix-api"]["status"] == "down"
    assert "keeps crashing" in by["abenix-api"]["status_text"]
    assert by["abenix-web"]["status"] == "degraded"
    assert by["coderun-a-b"]["status"] == "idle"
    assert by["abenix-worker"]["status"] == "progressing"
    # core first, critical before the rest
    assert ws[0]["group"] == "Core"


def test_statefulset_pods_map():
    ws = _workloads(
        [],
        [_pod("abenix-nats-0", sts="abenix-nats")],
        sts=[_deploy("abenix-nats", image="nats:2.10-alpine")],
    )
    assert (
        ws[0]["kind"] == "StatefulSet" and ws[0]["pods"][0]["name"] == "abenix-nats-0"
    )
    assert ws[0]["group"] == "Data"


def test_keda_scaling_reads_queue_depth():
    so = {
        "metadata": {"name": "abenix-agent-runtime-default"},
        "spec": {
            "minReplicaCount": 1,
            "maxReplicaCount": 8,
            "scaleTargetRef": {"name": "abenix-agent-runtime-default"},
            "triggers": [
                {"type": "nats-jetstream", "metadata": {"stream": "agents"}},
                {
                    "type": "prometheus",
                    "metadata": {"metricName": "abenix_execution_p95_ms"},
                },
            ],
        },
        "status": {
            "hpaName": "keda-hpa-abenix-agent-runtime-default",
            "conditions": [
                {"type": "Active", "status": "True"},
                {"type": "Paused", "status": "False"},
            ],
        },
    }
    hpa = {
        "metadata": {"name": "keda-hpa-abenix-agent-runtime-default"},
        "spec": {
            "minReplicas": 1,
            "maxReplicas": 8,
            "scaleTargetRef": {
                "kind": "Deployment",
                "name": "abenix-agent-runtime-default",
            },
            "metrics": [
                {
                    "type": "External",
                    "external": {
                        "metric": {"name": "s0-nats-jetstream-agents"},
                        "target": {"averageValue": "3"},
                    },
                },
                {
                    "type": "External",
                    "external": {
                        "metric": {"name": "s1-prometheus"},
                        "target": {"averageValue": "90k"},
                    },
                },
            ],
        },
        "status": {
            "currentReplicas": 3,
            "desiredReplicas": 4,
            "currentMetrics": [
                {
                    "type": "External",
                    "external": {
                        "metric": {"name": "s0-nats-jetstream-agents"},
                        "current": {"averageValue": "12"},
                    },
                },
            ],
        },
    }
    s = cv.build_scaling([hpa], [so])[("Deployment", "abenix-agent-runtime-default")]
    assert s["kind"] == "keda" and s["min"] == 1 and s["max"] == 8
    assert s["current"] == 3 and s["desired"] == 4 and s["active"] is True
    q = s["metrics"][0]
    assert (
        q["label"] == "Queue backlog (agents)"
        and q["current"] == "12"
        and q["target"] == "3"
    )
    assert (
        s["metrics"][1]["label"] == "p95 run time (ms)"
        and s["metrics"][1]["current"] is None
    )


def test_plain_hpa_cpu():
    hpa = {
        "metadata": {"name": "x"},
        "spec": {
            "minReplicas": 1,
            "maxReplicas": 2,
            "scaleTargetRef": {"kind": "Deployment", "name": "coderun-a"},
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {"name": "cpu", "target": {"averageUtilization": 70}},
                }
            ],
        },
        "status": {"currentReplicas": 0},
    }
    s = cv.build_scaling([hpa], [])[("Deployment", "coderun-a")]
    assert s["kind"] == "hpa" and s["metrics"][0]["target"] == "70%"
    assert s["metrics"][0]["label"] == "CPU use"


def test_events_window_and_workload_link():
    ws = _workloads(
        [_deploy("abenix-api")], [_pod("abenix-api-1a2b-z", rs="abenix-api-1a2b")]
    )
    evs = cv.build_events(
        [
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": "back-off",
                "count": 4,
                "involvedObject": {"kind": "Pod", "name": "abenix-api-1a2b-z"},
                "lastTimestamp": _ts(60),
            },
            {
                "type": "Warning",
                "reason": "Unhealthy",
                "involvedObject": {"kind": "Pod", "name": "abenix-api-9f9f-gone"},
                "lastTimestamp": _ts(120),
            },
            {
                "type": "Warning",
                "reason": "Old",
                "involvedObject": {"kind": "Pod", "name": "x"},
                "lastTimestamp": _ts(7200),
            },
        ],
        ws,
        NOW,
    )
    assert [e["reason"] for e in evs] == ["BackOff", "Unhealthy"]
    assert evs[0]["workload"] == "abenix-api" and evs[0]["count"] == 4
    assert evs[1]["workload"] == "abenix-api"


def test_verdict_levels():
    nodes = cv.build_nodes([_node()], [], [], NOW)
    healthy = _workloads([_deploy("abenix-api")], [])
    v = cv.verdict("in-cluster", nodes, healthy, [], {}, NOW)
    assert v["state"] == "healthy" and v["reasons"][0]["level"] == "ok"

    down = _workloads([_deploy("abenix-api", ready=0)], [])
    v = cv.verdict("in-cluster", nodes, down, [], {}, NOW)
    assert v["state"] == "critical" and "api is down" in v["reasons"][0]["text"]

    app_down = _workloads([_deploy("wingman-api", ready=0)], [])
    assert cv.verdict("in-cluster", nodes, app_down, [], {}, NOW)["state"] == "degraded"

    sick = cv.build_nodes([_node(ready=False, pressure=("DiskPressure",))], [], [], NOW)
    v = cv.verdict("in-cluster", sick, healthy, [], {}, NOW)
    assert v["state"] == "critical"
    assert any("low on disk" in r["text"] for r in v["reasons"])

    v = cv.verdict("outside", [], [], [], {}, NOW)
    assert (
        v["state"] == "unknown"
        and "not running inside a cluster" in v["reasons"][0]["text"]
    )

    blind = {k: {"state": "forbidden"} for k in ("pods", "deployments", "statefulsets")}
    assert cv.verdict("in-cluster", nodes, [], [], blind, NOW)["state"] == "degraded"


def test_verdict_mentions_recent_oom():
    oom = {"reason": "OOMKilled", "exitCode": 137, "finishedAt": _ts(240)}
    ws = _workloads(
        [_deploy("abenix-worker")],
        [_pod("abenix-worker-1a2b-q", rs="abenix-worker-1a2b", restarts=1, last=oom)],
    )
    v = cv.verdict("in-cluster", [], ws, [], {}, NOW)
    assert v["state"] == "degraded"
    assert any("ran out of memory" in r["text"] for r in v["reasons"])


def test_access_report_names_the_helm_value(monkeypatch):
    monkeypatch.setenv("CLUSTER_VIEW_RBAC", "false")
    rows = cv.access_report(
        {"nodes": {"state": "forbidden"}, "node_metrics": {"state": "not_installed"}}
    )
    by = {r["key"]: r for r in rows}
    assert by["pods"]["ok"] is True
    assert "clusterView.rbac.enabled is false" in by["nodes"]["fix"]
    assert "metrics-server" in by["node_metrics"]["fix"]
    monkeypatch.setenv("CLUSTER_VIEW_RBAC", "true")
    assert (
        "clusterView.rbac.enabled=true"
        in cv.access_report({"nodes": {"state": "forbidden"}})[0]["fix"]
    )


def test_classify_error():
    e = Exception("x")
    e.status = 403
    assert cv.classify_error(e)["state"] == "forbidden"
    e.status = 404
    assert cv.classify_error(e)["state"] == "not_installed"
    assert cv.classify_error(Exception("timed out"))["state"] == "unreachable"


def test_cache_is_single_flight():
    cache = cv.TTLCache()
    calls = 0

    async def produce():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    async def run():
        res = await asyncio.gather(*[cache.get("k", 10, produce) for _ in range(20)])
        again = await cache.get("k", 10, produce)
        return res, again

    res, again = asyncio.run(run())
    assert calls == 1
    assert {r[0] for r in res} == {1} and again[0] == 1


def test_history_falls_back_to_memory(monkeypatch):
    h = cv.History()

    async def none():
        return None

    monkeypatch.setattr(h, "_client", none)
    ws = [{"name": "abenix-api", "ready": 1, "desired": 2}]
    pts = asyncio.run(h.record(ws, NOW))
    cv.attach_history(ws, pts)
    assert ws[0]["history"] == [{"t": int(NOW), "ready": 1, "desired": 2}]


def test_pod_detail_lists_containers_and_events():
    pod = _pod(
        "abenix-api-1a2b-z",
        rs="abenix-api-1a2b",
        restarts=2,
        last={"reason": "Error", "exitCode": 1, "finishedAt": _ts(30)},
    )
    pod["spec"]["containers"][0]["image"] = "reg/api:abc"
    d = cv.build_pod_detail(
        pod,
        [
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": "m",
                "lastTimestamp": _ts(10),
            }
        ],
        NOW,
    )
    assert d["owner"] == "abenix-api" and d["owner_kind"] == "Deployment"
    assert d["containers"][0]["tag"] == "abc"
    assert d["containers"][0]["last_termination"]["exit_code"] == 1
    assert d["events"][0]["reason"] == "BackOff"


def test_pod_name_validation():
    assert cv.valid_pod_name("abenix-api-7d9f-x1")
    assert not cv.valid_pod_name("../etc")
    assert not cv.valid_pod_name("Bad Name")
    assert not cv.valid_pod_name("")


# ---- routes ----


def _client(role=UserRole.ADMIN):
    from app.routers import admin_cluster

    app = FastAPI()
    app.include_router(admin_cluster.router)
    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=role, is_admin=False
    )

    async def _user():
        return user

    async def _db():
        yield SimpleNamespace()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_overview_route_is_cached(monkeypatch):
    cv.CACHE.clear()
    calls = 0

    async def fake():
        nonlocal calls
        calls += 1
        return {
            "nodes": [],
            "workloads": [],
            "verdict": {"state": "healthy"},
            "grafana_hint": "http://localhost:3030",
        }

    monkeypatch.setattr(cv, "build_overview", fake)
    c = _client()
    r1 = c.get("/api/admin/cluster/overview")
    r2 = c.get("/api/admin/cluster/overview")
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls == 1
    assert "cache_age_seconds" in r2.json()["data"]
    assert r2.json()["data"]["grafana_url"] == "http://localhost:3030"
    assert "grafana_hint" not in r2.json()["data"]
    cv.CACHE.clear()


def test_non_admin_is_refused():
    c = _client(UserRole.USER)
    for path in (
        "/api/admin/cluster/overview",
        "/api/admin/cluster/pods/x",
        "/api/admin/cluster/pods/x/logs",
    ):
        assert c.get(path).status_code == 403


def test_bad_pod_name_and_outside_cluster(monkeypatch):
    c = _client()
    r = c.get("/api/admin/cluster/pods/Bad%20Name")
    assert r.status_code == 400
    monkeypatch.setattr(cv.K8S, "load", lambda: False)
    r = c.get("/api/admin/cluster/pods/abenix-api-x/logs")
    assert (
        r.status_code == 409 and r.json()["error"]["error_code"] == "NOT_IN_KUBERNETES"
    )
    r = c.get("/api/admin/cluster/pods/abenix-api-x/logs?lines=99999")
    assert r.status_code == 422


# ---- helm ----

helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render(*sets: str) -> list[dict]:
    cmd = ["helm", "template", "abenix", str(CHART), "-n", "abenix"]
    for s in sets:
        cmd += ["--set", s]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [
        d
        for d in yaml.safe_load_all(out)
        if d and "cluster-view" in d["metadata"]["name"]
    ]


@helm
def test_rbac_is_read_only_and_on_by_default():
    docs = _render("clusterView.rbac.metrics=true", "clusterView.rbac.keda=true")
    kinds = sorted(d["kind"] for d in docs)
    assert kinds == ["ClusterRole", "ClusterRoleBinding", "Role", "RoleBinding"]
    for d in docs:
        for rule in d.get("rules") or []:
            assert set(rule["verbs"]) <= {"get", "list", "watch"}
            assert "secrets" not in rule["resources"]
            assert "configmaps" not in rule["resources"]
    cluster = next(d for d in docs if d["kind"] == "ClusterRole")
    res = {r for rule in cluster["rules"] for r in rule["resources"]}
    assert res == {"nodes", "namespaces"}
    role = next(d for d in docs if d["kind"] == "Role")
    res = {r for rule in role["rules"] for r in rule["resources"]}
    assert {
        "pods",
        "pods/log",
        "events",
        "deployments",
        "replicasets",
        "horizontalpodautoscalers",
        "scaledobjects",
    } <= res
    binding = next(d for d in docs if d["kind"] == "RoleBinding")
    assert binding["subjects"][0]["name"] == "default"


@helm
def test_rbac_can_be_switched_off():
    assert _render("clusterView.rbac.enabled=false") == []


def test_events_group_per_reason_and_service_and_summarise():
    ws = _workloads(
        [_deploy("abenix-api"), _deploy("abenix-web")],
        [_pod("abenix-api-1a2b-z", rs="abenix-api-1a2b")],
    )
    raw = [
        {
            "type": "Warning",
            "reason": "Unhealthy",
            "message": f"Readiness probe failed {i}",
            "involvedObject": {"kind": "Pod", "name": f"abenix-api-1a2b-p{i}"},
            "lastTimestamp": _ts(30 + i),
        }
        for i in range(4)
    ] + [
        {
            "type": "Warning",
            "reason": "Unhealthy",
            "involvedObject": {"kind": "Pod", "name": "abenix-web-9z9z-q"},
            "lastTimestamp": _ts(90),
            "count": 2,
        }
    ]
    evs = cv.build_events(raw, ws, NOW)
    assert len(evs) == 2
    api = next(e for e in evs if e["workload"] == "abenix-api")
    assert api["count"] == 4 and api["objects"] == 4
    assert api["message"] == "Readiness probe failed 0"
    text = cv.events_summary(evs)
    assert text == (
        "6 warning events in the last 15 minutes, mostly failed health probes"
        " across 2 services."
    )
    v = cv.verdict("in-cluster", [], ws, evs, {}, NOW)
    assert v["state"] == "healthy"
    assert v["reasons"][0]["level"] == "ok"
    assert "2 services running" in v["reasons"][0]["text"]


def test_strip_ansi_from_log_lines():
    line = "\x1b[2m2026\x1b[0m [\x1b[32m\x1b[1minfo     \x1b[0m] http_request"
    assert cv.strip_ansi(line) == "2026 [info     ] http_request"


def test_logs_route_decodes_raw_body(monkeypatch):
    class Resp:
        data = b"2026-10-08T10:00:00Z \x1b[32mone\x1b[0m\n2026-10-08T10:00:01Z two\n"

        def release_conn(self):
            pass

    class Core:
        def read_namespaced_pod_log(self, name, ns, **kw):
            assert kw["_preload_content"] is False and kw["tail_lines"] == 50
            return Resp()

    async def no_audit(*a, **k):
        return None

    cv.CACHE.clear()
    monkeypatch.setattr(cv.K8S, "load", lambda: True)
    monkeypatch.setattr(cv.K8S, "core", Core())
    from app.routers import admin_cluster

    monkeypatch.setattr(admin_cluster, "log_action", no_audit)
    r = _client().get("/api/admin/cluster/pods/abenix-api-x/logs?lines=50")
    assert r.status_code == 200
    assert r.json()["data"]["lines"] == [
        "2026-10-08T10:00:00Z one",
        "2026-10-08T10:00:01Z two",
    ]
    cv.CACHE.clear()
