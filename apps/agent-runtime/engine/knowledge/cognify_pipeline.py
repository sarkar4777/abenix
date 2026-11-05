"""Cognify Pipeline, transform documents into a knowledge graph batch by batch."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from engine.knowledge import cognify_store as store
from engine.knowledge.entity_extractor import (
    DEFAULT_COGNIFY_MODEL,
    ChunkExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    estimate_chunk_tokens,
    extract_chunks,
)
from engine.knowledge.entity_resolver import resolve_entities
from engine.knowledge.graph_writer import (
    GraphUnavailable,
    fetch_existing_entities,
    stamp_pg_ids,
    write_entities,
    write_relationships,
)
from engine.knowledge.neo4j_client import (
    ensure_kb_keys,
    ensure_schema,
    is_neo4j_available,
)
from engine.knowledge.ontology import (
    MAX_ONTOLOGY_ROWS,
    BoundOntology,
    apply_ontology,
    as_bound,
)
from engine.knowledge.rate_limit import CallLimiter

logger = logging.getLogger(__name__)

STOP_JOB_BUDGET = "job_budget"
STOP_DAILY_BUDGET = "daily_budget"
STOP_REQUESTED = "user_requested"
STOP_TIME_SLICE = "time_slice"
STOP_GRAPH_DOWN = "graph_unavailable"

STOP_MESSAGES = {
    STOP_JOB_BUDGET: "Stopped at the job budget of ${budget:.2f} with ${spent:.2f} spent. "
    "Run Cognify again with a higher limit to continue, finished chunks are not paid for twice.",
    STOP_DAILY_BUDGET: "Stopped at the daily budget of ${budget:.2f}. "
    "Run Cognify again tomorrow or raise it in Settings > Cognify.",
    STOP_REQUESTED: "Stopped on request. Run Cognify again to continue from where it stopped.",
    STOP_GRAPH_DOWN: "Stopped because Neo4j stopped answering. "
    "What was extracted is saved and is written on the next run.",
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class CognifyResult:
    """Result of a full cognify run."""

    kb_id: str
    job_id: str
    status: str = "complete"
    documents_processed: int = 0
    chunks_analyzed: int = 0
    chunks_skipped: int = 0
    chunks_failed: int = 0
    entities_extracted: int = 0
    entities_after_resolution: int = 0
    entities_merged: int = 0
    entities_failed: int = 0
    relationships_extracted: int = 0
    relationships_written: int = 0
    relationships_failed: int = 0
    off_ontology_dropped: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    # Per-provider spend breakdown so the KB engine page can show
    # "Anthropic $X + OpenAI $Y" instead of a single flat number.
    anthropic_cost: float = 0.0
    openai_cost: float = 0.0
    google_cost: float = 0.0
    other_cost: float = 0.0
    duration_seconds: float = 0.0
    error: str | None = None
    stop_reason: str | None = None
    # Report data
    entities_by_type: dict[str, int] = field(default_factory=dict)
    top_entities: list[dict[str, Any]] = field(default_factory=list)
    relationship_types: dict[str, int] = field(default_factory=dict)
    # cognify_configs at work
    auto_accept_threshold: float = 0.0
    entities_held_back: int = 0
    relationships_held_back: int = 0
    held_back: list[dict[str, Any]] = field(default_factory=list)
    conflicts_recorded: int = 0
    documents_skipped_budget: int = 0


DEFAULT_COGNIFY_CONFIG: dict[str, Any] = {
    "auto_accept_threshold": 0.85,
    "conflict_action": "flag",
    "max_parallel_docs": 8,
    "daily_budget_usd": None,
}

DEFAULT_JOB_BUDGET_USD = _env_float("COGNIFY_JOB_BUDGET_USD", 50.0)
DEFAULT_PARALLEL_CHUNKS = int(_env_float("COGNIFY_MAX_PARALLEL_CHUNKS", 4))
DEFAULT_BATCH_CHUNKS = int(_env_float("COGNIFY_GRAPH_BATCH_CHUNKS", 20))
DEFAULT_RPM = _env_float("COGNIFY_REQUESTS_PER_MINUTE", 300)
DEFAULT_TPM = _env_float("COGNIFY_TOKENS_PER_MINUTE", 400000)


def load_cognify_config(tenant_id: str, db_url: str) -> dict[str, Any]:
    """The tenant's cognify_configs row over the defaults the settings page shows."""
    cfg = dict(DEFAULT_COGNIFY_CONFIG)
    if not db_url or not tenant_id:
        return cfg
    try:
        from sqlalchemy import text

        with store.engine_for(db_url).connect() as conn:
            row = conn.execute(
                text(
                    "SELECT auto_accept_threshold, conflict_action, max_parallel_docs, "
                    "daily_budget_usd FROM cognify_configs WHERE tenant_id = CAST(:t AS uuid)"
                ),
                {"t": tenant_id},
            ).fetchone()
            if row is not None:
                cfg.update(
                    auto_accept_threshold=float(row[0]),
                    conflict_action=row[1] or "flag",
                    max_parallel_docs=int(row[2] or 8),
                    daily_budget_usd=float(row[3]) if row[3] is not None else None,
                )
            spent = conn.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM cognify_jobs "
                    "WHERE tenant_id = CAST(:t AS uuid) AND created_at >= date_trunc('day', now())"
                ),
                {"t": tenant_id},
            ).scalar()
            cfg["spent_today_usd"] = float(spent or 0)
    except Exception as e:
        logger.warning("cognify config load failed, using defaults: %s", e)
    return cfg


def _hold_back(
    entities: list, relationships: list, threshold: float
) -> tuple[list, list, list[dict[str, Any]]]:
    """Drop proposals under the auto-accept threshold, and relationships left dangling."""
    if threshold <= 0:
        return entities, relationships, []
    kept = [e for e in entities if float(e.confidence) >= threshold]
    names = {e.canonical_name for e in kept}
    held = [
        {"kind": "entity", "name": e.canonical_name, "confidence": float(e.confidence)}
        for e in entities
        if float(e.confidence) < threshold
    ]
    kept_rels = []
    for r in relationships:
        if float(r.confidence) < threshold:
            held.append(
                {
                    "kind": "relationship",
                    "name": f"{r.source} {r.relationship_type} {r.target}",
                    "confidence": float(r.confidence),
                }
            )
        elif r.source in names and r.target in names:
            kept_rels.append(r)
    return kept, kept_rels, held


def _provider_key(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("chatgpt"):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    return "other"


def daily_budget_error(budget: float, spent: float) -> str:
    return (
        f"Daily Cognify budget of ${budget:.2f} is used up "
        f"(${spent:.2f} spent today). Raise it in Settings > Cognify "
        "or wait until tomorrow (UTC)."
    )


def chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def price_per_token(model: str) -> tuple[float, float]:
    from engine.llm_router import DEFAULT_PRICING, PRICING

    p = PRICING.get(model) or DEFAULT_PRICING
    return float(p["input"]), float(p["output"])


def estimate_cost(chunks: int, model: str, avg_chars: int = 1000) -> float:
    """What extracting this many chunks costs before anyone pays for it."""
    from engine.knowledge.entity_extractor import EXPECTED_OUTPUT_TOKENS

    tokens_in = estimate_chunk_tokens("x" * avg_chars) - EXPECTED_OUTPUT_TOKENS
    inp, out = price_per_token(model)
    return chunks * (tokens_in * inp + EXPECTED_OUTPUT_TOKENS * out)


_SIGNAL = re.compile(r"\b(?:[A-Z][\w&.-]+|\d[\d,.%-]*)\b")


def chunk_salience(text: str) -> float:
    """Names and numbers per word, the things extraction can use."""
    words = text.split()
    if len(words) < 8:
        return 0.0
    return (
        len(_SIGNAL.findall(text))
        / len(words)
        * min(1.0, len(set(words)) / len(words) * 2)
    )


@dataclass
class ChunkSelection:
    mode: str = "all"
    sample_rate: float = 1.0
    max_chunks_per_doc: int | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "ChunkSelection":
        mode = (cfg.get("selection") or "all").lower()
        return cls(
            mode=mode if mode in ("all", "sample", "salient") else "all",
            sample_rate=max(0.0, min(1.0, float(cfg.get("sample_rate") or 1.0))),
            max_chunks_per_doc=cfg.get("max_chunks_per_doc"),
        )

    def pick(self, chunks: list[str], hashes: list[str]) -> list[int]:
        """Stable for the same input, so a rerun of a sample does not pay for a new one."""
        live = [i for i, c in enumerate(chunks) if c.strip()]
        picked = live
        limit = self.max_chunks_per_doc
        if self.mode == "sample":
            picked = [
                i
                for i in live
                if int(hashes[i][:8], 16) / 0xFFFFFFFF < self.sample_rate
            ]
        elif self.mode == "salient":
            keep = max(1, round(len(live) * self.sample_rate))
            ranked = sorted(live, key=lambda i: (-chunk_salience(chunks[i]), i))
            picked = sorted(ranked[:keep])
        if limit and len(picked) > limit:
            ranked = sorted(picked, key=lambda i: (-chunk_salience(chunks[i]), i))
            picked = sorted(ranked[: int(limit)])
        return picked

    @property
    def covers_everything(self) -> bool:
        return (
            self.mode == "all" or self.sample_rate >= 1.0
        ) and not self.max_chunks_per_doc


ExtractFn = Callable[..., Awaitable[list[ChunkExtractionResult]]]


@dataclass
class CognifyContext:
    kb_id: str
    tenant_id: str
    job_id: str
    db_url: str = ""
    model: str = DEFAULT_COGNIFY_MODEL
    force: bool = False
    threshold: float = 0.85
    conflict_action: str = "flag"
    ontology: BoundOntology | None = None
    selection: ChunkSelection = field(default_factory=ChunkSelection)
    limiter: CallLimiter | None = None
    max_parallel_chunks: int = DEFAULT_PARALLEL_CHUNKS
    batch_chunks: int = DEFAULT_BATCH_CHUNKS
    job_budget: float | None = None
    daily_budget: float | None = None
    deadline: float | None = None
    extract: ExtractFn = extract_chunks
    # spend seen by this process, the only ledger when there is no database
    local_cost: float = 0.0
    local_chunks: int = 0


def build_context(
    kb_id: str,
    tenant_id: str,
    job_id: str,
    config: dict[str, Any],
    db_url: str,
    tenant_cfg: dict[str, Any] | None = None,
    ontology: BoundOntology | None = None,
) -> CognifyContext:
    tenant_cfg = (
        tenant_cfg if tenant_cfg is not None else load_cognify_config(tenant_id, db_url)
    )
    budget = config.get("max_cost_usd")
    return CognifyContext(
        kb_id=kb_id,
        tenant_id=tenant_id,
        job_id=job_id,
        db_url=db_url,
        model=config.get("model") or DEFAULT_COGNIFY_MODEL,
        force=bool(config.get("force", False)),
        threshold=float(tenant_cfg["auto_accept_threshold"]),
        conflict_action=tenant_cfg["conflict_action"],
        ontology=ontology,
        selection=ChunkSelection.from_config(config),
        limiter=CallLimiter(
            float(config.get("requests_per_minute") or DEFAULT_RPM),
            float(config.get("tokens_per_minute") or DEFAULT_TPM),
        ),
        max_parallel_chunks=int(
            config.get("max_parallel_chunks") or DEFAULT_PARALLEL_CHUNKS
        ),
        batch_chunks=int(config.get("graph_batch_chunks") or DEFAULT_BATCH_CHUNKS),
        job_budget=float(budget) if budget is not None else DEFAULT_JOB_BUDGET_USD,
        daily_budget=tenant_cfg.get("daily_budget_usd"),
    )


def stop_message(reason: str, budget: float | None = None, spent: float = 0.0) -> str:
    template = STOP_MESSAGES.get(reason, "Stopped.")
    return template.format(budget=budget or 0.0, spent=spent)


async def check_stop(
    ctx: CognifyContext, upcoming_cost: float = 0.0, chunks: int = 0
) -> str | None:
    """Why this batch must not start, if there is a reason."""
    if ctx.deadline is not None and time.monotonic() >= ctx.deadline:
        return STOP_TIME_SLICE
    state = await asyncio.to_thread(
        store.job_state, ctx.db_url, ctx.job_id, ctx.tenant_id
    )
    if state.stop_requested:
        return state.stop_reason or STOP_REQUESTED
    spent = max(state.cost, ctx.local_cost)
    # what this job has really paid per chunk beats the price list estimate
    if state.chunks_paid and chunks:
        upcoming_cost = max(upcoming_cost, state.cost / state.chunks_paid * chunks)
    budget = state.budget if state.budget is not None else ctx.job_budget
    if budget is not None and spent + upcoming_cost > budget:
        return STOP_JOB_BUDGET
    if ctx.daily_budget is not None and (
        state.spent_today + upcoming_cost >= ctx.daily_budget
    ):
        return STOP_DAILY_BUDGET
    return None


@dataclass
class DocumentOutcome:
    document_id: str
    filename: str = ""
    chunks_total: int = 0
    chunks_selected: int = 0
    chunks_skipped: int = 0
    chunks_done: int = 0
    chunks_failed: int = 0
    tokens: int = 0
    cost: float = 0.0
    entities_raw: int = 0
    entities_written: int = 0
    entities_failed: int = 0
    entities_merged: int = 0
    relationships_raw: int = 0
    relationships_written: int = 0
    relationships_failed: int = 0
    off_ontology: int = 0
    entities_held: int = 0
    relationships_held: int = 0
    conflicts: int = 0
    held_back: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    entity_types: dict[str, int] = field(default_factory=dict)
    relationship_types: dict[str, int] = field(default_factory=dict)
    top_entities: list[dict[str, Any]] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.stop_reason is None and self.chunks_failed == 0


def _result_to_json(r: ChunkExtractionResult) -> dict[str, Any]:
    return {
        "entities": [asdict(e) for e in r.entities],
        "relationships": [asdict(x) for x in r.relationships],
    }


def _result_from_json(
    data: dict[str, Any] | None, index: int, doc_id: str
) -> ChunkExtractionResult:
    data = data or {}
    return ChunkExtractionResult(
        entities=[ExtractedEntity(**e) for e in data.get("entities") or []],
        relationships=[
            ExtractedRelationship(**x) for x in data.get("relationships") or []
        ],
        chunk_index=index,
        doc_id=doc_id,
    )


async def _commit(
    ctx: CognifyContext,
    outcome: DocumentOutcome,
    results: list[ChunkExtractionResult],
    hashes: list[str],
    batch_id: str,
) -> None:
    """Resolve one batch against the stored graph, write it, then mark its chunks done."""
    counts = store.BatchCounts(chunks=len(hashes))
    raw_entities = []
    raw_relationships = []
    for r in results:
        raw_entities.extend(r.entities)
        raw_relationships.extend(r.relationships)
    counts.entities_extracted = len(raw_entities)
    counts.relationships_extracted = len(raw_relationships)

    existing = await fetch_existing_entities(
        ctx.kb_id, [e.name for e in raw_entities], ctx.tenant_id
    )
    resolution = await resolve_entities(
        raw_entities=raw_entities,
        raw_relationships=raw_relationships,
        existing_entities=existing,
        model=ctx.model,
        conflict_action=ctx.conflict_action,
        llm_resolve=False,
    )
    entities, relationships, held = _hold_back(
        resolution.entities, resolution.relationships, ctx.threshold
    )
    counts.entities_held = sum(1 for h in held if h["kind"] == "entity")
    counts.relationships_held = len(held) - counts.entities_held
    counts.held_back = sorted(held, key=lambda h: -h["confidence"])[:10]
    counts.entities_merged = resolution.merges_performed
    if ctx.ontology and ctx.ontology.graph_id:
        for e in entities:
            if (e.properties or {}).get("atlas_concept_id"):
                e.properties["atlas_graph_id"] = ctx.ontology.graph_id

    entity_stats = await write_entities(
        ctx.kb_id, entities, tenant_id=ctx.tenant_id, batch_id=batch_id
    )
    rel_stats = await write_relationships(ctx.kb_id, relationships, batch_id=batch_id)
    counts.entities_written = entity_stats.written
    counts.entities_failed = entity_stats.failed
    counts.relationships_written = rel_stats.written
    counts.relationships_failed = rel_stats.failed
    counts.errors = (entity_stats.errors + rel_stats.errors)[:10]

    if ctx.db_url and resolution.conflicts:
        counts.conflicts = await asyncio.to_thread(
            _record_conflicts,
            ctx.tenant_id,
            ctx.kb_id,
            resolution.conflicts,
            ctx.db_url,
        )
    written = set(entity_stats.ids)
    mirror_rels = [
        r for r in relationships if r.source in written and r.target in written
    ]
    pg_ids = await asyncio.to_thread(
        store.commit_batch,
        ctx.db_url,
        ctx.kb_id,
        ctx.tenant_id,
        outcome.document_id,
        ctx.job_id,
        [e for e in entities if e.canonical_name in written],
        mirror_rels,
        entity_stats.ids,
        hashes,
        counts,
    )
    try:
        await stamp_pg_ids(ctx.kb_id, pg_ids)
    except Exception as e:
        logger.warning("could not stamp Postgres ids on graph nodes: %s", e)

    outcome.chunks_done += len(hashes)
    outcome.entities_raw += counts.entities_extracted
    outcome.relationships_raw += counts.relationships_extracted
    outcome.entities_written += entity_stats.written
    outcome.entities_failed += entity_stats.failed
    outcome.entities_merged += resolution.merges_performed
    outcome.relationships_written += rel_stats.written
    outcome.relationships_failed += rel_stats.failed
    outcome.entities_held += counts.entities_held
    outcome.relationships_held += counts.relationships_held
    outcome.conflicts += counts.conflicts
    outcome.held_back = (outcome.held_back + counts.held_back)[:50]
    outcome.errors = (outcome.errors + counts.errors)[:20]
    for e in entities:
        outcome.entity_types[e.entity_type] = (
            outcome.entity_types.get(e.entity_type, 0) + 1
        )
        outcome.top_entities.append(
            {
                "name": e.canonical_name,
                "type": e.entity_type,
                "mentions": e.mention_count,
                "description": e.description,
            }
        )
    outcome.top_entities = sorted(outcome.top_entities, key=lambda t: -t["mentions"])[
        :20
    ]
    for r in relationships:
        outcome.relationship_types[r.relationship_type] = (
            outcome.relationship_types.get(r.relationship_type, 0) + 1
        )


async def cognify_document(
    ctx: CognifyContext, doc: dict[str, Any], count_totals: bool = True
) -> DocumentOutcome:
    """Process what one document still needs. Safe to call again after any failure."""
    doc_id = str(doc["id"])
    chunks: list[str] = doc.get("chunks") or []
    outcome = DocumentOutcome(document_id=doc_id, filename=doc.get("filename", ""))
    outcome.chunks_total = len(chunks)
    hashes = [chunk_hash(c) for c in chunks]

    ledger = await asyncio.to_thread(store.ledger_state, ctx.db_url, ctx.kb_id, doc_id)

    selected = ctx.selection.pick(chunks, hashes)
    outcome.chunks_selected = len(selected)
    seen: set[str] = set()
    todo: list[int] = []
    for i in selected:
        h = hashes[i]
        if h in seen or h in ledger.done or h in ledger.pending:
            outcome.chunks_skipped += 0 if h in ledger.pending else 1
            seen.add(h)
            continue
        seen.add(h)
        todo.append(i)
    if count_totals:
        await asyncio.to_thread(
            store.add_job_totals,
            ctx.db_url,
            ctx.job_id,
            len(selected),
            outcome.chunks_skipped,
        )

    # a crash after the model answered and before the graph write costs nothing to replay
    if ledger.pending:
        rows = sorted(ledger.pending.values(), key=lambda r: r.chunk_index)
        for start in range(0, len(rows), max(ctx.batch_chunks, 1)):
            batch = rows[start : start + ctx.batch_chunks]
            await _commit(
                ctx,
                outcome,
                [_result_from_json(r.result, r.chunk_index, doc_id) for r in batch],
                [r.chunk_hash for r in batch],
                _batch_id([r.chunk_hash for r in batch]),
            )

    known: deque[str] = deque(maxlen=50)
    provider_column = f"{_provider_key(ctx.model)}_cost"
    for start in range(0, len(todo), max(ctx.batch_chunks, 1)):
        batch = todo[start : start + ctx.batch_chunks]
        est = _batch_estimate(ctx.model, [chunks[i] for i in batch])
        if ctx.local_chunks:
            est = max(est, ctx.local_cost / ctx.local_chunks * len(batch))
        reason = await check_stop(ctx, est, len(batch))
        if reason:
            outcome.stop_reason = reason
            if reason != STOP_TIME_SLICE:
                await asyncio.to_thread(
                    store.request_stop, ctx.db_url, ctx.job_id, reason
                )
            break
        results = await ctx.extract(
            [(i, chunks[i]) for i in batch],
            doc_id,
            known_entities=list(known),
            model=ctx.model,
            ontology=ctx.ontology,
            limiter=ctx.limiter,
            max_parallel=ctx.max_parallel_chunks,
        )
        ok: list[tuple[int, ChunkExtractionResult]] = []
        rows_out: list[store.LedgerRow] = []
        tokens = cost = failed = 0
        for i, r in zip(batch, results):
            tokens += r.tokens_used
            cost += r.cost
            if r.error:
                failed += 1
                outcome.errors = (outcome.errors + [f"chunk {i} {r.error}"])[:20]
                continue
            outcome.off_ontology += apply_ontology(r, ctx.ontology)
            ok.append((i, r))
            rows_out.append(
                store.LedgerRow(hashes[i], i, _result_to_json(r), r.tokens_used, r.cost)
            )
        outcome.tokens += tokens
        outcome.cost += cost
        outcome.chunks_failed += failed
        ctx.local_cost += cost
        ctx.local_chunks += len(batch)
        await asyncio.to_thread(
            store.record_extractions,
            ctx.db_url,
            ctx.kb_id,
            doc_id,
            ctx.job_id,
            rows_out,
            tokens,
            cost,
            provider_column,
            failed,
        )
        if ok:
            await _commit(
                ctx,
                outcome,
                [r for _i, r in ok],
                [hashes[i] for i, _r in ok],
                _batch_id([hashes[i] for i, _r in ok]),
            )
        for _i, r in ok:
            for e in r.entities:
                if e.name not in known:
                    known.append(e.name)
    return outcome


def _batch_id(hashes: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(hashes)).encode()).hexdigest()[:24]


def _batch_estimate(model: str, texts: list[str]) -> float:
    inp, out = price_per_token(model)
    return sum(estimate_chunk_tokens(t) * inp for t in texts) + len(texts) * 400 * out


def _merge_outcome(result: CognifyResult, o: DocumentOutcome, model: str) -> None:
    result.chunks_analyzed += o.chunks_done
    result.chunks_skipped += o.chunks_skipped
    result.chunks_failed += o.chunks_failed
    result.total_tokens += o.tokens
    result.total_cost += o.cost
    setattr(
        result,
        f"{_provider_key(model)}_cost",
        getattr(result, f"{_provider_key(model)}_cost") + o.cost,
    )
    result.entities_extracted += o.entities_raw
    result.relationships_extracted += o.relationships_raw
    result.entities_after_resolution += o.entities_written
    result.entities_failed += o.entities_failed
    result.entities_merged += o.entities_merged
    result.relationships_written += o.relationships_written
    result.relationships_failed += o.relationships_failed
    result.off_ontology_dropped += o.off_ontology
    result.entities_held_back += o.entities_held
    result.relationships_held_back += o.relationships_held
    result.conflicts_recorded += o.conflicts
    result.held_back = sorted(
        result.held_back + o.held_back, key=lambda h: -h["confidence"]
    )[:50]
    for k, v in o.entity_types.items():
        result.entities_by_type[k] = result.entities_by_type.get(k, 0) + v
    for k, v in o.relationship_types.items():
        result.relationship_types[k] = result.relationship_types.get(k, 0) + v
    result.top_entities = sorted(
        result.top_entities + o.top_entities, key=lambda t: -t["mentions"]
    )[:20]


async def run_cognify(
    kb_id: str,
    tenant_id: str,
    job_id: str,
    documents: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    db_url: str = "",
) -> CognifyResult:
    """Run every document in this process. The worker runs one task per document instead."""
    start = time.monotonic()
    cfg = config or {}
    result = CognifyResult(kb_id=kb_id, job_id=job_id)
    db_url = store.usable_url(db_url, kb_id)
    tenant_cfg = load_cognify_config(tenant_id, db_url)
    result.auto_accept_threshold = float(tenant_cfg["auto_accept_threshold"])
    budget = tenant_cfg.get("daily_budget_usd")
    spent_before = float(tenant_cfg.get("spent_today_usd") or 0)
    if budget is not None and spent_before >= budget:
        result.status = "failed"
        result.error = daily_budget_error(budget, spent_before)
        result.duration_seconds = time.monotonic() - start
        return result

    if not await is_neo4j_available():
        result.status = "failed"
        result.error = "Neo4j is not available. Start the Neo4j container."
        return result

    await ensure_schema()
    await ensure_kb_keys(kb_id, tenant_id)
    ontology = await asyncio.to_thread(load_active_ontology, kb_id, db_url)
    ctx = build_context(kb_id, tenant_id, job_id, cfg, db_url, tenant_cfg, ontology)
    if ctx.force:
        for doc in documents:
            await asyncio.to_thread(
                store.clear_ledger, db_url, kb_id, str(doc.get("id"))
            )
    gate = asyncio.Semaphore(max(1, int(tenant_cfg["max_parallel_docs"])))

    async def _one(doc: dict[str, Any]) -> DocumentOutcome | None:
        async with gate:
            if result.stop_reason:
                result.documents_skipped_budget += 1
                return None
            return await cognify_document(ctx, doc)

    todo = [doc for doc in documents if doc.get("chunks")]
    for fut in asyncio.as_completed([_one(doc) for doc in todo]):
        try:
            outcome = await fut
        except GraphUnavailable as e:
            result.stop_reason = STOP_GRAPH_DOWN
            result.error = f"{stop_message(STOP_GRAPH_DOWN)} {e}"
            continue
        if outcome is None:
            continue
        result.documents_processed += 1
        _merge_outcome(result, outcome, ctx.model)
        if outcome.stop_reason and not result.stop_reason:
            result.stop_reason = outcome.stop_reason
        if outcome.finished and ctx.selection.covers_everything and db_url:
            await asyncio.to_thread(
                store.mark_document_cognified, db_url, outcome.document_id, job_id
            )

    if result.stop_reason in STOP_MESSAGES and not result.error:
        result.error = stop_message(
            result.stop_reason, ctx.job_budget, result.total_cost
        )
        if result.documents_skipped_budget:
            result.error += (
                f" {result.documents_skipped_budget} document(s) were not processed."
            )
    if result.stop_reason:
        result.status = "stopped"
    elif result.chunks_failed:
        result.error = (
            f"{result.chunks_failed} chunk(s) failed. Run Cognify again to retry them."
        )
    if result.entities_after_resolution or result.chunks_analyzed:
        await asyncio.to_thread(store.refresh_kb_counters, db_url, kb_id)
    result.duration_seconds = time.monotonic() - start
    logger.info(
        "Cognify [%s] %s: %d entities, %d relationships, %.1fs, $%.4f",
        job_id[:8],
        result.status,
        result.entities_after_resolution,
        result.relationships_written,
        result.duration_seconds,
        result.total_cost,
    )
    return result


def load_active_ontology(kb_id: str, db_url: str) -> BoundOntology | None:
    """The Atlas graph bound to this KB governs extraction, then the project's ontology."""
    if not db_url:
        return None
    try:
        from sqlalchemy import text

        with store.engine_for(db_url).connect() as conn:
            graph = conn.execute(
                text(
                    """
                    SELECT g.id, g.version, g.settings
                    FROM atlas_graphs g
                    JOIN knowledge_collections kb ON kb.id = g.kb_id
                    WHERE g.kb_id = CAST(:kb AS uuid)
                      AND g.tenant_id = kb.tenant_id
                      AND coalesce(g.settings->>'governs_extraction', 'true') <> 'false'
                      AND EXISTS (SELECT 1 FROM atlas_nodes n
                                  WHERE n.graph_id = g.id AND n.kind = 'concept')
                    ORDER BY (g.settings->>'governs_extraction') = 'true' DESC NULLS LAST,
                             g.updated_at DESC
                    LIMIT 1
                    """
                ),
                {"kb": kb_id},
            ).fetchone()
            if graph is not None:
                concepts = conn.execute(
                    text(
                        "SELECT id, label, description FROM atlas_nodes "
                        "WHERE graph_id = :g AND kind = 'concept' ORDER BY label LIMIT :n"
                    ),
                    {"g": graph[0], "n": MAX_ONTOLOGY_ROWS},
                ).fetchall()
                edges = conn.execute(
                    text(
                        """
                        SELECT e.id, e.label, e.description, f.label, t.label
                        FROM atlas_edges e
                        JOIN atlas_nodes f ON f.id = e.from_node_id AND f.kind = 'concept'
                        JOIN atlas_nodes t ON t.id = e.to_node_id AND t.kind = 'concept'
                        WHERE e.graph_id = :g ORDER BY e.label LIMIT :n
                        """
                    ),
                    {"g": graph[0], "n": MAX_ONTOLOGY_ROWS},
                ).fetchall()
                settings = graph[2] or {}
                return BoundOntology(
                    entity_types=[
                        {
                            "name": c[1],
                            "description": c[2] or "",
                            "concept_id": str(c[0]),
                        }
                        for c in concepts
                    ],
                    relationship_types=[
                        {
                            "name": e[1],
                            "description": e[2] or "",
                            "edge_id": str(e[0]),
                            "from": e[3],
                            "to": e[4],
                        }
                        for e in edges
                    ],
                    graph_id=str(graph[0]),
                    version=int(graph[1] or 0),
                    source="atlas",
                    strict=settings.get("ontology_mode", "strict") != "guided",
                )
            row = conn.execute(
                text(
                    """
                    SELECT s.entity_types, s.relationship_types
                    FROM knowledge_collections kb
                    JOIN knowledge_projects p ON p.id = kb.project_id
                    JOIN ontology_schemas s ON s.id = p.ontology_schema_id
                    WHERE kb.id = CAST(:kb_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"kb_id": kb_id},
            ).fetchone()
            if row is None:
                return None
            return as_bound(
                {"entity_types": row[0] or [], "relationship_types": row[1] or []}
            )
    except Exception as e:
        logger.warning("Failed to load active ontology for kb %s: %s", kb_id, e)
        return None


def _record_conflicts(tenant_id: str, kb_id: str, conflicts: list, db_url: str) -> int:
    """One cognify_conflicts row per disagreement, skipping ones already on file."""
    import uuid as uuid_mod

    from sqlalchemy import text

    def _doc(v: str) -> str | None:
        try:
            return str(uuid_mod.UUID(str(v)))
        except (TypeError, ValueError):
            return None

    written = 0
    try:
        with store.engine_for(db_url).begin() as conn:
            for c in conflicts:
                a_doc, b_doc = _doc(c.a_doc_id), _doc(c.b_doc_id)
                if not a_doc or not b_doc:
                    continue
                r = conn.execute(
                    text(
                        """
                        INSERT INTO cognify_conflicts (id, tenant_id, knowledge_base_id,
                            entity_canonical_name, property_name, source_a_doc_id,
                            source_a_value, source_a_confidence, source_b_doc_id,
                            source_b_value, source_b_confidence, status, resolved_value,
                            resolved_at)
                        SELECT CAST(:id AS uuid), CAST(:t AS uuid), CAST(:kb AS uuid), :entity,
                            :prop, CAST(:a_doc AS uuid), :a_val, :a_conf, CAST(:b_doc AS uuid),
                            :b_val, :b_conf, :status, :resolved,
                            CASE WHEN :status = 'open' THEN NULL ELSE now() END
                        WHERE NOT EXISTS (
                            SELECT 1 FROM cognify_conflicts
                            WHERE knowledge_base_id = CAST(:kb AS uuid)
                              AND entity_canonical_name = :entity
                              AND property_name = :prop
                              AND source_a_value = :a_val AND source_b_value = :b_val
                              AND status IN ('open', :status))
                        """
                    ),
                    {
                        "id": str(uuid_mod.uuid4()),
                        "t": tenant_id,
                        "kb": kb_id,
                        "entity": c.entity[:512],
                        "prop": c.property,
                        "a_doc": a_doc,
                        "a_val": c.a_value,
                        "a_conf": float(c.a_confidence),
                        "b_doc": b_doc,
                        "b_val": c.b_value,
                        "b_conf": float(c.b_confidence),
                        "status": c.status,
                        "resolved": c.resolved_value,
                    },
                )
                written += r.rowcount or 0
    except Exception as e:
        logger.warning("Could not record cognify conflicts for kb %s: %s", kb_id, e)
    return written
