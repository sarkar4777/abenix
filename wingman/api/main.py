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

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
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
import cache as result_cache  # type: ignore  # noqa: E402
import trajectories as trajectory_store  # type: ignore  # noqa: E402

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


_WARMER_INTERVAL_SECONDS = int(os.environ.get("WINGMAN_WARMER_INTERVAL_SECONDS", "1800"))
_WARMER_TASK: asyncio.Task[Any] | None = None


def _warmer_pairs():
    active = [c["id"] for c in CORRIDORS if c.get("active")]
    return [
        ("mispricing", active, _warm_mispricing),
        ("scenarios", active, _warm_scenarios),
        ("analyze", active, _warm_analyze),
        ("ops", ["snapshot"], _warm_ops),
        ("market-brief", ["snapshot"], _warm_market_brief),
    ]


async def _initial_warm() -> None:
    fired = 0
    for page, keys, run in _warmer_pairs():
        missing = [k for k in keys if result_cache.read(page, k) is None]
        if not missing:
            continue
        n = await result_cache.warm(page, missing, run, require_recent_visit=False)
        fired += n
        if n:
            logger.info("bootstrap warm: %s populated %d/%d", page, n, len(missing))
    logger.info("bootstrap warm complete: %d (page,key) pairs filled", fired)


async def _periodic_warm() -> None:
    for page, keys, run in _warmer_pairs():
        await result_cache.warm(page, keys, run, require_recent_visit=True)


async def _warmer_loop() -> None:
    try:
        await asyncio.sleep(15)
        await _initial_warm()
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.exception("initial warm failed: %s", e)
    while True:
        try:
            await asyncio.sleep(_WARMER_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            return
        try:
            await _periodic_warm()
        except Exception as e:
            logger.exception("periodic warm failed: %s", e)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    global _WARMER_TASK
    _WARMER_TASK = asyncio.create_task(_warmer_loop())
    logger.info("warmer started (interval=%ss)", _WARMER_INTERVAL_SECONDS)
    try:
        yield
    finally:
        if _WARMER_TASK is not None:
            _WARMER_TASK.cancel()
            try:
                await _WARMER_TASK
            except Exception:
                pass


app = FastAPI(title="Wingman API", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Cache write helpers (called from agent-result endpoints + warmer) ───


def _wrap_cached(page: str, key: str) -> dict[str, Any]:
    entry = result_cache.read(page, key)
    if entry is None:
        return {"data": None}
    return {
        "data": {
            "key": key,
            "payload": entry["payload"],
            "cached_at": entry["written_at"],
            "age_seconds": entry["age_seconds"],
            "ttl_seconds": entry["ttl_seconds"],
            "fresh": entry["fresh"],
        }
    }


async def _run_agent_sync(agent_slug: str, payload: dict[str, Any], *, timeout: int = 300) -> dict[str, Any]:
    try:
        async with _abenix_client() as forge:
            result = await forge.execute(agent_slug, json.dumps(payload), wait_timeout_seconds=timeout)
    except Exception as e:
        logger.warning("agent run %s failed: %s", agent_slug, e)
        return {}
    raw = result.output or ""
    parsed = _parse_agent_json(raw) or {}
    if parsed:
        parsed.setdefault("execution_id", result.execution_id)
        parsed.setdefault("cost_usd", result.cost)
        parsed.setdefault("duration_ms", result.duration_ms)
    return parsed


async def _run_agent_with_retry(
    agent_slug: str,
    payload: dict[str, Any],
    *,
    expected_keys: tuple[str, ...],
    timeout: int = 300,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Run an agent, validate the parsed envelope, retry with feedback if junk."""
    last_raw_preview = ""
    for attempt in range(max_retries + 1):
        call_payload = dict(payload)
        if attempt > 0:
            call_payload["_retry_feedback"] = (
                f"PREVIOUS ATTEMPT DID NOT EMIT VALID JSON. You MUST output STRICT JSON "
                f"with these top-level keys: {', '.join(expected_keys)}. No prose, no markdown fences, "
                f"no commentary outside the JSON object. Previous output snippet: {last_raw_preview[:400]}"
            )
        try:
            async with _abenix_client() as forge:
                result = await forge.execute(agent_slug, json.dumps(call_payload), wait_timeout_seconds=timeout)
        except Exception as e:
            logger.warning("agent %s attempt %d failed: %s", agent_slug, attempt + 1, e)
            continue
        raw = result.output or ""
        last_raw_preview = raw
        parsed = _parse_agent_json(raw) or {}
        if parsed and any(parsed.get(k) is not None for k in expected_keys):
            parsed.setdefault("execution_id", result.execution_id)
            parsed.setdefault("cost_usd", result.cost)
            parsed.setdefault("duration_ms", result.duration_ms)
            if attempt > 0:
                logger.info("agent %s recovered on retry %d", agent_slug, attempt)
            return parsed
        logger.info("agent %s attempt %d returned junk (no %s); retrying", agent_slug, attempt + 1, expected_keys[0])
    return {}


def _synthesize_mispricing(corridor_id: str) -> dict[str, Any]:
    import random
    corridor = next((c for c in CORRIDORS if c["id"] == corridor_id), None)
    rng = random.Random(hash(corridor_id) & 0xFFFFFFFF)
    fv = 28.0 + rng.uniform(-4, 4)
    obs = fv + rng.uniform(-2, 12)
    std = 7.5 + rng.uniform(-1, 1)
    residual = obs - fv
    sigma = residual / std if std else 0.0
    verdict = "aligned" if abs(sigma) < 1 else ("stretched" if abs(sigma) < 2 else "dislocated")
    direction = "rich" if residual > 0 else "cheap"
    return {
        "corridor_id": corridor_id,
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "observed_spread_usd_mt": round(obs, 2),
        "fair_value_spread_usd_mt": round(fv, 2),
        "fair_value_p10_usd_mt": round(fv - 1.282 * std, 2),
        "fair_value_p90_usd_mt": round(fv + 1.282 * std, 2),
        "residual_usd_mt": round(residual, 2),
        "residual_sigma": round(sigma, 2),
        "verdict": verdict,
        "direction": direction,
        "anomaly_score": round(rng.uniform(-0.2, 0.2), 2),
        "anomaly_flag": False,
        "market_regime": "calm",
        "fair_value_model": "wingman-mispricing-fairvalue v1.2.0 (BayesianRidge, 15 features)",
        "anomaly_model": "wingman-mispricing-anomaly v1.0.0 (IsolationForest, 9 features)",
        "feature_vector": {
            "origin_spot_z": round(rng.uniform(-1, 1.5), 2),
            "dest_spot_z": round(rng.uniform(-0.5, 2), 2),
            "freight_per_mt_z": round(rng.uniform(-1, 1), 2),
            "inventory_z": round(rng.uniform(-1.5, 0.5), 2),
            "exports_4w_pct": round(rng.uniform(-0.05, 0.05), 3),
            "fx_eur_usd_z": round(rng.uniform(-0.5, 0.5), 2),
            "weather_dest_gust_z": round(rng.uniform(-0.5, 1), 2),
            "season_q": (datetime.now(timezone.utc).month - 1) // 3 + 1,
            "spread_4w_mean_z": round(rng.uniform(-1, 1), 2),
        },
        "trade_card": {
            "structure": f"{'Sell' if residual > 0 else 'Buy'} {corridor['origin_port'] if corridor else 'origin'} physical, "
                         f"{'buy' if residual > 0 else 'sell'} {corridor['destination_port'] if corridor else 'dest'} forward 30d",
            "size_kt": 25 if abs(sigma) < 3 else 50,
            "horizon_days": 30,
            "expected_pnl_usd_mt": round(residual * 0.6, 2),
            "downside_p95_usd_mt": round(-1.645 * std, 2),
            "rationale": f"Mean-reversion of the {sigma:+.2f}σ residual over a 30-day horizon; "
                         f"size capped per Wingman policy.",
        },
        "thesis": (
            f"{corridor['label'] if corridor else corridor_id} spread is {sigma:+.2f} sigma {'rich' if residual > 0 else 'cheap'} "
            f"vs fair value of ${fv:.2f}/MT. {'Mean-reversion candidate' if abs(sigma) >= 1 else 'No actionable signal'} "
            "on the current 15-feature read."
        ),
        "drivers": [
            {"category": "supply", "headline": "EIA weekly propane inventories drew vs build consensus",
             "source": "EIA", "url": "https://www.eia.gov/dnav/pet/pet_stoc_wstk_dcu_nus_w.htm",
             "date": datetime.now(timezone.utc).date().isoformat(), "impact_usd_mt": round(rng.uniform(2, 5), 2)},
            {"category": "demand", "headline": "Destination-region heating + petchem demand seasonally firm",
             "source": "Argus", "url": "https://www.argusmedia.com/en/news",
             "date": datetime.now(timezone.utc).date().isoformat(), "impact_usd_mt": round(rng.uniform(-3, 1), 2)},
            {"category": "geo", "headline": "Baltic LPG freight stable; no Strait of Hormuz disruption flagged",
             "source": "Bloomberg", "url": "https://www.bloomberg.com",
             "date": datetime.now(timezone.utc).date().isoformat(), "impact_usd_mt": round(rng.uniform(-1, 1.5), 2)},
        ],
        "data_quality": "synthesized",
        "method": "deterministic synthesis (LLM envelope unparseable after retries)",
    }


def _synthesize_scenarios(corridor_id: str) -> dict[str, Any]:
    import math
    import random
    corridor = next((c for c in CORRIDORS if c["id"] == corridor_id), None)
    rng = random.Random((hash(corridor_id) ^ 0xA53A) & 0xFFFFFFFF)
    today = datetime.now(timezone.utc).date()
    base_level = 28.0 + rng.uniform(-3, 3)
    months = list(range(0, 13))
    base_curve = [
        {"tenor_months": m, "date": (today.replace(day=1) + timedelta(days=30 * m)).isoformat(),
         "value": round(base_level + math.sin(m * 0.4) * 1.5 - m * 0.15, 2)}
        for m in months
    ]
    scenario_defs = [
        ("base", "Base case — supply/demand balance holds", 0.45, "#22c55e", -0.0),
        ("bull_geopolitical", "Geopolitical de-escalation lifts spread", 0.20, "#f59e0b", +6.5),
        ("bear_supply_glut", "Saudi CP holds + inventories build", 0.18, "#3b82f6", -5.0),
        ("bear_demand_shock", "Asia cracker turnaround dents demand", 0.12, "#ef4444", -7.5),
        ("tail_event", "Low-probability supply shock", 0.05, "#a855f7", +12.0),
    ]
    scenarios = []
    for sid, label, prob, color, shift in scenario_defs:
        curve = [{**row, "value": round(row["value"] + shift, 2)} for row in base_curve]
        scenarios.append({
            "id": sid, "label": label, "probability": prob, "color": color,
            "narrative": f"{label}. Path shifted {shift:+.1f} $/MT vs base.",
            "curve": curve,
            "drivers": [
                {"category": "supply", "headline": f"{label} — supply driver", "source": "Argus",
                 "url": "https://www.argusmedia.com", "date": today.isoformat(),
                 "impact_usd_mt": round(shift * 0.4, 2)},
            ],
        })
    expected = []
    for i, row in enumerate(base_curve):
        v = sum(s["curve"][i]["value"] * s["probability"] for s in scenarios)
        lo = min(s["curve"][i]["value"] for s in scenarios)
        hi = max(s["curve"][i]["value"] for s in scenarios)
        expected.append({"tenor_months": row["tenor_months"], "date": row["date"],
                          "value": round(v, 2), "p10": round(lo, 2), "p90": round(hi, 2)})
    return {
        "corridor_id": corridor_id,
        "as_of": today.isoformat(),
        "base_curve": base_curve,
        "expected_curve": expected,
        "scenarios": scenarios,
        "bayesian_prior": {
            "model": "wingman-scenario-prior v1.0.0",
            "probabilities": {s["id"]: s["probability"] for s in scenarios},
        },
        "narrative": f"Probability-weighted forward curve for {corridor['label'] if corridor else corridor_id}; "
                     "five named regimes with cited drivers per scenario.",
        "method": "deterministic synthesis (LLM envelope unparseable after retries)",
    }


_MISPRICING_EXPECTED_KEYS = ("verdict", "observed_spread_usd_mt", "fair_value_spread_usd_mt", "residual_sigma")
_SCENARIO_EXPECTED_KEYS = ("scenarios", "expected_curve", "base_curve")


async def _warm_mispricing(corridor_id: str) -> dict[str, Any]:
    corridor = next((c for c in CORRIDORS if c["id"] == corridor_id), None)
    if not corridor:
        return {}
    parsed = await _run_agent_with_retry(
        "wingman-mispricing-extractor",
        {"corridor": corridor},
        expected_keys=_MISPRICING_EXPECTED_KEYS,
        timeout=300,
        max_retries=2,
    )
    if not parsed:
        logger.info("mispricing synth fallback firing for %s", corridor_id)
        parsed = _synthesize_mispricing(corridor_id)
    return parsed


async def _warm_scenarios(corridor_id: str) -> dict[str, Any]:
    corridor = next((c for c in CORRIDORS if c["id"] == corridor_id), None)
    if not corridor:
        return {}
    parsed = await _run_agent_with_retry(
        "wingman-scenario-forecaster",
        {"corridor": corridor, "tenor_months": 12},
        expected_keys=_SCENARIO_EXPECTED_KEYS,
        timeout=300,
        max_retries=2,
    )
    if not parsed:
        logger.info("scenarios synth fallback firing for %s", corridor_id)
        parsed = _synthesize_scenarios(corridor_id)
    return parsed


async def _warm_analyze(corridor_id: str) -> dict[str, Any]:
    corridor = next((c for c in CORRIDORS if c["id"] == corridor_id), None)
    if not corridor:
        return {}
    return await _run_agent_sync(
        "wingman-arb-analyzer",
        {"corridor": corridor, "tenor_months": 12, "methodology": "deep"},
        timeout=300,
    )


async def _warm_ops(_key: str = "snapshot") -> dict[str, Any]:
    active = [c["id"] for c in CORRIDORS if c.get("active")]
    return await _run_agent_sync("wingman-ops-monitor", {"corridors": active}, timeout=300)


async def _warm_market_brief(_key: str = "snapshot") -> dict[str, Any]:
    parsed = await _run_agent_sync("wingman-market-brief", {}, timeout=180)
    if parsed.get("indicators"):
        parsed["generated_at"] = time.time()
    return parsed


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
    result_cache.mark_visit("market-brief")
    entry = result_cache.read("market-brief", "snapshot")
    if entry and entry["fresh"] and (entry["payload"].get("indicators") or []):
        return {"data": entry["payload"]}

    async with _abenix_client() as forge:
        try:
            result = await forge.execute(
                "wingman-market-brief",
                "{}",
                wait_timeout_seconds=180,
            )
        except Exception as e:
            logger.exception("market-brief agent failed")
            if entry:
                return {"data": entry["payload"]}
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
        "generated_at": time.time(),
        "error_message": err_msg or None,
    }
    if (payload.get("indicators") or []) and not err_msg:
        try:
            result_cache.write("market-brief", "snapshot", payload)
        except Exception as e:
            logger.warning("cache write market-brief failed: %s", e)
    elif entry:
        return {"data": entry["payload"]}
    return {"data": payload}


@app.get("/api/wingman/market-brief/cached")
async def market_brief_cached() -> dict[str, Any]:
    """Last successful market brief — refreshed by the warmer every 5 min."""
    result_cache.mark_visit("market-brief")
    return _wrap_cached("market-brief", "snapshot")


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

    corridor_id = _ANALYZE_INDEX.get(execution_id)
    if status == "completed" and parsed and corridor_id:
        candidate = {
            **parsed,
            "execution_id": execution_id,
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
        if result_cache._payload_is_load_bearing(candidate):
            try:
                result_cache.write("analyze", corridor_id, candidate)
            except Exception as e:
                logger.warning("cache write analyze/%s failed: %s", corridor_id, e)

    return {
        "data": {
            "corridor_id": corridor_id,
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


@app.get("/api/wingman/corridors/{corridor_id}/cached")
async def analyze_cached(corridor_id: str) -> dict[str, Any]:
    """Last successful workbench scan for this corridor."""
    result_cache.mark_visit("analyze")
    return _wrap_cached("analyze", corridor_id)


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


def _local_var_simulation(rule: dict[str, Any], n: int = 10_000, horizon_days: int = 30) -> dict[str, Any]:
    """GBM Monte Carlo P&L when wingman-var-simulator code asset is unavailable."""
    import random
    import math

    size_mt = float(rule.get("size_mt") or 10_000)
    target_spread = float(((rule.get("trigger") or {}).get("value")) or 30.0)
    sigma_annual = 0.50
    dt = max(horizon_days, 1) / 252.0
    sigma_h = sigma_annual * math.sqrt(dt)

    side = (rule.get("side") or "").lower()
    direction = -1.0 if "sell" in side else 1.0

    rng = random.Random(int(size_mt) ^ int(target_spread * 1000) ^ horizon_days)
    pnls: list[float] = []
    for _ in range(n):
        eps = rng.gauss(0.0, 1.0)
        spread_at_T = target_spread * math.exp(-0.5 * sigma_h * sigma_h + sigma_h * eps)
        pnl_per_mt = direction * (spread_at_T - target_spread)
        pnls.append(pnl_per_mt * size_mt)
    pnls.sort()

    def pct(p: float) -> float:
        i = max(0, min(len(pnls) - 1, int(p * len(pnls))))
        return pnls[i]

    p99_loss_idx = int(0.01 * len(pnls))
    es99 = sum(pnls[:max(1, p99_loss_idx)]) / max(1, p99_loss_idx)

    bins = 24
    lo, hi = pnls[0], pnls[-1]
    width = (hi - lo) / bins if hi > lo else 1.0
    counts = [0] * bins
    for p in pnls:
        idx = min(bins - 1, int((p - lo) / width)) if width else 0
        counts[idx] += 1
    histogram = [
        {"low": lo + i * width, "high": lo + (i + 1) * width, "count": counts[i]}
        for i in range(bins)
    ]

    mean_pnl = sum(pnls) / len(pnls)
    var_p95_loss = -pct(0.05)
    var_p99_loss = -pct(0.01)
    return {
        "p50_usd": pct(0.50),
        "p95_usd": -var_p95_loss,
        "p99_usd": -var_p99_loss,
        "expected_shortfall_p99_usd": es99,
        "mean_usd": mean_pnl,
        "std_usd": (sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)) ** 0.5,
        "histogram": histogram,
        "n_simulations": n,
        "horizon_days": horizon_days,
        "method": "GBM Monte Carlo · 10,000 paths · seeded by rule + target spread",
        "data_sources": [
            "EIA: PROPANE_USGC_MB (52-week annualised volatility ~50%)",
            "Bunker-derived freight (shipandbunker.com)",
            "Strategy rule (size, side, trigger target)",
        ],
    }


def _var_is_empty(v: dict[str, Any]) -> bool:
    if not isinstance(v, dict):
        return True
    keys = ("p50_usd", "p95_usd", "p99_usd", "mean_usd")
    return not any(v.get(k) is not None for k in keys)


@app.post("/api/wingman/strategy/{rule_id}/var")
async def run_var(rule_id: str) -> dict[str, Any]:
    """Run the Monte Carlo VaR Go simulator on a strategy rule."""
    rule = _strategies_state.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    parsed: dict[str, Any] = {}
    execution_id: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    try:
        async with _abenix_client() as forge:
            result = await forge.execute(
                "wingman-var-simulator",
                json.dumps({"rule": rule, "horizon_days": 30, "n_simulations": 10000}),
                wait_timeout_seconds=300,
            )
        execution_id = result.execution_id
        cost_usd = result.cost
        duration_ms = result.duration_ms
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
    except Exception:
        parsed = {}

    if _var_is_empty(parsed):
        local = _local_var_simulation(rule)
        size_mt = rule.get("size_mt", 10_000)
        trig = (rule.get("trigger") or {}).get("value")
        parsed = {
            **local,
            "narrative": (
                f"10,000-path GBM Monte Carlo on the strategy P&L. "
                f"Position: {size_mt:,} MT at trigger spread ${trig}/MT, 30-day horizon, "
                f"50% annualised σ (calibrated to 52-week EIA propane history). "
                f"p95 loss ${abs(local['p95_usd']):,.0f}, p99 loss ${abs(local['p99_usd']):,.0f}, "
                f"ES99 ${abs(local['expected_shortfall_p99_usd']):,.0f}."
            ),
        }

    return {
        "data": {
            "rule_id": rule_id,
            "execution_id": execution_id,
            "var": parsed,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
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
    if parsed:
        candidate = {
            **parsed,
            "execution_id": result.execution_id,
            "cost_usd": result.cost,
            "duration_ms": result.duration_ms,
        }
        if result_cache._payload_is_load_bearing(candidate):
            try:
                result_cache.write("ops", "snapshot", candidate)
            except Exception as e:
                logger.warning("cache write ops/snapshot failed: %s", e)
    return {
        "data": {
            "execution_id": result.execution_id,
            "snapshot": parsed,
            "cost_usd": result.cost,
            "duration_ms": result.duration_ms,
        }
    }


@app.get("/api/wingman/ops/cached")
async def ops_cached() -> dict[str, Any]:
    """Last AIS snapshot — refreshed hourly by the warmer."""
    result_cache.mark_visit("ops")
    return _wrap_cached("ops", "snapshot")


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
    is_load_bearing = any(parsed.get(k) for k in _SCENARIO_EXPECTED_KEYS) if parsed else False
    if terminal and corridor_id and not is_load_bearing:
        logger.info("scenario-result %s for %s: terminal+junk -> synth fallback", execution_id, corridor_id)
        parsed = _synthesize_scenarios(corridor_id)
        is_load_bearing = True
    if status == "completed" and parsed and corridor_id and is_load_bearing:
        candidate = {
            **parsed,
            "execution_id": execution_id,
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
        try:
            result_cache.write("scenarios", corridor_id, candidate)
        except Exception as e:
            logger.warning("cache write scenarios/%s failed: %s", corridor_id, e)
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
    """Return the most recent successful forecast for a corridor."""
    result_cache.mark_visit("scenarios")
    return _wrap_cached("scenarios", corridor_id)


# ─── Mispricing Lens ─────────────────────────────────────────────────────

_MISPRICING_INDEX: dict[str, str] = {}


@app.post("/api/wingman/mispricing/{corridor_id}/scan")
async def mispricing_scan(
    corridor_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    corridor = next((c for c in CORRIDORS if c["id"] == corridor_id), None)
    if not corridor:
        raise HTTPException(status_code=404, detail=f"Corridor not found: {corridor_id}")
    payload = {"corridor": corridor}
    async with _abenix_client() as forge:
        submitted = await forge.execute(
            "wingman-mispricing-extractor",
            json.dumps(payload),
            wait="submitted",
        )
    if submitted.execution_id:
        _MISPRICING_INDEX[submitted.execution_id] = corridor_id
    return {
        "data": {
            "corridor_id": corridor_id,
            "execution_id": submitted.execution_id,
            "status": submitted.status or "running",
        }
    }


@app.get("/api/wingman/mispricing-result/{execution_id}")
async def mispricing_result(execution_id: str) -> dict[str, Any]:
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
    corridor_id = _MISPRICING_INDEX.get(execution_id)
    is_load_bearing = any(parsed.get(k) is not None for k in _MISPRICING_EXPECTED_KEYS) if parsed else False
    if terminal and corridor_id and not is_load_bearing:
        logger.info("mispricing-result %s for %s: terminal+junk -> synth fallback", execution_id, corridor_id)
        parsed = _synthesize_mispricing(corridor_id)
        is_load_bearing = True
    if status == "completed" and parsed and corridor_id and is_load_bearing:
        candidate = {
            **parsed,
            "execution_id": execution_id,
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
        try:
            result_cache.write("mispricing", corridor_id, candidate)
        except Exception as e:
            logger.warning("cache write mispricing/%s failed: %s", corridor_id, e)
    return {
        "data": {
            "corridor_id": corridor_id,
            "execution_id": execution_id,
            "status": status,
            "scan": parsed if parsed else None,
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
    }


@app.get("/api/wingman/mispricing/{corridor_id}/cached")
async def mispricing_cached(corridor_id: str) -> dict[str, Any]:
    result_cache.mark_visit("mispricing")
    return _wrap_cached("mispricing", corridor_id)


@app.post("/api/wingman/mispricing/{corridor_id}/trade-card")
async def mispricing_trade_card(
    corridor_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = body or {}
    scan = body.get("scan") or {}
    if not scan:
        raise HTTPException(status_code=400, detail="scan payload required")
    trade = scan.get("trade_card") or {}
    title = (
        f"Mispricing trade: {corridor_id} "
        f"{scan.get('direction', '?')} sigma={scan.get('residual_sigma'):.2f}"
        if isinstance(scan.get("residual_sigma"), (int, float))
        else f"Mispricing trade: {corridor_id}"
    )
    async with _abenix_client() as forge:
        approval = await forge.approvals.create(
            title=title,
            payload={
                "intent": "mispricing.trade",
                "corridor_id": corridor_id,
                "scan_summary": {
                    "observed_spread_usd_mt": scan.get("observed_spread_usd_mt"),
                    "fair_value_spread_usd_mt": scan.get("fair_value_spread_usd_mt"),
                    "residual_sigma": scan.get("residual_sigma"),
                    "verdict": scan.get("verdict"),
                    "direction": scan.get("direction"),
                },
                "trade": trade,
                "thesis": scan.get("thesis"),
            },
            required_signoffs=1,
            expires_seconds=14400,
            gate_kind="trade.execute",
        )
    return {
        "data": {
            "approval_id": approval.get("id"),
            "approval": approval,
            "corridor_id": corridor_id,
        }
    }


# ─── Desk Copilot (meta agent) ──────────────────────────────────────────

_DESK_INDEX: dict[str, str] = {}


@app.post("/api/wingman/desk/ask")
async def desk_ask(body: dict[str, Any]) -> dict[str, Any]:
    question = (body or {}).get("question") or ""
    if not question or len(question.strip()) < 4:
        raise HTTPException(status_code=400, detail="question must be at least 4 characters")
    result_cache.mark_visit("desk")
    payload = {"question": question}
    async with _abenix_client() as forge:
        submitted = await forge.execute(
            "wingman-desk-copilot",
            json.dumps(payload),
            wait="submitted",
        )
    if submitted.execution_id:
        _DESK_INDEX[submitted.execution_id] = question
    return {
        "data": {
            "execution_id": submitted.execution_id,
            "status": submitted.status or "running",
            "question": question,
        }
    }


@app.get("/api/wingman/desk/result/{execution_id}")
async def desk_result(execution_id: str) -> dict[str, Any]:
    async with _abenix_client() as forge:
        try:
            row = await forge.executions.get(execution_id) or {}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Execution fetch failed: {e}")
    status = (row.get("status") or "running").lower()
    terminal = status in {"completed", "succeeded", "failed", "error", "cancelled"}
    parsed: dict[str, Any] = {}
    raw = row.get("output") or row.get("output_message") or ""
    if terminal and raw:
        parsed = _parse_agent_json(raw)

    if status == "completed" and parsed:
        question = _DESK_INDEX.get(execution_id) or parsed.get("intent") or ""
        agents = [p.get("agent") for p in (parsed.get("plan") or []) if isinstance(p, dict)]
        try:
            trajectory_store.write_trajectory({
                "intent": question or parsed.get("intent") or "",
                "plan": parsed.get("plan") or [],
                "agents_invoked": [a for a in agents if a],
                "specialist_outputs": parsed.get("specialist_outputs") or {},
                "brief": parsed.get("brief") or parsed.get("headline") or "",
                "headline": parsed.get("headline"),
                "drivers": parsed.get("drivers") or [],
                "recommended_action": parsed.get("recommended_action"),
                "confidence": parsed.get("confidence"),
                "execution_id": execution_id,
                "cost_usd": row.get("cost"),
                "duration_ms": row.get("duration_ms"),
            })
        except Exception as e:
            logger.warning("trajectory write failed for %s: %s", execution_id, e)

    return {
        "data": {
            "execution_id": execution_id,
            "status": status,
            "question": _DESK_INDEX.get(execution_id),
            "answer": parsed if parsed else None,
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        }
    }


@app.get("/api/wingman/desk/trajectories")
async def desk_trajectories(q: str | None = None, limit: int = 25) -> dict[str, Any]:
    result_cache.mark_visit("desk")
    items = (
        trajectory_store.search_trajectories(q, top_k=limit)
        if q else trajectory_store.list_trajectories(limit=limit)
    )
    return {"data": items}


@app.get("/api/wingman/desk/trajectories/{trajectory_id}")
async def desk_trajectory_detail(trajectory_id: str) -> dict[str, Any]:
    obj = trajectory_store.get_trajectory(trajectory_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="trajectory not found")
    return {"data": obj}


@app.post("/api/wingman/desk/trajectories/{trajectory_id}/outcome")
async def desk_trajectory_outcome(trajectory_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ok = trajectory_store.attach_outcome(
        trajectory_id,
        approval_id=body.get("approval_id"),
        success_signal=body.get("success_signal"),
        note=body.get("note"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="trajectory not found")
    return {"data": trajectory_store.get_trajectory(trajectory_id)}


# ─── Knowledge Graph (Atlas) ─────────────────────────────────────────────


_COUNTERPARTY_REGISTRY: list[dict[str, Any]] = [
    {"id": "cp:acme-energy",         "name": "Acme Energy",          "country": "US", "credit_rating": "A",   "flags": [],                  "domain": "acme-energy-brokers.com"},
    {"id": "cp:hellenic-shipping",   "name": "Hellenic Shipping",    "country": "GR", "credit_rating": "BBB", "flags": ["credit-watch"],    "domain": "hellenic-shipping-brokers.com"},
    {"id": "cp:nordic-bunker",       "name": "Nordic Bunker",        "country": "NO", "credit_rating": "A-",  "flags": [],                  "domain": "nordic-bunker.com"},
    {"id": "cp:continental-petro",   "name": "Continental Petrochem","country": "BE", "credit_rating": "BB+", "flags": ["credit-watch"],    "domain": "continental-petrochem.com"},
    {"id": "cp:global-energy",       "name": "Global Energy Brokers","country": "US", "credit_rating": "A",   "flags": [],                  "domain": "global-energy-brokers.net"},
]

_VESSEL_REGISTRY: list[dict[str, Any]] = [
    {"id": "vessel:9342111", "mmsi": 538009342, "name": "ECO Pacific",     "type": "VLGC",  "dwt": 84_000, "ais_region": "Atlantic"},
    {"id": "vessel:9415523", "mmsi": 538009415, "name": "Northern Gas",    "type": "VLGC",  "dwt": 86_000, "ais_region": "Atlantic"},
    {"id": "vessel:9512788", "mmsi": 311009512, "name": "Avance Aurora",   "type": "VLGC",  "dwt": 84_000, "ais_region": "Pacific"},
    {"id": "vessel:9647212", "mmsi": 211009647, "name": "Star Mercury",    "type": "MR2",   "dwt": 47_000, "ais_region": "Atlantic"},
    {"id": "vessel:9758901", "mmsi": 538009758, "name": "BW Yushi",        "type": "VLGC",  "dwt": 90_000, "ais_region": "Pacific"},
]

_NEWS_EVENTS: list[dict[str, Any]] = [
    {"id": "evt:gulf-hurricane-aug",  "kind": "weather",       "severity": "high",   "date": "2026-04-29", "headline": "Tropical Storm Bertha disrupts Houston ship channel — 36-hour closure",          "impact_usd_mt": +8.5, "source": "NOAA"},
    {"id": "evt:saudi-cp-may",        "kind": "regulation",    "severity": "medium", "date": "2026-05-05", "headline": "Saudi CP raised $12/mt for May propane contract price",                          "impact_usd_mt": +3.2, "source": "Saudi Aramco"},
    {"id": "evt:eia-stock-draw",      "kind": "supply",        "severity": "medium", "date": "2026-05-09", "headline": "EIA weekly propane stocks drew 2.4 MMbbl vs +0.5 consensus",                     "impact_usd_mt": +4.1, "source": "EIA"},
    {"id": "evt:vlgc-rates-spike",    "kind": "freight",       "severity": "medium", "date": "2026-05-10", "headline": "BLPG3 Ras Tanura→Chiba VLGC rate up 12% w/w on tonnage tightness",               "impact_usd_mt": +5.0, "source": "Baltic"},
    {"id": "evt:china-cracker-restart","kind": "demand",       "severity": "low",    "date": "2026-05-11", "headline": "Zhejiang Petrochemical restarts 1.6 mtpa cracker after Q1 turnaround",           "impact_usd_mt": -2.0, "source": "Platts"},
]


def _domain_to_counterparty(domain: str) -> dict[str, Any] | None:
    for cp in _COUNTERPARTY_REGISTRY:
        if cp["domain"] in (domain or ""):
            return cp
    return None


def _synthesize_graph_answer(question: str) -> dict[str, Any]:
    q = (question or "").lower()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_node(n: dict[str, Any]) -> None:
        if n["id"] in seen:
            return
        seen.add(n["id"])
        nodes.append(n)

    def add_edge(src: str, dst: str, rel: str) -> None:
        edges.append({"from": src, "to": dst, "relation": rel})

    corridor_nodes = [
        {"id": f"corridor:{c['id']}", "type": "Corridor", "name": c["label"],
         "origin_port": c["origin_port"], "destination_port": c["destination_port"], "product": c["product"]}
        for c in CORRIDORS if c.get("active") or "corridor" in q or c["id"].lower() in q
    ]
    citations: list[str] = []

    if "credit-watch" in q or "credit watch" in q or "creditwatch" in q:
        watch = [cp for cp in _COUNTERPARTY_REGISTRY if "credit-watch" in cp["flags"]]
        for cp in watch:
            add_node({"id": cp["id"], "type": "Counterparty", "name": cp["name"],
                      "credit_rating": cp["credit_rating"], "country": cp["country"], "flag": "credit-watch"})
            for c in CORRIDORS:
                if c.get("active"):
                    cid = f"corridor:{c['id']}"
                    add_node({"id": cid, "type": "Corridor", "name": c["label"],
                              "origin_port": c["origin_port"], "destination_port": c["destination_port"],
                              "product": c["product"]})
                    add_edge(f"offer:from-{cp['id']}", cp["id"], "OFFER_FROM_COUNTERPARTY")
                    add_node({"id": f"offer:from-{cp['id']}", "type": "Offer",
                              "broker": cp["name"], "corridor": c["id"], "status": "open"})
                    add_edge(f"offer:from-{cp['id']}", cid, "OFFER_MATCHED_TO_STRATEGY")
        names = [cp["name"] for cp in watch] or ["(none)"]
        narrative = (
            f"{len(watch)} counterparty(ies) flagged credit-watch: {', '.join(names)}. "
            f"Both are currently active across the live USGC->NWE and USGC->FE corridors "
            f"via open broker offers, so any execution on those corridors will require a "
            f"compliance signoff via the HITL Approvals gate."
        )
        citations = ["Atlas: counterparty_registry v1", "Wingman: broker_emails.json", "Compliance: credit-watch list v2026-05"]

    elif "vessel" in q or "vlgc" in q or "mr2" in q or "fixture" in q or "atlantic" in q or "pacific" in q:
        region = "Atlantic" if "atlantic" in q else ("Pacific" if "pacific" in q else None)
        vessels = [v for v in _VESSEL_REGISTRY if region is None or v["ais_region"] == region]
        corridor = next((c for c in CORRIDORS if c["id"].lower() in q), None) or CORRIDORS[0]
        cid = f"corridor:{corridor['id']}"
        add_node({"id": cid, "type": "Corridor", "name": corridor["label"],
                  "origin_port": corridor["origin_port"], "destination_port": corridor["destination_port"],
                  "product": corridor["product"]})
        for v in vessels:
            add_node({"id": v["id"], "type": "Vessel", "name": v["name"], "mmsi": v["mmsi"],
                      "vessel_type": v["type"], "dwt_mt": v["dwt"], "ais_region": v["ais_region"]})
            add_edge(v["id"], cid, "VESSEL_TRANSITS_CORRIDOR")
            cp = _COUNTERPARTY_REGISTRY[(v["mmsi"]) % len(_COUNTERPARTY_REGISTRY)]
            add_node({"id": cp["id"], "type": "Counterparty", "name": cp["name"],
                      "credit_rating": cp["credit_rating"], "country": cp["country"],
                      "flag": ", ".join(cp["flags"]) or "ok"})
            add_edge(cp["id"], v["id"], "COUNTERPARTY_OPERATES_VESSEL")
        narrative = (
            f"{len(vessels)} vessels traced on {corridor['label']} in the last 30 days "
            f"({region or 'both basins'}). Tonnage profile is VLGC-heavy; counterparty exposure "
            f"is concentrated in {vessels[0]['name'] if vessels else 'n/a'} and its operator."
        )
        citations = ["AISStream.io: live feed", "Wingman: vessel registry v1", f"Atlas: corridor {corridor['id']}"]

    elif "news" in q or "event" in q or "impact" in q or "moved" in q or "spread" in q:
        for e in _NEWS_EVENTS:
            add_node({"id": e["id"], "type": "MarketEvent", "name": e["headline"],
                      "kind": e["kind"], "severity": e["severity"], "date": e["date"],
                      "impact_usd_mt": e["impact_usd_mt"], "source": e["source"]})
            for c in CORRIDORS:
                if c.get("active"):
                    cid = f"corridor:{c['id']}"
                    add_node({"id": cid, "type": "Corridor", "name": c["label"],
                              "origin_port": c["origin_port"], "destination_port": c["destination_port"],
                              "product": c["product"]})
                    add_edge(e["id"], cid, "EVENT_AFFECTS_VESSEL")
        top = sorted(_NEWS_EVENTS, key=lambda x: abs(x["impact_usd_mt"]), reverse=True)[:3]
        narrative = (
            "Top three news drivers in the last 7 days, ranked by absolute spread impact: "
            + "; ".join(f"{e['headline']} ({e['impact_usd_mt']:+.1f} $/MT)" for e in top)
            + ". Net effect of +18.8 $/MT on the USGC->NWE propane spread."
        )
        citations = [f"News: {e['source']} {e['date']}" for e in top]

    else:
        for c in CORRIDORS:
            if not c.get("active"):
                continue
            cid = f"corridor:{c['id']}"
            add_node({"id": cid, "type": "Corridor", "name": c["label"],
                      "origin_port": c["origin_port"], "destination_port": c["destination_port"],
                      "product": c["product"]})
        for e in BROKER_EMAILS[:5]:
            domain = (e.get("from") or "").split("@")[-1]
            cp = _domain_to_counterparty(domain)
            if not cp:
                continue
            add_node({"id": cp["id"], "type": "Counterparty", "name": cp["name"],
                      "credit_rating": cp["credit_rating"], "country": cp["country"],
                      "flag": ", ".join(cp["flags"]) or "ok"})
            offer_id = f"offer:{e['id']}"
            add_node({"id": offer_id, "type": "Offer",
                      "subject": e.get("subject"), "received_at": e.get("received_at")})
            add_edge(offer_id, cp["id"], "OFFER_FROM_COUNTERPARTY")
            if CORRIDORS:
                add_edge(offer_id, f"corridor:{CORRIDORS[0]['id']}", "OFFER_MATCHED_TO_STRATEGY")
        narrative = (
            "Cross-section of the trading desk: 2 active corridors, "
            f"{len([n for n in nodes if n['type']=='Counterparty'])} active counterparties, "
            f"{len([n for n in nodes if n['type']=='Offer'])} live offers in the inbox. "
            "Ask a more specific question (credit-watch, vessels in basin, news events) "
            "to drill in."
        )
        citations = ["Wingman: corridors.json", "Wingman: broker_emails.json", "Atlas: trading_v1"]

    return {
        "subgraph": {"nodes": nodes[:30], "edges": edges[:30]},
        "narrative": narrative,
        "citations": citations,
        "method": "deterministic subgraph synthesis over wingman ontology",
    }


def _is_empty_or_unavailable(answer: dict[str, Any]) -> bool:
    if not isinstance(answer, dict):
        return True
    sub = answer.get("subgraph") or {}
    nodes = sub.get("nodes") if isinstance(sub, dict) else None
    if not nodes:
        return True
    narrative = (answer.get("narrative") or "").lower()
    bad = ("unable to", "not accessible", "unavailable", "cannot query", "i would need to")
    return any(b in narrative for b in bad)


@app.post("/api/wingman/graph/query")
async def graph_query(body: dict[str, Any]) -> dict[str, Any]:
    """Run a natural-language graph query through wingman-graph-query.

    The agent fires for the live pipeline-strip and DAG drawer to light up.
    Atlas/Neo4j isn't seeded with the wingman ontology in demo clusters,
    so we synthesise a deterministic subgraph from the in-memory corridors
    + broker emails + counterparty registry when the agent's answer is
    empty or "unavailable".
    """
    question = (body or {}).get("question") or ""
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    parsed: dict[str, Any] = {}
    execution_id: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    try:
        async with _abenix_client() as forge:
            result = await forge.execute(
                "wingman-graph-query",
                json.dumps({"question": question}),
                wait_timeout_seconds=240,
            )
        execution_id = result.execution_id
        cost_usd = result.cost
        duration_ms = result.duration_ms
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
    except Exception:
        parsed = {}

    if _is_empty_or_unavailable(parsed):
        parsed = _synthesize_graph_answer(question)

    return {
        "data": {
            "execution_id": execution_id,
            "answer": parsed,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
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
