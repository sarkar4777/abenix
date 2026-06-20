"""Generalized canonical-anchor guardrail for commodity fair-value agents.

The agent runtime occasionally ignores the YAML "do NOT fall back" rule
and anchors its curve to the wrong commodity (e.g. Henry Hub when TTF or
JKM was fetched). Prompt-only fixes can't stop the model — this module
deterministically rebuilds the curve from the canonical tool call when
the agent's output sits outside the expected price band.

The logic is identical across commodities — only the band, currency,
anchor symbols, and output unit string differ. Each binding declares its
own AnchorConfig and the same _rewrite() does the work.

Importing this module registers every entry in BINDINGS against the
engine post-processor registry.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from statistics import mean
from typing import Iterable

logger = logging.getLogger(__name__)

# Minimum closes we want for a deterministic recompute. realized_vol_calc
# needs >=6 to compute returns; 20 is the defensive floor that still lets
# us run when the agent only fetched 30d.
MIN_PRICES_FOR_RECOMPUTE = 20


@dataclass(frozen=True)
class AnchorConfig:
    """Per-agent binding for the canonical-anchor guardrail.

    `region_bands` is the region-aware override hook. When set, the rewriter
    pulls a region tag off the canonical tool call's input args
    (`input.region`, upper-cased) and picks the matching (min, max, currency)
    tuple instead of the default `band_min`/`band_max`/`expected_currency`.
    Unknown regions fall back to the defaults so a typo doesn't silently
    disable the guardrail.
    """

    agent_slug: str
    tool_name: str
    symbol_aliases: frozenset[str]
    band_min: float
    band_max: float
    expected_currency: str
    price_key: str
    unit_string: str | None
    source_label: str
    fallback_vol: float
    rebuild_on_empty_degraded: bool
    region_bands: dict[str, tuple[float, float, str]] | None = None
    # Optional per-region overrides for the price key and unit string. Needed
    # for agents like Refined Products where RBOB/ULSD are USD/gal but JET is
    # USD/bbl — same agent, different units per sub-product. When set, the
    # rewriter swaps in the matching price_key + unit_string at override time.
    region_price_keys: dict[str, str] | None = None
    region_unit_strings: dict[str, str] | None = None


def _find_canonical_call(tool_runs: list[dict], cfg: AnchorConfig) -> dict | None:
    """Scan tool_runs for the canonical anchor matching `cfg`."""
    aliases = {a.lower() for a in cfg.symbol_aliases}
    for tr in tool_runs:
        if (tr.get("tool") or "").lower() != cfg.tool_name.lower():
            continue
        args = tr.get("input") or {}
        symbol = str(args.get("symbol") or "").lower()
        if symbol not in aliases:
            continue
        out = tr.get("output_summary") or {}
        if (out.get("status") or "").lower() != "ok":
            continue
        prices_count = int(out.get("prices_count") or 0)
        if prices_count < MIN_PRICES_FOR_RECOMPUTE:
            continue
        closes = out.get("closes") or []
        closes_nums = [float(c) for c in closes if isinstance(c, (int, float))]
        if len(closes_nums) < MIN_PRICES_FOR_RECOMPUTE:
            continue
        resolved = out.get("resolved_symbol") or out.get("symbol") or ""
        currency = out.get("currency") or cfg.expected_currency
        fetched_at = out.get("fetched_at") or out.get("last_refresh") or ""
        region = str(args.get("region") or "").strip().upper()
        return {
            "source": cfg.source_label,
            "symbol": resolved,
            "prices": closes_nums,
            "currency": currency,
            "fetched_at": fetched_at,
            "region": region,
        }
    return None


def _expected_band_outside(
    expected_curve: list, lo: float, hi: float, price_keys: Iterable[str]
) -> bool:
    """Any expected_curve price outside [lo, hi] -> band violation."""
    if not isinstance(expected_curve, list) or not expected_curve:
        return False
    for pt in expected_curve:
        price = None
        if isinstance(pt, dict):
            for key in price_keys:
                v = pt.get(key)
                if isinstance(v, (int, float)) and math.isfinite(v):
                    price = float(v)
                    break
        if price is None:
            continue
        if price < lo or price > hi:
            return True
    return False


def _realized_vol(prices: list[float], lookback: int, fallback: float) -> float:
    """Annualized realized vol from log-returns; mirrors realized_vol_calc."""
    window = prices[-lookback:] if len(prices) > lookback else prices
    if len(window) < 6:
        return fallback
    rets = [
        math.log(window[i] / window[i - 1])
        for i in range(1, len(window))
        if window[i] > 0 and window[i - 1] > 0
    ]
    if len(rets) < 2:
        return fallback
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252)


def _monte_carlo_curve(
    spot: float,
    vol: float,
    long_run_mean: float,
    tenor_months: int,
) -> tuple[list[float], list[float], list[float]]:
    """Local MC overlay — deterministic seed so the override is repeatable."""
    try:
        import numpy as np
    except ImportError:
        return (
            [spot] * tenor_months,
            [spot * 0.85] * tenor_months,
            [spot * 1.15] * tenor_months,
        )

    paths = 1000
    kappa = 0.15
    dt = 1.0 / 12.0
    sigma_step = vol * math.sqrt(dt)
    rng = np.random.default_rng(seed=42)
    log_lr = math.log(max(long_run_mean, 1e-6))
    prev = np.full(paths, math.log(spot))
    log_paths = np.zeros((paths, tenor_months))
    for t in range(tenor_months):
        shock = rng.standard_normal(paths) * sigma_step
        reversion = kappa * (log_lr - prev) * dt
        prev = prev + reversion + shock
        log_paths[:, t] = prev
    levels = np.exp(log_paths)
    expected = levels.mean(axis=0).tolist()
    p10 = np.percentile(levels, 10, axis=0).tolist()
    p90 = np.percentile(levels, 90, axis=0).tolist()
    return (
        [round(float(x), 2) for x in expected],
        [round(float(x), 2) for x in p10],
        [round(float(x), 2) for x in p90],
    )


def _curve_points(values: list[float], price_key: str) -> list[dict]:
    return [
        {"tenor_month": i + 1, price_key: round(float(v), 2)}
        for i, v in enumerate(values)
    ]


def _make_rewrite(cfg: AnchorConfig):
    """Bind a config into the (forecast, tool_runs, raw) -> forecast contract."""

    # Include both per-currency keys so multi-region agents (e.g. Power)
    # can emit price_eur_mwh or price_usd_mwh and the band check still
    # finds a number to test.
    price_keys = (
        cfg.price_key,
        "price_eur_mwh",
        "price_usd_mwh",
        "price_per_mwh",
        "price_usd_gal",
        "price_usd_bbl",
        "price_per_gal",
        "price_per_bbl",
        "expected",
        "price",
        "mid",
        "value",
    )

    def rewrite(forecast: dict, tool_runs: list[dict], raw_output: str) -> dict:
        if not isinstance(forecast, dict):
            return forecast

        canonical = _find_canonical_call(tool_runs, cfg)
        if canonical is None:
            return forecast

        # Always stamp spot_anchor from the canonical tool call's closes[-1]
        # BEFORE any band-violation short-circuit. The LLM was free-form
        # extracting it from the prose tool result and picking the wrong
        # number on concurrent runs (Latest Close vs Open vs Period High vs
        # Period Low). This stamp makes spot_anchor identical across all
        # parallel runs because it's derived from the cached closes array.
        try:
            canonical_spot = round(float(canonical["prices"][-1]), 2)
            forecast["spot_anchor"] = canonical_spot
            forecast["anchor_source"] = (
                f"{canonical['source']} ({canonical['symbol']}) latest close"
            )
        except (KeyError, IndexError, TypeError, ValueError) as e:
            logger.info(
                "post_processor[%s]: spot_anchor stamp skipped: %s",
                cfg.agent_slug,
                e,
            )

        band_min, band_max = cfg.band_min, cfg.band_max
        expected_currency = cfg.expected_currency
        price_key = cfg.price_key
        unit_string = cfg.unit_string
        region = canonical.get("region") or ""
        if cfg.region_bands:
            override = cfg.region_bands.get(region)
            if override is not None:
                band_min, band_max, expected_currency = override
            elif region:
                logger.info(
                    "post_processor[%s]: unknown region=%r, using default band",
                    cfg.agent_slug,
                    region,
                )
        if cfg.region_price_keys and region in cfg.region_price_keys:
            price_key = cfg.region_price_keys[region]
        if cfg.region_unit_strings and region in cfg.region_unit_strings:
            unit_string = cfg.region_unit_strings[region]

        expected = forecast.get("expected_curve") or []
        band_violation = _expected_band_outside(
            expected, band_min, band_max, price_keys
        )
        agent_gave_up = (
            cfg.rebuild_on_empty_degraded
            and not expected
            and str(forecast.get("data_quality") or "").lower() == "degraded"
        )
        if not band_violation and not agent_gave_up:
            return forecast

        if canonical["currency"] != expected_currency:
            logger.info(
                "post_processor[%s]: canonical currency=%s expected=%s, skipping override",
                cfg.agent_slug,
                canonical["currency"],
                expected_currency,
            )
            return forecast

        prices = canonical["prices"]
        spot = float(prices[-1])
        vol = _realized_vol(prices, lookback=60, fallback=cfg.fallback_vol)
        lrm_window = prices[-60:] if len(prices) >= 60 else prices
        long_run_mean = float(mean(lrm_window))

        tenor = forecast.get("tenor_months")
        if not isinstance(tenor, int) or tenor < 3 or tenor > 36:
            tenor = 12

        exp_vals, p10_vals, p90_vals = _monte_carlo_curve(
            spot=spot,
            vol=vol,
            long_run_mean=long_run_mean,
            tenor_months=tenor,
        )

        forecast["expected_curve"] = _curve_points(exp_vals, price_key)
        forecast["p10_curve"] = _curve_points(p10_vals, price_key)
        forecast["p90_curve"] = _curve_points(p90_vals, price_key)
        forecast["base_curve"] = _curve_points(exp_vals, price_key)
        if unit_string:
            forecast["unit"] = unit_string

        provenance = forecast.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        provenance["data_source"] = (
            f"{canonical['source']} ({canonical['symbol']}, "
            f"{len(canonical['prices'])} closes) + Monte Carlo overlay"
        )
        provenance["notes"] = (
            f"Live anchor used (latest_close={spot:.2f} {expected_currency} "
            f"as of {canonical['fetched_at'] or 'fetched_at unavailable'}). "
            "Agent fallback claims ignored."
        )
        provenance["mode"] = "mixed"
        provenance["last_refresh"] = (
            canonical["fetched_at"] or provenance.get("last_refresh") or ""
        )
        forecast["provenance"] = provenance

        meta = forecast.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        meta["post_processed"] = True
        meta["post_processor"] = cfg.agent_slug
        forecast["meta"] = meta

        forecast["data_quality"] = "live"

        logger.info(
            "post_processor[%s]: overrode curve with anchor spot=%.2f vol=%.3f lrm=%.2f",
            cfg.agent_slug,
            spot,
            vol,
            long_run_mean,
        )
        return forecast

    return rewrite


# Bindings — one per fair-value agent. Add new commodities by appending
# an AnchorConfig and the registry picks them up automatically.
BINDINGS: tuple[AnchorConfig, ...] = (
    AnchorConfig(
        agent_slug="contractiq_pipeline_gas_fairvalue",
        tool_name="yahoo_finance",
        symbol_aliases=frozenset({"natgas_ttf", "ttf=f"}),
        band_min=10.0,
        band_max=100.0,
        expected_currency="EUR",
        price_key="price_eur_mwh",
        unit_string=None,
        source_label="yahoo_finance natgas_ttf",
        fallback_vol=0.55,
        rebuild_on_empty_degraded=False,
    ),
    AnchorConfig(
        agent_slug="contractiq_lng_fairvalue",
        tool_name="yahoo_finance",
        symbol_aliases=frozenset({"natgas_jkm", "jkm=f"}),
        band_min=5.0,
        band_max=50.0,
        expected_currency="USD",
        price_key="price_usd_mmbtu",
        unit_string="USD/MMBtu",
        source_label="yahoo_finance natgas_jkm",
        fallback_vol=0.60,
        rebuild_on_empty_degraded=True,
    ),
    # Power is one agent that handles 5 regions. The canonical call still
    # comes through yahoo_finance, but the symbol varies per region and so
    # does the sane band. The region tag is read off input.region on the
    # tool call (set by the agent prompt); unknown regions fall back to the
    # default band so the guardrail never silently disables.
    # Crude is one agent that handles two regional benchmarks (Brent global,
    # WTI US). Same region-band pattern as Power: the canonical call carries
    # input.region=BRENT|WTI and the rewriter swaps in the matching band.
    # WTI band floor is 15 USD/bbl — it went negative once in April 2020 but
    # the modern liquid band sits well above zero.
    AnchorConfig(
        agent_slug="contractiq_crude_fairvalue",
        tool_name="yahoo_finance",
        symbol_aliases=frozenset(
            {
                "crude_brent", "bz=f",
                "crude_wti", "cl=f",
            }
        ),
        band_min=15.0,
        band_max=200.0,
        expected_currency="USD",
        price_key="price_usd_bbl",
        unit_string="USD/bbl",
        source_label="yahoo_finance crude",
        fallback_vol=0.45,
        rebuild_on_empty_degraded=True,
        region_bands={
            "BRENT": (20.0, 200.0, "USD"),
            "WTI":   (15.0, 180.0, "USD"),
        },
    ),
    # Coal is one agent that handles three regional benchmarks (Newcastle
    # thermal in Asia-Pac, API2 in Northwest Europe, API4 from Richards Bay
    # South Africa). Yahoo coverage on coal swaps is thin — these aliases
    # resolve to the cleanest tickers we know about, and the agent is wired
    # to degrade honestly when the proxy comes back empty (ICE clears the
    # API2/API4 cargoes daily but those settles aren't on a free feed).
    # Bands differ per benchmark: Newcastle (Asia-Pac thermal) trades wider
    # because China import policy + Indonesian export quotas spike it; API4
    # (Richards Bay) trades the tightest range historically.
    AnchorConfig(
        agent_slug="contractiq_coal_fairvalue",
        tool_name="yahoo_finance",
        symbol_aliases=frozenset(
            {
                "coal_newcastle", "mtf=f",
                "coal_api2", "api2=f",
                "coal_api4", "api4=f",
            }
        ),
        band_min=40.0,
        band_max=500.0,
        expected_currency="USD",
        price_key="price_usd_ton",
        unit_string="USD/ton",
        source_label="yahoo_finance coal",
        fallback_vol=0.50,
        rebuild_on_empty_degraded=True,
        region_bands={
            "NEWCASTLE": (50.0, 500.0, "USD"),
            "API2":      (40.0, 400.0, "USD"),
            "API4":      (40.0, 300.0, "USD"),
        },
    ),
    # Carbon — EU ETS EUA (European Union Allowance) front-month. Yahoo
    # has no clean free EUA future, so the anchor is the KRBN ETF NAV
    # (KraneShares Global Carbon Strategy, EUA-weighted) cross-checked
    # against CO2.L (London-listed Carbon ETC tracking ICE EUA). Band is
    # 30-200 EUR/tCO2: historical EUA range is ~5-95 EUR; the band carries
    # headroom for the Phase 4 MSR-driven upside. KRBN trades USD so the
    # canonical-anchor recompute will be skipped on currency mismatch
    # (handled by `currency != expected_currency` short-circuit) — the
    # binding is kept anchored to EUR to match the agent's emitted unit;
    # when KRBN is the proxy the agent stamps the FX-translated anchor
    # itself and the post-processor honors it.
    AnchorConfig(
        agent_slug="contractiq_carbon_fairvalue",
        tool_name="yahoo_finance",
        symbol_aliases=frozenset(
            {
                "carbon_eua", "krbn",
                "carbon_eua_etc", "co2.l",
            }
        ),
        band_min=30.0,
        band_max=200.0,
        expected_currency="EUR",
        price_key="price_eur_tco2",
        unit_string="EUR/tCO2",
        source_label="yahoo_finance carbon_eua",
        fallback_vol=0.55,
        rebuild_on_empty_degraded=True,
    ),
    AnchorConfig(
        agent_slug="contractiq_power_fairvalue",
        tool_name="yahoo_finance",
        symbol_aliases=frozenset(
            {
                "power_de_day_ahead", "ebr=f",
                "power_de_peakload", "epr=f",
                "power_fr_day_ahead", "fb=f",
                "power_nordpool", "npf=f",
                "power_ercot_north", "ercn=f",
                "power_pjm_west", "pjmw=f",
            }
        ),
        band_min=5.0,
        band_max=500.0,
        expected_currency="EUR",
        price_key="price_per_mwh",
        unit_string=None,
        source_label="yahoo_finance power",
        fallback_vol=0.70,
        rebuild_on_empty_degraded=True,
        region_bands={
            "DE":      (20.0, 400.0, "EUR"),
            "FR":      (20.0, 400.0, "EUR"),
            "NORDICS": (20.0, 400.0, "EUR"),
            "ERCOT":   (5.0,  300.0, "USD"),
            "PJM":     (10.0, 200.0, "USD"),
        },
    ),
    # Refined Products is one agent that handles three NYMEX front-month
    # sub-products (RBOB Gasoline, ULSD Heating Oil, Jet Kerosene). The
    # product tag is carried on the canonical tool call as input.region
    # (so the existing region_bands plumbing applies) — RBOB and ULSD trade
    # in USD/gal, JET trades in USD/bbl, so we need per-product price_key
    # and unit_string overrides too. Jet kero has no reliable free Yahoo
    # ticker (JKER=F is a best-effort attempt); when it returns empty the
    # agent flags degraded honestly and the post-processor leaves the
    # forecast alone (rebuild_on_empty_degraded only kicks in when the
    # canonical tool call DID return prices).
    AnchorConfig(
        agent_slug="contractiq_refined_fairvalue",
        tool_name="yahoo_finance",
        symbol_aliases=frozenset(
            {
                "refined_rbob", "rb=f",
                "refined_ulsd", "ho=f",
                "refined_jet",  "jker=f",
            }
        ),
        band_min=1.0,
        band_max=200.0,
        expected_currency="USD",
        price_key="price_usd_gal",
        unit_string=None,
        source_label="yahoo_finance refined",
        fallback_vol=0.45,
        rebuild_on_empty_degraded=True,
        region_bands={
            "RBOB": (1.0,  5.0,   "USD"),
            "ULSD": (1.0,  5.0,   "USD"),
            "JET":  (40.0, 200.0, "USD"),
        },
        region_price_keys={
            "RBOB": "price_usd_gal",
            "ULSD": "price_usd_gal",
            "JET":  "price_usd_bbl",
        },
        region_unit_strings={
            "RBOB": "USD/gal",
            "ULSD": "USD/gal",
            "JET":  "USD/bbl",
        },
    ),
)


def _register_all() -> None:
    try:
        from engine import post_processors as _registry
    except ImportError as e:
        logger.warning("canonical_anchor: engine.post_processors unavailable: %s", e)
        return
    for cfg in BINDINGS:
        _registry.register(cfg.agent_slug, _make_rewrite(cfg))


def rewrite_for_slug(slug: str, forecast: dict, tool_runs: list[dict]) -> dict:
    """Public helper for callers that import this module directly.

    Used by the contractiq API as defense-in-depth when the runtime hasn't
    already stamped meta.post_processed=true on the forecast.
    """
    for cfg in BINDINGS:
        if cfg.agent_slug == slug:
            return _make_rewrite(cfg)(forecast, tool_runs, "")
    return forecast


_register_all()
