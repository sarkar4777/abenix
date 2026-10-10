"""Round 3: real withdraw reasons, no notice to yourself, named duplicate requests, paged history,
decision search by words, and approval cards that say what is asked in plain words."""

from __future__ import annotations

import datetime as dt
import inspect
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import approvers as AP
from app.core import capabilities as caps
from app.routers import approvals as approvals_router
from app.routers import decisions as D
from models.approval import Approval, ApprovalStatus
from models.decision import DecisionModel, DecisionVersion
from models.user import UserRole


class _Res:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows


def _a(**kw):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        status=ApprovalStatus.pending,
        payload={},
        signoffs=[],
        gate_kind="decision_publish",
    )
    base.update(kw)
    return Approval(**base)


# 1. withdraw reasons


def test_a_withdrawal_keeps_why_and_who():
    a = _a(payload={"decision_key": "k"})
    by = uuid.uuid4()
    AP.mark_withdrawn(a, "The decision was archived.", by)
    assert a.status == ApprovalStatus.withdrawn and a.decided_at is not None
    row = approvals_router._serialize(a, {str(by): "Ana Admin"})
    assert row["withdraw_reason"] == "The decision was archived."
    assert row["withdrawn_by_name"] == "Ana Admin"
    b = _a()
    AP.mark_withdrawn(b, "The decision was archived.")
    row = approvals_router._serialize(b, {})
    assert row["withdrawn_by_name"] is None and row["withdraw_reason"]
    assert approvals_router._serialize(_a(), {})["withdraw_reason"] is None


def test_every_withdraw_path_records_a_reason():
    for fn in (
        D._close_reattests,
        D._withdraw_tier_change,
        D._withdraw_open,
        D.sweep_archived,
        D.withdraw,
    ):
        assert "mark_withdrawn(" in inspect.getsource(fn), fn.__name__
    from app.services import improvements

    assert "mark_withdrawn(" in inspect.getsource(improvements._withdraw_approval)
    # the person or action behind each one is passed on
    assert "by=actor" in inspect.getsource(D._do_archive)
    assert "by=actor" in inspect.getsource(D._do_retire)
    assert "by=user.id" in inspect.getsource(D.publish)
    assert "by=user.id" in inspect.getsource(D.update_model)


@pytest.mark.asyncio
async def test_taking_a_proposal_back_says_so():
    m = DecisionModel(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), key="k", name="K", risk_tier="high"
    )
    a = _a()
    v = DecisionVersion(
        id=uuid.uuid4(),
        model_id=m.id,
        version=2,
        state="proposed",
        approval_id=a.id,
        lock_version=1,
    )
    me = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=m.tenant_id, role=UserRole.ADMIN, email="a@x"
    )

    class Db:
        async def execute(self, stmt, params=None):
            ent = getattr(stmt.column_descriptions[0].get("entity"), "__name__", "")
            return _Res([m] if ent == "DecisionModel" else [v])

        async def get(self, cls, ident):
            return a

        async def commit(self):
            return None

        async def refresh(self, obj):
            return None

    with patch.object(D, "log_action", AsyncMock()):
        await D.withdraw(m.key, 2, None, me, Db())
    assert (
        a.payload["withdrawn"] == "Version 2 was taken back to a draft before sign-off."
    )
    assert a.payload["withdrawn_by"] == str(me.id)


# 2. no notice to yourself


@pytest.mark.asyncio
async def test_the_self_approver_is_not_told_about_their_own_signoff():
    me, other = uuid.uuid4(), uuid.uuid4()
    a = _a(title="Publish K version 1", tenant_id=uuid.uuid4())

    class Db:
        async def execute(self, stmt):
            return _Res([me, other])

        async def commit(self):
            return None

    with patch.object(approvals_router, "create_notification", AsyncMock()) as notify:
        await approvals_router._notify_self_approved(
            Db(), a, SimpleNamespace(id=me, full_name="Me", email="m@x"), "why"
        )
    assert [c.kwargs["user_id"] for c in notify.call_args_list] == [other]


# 3. a duplicate request names the decision and who asked


def test_a_waiting_request_is_named():
    m = DecisionModel(key="gw.safety.exclusion", name="Groundwork exclusion zones")
    words = D._pending_words(
        m,
        {
            "kind": "retire",
            "requested_by_name": "Rita",
            "requested_at": "2026-10-10T14:01:00+00:00",
        },
    )
    assert words == (
        "Rita already asked on 10 Oct 2026 at 14:01 UTC to retire a version of Groundwork exclusion zones, "
        "and it is waiting for sign-off. It can be approved or denied on Approvals."
    )
    assert "gw.safety.exclusion" not in words
    assert "_pending_words(m, waiting)" in inspect.getsource(D._guard_action)


# 4. paging what was settled


@pytest.mark.asyncio
async def test_settled_rows_come_in_pages_with_a_total():
    me = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=UserRole.ADMIN,
        email="a@x",
        created_at=None,
    )
    rows = [
        _a(status=ApprovalStatus.approved, requested_by=me.id, tenant_id=me.tenant_id)
        for _ in range(7)
    ]

    class Db:
        async def execute(self, stmt):
            return _Res(rows)

    with (
        patch.object(
            caps, "capabilities_for", AsyncMock(return_value=frozenset({"*"}))
        ),
        patch.object(
            approvals_router,
            "_serialize_many",
            AsyncMock(
                side_effect=lambda db, page, viewer: [{"id": str(a.id)} for a in page]
            ),
        ),
    ):
        r = await approvals_router._resolved_page(
            Db(), me, approvals_router.select(Approval), None, None, None, 3, 3, 0
        )
    body = json.loads(r.body)
    assert [x["id"] for x in body["data"]] == [str(a.id) for a in rows[3:6]]
    assert (
        body["meta"]["total"] == 7
        and body["meta"]["has_more"] is True
        and body["meta"]["offset"] == 3
    )


@pytest.mark.asyncio
async def test_settled_rows_the_viewer_never_concerned_are_not_counted():
    me = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=UserRole.USER,
        email="m@x",
        created_at=None,
    )
    mine = _a(
        status=ApprovalStatus.denied, requested_by=me.id, gate_kind="human_approval"
    )
    theirs = _a(status=ApprovalStatus.approved, gate_kind="human_approval")

    class Db:
        async def execute(self, stmt):
            return _Res([mine, theirs])

    with (
        patch.object(
            caps, "capabilities_for", AsyncMock(return_value=caps.ROLE_DEFAULTS["user"])
        ),
        patch.object(
            approvals_router,
            "_serialize_many",
            AsyncMock(
                side_effect=lambda db, page, viewer: [{"id": str(a.id)} for a in page]
            ),
        ),
    ):
        r = await approvals_router._resolved_page(
            Db(), me, approvals_router.select(Approval), None, None, None, 50, 0, 0
        )
    body = json.loads(r.body)
    assert [x["id"] for x in body["data"]] == [str(mine.id)] and body["meta"][
        "total"
    ] == 1


def test_the_list_takes_resolved_and_an_offset():
    src = inspect.getsource(approvals_router.list_approvals)
    assert 'status == "resolved"' in src and "resolved_offset" in src


# 5. search by words


def test_search_matches_each_word_in_name_key_or_description():
    from sqlalchemy.dialects import postgresql

    terms = D.search_terms("machine stop")
    assert len(terms) == 2
    sql = str(terms[0].compile(dialect=postgresql.dialect()))
    assert (
        "decision_models.name ILIKE" in sql
        and "decision_models.key ILIKE" in sql
        and "decision_models.description ILIKE" in sql
    )
    assert len(D.search_terms("gw.safety-exclusion")) == 3
    assert D.search_terms("   ") == []


# 7. cards in plain words


def test_kind_labels():
    assert approvals_router.kind_label("gw.plan.change") == "Plan change"
    assert approvals_router.kind_label("human_approval") == "Agent paused for a person"
    assert (
        approvals_router.kind_label("action:sample_plant.set_setpoint")
        == "Agent action"
    )
    assert approvals_router.kind_label(None) == "Request"
    assert approvals_router.kind_label("trade.execute") == "Execute"


def test_card_summaries():
    plan = _a(
        gate_kind="gw.plan.change",
        title="Approve plan change: hold trucks",
        payload={
            "why": "The superintendent's plan changes are at Watching",
            "changes": ["Hold all haul trucks", "Hold TC1"],
        },
        agent_id=uuid.uuid4(),
        agent_execution_id=uuid.uuid4(),
    )
    row = approvals_router._serialize(
        plan, {}, {str(plan.agent_id): "GW Site Superintendent"}
    )
    assert row["summary"] == (
        "GW Site Superintendent asks: Approve plan change: hold trucks. The superintendent's plan changes are at Watching. "
        "First change: Hold all haul trucks and 1 more"
    )
    assert (
        row["kind_label"] == "Plan change"
        and row["run_label"] == "Run of GW Site Superintendent"
    )
    gate = _a(
        gate_kind="human_approval",
        title="Refund 9200 EUR to order 7782",
        payload={"details": "Parcel arrived damaged.", "agent_name": "Refund Desk"},
    )
    assert (
        approvals_router._serialize(gate)["summary"]
        == "Refund Desk paused and asks a person: Refund 9200 EUR to order 7782. Parcel arrived damaged."
    )
    act = _a(
        gate_kind="action:plant.set",
        title="t",
        payload={
            "agent": {"name": "Plant operator"},
            "intent": "Raise pressure to 4.5 bar",
        },
    )
    assert (
        approvals_router._serialize(act)["summary"]
        == "Plant operator wants to act: Raise pressure to 4.5 bar"
    )
    dec = _a(
        gate_kind="decision_publish",
        title="Publish K version 1",
        payload={"summary": "Ready. 1 golden test pass."},
    )
    assert approvals_router._serialize(dec)["summary"] == "Ready. 1 golden test passes."
    assert "kind_label" in inspect.getsource(approvals_router.list_approvals)


# follow-ups from the frontend


def test_search_has_a_decisions_category_that_respects_access():
    from app.routers import search

    src = inspect.getsource(search.search)
    assert (
        '"category": "Decisions"' in src
        and 'has_capability(db, user, "decisions.view")' in src
    )
    assert "DecisionModel.archived_at.is_(None)" in src and "search_terms(q)" in src
    assert "isalnum" in src


@pytest.mark.asyncio
async def test_decision_cards_name_who_can_approve():
    tid = uuid.uuid4()
    asker = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tid,
        role=UserRole.ADMIN,
        email="a@x",
        full_name="Asker",
        is_active=True,
    )
    rita = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tid,
        role=UserRole.ADMIN,
        email="r@x",
        full_name="Rita",
        is_active=True,
    )
    a = _a(
        tenant_id=tid,
        gate_kind="decision_archive",
        requested_by=asker.id,
        policy={"capability": "approvals.sign", "exclude_requester": True},
    )
    people = [(asker, frozenset({"*"})), (rita, frozenset({"*"}))]
    with (
        patch.object(approvals_router, "tenant_people", AsyncMock(return_value=people)),
        patch.object(
            approvals_router, "sole_operator_enabled", AsyncMock(return_value=True)
        ),
        patch.object(approvals_router, "_requester_names", AsyncMock(return_value={})),
        patch.object(approvals_router, "_decision_details", AsyncMock(return_value={})),
        patch.object(approvals_router, "_agent_names", AsyncMock(return_value={})),
    ):
        rows = await approvals_router._serialize_many(None, [a])
    assert rows[0]["eligible_approvers"] == [{"id": str(rita.id), "name": "Rita"}]


def test_the_default_list_says_whether_there_is_more():
    src = inspect.getsource(approvals_router.list_approvals)
    assert (
        '"has_more": found > limit or not scanned_all' in src
        and "success(items, meta=meta)" in src
    )
