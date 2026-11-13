"""Email review: every AI-drafted email is an Abenix approval before it goes out.

The reviewer's three choices map onto the approval's three decisions:

    Send              approve
    Ask the customer  return for changes  (the note says what to ask)
    Escalate          deny                (the note says why)

The app raises the approval after the run, signs it when the reviewer decides
in the app, and polls it so a decision made on Abenix's own Approvals page
counts too. Nothing is mailed: "sent" records the text, the time and the
reviewer.

Asking the customer runs the email drafter again on the reviewer's note and
the RFQ, and the new clarification comes back for review.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from abenix_sdk import Abenix

from app.core.abenix import acting_subject, describe, new_sdk, reviewed_by, spawn, strip_reviewed_by
from app.core.config import settings
from app.core.results import (
    DRAFT_FIELDS,
    SUCCEEDED_RUN,
    RunUnreadable,
    lines_for_drafter,
    read_redraft,
    skus_in,
)
from app.core.store import EmailStore, StaleJob, add_event, current_draft, fail, new_draft, new_job, now

logger = logging.getLogger("quoteiq.reviews")


class ReviewRefused(Exception):
    """The review can't be done: 409 for the email's state, 422 for the request."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


# ── the three decisions ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Action:
    """One of the reviewer's choices and the approval decision it is."""

    status: str  # the approval's status once decided
    note_needed: str | None  # the refusal when the note is empty, or None if it is optional
    sign: Callable[[Abenix, str, str], Awaitable[Any]]  # (sdk, approval id, reason)
    apply: Callable[..., str | None]  # moves the record on, returns a redraft job if one starts


def _apply_send(r: dict[str, Any], draft: dict[str, Any], *, note: str | None, by: str, in_app: bool,
                where: str) -> None:
    use_edits = in_app and bool(draft.get("edited"))
    text = draft["edited"] if use_edits else draft["ai"]
    draft["sent"] = {**text, "at": now(), "by": by, "edited": use_edits}
    r["review"] = "sent"
    summary = f"Sent by {by}{where}" + (" with edits" if use_edits else "")
    if draft.get("edited") and not in_app:
        summary += ". The AI draft was sent and unsent edits in QuoteIQ were dropped"
    add_event(r, "sent", summary)
    return None


def _apply_ask(r: dict[str, Any], draft: dict[str, Any], *, note: str | None, by: str, in_app: bool,
               where: str) -> str:
    r.update(status="clarification", review="redrafting",
             redraft={"note": note or "Ask the customer for what is missing.", "started_at": now()})
    r["job"] = job = new_job()
    add_event(r, "ask", f"{by} chose to ask the customer{where}: {note or 'no note'}")
    return job


def _apply_escalate(r: dict[str, Any], draft: dict[str, Any], *, note: str | None, by: str, in_app: bool,
                    where: str) -> None:
    r.update(status="escalated", review=None)
    add_event(r, "escalated", f"Escalated by {by}{where}: {note or 'no note'}")
    return None


ACTIONS: dict[str, Action] = {
    "send": Action("approved", None, lambda sdk, aid, reason: sdk.approvals.approve(aid, reason=reason),
                   _apply_send),
    "ask": Action("returned", "Write what to ask the customer",
                  lambda sdk, aid, reason: sdk.approvals.return_for_changes(aid, reason), _apply_ask),
    "escalate": Action("denied", "Write why it is escalated",
                       lambda sdk, aid, reason: sdk.approvals.deny(aid, reason=reason), _apply_escalate),
}
ACTION_FOR_STATUS = {a.status: name for name, a in ACTIONS.items()}


# ── what the approval says ───────────────────────────────────────────────


def _kind_words(draft: dict[str, Any]) -> str:
    return "Quote" if draft["kind"] == "quote" else "Clarification"


def approval_title(record: dict[str, Any], draft: dict[str, Any]) -> str:
    title = (
        f"QuoteIQ: {_kind_words(draft).lower()} email to {record['from_name']} "
        f"(“{record['subject']}”). Approve sends it, Return for changes asks "
        f"the customer instead, Deny escalates to staff"
    )
    return title if len(title) <= 255 else title[:252] + "..."


def quote_lines(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The priced lines for the reviewer, as the customer will see them: no SKUs."""
    out = []
    for line in record.get("lines") or []:
        product = line.get("product") or {}
        pricing = line.get("pricing") or {}
        out.append({
            "customer_reference": line.get("customer_reference"),
            "standard_part_number": product.get("standard_part_number"),
            "description": product.get("name"),
            "currency": pricing.get("currency"),
            "lead_time_days": pricing.get("lead_time_days"),
            "prices": [
                {k: p.get(k) for k in ("requested_qty", "quoted_qty", "moq_applied", "discount_pct",
                                       "net_unit_price", "line_total")}
                for p in pricing.get("prices") or []
            ],
        })
    return out


def approval_payload(record: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": f"{_kind_words(draft)} email to {record['from_name']} for “{record['subject']}”",
        "app": "QuoteIQ",
        "email_id": record["id"],
        "rfq_subject": record["subject"],
        "customer": record["from_name"],
        "customer_email": record["from_email"],
        "draft": draft["kind"],
        "decisions": {
            "approve": "Send this email to the customer.",
            "return": "Ask the customer instead. Write what to ask, and QuoteIQ drafts a new clarification for review.",
            "deny": "Escalate to staff. Write why. Nothing is sent.",
        },
        "email": draft["ai"],
    }
    if draft.get("note"):
        payload["reviewer_note"] = draft["note"]
    if draft["kind"] == "quote":
        payload["quote_lines"] = quote_lines(record)
    return payload


# ── raising ──────────────────────────────────────────────────────────────


async def raise_review(sdk: Abenix, store: EmailStore, email_id: str, job: str | None = None,
                       agent_id: str | None = None) -> None:
    """Raise the Abenix approval for the email's current draft.

    The client token makes a repeated call return the same approval. It is
    built from the draft's run id, which is unique, so an email processed
    again after a reset never gets back an approval from before it.
    """
    record = await store.get(email_id)
    draft = current_draft(record or {})
    if record is None or draft is None:
        return
    token = f"quoteiq:{draft['execution_id'] or record['id'] + ':' + str(draft['n'])}:{draft['raises'] + 1}"
    try:
        approval = await sdk.approvals.create(
            approval_title(record, draft),
            approval_payload(record, draft),
            expires_seconds=settings.review_expiry_seconds,
            agent_id=agent_id,
            agent_execution_id=draft["execution_id"],
            client_token=token,
        )
        if not approval.get("id"):
            raise RuntimeError("Abenix returned no approval id")
    except Exception as exc:  # noqa: BLE001
        message = f"Could not raise the review in Abenix. {describe(exc)}"
        async with store.edit(email_id, job) as r:
            d = current_draft(r)
            if d is not None and d["n"] == draft["n"]:
                d["approval_error"] = message
                add_event(r, "review_error", message)
        logger.warning("%s: %s", email_id, message)
        return

    try:
        async with store.edit(email_id, job) as r:
            d = current_draft(r)
            if d is None or d["n"] != draft["n"]:
                raise StaleJob(email_id)
            d["approval"] = {
                "id": approval["id"],
                "status": "pending",
                "raised_at": now(),
                "expires_at": approval.get("expires_at"),
            }
            d["approval_error"] = None
            d["raises"] += 1
            r["review"] = "awaiting_review"
            add_event(r, "review_raised", "Review raised in Abenix" if d["raises"] == 1 else "Review raised again")
    except StaleJob:
        # The email was reset while the approval was being raised.
        await _deny_quietly(sdk, approval["id"])
        raise


async def raise_again(store: EmailStore, email_id: str) -> None:
    record = await store.get(email_id)
    if record is None:
        raise KeyError(email_id)
    draft = current_draft(record)
    expired = record.get("review") == "review_expired"
    unraised = record.get("review") == "awaiting_review" and draft and not draft.get("approval")
    if not (expired or unraised):
        raise ReviewRefused("only an expired review, or one that couldn't be raised, can be raised again")
    sdk = new_sdk()
    try:
        await raise_review(sdk, store, email_id)
    finally:
        await sdk.close()


# ── deciding ─────────────────────────────────────────────────────────────


async def review(store: EmailStore, email_id: str, action: str, note: str) -> None:
    """The reviewer's decision, made in the app, signed on the approval."""
    chosen = ACTIONS.get(action)
    if chosen is None:
        raise ReviewRefused(f"unknown action {action!r}", status=422)
    note = (note or "").strip()
    if chosen.note_needed and not note:
        raise ReviewRefused(chosen.note_needed, status=422)

    async with store.edit(email_id) as r:
        draft = current_draft(r)
        approval = (draft or {}).get("approval")
        if r.get("review") != "awaiting_review" or not draft:
            raise ReviewRefused("this email has no draft awaiting review")
        if not approval or approval.get("status") != "pending":
            raise ReviewRefused("this draft's review isn't open in Abenix. Raise it again first")
        # Keeps the poller off this approval, and edits out, while it is being signed.
        approval["status"] = "signing"
        approval_id = approval["id"]
        edited = bool(draft.get("edited"))

    if action == "send":
        reason = reviewed_by("sent with edits" if edited else None)
    else:
        reason = reviewed_by(note)

    sdk = new_sdk()
    try:
        await chosen.sign(sdk, approval_id, reason)
    except Exception as exc:  # noqa: BLE001
        async with store.edit(email_id) as r:
            d = current_draft(r)
            if d and (d.get("approval") or {}).get("id") == approval_id and d["approval"]["status"] == "signing":
                d["approval"]["status"] = "pending"
        # Decided elsewhere meanwhile (Abenix's Approvals page, or expired)? Apply that.
        try:
            current = await sdk.approvals.get(approval_id)
        except Exception:  # noqa: BLE001
            current = {}
        if current.get("status") and current["status"] != "pending":
            await apply_approval(store, email_id, current)
            raise ReviewRefused(f"this review was already {current['status']} in Abenix") from exc
        raise ReviewRefused(f"Abenix didn't take the decision. {describe(exc)}") from exc
    finally:
        await sdk.close()

    await apply_decision(store, email_id, approval_id, chosen.status, note=note or None,
                         by=settings.staff_name, in_app=True)


async def apply_approval(store: EmailStore, email_id: str, approval: dict[str, Any]) -> None:
    """Apply an approval read from Abenix, decided outside the app."""
    signoffs = approval.get("signoffs") or []
    last = signoffs[-1] if signoffs else {}
    note = strip_reviewed_by(last.get("reason")) or None
    by = last.get("user_name") or "Abenix"
    await apply_decision(store, email_id, approval["id"], approval["status"], note=note, by=by, in_app=False)


async def apply_decision(store: EmailStore, email_id: str, approval_id: str, status: str, *,
                         note: str | None, by: str, in_app: bool) -> None:
    """Move the email on from a decided approval. Applies once per approval."""
    redraft_job = None
    async with store.edit(email_id) as r:
        draft = current_draft(r)
        approval = (draft or {}).get("approval") or {}
        if approval.get("id") != approval_id or approval.get("status") not in {"pending", "signing"}:
            return
        approval["status"] = status
        approval["decided_at"] = now()
        action = ACTION_FOR_STATUS.get(status)
        if action is None:  # expired, withdrawn
            r["review"] = "review_expired"
            add_event(r, "review_expired", f"Review {status} in Abenix before anyone decided")
        else:
            draft["decision"] = {"action": action, "note": None if action == "send" else note, "by": by,
                                 "at": now(), "in_app": in_app}
            redraft_job = ACTIONS[action].apply(r, draft, note=note, by=by, in_app=in_app,
                                                where="" if in_app else " in Abenix")
    if redraft_job:
        start_redraft(store, email_id, redraft_job)


# ── the redraft ──────────────────────────────────────────────────────────


def drafter_message(record: dict[str, Any]) -> str:
    """What the email drafter is given to redraft from the reviewer's note:
    the RFQ's sender and subject, the brief, and the line results, without SKUs."""
    sender = dict(record.get("sender") or {"name": record["from_name"]})
    sender["email"] = record["from_email"]
    return json.dumps({
        "sender": sender,
        "subject": record["subject"],
        "staff_name": settings.staff_name,
        "brief": record.get("email_brief") or {},
        "lines": lines_for_drafter(record.get("lines") or []),
        "reviewer_note": record["redraft"]["note"],
    })


async def redraft(store: EmailStore, email_id: str, job: str) -> None:
    """Run the email drafter on the reviewer's note. The new draft goes back for review."""
    record = await store.get(email_id)
    if record is None or not record.get("redraft"):
        return
    note = record["redraft"]["note"]
    sdk = new_sdk(timeout=settings.redraft_timeout_seconds + 30)
    try:
        try:
            result = await sdk.execute(settings.drafter_slug, drafter_message(record), act_as=acting_subject())
            status = str(result.status or "").lower()
            if status not in SUCCEEDED_RUN:
                raise RunUnreadable(f"the drafting run {status or 'did not finish'}")
            email = read_redraft(result.output, record["from_email"])
        except Exception as exc:  # noqa: BLE001
            why = str(exc) if isinstance(exc, RunUnreadable) else describe(exc)
            await fail(store, email_id, job, "redraft", f"Could not redraft from the note. {why}")
            return
        async with store.edit(email_id, job) as r:
            r["drafts"].append(new_draft(r, "redraft", result.execution_id, email, note=note))
            r.update(status="clarification", review="awaiting_review", redraft=None, error=None, error_step=None)
            add_event(r, "redrafted", "Clarification redrafted from the reviewer's note")
        await raise_review(sdk, store, email_id, job)
    except StaleJob:
        logger.info("%s: redraft dropped, the email was reset meanwhile", email_id)
    finally:
        await sdk.close()


def start_redraft(store: EmailStore, email_id: str, job: str) -> None:
    spawn(redraft(store, email_id, job), name=f"redraft:{email_id}")


# ── decisions made on Abenix's own pages ─────────────────────────────────


async def poll_once(store: EmailStore) -> None:
    pending = []
    for record in await store.list():
        approval = (current_draft(record) or {}).get("approval") or {}
        if record.get("review") == "awaiting_review" and approval.get("status") == "pending":
            pending.append((record["id"], approval["id"]))
    if not pending:
        return
    sdk = new_sdk(timeout=15)
    try:
        for email_id, approval_id in pending:
            try:
                approval = await sdk.approvals.get(approval_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("approval %s unreadable: %s", approval_id, describe(exc))
                continue
            status = approval.get("status")
            if status == "pending" and _past(approval.get("expires_at")):
                approval = {**approval, "status": "expired"}
            if approval.get("status") and approval["status"] != "pending":
                await apply_approval(store, email_id, approval)
    finally:
        await sdk.close()


async def poll_forever(store: EmailStore) -> None:
    while True:
        await asyncio.sleep(settings.approval_poll_seconds)
        try:
            await poll_once(store)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("approval poll failed")


def _past(when: str | None) -> bool:
    if not when:
        return False
    try:
        moment = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment < datetime.now(timezone.utc)


# ── edits ────────────────────────────────────────────────────────────────


def _editable(r: dict[str, Any], doing: str) -> dict[str, Any]:
    """The draft the reviewer may change, or ReviewRefused."""
    draft = current_draft(r)
    if r.get("review") != "awaiting_review" or not draft:
        raise ReviewRefused(f"only a draft awaiting review can be {doing}")
    if (draft.get("approval") or {}).get("status") == "signing":
        # The decision being signed already chose which text goes out.
        raise ReviewRefused(f"this draft's decision is being signed in Abenix, so it can't be {doing} now")
    return draft


async def save_edits(store: EmailStore, email_id: str, fields: dict[str, str]) -> None:
    skus = skus_in(fields)
    if skus:
        raise ReviewRefused(f"Take out {', '.join(skus)}. SKUs must not reach the customer", status=422)
    async with store.edit(email_id) as r:
        draft = _editable(r, "edited")
        edited = {"to": draft["ai"]["to"], **{f: fields[f] for f in DRAFT_FIELDS}}
        if all(edited[f] == draft["ai"][f] for f in DRAFT_FIELDS):
            if draft.get("edited"):
                add_event(r, "reverted", f"{settings.staff_name} reverted to the AI draft")
            draft["edited"] = None
            return
        if not draft.get("edited"):
            add_event(r, "edited", f"Edited by {settings.staff_name}")
        draft["edited"] = edited


async def revert_edits(store: EmailStore, email_id: str) -> None:
    async with store.edit(email_id) as r:
        draft = _editable(r, "reverted")
        if draft.get("edited"):
            draft["edited"] = None
            add_event(r, "reverted", f"{settings.staff_name} reverted to the AI draft")


# ── reset ────────────────────────────────────────────────────────────────


async def _deny_quietly(sdk: Abenix, approval_id: str) -> bool:
    try:
        await sdk.approvals.deny(approval_id, reason=reviewed_by("example reset, nothing sent"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("could not close approval %s on reset: %s", approval_id, describe(exc))
        return False


async def reset(store: EmailStore) -> dict[str, int]:
    """Clear every result. Open reviews are denied so Abenix's queue stays clean;
    runs still going are left to finish and their results ignored."""
    open_ids = await store.reset()
    if not open_ids:
        return {"approvals_closed": 0, "approvals_left_open": 0}
    sdk = new_sdk(timeout=15)
    try:
        closed = sum([await _deny_quietly(sdk, aid) for aid in open_ids])
    finally:
        await sdk.close()
    return {"approvals_closed": closed, "approvals_left_open": len(open_ids) - closed}
