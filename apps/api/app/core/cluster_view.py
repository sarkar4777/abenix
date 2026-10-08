"""Cluster view: read-only snapshot of nodes, workloads, scaling and events."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

SA_NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
HELM_VALUE = "clusterView.rbac.enabled"
OVERVIEW_TTL = 10.0
POD_TTL = 5.0
LOG_TTL = 3.0
HISTORY_POINTS = 90
HISTORY_EVERY = 15.0
EVENT_WINDOW = 3600
RECENT_WINDOW = 900
MAX_LOG_LINES = 2000
POD_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")


def namespace() -> str:
    ns = os.environ.get("KUBERNETES_NAMESPACE", "").strip()
    if ns:
        return ns
    try:
        with open(SA_NAMESPACE_FILE, encoding="utf-8") as f:
            return f.read().strip() or "abenix"
    except OSError:
        return "abenix"


def release() -> str:
    return os.environ.get("HELM_RELEASE", "").strip() or "abenix"


def rbac_value() -> str | None:
    v = os.environ.get("CLUSTER_VIEW_RBAC", "").strip().lower()
    return v or None


def parse_quantity(q: Any) -> float:
    if q is None or q == "":
        return 0.0
    s = str(q).strip()
    units = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "Pi": 1024**5,
        "k": 1e3,
        "K": 1e3,
        "M": 1e6,
        "G": 1e9,
        "T": 1e12,
    }
    try:
        for suf in ("Ki", "Mi", "Gi", "Ti", "Pi"):
            if s.endswith(suf):
                return float(s[:-2]) * units[suf]
        # divide for the small suffixes so 3800m is exactly 3.8
        small = {"n": 1e9, "u": 1e6, "m": 1e3}
        if s[-1] in small:
            return float(s[:-1]) / small[s[-1]]
        if s[-1] in units:
            return float(s[:-1]) * units[s[-1]]
        return float(s)
    except (ValueError, IndexError):
        return 0.0


def parse_time(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso(v: Any) -> str | None:
    t = parse_time(v)
    return t.isoformat() if t else None


def age_seconds(v: Any, now: float) -> int | None:
    t = parse_time(v)
    return max(0, int(now - t.timestamp())) if t else None


def plain_ago(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 90:
        return "just now" if s < 30 else "a minute ago"
    if s < 3600:
        return f"{s // 60} minutes ago"
    if s < 7200:
        return "an hour ago"
    if s < 86400:
        return f"{s // 3600} hours ago"
    return f"{s // 86400} days ago"


def image_tag(image: str) -> str:
    ref = image.split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1]
    if "@" in image:
        return image.split("@", 1)[1][:19]
    return last.split(":", 1)[1] if ":" in last else "latest"


# ---- service grouping ----

GROUPS = ("Core", "Runtime pools", "Data", "Apps")
_CORE = {
    "api": True,
    "web": True,
    "worker": True,
    "cognify-worker": False,
    "livekit-server": False,
    "livekit": False,
    "prometheus": False,
    "grafana": False,
    "alertmanager": False,
}
_DATA = {
    "postgresql": True,
    "postgresql-primary": True,
    "postgresql-read": False,
    "redis-master": True,
    "redis": True,
    "redis-replicas": False,
    "nats": True,
    "neo4j": False,
    "timescaledb": False,
    "mosquitto": False,
}


def classify(name: str, rel: str | None = None) -> dict[str, Any]:
    rel = rel or release()
    base = name[len(rel) + 1 :] if name.startswith(f"{rel}-") else name
    if base in _CORE:
        return {"group": "Core", "display": base, "critical": _CORE[base]}
    if base in _DATA:
        return {"group": "Data", "display": base, "critical": _DATA[base]}
    if base.startswith("agent-runtime"):
        pool = base[len("agent-runtime-") :] or "default"
        return {
            "group": "Runtime pools",
            "display": f"agent-runtime · {pool}",
            "critical": pool == "default",
        }
    if base.startswith(("coderun-", "code-runner")) or name.startswith("coderun-"):
        return {"group": "Runtime pools", "display": base, "critical": False}
    if base.startswith("edge"):
        return {"group": "Runtime pools", "display": base, "critical": False}
    return {"group": "Apps", "display": base, "critical": False}


# ---- k8s access ----

RESOURCES: dict[str, dict[str, str]] = {
    "nodes": {
        "label": "Nodes",
        "why": "node count, cores, memory, pressure and taints",
        "scope": "cluster",
    },
    "node_metrics": {
        "label": "Node usage (metrics-server)",
        "why": "live CPU and memory use per node",
        "scope": "cluster",
    },
    "pods": {
        "label": "Pods",
        "why": "ready counts, restarts and the pod drawer",
        "scope": "namespace",
    },
    "pod_metrics": {
        "label": "Pod usage (metrics-server)",
        "why": "live CPU and memory use per pod",
        "scope": "namespace",
    },
    "deployments": {
        "label": "Deployments",
        "why": "desired and ready replicas for each service",
        "scope": "namespace",
    },
    "statefulsets": {
        "label": "StatefulSets",
        "why": "Postgres, Redis, NATS and other data services",
        "scope": "namespace",
    },
    "replicasets": {
        "label": "ReplicaSets",
        "why": "matching pods to their service",
        "scope": "namespace",
    },
    "events": {
        "label": "Events",
        "why": "the warnings timeline and pod events",
        "scope": "namespace",
    },
    "hpas": {
        "label": "Autoscalers (HPA)",
        "why": "min, max and current replicas",
        "scope": "namespace",
    },
    "scaledobjects": {
        "label": "KEDA ScaledObjects",
        "why": "queue-driven scaling state",
        "scope": "namespace",
    },
    "pvcs": {
        "label": "Volumes (PVCs)",
        "why": "disk claims and their status",
        "scope": "namespace",
    },
}
_OPTIONAL = {"node_metrics", "pod_metrics", "scaledobjects", "hpas"}


class K8s:
    """Lazily built clients, shared by every request."""

    def __init__(self) -> None:
        self.mode: str | None = None
        self.reason = ""
        self.core = self.apps = self.autoscaling = self.custom = None
        self._api_client = None
        self._loaded_at = 0.0

    def load(self) -> bool:
        if self.mode in ("in-cluster", "kubeconfig"):
            return True
        # a failed load is retried after a minute, the API may start before RBAC lands
        if self.mode == "outside" and time.monotonic() - self._loaded_at < 60:
            return False
        self._loaded_at = time.monotonic()
        try:
            from kubernetes import client, config
        except Exception as e:
            self.mode, self.reason = "outside", f"kubernetes client missing: {e}"
            return False
        try:
            config.load_incluster_config()
            self.mode = "in-cluster"
        except Exception:
            try:
                config.load_kube_config()
                self.mode = "kubeconfig"
            except Exception as e:
                self.mode = "outside"
                self.reason = str(e)[:200]
                return False
        self._api_client = client.ApiClient()
        self.core = client.CoreV1Api(self._api_client)
        self.apps = client.AppsV1Api(self._api_client)
        self.autoscaling = client.AutoscalingV2Api(self._api_client)
        self.custom = client.CustomObjectsApi(self._api_client)
        return True

    def to_dict(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return obj
        return self._api_client.sanitize_for_serialization(obj)


K8S = K8s()


def classify_error(e: Exception) -> dict[str, Any]:
    status = getattr(e, "status", None)
    if status == 403:
        return {"state": "forbidden", "status": 403}
    if status == 404:
        return {"state": "not_installed", "status": 404}
    if status == 401:
        return {"state": "forbidden", "status": 401}
    if status:
        return {"state": "error", "status": status, "detail": str(e)[:200]}
    return {"state": "unreachable", "detail": str(e)[:200]}


def fix_for(key: str, err: dict[str, Any]) -> str:
    state = err.get("state")
    if state == "not_installed":
        if key in ("node_metrics", "pod_metrics"):
            return (
                "metrics-server is not installed, so live CPU and memory use is not shown. "
                "On minikube run: minikube addons enable metrics-server. AKS ships it."
            )
        if key == "scaledobjects":
            return "KEDA is not installed in this cluster, so queue-driven scaling is not shown."
        return "This resource type does not exist in this cluster."
    if state == "forbidden":
        off = rbac_value() == "false"
        base = f"The API's service account is not allowed to read {RESOURCES[key]['label'].lower()}."
        if off:
            return (
                f"{base} {HELM_VALUE} is false in this release. "
                f"Set it to true and run helm upgrade."
            )
        return (
            f"{base} Set {HELM_VALUE}=true (the default) and run helm upgrade "
            f"so the read-only role is installed."
        )
    if state == "unreachable":
        return "The Kubernetes API did not answer. Try again in a minute."
    return "The Kubernetes API returned an error. Try again in a minute."


def access_report(errors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for key, meta in RESOURCES.items():
        err = errors.get(key)
        row = {
            "key": key,
            "label": meta["label"],
            "why": meta["why"],
            "scope": meta["scope"],
            "ok": err is None,
            "optional": key in _OPTIONAL,
        }
        if err:
            row["state"] = err.get("state")
            row["fix"] = fix_for(key, err)
        out.append(row)
    return out


def fetch_snapshot(ns: str) -> dict[str, Any]:
    """Blocking reads, one call per resource. Each failure is recorded, never raised."""
    k = K8S
    calls: dict[str, Callable[[], Any]] = {
        "nodes": lambda: k.core.list_node(_request_timeout=8),
        "node_metrics": lambda: k.custom.list_cluster_custom_object(
            "metrics.k8s.io", "v1beta1", "nodes", _request_timeout=8
        ),
        "pods": lambda: k.core.list_namespaced_pod(ns, _request_timeout=8),
        "pod_metrics": lambda: k.custom.list_namespaced_custom_object(
            "metrics.k8s.io", "v1beta1", ns, "pods", _request_timeout=8
        ),
        "deployments": lambda: k.apps.list_namespaced_deployment(
            ns, _request_timeout=8
        ),
        "statefulsets": lambda: k.apps.list_namespaced_stateful_set(
            ns, _request_timeout=8
        ),
        "replicasets": lambda: k.apps.list_namespaced_replica_set(
            ns, _request_timeout=8
        ),
        "events": lambda: k.core.list_namespaced_event(
            ns, field_selector="type=Warning", _request_timeout=8
        ),
        "hpas": lambda: k.autoscaling.list_namespaced_horizontal_pod_autoscaler(
            ns, _request_timeout=8
        ),
        "scaledobjects": lambda: k.custom.list_namespaced_custom_object(
            "keda.sh", "v1alpha1", ns, "scaledobjects", _request_timeout=8
        ),
        "pvcs": lambda: k.core.list_namespaced_persistent_volume_claim(
            ns, _request_timeout=8
        ),
    }
    raw: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, dict[str, Any]] = {}

    def one(key: str) -> None:
        try:
            res = k.to_dict(calls[key]())
            raw[key] = list((res or {}).get("items") or [])
        except Exception as e:
            raw[key] = []
            errors[key] = classify_error(e)

    # in parallel so a slow API server costs one timeout, not eleven
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(one, calls))
    return {"raw": raw, "errors": errors}


# ---- builders (pure, take the JSON the API returns) ----


def _meta(o: dict[str, Any]) -> dict[str, Any]:
    return o.get("metadata") or {}


def build_nodes(
    nodes: list[dict], node_metrics: list[dict], pods: list[dict], now: float
) -> list[dict[str, Any]]:
    usage = {}
    for m in node_metrics:
        u = m.get("usage") or {}
        usage[_meta(m).get("name")] = {
            "cpu": parse_quantity(u.get("cpu")),
            "mem": parse_quantity(u.get("memory")),
        }
    per_node: dict[str, dict[str, float]] = {}
    for p in pods:
        node = (p.get("spec") or {}).get("nodeName")
        phase = (p.get("status") or {}).get("phase")
        if not node or phase in ("Succeeded", "Failed"):
            continue
        acc = per_node.setdefault(node, {"pods": 0, "cpu_req": 0.0, "mem_req": 0.0})
        acc["pods"] += 1
        for c in (p.get("spec") or {}).get("containers") or []:
            req = (c.get("resources") or {}).get("requests") or {}
            acc["cpu_req"] += parse_quantity(req.get("cpu"))
            acc["mem_req"] += parse_quantity(req.get("memory"))

    out = []
    for n in nodes:
        md = _meta(n)
        st = n.get("status") or {}
        spec = n.get("spec") or {}
        labels = md.get("labels") or {}
        cap = st.get("capacity") or {}
        alloc = st.get("allocatable") or {}
        conds = st.get("conditions") or []
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True" for c in conds
        )
        pressure = [
            c.get("type")
            for c in conds
            if c.get("type")
            in ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")
            and c.get("status") == "True"
        ]
        roles = sorted(
            k.split("/", 1)[1]
            for k in labels
            if k.startswith("node-role.kubernetes.io/") and "/" in k
        )
        info = st.get("nodeInfo") or {}
        name = md.get("name")
        u = usage.get(name)
        here = per_node.get(name, {"pods": 0, "cpu_req": 0.0, "mem_req": 0.0})
        cpu_alloc = parse_quantity(alloc.get("cpu"))
        mem_alloc = parse_quantity(alloc.get("memory"))
        out.append(
            {
                "name": name,
                "ready": ready,
                "unschedulable": bool(spec.get("unschedulable")),
                "roles": roles,
                "pool": labels.get("kubernetes.azure.com/agentpool")
                or labels.get("agentpool")
                or labels.get("eks.amazonaws.com/nodegroup"),
                "zone": labels.get("topology.kubernetes.io/zone"),
                "instance_type": labels.get("node.kubernetes.io/instance-type"),
                "kubelet_version": info.get("kubeletVersion"),
                "os_image": info.get("osImage"),
                "container_runtime": info.get("containerRuntimeVersion"),
                "created": iso(md.get("creationTimestamp")),
                "age_seconds": age_seconds(md.get("creationTimestamp"), now),
                "cpu_cores": parse_quantity(cap.get("cpu")),
                "cpu_allocatable_cores": cpu_alloc,
                "mem_bytes": parse_quantity(cap.get("memory")),
                "mem_allocatable_bytes": mem_alloc,
                "pods_capacity": int(parse_quantity(cap.get("pods"))),
                "pods_here": int(here["pods"]),
                "cpu_requested_cores": round(here["cpu_req"], 3),
                "mem_requested_bytes": here["mem_req"],
                "cpu_used_cores": round(u["cpu"], 3) if u else None,
                "mem_used_bytes": u["mem"] if u else None,
                "cpu_pct": (
                    round(100 * u["cpu"] / cpu_alloc, 1) if u and cpu_alloc else None
                ),
                "mem_pct": (
                    round(100 * u["mem"] / mem_alloc, 1) if u and mem_alloc else None
                ),
                "pressure": pressure,
                "conditions": [
                    {
                        "type": c.get("type"),
                        "status": c.get("status"),
                        "reason": c.get("reason"),
                        "message": (c.get("message") or "")[:300],
                    }
                    for c in conds
                ],
                "taints": [
                    {
                        "key": t.get("key"),
                        "value": t.get("value"),
                        "effect": t.get("effect"),
                    }
                    for t in spec.get("taints") or []
                ],
            }
        )
    out.sort(key=lambda x: x["name"] or "")
    return out


def pod_owner(pod: dict, rs_owner: dict[str, str]) -> tuple[str | None, str | None]:
    md = _meta(pod)
    for ref in md.get("ownerReferences") or []:
        kind, name = ref.get("kind"), ref.get("name")
        if kind == "ReplicaSet" and name:
            if name in rs_owner:
                return "Deployment", rs_owner[name]
            h = (md.get("labels") or {}).get("pod-template-hash")
            if h and name.endswith(f"-{h}"):
                return "Deployment", name[: -len(h) - 1]
            return "ReplicaSet", name
        if kind in ("StatefulSet", "DaemonSet", "Job"):
            return kind, name
    return None, None


def summarize_pod(
    pod: dict, metrics: dict[str, dict[str, float]], now: float
) -> dict[str, Any]:
    md = _meta(pod)
    st = pod.get("status") or {}
    spec = pod.get("spec") or {}
    statuses = st.get("containerStatuses") or []
    restarts = sum(int(c.get("restartCount") or 0) for c in statuses)
    ready_n = sum(1 for c in statuses if c.get("ready"))
    waiting = None
    last_term = None
    for c in statuses:
        w = (c.get("state") or {}).get("waiting")
        if w and w.get("reason") and not waiting:
            waiting = {
                "reason": w.get("reason"),
                "message": (w.get("message") or "")[:300],
                "container": c.get("name"),
            }
        t = (c.get("lastState") or {}).get("terminated")
        if t:
            at = parse_time(t.get("finishedAt"))
            cand = {
                "reason": t.get("reason") or "Exited",
                "exit_code": t.get("exitCode"),
                "at": at.isoformat() if at else None,
                "container": c.get("name"),
                "pod": md.get("name"),
            }
            if not last_term or (cand["at"] or "") > (last_term["at"] or ""):
                last_term = cand
    phase = st.get("phase") or "Unknown"
    deleting = bool(md.get("deletionTimestamp"))
    if deleting:
        status = "Terminating"
    elif waiting:
        status = waiting["reason"]
    elif phase == "Running" and statuses and ready_n < len(statuses):
        status = "Not ready"
    else:
        status = phase
    m = metrics.get(md.get("name"))
    return {
        "name": md.get("name"),
        "phase": phase,
        "status": status,
        "ready": bool(statuses) and ready_n == len(statuses),
        "containers_ready": ready_n,
        "containers_total": len(statuses) or len(spec.get("containers") or []),
        "restarts": restarts,
        "node": spec.get("nodeName"),
        "created": iso(md.get("creationTimestamp")),
        "age_seconds": age_seconds(md.get("creationTimestamp"), now),
        "waiting": waiting,
        "last_termination": last_term,
        "cpu_used_cores": round(m["cpu"], 3) if m else None,
        "mem_used_bytes": m["mem"] if m else None,
        "terminating": deleting,
    }


def pod_metrics_map(items: list[dict]) -> dict[str, dict[str, float]]:
    out = {}
    for m in items:
        cpu = mem = 0.0
        for c in m.get("containers") or []:
            u = c.get("usage") or {}
            cpu += parse_quantity(u.get("cpu"))
            mem += parse_quantity(u.get("memory"))
        out[_meta(m).get("name")] = {"cpu": cpu, "mem": mem}
    return out


def _metric_label(name: str, triggers: list[dict]) -> str:
    # KEDA names external metrics s<index>-<trigger type>-<detail>
    m = re.match(r"^s(\d+)-(.*)$", name or "")
    if m:
        idx = int(m.group(1))
        if idx < len(triggers):
            t = triggers[idx]
            typ = t.get("type") or ""
            md = t.get("metadata") or {}
            if typ == "nats-jetstream":
                return f"Queue backlog ({md.get('stream') or 'stream'})"
            if typ == "prometheus":
                metric = md.get("metricName") or ""
                if "p95" in metric:
                    return "p95 run time (ms)"
                return metric or "Prometheus query"
            if typ in ("cpu", "memory"):
                return f"{typ.upper()} use"
            return typ
        return m.group(2)
    if name in ("cpu", "memory"):
        return f"{name.upper() if name == 'cpu' else 'Memory'} use"
    return name


def build_scaling(
    hpas: list[dict], scaledobjects: list[dict]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Map (kind, name) of a scale target to its autoscaler state."""
    so_by_hpa = {}
    so_by_target = {}
    for so in scaledobjects:
        st = so.get("status") or {}
        spec = so.get("spec") or {}
        ref = spec.get("scaleTargetRef") or {}
        so_by_target[(ref.get("kind") or "Deployment", ref.get("name"))] = so
        if st.get("hpaName"):
            so_by_hpa[st["hpaName"]] = so
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for h in hpas:
        md = _meta(h)
        spec = h.get("spec") or {}
        st = h.get("status") or {}
        ref = spec.get("scaleTargetRef") or {}
        key = (ref.get("kind") or "Deployment", ref.get("name"))
        so = so_by_hpa.get(md.get("name")) or so_by_target.get(key)
        triggers = ((so or {}).get("spec") or {}).get("triggers") or []
        targets = {}
        for m in spec.get("metrics") or []:
            typ = m.get("type")
            if typ == "External":
                ext = m.get("external") or {}
                tgt = ext.get("target") or {}
                targets[(ext.get("metric") or {}).get("name")] = tgt.get(
                    "averageValue"
                ) or tgt.get("value")
            elif typ == "Resource":
                res = m.get("resource") or {}
                tgt = res.get("target") or {}
                util = tgt.get("averageUtilization")
                targets[res.get("name")] = (
                    f"{util}%" if util is not None else tgt.get("averageValue")
                )
        metrics = []
        seen = set()
        for m in st.get("currentMetrics") or []:
            typ = m.get("type")
            if typ == "External":
                ext = m.get("external") or {}
                name = (ext.get("metric") or {}).get("name")
                cur = (ext.get("current") or {}).get("averageValue") or (
                    ext.get("current") or {}
                ).get("value")
            elif typ == "Resource":
                res = m.get("resource") or {}
                name = res.get("name")
                c = res.get("current") or {}
                util = c.get("averageUtilization")
                cur = f"{util}%" if util is not None else c.get("averageValue")
            else:
                continue
            seen.add(name)
            metrics.append(
                {
                    "name": name,
                    "label": _metric_label(name, triggers),
                    "current": cur,
                    "current_value": parse_quantity(
                        str(cur).rstrip("%") if cur else None
                    ),
                    "target": targets.get(name),
                }
            )
        for name, tgt in targets.items():
            if name not in seen:
                metrics.append(
                    {
                        "name": name,
                        "label": _metric_label(name, triggers),
                        "current": None,
                        "current_value": None,
                        "target": tgt,
                    }
                )
        so_st = (so or {}).get("status") or {}
        conds = {c.get("type"): c for c in so_st.get("conditions") or []}
        out[key] = {
            "kind": "keda" if so else "hpa",
            "name": (_meta(so).get("name") if so else md.get("name")),
            "min": spec.get("minReplicas"),
            "max": spec.get("maxReplicas"),
            "current": st.get("currentReplicas"),
            "desired": st.get("desiredReplicas"),
            "metrics": metrics,
            "active": (
                (conds.get("Active") or {}).get("status") == "True" if so else None
            ),
            "paused": (
                (conds.get("Paused") or {}).get("status") == "True" if so else None
            ),
            "last_active": iso(so_st.get("lastActiveTime")) if so else None,
            "triggers": [t.get("type") for t in triggers],
        }
    # a ScaledObject whose HPA we could not read still says something useful
    for key, so in so_by_target.items():
        if key in out:
            continue
        spec = so.get("spec") or {}
        out[key] = {
            "kind": "keda",
            "name": _meta(so).get("name"),
            "min": spec.get("minReplicaCount"),
            "max": spec.get("maxReplicaCount"),
            "current": None,
            "desired": None,
            "metrics": [],
            "active": None,
            "paused": None,
            "last_active": iso((so.get("status") or {}).get("lastActiveTime")),
            "triggers": [t.get("type") for t in spec.get("triggers") or []],
        }
    return out


def _workload_status(
    desired: int, ready: int, updated: int, rolling: bool, pods: list[dict]
) -> tuple[str, str]:
    stuck = next((p["waiting"] for p in pods if p.get("waiting")), None)
    if desired == 0:
        return "idle", "Scaled to zero. It starts when work arrives."
    if ready >= desired and not rolling:
        return "healthy", f"All {desired} running and ready."
    why = ""
    if stuck:
        why = f" {plain_waiting(stuck['reason'])}"
    if ready == 0:
        return "down", f"No pods ready (0 of {desired}).{why}"
    if rolling or updated < desired:
        return (
            "progressing",
            f"Rolling out a new version ({ready} of {desired} ready).{why}",
        )
    return "degraded", f"{ready} of {desired} pods ready.{why}"


def plain_waiting(reason: str) -> str:
    return {
        "CrashLoopBackOff": "A container keeps crashing and restarting.",
        "ImagePullBackOff": "The image cannot be pulled.",
        "ErrImagePull": "The image cannot be pulled.",
        "CreateContainerConfigError": "A config map or secret the pod needs is missing.",
        "ContainerCreating": "Containers are starting.",
        "PodInitializing": "Init containers are still running.",
        "OOMKilled": "A container ran out of memory.",
    }.get(reason, f"Waiting: {reason}.")


def plain_termination(reason: str | None) -> str:
    return {
        "OOMKilled": "ran out of memory",
        "Error": "exited with an error",
        "Completed": "exited normally",
        "ContainerCannotRun": "could not start",
    }.get(reason or "", (reason or "stopped").lower())


def build_workloads(
    deployments: list[dict],
    statefulsets: list[dict],
    replicasets: list[dict],
    pods: list[dict],
    pod_metrics: list[dict],
    scaling: dict[tuple[str, str], dict[str, Any]],
    now: float,
    rel: str | None = None,
) -> list[dict[str, Any]]:
    rs_owner = {}
    for rs in replicasets:
        for ref in _meta(rs).get("ownerReferences") or []:
            if ref.get("kind") == "Deployment":
                rs_owner[_meta(rs).get("name")] = ref.get("name")
    pm = pod_metrics_map(pod_metrics)
    by_owner: dict[tuple[str, str], list[dict]] = {}
    for p in pods:
        kind, name = pod_owner(p, rs_owner)
        if kind and name:
            by_owner.setdefault((kind, name), []).append(summarize_pod(p, pm, now))

    out = []
    for kind, items in (("Deployment", deployments), ("StatefulSet", statefulsets)):
        for w in items:
            md = _meta(w)
            spec = w.get("spec") or {}
            st = w.get("status") or {}
            name = md.get("name")
            desired = int(
                spec.get("replicas") if spec.get("replicas") is not None else 1
            )
            ready = int(st.get("readyReplicas") or 0)
            updated = int(st.get("updatedReplicas") or 0)
            rolling = (st.get("observedGeneration") or 0) < (
                md.get("generation") or 0
            ) or (desired > 0 and updated < desired)
            wpods = sorted(
                by_owner.get((kind, name), []), key=lambda p: p["name"] or ""
            )
            containers = ((spec.get("template") or {}).get("spec") or {}).get(
                "containers"
            ) or []
            images = [
                {
                    "container": c.get("name"),
                    "image": c.get("image"),
                    "tag": image_tag(c.get("image") or ""),
                }
                for c in containers
            ]
            last = None
            for p in wpods:
                t = p.get("last_termination")
                if t and (not last or (t["at"] or "") > (last["at"] or "")):
                    last = t
            status, why = _workload_status(desired, ready, updated, rolling, wpods)
            info = classify(name, rel)
            cpu = [
                p["cpu_used_cores"] for p in wpods if p["cpu_used_cores"] is not None
            ]
            mem = [
                p["mem_used_bytes"] for p in wpods if p["mem_used_bytes"] is not None
            ]
            out.append(
                {
                    "kind": kind,
                    "name": name,
                    **info,
                    "desired": desired,
                    "ready": ready,
                    "updated": updated,
                    "available": int(st.get("availableReplicas") or 0),
                    "status": status,
                    "status_text": why,
                    "images": images,
                    "image_tag": images[0]["tag"] if images else None,
                    "created": iso(md.get("creationTimestamp")),
                    "age_seconds": age_seconds(md.get("creationTimestamp"), now),
                    "restarts": sum(p["restarts"] for p in wpods),
                    "last_restart": last,
                    "pods": wpods,
                    "cpu_used_cores": round(sum(cpu), 3) if cpu else None,
                    "mem_used_bytes": sum(mem) if mem else None,
                    "scaling": scaling.get((kind, name)),
                    "history": [],
                }
            )
    order = {g: i for i, g in enumerate(GROUPS)}
    out.sort(key=lambda w: (order.get(w["group"], 9), not w["critical"], w["display"]))
    return out


def _closest_workload(obj: str, names: list[str]) -> str | None:
    # pods and replica sets carry their workload's name plus a suffix
    for n in names:
        if obj == n or obj.startswith(f"{n}-"):
            return n
    return None


def build_events(
    events: list[dict], workloads: list[dict], now: float, window: int = EVENT_WINDOW
) -> list[dict[str, Any]]:
    pod_to_w = {p["name"]: w["name"] for w in workloads for p in w["pods"]}
    names = sorted((w["name"] for w in workloads), key=len, reverse=True)
    out = []
    for e in events:
        md = _meta(e)
        t = (
            parse_time(e.get("lastTimestamp"))
            or parse_time(e.get("eventTime"))
            or parse_time(e.get("firstTimestamp"))
            or parse_time(md.get("creationTimestamp"))
        )
        if not t or now - t.timestamp() > window:
            continue
        obj = e.get("involvedObject") or {}
        kind, name = obj.get("kind"), obj.get("name")
        workload = None
        if kind == "Pod":
            workload = pod_to_w.get(name)
        if not workload and name:
            workload = _closest_workload(name, names)
        out.append(
            {
                "type": e.get("type") or "Warning",
                "reason": e.get("reason"),
                "message": (e.get("message") or "")[:500],
                "kind": kind,
                "object": name,
                "workload": workload,
                "count": int(e.get("count") or 1),
                "at": t.isoformat(),
                "age_seconds": int(now - t.timestamp()),
            }
        )
    return group_events(out)


EVENT_PLAIN = {
    "Unhealthy": "failed health probes",
    "BackOff": "containers restarting",
    "FailedScheduling": "pods that could not be placed",
    "Failed": "failed image pulls or starts",
    "FailedMount": "volumes that would not mount",
    "FailedGetResourceMetric": "autoscalers missing metrics",
    "FailedComputeMetricsReplicas": "autoscalers missing metrics",
    "Evicted": "evicted pods",
    "OOMKilling": "containers out of memory",
}


def group_events(events: list[dict]) -> list[dict[str, Any]]:
    # one row per reason and service, a rollout otherwise floods the timeline
    groups: dict[tuple, dict[str, Any]] = {}
    for e in sorted(events, key=lambda x: x["at"], reverse=True):
        key = (e["reason"], e["workload"] or f"{e['kind']}/{e['object']}")
        g = groups.get(key)
        if g is None:
            groups[key] = {
                **e,
                "objects": 1,
                "first_at": e["at"],
                "_seen": {e["object"]},
            }
            continue
        g["count"] += e["count"]
        g["first_at"] = e["at"]
        if e["object"] not in g["_seen"]:
            g["_seen"].add(e["object"])
            g["objects"] += 1
    out = []
    for g in groups.values():
        g.pop("_seen", None)
        out.append(g)
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:100]


def events_summary(events: list[dict]) -> str | None:
    if not events:
        return None
    n = sum(e["count"] for e in events)
    by_reason: dict[str, int] = {}
    for e in events:
        by_reason[e["reason"] or ""] = by_reason.get(e["reason"] or "", 0) + e["count"]
    top = max(by_reason, key=by_reason.get)
    services = {e["workload"] for e in events if e["reason"] == top and e["workload"]}
    text = f"{n} warning event{'s' if n != 1 else ''} in the last 15 minutes"
    plain = EVENT_PLAIN.get(top, top)
    if by_reason[top] * 2 >= n and plain:
        text += f", mostly {plain}"
        if len(services) > 1:
            text += f" across {len(services)} services"
        elif services:
            text += f" on {classify(next(iter(services)))['display']}"
    return text + "."


def build_pvcs(items: list[dict]) -> list[dict[str, Any]]:
    out = []
    for pvc in items:
        st = pvc.get("status") or {}
        spec = pvc.get("spec") or {}
        req = ((spec.get("resources") or {}).get("requests") or {}).get("storage")
        out.append(
            {
                "pvc": _meta(pvc).get("name"),
                "requested_bytes": parse_quantity(req),
                "capacity_bytes": parse_quantity(
                    (st.get("capacity") or {}).get("storage")
                ),
                "status": st.get("phase"),
                "storage_class": spec.get("storageClassName"),
            }
        )
    return out


def verdict(
    mode: str,
    nodes: list[dict],
    workloads: list[dict],
    events: list[dict],
    errors: dict[str, dict],
    now: float,
) -> dict[str, Any]:
    reasons: list[dict[str, Any]] = []

    def add(level: str, text: str, target: str | None = None, kind: str = "") -> None:
        reasons.append({"level": level, "text": text, "target": target, "kind": kind})

    if mode == "outside":
        return {
            "state": "unknown",
            "label": "Not running in Kubernetes",
            "reasons": [
                {
                    "level": "info",
                    "text": "The API is not running inside a cluster and has no kubeconfig, so there are no nodes or pods to show.",
                    "target": None,
                    "kind": "access",
                }
            ],
        }
    core_blind = all(k in errors for k in ("pods", "deployments", "statefulsets"))
    if core_blind:
        add(
            "warning",
            "The API cannot read pods or workloads in its namespace, so service health is unknown.",
            kind="access",
        )

    for n in nodes:
        if not n["ready"]:
            add("critical", f"Node {n['name']} is not ready.", n["name"], "node")
        for p in n["pressure"]:
            label = {
                "MemoryPressure": "is low on memory",
                "DiskPressure": "is low on disk",
                "PIDPressure": "is running out of process slots",
                "NetworkUnavailable": "has no network",
            }.get(p, p)
            add("warning", f"Node {n['name']} {label}.", n["name"], "node")
        if n["unschedulable"]:
            add(
                "info",
                f"Node {n['name']} is cordoned, new pods will not land on it.",
                n["name"],
                "node",
            )
        for key, label in (("cpu_pct", "CPU"), ("mem_pct", "memory")):
            v = n.get(key)
            if v is not None and v >= 90:
                add(
                    "warning",
                    f"Node {n['name']} {label} is {v:.0f}% used.",
                    n["name"],
                    "node",
                )
        if n["pods_capacity"] and n["pods_here"] >= 0.9 * n["pods_capacity"]:
            add(
                "warning",
                f"Node {n['name']} is near its pod limit ({n['pods_here']} of {n['pods_capacity']}).",
                n["name"],
                "node",
            )

    for w in workloads:
        st = w["status"]
        if st == "down":
            add(
                "critical" if w["critical"] else "warning",
                f"{w['display']} is down. {w['status_text']}",
                w["name"],
                "workload",
            )
        elif st == "degraded":
            add("warning", f"{w['display']}: {w['status_text']}", w["name"], "workload")
        elif st == "progressing" and any(p.get("waiting") for p in w["pods"]):
            add("warning", f"{w['display']}: {w['status_text']}", w["name"], "workload")
        last = w.get("last_restart")
        if last and last.get("at"):
            t = parse_time(last["at"])
            if t and now - t.timestamp() <= RECENT_WINDOW:
                add(
                    "warning" if last.get("reason") == "OOMKilled" else "info",
                    f"{w['display']} restarted {plain_ago(now - t.timestamp())}, it {plain_termination(last.get('reason'))}.",
                    w["name"],
                    "workload",
                )

    summary = events_summary([e for e in events if e["age_seconds"] <= RECENT_WINDOW])
    if summary:
        add("info", summary, kind="events")
    if "nodes" in errors and errors["nodes"].get("state") == "forbidden":
        add(
            "info",
            "Node details are hidden because the API is not allowed to read nodes.",
            kind="access",
        )

    levels = {r["level"] for r in reasons}
    if "critical" in levels:
        state, label = "critical", "Service down"
    elif "warning" in levels:
        state, label = "degraded", "Needs attention"
    elif core_blind:
        state, label = "unknown", "Health unknown"
    else:
        state, label = "healthy", "All systems healthy"
    if state == "healthy":
        up = sum(1 for w in workloads if w["status"] == "healthy")
        idle = sum(1 for w in workloads if w["status"] == "idle")
        node_part = (
            f"{len(nodes)} node{'s' if len(nodes) != 1 else ''} ready"
            if nodes
            else "Nodes not visible"
        )
        text = f"{node_part}, {up} service{'s' if up != 1 else ''} running"
        if idle:
            text += f", {idle} scaled to zero"
        add("ok", text + ".")
    rank = {"critical": 0, "warning": 1, "ok": 2, "info": 3}
    reasons.sort(key=lambda r: rank.get(r["level"], 9))
    return {"state": state, "label": label, "reasons": reasons}


# ---- caching and history ----


class TTLCache:
    """Short-lived cache with single flight, so many admins cost one k8s round."""

    def __init__(self) -> None:
        self._data: dict[Any, tuple[float, Any]] = {}
        self._locks: dict[Any, asyncio.Lock] = {}

    async def get(
        self, key: Any, ttl: float, producer: Callable[[], Awaitable[Any]]
    ) -> tuple[Any, float]:
        hit = self._data.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1], hit[0]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._data.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1], hit[0]
            value = await producer()
            stamp = time.monotonic()
            self._data[key] = (stamp, value)
            if len(self._data) > 256:
                oldest = sorted(self._data.items(), key=lambda kv: kv[1][0])[:64]
                for k, _ in oldest:
                    self._data.pop(k, None)
                    self._locks.pop(k, None)
            return value, stamp

    def clear(self) -> None:
        self._data.clear()
        self._locks.clear()


CACHE = TTLCache()


class History:
    """Ready and desired replicas per workload over time. Redis when there, memory otherwise."""

    KEY = "abenix:cluster:history"
    GATE = "abenix:cluster:history:gate"

    def __init__(self) -> None:
        self._mem: deque = deque(maxlen=HISTORY_POINTS)
        self._last = 0.0
        self._redis = None
        self._redis_down_until = 0.0

    async def _client(self):
        if time.monotonic() < self._redis_down_until:
            return None
        if self._redis is None:
            try:
                import redis.asyncio as aioredis

                url = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
                self._redis = aioredis.from_url(
                    url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
            except Exception:
                self._redis_down_until = time.monotonic() + 60
                return None
        return self._redis

    async def record(self, workloads: list[dict], wall: float) -> list[dict]:
        point = {
            "t": int(wall),
            "w": {w["name"]: [w["ready"], w["desired"]] for w in workloads},
        }
        r = await self._client()
        if r is not None:
            try:
                if await r.set(self.GATE, "1", nx=True, ex=int(HISTORY_EVERY)):
                    await r.lpush(self.KEY, json.dumps(point))
                    await r.ltrim(self.KEY, 0, HISTORY_POINTS - 1)
                    await r.expire(self.KEY, 6 * 3600)
                rows = await r.lrange(self.KEY, 0, HISTORY_POINTS - 1)
                return [json.loads(x) for x in reversed(rows)]
            except Exception as e:
                logger.debug("cluster history redis unavailable: %s", e)
                self._redis_down_until = time.monotonic() + 60
                self._redis = None
        if time.monotonic() - self._last >= HISTORY_EVERY or not self._mem:
            self._mem.append(point)
            self._last = time.monotonic()
        return list(self._mem)


HISTORY = History()


def attach_history(workloads: list[dict], points: list[dict]) -> None:
    for w in workloads:
        series = []
        for p in points:
            v = (p.get("w") or {}).get(w["name"])
            if v is not None:
                series.append({"t": p["t"], "ready": v[0], "desired": v[1]})
        w["history"] = series[-HISTORY_POINTS:]


async def build_overview() -> dict[str, Any]:
    ns = namespace()
    rel = release()
    wall = time.time()
    loaded = await asyncio.to_thread(K8S.load)
    base = {
        "namespace": ns,
        "release": rel,
        "source": K8S.mode or "outside",
        "rbac_value": HELM_VALUE,
        "rbac_setting": rbac_value(),
        "generated_at": datetime.fromtimestamp(wall, timezone.utc).isoformat(),
        "ttl_seconds": OVERVIEW_TTL,
    }
    if not loaded:
        return {
            **base,
            "outside_reason": K8S.reason,
            "nodes": [],
            "workloads": [],
            "events": [],
            "pvcs": [],
            "access": [],
            "totals": {},
            "verdict": verdict("outside", [], [], [], {}, wall),
        }
    snap = await asyncio.to_thread(fetch_snapshot, ns)
    raw, errors = snap["raw"], snap["errors"]
    if all(e.get("state") == "unreachable" for e in errors.values()) and len(
        errors
    ) == len(RESOURCES):
        K8S.mode = None
    nodes = build_nodes(raw["nodes"], raw["node_metrics"], raw["pods"], wall)
    scaling = build_scaling(raw["hpas"], raw["scaledobjects"])
    workloads = build_workloads(
        raw["deployments"],
        raw["statefulsets"],
        raw["replicasets"],
        raw["pods"],
        raw["pod_metrics"],
        scaling,
        wall,
        rel,
    )
    events = build_events(raw["events"], workloads, wall)
    attach_history(workloads, await HISTORY.record(workloads, wall))
    phases: dict[str, int] = {}
    for p in raw["pods"]:
        ph = (p.get("status") or {}).get("phase") or "Unknown"
        phases[ph] = phases.get(ph, 0) + 1
    totals = {
        "nodes": len(nodes),
        "nodes_ready": sum(1 for n in nodes if n["ready"]),
        "cpu_cores": round(sum(n["cpu_cores"] for n in nodes), 2),
        "cpu_allocatable_cores": round(
            sum(n["cpu_allocatable_cores"] for n in nodes), 2
        ),
        "mem_bytes": sum(n["mem_bytes"] for n in nodes),
        "mem_allocatable_bytes": sum(n["mem_allocatable_bytes"] for n in nodes),
        "cpu_used_cores": (
            round(sum(n["cpu_used_cores"] or 0 for n in nodes), 3)
            if any(n["cpu_used_cores"] is not None for n in nodes)
            else None
        ),
        "mem_used_bytes": (
            sum(n["mem_used_bytes"] or 0 for n in nodes)
            if any(n["mem_used_bytes"] is not None for n in nodes)
            else None
        ),
        "pods": len(raw["pods"]),
        "pod_phases": phases,
        "services": len(workloads),
        "services_healthy": sum(
            1 for w in workloads if w["status"] in ("healthy", "idle")
        ),
        "restarts": sum(w["restarts"] for w in workloads),
        "warnings_recent": sum(
            e["count"] for e in events if e["age_seconds"] <= RECENT_WINDOW
        ),
    }
    # scripts/deploy.sh forwards Grafana to 3030 on minikube
    local = any(
        "minikube.k8s.io/name" in (_meta(n).get("labels") or {}) for n in raw["nodes"]
    )
    has_grafana = any(w["name"].endswith("grafana") for w in workloads)
    return {
        **base,
        "grafana_hint": "http://localhost:3030" if local and has_grafana else "",
        "nodes": nodes,
        "workloads": workloads,
        "events": events,
        "pvcs": build_pvcs(raw["pvcs"]),
        "access": access_report(errors),
        "totals": totals,
        "verdict": verdict(K8S.mode or "", nodes, workloads, events, errors, wall),
    }


# ---- pod drawer ----


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def valid_pod_name(name: str) -> bool:
    return bool(POD_NAME_RE.match(name or ""))


def build_pod_detail(pod: dict, events: list[dict], now: float) -> dict[str, Any]:
    md = _meta(pod)
    spec = pod.get("spec") or {}
    st = pod.get("status") or {}
    statuses = {c.get("name"): c for c in st.get("containerStatuses") or []}
    init_statuses = {c.get("name"): c for c in st.get("initContainerStatuses") or []}

    def container(c: dict, s: dict | None, init: bool) -> dict[str, Any]:
        s = s or {}
        state = s.get("state") or {}
        cur_key = next(iter(state.keys()), None) if state else None
        cur = state.get(cur_key) or {} if cur_key else {}
        last = (s.get("lastState") or {}).get("terminated")
        res = c.get("resources") or {}
        return {
            "name": c.get("name"),
            "init": init,
            "image": c.get("image"),
            "tag": image_tag(c.get("image") or ""),
            "ready": bool(s.get("ready")),
            "restarts": int(s.get("restartCount") or 0),
            "state": cur_key or "unknown",
            "state_reason": cur.get("reason"),
            "state_message": (cur.get("message") or "")[:500],
            "started_at": iso(cur.get("startedAt")),
            "last_termination": (
                {
                    "reason": last.get("reason"),
                    "exit_code": last.get("exitCode"),
                    "at": iso(last.get("finishedAt")),
                    "message": (last.get("message") or "")[:500],
                }
                if last
                else None
            ),
            "requests": res.get("requests") or {},
            "limits": res.get("limits") or {},
        }

    containers = [
        container(c, init_statuses.get(c.get("name")), True)
        for c in spec.get("initContainers") or []
    ] + [
        container(c, statuses.get(c.get("name")), False)
        for c in spec.get("containers") or []
    ]
    ev = []
    for e in events:
        t = (
            parse_time(e.get("lastTimestamp"))
            or parse_time(e.get("eventTime"))
            or parse_time(e.get("firstTimestamp"))
            or parse_time(_meta(e).get("creationTimestamp"))
        )
        ev.append(
            {
                "type": e.get("type"),
                "reason": e.get("reason"),
                "message": (e.get("message") or "")[:500],
                "count": int(e.get("count") or 1),
                "at": t.isoformat() if t else None,
                "age_seconds": int(now - t.timestamp()) if t else None,
            }
        )
    ev.sort(key=lambda x: x["at"] or "", reverse=True)
    summary = summarize_pod(pod, {}, now)
    kind, owner = pod_owner(pod, {})
    return {
        **summary,
        "namespace": md.get("namespace"),
        "owner_kind": kind,
        "owner": owner,
        "ip": st.get("podIP"),
        "qos": st.get("qosClass"),
        "started": iso(st.get("startTime")),
        "conditions": [
            {
                "type": c.get("type"),
                "status": c.get("status"),
                "reason": c.get("reason"),
                "message": (c.get("message") or "")[:300],
            }
            for c in st.get("conditions") or []
        ],
        "containers": containers,
        "events": ev[:50],
    }
