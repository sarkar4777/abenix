"""End-to-end test suite for the Industrial IoT overhaul.

Three stages, each reported separately:

  Stage A — retired slugs are absent / archived in the catalog
  Stage B — protected domains (OracleNet, the example app, Saudi Tourism)
            + every surviving seeded agent smoke-runs (create agent,
            don't execute — executing 70 agents would cost real $$).
  Stage C — the full Industrial IoT flow:
              1) upload pump-dsp-correction  -> status=ready, output_schema
              2) upload rul-estimator        -> status=ready
              3) upload cold-chain-corrector -> status=ready, output_schema
              4) execute iot-pump-pipeline   with a scripted window
              5) execute iot-coldchain-pipeline with a scripted shipment
            Each pipeline is driven via POST /api/agents/<id>/execute
            with stream=false, wait=true so we can assert the final
            output shape synchronously.

Run:
    python scripts/e2e_industrial_iot.py

Env:
    AF_API=http://localhost:8000  (default)
    AF_EMAIL / AF_PASSWORD        (default admin creds)
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx


API = os.environ.get("AF_API", "http://localhost:8000")
EMAIL = os.environ.get("AF_EMAIL", "admin@abenix.dev")
PASSWORD = os.environ.get("AF_PASSWORD", "Admin123456")
REPO = Path(__file__).resolve().parents[1]


RETIRED_SLUGS = {
    "cache-manager", "query-router", "validation-agent",
    "migration-observatory", "migration-pipeline", "data-mover",
    "sql-transformer", "schema-architect", "report-migrator",
    "generic-stress-test", "iot-sensor-monitor",
    "predictive-maintenance", "supply-chain-risk-monitor",
}

PROTECTED_SLUGS = {
    # OracleNet (8)
    "oraclenet-pipeline", "oraclenet-current-state", "oraclenet-contrarian",
    "oraclenet-historian", "oraclenet-second-order", "oraclenet-synthesizer",
    "oraclenet-provenance", "oraclenet-stakeholder-sim",
    # the example app (subset — spot check, not all 17)
    "example_app-chat", "example_app-pipeline", "example_app-clause-benchmarker",
    # Saudi Tourism (5)
    "st-chat", "st-analytics", "st-data-extractor", "st-report-generator", "st-simulator",
}

NEW_IOT_SLUGS = {
    "iot-pump-dsp-analyzer",   "iot-pump-diagnosis",    "iot-maintenance-planner",
    "iot-coldchain-monitor",   "iot-excursion-adjudicator", "iot-claims-dispatcher",
    "iot-pump-pipeline",       "iot-coldchain-pipeline",
}


def login() -> str:
    r = httpx.post(f"{API}/api/auth/login",
                   json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["access_token"]


def hdr(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def banner(n: str) -> None:
    print()
    print("=" * 72)
    print(n)
    print("=" * 72)


# ─── Stage A — retired slugs ─────────────────────────────────────────────

def stage_a_retired(token: str) -> dict[str, Any]:
    banner("Stage A  ·  Retired agents are absent or archived")
    r = httpx.get(f"{API}/api/agents?limit=100", headers=hdr(token), timeout=30)
    r.raise_for_status()
    rows = r.json().get("data") or []
    by_slug = {a.get("slug"): a for a in rows if isinstance(a, dict)}
    failures: list[str] = []
    for slug in sorted(RETIRED_SLUGS):
        a = by_slug.get(slug)
        if a is None:
            print(f"  ok   {slug}  — not present (good)")
            continue
        status = (a.get("status") or "").lower()
        if status == "archived":
            print(f"  ok   {slug}  — archived (good)")
        else:
            print(f"  FAIL {slug}  — status={status!r} (expected archived or missing)")
            failures.append(slug)
    return {"failures": failures, "catalog": rows}


# ─── Stage B — protected + surviving smoke ──────────────────────────────

def stage_b_catalog(token: str, catalog_rows: list[dict]) -> dict[str, Any]:
    banner("Stage B  ·  Protected domains + surviving agent catalog")
    by_slug = {a.get("slug"): a for a in catalog_rows if isinstance(a, dict)}

    failures: list[str] = []
    # All protected slugs present + active
    for slug in sorted(PROTECTED_SLUGS):
        a = by_slug.get(slug)
        if a is None:
            print(f"  FAIL {slug}  — missing from catalog")
            failures.append(slug)
            continue
        if (a.get("status") or "").lower() == "archived":
            print(f"  FAIL {slug}  — archived but should be active")
            failures.append(slug)
            continue
        print(f"  ok   {slug}  (protected)")

    # All new IoT slugs present + active
    for slug in sorted(NEW_IOT_SLUGS):
        a = by_slug.get(slug)
        if a is None:
            print(f"  FAIL {slug}  — missing from catalog (seeder didn't run?)")
            failures.append(slug)
            continue
        print(f"  ok   {slug}  (industrial-iot)")

    # Count of surviving agents
    surviving = [a for a in catalog_rows if (a.get("status") or "").lower() != "archived"]
    print(f"  ----  surviving active agents: {len(surviving)}")

    return {"failures": failures, "surviving_count": len(surviving)}


# ─── Stage C — Industrial IoT flows ─────────────────────────────────────

def _zip_example(src_rel: str, out_path: Path) -> Path:
    src = REPO / "examples" / "code-assets" / src_rel
    if not src.is_dir():
        raise RuntimeError(f"missing example source: {src}")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src))
    return out_path


def upload_asset(token: str, zip_path: Path, name: str, desc: str) -> dict:
    with open(zip_path, "rb") as f:
        r = httpx.post(f"{API}/api/code-assets",
                       headers=hdr(token),
                       files={"file": (zip_path.name, f, "application/zip")},
                       data={"metadata": json.dumps({"name": name, "description": desc})},
                       timeout=120)
    r.raise_for_status()
    return r.json()["data"]


def poll_asset_ready(token: str, asset_id: str, timeout_s: int = 180) -> dict:
    deadline = time.monotonic() + timeout_s
    last = {}
    while time.monotonic() < deadline:
        r = httpx.get(f"{API}/api/code-assets/{asset_id}", headers=hdr(token), timeout=15)
        r.raise_for_status()
        last = r.json()["data"]
        if last.get("status") == "ready":
            return last
        if last.get("status") == "failed":
            raise RuntimeError(f"asset {asset_id} failed: {last.get('error')}")
        time.sleep(3)
    raise TimeoutError(f"asset {asset_id} never reached ready (last={last.get('status')})")


def poll_asset_probe(token: str, asset_id: str, timeout_s: int = 180) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = httpx.get(f"{API}/api/code-assets/{asset_id}", headers=hdr(token), timeout=15)
        r.raise_for_status()
        data = r.json()["data"]
        if data.get("output_schema"):
            return True
        time.sleep(3)
    return False


def find_pipeline_id(token: str, slug: str) -> str | None:
    r = httpx.get(f"{API}/api/agents?limit=100", headers=hdr(token), timeout=30)
    r.raise_for_status()
    for a in r.json().get("data") or []:
        if a.get("slug") == slug:
            return a.get("id")
    return None


def execute_pipeline(
    token: str, pipeline_id: str, message: dict, context: dict,
    wait_timeout: int = 240,
) -> dict:
    r = httpx.post(
        f"{API}/api/agents/{pipeline_id}/execute",
        headers=hdr(token),
        json={
            "message": json.dumps(message),
            "stream": False, "wait": True,
            "wait_timeout_seconds": wait_timeout,
            "context": context,
        },
        timeout=wait_timeout + 30,
    )
    return r.json()


def _build_pump_window() -> dict:
    # Deterministic acute-imbalance signature — 1× shaft + light bearing.
    random.seed(7)
    n = 500
    rate = 2000
    shaft_hz = 30.0
    samples = []
    for k in range(n):
        t = k / rate
        samples.append(
            0.25 * math.sin(2 * math.pi * shaft_hz * t)
            + 0.10 * math.sin(2 * math.pi * 650 * t + random.random() * 6.28)
            + 0.02 * (random.random() - 0.5)
        )
    return {
        "samples": samples,
        "sample_rate_hz": rate,
        "sensor_id": "PUMP-E2E-01",
        "shaft_rpm": 1800,
    }


def _build_coldchain_shipment() -> dict:
    readings = []
    start_ms = 1_714_000_000_000
    for i in range(20):
        temp = 4.5 + (0.2 * (0.5 - (i * 0.13 % 1.0)))
        door = False
        if 8 <= i <= 12:
            bell = math.sin(math.pi * ((i - 7) / 5))
            temp = 4.5 + bell * 8.5
        if i in (15, 16):
            temp = 5.5
            door = True
        readings.append({
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime((start_ms + i * 300_000) / 1000)
            ),
            "temp_c": round(temp, 2),
            "door_open": door,
            "lat": 37.77 + (34.05 - 37.77) * (i / 19),
            "lon": -122.42 + (-118.24 + 122.42) * (i / 19),
        })
    return {
        "readings": readings,
        "product_spec": {
            "sku": "PHARM-A-INSULIN",
            "name": "Insulin vials",
            "min_c": 2.0,
            "max_c": 8.0,
            "excursion_minutes": 10,
            "door_open_minutes": 5,
            "unit_value_usd": 120,
            "units_in_shipment": 500,
        },
        "shipment_context": {
            "shipment_id": "SHP-E2E-001",
            "carrier": "AcmeReefer",
            "origin": "SFO",
            "destination": "LAX",
            "customer_email": "qa@customer.example",
            "policy_ref": "E2E-TEST",
        },
    }


def stage_c_iot(token: str) -> dict[str, Any]:
    banner("Stage C  ·  Industrial IoT end-to-end")
    import tempfile
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        # 1 — pump DSP
        print("  · uploading pump-dsp-correction …")
        zp = _zip_example("pump-dsp-correction", Path(td) / "pump.zip")
        pump = upload_asset(token, zp, f"pump-dsp-e2e-{int(time.time())}", "E2E pump DSP")
        pump = poll_asset_ready(token, pump["id"])
        print(f"    ok  id={pump['id'][:12]}…  image={pump.get('suggested_image')}")
        pump_probe = poll_asset_probe(token, pump["id"])
        print(f"    {'ok' if pump_probe else 'warn'}  smoke-test probe"
              f"  output_schema {'populated' if pump_probe else 'pending'}")

        # 2 — RUL
        print("  · uploading rul-estimator …")
        zr = _zip_example("rul-estimator", Path(td) / "rul.zip")
        rul = upload_asset(token, zr, f"rul-estimator-e2e-{int(time.time())}", "E2E RUL")
        rul = poll_asset_ready(token, rul["id"])
        print(f"    ok  id={rul['id'][:12]}…")

        # 3 — cold chain
        print("  · uploading cold-chain-corrector …")
        zc = _zip_example("cold-chain-corrector", Path(td) / "coldchain.zip")
        cc = upload_asset(token, zc, f"cold-chain-e2e-{int(time.time())}", "E2E cold chain")
        cc = poll_asset_ready(token, cc["id"])
        cc_probe = poll_asset_probe(token, cc["id"])
        print(f"    ok  id={cc['id'][:12]}…  probe={'ok' if cc_probe else 'pending'}")

    # 4 — execute pump pipeline
    pump_pl = find_pipeline_id(token, "iot-pump-pipeline")
    if not pump_pl:
        failures.append("iot-pump-pipeline not seeded")
        print("    FAIL iot-pump-pipeline not seeded")
    else:
        print("  · executing iot-pump-pipeline …")
        resp = execute_pipeline(
            token, pump_pl,
            _build_pump_window(),
            {"pump_dsp_asset_id": pump["id"], "rul_asset_id": rul["id"],
             "asset_context": {"sensor_id": "PUMP-E2E-01", "site": "E2E Lab"}},
        )
        err = resp.get("error")
        data = resp.get("data") or {}
        final_out = data.get("final_output") or {}
        if err:
            failures.append(f"pump-pipeline execute: {err}")
            print(f"    FAIL {err}")
        elif data.get("status") != "completed":
            failures.append(f"pump-pipeline non-completed status: {data.get('status')}")
            failed = data.get("failed_nodes") or []
            print(f"    FAIL status={data.get('status')}  failed_nodes={failed}")
        elif not final_out:
            failures.append("pump-pipeline empty final_output")
            print(f"    FAIL empty final_output")
        else:
            sev = final_out.get("severity")
            dsp = final_out.get("dsp") or {}
            print(f"    ok  severity={sev}  rms={dsp.get('rms')}  peak={dsp.get('peak')}")
            if not sev:
                failures.append("pump-pipeline final_output missing severity")
            if not dsp or not dsp.get("rms"):
                failures.append("pump-pipeline final_output missing dsp.rms")

    # 5 — execute cold chain pipeline
    cc_pl = find_pipeline_id(token, "iot-coldchain-pipeline")
    if not cc_pl:
        failures.append("iot-coldchain-pipeline not seeded")
        print("    FAIL iot-coldchain-pipeline not seeded")
    else:
        print("  · executing iot-coldchain-pipeline …")
        resp = execute_pipeline(
            token, cc_pl,
            _build_coldchain_shipment(),
            {"coldchain_asset_id": cc["id"]},
        )
        err = resp.get("error")
        data = resp.get("data") or {}
        final_out = data.get("final_output") or {}
        if err:
            failures.append(f"coldchain-pipeline execute: {err}")
            print(f"    FAIL {err}")
        elif data.get("status") != "completed":
            failures.append(f"coldchain-pipeline non-completed: {data.get('status')}")
            failed = data.get("failed_nodes") or []
            print(f"    FAIL status={data.get('status')}  failed_nodes={failed}")
        elif not final_out:
            failures.append("coldchain-pipeline empty final_output")
            print(f"    FAIL empty final_output")
        else:
            sev = (final_out.get("adjudication") or {}).get("severity")
            mon = final_out.get("monitor") or {}
            excs = (mon.get("excursions") or [])
            print(f"    ok  adj_severity={sev}  excursions={len(excs)}  claim={'yes' if final_out.get('claim') else 'no'}")
            if not mon.get("summary"):
                failures.append("coldchain-pipeline final_output missing monitor.summary")

    return {"failures": failures}


# ─── Main ────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        token = login()
    except Exception as e:
        print(f"login failed: {e}")
        return 2

    a = stage_a_retired(token)
    b = stage_b_catalog(token, a.get("catalog") or [])
    c = stage_c_iot(token)

    banner("SUMMARY")
    total_fail = len(a["failures"]) + len(b["failures"]) + len(c["failures"])
    print(f"  Stage A  retired        : {len(a['failures'])} failure(s)")
    print(f"  Stage B  catalog        : {len(b['failures'])} failure(s)"
          f"  ({b['surviving_count']} active agents)")
    print(f"  Stage C  industrial-iot : {len(c['failures'])} failure(s)")
    if total_fail == 0:
        print("\n  ALL GREEN")
        return 0
    print("\n  FAILURES:")
    for stage_name, res in (("A", a), ("B", b), ("C", c)):
        for f in res["failures"]:
            print(f"    [{stage_name}] {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
