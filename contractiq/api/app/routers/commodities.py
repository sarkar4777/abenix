"""ContractIQ Commodities — Wingman-style fair-value / anomaly / thesis lenses.

Three endpoints per commodity slug. Each one is a thin pass-through to a
dedicated Abenix agent (contractiq_<slug>_fairvalue / anomaly / thesis) so all
LLM and ML work stays in the agent runtime — this router never talks to a
model directly.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

import time

from app.core.responses import error, success
from app.routers.auth import get_contractiq_user
from app.models.contractiq_models import ContractIQUser

# Process-local rolling record of the last successful spot_anchor per
# (commodity_key, region_or_hub) within the last 60s. Used purely for a
# post-condition sanity warning when a fresh run's anchor diverges by
# more than the threshold from a recent successful one — surfaces the
# Brent 80 -> 126 USD/bbl race in the logs even after the yahoo_finance
# cache + lock pin the spot.
_SPOT_DIVERGENCE_PCT = 5.0
_SPOT_HISTORY_TTL_SECS = 60.0
_RECENT_SPOTS: dict[tuple, tuple[float, float]] = {}  # key -> (value, expires_at)


def _record_and_warn_spot(key: tuple, value: float) -> None:
    """Log a warning when the new spot_anchor diverges >5% from a
    recent successful run for the same key. Always records the new
    value (with a fresh TTL) so the next caller compares against the
    latest known good."""
    if value is None or not isinstance(value, (int, float)) or value <= 0:
        return
    now = time.monotonic()
    # Drop expired entries lazily — keeps the dict small without a sweeper.
    for k in [k for k, (_, exp) in _RECENT_SPOTS.items() if exp <= now]:
        _RECENT_SPOTS.pop(k, None)
    prev = _RECENT_SPOTS.get(key)
    if prev and prev[1] > now:
        diff_pct = abs(value - prev[0]) / prev[0] * 100.0 if prev[0] else 0.0
        if diff_pct > _SPOT_DIVERGENCE_PCT:
            logger.warning(
                "spot_anchor divergence: key=%s prev=%.4f new=%.4f diff=%.2f%% "
                "(within %ds window) — possible yahoo_finance race or stale cache",
                key, prev[0], value, diff_pct, int(_SPOT_HISTORY_TTL_SECS),
            )
    _RECENT_SPOTS[key] = (float(value), now + _SPOT_HISTORY_TTL_SECS)


def _canonical_latest_close(raw_calls: list[Any] | None) -> float | None:
    """Read the cross-pod canonical latest_close off the yahoo_finance tool
    call's output_summary. This is the byte-stable number the cache emits;
    if the agent's spot_anchor diverges from it the LLM picked the wrong
    field out of the prose tool result and we should repair in-place."""
    if not raw_calls:
        return None
    for c in raw_calls:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or c.get("tool_name") or "").lower()
        if name != "yahoo_finance":
            continue
        summary = c.get("output_summary") or {}
        if not isinstance(summary, dict):
            continue
        lc = summary.get("latest_close")
        if isinstance(lc, (int, float)) and lc > 0:
            return float(lc)
        # Defense: some runs only carry the closes array.
        closes = summary.get("closes") or []
        if isinstance(closes, list) and closes:
            tail = closes[-1]
            if isinstance(tail, (int, float)) and tail > 0:
                return float(tail)
    return None


def _repair_spot_anchor(parsed: dict | None, raw_calls: list[Any] | None) -> dict | None:
    """Cross-check parsed.spot_anchor against the tool-call canonical
    latest_close. If they diverge >1% (or spot_anchor is missing), stamp
    the canonical value and tag provenance. Defense in depth for when the
    runtime post_processor list isn't loaded."""
    if not isinstance(parsed, dict):
        return parsed
    canonical = _canonical_latest_close(raw_calls)
    if canonical is None:
        return parsed
    current = _extract_spot_anchor(parsed)
    if current is not None and current > 0:
        diff_pct = abs(current - canonical) / canonical * 100.0
        if diff_pct <= 1.0:
            return parsed
        logger.warning(
            "router repair: spot_anchor=%.4f differs from tool latest_close=%.4f "
            "by %.2f%% — stamping canonical",
            current, canonical, diff_pct,
        )
    parsed["spot_anchor"] = round(canonical, 2)
    parsed.setdefault("anchor_source", "yahoo_finance latest_close (router repair)")
    return parsed


def _extract_spot_anchor(parsed: dict | None) -> float | None:
    """Pull spot_anchor out of the agent payload — agents store it at
    the top level or under provenance, depending on the template."""
    if not isinstance(parsed, dict):
        return None
    for path in (("spot_anchor",), ("provenance", "spot_anchor"), ("anchor",)):
        cur: Any = parsed
        for p in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(p)
        if isinstance(cur, (int, float)) and cur > 0:
            return float(cur)
        if isinstance(cur, str):
            try:
                v = float(cur)
                if v > 0:
                    return v
            except ValueError:
                pass
    return None

# Make the bundled abenix_sdk importable at module load instead of on every
# request. Doing this per-request was a race-condition footgun — two
# concurrent calls could both push the same path, blow up sys.path ordering,
# and risk shadowing a sibling package. The path is idempotent because we
# guard with a membership check before inserting.
_SDK_PATH = str(Path(__file__).resolve().parents[2] / "sdk")
if _SDK_PATH not in sys.path:
    sys.path.insert(0, _SDK_PATH)

from abenix_sdk import Abenix, ActingSubject  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/commodities", tags=["contractiq-commodities"])


# Commodities we have agents for. Others are advertised as "coming soon" in the
# UI but the API still 400s so we never accidentally fire an unbuilt agent.
SUPPORTED_SLUGS = {
    "pipeline_gas",
    "lng",
    "power",
    "carbon",
    "crude",
    "refined",
    "coal",
}

# Hubs per commodity. Validated server-side so a typo in the UI doesn't hit a
# bogus agent prompt.
SUPPORTED_HUBS: dict[str, set[str]] = {
    "pipeline_gas": {"TTF", "NBP", "PEG", "THE", "CEGH", "PSV"},
    "lng": {"JKM", "FOB_USGC", "DES_NWE", "TFDES"},
}

DEFAULT_HUB: dict[str, str] = {
    "pipeline_gas": "TTF",
    "lng": "JKM",
}

# Region-driven commodities (one agent, multiple benchmarks). The "hub" lever on
# the API surface becomes a region picker that the agent reads off the input.
# Carbon currently only has EUA so its region set is single-element but the
# selector keeps the shape uniform for the UI.
SUPPORTED_REGIONS: dict[str, set[str]] = {
    "power": {"DE", "FR", "NORDICS", "ERCOT", "PJM"},
    "crude": {"BRENT", "WTI"},
    "coal": {"NEWCASTLE", "API2", "API4"},
    "carbon": {"EUA"},
}

DEFAULT_REGION: dict[str, str] = {
    "power": "DE",
    "crude": "BRENT",
    "coal": "NEWCASTLE",
    "carbon": "EUA",
}

# Product-driven commodities. Refined splits into RBOB/ULSD/JET — one agent,
# three products.
SUPPORTED_PRODUCTS: dict[str, set[str]] = {
    "refined": {"RBOB", "ULSD", "JET"},
}

DEFAULT_PRODUCT: dict[str, str] = {
    "refined": "RBOB",
}


def _parse_json_blob(text: str) -> dict | None:
    """Same lenient JSON extractor used by insights.py — kept local so the two
    routers can diverge without coupling."""
    if not text:
        return None
    cleaned = text.strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass
    fence = re.search(r"```(?:json)?\s*\n([\s\S]*?)```", cleaned)
    if fence:
        inner = fence.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


async def _call_abenix(
    user: ContractIQUser,
    agent_slug: str,
    message: str,
    timeout: float = 300.0,
) -> tuple[dict | None, str, dict]:
    """Invoke an Abenix agent via SDK with actAs delegation."""
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
        raw = result.output or ""
        parsed = _parse_json_blob(raw)
        # Surface the per-call tool payload (name, args, content snippet) so
        # the UI audit drawer can render a real exec trace instead of just a
        # call count. Truncate content to 200 chars to keep the payload tight.
        raw_calls = list(result.tool_calls or [])
        tool_call_details: list[dict[str, Any]] = []
        for c in raw_calls:
            if not isinstance(c, dict):
                continue
            content_val = c.get("content") or c.get("result") or c.get("output") or ""
            if not isinstance(content_val, str):
                try:
                    content_val = json.dumps(content_val)
                except Exception:
                    content_val = str(content_val)
            tool_call_details.append(
                {
                    "tool_name": c.get("tool_name") or c.get("name") or "",
                    "args": c.get("args") or c.get("arguments") or {},
                    "content_snippet": content_val[:200],
                }
            )
        meta = {
            "execution_id": str(getattr(result, "execution_id", "") or ""),
            "duration_ms": result.duration_ms or 0,
            "cost_usd": float(result.cost or 0.0),
            "model": getattr(result, "model", None),
            "tool_calls": len(raw_calls),
            "tool_call_details": tool_call_details,
            "input_tokens": result.input_tokens or 0,
            "output_tokens": result.output_tokens or 0,
            # Raw tool_calls (with output_summary stamped by the runtime)
            # — only used by the per-endpoint guardrail below; not surfaced
            # to the UI to keep the response payload tight.
            "_raw_tool_calls": raw_calls,
        }
        return parsed, raw, meta


def _tool_runs_from_raw(raw_calls: list[Any]) -> list[dict[str, Any]]:
    """Project the SDK's raw tool_calls into the (tool, input, output_summary)
    shape the canonical-anchor guardrail expects."""
    out: list[dict[str, Any]] = []
    for c in raw_calls or []:
        if not isinstance(c, dict):
            continue
        tool = c.get("name") or c.get("tool_name") or ""
        args = c.get("arguments") or c.get("args") or {}
        summary = c.get("output_summary") or {}
        out.append({"tool": tool, "input": args, "output_summary": summary})
    return out


def _apply_canonical_guardrail(
    slug: str, parsed: dict | None, raw_calls: list[Any]
) -> dict | None:
    """Defense-in-depth canonical-anchor pass for fair-value agents.

    The agent-runtime already runs the same rewrite via
    `contractiq.runtime.post_processors.canonical_anchor` when its
    POST_PROCESSOR_MODULES env var includes that path. If the runtime
    succeeded the forecast carries `meta.post_processed=true` and we pass
    through. If for any reason it didn't (older binary, direct embed
    mode), the CIQ router applies the same rewrite using the
    output_summary stamped onto each tool_call by the executor.
    """
    if not isinstance(parsed, dict):
        return parsed
    if isinstance(parsed.get("meta"), dict) and parsed["meta"].get("post_processed"):
        return parsed

    tool_runs = _tool_runs_from_raw(raw_calls)
    if not tool_runs:
        return parsed

    try:
        from contractiq.runtime.post_processors.canonical_anchor import (
            rewrite_for_slug,
        )
    except Exception as e:
        logger.debug("canonical guardrail: module unavailable: %s", e)
        return parsed

    try:
        return rewrite_for_slug(slug, parsed, tool_runs)
    except Exception as e:
        logger.warning("canonical guardrail: rewrite failed for %s: %s", slug, e)
        return parsed


def _apply_pipeline_gas_guardrail(
    parsed: dict | None, raw_calls: list[Any]
) -> dict | None:
    return _apply_canonical_guardrail(
        "contractiq_pipeline_gas_fairvalue", parsed, raw_calls
    )


def _apply_lng_guardrail(
    parsed: dict | None, raw_calls: list[Any]
) -> dict | None:
    return _apply_canonical_guardrail(
        "contractiq_lng_fairvalue", parsed, raw_calls
    )


def _validate(slug: str, hub: str | None) -> tuple[str, str] | JSONResponse:
    if slug not in SUPPORTED_SLUGS:
        return error(f"Commodity '{slug}' is not enabled yet", 400)
    hub_clean = (hub or DEFAULT_HUB.get(slug, "")).upper().strip()
    if hub_clean not in SUPPORTED_HUBS.get(slug, set()):
        return error(
            f"Hub '{hub_clean}' is not supported for {slug}. "
            f"Use one of: {sorted(SUPPORTED_HUBS.get(slug, set()))}",
            400,
        )
    return (slug, hub_clean)


def _validate_region(slug: str, region: str | None) -> tuple[str, str] | JSONResponse:
    if slug not in SUPPORTED_SLUGS:
        return error(f"Commodity '{slug}' is not enabled yet", 400)
    region_clean = (region or DEFAULT_REGION.get(slug, "")).upper().strip()
    if region_clean not in SUPPORTED_REGIONS.get(slug, set()):
        return error(
            f"Region '{region_clean}' is not supported for {slug}. "
            f"Use one of: {sorted(SUPPORTED_REGIONS.get(slug, set()))}",
            400,
        )
    return (slug, region_clean)


def _validate_product(slug: str, product: str | None) -> tuple[str, str] | JSONResponse:
    if slug not in SUPPORTED_SLUGS:
        return error(f"Commodity '{slug}' is not enabled yet", 400)
    product_clean = (product or DEFAULT_PRODUCT.get(slug, "")).upper().strip()
    if product_clean not in SUPPORTED_PRODUCTS.get(slug, set()):
        return error(
            f"Product '{product_clean}' is not supported for {slug}. "
            f"Use one of: {sorted(SUPPORTED_PRODUCTS.get(slug, set()))}",
            400,
        )
    return (slug, product_clean)


def _build_response(parsed: dict | None, raw: str, meta: dict, lens: str) -> dict:
    """Shape the agent payload + execution meta into the API envelope."""
    return {
        "lens": lens,
        "forecast": parsed,
        "raw_output": None if parsed else (raw or "")[:2000],
        "execution_id": meta.get("execution_id"),
        "cost_usd": meta.get("cost_usd"),
        "duration_ms": meta.get("duration_ms"),
        "model": meta.get("model"),
        "tool_calls": meta.get("tool_calls"),
        "input_tokens": meta.get("input_tokens"),
        "output_tokens": meta.get("output_tokens"),
        "meta": {
            "tool_calls": meta.get("tool_call_details") or [],
        },
    }


def _strip_internal_meta(meta: dict) -> dict:
    """Drop fields that should never reach the UI envelope."""
    return {k: v for k, v in meta.items() if not k.startswith("_")}


# ─── Endpoints ──────────────────────────────────────────────────────────


@router.post("/{slug}/forward/run")
async def run_forward(
    slug: str,
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    """Run the forward-curve fan-chart agent for {slug}.

    Pipeline_gas and lng key off a hub label (TTF/JKM/etc). Power is a single
    multi-region agent that takes a region tag (DE/FR/NORDICS/ERCOT/PJM) +
    horizon. The endpoint routes on slug to keep the UI surface uniform.
    """
    body = body or {}

    # Region-driven commodities: power, crude, coal, carbon. Same JSON-shaped
    # input contract — the agent reads {commodity, region, horizon_months}.
    if slug in SUPPORTED_REGIONS:
        check = _validate_region(slug, body.get("region"))
        if isinstance(check, JSONResponse):
            return check
        slug_clean, region_clean = check
        horizon = body.get("horizon_months")
        try:
            horizon_int = int(horizon) if horizon is not None else 12
        except (TypeError, ValueError):
            horizon_int = 12
        horizon_int = max(3, min(24, horizon_int))

        agent_slug = f"contractiq_{slug_clean}_fairvalue"
        msg = json.dumps(
            {
                "commodity": slug_clean,
                "region": region_clean,
                "horizon_months": horizon_int,
            }
        )
        try:
            parsed, raw, meta = await _call_abenix(user, agent_slug, msg)
        except Exception as e:
            logger.exception("%s forward run failed for region=%s", slug_clean, region_clean)
            return error(f"Agent invocation failed: {e}", 503)

        parsed = _apply_canonical_guardrail(agent_slug, parsed, meta.get("_raw_tool_calls"))
        parsed = _repair_spot_anchor(parsed, meta.get("_raw_tool_calls"))
        spot = _extract_spot_anchor(parsed)
        if spot is not None:
            _record_and_warn_spot((slug_clean, region_clean), spot)

        # Live-feed honesty: when the agent reported degraded data quality
        # AND no spot anchor was produced, surface as HTTP 503 with the
        # same body so the UI shows "Live feed unavailable" instead of
        # rendering an empty chart. Applies to every region-driven
        # commodity (power DE/FR/NORDICS is the trigger today; coal/crude
        # benefit from the same gate).
        body_envelope = _build_response(
            parsed, raw, _strip_internal_meta(meta), lens="forward"
        )
        data_quality = (
            (parsed or {}).get("data_quality")
            if isinstance(parsed, dict)
            else None
        )
        if spot is None and data_quality == "degraded":
            logger.warning(
                "%s forward returned degraded with no spot_anchor for region=%s "
                "— surfacing as HTTP 503",
                slug_clean, region_clean,
            )
            return JSONResponse(
                status_code=503,
                content={"data": body_envelope, "error": {
                    "message": (
                        f"Live feed unavailable for {region_clean} "
                        f"{slug_clean}, please try later"
                    ),
                    "code": 503,
                    "data_quality": "degraded",
                }},
            )
        return success(body_envelope)

    # Product-driven commodities: refined (RBOB/ULSD/JET). Same JSON-shaped
    # input as the region branch but the lever is product instead of region.
    if slug in SUPPORTED_PRODUCTS:
        check = _validate_product(slug, body.get("product"))
        if isinstance(check, JSONResponse):
            return check
        slug_clean, product_clean = check
        horizon = body.get("horizon_months")
        try:
            horizon_int = int(horizon) if horizon is not None else 12
        except (TypeError, ValueError):
            horizon_int = 12
        horizon_int = max(3, min(24, horizon_int))

        agent_slug = f"contractiq_{slug_clean}_fairvalue"
        msg = json.dumps(
            {
                "commodity": slug_clean,
                "product": product_clean,
                "horizon_months": horizon_int,
            }
        )
        try:
            parsed, raw, meta = await _call_abenix(user, agent_slug, msg)
        except Exception as e:
            logger.exception("%s forward run failed for product=%s", slug_clean, product_clean)
            return error(f"Agent invocation failed: {e}", 503)

        parsed = _apply_canonical_guardrail(agent_slug, parsed, meta.get("_raw_tool_calls"))
        parsed = _repair_spot_anchor(parsed, meta.get("_raw_tool_calls"))
        spot = _extract_spot_anchor(parsed)
        if spot is not None:
            _record_and_warn_spot((slug_clean, product_clean), spot)
        return success(_build_response(parsed, raw, _strip_internal_meta(meta), lens="forward"))

    check = _validate(slug, body.get("hub"))
    if isinstance(check, JSONResponse):
        return check
    slug_clean, hub_clean = check

    agent_slug = f"contractiq_{slug_clean}_fairvalue"
    msg = (
        f"Generate a forward-curve fair-value view for hub={hub_clean}. "
        f"Return a JSON object with: base_curve (array of "
        f"{{tenor,mid}}), expected_curve (array of {{tenor,expected}}), "
        f"p10 and p90 (arrays of {{tenor,value}}), scenarios (3-5 named "
        f"with probability + impact), drivers (cited headlines), "
        f"provenance (data_source, last_refresh, mode)."
    )
    try:
        parsed, raw, meta = await _call_abenix(user, agent_slug, msg)
    except Exception as e:
        logger.exception("Forward run failed for %s/%s", slug_clean, hub_clean)
        return error(f"Agent invocation failed: {e}", 503)

    # Deterministic guardrail for pipeline_gas: override fabricated curves
    # when the agent ignored its own tool output (azure-gpt-4o repeatedly
    # ran natgas_ttf successfully then anchored on Henry Hub USD anyway).
    # Runtime-side post-processor already does this; the CIQ call is a
    # defense-in-depth pass that no-ops when meta.post_processed is set.
    if slug_clean == "pipeline_gas":
        parsed = _apply_pipeline_gas_guardrail(parsed, meta.get("_raw_tool_calls"))
    elif slug_clean == "lng":
        parsed = _apply_lng_guardrail(parsed, meta.get("_raw_tool_calls"))

    parsed = _repair_spot_anchor(parsed, meta.get("_raw_tool_calls"))
    spot = _extract_spot_anchor(parsed)
    if spot is not None:
        _record_and_warn_spot((slug_clean, hub_clean), spot)

    return success(_build_response(parsed, raw, _strip_internal_meta(meta), lens="forward"))


@router.post("/{slug}/anomaly/run")
async def run_anomaly(
    slug: str,
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    """Run the anomaly / spread-residual agent for {slug} on the requested hub."""
    body = body or {}
    check = _validate(slug, body.get("hub"))
    if isinstance(check, JSONResponse):
        return check
    slug_clean, hub_clean = check

    agent_slug = f"contractiq_{slug_clean}_anomaly"
    msg = (
        f"Detect spread anomalies for hub={hub_clean}. Return JSON with: "
        f"verdict (aligned/stretched/dislocated), direction (rich/cheap), "
        f"observed_spread, fair_value_band, residual_sigma, "
        f"anomaly_flag, market_regime."
    )
    try:
        parsed, raw, meta = await _call_abenix(user, agent_slug, msg)
    except Exception as e:
        logger.exception("Anomaly run failed for %s/%s", slug_clean, hub_clean)
        return error(f"Agent invocation failed: {e}", 503)

    return success(_build_response(parsed, raw, _strip_internal_meta(meta), lens="anomaly"))


@router.post("/{slug}/thesis/run")
async def run_thesis(
    slug: str,
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    """Run the narrative-thesis agent for {slug} on the requested hub."""
    body = body or {}
    check = _validate(slug, body.get("hub"))
    if isinstance(check, JSONResponse):
        return check
    slug_clean, hub_clean = check

    agent_slug = f"contractiq_{slug_clean}_thesis"
    msg = (
        f"Write the trading thesis for hub={hub_clean}. Return JSON with: "
        f"summary (2-3 sentence headline), narrative_markdown (full "
        f"explainer), key_drivers (array of {{category, headline, "
        f"source, url, impact}}), trade_card (structure, size, horizon, "
        f"expected_pnl, downside_p95), confidence."
    )
    try:
        parsed, raw, meta = await _call_abenix(user, agent_slug, msg)
    except Exception as e:
        logger.exception("Thesis run failed for %s/%s", slug_clean, hub_clean)
        return error(f"Agent invocation failed: {e}", 503)

    return success(_build_response(parsed, raw, _strip_internal_meta(meta), lens="thesis"))


_COMMODITY_LABELS: dict[str, str] = {
    "pipeline_gas": "Pipeline Gas",
    "lng": "LNG",
    "power": "Power",
    "carbon": "Carbon (EUA)",
    "crude": "Crude",
    "refined": "Refined Products",
    "coal": "Coal",
}


@router.get("/catalog")
async def catalog() -> JSONResponse:
    """List supported commodities + hubs/regions/products so the UI never hardcodes them."""
    return success(
        {
            "commodities": [
                {
                    "slug": s,
                    "label": _COMMODITY_LABELS.get(s, s),
                    "hubs": sorted(SUPPORTED_HUBS.get(s, set())),
                    "default_hub": DEFAULT_HUB.get(s),
                    "regions": sorted(SUPPORTED_REGIONS.get(s, set())),
                    "default_region": DEFAULT_REGION.get(s),
                    "products": sorted(SUPPORTED_PRODUCTS.get(s, set())),
                    "default_product": DEFAULT_PRODUCT.get(s),
                }
                for s in sorted(SUPPORTED_SLUGS)
            ]
        }
    )
