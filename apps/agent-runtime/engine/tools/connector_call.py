"""connector_call — execute one operation against a tenant-owned connector.

Resolves the connector + preset, fills the URL/body/query templates from
``parameters``, applies the connector's auth, and returns parsed response.
The secret is the write-only one saved in Admin -> Connectors, read from the
tool credentials store under ``secret_key(connector_id)`` for the connector's
own tenant. Every URL and redirect hop goes through ``engine.url_guard``.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from engine import credentials, url_guard
from engine.tools.base import READ_ONLY, BaseTool, Effect, ToolResult

LEGACY_SECRET_NOTICE = (
    "Re-enter this connector's secret, it used to point at an Abenix API key"
)


def secret_key(connector_id: Any) -> str:
    """Credentials store key for one connector's secret."""
    return f"CONNECTOR_{uuid.UUID(str(connector_id)).hex.upper()}_SECRET"


def auth_headers(
    auth_type: str, secret: str | None, config: dict[str, Any] | None
) -> dict[str, str]:
    config = config or {}
    if not secret:
        return {}
    if auth_type in ("bearer", "oauth2"):
        return {"Authorization": f"Bearer {secret}"}
    if auth_type == "api_key":
        return {str(config.get("auth_header_name") or "X-API-Key"): secret}
    if auth_type == "basic":
        username = config.get("username", "")
        creds = base64.b64encode(f"{username}:{secret}".encode()).decode()
        return {"Authorization": f"Basic {creds}"}
    return {}


async def resolve_secret(connector_id: Any, tenant_id: Any) -> str:
    """The stored secret for this connector, scoped to the connector's tenant."""
    tid = str(tenant_id or "").strip()
    if not tid:
        return ""
    await credentials.ensure_fresh()
    return credentials.get(secret_key(connector_id), tenant_id=tid)


def private_targets_allowed() -> bool:
    return url_guard.env_flag("CONNECTORS_ALLOW_PRIVATE_TARGETS")


def _http_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


def _api_path() -> str:
    """Best-effort resolution of the API app dir so we can import preset loader."""
    candidates = [
        Path(__file__).resolve().parents[4] / "apps" / "api",
        Path("/app/apps/api"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[0])


_API_PATH_ADDED = False


def _ensure_api_imports() -> None:
    global _API_PATH_ADDED
    if _API_PATH_ADDED:
        return
    p = _api_path()
    if p not in sys.path:
        sys.path.insert(0, p)
    pkg = str(Path(__file__).resolve().parents[4] / "packages" / "db")
    if Path(pkg).exists() and pkg not in sys.path:
        sys.path.insert(0, pkg)
    _API_PATH_ADDED = True


def _format_template(template: Any, params: dict[str, Any]) -> Any:
    """Substitute {placeholder} tokens in strings, recurse into dict/list."""
    if isinstance(template, str):
        out = template
        for k, v in params.items():
            out = out.replace("{" + k + "}", "" if v is None else str(v))
        return out
    if isinstance(template, dict):
        result = {}
        for k, v in template.items():
            rendered = _format_template(v, params)
            # Drop empty placeholders so we don't post `null`/empty fields.
            if (
                isinstance(rendered, str)
                and rendered.startswith("{")
                and rendered.endswith("}")
            ):
                continue
            if rendered in (None, ""):
                continue
            result[k] = rendered
        return result
    if isinstance(template, list):
        return [_format_template(v, params) for v in template]
    return template


class ConnectorCallTool(BaseTool):
    name = "connector_call"
    risk_tier = "medium"
    effect = Effect(
        kind="external",
        label="Call an operation on a connected system",
        target_param="connector_id",
    )
    description = (
        "Execute an operation against one of the tenant's configured "
        "connectors (CMMS, HRIS, telematics, weather, cost data). The "
        "operation, URL template, and body shape come from the connector's "
        "preset. Pass parameters as a flat object."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "connector_id": {
                "type": "string",
                "description": "UUID of the configured connector to call",
            },
            "operation": {
                "type": "string",
                "description": "Preset operation name (e.g. create_work_order, get_forecast)",
            },
            "parameters": {
                "type": "object",
                "description": "Operation parameters keyed by name from the preset",
            },
        },
        "required": ["connector_id", "operation"],
    }

    _READ_PREFIXES = (
        "get",
        "list",
        "read",
        "search",
        "fetch",
        "query",
        "find",
        "lookup",
    )

    @classmethod
    def effect_for(cls, arguments: dict[str, Any]) -> Effect | None:
        op = str(arguments.get("operation") or "").lower()
        return READ_ONLY if op.startswith(cls._READ_PREFIXES) else cls.effect

    async def _load(self, connector_id: str) -> dict[str, Any] | str:
        """The connector as plain values, or why it cannot be used."""
        try:
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

            from models.connector import Connector  # type: ignore
        except Exception as e:
            return f"db imports failed: {e}"
        try:
            cid = uuid.UUID(connector_id)
        except ValueError:
            return "connector_id is not a valid id"

        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return "DATABASE_URL not configured for runtime"

        from engine.db_pool import shared_engine

        Session = async_sessionmaker(
            shared_engine(db_url), class_=AsyncSession, expire_on_commit=False
        )
        async with Session() as session:
            q = select(Connector).where(Connector.id == cid)
            tenant = credentials.current_tenant()
            if tenant:
                try:
                    q = q.where(Connector.tenant_id == uuid.UUID(tenant))
                except ValueError:
                    return "Connector not found"
            c = (await session.execute(q)).scalar_one_or_none()
            if not c:
                return "Connector not found"
            return {
                "id": str(c.id),
                "tenant_id": str(c.tenant_id),
                "preset_key": c.preset_key,
                "base_url": c.base_url,
                "auth_type": (
                    c.auth_type.value
                    if hasattr(c.auth_type, "value")
                    else str(c.auth_type)
                ),
                "config": c.config or {},
                # legacy ApiKey pointer, never sent, only raises the notice
                "legacy_ref": bool(c.secret_ref),
                "is_active": c.is_active,
            }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        connector_id = str(arguments.get("connector_id") or "").strip()
        operation = str(arguments.get("operation") or "").strip()
        parameters = arguments.get("parameters") or {}
        if not connector_id or not operation:
            return ToolResult(
                content="connector_id and operation are required", is_error=True
            )

        _ensure_api_imports()
        try:
            from app.core.connector_presets import get_preset  # type: ignore
        except Exception as e:
            return ToolResult(content=f"preset loader unavailable: {e}", is_error=True)

        c = await self._load(connector_id)
        if isinstance(c, str):
            return ToolResult(content=c, is_error=True)
        if c.get("is_active") is False:
            return ToolResult(content="This connector is turned off", is_error=True)

        preset_key = c["preset_key"]
        preset = get_preset(preset_key) if preset_key else None
        if not preset:
            return ToolResult(
                content=f"No preset registered for key={preset_key}",
                is_error=True,
            )
        op = (preset.get("operations") or {}).get(operation)
        if not op:
            return ToolResult(
                content=f"Operation '{operation}' not in preset '{preset_key}'",
                is_error=True,
            )

        auth_type = c["auth_type"]
        config = c["config"]
        secret_value = await resolve_secret(c["id"], c["tenant_id"])
        if not secret_value and c["legacy_ref"] and auth_type != "none":
            return ToolResult(
                content=f"{LEGACY_SECRET_NOTICE}, in Admin -> Connectors.",
                is_error=True,
            )

        method = (op.get("method") or "GET").upper()
        path_template = op.get("path") or ""
        body_template = op.get("body_template")
        query_template = op.get("query_params")

        path = _format_template(path_template, parameters)
        url = c["base_url"].rstrip("/") + "/" + path.lstrip("/")
        query = _format_template(query_template, parameters) if query_template else None
        # Trim empty query params
        if isinstance(query, dict):
            query = {k: v for k, v in query.items() if v not in (None, "")}
        body = _format_template(body_template, parameters) if body_template else None

        secret_headers = auth_headers(auth_type, secret_value, config)
        headers: dict[str, str] = {"Accept": "application/json", **secret_headers}

        started = time.monotonic()

        def _failed(msg: str, **extra: Any) -> ToolResult:
            return ToolResult(
                content=json.dumps(
                    {
                        "ok": False,
                        "status_code": None,
                        "response_body": {"error": msg},
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "called_url": url,
                        **extra,
                    }
                ),
                is_error=True,
            )

        try:
            async with _http_client(20.0) as client:
                req = client.build_request(
                    method, url, params=query, json=body, headers=headers
                )
                resp = await url_guard.send_guarded(
                    client,
                    req,
                    allow_private=private_targets_allowed(),
                    sensitive_headers=secret_headers.keys(),
                )
                latency_ms = int((time.monotonic() - started) * 1000)
                # Try JSON; fall back to text excerpt
                try:
                    parsed = resp.json()
                except Exception:
                    parsed = {"_raw_text": (resp.text or "")[:2000]}
                payload = {
                    "ok": 200 <= resp.status_code < 300,
                    "status_code": resp.status_code,
                    "response_body": parsed,
                    "latency_ms": latency_ms,
                    "called_url": str(resp.request.url),
                }
                return ToolResult(content=json.dumps(payload, default=str))
        except url_guard.Blocked as e:
            return _failed(
                f"Blocked: {e.reason}. Connectors may only call public addresses.",
                blocked=True,
            )
        except url_guard.TooManyRedirects as e:
            return _failed(str(e))
        except httpx.HTTPError as e:
            return _failed(str(e))
