"""Archiving a decision closes everything still open on it, and nothing on an archived decision can be signed."""

from __future__ import annotations

import inspect
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import approvals as approvals_router
from app.routers import decisions as D
from app.routers import inbox
from app.schemas.connectors import ApprovalSignoffRequest
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


def _approval(kind, key="k", version=None, status=ApprovalStatus.pending):
    return Approval(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title=f"{kind} {key}",
        gate_kind=kind,
        status=status,
        requested_by=uuid.uuid4(),
        payload={"decision_key": key, "version": version, "link": f"/decisions/{key}"},
        signoffs=[],
    )


class _Db:
    def __init__(self, approvals, versions, models=()):
        self.approvals, self.versions, self.models = approvals, versions, list(models)
        self.commits = 0

    async def execute(self, stmt, params=None):
        ent = getattr(stmt.column_descriptions[0].get("entity"), "__name__", "")
        if ent == "Approval":
            return _Res([a for a in self.approvals if a.status == ApprovalStatus.pending])
        if ent == "DecisionVersion":
            return _Res([v for v in self.versions if v.state in ("proposed", "approved")])
        if ent == "DecisionModel":
            return _Res(self.models)
        return _Res([])

    async def commit(self):
        self.commits += 1


def _model():
    return DecisionModel(id=uuid.uuid4(), tenant_id=uuid.uuid4(), key="k", name="K", risk_tier="high")


@pytest.mark.asyncio
async def test_archiving_withdraws_everything_open_but_the_archive_request():
    m = _model()
    publish = _approval("decision_publish", version=3)
    tier = _approval("decision_tier_change")
    review = _approval("decision_reattest", version=1)
    archive = _approval("decision_archive")
    v3 = DecisionVersion(id=uuid.uuid4(), version=3, state="proposed", approval_id=publish.id, lock_version=1, risk_tier_at_proposal="high")
    v4 = DecisionVersion(id=uuid.uuid4(), version=4, state="approved", lock_version=1)
    db = _Db([publish, tier, review, archive], [v3, v4])
    with patch.object(D, "log_action", AsyncMock()) as audit:
        out = await D._do_archive(db, m.tenant_id, uuid.uuid4(), m, None, {}, keep=archive.id)
    assert m.archived_at is not None
    assert {a.id for a in out} == {publish.id, tier.id, review.id}
    for a in (publish, tier, review):
        assert a.status == ApprovalStatus.withdrawn
        assert a.payload["withdrawn"] == "The decision was archived."
    assert archive.status == ApprovalStatus.pending
    assert v3.state == "draft" and v3.approval_id is None and v4.state == "draft"
    details = audit.call_args.args[4]
    assert sorted(details["back_to_draft"]) == [3, 4] and len(details["withdrawn_approvals"]) == 3


@pytest.mark.asyncio
async def test_the_requester_is_told():
    a = _approval("decision_publish", version=2)
    db = SimpleNamespace(commit=AsyncMock())
    with patch("app.core.notifications.create_notification", AsyncMock()) as notify:
        await D.tell_withdrawn(db, [a], D.ARCHIVED_WITHDRAWN)
    db.commit.assert_awaited_once()
    kw = notify.call_args.kwargs
    assert kw["user_id"] == a.requested_by and kw["message"] == "Your request was withdrawn. The decision was archived."
    assert kw["link"] == "/decisions/k"


def test_both_archive_paths_tell_the_requesters():
    assert "tell_withdrawn(db, withdrawn, ARCHIVED_WITHDRAWN)" in inspect.getsource(D.archive_model)
    src = inspect.getsource(D._on_action_resolved)
    assert "keep=a.id" in src and "tell_withdrawn(db, withdrawn, ARCHIVED_WITHDRAWN)" in src


@pytest.mark.asyncio
async def test_leftovers_on_archived_decisions_are_swept():
    m = _model()
    m.archived_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    left = _approval("decision_publish", version=1)
    v1 = DecisionVersion(id=uuid.uuid4(), version=1, state="proposed", approval_id=left.id, lock_version=1)
    db = _Db([left], [v1], models=[m])
    with patch.object(D, "tell_withdrawn", AsyncMock()) as told:
        n = await D.sweep_archived(db, m.tenant_id)
    assert n == 1 and left.status == ApprovalStatus.withdrawn and v1.state == "draft"
    assert db.commits == 1
    told.assert_awaited_once()
    db = _Db([], [], models=[m])
    assert await D.sweep_archived(db, m.tenant_id) == 0 and db.commits == 0


def test_the_sweep_leaves_restore_requests_alone():
    from sqlalchemy.dialects import postgresql

    captured = []

    class Db:
        async def execute(self, stmt):
            captured.append(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))
            return _Res([])

    import asyncio

    asyncio.run(D.sweep_archived(Db(), uuid.uuid4()))
    assert "decision_publish" in captured[0] and "decision_restore" not in captured[0]


@pytest.mark.asyncio
async def test_signing_on_an_archived_decision_is_refused_and_withdrawn():
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.ADMIN, email="a@x", full_name="A")
    a = _approval("decision_publish", version=1)
    a.tenant_id = user.tenant_id

    class Db:
        async def execute(self, stmt, params=None):
            return _Res([a])

    with (
        patch.object(D, "archived_key", AsyncMock(return_value=True)),
        patch.object(D, "sweep_archived", AsyncMock(return_value=1)) as sweep,
    ):
        r = await approvals_router.sign_off(str(a.id), ApprovalSignoffRequest(decision="approve"), user, Db())
    body = json.loads(r.body)
    assert r.status_code == 409 and body["error"]["error_code"] == "DECISION_ARCHIVED"
    assert body["error"]["message"] == "This decision was archived, so there is nothing to approve. It has been withdrawn."
    sweep.assert_awaited_once()


def test_a_restore_request_can_still_be_signed():
    src = inspect.getsource(approvals_router.sign_off)
    assert 'a.gate_kind != "decision_restore"' in src


def test_lists_and_counts_sweep_first():
    assert "_sweep_archived(db, user.tenant_id)" in inspect.getsource(approvals_router.list_approvals)
    assert "_sweep_archived(db, user.tenant_id)" in inspect.getsource(inbox.inbox_counts)


def test_retiring_withdraws_reviews_and_duplicate_retires_for_that_version():
    src = inspect.getsource(D._do_retire)
    assert "_close_reattests(" in src
    assert 'kinds=("decision_retire",)' in src and "versions={v.version}" in src
