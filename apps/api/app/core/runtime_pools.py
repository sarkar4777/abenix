"""Which runtime pools exist on this cluster, and the per-agent pools the API creates."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

POOL_NOT_DEPLOYED = "POOL_NOT_DEPLOYED"
QUEUE_NOT_PICKED_UP = "QUEUE_NOT_PICKED_UP"
POOL_LABEL = "abenix.io/pool"
AGENT_LABEL = "abenix.io/dedicated-agent"
# code runners carry abenix.io/pool too, with an image family in it
POOL_DEPLOYMENTS = "app.kubernetes.io/component=runtime-pool"
POOL_SCALERS = f"{POOL_LABEL},app!=abenix-code-runner"
HASH_ANNOTATION = "abenix.io/template-hash"
INVENTORY_TTL_SECONDS = 15.0
# a pool the cached list does not name may have just been created, look again soon
MISS_RETRY_SECONDS = 3.0
NS_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def effective_pool(agent: Any) -> str:
    """The queue a run of this agent goes to."""
    if getattr(agent, "dedicated_mode", False):
        return dedicated_key(agent.id)
    return getattr(agent, "runtime_pool", None) or "default"


def dedicated_key(agent_id: Any) -> str:
    return f"dedicated-{agent_id}"


def dedicated_name(agent_id: Any) -> str:
    # the full id does not fit a Deployment name once the release prefix is on it
    template = os.environ.get("DEDICATED_POOL_TEMPLATE", "abenix-agent-runtime-default")
    prefix = template.rsplit("-", 1)[0]
    return f"{prefix}-dedicated-{str(agent_id).replace('-', '')[:12]}"


def in_cluster() -> bool:
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


def _namespace() -> str:
    try:
        return Path(NS_FILE).read_text().strip() or "abenix"
    except OSError:
        return os.environ.get("POD_NAMESPACE", "abenix")


@dataclass
class PoolInfo:
    deployment: str
    replicas: int
    has_scaler: bool = False


class _Kube:
    def __init__(self) -> None:
        from kubernetes import client, config  # type: ignore

        config.load_incluster_config()
        self.client = client
        self.apps = client.AppsV1Api()
        self.custom = client.CustomObjectsApi()
        self.ns = _namespace()

    def scaled_objects(self, selector: str) -> list[dict[str, Any]]:
        try:
            out = self.custom.list_namespaced_custom_object(
                "keda.sh",
                "v1alpha1",
                self.ns,
                "scaledobjects",
                label_selector=selector,
                _request_timeout=5,
            )
        except Exception as e:
            # no KEDA CRD on this cluster
            if getattr(e, "status", None) == 404:
                return []
            raise
        return out.get("items", [])

    def get_scaled_object(self, name: str) -> dict[str, Any] | None:
        try:
            return self.custom.get_namespaced_custom_object(
                "keda.sh", "v1alpha1", self.ns, "scaledobjects", name
            )
        except Exception as e:
            if getattr(e, "status", None) == 404:
                return None
            raise

    def serialize(self, obj: Any) -> dict[str, Any]:
        return self.client.ApiClient().sanitize_for_serialization(obj)


def _read_inventory() -> dict[str, PoolInfo] | None:
    """Pools by key from the cluster, None when this process cannot tell."""
    if not in_cluster():
        return None
    try:
        kube = _Kube()
        deployments = kube.apps.list_namespaced_deployment(
            kube.ns, label_selector=POOL_DEPLOYMENTS, _request_timeout=5
        ).items
        out = {
            d.metadata.labels[POOL_LABEL]: PoolInfo(
                d.metadata.name, int(d.spec.replicas or 0)
            )
            for d in deployments
        }
        for so in kube.scaled_objects(POOL_SCALERS):
            info = out.get(so["metadata"]["labels"][POOL_LABEL])
            if info is not None:
                info.has_scaler = True
        return out
    except Exception as e:
        logger.warning("could not read the runtime pools from the cluster: %s", e)
        return None


_cache: tuple[float, dict[str, PoolInfo] | None] = (0.0, None)
_cache_filled = False


def reset_inventory() -> None:
    global _cache, _cache_filled
    _cache = (0.0, None)
    _cache_filled = False


async def inventory(
    max_age: float = INVENTORY_TTL_SECONDS,
) -> dict[str, PoolInfo] | None:
    global _cache, _cache_filled
    at, known = _cache
    if _cache_filled and time.monotonic() - at < max_age:
        return known
    known = await asyncio.to_thread(_read_inventory)
    _cache = (time.monotonic(), known)
    _cache_filled = True
    return known


async def pool_problem(pool: str) -> str | None:
    """Why a run sent to this pool would never start, None when it will or we cannot tell."""
    # provisioned before the flag was set, and the reconcile puts back whatever goes missing
    if pool.startswith("dedicated-"):
        return None
    known = await inventory()
    if known is None:
        return None
    if pool not in known:
        known = await inventory(MISS_RETRY_SECONDS)
        if known is None:
            return None
    info = known.get(pool)
    if info is None:
        names = ", ".join(sorted(known)) or "none"
        return (
            f"Runtime pool '{pool}' is not deployed on this cluster, so no worker would "
            f"ever take this run. Pools deployed here: {names}. Move the agent to one of "
            "them, or add the pool to scaling.pools in the chart."
        )
    if info.replicas == 0 and not info.has_scaler:
        return (
            f"Runtime pool '{pool}' is not deployed on this cluster with any worker. It "
            "has no replicas and no autoscaler to wake it."
        )
    return None


def not_picked_up_message(pool: str | None, minutes: int) -> str:
    where = f"pool '{pool}'" if pool else "its pool"
    return (
        f"No worker picked this run up within {minutes} minutes. Either {where} has no "
        "consumer that can reach NATS, or its backlog is longer than that. Check the "
        "pool's pods, then run it again."
    )


# dedicated pools


def _settings() -> dict[str, Any]:
    return {
        "template": os.environ.get("DEDICATED_POOL_TEMPLATE", ""),
        "max_replicas": int(os.environ.get("DEDICATED_POOL_MAX_REPLICAS", "5")),
        "max_pools": int(os.environ.get("DEDICATED_POOL_MAX_POOLS", "20")),
    }


def _bounds(agent: Any, cap: int) -> tuple[int, int]:
    top = max(1, min(int(agent.max_replicas or 1), cap))
    return min(max(0, int(agent.min_replicas or 0)), top), top


def build_deployment(
    template: dict[str, Any],
    agent: Any,
    cap: int,
    has_scaler: bool,
) -> dict[str, Any]:
    """A pool Deployment for one agent, cloned from the chart's pool so image and secrets match."""
    key = dedicated_key(agent.id)
    name = dedicated_name(agent.id)
    meta = template["metadata"]
    labels = {
        "app.kubernetes.io/name": "agent-runtime",
        "app.kubernetes.io/component": "runtime-pool",
        POOL_LABEL: key,
        AGENT_LABEL: str(agent.id),
    }
    instance = (meta.get("labels") or {}).get("app.kubernetes.io/instance")
    if instance:
        labels["app.kubernetes.io/instance"] = instance
    pod = copy.deepcopy(template["spec"]["template"])
    pod_meta = pod.setdefault("metadata", {})
    pod_meta["labels"] = {
        **(pod_meta.get("labels") or {}),
        POOL_LABEL: key,
        AGENT_LABEL: str(agent.id),
    }
    # a rollout stamp from the template pool must not roll this pool too
    (pod_meta.get("annotations") or {}).pop("kubectl.kubernetes.io/restartedAt", None)
    pod_meta.pop("creationTimestamp", None)
    for container in pod["spec"]["containers"]:
        if container["name"] != "agent-runtime":
            continue
        for env in container.get("env") or []:
            if env["name"] == "RUNTIME_POOL":
                env["value"] = key
            elif env["name"] == "AGENT_CONCURRENCY":
                env["value"] = str(agent.concurrency_per_replica or 3)
    digest = hashlib.sha256(json.dumps(pod, sort_keys=True).encode()).hexdigest()[:16]
    low, top = _bounds(agent, cap)
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "labels": labels,
            "annotations": {HASH_ANNOTATION: digest},
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": meta["name"],
                    "uid": meta["uid"],
                    "controller": False,
                    "blockOwnerDeletion": False,
                }
            ],
        },
        "spec": {
            "replicas": low if has_scaler else max(1, low),
            "revisionHistoryLimit": 1,
            "selector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "agent-runtime",
                    POOL_LABEL: key,
                }
            },
            "template": pod,
        },
    }


def build_scaler(
    template: dict[str, Any], agent: Any, cap: int, owner: dict[str, Any]
) -> dict[str, Any]:
    """A ScaledObject for one agent's pool, with the cooldowns the chart gave the template pool."""
    key = dedicated_key(agent.id)
    name = dedicated_name(agent.id)
    spec = copy.deepcopy(template["spec"])
    low, top = _bounds(agent, cap)
    spec["scaleTargetRef"] = {"name": name}
    spec["minReplicaCount"] = low
    spec["maxReplicaCount"] = top
    # prometheus only scrapes pools with a Service, so a dedicated pool scales on queue lag
    spec["triggers"] = [
        t for t in spec.get("triggers") or [] if t.get("type") != "prometheus"
    ]
    for trigger in spec["triggers"]:
        meta = trigger.get("metadata") or {}
        if "consumer" in meta:
            meta["consumer"] = f"abenix-{key}-consumer"
    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": name,
            "labels": {POOL_LABEL: key, AGENT_LABEL: str(agent.id)},
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": owner["name"],
                    "uid": owner["uid"],
                    "controller": False,
                    "blockOwnerDeletion": False,
                }
            ],
        },
        "spec": spec,
    }


def _ensure_sync(agent: Any, kube: Any | None = None) -> str:
    """Create or update the agent's Deployment and ScaledObject. Returns created or updated."""
    cfg = _settings()
    kube = kube or _Kube()
    from kubernetes.client.exceptions import ApiException  # type: ignore

    try:
        template = kube.serialize(
            kube.apps.read_namespaced_deployment(cfg["template"], kube.ns)
        )
    except ApiException as e:
        if e.status == 404:
            raise RuntimeError(
                f"Dedicated pools are cloned from {cfg['template']}, which is not deployed."
            ) from e
        raise
    template_scaler = kube.get_scaled_object(cfg["template"])
    name = dedicated_name(agent.id)
    body = build_deployment(
        template, agent, cfg["max_replicas"], template_scaler is not None
    )
    try:
        current = kube.apps.read_namespaced_deployment(name, kube.ns)
    except ApiException as e:
        if e.status != 404:
            raise
        current = None
    state = "updated"
    if current is None:
        pools = kube.apps.list_namespaced_deployment(
            kube.ns, label_selector=AGENT_LABEL
        ).items
        if len(pools) >= cfg["max_pools"]:
            raise RuntimeError(
                f"This cluster already has {len(pools)} dedicated pools, the limit set by "
                "scaling.dedicated.maxPools."
            )
        current = kube.apps.create_namespaced_deployment(kube.ns, body)
        state = "created"
    else:
        annotations = current.metadata.annotations or {}
        if (
            annotations.get(HASH_ANNOTATION)
            != body["metadata"]["annotations"][HASH_ANNOTATION]
        ):
            patch = {
                "metadata": {"annotations": body["metadata"]["annotations"]},
                "spec": {"template": body["spec"]["template"]},
            }
            kube.apps.patch_namespaced_deployment(name, kube.ns, patch)
    if template_scaler is None:
        return state
    owner = {"name": name, "uid": current.metadata.uid}
    so = build_scaler(template_scaler, agent, cfg["max_replicas"], owner)
    try:
        if kube.get_scaled_object(name) is None:
            kube.custom.create_namespaced_custom_object(
                "keda.sh", "v1alpha1", kube.ns, "scaledobjects", so
            )
        else:
            kube.custom.patch_namespaced_custom_object(
                "keda.sh",
                "v1alpha1",
                kube.ns,
                "scaledobjects",
                name,
                {"spec": so["spec"]},
            )
    except Exception:
        # half a pool would queue runs nothing scales for
        if state == "created":
            _delete_sync(agent.id, kube)
        raise
    return state


def _delete_sync(agent_id: Any, kube: Any | None = None) -> None:
    kube = kube or _Kube()
    name = dedicated_name(agent_id)
    try:
        kube.custom.delete_namespaced_custom_object(
            "keda.sh", "v1alpha1", kube.ns, "scaledobjects", name
        )
    except Exception as e:
        if getattr(e, "status", None) != 404:
            raise
    try:
        kube.apps.delete_namespaced_deployment(name, kube.ns)
    except Exception as e:
        if getattr(e, "status", None) != 404:
            raise


def _queue_backend() -> Any:
    runtime = str(Path(__file__).resolve().parents[3] / "agent-runtime")
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    from engine.queue_backend import get_queue_backend  # type: ignore

    return get_queue_backend()


def dedicated_refusal() -> str | None:
    """Why this deployment cannot give an agent its own pool."""
    if not os.environ.get("DEDICATED_POOL_TEMPLATE"):
        return "Dedicated pools are off, set scaling.dedicated.enabled in the chart."
    if not in_cluster():
        return "Dedicated pools need the API to run inside the Kubernetes cluster."
    return None


async def provision(agent: Any) -> str:
    """Bring up the agent's pool and its durable. Raises with a reason when it cannot."""
    state = await asyncio.to_thread(_ensure_sync, agent)
    await _queue_backend().ensure_consumer(dedicated_key(agent.id))
    reset_inventory()
    return state


async def retire(agent_id: Any) -> str:
    """Remove the pool once nothing is queued on it. Returns removed or draining."""
    backend = _queue_backend()
    key = dedicated_key(agent_id)
    left = await backend.backlog(key)
    if left:
        return "draining"
    await asyncio.to_thread(_delete_sync, agent_id)
    await backend.remove_queue(key)
    reset_inventory()
    return "removed"


async def reconcile() -> dict[str, int]:
    """Durables for every deployed pool, a pool for every dedicated agent, none for any other."""
    known = await inventory(0)
    if known is None:
        return {}
    backend = _queue_backend()
    for pool in known:
        await backend.ensure_consumer(pool)
    if dedicated_refusal():
        return {}

    from sqlalchemy import select

    from app.core.deps import async_session
    from models.agent import Agent, AgentStatus

    async with async_session() as db:
        agents = (
            (
                await db.execute(
                    select(Agent).where(
                        Agent.dedicated_mode.is_(True),
                        Agent.status != AgentStatus.ARCHIVED,
                    )
                )
            )
            .scalars()
            .all()
        )
    wanted = {str(a.id) for a in agents}
    created = removed = 0
    for agent in agents:
        try:
            state = await provision(agent)
            created += state == "created"
        except Exception as e:
            logger.warning("dedicated pool for %s not ready: %s", agent.id, e)
    for key in known:
        if not key.startswith("dedicated-"):
            continue
        agent_id = key[len("dedicated-") :]
        if agent_id in wanted:
            continue
        try:
            removed += await retire(agent_id) == "removed"
        except Exception as e:
            logger.warning("could not remove the pool %s: %s", key, e)
    out = {}
    if created:
        out["created"] = created
    if removed:
        out["removed"] = removed
    return out
