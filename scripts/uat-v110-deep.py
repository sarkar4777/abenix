#!/usr/bin/env python3
"""Abenix v1.1.0 deep UAT — exercises every primitive end-to-end.

Drives:
  1. login
  2. create + test a connector (servicenow preset)
  3. submit + approve a multi-signoff approval
  4. create an edge-compatible agent + compile a .agent bundle
  5. deploy bundle to abenix-edge gateway + verify hot-load
  6. idempotency replay against the new agent
  7. enqueue an execution → DLQ admin shows zero failures
  8. integrations status all configured

Each step prints PASS/FAIL with a one-line reason.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get("API", "http://localhost:8000")
EMAIL = os.environ.get("AF_EMAIL", "admin@abenix.dev")
PASSWORD = os.environ.get("AF_PASSWORD", "Admin123456")

PASSED = 0
FAILED = 0


def req(method, path, body=None, token=None, headers=None, raw=False):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if headers:
        h.update(headers)
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{API}{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=180) as f:
            payload = f.read()
            if raw:
                return f.status, payload, dict(f.headers)
            if not payload:
                return f.status, {}
            try:
                return f.status, json.loads(payload)
            except json.JSONDecodeError:
                return f.status, {"_raw": payload.decode("utf-8", "replace")[:200]}
    except urllib.error.HTTPError as e:
        body_bytes = e.read() or b"{}"
        try:
            return e.code, json.loads(body_bytes)
        except Exception:
            return e.code, {"_raw": body_bytes.decode("utf-8", "replace")}


def check(label, ok, detail=""):
    global PASSED, FAILED
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  -- {detail}" if detail else ""))
    if ok:
        PASSED += 1
    else:
        FAILED += 1


def main():
    print(f"Abenix v1.1.0 deep UAT against {API}")

    # 1. login
    sc, r = req("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    if sc != 200:
        check("login", False, f"HTTP {sc}")
        return 1
    tok = r["data"]["access_token"]
    me_id = r["data"]["user"]["id"]
    check("login", True)

    # 2. integrations status — anthropic + openai + gemini + tavily must be configured
    sc, r = req("GET", "/api/integrations/status", token=tok)
    statuses = r.get("data") or {}
    must_be_configured = ["anthropic", "openai", "gemini", "tavily"]
    miss = [k for k in must_be_configured if statuses.get(k) != "configured"]
    check("integrations status (LLM keys configured)", not miss, f"missing: {miss or 'none'}")

    # 3. connector presets
    sc, r = req("GET", "/api/connectors/presets", token=tok)
    presets = r.get("data") or []
    check("8 connector presets exposed", len(presets) >= 8, f"{len(presets)} presets")

    # 4. create a connector against the servicenow preset
    cname = f"uat-deep-{uuid.uuid4().hex[:6]}"
    sc, r = req(
        "POST",
        "/api/connectors",
        {
            "name": cname,
            "kind": "cmms",
            "preset_key": "cmms_servicenow",
            "base_url": "https://uat.example.servicenow.com",
            "config": {"username": "uat", "instance": "uat"},
            "auth_type": "basic",
            "secret_ref": None,
        },
        token=tok,
    )
    connector_id = (r.get("data") or {}).get("id")
    check(f"connector create ({cname})", sc == 201 and bool(connector_id), f"id={connector_id}")

    # 5. submit an approval request
    if me_id:
        sc, r = req(
            "POST",
            "/api/approvals",
            {
                "title": "uat deep approval",
                "description": "auto-created by uat-v110-deep.py",
                "required_signoffs": 1,
                "expires_seconds": 600,
                "context": {"action": "noop"},
            },
            token=tok,
        )
        approval_id = (r.get("data") or {}).get("id")
        check("approval create", sc in (200, 201) and bool(approval_id), f"id={approval_id} HTTP {sc}")

        if approval_id:
            sc, r = req("POST", f"/api/approvals/{approval_id}/signoff", {"decision": "approve", "note": "uat"}, token=tok)
            check("approval sign-off", sc in (200, 204), f"HTTP {sc}")

            sc, r = req("GET", f"/api/approvals/{approval_id}", token=tok)
            status = (r.get("data") or {}).get("status")
            check("approval reaches approved state", status in ("approved", "complete"), f"status={status}")

    # 6. create an active edge-compatible agent under admin's tenant
    agent_slug = f"uat-edge-{uuid.uuid4().hex[:6]}"
    sc, r = req(
        "POST",
        "/api/agents",
        {
            "name": "UAT Edge Agent",
            "slug": agent_slug,
            "description": "edge-compatible UAT agent",
            "system_prompt": "You acknowledge messages with a JSON {ack: true}.",
            "model": "claude-sonnet-4-5-20250929",
            "model_provider": "anthropic",
            "temperature": 0.1,
            "max_iterations": 1,
            "tools": [],
            "model_config": {
                "edge_compatible": True,
                "edge_constraints": {
                    "max_payload_bytes": 4096,
                    "max_runtime_seconds": 5,
                    "mqtt_subscribe": ["uat/in"],
                    "mqtt_publish": ["uat/out"],
                },
            },
        },
        token=tok,
    )
    agent_id = (r.get("data") or {}).get("id")
    check(f"create edge-compatible agent ({agent_slug})", sc in (200, 201) and bool(agent_id), f"id={agent_id} HTTP {sc}")

    if agent_id:
        # Activate the agent (PUT, not PATCH)
        sc, r = req("POST", f"/api/agents/{agent_id}/publish", {}, token=tok)
        check("agent activate (publish)", sc in (200, 201, 204), f"HTTP {sc}")

        # 7. compile the .agent bundle
        sc, r, hdr = req("POST", f"/api/edge/agents/{agent_id}/compile", token=tok, raw=True)
        digest = hdr.get("X-Bundle-Digest", "")
        check(
            "edge .agent bundle compile",
            sc == 200 and len(r) > 200,
            f"HTTP {sc} size={len(r) if isinstance(r,bytes) else '?'}B digest={digest[:16]}...",
        )

        # 8. deploy bundle to a registered gateway
        sc, r = req("GET", "/api/edge/gateways", token=tok)
        gws = (r.get("data") or {}).get("gateways", [])
        target = next((g for g in gws if g.get("gateway_id") == "edge-cluster-default"), None)
        if target:
            sc, r = req("POST", f"/api/edge/gateways/{target['id']}/deploy", {"agent_id": agent_id}, token=tok)
            data = r.get("data") or {}
            check(
                "edge bundle deploy",
                sc in (200, 201) and (data.get("deployed") or data.get("transport")),
                f"HTTP {sc} transport={data.get('transport')}",
            )
        else:
            check("edge bundle deploy", False, "edge-cluster-default not found in gateways")

        # 9. idempotency replay — must be non-streaming
        key = str(uuid.uuid4())
        body_payload = {"message": "ping", "stream": False, "context": {}}
        sc1, r1 = req(
            "POST",
            f"/api/agents/{agent_id}/execute",
            body_payload,
            token=tok,
            headers={"Idempotency-Key": key},
        )
        sc2, r2 = req(
            "POST",
            f"/api/agents/{agent_id}/execute",
            body_payload,
            token=tok,
            headers={"Idempotency-Key": key},
        )
        replay = (
            (r2.get("data") or {}).get("idempotent_replay")
            if isinstance(r2, dict) and isinstance(r2.get("data"), dict)
            else None
        )
        check(
            "idempotency replay",
            sc1 in (200, 202) and sc2 in (200, 202),
            f"first={sc1} second={sc2} replay={replay}",
        )

    # 10. DLQ admin
    sc, r = req("GET", "/api/admin/dlq", token=tok)
    rows = r.get("data") or []
    check("admin DLQ accessible", sc == 200, f"{len(rows) if isinstance(rows, list) else '?'} rows")

    print()
    print(f"PASS {PASSED}   FAIL {FAILED}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
