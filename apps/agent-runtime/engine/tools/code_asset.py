"""Code-asset tool — run a user-uploaded repo as a pipeline step."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shlex
import time
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools.sandboxed_job import SandboxedJobTool

logger = logging.getLogger(__name__)

# Keyed by sha256(zip_content || build_command || image). The value is a
# tar.gz of /tmp/app AFTER the build step completes. On cache hit we
# inject the pre-built tree instead of the raw source + build command.
_BUILD_CACHE_DIR = Path(os.environ.get("CODE_ASSET_BUILD_CACHE", "/data/code-asset-cache"))


# Bumped when the cache-snapshot layout changes. Prior entries don't
# include /tmp/bin and were rooted at /tmp/app/*, which broke cache-hit
# replay. Increment to invalidate all prior entries cluster-wide.
_CACHE_LAYOUT_VERSION = "v2"


def _cache_key(zip_bytes: bytes, build_cmd: str, image: str) -> str:
    h = hashlib.sha256()
    h.update(_CACHE_LAYOUT_VERSION.encode())
    h.update(zip_bytes)
    h.update(build_cmd.encode())
    h.update(image.encode())
    return h.hexdigest()


def _cache_get(key: str) -> Path | None:
    p = _BUILD_CACHE_DIR / f"{key}.tgz"
    if p.exists() and p.stat().st_size > 0:
        logger.info("code_asset build-cache HIT: %s (%d bytes)", key[:12], p.stat().st_size)
        return p
    return None


def _cache_put(key: str, tgz_bytes: bytes) -> None:
    try:
        _BUILD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _BUILD_CACHE_DIR / f"{key}.tgz"
        p.write_bytes(tgz_bytes)
        logger.info("code_asset build-cache STORE: %s (%d bytes)", key[:12], len(tgz_bytes))
    except Exception as e:
        logger.warning("code_asset build-cache store failed: %s", e)


class CodeAssetTool(BaseTool):
    name = "code_asset"
    description = (
        "Execute a registered code asset (a user-uploaded zip/git repo) "
        "with a JSON input. Runs inside the sandboxed_job isolation layer "
        "using the asset's suggested image + build + run commands. Returns "
        "the parsed JSON output (or {raw: stdout} if the asset's output "
        "isn't JSON). Register assets via POST /api/code-assets."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code_asset_id": {
                "type": "string",
                "description": "UUID of the registered code asset.",
            },
            "input": {
                "type": "object",
                "description": "JSON object passed to the asset on stdin. "
                               "Shape must match the asset's declared "
                               "input_schema. Always an object, never a "
                               "bare string or number — wrap the payload "
                               "in {field: value} form.",
                "additionalProperties": True,
            },
            "timeout_seconds": {
                "type": "integer", "default": 120, "minimum": 10, "maximum": 900,
            },
            "memory_mb": {
                "type": "integer", "default": 1024, "minimum": 128, "maximum": 4096,
            },
            "allow_network": {
                "type": "boolean", "default": False,
                "description": "Needed if the asset calls external APIs "
                               "(also requires SANDBOXED_JOB_ALLOW_NETWORK=true).",
            },
        },
        "required": ["code_asset_id"],
    }

    def __init__(
        self, *, tenant_id: str = "", redis_url: str = "", db_url: str = "",
    ):
        self._tenant_id = tenant_id
        self._redis_url = redis_url
        self._db_url = db_url or os.environ.get("DATABASE_URL", "")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        asset_id = (arguments.get("code_asset_id") or "").strip()
        if not asset_id:
            return ToolResult(content="code_asset_id is required", is_error=True)

        input_payload = arguments.get("input")
        if input_payload is None:
            input_payload = {}

        asset = await _load_asset(self._db_url, self._tenant_id, asset_id)
        if asset is None:
            return ToolResult(
                content=f"Code asset {asset_id} not found (or not in your tenant).",
                is_error=True,
            )
        if asset.get("status") != "ready":
            return ToolResult(
                content=f"Code asset {asset_id} is {asset.get('status')} — wait for "
                        f"analysis to complete or re-upload.",
                is_error=True,
                metadata={"status": asset.get("status")},
            )

        image = (asset.get("suggested_image") or "").strip()
        build_cmd = (asset.get("suggested_build_command") or "true").strip()
        run_cmd = (asset.get("suggested_run_command") or "").strip()
        storage_uri = (asset.get("storage_uri") or "").strip()
        if not (image and run_cmd and storage_uri):
            return ToolResult(
                content="Code asset is missing image/run_command/storage_uri — analysis probably failed.",
                is_error=True,
            )

        # Validate input against schema if declared
        in_schema = asset.get("input_schema") or None
        if in_schema:
            err = _validate_against_schema(input_payload, in_schema)
            if err:
                return ToolResult(
                    content=f"Input does not match asset's input_schema: {err}",
                    is_error=True,
                )

        import base64
        zip_path = asset.get("storage_uri") or ""
        max_inline = int(os.environ.get("CODE_ASSET_MAX_INLINE_BYTES", "400000"))
        want_network = bool(arguments.get("allow_network", False))

        use_inline = False
        try:
            import pathlib as _p
            p = _p.Path(zip_path)
            if p.exists() and p.stat().st_size <= max_inline:
                use_inline = True
        except Exception as e:
            logger.debug("inline read failed, will fall back to HTTP: %s", e)

        input_json = json.dumps(input_payload)
        input_b64 = base64.b64encode(input_json.encode()).decode()

        # Collect secrets (env vars) for the run. They're NOT passed on
        # the command line — they live as env, so `ps` + logs never show
        # them. See _collect_secrets for the revealing-at-runtime path.
        run_env = await _collect_secrets(
            self._db_url, self._tenant_id, asset_id,
        )
        # Mix in any caller-supplied env too (lowest priority — secrets win).
        for k, v in (arguments.get("env") or {}).items():
            if k not in run_env:
                run_env[str(k)] = str(v)

        if use_inline:
            import io as _io
            import tarfile as _tarfile
            import zipfile as _zipfile

            def _zip_to_tgz_b64(zip_bytes: bytes) -> str:
                out = _io.BytesIO()
                with _tarfile.open(fileobj=out, mode="w:gz") as tf:
                    with _zipfile.ZipFile(_io.BytesIO(zip_bytes)) as zf:
                        for name in zf.namelist():
                            if name.endswith("/"):
                                continue
                            data = zf.read(name)
                            info = _tarfile.TarInfo(name=name)
                            info.size = len(data)
                            info.mode = 0o644
                            tf.addfile(info, _io.BytesIO(data))
                return base64.b64encode(out.getvalue()).decode()

            import pathlib as _pathlib
            zip_bytes = _pathlib.Path(zip_path).read_bytes()
            cache_k = _cache_key(zip_bytes, build_cmd, image)
            cached_tgz = _cache_get(cache_k)

            # Wrap the run command's stdout in explicit sentinels so we
            # can fish out the asset's actual output reliably, even when
            # the k8s pod log merges stdout + stderr and the build-cache
            # base64 blob pushes everything past any tail-window we read.
            run_wrapped = (
                "echo '___ASSET_OUT_START___'; "
                f"cat /tmp/input.json | {{ {run_cmd}; }}; "
                "echo '___ASSET_OUT_END___'"
            )

            if cached_tgz is not None:
                asset_tgz_b64 = base64.b64encode(cached_tgz.read_bytes()).decode()
                bash = (
                    "set -e; "
                    "mkdir -p /tmp/app; "
                    'printf "%s" "$_ASSET_TGZ_B64" | base64 -d > /tmp/asset.tgz; '
                    "cd /tmp && tar -xzf /tmp/asset.tgz; "
                    'printf "%s" "$_ASSET_INPUT_B64" | base64 -d > /tmp/input.json; '
                    f"{run_wrapped}"
                )
            else:
                # Snapshot captures /tmp/app/* + /tmp/bin (common Go/Rust
                # binary output location). Anything else the build put
                # under /tmp won't survive — authors who need more must
                # emit it into /tmp/app.
                asset_tgz_b64 = _zip_to_tgz_b64(zip_bytes)
                bash = (
                    "set -e; "
                    "mkdir -p /tmp/app; "
                    'printf "%s" "$_ASSET_TGZ_B64" | base64 -d > /tmp/asset.tgz; '
                    "cd /tmp/app && tar -xzf /tmp/asset.tgz; "
                    f"{{ {build_cmd}; }} 1>&2; "
                    # Snapshot from /tmp so we pick up both the source tree
                    # (app/) AND the compiled binary (bin). tar --ignore-
                    # failed-read skips bin if it doesn't exist, letting
                    # interpreted assets (Python/Ruby) reuse this path.
                    "echo '___BUILD_CACHE_START___' >&2; "
                    "cd /tmp && tar -czf - --ignore-failed-read app bin 2>/dev/null | base64 >&2; "
                    "echo '___BUILD_CACHE_END___' >&2; "
                    'printf "%s" "$_ASSET_INPUT_B64" | base64 -d > /tmp/input.json; '
                    f"{run_wrapped}"
                )

            run_env["_ASSET_TGZ_B64"] = asset_tgz_b64
            run_env["_ASSET_INPUT_B64"] = input_b64

            sandbox = SandboxedJobTool(tenant_id=self._tenant_id, redis_url=self._redis_url)
            sandbox_result = await sandbox.execute({
                "image": image,
                "command": bash,
                "timeout_seconds": int(arguments.get("timeout_seconds", 120)),
                "memory_mb": int(arguments.get("memory_mb", 1024)),
                "cpu_limit": 2.0,
                "network": want_network,
                "env": run_env,
            })

            # Extract and store the build snapshot from stderr if this was
            # a cache miss and the sandbox succeeded.
            if cached_tgz is None and not sandbox_result.is_error:
                try:
                    logs = sandbox_result.metadata.get("logs") or sandbox_result.content or ""
                    start_marker = "___BUILD_CACHE_START___"
                    end_marker = "___BUILD_CACHE_END___"
                    si = logs.find(start_marker)
                    ei = logs.find(end_marker)
                    if si >= 0 and ei > si:
                        b64_blob = logs[si + len(start_marker):ei].strip()
                        if b64_blob:
                            _cache_put(cache_k, base64.b64decode(b64_blob))
                except Exception as e:
                    logger.debug("build-cache extraction failed: %s", e)
        else:
            # HTTP fallback for large assets. Same security posture as
            # before: the API mints a short-lived access token and passes
            # it via env so the pod can fetch its code.
            api_base = os.environ.get(
                "CODE_ASSET_DOWNLOAD_BASE_URL",
                "http://abenix-api.abenix.svc.cluster.local:8000",
            )
            download_url = f"{api_base}/api/code-assets/{asset_id}/download"
            auth_header = os.environ.get("CODE_ASSET_DOWNLOAD_TOKEN", "")

            # Per-language bootstrap — matches the image ecosystem.
            if image.startswith(("python:", "python3:")):
                boot = (
                    'python - <<PYEOF\n'
                    'import os, urllib.request, zipfile, io\n'
                    'req = urllib.request.Request(os.environ["_DL_URL"])\n'
                    'auth = os.environ.get("_DL_AUTH", "")\n'
                    'if auth: req.add_header("Authorization", auth)\n'
                    'data = urllib.request.urlopen(req, timeout=60).read()\n'
                    'zipfile.ZipFile(io.BytesIO(data)).extractall("/tmp/app")\n'
                    'PYEOF'
                )
            elif image.startswith(("node:", "node")):
                boot = (
                    'node -e "'
                    'const https=require(\'http\'),url=new URL(process.env._DL_URL),'
                    'fs=require(\'fs\'),{execSync}=require(\'child_process\');'
                    'const buf=[];'
                    'https.get(url,{headers:{Authorization:process.env._DL_AUTH||\'\'}},r=>{'
                    'r.on(\'data\',c=>buf.push(c));'
                    'r.on(\'end\',()=>{'
                    'fs.writeFileSync(\'/tmp/asset.zip\',Buffer.concat(buf));'
                    'try{execSync(\'cd /tmp/app && unzip -q -o /tmp/asset.zip\');}'
                    'catch(e){console.error(\'no unzip; try a -slim image or pre-bake unzip\');process.exit(1);}'
                    '});'
                    '});"'
                )
            else:
                # Generic fallback: try wget+tar (if the asset is already
                # repackaged as tar.gz) OR curl+tar, then finally error.
                boot = (
                    'if command -v wget >/dev/null 2>&1; then '
                    '  wget -q --header="Authorization: $_DL_AUTH" -O /tmp/asset.zip "$_DL_URL"; '
                    'elif command -v curl >/dev/null 2>&1; then '
                    '  curl -fsSL -H "Authorization: $_DL_AUTH" -o /tmp/asset.zip "$_DL_URL"; '
                    'else echo "no fetcher in this image" >&2; exit 1; fi; '
                    'if command -v unzip >/dev/null 2>&1; then '
                    '  cd /tmp/app && unzip -q -o /tmp/asset.zip; '
                    'else echo "no unzip in this image; switch to inline delivery by '
                    'shrinking the asset under CODE_ASSET_MAX_INLINE_BYTES" >&2; exit 1; fi'
                )

            run_env["_DL_URL"] = download_url
            run_env["_DL_AUTH"] = auth_header

            bash = (
                "set -e; "
                "mkdir -p /tmp/app; "
                f"{boot}; "
                "cd /tmp/app; "
                f"echo {shlex.quote(input_b64)} | base64 -d > /tmp/input.json; "
                f"{{ {build_cmd}; }} 1>&2; "
                f"cat /tmp/input.json | {{ {run_cmd}; }}"
            )
            # HTTP path requires network (by definition).
            want_network = True

            sandbox = SandboxedJobTool(tenant_id=self._tenant_id, redis_url=self._redis_url)
            sandbox_result = await sandbox.execute({
                "image": image,
                "command": bash,
                "timeout_seconds": int(arguments.get("timeout_seconds", 120)),
                "memory_mb": int(arguments.get("memory_mb", 1024)),
                "cpu_limit": 2.0,
                "network": want_network,
                "env": run_env,
            })

        if sandbox_result.is_error:
            return ToolResult(
                content=f"Code asset execution failed:\n{sandbox_result.content}",
                is_error=True,
                metadata={
                    "code_asset_id": asset_id,
                    "sandbox_backend": sandbox_result.metadata.get("backend"),
                    "exit_code": sandbox_result.metadata.get("exit_code"),
                },
            )

        # sandboxed_job uses `stdout` on the docker backend and `logs` on
        # the k8s backend — take whichever is present. Both contain the
        # full stdout stream we need to parse.
        stdout = (
            sandbox_result.metadata.get("stdout")
            or sandbox_result.metadata.get("logs")
            or ""
        )
        logger.info("code_asset: raw stdout (%d bytes): %s", len(stdout), stdout[:1000])

        # Extract what's between our explicit output sentinels — this is
        # the ONLY content the asset itself wrote to stdout after running.
        # Without sentinels, the build-cache base64 blob (which the k8s
        # log API merges in) swamps any tail-window heuristic.
        asset_out = ""
        s_start = stdout.find("___ASSET_OUT_START___")
        s_end = stdout.find("___ASSET_OUT_END___")
        if s_start >= 0 and s_end > s_start:
            asset_out = stdout[s_start + len("___ASSET_OUT_START___"):s_end].strip()
        # Fallback to the old heuristic — useful for legacy assets that
        # predate the sentinel wrapper.
        if not asset_out:
            for line in reversed(stdout.splitlines()):
                s = line.strip()
                if s.startswith(("{", "[")):
                    asset_out = s
                    break
        if not asset_out:
            asset_out = stdout.strip()

        parsed: Any
        try:
            parsed = json.loads(asset_out)
        except Exception:
            parsed = {"raw": asset_out[:4000]}

        # Validate against output_schema if declared (log but don't fail —
        # a non-matching output is data the caller should still see).
        out_schema = asset.get("output_schema") or None
        schema_ok = True
        schema_err = ""
        if out_schema:
            err = _validate_against_schema(parsed, out_schema)
            if err:
                schema_ok = False
                schema_err = err

        await _record_last_test(self._db_url, asset_id, input_payload, parsed, schema_ok)

        return ToolResult(
            content=json.dumps({
                "result": parsed,
                "schema_ok": schema_ok,
                "schema_error": schema_err,
            }),
            metadata={
                "code_asset_id": asset_id,
                "exit_code": sandbox_result.metadata.get("exit_code"),
                "backend": sandbox_result.metadata.get("backend"),
                "schema_ok": schema_ok,
            },
        )


# ─── DB helpers (keep the tool importable without SQLAlchemy in the hot path) ─

async def _load_asset(
    db_url: str, tenant_id: str, asset_id: str,
) -> dict[str, Any] | None:
    if not db_url:
        return None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as sql_text
    except ImportError:
        return None
    try:
        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)
        async with engine.begin() as conn:
            params: dict[str, Any] = {"aid": asset_id}
            where = "id = CAST(:aid AS uuid)"
            if tenant_id:
                where += " AND tenant_id = CAST(:tid AS uuid)"
                params["tid"] = tenant_id
            r = await conn.execute(
                sql_text(
                    f"SELECT id, status, storage_uri, suggested_image, "
                    f"suggested_build_command, suggested_run_command, "
                    f"input_schema, output_schema "
                    f"FROM code_assets WHERE {where}"
                ),
                params,
            )
            row = r.first()
        await engine.dispose()
    except Exception as e:
        logger.debug("code_asset load failed: %s", e)
        return None
    if not row:
        return None
    return {
        "id": str(row[0]),
        "status": row[1].value if hasattr(row[1], "value") else str(row[1]),
        "storage_uri": row[2],
        "suggested_image": row[3],
        "suggested_build_command": row[4],
        "suggested_run_command": row[5],
        "input_schema": row[6],
        "output_schema": row[7],
    }


async def _record_last_test(
    db_url: str, asset_id: str, input_payload: Any, output: Any, ok: bool,
) -> None:
    if not db_url:
        return
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as sql_text
    except ImportError:
        return
    try:
        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)
        async with engine.begin() as conn:
            await conn.execute(
                sql_text(
                    "UPDATE code_assets SET "
                    "  last_test_input = CAST(:inp AS jsonb), "
                    "  last_test_output = CAST(:out AS jsonb), "
                    "  last_test_ok = :ok, "
                    "  last_test_at = NOW() "
                    "WHERE id = CAST(:aid AS uuid)"
                ),
                {
                    "aid": asset_id,
                    "inp": json.dumps(input_payload)[:20_000],
                    "out": json.dumps(output)[:20_000],
                    "ok": ok,
                },
            )
        await engine.dispose()
    except Exception as e:
        logger.debug("code_asset record_last_test failed: %s", e)


def _validate_against_schema(payload: Any, schema: dict[str, Any]) -> str:
    """Validate a payload against a JSON Schema."""
    if not isinstance(schema, dict) or not schema:
        return ""
    # Try full JSON Schema validation first
    try:
        import jsonschema  # type: ignore
        try:
            jsonschema.validate(payload, schema)
            return ""
        except jsonschema.ValidationError as e:
            # e.message on its own is clearer than the default string
            # which includes the full schema dump.
            pth = list(getattr(e, "absolute_path", []))
            loc = "/".join(str(x) for x in pth) if pth else "(root)"
            return f"{loc}: {e.message}"
        except jsonschema.SchemaError as e:
            return f"invalid schema: {e.message}"
    except ImportError:
        pass
    # Minimal fallback
    typ = schema.get("type")
    if typ == "object" and not isinstance(payload, dict):
        return f"expected object, got {type(payload).__name__}"
    if typ == "array" and not isinstance(payload, list):
        return f"expected array, got {type(payload).__name__}"
    if typ == "string" and not isinstance(payload, str):
        return f"expected string, got {type(payload).__name__}"
    if typ == "number" and not isinstance(payload, (int, float)):
        return f"expected number, got {type(payload).__name__}"
    if typ == "integer" and not isinstance(payload, int):
        return f"expected integer, got {type(payload).__name__}"
    if typ == "boolean" and not isinstance(payload, bool):
        return f"expected boolean, got {type(payload).__name__}"
    required = schema.get("required") or []
    if isinstance(payload, dict) and required:
        missing = [k for k in required if k not in payload]
        if missing:
            return f"missing required keys: {missing}"
    return ""


async def _collect_secrets(
    db_url: str, tenant_id: str, asset_id: str,
) -> dict[str, str]:
    """Load per-asset secrets and return them as a {KEY: value} dict"""
    if not db_url:
        return {}
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as sql_text
    except ImportError:
        return {}
    try:
        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)
        rows: list[tuple[str, bytes, bytes]] = []
        async with engine.begin() as conn:
            try:
                r = await conn.execute(
                    sql_text(
                        "SELECT name, nonce, ciphertext FROM code_asset_secrets "
                        "WHERE code_asset_id = CAST(:aid AS uuid)"
                    ),
                    {"aid": asset_id},
                )
                rows = [(row[0], bytes(row[1]), bytes(row[2])) for row in r.fetchall()]
            except Exception:
                # Table doesn't exist → no secrets configured on this cluster
                rows = []
        await engine.dispose()
    except Exception as e:
        logger.debug("code_asset secrets load failed: %s", e)
        return {}

    if not rows:
        return {}

    key_hex = os.environ.get("CODE_ASSET_SECRETS_KEY", "").strip()
    if not key_hex:
        logger.warning(
            "code_asset has %d stored secrets for asset %s but "
            "CODE_ASSET_SECRETS_KEY is not set — skipping decryption",
            len(rows), asset_id[:8],
        )
        return {}
    try:
        key = bytes.fromhex(key_hex)
        if len(key) not in (16, 24, 32):
            logger.warning("CODE_ASSET_SECRETS_KEY must be 16/24/32 hex-bytes")
            return {}
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aes = AESGCM(key)
        out: dict[str, str] = {}
        for name, nonce, ct in rows:
            try:
                plain = aes.decrypt(nonce, ct, None).decode("utf-8")
                out[name] = plain
            except Exception as e:
                logger.warning("failed to decrypt secret %s: %s", name, e)
        return out
    except ImportError:
        logger.warning("cryptography not installed — secrets skipped")
        return {}
    except Exception as e:
        logger.debug("secrets decrypt failed: %s", e)
        return {}
