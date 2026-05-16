"""Sandboxed job — run a one-shot command in an isolated container."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import time
import uuid
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_K8S_TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
_K8S_NS_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")


def _in_cluster() -> bool:
    """True if we're running inside a Kubernetes pod with a service account."""
    return _K8S_TOKEN.exists()


def _allowed_images() -> set[str]:
    raw = os.environ.get("SANDBOXED_JOB_ALLOWED_IMAGES", "").strip()
    return {i.strip() for i in raw.split(",") if i.strip()}


def _image_family(image: str) -> str:
    """Map a container image to a coarse family label for Prometheus."""
    img = image.lower()
    if "python" in img:
        return "python"
    if "node" in img:
        return "node"
    if "golang" in img or img.startswith("go:"):
        return "go"
    if "rust" in img:
        return "rust"
    if "ruby" in img:
        return "ruby"
    if "perl" in img:
        return "perl"
    if "java" in img or "temurin" in img or "openjdk" in img:
        return "java"
    return "other"


def _emit_sandbox_metrics(
    *,
    backend: str,
    image: str,
    exit_code: int | None,
    duration_ms: int | None,
    timed_out: bool,
) -> None:
    """Push a sandbox run into the Grafana counters. Outcome bucket:
    `ok` (exit 0), `timeout` (deadline hit), `nonzero` (exit != 0)."""
    try:
        from engine import metrics as _m

        family = _image_family(image)
        if timed_out:
            outcome = "timeout"
        elif exit_code == 0:
            outcome = "ok"
        else:
            outcome = "nonzero"
        _m.SANDBOX_RUNS.labels(
            backend=backend, image_family=family, outcome=outcome
        ).inc()
        if duration_ms is not None:
            _m.SANDBOX_DURATION.labels(backend=backend, image_family=family).observe(
                duration_ms / 1000.0
            )
    except Exception:
        pass


def _valid_env_name(k: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)))


class SandboxedJobTool(BaseTool):
    name = "sandboxed_job"
    description = (
        "Run a one-shot command in an isolated container. Auto-selects "
        "Kubernetes Jobs when running inside a cluster, or local Docker "
        "otherwise — same interface, same result shape. Hardened by "
        "default: read-only FS, no capabilities, no network (unless "
        "SANDBOXED_JOB_ALLOW_NETWORK=true), cpu+memory limits, "
        "activeDeadline timeout. Requires SANDBOXED_JOB_ENABLED=true "
        "and image must be in SANDBOXED_JOB_ALLOWED_IMAGES."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "image": {
                "type": "string",
                "description": "Container image (must be in the allow-list). "
                "Examples: 'python:3.12-slim', 'alpine:3.20', 'pandoc/core:3.5'.",
            },
            "command": {
                "type": "string",
                "description": "Shell command to run inside the container.",
            },
            "timeout_seconds": {
                "type": "integer",
                "default": 60,
                "minimum": 5,
                "maximum": 1800,
            },
            "memory_mb": {
                "type": "integer",
                "default": 512,
                "minimum": 64,
                "maximum": 8192,
            },
            "cpu_limit": {
                "type": "number",
                "default": 1.0,
                "minimum": 0.1,
                "maximum": 4.0,
            },
            "network": {
                "type": "boolean",
                "default": False,
                "description": "Allow network. Only effective if "
                "SANDBOXED_JOB_ALLOW_NETWORK=true on the host.",
            },
            "env": {
                "type": "object",
                "description": "Env vars to set inside the container. Keys must be "
                "valid shell identifiers.",
            },
            "stdin": {
                "type": "string",
                "description": "Optional stdin piped into the command.",
            },
            "stdin_bytes_b64": {
                "type": "string",
                "description": "Binary stdin payload, base64-encoded. "
                "Takes precedence over `stdin`. Used by "
                "code_asset to deliver a tar.gz of the "
                "asset contents without needing HTTP access.",
            },
        },
        "required": ["image", "command"],
    }

    def __init__(self, tenant_id: str = "", redis_url: str = ""):
        # Tenant-scoped Redis overrides for enabled / allowed_images / allow_network.
        # Set via UI: Settings → Sandbox. If not set, falls back to env vars.
        self._tenant_id = tenant_id
        self._redis_url = redis_url

    async def _resolve_settings(self) -> dict[str, Any]:
        """Merge env defaults with tenant Redis overrides. Tenant wins when set."""
        settings = {
            "enabled": (
                os.environ.get("SANDBOXED_JOB_ENABLED", "").lower()
                in ("1", "true", "yes")
            ),
            "allow_network": (
                os.environ.get("SANDBOXED_JOB_ALLOW_NETWORK", "").lower()
                in ("1", "true", "yes")
            ),
            "allowed_images": _allowed_images(),
        }
        if not (self._tenant_id and self._redis_url):
            return settings
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(self._redis_url, decode_responses=True)
            tk = f"sandbox:settings:{self._tenant_id}"
            raw = await r.hgetall(tk)
            await r.aclose()
            if raw:
                if "enabled" in raw:
                    settings["enabled"] = raw["enabled"].strip().lower() in (
                        "1",
                        "true",
                        "yes",
                    )
                if "allow_network" in raw:
                    settings["allow_network"] = raw[
                        "allow_network"
                    ].strip().lower() in ("1", "true", "yes")
                if "allowed_images" in raw and raw["allowed_images"].strip():
                    settings["allowed_images"] = sorted(
                        {
                            i.strip()
                            for i in raw["allowed_images"].split(",")
                            if i.strip()
                        }
                    )
        except Exception:
            pass  # Redis blip → fall back to env defaults silently
        return settings

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        cfg = await self._resolve_settings()
        if not cfg["enabled"]:
            return ToolResult(
                content=(
                    "sandboxed_job is disabled. Toggle ON in Settings → Sandbox, "
                    "or set SANDBOXED_JOB_ENABLED=true on the API host."
                ),
                is_error=True,
                metadata={"skipped": True, "reason": "disabled"},
            )

        image = (arguments.get("image") or "").strip()
        command = (arguments.get("command") or "").strip()
        if not (image and command):
            return ToolResult(content="image and command are required", is_error=True)

        allowed = cfg["allowed_images"]
        if not allowed:
            return ToolResult(
                content=(
                    "Allowed-images list is empty. Add at least one image in "
                    "Settings → Sandbox (e.g. 'python:3.12-slim,alpine:3.20')."
                ),
                is_error=True,
            )
        if image not in allowed:
            return ToolResult(
                content=f"Image '{image}' not in the allow-list. Allowed: {', '.join(allowed)}",
                is_error=True,
            )

        timeout = int(arguments.get("timeout_seconds", 60))
        memory_mb = int(arguments.get("memory_mb", 512))
        cpu = float(arguments.get("cpu_limit", 1.0))
        want_network = bool(arguments.get("network"))
        if want_network and not cfg["allow_network"]:
            return ToolResult(
                content="network=true requires the host operator to enable network in Settings → Sandbox (or SANDBOXED_JOB_ALLOW_NETWORK=true on the API host).",
                is_error=True,
            )

        env_vars: dict[str, str] = {}
        for k, v in (arguments.get("env") or {}).items():
            if _valid_env_name(k):
                env_vars[str(k)] = str(v)
        # stdin_bytes_b64 (binary, arbitrary) takes precedence over stdin
        # (text). This is how code_asset ships a tar.gz payload in —
        # the alternative (HTTP fetch from the pod) requires curl/wget
        # in the image and a short-lived token leak risk.
        stdin_b: bytes = b""
        raw_b64 = (arguments.get("stdin_bytes_b64") or "").strip()
        if raw_b64:
            import base64 as _b64

            try:
                stdin_b = _b64.b64decode(raw_b64)
            except Exception:
                return ToolResult(
                    content="stdin_bytes_b64 is not valid base64",
                    is_error=True,
                )
        else:
            stdin_str = arguments.get("stdin") or ""
            stdin_b = stdin_str.encode("utf-8") if stdin_str else b""

        if _in_cluster():
            logger.info("sandboxed_job: using kubernetes backend")
            return await _run_k8s(
                image=image,
                command=command,
                timeout=timeout,
                memory_mb=memory_mb,
                cpu=cpu,
                network=want_network,
                env=env_vars,
                stdin=stdin_b,
            )
        logger.info("sandboxed_job: using docker backend")
        return await _run_docker(
            image=image,
            command=command,
            timeout=timeout,
            memory_mb=memory_mb,
            cpu=cpu,
            network=want_network,
            env=env_vars,
            stdin=stdin_b,
        )


async def _run_docker(
    *,
    image: str,
    command: str,
    timeout: int,
    memory_mb: int,
    cpu: float,
    network: bool,
    env: dict[str, str],
    stdin: bytes,
) -> ToolResult:
    net_arg = [] if network else ["--network", "none"]
    env_args: list[str] = []
    for k, v in env.items():
        env_args.extend(["-e", f"{k}={v}"])

    argv = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop=ALL",
        "--memory",
        f"{memory_mb}m",
        "--cpus",
        str(cpu),
        *net_arg,
        *env_args,
        image,
        "sh",
        "-c",
        command,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return ToolResult(
            content="`docker` not found on PATH — install Docker or deploy to k8s.",
            is_error=True,
        )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin if stdin else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        _emit_sandbox_metrics(
            backend="docker",
            image=image,
            exit_code=None,
            duration_ms=timeout * 1000,
            timed_out=True,
        )
        return ToolResult(
            content=f"Container timed out after {timeout}s.",
            is_error=True,
            metadata={
                "backend": "docker",
                "image": image,
                "exit_code": None,
                "timed_out": True,
            },
        )

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    rc = proc.returncode
    body = (out + ("\n[STDERR]\n" + err if err.strip() else ""))[:8000]
    _emit_sandbox_metrics(
        backend="docker",
        image=image,
        exit_code=rc,
        duration_ms=None,
        timed_out=False,
    )
    return ToolResult(
        content=(
            f"sandboxed_job (docker) exit_code={rc}\n"
            f"  image: {image}\n"
            f"  cmd:   {shlex.join(['sh', '-c', command])}\n"
            f"--- stdout/stderr ---\n{body}"
        ),
        is_error=rc != 0,
        metadata={
            "backend": "docker",
            "image": image,
            "exit_code": rc,
            "stdout": out[:4000],
            "stderr": err[:2000],
        },
    )


async def _run_k8s(
    *,
    image: str,
    command: str,
    timeout: int,
    memory_mb: int,
    cpu: float,
    network: bool,
    env: dict[str, str],
    stdin: str,
) -> ToolResult:
    # Local import so the tool loads even when the k8s package isn't installed
    # on a docker-only developer machine.
    try:
        from kubernetes import client, config  # type: ignore
    except ImportError:
        return ToolResult(
            content="kubernetes python client not installed. Add `kubernetes>=29.0.0` to the runtime image.",
            is_error=True,
        )

    try:
        config.load_incluster_config()
    except Exception as e:
        return ToolResult(
            content=f"Failed to load in-cluster config: {e}", is_error=True
        )

    namespace = os.environ.get("SANDBOXED_JOB_NAMESPACE", "").strip()
    if not namespace:
        # Same namespace as the agent-runtime pod if nothing set.
        try:
            namespace = _K8S_NS_FILE.read_text().strip() or "abenix"
        except Exception:
            namespace = "abenix"

    job_name = f"sjob-{uuid.uuid4().hex[:10]}"
    env_list = [client.V1EnvVar(name=k, value=v) for k, v in env.items()]

    container = client.V1Container(
        name="worker",
        image=image,
        command=["sh", "-c", command],
        env=env_list,
        resources=client.V1ResourceRequirements(
            limits={"cpu": str(cpu), "memory": f"{memory_mb}Mi"},
            requests={"cpu": str(min(cpu, 0.2)), "memory": f"{min(memory_mb, 128)}Mi"},
        ),
        security_context=client.V1SecurityContext(
            run_as_non_root=True,
            run_as_user=65534,
            read_only_root_filesystem=True,
            allow_privilege_escalation=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        ),
        # Writable scratch space so read-only FS doesn't break most tools.
        volume_mounts=[
            client.V1VolumeMount(name="tmp", mount_path="/tmp"),
        ],
        stdin=bool(stdin),
        stdin_once=bool(stdin),
        tty=False,
    )

    pod_spec_kwargs: dict[str, Any] = dict(
        restart_policy="Never",
        containers=[container],
        volumes=[
            client.V1Volume(
                name="tmp", empty_dir=client.V1EmptyDirVolumeSource(size_limit="64Mi")
            )
        ],
        automount_service_account_token=False,
        enable_service_links=False,
    )
    if not network:
        # No DNS, no /etc/resolv.conf entries — egress becomes impossible
        # without a properly-configured NetworkPolicy. Defence in depth.
        pod_spec_kwargs["dns_policy"] = "None"
        pod_spec_kwargs["dns_config"] = client.V1PodDNSConfig(nameservers=["127.0.0.1"])

    pod_template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(
            labels={"app": "sandboxed-job", "job": job_name},
        ),
        spec=client.V1PodSpec(**pod_spec_kwargs),
    )

    job = client.V1Job(
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=namespace,
            labels={"app": "sandboxed-job"},
        ),
        spec=client.V1JobSpec(
            template=pod_template,
            backoff_limit=0,  # no retries — one shot
            active_deadline_seconds=timeout,  # hard kill past timeout
            ttl_seconds_after_finished=120,  # auto-clean after 2 min
            completions=1,
            parallelism=1,
        ),
    )

    batch = client.BatchV1Api()
    core = client.CoreV1Api()

    def _delete_job() -> None:
        try:
            batch.delete_namespaced_job(
                name=job_name,
                namespace=namespace,
                propagation_policy="Background",
            )
        except Exception:
            pass

    # Submit
    try:
        batch.create_namespaced_job(namespace=namespace, body=job)
    except Exception as e:
        return ToolResult(content=f"k8s job submission failed: {e}", is_error=True)

    # Poll for the pod, then for completion. Loop is bounded by timeout+30s.
    deadline = time.monotonic() + timeout + 30
    pod_name: str | None = None
    while time.monotonic() < deadline:
        pods = core.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"job={job_name}",
        ).items
        if pods:
            pod_name = pods[0].metadata.name
            phase = pods[0].status.phase
            if phase in ("Succeeded", "Failed"):
                break
        await asyncio.sleep(1.5)

    if not pod_name:
        _delete_job()
        return ToolResult(
            content=f"k8s pod for job {job_name} never became visible within deadline.",
            is_error=True,
            metadata={
                "backend": "kubernetes",
                "job_name": job_name,
                "namespace": namespace,
                "timed_out": True,
            },
        )

    try:
        resp = core.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container="worker",
            _preload_content=False,
        )
        raw_body = resp.data if hasattr(resp, "data") else resp.read()
        if isinstance(raw_body, bytes):
            raw_logs = raw_body.decode("utf-8", errors="replace")
        else:
            raw_logs = str(raw_body)
    except Exception as e:
        raw_logs = f"(log read failed: {e})"

    try:
        pod = core.read_namespaced_pod(name=pod_name, namespace=namespace)
        statuses = pod.status.container_statuses or []
        exit_code: int | None = None
        timed_out = False
        for s in statuses:
            term = getattr(s.state, "terminated", None)
            if term is not None:
                exit_code = term.exit_code
                if (term.reason or "").lower() == "deadlineexceeded":
                    timed_out = True
                break
        phase = pod.status.phase
    except Exception:
        exit_code = None
        phase = "Unknown"
        timed_out = False

    _delete_job()  # cleanup; ttlSecondsAfterFinished is the backstop.

    # 8 KB is tight: assets that cache a built binary push ~1-10 MB of
    # base64'd tar.gz through stderr. Raise the cap to 256 KB so the
    # asset's actual stdout (delimited by ___ASSET_OUT_*___) isn't
    # truncated out of existence.
    body = (raw_logs or "")[:262144]
    _emit_sandbox_metrics(
        backend="kubernetes",
        image=image,
        exit_code=exit_code,
        duration_ms=None,
        timed_out=timed_out,
    )
    return ToolResult(
        content=(
            f"sandboxed_job (k8s) exit_code={exit_code} phase={phase}\n"
            f"  namespace: {namespace}\n"
            f"  image:     {image}\n"
            f"  cmd:       {shlex.join(['sh', '-c', command])}\n"
            f"--- pod logs ---\n{body}"
        ),
        is_error=(exit_code != 0) if exit_code is not None else True,
        metadata={
            "backend": "kubernetes",
            "job_name": job_name,
            "pod_name": pod_name,
            "namespace": namespace,
            "image": image,
            "exit_code": exit_code,
            "phase": phase,
            "timed_out": timed_out,
            # code_asset extracts its delimited output from this blob, so
            # we let it see up to 256 KB — same cap as `body` above.
            "logs": raw_logs[:262144] if raw_logs else "",
        },
    )
