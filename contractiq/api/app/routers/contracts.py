"""ContractIQ — Contract management and extraction API."""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Query, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, SessionLocal
from app.core.responses import error, success
from app.routers.auth import get_contractiq_user, tenant_id_for

from app.models.contractiq_models import (
    ContractIQContract, ContractIQUser, ContractIQExtractedData,
    ContractIQClause, ContractIQAsset, ContractIQEvent,
    ContractIQRiskAnalysis, ContractStatus, ClauseType, RiskLevel, ContractIQExtractionTaxonomy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contractiq", tags=["contractiq"])


@router.get("/contracts")
async def list_contracts(
    search: str = Query("", max_length=255),
    contract_type: str = Query(""),
    status: str = Query(""),
    sort: str = Query("newest"),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """List contracts. Tenant scope is enforced for every role — admins see
    every contract within their own tenant, analysts see only their own."""
    tid = tenant_id_for(user)
    # Tenant filter is applied unconditionally. This is the hard wall — an
    # admin token from tenant B must never see tenant A's contracts. The
    # user_id filter for non-admins narrows further WITHIN the tenant.
    query = select(ContractIQContract).where(ContractIQContract.tenant_id == tid)

    if user.role.value != "admin":
        query = query.where(ContractIQContract.user_id == user.id)

    if search:
        from sqlalchemy import or_
        query = query.where(or_(
            ContractIQContract.title.ilike(f"%{search}%"),
            ContractIQContract.counterparty_a.ilike(f"%{search}%"),
            ContractIQContract.counterparty_b.ilike(f"%{search}%"),
        ))
    if contract_type:
        query = query.where(ContractIQContract.contract_type == contract_type)
    if status:
        query = query.where(ContractIQContract.status == status)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_q) or 0

    # Sort
    if sort == "oldest":
        query = query.order_by(ContractIQContract.created_at.asc())
    elif sort == "name":
        query = query.order_by(ContractIQContract.title.asc())
    elif sort == "risk":
        query = query.order_by(ContractIQContract.risk_score.desc().nullslast())
    else:
        query = query.order_by(ContractIQContract.created_at.desc())

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    contracts = result.scalars().all()

    data = [
        {
            "id": str(c.id),
            "title": c.title,
            "contract_type": c.contract_type.value if c.contract_type else None,
            "status": c.status.value if c.status else None,
            "counterparty_a": c.counterparty_a,
            "counterparty_b": c.counterparty_b,
            "effective_date": c.effective_date.isoformat() if c.effective_date else None,
            "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
            "risk_score": c.risk_score,
            "total_capacity_mw": c.total_capacity_mw,
            "page_count": c.page_count,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in contracts
    ]

    return JSONResponse(content={"data": data, "error": None, "meta": {"total": total, "limit": limit, "offset": offset}})


@router.post("/contracts")
async def create_contract(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a new contract record (before uploading the file)."""
    contract = ContractIQContract(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant_id_for(user),
        contract_type=body.get("contract_type", "ppa"),
        title=body.get("title", "Untitled Contract"),
        counterparty_a=body.get("counterparty_a"),
        counterparty_b=body.get("counterparty_b"),
        currency=body.get("currency", "USD"),
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)

    return success({
        "id": str(contract.id),
        "title": contract.title,
        "status": contract.status.value,
    })


@router.post("/contracts/upload")
async def upload_contract(
    file: UploadFile = File(...),
    title: str = Form(...),
    contract_type: str = Form("ppa"),
    counterparty_a: str = Form(""),
    counterparty_b: str = Form(""),
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Upload a contract file (PDF or text) and create a contract record."""
    if not file.filename:
        return error("No file provided", 400)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("pdf", "txt", "text", "doc", "docx"):
        return error("Unsupported file type. Use PDF, TXT, or DOC.", 400)

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        return error("File too large (max 50MB)", 400)

    # Extract text from file
    if ext in ("txt", "text"):
        file_text = content.decode("utf-8", errors="replace")
    elif ext == "pdf":
        try:
            import io
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(content))
            file_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            file_text = content.decode("utf-8", errors="replace")
    else:
        file_text = content.decode("utf-8", errors="replace")

    page_count = max(1, len(file_text) // 3000)  # Rough page estimate

    contract = ContractIQContract(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant_id_for(user),
        contract_type=contract_type,
        title=title,
        counterparty_a=counterparty_a or None,
        counterparty_b=counterparty_b or None,
        original_filename=file.filename,
        page_count=page_count,
        status=ContractStatus.UPLOADED,
        currency="USD",
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)

    # Store raw text as extraction summary for later processing
    contract.extraction_summary = {"raw_text_length": len(file_text), "raw_text": file_text[:200000]}
    await db.commit()

    return success({
        "id": str(contract.id),
        "title": contract.title,
        "status": contract.status.value,
        "page_count": page_count,
        "file_size": len(content),
    })


# ── Self-learning taxonomy helpers ──────────────────────────────────

async def _build_taxonomy_hint(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Return a string to prepend to the contract text that tells the"""
    try:
        rows = (await db.execute(
            select(ContractIQExtractionTaxonomy)
            .where(ContractIQExtractionTaxonomy.user_id == user_id)
            .order_by(ContractIQExtractionTaxonomy.usage_count.desc())
            .limit(200)
        )).scalars().all()
    except Exception:
        return ""
    if not rows:
        return ""
    # Bucket by type for a clean prompt
    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r.taxonomy_type, []).append(r)

    lines = ["=== DISCOVERED TAXONOMY FROM YOUR PORTFOLIO ==="]
    lines.append("Use these EXACT keys in the JSON output when the same concept appears.")
    lines.append("Only invent a new key when no existing one applies.\n")

    clusters = by_type.get("cluster") or []
    if clusters:
        lines.append("Deal cluster keys already in your vocabulary:")
        for r in clusters[:25]:
            legs = (r.taxonomy_metadata or {}).get("example_legs") or []
            leg_s = f" [legs: {', '.join(legs[:4])}]" if legs else ""
            desc = (r.description or "")[:80]
            lines.append(f"  - {r.key}{leg_s} — {desc} (seen {r.usage_count}x)")

    legs_all = by_type.get("leg") or []
    if legs_all:
        lines.append("\nDeal leg keys already in your vocabulary:")
        for r in legs_all[:40]:
            parent = (r.taxonomy_metadata or {}).get("parent_cluster")
            p = f" ({parent})" if parent else ""
            lines.append(f"  - {r.key}{p}")

    # Field types per extraction area
    for area in ("commercial_terms", "technical_data", "legal_terms",
                 "financial_terms", "operational_terms"):
        ftype = f"field:{area}"
        fields = by_type.get(ftype) or []
        if fields:
            lines.append(f"\nField names you've used in {area}:")
            for r in fields[:30]:
                t = (r.taxonomy_metadata or {}).get("field_type") or ""
                lines.append(f"  - {r.key}" + (f" ({t})" if t else ""))

    lines.append("\n=== END TAXONOMY ===\n")
    return "\n".join(lines)


async def _learn_taxonomy(
    db: AsyncSession,
    user_id: uuid.UUID,
    contract_id: uuid.UUID,
    parsed: dict,
) -> dict:
    """Upsert every cluster/leg/field discovered in this extraction so the"""
    summary = {"clusters_new": 0, "clusters_updated": 0,
               "legs_new": 0, "legs_updated": 0,
               "fields_new": 0, "fields_updated": 0}

    async def _upsert(ttype: str, key: str, description: str | None, metadata: dict | None) -> str:
        """Returns 'new' or 'updated'."""
        existing = (await db.execute(
            select(ContractIQExtractionTaxonomy).where(
                ContractIQExtractionTaxonomy.user_id == user_id,
                ContractIQExtractionTaxonomy.taxonomy_type == ttype,
                ContractIQExtractionTaxonomy.key == key,
            )
        )).scalar_one_or_none()
        if existing:
            existing.usage_count = (existing.usage_count or 0) + 1
            existing.last_seen_at = datetime.now(timezone.utc)
            # Merge metadata (union of example lists)
            if metadata and isinstance(metadata, dict):
                cur = dict(existing.taxonomy_metadata or {})
                for k, v in metadata.items():
                    if isinstance(v, list):
                        cur[k] = sorted(set((cur.get(k) or []) + list(v)))
                    else:
                        cur.setdefault(k, v)
                existing.taxonomy_metadata = cur
            if description and not existing.description:
                existing.description = description[:500]
            return "updated"
        else:
            db.add(ContractIQExtractionTaxonomy(
                user_id=user_id,
                taxonomy_type=ttype,
                key=key[:120],
                description=(description or None) and str(description)[:500],
                taxonomy_metadata=metadata,
                usage_count=1,
                first_seen_contract_id=contract_id,
            ))
            return "new"

    # Deal clusters + their legs
    for cluster_key, cluster_body in (parsed.get("deal_clusters") or {}).items():
        if not isinstance(cluster_body, dict):
            continue
        legs = (cluster_body.get("deal_legs") or {}) if isinstance(cluster_body.get("deal_legs"), dict) else {}
        res = await _upsert(
            "cluster", cluster_key,
            cluster_body.get("description"),
            {"example_legs": list(legs.keys())},
        )
        summary[f"clusters_{res}"] = summary.get(f"clusters_{res}", 0) + 1
        for leg_key, leg_body in legs.items():
            sample_fields = list(leg_body.keys()) if isinstance(leg_body, dict) else []
            res = await _upsert(
                "leg", leg_key, None,
                {"parent_cluster": cluster_key, "sample_fields": sample_fields},
            )
            summary[f"legs_{res}"] = summary.get(f"legs_{res}", 0) + 1

    # Dynamic fields across the 5 extraction arrays
    for area in ("commercial_terms", "technical_data", "legal_terms",
                 "financial_terms", "operational_terms"):
        for item in (parsed.get(area) or []):
            if not isinstance(item, dict):
                continue
            fname = item.get("field")
            if not fname or not isinstance(fname, str):
                continue
            res = await _upsert(
                f"field:{area}", fname, None,
                {"field_type": item.get("type")},
            )
            summary[f"fields_{res}"] = summary.get(f"fields_{res}", 0) + 1

    try:
        await db.commit()
    except Exception as e:
        logger.exception("taxonomy commit failed: %s", e)
        await db.rollback()
    return summary


def _parse_extraction_json(text: str) -> dict | None:
    """Extract JSON from LLM response that may have markdown wrapping."""
    if not text or not text.strip():
        return None
    cleaned = text.strip()

    # Strategy 1: greedy capture between ``` markers — matches up to the LAST ```
    m = re.search(r"```(?:json)?\s*\n?([\s\S]*)```", cleaned)
    if m:
        cleaned = m.group(1).strip()
    elif cleaned.startswith("```"):
        # Truncated response — no closing ```, strip the opening marker
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned).strip()

    # `strict=False` tolerates raw control chars (newlines, tabs) inside
    # quoted strings — gemini emits multi-line strings without escaping the
    # newlines, which standard json.loads rejects.
    last_err: json.JSONDecodeError | None = None
    last_payload: str = ""

    def _loads(s: str):
        nonlocal last_err, last_payload
        try:
            return json.loads(s, strict=False)
        except json.JSONDecodeError as e:
            last_err = e
            last_payload = s
            raise

    # Strategy 2: direct parse
    try:
        return _loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy 3: outermost { … } in the cleaned text
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return _loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Strategy 4: outermost { … } in the original text (in case stripping mangled it)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return _loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Strategy 5: tolerate trailing commas in objects/arrays — gemini emits them
    # under load when output_tokens are tight. Strip them and retry.
    for candidate in (cleaned, text):
        s = candidate.find("{")
        e = candidate.rfind("}")
        if s == -1 or e <= s:
            continue
        slice_ = candidate[s:e + 1]
        slice_ = re.sub(r",(\s*[}\]])", r"\1", slice_)
        try:
            return _loads(slice_)
        except json.JSONDecodeError:
            continue

    # Strategy 6: last-resort tolerant repair — handles unquoted values,
    # missing commas, smart quotes, comments, and other common LLM JSON
    # mistakes that standard json.loads rejects.
    try:
        from json_repair import repair_json
        for candidate in (cleaned, text):
            s = candidate.find("{")
            e = candidate.rfind("}")
            if s == -1 or e <= s:
                continue
            repaired = repair_json(candidate[s:e + 1], return_objects=True)
            if isinstance(repaired, dict) and repaired:
                return repaired
    except Exception as repair_err:
        logger.warning("json-repair fallback failed: %s", repair_err)

    if last_err is not None and last_payload:
        pos = last_err.pos
        ctx_start = max(0, pos - 120)
        ctx_end = min(len(last_payload), pos + 120)
        logger.error(
            "JSON parse failure at line %d col %d pos %d: %s; CONTEXT=%r",
            last_err.lineno, last_err.colno, pos, last_err.msg,
            last_payload[ctx_start:ctx_end],
        )

    return None


def _parse_date(date_str: str) -> datetime | None:
    """Parse a date string, ensuring it's timezone-aware."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


CLAUSE_TYPE_MAP = {
    "termination": ClauseType.TERMINATION,
    "force_majeure": ClauseType.FORCE_MAJEURE,
    "pricing": ClauseType.PRICING,
    "payment": ClauseType.PAYMENT,
    "performance_guarantee": ClauseType.PERFORMANCE_GUARANTEE,
    "curtailment": ClauseType.CURTAILMENT,
    "change_of_law": ClauseType.CHANGE_OF_LAW,
    "insurance": ClauseType.INSURANCE,
    "indemnity": ClauseType.INDEMNITY,
    "dispute_resolution": ClauseType.DISPUTE_RESOLUTION,
    "assignment": ClauseType.ASSIGNMENT,
    "confidentiality": ClauseType.CONFIDENTIALITY,
    "other": ClauseType.OTHER,
}

RISK_LEVEL_MAP = {
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "critical": RiskLevel.CRITICAL,
}


@router.post("/contracts/{contract_id}/extract")
async def extract_contract(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Run LLM-based extraction on an uploaded contract. Streams SSE progress."""
    query = (
        select(ContractIQContract)
        .where(ContractIQContract.id == contract_id)
        .where(ContractIQContract.tenant_id == tenant_id_for(user))
    )
    if user.role.value != "admin":
        query = query.where(ContractIQContract.user_id == user.id)
    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return JSONResponse(content={"data": None, "error": {"message": "Contract not found"}}, status_code=404)

    raw_text = (contract.extraction_summary or {}).get("raw_text", "")
    if not raw_text:
        return JSONResponse(content={"data": None, "error": {"message": "No text to extract — upload a file first"}}, status_code=400)

    # Use first 100K chars for extraction (Claude context limit)
    contract_text = raw_text[:100000]

    # ── Self-learning taxonomy: pull top entries the user has seen before
    # and prepend as a vocabulary hint so the agent reuses stable keys
    # across the portfolio rather than re-inventing names each time.
    taxonomy_hint = await _build_taxonomy_hint(db, user.id)
    if taxonomy_hint:
        contract_text = taxonomy_hint + "\n\n=== CONTRACT TEXT ===\n\n" + contract_text

    # Capture user fields by value — closure must not retain the request scope
    user_id = user.id
    user_email = user.email
    user_full_name = user.full_name

    import asyncio
    progress_queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()

    async def _extract_and_persist():
        """Run the agent call + parse + DB writes.

        Each DB write batch opens its own short-lived SessionLocal context.
        Holding one session across the long-running forge.execute() call
        (which takes 60-120s on real contracts) loses greenlet context on
        asyncpg and causes MissingGreenlet on subsequent writes. No ORM rows
        live across the agent call — all mutations are UPDATE statements.
        """
        from abenix_sdk import Abenix, ActingSubject

        async def emit(event: dict) -> None:
            try:
                progress_queue.put_nowait(event)
            except Exception:
                pass

        api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
        api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")

        async def _set_status(new_status: ContractStatus, summary_patch: dict | None = None) -> None:
            async with SessionLocal() as s:
                values: dict = {"status": new_status}
                if summary_patch is not None:
                    existing = (await s.execute(
                        select(ContractIQContract.extraction_summary).where(ContractIQContract.id == contract_id)
                    )).scalar_one_or_none() or {}
                    values["extraction_summary"] = {**existing, **summary_patch}
                await s.execute(
                    update(ContractIQContract).where(ContractIQContract.id == contract_id).values(**values)
                )
                await s.commit()

        try:
            await _set_status(ContractStatus.EXTRACTING)

            await emit({'event': 'status', 'agent': 'document_ingester', 'status': 'running'})
            await emit({'event': 'status', 'agent': 'commercial_extractor', 'status': 'running'})
            await emit({'event': 'status', 'agent': 'technical_extractor', 'status': 'running'})

            if not api_key:
                await _set_status(ContractStatus.ERROR)
                await emit({'event': 'error', 'message': 'CONTRACTIQ_ABENIX_API_KEY not configured on contractiq-api'})
                return

            subject = ActingSubject(
                subject_type="contractiq",
                subject_id=str(user_id),
                email=user_email,
                display_name=user_full_name,
            )
            async with Abenix(api_key=api_key, base_url=api_base, act_as=subject, timeout=600.0) as forge:
                result = await forge.execute("contractiq-extractor", contract_text[:80000])
                extraction_text = result.output or ""
                logger.info("Abenix extraction complete: %d chars, %d tool_calls, $%.4f",
                           len(extraction_text), len(result.tool_calls), result.cost)

            await emit({'event': 'status', 'agent': 'document_ingester', 'status': 'complete'})
            await emit({'event': 'status', 'agent': 'commercial_extractor', 'status': 'complete'})
            await emit({'event': 'status', 'agent': 'technical_extractor', 'status': 'complete'})

            logger.info("Extraction output: %d chars, first 200: %s", len(extraction_text), extraction_text[:200])
            parsed = _parse_extraction_json(extraction_text)
            if not parsed:
                logger.error(
                    "Failed to parse extraction JSON (%d chars). HEAD=%r TAIL=%r",
                    len(extraction_text),
                    extraction_text[:300],
                    extraction_text[-300:],
                )
                await _set_status(
                    ContractStatus.ERROR,
                    summary_patch={
                        "extraction_error": "Failed to parse LLM output",
                        "raw_output": extraction_text[:2000],
                    },
                )
                await emit({'event': 'error', 'message': 'Failed to parse extraction output'})
                return

            await emit({'event': 'status', 'agent': 'legal_extractor', 'status': 'running'})
            await emit({'event': 'status', 'agent': 'financial_extractor', 'status': 'running'})

            parties = parsed.get("parties", {})

            # Resolve final contract column values from `parties` + parsed sections.
            party_values: dict = {}
            if parties.get("counterparty_a"):
                party_values["counterparty_a"] = parties["counterparty_a"]
            if parties.get("counterparty_b"):
                party_values["counterparty_b"] = parties["counterparty_b"]
            if parties.get("total_capacity_mw"):
                try:
                    party_values["total_capacity_mw"] = float(parties["total_capacity_mw"])
                except (ValueError, TypeError):
                    pass
            if parties.get("contract_value"):
                try:
                    party_values["contract_value"] = float(parties["contract_value"])
                except (ValueError, TypeError):
                    pass
            if parties.get("currency"):
                party_values["currency"] = parties["currency"]
            if parties.get("effective_date"):
                ed_val = _parse_date(parties["effective_date"])
                if ed_val is not None:
                    party_values["effective_date"] = ed_val
            if parties.get("expiry_date"):
                exp_val = _parse_date(parties["expiry_date"])
                if exp_val is not None:
                    party_values["expiry_date"] = exp_val

            # Batch 1 — extracted_data rows (terms + definitions)
            async with SessionLocal() as s:
                for section_key in ("commercial_terms", "technical_data", "legal_terms", "financial_terms", "operational_terms"):
                    for item in parsed.get(section_key, []):
                        s.add(ContractIQExtractedData(
                            id=uuid.uuid4(),
                            contract_id=contract_id,
                            section=item.get("section", section_key),
                            field_name=item.get("field", item.get("term", "unknown")),
                            field_value=str(item.get("value", item.get("definition", ""))),
                            field_type=item.get("type", "string"),
                            confidence_score=0.85,
                            extraction_pass=1,
                        ))
                for defn in parsed.get("definitions", []):
                    s.add(ContractIQExtractedData(
                        id=uuid.uuid4(),
                        contract_id=contract_id,
                        section="definitions",
                        field_name=defn.get("term", "unknown"),
                        field_value=str(defn.get("definition", "")),
                        field_type="definition",
                        confidence_score=0.90,
                        extraction_pass=1,
                    ))
                await s.commit()

            await emit({'event': 'status', 'agent': 'legal_extractor', 'status': 'complete'})
            await emit({'event': 'status', 'agent': 'financial_extractor', 'status': 'complete'})

            # Batch 2 — clauses
            await emit({'event': 'status', 'agent': 'clause_classifier', 'status': 'running'})
            async with SessionLocal() as s:
                for clause_data in parsed.get("clauses", []):
                    ct = CLAUSE_TYPE_MAP.get(clause_data.get("type", "other"), ClauseType.OTHER)
                    rl = RISK_LEVEL_MAP.get(clause_data.get("risk_level", "low"), RiskLevel.LOW)
                    s.add(ContractIQClause(
                        id=uuid.uuid4(),
                        contract_id=contract_id,
                        clause_number=clause_data.get("number"),
                        clause_title=clause_data.get("title", "Untitled Clause"),
                        clause_text=clause_data.get("text", ""),
                        clause_type=ct,
                        risk_level=rl,
                        risk_notes=clause_data.get("risk_notes"),
                    ))
                await s.commit()
            await emit({'event': 'status', 'agent': 'clause_classifier', 'status': 'complete'})

            # Batch 3 — assets
            await emit({'event': 'status', 'agent': 'asset_registry', 'status': 'running'})
            async with SessionLocal() as s:
                for asset_data in parsed.get("assets", []):
                    cod = _parse_date(asset_data.get("cod_date", ""))
                    s.add(ContractIQAsset(
                        id=uuid.uuid4(),
                        contract_id=contract_id,
                        asset_name=asset_data.get("name", "Unknown Asset"),
                        asset_type=asset_data.get("type", "solar_plant"),
                        capacity_mw=asset_data.get("capacity_mw"),
                        location=asset_data.get("location"),
                        technology=asset_data.get("technology"),
                        cod_date=cod,
                        degradation_rate=asset_data.get("degradation_rate"),
                    ))
                await s.commit()
            await emit({'event': 'status', 'agent': 'asset_registry', 'status': 'complete'})

            # Batch 4 — events
            await emit({'event': 'status', 'agent': 'event_extractor', 'status': 'running'})
            async with SessionLocal() as s:
                for event_data in parsed.get("events", []):
                    event_date = _parse_date(event_data.get("date", ""))
                    s.add(ContractIQEvent(
                        id=uuid.uuid4(),
                        contract_id=contract_id,
                        event_type=event_data.get("type", "milestone"),
                        event_date=event_date,
                        description=event_data.get("description", ""),
                        status="upcoming" if event_date and event_date > datetime.now(timezone.utc) else "passed",
                    ))
                await s.commit()
            await emit({'event': 'status', 'agent': 'event_extractor', 'status': 'complete'})

            # Batch 5 — risks
            await emit({'event': 'status', 'agent': 'risk_analyzer', 'status': 'running'})
            risk_scores: list[float] = []
            async with SessionLocal() as s:
                for risk_data in parsed.get("risk_assessment", []):
                    try:
                        score = float(risk_data.get("score", 50))
                    except (ValueError, TypeError):
                        score = 50.0
                    risk_scores.append(score)
                    s.add(ContractIQRiskAnalysis(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id_for(user),
                        contract_id=contract_id,
                        analysis_type="single",
                        risk_category=risk_data.get("category", "operational"),
                        risk_score=score,
                        risk_description=risk_data.get("description", ""),
                        mitigation_suggestion=risk_data.get("mitigation"),
                    ))
                await s.commit()
            overall_risk_score = sum(risk_scores) / len(risk_scores) if risk_scores else 50.0

            completeness_checks = [
                ("parties.counterparty_a", bool(parties.get("counterparty_a"))),
                ("parties.counterparty_b", bool(parties.get("counterparty_b"))),
                ("parties.contract_type", bool(parties.get("contract_type"))),
                ("parties.effective_date", bool(parties.get("effective_date"))),
                ("parties.expiry_date", bool(parties.get("expiry_date"))),
                ("parties.governing_law", bool(parties.get("governing_law"))),
                ("commercial_terms", len(parsed.get("commercial_terms", [])) > 0),
                ("technical_data", len(parsed.get("technical_data", [])) > 0),
                ("legal_terms", len(parsed.get("legal_terms", [])) > 0),
                ("financial_terms", len(parsed.get("financial_terms", [])) > 0),
                ("operational_terms", len(parsed.get("operational_terms", [])) > 0),
                ("definitions", len(parsed.get("definitions", [])) > 0),
                ("clauses", len(parsed.get("clauses", [])) >= 3),
                ("assets", len(parsed.get("assets", [])) > 0),
                ("events", len(parsed.get("events", [])) > 0),
                ("risk_assessment", len(parsed.get("risk_assessment", [])) > 0),
                ("deal_clusters", bool(parsed.get("deal_clusters")) and isinstance(parsed.get("deal_clusters"), dict) and len(parsed["deal_clusters"]) > 0),
            ]
            present = [k for k, ok in completeness_checks if ok]
            missing_fields = [k for k, ok in completeness_checks if not ok]
            completeness_score = round(100.0 * len(present) / len(completeness_checks), 1)

            summary_data = {
                "raw_text_length": len(raw_text),
                "raw_text": raw_text[:200000],
                "extracted_fields": sum(len(parsed.get(k, [])) for k in ("commercial_terms", "technical_data", "legal_terms", "financial_terms", "operational_terms", "definitions")),
                "clauses_count": len(parsed.get("clauses", [])),
                "assets_count": len(parsed.get("assets", [])),
                "events_count": len(parsed.get("events", [])),
                "risk_categories": len(parsed.get("risk_assessment", [])),
                "overall_risk_score": overall_risk_score,
                "deal_clusters": parsed.get("deal_clusters"),
                "counterparty_a_role": parties.get("counterparty_a_role"),
                "counterparty_b_role": parties.get("counterparty_b_role"),
                "contract_type_detected": parties.get("contract_type"),
                "governing_law": parties.get("governing_law"),
                "dispute_resolution": parties.get("dispute_resolution"),
                "completeness_score": completeness_score,
                "missing_fields": missing_fields,
                "present_fields": present,
            }

            # Batch 6 — final contract row update (status, risk_score, party fields, summary)
            async with SessionLocal() as s:
                await s.execute(
                    update(ContractIQContract).where(ContractIQContract.id == contract_id).values(
                        status=ContractStatus.ANALYZED,
                        risk_score=overall_risk_score,
                        extraction_summary=summary_data,
                        **party_values,
                    )
                )
                await s.commit()
            await emit({'event': 'status', 'agent': 'risk_analyzer', 'status': 'complete'})

            # Taxonomy learning — its own session
            try:
                async with SessionLocal() as s:
                    learn_summary = await _learn_taxonomy(s, user_id, contract_id, parsed)
                    await emit({'event': 'taxonomy_learned', **learn_summary})
                    logger.info("Taxonomy updated: %s", learn_summary)
            except Exception as e:
                logger.warning("Taxonomy learning failed: %s", e)

            await emit({'event': 'status', 'agent': 'synthesis', 'status': 'running'})

            # Knowledge graph indexing — fire and forget
            try:
                if api_key:
                    async def _run_cognify_background():
                        try:
                            kg_subject = ActingSubject(subject_type="contractiq", subject_id=str(user_id))
                            async with Abenix(api_key=api_key, base_url=api_base, act_as=kg_subject, timeout=30.0) as kg_forge:
                                coll = await kg_forge.knowledge.ensure_subject_collection(
                                    project_slug="contractiq",
                                    subject_type="contractiq",
                                    subject_id=str(user_id),
                                    description=f"Per-user contracts corpus for {user_email}",
                                )
                                kb_id = coll["id"]
                                kg_result = await kg_forge.knowledge.cognify(kb_id, doc_ids=[str(contract_id)])
                                logger.info("Cognify triggered for contract %s: job=%s kb=%s", contract_id, kg_result.get("job_id"), kb_id)
                        except Exception as e:
                            logger.warning("Background Cognify failed for contract %s: %s", contract_id, e)
                    asyncio.create_task(_run_cognify_background())
                    await emit({'event': 'status', 'agent': 'knowledge_graph', 'status': 'queued', 'message': 'Knowledge graph indexing dispatched to Abenix'})
                else:
                    await emit({'event': 'status', 'agent': 'knowledge_graph', 'status': 'skipped', 'message': 'Abenix SDK not configured'})
            except Exception as kg_err:
                logger.warning("Knowledge graph dispatch failed for contract %s: %s", contract_id, kg_err)
                await emit({'event': 'status', 'agent': 'knowledge_graph', 'status': 'skipped'})

            await emit({'event': 'status', 'agent': 'synthesis', 'status': 'complete'})
            await emit({'event': 'completeness', 'score': completeness_score, 'missing_fields': missing_fields})
            await emit({'event': 'done', 'contract_id': str(contract_id), 'status': 'analyzed', 'completeness_score': completeness_score})

        except Exception as e:
            logger.exception("Background extraction failed: %s", e)
            err_msg = f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}"
            try:
                await _set_status(ContractStatus.ERROR)
            except Exception:
                pass
            await emit({'event': 'error', 'message': err_msg})
        finally:
            await emit(SENTINEL)

    # Detach the worker so client disconnect cannot cancel persistence
    asyncio.create_task(_extract_and_persist())

    async def stream_extraction():
        # SSE viewer over the background task's progress queue. Client
        # disconnects only kill this consumer — the work has already been
        # detached by asyncio.create_task above.
        try:
            while True:
                event = await progress_queue.get()
                if event is SENTINEL:
                    return
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            logger.info("SSE consumer cancelled for contract %s; extraction continues in background", contract_id)
            raise

    return StreamingResponse(stream_extraction(), media_type="text/event-stream")


@router.post("/contracts/{contract_id}/deep-extract")
async def deep_extract_contract(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Run multi-pass deep extraction to get 100+ fields from a contract.
    Uses contract-type-specific schemas with 4 targeted extraction passes."""
    query = (
        select(ContractIQContract)
        .where(ContractIQContract.id == contract_id)
        .where(ContractIQContract.tenant_id == tenant_id_for(user))
    )
    if user.role.value != "admin":
        query = query.where(ContractIQContract.user_id == user.id)
    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return JSONResponse(content={"data": None, "error": {"message": "Contract not found"}}, status_code=404)

    raw_text = (contract.extraction_summary or {}).get("raw_text", "")
    if not raw_text:
        return JSONResponse(content={"data": None, "error": {"message": "No text available"}}, status_code=400)

    contract_text = raw_text[:100000]

    from app.core.extraction_schemas import get_schema_for_type, get_total_fields
    from app.routers.insights import _call_abenix

    async def stream_deep_extraction():
        if not os.environ.get("CONTRACTIQ_ABENIX_API_KEY"):
            yield f"data: {json.dumps({'event': 'error', 'message': 'CONTRACTIQ_ABENIX_API_KEY not configured on contractiq-api'})}\n\n"
            return

        ctype = contract.contract_type.value if contract.contract_type else "ppa"
        schema = get_schema_for_type(ctype)
        total_fields = get_total_fields(ctype)

        yield f"data: {json.dumps({'event': 'info', 'message': f'Deep extraction: {len(schema)} passes, {total_fields} fields for {ctype.upper()}'})}\n\n"

        all_fields_count = 0
        pass_num = 0

        for pass_key, pass_config in schema.items():
            pass_num += 1
            section = pass_config["section"]
            fields = pass_config["fields"]
            focus = pass_config["prompt_focus"]

            yield f"data: {json.dumps({'event': 'pass_start', 'pass': pass_num, 'name': pass_key, 'fields': len(fields), 'focus': focus})}\n\n"

            # Use first 60K for most passes, back half for pass 2+ on long contracts
            text_slice = contract_text[:60000]
            if pass_num >= 3 and len(contract_text) > 60000:
                text_slice = contract_text[40000:100000]

            prompt = f"""Extract the following fields from this {ctype.upper()} contract.
Focus on: {focus}

CONTRACT TEXT:
{text_slice}

FIELDS TO EXTRACT (return ALL of them):
{json.dumps(fields, indent=2)}

Return a JSON array where each element is:
{{
  "field_name": "exact name from the list above",
  "field_value": "the actual value from the contract",
  "field_type": "string|number|currency|percentage|date|boolean",
  "confidence": 0.0 to 1.0,
  "source_text": "the exact sentence or clause where you found this (max 200 chars)"
}}

Rules:
- If a field is not found, set field_value to "NOT_FOUND" and confidence to 0.0
- Use exact values from the contract text
- For dates use YYYY-MM-DD format
- For currencies include the code (e.g., "45.50 USD/MWh")
- For percentages include the % symbol
- Extract EVERY field in the list — do not skip any"""

            try:
                parsed_fields, resp_text, _meta = await _call_abenix(
                    user, "contractiq-deep-extractor", prompt, timeout=300.0,
                )
                if parsed_fields and isinstance(parsed_fields, list):
                    extracted = parsed_fields
                elif parsed_fields and isinstance(parsed_fields, dict):
                    extracted = parsed_fields.get("fields", [parsed_fields])
                else:
                    try:
                        start = resp_text.find("[")
                        end = resp_text.rfind("]")
                        if start != -1 and end > start:
                            extracted = json.loads(resp_text[start:end + 1])
                        else:
                            extracted = []
                    except (json.JSONDecodeError, ValueError):
                        extracted = []

                # Save extracted fields
                saved = 0
                for item in extracted:
                    if not isinstance(item, dict):
                        continue
                    fname = item.get("field_name", "")
                    fval = str(item.get("field_value", ""))
                    if not fname or fval == "NOT_FOUND":
                        continue

                    ed = ContractIQExtractedData(
                        id=uuid.uuid4(),
                        contract_id=contract_id,
                        section=section,
                        field_name=fname,
                        field_value=fval,
                        field_type=item.get("field_type", "string"),
                        confidence_score=float(item.get("confidence", 0.8)),
                        extraction_pass=pass_num + 10,  # Offset to distinguish from initial extraction
                    )
                    db.add(ed)
                    saved += 1

                await db.commit()
                all_fields_count += saved

                yield f"data: {json.dumps({'event': 'pass_complete', 'pass': pass_num, 'name': pass_key, 'fields_extracted': saved, 'total': all_fields_count})}\n\n"

            except Exception as e:
                logger.error("Deep extraction pass %d failed: %s", pass_num, e)
                yield f"data: {json.dumps({'event': 'pass_error', 'pass': pass_num, 'name': pass_key, 'error': str(e)})}\n\n"

        yield f"data: {json.dumps({'event': 'done', 'total_fields': all_fields_count, 'passes': pass_num})}\n\n"

    return StreamingResponse(stream_deep_extraction(), media_type="text/event-stream")


@router.get("/contracts/{contract_id}")
async def get_contract(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get full contract details with extracted data, clauses, assets, events."""
    query = (
        select(ContractIQContract)
        .where(ContractIQContract.id == contract_id)
        .where(ContractIQContract.tenant_id == tenant_id_for(user))
    )
    if user.role.value != "admin":
        query = query.where(ContractIQContract.user_id == user.id)

    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    # Fetch related data
    extracted = await db.execute(
        select(ContractIQExtractedData).where(ContractIQExtractedData.contract_id == contract_id)
    )
    clauses = await db.execute(
        select(ContractIQClause).where(ContractIQClause.contract_id == contract_id)
    )
    assets = await db.execute(
        select(ContractIQAsset).where(ContractIQAsset.contract_id == contract_id)
    )
    events = await db.execute(
        select(ContractIQEvent).where(ContractIQEvent.contract_id == contract_id).order_by(ContractIQEvent.event_date)
    )
    risks = await db.execute(
        select(ContractIQRiskAnalysis).where(ContractIQRiskAnalysis.contract_id == contract_id)
    )

    return success({
        "id": str(contract.id),
        "title": contract.title,
        "contract_type": contract.contract_type.value,
        "status": contract.status.value,
        "counterparty_a": contract.counterparty_a,
        "counterparty_b": contract.counterparty_b,
        "effective_date": contract.effective_date.isoformat() if contract.effective_date else None,
        "expiry_date": contract.expiry_date.isoformat() if contract.expiry_date else None,
        "risk_score": contract.risk_score,
        "total_capacity_mw": contract.total_capacity_mw,
        "page_count": contract.page_count,
        "extraction_summary": contract.extraction_summary,
        "extracted_data": [
            {"section": e.section, "field_name": e.field_name, "field_value": e.field_value,
             "field_type": e.field_type, "confidence": e.confidence_score, "page": e.page_reference}
            for e in extracted.scalars().all()
        ],
        "clauses": [
            {"id": str(c.id), "number": c.clause_number, "title": c.clause_title,
             "text": c.clause_text[:500], "type": c.clause_type.value, "risk_level": c.risk_level.value,
             "risk_notes": c.risk_notes}
            for c in clauses.scalars().all()
        ],
        "assets": [
            {"id": str(a.id), "name": a.asset_name, "type": a.asset_type,
             "capacity_mw": a.capacity_mw, "location": a.location, "technology": a.technology,
             "cod_date": a.cod_date.isoformat() if a.cod_date else None}
            for a in assets.scalars().all()
        ],
        "events": [
            {"id": str(ev.id), "type": ev.event_type, "date": ev.event_date.isoformat() if ev.event_date else None,
             "description": ev.description, "status": ev.status}
            for ev in events.scalars().all()
        ],
        "risk_analyses": [
            {"category": r.risk_category, "score": r.risk_score,
             "description": r.risk_description, "mitigation": r.mitigation_suggestion}
            for r in risks.scalars().all()
        ],
    })


@router.delete("/contracts/{contract_id}")
async def delete_contract(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Delete a contract and all related data. Owner or admin only."""
    query = (
        select(ContractIQContract)
        .where(ContractIQContract.id == contract_id)
        .where(ContractIQContract.tenant_id == tenant_id_for(user))
    )
    if user.role.value != "admin":
        query = query.where(ContractIQContract.user_id == user.id)

    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return error("Contract not found or access denied", 404)

    await db.delete(contract)  # Cascades to all related tables
    await db.commit()
    return success({"deleted": True})


# ── Deal clusters aggregation across portfolio ────────────────────────

@router.get("/deal-clusters")
async def list_deal_clusters(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Aggregate deal clusters from every analyzed contract in the user's"""
    # Tenant filter is the hard wall — admins still see only their own tenant.
    q = select(ContractIQContract).where(
        ContractIQContract.tenant_id == tenant_id_for(user)
    )
    if user.role.value != "admin":
        q = q.where(ContractIQContract.user_id == user.id)
    rows = (await db.execute(q)).scalars().all()

    # Pre-load clause rows for each contract so we can link cluster.clauses
    # (which may be clause numbers, titles, or free text references) to
    # actual clause records with full text + risk_notes. This powers the
    # cluster → clause drill-through modal on /deal-clusters.
    clauses_by_contract: dict[str, list[dict]] = {}
    if rows:
        clause_q = select(ContractIQClause).where(
            ContractIQClause.contract_id.in_([c.id for c in rows])
        )
        for cl in (await db.execute(clause_q)).scalars().all():
            clauses_by_contract.setdefault(str(cl.contract_id), []).append({
                "id": str(cl.id),
                "number": cl.clause_number,
                "title": cl.clause_title,
                "text": cl.clause_text,
                "type": cl.clause_type.value if hasattr(cl.clause_type, "value") else str(cl.clause_type),
                "risk_level": cl.risk_level.value if hasattr(cl.risk_level, "value") else str(cl.risk_level),
                "risk_notes": cl.risk_notes,
            })

    def _match_cluster_clauses(contract_id: str, cluster_refs: list) -> list[dict]:
        """Match the cluster's clause references against the persisted"""
        pool = clauses_by_contract.get(contract_id, [])
        if not cluster_refs:
            return []
        matched: list[dict] = []
        seen: set[str] = set()
        for ref in cluster_refs:
            if not isinstance(ref, (str, dict)):
                continue
            ref_str = ref if isinstance(ref, str) else (
                ref.get("title") or ref.get("number") or ""
            )
            ref_low = (ref_str or "").lower().strip()
            if not ref_low:
                continue
            for cl in pool:
                if cl["id"] in seen:
                    continue
                if (cl["number"] and cl["number"].lower() == ref_low) or \
                   (cl["title"] and (ref_low in cl["title"].lower() or cl["title"].lower() in ref_low)):
                    matched.append(cl)
                    seen.add(cl["id"])
        return matched

    clusters: list[dict] = []
    for c in rows:
        summary = c.extraction_summary or {}
        dc = summary.get("deal_clusters")
        if not isinstance(dc, dict):
            continue
        contract_id_str = str(c.id)
        for cluster_key, cluster_body in dc.items():
            if not isinstance(cluster_body, dict):
                continue
            raw_refs = cluster_body.get("clauses") or []
            clusters.append({
                "contract_id": contract_id_str,
                "contract_title": c.title,
                "counterparty_a": c.counterparty_a,
                "counterparty_b": c.counterparty_b,
                "cluster_key": cluster_key,
                "description": cluster_body.get("description"),
                "clauses": raw_refs,
                "clause_rows": _match_cluster_clauses(contract_id_str, raw_refs),
                "deal_legs": cluster_body.get("deal_legs") or {},
            })
    return success({
        "total_contracts": len(rows),
        "total_clusters": len(clusters),
        "clusters": clusters,
    })


@router.get("/timeline")
async def list_timeline(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(500, ge=1, le=2000),
    contract_id: str = Query(""),
    event_type: str = Query(""),
    status: str = Query(""),
) -> JSONResponse:
    """Aggregate every event across the caller's contracts into a"""
    # Tenant scope: admins see every event WITHIN their tenant; analysts see
    # only their own. Tenant filter on the joined contract is unconditional.
    base = (
        select(ContractIQEvent, ContractIQContract.id, ContractIQContract.title,
               ContractIQContract.contract_type, ContractIQContract.counterparty_a,
               ContractIQContract.counterparty_b)
        .join(ContractIQContract, ContractIQEvent.contract_id == ContractIQContract.id)
        .where(ContractIQContract.tenant_id == tenant_id_for(user))
    )
    if user.role.value != "admin":
        base = base.where(ContractIQContract.user_id == user.id)
    if contract_id:
        try:
            base = base.where(ContractIQContract.id == uuid.UUID(contract_id))
        except ValueError:
            pass
    if event_type:
        base = base.where(ContractIQEvent.event_type == event_type)
    if status:
        base = base.where(ContractIQEvent.status == status)
    base = base.order_by(ContractIQEvent.event_date.asc().nulls_last()).limit(limit)

    rows = (await db.execute(base)).all()
    events = []
    for ev, cid, title, ctype, cpa, cpb in rows:
        events.append({
            "id": str(ev.id),
            "contract_id": str(cid),
            "contract_title": title,
            "contract_type": ctype,
            "counterparty_a": cpa,
            "counterparty_b": cpb,
            "event_type": ev.event_type,
            "event_date": ev.event_date.isoformat() if ev.event_date else None,
            "description": ev.description,
            "status": ev.status,
            "is_recurring": ev.is_recurring,
            "notification_days_before": ev.notification_days_before,
        })

    # Bucket counts for the page header KPIs.
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    upcoming_30d = 0
    overdue = 0
    now = datetime.now(timezone.utc)
    for e in events:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
        if e["event_date"]:
            try:
                d = datetime.fromisoformat(e["event_date"].replace("Z", "+00:00"))
                delta = (d - now).total_seconds()
                if 0 <= delta <= 30 * 86400:
                    upcoming_30d += 1
                elif delta < 0 and e["status"] != "passed":
                    overdue += 1
            except Exception:
                pass

    return JSONResponse({"data": {
        "events": events,
        "total": len(events),
        "by_type": by_type,
        "by_status": by_status,
        "upcoming_30d": upcoming_30d,
        "overdue": overdue,
    }})


# ── Self-learning taxonomy read API ─────────────────────────────────

@router.get("/clauses")
async def list_clauses(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    search: str = Query("", max_length=255),
    clause_type: str = Query(""),
    risk_level: str = Query(""),
    contract_id: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    """Cross-contract Clause Library."""
    from sqlalchemy import or_, func as sa_func

    tid = tenant_id_for(user)
    base = (
        select(ContractIQClause, ContractIQContract.title.label("contract_title"),
               ContractIQContract.contract_type.label("contract_type"))
        .join(ContractIQContract, ContractIQClause.contract_id == ContractIQContract.id)
        .where(ContractIQContract.tenant_id == tid)
    )
    if user.role.value != "admin":
        base = base.where(ContractIQContract.user_id == user.id)
    if contract_id:
        try:
            base = base.where(ContractIQClause.contract_id == uuid.UUID(contract_id))
        except ValueError:
            pass
    if clause_type:
        base = base.where(ContractIQClause.clause_type == clause_type)
    if risk_level:
        base = base.where(ContractIQClause.risk_level == risk_level)
    if search:
        s = f"%{search}%"
        base = base.where(or_(
            ContractIQClause.clause_title.ilike(s),
            ContractIQClause.clause_text.ilike(s),
            ContractIQClause.clause_number.ilike(s),
        ))

    total = (await db.execute(select(sa_func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.order_by(ContractIQClause.created_at.desc()).limit(limit).offset(offset))).all()

    items = []
    for clause, contract_title, ctype in rows:
        items.append({
            "id": str(clause.id),
            "contract_id": str(clause.contract_id),
            "contract_title": contract_title,
            "contract_type": ctype.value if hasattr(ctype, "value") else str(ctype) if ctype else None,
            "clause_number": clause.clause_number,
            "clause_title": clause.clause_title,
            "clause_text": (clause.clause_text or "")[:1500],
            "clause_type": clause.clause_type.value if hasattr(clause.clause_type, "value") else str(clause.clause_type),
            "risk_level": clause.risk_level.value if hasattr(clause.risk_level, "value") else str(clause.risk_level),
            "risk_notes": clause.risk_notes,
            "created_at": clause.created_at.isoformat() if clause.created_at else None,
        })

    # Aggregates over the unfiltered scope (so chips don't disappear when
    # filtered). Tenant guard goes on every join so the role check only
    # narrows ownership within the tenant.
    by_type_base = (
        select(ContractIQClause.clause_type, sa_func.count())
        .join(ContractIQContract, ContractIQClause.contract_id == ContractIQContract.id)
        .where(ContractIQContract.tenant_id == tid)
    )
    if user.role.value != "admin":
        by_type_base = by_type_base.where(ContractIQContract.user_id == user.id)
    by_type_q = await db.execute(by_type_base.group_by(ContractIQClause.clause_type))
    by_type = {(t.value if hasattr(t, "value") else str(t)): int(c) for t, c in by_type_q.all()}

    by_risk_base = (
        select(ContractIQClause.risk_level, sa_func.count())
        .join(ContractIQContract, ContractIQClause.contract_id == ContractIQContract.id)
        .where(ContractIQContract.tenant_id == tid)
    )
    if user.role.value != "admin":
        by_risk_base = by_risk_base.where(ContractIQContract.user_id == user.id)
    by_risk_q = await db.execute(by_risk_base.group_by(ContractIQClause.risk_level))
    by_risk = {(r.value if hasattr(r, "value") else str(r)): int(c) for r, c in by_risk_q.all()}

    return success({
        "items": items,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "by_type": by_type,
        "by_risk": by_risk,
    })


@router.get("/clauses/gaps")
async def clause_gaps(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Missing-clauses gap analysis."""
    from sqlalchemy import func as sa_func

    tid = tenant_id_for(user)
    # Standard set: every type the portfolio has ever produced (excluding 'other')
    type_q = (
        select(ContractIQClause.clause_type)
        .distinct()
        .join(ContractIQContract, ContractIQClause.contract_id == ContractIQContract.id)
        .where(ContractIQContract.tenant_id == tid)
    )
    if user.role.value != "admin":
        type_q = type_q.where(ContractIQContract.user_id == user.id)
    seen_types = [
        (t.value if hasattr(t, "value") else str(t))
        for (t,) in (await db.execute(type_q)).all()
    ]
    standard = sorted([t for t in seen_types if t and t != "other"])

    # Per-contract presence map — tenant filter is unconditional.
    contracts_q = (
        select(ContractIQContract)
        .where(ContractIQContract.status != ContractStatus.UPLOADED)
        .where(ContractIQContract.tenant_id == tid)
    )
    if user.role.value != "admin":
        contracts_q = contracts_q.where(ContractIQContract.user_id == user.id)
    contracts = (await db.execute(contracts_q.order_by(ContractIQContract.created_at.desc()).limit(200))).scalars().all()

    rows = []
    for c in contracts:
        per_type_q = await db.execute(
            select(ContractIQClause.clause_type, sa_func.count())
            .where(ContractIQClause.contract_id == c.id)
            .group_by(ContractIQClause.clause_type)
        )
        present = {
            (t.value if hasattr(t, "value") else str(t)): int(n)
            for t, n in per_type_q.all()
        }
        missing = [t for t in standard if present.get(t, 0) == 0]
        rows.append({
            "contract_id": str(c.id),
            "contract_title": c.title,
            "contract_type": c.contract_type.value if hasattr(c.contract_type, "value") else str(c.contract_type) if c.contract_type else None,
            "present": present,
            "missing": missing,
            "coverage_pct": round(100.0 * (len(standard) - len(missing)) / len(standard), 1) if standard else 100.0,
        })

    # Sort by coverage asc so the worst contracts surface first
    rows.sort(key=lambda r: r["coverage_pct"])

    # Per-type roll-up: how many contracts are missing this type
    rollup = []
    for t in standard:
        missing_count = sum(1 for r in rows if t in r["missing"])
        rollup.append({
            "clause_type": t,
            "present_in": len(rows) - missing_count,
            "missing_in": missing_count,
            "coverage_pct": round(100.0 * (len(rows) - missing_count) / len(rows), 1) if rows else 100.0,
        })
    rollup.sort(key=lambda r: r["coverage_pct"])

    return success({
        "standard_types": standard,
        "rows": rows,
        "rollup": rollup,
        "total_contracts": len(rows),
    })


@router.get("/taxonomy")
async def list_taxonomy(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    taxonomy_type: str = Query(""),
    limit: int = Query(200, ge=1, le=500),
) -> JSONResponse:
    """Return the user's discovered taxonomy — cluster names, leg names,"""
    q = select(ContractIQExtractionTaxonomy).where(
        ContractIQExtractionTaxonomy.user_id == user.id
    )
    if taxonomy_type:
        q = q.where(ContractIQExtractionTaxonomy.taxonomy_type == taxonomy_type)
    q = q.order_by(ContractIQExtractionTaxonomy.usage_count.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    # Bucket into groups
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r.taxonomy_type, []).append({
            "key": r.key,
            "description": r.description,
            "metadata": r.taxonomy_metadata,
            "usage_count": r.usage_count,
            "first_seen_contract_id": str(r.first_seen_contract_id) if r.first_seen_contract_id else None,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
        })
    return success({
        "total": len(rows),
        "groups": groups,
    })
