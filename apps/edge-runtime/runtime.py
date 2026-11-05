"""Abenix edge runtime, one pod that runs signed `.agent` bundles on port 8080."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import re
import shutil
import signal
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

LOG = logging.getLogger("edge-runtime")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


EDGE_SAFE_TOOLS = {
    "mqtt_publish",
    "mqtt_subscribe",
    "current_time",
    "windowed_state",
    "connector_call",
    "code_executor",
}


SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,94}")
ROUTE_RE = re.compile(r"/agents/([^/]+)/(bundle|execute)")
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_MEMBERS = 256
CODE_TIMEOUT_SECONDS = 5
CODE_OUTPUT_BYTES = 64 * 1024
OAUTH_BETA = "oauth-2025-04-20"
SAVED_BUNDLE = "bundle.agent"


def deploy_topic(gateway_id: str, slug: str = "+") -> str:
    return f"edge/{gateway_id}/deploy/{slug}"


def ack_topic(gateway_id: str, slug: str) -> str:
    return f"edge/{gateway_id}/ack/{slug}"


class Config:
    def __init__(self) -> None:
        self.gateway_id = os.environ.get("GATEWAY_ID", "edge-local")
        self.gateway_name = os.environ.get("GATEWAY_NAME", self.gateway_id)
        self.platform_url = os.environ.get(
            "PLATFORM_URL", "http://host.docker.internal:8000"
        )
        self.platform_token = os.environ.get("PLATFORM_TOKEN", "")
        self.mqtt_url = os.environ.get("MQTT_URL", "").strip()
        self.signing_pubkey_pem = os.environ.get("SIGNING_PUBKEY_PEM", "").strip()
        self.signing_pubkey_path = os.environ.get(
            "SIGNING_PUBKEY_PATH", "/etc/edge/signing_pub.pem"
        )
        # Only the literal string "true" opens these, development only
        self.allow_unsigned = (
            os.environ.get("EDGE_ALLOW_UNSIGNED", "").strip() == "true"
        )
        self.allow_no_auth = os.environ.get("EDGE_ALLOW_NO_AUTH", "").strip() == "true"
        self.code_enabled = (
            os.environ.get("EDGE_ENABLE_CODE_EXECUTOR", "").strip() == "true"
        )
        self.auth_token = os.environ.get("EDGE_AUTH_TOKEN", "").strip()
        # When set, bundles compiled for another tenant are refused
        self.tenant_id = os.environ.get("TENANT_ID", "").strip()
        self.bundle_dir = Path(os.environ.get("BUNDLE_DIR", "/var/edge/agents"))
        self.endpoint_url = os.environ.get("ENDPOINT_URL", "")
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        self.anthropic_auth_token = (
            os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
            or os.environ.get("CLAUDE_SUBSCRIPTION_TOKEN", "").strip()
        )
        self.anthropic_base_url = os.environ.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        )
        self.bundle_dir.mkdir(parents=True, exist_ok=True)


class BundleError(Exception):
    pass


def _load_pubkey(cfg: Config):
    pem = cfg.signing_pubkey_pem
    if not pem:
        p = Path(cfg.signing_pubkey_path)
        if p.exists():
            pem = p.read_text()
    if not pem:
        return None
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def check_startup(cfg: Config) -> None:
    """Refuse to boot a gateway that could not verify anything it is sent."""
    try:
        pubkey = _load_pubkey(cfg)
    except ValueError as e:
        raise SystemExit(
            f"edge-runtime refused to start, the signing public key could not be parsed {e}"
        )
    if cfg.allow_unsigned:
        LOG.warning(
            "EDGE_ALLOW_UNSIGNED=true, unsigned bundles will be accepted on this "
            "gateway. Development only, never run production like this."
        )
    elif pubkey is None:
        raise SystemExit(
            "edge-runtime refused to start, no signing public key. Set SIGNING_PUBKEY_PEM or mount "
            f"it at SIGNING_PUBKEY_PATH ({cfg.signing_pubkey_path}). Fetch it from "
            "GET /api/edge/signing-key on the platform. EDGE_ALLOW_UNSIGNED=true "
            "bypasses this for local development only."
        )
    if cfg.allow_no_auth:
        LOG.warning(
            "EDGE_ALLOW_NO_AUTH=true, anyone who can reach this port can install and "
            "run agents. Development only, never run production like this."
        )
    elif not cfg.auth_token:
        raise SystemExit(
            "edge-runtime refused to start, no EDGE_AUTH_TOKEN. Set it so bundle install and execute "
            "need a bearer token. EDGE_ALLOW_NO_AUTH=true bypasses this for local "
            "development only."
        )
    if cfg.code_enabled:
        LOG.warning(
            "EDGE_ENABLE_CODE_EXECUTOR=true, params.code runs for agents that list "
            "code_executor. Scrubbed environment, no shell, %d s limit.",
            CODE_TIMEOUT_SECONDS,
        )
    if cfg.tenant_id:
        LOG.info("tenant_binding tenant_id=%s", cfg.tenant_id)


def _strip_signature(bundle: bytes) -> bytes:
    """Bundle bytes with the signature.sig header and data blocks cut out."""
    off = 0
    while off + 512 <= len(bundle):
        header = bundle[off : off + 512]
        if not any(header):
            break
        name = header[:100].split(b"\0", 1)[0].decode("utf-8", "replace")
        size = int(header[124:136].replace(b"\0", b" ").strip() or b"0", 8)
        end = off + 512 + -(-size // 512) * 512
        if name == "signature.sig":
            return bundle[:off] + bundle[end:]
        off = end
    return bundle


def _read_members(bundle_bytes: bytes) -> tuple[bytes | None, list]:
    """Plain files and folders under safe relative names only, anything else refuses the bundle."""
    if len(bundle_bytes) > MAX_BUNDLE_BYTES:
        raise BundleError(f"bundle is over {MAX_BUNDLE_BYTES} bytes")
    sig: bytes | None = None
    members: list[tuple[tarfile.TarInfo, bytes]] = []
    seen: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r:") as tar:
            for m in tar:
                if len(seen) >= MAX_BUNDLE_MEMBERS:
                    raise BundleError("bundle has too many entries")
                _check_member(m)
                if m.name in seen:
                    raise BundleError(f"duplicate entry in bundle {m.name}")
                seen.add(m.name)
                f = tar.extractfile(m) if m.isreg() else None
                data = f.read() if f else b""
                if m.name == "signature.sig":
                    sig = data
                else:
                    members.append((m, data))
    except (tarfile.TarError, EOFError, ValueError) as e:
        raise BundleError(f"bundle is not a readable tar file {e}") from e
    return sig, members


def _check_member(m: tarfile.TarInfo) -> None:
    if not (m.isreg() or m.isdir()):
        raise BundleError(f"bundle entry {m.name} is a link or device, refused")
    parts = m.name.split("/")
    if not m.name or m.name.startswith("/") or "\\" in m.name or ".." in parts:
        raise BundleError(f"unsafe path in bundle {m.name}")


def _verify_signature(
    bundle_bytes: bytes, pubkey, allow_unsigned: bool = False
) -> tuple[bytes, dict]:
    """Strip the signature out, verify it, and return (raw_tar, manifest).

    Missing signature or missing pubkey fail unless allow_unsigned. A present
    but invalid signature always fails.
    """
    sig, members = _read_members(bundle_bytes)

    if sig is None and not allow_unsigned:
        raise BundleError(
            "bundle is unsigned (no signature.sig). Refusing to load, set "
            "EDGE_ALLOW_UNSIGNED=true only for local development"
        )

    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as dst:
        for m, data in members:
            info = tarfile.TarInfo(name=m.name)
            info.size = len(data)
            info.mtime = m.mtime
            info.mode = m.mode or 0o644
            dst.addfile(info, io.BytesIO(data))
    raw_tar = out.getvalue()

    if sig is None:
        LOG.warning(
            "accepting UNSIGNED bundle because EDGE_ALLOW_UNSIGNED=true, "
            "development only"
        )
    elif pubkey is None:
        if not allow_unsigned:
            raise BundleError(
                "no signing public key configured, cannot verify bundle. Set "
                "SIGNING_PUBKEY_PEM or SIGNING_PUBKEY_PATH"
            )
        LOG.warning(
            "accepting UNVERIFIED bundle, no pubkey and EDGE_ALLOW_UNSIGNED=true, "
            "development only"
        )
    else:
        # platform bundles sign the received bytes minus signature.sig, older ones a rebuilt tar
        last: InvalidSignature | None = None
        for view in (_strip_signature(bundle_bytes), raw_tar):
            try:
                pubkey.verify(
                    sig,
                    view,
                    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                    hashes.SHA256(),
                )
                last = None
                break
            except InvalidSignature as e:
                last = e
        if last is not None:
            raise BundleError("bundle_signature_invalid") from last

    manifest = None
    for m, data in members:
        if m.name == "agent.yaml":
            try:
                manifest = yaml.safe_load(data.decode("utf-8"))
            except (yaml.YAMLError, UnicodeDecodeError) as e:
                raise BundleError(f"agent.yaml is not readable {e}") from e
            break
    if not isinstance(manifest, dict):
        raise BundleError("bundle missing agent.yaml")
    return raw_tar, manifest


def valid_slug(slug: Any) -> bool:
    return isinstance(slug, str) and bool(SLUG_RE.fullmatch(slug)) and ".." not in slug


def _validate_manifest(manifest: dict) -> None:
    required = {
        "name",
        "slug",
        "version",
        "model",
        "temperature",
        "max_iterations",
        "max_tokens",
        "tools",
        "edge_constraints",
    }
    missing = required - set(manifest.keys())
    if missing:
        raise BundleError(f"manifest missing fields {sorted(missing)}")
    if not valid_slug(manifest["slug"]):
        raise BundleError(f"manifest slug is not a safe name {manifest['slug']!r}")
    for t in manifest.get("tools") or []:
        if t not in EDGE_SAFE_TOOLS:
            raise BundleError(f"tool not edge-safe {t}")


def _untar_to_dir(bundle_bytes: bytes, dest: Path) -> None:
    """Write beside the live folder and swap, so a failed install leaves the old agent serving."""
    _, members = _read_members(bundle_bytes)
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{dest.name}-", dir=dest.parent))
    old = None
    try:
        for m, data in members:
            target = staging / m.name
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (staging / SAVED_BUNDLE).write_bytes(bundle_bytes)
        staging.chmod(0o755)
        if dest.exists():
            old = dest.with_name(f".old-{dest.name}-{os.getpid()}-{time.time_ns()}")
            dest.rename(old)
        staging.rename(dest)
    except BaseException:
        if old is not None and not dest.exists():
            old.rename(dest)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


class LoadedAgent:
    def __init__(self, slug: str, dir_path: Path, manifest: dict, digest: str):
        self.slug = slug
        self.dir = dir_path
        self.manifest = manifest
        self.digest = digest
        self.system_prompt = (dir_path / "system_prompt.md").read_text(encoding="utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.manifest.get("name"),
            "version": self.manifest.get("version"),
            "model": self.manifest.get("model"),
            "tools": self.manifest.get("tools", []),
            "digest": self.digest,
            "edge_constraints": self.manifest.get("edge_constraints", {}),
        }


class Registry:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.agents: dict[str, LoadedAgent] = {}
        self.lock = threading.Lock()

    def _check_tenant(self, manifest: dict) -> None:
        if not self.cfg.tenant_id:
            return
        bundle_tenant = str(manifest.get("tenant_id") or "")
        if bundle_tenant != self.cfg.tenant_id:
            LOG.error(
                "bundle_tenant_mismatch slug=%s bundle_tenant=%s runtime_tenant=%s",
                manifest.get("slug"),
                bundle_tenant or "<none>",
                self.cfg.tenant_id,
            )
            raise BundleError(
                f"bundle tenant_id {bundle_tenant or '<none>'} does not match "
                f"runtime TENANT_ID {self.cfg.tenant_id}"
            )

    def install_bundle(
        self, bundle_bytes: bytes, expected_slug: str | None = None
    ) -> LoadedAgent:
        try:
            pubkey = _load_pubkey(self.cfg)
            _, manifest = _verify_signature(
                bundle_bytes, pubkey, self.cfg.allow_unsigned
            )
            _validate_manifest(manifest)
            self._check_tenant(manifest)
            slug = manifest["slug"]
            if expected_slug is not None and expected_slug != slug:
                raise BundleError(
                    f"bundle is for agent {slug}, it was sent to {expected_slug}"
                )
        except (BundleError, ValueError) as e:
            # Nothing was touched, whatever is loaded keeps serving
            LOG.error("bundle_rejected reason=%s loaded_agents=%d", e, len(self.agents))
            raise BundleError(str(e)) from e
        digest = hashlib.sha256(bundle_bytes).hexdigest()
        with self.lock:
            current = self.agents.get(slug)
            if current is not None and current.digest == digest:
                return current
            dest = self.cfg.bundle_dir / slug
            _untar_to_dir(bundle_bytes, dest)
            agent = LoadedAgent(slug, dest, manifest, digest)
            self.agents[slug] = agent
        LOG.info("agent_loaded slug=%s digest=%s", slug, digest)
        return agent

    def get(self, slug: str) -> LoadedAgent | None:
        with self.lock:
            return self.agents.get(slug)

    def list(self) -> list[LoadedAgent]:
        with self.lock:
            return list(self.agents.values())

    def reload_from_disk(self) -> None:
        """Runs the saved bundle through the full install, so a tampered volume stays out."""
        if not self.cfg.bundle_dir.exists():
            return
        for d in self.cfg.bundle_dir.iterdir():
            if d.name.startswith("."):
                shutil.rmtree(d, ignore_errors=True)
                continue
            saved = d / SAVED_BUNDLE
            try:
                if not saved.exists():
                    raise BundleError("no saved bundle, push the agent again")
                agent = self.install_bundle(saved.read_bytes(), expected_slug=d.name)
                LOG.info("agent_reloaded_from_disk slug=%s", agent.slug)
            except Exception as e:
                LOG.warning("agent_reload_failed dir=%s err=%s", d, e)


def _llm_headers(cfg: Config) -> dict[str, str] | None:
    headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    if cfg.anthropic_api_key:
        return {**headers, "x-api-key": cfg.anthropic_api_key}
    if cfg.anthropic_auth_token:
        return {
            **headers,
            "authorization": f"Bearer {cfg.anthropic_auth_token}",
            "anthropic-beta": OAUTH_BETA,
        }
    return None


async def _call_anthropic(
    cfg: Config,
    manifest: dict,
    system_prompt: str,
    user_message: str,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    headers = _llm_headers(cfg)
    if headers is None:
        return {
            "ok": False,
            "error": "ANTHROPIC_API_KEY not configured on edge runtime",
            "stub": True,
            "echo": user_message,
        }
    body = {
        "model": manifest.get("model", "claude-sonnet-4-5-20250929"),
        "max_tokens": int(manifest.get("max_tokens", 1024)),
        "temperature": float(manifest.get("temperature", 0.7)),
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(
                f"{cfg.anthropic_base_url.rstrip('/')}/v1/messages",
                json=body,
                headers=headers,
            )
            if r.status_code >= 300:
                return {
                    "ok": False,
                    "error": f"model call answered {r.status_code} {r.text[:300]}",
                }
            data = r.json()
            text = ""
            for block in data.get("content", []) or []:
                if block.get("type") == "text":
                    text += block.get("text", "")
            return {"ok": True, "text": text, "usage": data.get("usage", {})}
    except Exception as e:
        return {"ok": False, "error": f"model call failed {type(e).__name__} {e}"}


async def run_code(code: str, timeout_s: float) -> dict[str, Any]:
    """python3 with no shell, no inherited environment and its own process group."""
    with tempfile.TemporaryDirectory(prefix="edge-code-") as scratch:
        proc = await asyncio.create_subprocess_exec(
            sys.executable or "python3",
            "-I",
            "-c",
            code,
            cwd=scratch,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": scratch},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            await proc.wait()
            return {"ok": False, "error": "code_executor_timeout"}
    return {
        "ok": proc.returncode == 0,
        "stdout": out[:CODE_OUTPUT_BYTES].decode("utf-8", "replace"),
        "stderr": err[:CODE_OUTPUT_BYTES].decode("utf-8", "replace"),
        "exit_code": proc.returncode,
    }


async def _run_agent(
    cfg: Config,
    agent: LoadedAgent,
    user_message: str,
    params: dict[str, Any],
    max_runtime: float,
) -> dict[str, Any]:
    code = params.get("code") if isinstance(params, dict) else None
    if code:
        if not cfg.code_enabled:
            return {
                "ok": False,
                "error": "code_executor is off on this gateway, set EDGE_ENABLE_CODE_EXECUTOR=true to allow it",
            }
        if "code_executor" not in (agent.manifest.get("tools") or []):
            return {"ok": False, "error": "code_executor not in tool whitelist"}
        if not isinstance(code, str):
            return {"ok": False, "error": "params.code must be text"}
        return await run_code(code, min(CODE_TIMEOUT_SECONDS, max_runtime))
    return await _call_anthropic(
        cfg, agent.manifest, agent.system_prompt, user_message, max_runtime
    )


async def execute_agent(
    cfg: Config, agent: LoadedAgent, user_message: str, params: dict[str, Any]
) -> dict[str, Any]:
    constraints = agent.manifest.get("edge_constraints", {})
    max_payload = int(constraints.get("max_payload_bytes", 65536))
    if len(user_message.encode("utf-8")) > max_payload:
        return {"ok": False, "error": f"payload exceeds {max_payload} bytes"}

    weights_dir = agent.dir / "model_weights"
    if weights_dir.exists() and any(weights_dir.iterdir()):
        return {
            "ok": False,
            "error": "local model_weights present but no local inference shipped in v1.1",
            "phase_2": True,
        }

    max_runtime = float(constraints.get("max_runtime_seconds") or 30)
    started = time.time()
    try:
        result = await asyncio.wait_for(
            _run_agent(cfg, agent, user_message, params, max_runtime), max_runtime
        )
    except asyncio.TimeoutError:
        result = {
            "ok": False,
            "error": f"max_runtime_seconds exceeded after {max_runtime:g} s",
            "error_code": "max_runtime_exceeded",
        }
    duration_ms = int((time.time() - started) * 1000)
    return {
        "slug": agent.slug,
        "digest": agent.digest,
        "duration_ms": duration_ms,
        "params": params,
        "result": result,
    }


def _http_response(status: int, body: dict, extra_headers: str = "") -> bytes:
    payload = json.dumps(body).encode("utf-8")
    headers = (
        f"HTTP/1.1 {status} OK\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"{extra_headers}"
        f"Connection: close\r\n\r\n"
    ).encode("utf-8")
    return headers + payload


def authorized(cfg: Config, header: str) -> bool:
    if cfg.allow_no_auth:
        return True
    if not cfg.auth_token:
        return False
    scheme, _, token = header.strip().partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(
        token.strip().encode("utf-8"), cfg.auth_token.encode("utf-8")
    )


async def _handle_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    cfg: Config,
    registry: Registry,
) -> None:
    try:
        request_line = await reader.readline()
        if not request_line:
            return
        parts = request_line.decode("latin-1").strip().split()
        if len(parts) < 3:
            return
        method, path, _ = parts
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break
            k, _, v = line.decode("latin-1").partition(":")
            headers[k.strip().lower()] = v.strip()
        route = ROUTE_RE.fullmatch(path) if method == "POST" else None
        if route and not authorized(cfg, headers.get("authorization", "")):
            writer.write(
                _http_response(
                    401,
                    {
                        "error": "unauthorized",
                        "message": "Send Authorization: Bearer with this gateway's EDGE_AUTH_TOKEN",
                    },
                    "WWW-Authenticate: Bearer\r\n",
                )
            )
            await writer.drain()
            return
        clen = int(headers.get("content-length", "0") or "0")
        if clen > MAX_BUNDLE_BYTES:
            writer.write(
                _http_response(413, {"error": f"body over {MAX_BUNDLE_BYTES} bytes"})
            )
            await writer.drain()
            return
        body_bytes = await reader.readexactly(clen) if clen > 0 else b""

        if method == "GET" and path == "/health":
            writer.write(
                _http_response(
                    200,
                    {
                        "status": "ok",
                        "agents": len(registry.agents),
                        "gateway_id": cfg.gateway_id,
                    },
                )
            )
        elif method == "GET" and path == "/agents":
            writer.write(
                _http_response(200, {"agents": [a.to_dict() for a in registry.list()]})
            )
        elif route and route.group(2) == "bundle":
            slug = route.group(1)
            if not valid_slug(slug):
                writer.write(_http_response(400, {"error": "unsafe agent slug"}))
            else:
                try:
                    a = await asyncio.to_thread(
                        registry.install_bundle, body_bytes, slug
                    )
                    writer.write(_http_response(200, {"loaded": a.to_dict()}))
                except Exception as e:
                    writer.write(_http_response(400, {"error": str(e), "slug": slug}))
        elif route:
            slug = route.group(1)
            agent = registry.get(slug) if valid_slug(slug) else None
            if agent is None:
                writer.write(_http_response(404, {"error": f"unknown agent {slug}"}))
            else:
                try:
                    payload = json.loads(body_bytes.decode("utf-8") or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("not an object")
                    if not isinstance(payload.get("message", ""), str):
                        raise ValueError("message must be text")
                except ValueError as e:
                    writer.write(
                        _http_response(400, {"error": f"body is not valid {e}"})
                    )
                else:
                    result = await execute_agent(
                        cfg,
                        agent,
                        payload.get("message", ""),
                        payload.get("params") or {},
                    )
                    writer.write(_http_response(200, result))
        else:
            writer.write(_http_response(404, {"error": "not found", "path": path}))
        await writer.drain()
    except Exception as e:
        LOG.exception("http_error err=%s", e)
        try:
            writer.write(_http_response(500, {"error": str(e)}))
            await writer.drain()
        except Exception:
            pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def http_server(cfg: Config, registry: Registry, port: int) -> None:
    server = await asyncio.start_server(
        lambda r, w: _handle_request(r, w, cfg, registry), "0.0.0.0", port
    )
    LOG.info("http_listening port=%d", port)
    async with server:
        await server.serve_forever()


async def register_with_platform(cfg: Config) -> bool:
    if not cfg.platform_url or not cfg.platform_token:
        LOG.warning(
            "skip_register: PLATFORM_URL=%s PLATFORM_TOKEN=%s",
            bool(cfg.platform_url),
            bool(cfg.platform_token),
        )
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                f"{cfg.platform_url.rstrip('/')}/api/edge/gateways/register",
                json={
                    "gateway_id": cfg.gateway_id,
                    "name": cfg.gateway_name,
                    "endpoint_url": cfg.endpoint_url,
                },
                headers={"Authorization": f"Bearer {cfg.platform_token}"},
            )
            r.raise_for_status()
            LOG.info("registered_with_platform status=%d", r.status_code)
            return True
    except Exception as e:
        LOG.warning("register_failed err=%s", e)
        return False


def mqtt_subscriber(cfg: Config, registry: Registry) -> None:
    if not cfg.mqtt_url:
        LOG.info("mqtt_disabled")
        return
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        LOG.warning("paho-mqtt not installed, skipping MQTT subscription")
        return

    u = urlparse(cfg.mqtt_url if "://" in cfg.mqtt_url else f"mqtt://{cfg.mqtt_url}")
    host, port = u.hostname or "localhost", u.port or 1883
    topic = deploy_topic(cfg.gateway_id)
    prefix = deploy_topic(cfg.gateway_id, "")

    def on_connect(client, userdata, flags, rc, props=None):
        LOG.info("mqtt_connected rc=%s topic=%s", rc, topic)
        client.subscribe(topic, qos=1)

    def on_message(client, userdata, msg):
        # clearing a retained bundle arrives as an empty message
        if not msg.payload or not msg.topic.startswith(prefix):
            return
        slug = msg.topic[len(prefix) :]
        digest = hashlib.sha256(msg.payload).hexdigest()
        ack: dict[str, Any] = {"slug": slug, "digest": digest}
        try:
            agent = registry.install_bundle(msg.payload, slug)
            ack["ok"] = True
            LOG.info("mqtt_bundle_loaded slug=%s", agent.slug)
        except Exception as e:
            ack.update(ok=False, error=str(e))
            LOG.error("mqtt_bundle_failed slug=%s err=%s", slug, e)
        client.publish(ack_topic(cfg.gateway_id, slug), json.dumps(ack), qos=1)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if u.username:
        client.username_pw_set(u.username, u.password)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(1, 30)
    client.connect_async(host, port, 30)
    try:
        client.loop_forever(retry_first_connection=True)
    except Exception as e:
        LOG.error("mqtt_loop_failed err=%s", e)


async def amain(port: int) -> None:
    cfg = Config()
    check_startup(cfg)
    registry = Registry(cfg)
    registry.reload_from_disk()

    asyncio.create_task(_register_loop(cfg))
    threading.Thread(target=mqtt_subscriber, args=(cfg, registry), daemon=True).start()
    await http_server(cfg, registry, port)


async def _register_loop(cfg: Config) -> None:
    while True:
        await register_with_platform(cfg)
        await asyncio.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()

    def _stop(*_):
        LOG.info("shutting down")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    asyncio.run(amain(args.port))


if __name__ == "__main__":
    main()
