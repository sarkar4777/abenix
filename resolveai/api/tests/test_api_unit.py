"""Unit tests for the ResolveAI FastAPI app."""
from __future__ import annotations

import copy
from typing import Any

import pytest


# ─── /health ─────────────────────────────────────────────────────────

async def test_health_returns_200_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert body.get("service") == "resolveai-api"


# ─── /api/resolveai/pipelines ────────────────────────────────────────

async def test_pipelines_endpoint_lists_documented_four(client):
    r = await client.get("/api/resolveai/pipelines")
    assert r.status_code == 200
    keys = {p["key"] for p in r.json()["data"]}
    # Design doc §3 — these four must always be present.
    assert keys >= {
        "inbound-resolution",
        "sla-sweep",
        "post-resolution-qa",
        "trend-mining",
    }


# ─── POST /api/resolveai/cases  (ingest) ─────────────────────────────

async def test_ingest_refund_auto_resolves_under_ceiling(
    client, mock_sdk, sample_ticket,
):
    """Deflection ≥ 0.6 with an under-ceiling refund → ``auto_resolved``."""
    r = await client.post("/api/resolveai/cases", json=sample_ticket("refund"))
    assert r.status_code == 201
    case = r.json()

    assert case["status"] == "auto_resolved"
    assert case["deflection_score"] == pytest.approx(0.85)
    assert case["resolution"]  # non-empty reply text
    assert case["cost_usd"] > 0
    assert case["duration_ms"] > 0
    # ``ticket_ingested`` + ``pipeline_completed`` events must both exist.
    kinds = {e["type"] for e in case["events"]}
    assert "ticket_ingested" in kinds
    # Either "pipeline_completed" or "status_changed" (older naming)
    assert kinds & {"pipeline_completed", "status_changed"}


async def test_ingest_low_confidence_hands_to_human(
    client, mock_sdk, sample_ticket,
):
    """Deflection < 0.6 → case handed to a human, no auto-resolved flag."""
    payload = copy.deepcopy(mock_sdk._payload)
    payload["deflection_score"] = 0.42
    mock_sdk.configure(output=payload)

    r = await client.post(
        "/api/resolveai/cases", json=sample_ticket("complaint"),
    )
    assert r.status_code == 201
    case = r.json()
    assert case["status"] == "handed_to_human"
    assert case["deflection_score"] == pytest.approx(0.42)


async def test_ingest_missing_required_field_returns_422(client, mock_sdk):
    """FastAPI should 422 on missing ``customer_id`` / ``subject`` / ``body``."""
    r = await client.post(
        "/api/resolveai/cases",
        json={"channel": "chat"},  # no customer_id, subject, body
    )
    assert r.status_code == 422


async def test_ingest_pipeline_error_marks_case_pipeline_error(
    client, mock_sdk, sample_ticket,
):
    """SDK raising an exception → case persists with status=pipeline_error."""
    mock_sdk.raise_on_execute(RuntimeError("downstream agent exploded"))
    r = await client.post(
        "/api/resolveai/cases", json=sample_ticket("exchange"),
    )
    # Design: accepted-but-degraded is 202 (not 500) because we keep
    # the case row so a human can pick it up.
    assert r.status_code == 202
    case = r.json()
    assert case["status"] == "pipeline_error"
    assert any(e["type"] == "pipeline_error" for e in case["events"])


# ─── GET /api/resolveai/cases  (list + filter) ───────────────────────

async def test_list_cases_filter_by_status(
    client, mock_sdk, sample_ticket,
):
    # Case 1: auto_resolved (default payload)
    await client.post("/api/resolveai/cases", json=sample_ticket("refund"))
    # Case 2: handed_to_human — tweak deflection
    low = copy.deepcopy(mock_sdk._payload)
    low["deflection_score"] = 0.2
    mock_sdk.configure(output=low)
    await client.post("/api/resolveai/cases", json=sample_ticket("complaint"))

    all_rows = (await client.get("/api/resolveai/cases")).json()["data"]
    assert len(all_rows) == 2

    only_auto = (
        await client.get("/api/resolveai/cases?status=auto_resolved")
    ).json()["data"]
    assert len(only_auto) == 1
    assert only_auto[0]["status"] == "auto_resolved"

    only_hth = (
        await client.get("/api/resolveai/cases?status=handed_to_human")
    ).json()["data"]
    assert len(only_hth) == 1
    assert only_hth[0]["status"] == "handed_to_human"


async def test_list_cases_limit_caps_result_size(
    client, mock_sdk, sample_ticket,
):
    for _ in range(3):
        await client.post(
            "/api/resolveai/cases", json=sample_ticket("refund"),
        )
    r = await client.get("/api/resolveai/cases?limit=2")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2


# ─── GET /api/resolveai/cases/{id} ───────────────────────────────────

async def test_get_unknown_case_returns_404(client, random_case_id):
    r = await client.get(f"/api/resolveai/cases/{random_case_id}")
    assert r.status_code == 404


async def test_get_case_returns_full_detail(
    client, mock_sdk, sample_ticket,
):
    created = (await client.post(
        "/api/resolveai/cases", json=sample_ticket("refund"),
    )).json()

    r = await client.get(f"/api/resolveai/cases/{created['id']}")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["id"] == created["id"]
    assert body["subject"] == created["subject"]


# ─── POST …/cases/{id}/take-over ─────────────────────────────────────

async def test_take_over_flips_status_to_human_handling(
    client, mock_sdk, sample_ticket,
):
    created = (await client.post(
        "/api/resolveai/cases", json=sample_ticket("refund"),
    )).json()

    r = await client.post(
        f"/api/resolveai/cases/{created['id']}/take-over",
        json={"reason": "customer asked for a manager"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "human_handling"
    assert any(
        e["type"] == "human_takeover"
        for e in r.json()["data"]["events"]
    )


async def test_take_over_on_unknown_case_returns_404(
    client, random_case_id,
):
    r = await client.post(
        f"/api/resolveai/cases/{random_case_id}/take-over",
        json={"reason": "testing"},
    )
    assert r.status_code == 404


# ─── POST …/cases/{id}/close ─────────────────────────────────────────

async def test_close_case_flips_status_to_closed(
    client, mock_sdk, sample_ticket,
):
    created = (await client.post(
        "/api/resolveai/cases", json=sample_ticket("refund"),
    )).json()

    r = await client.post(
        f"/api/resolveai/cases/{created['id']}/close",
        json={"resolution": "resolved OOB", "closed_by": "agent-42"},
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["status"] == "closed"


async def test_close_unknown_case_returns_404(client, random_case_id):
    r = await client.post(
        f"/api/resolveai/cases/{random_case_id}/close",
        json={"resolution": "n/a"},
    )
    assert r.status_code == 404


# ─── GET /api/resolveai/metrics ──────────────────────────────────────

async def test_metrics_reflects_ingested_count_and_deflection_rate(
    client, mock_sdk, sample_ticket,
):
    # 2 auto-resolved + 1 handed-to-human → deflection_rate = 2/3
    await client.post("/api/resolveai/cases", json=sample_ticket("refund"))
    await client.post("/api/resolveai/cases", json=sample_ticket("exchange"))

    low = copy.deepcopy(mock_sdk._payload)
    low["deflection_score"] = 0.30
    mock_sdk.configure(output=low)
    await client.post("/api/resolveai/cases", json=sample_ticket("complaint"))

    r = await client.get("/api/resolveai/metrics")
    assert r.status_code == 200
    m = r.json()["data"]
    assert m["total_cases"] == 3
    assert m["auto_resolved"] == 2
    assert m["handed_to_human"] == 1
    assert m["deflection_rate"] == pytest.approx(2 / 3, rel=1e-4)
    assert m["total_cost_usd"] > 0


async def test_metrics_on_empty_db_returns_zeroes(client):
    r = await client.get("/api/resolveai/metrics")
    assert r.status_code == 200
    m = r.json()["data"]
    assert m["total_cases"] == 0
    assert m["deflection_rate"] == 0.0
    assert m["total_cost_usd"] == 0.0


# ─── GET …/cases/{id}/audit-trail ────────────────────────────────────

async def test_audit_trail_empty_on_fresh_case(
    client, mock_sdk, sample_ticket,
):
    """Right after ingest with no over-ceiling action, audit is empty."""
    created = (await client.post(
        "/api/resolveai/cases", json=sample_ticket("exchange"),
    )).json()

    r = await client.get(
        f"/api/resolveai/cases/{created['id']}/audit-trail",
    )
    assert r.status_code == 200
    body = r.json()
    items = body.get("data", body)
    assert items == []


async def test_audit_trail_unknown_case_returns_404(client, random_case_id):
    r = await client.get(
        f"/api/resolveai/cases/{random_case_id}/audit-trail",
    )
    assert r.status_code == 404


# ─── POST …/cases/{id}/approve  +  /reject ───────────────────────────

async def test_approve_unknown_case_returns_404(client, random_case_id):
    r = await client.post(
        f"/api/resolveai/cases/{random_case_id}/approve",
        json={"action_id": "00000000-0000-0000-0000-000000000000",
              "approver": "test-manager"},
    )
    assert r.status_code == 404


async def test_reject_unknown_case_returns_404(client, random_case_id):
    r = await client.post(
        f"/api/resolveai/cases/{random_case_id}/reject",
        json={"action_id": "00000000-0000-0000-0000-000000000000",
              "approver": "test-manager", "reason": "over ceiling"},
    )
    assert r.status_code == 404


async def test_approve_unknown_action_on_known_case_returns_404(
    client, mock_sdk, sample_ticket,
):
    created = (await client.post(
        "/api/resolveai/cases", json=sample_ticket("refund"),
    )).json()
    r = await client.post(
        f"/api/resolveai/cases/{created['id']}/approve",
        json={"action_id": "deadbeef-dead-beef-dead-beefdeadbeef",
              "approver": "test"},
    )
    assert r.status_code == 404


# ─── /admin/settings (GET + PATCH) ───────────────────────────────────

async def test_admin_settings_get_returns_default_tiers(client):
    r = await client.get("/api/resolveai/admin/settings")
    assert r.status_code == 200
    data = r.json()["data"]
    # Design §2 tiers: auto ≤ $25, T1 lead ≤ $250, manager > $250.
    assert "approval_tiers" in data
    tiers = data["approval_tiers"]
    assert tiers.get("auto_ceiling_usd") == 25.0
    assert tiers.get("t1_ceiling_usd") == 250.0


async def test_admin_settings_patch_persists_and_reads_back(client):
    patch_body = {
        "approval_tiers": {
            "auto_ceiling_usd": 42.0,
            "t1_ceiling_usd": 420.0,
            "manager_ceiling_usd": 4200.0,
        },
        "sla_first_response_minutes": 7,
    }
    p = await client.patch(
        "/api/resolveai/admin/settings", json=patch_body,
    )
    assert p.status_code in (200, 204)

    g = await client.get("/api/resolveai/admin/settings")
    assert g.status_code == 200
    data = g.json()["data"]
    assert data["approval_tiers"]["auto_ceiling_usd"] == 42.0
    assert data["sla_first_response_minutes"] == 7


async def test_admin_pending_approvals_empty_on_fresh_app(client):
    r = await client.get("/api/resolveai/admin/pending-approvals")
    assert r.status_code == 200
    data = r.json().get("data")
    assert isinstance(data, list)
    assert data == []


async def test_admin_pending_approvals_reflects_rows_in_pending_status(
    client, mock_sdk, sample_ticket, app,
):
    """When an ActionAudit row with status=pending_approval exists, it"""
    created = (await client.post(
        "/api/resolveai/cases", json=sample_ticket("refund"),
    )).json()

    # Reach through to the InMemoryStore and persist an audit row.
    store = app.state.store
    await store.record_action(created["id"], {
        "action_type": "issue_refund",
        "amount_usd": 899.99,
        "requires_approval": True,
        "status": "pending_approval",
        "rationale": "over auto-ceiling",
    })

    r = await client.get("/api/resolveai/admin/pending-approvals")
    assert r.status_code == 200
    data = r.json()["data"]
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["status"] == "pending_approval"
    assert data[0]["case"]["id"] == created["id"]


# ─── POST /api/resolveai/sla/sweep ───────────────────────────────────

async def test_sla_sweep_on_empty_db_returns_zero_breached(client):
    r = await client.post("/api/resolveai/sla/sweep", json={})
    assert r.status_code == 200
    body = r.json()
    data = body.get("data", body)
    meta = body.get("meta", {})
    breaches = data.get("breaches") if isinstance(data, dict) else None
    if breaches is None:
        breaches = meta.get("breach_count", 0)
        assert breaches == 0
    else:
        assert breaches == []


# ─── POST /api/resolveai/qa/run/{case_id} ────────────────────────────

async def test_qa_run_on_closed_case_creates_csat_row(
    client, mock_sdk, sample_ticket,
):
    # Make the SDK return a believable post-QA payload. The stub
    # client returns it for every .execute() call regardless of slug.
    mock_sdk.configure(output={
        "reply": "closed",
        "deflection_score": 0.9,
        "qa_review": {
            "predicted_csat": 4.2,
            "tone_score": 0.88,
            "correctness_score": 0.95,
        },
        "predicted_csat": 4.2,
    })
    created = (await client.post(
        "/api/resolveai/cases", json=sample_ticket("refund"),
    )).json()

    # Close the case first — QA only makes sense on closed cases.
    await client.post(
        f"/api/resolveai/cases/{created['id']}/close",
        json={"resolution": "resolved"},
    )

    r = await client.post(
        f"/api/resolveai/qa/run/{created['id']}", json={},
    )
    assert r.status_code == 200

    scores = await client.get("/api/resolveai/qa/scores")
    assert scores.status_code == 200
    rows = scores.json().get("data", scores.json())
    assert isinstance(rows, list)
    assert len(rows) >= 1


async def test_qa_run_on_unknown_case_returns_404(client, random_case_id):
    r = await client.post(
        f"/api/resolveai/qa/run/{random_case_id}", json={},
    )
    assert r.status_code == 404


# ─── POST /api/resolveai/trends/mine ─────────────────────────────────

async def test_trends_mine_on_empty_db_returns_empty_clusters(client):
    r = await client.post("/api/resolveai/trends/mine", json={})
    assert r.status_code == 200
    body = r.json()
    data = body.get("data", body)
    # trends/mine returns the list of written VoC insights as `data`.
    # On an empty DB the pipeline has nothing to cluster so insights=0.
    assert data == []


async def test_trends_insights_endpoint_returns_list(client):
    r = await client.get("/api/resolveai/trends/insights")
    assert r.status_code == 200
    data = r.json().get("data", r.json())
    assert isinstance(data, list)
    assert data == []
