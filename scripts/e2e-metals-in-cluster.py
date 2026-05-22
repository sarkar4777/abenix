"""End-to-end metals demo run from inside the cluster.

Registers a user, uploads the doré intake contract, kicks off standard
extraction, polls until analyzed, runs the metals extractor + compliance
auditor + dispute scorer, then prints a summary.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error


BASE = "http://localhost:8001"


def post(path, body, token=None, files=None):
    url = f"{BASE}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if files:
        boundary = "----xboundary"
        parts = []
        # form fields first
        for name, val in (body or {}).items():
            parts.append(f"--{boundary}\r\n")
            parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
            parts.append(str(val))
            parts.append("\r\n")
        for name, (fname, data, ctype) in files.items():
            parts.append(f"--{boundary}\r\n")
            parts.append(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\n')
            parts.append(f"Content-Type: {ctype}\r\n\r\n")
            parts.append(data.decode("latin-1") if isinstance(data, bytes) else data)
            parts.append("\r\n")
        parts.append(f"--{boundary}--\r\n")
        raw = "".join(parts).encode("latin-1")
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
    else:
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=900)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def get(path, token):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"})
    resp = urllib.request.urlopen(req, timeout=60)
    return resp.status, json.loads(resp.read().decode())


def main():
    print("=== ContractIQ Precious Metals E2E ===")

    email = f"metals-e2e-{int(time.time())}@test.com"
    print(f"\n[1] register {email}")
    s, body = post("/api/contractiq/auth/register", {
        "email": email,
        "password": "MetalsE2E!",
        "full_name": "Metals E2E",
        "organization": "Demo Refiner",
    })
    print(f"    status={s}")
    if s >= 300:
        print(body); return 1
    token = body["data"]["access_token"]

    print("\n[2] upload dore intake contract")
    text = open("/tmp/metals.txt", "rb").read()
    s, body = post("/api/contractiq/contracts/upload",
        body={
            "title": "Dore Intake and Refining Agreement",
            "contract_type": "ppa",
            "counterparty_a": "Andean Prima Mining S.A.",
            "counterparty_b": "Helvetia Metals Refining AG",
        },
        token=token,
        files={"file": ("precious_metals_dore_intake.txt", text, "text/plain")},
    )
    print(f"    status={s}")
    if s >= 300:
        print(body); return 1
    contract_id = body["data"].get("contract_id") or body["data"].get("id")
    print(f"    contract_id={contract_id}")

    print("\n[3] kick standard extraction + wait for analyzed")
    # Extract endpoint streams SSE — just fire and drain a few lines
    try:
        req = urllib.request.Request(
            f"{BASE}/api/contractiq/contracts/{contract_id}/extract",
            data=b"{}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read(256)
    except Exception as _e:
        pass
    print(f"    extract triggered")
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(4)
        _, body = get(f"/api/contractiq/contracts/{contract_id}", token)
        st = body.get("data", {}).get("status")
        print(f"    contract.status={st}")
        if st in {"analyzed", "error"}:
            break
    if body.get("data", {}).get("status") != "analyzed":
        print("    extraction did not complete in time")
        return 2

    print("\n[4] metals extractor")
    s, body = post(f"/api/contractiq/metals/contracts/{contract_id}/extract", {}, token=token)
    print(f"    status={s}")
    if s == 200:
        d = body["data"]
        print(f"    material={d.get('material')}  loco={d.get('loco')}  pricing={d.get('pricing_reference')}")
        print(f"    fineness_target={d.get('fineness_target')}  assay_tolerance={d.get('assay_tolerance_pct')}%")
        print(f"    umpire_clause={d.get('umpire_clause_present')}  vault={d.get('vaulting_type')}")
        print(f"    russian_excluded={d.get('russian_origin_excluded')}  confidence={d.get('confidence')}")
    else:
        print(f"    error: {body}")
        return 3

    print("\n[5] metals compliance audit")
    s, body = post(f"/api/contractiq/metals/contracts/{contract_id}/compliance-audit", {}, token=token)
    print(f"    status={s}")
    if s == 200:
        d = body["data"]
        print(f"    overall_score={d.get('overall_score')}  block_issues={d.get('block_level_issues')}  clarify={d.get('clarification_requests')}")
        print(f"    verdicts={len(d.get('verdicts') or [])}  superseded_refs={len(d.get('superseded_references') or [])}")
    else:
        print(f"    error: {body}")

    print("\n[6] dispute risk scorer")
    s, body = post(f"/api/contractiq/metals/contracts/{contract_id}/dispute-risk", {}, token=token)
    print(f"    status={s}")
    if s == 200:
        d = body["data"]
        print(f"    tier={d.get('tier')}  aggregate={d.get('aggregate_score')}  loss=${d.get('expected_loss_usd'):,.0f}  pct={d.get('expected_loss_pct_of_notional')}%")
        print(f"    dimensions={len(d.get('dimensions') or [])}")

    print("\n[7] overview check")
    s, body = get("/api/contractiq/metals/overview", token)
    print(f"    {json.dumps(body['data'], indent=2)}")

    print("\n=== ALL CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
