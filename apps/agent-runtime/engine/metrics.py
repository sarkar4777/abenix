from __future__ import annotations

from prometheus_client import REGISTRY, Counter, Gauge, Histogram


def _safe_metric(metric_cls, name: str, *args, **kwargs):
    """Register a metric; reuse the existing one if a matching name is
    already in the global REGISTRY.

    Single canonical entry point for the runtime — any module that needs
    a Counter / Gauge / Histogram MUST come through here instead of
    instantiating the prom_client class at import time. Bare construction
    crashes the runtime when the same module gets imported twice via
    different sys.path entries (the api host injects ``apps/agent-runtime``
    on PYTHONPATH so this is a routine hazard).
    """
    existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
    if existing is not None:
        return existing
    try:
        return metric_cls(name, *args, **kwargs)
    except ValueError:
        # Race / shadow registration — fall back to whatever the registry
        # has now. Prefer a working metric over an exception.
        return getattr(REGISTRY, "_names_to_collectors", {}).get(name) or metric_cls(
            name,
            *args,
            **kwargs,
            registry=None,
        )


def _safe_counter(name: str, doc: str, labelnames: list[str] | None = None):
    """Counter convenience wrapper around _safe_metric. Kept around so the
    older cache/orchestrator import surface stays stable."""
    if labelnames:
        return _safe_metric(Counter, name, doc, labelnames)
    return _safe_metric(Counter, name, doc)


def _safe_histogram(name: str, doc: str, labelnames: list[str] | None = None, **kw):
    if labelnames:
        return _safe_metric(Histogram, name, doc, labelnames, **kw)
    return _safe_metric(Histogram, name, doc, **kw)


def _safe_gauge(name: str, doc: str, labelnames: list[str] | None = None):
    if labelnames:
        return _safe_metric(Gauge, name, doc, labelnames)
    return _safe_metric(Gauge, name, doc)


# Cache layer metrics — moved here from engine/cache/orchestrator.py so
# every metric in the runtime is defined once, in this module. The
# orchestrator imports these symbols by name.
cache_hits = _safe_counter(
    "abenix_cache_hits_total",
    "Cache hits by layer",
    ["layer"],
)
cache_misses = _safe_counter(
    "abenix_cache_misses_total",
    "Cache misses (full waterfall miss)",
)


llm_tokens_total = _safe_metric(
    Counter,
    "abenix_runtime_llm_tokens_total",
    "LLM tokens consumed (runtime-side)",
    ["model", "direction"],
)

llm_request_duration_seconds = _safe_metric(
    Histogram,
    "abenix_llm_request_duration_seconds",
    "LLM request latency",
    ["model", "provider"],
)

llm_errors_total = _safe_metric(
    Counter,
    "abenix_llm_errors_total",
    "LLM request errors",
    ["model", "error_type", "provider"],
)

agent_execution_duration_seconds = _safe_metric(
    Histogram,
    "abenix_agent_execution_duration_seconds",
    "Agent execution duration",
)

agent_active_streams = _safe_metric(
    Gauge,
    "abenix_agent_active_streams",
    "Number of active agent streams",
)

tool_execution_duration_seconds = _safe_metric(
    Histogram,
    "abenix_tool_execution_duration_seconds",
    "Tool execution duration",
    ["tool_name"],
)

# We expose short uppercase aliases so call sites stay readable without
# the `_total` / `_seconds` boilerplate. Both names point at the same
# Counter/Histogram instance — no double-counting.
LLM_TOKENS = _safe_metric(
    Counter,
    "abenix_llm_tokens_provider_total",
    "LLM tokens broken out by provider + model + direction",
    ["provider", "model", "direction"],
)
LLM_COST_USD = _safe_metric(
    Counter,
    "abenix_llm_cost_usd_provider_total",
    "Dollar cost of LLM calls grouped by provider + model",
    ["provider", "model"],
)
LLM_DURATION = _safe_metric(
    Histogram,
    "abenix_llm_call_duration_provider_seconds",
    "LLM call latency by provider + model",
    ["provider", "model"],
    buckets=(0.1, 0.3, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)

# Sandbox runs (code_asset / sandboxed_job / ml_model). Outcome:
# ok | timeout | nonzero. image_family: python|node|go|rust|ruby|java|perl|other.
SANDBOX_RUNS = _safe_metric(
    Counter,
    "abenix_runtime_sandbox_runs_total",
    "Sandbox runs grouped by backend / image family / outcome",
    ["backend", "image_family", "outcome"],
)
SANDBOX_DURATION = _safe_metric(
    Histogram,
    "abenix_runtime_sandbox_run_duration_seconds",
    "Sandbox end-to-end run time",
    ["backend", "image_family"],
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)

# Tool calls — every tool invocation per agent run. Lets us see "agent X
# called database_query 412 times in 60s" runaway loops.
TOOL_CALLS = _safe_metric(
    Counter,
    "abenix_runtime_tool_calls_total",
    "Tool invocations grouped by tool + outcome",
    ["tool_name", "outcome"],  # outcome = ok|error
)

# Moderation gate decisions. `source` = pre_llm|post_llm|tool_output|
# api_vet|agent_tool. `outcome` = allowed|flagged|redacted|blocked|error.
# Dashboards alert when `blocked` spikes — usually signals a jailbreak
# attempt or a prompt leak.
moderation_decisions_total = _safe_metric(
    Counter,
    "abenix_moderation_decisions_total",
    "Moderation decisions grouped by source + outcome",
    ["source", "outcome"],
)

# Per-resource invocation counters — feed the resource-centric Grafana
# dashboards and the /api/<resource>/{id}/stats endpoints alongside the DB
# event log (code_asset_invocations / ml_model_invocations / kb_query_invocations).
CODE_ASSET_INVOCATIONS_TOTAL = _safe_metric(
    Counter,
    "abenix_code_asset_invocations_total",
    "Code asset pod invocations grouped by asset + status",
    ["code_asset_id", "status"],
)
CODE_ASSET_DURATION_SECONDS = _safe_metric(
    Histogram,
    "abenix_code_asset_duration_seconds",
    "Code asset pod end-to-end duration",
    ["code_asset_id"],
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)

ML_MODEL_INVOCATIONS_TOTAL = _safe_metric(
    Counter,
    "abenix_ml_model_invocations_total",
    "ML model predictions grouped by model + operation + status",
    ["ml_model_id", "operation", "status"],
)
ML_MODEL_DURATION_SECONDS = _safe_metric(
    Histogram,
    "abenix_ml_model_duration_seconds",
    "ML model inference latency",
    ["ml_model_id", "operation"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
ML_MODEL_COST_USD_TOTAL = _safe_metric(
    Counter,
    "abenix_ml_model_cost_usd_total",
    "Cumulative ML model inference cost in USD",
    ["ml_model_id"],
)

KB_QUERY_INVOCATIONS_TOTAL = _safe_metric(
    Counter,
    "abenix_kb_query_invocations_total",
    "Knowledge-base query invocations grouped by collection + status",
    ["kb_collection_id", "status"],
)
KB_QUERY_DURATION_SECONDS = _safe_metric(
    Histogram,
    "abenix_kb_query_duration_seconds",
    "Knowledge-base query latency",
    ["kb_collection_id"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
