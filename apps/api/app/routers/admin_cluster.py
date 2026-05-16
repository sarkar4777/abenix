from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import success
from models.user import User

router = APIRouter(prefix="/api/admin/cluster", tags=["admin-cluster"])

_NAMESPACE = os.environ.get("KUBERNETES_NAMESPACE", "abenix")
_GRAFANA_URL_ENV = os.environ.get("GRAFANA_URL", "")


def _parse_quantity(q: str | None) -> float:
    """Tiny parser for k8s resource quantities (e.g. '4', '2000m', '8Gi', '512Mi')."""
    if not q:
        return 0.0
    s = str(q).strip()
    try:
        # millicores
        if s.endswith("m"):
            return float(s[:-1]) / 1000.0
        units = {
            "Ki": 1024,
            "Mi": 1024**2,
            "Gi": 1024**3,
            "Ti": 1024**4,
            "K": 1000,
            "M": 1000**2,
            "G": 1000**3,
            "T": 1000**4,
        }
        for suf, mul in units.items():
            if s.endswith(suf):
                return float(s[: -len(suf)]) * mul
        return float(s)
    except Exception:
        return 0.0


def _load_k8s():
    """Lazy-load + configure the k8s client. Returns (core_v1, kind) or (None, reason)."""
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
            return client.CoreV1Api(), "in-cluster"
        except Exception:
            config.load_kube_config()
            return client.CoreV1Api(), "kubeconfig"
    except Exception as e:
        return None, f"k8s client unavailable: {e}"


@router.get("/summary")
async def cluster_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cluster health snapshot — nodes, pods, PVCs, DB size.

    Queries the Kubernetes API directly (works the same on minikube and AKS
    without requiring kube-state-metrics + node-exporter).
    """
    if not (getattr(user, "is_admin", False) or user.role == "admin"):
        raise HTTPException(status_code=403, detail="admin-only")

    nodes: list[dict[str, Any]] = []
    pods: dict[str, int] = {}
    disks: list[dict[str, Any]] = []
    db_info: dict[str, Any] = {}
    k8s_source: str = "unknown"

    core_v1, src = _load_k8s()
    if core_v1 is None:
        k8s_source = src
    else:
        k8s_source = src
        # Nodes
        try:
            for n in core_v1.list_node().items:
                cap = n.status.capacity or {}
                alloc = n.status.allocatable or {}
                nodes.append(
                    {
                        "name": n.metadata.name,
                        "cpu_cores": _parse_quantity(cap.get("cpu")),
                        "cpu_allocatable_cores": _parse_quantity(alloc.get("cpu")),
                        "mem_bytes": _parse_quantity(cap.get("memory")),
                        "mem_allocatable_bytes": _parse_quantity(alloc.get("memory")),
                        "pods_capacity": int(_parse_quantity(cap.get("pods"))),
                        "ready": any(
                            c.type == "Ready" and c.status == "True"
                            for c in (n.status.conditions or [])
                        ),
                    }
                )
        except Exception as e:
            nodes.append({"error": str(e)[:200]})

        # Pods grouped by phase
        try:
            for p in core_v1.list_namespaced_pod(_NAMESPACE).items:
                phase = p.status.phase or "Unknown"
                pods[phase] = pods.get(phase, 0) + 1
        except Exception:
            pass

        # PVCs — listed via Persistent Volume Claims, capacity from status
        try:
            for pvc in core_v1.list_namespaced_persistent_volume_claim(
                _NAMESPACE
            ).items:
                cap = (pvc.status.capacity or {}).get("storage")
                req = (
                    (pvc.spec.resources.requests or {}).get("storage")
                    if pvc.spec.resources
                    else None
                )
                disks.append(
                    {
                        "pvc": pvc.metadata.name,
                        "requested_bytes": _parse_quantity(req),
                        "capacity_bytes": _parse_quantity(cap),
                        "status": pvc.status.phase,
                    }
                )
        except Exception:
            pass

    # DB size — direct SQL beats anything else for accuracy
    try:
        row = (
            await db.execute(text("SELECT pg_database_size(current_database()) AS sz"))
        ).first()
        if row:
            db_info["bytes"] = int(row.sz)
        rows = (
            await db.execute(
                text(
                    "SELECT relname AS name, pg_total_relation_size(oid) AS bytes "
                    "FROM pg_class WHERE relkind='r' AND relnamespace = 'public'::regnamespace "
                    "ORDER BY bytes DESC LIMIT 10"
                )
            )
        ).all()
        db_info["top_tables"] = [{"name": r.name, "bytes": int(r.bytes)} for r in rows]
    except Exception as e:
        db_info["error"] = str(e)[:200]

    return success(
        {
            "nodes": nodes,
            "pods": pods,
            "disks": disks,
            "database": db_info,
            "k8s_source": k8s_source,
            "namespace": _NAMESPACE,
            "grafana_url": _GRAFANA_URL_ENV,
        }
    )
