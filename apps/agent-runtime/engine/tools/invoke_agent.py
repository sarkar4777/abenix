from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx

from engine import progress
from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

TERMINAL = {"completed", "succeeded", "failed", "error", "cancelled"}
MAX_DELEGATION_DEPTH = 3
TOKEN_TTL_SECONDS = 300

_HASHES = {"256": hashlib.sha256, "384": hashlib.sha384, "512": hashlib.sha512}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _sign(signing_input: bytes, alg: str) -> bytes | None:
    bits = alg[2:]
    if alg.startswith("HS") and bits in _HASHES:
        secret = os.environ.get("SECRET_KEY", "")
        if not secret:
            return None
        return hmac.new(secret.encode(), signing_input, _HASHES[bits]).digest()
    if alg.startswith("RS") and bits in _HASHES:
        pem = os.environ.get("JWT_PRIVATE_KEY", "").replace("\\n", "\n").strip()
        if not pem:
            return None
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        key = serialization.load_pem_private_key(pem.encode(), password=None)
        algo = {"256": hashes.SHA256, "384": hashes.SHA384, "512": hashes.SHA512}
        return key.sign(signing_input, padding.PKCS1v15(), algo[bits]())  # type: ignore[union-attr,call-arg]
    return None


def mint_user_token(
    user_id: str, tenant_id: str, role: str, ttl: int = TOKEN_TTL_SECONDS
) -> str:
    """Short-lived access token with the claims create_access_token issues."""
    alg = (os.environ.get("JWT_ALGORITHM") or "RS256").upper()
    now = int(time.time())
    claims = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role or "user",
        "type": "access",
        "exp": now + ttl,
        "iat": now,
    }
    header = {"alg": alg, "typ": "JWT"}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    ).encode()
    try:
        sig = _sign(signing_input, alg)
    except Exception as e:
        logger.warning("invoke_agent: token signing failed: %s", e)
        sig = None
    if sig is not None:
        return signing_input.decode() + "." + _b64url(sig)
    # inside the API process the app's own signer has the key even in debug mode
    try:
        import uuid as _uuid

        from app.core.security import create_access_token  # type: ignore

        return create_access_token(
            _uuid.UUID(str(user_id)), _uuid.UUID(str(tenant_id)), role or "user"
        )
    except Exception:
        return ""


def mint_asset_fetch_token(asset_id: str, tenant_id: str, ttl: int = 600) -> str:
    """Token that can fetch one code asset's archive and nothing else."""
    return mint_fetch_token("code_asset_fetch", asset_id, tenant_id, ttl)


def mint_fetch_token(
    kind: str, resource_id: str, tenant_id: str, ttl: int = 600
) -> str:
    """Short-lived token that can fetch one stored file of one resource."""
    alg = (os.environ.get("JWT_ALGORITHM") or "RS256").upper()
    now = int(time.time())
    claims = {
        "sub": str(resource_id),
        "tenant_id": str(tenant_id),
        "type": kind,
        "exp": now + ttl,
        "iat": now,
    }
    header = {"alg": alg, "typ": "JWT"}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    ).encode()
    try:
        sig = _sign(signing_input, alg)
    except Exception as e:
        logger.warning("code asset fetch token signing failed: %s", e)
        return ""
    return signing_input.decode() + "." + _b64url(sig) if sig is not None else ""


class InvokeAgentTool(BaseTool):
    name = "invoke_agent"
    risk_tier = "low"
    description = (
        "Invoke a registered platform agent by slug. The platform enqueues the "
        "sub-execution, runs it on the appropriate runtime pool, and this tool "
        "returns the parsed JSON envelope. Use it to fan a desk-level question "
        "out across the specialised sub-agents and synthesise a unified "
        "brief from their outputs."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_slug": {
                "type": "string",
                "description": "Slug of the registered agent to invoke (e.g. 'arb-analyzer').",
            },
            "input": {
                "type": "object",
                "description": "JSON object passed as the input to the sub-agent.",
                "additionalProperties": True,
            },
            "wait_timeout_seconds": {
                "type": "integer",
                "default": 240,
                "minimum": 30,
                "maximum": 600,
            },
        },
        "required": ["agent_slug", "input"],
    }

    def __init__(
        self,
        *,
        tenant_id: str = "",
        execution_id: str = "",
        agent_id: str = "",
        user_id: str = "",
        user_role: str = "",
        delegation_depth: int = 0,
        api_key: str = "",
        api_base: str = "",
    ) -> None:
        self._tenant_id = str(tenant_id or "")
        self._execution_id = str(execution_id or "")
        self._agent_id = str(agent_id or "")
        self._user_id = str(user_id or "")
        self._user_role = user_role or "user"
        try:
            self._depth = int(delegation_depth or 0)
        except (TypeError, ValueError):
            self._depth = 0
        self._api_key = (
            api_key
            or os.environ.get("ABENIX_PLATFORM_API_KEY", "")
            or os.environ.get("INTERNAL_API_TOKEN", "")
            or os.environ.get("ABENIX_INTERNAL_API_KEY", "")
            or os.environ.get("PLATFORM_API_KEY", "")
        )
        self._api_base = (
            api_base
            or os.environ.get("ABENIX_INTERNAL_URL", "")
            or os.environ.get("ABENIX_API_URL", "http://abenix-api:8000")
        )

    def _headers(self) -> dict[str, str] | None:
        # fresh token per request so a long poll never outlives it
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._user_id:
            token = mint_user_token(self._user_id, self._tenant_id, self._user_role)
            if not token:
                return None
            headers["Authorization"] = f"Bearer {token}"
            return headers
        if not self._api_key:
            return None
        if self._api_key.startswith("af_"):
            headers["X-API-Key"] = self._api_key
        else:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        slug = (arguments.get("agent_slug") or "").strip()
        payload = arguments.get("input") or {}
        timeout = int(arguments.get("wait_timeout_seconds") or 240)
        if not slug:
            return ToolResult(content="agent_slug is required", is_error=True)
        child_depth = self._depth + 1
        if child_depth > MAX_DELEGATION_DEPTH:
            return ToolResult(
                content=f"sub-agent depth limit reached ({MAX_DELEGATION_DEPTH})",
                is_error=True,
            )
        if not self._user_id:
            if not self._tenant_id:
                return ToolResult(
                    content="invoke_agent needs a calling user or a tenant to run in",
                    is_error=True,
                )
            logger.warning(
                "invoke_agent: no calling user on execution %s, using the platform key "
                "limited to tenant %s",
                self._execution_id or "-",
                self._tenant_id,
            )
        if self._headers() is None:
            if self._user_id:
                msg = (
                    "Could not sign a token for the calling user "
                    "(JWT_PRIVATE_KEY or SECRET_KEY missing on the runtime)."
                )
            else:
                msg = "No platform API key on the runtime pod (looked for ABENIX_PLATFORM_API_KEY / INTERNAL_API_TOKEN)."
            return ToolResult(content=msg, is_error=True)

        not_found = ToolResult(
            content=f"agent slug not found or not shared with you: {slug}",
            is_error=True,
        )
        root_id = (
            await progress.root_for(self._execution_id) if self._execution_id else ""
        )

        t0 = time.time()
        try:
            async with httpx.AsyncClient(
                base_url=self._api_base, timeout=timeout + 30
            ) as client:
                lookup = await client.get(
                    "/api/agents",
                    params={"slug": slug, "limit": 5},
                    headers=self._headers() or {},
                )
                if lookup.status_code != 200:
                    return ToolResult(
                        content=f"agent lookup failed: HTTP {lookup.status_code} {lookup.text[:300]}",
                        is_error=True,
                    )
                items = (lookup.json() or {}).get("data") or []
                if isinstance(items, dict):
                    items = items.get("items") or []
                candidates = [
                    a for a in items if (a.get("slug") or "").lower() == slug.lower()
                ]
                if not self._user_id:
                    candidates = [
                        a
                        for a in candidates
                        if str(a.get("tenant_id") or "") == self._tenant_id
                    ]
                # same-tenant copy wins over a platform agent with the same slug
                candidates.sort(
                    key=lambda a: str(a.get("tenant_id") or "") != self._tenant_id
                )
                match = candidates[0] if candidates else None
                if match is None:
                    return not_found
                agent_id = match.get("id")
                if self._agent_id and str(agent_id) == self._agent_id:
                    return ToolResult(
                        content=f"an agent cannot invoke itself: {slug}",
                        is_error=True,
                    )

                submit_body: dict[str, Any] = {
                    "message": (
                        json.dumps(payload) if not isinstance(payload, str) else payload
                    ),
                    "stream": False,
                    "wait_mode": "submitted",
                    "delegation_depth": child_depth,
                }
                if self._execution_id:
                    submit_body["parent_execution_id"] = self._execution_id
                submit_r = await client.post(
                    f"/api/agents/{agent_id}/execute",
                    headers=self._headers() or {},
                    content=json.dumps(submit_body),
                )
                if submit_r.status_code in (403, 404):
                    return not_found
                if submit_r.status_code != 200:
                    return ToolResult(
                        content=f"agent execute submit failed: HTTP {submit_r.status_code} {submit_r.text[:300]}",
                        is_error=True,
                    )
                submit_data = (
                    (submit_r.json() or {}).get("data") or submit_r.json() or {}
                )
                sub_exec_id = submit_data.get("execution_id") or submit_data.get("id")
                if not sub_exec_id:
                    return ToolResult(
                        content="submitted but no sub-execution_id returned",
                        is_error=True,
                    )

                if root_id:
                    await progress.set_parent(sub_exec_id, root_id)
                    await progress.publish(
                        self._execution_id,
                        {
                            "phase": "sub_started",
                            "agent_slug": slug,
                            "agent_name": (match.get("name") or slug),
                            "sub_execution_id": sub_exec_id,
                        },
                        root_execution_id=root_id,
                    )

                deadline = t0 + timeout
                row: dict[str, Any] = {}
                while time.time() < deadline:
                    await asyncio.sleep(2.0)
                    poll_r = await client.get(
                        f"/api/executions/{sub_exec_id}",
                        headers=self._headers() or {},
                    )
                    if poll_r.status_code != 200:
                        continue
                    row = (poll_r.json() or {}).get("data") or {}
                    status = (row.get("status") or "running").lower()
                    if status in TERMINAL:
                        break

                if not row or (row.get("status") or "running").lower() not in TERMINAL:
                    if root_id:
                        await progress.publish(
                            self._execution_id,
                            {
                                "phase": "sub_timeout",
                                "agent_slug": slug,
                                "sub_execution_id": sub_exec_id,
                            },
                            root_execution_id=root_id,
                        )
                    return ToolResult(
                        content=f"agent {slug} timed out after {timeout}s (sub-execution {sub_exec_id})",
                        is_error=True,
                        metadata={"agent_slug": slug, "execution_id": sub_exec_id},
                    )

                output = row.get("output") or row.get("output_message") or ""
                duration_ms = int((time.time() - t0) * 1000)
                parsed: Any = output
                try:
                    parsed = json.loads(output) if isinstance(output, str) else output
                except Exception:
                    s = (output or "").strip()
                    first, last = s.find("{"), s.rfind("}")
                    if first != -1 and last > first:
                        try:
                            parsed = json.loads(s[first : last + 1])
                        except Exception:
                            parsed = {"raw": s[:2000]}

                if root_id:
                    await progress.publish(
                        self._execution_id,
                        {
                            "phase": "sub_finished",
                            "agent_slug": slug,
                            "sub_execution_id": sub_exec_id,
                            "status": row.get("status"),
                            "duration_ms": row.get("duration_ms") or duration_ms,
                            "cost_usd": row.get("cost"),
                        },
                        root_execution_id=root_id,
                    )

                envelope = {
                    "agent_slug": slug,
                    "agent_id": agent_id,
                    "execution_id": sub_exec_id,
                    "parent_execution_id": self._execution_id or None,
                    "status": (row.get("status") or "completed"),
                    "output": parsed,
                    "duration_ms": row.get("duration_ms") or duration_ms,
                    "cost_usd": row.get("cost"),
                }
                return ToolResult(
                    content=json.dumps(envelope, default=str),
                    metadata={"agent_slug": slug, "execution_id": sub_exec_id},
                )
        except httpx.TimeoutException:
            return ToolResult(
                content=f"agent {slug} timed out after {timeout}s", is_error=True
            )
        except Exception as e:
            logger.warning("invoke_agent %s failed: %s", slug, e)
            return ToolResult(content=f"invoke_agent {slug} failed: {e}", is_error=True)
