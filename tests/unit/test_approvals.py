"""Unit tests for the approvals engine.

These cover the deterministic state machine: pure ``_evaluate_status`` over
in-memory Approval rows. Async DB / HTTP behaviour is exercised in the
integration suite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models.approval import Approval, ApprovalStatus


def _row(
    *,
    required: int = 1,
    signoffs: list[dict] | None = None,
    expires_at=None,
) -> Approval:
    a = Approval()
    a.required_signoffs = required
    a.signoffs = signoffs or []
    a.status = ApprovalStatus.pending
    a.expires_at = expires_at
    return a


def test_pending_until_threshold_met() -> None:
    from app.routers.approvals import _evaluate_status

    a = _row(required=2, signoffs=[{"decision": "approve", "user_id": "u1"}])
    assert _evaluate_status(a) == ApprovalStatus.pending


def test_approved_when_threshold_met() -> None:
    from app.routers.approvals import _evaluate_status

    a = _row(
        required=2,
        signoffs=[
            {"decision": "approve", "user_id": "u1"},
            {"decision": "approve", "user_id": "u2"},
        ],
    )
    assert _evaluate_status(a) == ApprovalStatus.approved


def test_single_deny_short_circuits_to_denied() -> None:
    from app.routers.approvals import _evaluate_status

    a = _row(
        required=3,
        signoffs=[
            {"decision": "approve", "user_id": "u1"},
            {"decision": "deny", "user_id": "u2"},
        ],
    )
    assert _evaluate_status(a) == ApprovalStatus.denied


def test_expired_when_deadline_passed_with_no_decision() -> None:
    from app.routers.approvals import _evaluate_status

    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    a = _row(required=1, signoffs=[], expires_at=past)
    assert _evaluate_status(a) == ApprovalStatus.expired


def test_expiry_in_future_keeps_pending() -> None:
    from app.routers.approvals import _evaluate_status

    future = datetime.now(timezone.utc) + timedelta(seconds=300)
    a = _row(required=1, signoffs=[], expires_at=future)
    assert _evaluate_status(a) == ApprovalStatus.pending


def test_approved_takes_priority_over_unexpired_signoffs_count() -> None:
    """Even if expires_at is set, three approvals on a 3-of-N row → approved."""
    from app.routers.approvals import _evaluate_status

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    a = _row(
        required=3,
        signoffs=[
            {"decision": "approve", "user_id": "u1"},
            {"decision": "approve", "user_id": "u2"},
            {"decision": "approve", "user_id": "u3"},
        ],
        expires_at=future,
    )
    assert _evaluate_status(a) == ApprovalStatus.approved


def test_deny_beats_approval_count_even_at_threshold() -> None:
    from app.routers.approvals import _evaluate_status

    a = _row(
        required=1,
        signoffs=[
            {"decision": "approve", "user_id": "u1"},
            {"decision": "deny", "user_id": "u2"},
        ],
    )
    assert _evaluate_status(a) == ApprovalStatus.denied


def test_approval_status_enum_values() -> None:
    assert {s.value for s in ApprovalStatus} == {
        "pending",
        "approved",
        "denied",
        "expired",
        "returned",
        "withdrawn",
    }


def test_return_for_correction_wins_over_pending_approvals() -> None:
    from types import SimpleNamespace

    from app.routers.approvals import _evaluate_status

    a = SimpleNamespace(
        signoffs=[{"decision": "approve"}, {"decision": "return", "reason": "fix the threshold"}],
        required_signoffs=3,
        expires_at=None,
    )
    assert _evaluate_status(a) == ApprovalStatus.returned
    a.signoffs.append({"decision": "deny"})
    assert _evaluate_status(a) == ApprovalStatus.denied


def test_escalation_hours_validated() -> None:
    from engine.risk import DEFAULT_POLICIES, validate_policy

    assert DEFAULT_POLICIES["critical"]["publish_approvals"]["escalate_after_hours"] == 4
    assert DEFAULT_POLICIES["low"]["publish_approvals"]["escalate_after_hours"] == 0
    ok = {"publish_approvals": {"min_approvers": 1, "escalate_after_hours": 8}}
    assert validate_policy(ok) == []
    bad = {"publish_approvals": {"min_approvers": 1, "escalate_after_hours": -1}}
    assert any("escalate_after_hours" in p for p in validate_policy(bad))
