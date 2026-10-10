"""decisions.review gates decision publish sign-off, and the sweeper leaves leased runs alone."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import capabilities as caps
from app.core.hitl import approver_denial


def _user(role="user"):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=SimpleNamespace(value=role)
    )


def _granted(*keys):
    return AsyncMock(return_value=frozenset(keys))


POLICY = {"capability": "approvals.sign", "exclude_requester": True}


def test_review_is_in_the_catalog_and_not_a_role_default():
    assert "decisions.review" in caps.KEYS
    assert "decisions.review" not in caps.ROLE_DEFAULTS["user"]
    assert "decisions.review" not in caps.ROLE_DEFAULTS["creator"]
    assert caps.holds(caps.ROLE_DEFAULTS["admin"], "decisions.review")


@pytest.mark.asyncio
async def test_decision_publish_needs_review_on_top_of_signing():
    u = _user()
    with patch.object(caps, "capabilities_for", _granted("approvals.sign")):
        why = await approver_denial(None, u, uuid.uuid4(), POLICY, "decision_publish")
    assert why and why.capability == "decisions.review"
    assert "decisions.review" not in why and "review decisions" in why


@pytest.mark.asyncio
async def test_review_alone_does_not_bypass_the_tier_capability():
    u = _user()
    pol = {"capability": "approvals.sign:legal"}
    with patch.object(caps, "capabilities_for", _granted("decisions.review")):
        why = await approver_denial(None, u, uuid.uuid4(), pol, "decision_publish")
    assert why and why.capability == "approvals.sign:legal"
    assert '"Sign approvals" permission for legal' in why


@pytest.mark.asyncio
async def test_reviewer_with_signing_may_sign_but_not_their_own_proposal():
    u = _user()
    with patch.object(
        caps, "capabilities_for", _granted("decisions.review", "approvals.sign")
    ):
        assert (
            await approver_denial(None, u, uuid.uuid4(), POLICY, "decision_publish")
            is None
        )
        own = await approver_denial(None, u, u.id, POLICY, "decision_publish")
    assert own and "someone else" in own


@pytest.mark.asyncio
async def test_other_gates_do_not_ask_for_review():
    u = _user()
    with patch.object(caps, "capabilities_for", _granted("approvals.sign")):
        assert await approver_denial(None, u, uuid.uuid4(), POLICY, "tool_call") is None
        assert await approver_denial(None, u, uuid.uuid4(), POLICY) is None


@pytest.mark.asyncio
async def test_signoff_route_passes_the_gate_kind():
    import inspect

    from app.routers import approvals

    src = inspect.getsource(approvals.sign_off)
    assert "approver_denial(db, user, a.requested_by, a.policy, a.gate_kind)" in src


class _Rows:
    def all(self):
        return []


class _Db:
    def __init__(self):
        self.sql: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        from sqlalchemy.dialects import postgresql

        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))
        return _Rows()


@pytest.mark.asyncio
async def test_sweeper_skips_runs_whose_lease_is_still_renewed():
    from app.core import scheduler

    db = _Db()

    @asynccontextmanager
    async def _lock(key):
        yield True

    with patch.object(scheduler, "advisory_lock", _lock), patch(
        "app.core.deps.async_session", lambda: db
    ):
        await scheduler.sweep_stale_executions()
    sql = db.sql[0]
    assert "executions.lease_expires_at IS NULL" in sql
    assert "executions.lease_expires_at < now()" in sql


@pytest.mark.asyncio
async def test_signing_granted_by_a_permission_set_opens_gates_without_a_policy():
    u = _user("user")
    with patch.object(caps, "capabilities_for", _granted("approvals.sign")):
        assert await approver_denial(None, u, uuid.uuid4(), None, "human_approval") is None
    with patch.object(caps, "capabilities_for", _granted()):
        why = await approver_denial(None, u, uuid.uuid4(), None, "human_approval")
    assert why and "admins, creators" in why and why.capability == "approvals.sign"
