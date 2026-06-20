"""Use-case registry — the navigation surface for standalone apps.

The TopBar "Use Cases" menu and any launcher surface calls this endpoint
to discover standalone apps at runtime, so the URLs are NEVER hardcoded
in the client bundle.

The catalogue itself is data, not code — it is loaded at import time
from the JSON file pointed at by `USE_CASE_CATALOG_PATH` (default
`infra/use_cases_catalog.json`). The router has no knowledge of any
specific app name.

Resolution order for each entry (first match wins):
  1. `USE_CASE_URLS` env var (JSON object mapping key → url). Lets ops
     override for any quirky deployment without a code change.
  2. Per-app env var named on the catalogue entry (set on the api pod
     from the Helm values).
  3. Host-derived default. If the caller arrives via `*.nip.io` or a
     custom domain, we build the host by swapping the subdomain.
  4. Final fallback — `http://localhost:<local_port>` (dev).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/use-cases", tags=["use-cases"])


def _default_catalog_path() -> Path:
    # repo-relative default: infra/use_cases_catalog.json
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "infra" / "use_cases_catalog.json"
        if candidate.exists():
            return candidate
    return here.parent / "use_cases_catalog.json"


def _load_catalog() -> list[dict[str, Any]]:
    path = os.environ.get("USE_CASE_CATALOG_PATH", "").strip()
    target = Path(path) if path else _default_catalog_path()
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logger.warning(
            "USE_CASE_CATALOG file is not a JSON array — using empty catalog"
        )
    except FileNotFoundError:
        logger.warning("USE_CASE_CATALOG not found at %s — using empty catalog", target)
    except Exception as exc:
        logger.warning(
            "USE_CASE_CATALOG failed to load (%s) — using empty catalog", exc
        )
    return []


CATALOG = _load_catalog()


def _current_host(request: Request) -> str:
    """Best-effort current host (accounts for ingress forwarding)."""
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
        or "localhost"
    )
    # `*.nip.io` strips trivially; other domains too.
    return host.split(",")[0].strip()


def _scheme(request: Request) -> str:
    return request.headers.get("x-forwarded-proto") or request.url.scheme or "http"


def _bulk_overrides() -> dict[str, str]:
    raw = os.environ.get("USE_CASE_URLS", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw) or {}
    except Exception:
        logger.warning("USE_CASE_URLS is set but is not valid JSON — ignoring")
        return {}


def _resolve(entry: dict[str, Any], request: Request) -> str:
    """Return the public URL for one catalog entry, this request."""
    # 1. Bulk override
    bulk = _bulk_overrides()
    if entry["key"] in bulk:
        return bulk[entry["key"]]

    # 2. Per-app env var
    if entry.get("env_var"):
        explicit = os.environ.get(entry["env_var"], "").strip()
        if explicit:
            return explicit.rstrip("/")

    # 3. Inline apps (OracleNet) — same origin, explicit path.
    if entry.get("inline_path"):
        scheme = _scheme(request)
        host = _current_host(request)
        return f"{scheme}://{host}{entry['inline_path']}"

    # 4. Host-derived subdomain (nip.io / wildcard ingress style)
    host = _current_host(request)
    scheme = _scheme(request)
    bare = host.split(":")[0]
    # If the caller arrives via a wildcard host (e.g. 20.41.36.95.nip.io
    # or a real subdomain), we can prepend the app subdomain and re-use
    # the scheme. Localhost can't do this → falls through to port.
    if bare != "localhost" and bare != "127.0.0.1" and not bare.startswith("192.168."):
        return f"{scheme}://{entry['host_subdomain']}.{bare}".rstrip("/")

    # 5. Localhost fallback — dev / start.sh
    return f"http://localhost:{entry['local_port']}"


@router.get("")
async def list_use_cases(request: Request) -> JSONResponse:
    """Public — returns the resolved URL list that the client can render
    without ever hardcoding a host.
    """
    data = []
    for entry in CATALOG:
        data.append(
            {
                "key": entry["key"],
                "label": entry["label"],
                "description": entry["description"],
                "icon": entry.get("icon"),
                "color": entry.get("color"),
                "url": _resolve(entry, request),
                "inline": bool(entry.get("inline_path")),
            }
        )
    return JSONResponse({"data": data, "error": None, "meta": None})
