"""Endur / ETRM JSON deal template CRUD + LLM-driven generation."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.routers.auth import get_contractiq_user, tenant_id_for
from app.models.contractiq_models import (
    ContractIQContract,
    ContractIQClause,
    ContractIQDealTemplate,
    ContractIQUser,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq", tags=["contractiq-templates"])


CATEGORIES = [
    "power_physical",
    "power_physical_deal_fee",
    "power_european_option_phys",
    "power_financial_swap",
    "power_asian_option_financial",
    "power_option_strategy",
    "commodity_physical_gas",
    "commodity_fees",
    "commodity_physical_certificate",
    # Three extras commonly seen in real Endur catalogs.
    "power_swap",
    "lng_tolling",
    "interconnector_capacity",
]

CATEGORY_LABEL = {
    "power_physical":                "Power Physical",
    "power_physical_deal_fee":       "Power Physical · Deal Fee",
    "power_european_option_phys":    "Power European Option · Phys underlying",
    "power_financial_swap":          "Power Financial Swap",
    "power_asian_option_financial":  "Power Asian Option · Financial underlying",
    "power_option_strategy":         "Power Option Strategy (Straddle / Floor / Collar / …)",
    "commodity_physical_gas":        "Commodity Physical (Gas)",
    "commodity_fees":                "Commodity Fees",
    "commodity_physical_certificate":"Commodity Physical (Certificate)",
    "power_swap":                    "Power Swap",
    "lng_tolling":                   "LNG Tolling Service",
    "interconnector_capacity":       "Interconnector Capacity",
}


# ─── Starter templates (pre-seeded on startup) ────────────────────────
# Use ${placeholders} so users see how the LLM resolves them. Keep
# field names close to what Endur 24.x ships.

STARTER_TEMPLATES: dict[str, dict] = {
    "power_physical": {
        "deal_type": "Power Physical",
        "deal_id": "${deal_id}",
        "trade_date": "${trade_date}",
        "buyer": "${counterparty_a}",
        "seller": "${counterparty_b}",
        "delivery_period": {"start": "${effective_date}", "end": "${expiry_date}"},
        "delivery_point": "${delivery_point}",
        "volume": {"shape": "${volume_shape}", "mwh_per_period": "${volume_mwh}"},
        "price": {"type": "${price_type}", "value": "${price_value}", "currency": "${currency}", "indexation": "${indexation}"},
        "settlement": "${settlement_type}",
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "power_physical_deal_fee": {
        "deal_type": "Power Physical · Deal Fee",
        "parent_deal_id": "${parent_deal_id}",
        "fee_type": "${fee_type}",
        "fee_basis": "${fee_basis}",
        "fee_rate": {"value": "${fee_rate}", "currency": "${currency}", "unit": "${fee_unit}"},
        "frequency": "${fee_frequency}",
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "power_european_option_phys": {
        "deal_type": "Power European Option (Physical)",
        "deal_id": "${deal_id}",
        "buyer": "${counterparty_a}",
        "seller": "${counterparty_b}",
        "option_type": "${option_type}",
        "exercise_style": "European",
        "strike": {"value": "${strike}", "currency": "${currency}"},
        "expiry": "${option_expiry}",
        "underlying": {"commodity": "Power", "delivery_point": "${delivery_point}", "volume_mwh": "${volume_mwh}"},
        "premium": {"value": "${premium_value}", "currency": "${currency}", "payment_date": "${premium_payment_date}"},
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "power_financial_swap": {
        "deal_type": "Power Financial Swap",
        "deal_id": "${deal_id}",
        "buyer": "${counterparty_a}",
        "seller": "${counterparty_b}",
        "trade_date": "${trade_date}",
        "tenor": {"start": "${effective_date}", "end": "${expiry_date}"},
        "fixed_leg": {"price": "${fixed_price}", "currency": "${currency}", "volume_mwh": "${volume_mwh}"},
        "float_leg": {"index": "${float_index}", "publication": "${float_publication}", "volume_mwh": "${volume_mwh}"},
        "settlement_dates": "${settlement_dates}",
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "power_asian_option_financial": {
        "deal_type": "Power Asian Option (Financial)",
        "deal_id": "${deal_id}",
        "buyer": "${counterparty_a}",
        "seller": "${counterparty_b}",
        "option_type": "${option_type}",
        "exercise_style": "Asian",
        "averaging_method": "${averaging_method}",
        "averaging_dates": "${averaging_dates}",
        "strike": {"value": "${strike}", "currency": "${currency}"},
        "premium": {"value": "${premium_value}", "currency": "${currency}", "payment_date": "${premium_payment_date}"},
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "power_option_strategy": {
        "deal_type": "Power Option Strategy",
        "strategy_type": "${strategy_type}",
        "child_deals": [
            {"role": "${role_1}", "deal": "${child_deal_1}"},
            {"role": "${role_2}", "deal": "${child_deal_2}"}
        ],
        "net_premium": {"value": "${net_premium}", "currency": "${currency}"},
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "commodity_physical_gas": {
        "deal_type": "Commodity Physical (Gas)",
        "deal_id": "${deal_id}",
        "buyer": "${counterparty_a}",
        "seller": "${counterparty_b}",
        "delivery_point": "${delivery_point}",
        "delivery_period": {"start": "${effective_date}", "end": "${expiry_date}"},
        "volume": {"unit": "${volume_unit}", "value": "${volume_value}"},
        "price": {"type": "${price_type}", "value": "${price_value}", "currency": "${currency}", "indexation": "${indexation}"},
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "commodity_fees": {
        "deal_type": "Commodity Fees",
        "parent_deal_id": "${parent_deal_id}",
        "fee_components": [
            {"name": "${fee_name_1}", "rate": "${fee_rate_1}", "currency": "${currency}", "basis": "${fee_basis_1}"},
        ],
        "billing_frequency": "${billing_frequency}",
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "commodity_physical_certificate": {
        "deal_type": "Commodity Physical (Certificate)",
        "deal_id": "${deal_id}",
        "buyer": "${counterparty_a}",
        "seller": "${counterparty_b}",
        "certificate_type": "${certificate_type}",
        "registry": "${registry}",
        "vintage": "${vintage}",
        "volume_mwh": "${volume_mwh}",
        "price": {"value": "${price_per_certificate}", "currency": "${currency}"},
        "delivery_window": {"start": "${effective_date}", "end": "${expiry_date}"},
        "bundled": "${bundled}",
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "power_swap": {
        "deal_type": "Power Swap",
        "fixed_leg": {"price": "${fixed_price}", "volume_mwh": "${volume_mwh}", "currency": "${currency}"},
        "float_leg": {"index": "${float_index}", "volume_mwh": "${volume_mwh}"},
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "lng_tolling": {
        "deal_type": "LNG Tolling",
        "tolling_party": "${counterparty_a}",
        "operator": "${counterparty_b}",
        "facility": "${facility}",
        "annual_capacity_mtpa": "${capacity_mtpa}",
        "tolling_fee": {"value": "${tolling_fee}", "currency": "${currency}", "unit": "${fee_unit}"},
        "tenor": {"start": "${effective_date}", "end": "${expiry_date}"},
        "take_or_pay_pct": "${take_or_pay_pct}",
        "make_up_rights": "${make_up_rights}",
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
    "interconnector_capacity": {
        "deal_type": "Interconnector Capacity",
        "buyer": "${counterparty_a}",
        "seller": "${counterparty_b}",
        "interconnector": "${interconnector}",
        "direction": "${direction}",
        "capacity_mw": "${capacity_mw}",
        "tenor": {"start": "${effective_date}", "end": "${expiry_date}"},
        "reserve_price": {"value": "${reserve_price}", "currency": "${currency}"},
        "use_it_or_lose_it": "${uiolo}",
        "external_refs": {"contract_id": "${contract_id}", "clause_refs": "${clause_refs}"},
    },
}


async def ensure_starters(db: AsyncSession, user_id: uuid.UUID) -> None:
    """One-time per-user pre-seed of starter templates. Idempotent —
    only inserts categories the user doesn't already own."""
    existing = (await db.execute(
        select(ContractIQDealTemplate.category)
        .where(ContractIQDealTemplate.user_id == user_id)
        .where(ContractIQDealTemplate.is_starter.is_(True))
    )).scalars().all()
    have = set(existing)
    for cat, payload in STARTER_TEMPLATES.items():
        if cat in have:
            continue
        db.add(ContractIQDealTemplate(
            user_id=user_id,
            category=cat,
            name=f"Starter · {CATEGORY_LABEL.get(cat, cat)}",
            description=f"Default Endur skeleton for {CATEGORY_LABEL.get(cat, cat)}. Replace with your tenant-specific shape via the upload modal.",
            template_json=payload,
            is_starter=True,
        ))
    await db.commit()


# ─── CRUD ─────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await ensure_starters(db, user.id)
    rows = (await db.execute(
        select(ContractIQDealTemplate).where(ContractIQDealTemplate.user_id == user.id)
        .order_by(ContractIQDealTemplate.category, ContractIQDealTemplate.is_starter.desc(), ContractIQDealTemplate.name)
    )).scalars().all()
    out = [
        {
            "id": str(t.id),
            "category": t.category,
            "category_label": CATEGORY_LABEL.get(t.category, t.category),
            "name": t.name,
            "description": t.description,
            "field_count": _count_placeholders(t.template_json),
            "template_json": t.template_json,
            "is_starter": t.is_starter,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in rows
    ]
    return JSONResponse({"data": {
        "templates": out,
        "categories": [{"key": k, "label": CATEGORY_LABEL[k]} for k in CATEGORIES],
    }})


@router.post("/templates")
async def create_template(
    body: dict[str, Any],
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    cat = (body.get("category") or "").strip()
    if cat not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of: {', '.join(CATEGORIES)}")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    tpl = body.get("template_json")
    if not isinstance(tpl, (dict, list)):
        raise HTTPException(status_code=400, detail="template_json must be an object or array")
    row = ContractIQDealTemplate(
        user_id=user.id,
        category=cat,
        name=name[:200],
        description=(body.get("description") or None),
        template_json=tpl,
        is_starter=False,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return JSONResponse({"data": {"id": str(row.id), "category": row.category, "name": row.name}}, status_code=201)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (await db.execute(
        select(ContractIQDealTemplate)
        .where(ContractIQDealTemplate.id == template_id)
        .where(ContractIQDealTemplate.user_id == user.id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(row)
    await db.commit()
    return JSONResponse({"data": {"deleted": str(template_id)}})


# ─── LLM-driven population ────────────────────────────────────────────

@router.post("/generate-endur-json")
async def generate_endur_json(
    body: dict[str, Any],
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Populate a template using a contract's deal cluster + clauses."""
    tpl_id = body.get("template_id")
    contract_id = body.get("contract_id")
    cluster_key = body.get("cluster_key")
    if not tpl_id or not contract_id:
        raise HTTPException(status_code=400, detail="template_id and contract_id are required")

    template = (await db.execute(
        select(ContractIQDealTemplate)
        .where(ContractIQDealTemplate.id == uuid.UUID(tpl_id))
        .where(ContractIQDealTemplate.user_id == user.id)
    )).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Tenant filter goes on the SELECT itself — admin from tenant B must never
    # be able to load a contract from tenant A even before the user_id check.
    contract = (await db.execute(
        select(ContractIQContract)
        .where(ContractIQContract.id == uuid.UUID(contract_id))
        .where(ContractIQContract.tenant_id == tenant_id_for(user))
    )).scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if user.role.value != "admin" and contract.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Pull the cluster + clauses to give the agent enough context.
    # `deal_clusters` lives inside `extraction_summary`, not on the
    # contract directly.
    summary = contract.extraction_summary or {}
    deal_clusters = summary.get("deal_clusters") or {}
    cluster_data = (
        deal_clusters.get(cluster_key)
        if cluster_key and isinstance(deal_clusters, dict)
        else deal_clusters
    )
    clauses = (await db.execute(
        select(ContractIQClause).where(ContractIQClause.contract_id == contract.id)
    )).scalars().all()
    clause_payload = [
        {
            "id": str(c.id),
            "number": c.clause_number,
            "title": c.clause_title,
            "type": c.clause_type.value if hasattr(c.clause_type, "value") else str(c.clause_type),
            "text": (c.clause_text or "")[:600],
        }
        for c in clauses
    ]

    # The Endur deal-template-filler agent (YAML in packages/db/seeds/agents/
    # contractiq_endur_template_filler.yaml) owns the system prompt + structured
    # output schema. Router just supplies the payload below.
    payload = {
        "template": template.template_json,
        "contract": {
            "id": str(contract.id),
            "title": contract.title,
            "counterparty_a": contract.counterparty_a,
            "counterparty_b": contract.counterparty_b,
            "effective_date": contract.effective_date.isoformat() if contract.effective_date else None,
            "expiry_date": contract.expiry_date.isoformat() if contract.expiry_date else None,
            "contract_type": contract.contract_type,
        },
        "cluster_key": cluster_key,
        "cluster": cluster_data,
        "clauses": clause_payload,
    }

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))
    from abenix_sdk import Abenix, ActingSubject  # type: ignore[import-not-found]
    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        raise HTTPException(status_code=500, detail="CONTRACTIQ_ABENIX_API_KEY not configured")
    subject = ActingSubject(
        subject_type="contractiq", subject_id=str(user.id),
        email=user.email, display_name=user.full_name,
    )
    # Call the dedicated Abenix agent
    # `contractiq-endur-template-filler` (YAML in
    # packages/db/seeds/agents/). It owns the prompt + tool budget +
    # structured output schema; ContractIQ stays a thin client.
    try:
        async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=180.0) as forge:
            result = await forge.execute(
                "contractiq-endur-template-filler",
                json.dumps(payload, default=str),
            )
    except Exception as exc:
        logger.exception("generate-endur-json failed")
        raise HTTPException(status_code=502, detail=f"Agent call failed: {exc}")

    raw = getattr(result, "output", None)
    populated_json: Any = None
    unfilled: list = []
    provenance: dict = {}
    summary_text: str = ""
    parse_error: str | None = None

    parsed: Any = None
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        s = raw.strip()
        # Strip ```json fences if the agent wrapped its output. Use a
        # robust regex so we don't mangle the body when the closing fence
        # is absent or there's leading prose.
        m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", s)
        if m:
            s = m.group(1).strip()
        elif s.startswith("```"):
            s = re.sub(r"^```(?:json)?\s*\n?", "", s).strip()
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            # Try the outermost brace span — handles trailing prose.
            try:
                start, end = s.find("{"), s.rfind("}")
                if start != -1 and end > start:
                    parsed = json.loads(s[start:end + 1])
            except json.JSONDecodeError:
                parsed = None
                parse_error = "Agent output was not valid JSON. The model may have truncated or returned prose."

    if isinstance(parsed, dict):
        populated_json = parsed.get("populated_json")
        unfilled = parsed.get("_unfilled") or []
        provenance = parsed.get("_provenance") or {}
        summary_text = parsed.get("summary") or ""

    # ── Validation: a populated_json that still has ${...} placeholders or
    # weird key artifacts (e.g. fragments like '-300">') is broken output.
    # Reject it instead of rendering garbage to the user.
    def _walk_strings(obj: Any):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                yield k
                yield from _walk_strings(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _walk_strings(v)

    if populated_json is not None:
        bad_key = False
        leftover_placeholders: list[str] = []
        for s in _walk_strings(populated_json):
            if "${" in s and "}" in s:
                # Track every leftover ${name} so the UI can list them.
                for ph in re.findall(r"\$\{([^}]+)\}", s):
                    if ph not in leftover_placeholders:
                        leftover_placeholders.append(ph)
            # Heuristic: real Endur keys never contain '">' or '<' or
            # raw HTML-escape fragments. If we see one we've got mangled
            # output (the screenshot bug — '-300">' creeping into keys).
            if any(tok in s for tok in ('">', '<"', "</", "&quot;")):
                bad_key = True
        if bad_key:
            logger.warning("generate-endur-json: rejected populated_json with mangled keys")
            parse_error = (
                "The agent returned malformed JSON (HTML-escape fragments in keys). "
                "Re-run, or open Executions in Abenix to inspect the raw output."
            )
            populated_json = None
        elif leftover_placeholders:
            # Promote them into `unfilled` so the UI shows them as expected.
            for ph in leftover_placeholders:
                if ph not in unfilled:
                    unfilled.append(ph)

    # Surface the agent's tool-call trace to the UI so analysts
    # (and the CxO) can see exactly which tools fired and what
    # they returned. The SDK exposes this as result.tool_calls.
    tool_calls = getattr(result, "tool_calls", None) or []
    trace = []
    for t in tool_calls:
        if not isinstance(t, dict):
            continue
        trace.append({
            "name": t.get("name"),
            "arguments": t.get("arguments"),
            "duration_ms": t.get("duration_ms"),
            "result_preview": (
                (t.get("result") or "")[:240]
                if isinstance(t.get("result"), str)
                else (json.dumps(t.get("result"))[:240] if t.get("result") is not None else None)
            ),
        })

    return JSONResponse({"data": {
        "template_id": str(template.id),
        "category": template.category,
        "category_label": CATEGORY_LABEL.get(template.category, template.category),
        "contract_id": str(contract.id),
        "cluster_key": cluster_key,
        "populated_json": populated_json,
        "unfilled": unfilled,
        "provenance": provenance,
        "summary": summary_text,
        "tool_calls": trace,
        "cost_usd": getattr(result, "cost", 0.0),
        "duration_ms": getattr(result, "duration_ms", 0),
        "agent_slug": "contractiq-endur-template-filler",
        "parse_error": parse_error,
        # Keep `raw` only when parsing failed so the UI can show what
        # the agent actually said.
        "raw_output": raw if populated_json is None else None,
    }})


def _count_placeholders(obj: Any) -> int:
    if isinstance(obj, str):
        return 1 if obj.startswith("${") and obj.endswith("}") else 0
    if isinstance(obj, dict):
        return sum(_count_placeholders(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_placeholders(x) for x in obj)
    return 0
