from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cluster_view as cv
from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/cluster", tags=["admin-cluster"])

_NAMESPACE = os.environ.get("KUBERNETES_NAMESPACE", "abenix")
_GRAFANA_URL_ENV = os.environ.get("GRAFANA_URL", "")


def _ensure_admin(user: User) -> None:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    if not (getattr(user, "is_admin", False) or r.lower() == "admin"):
        raise HTTPException(status_code=403, detail="admin-only")


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
    _ensure_admin(user)

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


@router.get("/overview")
async def cluster_overview(user: User = Depends(get_current_user)):
    """Nodes, services, scaling, warnings and a health verdict, cached briefly."""
    _ensure_admin(user)
    data, stamp = await cv.CACHE.get("overview", cv.OVERVIEW_TTL, cv.build_overview)
    out = dict(data)
    out["grafana_url"] = _GRAFANA_URL_ENV or out.pop("grafana_hint", "")
    out["cache_age_seconds"] = round(time.monotonic() - stamp, 1)
    return success(out)


@router.get("/database")
async def cluster_database(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Database size and the largest tables, cached for a minute."""
    _ensure_admin(user)

    async def produce() -> dict[str, Any]:
        info: dict[str, Any] = {}
        try:
            row = (
                await db.execute(
                    text("SELECT pg_database_size(current_database()) AS sz")
                )
            ).first()
            info["bytes"] = int(row.sz) if row else None
            rows = (
                await db.execute(
                    text(
                        "SELECT relname AS name, pg_total_relation_size(oid) AS bytes "
                        "FROM pg_class WHERE relkind='r' AND relnamespace = 'public'::regnamespace "
                        "ORDER BY bytes DESC LIMIT 8"
                    )
                )
            ).all()
            info["top_tables"] = [{"name": r.name, "bytes": int(r.bytes)} for r in rows]
        except Exception as e:
            logger.warning("cluster database size failed: %s", e)
            info["error"] = "The database size could not be read right now."
        return info

    data, _ = await cv.CACHE.get("database", 60, produce)
    return success(data)


def _pod_error(e: Exception, what: str):
    err = cv.classify_error(e)
    if err.get("status") == 404:
        return error(
            "That pod no longer exists. It may have been replaced, refresh the page.",
            404,
            "POD_NOT_FOUND",
        )
    if err.get("state") == "forbidden":
        return error(
            f"The API is not allowed to read {what}. Set {cv.HELM_VALUE}=true and run helm upgrade.",
            403,
            "CLUSTER_FORBIDDEN",
        )
    return error(
        f"Could not read {what} from the cluster right now. Try again in a minute.",
        502,
        "CLUSTER_UNAVAILABLE",
    )


async def _pod_detail(name: str) -> dict[str, Any]:
    ns = cv.namespace()

    def fetch():
        pod = cv.K8S.to_dict(
            cv.K8S.core.read_namespaced_pod(name, ns, _request_timeout=8)
        )
        events: list = []
        events_error = None
        try:
            res = cv.K8S.to_dict(
                cv.K8S.core.list_namespaced_event(
                    ns,
                    field_selector=f"involvedObject.kind=Pod,involvedObject.name={name}",
                    _request_timeout=8,
                )
            )
            events = res.get("items") or []
        except Exception as e:
            events_error = cv.fix_for("events", cv.classify_error(e))
        return pod, events, events_error

    pod, events, events_error = await asyncio.to_thread(fetch)
    detail = cv.build_pod_detail(pod, events, time.time())
    detail["events_error"] = events_error
    return detail


def _outside():
    return error(
        "The API is not running in Kubernetes, so there are no pods to show.",
        409,
        "NOT_IN_KUBERNETES",
    )


@router.get("/pods/{name}")
async def pod_detail(name: str, user: User = Depends(get_current_user)):
    """One pod: containers, conditions, last termination and its events."""
    _ensure_admin(user)
    if not cv.valid_pod_name(name):
        return error("That is not a valid pod name.", 400, "BAD_POD_NAME")
    if not await asyncio.to_thread(cv.K8S.load):
        return _outside()
    try:
        data, _ = await cv.CACHE.get(
            ("pod", name), cv.POD_TTL, lambda: _pod_detail(name)
        )
    except Exception as e:
        return _pod_error(e, "this pod")
    return success(data)


_audited: dict[tuple[str, str], float] = {}


@router.get("/pods/{name}/logs")
async def pod_logs(
    name: str,
    request: Request,
    container: str = Query("", max_length=63),
    lines: int = Query(200, ge=1, le=cv.MAX_LOG_LINES),
    previous: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Last N log lines of a pod container. Admin only, audited."""
    _ensure_admin(user)
    if not cv.valid_pod_name(name) or (container and not cv.valid_pod_name(container)):
        return error("That is not a valid pod or container name.", 400, "BAD_POD_NAME")
    if not await asyncio.to_thread(cv.K8S.load):
        return _outside()
    ns = cv.namespace()

    def fetch() -> str:
        kwargs: dict[str, Any] = {
            "tail_lines": lines,
            "timestamps": True,
            "previous": previous,
            "limit_bytes": 512 * 1024,
            "_request_timeout": 10,
            # the client's own decoding turns the body into a quoted repr
            "_preload_content": False,
        }
        if container:
            kwargs["container"] = container
        resp = cv.K8S.core.read_namespaced_pod_log(name, ns, **kwargs)
        try:
            return (resp.data or b"").decode("utf-8", "replace")
        finally:
            resp.release_conn()

    async def produce() -> str:
        return await asyncio.to_thread(fetch)

    try:
        body, _ = await cv.CACHE.get(
            ("logs", name, container, lines, previous), cv.LOG_TTL, produce
        )
    except Exception as e:
        status = getattr(e, "status", None)
        if status == 400:
            msg = (
                "There is no earlier run of this container to show. It has not restarted."
                if previous
                else "Logs are not available yet. The container may still be starting."
            )
            return error(msg, 400, "LOGS_UNAVAILABLE")
        return _pod_error(e, "pod logs")

    key = (str(user.id), name)
    now = time.monotonic()
    if now - _audited.get(key, 0) > 600:
        if len(_audited) > 5000:
            _audited.clear()
        _audited[key] = now
        try:
            await log_action(
                db,
                user.tenant_id,
                user.id,
                "cluster.pod_logs.read",
                {"pod": name, "container": container or None, "namespace": ns},
                request,
                resource_type="pod",
                resource_id=name,
            )
            await db.commit()
        except Exception as e:
            logger.warning("audit of pod log read failed: %s", e)
    text_lines = cv.strip_ansi(body).splitlines()
    return success(
        {
            "pod": name,
            "container": container or None,
            "previous": previous,
            "lines": text_lines[-lines:],
            "truncated": len(body) >= 512 * 1024,
        }
    )
