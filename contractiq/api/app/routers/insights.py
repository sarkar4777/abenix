"""ContractIQ Insights — 9 agentic features powered by Abenix."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select, func as sqlfunc, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.routers.auth import get_contractiq_user

from app.models.contractiq_models import (
    ContractIQUser,
    ContractIQContract,
    ContractIQEvent,
    ContractIQCreditRisk,
    ContractIQBriefing,
    ContractIQRenewalPacket,
    ContractIQFMNotice,
    ContractIQReconciliation,
    ContractIQContractFamily,
    ContractIQClauseAnomaly,
    ContractIQVersionDiff,
    ContractIQStressTest,
    ContractIQHedgeRecommendation,
    ContractIQKycCheck,
    ContractIQClause,
    ContractIQForecastCurve,
    ContractIQValuation,
    ContractIQClauseBenchmark,
    InsightStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/insights", tags=["contractiq-insights"])


# ─── Helpers ────────────────────────────────────────────────────────────


def _parse_json_blob(text: str) -> dict | None:
    """Extract a JSON object from an LLM response — robust to:"""
    if not text:
        return None
    cleaned = text.strip()

    # 1. Direct
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Fenced — grab the FIRST complete fenced block; prefer ```json but
    #    accept plain ``` too
    fence = re.search(r"```(?:json)?\s*\n([\s\S]*?)```", cleaned)
    if fence:
        inner = fence.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
        # Try outermost { … } inside the fence
        fs, fe = inner.find("{"), inner.rfind("}")
        if fs != -1 and fe > fs:
            try:
                return json.loads(inner[fs : fe + 1])
            except json.JSONDecodeError:
                pass

    # 3. Outermost { … } span across the whole text
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 4. Brace-balance recovery on truncated output
    candidate = cleaned[start:] if start >= 0 else cleaned
    last_close = candidate.rfind("}")
    if last_close < 0:
        return None
    truncated = candidate[: last_close + 1]

    def _balanced_attempt(s: str) -> dict | None:
        depth_b = depth_k = 0
        in_str = esc = False
        for ch in s:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth_b += 1
            elif ch == "}":
                depth_b -= 1
            elif ch == "[":
                depth_k += 1
            elif ch == "]":
                depth_k -= 1
        fix = re.sub(r",\s*$", "", s) + "]" * max(0, depth_k) + "}" * max(0, depth_b)
        try:
            return json.loads(fix)
        except json.JSONDecodeError:
            last_comma = fix.rfind(",")
            if last_comma < 0:
                return None
            fix2 = fix[:last_comma] + "}" * max(0, depth_b) + "]" * max(0, depth_k)
            try:
                return json.loads(fix2)
            except json.JSONDecodeError:
                return None

    return _balanced_attempt(truncated)


def _format_parse_error(raw: str) -> str:
    head = (raw or "").strip()[:120].lower()
    refusal_markers = (
        "i am unable",
        "i'm unable",
        "i cannot",
        "i can't",
        "i am sorry",
        "as an ai",
    )
    if any(m in head for m in refusal_markers):
        return (
            "The agent declined to produce structured output (likely a "
            "live-data tool failure or model refusal). Try again or check "
            "tool credentials."
        )
    if not head:
        return "Empty response from agent."
    return f"Agent returned non-JSON output. Sample: {raw[:200].strip()}"


async def _build_portfolio_context(db: AsyncSession, user_id) -> str:
    """Build a text summary of the user's contract portfolio for agent context."""
    result = await db.execute(
        select(ContractIQContract).where(ContractIQContract.user_id == user_id)
    )
    contracts = result.scalars().all()
    if not contracts:
        return "No contracts in portfolio."

    lines = [f"Portfolio: {len(contracts)} contracts\n"]
    for c in contracts:
        summary = c.extraction_summary or {}
        lines.append(
            f"- {c.title} ({c.contract_type or '?'}) | Status: {c.status.value if hasattr(c.status, 'value') else c.status} | "
            f"Party A: {c.counterparty_a or '?'} → Party B: {c.counterparty_b or '?'} | "
            f"Capacity: {c.total_capacity_mw or '?'} MW | "
            f"Risk Score: {summary.get('overall_risk_score', '?')} | "
            f"Clauses: {summary.get('clauses_count', 0)} | Events: {summary.get('events_count', 0)} | "
            f"Effective: {c.effective_date or '?'} → Expiry: {c.expiry_date or '?'}"
        )

    # Add events from analyzed contracts
    for c in contracts:
        if (
            c.status
            and (c.status.value if hasattr(c.status, "value") else c.status)
            == "analyzed"
        ):
            events_result = await db.execute(
                select(ContractIQEvent)
                .where(ContractIQEvent.contract_id == c.id)
                .limit(10)
            )
            events = events_result.scalars().all()
            if events:
                lines.append(f"\nUpcoming events for {c.title}:")
                for ev in events:
                    lines.append(
                        f"  - {ev.event_date}: {ev.event_type} — {ev.description}"
                    )

    return "\n".join(lines)


async def _call_abenix(
    user: ContractIQUser,
    agent_slug: str,
    message: str,
    timeout: float = 300.0,
) -> tuple[dict | None, str, dict | None]:
    """Execute an Abenix agent via SDK with actAs delegation."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))
    from abenix_sdk import Abenix, ActingSubject

    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        raise RuntimeError("CONTRACTIQ_ABENIX_API_KEY not configured")

    subject = ActingSubject(
        subject_type="contractiq",
        subject_id=str(user.id),
        email=user.email,
        display_name=user.full_name,
    )
    async with Abenix(
        api_key=api_key, base_url=api_base, act_as=subject, timeout=timeout
    ) as forge:
        result = await forge.execute(agent_slug, message)
        raw_output = result.output or ""
        parsed = _parse_json_blob(raw_output)
        cost = result.cost or 0.0
        duration = result.duration_ms or 0
        tool_calls = len(result.tool_calls or [])
        input_tokens = result.input_tokens or 0
        output_tokens = result.output_tokens or 0

        if parsed is None and raw_output.strip():
            repair_msg = (
                "Your previous answer was not valid JSON. Re-emit the SAME "
                "information as a single JSON object that matches your "
                "agreed output schema. If you genuinely have no data, use "
                "the schema's unavailable / empty-state envelope. Do not "
                "include any prose, apology, or markdown fence.\n\n"
                "=== PREVIOUS ANSWER ===\n"
                f"{raw_output[:4000]}"
            )
            try:
                repair = await forge.execute(agent_slug, repair_msg)
                repair_raw = repair.output or ""
                parsed = _parse_json_blob(repair_raw)
                cost += repair.cost or 0.0
                duration += repair.duration_ms or 0
                tool_calls += len(repair.tool_calls or [])
                input_tokens += repair.input_tokens or 0
                output_tokens += repair.output_tokens or 0
                if parsed is not None:
                    raw_output = repair_raw
            except Exception as e:
                logger.warning("JSON repair pass failed for %s: %s", agent_slug, e)

        meta = {
            "duration_ms": duration,
            "cost": cost,
            "model": result.model,
            "tool_calls": tool_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        return parsed, raw_output, meta


# 1. Daily Executive Briefing


@router.post("/briefing/generate")
async def generate_briefing(
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Generate today's executive briefing."""
    body = body or {}
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    row = ContractIQBriefing(
        user_id=user.id,
        for_date=today,
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Build portfolio context so the agent has real data regardless of tool access
    portfolio_ctx = await _build_portfolio_context(db, user.id)

    try:
        briefing_prompt = (
            body.get("focus")
            or "Generate today's executive briefing for my contract portfolio."
        ) + f"\n\n=== PORTFOLIO DATA ===\n{portfolio_ctx}"
        parsed, raw, meta = await _call_abenix(
            user,
            "contractiq-executive-briefing",
            briefing_prompt,
        )
        if not parsed:
            row.status = InsightStatus.FAILED.value
            row.error_message = _format_parse_error(raw)
        else:
            row.headline = parsed.get("headline", "")[:500]
            row.body_markdown = parsed.get("body_markdown", "")
            row.metrics = parsed.get("metrics") or {}
            row.top_actions = parsed.get("top_actions") or []
            row.status = InsightStatus.COMPLETED.value
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
            row.duration_ms = meta.get("duration_ms")
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Briefing generation failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_briefing(row))


@router.get("/briefing/today")
async def get_today_briefing(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get the most recent briefing for today (or null)."""
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    row = (
        await db.execute(
            select(ContractIQBriefing)
            .where(
                ContractIQBriefing.user_id == user.id,
                ContractIQBriefing.for_date >= today,
            )
            .order_by(ContractIQBriefing.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return success(_serialize_briefing(row) if row else None)


@router.get("/briefing/history")
async def list_briefings(
    limit: int = Query(20, ge=1, le=100),
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQBriefing)
                .where(ContractIQBriefing.user_id == user.id)
                .order_by(ContractIQBriefing.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_briefing(r) for r in rows])


def _serialize_briefing(r: ContractIQBriefing) -> dict:
    return {
        "id": str(r.id),
        "for_date": r.for_date.isoformat() if r.for_date else None,
        "status": r.status,
        "headline": r.headline,
        "body_markdown": r.body_markdown,
        "metrics": r.metrics,
        "top_actions": r.top_actions,
        "cost_usd": r.cost_usd,
        "duration_ms": r.duration_ms,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# 2. Renewal Negotiation Copilot


@router.get("/renewals/upcoming")
async def list_upcoming_renewals(
    days: int = Query(180, ge=1, le=730),
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List contracts whose expiry_date is within the next N days."""
    cutoff = datetime.now(timezone.utc) + timedelta(days=days)
    q = (
        select(ContractIQContract)
        .where(
            ContractIQContract.user_id == user.id,
            ContractIQContract.expiry_date.is_not(None),
            ContractIQContract.expiry_date <= cutoff,
            ContractIQContract.expiry_date >= datetime.now(timezone.utc),
        )
        .order_by(ContractIQContract.expiry_date.asc())
    )
    rows = (await db.execute(q)).scalars().all()
    return success(
        [
            {
                "id": str(c.id),
                "title": c.title,
                "contract_type": c.contract_type.value,
                "counterparty_a": c.counterparty_a,
                "counterparty_b": c.counterparty_b,
                "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
                "days_to_expiry": (
                    (c.expiry_date - datetime.now(timezone.utc)).days
                    if c.expiry_date
                    else None
                ),
                "risk_score": c.risk_score,
                "total_capacity_mw": c.total_capacity_mw,
            }
            for c in rows
        ]
    )


@router.post("/renewals/{contract_id}/generate")
async def generate_renewal_packet(
    contract_id: uuid.UUID,
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    body = body or {}
    contract = (
        await db.execute(
            select(ContractIQContract).where(
                ContractIQContract.id == contract_id,
                ContractIQContract.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    days_to_expiry = (
        (contract.expiry_date - datetime.now(timezone.utc)).days
        if contract.expiry_date
        else None
    )

    row = ContractIQRenewalPacket(
        user_id=user.id,
        contract_id=contract_id,
        status=InsightStatus.RUNNING.value,
        days_to_expiry=days_to_expiry,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    msg = (
        f"Build a complete renewal negotiation packet for contract {contract_id} "
        f"(title: '{contract.title}', counterparty: {contract.counterparty_a}/{contract.counterparty_b}). "
        f"Days to expiry: {days_to_expiry}. {body.get('focus','')}"
    )
    try:
        parsed, raw, meta = await _call_abenix(user, "contractiq-renewal-copilot", msg)
        if parsed:
            row.market_context = parsed.get("market_context") or {}
            row.historical_pricing = parsed.get("historical_pricing") or {}
            row.counterparty_intel = parsed.get("counterparty_intel") or {}
            row.term_sheet = parsed.get("term_sheet") or {}
            row.npv_uplift = parsed.get("npv_uplift")
            row.full_packet_markdown = parsed.get("full_packet_markdown") or ""
            row.status = InsightStatus.COMPLETED.value
        else:
            row.status = InsightStatus.FAILED.value
            row.error_message = _format_parse_error(raw)
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Renewal packet failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_renewal(row))


@router.get("/renewals")
async def list_renewal_packets(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQRenewalPacket)
                .where(ContractIQRenewalPacket.user_id == user.id)
                .order_by(ContractIQRenewalPacket.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_renewal(r) for r in rows])


@router.get("/renewals/{packet_id}")
async def get_renewal_packet(
    packet_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ContractIQRenewalPacket).where(
                ContractIQRenewalPacket.id == packet_id,
                ContractIQRenewalPacket.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("Renewal packet not found", 404)
    return success(_serialize_renewal(row))


def _serialize_renewal(r: ContractIQRenewalPacket) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id),
        "status": r.status,
        "days_to_expiry": r.days_to_expiry,
        "market_context": r.market_context,
        "historical_pricing": r.historical_pricing,
        "counterparty_intel": r.counterparty_intel,
        "term_sheet": r.term_sheet,
        "npv_uplift": r.npv_uplift,
        "full_packet_markdown": r.full_packet_markdown,
        "cost_usd": r.cost_usd,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# 3. Force Majeure Monitor


@router.post("/force-majeure/scan")
async def run_fm_scan(
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    body = body or {}
    # Pre-flight: if the user has no contracts, the agent has nothing to scan.
    # Return a structured 200 instead of letting the agent guess and emit prose.
    contract_count = (
        await db.execute(
            select(sqlfunc.count())
            .select_from(ContractIQContract)
            .where(
                ContractIQContract.user_id == user.id,
            )
        )
    ).scalar() or 0
    if contract_count == 0:
        return success(
            {
                "scan_summary": "No contracts in portfolio — upload a contract first to enable force majeure monitoring.",
                "scanned_contracts": 0,
                "notices_created": 0,
                "notices": [],
                "warning": "empty_portfolio",
            }
        )

    try:
        parsed, raw, meta = await _call_abenix(
            user,
            "contractiq-force-majeure-monitor",
            body.get("focus")
            or "Run a full force majeure scan across all my contracts.",
        )
    except Exception as e:
        logger.exception("FM scan failed")
        return error(f"Force majeure scan failed: {e}", 503)

    if not parsed:
        # Agent returned prose instead of JSON. Surface as a structured 200
        # with the raw text so the UI can show a useful message rather than a
        # blank 500.
        logger.warning(
            "FM scan: agent returned non-JSON output (%d chars)", len(raw or "")
        )
        return success(
            {
                "scan_summary": (raw or "Agent returned no parseable output")[:1000],
                "scanned_contracts": contract_count,
                "notices_created": 0,
                "notices": [],
                "warning": "agent_output_not_parseable",
            }
        )

    notices_created: list[dict] = []
    for n in parsed.get("notices", []):
        try:
            cid = uuid.UUID(n.get("contract_id", ""))
        except (ValueError, TypeError):
            continue
        # verify ownership
        owns = (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQContract)
                .where(
                    ContractIQContract.id == cid,
                    ContractIQContract.user_id == user.id,
                )
            )
        ).scalar() or 0
        if not owns:
            continue
        deadline = None
        if n.get("deadline_to_notify_iso"):
            try:
                deadline = datetime.fromisoformat(
                    n["deadline_to_notify_iso"].replace("Z", "+00:00")
                )
            except ValueError:
                pass
        row = ContractIQFMNotice(
            user_id=user.id,
            contract_id=cid,
            trigger_type=(n.get("trigger_type") or "regulation")[:100],
            trigger_description=n.get("trigger_description", ""),
            severity=(n.get("severity") or "warning")[:20],
            applicable_clauses=n.get("applicable_clauses") or [],
            financial_impact_usd=n.get("financial_impact_usd"),
            draft_notice=n.get("draft_notice") or "",
            deadline_to_notify=deadline,
            status="awaiting_review",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        notices_created.append(_serialize_fm(row))

    return success(
        {
            "scan_summary": parsed.get("scan_summary", ""),
            "scanned_contracts": parsed.get("scanned_contracts", 0),
            "notices_created": len(notices_created),
            "notices": notices_created,
        }
    )


@router.get("/force-majeure/notices")
async def list_fm_notices(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQFMNotice)
                .where(ContractIQFMNotice.user_id == user.id)
                .order_by(ContractIQFMNotice.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_fm(r) for r in rows])


@router.post("/force-majeure/notices/{notice_id}/review")
async def review_fm_notice(
    notice_id: uuid.UUID,
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """HITL gate: approve, send, or dismiss a notice."""
    row = (
        await db.execute(
            select(ContractIQFMNotice).where(
                ContractIQFMNotice.id == notice_id,
                ContractIQFMNotice.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("Notice not found", 404)
    new_status = body.get("status", "")
    if new_status not in ("draft", "awaiting_review", "sent", "dismissed"):
        return error("Invalid status", 400)
    row.status = new_status
    row.reviewed_by = user.id
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    return success(_serialize_fm(row))


def _serialize_fm(r: ContractIQFMNotice) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id),
        "trigger_type": r.trigger_type,
        "trigger_description": r.trigger_description,
        "severity": r.severity,
        "applicable_clauses": r.applicable_clauses,
        "financial_impact_usd": r.financial_impact_usd,
        "draft_notice": r.draft_notice,
        "deadline_to_notify": (
            r.deadline_to_notify.isoformat() if r.deadline_to_notify else None
        ),
        "status": r.status,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# 4. Settlement Reconciliation


@router.post("/reconciliation/upload")
async def reconcile_invoice(
    contract_id: str = Form(...),
    invoice_period: str = Form(""),
    invoice_amount: float = Form(...),
    file: UploadFile | None = File(None),
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload an invoice (file optional) and reconcile it against the contract."""
    try:
        cid = uuid.UUID(contract_id)
    except ValueError:
        return error("Invalid contract_id", 400)

    contract = (
        await db.execute(
            select(ContractIQContract).where(
                ContractIQContract.id == cid,
                ContractIQContract.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    # Optional file content (text-only for v1)
    invoice_text = ""
    filename = None
    if file:
        filename = file.filename
        content = await file.read()
        if file.content_type and "text" in file.content_type:
            invoice_text = content.decode("utf-8", errors="replace")[:50000]

    row = ContractIQReconciliation(
        user_id=user.id,
        contract_id=cid,
        invoice_filename=filename,
        invoice_period=invoice_period,
        invoice_amount=invoice_amount,
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    msg = (
        f"Reconcile this invoice against contract {cid} ('{contract.title}'). "
        f"Invoice period: {invoice_period}. Invoice total: {invoice_amount}.\n\n"
        f"Invoice text (if provided):\n{invoice_text or 'No file content provided — use the contract pricing fields to compute the expected amount and compare.'}"
    )
    try:
        parsed, raw, meta = await _call_abenix(
            user, "contractiq-settlement-reconciler", msg
        )
        if parsed:
            row.expected_amount = parsed.get("expected_amount")
            row.variance_amount = parsed.get("variance_amount")
            row.variance_pct = parsed.get("variance_pct")
            row.line_items = parsed.get("line_items") or []
            row.discrepancies = parsed.get("discrepancies") or []
            row.dispute_letter = parsed.get("dispute_letter")
            row.status = InsightStatus.COMPLETED.value
        else:
            row.status = InsightStatus.FAILED.value
            row.error_message = f"Could not parse response. Raw: {raw[:500]}"
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Reconciliation failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_recon(row))


@router.get("/reconciliation")
async def list_reconciliations(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQReconciliation)
                .where(ContractIQReconciliation.user_id == user.id)
                .order_by(ContractIQReconciliation.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_recon(r) for r in rows])


def _serialize_recon(r: ContractIQReconciliation) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id) if r.contract_id else None,
        "invoice_filename": r.invoice_filename,
        "invoice_period": r.invoice_period,
        "invoice_amount": float(r.invoice_amount) if r.invoice_amount else None,
        "expected_amount": float(r.expected_amount) if r.expected_amount else None,
        "variance_amount": float(r.variance_amount) if r.variance_amount else None,
        "variance_pct": r.variance_pct,
        "line_items": r.line_items,
        "discrepancies": r.discrepancies,
        "dispute_letter": r.dispute_letter,
        "status": r.status,
        "cost_usd": r.cost_usd,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# 5. Contract Families (data model only — no agent)


@router.get("/families")
async def list_families(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQContractFamily)
                .where(ContractIQContractFamily.user_id == user.id)
                .order_by(ContractIQContractFamily.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_family(r) for r in rows])


@router.post("/families")
async def create_family(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    family_name = (body.get("family_name") or "").strip()
    if not family_name:
        return error("family_name is required", 400)
    member_ids = body.get("member_contract_ids") or []
    master_id = body.get("master_contract_id")

    row = ContractIQContractFamily(
        user_id=user.id,
        family_name=family_name[:500],
        description=body.get("description"),
        master_contract_id=uuid.UUID(master_id) if master_id else None,
        member_contract_ids=member_ids,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return success(_serialize_family(row), status_code=201)


@router.put("/families/{family_id}")
async def update_family(
    family_id: uuid.UUID,
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ContractIQContractFamily).where(
                ContractIQContractFamily.id == family_id,
                ContractIQContractFamily.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("Family not found", 404)
    if "family_name" in body:
        row.family_name = body["family_name"][:500]
    if "description" in body:
        row.description = body["description"]
    if "member_contract_ids" in body:
        row.member_contract_ids = body["member_contract_ids"]
    if "master_contract_id" in body:
        row.master_contract_id = (
            uuid.UUID(body["master_contract_id"])
            if body["master_contract_id"]
            else None
        )
    await db.commit()
    await db.refresh(row)
    return success(_serialize_family(row))


@router.delete("/families/{family_id}")
async def delete_family(
    family_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ContractIQContractFamily).where(
                ContractIQContractFamily.id == family_id,
                ContractIQContractFamily.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("Family not found", 404)
    await db.delete(row)
    await db.commit()
    return success({"deleted": True})


def _serialize_family(r: ContractIQContractFamily) -> dict:
    return {
        "id": str(r.id),
        "family_name": r.family_name,
        "description": r.description,
        "master_contract_id": (
            str(r.master_contract_id) if r.master_contract_id else None
        ),
        "member_contract_ids": r.member_contract_ids or [],
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# 6. Clause Anomaly Detector


@router.post("/anomalies/scan")
async def scan_clause_anomalies(
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    body = body or {}
    # Pre-flight: anomaly detection needs at least 2 analyzed contracts with
    # extracted clauses to have any benchmark cohort. Return a structured 200
    # with a clear message instead of letting the agent invent results.
    clause_count = (
        await db.execute(
            select(sqlfunc.count())
            .select_from(ContractIQClause)
            .join(
                ContractIQContract,
                ContractIQClause.contract_id == ContractIQContract.id,
            )
            .where(ContractIQContract.user_id == user.id)
        )
    ).scalar() or 0
    if clause_count < 5:
        return success(
            {
                "scanned_clauses": clause_count,
                "anomalies_found": 0,
                "anomalies_persisted": 0,
                "anomalies": [],
                "warning": "insufficient_clauses",
                "scan_summary": (
                    f"Need at least 5 extracted clauses to detect anomalies "
                    f"(found {clause_count}). Upload and extract more contracts first."
                ),
            }
        )

    try:
        parsed, raw, meta = await _call_abenix(
            user,
            "contractiq-clause-anomaly",
            body.get("focus")
            or "Scan for clause anomalies across my entire portfolio.",
        )
    except Exception as e:
        logger.exception("Anomaly scan failed")
        return error(f"Scan failed: {e}", 503)

    if not parsed:
        # Agent returned prose; degrade to a structured 200 instead of an
        # opaque 500 so the UI shows the message and the user can retry.
        logger.warning(
            "Anomaly scan: agent returned non-JSON output (%d chars)", len(raw or "")
        )
        return success(
            {
                "scanned_clauses": clause_count,
                "anomalies_found": 0,
                "anomalies_persisted": 0,
                "anomalies": [],
                "warning": "agent_output_not_parseable",
                "scan_summary": (raw or "Agent returned no parseable output")[:1000],
            }
        )

    created: list[dict] = []
    for a in parsed.get("anomalies", []):
        try:
            clause_id = uuid.UUID(a.get("clause_id", ""))
            contract_id = uuid.UUID(a.get("contract_id", ""))
        except (ValueError, TypeError):
            continue
        # Verify both FKs before insert — agents sometimes hallucinate IDs.
        owns = (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQContract)
                .where(
                    ContractIQContract.id == contract_id,
                    ContractIQContract.user_id == user.id,
                )
            )
        ).scalar() or 0
        if not owns:
            continue
        # Clause FK check — skip hallucinated ids so the whole scan doesn't fail.
        clause_ok = (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQClause)
                .where(
                    ContractIQClause.id == clause_id,
                    ContractIQClause.contract_id == contract_id,
                )
            )
        ).scalar() or 0
        if not clause_ok:
            continue
        row = ContractIQClauseAnomaly(
            user_id=user.id,
            clause_id=clause_id,
            contract_id=contract_id,
            anomaly_score=float(a.get("anomaly_score", 0.0)),
            severity=(a.get("severity") or "info")[:20],
            explanation=a.get("explanation", ""),
            benchmark_summary=a.get("benchmark") or {},
        )
        db.add(row)
        try:
            await db.commit()
            await db.refresh(row)
            created.append(_serialize_anomaly(row))
        except Exception:
            await db.rollback()
            continue

    return success(
        {
            "scanned_clauses": parsed.get("scanned_clauses", 0),
            "anomalies_found": parsed.get("anomalies_found", 0),
            "anomalies_persisted": len(created),
            "anomalies": created,
        }
    )


@router.get("/anomalies")
async def list_anomalies(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQClauseAnomaly)
                .where(
                    ContractIQClauseAnomaly.user_id == user.id,
                    ContractIQClauseAnomaly.is_dismissed.is_(False),
                )
                .order_by(ContractIQClauseAnomaly.anomaly_score.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_anomaly(r) for r in rows])


@router.post("/anomalies/{anomaly_id}/dismiss")
async def dismiss_anomaly(
    anomaly_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ContractIQClauseAnomaly).where(
                ContractIQClauseAnomaly.id == anomaly_id,
                ContractIQClauseAnomaly.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("Anomaly not found", 404)
    row.is_dismissed = True
    await db.commit()
    return success({"dismissed": True})


def _serialize_anomaly(r: ContractIQClauseAnomaly) -> dict:
    return {
        "id": str(r.id),
        "clause_id": str(r.clause_id),
        "contract_id": str(r.contract_id),
        "anomaly_score": r.anomaly_score,
        "severity": r.severity,
        "explanation": r.explanation,
        "benchmark_summary": r.benchmark_summary,
        "is_dismissed": r.is_dismissed,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# 7. Version Diff


@router.post("/version-diff")
async def run_version_diff(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    base_id_str = body.get("base_contract_id")
    new_id_str = body.get("new_contract_id")
    if not base_id_str or not new_id_str:
        return error("base_contract_id and new_contract_id are required", 400)
    try:
        base_id = uuid.UUID(base_id_str)
        new_id = uuid.UUID(new_id_str)
    except ValueError:
        return error("Invalid UUID(s)", 400)

    # Verify ownership of both
    owned = (
        await db.execute(
            select(sqlfunc.count())
            .select_from(ContractIQContract)
            .where(
                ContractIQContract.id.in_([base_id, new_id]),
                ContractIQContract.user_id == user.id,
            )
        )
    ).scalar() or 0
    if owned < 2:
        return error("One or both contracts not found", 404)

    row = ContractIQVersionDiff(
        user_id=user.id,
        base_contract_id=base_id,
        new_contract_id=new_id,
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    msg = f"Compare contracts: BASE={base_id} vs NEW={new_id}. Identify all material changes."
    try:
        parsed, raw, meta = await _call_abenix(user, "contractiq-version-diff", msg)
        if parsed:
            row.summary = parsed.get("summary")
            row.changes = parsed.get("changes") or []
            row.overall_impact = parsed.get("overall_impact")
            row.status = InsightStatus.COMPLETED.value
        else:
            row.status = InsightStatus.FAILED.value
            row.error_message = f"Could not parse response. Raw: {raw[:500]}"
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Version diff failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_diff(row))


@router.get("/version-diff")
async def list_version_diffs(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQVersionDiff)
                .where(ContractIQVersionDiff.user_id == user.id)
                .order_by(ContractIQVersionDiff.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_diff(r) for r in rows])


def _serialize_diff(r: ContractIQVersionDiff) -> dict:
    return {
        "id": str(r.id),
        "base_contract_id": str(r.base_contract_id),
        "new_contract_id": str(r.new_contract_id),
        "status": r.status,
        "summary": r.summary,
        "changes": r.changes,
        "overall_impact": r.overall_impact,
        "cost_usd": r.cost_usd,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# 8. Stress Test Simulator


@router.post("/stress-test")
async def run_stress_test(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    contract_id_str = body.get("contract_id")
    scope = body.get("scope", "single")
    iterations = int(body.get("iterations", 1000))
    iterations = max(100, min(iterations, 10000))
    scenario_params = body.get("scenario_params") or {
        "power_price_shock_pct": [-30, 30],
        "fx_shock_pct": [-15, 15],
    }
    name = body.get("name") or "Stress Test"

    contract_id = None
    if contract_id_str:
        try:
            contract_id = uuid.UUID(contract_id_str)
        except ValueError:
            return error("Invalid contract_id", 400)
        owns = (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQContract)
                .where(
                    ContractIQContract.id == contract_id,
                    ContractIQContract.user_id == user.id,
                )
            )
        ).scalar() or 0
        if not owns:
            return error("Contract not found", 404)

    row = ContractIQStressTest(
        user_id=user.id,
        contract_id=contract_id,
        scope=scope,
        name=name[:500],
        scenario_params=scenario_params,
        iterations=iterations,
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    msg = (
        f"Run a Monte Carlo stress test. Scope={scope}. "
        f"{'Contract='+str(contract_id) if contract_id else 'Use entire portfolio.'} "
        f"Iterations={iterations}. Scenario params={json.dumps(scenario_params)}."
    )
    try:
        parsed, raw, meta = await _call_abenix(
            user, "contractiq-stress-test", msg, timeout=600.0
        )
        if parsed:
            row.base_npv = parsed.get("base_npv")
            row.p5_npv = parsed.get("p5_npv")
            row.p50_npv = parsed.get("p50_npv")
            row.p95_npv = parsed.get("p95_npv")
            row.var_95 = parsed.get("var_95")
            row.expected_shortfall = parsed.get("expected_shortfall")
            row.distribution = parsed.get("distribution") or []
            row.worst_scenarios = parsed.get("worst_scenarios") or []
            row.summary_markdown = parsed.get("summary_markdown")
            row.status = InsightStatus.COMPLETED.value
        else:
            row.status = InsightStatus.FAILED.value
            row.error_message = f"Could not parse response. Raw: {raw[:500]}"
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Stress test failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_stress(row))


@router.get("/stress-test")
async def list_stress_tests(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQStressTest)
                .where(ContractIQStressTest.user_id == user.id)
                .order_by(ContractIQStressTest.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_stress(r) for r in rows])


@router.get("/stress-test/{test_id}")
async def get_stress_test(
    test_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ContractIQStressTest).where(
                ContractIQStressTest.id == test_id,
                ContractIQStressTest.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("Stress test not found", 404)
    return success(_serialize_stress(row))


def _serialize_stress(r: ContractIQStressTest) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id) if r.contract_id else None,
        "scope": r.scope,
        "name": r.name,
        "scenario_params": r.scenario_params,
        "iterations": r.iterations,
        "status": r.status,
        "base_npv": r.base_npv,
        "p5_npv": r.p5_npv,
        "p50_npv": r.p50_npv,
        "p95_npv": r.p95_npv,
        "var_95": r.var_95,
        "expected_shortfall": r.expected_shortfall,
        "distribution": r.distribution,
        "worst_scenarios": r.worst_scenarios,
        "summary_markdown": r.summary_markdown,
        "cost_usd": r.cost_usd,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# 9. Hedge Recommendations


@router.post("/hedge/{contract_id}/recommend")
async def recommend_hedges(
    contract_id: uuid.UUID,
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    body = body or {}
    contract = (
        await db.execute(
            select(ContractIQContract).where(
                ContractIQContract.id == contract_id,
                ContractIQContract.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    risk_tolerance = body.get("risk_tolerance", "medium")
    row = ContractIQHedgeRecommendation(
        user_id=user.id,
        contract_id=contract_id,
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    msg = (
        f"Recommend hedges for contract {contract_id} ('{contract.title}'). "
        f"Risk tolerance: {risk_tolerance}. "
        f"Currency: {contract.currency or 'USD'}. Capacity: {contract.total_capacity_mw} MW."
    )
    try:
        parsed, raw, meta = await _call_abenix(user, "contractiq-hedge-advisor", msg)
        if parsed:
            row.exposure_type = parsed.get("exposure_type")
            row.notional_amount = parsed.get("notional_amount")
            row.notional_currency = parsed.get("notional_currency")
            row.tenor_months = parsed.get("tenor_months")
            row.structures = parsed.get("structures") or []
            row.recommended_structure = parsed.get("recommended_structure")
            row.rationale = parsed.get("rationale")
            row.status = InsightStatus.COMPLETED.value
        else:
            row.status = InsightStatus.FAILED.value
            row.error_message = f"Could not parse response. Raw: {raw[:500]}"
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Hedge recommendation failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_hedge(row))


@router.get("/hedge")
async def list_hedge_recommendations(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQHedgeRecommendation)
                .where(ContractIQHedgeRecommendation.user_id == user.id)
                .order_by(ContractIQHedgeRecommendation.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_hedge(r) for r in rows])


def _serialize_hedge(r: ContractIQHedgeRecommendation) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id),
        "status": r.status,
        "exposure_type": r.exposure_type,
        "notional_amount": r.notional_amount,
        "notional_currency": r.notional_currency,
        "tenor_months": r.tenor_months,
        "structures": r.structures,
        "recommended_structure": r.recommended_structure,
        "rationale": r.rationale,
        "cost_usd": r.cost_usd,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# Market Monitor Trigger — bridges the market page to the pipeline


@router.post("/market-monitor/run")
async def run_market_monitor(
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Fire the contractiq-market-monitor pipeline via the Abenix SDK."""
    body = body or {}
    try:
        parsed, raw, meta = await _call_abenix(
            user,
            "contractiq-market-monitor",
            body.get("focus") or "Run full market monitor scan against the portfolio.",
            timeout=600.0,
        )
    except Exception as e:
        logger.exception("Market monitor run failed")
        return error(f"Market monitor failed: {e}", 503)

    # The pipeline writes alerts directly via database_writer — we just return
    # the final summary + meta so the UI can show how much it cost and how long
    # it took.
    return success(
        {
            "summary": (raw or "")[:2000] if not parsed else parsed.get("summary", ""),
            "alerts_created": parsed.get("alerts_created") if parsed else None,
            "duration_ms": (meta or {}).get("duration_ms"),
            "cost_usd": (meta or {}).get("cost"),
        }
    )


# Hub overview — counts for the Insights Hub landing page


@router.get("/overview")
async def get_overview(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    next_180 = datetime.now(timezone.utc) + timedelta(days=180)

    counts = {
        "briefings_today": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQBriefing)
                .where(
                    ContractIQBriefing.user_id == user.id,
                    ContractIQBriefing.for_date >= today,
                )
            )
        ).scalar()
        or 0,
        "renewals_upcoming": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQContract)
                .where(
                    ContractIQContract.user_id == user.id,
                    ContractIQContract.expiry_date.is_not(None),
                    ContractIQContract.expiry_date <= next_180,
                    ContractIQContract.expiry_date >= datetime.now(timezone.utc),
                )
            )
        ).scalar()
        or 0,
        "fm_notices_pending": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQFMNotice)
                .where(
                    ContractIQFMNotice.user_id == user.id,
                    ContractIQFMNotice.status == "awaiting_review",
                )
            )
        ).scalar()
        or 0,
        "reconciliations_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQReconciliation)
                .where(ContractIQReconciliation.user_id == user.id)
            )
        ).scalar()
        or 0,
        "families_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQContractFamily)
                .where(ContractIQContractFamily.user_id == user.id)
            )
        ).scalar()
        or 0,
        "anomalies_active": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQClauseAnomaly)
                .where(
                    ContractIQClauseAnomaly.user_id == user.id,
                    ContractIQClauseAnomaly.is_dismissed.is_(False),
                )
            )
        ).scalar()
        or 0,
        "diffs_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQVersionDiff)
                .where(ContractIQVersionDiff.user_id == user.id)
            )
        ).scalar()
        or 0,
        "stress_tests_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQStressTest)
                .where(ContractIQStressTest.user_id == user.id)
            )
        ).scalar()
        or 0,
        "hedge_recs_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQHedgeRecommendation)
                .where(ContractIQHedgeRecommendation.user_id == user.id)
            )
        ).scalar()
        or 0,
        "credit_risks_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQCreditRisk)
                .where(ContractIQCreditRisk.user_id == user.id)
            )
        ).scalar()
        or 0,
        "valuations_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQValuation)
                .where(ContractIQValuation.user_id == user.id)
            )
        ).scalar()
        or 0,
        "forecast_curves_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQForecastCurve)
                .where(ContractIQForecastCurve.user_id == user.id)
            )
        ).scalar()
        or 0,
        "benchmarks_total": (
            await db.execute(
                select(sqlfunc.count())
                .select_from(ContractIQClauseBenchmark)
                .where(ContractIQClauseBenchmark.user_id == user.id)
            )
        ).scalar()
        or 0,
    }
    return success(counts)


# 10. COUNTERPARTY CREDIT RISK


def _serialize_credit_risk(r: ContractIQCreditRisk) -> dict:
    return {
        "id": str(r.id),
        "counterparty_name": r.counterparty_name,
        "ticker": r.ticker,
        "sector": r.sector,
        "credit_rating": r.credit_rating,
        "credit_score": r.credit_score,
        "altman_z_score": r.altman_z_score,
        "z_score_zone": r.z_score_zone,
        "probability_of_default_pct": r.probability_of_default_pct,
        "risk_level": r.risk_level,
        "key_ratios": r.key_ratios,
        "financial_highlights": r.financial_highlights,
        "risk_factors": r.risk_factors,
        "mitigating_factors": r.mitigating_factors,
        "credit_mitigation_recommendations": r.credit_mitigation_recommendations,
        "monitoring_triggers": r.monitoring_triggers,
        "narrative": r.narrative,
        "status": r.status,
        "error_message": r.error_message,
        "cost_usd": r.cost_usd,
        "assessed_at": r.assessed_at.isoformat() if r.assessed_at else None,
    }


@router.get("/credit-risk")
async def list_credit_risks(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List all credit risk assessments for this user."""
    result = await db.execute(
        select(ContractIQCreditRisk)
        .where(ContractIQCreditRisk.user_id == user.id)
        .order_by(ContractIQCreditRisk.assessed_at.desc())
    )
    rows = result.scalars().all()
    return success([_serialize_credit_risk(r) for r in rows])


@router.get("/credit-risk/portfolio")
async def get_portfolio_credit_summary(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a portfolio-level credit risk summary based on contract counterparties."""
    # Get unique counterparties from analyzed contracts
    contracts = (
        (
            await db.execute(
                select(ContractIQContract).where(ContractIQContract.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )

    counterparties = set()
    for c in contracts:
        if c.counterparty_a:
            counterparties.add(c.counterparty_a)
        if c.counterparty_b:
            counterparties.add(c.counterparty_b)

    # Get latest assessment for each counterparty
    assessments = []
    for name in counterparties:
        result = await db.execute(
            select(ContractIQCreditRisk)
            .where(
                ContractIQCreditRisk.user_id == user.id,
                ContractIQCreditRisk.counterparty_name == name,
                ContractIQCreditRisk.status == InsightStatus.COMPLETED.value,
            )
            .order_by(ContractIQCreditRisk.assessed_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            assessments.append(_serialize_credit_risk(row))

    return success(
        {
            "counterparties": list(counterparties),
            "assessments": assessments,
            "total_counterparties": len(counterparties),
            "assessed_count": len(assessments),
            "unassessed": list(
                counterparties - {a["counterparty_name"] for a in assessments}
            ),
        }
    )


@router.post("/credit-risk/assess")
async def assess_credit_risk(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run credit risk assessment for a counterparty."""
    counterparty_name = body.get("counterparty_name", "").strip()
    if not counterparty_name:
        return error("counterparty_name is required", 400)

    row = ContractIQCreditRisk(
        user_id=user.id,
        counterparty_name=counterparty_name,
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Build context from contracts involving this counterparty
    contracts = (
        (
            await db.execute(
                select(ContractIQContract).where(
                    ContractIQContract.user_id == user.id,
                    or_(
                        ContractIQContract.counterparty_a.ilike(
                            f"%{counterparty_name}%"
                        ),
                        ContractIQContract.counterparty_b.ilike(
                            f"%{counterparty_name}%"
                        ),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    contract_context = ""
    if contracts:
        contract_context = "\n\nRelated contracts in portfolio:\n"
        for c in contracts:
            contract_context += (
                f"- {c.title} ({c.contract_type}): {c.counterparty_a} → {c.counterparty_b}, "
                f"Capacity: {c.total_capacity_mw} MW, Value: {c.contract_value}, "
                f"Effective: {c.effective_date} → {c.expiry_date}\n"
            )

    try:
        parsed, raw, meta = await _call_abenix(
            user,
            "counterparty-credit-risk",
            f"Assess the counterparty credit risk for: {counterparty_name}{contract_context}",
            timeout=300.0,
        )
        if not parsed:
            row.status = InsightStatus.FAILED.value
            row.error_message = f"Could not parse agent response. Raw: {raw[:500]}"
        else:

            def _cap(v, n):
                return v[:n] if isinstance(v, str) else v

            def _numeric(v):
                """LLMs sometimes write 'N/A' in float fields. Coerce to None."""
                if isinstance(v, (int, float)):
                    return v
                if isinstance(v, str):
                    try:
                        return float(v)
                    except ValueError:
                        return None
                return None

            row.ticker = _cap(parsed.get("ticker"), 40)
            row.sector = _cap(parsed.get("sector"), 255)
            row.credit_rating = _cap(parsed.get("credit_rating"), 80)
            row.credit_score = _numeric(parsed.get("credit_score"))
            if row.credit_score is not None:
                row.credit_score = int(row.credit_score)
            row.altman_z_score = _numeric(parsed.get("altman_z_score"))
            row.z_score_zone = _cap(parsed.get("z_score_zone"), 40)
            row.probability_of_default_pct = _numeric(
                parsed.get("probability_of_default_pct")
            )
            row.risk_level = _cap(parsed.get("risk_level"), 40)
            row.key_ratios = parsed.get("key_ratios")
            row.financial_highlights = parsed.get("financial_highlights")
            row.risk_factors = parsed.get("risk_factors")
            row.mitigating_factors = parsed.get("mitigating_factors")
            row.credit_mitigation_recommendations = parsed.get(
                "credit_mitigation_recommendations"
            )
            row.monitoring_triggers = parsed.get("monitoring_triggers")
            row.narrative = parsed.get("narrative")
            row.status = InsightStatus.COMPLETED.value
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Credit risk assessment failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_credit_risk(row))


@router.post("/credit-risk/assess-all")
async def assess_all_counterparties(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Assess credit risk for ALL unique counterparties in the portfolio."""
    contracts = (
        (
            await db.execute(
                select(ContractIQContract).where(ContractIQContract.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )

    counterparties = set()
    for c in contracts:
        if c.counterparty_a:
            counterparties.add(c.counterparty_a)
        if c.counterparty_b:
            counterparties.add(c.counterparty_b)

    if not counterparties:
        return error("No counterparties found in your contracts", 400)

    results = []
    for name in counterparties:
        # Skip if recently assessed (within last hour)
        recent = await db.execute(
            select(ContractIQCreditRisk)
            .where(
                ContractIQCreditRisk.user_id == user.id,
                ContractIQCreditRisk.counterparty_name == name,
                ContractIQCreditRisk.assessed_at
                > datetime.now(timezone.utc) - timedelta(hours=1),
            )
            .limit(1)
        )
        if recent.scalar_one_or_none():
            continue

        row = ContractIQCreditRisk(
            user_id=user.id,
            counterparty_name=name,
            status=InsightStatus.RUNNING.value,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        try:
            parsed, raw, meta = await _call_abenix(
                user,
                "counterparty-credit-risk",
                f"Assess the counterparty credit risk for: {name}",
                timeout=300.0,
            )
            if parsed:
                _caps = {
                    "ticker": 40,
                    "sector": 255,
                    "credit_rating": 80,
                    "z_score_zone": 40,
                    "risk_level": 40,
                }
                for field in [
                    "ticker",
                    "sector",
                    "credit_rating",
                    "credit_score",
                    "altman_z_score",
                    "z_score_zone",
                    "probability_of_default_pct",
                    "risk_level",
                    "key_ratios",
                    "financial_highlights",
                    "risk_factors",
                    "mitigating_factors",
                    "credit_mitigation_recommendations",
                    "monitoring_triggers",
                    "narrative",
                ]:
                    val = parsed.get(field)
                    if val is None:
                        continue
                    if isinstance(val, str) and field in _caps:
                        val = val[: _caps[field]]
                    setattr(row, field, val)
                row.status = InsightStatus.COMPLETED.value
            else:
                row.status = InsightStatus.FAILED.value
                row.error_message = raw[:500]
            if meta:
                row.cost_usd = meta.get("cost") or 0.0
            await db.commit()
            results.append(_serialize_credit_risk(row))
        except Exception as e:
            row.status = InsightStatus.FAILED.value
            row.error_message = str(e)[:200]
            await db.commit()
            results.append(_serialize_credit_risk(row))

    return success({"assessed": len(results), "counterparties": results})


# 11. KYC STANDARD CHECK (industry-standard template format)


def _serialize_kyc(r: ContractIQKycCheck) -> dict:
    return {
        "id": str(r.id),
        "status": r.status,
        "profit_centre": r.profit_centre,
        "activity_trigger": r.activity_trigger,
        "type_of_business_relationship": r.type_of_business_relationship,
        "start_date_of_check": (
            r.start_date_of_check.isoformat() if r.start_date_of_check else None
        ),
        "counterparty": {
            "name": r.counterparty_name,
            "address": r.counterparty_address,
            "primary_business": r.primary_business,
            "description": r.business_description,
            "legal_form": r.legal_form,
            "registration_number": r.registration_number,
            "lei": r.lei,
            "incorporation_date": r.incorporation_date,
            "status": r.entity_status,
            "country_iso2": r.country_iso2,
            "country_name": r.country_name,
        },
        "sanctions_applicable": r.sanctions_applicable,
        "indicator_i": {
            "title": "Country of Domicile Corruption Index Rank",
            "value": r.indicator_i_value,
            "score": r.indicator_i_score,
            "rationale": r.indicator_i_rationale,
        },
        "indicator_ii": {
            "title": "Annual Contracted Volume / Notional Value",
            "value_usd": r.indicator_ii_value_usd,
            "score": r.indicator_ii_score,
            "rationale": r.indicator_ii_rationale,
        },
        "indicator_iii": {
            "title": "Industry Segment",
            "value": r.indicator_iii_value,
            "score": r.indicator_iii_score,
            "rationale": r.indicator_iii_rationale,
        },
        "aggregated_score": r.aggregated_score,
        "type_of_check": r.type_of_check,
        "basic_compliance": r.basic_compliance,
        "intermediate_checks": r.intermediate_checks,
        "shareholder_structure_summary": r.shareholder_structure_summary,
        "ubos": r.ubos,
        "discovery_gaps": r.discovery_gaps,
        "summary_of_compliance_risk_assessment": r.summary_of_compliance_risk_assessment,
        "general_comments": r.general_comments,
        "legal_consulted": r.legal_consulted,
        "legal_opinion_summary": r.legal_opinion_summary,
        "outcome_of_check": r.outcome_of_check,
        "top_recommendations": r.top_recommendations,
        "narrative": r.narrative,
        "supporting_docs_location": r.supporting_docs_location,
        "local_kyc_expert_name": r.local_kyc_expert_name,
        "signed_at": r.signed_at.isoformat() if r.signed_at else None,
        "tool_warnings": r.tool_warnings,
        "cost_usd": r.cost_usd,
        "duration_ms": r.duration_ms,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/kyc")
async def list_kyc_checks(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    rows = (
        (
            await db.execute(
                select(ContractIQKycCheck)
                .where(ContractIQKycCheck.user_id == user.id)
                .order_by(ContractIQKycCheck.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return success([_serialize_kyc(r) for r in rows])


@router.get("/kyc/{kyc_id}")
async def get_kyc_check(
    kyc_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ContractIQKycCheck).where(
                ContractIQKycCheck.id == kyc_id,
                ContractIQKycCheck.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("KYC check not found", 404)
    return success(_serialize_kyc(row))


@router.post("/kyc/run")
async def run_kyc_check(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run a KYC standard check. All real work happens in Abenix via"""
    name = (body.get("counterparty_name") or "").strip()
    country = (body.get("country_iso2") or "").strip().upper()
    industry = (body.get("industry_segment") or "").strip()
    try:
        notional = float(body.get("annual_notional_usd") or 0)
    except (TypeError, ValueError):
        notional = 0.0

    if not name or not country or not industry or notional <= 0:
        return error(
            "counterparty_name, country_iso2, industry_segment, and annual_notional_usd are required",
            400,
        )

    row = ContractIQKycCheck(
        user_id=user.id,
        counterparty_name=name[:255],
        country_iso2=country[:3],
        profit_centre=(body.get("profit_centre") or None),
        activity_trigger=(body.get("activity_trigger") or "Pre-Check"),
        type_of_business_relationship=(
            body.get("type_of_business_relationship") or "Noncore"
        ),
        primary_business=body.get("primary_business"),
        business_description=body.get("description"),
        start_date_of_check=datetime.now(timezone.utc),
        indicator_ii_value_usd=notional,
        indicator_iii_value=industry,
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Compose the prompt
    ctx = (
        f"Run a KYC Standard Check for counterparty '{name}'. "
        f"Country: {country}. Industry segment: {industry}. "
        f"Annual contracted volume / notional USD: {notional:.0f}. "
        f"Activity trigger: {row.activity_trigger}. "
        f"Business relationship type: {row.type_of_business_relationship}. "
    )
    if row.primary_business:
        ctx += f" Primary business: {row.primary_business}."
    if row.business_description:
        ctx += f" Description: {row.business_description}."

    try:
        parsed, raw, meta = await _call_abenix(
            user,
            "kyc-standard-check",
            ctx,
            timeout=900.0,
        )
    except Exception as e:
        logger.exception("KYC agent call failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()
        return error(f"KYC agent failed: {e}", 503)

    if not parsed:
        row.status = InsightStatus.FAILED.value
        row.error_message = f"Agent returned unparseable output. Raw: {raw[:500]}"
        await db.commit()
        return error("Agent returned unparseable JSON", 500)

    # Persist everything
    cp = parsed.get("counterparty") or {}
    row.counterparty_address = cp.get("address")
    row.primary_business = cp.get("primary_business") or row.primary_business
    row.business_description = cp.get("description") or row.business_description
    row.legal_form = cp.get("legal_form")
    row.registration_number = cp.get("registration_number")
    row.lei = cp.get("lei")
    row.incorporation_date = cp.get("incorporation_date")
    row.entity_status = cp.get("status")
    row.country_name = cp.get("country_name")
    row.sanctions_applicable = bool(parsed.get("sanctions_applicable", False))

    for key, idx in [
        ("indicator_i", "i"),
        ("indicator_ii", "ii"),
        ("indicator_iii", "iii"),
    ]:
        data = parsed.get(key) or {}
        if idx == "i":
            row.indicator_i_value = _num(data.get("value"))
            row.indicator_i_score = _num(data.get("score"))
            row.indicator_i_rationale = data.get("rationale")
        elif idx == "ii":
            row.indicator_ii_value_usd = (
                _num(data.get("value_usd")) or row.indicator_ii_value_usd
            )
            row.indicator_ii_score = _num(data.get("score"))
            row.indicator_ii_rationale = data.get("rationale")
        elif idx == "iii":
            row.indicator_iii_value = data.get("value") or row.indicator_iii_value
            row.indicator_iii_score = _num(data.get("score"))
            row.indicator_iii_rationale = data.get("rationale")

    row.aggregated_score = _num(parsed.get("aggregated_score"))
    row.type_of_check = parsed.get("type_of_check")
    row.basic_compliance = parsed.get("basic_compliance") or {}
    row.intermediate_checks = parsed.get("intermediate_checks") or []
    row.shareholder_structure_summary = parsed.get("shareholder_structure_summary")
    row.ubos = parsed.get("ubos") or []
    row.discovery_gaps = parsed.get("discovery_gaps") or []
    row.summary_of_compliance_risk_assessment = parsed.get(
        "summary_of_compliance_risk_assessment"
    )
    row.general_comments = parsed.get("general_comments")
    row.legal_consulted = bool(parsed.get("legal_consulted", False))
    row.outcome_of_check = parsed.get("outcome_of_check")
    row.top_recommendations = parsed.get("top_recommendations") or []
    row.narrative = parsed.get("narrative")
    row.tool_warnings = parsed.get("tool_warnings") or []
    row.raw_agent_response = parsed
    row.status = InsightStatus.COMPLETED.value
    if meta:
        row.cost_usd = meta.get("cost") or 0.0
        row.duration_ms = meta.get("duration_ms")
    await db.commit()
    await db.refresh(row)
    return success(_serialize_kyc(row))


@router.put("/kyc/{kyc_id}/review-item")
async def review_kyc_item(
    kyc_id: uuid.UUID,
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Reviewer overrides the L/M/H risk or comment on a specific line item."""
    row = (
        await db.execute(
            select(ContractIQKycCheck).where(
                ContractIQKycCheck.id == kyc_id,
                ContractIQKycCheck.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("KYC check not found", 404)

    item_name = body.get("item_name")
    if not item_name:
        return error("item_name is required", 400)
    new_risk = body.get("risk")
    new_comment = body.get("comment")
    new_outcome = body.get("outcome")

    # Deep copy so SQLAlchemy sees a new JSONB object and persists it.
    from copy import deepcopy

    items = deepcopy(list(row.intermediate_checks or []))
    found = False
    for it in items:
        if it.get("name") == item_name:
            if new_risk and new_risk in ("L", "M", "H"):
                it["risk"] = new_risk
            if new_comment is not None:
                it["comment"] = new_comment[:500]
            if new_outcome and new_outcome in ("ok", "fail", "n-a"):
                it["outcome"] = new_outcome
            it["reviewed_by"] = str(user.id)
            it["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if not found:
        return error(f"item_name '{item_name}' not found in intermediate_checks", 404)
    row.intermediate_checks = items
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(row, "intermediate_checks")
    await db.commit()
    await db.refresh(row)
    return success(_serialize_kyc(row))


@router.delete("/kyc/{kyc_id}")
async def delete_kyc(
    kyc_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete a KYC check record."""
    row = (
        await db.execute(
            select(ContractIQKycCheck).where(
                ContractIQKycCheck.id == kyc_id,
                ContractIQKycCheck.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("KYC check not found", 404)
    await db.delete(row)
    await db.commit()
    return success({"deleted": True})


@router.post("/kyc/{kyc_id}/sign-off")
async def sign_off_kyc(
    kyc_id: uuid.UUID,
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Final sign-off: HITL approval of the KYC file."""
    row = (
        await db.execute(
            select(ContractIQKycCheck).where(
                ContractIQKycCheck.id == kyc_id,
                ContractIQKycCheck.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("KYC check not found", 404)

    outcome = (body.get("outcome_of_check") or "").lower()
    if outcome not in ("positive", "negative"):
        return error("outcome_of_check must be 'positive' or 'negative'", 400)

    row.outcome_of_check = outcome
    row.general_comments = body.get("general_comments") or row.general_comments
    row.legal_consulted = bool(body.get("legal_consulted", row.legal_consulted))
    row.legal_opinion_summary = (
        body.get("legal_opinion_summary") or row.legal_opinion_summary
    )
    row.supporting_docs_location = (
        body.get("supporting_docs_location") or row.supporting_docs_location
    )
    row.local_kyc_expert_name = (
        body.get("local_kyc_expert_name") or user.full_name or user.email
    )
    row.signed_at = datetime.now(timezone.utc)
    row.signed_by_user_id = user.id
    await db.commit()
    await db.refresh(row)
    return success(_serialize_kyc(row))


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Wave 1 — Portfolio Valuation, Forward Curves, Take-or-Pay Monitor

DEFAULT_MARKETS = [
    {
        "slug": "n2ex_uk_da_power",
        "market": "N2EX UK Day-Ahead Power",
        "unit": "GBP/MWh",
        "relevant_to": ["power_physical", "power_swap"],
    },
    {
        "slug": "eex_de_power",
        "market": "EEX DE Power",
        "unit": "EUR/MWh",
        "relevant_to": ["power_physical", "power_swap"],
    },
    {
        "slug": "ttf_natgas",
        "market": "TTF NatGas",
        "unit": "EUR/MWh",
        "relevant_to": ["gas_physical"],
    },
    {
        "slug": "jkm_lng",
        "market": "JKM LNG",
        "unit": "USD/MMBtu",
        "relevant_to": ["gas_physical"],
    },
    {
        "slug": "eua_carbon",
        "market": "EUA Carbon",
        "unit": "EUR/tCO2",
        "relevant_to": ["carbon", "power_physical"],
    },
    {"slug": "eur_usd", "market": "EUR/USD", "unit": "rate", "relevant_to": ["*"]},
]


def _serialize_curve(r: ContractIQForecastCurve) -> dict:
    return {
        "id": str(r.id),
        "market": r.market,
        "methodology": r.methodology,
        "unit": r.unit,
        "base_date": r.base_date.isoformat() if r.base_date else None,
        "tenor_months": r.tenor_months,
        "curve": r.curve,
        "fundamental_drivers": r.fundamental_drivers,
        "sentiment_score": r.sentiment_score,
        "sentiment_adjustment_pct": r.sentiment_adjustment_pct,
        "narrative": r.narrative,
        "data_sources": r.data_sources,
        "status": r.status,
        "cost_usd": r.cost_usd,
        "duration_ms": r.duration_ms,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _serialize_valuation(r: ContractIQValuation) -> dict:
    return {
        "id": str(r.id),
        "valuation_type": r.valuation_type,
        "scope": r.scope,
        "contract_id": str(r.contract_id) if r.contract_id else None,
        "valuation_date": r.valuation_date.isoformat() if r.valuation_date else None,
        "payload": r.payload,
        "portfolio_mtm": r.portfolio_mtm,
        "portfolio_mtm_ccy": r.portfolio_mtm_ccy,
        "total_shortfall_usd": r.total_shortfall_usd,
        "alert_count": r.alert_count,
        "status": r.status,
        "cost_usd": r.cost_usd,
        "duration_ms": r.duration_ms,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


async def _relevant_markets(db: AsyncSession, user_id) -> list[dict]:
    """Pick which of the DEFAULT_MARKETS this user actually needs curves"""
    rows = (
        (
            await db.execute(
                select(ContractIQContract).where(ContractIQContract.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    cluster_keys_in_play: set[str] = set()
    for c in rows:
        summary = c.extraction_summary or {}
        dc = summary.get("deal_clusters")
        if isinstance(dc, dict):
            cluster_keys_in_play.update(dc.keys())

    picked: list[dict] = []
    for m in DEFAULT_MARKETS:
        rel = set(m["relevant_to"])
        if "*" in rel or rel & cluster_keys_in_play or not cluster_keys_in_play:
            picked.append(m)
    # Always include FX so we always value cross-currency contracts
    if not any(m["slug"] == "eur_usd" for m in picked):
        picked.append(next(m for m in DEFAULT_MARKETS if m["slug"] == "eur_usd"))
    return picked


# ─── Forward curves ──────────────────────────────────────────────────────


@router.post("/valuation/forecast-curves/run")
async def run_forecast_curves(
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Fire `contractiq-price-forecaster` for every market relevant to the"""
    body = body or {}
    override_markets = body.get("markets")
    tenor = int(body.get("tenor_months") or 24)
    methodology = body.get("methodology") or "market+sentiment"
    base_date = datetime.now(timezone.utc)

    targets: list[dict]
    if override_markets:
        targets = [
            m if isinstance(m, dict) else {"market": m} for m in override_markets
        ]
    else:
        targets = await _relevant_markets(db, user.id)

    results: list[dict] = []
    for t in targets:
        market_name = t["market"]
        row = ContractIQForecastCurve(
            user_id=user.id,
            market=market_name,
            methodology=methodology,
            unit=t.get("unit"),
            base_date=base_date,
            tenor_months=tenor,
            status=InsightStatus.RUNNING.value,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        prompt = json.dumps(
            {
                "market": market_name,
                "tenor_months": tenor,
                "methodology": methodology,
                "base_date": base_date.date().isoformat(),
            }
        )
        try:
            parsed, raw, meta = await _call_abenix(
                user,
                "contractiq-price-forecaster",
                prompt,
                timeout=300.0,
            )
            if not parsed:
                row.status = InsightStatus.FAILED.value
                row.error_message = _format_parse_error(raw)
            else:
                row.curve = parsed.get("curve") or []
                row.fundamental_drivers = parsed.get("fundamental_drivers") or []
                row.sentiment_score = _num(parsed.get("sentiment_score"))
                row.sentiment_adjustment_pct = _num(
                    parsed.get("sentiment_adjustment_pct")
                )
                row.narrative = parsed.get("narrative")
                row.data_sources = parsed.get("data_sources") or []
                row.unit = parsed.get("unit") or row.unit
                row.raw_agent_response = parsed
                row.status = InsightStatus.COMPLETED.value
            if meta:
                row.cost_usd = meta.get("cost") or 0.0
                row.duration_ms = meta.get("duration_ms")
            await db.commit()
            await db.refresh(row)
        except Exception as e:
            logger.exception("Forecast curve failed for market=%s", market_name)
            row.status = InsightStatus.FAILED.value
            row.error_message = str(e)[:500]
            await db.commit()

        results.append(_serialize_curve(row))

    return success(
        {
            "curves_generated": len(
                [r for r in results if r["status"] == InsightStatus.COMPLETED.value]
            ),
            "total_targets": len(targets),
            "curves": results,
        }
    )


@router.get("/valuation/forecast-curves")
async def list_forecast_curves(
    limit: int = Query(50, ge=1, le=200),
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the latest curve for each market (one per market, newest wins)."""
    rows = (
        (
            await db.execute(
                select(ContractIQForecastCurve)
                .where(ContractIQForecastCurve.user_id == user.id)
                .order_by(ContractIQForecastCurve.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    # Dedupe by market, newest first
    seen: set[str] = set()
    unique_latest: list[dict] = []
    for r in rows:
        if r.market in seen:
            continue
        seen.add(r.market)
        unique_latest.append(_serialize_curve(r))
    return success({"total": len(unique_latest), "curves": unique_latest})


# ─── Portfolio valuation ────────────────────────────────────────────────


async def _build_valuation_context(db: AsyncSession, user_id) -> str:
    """Assemble the prompt context for the valuator agent:
    portfolio summary + the latest available forward curves.
    """
    portfolio_ctx = await _build_portfolio_context(db, user_id)

    curves = (
        (
            await db.execute(
                select(ContractIQForecastCurve)
                .where(
                    ContractIQForecastCurve.user_id == user_id,
                    ContractIQForecastCurve.status == InsightStatus.COMPLETED.value,
                )
                .order_by(ContractIQForecastCurve.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    seen: set[str] = set()
    curve_lines: list[str] = ["\n=== LATEST FORWARD CURVES ==="]
    for r in curves:
        if r.market in seen:
            continue
        seen.add(r.market)
        # Only first 12 points to keep prompt compact
        points = (r.curve or [])[:12]
        pstr = ", ".join(
            f"M{p.get('tenor_months')}={p.get('price')}"
            for p in points
            if isinstance(p, dict)
        )
        curve_lines.append(
            f"- {r.market} ({r.unit or '?'}) base={r.base_date.date().isoformat() if r.base_date else '?'}: {pstr}"
        )
    if len(curve_lines) == 1:
        curve_lines.append(
            "(no forward curves available — run /valuation/forecast-curves/run first)"
        )

    return portfolio_ctx + "\n" + "\n".join(curve_lines)


@router.post("/valuation/run")
async def run_portfolio_valuation(
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Fire `contractiq-portfolio-valuator`.
    body: {scope: 'portfolio'|'single', contract_id?: uuid}"""
    body = body or {}
    scope = (body.get("scope") or "portfolio").lower()
    contract_id_raw = body.get("contract_id")
    contract_id = None
    if contract_id_raw:
        try:
            contract_id = uuid.UUID(str(contract_id_raw))
        except (ValueError, TypeError):
            return error("Invalid contract_id", 400)

    row = ContractIQValuation(
        user_id=user.id,
        valuation_type="mtm",
        scope=scope,
        contract_id=contract_id,
        valuation_date=datetime.now(timezone.utc),
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    ctx = await _build_valuation_context(db, user.id)
    prompt = (
        json.dumps(
            {
                "scope": scope,
                "contract_id": str(contract_id) if contract_id else None,
            }
        )
        + f"\n\n=== PORTFOLIO + CURVES ===\n{ctx}"
    )

    try:
        parsed, raw, meta = await _call_abenix(
            user,
            "contractiq-portfolio-valuator",
            prompt,
            timeout=420.0,
        )
        if not parsed:
            row.status = InsightStatus.FAILED.value
            row.error_message = _format_parse_error(raw)
        else:
            row.payload = parsed
            row.portfolio_mtm = _num(parsed.get("portfolio_mtm"))
            row.portfolio_mtm_ccy = parsed.get("portfolio_mtm_ccy") or "USD"
            vd = parsed.get("valuation_date")
            if vd:
                try:
                    row.valuation_date = datetime.fromisoformat(
                        vd.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass
            row.status = InsightStatus.COMPLETED.value
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
            row.duration_ms = meta.get("duration_ms")
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Portfolio valuation failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_valuation(row))


@router.get("/valuation/latest")
async def get_latest_valuation(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the most recent completed MtM valuation."""
    row = (
        await db.execute(
            select(ContractIQValuation)
            .where(
                ContractIQValuation.user_id == user.id,
                ContractIQValuation.valuation_type == "mtm",
            )
            .order_by(ContractIQValuation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return success(_serialize_valuation(row) if row else None)


# ─── Take-or-Pay monitor ────────────────────────────────────────────────


@router.post("/valuation/top-monitor/run")
async def run_top_monitor(
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Fire `contractiq-top-monitor`. body: {contract_id?}"""
    body = body or {}
    contract_id_raw = body.get("contract_id")
    contract_id = None
    if contract_id_raw:
        try:
            contract_id = uuid.UUID(str(contract_id_raw))
        except (ValueError, TypeError):
            return error("Invalid contract_id", 400)

    row = ContractIQValuation(
        user_id=user.id,
        valuation_type="top_monitor",
        scope="single" if contract_id else "portfolio",
        contract_id=contract_id,
        valuation_date=datetime.now(timezone.utc),
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    portfolio_ctx = await _build_portfolio_context(db, user.id)
    prompt = (
        json.dumps(
            {
                "contract_id": str(contract_id) if contract_id else None,
            }
        )
        + f"\n\n=== PORTFOLIO ===\n{portfolio_ctx}"
    )

    try:
        parsed, raw, meta = await _call_abenix(
            user,
            "contractiq-top-monitor",
            prompt,
            timeout=300.0,
        )
        if not parsed:
            row.status = InsightStatus.FAILED.value
            row.error_message = _format_parse_error(raw)
        else:
            row.payload = parsed
            row.total_shortfall_usd = _num(parsed.get("portfolio_shortfall_usd"))
            alerts = parsed.get("alerts") or []
            row.alert_count = len(alerts) if isinstance(alerts, list) else 0
            row.status = InsightStatus.COMPLETED.value
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
            row.duration_ms = meta.get("duration_ms")
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Take-or-Pay monitor failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_valuation(row))


@router.get("/valuation/top-monitor")
async def get_latest_top_monitor(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the most recent Take-or-Pay monitor snapshot."""
    row = (
        await db.execute(
            select(ContractIQValuation)
            .where(
                ContractIQValuation.user_id == user.id,
                ContractIQValuation.valuation_type == "top_monitor",
            )
            .order_by(ContractIQValuation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return success(_serialize_valuation(row) if row else None)


# Clause Benchmarking (Wave 2 first landing)


def _serialize_benchmark(r: ContractIQClauseBenchmark) -> dict:
    return {
        "id": str(r.id),
        "clause_id": str(r.clause_id) if r.clause_id else None,
        "contract_id": str(r.contract_id) if r.contract_id else None,
        "clause_type": r.clause_type,
        "jurisdiction": r.jurisdiction,
        "stance": r.stance,
        "deviation_score": r.deviation_score,
        "market_standard_summary": r.market_standard_summary,
        "peer_comparisons": r.peer_comparisons,
        "recommendations": r.recommendations,
        "suggested_language": r.suggested_language,
        "sources": r.sources,
        "narrative": r.narrative,
        "status": r.status,
        "cost_usd": r.cost_usd,
        "duration_ms": r.duration_ms,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


async def _build_benchmark_context(
    db: AsyncSession,
    user_id,
    clause: ContractIQClause,
    contract: ContractIQContract,
) -> str:
    """Build the prompt context appended after the JSON instruction:
    full clause text + up to 10 peer clauses from the user's portfolio."""
    lines: list[str] = [
        "=== TARGET CLAUSE ===",
        f"Contract: {contract.title}",
        f"Contract type: {contract.contract_type.value if hasattr(contract.contract_type, 'value') else contract.contract_type}",
        f"Clause number: {clause.clause_number or '—'}",
        f"Clause title: {clause.clause_title}",
        f"Clause type: {clause.clause_type.value if hasattr(clause.clause_type, 'value') else clause.clause_type}",
        f"Risk level (as-extracted): {clause.risk_level.value if hasattr(clause.risk_level, 'value') else clause.risk_level}",
        "",
        "--- Clause text ---",
        clause.clause_text or "(no text)",
        "",
    ]
    if clause.risk_notes:
        lines.append(f"Extractor risk notes: {clause.risk_notes}")
        lines.append("")

    # Peer clauses of the same type
    peers = (
        await db.execute(
            select(ContractIQClause, ContractIQContract)
            .join(
                ContractIQContract,
                ContractIQContract.id == ContractIQClause.contract_id,
            )
            .where(
                ContractIQContract.user_id == user_id,
                ContractIQClause.clause_type == clause.clause_type,
                ContractIQClause.id != clause.id,
            )
            .order_by(ContractIQClause.created_at.desc())
            .limit(10)
        )
    ).all()

    lines.append("=== PEER CLAUSES (same type, your portfolio) ===")
    if not peers:
        lines.append(
            "(no peers of this type in portfolio yet — rely on market research)"
        )
    else:
        for pc, pct in peers:
            lines.append(
                f"- [{pct.title}] {pc.clause_title} (risk={pc.risk_level.value if hasattr(pc.risk_level,'value') else pc.risk_level})"
            )
            # Cap text to keep prompt compact
            lines.append(f"  {(pc.clause_text or '')[:1500]}")
            lines.append("")

    return "\n".join(lines)


@router.post("/benchmarks/run")
async def run_clause_benchmark(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Benchmark a single clause. body: {clause_id: uuid, jurisdiction?: str}"""
    try:
        clause_id = uuid.UUID(str(body.get("clause_id", "")))
    except (ValueError, TypeError):
        return error("clause_id is required and must be a UUID", 400)
    jurisdiction = (body.get("jurisdiction") or "").strip() or None

    # Load clause + contract with RBAC
    clause = (
        await db.execute(
            select(ContractIQClause).where(ContractIQClause.id == clause_id)
        )
    ).scalar_one_or_none()
    if not clause:
        return error("Clause not found", 404)

    contract = (
        await db.execute(
            select(ContractIQContract).where(
                ContractIQContract.id == clause.contract_id,
                ContractIQContract.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not contract:
        return error("Clause not found or access denied", 404)

    # Create row early so the UI can poll status
    row = ContractIQClauseBenchmark(
        user_id=user.id,
        clause_id=clause.id,
        contract_id=contract.id,
        clause_type=(
            clause.clause_type.value
            if hasattr(clause.clause_type, "value")
            else str(clause.clause_type)
        ),
        jurisdiction=jurisdiction,
        status=InsightStatus.RUNNING.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    clause_type_str = row.clause_type
    contract_type_str = (
        contract.contract_type.value
        if hasattr(contract.contract_type, "value")
        else str(contract.contract_type)
    )

    prompt_json = json.dumps(
        {
            "clause_id": str(clause.id),
            "contract_id": str(contract.id),
            "clause_type": clause_type_str,
            "contract_type": contract_type_str,
            "jurisdiction": jurisdiction,
        }
    )
    context = await _build_benchmark_context(db, user.id, clause, contract)
    prompt = prompt_json + "\n\n" + context

    try:
        parsed, raw, meta = await _call_abenix(
            user,
            "contractiq-clause-benchmarker",
            prompt,
            timeout=420.0,
        )
        if not parsed:
            row.status = InsightStatus.FAILED.value
            row.error_message = _format_parse_error(raw)
        else:
            row.stance = (parsed.get("stance") or "")[:30] or None
            dev = parsed.get("deviation_score")
            if isinstance(dev, (int, float)):
                row.deviation_score = max(-1.0, min(1.0, float(dev)))
            row.market_standard_summary = parsed.get("market_standard_summary")
            row.peer_comparisons = parsed.get("peer_comparisons") or []
            row.recommendations = parsed.get("recommendations") or []
            row.suggested_language = parsed.get("suggested_language")
            row.sources = parsed.get("sources") or []
            row.narrative = parsed.get("narrative")
            row.raw_agent_response = parsed
            row.status = InsightStatus.COMPLETED.value
        if meta:
            row.cost_usd = meta.get("cost") or 0.0
            row.duration_ms = meta.get("duration_ms")
        await db.commit()
        await db.refresh(row)
    except Exception as e:
        logger.exception("Clause benchmark failed")
        row.status = InsightStatus.FAILED.value
        row.error_message = str(e)[:500]
        await db.commit()

    return success(_serialize_benchmark(row))


@router.get("/benchmarks")
async def list_benchmarks(
    limit: int = Query(100, ge=1, le=500),
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List benchmark runs newest-first, one per clause (latest wins)."""
    rows = (
        (
            await db.execute(
                select(ContractIQClauseBenchmark)
                .where(ContractIQClauseBenchmark.user_id == user.id)
                .order_by(ContractIQClauseBenchmark.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    seen: set[str] = set()
    latest: list[dict] = []
    for r in rows:
        key = str(r.clause_id)
        if key in seen:
            continue
        seen.add(key)
        latest.append(_serialize_benchmark(r))
    return success({"total": len(latest), "benchmarks": latest})


@router.get("/benchmarks/clause/{clause_id}")
async def get_clause_benchmark(
    clause_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Latest benchmark for a specific clause, or null."""
    row = (
        await db.execute(
            select(ContractIQClauseBenchmark)
            .where(
                ContractIQClauseBenchmark.user_id == user.id,
                ContractIQClauseBenchmark.clause_id == clause_id,
            )
            .order_by(ContractIQClauseBenchmark.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return success(_serialize_benchmark(row) if row else None)


@router.get("/benchmarks/{benchmark_id}")
async def get_benchmark(
    benchmark_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return a single benchmark row by id."""
    row = (
        await db.execute(
            select(ContractIQClauseBenchmark).where(
                ContractIQClauseBenchmark.id == benchmark_id,
                ContractIQClauseBenchmark.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return error("Benchmark not found", 404)
    return success(_serialize_benchmark(row))
