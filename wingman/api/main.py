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
import narration as narration_store  # type: ignore  # noqa: E402

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
    # Strip stray CR/LF — a secret-mounted file with a trailing newline turns
    # X-API-Key into an illegal httpx header value and every forge.* call dies
    # with "Illegal header value", taking market-brief/approvals/tools/ops down.
    api_key = os.environ.get("WINGMAN_ABENIX_API_KEY", "").strip().rstrip(chr(13) + chr(10))
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


async def _startup_warm_all() -> None:
    """Aggressive startup warmer — explicitly walks every active corridor
    and fires scan + forecast, plus one market-brief snapshot. Runs once
    on lifespan startup so /signals, /mispricing/cached, /scenarios/cached
    and /market-brief return real data on the first browser hit instead
    of {"data": null}. Each corridor/page warm is best-effort and isolated
    so one failure doesn't poison the rest."""
    active = [c["id"] for c in CORRIDORS if c.get("active")]
    logger.info("startup warm: %d active corridors, market-brief", len(active))

    # /scan (mispricing) — one per active corridor.
    for cid in active:
        try:
            payload = await _warm_mispricing(cid)
            if payload:
                result_cache.write("mispricing", cid, payload)
                logger.info("startup warm: mispricing/%s populated", cid)
            else:
                logger.info("startup warm: mispricing/%s empty (agent unavailable)", cid)
        except Exception as e:
            logger.warning("startup warm mispricing/%s failed: %s", cid, e)

    # /forecast (scenarios) — one per active corridor.
    for cid in active:
        try:
            payload = await _warm_scenarios(cid)
            if payload:
                result_cache.write("scenarios", cid, payload)
                logger.info("startup warm: scenarios/%s populated", cid)
            else:
                logger.info("startup warm: scenarios/%s empty (agent unavailable)", cid)
        except Exception as e:
            logger.warning("startup warm scenarios/%s failed: %s", cid, e)

    # /market-brief — one snapshot.
    try:
        brief = await _warm_market_brief()
        if brief:
            result_cache.write("market-brief", "snapshot", brief)
            logger.info("startup warm: market-brief/snapshot populated")
        else:
            logger.info("startup warm: market-brief/snapshot empty (agent unavailable)")
    except Exception as e:
        logger.warning("startup warm market-brief failed: %s", e)

    logger.info("startup warm: done")


async def _periodic_warm() -> None:
    for page, keys, run in _warmer_pairs():
        await result_cache.warm(page, keys, run, require_recent_visit=True)


async def _warmer_loop() -> None:
    try:
        # Short delay so the SDK/HTTP stack is up before we hammer agents.
        await asyncio.sleep(15)
        # Aggressive corridor walk that populates Home's TodaysSignals on
        # first load even when the file cache is empty (fresh deploy / PVC
        # wiped). Runs in addition to the page-keyed _initial_warm above.
        await _startup_warm_all()
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
    payload = _convert_units_deep(entry["payload"])
    return {
        "data": {
            "key": key,
            "payload": payload,
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


_MISPRICING_EXPECTED_KEYS = ("verdict", "observed_spread_usd_mt", "fair_value_spread_usd_mt", "residual_sigma")
_SCENARIO_EXPECTED_KEYS = ("scenarios", "expected_curve", "base_curve")

# Realistic propane corridor spreads sit in +/-200 USD/MT. 2000 is a generous
# outlier ceiling — anything beyond that is an agent hallucination and must
# never be cached. Memory rule: no synth in wingman-api; show "data unavailable"
# instead of a fabricated value.
_FAIR_VALUE_SPREAD_OUTLIER_USD_MT = 2000.0

try:
    from prometheus_client import Counter as _PromCounter  # type: ignore
    wingman_signal_rejected_total = _PromCounter(
        "wingman_signal_rejected_total",
        "Mispricing scans rejected before cache write because they failed sanity checks.",
        ["reason"],
    )
except Exception:  # prometheus_client not installed — degrade silently
    class _NoopCounter:
        def labels(self, **_kwargs):
            return self
        def inc(self, _n: float = 1) -> None:
            return None
    wingman_signal_rejected_total = _NoopCounter()  # type: ignore[assignment]


def _mispricing_passes_sanity(scan: dict[str, Any]) -> bool:
    """Reject agent output that can't be a real market state before we cache it.
    - |fair_value_spread_usd_mt| must be <= 2000 (realistic propane spread ceiling).
    - p10 and p90 must both be non-null AND p90 > p10 (a real band, not a point).
    - residual_sigma must be non-null.
    On failure we bump a labeled metric and the caller treats the scan as agent-unavailable."""
    if not isinstance(scan, dict):
        wingman_signal_rejected_total.labels(reason="fair_value_outlier").inc()
        return False
    try:
        fv = float(scan.get("fair_value_spread_usd_mt"))
    except (TypeError, ValueError):
        wingman_signal_rejected_total.labels(reason="fair_value_outlier").inc()
        return False
    if abs(fv) > _FAIR_VALUE_SPREAD_OUTLIER_USD_MT:
        logger.warning(
            "mispricing sanity reject: fair_value_spread_usd_mt=%.2f exceeds +/-%.0f outlier ceiling",
            fv, _FAIR_VALUE_SPREAD_OUTLIER_USD_MT,
        )
        wingman_signal_rejected_total.labels(reason="fair_value_outlier").inc()
        return False
    p10 = scan.get("fair_value_p10_usd_mt")
    p90 = scan.get("fair_value_p90_usd_mt")
    if p10 is None or p90 is None:
        wingman_signal_rejected_total.labels(reason="band_collapsed").inc()
        return False
    try:
        if float(p90) <= float(p10):
            wingman_signal_rejected_total.labels(reason="band_collapsed").inc()
            return False
    except (TypeError, ValueError):
        wingman_signal_rejected_total.labels(reason="band_collapsed").inc()
        return False
    if scan.get("residual_sigma") is None:
        wingman_signal_rejected_total.labels(reason="sigma_missing").inc()
        return False
    return True


def _scan_has_required_numbers(scan: dict[str, Any]) -> bool:
    """A scan is load-bearing when observed and fair-value are both
    numeric floats — the sign doesn't matter (a closed arb is a real
    market state) but None / NaN / non-numeric means the agent didn't
    actually compute them from tool outputs."""
    if not isinstance(scan, dict):
        return False
    obs = scan.get("observed_spread_usd_mt")
    fv = scan.get("fair_value_spread_usd_mt")
    if obs is None or fv is None:
        return False
    try:
        obs_f = float(obs)
        fv_f = float(fv)
    except (TypeError, ValueError):
        return False
    import math
    return math.isfinite(obs_f) and math.isfinite(fv_f)


async def _warm_mispricing(corridor_id: str) -> dict[str, Any]:
    """Fire the Abenix mispricing extractor agent and return whatever it
    produces. The agent itself sources every number from real-service
    tools (eia_open_data, yahoo_finance, freight_baltic_blpg, options_data,
    vessel_specs, tavily_search) plus the two deployed ML models — there
    is no synthesis, no anchoring, and no manual cache write on this path.
    If the agent fails or returns numbers that aren't load-bearing,
    return an empty envelope; the UI then renders the "data unavailable"
    state instead of a fake snapshot."""
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
    if parsed and _scan_has_required_numbers(parsed) and _mispricing_passes_sanity(parsed):
        return parsed
    logger.info("mispricing agent unavailable for %s — UI will show data-unavailable state", corridor_id)
    return {}


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
        logger.info("scenarios agent unavailable for %s — UI will show data-unavailable state", corridor_id)
        return {}
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
@app.get("/api/health")
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


# Today's signals — one call returns every active corridor's latest
# cached Price-at-Risk scan summary. Pure cache reads (no agent fires)
# so the home page paints fast. The mispricing cache already has its own
# TTL; this endpoint just rolls them up.
@app.get("/api/wingman/signals")
async def todays_signals() -> dict[str, Any]:
    active = [c for c in CORRIDORS if c.get("active")]
    rows: list[dict[str, Any]] = []
    for c in active:
        entry = result_cache.read("mispricing", c["id"])
        scan = (entry or {}).get("payload") or {}
        # Evict degraded/unavailable rows — agent flagged the scan as not
        # trustworthy, so don't keep serving 27-min-old garbage for the rest
        # of the TTL. Next read returns the data-unavailable state.
        dq = (scan.get("data_quality") or "").lower()
        if dq in ("degraded", "unavailable"):
            result_cache.evict("mispricing", c["id"])
            entry = None
            scan = {}
        rows.append({
            "id": c["id"],
            "label": c["label"],
            "product": c.get("product"),
            "origin_port": c.get("origin_port"),
            "destination_port": c.get("destination_port"),
            "verdict": scan.get("verdict"),
            "direction": scan.get("direction"),
            "observed_spread_usd_mt": scan.get("observed_spread_usd_mt"),
            "fair_value_spread_usd_mt": scan.get("fair_value_spread_usd_mt"),
            "fair_value_p10_usd_mt": scan.get("fair_value_p10_usd_mt"),
            "fair_value_p90_usd_mt": scan.get("fair_value_p90_usd_mt"),
            "residual_usd_mt": scan.get("residual_usd_mt"),
            "residual_sigma": scan.get("residual_sigma"),
            "market_regime": scan.get("market_regime"),
            "anomaly_flag": scan.get("anomaly_flag"),
            "cached_at": (entry or {}).get("written_at"),
            "age_seconds": (entry or {}).get("age_seconds"),
            "fresh": (entry or {}).get("fresh"),
            "data_quality": scan.get("data_quality") if scan else "unavailable",
        })
    return {"data": {"signals": rows, "as_of": time.time()}}


# Convert every price-like indicator to $/MT using industry-standard
# densities/conversions so the whole UI shows one unit. Propane uses the
# API/EIA density of 0.508 kg/L (1 gal = 1.923 kg → 524.95 gal/MT).
# Crude (WTI/Brent) uses API gravity ~35° avg (1 MT ≈ 7.45 bbl). HH gas
# and FX rates have no MT equivalent so they're left untouched.
_PROPANE_GAL_PER_MT = 524.95
_CRUDE_BBL_PER_MT = 7.45

# Regex post-processor: agent LLM narratives sometimes quote prices in
# native $/gal or $/bbl ("Mont Belvieu propane $0.864/gal", "WTI
# $105.78/bbl"). Convert in-place so trader sees consistent $/MT.
# Heuristic: $X/gal is propane unless the surrounding 30 chars say
# "RBOB" or "ULSD"/"gasoline"/"diesel" (refined products use 333/308
# gal/MT). $X/bbl is always crude.
import re as _re
_GAL_PAT = _re.compile(r"\$([0-9]+(?:\.[0-9]+)?)\s*/\s*gal\b")
_BBL_PAT = _re.compile(r"\$([0-9]+(?:\.[0-9]+)?)\s*/\s*bbl\b")

def _convert_text_units(s: str) -> str:
    """Convert only $X/gal mentions of LPG to $/MT. Crude/refined $/bbl is
    industry-standard and stays. RBOB/ULSD $/gal is also industry-standard
    in the US and stays. Only propane-context $/gal flips."""
    if not s or not isinstance(s, str):
        return s
    def _gal_sub(m: _re.Match) -> str:
        val = float(m.group(1))
        ctx = s[max(0, m.start() - 50): m.start() + 40].lower()
        is_lpg = any(k in ctx for k in (
            "propane", "butane", "lpg", "ethane", "ngl",
            "mont belvieu", "belvieu", "blpg",
        ))
        is_refined_or_crude = any(k in ctx for k in (
            "rbob", "gasoline", "ulsd", "diesel", "heating oil", "jet",
        ))
        if is_lpg and not is_refined_or_crude:
            return f"${round(val * _PROPANE_GAL_PER_MT, 1)}/MT"
        return m.group(0)
    return _GAL_PAT.sub(_gal_sub, s)

def _convert_units_deep(obj: Any) -> Any:
    """Walk an agent-output dict and convert $/gal/$/bbl in every string."""
    if isinstance(obj, str):
        return _convert_text_units(obj)
    if isinstance(obj, list):
        return [_convert_units_deep(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _convert_units_deep(v) for k, v in obj.items()}
    return obj

def _normalize_to_usd_per_mt(indicators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Industry-standard unit rule:
    - LPG / propane / butane / ethane → $/MT (cargo trader unit)
    - Crude (WTI/Brent/Dubai/OPEC)    → $/bbl (universal benchmark — KEEP)
    - Refined products (RBOB/ULSD)    → $/bbl (Argus/Platts standard — KEEP)
    - Henry Hub natgas                → $/MMBtu (US convention — KEEP)
    - EU TTF                          → €/MWh (EU convention — KEEP)
    Only $/gal-quoted LPG gets converted; crude/refined $/bbl stays as-is.
    """
    out: list[dict[str, Any]] = []
    for raw in (indicators or []):
        ind = dict(raw)
        unit = (ind.get("unit") or "").strip()
        label = (ind.get("label") or "").lower()
        latest = ind.get("latest")
        if latest is None or unit not in ("$/gal",):
            out.append(ind)
            continue
        is_lpg = any(k in label for k in ("propane", "butane", "lpg", "ethane", "ngl"))
        if not is_lpg:
            out.append(ind)
            continue
        try:
            ind["latest"] = round(float(latest) * _PROPANE_GAL_PER_MT, 2)
            ind["source_unit"] = unit
            ind["source_value"] = latest
            ind["unit"] = "$/MT"
            hist = ind.get("history")
            if isinstance(hist, list):
                ind["history"] = [
                    {**h, "value": round(float(h["value"]) * _PROPANE_GAL_PER_MT, 2)}
                    for h in hist
                    if isinstance(h, dict) and h.get("value") is not None
                ]
        except (TypeError, ValueError):
            pass
        out.append(ind)
    return out


@app.get("/api/wingman/market-brief")
async def market_brief() -> dict[str, Any]:
    result_cache.mark_visit("market-brief")
    entry = result_cache.read("market-brief", "snapshot")
    if entry and entry["fresh"] and (entry["payload"].get("indicators") or []):
        payload = dict(entry["payload"])
        payload["indicators"] = _normalize_to_usd_per_mt(payload.get("indicators") or [])
        return {"data": payload}

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
                fb = dict(entry["payload"])
                fb["indicators"] = _normalize_to_usd_per_mt(fb.get("indicators") or [])
                return {"data": fb}
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
        payload["indicators"] = _normalize_to_usd_per_mt(payload["indicators"])
        try:
            result_cache.write("market-brief", "snapshot", payload)
        except Exception as e:
            logger.warning("cache write market-brief failed: %s", e)
    elif entry:
        fb = dict(entry["payload"])
        fb["indicators"] = _normalize_to_usd_per_mt(fb.get("indicators") or [])
        return {"data": fb}
    return {"data": payload}


@app.get("/api/wingman/market-brief/cached")
async def market_brief_cached() -> dict[str, Any]:
    """Last successful market brief — refreshed by the warmer every 5 min."""
    result_cache.mark_visit("market-brief")
    wrapped = _wrap_cached("market-brief", "snapshot")
    inner = (wrapped.get("data") or {}).get("payload") or {}
    if isinstance(inner.get("indicators"), list):
        inner["indicators"] = _normalize_to_usd_per_mt(inner["indicators"])
    return wrapped


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
        "data": _convert_units_deep({
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
        })
    }


@app.get("/api/wingman/corridors/{corridor_id}/cached")
async def analyze_cached(corridor_id: str) -> dict[str, Any]:
    """Last successful workbench scan for this corridor."""
    result_cache.mark_visit("analyze")
    return _wrap_cached("analyze", corridor_id)


# ─── Broker Inbox ────────────────────────────────────────────────────────


# How long ago each broker email should appear to have landed, in minutes.
# Stamped at request time so the inbox always reads as freshly arrived and
# never rots against the seeded 2026-05-07 strings in broker_emails.json.
_INBOX_AGE_OFFSETS_MIN = [3, 15, 30, 90, 120]


@app.get("/api/wingman/inbox")
async def list_broker_emails() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    emails: list[dict[str, Any]] = []
    for idx, email in enumerate(BROKER_EMAILS):
        offset = _INBOX_AGE_OFFSETS_MIN[idx] if idx < len(_INBOX_AGE_OFFSETS_MIN) else _INBOX_AGE_OFFSETS_MIN[-1]
        stamped = dict(email)
        stamped["received_at"] = (now - timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
        emails.append(stamped)
    return {"data": emails}


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


# Custom-email endpoints: trader pastes their own email body, we run the
# same classifier / parser agents without an entry in BROKER_EMAILS. The
# request-supplied body is the only mutable thing.
@app.post("/api/wingman/inbox/custom/classify")
async def classify_custom_email(body: dict[str, Any]) -> dict[str, Any]:
    text = (body or {}).get("body") or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="body is required")
    async with _abenix_client() as forge:
        submitted = await forge.execute(
            "wingman-broker-classifier",
            json.dumps({"body": text}),
            wait="submitted",
        )
    if submitted.execution_id:
        _CLASSIFY_INDEX[submitted.execution_id] = "custom"
    return {"data": {"email_id": "custom", "execution_id": submitted.execution_id, "status": submitted.status or "running"}}


@app.post("/api/wingman/inbox/custom/parse")
async def parse_custom_email(body: dict[str, Any]) -> dict[str, Any]:
    text = (body or {}).get("body") or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="body is required")
    async with _abenix_client() as forge:
        submitted = await forge.execute(
            "wingman-broker-parser",
            json.dumps({"body": text}),
            wait="submitted",
        )
    if submitted.execution_id:
        _PARSE_INDEX[submitted.execution_id] = "custom"
    return {"data": {"email_id": "custom", "execution_id": submitted.execution_id, "status": submitted.status or "running"}}


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
    """Run the Monte Carlo VaR simulator agent on a strategy rule."""
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

    return {
        "data": {
            "rule_id": rule_id,
            "execution_id": execution_id,
            "var": parsed or None,
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
    try:
        async with _abenix_client() as forge:
            result = await forge.execute(
                "wingman-ops-monitor",
                json.dumps({"corridors": [c["id"] for c in CORRIDORS if c.get("active")]}),
                wait_timeout_seconds=300,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ops-snapshot agent failed")
        raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
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
        logger.info("scenario-result %s for %s: agent unavailable — no cache write", execution_id, corridor_id)
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
        "data": _convert_units_deep({
            "corridor_id": corridor_id,
            "execution_id": execution_id,
            "status": status,
            "forecast": parsed if parsed else None,
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        })
    }


@app.get("/api/wingman/scenarios/{corridor_id}/cached")
async def scenarios_cached(corridor_id: str) -> dict[str, Any]:
    """Return the most recent successful forecast for a corridor."""
    result_cache.mark_visit("scenarios")
    return _wrap_cached("scenarios", corridor_id)


# ─── Price at Risk Lens ─────────────────────────────────────────────────

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
    is_load_bearing = (
        any(parsed.get(k) is not None for k in _MISPRICING_EXPECTED_KEYS)
        and _scan_has_required_numbers(parsed)
        and _mispricing_passes_sanity(parsed)
    ) if parsed else False
    if terminal and corridor_id and not is_load_bearing:
        logger.info("mispricing-result %s for %s: agent unavailable — no cache write", execution_id, corridor_id)
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
        "data": _convert_units_deep({
            "corridor_id": corridor_id,
            "execution_id": execution_id,
            "status": status,
            "scan": parsed if parsed else None,
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        })
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


# ─── Wingman Copilot (meta agent) ──────────────────────────────────────────

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


_BRIEF_REPAIR_CACHE: dict[str, dict[str, Any]] = {}


async def _repair_brief_via_agent(execution_id: str, raw: str, question: str) -> dict[str, Any]:
    if not raw:
        return {}
    if execution_id in _BRIEF_REPAIR_CACHE:
        return _BRIEF_REPAIR_CACHE[execution_id]
    payload = {"raw": raw[:8000], "question": question or ""}
    try:
        async with _abenix_client() as forge:
            result = await forge.execute(
                "wingman-brief-repair",
                json.dumps(payload),
                wait_timeout_seconds=45,
            )
        repaired = _parse_agent_json(result.output or "") or {}
        if repaired:
            repaired["_repaired"] = True
            _BRIEF_REPAIR_CACHE[execution_id] = repaired
            logger.info("brief-repair %s: salvaged %d-char output", execution_id, len(raw))
            return repaired
    except Exception as e:
        logger.warning("brief-repair %s failed: %s", execution_id, e)
    floor = {
        "intent": question or "",
        "headline": "Brief could not be parsed for this run.",
        "brief": (raw or "")[:1200],
        "recommended_action": "watch",
        "confidence": "low",
        "_repaired": False,
        "_unparsed": True,
    }
    _BRIEF_REPAIR_CACHE[execution_id] = floor
    return floor


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
        if status == "completed" and not parsed:
            question = _DESK_INDEX.get(execution_id) or ""
            parsed = await _repair_brief_via_agent(execution_id, raw, question)

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
                "has_narration": narration_store.has(execution_id),
            })
        except Exception as e:
            logger.warning("trajectory write failed for %s: %s", execution_id, e)

    return {
        "data": _convert_units_deep({
            "execution_id": execution_id,
            "status": status,
            "question": _DESK_INDEX.get(execution_id),
            "answer": parsed if parsed else None,
            "error_message": row.get("error_message"),
            "failure_code": row.get("failure_code"),
            "cost_usd": row.get("cost"),
            "duration_ms": row.get("duration_ms"),
        })
    }


@app.get("/api/wingman/desk/narration/{execution_id}")
async def desk_narration(execution_id: str) -> StreamingResponse:
    async def gen():
        async for chunk in narration_store.sse_stream(execution_id):
            yield chunk
    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@app.get("/api/wingman/desk/narration/{execution_id}/replay")
async def desk_narration_replay(execution_id: str, speed: float = 4.0) -> StreamingResponse:
    async def gen():
        async for chunk in narration_store.replay_stream(execution_id, speed=speed):
            yield chunk
    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@app.get("/api/wingman/desk/narration/{execution_id}/log")
async def desk_narration_log(execution_id: str) -> dict[str, Any]:
    return {"data": {"execution_id": execution_id, "events": narration_store.load(execution_id)}}


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


# ─── Compliance Lens — cross-check trades / rules / hedges / offers ────

_COMPLIANCE_RULES_VERSION = "2025-Q2-v1"


def _action_fingerprint(action: dict[str, Any]) -> str:
    import hashlib
    payload = json.dumps(action, sort_keys=True, default=str)
    return hashlib.sha256((payload + "|" + _COMPLIANCE_RULES_VERSION).encode("utf-8")).hexdigest()[:24]


@app.post("/api/wingman/compliance/validate")
async def compliance_validate(body: dict[str, Any]) -> dict[str, Any]:
    action = (body or {}).get("action") or {}
    if not action.get("action_kind"):
        raise HTTPException(status_code=400, detail="action.action_kind required")

    fingerprint = _action_fingerprint(action)
    cached = result_cache.read("compliance", fingerprint)
    if cached is not None:
        return {"data": cached, "cache": "hit"}

    async with _abenix_client() as forge:
        result = await forge.execute(
            "wingman-compliance-validator",
            json.dumps(action),
            wait_timeout_seconds=120,
        )
    raw = result.output or "{}"
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(raw)
    except Exception:
        s = raw.strip()
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last > first:
            try:
                parsed = json.loads(s[first : last + 1])
            except Exception:
                parsed = {}
    if not parsed:
        parsed = {
            "verdict": "WARN",
            "summary": "Compliance check could not parse validator output; treat as WARN.",
            "reasons": ["validator returned unstructured output"],
            "remediation": ["re-run the check or open the trade for manual review"],
            "citations": [],
            "checks": [],
            "rules_version": _COMPLIANCE_RULES_VERSION,
        }
    parsed["fingerprint"] = fingerprint
    parsed["execution_id"] = getattr(result, "execution_id", None)
    parsed["cost_usd"] = getattr(result, "cost", None)
    parsed["duration_ms"] = getattr(result, "duration_ms", None)
    try:
        result_cache.write("compliance", fingerprint, parsed)
    except Exception:
        pass
    return {"data": parsed, "cache": "miss"}


@app.get("/api/wingman/compliance/cached/{fingerprint}")
async def compliance_cached(fingerprint: str) -> dict[str, Any]:
    cached = result_cache.read("compliance", fingerprint)
    if cached is None:
        raise HTTPException(status_code=404, detail="not in cache")
    return {"data": cached}


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
        parsed = {
            "narrative": "Graph query agent did not return a load-bearing answer. Retry the query, or refine the question.",
            "nodes": [],
            "edges": [],
            "citations": [],
            "data_quality": "agent_unavailable",
        }

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
    try:
        async with _abenix_client() as forge:
            items = await forge.approvals.list(status=status, limit=200)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("approvals list failed")
        raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
    return {"data": items}


@app.get("/api/wingman/approvals/{approval_id}")
async def get_approval(approval_id: str) -> dict[str, Any]:
    try:
        async with _abenix_client() as forge:
            row = await forge.approvals.get(approval_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("approval get failed for %s", approval_id)
        raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
    return {"data": row}


@app.post("/api/wingman/approvals/{approval_id}/approve")
async def approve_approval(
    approval_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = body or {}
    try:
        async with _abenix_client() as forge:
            row = await forge.approvals.approve(
                approval_id, reason=str(body.get("reason") or "")
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("approval approve failed for %s", approval_id)
        raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
    return {"data": row}


@app.post("/api/wingman/approvals/{approval_id}/deny")
async def deny_approval(
    approval_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = body or {}
    try:
        async with _abenix_client() as forge:
            row = await forge.approvals.deny(
                approval_id, reason=str(body.get("reason") or "")
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("approval deny failed for %s", approval_id)
        raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
    return {"data": row}


# ─── Execution detail passthrough ──────────────────────────────────────


@app.get("/api/wingman/executions/{execution_id}")
async def execution_detail(execution_id: str) -> dict[str, Any]:
    """Forward the platform's full execution row.

    Useful when the trader UI shows FAILED but the page has no
    error_message — this endpoint surfaces error_message, failure_code,
    tool_calls and the raw output without needing a platform admin token.

    Ownership: row.subject_type must be 'wingman' (or empty for legacy rows)
    AND row.subject_id must equal the configured Wingman trader. Without this
    gate, anyone with cluster network access could enumerate any tenant's
    execution by id and read raw outputs.
    """
    async with _abenix_client() as forge:
        try:
            row = await forge.executions.get(execution_id) or {}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Execution fetch failed: {e}")
    trader_id = os.environ.get("WINGMAN_DEMO_TRADER_ID", "demo-trader")
    subj_type = str(row.get("subject_type") or "").lower()
    subj_id = str(row.get("subject_id") or "")
    if subj_type not in ("", "wingman") or (subj_id and subj_id != trader_id):
        raise HTTPException(status_code=404, detail="execution not found")
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


# ─── Identity stub ──────────────────────────────────────────────────────

# Wingman has no user database — every browser session acts as the demo
# trader (see _build_subject above). The sidebar fires /api/auth/me to
# populate the bottom-left footer; without this stub the proxy returns a
# 404 and the browser logs a noisy console error on every page load.
@app.get("/api/auth/me")
async def auth_me() -> dict[str, Any]:
    trader_id = os.environ.get("WINGMAN_DEMO_TRADER_ID", "demo-trader")
    return {
        "full_name": f"Wingman {trader_id.replace('-', ' ').title()}",
        "email": f"{trader_id}@wingman.local",
        "subject_id": trader_id,
    }


# ─── Tool catalog passthrough (for AI Builder linking) ──────────────────


@app.get("/api/wingman/tools")
async def list_tools() -> dict[str, Any]:
    """Forward the platform tool catalog via ``forge.tools.list()`` so the
    Wingman builder palette sees the same set as the main Abenix builder
    and the call goes through SDK-managed auth."""
    try:
        async with _abenix_client() as forge:
            items = await forge.tools.list()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("tools list failed")
        raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
    return {"data": items}


# ─── Code-asset registry passthrough ────────────────────────────────────
# Some surfaces (NotificationBell, future builder palette) probe the
# platform code-asset registry on mount. Without this passthrough the
# request lands on Next.js with no rewrite match and the browser logs a
# 502 / 404 console error. Route via the SDK's authenticated http client
# so the Abenix RBAC + acting-subject contract is preserved — never raw
# httpx to ABENIX_URL.
@app.get("/api/code-assets")
async def list_code_assets(scope: str = "all") -> dict[str, Any]:
    try:
        async with _abenix_client() as forge:
            res = await forge.http.get(
                "/api/code-assets",
                params={"scope": scope},
                headers=forge._subject_headers(),
            )
            res.raise_for_status()
            body = res.json() or {}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("code-assets list failed")
        raise HTTPException(status_code=502, detail=f"Backend unreachable: {e}")
    return body if isinstance(body, dict) else {"data": body}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8006"))
    uvicorn.run(app, host="0.0.0.0", port=port)
