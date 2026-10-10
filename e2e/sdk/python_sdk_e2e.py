"""Python SDK against the live API, the way a developer uses it.

Needs a key generated in the UI (e2e/sdk/mint_key.spec.ts writes one):

    SDK_KEY_FILE=e2e/sdk/.sdk-key ABENIX_URL=http://localhost:8000 \\
        python -m pytest e2e/sdk/python_sdk_e2e.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "sdk" / "python"))

from abenix_sdk import Abenix, AbenixError, StreamEvent  # noqa: E402

BASE = os.environ.get("ABENIX_URL", "http://localhost:8000")
AGENT_SLUG = os.environ.get("SDK_E2E_AGENT", "sdk-e2e-assistant")
ACTION_KEY = "sample_plant.set_setpoint"
RUN = uuid.uuid4().hex[:8]


def _key() -> str:
    key = os.environ.get("ABENIX_API_KEY", "").strip()
    if not key:
        f = Path(os.environ.get("SDK_KEY_FILE", ROOT / "e2e" / "sdk" / ".sdk-key"))
        if f.exists():
            key = f.read_text(encoding="utf-8").strip()
    if not key:
        pytest.skip("no API key, run e2e/sdk/mint_key.spec.ts first")
    return key


def run(coro_fn):
    """Each test gets its own client on its own loop."""

    async def go():
        async with Abenix(api_key=_key(), base_url=BASE, timeout=240) as forge:
            return await coro_fn(forge)

    return asyncio.run(go())


async def ensure_agent(forge: Abenix) -> dict:
    agent = await forge.agents.by_slug(AGENT_SLUG)
    if agent:
        return agent
    return await forge.agents.create(
        {
            "name": "SDK e2e assistant",
            "slug": AGENT_SLUG,
            "description": "Answers short questions. Used by the SDK end to end suites.",
            "system_prompt": "You answer in one short sentence. No preamble.",
            "model_config": {
                "model": "claude-haiku-4-5-20251001",
                "temperature": 0,
                "max_tokens": 200,
                "tools": [],
            },
        }
    )


def test_identity():
    async def body(forge: Abenix):
        me = await forge.me()
        assert me["user"]["email"]
        perms = await forge.permissions()
        assert perms["role"]
        assert isinstance(perms["capabilities"], list) and perms["capabilities"]

    run(body)


def test_run_stream_and_read_back():
    async def body(forge: Abenix):
        agent = await ensure_agent(forge)
        result = await forge.execute(
            AGENT_SLUG, "What is the capital of France? One word."
        )
        assert result.status == "completed", result
        assert result.execution_id
        assert "paris" in result.output.lower(), result.output

        row = await forge.executions.get(result.execution_id)
        assert row["status"] == "completed"
        assert row["agent_id"] == agent["id"]
        out = row.get("output_message") or row.get("output") or ""
        assert "paris" in out.lower()

        events: list[StreamEvent] = []
        async for ev in forge.stream(agent["id"], "Name the largest planet. One word."):
            events.append(ev)
        kinds = [e.type for e in events]
        assert "token" in kinds and kinds[-1] == "done", kinds
        errors = [e.message for e in events if e.type == "error"]
        assert not errors, errors
        text = "".join(e.text or "" for e in events if e.type == "token")
        assert "jupiter" in text.lower(), text
        streamed_id = events[-1].execution_id
        assert streamed_id, "done carries the execution id"

        # a streamed run is written as it finishes
        streamed: dict = {}
        for _ in range(20):
            streamed = await forge.executions.get(streamed_id)
            if streamed["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(1)
        assert streamed["status"] == "completed", streamed["status"]

        listed = await forge.executions.list(agent_id=agent["id"], limit=20)
        ids = {r["id"] for r in listed}
        assert result.execution_id in ids and streamed_id in ids

        snaps = []
        async for snap in forge.watch(result.execution_id):
            snaps.append(snap)
            if snap.is_terminal:
                break
        assert snaps and snaps[-1].status == "completed"

    run(body)


def test_approvals_create_wait_and_decide():
    async def body(forge: Abenix):
        token = f"sdk-e2e-{RUN}"
        created = await forge.approvals.create(
            "SDK e2e: release the March invoices",
            {"invoices": 3, "total": 1250.0},
            client_token=token,
            expires_seconds=600,
        )
        aid = created["id"]
        assert created["status"] == "pending"
        # the same client_token gives back the same approval
        again = await forge.approvals.create("dup", {}, client_token=token)
        assert again["id"] == aid

        pending = await forge.approvals.list(status="pending")
        assert aid in {a["id"] for a in pending}
        got = await forge.approvals.get(aid)
        assert got["payload"]["invoices"] == 3

        async def approve_later():
            await asyncio.sleep(2)
            return await forge.approvals.approve(aid, reason="checked the totals")

        waited, approved = await asyncio.gather(
            forge.approvals.wait_for(aid, timeout_seconds=30), approve_later()
        )
        assert approved["status"] == "approved"
        assert waited["status"] == "approved", waited

        second = await forge.approvals.create(
            "SDK e2e: delete the archive", {"rows": 9}, expires_seconds=600
        )
        denied = await forge.approvals.deny(second["id"], reason="not this quarter")
        assert denied["status"] == "denied"
        with pytest.raises(ValueError):
            await forge.approvals.return_for_changes(second["id"], "  ")

    run(body)


def test_autonomy_propose_wait_and_outcome():
    async def body(forge: Abenix):
        overview = await forge.autonomy.overview()
        grants = [
            g
            for g in overview["grants"]
            if (g.get("action_type") or {}).get("key") == ACTION_KEY
        ]
        if not grants:
            pytest.skip(
                "the sample plant is not installed, use Install sample on /autonomy"
            )
        args = {"operation": "set_setpoint", "setpoint_bar": 4.5}
        prediction = {"metric": "pressure_bar", "value": 4.5, "low": 4.45, "high": 4.55}
        proposed = await forge.actions.propose(
            ACTION_KEY, args, intent="hold pressure near 4.5 bar", prediction=prediction
        )
        assert proposed["decision"] in ("run", "wait"), proposed
        if proposed["decision"] == "wait":
            assert proposed["approval_id"]

            async def approve_later():
                await asyncio.sleep(2)
                return await forge.approvals.approve(
                    proposed["approval_id"],
                    reason="inside the band",
                    edited_arguments={"setpoint_bar": 4.4},
                )

            cleared, _ = await asyncio.gather(
                forge.actions.wait(proposed["action_id"], timeout_seconds=30),
                approve_later(),
            )
            assert cleared["decision"] == "run", cleared
            assert cleared["edited"] is True
            assert cleared["arguments"]["setpoint_bar"] == 4.4
        await forge.actions.executed(
            proposed["action_id"], ok=True, result_preview="setpoint applied"
        )
        await forge.actions.report_outcome(
            proposed["action_id"], 4.47, note="read from the gauge"
        )
        detail = await forge.actions.get(proposed["action_id"])
        action = detail.get("action", detail)
        assert action["status"] == "executed", action
        assert action["outcome_status"] not in ("none", "pending"), action

        with pytest.raises(AbenixError) as e:
            await forge.actions.propose("no.such.action", {})
        assert e.value.status == 404 and e.value.code == "UNKNOWN_ACTION"

    run(body)


def test_lessons_and_feedback():
    async def body(forge: Abenix):
        agent = await ensure_agent(forge)
        result = await forge.execute(
            agent["id"], "How many days are in a leap year? Digits only."
        )
        assert result.execution_id
        lesson = await forge.lessons.report(
            agent["id"],
            "Answered with words when digits were asked for",
            expected="366",
            execution_id=result.execution_id,
        )
        assert lesson["lesson_id"] and lesson["agent_id"] == agent["id"]

        up = await forge.feedback.give(1, execution_id=result.execution_id)
        assert up.get("id")
        down = await forge.feedback.give(
            -1, execution_id=result.execution_id, correction="366"
        )
        assert down.get("id")
        assert down.get("lesson_id"), down

        with pytest.raises(ValueError):
            await forge.feedback.give(0, execution_id=result.execution_id)
        with pytest.raises(ValueError):
            await forge.lessons.report(agent["id"], " ")

        proposals = await forge.improvements.list(agent_id=agent["id"])
        assert isinstance(proposals, list)

    run(body)


def test_knowledge_upload_and_search():
    async def body(forge: Abenix):
        boot = await forge.knowledge.bootstrap_project(
            "sdk-e2e",
            "SDK e2e",
            collections=[{"name": "SDK e2e notes", "slug": "sdk-e2e-notes"}],
        )
        kb_id = boot["collections"][0]["id"]
        fact = f"The SDK e2e warehouse code {RUN} opens at 06:30 and closes at 21:00."
        doc = await forge.knowledge.upload(
            kb_id, fact.encode("utf-8"), filename=f"hours-{RUN}.txt"
        )
        assert doc["id"]
        deadline = time.time() + 180
        status = doc["status"]
        while time.time() < deadline:
            docs = await forge.knowledge.documents(kb_id)
            mine = next((d for d in docs if d["id"] == doc["id"]), None)
            status = (mine or {}).get("status")
            if status in ("ready", "failed", "degraded"):
                break
            await asyncio.sleep(3)
        assert status == "ready", status

        found = await forge.knowledge.search(
            kb_id, f"When does warehouse {RUN} open?", mode="vector", top_k=5
        )
        texts = " ".join(r["content"] for r in found["results"])
        assert RUN in texts, found

        with pytest.raises(AbenixError) as e:
            await forge.knowledge.upload(kb_id, b"", filename="empty.txt")
        assert e.value.status == 400

    run(body)


def test_chat_thread_send_and_read():
    async def body(forge: Abenix):
        await ensure_agent(forge)
        thread = await forge.chat.create(agent_slug=AGENT_SLUG, title=f"sdk e2e {RUN}")
        turn = await forge.chat.send(thread["id"], "Reply with the single word: ready")
        reply = turn["assistant_message"]["content"]
        assert "ready" in reply.lower(), reply
        assert not reply.startswith("[error]"), reply
        full = await forge.chat.get(thread["id"])
        assert len(full["messages"]) == 2
        await forge.chat.delete(thread["id"])

    run(body)
