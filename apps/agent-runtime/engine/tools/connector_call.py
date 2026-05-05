"""connector_call — execute one operation against a tenant-owned connector.

Resolves the connector + preset, fills the URL/body/query templates from
``parameters``, applies the connector's auth, and returns parsed response.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult


def _api_path() -> str:
    """Best-effort resolution of the API app dir so we can import preset loader."""
    candidates = [
        Path(__file__).resolve().parents[3] / "apps" / "api",
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
    pkg = str(Path(__file__).resolve().parents[3] / "packages" / "db")
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

        # Load connector + secret via async DB session.
        try:
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import (
                AsyncSession,
                async_sessionmaker,
                create_async_engine,
            )

            from models.api_key import ApiKey  # type: ignore
            from models.connector import Connector  # type: ignore
        except Exception as e:
            return ToolResult(content=f"db imports failed: {e}", is_error=True)

        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return ToolResult(
                content="DATABASE_URL not configured for runtime", is_error=True
            )

        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)
        Session = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            async with Session() as session:
                cr = await session.execute(
                    select(Connector).where(Connector.id == connector_id)
                )
                c = cr.scalar_one_or_none()
                if not c:
                    return ToolResult(content="Connector not found", is_error=True)

                preset_key = c.preset_key
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

                secret_value: str | None = None
                if c.secret_ref:
                    sr = await session.execute(
                        select(ApiKey).where(ApiKey.id == c.secret_ref)
                    )
                    sk = sr.scalar_one_or_none()
                    if sk:
                        secret_value = sk.key_prefix
                config = c.config or {}
                base_url = c.base_url
                auth_type = (
                    c.auth_type.value
                    if hasattr(c.auth_type, "value")
                    else str(c.auth_type)
                )
        finally:
            await engine.dispose()

        method = (op.get("method") or "GET").upper()
        path_template = op.get("path") or ""
        body_template = op.get("body_template")
        query_template = op.get("query_params")

        path = _format_template(path_template, parameters)
        url = base_url.rstrip("/") + "/" + path.lstrip("/")
        query = _format_template(query_template, parameters) if query_template else None
        # Trim empty query params
        if isinstance(query, dict):
            query = {k: v for k, v in query.items() if v not in (None, "")}
        body = _format_template(body_template, parameters) if body_template else None

        headers: dict[str, str] = {"Accept": "application/json"}
        if secret_value:
            if auth_type == "bearer":
                headers["Authorization"] = f"Bearer {secret_value}"
            elif auth_type == "api_key":
                hn = config.get("auth_header_name") or "X-API-Key"
                headers[hn] = secret_value
            elif auth_type == "basic":
                import base64

                username = config.get("username", "")
                creds = base64.b64encode(f"{username}:{secret_value}".encode()).decode()
                headers["Authorization"] = f"Basic {creds}"
            elif auth_type == "oauth2":
                headers["Authorization"] = f"Bearer {secret_value}"

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.request(
                    method, url, params=query, json=body, headers=headers
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
        except httpx.HTTPError as e:
            latency_ms = int((time.monotonic() - started) * 1000)
            return ToolResult(
                content=json.dumps(
                    {
                        "ok": False,
                        "status_code": None,
                        "response_body": {"error": str(e)},
                        "latency_ms": latency_ms,
                        "called_url": url,
                    }
                ),
                is_error=True,
            )
