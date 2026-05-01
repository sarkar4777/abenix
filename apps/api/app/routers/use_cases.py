"""Use-case registry — the navigation surface for standalone apps.

The TopBar "Use Cases" menu and any launcher surface calls this endpoint
to discover standalone apps (the example app, Saudi Tourism, Industrial IoT,
…) at runtime so the URLs are NEVER hardcoded in the client bundle.

Resolution order (first match wins):
  1. `USE_CASE_URLS` env var (JSON object mapping key → url). Lets ops
     override for any quirky deployment without a code change.
  2. Per-app env var (`EXAMPLE_APP_PUBLIC_URL`, `SAUDITOURISM_PUBLIC_URL`,
     `INDUSTRIAL_IOT_PUBLIC_URL`). Set on the api pod from the Helm
     values.
  3. Host-derived default. If the caller arrives via `*.nip.io` or a
     custom domain, we build the host by swapping the subdomain:
        api-host   → ciq.<host> / st.<host> / iot.<host>
  4. Final fallback — `http://localhost:3001` / `3002` / `3003` (dev).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/use-cases", tags=["use-cases"])


# Canonical catalogue of apps the platform currently ships.
# Each entry's `url` is filled in at request time by _resolve.
CATALOG = [
    {
        "key": "example_app",
        "label": "the example app",
        "description": "Standalone app — PPA & gas contract intelligence.",
        "icon": "example_app",
        "color": "emerald",
        "host_subdomain": "ciq",
        "local_port": 3001,
        "env_var": "EXAMPLE_APP_PUBLIC_URL",
    },
    {
        "key": "sauditourism",
        "label": "Saudi Tourism",
        "description": "KSA Ministry of Tourism analytics — visitor data, simulations, AI reports.",
        "icon": "globe",
        "color": "green",
        "host_subdomain": "tourism",
        "local_port": 3002,
        "env_var": "SAUDITOURISM_PUBLIC_URL",
    },
    {
        "key": "industrial-iot",
        "label": "Industrial IoT",
        "description": "Standalone app — pump vibration + cold-chain telemetry, live pipelines on streamed sensor data.",
        "icon": "zap",
        "color": "purple",
        "host_subdomain": "iot",
        "local_port": 3003,
        "env_var": "INDUSTRIAL_IOT_PUBLIC_URL",
    },
    {
        "key": "oraclenet",
        "label": "OracleNet",
        "description": "Strategic decision analysis with 7 AI agents. Simulates consequences before you decide.",
        "icon": "cpu",
        "color": "cyan",
        # OracleNet still runs inside the core web app — its URL is
        # derived from the requesting origin itself.
        "inline_path": "/oraclenet",
    },
    {
        "key": "resolveai",
        "label": "ResolveAI",
        "description": "Customer-service AI that resolves tickets, cites policy, and predicts CSAT.",
        "icon": "headphones",
        "color": "rose",
        "host_subdomain": "care",
        "local_port": 3004,
        "env_var": "RESOLVEAI_PUBLIC_URL",
    },
    {
        "key": "claimsiq",
        "label": "ClaimsIQ",
        "description": "Insurance FNOL adjudication — multimodal damage assessment, fraud screening, and live pipeline DAG. Java + Vaadin Flow demonstrating the JVM SDK.",
        "icon": "shield",
        "color": "indigo",
        "host_subdomain": "claims",
        "local_port": 3005,
        "env_var": "CLAIMSIQ_PUBLIC_URL",
    },
]


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
    return (
        request.headers.get("x-forwarded-proto")
        or request.url.scheme
        or "http"
    )


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
        data.append({
            "key": entry["key"],
            "label": entry["label"],
            "description": entry["description"],
            "icon": entry.get("icon"),
            "color": entry.get("color"),
            "url": _resolve(entry, request),
            "inline": bool(entry.get("inline_path")),
        })
    return JSONResponse({"data": data, "error": None, "meta": None})
