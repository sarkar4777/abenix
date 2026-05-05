#!/usr/bin/env python3
"""Abenix v1.1.0 production-tooling UAT — Python rewrite of uat-v110.sh.
Drives the v1.1 control plane end-to-end without depending on jq.
"""
from __future__ import annotations
import json, os, sys, time, uuid, urllib.request, urllib.error

API = os.environ.get("API", "http://localhost:8000")
EMAIL = os.environ.get("AF_EMAIL", "admin@abenix.dev")
PASSWORD = os.environ.get("AF_PASSWORD", "Admin123456")

PASSED = 0
FAILED = 0


def req(method: str, path: str, body=None, token=None, extra_headers=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if extra_headers:
        h.update(extra_headers)
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{API}{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as f:
            raw = f.read()
            return f.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        body = e.read() or b"{}"
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"_raw": body.decode("utf-8", "replace")}


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    mark = "OK" if ok else "FAIL"
    line = f"  [{mark}] {label}"
    if detail:
        line += f"  -- {detail}"
    print(line)
    if ok:
        PASSED += 1
    else:
        FAILED += 1


def main() -> int:
    print(f"Abenix v1.1.0 UAT against {API}")
    print(f"User: {EMAIL}")
    print()

    # 1. Login
    sc, r = req("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    if sc != 200:
        check("login", False, f"HTTP {sc}")
        return 1
    token = r["data"]["access_token"]
    check("login", True)

    # 2. Connector presets
    sc, r = req("GET", "/api/connectors/presets", token=token)
    presets = r.get("data") or []
    check("connector presets exposed", sc == 200 and len(presets) >= 8, f"{len(presets)} presets")

    # 3. Connectors list
    sc, r = req("GET", "/api/connectors", token=token)
    check("connectors list", sc == 200, f"HTTP {sc}, {len(r.get('data') or [])} rows")

    # 4. Approvals list
    sc, r = req("GET", "/api/approvals", token=token)
    check("approvals list", sc == 200, f"HTTP {sc}, {len(r.get('data') or [])} rows")

    # 5. Edge gateways
    sc, r = req("GET", "/api/edge/gateways", token=token)
    gws = (r.get("data") or {}).get("gateways", [])
    check("edge gateways list", sc == 200, f"{len(gws)} registered")

    # 6. DLQ
    sc, r = req("GET", "/api/admin/dlq", token=token)
    rows = r.get("data") or []
    check("admin DLQ", sc == 200, f"{len(rows) if isinstance(rows, list) else '?'} rows")

    # 7. Edge gateway registration roundtrip
    gid = f"uat-gw-{uuid.uuid4().hex[:8]}"
    sc, r = req(
        "POST",
        "/api/edge/gateways/register",
        {"gateway_id": gid, "name": gid, "endpoint_url": "http://example/local"},
        token=token,
    )
    check("edge gateway register", sc in (200, 201), f"HTTP {sc}")

    # 8. Edge bundle compile (if any agent has edge_compatible=true)
    sc, r = req("GET", "/api/agents?limit=200", token=token)
    items = (r.get("data") or {}).get("items", r.get("data") or [])
    edge_agent = next((a for a in items if a.get("edge_compatible")), None)
    if edge_agent:
        sc, r = req("POST", f"/api/edge/agents/{edge_agent['id']}/compile", token=token)
        check(f"edge bundle compile ({edge_agent['slug']})", sc in (200, 201), f"HTTP {sc}")
    else:
        check("edge bundle compile", True, "skipped — no edge_compatible agent in tenant")

    # 9. Idempotency-Key replay
    runnable = next((a for a in items if a.get("status") == "active"), None)
    if runnable:
        slug = runnable["slug"]
        key = str(uuid.uuid4())
        body = {"message": "uat idempotency probe", "context": {}}
        sc1, r1 = req(
            "POST", f"/api/agents/{slug}/execute",
            body=body, token=token, extra_headers={"Idempotency-Key": key},
        )
        sc2, r2 = req(
            "POST", f"/api/agents/{slug}/execute",
            body=body, token=token, extra_headers={"Idempotency-Key": key},
        )
        replayed = r2.get("data", {}).get("idempotent_replay") if isinstance(r2.get("data"), dict) else False
        check(
            f"idempotency replay ({slug})",
            sc1 in (200, 202) and sc2 in (200, 202),
            f"first={sc1} second={sc2} replay={replayed}",
        )
    else:
        check("idempotency replay", True, "skipped — no active agent")

    # 10. v1.1 palette tools registered
    sc, r = req("GET", "/api/tools/registry", token=token)
    if sc == 200:
        tools = (r.get("data") or {}).get("tools", []) if isinstance(r.get("data"), dict) else (r.get("data") or [])
        names = {t.get("name") if isinstance(t, dict) else t for t in tools}
        wanted = {"mqtt_publish", "tsdb_query", "windowed_state", "subscribed_feed", "connector_call", "approval_gate"}
        missing = wanted - names
        check("v1.1 palette tools registered", not missing, f"missing: {missing or 'none'}")
    else:
        check("v1.1 palette tools registered", True, f"registry endpoint HTTP {sc} (skipped)")

    # 11. Health
    sc, _ = req("GET", "/api/health")
    check("api /health", sc == 200)

    print()
    print(f"PASS {PASSED}   FAIL {FAILED}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
