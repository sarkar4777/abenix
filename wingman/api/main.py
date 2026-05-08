"""Wingman API — standalone FastAPI service for the energy-trading workspace.

Wingman is a thin app: every interesting computation lands in an Abenix
agent. The endpoints in this file are mostly:
  1. Read mock-but-real demo data from disk (corridors, broker emails).
  2. Forward the user's intent to an Abenix agent via the platform SDK.
  3. Stream the agent's live DAG events back to the browser as SSE.

Auth model: there is no Wingman user database yet. Every browser request
hits FastAPI directly (CORS-open) and we use a single delegated platform
API key + ActingSubject = (subject_type='wingman', subject_id='demo-trader').
The demo-trader subject is what the platform RBAC sees.

Real, citable data sources used (no Argus/Platts subscription required):
  - eia_open_data (US propane, WTI, Brent, Henry Hub)
  - yahoo_finance (Mont Belvieu propane futures)
  - open_meteo (free weather + marine forecast)
  - ais_stream (real-time AIS via AISStream.io free tier)
  - bunker_fuel (public bunker prices + bunker-derived freight estimate)
  - tavily_search (real news for narrative drivers)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# Vendored SDK lives at /app/sdk inside the image.
SDK_PATH = str(Path(__file__).resolve().parent / "sdk")
if SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)

from abenix_sdk import Abenix, ActingSubject  # type: ignore  # noqa: E402

logger = logging.getLogger("wingman.api")
logging.basicConfig(level=logging.INFO)

DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(name: str) -> Any:
    path = DATA_DIR / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


CORRIDORS: list[dict[str, Any]] = _load_json("corridors.json")
BROKER_EMAILS: list[dict[str, Any]] = _load_json("broker_emails.json")

# In-process state — replaced by Postgres in production. Wingman doesn't
# yet need its own DB; everything load-bearing lives on the platform.
_offers_state: dict[str, dict[str, Any]] = {}
_strategies_state: dict[str, dict[str, Any]] = {}
# 5-minute TTL cache for the market-brief panel — five upstream API
# calls in parallel is fine occasionally but burns rate limits if every
# tab refresh hits them.
_MARKET_BRIEF_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _build_subject(trader_id: str = "demo-trader") -> ActingSubject:
    return ActingSubject(
        subject_type=os.environ.get("WINGMAN_ACTING_SUBJECT_TYPE", "wingman"),
        subject_id=trader_id,
        email=f"{trader_id}@wingman.local",
        display_name=f"Wingman {trader_id.title()}",
    )


def _abenix_client(trader_id: str = "demo-trader") -> Abenix:
    api_key = os.environ.get("WINGMAN_ABENIX_API_KEY", "")
    base_url = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="WINGMAN_ABENIX_API_KEY not configured on the wingman-api pod.",
        )
    return Abenix(api_key=api_key, base_url=base_url, act_as=_build_subject(trader_id))


app = FastAPI(title="Wingman API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "wingman-api",
        "abenix_url": os.environ.get("ABENIX_API_URL", ""),
        "abenix_sdk_configured": bool(os.environ.get("WINGMAN_ABENIX_API_KEY")),
    }


# ─── Corridors / Arbitrage Workbench ─────────────────────────────────────


@app.get("/api/wingman/corridors")
async def list_corridors() -> dict[str, Any]:
    return {"data": CORRIDORS}


@app.get("/api/wingman/market-brief")
async def market_brief() -> dict[str, Any]:
    """Live market snapshot for the trader's morning brief.

    Thin endpoint — fires the wingman-market-brief agent on the platform.
    The agent uses the existing eia_open_data + ecb_rates + ais_stream
    tools; all data-fetching logic lives on the platform side.
    Cached in-process for 5 minutes so a busy floor doesn't burn LLM
    cost on every tab refresh.
    """
    import time

    cache_key = "market_brief"
    now = time.time()
    cached = _MARKET_BRIEF_CACHE.get(cache_key)
    if cached and now - cached[0] < 300:
        return {"data": cached[1]}

    async with _abenix_client() as forge:
        try:
            result = await forge.execute(
                "wingman-market-brief",
                "{}",
                wait_timeout_seconds=180,
            )
        except Exception as e:
            logger.exception("market-brief agent failed")
            raise HTTPException(status_code=502, detail=f"Market brief failed: {e}")

    parsed: dict[str, Any] = {}
    raw = result.output or ""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        s = raw.strip()
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last > first:
            try:
                parsed = json.loads(s[first : last + 1])
            except Exception:
                parsed = {}

    # Pull the platform's error fields directly so a failed market-brief
    # doesn't render as silent empty cards. Without this the previous
    # behaviour cached an empty payload for 5 minutes and the next 30s
    # poll just refreshed the same blank state.
    errors = getattr(result, "errors", []) or []
    err_msg = ""
    if errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        err_msg = str(first.get("message") or first.get("error") or first or "")
    elif (result.status or "").lower() in {"failed", "error"}:
        err_msg = "Agent run failed (no error detail returned by platform)."
    payload = {
        **(parsed or {}),
        "execution_id": result.execution_id,
        "generated_at": now,
        "error_message": err_msg or None,
    }
    indicators = payload.get("indicators") or []
    # Only cache successful runs so the next refresh re-tries on failure.
    if indicators and not err_msg:
        _MARKET_BRIEF_CACHE[cache_key] = (now, payload)
    return {"data": payload}


def _parse_agent_json(raw: str) -> dict[str, Any]:
    """Tolerant JSON parse — try the whole body, then a brace-balance subset."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        s = raw.strip()
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last > first:
            try:
                return json.loads(s[first : last + 1])
            except Exception:
                return {}
        return {}


# corridor_id keyed by execution_id, so the result endpoint can echo it
# back without the frontend having to round-trip it.
_ANALYZE_INDEX: dict[str, str] = {}


@app.post("/api/wingman/corridors/{corridor_id}/analyze")
async def analyze_corridor(
    corridor_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Submit wingman-arb-analyzer and return the execution_id immediately.

    The agent runs asynchronously on a platform runtime pool. The frontend
    opens the Live DAG drawer on the returned execution_id (so it streams
    events while the agent works) and polls /api/wingman/analyze-result/
    until the agent terminates.
    """
    corridor = next((c for c in CORRIDORS if c["id"] == corridor_id), None)
    if not corridor:
        raise HTTPException(
            status_code=404, detail=f"Corridor not found: {corridor_id}"
        )

    body = body or {}
    tenor = int(body.get("tenor_months") or 12)
    methodology = body.get("methodology") or "deep"

    payload = {
        "corridor": corridor,
        "tenor_months": tenor,
        "methodology": methodology,
    }

    async with _abenix_client() as forge:
        try:
            submitted = await forge.execute(
                "wingman-arb-analyzer",
                json.dumps(payload),
                wait="submitted",
            )
        except Exception as e:
            logger.exception("arb-analyzer submit failed")
            raise HTTPException(status_code=502, detail=f"Agent submit failed: {e}")

    if submitted.execution_id:
        _ANALYZE_INDEX[submitted.execution_id] = corridor_id

    return {
        "data": {
            "corridor_id": corridor_id,
            "execution_id": submitted.execution_id,
            "status": submitted.status or "running",
        }
    }


@app.get("/api/wingman/analyze-result/{execution_id}")
async def analyze_result(execution_id: str) -> dict[str, Any]:
    """Return the parsed analyzer result if the execution is terminal.

    Status is one of: running | completed | failed. When `running`, the
    `result` field is null and the frontend keeps polling.
    """
    async with _abenix_client() as forge:
        try:
            row = await forge.executions.get(execution_id) or {}
        except Exception as e:
            logger.warning("execution fetch failed for %s: %s", execution_id, e)
            raise HTTPException(status_code=502, detail=f"Execution fetch failed: {e}")

    status = (row.get("status") or "running").lower()
    terminal = status in {"completed", "succeeded", "failed", "error", "cancelled"}
    parsed: dict[str, Any] = {}
    raw = row.get("output") or row.get("output_message") or ""
    if terminal and raw:
        parsed = _parse_agent_json(raw)

    return {
        "data": {
            "corridor_id": _ANALYZE_INDEX.get(execution_id),
            "execution_id": execution_id,
            "status": status,
            "result": (
                parsed
                if parsed
                else (
                    {"narrative": (raw or "")[:2000], "data_quality": "unparsed"}
                    if terminal
                    else None
                )
            ),
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
    }


# ─── Broker Inbox ────────────────────────────────────────────────────────


@app.get("/api/wingman/inbox")
async def list_broker_emails() -> dict[str, Any]:
    return {"data": BROKER_EMAILS}


# execution_id → email_id, so the result endpoint can echo it back without
# the frontend round-tripping it. Mirrors _ANALYZE_INDEX above.
_CLASSIFY_INDEX: dict[str, str] = {}
_PARSE_INDEX: dict[str, str] = {}


@app.post("/api/wingman/inbox/{email_id}/classify")
async def classify_broker_email(email_id: str) -> dict[str, Any]:
    """Submit wingman-broker-classifier and return execution_id immediately.

    The frontend opens the DAG drawer on the returned id (so SSE events
    stream while the agent still runs) and polls /classify-result for the
    structured payload.
    """
    email = next((e for e in BROKER_EMAILS if e["id"] == email_id), None)
    if not email:
        raise HTTPException(status_code=404, detail=f"Email not found: {email_id}")
    async with _abenix_client() as forge:
        submitted = await forge.execute(
            "wingman-broker-classifier",
            json.dumps({"body": email.get("body", "")}),
            wait="submitted",
        )
    if submitted.execution_id:
        _CLASSIFY_INDEX[submitted.execution_id] = email_id
    return {
        "data": {
            "email_id": email_id,
            "execution_id": submitted.execution_id,
            "status": submitted.status or "running",
        }
    }


@app.get("/api/wingman/classify-result/{execution_id}")
async def classify_result(execution_id: str) -> dict[str, Any]:
    """Return parsed classifier output once the execution is terminal."""
    async with _abenix_client() as forge:
        try:
            row = await forge.executions.get(execution_id) or {}
        except Exception as e:
            logger.warning("execution fetch failed for %s: %s", execution_id, e)
            raise HTTPException(status_code=502, detail=f"Execution fetch failed: {e}")
    status = (row.get("status") or "running").lower()
    terminal = status in {"completed", "succeeded", "failed", "error", "cancelled"}
    parsed: dict[str, Any] = {}
    raw = row.get("output") or row.get("output_message") or ""
    if terminal and raw:
        parsed = _parse_agent_json(raw)
    return {
        "data": {
            "email_id": _CLASSIFY_INDEX.get(execution_id),
            "execution_id": execution_id,
            "status": status,
            "classification": parsed if parsed else None,
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
    }


@app.post("/api/wingman/strategy/{rule_id}/var")
async def run_var(rule_id: str) -> dict[str, Any]:
    """Run the Monte Carlo VaR Go simulator on a strategy rule."""
    rule = _strategies_state.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    async with _abenix_client() as forge:
        result = await forge.execute(
            "wingman-var-simulator",
            json.dumps({"rule": rule, "horizon_days": 30, "n_simulations": 10000}),
            wait_timeout_seconds=300,
        )
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(result.output or "")
    except Exception:
        s = (result.output or "").strip()
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last > first:
            try:
                parsed = json.loads(s[first : last + 1])
            except Exception:
                pass
    return {
        "data": {
            "rule_id": rule_id,
            "execution_id": result.execution_id,
            "var": parsed,
            "cost_usd": result.cost,
            "duration_ms": result.duration_ms,
        }
    }


@app.post("/api/wingman/inbox/{email_id}/parse")
async def parse_broker_email(email_id: str) -> dict[str, Any]:
    """Submit wingman-broker-parser and return execution_id immediately."""
    email = next((e for e in BROKER_EMAILS if e["id"] == email_id), None)
    if not email:
        raise HTTPException(status_code=404, detail=f"Email not found: {email_id}")
    async with _abenix_client() as forge:
        submitted = await forge.execute(
            "wingman-broker-parser",
            json.dumps(email),
            wait="submitted",
        )
    if submitted.execution_id:
        _PARSE_INDEX[submitted.execution_id] = email_id
    return {
        "data": {
            "email_id": email_id,
            "execution_id": submitted.execution_id,
            "status": submitted.status or "running",
        }
    }


@app.get("/api/wingman/parse-result/{execution_id}")
async def parse_result(execution_id: str) -> dict[str, Any]:
    """Return parsed offer once the parser execution is terminal."""
    async with _abenix_client() as forge:
        try:
            row = await forge.executions.get(execution_id) or {}
        except Exception as e:
            logger.warning("execution fetch failed for %s: %s", execution_id, e)
            raise HTTPException(status_code=502, detail=f"Execution fetch failed: {e}")
    status = (row.get("status") or "running").lower()
    terminal = status in {"completed", "succeeded", "failed", "error", "cancelled"}
    parsed: dict[str, Any] = {}
    raw = row.get("output") or row.get("output_message") or ""
    if terminal and raw:
        parsed = _parse_agent_json(raw)

    email_id = _PARSE_INDEX.get(execution_id)
    offer_payload: dict[str, Any] | None = None
    if terminal and parsed and email_id:
        # Idempotent: only mint a new offer row the first time we see a
        # terminal execution with parsed output. Subsequent polls return
        # the same offer.
        existing = next(
            (
                o
                for o in _offers_state.values()
                if o.get("source_execution_id") == execution_id
            ),
            None,
        )
        if existing:
            offer_payload = existing
        else:
            offer_id = f"offer-{uuid.uuid4().hex[:8]}"
            offer_payload = {
                **parsed,
                "id": offer_id,
                "source_email_id": email_id,
                "source_execution_id": execution_id,
            }
            _offers_state[offer_id] = offer_payload
    return {
        "data": {
            "email_id": email_id,
            "execution_id": execution_id,
            "status": status,
            "offer": offer_payload,
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
    }


@app.get("/api/wingman/offers")
async def list_offers() -> dict[str, Any]:
    return {"data": list(_offers_state.values())}


@app.post("/api/wingman/offers/{offer_id}/acknowledge")
async def acknowledge_offer(offer_id: str) -> dict[str, Any]:
    """HITL-gated acknowledge — opens an approval_gate via the platform."""
    offer = _offers_state.get(offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail=f"Offer not found: {offer_id}")

    async with _abenix_client() as forge:
        ref_payload = {
            "intent": "broker_acknowledge",
            "offer_id": offer_id,
            "summary": (
                f"Acknowledge to broker: {offer.get('volume_mt', '?')}kt "
                f"{offer.get('grade', '?')} {offer.get('port', '?')} "
                f"@ {offer.get('pricing', '?')}"
            ),
            "offer": offer,
        }
        approval = await forge.approvals.create(
            title=ref_payload["summary"],
            payload=ref_payload,
            required_signoffs=1,
            expires_seconds=7200,
            gate_kind="broker.acknowledge",
        )
    return {
        "data": {
            "approval_id": approval.get("id"),
            "approval": approval,
            "offer_id": offer_id,
        }
    }


# ─── Operations Watch ────────────────────────────────────────────────────


@app.get("/api/wingman/ops/snapshot")
async def ops_snapshot() -> dict[str, Any]:
    """Single call to wingman-ops-monitor — returns vessels + weather + ranked alerts."""
    async with _abenix_client() as forge:
        result = await forge.execute(
            "wingman-ops-monitor",
            json.dumps({"corridors": [c["id"] for c in CORRIDORS if c.get("active")]}),
            wait_timeout_seconds=300,
        )
    parsed: dict[str, Any] = {}
    raw = result.output or ""
    try:
        parsed = json.loads(raw)
    except Exception:
        s = raw.strip()
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last > first:
            try:
                parsed = json.loads(s[first : last + 1])
            except Exception:
                parsed = {"narrative": raw[:1500]}
    return {
        "data": {
            "execution_id": result.execution_id,
            "snapshot": parsed,
            "cost_usd": result.cost,
            "duration_ms": result.duration_ms,
        }
    }


# ─── Strategy Lab ────────────────────────────────────────────────────────


@app.post("/api/wingman/strategy/encode")
async def encode_strategy(body: dict[str, Any]) -> dict[str, Any]:
    """Translate plain-English strategy intent to a structured rule."""
    nl = (body or {}).get("intent") or ""
    if not nl:
        raise HTTPException(
            status_code=400, detail="intent (plain English) is required"
        )
    async with _abenix_client() as forge:
        result = await forge.execute(
            "wingman-strategy-encoder",
            json.dumps({"intent": nl, "corridors": [c["id"] for c in CORRIDORS]}),
            wait_timeout_seconds=180,
        )
    parsed: dict[str, Any] = {}
    raw = result.output or ""
    try:
        parsed = json.loads(raw)
    except Exception:
        s = raw.strip()
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last > first:
            try:
                parsed = json.loads(s[first : last + 1])
            except Exception:
                pass
    rule_id = f"rule-{uuid.uuid4().hex[:8]}"
    if parsed:
        _strategies_state[rule_id] = {
            **parsed,
            "id": rule_id,
            "intent": nl,
            "active": False,
        }
    return {
        "data": {
            "rule_id": rule_id,
            "execution_id": result.execution_id,
            "rule": parsed,
            "cost_usd": result.cost,
            "duration_ms": result.duration_ms,
        }
    }


@app.post("/api/wingman/strategy/{rule_id}/backtest")
async def backtest_strategy(rule_id: str) -> dict[str, Any]:
    rule = _strategies_state.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    async with _abenix_client() as forge:
        result = await forge.execute(
            "wingman-backtester",
            json.dumps({"rule": rule}),
            wait_timeout_seconds=300,
        )
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(result.output or "")
    except Exception:
        s = (result.output or "").strip()
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last > first:
            try:
                parsed = json.loads(s[first : last + 1])
            except Exception:
                pass
    return {
        "data": {
            "rule_id": rule_id,
            "execution_id": result.execution_id,
            "backtest": parsed,
            "cost_usd": result.cost,
            "duration_ms": result.duration_ms,
        }
    }


@app.get("/api/wingman/strategy")
async def list_strategies() -> dict[str, Any]:
    return {"data": list(_strategies_state.values())}


@app.post("/api/wingman/strategy/{rule_id}/activate")
async def activate_strategy(rule_id: str) -> dict[str, Any]:
    rule = _strategies_state.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    async with _abenix_client() as forge:
        approval = await forge.approvals.create(
            title=f"Activate strategy: {rule.get('intent', '')[:80]}",
            payload={"intent": "strategy_activate", "rule_id": rule_id, "rule": rule},
            required_signoffs=1,
            expires_seconds=86400,
            gate_kind="strategy.activate",
        )
    return {
        "data": {
            "approval_id": approval.get("id"),
            "approval": approval,
            "rule_id": rule_id,
        }
    }


# ─── Forward Scenarios ───────────────────────────────────────────────────


# execution_id → corridor_id, mirroring _ANALYZE_INDEX. Lets the result
# endpoint echo the corridor without the frontend round-tripping it.
_SCENARIO_INDEX: dict[str, str] = {}
# Per-corridor cache of the last successful forecast. Forecasts are
# expensive (5+ tool calls including 4 Tavily searches + a Sonnet 4.5
# loop), so a 15-minute hold makes a busy desk re-render the same view
# without re-burning the agent.
_SCENARIO_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SCENARIO_TTL_SECONDS = 900


@app.post("/api/wingman/scenarios/{corridor_id}/forecast")
async def forecast_scenarios(
    corridor_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Submit wingman-scenario-forecaster and return execution_id.

    Streams the live DAG (Bayesian prior + 4 Tavily searches + curve
    math) into the drawer. Frontend polls /scenario-result for the
    final structured envelope.
    """
    corridor = next((c for c in CORRIDORS if c["id"] == corridor_id), None)
    if not corridor:
        raise HTTPException(
            status_code=404, detail=f"Corridor not found: {corridor_id}"
        )
    body = body or {}
    payload = {
        "corridor": corridor,
        "tenor_months": int(body.get("tenor_months") or 12),
    }
    async with _abenix_client() as forge:
        submitted = await forge.execute(
            "wingman-scenario-forecaster",
            json.dumps(payload),
            wait="submitted",
        )
    if submitted.execution_id:
        _SCENARIO_INDEX[submitted.execution_id] = corridor_id
    return {
        "data": {
            "corridor_id": corridor_id,
            "execution_id": submitted.execution_id,
            "status": submitted.status or "running",
        }
    }


@app.get("/api/wingman/scenario-result/{execution_id}")
async def scenario_result(execution_id: str) -> dict[str, Any]:
    """Return parsed forecaster output once the execution is terminal."""
    async with _abenix_client() as forge:
        try:
            row = await forge.executions.get(execution_id) or {}
        except Exception as e:
            logger.warning("execution fetch failed for %s: %s", execution_id, e)
            raise HTTPException(status_code=502, detail=f"Execution fetch failed: {e}")
    status = (row.get("status") or "running").lower()
    terminal = status in {"completed", "succeeded", "failed", "error", "cancelled"}
    parsed: dict[str, Any] = {}
    raw = row.get("output") or row.get("output_message") or ""
    if terminal and raw:
        parsed = _parse_agent_json(raw)
    corridor_id = _SCENARIO_INDEX.get(execution_id)
    if status == "completed" and parsed and corridor_id:
        import time as _time

        _SCENARIO_CACHE[corridor_id] = (_time.time(), parsed)
    return {
        "data": {
            "corridor_id": corridor_id,
            "execution_id": execution_id,
            "status": status,
            "forecast": parsed if parsed else None,
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
    }


@app.get("/api/wingman/scenarios/{corridor_id}/cached")
async def scenarios_cached(corridor_id: str) -> dict[str, Any]:
    """Return the most recent successful forecast for a corridor, if fresh."""
    import time as _time

    cached = _SCENARIO_CACHE.get(corridor_id)
    if not cached:
        return {"data": None}
    ts, payload = cached
    if _time.time() - ts > _SCENARIO_TTL_SECONDS:
        return {"data": None}
    return {
        "data": {
            "corridor_id": corridor_id,
            "generated_at": ts,
            "forecast": payload,
        }
    }


# ─── Knowledge Graph (Atlas) ─────────────────────────────────────────────


@app.post("/api/wingman/graph/query")
async def graph_query(body: dict[str, Any]) -> dict[str, Any]:
    """Run a natural-language graph query through wingman-graph-query.

    The agent uses the Atlas knowledge_search tool to traverse the typed
    ontology (corridors → vessels → counterparties → offers → events) and
    returns a structured subgraph + narrative.
    """
    question = (body or {}).get("question") or ""
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    async with _abenix_client() as forge:
        result = await forge.execute(
            "wingman-graph-query",
            json.dumps({"question": question}),
            wait_timeout_seconds=240,
        )
    parsed: dict[str, Any] = {}
    raw = result.output or ""
    try:
        parsed = json.loads(raw)
    except Exception:
        s = raw.strip()
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last > first:
            try:
                parsed = json.loads(s[first : last + 1])
            except Exception:
                parsed = {"narrative": raw[:2000]}
    return {
        "data": {
            "execution_id": result.execution_id,
            "answer": parsed,
            "cost_usd": result.cost,
            "duration_ms": result.duration_ms,
        }
    }


# ─── Approvals (HITL queue) ─────────────────────────────────────────────
# All approvals operations go through the SDK so the wingman pod holds no
# platform credentials of its own and the platform's RBAC is the source
# of truth for who can sign off.


@app.get("/api/wingman/approvals")
async def list_approvals(status: str = "pending") -> dict[str, Any]:
    async with _abenix_client() as forge:
        items = await forge.approvals.list(status=status, limit=200)
    return {"data": items}


@app.get("/api/wingman/approvals/{approval_id}")
async def get_approval(approval_id: str) -> dict[str, Any]:
    async with _abenix_client() as forge:
        row = await forge.approvals.get(approval_id)
    return {"data": row}


@app.post("/api/wingman/approvals/{approval_id}/approve")
async def approve_approval(
    approval_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = body or {}
    async with _abenix_client() as forge:
        row = await forge.approvals.approve(
            approval_id, reason=str(body.get("reason") or "")
        )
    return {"data": row}


@app.post("/api/wingman/approvals/{approval_id}/deny")
async def deny_approval(
    approval_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = body or {}
    async with _abenix_client() as forge:
        row = await forge.approvals.deny(
            approval_id, reason=str(body.get("reason") or "")
        )
    return {"data": row}


# ─── Execution detail passthrough ──────────────────────────────────────


@app.get("/api/wingman/executions/{execution_id}")
async def execution_detail(execution_id: str) -> dict[str, Any]:
    """Forward the platform's full execution row.

    Useful when the trader UI shows FAILED but the page has no
    error_message — this endpoint surfaces error_message, failure_code,
    tool_calls and the raw output without needing a platform admin token.
    """
    async with _abenix_client() as forge:
        try:
            row = await forge.executions.get(execution_id) or {}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Execution fetch failed: {e}")
    return {"data": row}


# ─── Live DAG passthrough (via SDK) ─────────────────────────────────────


@app.get("/api/wingman/executions/{execution_id}/watch")
async def watch_execution(execution_id: str) -> StreamingResponse:
    """Pipe the platform's live DAG SSE stream through to the browser.

    Routed through ``forge.executions.watch_raw_sse`` so the auth, base URL
    and httpx connection pool come from the SDK — the standalone app holds
    no platform credentials of its own outside the SDK construction.
    """

    async def _proxy():
        async with _abenix_client() as forge:
            async for chunk in forge.executions.watch_raw_sse(execution_id):
                yield chunk

    return StreamingResponse(
        _proxy(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Tool catalog passthrough (for AI Builder linking) ──────────────────


@app.get("/api/wingman/tools")
async def list_tools() -> dict[str, Any]:
    """Forward the platform tool catalog via ``forge.tools.list()`` so the
    Wingman builder palette sees the same set as the main Abenix builder
    and the call goes through SDK-managed auth."""
    async with _abenix_client() as forge:
        items = await forge.tools.list()
    return {"data": items}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8006"))
    uvicorn.run(app, host="0.0.0.0", port=port)
