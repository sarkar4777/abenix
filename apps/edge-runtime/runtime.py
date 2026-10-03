"""AgentForge edge runtime — single-file pod that runs `.agent` bundles.

Listens on :8080 for HTTP, subscribes to `edge.{gateway_id}.deploy` over
MQTT, and executes agents locally. Anthropic API by default; Phase-2
plugs in a distilled local model via `model_weights/` in the bundle.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import signal
import sys
import tarfile
import threading
import time
from pathlib import Path
from typing import Any

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


# ─── config ────────────────────────────────────────────────────────────────


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
        # Only the literal string "true" opens the unsigned path, dev only
        self.allow_unsigned = (
            os.environ.get("EDGE_ALLOW_UNSIGNED", "").strip().lower() == "true"
        )
        # When set, bundles compiled for another tenant are refused
        self.tenant_id = os.environ.get("TENANT_ID", "").strip()
        self.bundle_dir = Path(os.environ.get("BUNDLE_DIR", "/var/edge/agents"))
        self.endpoint_url = os.environ.get("ENDPOINT_URL", "")
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.anthropic_base_url = os.environ.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        )
        self.bundle_dir.mkdir(parents=True, exist_ok=True)


# ─── bundle handling ───────────────────────────────────────────────────────


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
        raise SystemExit(f"edge-runtime: signing public key could not be parsed: {e}")
    if cfg.allow_unsigned:
        LOG.warning(
            "EDGE_ALLOW_UNSIGNED=true: unsigned bundles will be accepted on this "
            "gateway. Development only, never run production like this."
        )
    elif pubkey is None:
        raise SystemExit(
            "edge-runtime: no signing public key. Set SIGNING_PUBKEY_PEM or mount "
            f"it at SIGNING_PUBKEY_PATH ({cfg.signing_pubkey_path}). Fetch it from "
            "GET /api/edge/signing-key on the platform. EDGE_ALLOW_UNSIGNED=true "
            "bypasses this for local development only."
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


def _verify_signature(
    bundle_bytes: bytes, pubkey, allow_unsigned: bool = False
) -> tuple[bytes, dict]:
    """Strip the signature out, verify it, and return (raw_tar, manifest).

    Missing signature or missing pubkey fail unless allow_unsigned. A present
    but invalid signature always fails.
    """
    sig: bytes | None = None
    members: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r") as tar:
        for m in tar.getmembers():
            f = tar.extractfile(m)
            data = f.read() if f else b""
            if m.name == "signature.sig":
                sig = data
            else:
                members.append((m, data))

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
            raise BundleError(f"bundle_signature_invalid: {last}") from last

    manifest = None
    for m, data in members:
        if m.name == "agent.yaml":
            manifest = yaml.safe_load(data.decode("utf-8"))
            break
    if manifest is None:
        raise BundleError("bundle missing agent.yaml")
    return raw_tar, manifest


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
        raise BundleError(f"manifest missing fields: {sorted(missing)}")
    for t in manifest.get("tools") or []:
        if t.startswith("atlas_") or t.startswith("mcp_"):
            raise BundleError(f"tool not edge-safe: {t}")
        if t not in EDGE_SAFE_TOOLS:
            raise BundleError(f"tool not edge-safe: {t}")


def _untar_to_dir(bundle_bytes: bytes, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r") as tar:
        for m in tar.getmembers():
            if ".." in m.name or m.name.startswith("/"):
                raise BundleError(f"unsafe path in bundle: {m.name}")
            tar.extract(m, path=dest)


# ─── agent registry + executor ─────────────────────────────────────────────


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

    def install_bundle(self, bundle_bytes: bytes) -> LoadedAgent:
        pubkey = _load_pubkey(self.cfg)
        try:
            _, manifest = _verify_signature(
                bundle_bytes, pubkey, self.cfg.allow_unsigned
            )
        except BundleError as e:
            # Nothing was touched, whatever is loaded keeps serving
            LOG.error("bundle_rejected reason=%s loaded_agents=%d", e, len(self.agents))
            raise
        _validate_manifest(manifest)
        self._check_tenant(manifest)
        slug = manifest["slug"]
        dest = self.cfg.bundle_dir / slug
        _untar_to_dir(bundle_bytes, dest)
        digest = hashlib.sha256(bundle_bytes).hexdigest()
        agent = LoadedAgent(slug, dest, manifest, digest)
        with self.lock:
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
        if not self.cfg.bundle_dir.exists():
            return
        for d in self.cfg.bundle_dir.iterdir():
            try:
                manifest = yaml.safe_load((d / "agent.yaml").read_text("utf-8"))
                self._check_tenant(manifest)
                slug = manifest["slug"]
                fake_digest = hashlib.sha256(slug.encode()).hexdigest()
                self.agents[slug] = LoadedAgent(slug, d, manifest, fake_digest)
                LOG.info("agent_reloaded_from_disk slug=%s", slug)
            except Exception as e:
                LOG.warning("agent_reload_failed dir=%s err=%s", d, e)


async def _call_anthropic(
    cfg: Config, manifest: dict, system_prompt: str, user_message: str
) -> dict[str, Any]:
    if not cfg.anthropic_api_key:
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
    headers = {
        "x-api-key": cfg.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{cfg.anthropic_base_url}/v1/messages",
                json=body,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            text = ""
            for block in data.get("content", []) or []:
                if block.get("type") == "text":
                    text += block.get("text", "")
            return {"ok": True, "text": text, "usage": data.get("usage", {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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

    started = time.time()
    result = await _call_anthropic(
        cfg, agent.manifest, agent.system_prompt, user_message
    )
    duration_ms = int((time.time() - started) * 1000)
    return {
        "slug": agent.slug,
        "digest": agent.digest,
        "duration_ms": duration_ms,
        "params": params,
        "result": result,
    }


# ─── HTTP server (asyncio, no FastAPI) ─────────────────────────────────────


def _http_response(status: int, body: dict) -> bytes:
    payload = json.dumps(body).encode("utf-8")
    headers = (
        f"HTTP/1.1 {status} OK\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode("utf-8")
    return headers + payload


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
        clen = int(headers.get("content-length", "0") or "0")
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
        elif (
            method == "POST"
            and path.endswith("/bundle")
            and path.startswith("/agents/")
        ):
            slug = path[len("/agents/") : -len("/bundle")]
            try:
                a = registry.install_bundle(body_bytes)
                writer.write(_http_response(200, {"loaded": a.to_dict()}))
            except (BundleError, Exception) as e:
                writer.write(_http_response(400, {"error": str(e), "slug": slug}))
        elif method == "POST" and "/execute" in path and path.startswith("/agents/"):
            slug = path[len("/agents/") : -len("/execute")]
            agent = registry.get(slug)
            if agent is None:
                writer.write(_http_response(404, {"error": f"unknown agent {slug}"}))
            else:
                try:
                    payload = json.loads(body_bytes.decode("utf-8") or "{}")
                except Exception:
                    payload = {}
                user_message = payload.get("message", "")
                params = payload.get("params") or {}
                result = await execute_agent(cfg, agent, user_message, params)
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


# ─── platform registration ────────────────────────────────────────────────


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


# ─── MQTT subscriber ──────────────────────────────────────────────────────


def mqtt_subscriber(cfg: Config, registry: Registry) -> None:
    if not cfg.mqtt_url:
        LOG.info("mqtt_disabled")
        return
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        LOG.warning("paho-mqtt not installed; skipping MQTT subscription")
        return

    host = cfg.mqtt_url.replace("mqtt://", "").split(":")[0] or "localhost"
    port = 1883
    try:
        port = int(cfg.mqtt_url.replace("mqtt://", "").split(":")[1].split("/")[0])
    except Exception:
        pass
    topic = f"edge.{cfg.gateway_id}.deploy"

    def on_connect(client, userdata, flags, rc):
        LOG.info("mqtt_connected rc=%s topic=%s", rc, topic)
        client.subscribe(topic)

    def on_message(client, userdata, msg):
        try:
            agent = registry.install_bundle(msg.payload)
            LOG.info("mqtt_bundle_loaded slug=%s", agent.slug)
        except Exception as e:
            LOG.error("mqtt_bundle_failed err=%s", e)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(host, port, 60)
        client.loop_forever()
    except Exception as e:
        LOG.error("mqtt_loop_failed err=%s", e)


# ─── main ─────────────────────────────────────────────────────────────────


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
