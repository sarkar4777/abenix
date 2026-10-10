"""Slack and email copies of notifications: link text, who gets email, and the URL guard."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import types
from pathlib import Path

import pytest
import yaml

from app.core import notifications as n

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "infra/helm/abenix"


def test_mask_shows_the_real_host() -> None:
    assert n.mask_webhook("https://hooks.slack.com/services/T/B/abcdef123456") == (
        "https://hooks.slack.com/…123456"
    )
    assert n.mask_webhook("http://catcher:8080/hooks/run1").startswith(
        "http://catcher:8080/…"
    )
    assert n.mask_webhook("") == ""


def test_slack_url_guard_blocks_private_targets(monkeypatch) -> None:
    monkeypatch.delenv("EVENTS_ALLOW_PRIVATE_TARGETS", raising=False)
    monkeypatch.setenv("EVENTS_ALLOWED_INTERNAL_HOSTS", "abenix-webhook-catcher")
    run = asyncio.run
    assert run(n.slack_url_problem("http://localhost:8080/x"))
    assert run(n.slack_url_problem("https://10.0.0.5/hook"))
    assert run(n.slack_url_problem("https://169.254.169.254/latest"))
    assert run(n.slack_url_problem("ftp://hooks.slack.com/x"))
    # plain http only for a host the operator named
    assert run(n.slack_url_problem("http://93.184.216.34/x"))
    assert run(n.slack_url_problem("https://93.184.216.34/x")) is None
    assert (
        run(n.slack_url_problem("http://abenix-webhook-catcher:8080/hooks/a")) is None
    )


def test_post_slack_refuses_a_private_url(monkeypatch) -> None:
    monkeypatch.delenv("EVENTS_ALLOWED_INTERNAL_HOSTS", raising=False)
    monkeypatch.delenv("EVENTS_ALLOW_PRIVATE_TARGETS", raising=False)
    ok = asyncio.run(
        n._post_slack("https://127.0.0.1/x", title="t", message="m", link=None)
    )
    assert ok is False


def test_slack_text_carries_a_readable_link(monkeypatch) -> None:
    sent: dict = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            sent.update(json)
            return types.SimpleNamespace(status_code=200)

    async def no_problem(url):
        return None

    monkeypatch.setattr(n, "slack_url_problem", no_problem)
    monkeypatch.setattr(n.httpx, "AsyncClient", FakeClient)
    ok = asyncio.run(
        n._post_slack(
            "https://hooks.slack.com/x",
            title="Abenix — Run failed",
            message="boom",
            link="http://localhost:3100/agents/a/chat",
        )
    )
    assert ok
    assert "<http://localhost:3100/agents/a/chat|Open in Abenix>" in sent["text"]
    assert sent["text"].startswith("*Abenix — Run failed*")


def test_email_body_and_full_links(monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3100")
    body = n._email_body("Run failed", "The model refused", "/agents/x/chat")
    assert "Open it in Abenix: http://localhost:3100/agents/x/chat" in body
    assert "http://localhost:3100/settings/notifications" in body
    assert n._full_link("/approvals") == "http://localhost:3100/approvals"
    assert n._full_link("https://elsewhere/x") == "https://elsewhere/x"
    assert n._full_link(None) is None


def test_requests_that_need_someone_are_emailed() -> None:
    assert "approval_pending" in n.EMAIL_ALWAYS
    assert "autonomy_demoted" in n.EMAIL_ALWAYS
    assert n._severity_for("execution_failed") == "error"


def test_a_failed_run_is_not_announced_as_completed() -> None:
    from app.routers.agents import completion_event_type

    failed = types.SimpleNamespace(status=types.SimpleNamespace(value="failed"))
    done = types.SimpleNamespace(status=types.SimpleNamespace(value="completed"))
    assert completion_event_type("execution_complete", failed) == "execution_failed"
    assert completion_event_type("execution_complete", done) == "execution_complete"
    assert completion_event_type("execution_failed", done) == "execution_failed"


needs_helm = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _render(*args: str) -> list[dict]:
    out = subprocess.run(
        ["helm", "template", "abenix", str(CHART), "-n", "abenix", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _config(docs: list[dict]) -> dict:
    return next(
        d
        for d in docs
        if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "abenix-config"
    )["data"]


@needs_helm
def test_dev_catchers_are_off_by_default() -> None:
    docs = _render()
    names = {d["metadata"]["name"] for d in docs}
    assert "abenix-mailpit" not in names and "abenix-mock-oidc" not in names
    cfg = _config(docs)
    assert cfg["SMTP_HOST"] == ""
    assert "webhook-catcher" not in cfg["EVENTS_ALLOWED_INTERNAL_HOSTS"]
    assert "OIDC_INTERNAL_URL_MAP" not in cfg


@needs_helm
def test_local_values_turn_the_catchers_on() -> None:
    docs = _render("-f", str(CHART / "values-local.yaml"))
    names = {d["metadata"]["name"] for d in docs}
    assert {"abenix-mailpit", "abenix-webhook-catcher", "abenix-mock-oidc"} <= names
    cfg = _config(docs)
    assert cfg["SMTP_HOST"] == "abenix-mailpit" and cfg["SMTP_STARTTLS"] == "false"
    assert "abenix-webhook-catcher" in cfg["EVENTS_ALLOWED_INTERNAL_HOSTS"].split(",")
    assert cfg["OIDC_INTERNAL_URL_MAP"].startswith(
        "http://localhost:8090=http://abenix-mock-oidc."
    )


def test_an_approval_request_posts_once_to_the_channel(monkeypatch) -> None:
    import uuid

    from app.routers import approvals

    members = [types.SimpleNamespace(id=uuid.uuid4()) for _ in range(4)]
    seen = {"notify": [], "slack": 0}

    class DB:
        async def execute(self, stmt):
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: members)
            )

        async def commit(self):
            pass

    async def fake_create(db, **kw):
        seen["notify"].append(kw)

    async def fake_once(db, tenant_id, **kw):
        seen["slack"] += 1
        assert kw["link"] == "/approvals"

    async def no_settings(db, tid):
        return {}

    async def no_hook(*a, **k):
        return None

    monkeypatch.setattr(approvals, "create_notification", fake_create)
    monkeypatch.setattr(n, "post_once_to_tenant_slack", fake_once)
    monkeypatch.setattr(approvals, "_tenant_settings", no_settings)
    monkeypatch.setattr(approvals, "_post_webhook", no_hook)
    a = types.SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title="Publish rates version 1",
        agent_id=None,
        agent_execution_id=None,
        required_signoffs=1,
        expires_at=None,
        gate_kind="decision_publish",
    )
    monkeypatch.setattr(approvals, "_serialize", lambda x: {})
    requester = types.SimpleNamespace(id=uuid.uuid4(), full_name="Ann", email="a@b")
    asyncio.run(approvals._notify_pending(DB(), a, requester=requester))
    assert len(seen["notify"]) == 4
    assert all(k["slack"] is False for k in seen["notify"])
    assert seen["slack"] == 1


def test_only_admins_change_retention() -> None:
    import uuid

    from app.routers.settings import update_retention
    from models.user import UserRole

    member = types.SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.USER
    )
    r = asyncio.run(update_retention({"execution_retention_days": 7}, member, None))
    assert r.status_code == 403
    admin = types.SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.ADMIN
    )
    r = asyncio.run(update_retention({"audit_log_retention_days": 30}, admin, None))
    assert r.status_code == 400
    assert b"365 or more" in r.body


class _FakeRedis:
    def __init__(self):
        self.kv: dict = {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def get(self, k):
        return self.kv.get(k)


def test_pool_runs_are_announced_once(monkeypatch) -> None:
    import uuid
    from datetime import datetime, timezone

    from app.routers import agents
    from app.services import run_announcer as ra
    from models.execution import ExecutionStatus

    def row(**kw):
        base = dict(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            trigger_id=None,
            parent_execution_id=None,
            status=ExecutionStatus.FAILED,
            cost=None,
            duration_ms=10,
            error_message="Moderation policy blocked the request",
            completed_at=datetime.now(timezone.utc),
        )
        base.update(kw)
        return types.SimpleNamespace(**base)

    rows = [row(), row(status=ExecutionStatus.COMPLETED, error_message=None)]
    told = []

    class DB:
        async def execute(self, q):
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: rows)
            )

        async def rollback(self):
            pass

    class Factory:
        async def __aenter__(self):
            return DB()

        async def __aexit__(self, *a):
            return False

    async def fake_emit(db, ex, ev, **kw):
        if not await ra.claim(ex.id, redis=kw["redis"]):
            return False
        told.append((ev, kw.get("error_message")))
        return True

    monkeypatch.setattr(agents, "_emit_execution_event", fake_emit)
    r = _FakeRedis()
    assert asyncio.run(ra.announce_backlog(lambda: Factory(), redis=r)) == 2
    assert told[0] == ("execution_failed", "Moderation policy blocked the request")
    assert told[1] == ("execution_complete", None)
    # a second scan over the same window says nothing again
    assert asyncio.run(ra.announce_backlog(lambda: Factory(), redis=r)) == 0
    assert ra.wants_announcement(row(trigger_id=uuid.uuid4())) is False
    assert ra.wants_announcement(row(parent_execution_id=uuid.uuid4())) is False


def test_failed_trigger_runs_from_a_pool_tell_the_trigger_owner(monkeypatch) -> None:
    import uuid
    from datetime import datetime, timezone

    from app.routers import agents, triggers
    from app.services import run_announcer as ra
    from models.execution import ExecutionStatus

    tid = uuid.uuid4()
    failed = types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trigger_id=tid,
        parent_execution_id=None,
        status=ExecutionStatus.FAILED,
        cost=None,
        duration_ms=10,
        error_message="Tool timed out",
        completed_at=datetime.now(timezone.utc),
    )
    noticed = []

    class DB:
        async def execute(self, q):
            return types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(all=lambda: [failed])
            )

        async def rollback(self):
            pass

    class Factory:
        async def __aenter__(self):
            return DB()

        async def __aexit__(self, *a):
            return False

    async def fake_once(db, trigger_id, execution_id, error):
        noticed.append((trigger_id, execution_id, error))
        return True

    async def no_emit(*a, **kw):
        raise AssertionError("a trigger run is not announced as a plain run")

    monkeypatch.setattr(triggers, "notify_trigger_failure_once", fake_once)
    monkeypatch.setattr(agents, "_emit_execution_event", no_emit)
    assert asyncio.run(ra.announce_backlog(lambda: Factory(), redis=_FakeRedis())) == 1
    assert noticed == [(tid, failed.id, "Tool timed out")]
