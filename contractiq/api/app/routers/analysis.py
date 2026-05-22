"""ContractIQ Analysis — risk analysis, comparison, and cross-contract chat."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.routers.auth import get_contractiq_user

from app.models.contractiq_models import (
    ContractIQContract, ContractIQUser, ContractIQClause, ContractIQAsset,
    ContractIQExtractedData, ContractIQRiskAnalysis, ContractIQComparison,
    ContractIQEvent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contractiq", tags=["contractiq-analysis"])


def _extract_json_from_agent_output(text: str) -> dict | None:
    """Robust JSON extractor for LLM output."""
    import re as _re
    if not text:
        return None
    cleaned = text.strip()

    # 1. Direct parse
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Strip markdown code fences (```json ... ```  or  ``` ... ```)
    fence = _re.search(r"```(?:json)?\s*\n([\s\S]*?)```", cleaned)
    if fence:
        inner = fence.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
        # Fall through — maybe fence content is also truncated, try balance recovery
        cleaned_for_balance = inner
    else:
        cleaned_for_balance = cleaned

    # 3. Find outermost { ... } span
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidate = cleaned[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 4. Truncation recovery — balance braces + brackets, trim trailing partial
    #    Only attempt this on the fenced content if we had a fence; else on the
    #    outermost brace span.
    candidate = cleaned_for_balance if fence else (cleaned[start:] if start >= 0 else cleaned)

    # Cut at last complete `}` before the tail
    last_brace = candidate.rfind("}")
    if last_brace < 0:
        return None
    truncated = candidate[:last_brace + 1]

    # Count unmatched braces and brackets
    def _attempt(s: str) -> dict | None:
        # Walk and track string state; count opening vs closing braces/brackets
        depth_brace = 0
        depth_brack = 0
        in_str = False
        esc = False
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
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
            elif ch == "[":
                depth_brack += 1
            elif ch == "]":
                depth_brack -= 1
        fix = s
        # Trim trailing comma before we close
        fix = _re.sub(r",\s*$", "", fix)
        fix += "]" * max(0, depth_brack)
        fix += "}" * max(0, depth_brace)
        try:
            return json.loads(fix)
        except json.JSONDecodeError:
            # Try trimming back to the last comma before a key and retry
            last_comma = fix.rfind(",")
            if last_comma < 0:
                return None
            fix2 = fix[:last_comma] + "}" * max(0, depth_brace) + "]" * max(0, depth_brack)
            try:
                return json.loads(fix2)
            except json.JSONDecodeError:
                return None

    return _attempt(truncated)


@router.post("/contracts/{contract_id}/analyze")
async def analyze_contract(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run a deep risk re-analysis on an already-extracted contract.

    Builds a structured context summary, invokes the contractiq-extractor
    agent to produce an updated risk assessment + clause re-classification,
    and persists fresh ContractIQRiskAnalysis rows + an updated risk_score.
    """
    query = select(ContractIQContract).where(ContractIQContract.id == contract_id)
    if user.role.value != "admin":
        query = query.where(ContractIQContract.user_id == user.id)
    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    extracted_rows = (await db.execute(
        select(ContractIQExtractedData).where(ContractIQExtractedData.contract_id == contract_id)
    )).scalars().all()
    clause_rows = (await db.execute(
        select(ContractIQClause).where(ContractIQClause.contract_id == contract_id)
    )).scalars().all()

    if not extracted_rows and not clause_rows:
        return error(
            "Contract has no extracted data — run extraction first via /contracts/{id}/extract",
            400,
        )

    summary_lines = [
        f"Contract: {contract.title}",
        f"Type: {contract.contract_type.value if contract.contract_type else '?'}",
        f"Parties: {contract.counterparty_a or '?'} ↔ {contract.counterparty_b or '?'}",
        f"Capacity: {contract.total_capacity_mw or '?'} MW",
        f"Effective: {contract.effective_date} → Expiry: {contract.expiry_date}",
        "",
        "EXTRACTED FIELDS:",
    ]
    for e in extracted_rows[:80]:
        summary_lines.append(f"  - [{e.section}] {e.field_name}: {str(e.field_value)[:200]}")
    summary_lines.append("")
    summary_lines.append("CLAUSES:")
    for c in clause_rows[:40]:
        summary_lines.append(
            f"  - [{c.clause_type.value}] {c.clause_title} | risk={c.risk_level.value} | "
            f"{(c.clause_text or '')[:300]}"
        )

    msg = (
        "Re-analyze the following extracted contract and return a fresh risk "
        "assessment. Output a single JSON object with `risk_assessment` "
        "(array of {category, score 0-100, description, mitigation}) and "
        "`overall_risk_score` (0-100). Be specific.\n\n"
        + "\n".join(summary_lines)
    )

    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        return error("CONTRACTIQ_ABENIX_API_KEY not configured", 503)

    from abenix_sdk import Abenix, ActingSubject

    subject = ActingSubject(
        subject_type="contractiq",
        subject_id=str(user.id),
        email=user.email,
        display_name=user.full_name,
    )
    try:
        async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=300.0) as forge:
            result = await forge.execute("contractiq-extractor", msg[:60000])
        parsed = _extract_json_from_agent_output(result.output or "")
    except Exception as e:
        logger.exception("Deep analyze failed for contract %s", contract_id)
        return error(f"Analysis failed: {e}", 503)

    if not parsed:
        return success({
            "contract_id": str(contract_id),
            "status": "completed_unparseable",
            "raw_output": (result.output or "")[:2000],
            "warning": "agent_output_not_parseable",
        })

    # Persist fresh risk rows. Replace prior risk_assessment for this contract.
    from sqlalchemy import delete as sql_delete
    await db.execute(
        sql_delete(ContractIQRiskAnalysis).where(
            ContractIQRiskAnalysis.contract_id == contract_id,
            ContractIQRiskAnalysis.analysis_type == "deep_reanalysis",
        )
    )
    risk_scores: list[float] = []
    persisted: list[dict] = []
    for r in parsed.get("risk_assessment", []) or []:
        try:
            score = float(r.get("score", 50))
        except (ValueError, TypeError):
            score = 50.0
        risk_scores.append(score)
        row = ContractIQRiskAnalysis(
            id=uuid.uuid4(),
            contract_id=contract_id,
            analysis_type="deep_reanalysis",
            risk_category=str(r.get("category", "operational"))[:100],
            risk_score=score,
            risk_description=str(r.get("description", ""))[:2000],
            mitigation_suggestion=str(r.get("mitigation") or "")[:2000] or None,
        )
        db.add(row)
        persisted.append({
            "category": row.risk_category,
            "score": row.risk_score,
            "description": row.risk_description,
            "mitigation": row.mitigation_suggestion,
        })
    overall = parsed.get("overall_risk_score")
    if overall is None and risk_scores:
        overall = sum(risk_scores) / len(risk_scores)
    if overall is not None:
        try:
            contract.risk_score = float(overall)
        except (ValueError, TypeError):
            pass
    await db.commit()

    return success({
        "contract_id": str(contract_id),
        "status": "analyzed",
        "overall_risk_score": contract.risk_score,
        "risk_assessment": persisted,
        "agent_model": result.model,
        "duration_ms": result.duration_ms,
        "cost": result.cost,
        "tool_calls": len(result.tool_calls or []),
    })


@router.post("/compare")
async def compare_contracts(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Compare 2-5 contracts side by side."""
    contract_ids = body.get("contract_ids", [])
    comparison_type = body.get("comparison_type", "side_by_side")

    if len(contract_ids) < 2 or len(contract_ids) > 5:
        return error("Select 2-5 contracts to compare", 400)

    contracts_data = []
    for cid in contract_ids:
        try:
            uid = uuid.UUID(cid)
        except ValueError:
            continue

        query = select(ContractIQContract).where(ContractIQContract.id == uid)
        if user.role.value != "admin":
            query = query.where(ContractIQContract.user_id == user.id)
        result = await db.execute(query)
        contract = result.scalar_one_or_none()
        if not contract:
            continue

        # Get extracted commercial terms
        extracted = await db.execute(
            select(ContractIQExtractedData).where(
                ContractIQExtractedData.contract_id == uid,
                ContractIQExtractedData.section == "commercial_terms",
            )
        )
        terms = {e.field_name: e.field_value for e in extracted.scalars().all()}

        contracts_data.append({
            "id": str(contract.id),
            "title": contract.title,
            "contract_type": contract.contract_type.value,
            "counterparty_a": contract.counterparty_a,
            "effective_date": contract.effective_date.isoformat() if contract.effective_date else None,
            "expiry_date": contract.expiry_date.isoformat() if contract.expiry_date else None,
            "risk_score": contract.risk_score,
            "total_capacity_mw": contract.total_capacity_mw,
            "contract_value": float(contract.contract_value) if contract.contract_value else None,
            "currency": contract.currency,
            "commercial_terms": terms,
        })

    if len(contracts_data) < 2:
        return error("Could not find enough contracts to compare", 404)

    # Save comparison
    comparison = ContractIQComparison(
        id=uuid.uuid4(),
        user_id=user.id,
        contract_ids=[str(c["id"]) for c in contracts_data],
        comparison_type=comparison_type,
        results={"contracts": contracts_data},
    )
    db.add(comparison)
    await db.commit()

    return success({
        "comparison_id": str(comparison.id),
        "comparison_type": comparison_type,
        "contracts": contracts_data,
    })


# NOTE: Chat system prompt lives in the Abenix agent definition
# (packages/db/seeds/agents/contractiq_chat_agent.yaml). ContractIQ does not
# inject its own system prompt — it just calls forge.execute("contractiq-chat", query).


@router.post("/chat")
async def cross_contract_chat(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Ask questions across all user's contracts using an agent with tools."""
    from sqlalchemy import func as sqlfunc

    query_text = body.get("query", "")
    thread_id = body.get("thread_id")
    if not query_text or len(query_text) < 3:
        return error("Query must be at least 3 characters", 400)

    # Check contract count
    count_result = await db.execute(
        select(sqlfunc.count()).select_from(ContractIQContract).where(ContractIQContract.user_id == user.id)
    )
    contract_count = count_result.scalar() or 0
    if contract_count == 0:
        return success({
            "query": query_text,
            "answer": "You don't have any contracts yet. Upload a contract first to start asking questions.",
            "sources": [],
        })

    src_result = await db.execute(
        select(
            ContractIQContract.id,
            ContractIQContract.title,
            ContractIQContract.contract_type,
            ContractIQContract.counterparty_a,
            ContractIQContract.counterparty_b,
            ContractIQContract.total_capacity_mw,
            ContractIQContract.contract_value,
            ContractIQContract.currency,
            ContractIQContract.effective_date,
            ContractIQContract.expiry_date,
            ContractIQContract.risk_score,
            ContractIQContract.status,
            ContractIQContract.extraction_summary,
        )
        .where(ContractIQContract.user_id == user.id)
        .order_by(ContractIQContract.created_at.desc())
    )
    rows = src_result.all()
    sources = [
        {"id": str(r.id), "title": r.title, "type": r.contract_type.value if r.contract_type else None}
        for r in rows
    ]
    portfolio_lines = []
    for r in rows:
        ctype = r.contract_type.value if r.contract_type else "?"
        cap = f"{r.total_capacity_mw} MW" if r.total_capacity_mw else "—"
        val = f"{r.contract_value:.0f} {r.currency or ''}".strip() if r.contract_value else "—"
        eff = r.effective_date.date().isoformat() if r.effective_date else "—"
        exp = r.expiry_date.date().isoformat() if r.expiry_date else "—"
        risk = f"{r.risk_score:.0f}" if r.risk_score is not None else "—"
        cps = f"{r.counterparty_a or '—'} ↔ {r.counterparty_b or '—'}"
        portfolio_lines.append(
            f"- [{r.title}] type={ctype} | {cps} | capacity={cap} | value={val} | "
            f"effective={eff} | expiry={exp} | risk={risk}"
        )
    portfolio_brief = "\n".join(portfolio_lines) if portfolio_lines else "(empty)"

    from abenix_sdk import Abenix, ActingSubject

    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")

    if not api_key:
        return error(
            "CONTRACTIQ_ABENIX_API_KEY not configured. "
            "Create an Abenix API key with can_delegate scope and set the env var.",
            503,
        )

    # Acting subject: the ContractIQ end user
    subject = ActingSubject(
        subject_type="contractiq",
        subject_id=str(user.id),
        email=user.email,
        display_name=user.full_name,
    )

    # The portfolio brief is sent as fresh per-turn `context` (not as part
    # of the user message) so it doesn't bloat the persisted thread history
    # — only the user's actual words are stored. The thread accumulates
    # turn-by-turn; Abenix repacks history on every turn.
    fresh_context = (
        f"PORTFOLIO BRIEF ({contract_count} contracts)\n"
        f"{portfolio_brief}\n\n"
        f"Answer using this brief plus prior turns. Use tools (knowledge_search, "
        f"financial_calculator, market data tools) only for data not already in the brief."
    )

    try:
        async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=300.0) as forge:
            # Find or create the thread bound to contractiq-chat
            if thread_id:
                tid = thread_id
            else:
                # Reuse the most recent un-archived ContractIQ thread for
                # this subject if one exists, otherwise create a new one.
                threads = await forge.chat.list(app_slug="contractiq", agent_slug="contractiq-chat", limit=1)
                if threads:
                    tid = threads[0]["id"]
                else:
                    new_thread = await forge.chat.create(
                        app_slug="contractiq",
                        agent_slug="contractiq-chat",
                    )
                    tid = new_thread["id"]

            turn = await forge.chat.send(tid, query_text, context=fresh_context)
            assistant = turn.get("assistant_message") or {}
            thread = turn.get("thread") or {}

            return success({
                "query": query_text,
                "thread_id": tid,
                "thread": thread,
                "answer": assistant.get("content", ""),
                "sources": sources,
                "contracts_analyzed": contract_count,
                "tool_calls": len(assistant.get("tool_calls") or []),
                "model": assistant.get("model_used"),
                "duration_ms": assistant.get("duration_ms"),
                "cost": assistant.get("cost"),
            })

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error("ContractIQ chat error: %s\n%s", repr(e), tb)
        return error(f"Chat service unavailable: {repr(e)}", 503)


@router.get("/chat/threads")
async def list_chat_threads(
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    """List the user's saved ContractIQ chat threads (sidebar)."""
    from abenix_sdk import Abenix, ActingSubject
    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        return success({"threads": []})
    subject = ActingSubject(
        subject_type="contractiq", subject_id=str(user.id),
        email=user.email, display_name=user.full_name,
    )
    async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=30.0) as forge:
        threads = await forge.chat.list(app_slug="contractiq", agent_slug="contractiq-chat", limit=50)
    return success({"threads": threads})


@router.get("/chat/threads/{thread_id}")
async def get_chat_thread(
    thread_id: str,
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    """Fetch a single thread + all its messages."""
    from abenix_sdk import Abenix, ActingSubject
    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        return error("Chat history unavailable", 503)
    subject = ActingSubject(
        subject_type="contractiq", subject_id=str(user.id),
        email=user.email, display_name=user.full_name,
    )
    async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=30.0) as forge:
        thread = await forge.chat.get(thread_id)
    return success(thread)


@router.delete("/chat/threads/{thread_id}")
async def delete_chat_thread(
    thread_id: str,
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    from abenix_sdk import Abenix, ActingSubject
    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        return error("Chat history unavailable", 503)
    subject = ActingSubject(
        subject_type="contractiq", subject_id=str(user.id),
        email=user.email, display_name=user.full_name,
    )
    async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=30.0) as forge:
        await forge.chat.delete(thread_id)
    return success({"deleted": True})


@router.post("/contracts/{contract_id}/functional-analysis")
async def functional_analysis(
    contract_id: str,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run functional analysis on a contract — extracts the 7-section template"""
    import uuid as _uuid
    contract_result = await db.execute(
        select(ContractIQContract).where(
            ContractIQContract.id == _uuid.UUID(contract_id),
            ContractIQContract.user_id == user.id,
        )
    )
    contract = contract_result.scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    raw_text = contract.raw_text or (contract.extraction_summary or {}).get("raw_text", "")
    if not raw_text:
        return error("Contract has no extracted text yet — run extraction first", 400)

    from abenix_sdk import Abenix, ActingSubject

    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        return error("CONTRACTIQ_ABENIX_API_KEY not configured", 503)

    subject = ActingSubject(
        subject_type="contractiq",
        subject_id=str(user.id),
        email=user.email,
        display_name=user.full_name,
    )

    try:
        async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=600.0) as forge:
            result = await forge.execute(
                "contractiq-functional-analysis",
                raw_text[:50000],
            )

            analysis = _extract_json_from_agent_output(result.output or "")
            if analysis is None:
                analysis = {"raw_output": result.output}

            # Store the analysis on the contract record
            contract.functional_analysis = analysis
            await db.commit()

            return success({
                "contract_id": contract_id,
                "analysis": analysis,
                "model": result.model,
                "duration_ms": result.duration_ms,
                "cost": result.cost,
                "tool_calls": len(result.tool_calls),
            })

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error("Functional analysis error: %s\n%s", repr(e), tb)
        return error(f"Functional analysis failed: {repr(e)}", 503)


@router.get("/contracts/{contract_id}/functional-analysis")
async def get_functional_analysis(
    contract_id: str,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Retrieve a previously computed functional analysis for a contract."""
    import uuid as _uuid
    contract_result = await db.execute(
        select(ContractIQContract).where(
            ContractIQContract.id == _uuid.UUID(contract_id),
            ContractIQContract.user_id == user.id,
        )
    )
    contract = contract_result.scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    fa = getattr(contract, "functional_analysis", None)
    if not fa:
        return error("No functional analysis yet — trigger one via POST", 404)

    return success({
        "contract_id": contract_id,
        "analysis": fa,
    })


@router.get("/cognify-status")
async def cognify_status(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Check knowledge graph status via Abenix SDK."""
    from sqlalchemy import func as sqlfunc

    graph_stats = {"available": False, "entities": 0, "relationships": 0}
    kb_id: str | None = None
    try:
        from abenix_sdk import Abenix, ActingSubject
        api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
        api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
        if api_key:
            subject = ActingSubject(subject_type="contractiq", subject_id=str(user.id))
            async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=30.0) as forge:
                coll = await forge.knowledge.ensure_subject_collection(
                    project_slug="contractiq",
                    subject_type="contractiq",
                    subject_id=str(user.id),
                    description=f"Per-user contracts corpus for {user.email}",
                )
                kb_id = coll.get("id")
                if kb_id:
                    stats = await forge.knowledge.graph_stats(kb_id)
                    graph_stats = {"available": True, **stats}
    except Exception as e:
        logger.warning("Cognify status check failed: %s", e)

    total = await db.scalar(
        select(sqlfunc.count()).select_from(ContractIQContract).where(
            ContractIQContract.user_id == user.id,
            ContractIQContract.status == "analyzed",
        )
    )

    return success({
        "kb_id": kb_id,
        "total_analyzed_contracts": total or 0,
        "graph": graph_stats,
    })


@router.post("/cognify")
async def trigger_cognify(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Trigger Cognify via Abenix SDK to build the knowledge graph for analyzed contracts."""
    contracts = await db.execute(
        select(ContractIQContract).where(
            ContractIQContract.user_id == user.id,
            ContractIQContract.status == "analyzed",
        )
    )
    contract_list = contracts.scalars().all()

    if not contract_list:
        return error("No analyzed contracts found. Upload and extract contracts first.", 400)

    try:
        from abenix_sdk import Abenix, ActingSubject
        api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
        api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
        if not api_key:
            return error("CONTRACTIQ_ABENIX_API_KEY not configured", 503)

        subject = ActingSubject(subject_type="contractiq", subject_id=str(user.id))
        async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=30.0) as forge:
            # KB v2: resolve the user's collection UUID via the
            # bootstrap-shaped helper. First call creates it; later
            # calls just look it up.
            coll = await forge.knowledge.ensure_subject_collection(
                project_slug="contractiq",
                subject_type="contractiq",
                subject_id=str(user.id),
                description=f"Per-user contracts corpus for {user.email}",
            )
            kb_id = coll["id"]
            doc_ids = [str(c.id) for c in contract_list]
            result = await forge.knowledge.cognify(kb_id, doc_ids=doc_ids)
            return success({
                "status": "cognify_triggered",
                "job_id": result.get("job_id"),
                "documents": len(doc_ids),
                "kb_id": kb_id,
                "message": f"Cognify started via Abenix SDK for {len(doc_ids)} contracts.",
            })
    except Exception as e:
        logger.error("Cognify trigger failed: %s", e)
        return error(f"Cognify failed: {e}", 503)


@router.get("/analytics/portfolio")
async def portfolio_analytics(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Portfolio-level analytics across all user's contracts."""
    from sqlalchemy import func

    scope_filter = ContractIQContract.user_id == user.id

    # Aggregate stats
    stats_result = await db.execute(
        select(
            func.count(ContractIQContract.id).label("total"),
            func.sum(ContractIQContract.total_capacity_mw).label("total_capacity"),
            func.avg(ContractIQContract.risk_score).label("avg_risk"),
            func.sum(ContractIQContract.contract_value).label("total_value"),
        ).where(scope_filter)
    )
    stats = stats_result.one()

    # By type
    type_result = await db.execute(
        select(
            ContractIQContract.contract_type,
            func.count(ContractIQContract.id).label("count"),
            func.sum(ContractIQContract.total_capacity_mw).label("capacity"),
        ).where(scope_filter).group_by(ContractIQContract.contract_type)
    )
    by_type = [
        {"type": r.contract_type.value, "count": r.count, "capacity": float(r.capacity or 0)}
        for r in type_result.all()
    ]

    # Risk distribution
    risk_result = await db.execute(
        select(ContractIQRiskAnalysis.risk_category, func.avg(ContractIQRiskAnalysis.risk_score).label("avg"))
        .join(ContractIQContract)
        .where(scope_filter)
        .group_by(ContractIQRiskAnalysis.risk_category)
    )
    risk_by_category = [
        {"category": r.risk_category, "avg_score": round(float(r.avg or 0), 1)}
        for r in risk_result.all()
    ]

    # Individual contract risk scores for distribution chart
    from sqlalchemy import func
    contracts_result = await db.execute(
        select(
            ContractIQContract.id,
            ContractIQContract.title,
            ContractIQContract.contract_type,
            ContractIQContract.risk_score,
            ContractIQContract.total_capacity_mw,
            ContractIQContract.contract_value,
            ContractIQContract.effective_date,
            ContractIQContract.expiry_date,
            ContractIQContract.status,
            ContractIQContract.counterparty_a,
        ).where(scope_filter).order_by(ContractIQContract.created_at.desc())
    )
    contracts_detail = [
        {
            "id": str(r.id),
            "title": r.title,
            "type": r.contract_type.value if r.contract_type else None,
            "risk_score": float(r.risk_score) if r.risk_score else None,
            "capacity_mw": float(r.total_capacity_mw) if r.total_capacity_mw else None,
            "value": float(r.contract_value) if r.contract_value else None,
            "effective_date": r.effective_date.isoformat() if r.effective_date else None,
            "expiry_date": r.expiry_date.isoformat() if r.expiry_date else None,
            "status": r.status.value if r.status else None,
            "counterparty": r.counterparty_a,
        }
        for r in contracts_result.all()
    ]

    # Clause type distribution across portfolio
    clause_dist_result = await db.execute(
        select(
            ContractIQClause.clause_type,
            ContractIQClause.risk_level,
            func.count(ContractIQClause.id).label("count"),
        )
        .join(ContractIQContract)
        .where(scope_filter)
        .group_by(ContractIQClause.clause_type, ContractIQClause.risk_level)
    )
    clause_distribution = [
        {"type": r.clause_type.value, "risk_level": r.risk_level.value, "count": r.count}
        for r in clause_dist_result.all()
    ]

    # Upcoming events
    from datetime import datetime, timezone
    events_result = await db.execute(
        select(
            ContractIQEvent.event_type,
            ContractIQEvent.event_date,
            ContractIQEvent.description,
            ContractIQContract.title.label("contract_title"),
        )
        .join(ContractIQContract)
        .where(scope_filter, ContractIQEvent.event_date.isnot(None))
        .order_by(ContractIQEvent.event_date)
        .limit(20)
    )
    upcoming_events = [
        {
            "type": r.event_type,
            "date": r.event_date.isoformat() if r.event_date else None,
            "description": r.description[:200] if r.description else "",
            "contract": r.contract_title,
        }
        for r in events_result.all()
    ]

    # Contracts expiring within 12 months
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    expiring_soon = sum(
        1 for c in contracts_detail
        if c.get("expiry_date") and datetime.fromisoformat(c["expiry_date"]).replace(tzinfo=timezone.utc) < now + timedelta(days=365)
    )

    return success({
        "total_contracts": stats.total or 0,
        "total_capacity_mw": float(stats.total_capacity or 0),
        "avg_risk_score": round(float(stats.avg_risk or 0), 1),
        "total_contract_value": float(stats.total_value or 0),
        "contracts_expiring_soon": expiring_soon,
        "by_type": by_type,
        "risk_by_category": risk_by_category,
        "contracts": contracts_detail,
        "clause_distribution": clause_distribution,
        "upcoming_events": upcoming_events,
    })


# ─── Market Data & Alerts ─────────────────────────────────────────────────────

@router.get("/market-data")
async def market_data(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Live market data with PnL and exposure calculations. Polled every 15s by frontend."""
    from datetime import datetime, timezone
    from app.core.market_cache import fetch_all_market_data

    # Fetch market data (cached, parallel)
    market = await fetch_all_market_data()

    # Get user's contracts with pricing data
    contracts_result = await db.execute(
        select(ContractIQContract).where(
            ContractIQContract.user_id == user.id,
            ContractIQContract.status == "analyzed",
        )
    )
    contracts = contracts_result.scalars().all()

    # Calculate PnL per contract
    exposure_list = []
    total_pnl = 0.0
    total_mtm = 0.0
    in_money = 0
    out_money = 0

    for c in contracts:
        # Get contract price from extracted data
        price_field = await db.execute(
            select(ContractIQExtractedData).where(
                ContractIQExtractedData.contract_id == c.id,
                ContractIQExtractedData.field_name.in_([
                    "contract_price", "contract_price_per_mwh",
                    "fixed_price_per_mwh", "contract_price_per_mmbtu",
                ]),
            ).limit(1)
        )
        price_row = price_field.scalar_one_or_none()

        contract_price = None
        if price_row:
            try:
                val = price_row.field_value.replace("$", "").replace("€", "").replace(",", "")
                # Extract numeric part
                import re
                nums = re.findall(r"[\d.]+", val)
                if nums:
                    contract_price = float(nums[0])
            except (ValueError, TypeError, AttributeError):
                pass

        # Estimate capacity factor and annual generation
        capacity = float(c.total_capacity_mw or 0)
        cap_factor = 0.25 if c.contract_type and c.contract_type.value == "ppa" else 0.85
        annual_mwh = capacity * 8760 * cap_factor if capacity else 0

        # Calculate remaining years
        remaining_years = 0
        if c.expiry_date:
            delta = c.expiry_date - datetime.now(timezone.utc)
            remaining_years = max(0, delta.days / 365.25)

        # Simple PnL: assume spot price = 55 EUR/MWh as baseline
        # (real implementation reads from market data tool response)
        spot_price = 55.0  # Placeholder — enhanced by market data
        pnl_per_mwh = (spot_price - contract_price) if contract_price else 0
        annual_pnl = pnl_per_mwh * annual_mwh
        mtm = annual_pnl * remaining_years

        if contract_price and pnl_per_mwh > 0:
            in_money += 1
        elif contract_price and pnl_per_mwh < 0:
            out_money += 1

        total_pnl += annual_pnl
        total_mtm += mtm

        exposure_list.append({
            "id": str(c.id),
            "title": c.title,
            "contract_type": c.contract_type.value if c.contract_type else None,
            "contract_price": contract_price,
            "spot_price": spot_price,
            "pnl_per_mwh": round(pnl_per_mwh, 2),
            "annual_pnl": round(annual_pnl, 0),
            "mark_to_market": round(mtm, 0),
            "capacity_mw": capacity,
            "remaining_years": round(remaining_years, 1),
            "risk_score": float(c.risk_score) if c.risk_score else None,
            "direction": "in_money" if pnl_per_mwh > 0 else "out_of_money" if pnl_per_mwh < 0 else "at_par",
        })

    # Recent alerts
    from app.models.contractiq_models import ContractIQMarketAlert
    try:
        alerts_result = await db.execute(
            select(ContractIQMarketAlert)
            .join(ContractIQContract)
            .where(ContractIQContract.user_id == user.id)
            .order_by(ContractIQMarketAlert.created_at.desc())
            .limit(10)
        )
        recent_alerts = [
            {
                "id": str(a.id),
                "severity": a.severity,
                "title": a.title,
                "description": a.description[:200] if a.description else "",
                "alert_type": a.alert_type,
                "delta_pct": a.delta_pct,
                "is_acknowledged": a.is_acknowledged,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts_result.scalars().all()
        ]
    except Exception:
        recent_alerts = []

    return success({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "exposure": {
            "contracts": exposure_list,
            "totals": {
                "total_annual_pnl": round(total_pnl, 0),
                "total_mtm": round(total_mtm, 0),
                "contracts_in_money": in_money,
                "contracts_out_of_money": out_money,
            },
        },
        "recent_alerts": recent_alerts,
    })


@router.get("/alerts")
async def list_alerts(
    severity: str = Query(""),
    acknowledged: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List market alerts for the user's contracts."""
    from sqlalchemy import func
    from app.models.contractiq_models import ContractIQMarketAlert

    query = (
        select(ContractIQMarketAlert)
        .join(ContractIQContract)
        .where(ContractIQContract.user_id == user.id)
    )

    if severity:
        query = query.where(ContractIQMarketAlert.severity == severity)
    if acknowledged == "true":
        query = query.where(ContractIQMarketAlert.is_acknowledged.is_(True))
    elif acknowledged == "false":
        query = query.where(ContractIQMarketAlert.is_acknowledged.is_(False))

    count_q = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_q) or 0

    query = query.order_by(ContractIQMarketAlert.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    alerts = result.scalars().all()

    data = [
        {
            "id": str(a.id),
            "contract_id": str(a.contract_id),
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "description": a.description,
            "contract_field": a.contract_field,
            "contract_value": a.contract_value,
            "market_value": a.market_value,
            "delta_pct": a.delta_pct,
            "is_acknowledged": a.is_acknowledged,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]
    return JSONResponse(content={"data": data, "error": None, "meta": {"total": total, "limit": limit, "offset": offset}})


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Mark a market alert as acknowledged."""
    from datetime import datetime, timezone
    from sqlalchemy import update as sql_update
    from app.models.contractiq_models import ContractIQMarketAlert

    # Verify the alert belongs to the user's contracts
    alert = await db.execute(
        select(ContractIQMarketAlert)
        .join(ContractIQContract)
        .where(ContractIQMarketAlert.id == alert_id, ContractIQContract.user_id == user.id)
    )
    if not alert.scalar_one_or_none():
        return error("Alert not found", 404)

    await db.execute(
        sql_update(ContractIQMarketAlert).where(ContractIQMarketAlert.id == alert_id).values(
            is_acknowledged=True,
            acknowledged_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return success({"acknowledged": True})


# ─── Market Simulation & Stress Test ─────────────────────────────────────

@router.post("/simulate")
async def run_simulation(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run a market simulation / stress test on a contract or the full portfolio."""
    sim_type = body.get("simulation_type", "full_stress_test")
    contract_id = body.get("contract_id")
    params = body.get("parameters") or {}
    news = body.get("news_headlines") or []

    from sqlalchemy import func as sqlfunc
    if contract_id:
        cq = await db.execute(
            select(ContractIQContract).where(
                ContractIQContract.id == uuid.UUID(contract_id),
                ContractIQContract.user_id == user.id,
            )
        )
        contract = cq.scalar_one_or_none()
        if not contract:
            return error("Contract not found", 404)
        scope_desc = f"contract '{contract.title}'"
    else:
        count = await db.scalar(
            select(sqlfunc.count()).select_from(ContractIQContract).where(
                ContractIQContract.user_id == user.id,
            )
        )
        scope_desc = f"full portfolio ({count} contracts)"

    # Build portfolio context for the agent
    portfolio_contracts = (await db.execute(
        select(ContractIQContract).where(ContractIQContract.user_id == user.id)
    )).scalars().all()
    portfolio_lines = []
    for pc in portfolio_contracts:
        s = pc.extraction_summary or {}
        portfolio_lines.append(
            f"- {pc.title} ({pc.contract_type}): {pc.counterparty_a} → {pc.counterparty_b}, "
            f"Capacity: {pc.total_capacity_mw or '?'} MW, Value: {pc.contract_value}, "
            f"Risk: {s.get('overall_risk_score', '?')}, Status: {pc.status.value if hasattr(pc.status, 'value') else pc.status}, "
            f"Effective: {pc.effective_date} → {pc.expiry_date}"
        )
    portfolio_ctx = "\n".join(portfolio_lines) if portfolio_lines else "No contracts in portfolio."

    query = f"""Run a {sim_type} simulation on {scope_desc}.

=== PORTFOLIO DATA ===
{portfolio_ctx}

Simulation parameters: {json.dumps(params)}

{"News headlines for sentiment analysis: " + json.dumps(news) if news else ""}

Instructions:
1. Use the portfolio data above as the basis for the simulation
2. Based on simulation_type:
   - weather_impact: Run weather_simulator for each asset location, compute energy yield impact
   - price_sensitivity: Use scenario_planner to sweep price parameters (±20% in 5 steps)
   - monte_carlo: Use risk_analyzer for 1000-iteration Monte Carlo on NPV/revenue
   - sentiment_impact: Use sentiment_analyzer on the provided headlines, adjust risk premiums
   - full_stress_test: Run ALL of the above in sequence, build a combined risk DAG
3. Use financial_calculator for NPV/IRR computations
4. Use graph_builder to create the scenario dependency DAG
5. Return structured JSON with ALL results"""

    from abenix_sdk import Abenix, ActingSubject
    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        return error("CONTRACTIQ_ABENIX_API_KEY not configured", 503)

    subject = ActingSubject(
        subject_type="contractiq",
        subject_id=str(user.id),
        email=user.email,
        display_name=user.full_name,
    )

    try:
        async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=600.0) as forge:
            result = await forge.execute("contractiq-market-simulator", query)

            # Robust parse — agents commonly emit prose before/after the JSON
            # and wrap it in ```json fences. Try fenced extraction first, then
            # outermost brace span, then keep raw_output as a last resort.
            sim_result = None
            out = result.output or ""
            cleaned = out.strip()
            try:
                m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", cleaned)
                if m:
                    cleaned = m.group(1).strip()
                try:
                    sim_result = json.loads(cleaned)
                except json.JSONDecodeError:
                    s, e = cleaned.find("{"), cleaned.rfind("}")
                    if s != -1 and e > s:
                        sim_result = json.loads(cleaned[s:e + 1])
            except Exception as parse_err:
                logger.warning("simulate: agent output failed to parse — %s", parse_err)
                sim_result = None
            if sim_result is None:
                # Surface clean payload + raw so the frontend can choose.
                sim_result = {"raw_output": out, "parse_error": "Agent output was not valid JSON"}

            return success({
                "simulation_type": sim_type,
                "scope": scope_desc,
                "results": sim_result,
                "model": result.model,
                "duration_ms": result.duration_ms,
                "cost": result.cost,
                "tool_calls": len(result.tool_calls),
            })

    except Exception as e:
        import traceback
        logger.error("Simulation error: %s\n%s", repr(e), traceback.format_exc())
        return error(f"Simulation failed: {repr(e)}", 503)
