"""Warm code runners: one Deployment per tenant and asset version, called over NATS."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

APP_LABEL = "abenix-code-runner"
MANIFEST = "abenix-runner.json"
GATEWAY_UID = 10001
METRICS_PORT = 9464
TIERS = ("low", "medium", "high", "critical")

_POOLS = (
    ("python", re.compile(r"^(?:[\w.:-]+/)*python3?:(\d+\.\d+)")),
    ("node", re.compile(r"^(?:[\w.:-]+/)*node:(\d+)")),
    ("go", re.compile(r"^(?:[\w.:-]+/)*golang:(\d+\.\d+)")),
    ("ruby", re.compile(r"^(?:[\w.:-]+/)*ruby:(\d+\.\d+)")),
    ("java", re.compile(r"^(?:[\w.:-]+/)*eclipse-temurin:(\d+)")),
)


# Kept identical to apps/code-runner/runner.py pool_for_image, a test pins the two.
def pool_for_image(image: str) -> str | None:
    img = (image or "").strip().lower()
    for family, rx in _POOLS:
        m = rx.match(img)
        if m:
            return f"{family}-{m.group(1)}"
    return None


# Kept identical to apps/code-runner/runner.py subject_for, a test pins the two.
def subject_for(tenant_id: str, asset_id: str, revision: str, network: bool) -> str:
    base = f"code.{tenant_id}.{asset_id}.{revision}"
    return base + ".net" if network else base


def runner_revision(asset: dict[str, Any]) -> str:
    """Version number plus a hash of everything that changes what the runner holds."""
    h = hashlib.sha256()
    for k in (
        "suggested_image",
        "suggested_build_command",
        "suggested_run_command",
        "storage_uri",
    ):
        h.update(str(asset.get(k) or "").encode())
        h.update(b"\0")
    return f"v{int(asset.get('version') or 1)}-{h.hexdigest()[:6]}"


def runner_name(tenant_id: str, asset_id: str, revision: str, network: bool) -> str:
    t = re.sub(r"[^a-z0-9]", "", tenant_id.lower())[:8] or "system"
    a = re.sub(r"[^a-z0-9]", "", asset_id.lower())[:8]
    name = f"coderun-{t}-{a}-{revision.lower()}" + ("-net" if network else "")
    return re.sub(r"[^a-z0-9-]", "-", name)[:63].rstrip("-")


def tenant_uid(tenant_id: str) -> int:
    return 20000 + int(hashlib.sha256(tenant_id.encode()).hexdigest()[:8], 16) % 10000


def _env_json(name: str, default: Any) -> Any:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("%s is not valid JSON, using the default", name)
        return default


def _parse_tier_map(raw: str) -> dict[str, int]:
    out = {"low": 0, "medium": 0, "high": 1, "critical": 1}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                out[k.strip().lower()] = int(v)
            except ValueError:
                pass
    return out


@dataclass
class Settings:
    mode: str = "auto"
    images: dict[str, str] = field(default_factory=dict)
    pull_policy: str = "IfNotPresent"
    namespace: str = ""
    concurrency: int = 4
    max_replicas: int = 5
    exec_resources: dict[str, Any] = field(default_factory=dict)
    gateway_resources: dict[str, Any] = field(default_factory=dict)
    runtime_class: str = ""
    keda: bool = False
    prometheus_url: str = ""
    idle_seconds: int = 900
    drain_seconds: int = 120
    min_warm: dict[str, int] = field(default_factory=dict)
    hot_calls_per_hour: int = 30
    default_tier: str = "medium"
    nats_url: str = ""
    runner_nats_url: str = ""
    nats_secret: str = ""
    fetch_ttl: int = 21600
    api_url: str = ""
    max_payload: int = 900_000
    grace_seconds: int = 930
    ws_size: str = "2Gi"
    scratch_size: str = "1Gi"
    pull_secret: str = ""


def settings() -> Settings:
    e = os.environ.get
    nats_url = e("NATS_URL", "").strip()
    return Settings(
        mode=(e("CODE_RUNNER_MODE", "auto") or "auto").strip().lower(),
        images={
            str(k): str(v)
            for k, v in (_env_json("CODE_RUNNER_IMAGES", {}) or {}).items()
            if v
        },
        pull_policy=e("CODE_RUNNER_PULL_POLICY", "IfNotPresent"),
        namespace=e("CODE_RUNNER_NAMESPACE", "").strip(),
        concurrency=int(e("CODE_RUNNER_CONCURRENCY", "4")),
        max_replicas=int(e("CODE_RUNNER_MAX_REPLICAS", "5")),
        exec_resources=_env_json("CODE_RUNNER_EXEC_RESOURCES", None)
        or {
            "requests": {"cpu": "100m", "memory": "256Mi"},
            "limits": {"cpu": "2", "memory": "2Gi"},
        },
        gateway_resources=_env_json("CODE_RUNNER_GATEWAY_RESOURCES", None)
        or {
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {"cpu": "500m", "memory": "256Mi"},
        },
        runtime_class=e("CODE_RUNNER_RUNTIME_CLASS", "").strip(),
        keda=e("CODE_RUNNER_KEDA", "").lower() in ("1", "true", "yes"),
        prometheus_url=e("CODE_RUNNER_PROMETHEUS_URL", "").strip(),
        idle_seconds=int(e("CODE_RUNNER_IDLE_SECONDS", "900")),
        drain_seconds=int(e("CODE_RUNNER_DRAIN_SECONDS", "120")),
        min_warm=_parse_tier_map(e("CODE_RUNNER_MIN_WARM", "")),
        hot_calls_per_hour=int(e("CODE_RUNNER_HOT_CALLS_PER_HOUR", "30")),
        default_tier=(e("CODE_RUNNER_DEFAULT_TIER", "medium") or "medium").lower(),
        nats_url=nats_url,
        runner_nats_url=e("CODE_RUNNER_NATS_URL", "").strip() or nats_url,
        nats_secret=e("CODE_RUNNER_NATS_SECRET", "").strip(),
        fetch_ttl=int(e("CODE_RUNNER_FETCH_TTL", "21600")),
        api_url=(
            e("CODE_RUNNER_API_URL", "").strip()
            or e(
                "CODE_ASSET_DOWNLOAD_BASE_URL",
                "http://abenix-api.abenix.svc.cluster.local:8000",
            )
        ).rstrip("/"),
        max_payload=int(e("CODE_RUNNER_MAX_PAYLOAD", "900000")),
        grace_seconds=int(e("CODE_RUNNER_GRACE_SECONDS", "930")),
        ws_size=e("CODE_RUNNER_WS_SIZE", "2Gi"),
        scratch_size=e("CODE_RUNNER_SCRATCH_SIZE", "1Gi"),
        pull_secret=e("CODE_RUNNER_PULL_SECRET", "").strip(),
    )


def configured() -> bool:
    return bool(_env_json("CODE_RUNNER_IMAGES", {}))


def mode() -> str:
    m = (os.environ.get("CODE_RUNNER_MODE", "auto") or "auto").strip().lower()
    return m if m in ("auto", "warm", "job") else "auto"


# ── per-asset runner settings from the archive ────────────────────────────────

_manifest_cache: dict[str, dict[str, Any]] = {}


def read_manifest(storage_uri: str) -> dict[str, Any]:
    """abenix-runner.json at the project root, or {} when absent or unreadable."""
    if not storage_uri:
        return {}
    if storage_uri in _manifest_cache:
        return _manifest_cache[storage_uri]
    out: dict[str, Any] = {}
    try:
        from engine.tools.code_asset import single_root_prefix

        with zipfile.ZipFile(storage_uri) as zf:
            names = zf.namelist()
            prefix = single_root_prefix(names)
            if prefix + MANIFEST in names:
                data = json.loads(zf.read(prefix + MANIFEST))
                out = data if isinstance(data, dict) else {}
    except Exception as e:
        # an archive not yet on this pod's disk is read again next time, not remembered as empty
        logger.debug("runner manifest unreadable for %s: %s", storage_uri, e)
        return out
    _manifest_cache[storage_uri] = out
    return out


def min_warm_for(manifest: dict[str, Any], calls_last_hour: int, s: Settings) -> int:
    tier = str(manifest.get("risk_tier") or s.default_tier).lower()
    n = s.min_warm.get(tier if tier in TIERS else s.default_tier, 0)
    try:
        n = max(n, int(manifest.get("min_warm") or 0))
    except (TypeError, ValueError):
        pass
    if s.hot_calls_per_hour > 0 and calls_last_hour >= s.hot_calls_per_hour:
        n = max(n, 1)
    return min(n, s.max_replicas)


# ── spec and manifests ───────────────────────────────────────────────────────


@dataclass
class RunnerSpec:
    tenant_id: str
    asset_id: str
    version: int
    revision: str
    asset_image: str
    image: str
    pool: str
    build_cmd: str
    run_cmd: str
    network: bool
    name: str
    subject: str
    fetch_url: str
    min_warm: int = 0


def spec_for(
    asset: dict[str, Any], tenant_id: str, network: bool, s: Settings
) -> RunnerSpec | None:
    image = (asset.get("suggested_image") or "").strip()
    pool = pool_for_image(image)
    if not pool or pool not in s.images:
        return None
    asset_id = str(asset.get("id"))
    revision = runner_revision(asset)
    version = int(asset.get("version") or 1)
    return RunnerSpec(
        tenant_id=tenant_id,
        asset_id=asset_id,
        version=version,
        revision=revision,
        asset_image=image,
        image=s.images[pool],
        pool=pool,
        build_cmd=(asset.get("suggested_build_command") or "true").strip(),
        run_cmd=(asset.get("suggested_run_command") or "").strip(),
        network=network,
        name=runner_name(tenant_id, asset_id, revision, network),
        subject=subject_for(tenant_id, asset_id, revision, network),
        fetch_url=f"{s.api_url}/api/code-assets/{asset_id}/fetch?version={version}",
    )


def labels_for(spec: RunnerSpec) -> dict[str, str]:
    return {
        "app": APP_LABEL,
        "app.kubernetes.io/name": "code-runner",
        "abenix.io/code-runner": spec.name,
        "abenix.io/tenant": spec.tenant_id or "system",
        "abenix.io/asset": spec.asset_id,
        "abenix.io/revision": spec.revision,
        "abenix.io/pool": spec.pool,
        "abenix.io/network": "open" if spec.network else "none",
    }


def _sec(uid: int) -> dict[str, Any]:
    return {
        "runAsNonRoot": True,
        "runAsUser": uid,
        "runAsGroup": uid,
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }


def _as_multiplier(pool: str) -> str:
    # V8, Go and the JVM reserve far more address space than they use
    return "1" if pool.split("-", 1)[0] in ("python", "ruby") else "0"


def build_deployment(spec: RunnerSpec, s: Settings, replicas: int) -> dict[str, Any]:
    labels = labels_for(spec)
    uid = tenant_uid(spec.tenant_id or "system")
    env = lambda d: [{"name": k, "value": str(v)} for k, v in d.items()]  # noqa: E731
    init = {
        "name": "prepare",
        "image": spec.image,
        "imagePullPolicy": s.pull_policy,
        "args": ["prepare"],
        "env": env(
            {
                "CODERUN_BUILD_ROOT": "/tmp",
                "CODERUN_REVISION": spec.revision,
                "CODERUN_FETCH_URL": spec.fetch_url,
                "CODERUN_BUILD_CMD": spec.build_cmd,
            }
        )
        + [
            {
                "name": "CODERUN_FETCH_TOKEN",
                "valueFrom": {
                    "secretKeyRef": {"name": f"{spec.name}-fetch", "key": "token"}
                },
            }
        ],
        "securityContext": _sec(uid),
        "resources": s.exec_resources,
        "volumeMounts": [{"name": "ws", "mountPath": "/tmp"}],
    }
    exec_c = {
        "name": "exec",
        "image": spec.image,
        "imagePullPolicy": s.pull_policy,
        "args": ["exec"],
        "env": env(
            {
                "CODERUN_WS": "/ws",
                "CODERUN_TMP": "/tmp",
                "CODERUN_SCRATCH": "/scratch",
                "CODERUN_SOCKET": "/run/coderun/exec.sock",
                "CODERUN_RUN_CMD": spec.run_cmd,
                "CODERUN_CONCURRENCY": s.concurrency,
                "CODERUN_AS_MULTIPLIER": _as_multiplier(spec.pool),
            }
        ),
        "securityContext": _sec(uid),
        "resources": s.exec_resources,
        "volumeMounts": [
            {"name": "ws", "mountPath": "/ws", "readOnly": True},
            {"name": "tmp", "mountPath": "/tmp"},
            {"name": "scratch", "mountPath": "/scratch"},
            {"name": "sock", "mountPath": "/run/coderun"},
        ],
    }
    gw_env = env(
        {
            "CODERUN_NAME": spec.name,
            "CODERUN_REVISION": spec.revision,
            "CODERUN_TENANT": spec.tenant_id,
            "CODERUN_ASSET": spec.asset_id,
            "CODERUN_NETWORK": "true" if spec.network else "false",
            "CODERUN_IMAGE": spec.asset_image,
            "CODERUN_CONCURRENCY": s.concurrency,
            "CODERUN_SOCKET": "/run/coderun/exec.sock",
            "CODERUN_METRICS_PORT": METRICS_PORT,
            "CODERUN_DRAIN_SECONDS": max(30, s.grace_seconds - 15),
            "NATS_URL": s.runner_nats_url,
        }
    ) + [
        {"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}}
    ]
    if s.nats_secret:
        gw_env += [
            {
                "name": "NATS_USER",
                "valueFrom": {"secretKeyRef": {"name": s.nats_secret, "key": "user"}},
            },
            {
                "name": "NATS_PASSWORD",
                "valueFrom": {
                    "secretKeyRef": {"name": s.nats_secret, "key": "password"}
                },
            },
        ]
    gateway = {
        "name": "gateway",
        "image": spec.image,
        "imagePullPolicy": s.pull_policy,
        "args": ["gateway"],
        "env": gw_env,
        "ports": [{"name": "metrics", "containerPort": METRICS_PORT}],
        "readinessProbe": {
            "httpGet": {"path": "/healthz", "port": METRICS_PORT},
            "periodSeconds": 2,
            "failureThreshold": 2,
        },
        "livenessProbe": {
            "httpGet": {"path": "/healthz", "port": METRICS_PORT},
            "initialDelaySeconds": 20,
            "periodSeconds": 20,
            "failureThreshold": 6,
        },
        "securityContext": _sec(GATEWAY_UID),
        "resources": s.gateway_resources,
        "volumeMounts": [
            {"name": "sock", "mountPath": "/run/coderun"},
            {"name": "gwtmp", "mountPath": "/tmp"},
        ],
    }
    pod_spec: dict[str, Any] = {
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "terminationGracePeriodSeconds": s.grace_seconds,
        "securityContext": {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "initContainers": [init],
        "containers": [gateway, exec_c],
        "volumes": [
            {"name": "ws", "emptyDir": {"sizeLimit": s.ws_size}},
            {"name": "tmp", "emptyDir": {"sizeLimit": "256Mi"}},
            {"name": "scratch", "emptyDir": {"sizeLimit": s.scratch_size}},
            {"name": "sock", "emptyDir": {"medium": "Memory", "sizeLimit": "1Mi"}},
            {"name": "gwtmp", "emptyDir": {"sizeLimit": "16Mi"}},
        ],
    }
    if s.runtime_class:
        pod_spec["runtimeClassName"] = s.runtime_class
    if s.pull_secret:
        pod_spec["imagePullSecrets"] = [{"name": s.pull_secret}]
    now = str(int(time.time()))
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": spec.name,
            "labels": labels,
            "annotations": {
                "abenix.io/subject": spec.subject,
                "abenix.io/asset-version": str(spec.version),
                "abenix.io/kicked-at": now,
                "abenix.io/token-exp": str(int(time.time()) + s.fetch_ttl),
            },
        },
        "spec": {
            "replicas": replicas,
            "revisionHistoryLimit": 1,
            "selector": {"matchLabels": {"abenix.io/code-runner": spec.name}},
            "template": {
                "metadata": {
                    "labels": labels,
                    "annotations": {
                        "prometheus.io/scrape": "true",
                        "prometheus.io/port": str(METRICS_PORT),
                        "prometheus.io/path": "/metrics",
                    },
                },
                "spec": pod_spec,
            },
        },
    }


def build_secret(spec: RunnerSpec, token: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": f"{spec.name}-fetch", "labels": labels_for(spec)},
        "type": "Opaque",
        "stringData": {"token": token},
    }


def build_scaler(spec: RunnerSpec, s: Settings, min_replicas: int) -> dict[str, Any]:
    if s.keda and s.prometheus_url:
        return {
            "apiVersion": "keda.sh/v1alpha1",
            "kind": "ScaledObject",
            "metadata": {"name": spec.name, "labels": labels_for(spec)},
            "spec": {
                "scaleTargetRef": {"name": spec.name},
                "minReplicaCount": min_replicas,
                "maxReplicaCount": s.max_replicas,
                "pollingInterval": 10,
                "cooldownPeriod": s.idle_seconds,
                "advanced": {
                    "horizontalPodAutoscalerConfig": {
                        "behavior": {
                            "scaleDown": {"stabilizationWindowSeconds": 300},
                            "scaleUp": {"stabilizationWindowSeconds": 0},
                        }
                    }
                },
                "triggers": [
                    {
                        "type": "prometheus",
                        "metadata": {
                            "serverAddress": s.prometheus_url,
                            "query": (
                                "sum(abenix_coderunner_load"
                                f'{{runner="{spec.name}"}}) or vector(0)'
                            ),
                            "threshold": str(max(1, s.concurrency)),
                            "activationThreshold": "0",
                        },
                    }
                ],
            },
        }
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": spec.name, "labels": labels_for(spec)},
        "spec": {
            "scaleTargetRef": {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": spec.name,
            },
            "minReplicas": 1,
            "maxReplicas": max(1, s.max_replicas),
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {
                        "name": "cpu",
                        "target": {"type": "Utilization", "averageUtilization": 70},
                    },
                }
            ],
        },
    }


# ── kubernetes ───────────────────────────────────────────────────────────────


def _namespace(s: Settings) -> str:
    if s.namespace:
        return s.namespace
    ns = os.environ.get("SANDBOXED_JOB_NAMESPACE", "").strip()
    if ns:
        return ns
    from engine.tools.sandboxed_job import _K8S_NS_FILE

    try:
        return _K8S_NS_FILE.read_text().strip() or "abenix"
    except Exception:
        return "abenix"


class K8s:
    """Same client setup the sandboxed_job tool and ML model deploys use."""

    def __init__(self, s: Settings):
        from kubernetes import client, config  # type: ignore

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        self.client = client
        self.apps = client.AppsV1Api()
        self.core = client.CoreV1Api()
        self.custom = client.CustomObjectsApi()
        self.autoscaling = client.AutoscalingV2Api()
        self.ns = _namespace(s)
        self.s = s

    def _exists(self, e: Exception) -> bool:
        return getattr(e, "status", None) == 409

    def _missing(self, e: Exception) -> bool:
        return getattr(e, "status", None) == 404

    def get_deployment(self, name: str) -> Any | None:
        try:
            return self.apps.read_namespaced_deployment(name, self.ns)
        except Exception as e:
            if self._missing(e):
                return None
            raise

    def list_runners(self) -> list[Any]:
        return self.apps.list_namespaced_deployment(
            self.ns, label_selector=f"app={APP_LABEL}"
        ).items

    def _owner(self, dep: Any) -> list[dict[str, Any]]:
        return [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": dep.metadata.name,
                "uid": dep.metadata.uid,
                "controller": False,
                "blockOwnerDeletion": False,
            }
        ]

    def put_secret(self, spec: RunnerSpec, token: str, owner: Any | None) -> None:
        body = build_secret(spec, token)
        if owner is not None:
            body["metadata"]["ownerReferences"] = self._owner(owner)
        try:
            self.core.create_namespaced_secret(self.ns, body)
        except Exception as e:
            if not self._exists(e):
                raise
            patch: dict[str, Any] = {"stringData": {"token": token}}
            if owner is not None:
                patch["metadata"] = {"ownerReferences": self._owner(owner)}
            self.core.patch_namespaced_secret(f"{spec.name}-fetch", self.ns, patch)

    def put_scaler(self, spec: RunnerSpec, owner: Any, min_replicas: int) -> None:
        body = build_scaler(spec, self.s, min_replicas)
        body["metadata"]["ownerReferences"] = self._owner(owner)
        if body["kind"] == "ScaledObject":
            try:
                self.custom.create_namespaced_custom_object(
                    "keda.sh", "v1alpha1", self.ns, "scaledobjects", body
                )
            except Exception as e:
                if not self._exists(e):
                    raise
                self.set_keda_min(spec.name, min_replicas)
            return
        try:
            self.autoscaling.create_namespaced_horizontal_pod_autoscaler(self.ns, body)
        except Exception as e:
            if not self._exists(e):
                raise

    def set_keda_min(self, name: str, n: int) -> None:
        self.custom.patch_namespaced_custom_object(
            "keda.sh",
            "v1alpha1",
            self.ns,
            "scaledobjects",
            name,
            {"spec": {"minReplicaCount": n}},
        )

    def scale(self, name: str, replicas: int, annotations: dict | None = None) -> None:
        body: dict[str, Any] = {"spec": {"replicas": replicas}}
        if annotations:
            body["metadata"] = {"annotations": annotations}
        self.apps.patch_namespaced_deployment(name, self.ns, body)

    def annotate(self, name: str, annotations: dict[str, str]) -> None:
        self.apps.patch_namespaced_deployment(
            name, self.ns, {"metadata": {"annotations": annotations}}
        )

    def delete(self, name: str) -> None:
        try:
            self.apps.delete_namespaced_deployment(
                name, self.ns, propagation_policy="Background"
            )
        except Exception as e:
            if not self._missing(e):
                raise

    def ensure(self, spec: RunnerSpec, token: str, at_least: int) -> str:
        """Create the runner or bring it to at least `at_least` replicas."""
        now = str(int(time.time()))
        exp = str(int(time.time()) + self.s.fetch_ttl)
        dep = self.get_deployment(spec.name)
        if dep is None:
            self.put_secret(spec, token, None)
            body = build_deployment(spec, self.s, max(at_least, spec.min_warm))
            try:
                dep = self.apps.create_namespaced_deployment(self.ns, body)
            except Exception as e:
                if not self._exists(e):
                    raise
                dep = self.get_deployment(spec.name)
            self.put_secret(spec, token, dep)
            self.put_scaler(spec, dep, max(at_least, spec.min_warm))
            return "created"
        self.put_secret(spec, token, dep)
        ann = {"abenix.io/kicked-at": now, "abenix.io/token-exp": exp}
        if self.s.keda and self.s.prometheus_url and at_least > 0:
            try:
                self.set_keda_min(spec.name, max(at_least, spec.min_warm))
            except Exception as e:
                logger.warning("keda min patch failed for %s: %s", spec.name, e)
        if (dep.spec.replicas or 0) < at_least:
            self.scale(spec.name, at_least, ann)
            return "scaled"
        self.annotate(spec.name, ann)
        return "present"


# ── usage tracking ───────────────────────────────────────────────────────────

_redis_clients: dict[tuple[str, int], Any] = {}


def _redis(url: str) -> Any | None:
    if not url:
        return None
    try:
        import redis.asyncio as aioredis

        key = (url, id(asyncio.get_running_loop()))
        if key not in _redis_clients:
            _redis_clients[key] = aioredis.from_url(url, decode_responses=True)
        return _redis_clients[key]
    except Exception:
        return None


async def record_use(redis_url: str, name: str) -> None:
    r = _redis(redis_url)
    if r is None:
        return
    try:
        await r.set(f"coderun:last:{name}", int(time.time()), ex=7 * 86400)
        if await r.incr(f"coderun:calls:{name}") == 1:
            await r.expire(f"coderun:calls:{name}", 3600)
    except Exception as e:
        logger.debug("record_use failed: %s", e)


async def usage(redis_url: str, name: str) -> tuple[int | None, int]:
    r = _redis(redis_url)
    if r is None:
        return None, 0
    try:
        last, calls = await r.mget(f"coderun:last:{name}", f"coderun:calls:{name}")
        return (int(last) if last else None), int(calls or 0)
    except Exception:
        return None, 0


_bg: set[asyncio.Future] = set()


def fire(coro: Any) -> None:
    t = asyncio.ensure_future(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


# ── NATS ─────────────────────────────────────────────────────────────────────

_nc: dict[int, Any] = {}
_nc_locks: dict[int, asyncio.Lock] = {}


class NotConfigured(Exception):
    pass


async def nats_client(s: Settings) -> Any:
    """One connection per process and event loop, created lazily, reconnecting."""
    if not s.nats_url:
        raise NotConfigured("NATS_URL is not set")
    key = id(asyncio.get_running_loop())
    nc = _nc.get(key)
    if nc is not None and nc.is_connected:
        return nc
    if nc is not None and getattr(nc, "is_reconnecting", False):
        raise ConnectionError("NATS is reconnecting")
    lock = _nc_locks.setdefault(key, asyncio.Lock())
    async with lock:
        nc = _nc.get(key)
        if nc is not None and nc.is_connected:
            return nc
        import nats  # type: ignore

        nc = await nats.connect(
            servers=[s.nats_url],
            user=os.environ.get("NATS_USER") or None,
            password=os.environ.get("NATS_PASSWORD") or None,
            name=f"code-asset-{os.environ.get('HOSTNAME', 'local')}",
            connect_timeout=2,
            max_reconnect_attempts=-1,
            reconnect_time_wait=1,
            allow_reconnect=True,
        )
        _nc[key] = nc
        return nc


@dataclass
class WarmOutcome:
    resp: dict[str, Any] | None = None
    reason: str = ""
    fallback: bool = True
    name: str = ""
    duration_ms: int = 0


_kicked: dict[str, float] = {}
KICK_EVERY = 20.0
# how long a call waits for a runner that is starting, before the slower Job path
WARM_WAIT = float(os.environ.get("CODE_RUNNER_WARM_WAIT", "60"))
BUSY_RETRIES = 3


def _no_responders(e: Exception) -> bool:
    try:
        from nats.errors import NoRespondersError  # type: ignore

        if isinstance(e, NoRespondersError):
            return True
    except Exception:
        pass
    return type(e).__name__ == "NoRespondersError"


def _timeout(e: Exception) -> bool:
    try:
        from nats.errors import TimeoutError as NatsTimeout  # type: ignore

        if isinstance(e, NatsTimeout):
            return True
    except Exception:
        pass
    return isinstance(e, asyncio.TimeoutError)


def build_request(
    spec: RunnerSpec,
    input_payload: Any,
    env: dict[str, str],
    timeout_s: int,
    memory_mb: int,
) -> dict[str, Any]:
    return {
        "v": 1,
        "id": uuid.uuid4().hex,
        "tenant_id": spec.tenant_id,
        "asset_id": spec.asset_id,
        "revision": spec.revision,
        "input": input_payload,
        "env": env,
        "timeout_s": int(timeout_s),
        "memory_mb": int(memory_mb),
    }


async def kick(spec: RunnerSpec, storage_uri: str = "") -> str:
    """Create or wake the runner in the background. Never raises."""
    now = time.monotonic()
    if now - _kicked.get(spec.name, 0) < KICK_EVERY:
        return "recent"
    _kicked[spec.name] = now
    s = settings()
    try:
        from engine.tools.invoke_agent import mint_asset_fetch_token

        if storage_uri:
            spec.min_warm = min_warm_for(read_manifest(storage_uri), 0, s)
        token = mint_asset_fetch_token(
            spec.asset_id, spec.tenant_id or "", ttl=s.fetch_ttl
        )
        state = await asyncio.to_thread(lambda: K8s(s).ensure(spec, token, 1))
        logger.info("code runner %s %s", spec.name, state)
        return state
    except Exception as e:
        _kicked.pop(spec.name, None)
        logger.warning("code runner kick failed for %s: %s", spec.name, e)
        return f"failed: {e}"


async def call_warm(
    *,
    asset: dict[str, Any],
    tenant_id: str,
    input_payload: Any,
    env: dict[str, str],
    timeout_s: int,
    memory_mb: int,
    network: bool,
    redis_url: str = "",
    s: Settings | None = None,
) -> WarmOutcome:
    s = s or settings()
    if not s.images:
        return WarmOutcome(reason="code runners are not configured")
    spec = spec_for(asset, tenant_id, network, s)
    if spec is None:
        pool = pool_for_image(asset.get("suggested_image") or "")
        return WarmOutcome(reason=f"no warm runner image for pool {pool or 'unknown'}")
    req = build_request(spec, input_payload, env, timeout_s, memory_mb)
    data = json.dumps(req).encode()
    if len(data) > s.max_payload:
        return WarmOutcome(reason="request too large for NATS", name=spec.name)
    try:
        nc = await nats_client(s)
    except NotConfigured as e:
        return WarmOutcome(reason=str(e), name=spec.name)
    except Exception as e:
        return WarmOutcome(reason=f"NATS unavailable: {e}", name=spec.name)
    t0 = time.monotonic()
    resp: dict[str, Any] | None = None
    for attempt in range(BUSY_RETRIES + 1):
        if attempt:
            await asyncio.sleep(0.05 * 2**attempt)
        try:
            msg = await nc.request(spec.subject, data, timeout=timeout_s + 20)
        except Exception as e:
            if _no_responders(e):
                fire(kick(spec, asset.get("storage_uri") or ""))
                msg = await _await_runner(nc, spec, data, asset, timeout_s)
                if msg is None:
                    return WarmOutcome(
                        reason="no warm runner yet, warming it", name=spec.name
                    )
            elif _timeout(e):
                return WarmOutcome(
                    reason="runner did not reply in time",
                    fallback=False,
                    name=spec.name,
                )
            else:
                return WarmOutcome(
                    reason=f"NATS request failed: {e}", fallback=False, name=spec.name
                )
        try:
            resp = json.loads(msg.data)
        except ValueError:
            return WarmOutcome(
                reason="runner sent an unreadable reply",
                fallback=False,
                name=spec.name,
            )
        if not resp.get("refused"):
            break
        if attempt < BUSY_RETRIES and resp.get("reason") in ("busy", "draining"):
            continue
        return WarmOutcome(
            reason=f"runner refused: {resp.get('reason')}", name=spec.name
        )
    fire(record_use(redis_url, spec.name))
    return WarmOutcome(
        resp=resp,
        name=spec.name,
        duration_ms=int((time.monotonic() - t0) * 1000),
    )


def keeps_warm(asset: dict[str, Any]) -> bool:
    """True when the asset's manifest asks for a runner kept warm."""
    try:
        return (
            min_warm_for(read_manifest(asset.get("storage_uri") or ""), 0, settings())
            > 0
        )
    except Exception:
        return False


async def _await_runner(
    nc: Any, spec: RunnerSpec, data: bytes, asset: dict[str, Any], timeout_s: int
) -> Any | None:
    """Wait for a runner that is starting, when the asset is meant to stay warm."""
    if WARM_WAIT <= 0 or not keeps_warm(asset):
        return None
    deadline = time.monotonic() + WARM_WAIT
    while time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        try:
            return await nc.request(spec.subject, data, timeout=timeout_s + 20)
        except Exception as e:
            if not _no_responders(e):
                return None
    return None


# ── reaper ───────────────────────────────────────────────────────────────────


def _ts(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def plan_runner(
    dep_meta: dict[str, Any],
    asset: dict[str, Any] | None,
    last_use: int | None,
    calls: int,
    now: int,
    s: Settings,
) -> tuple[str, int | None]:
    """What to do with one runner: delete, scale (to n), refresh, or keep."""
    labels = dep_meta.get("labels") or {}
    ann = dep_meta.get("annotations") or {}
    created = _ts(dep_meta.get("created")) or now
    seen = max(x for x in (last_use, _ts(ann.get("abenix.io/kicked-at")), created) if x)
    idle = now - seen
    current = (
        asset is not None
        and asset.get("status") == "ready"
        and runner_revision(asset) == labels.get("abenix.io/revision")
    )
    if not current:
        return ("delete", None) if idle >= s.drain_seconds else ("drain", None)
    want = min_warm_for(read_manifest(asset.get("storage_uri") or ""), calls, s)
    replicas = int(dep_meta.get("replicas") or 0)
    if replicas < want:
        return "scale", want
    if want == 0 and replicas > 0 and idle >= s.idle_seconds:
        return "scale", 0
    exp = _ts(ann.get("abenix.io/token-exp")) or 0
    if replicas > 0 and exp - now < s.fetch_ttl // 2:
        return "refresh", None
    return "keep", None


async def _load_assets(db_url: str, ids: list[str] | None) -> dict[str, dict]:
    from sqlalchemy import text as sql_text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)
    try:
        async with engine.begin() as conn:
            sql = (
                "SELECT id, tenant_id, status, version, storage_uri, suggested_image, "
                "suggested_build_command, suggested_run_command FROM code_assets "
            )
            if ids is None:
                r = await conn.execute(sql_text(sql + "WHERE status = 'ready'"))
            elif not ids:
                return {}
            else:
                r = await conn.execute(
                    sql_text(sql + "WHERE CAST(id AS text) = ANY(:ids)"),
                    {"ids": ids},
                )
            out = {}
            for row in r.fetchall():
                st = row[2].value if hasattr(row[2], "value") else str(row[2])
                out[str(row[0])] = {
                    "id": str(row[0]),
                    "tenant_id": str(row[1]) if row[1] else "",
                    "status": st,
                    "version": row[3],
                    "storage_uri": row[4],
                    "suggested_image": row[5],
                    "suggested_build_command": row[6],
                    "suggested_run_command": row[7],
                }
            return out
    finally:
        await engine.dispose()


async def reap_once(db_url: str, redis_url: str, prewarm: bool = True) -> dict:
    s = settings()
    k = await asyncio.to_thread(K8s, s)
    deps = await asyncio.to_thread(k.list_runners)
    ids = sorted(
        {(d.metadata.labels or {}).get("abenix.io/asset", "") for d in deps} - {""}
    )
    assets = await _load_assets(db_url, ids)
    now = int(time.time())
    report: dict[str, list[str]] = {
        k_: [] for k_ in ("delete", "drain", "scale", "refresh", "keep", "create")
    }
    from engine.tools.invoke_agent import mint_asset_fetch_token

    present: set[str] = set()
    for d in deps:
        name = d.metadata.name
        present.add(name)
        labels = d.metadata.labels or {}
        last, calls = await usage(redis_url, name)
        created = d.metadata.creation_timestamp
        meta = {
            "labels": labels,
            "annotations": d.metadata.annotations or {},
            "created": int(created.timestamp()) if created else None,
            "replicas": d.spec.replicas,
        }
        action, n = plan_runner(
            meta, assets.get(labels.get("abenix.io/asset", "")), last, calls, now, s
        )
        report[action].append(name if n is None else f"{name}={n}")
        try:
            if action == "delete":
                await asyncio.to_thread(k.delete, name)
            elif action == "scale":
                if k.s.keda and k.s.prometheus_url:
                    await asyncio.to_thread(k.set_keda_min, name, n)
                await asyncio.to_thread(k.scale, name, n)
            elif action == "refresh":
                asset = assets[labels["abenix.io/asset"]]
                spec = spec_for(
                    asset,
                    labels.get("abenix.io/tenant", ""),
                    labels.get("abenix.io/network") == "open",
                    s,
                )
                if spec is not None:
                    tok = mint_asset_fetch_token(
                        spec.asset_id, spec.tenant_id, ttl=s.fetch_ttl
                    )
                    await asyncio.to_thread(k.put_secret, spec, tok, d)
                    await asyncio.to_thread(
                        k.annotate,
                        name,
                        {"abenix.io/token-exp": str(now + s.fetch_ttl)},
                    )
        except Exception as e:
            logger.warning("reaper %s on %s failed: %s", action, name, e)
    if prewarm:
        for asset in (await _load_assets(db_url, None)).values():
            manifest = read_manifest(asset.get("storage_uri") or "")
            want = min_warm_for(manifest, 0, s)
            if want <= 0:
                continue
            spec = spec_for(asset, asset["tenant_id"], bool(manifest.get("network")), s)
            if spec is None or spec.name in present:
                continue
            spec.min_warm = want
            try:
                tok = mint_asset_fetch_token(
                    spec.asset_id, spec.tenant_id, ttl=s.fetch_ttl
                )
                await asyncio.to_thread(k.ensure, spec, tok, want)
                report["create"].append(spec.name)
            except Exception as e:
                logger.warning("prewarm %s failed: %s", spec.name, e)
    return report


async def warm_asset(db_url: str, asset_id: str, network: bool = False) -> str:
    assets = await _load_assets(db_url, [asset_id])
    asset = assets.get(asset_id)
    if asset is None:
        return "asset not found"
    s = settings()
    spec = spec_for(asset, asset["tenant_id"], network, s)
    if spec is None:
        return "no warm runner image for this asset"
    _kicked.pop(spec.name, None)
    return f"{spec.name}: {await kick(spec, asset.get('storage_uri') or '')}"


async def scale_asset_to_zero(db_url: str, asset_id: str, network: bool = False) -> str:
    assets = await _load_assets(db_url, [asset_id])
    asset = assets.get(asset_id)
    if asset is None:
        return "asset not found"
    s = settings()
    spec = spec_for(asset, asset["tenant_id"], network, s)
    if spec is None:
        return "no warm runner image for this asset"
    k = await asyncio.to_thread(K8s, s)
    if k.get_deployment(spec.name) is None:
        return f"{spec.name}: absent"
    if s.keda and s.prometheus_url:
        await asyncio.to_thread(k.set_keda_min, spec.name, 0)
    await asyncio.to_thread(k.scale, spec.name, 0)
    return f"{spec.name}: scaled to 0"


def main(argv: list[str]) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    db_url = os.environ.get("DATABASE_URL", "")
    redis_url = os.environ.get("REDIS_URL", "")
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "reap":
        try:
            report = asyncio.run(reap_once(db_url, redis_url))
        except Exception as e:
            # a fresh install runs this before the migrations have made the tables
            if "does not exist" in str(e):
                print("schema not migrated yet, nothing to reap")
                return 0
            raise
        print(json.dumps({k: v for k, v in report.items() if v}, indent=1))
        return 0
    if cmd in ("warm", "scale-zero") and len(argv) > 2:
        net = "--net" in argv
        fn = warm_asset if cmd == "warm" else scale_asset_to_zero
        print(asyncio.run(fn(db_url, argv[2], net)))
        return 0
    print(
        "usage: python -m engine.code_runners reap | warm <asset_id> [--net]"
        " | scale-zero <asset_id> [--net]"
    )
    return 2


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
