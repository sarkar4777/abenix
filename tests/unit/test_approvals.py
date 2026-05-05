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
    }
