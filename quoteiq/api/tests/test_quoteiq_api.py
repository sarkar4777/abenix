"""Tests for the QuoteIQ API that need no Abenix: the inbox, reading a run, and
the review flow against a fake SDK.

    cd quoteiq/api && pytest
"""

from __future__ import annotations

import asyncio
import dataclasses
import json

import httpx
import pytest

from app.core import abenix, results, reviews, runs
from app.core.config import settings
from app.core.emails import load_emails, parse_email
from app.core.reviews import ReviewRefused
from app.core.store import EmailStore, current_draft
from tests import fakes

STAFF = settings.staff_name


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> fakes.FakeSDK:
    fake = fakes.FakeSDK()
    for module in (runs, reviews):
        monkeypatch.setattr(module, "new_sdk", lambda *a, **k: fake)
    return fake


@pytest.fixture
async def store() -> EmailStore:
    s = EmailStore()
    await s.load(load_emails())
    return s


async def drain() -> None:
    """Wait for every background job the app started."""
    while abenix._tasks:
        await asyncio.gather(*list(abenix._tasks), return_exceptions=True)


async def processed(store: EmailStore, sdk: fakes.FakeSDK, *outputs) -> list[dict]:
    """Process the next emails with these pipeline results; return the records."""
    sdk.pipeline_outputs.extend(outputs)
    claimed = []
    for _ in outputs:
        record = await store.claim_next()
        claimed.append(record["id"])
        abenix.spawn(runs.process_email(store, record["id"], record["job"]), name=record["id"])
    await drain()
    return [await store.get(i) for i in claimed]


# ── the inbox ────────────────────────────────────────────────────────────


def test_every_example_email_loads_in_queue_order():
    emails = load_emails()
    assert [e["id"][:2] for e in emails] == ["01", "02", "03", "04", "05", "06", "07"]
    assert all(e["from_email"].endswith(".example") for e in emails)


def test_the_sender_and_subject_come_from_the_headers():
    e = parse_email("x", "From: Brackenmoor Defence Systems, Procurement <procurement@brackenmoor-defence.example>\n"
                         "Subject: Quotation request: J 51034 wire\n\nDear Sir or Madam,")
    assert e["from_name"] == "Brackenmoor Defence Systems, Procurement"
    assert e["from_email"] == "procurement@brackenmoor-defence.example"
    assert e["subject"] == "Quotation request: J 51034 wire"


def test_an_email_without_an_address_is_refused():
    with pytest.raises(ValueError):
        parse_email("x", "From: Someone\nSubject: Hi\n\nHello")


async def test_a_chosen_email_is_claimed_out_of_queue_order(store):
    ids = [r["id"] for r in await store.list()]
    chosen = await store.claim(ids[4])
    assert chosen["status"] == "processing" and chosen["job"]
    assert await store.claim(ids[4]) is None  # already taken
    assert (await store.claim_next())["id"] == ids[0]  # the queue skips nothing else
    with pytest.raises(KeyError):
        await store.claim("nope")


async def test_claims_take_emails_in_order_until_none_is_left(store):
    ids = [(await store.claim_next())["id"][:2] for _ in range(7)]
    assert ids == ["01", "02", "03", "04", "05", "06", "07"]
    assert await store.claim_next() is None
    assert (await store.stats())["processing"] == 7


# ── reading a run ────────────────────────────────────────────────────────


def test_a_quote_run_reads_into_lines_and_a_draft_addressed_from_the_headers():
    out = fakes.run_output("quote")
    out["email"]["to"] = "someone-else@example"
    got = results.read_run(fakes.finished_run("e1", out), to="d.okafor@quillfeather-avionics.example")
    assert got["status"] == "success"
    assert [line["outcome"] for line in got["lines"]] == ["matched", "matched"]
    assert got["lines"][0]["product"]["sku"] == "FW-10001"
    assert got["email"]["to"] == "d.okafor@quillfeather-avionics.example"
    assert got["reason"] is None  # "[not available]" isn't shown as a reason


def test_an_escalation_has_no_email_and_keeps_the_items_for_staff():
    got = results.read_run(fakes.finished_run("e1", fakes.run_output("escalation")), to="a@b.example")
    assert got["status"] == "escalated"
    assert got["email"] is None
    assert got["escalation"]["summary"] == "One size missing"
    assert got["escalation"]["reason"] is None


@pytest.mark.parametrize("key", ["nearest_products", "nearest"])
def test_an_escalation_items_nearest_products_read_the_same_under_either_name(key):
    out = fakes.run_output("escalation")
    out["escalation"]["items"] = [{"outcome": "not_in_catalogue", key: [{"sku": "FW-10004", "name": "8 AWG"}]}]
    [item] = results.read_run(fakes.finished_run("e1", out), to="a@b.example")["escalation"]["items"]
    assert item["nearest_products"] == [{"sku": "FW-10004", "name": "8 AWG"}] and "nearest" not in item


def test_the_output_text_is_read_when_the_result_node_is_missing():
    run = fakes.finished_run("e1", fakes.run_output("clarification"))
    run["node_results"] = {}
    assert results.read_run(run, to="a@b.example")["status"] == "clarification"


@pytest.mark.parametrize("break_it, message", [
    (lambda o: o.update(outcome="maybe"), "outcome"),
    (lambda o: o.update(lines=[]), "no RFQ lines"),
    (lambda o: o["lines"].append({"response": "not json"}), "isn't JSON"),
    (lambda o: o["lines"].append({"response": json.dumps({"outcome": "found"})}), "no known outcome"),
    (lambda o: o.update(email="[not available]"), "no email"),
    (lambda o: o["email"].update(body=""), "no body"),
])
def test_a_run_that_cant_be_read_is_a_system_error(break_it, message):
    out = fakes.run_output("quote")
    break_it(out)
    with pytest.raises(results.RunUnreadable, match=message):
        results.read_run(fakes.finished_run("e1", out), to="a@b.example")


def test_a_drafted_email_naming_a_sku_is_a_system_error():
    out = fakes.run_output("quote")
    out["email"]["body"] += " Item FW-10001 is in stock."
    with pytest.raises(results.RunUnreadable, match="SKU FW-10001"):
        results.read_run(fakes.finished_run("e1", out), to="a@b.example")


@pytest.mark.parametrize("answer", [
    {"awg": [20, 22], "colour_code": ["0", "9"]},
    [{"attribute": "awg", "values": [20, 22]}, {"attribute": "colour_code", "values": ["0", "9"]}],
])
def test_what_candidates_differ_on_reads_the_same_in_either_shape(answer):
    item = {"response": json.dumps({"outcome": "needs_clarification", "differs_on": answer})}
    assert results.read_line(item, 0)["differs_on"] == {"awg": [20, 22], "colour_code": ["0", "9"]}


def test_free_text_the_model_answers_as_an_object_reads_as_text():
    out = fakes.run_output("escalation")
    out["lines"][1] = fakes.other_line(2, "erp_record_inconsistent",
                                       problem={"fields_disagree": ["product_color vs colour_code"]})
    out["escalation"]["items"] = [{"problem": {"fields_disagree": ["product_color vs colour_code"]}}]
    got = results.read_run(fakes.finished_run("e1", out), to="a@b.example")
    assert got["lines"][1]["problem"] == "fields disagree: product_color vs colour_code"
    assert got["escalation"]["items"][0]["problem"] == "fields disagree: product_color vs colour_code"


def test_a_failed_run_says_why():
    with pytest.raises(results.RunUnreadable, match="failed: model overloaded"):
        results.read_run(fakes.finished_run("e1", None, "failed"), to="a@b.example")


def test_progress_counts_each_finished_line_once():
    p = results.new_progress()
    events = [
        {"event": "node_start", "node_id": "extract"},
        {"event": "node_complete", "node_id": "extract", "status": "completed"},
        {"event": "node_start", "node_id": "search[0]"},  # the for_each step itself never starts
        {"event": "node_complete", "node_id": "search[1]", "status": "completed"},
        {"event": "node_complete", "node_id": "search[1]", "status": "completed"},  # replayed twice
        {"event": "node_complete", "node_id": "search[0]", "status": "completed"},
        {"event": "token", "text": "..."},
    ]
    for e in events:
        results.apply_event(p, e)
    assert p["steps"]["extract"] == "done"
    assert p["steps"]["search"] == "running"
    assert p["lines_done"] == 2


# ── processing ───────────────────────────────────────────────────────────


async def test_a_quote_is_raised_for_review_on_abenix(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    assert (record["status"], record["review"]) == ("success", "awaiting_review")
    run_call = sdk.executed[0]
    assert run_call["wait"] == "submitted"
    assert run_call["act_as"].display_name == STAFF
    assert run_call["context"]["sender_email"] == record["from_email"]

    [approval] = sdk.approvals_for("pending")
    assert approval["expires_seconds"] == 7 * 24 * 3600
    assert approval["agent_execution_id"] == record["run"]["execution_id"]
    assert "Approve sends it" in approval["title"] and "Deny escalates" in approval["title"]
    assert approval["payload"]["quote_lines"][0]["description"].startswith("26 AWG")
    assert "FW-" not in json.dumps(approval["payload"])  # no SKUs reach the reviewer's email view
    assert current_draft(record)["approval"]["id"] == approval["id"]


async def test_an_escalation_raises_no_review(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("escalation"))
    assert (record["status"], record["review"]) == ("escalated", None)
    assert record["drafts"] == [] and sdk.approvals_by_id == {}


async def test_a_failed_run_is_a_system_error_that_retry_runs_again(store, sdk):
    [record] = await processed(store, sdk, "failed")
    assert (record["status"], record["error_step"]) == ("system_error", "pipeline")
    assert "model overloaded" in record["error"]

    sdk.pipeline_outputs.append(fakes.run_output("clarification"))
    await runs.retry(store, record["id"])
    await drain()
    record = await store.get(record["id"])
    assert (record["status"], record["review"]) == ("clarification", "awaiting_review")
    assert record["error"] is None


async def test_a_failed_check_of_the_run_is_tried_again(store, sdk, monkeypatch):
    monkeypatch.setattr(runs, "POLL_SECONDS", 0)
    sdk.check_errors = [httpx.ConnectError("blip"), fakes.status_error(503), httpx.ReadTimeout("slow")]
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    assert (record["status"], record["review"]) == ("success", "awaiting_review")


async def test_a_check_abenix_refuses_is_a_system_error_at_once(store, sdk, monkeypatch):
    monkeypatch.setattr(runs, "POLL_SECONDS", 0)
    sdk.check_errors = [fakes.status_error(404)]
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    assert record["status"] == "system_error"
    assert "Lost track of the run" in record["error"] and "404" in record["error"]


async def test_checks_failing_until_the_deadline_say_why(store, sdk, monkeypatch):
    monkeypatch.setattr(runs, "POLL_SECONDS", 0)
    monkeypatch.setattr(runs, "settings", dataclasses.replace(settings, run_timeout_seconds=0))
    sdk.check_errors = [httpx.ConnectError("abenix down")] * 50
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    assert record["status"] == "system_error"
    assert "couldn't be read" in record["error"] and "abenix down" in record["error"]


async def test_only_a_system_error_can_be_retried(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    with pytest.raises(ValueError):
        await runs.retry(store, record["id"])


async def test_a_review_that_cant_be_raised_can_be_raised_again(store, sdk):
    sdk.fail_approvals = True
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    assert record["review"] == "awaiting_review"
    assert current_draft(record)["approval"] is None
    assert "Could not raise" in current_draft(record)["approval_error"]

    sdk.fail_approvals = False
    await reviews.raise_again(store, record["id"])
    assert current_draft(await store.get(record["id"]))["approval"]["status"] == "pending"


# ── reviewing in the app ─────────────────────────────────────────────────


async def test_send_approves_and_records_what_was_sent(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    await reviews.review(store, record["id"], "send", "")
    record = await store.get(record["id"])
    assert sdk.signed[-1][1:] == ("approved", f"Reviewed by {STAFF}")
    assert (record["status"], record["review"]) == ("success", "sent")
    assert current_draft(record)["sent"]["body"] == current_draft(record)["ai"]["body"]


async def test_an_edited_draft_is_sent_as_edited(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    ai = current_draft(record)["ai"]
    await reviews.save_edits(store, record["id"], {**ai, "body": "Edited body"})
    await reviews.review(store, record["id"], "send", "")
    draft = current_draft(await store.get(record["id"]))
    assert sdk.signed[-1][2] == f"Reviewed by {STAFF}: sent with edits"
    assert draft["sent"]["body"] == "Edited body" and draft["sent"]["edited"] is True
    assert draft["ai"]["body"] == ai["body"]


async def test_no_edit_or_revert_while_a_send_is_being_signed(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    ai = current_draft(record)["ai"]
    await reviews.save_edits(store, record["id"], {**ai, "body": "Reviewed body"})
    sdk.hold_signing = asyncio.Event()
    sending = asyncio.create_task(reviews.review(store, record["id"], "send", ""))
    await sdk.signing.wait()

    with pytest.raises(ReviewRefused, match="being signed"):
        await reviews.save_edits(store, record["id"], {**ai, "body": "Changed while sending"})
    with pytest.raises(ReviewRefused, match="being signed"):
        await reviews.revert_edits(store, record["id"])

    sdk.hold_signing.set()
    await sending
    draft = current_draft(await store.get(record["id"]))
    assert sdk.signed[-1][2] == f"Reviewed by {STAFF}: sent with edits"
    assert draft["sent"]["body"] == "Reviewed body" and draft["sent"]["edited"] is True


async def test_an_edit_naming_a_sku_is_refused(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    ai = current_draft(record)["ai"]
    with pytest.raises(ReviewRefused, match="FW-10002") as refused:
        await reviews.save_edits(store, record["id"], {**ai, "body": "We can offer FW-10002 instead."})
    assert refused.value.status == 422
    assert current_draft(await store.get(record["id"]))["edited"] is None


async def test_saving_the_ai_text_back_is_a_revert(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    ai = current_draft(record)["ai"]
    await reviews.save_edits(store, record["id"], {**ai, "greeting": "Hello Daniel,"})
    await reviews.save_edits(store, record["id"], dict(ai))
    assert current_draft(await store.get(record["id"]))["edited"] is None


async def test_ask_the_customer_returns_the_approval_and_redrafts_for_review(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    sdk.drafts.append({**fakes.email("clarification"), "to": "wrong@example"})
    await reviews.review(store, record["id"], "ask", "Ask whether 1.1 mm OD is a hard limit")
    await drain()

    assert sdk.signed[-1][1:] == ("returned", f"Reviewed by {STAFF}: Ask whether 1.1 mm OD is a hard limit")
    drafter_input = json.loads(sdk.executed[-1]["message"])
    assert drafter_input["reviewer_note"] == "Ask whether 1.1 mm OD is a hard limit"
    assert drafter_input["sender"]["email"] == record["from_email"]
    assert [line["outcome"] for line in drafter_input["lines"]] == ["matched", "matched"]
    assert drafter_input["lines"][0]["product"]["name"].startswith("26 AWG")
    assert drafter_input["lines"][0]["pricing"]["prices"][0]["quoted_qty"] == 100
    assert "FW-" not in sdk.executed[-1]["message"]  # the drafter never sees a SKU

    record = await store.get(record["id"])
    assert (record["status"], record["review"]) == ("clarification", "awaiting_review")
    first, second = record["drafts"]
    assert first["decision"]["action"] == "ask"
    assert second["kind"] == "redraft" and second["ai"]["to"] == record["from_email"]
    assert second["approval"]["status"] == "pending"
    assert len(sdk.approvals_for("pending")) == 1


async def test_a_failed_redraft_is_retried_with_the_same_note(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("clarification"))
    sdk.drafts.append("failed")
    await reviews.review(store, record["id"], "ask", "Ask for the colour only")
    await drain()
    failed = await store.get(record["id"])
    assert (failed["status"], failed["error_step"]) == ("system_error", "redraft")

    sdk.drafts.append(fakes.email("clarification"))
    await runs.retry(store, record["id"])
    await drain()
    record = await store.get(record["id"])
    assert (record["status"], record["review"]) == ("clarification", "awaiting_review")
    assert json.loads(sdk.executed[-1]["message"])["reviewer_note"] == "Ask for the colour only"


async def test_escalate_needs_a_note_beyond_the_reviewer_name(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    with pytest.raises(ReviewRefused) as refused:
        await reviews.review(store, record["id"], "escalate", "   ")
    assert refused.value.status == 422
    await reviews.review(store, record["id"], "escalate", "We can't make 1.1 mm OD in green")
    record = await store.get(record["id"])
    assert sdk.signed[-1][1] == "denied"
    assert (record["status"], record["review"]) == ("escalated", None)


async def test_a_decided_draft_cant_be_decided_again(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    await reviews.review(store, record["id"], "send", "")
    with pytest.raises(ReviewRefused):
        await reviews.review(store, record["id"], "escalate", "too late")


# ── decisions made on Abenix's own Approvals page ────────────────────────


async def test_a_send_on_abenix_sends_the_ai_draft_and_drops_unsent_edits(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    ai = current_draft(record)["ai"]
    await reviews.save_edits(store, record["id"], {**ai, "body": "Edited in the app"})
    await sdk.approvals.approve(current_draft(record)["approval"]["id"], reason="Looks right")
    await reviews.poll_once(store)
    record = await store.get(record["id"])
    draft = current_draft(record)
    assert record["review"] == "sent"
    assert draft["sent"]["body"] == ai["body"] and draft["decision"]["in_app"] is False
    assert "unsent edits" in record["history"][-1]["summary"]


async def test_a_return_on_abenix_redrafts_from_its_reason(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("quote"))
    sdk.drafts.append(fakes.email("clarification"))
    await sdk.approvals.return_for_changes(current_draft(record)["approval"]["id"], "Ask about the jacket")
    await reviews.poll_once(store)
    await drain()
    assert json.loads(sdk.executed[-1]["message"])["reviewer_note"] == "Ask about the jacket"
    assert (await store.get(record["id"]))["review"] == "awaiting_review"


async def test_an_expired_review_can_be_raised_again(store, sdk):
    [record] = await processed(store, sdk, fakes.run_output("clarification"))
    first = current_draft(record)["approval"]["id"]
    sdk.approvals_by_id[first]["status"] = "expired"
    await reviews.poll_once(store)
    assert (await store.get(record["id"]))["review"] == "review_expired"
    with pytest.raises(ReviewRefused):
        await reviews.review(store, record["id"], "send", "")

    await reviews.raise_again(store, record["id"])
    draft = current_draft(await store.get(record["id"]))
    assert draft["approval"]["id"] != first and draft["raises"] == 2
    assert sdk.approvals_by_id[draft["approval"]["id"]]["client_token"].endswith(":2")


# ── reset ────────────────────────────────────────────────────────────────


async def test_reset_denies_open_reviews_and_clears_every_result(store, sdk):
    await processed(store, sdk, fakes.run_output("quote"), fakes.run_output("escalation"))
    closed = await reviews.reset(store)
    assert closed == {"approvals_closed": 1, "approvals_left_open": 0}
    assert sdk.signed[-1][2] == f"Reviewed by {STAFF}: example reset, nothing sent"
    stats = await store.stats()
    assert (stats["waiting"], stats["processed"]) == (7, 0)


async def test_a_run_that_ends_after_a_reset_is_ignored(store, sdk):
    sdk.pipeline_outputs.append(fakes.run_output("quote"))
    record = await store.claim_next()
    await reviews.reset(store)
    await runs.process_email(store, record["id"], record["job"])
    after = await store.get(record["id"])
    assert after["status"] == "waiting" and after["drafts"] == []
    assert sdk.approvals_by_id == {}


async def test_stats_count_each_status_with_its_reviews(store, sdk):
    await processed(store, sdk, fakes.run_output("quote"), fakes.run_output("clarification"),
                    fakes.run_output("escalation"), "failed")
    stats = await store.stats()
    assert stats["processed"] == 4 and stats["waiting"] == 3
    assert stats["by_status"]["success"] == {"count": 1, "awaiting_review": 1}
    assert stats["by_status"]["clarification"] == {"count": 1, "awaiting_review": 1}
    assert stats["by_status"]["escalated"]["count"] == 1
    assert stats["by_status"]["system_error"]["count"] == 1


# ── the HTTP surface ─────────────────────────────────────────────────────


async def test_the_endpoints_answer_in_the_envelope(store, sdk):
    import main

    main.app.state.store = store
    sdk.pipeline_outputs.append(fakes.run_output("quote"))
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://qq") as client:
        started = await client.post("/api/qq/process-next")
        assert started.status_code == 202
        email_id = started.json()["data"]["id"]
        await drain()

        page = (await client.get(f"/api/qq/emails/{email_id}")).json()["data"]
        assert page["prev_id"] is None and page["next_id"].startswith("02")
        assert page["run_url"].endswith(page["run"]["execution_id"])
        assert "job" not in page

        rows = (await client.get("/api/qq/emails", params={"status": "success"})).json()["data"]
        assert [r["id"] for r in rows] == [email_id] and rows[0]["line_count"] == 2

        again = await client.post(f"/api/qq/emails/{email_id}/process")
        assert again.status_code == 409 and "already" in again.json()["detail"]
        assert (await client.post("/api/qq/emails/nope/process")).status_code == 404

        no_note = await client.post(f"/api/qq/emails/{email_id}/review", json={"action": "ask", "note": ""})
        assert no_note.status_code == 422
        sent = await client.post(f"/api/qq/emails/{email_id}/review", json={"action": "send"})
        assert sent.json()["data"]["review"] == "sent"
        assert (await client.get("/api/qq/emails/nope")).status_code == 404
