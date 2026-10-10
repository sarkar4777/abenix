"""Tool metadata API — returns descriptions and schemas for all built-in tools."""

from __future__ import annotations

import logging
import asyncio
import os
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


# ── Schema discovery from the runtime ─────────────────────────────────────
# Every BaseTool subclass declares `input_schema` as a class attribute. The
# catalogue below carries the human-friendly metadata (category, blurb), but
# the JSON Schema lives with the implementation. We pull schemas from the
# runtime registry on first request and memoise — keeps the catalogue and
# the executor in lockstep without duplicating definitions.
_RUNTIME_SCHEMAS: dict[str, dict[str, Any]] | None = None


# Tools the executor builds with execution context, so they are not in
# _TOOL_CLASSES but still belong in the catalogue.
LAZY_TOOL_MODULES = [
    ("engine.tools.knowledge_search", ["KnowledgeSearchTool"]),
    # Registered the same lazy way as knowledge_search, and missing here
    # meant it never appeared in the catalogue at all.
    ("engine.tools.knowledge_store", ["KnowledgeStoreTool"]),
    ("engine.tools.graph_explorer_tool", ["GraphExplorerTool"]),
    (
        "engine.tools.atlas_tools",
        [
            "AtlasDescribeTool",
            "AtlasQueryTool",
            "AtlasTraverseTool",
            "AtlasSearchGroundedTool",
        ],
    ),
    ("engine.tools.schema_portfolio_tool", ["SchemaPortfolioTool"]),
]


def _lazy_tool_classes() -> dict[str, type]:
    import importlib

    out: dict[str, type] = {}
    for mod_path, class_names in LAZY_TOOL_MODULES:
        try:
            mod = importlib.import_module(mod_path)
        except Exception as e:  # noqa: BLE001
            logger.debug("lazy tool import failed %s: %s", mod_path, e)
            continue
        for cn in class_names:
            cls = getattr(mod, cn, None)
            name = getattr(cls, "name", None) if cls else None
            if cls is not None and name:
                out[name] = cls
    return out


def _runtime_tool_slugs() -> list[str]:
    """Every tool slug the executor can actually run."""
    try:
        from engine.agent_executor import list_tool_classes  # type: ignore

        slugs = list(list_tool_classes())
        slugs += [n for n in _lazy_tool_classes() if n not in slugs]
        return slugs
    except Exception as e:  # pragma: no cover — import-environment dependent
        logger.warning("could not enumerate runtime tools: %s", e)
        return []


def _runtime_tool_description(slug: str) -> str | None:
    """The tool class description in full, or the first line of its docstring."""
    try:
        from engine.agent_executor import get_tool_class  # type: ignore

        cls = get_tool_class(slug) or _lazy_tool_classes().get(slug)
        if cls is None:
            return None
        desc = getattr(cls, "description", None)
        if isinstance(desc, str) and desc.strip():
            # whole text, the catalogue clamps it for display
            return " ".join(desc.split())
        doc = (cls.__doc__ or "").strip()
        return doc.split("\n")[0] or None
    except Exception:
        return None


# Slug-prefix hints for bucketing an uncatalogued tool into a palette group.
_CATEGORY_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("atlas_", "graph_", "vector_", "knowledge_", "semantic_"), "data"),
    (
        ("mqtt_", "tsdb_", "windowed_", "subscribed_", "kafka_", "redis_stream"),
        "integration",
    ),
    (("moodys", "spg_", "fitch", "edgar", "ferc", "bundesanzeiger", "eex_"), "finance"),
    (("crypto_", "realized_vol", "monte_carlo", "notional_", "credit_risk"), "finance"),
    (("fred_", "world_bank", "country_cpi", "gov_data", "eia_"), "data"),
    (("companies_house", "moodys_orbis", "address_", "geocod"), "kyc"),
    (("twilio", "zapier", "connector_", "browser_"), "integration"),
    (("plotly_", "mermaid_", "translation", "narrate"), "multimodal"),
    (("approval_gate", "sub_pipeline", "invoke_agent"), "pipeline"),
    (("decision_",), "decisions"),
    (("source_",), "sources"),
)


def _guess_category(slug: str) -> str:
    for prefixes, category in _CATEGORY_HINTS:
        if slug.startswith(prefixes):
            return category
    return "core"


def _load_runtime_schemas() -> dict[str, dict[str, Any]]:
    """Return {tool_name: input_schema} pulled from the runtime registry."""
    global _RUNTIME_SCHEMAS
    if _RUNTIME_SCHEMAS is not None:
        return _RUNTIME_SCHEMAS
    out: dict[str, dict[str, Any]] = {}
    try:
        from engine.agent_executor import (  # type: ignore
            _CONTEXT_TOOL_FACTORIES,
            _TOOL_CLASSES,
            _ensure_tool_classes,
        )

        _ensure_tool_classes()
        for name, cls in _TOOL_CLASSES.items():
            schema = getattr(cls, "input_schema", None)
            if isinstance(schema, dict):
                out[name] = schema
        for name, cls in _CONTEXT_TOOL_FACTORIES.items():
            schema = getattr(cls, "input_schema", None)
            if isinstance(schema, dict):
                out[name] = schema
    except Exception as e:  # pragma: no cover — surfaces in logs at startup
        logger.warning("could not load runtime tool schemas: %s", e)

    # Tools that the executor instantiates lazily (Atlas + KB + portfolio
    # need execution context — they're not in _TOOL_CLASSES). Pull their
    # schemas straight off the class so the catalogue still publishes a
    # contract.
    _LAZY_MODULES = LAZY_TOOL_MODULES
    import importlib

    for mod_path, class_names in _LAZY_MODULES:
        try:
            mod = importlib.import_module(mod_path)
        except Exception as e:
            logger.debug("lazy schema lookup: cannot import %s: %s", mod_path, e)
            continue
        for cn in class_names:
            cls = getattr(mod, cn, None)
            if cls is None:
                continue
            name = getattr(cls, "name", None)
            schema = getattr(cls, "input_schema", None)
            if name and isinstance(schema, dict):
                out.setdefault(name, schema)
    _RUNTIME_SCHEMAS = out
    return out


# Complete tool catalog with descriptions and categories
TOOL_CATALOG = [
    {
        "id": "calculator",
        "name": "Calculator",
        "description": "Evaluate mathematical expressions and formulas. Always invoke this tool for any arithmetic, never compute mentally.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The arithmetic expression to evaluate, e.g. '17*23 + 9' or 'sqrt(144)'.",
                }
            },
            "required": ["expression"],
        },
    },
    {
        "id": "current_time",
        "name": "Current Time",
        "description": "Get current date and time in UTC or any IANA timezone. Always invoke when the user asks about time, date, or scheduling.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name (e.g. 'UTC', 'Europe/London', 'America/New_York'). Defaults to 'UTC'.",
                    "default": "UTC",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'iso' (2026-05-02T14:30:00Z), 'human' (May 2, 2026 14:30 UTC), or 'unix'.",
                    "default": "iso",
                },
            },
            "required": [],
        },
    },
    {
        "id": "web_search",
        "name": "Web Search",
        "description": "Search the internet for real-time information using DuckDuckGo. Use when the user asks about recent events, current data, or anything not in the model's training cutoff.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (1–10).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "id": "file_reader",
        "name": "File Reader",
        "description": "Read and extract text from a PDF, DOCX, TXT, or CSV file. Pass either an inline `text` payload (which is auto-saved to a temp file) OR a `path` to an existing file.",
        "category": "data",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Filesystem path to the file. If omitted, `text` must be supplied.",
                },
                "text": {
                    "type": "string",
                    "description": "Inline text content. The tool will create a temp file and read from it. Useful when the LLM is given a document inline rather than as an attachment.",
                },
                "format": {
                    "type": "string",
                    "description": "File format hint: 'pdf', 'docx', 'txt', 'csv'. Auto-detected from extension if not given.",
                    "enum": ["pdf", "docx", "txt", "csv"],
                },
            },
            "required": [],
        },
    },
    {
        "id": "csv_analyzer",
        "name": "CSV Analyzer",
        "description": "Parse and analyze CSV data — column stats, row counts, data types, missing-value summary. Pass inline CSV content via `text` or a `path` to an existing file.",
        "category": "data",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to a CSV file."},
                "text": {
                    "type": "string",
                    "description": "Inline CSV content (lines separated by \\n). Auto-saved to a temp file before analysis.",
                },
                "delimiter": {
                    "type": "string",
                    "description": "Field delimiter, default ','.",
                    "default": ",",
                },
            },
            "required": [],
        },
    },
    {
        "id": "spreadsheet_analyzer",
        "name": "Spreadsheet Analyzer",
        "description": "Read and analyze Excel workbooks with multi-sheet support",
        "category": "data",
    },
    {
        "id": "json_transformer",
        "name": "JSON Transformer",
        "description": "Reshape, filter, and transform JSON data structures",
        "category": "data",
    },
    {
        "id": "regex_extractor",
        "name": "Regex Extractor",
        "description": "Extract patterns from text using regular expressions",
        "category": "data",
    },
    {
        "id": "text_analyzer",
        "name": "Text Analyzer",
        "description": "NLP analysis — sentiment, entities, keywords, summarization",
        "category": "data",
    },
    {
        "id": "code_executor",
        "name": "Code Executor",
        "description": "Execute Python code in a sandboxed environment with numpy/pandas",
        "category": "core",
    },
    {
        "id": "llm_call",
        "name": "LLM Call",
        "description": "Call another LLM model as a sub-step with custom prompt",
        "category": "pipeline",
    },
    {
        "id": "email_sender",
        "name": "Email Sender",
        "description": "Send emails via SMTP with HTML support",
        "category": "integration",
    },
    {
        "id": "http_client",
        "name": "HTTP Client",
        "description": "Make HTTP requests to any external API (GET, POST, PUT, DELETE)",
        "category": "integration",
    },
    {
        "id": "data_merger",
        "name": "Data Merger",
        "description": "Merge and combine outputs from parallel pipeline steps",
        "category": "pipeline",
    },
    {
        "id": "data_exporter",
        "name": "Data Exporter",
        "description": "Export results to S3, webhooks, files, or external APIs",
        "category": "integration",
    },
    {
        "id": "database_query",
        "name": "Database Query",
        "description": "Execute read-only SQL queries against PostgreSQL databases",
        "category": "data",
    },
    {
        "id": "database_writer",
        "name": "Database Writer",
        "description": "Insert or upsert data into PostgreSQL tables (af_ prefix only)",
        "category": "data",
    },
    {
        "id": "cloud_storage",
        "name": "Cloud Storage",
        "description": "Read and write to S3, Google Cloud Storage, or Azure Blob",
        "category": "integration",
    },
    {
        "id": "github_tool",
        "name": "GitHub Tool",
        "description": "Search repos, read files, list PRs/issues, create issues via GitHub API",
        "category": "integration",
    },
    {
        "id": "image_analyzer",
        "name": "Image Analyzer",
        "description": "Analyze images using vision models — OCR, object detection, description",
        "category": "multimodal",
    },
    {
        "id": "schema_validator",
        "name": "Schema Validator",
        "description": "Validate JSON data against JSON Schema definitions",
        "category": "data",
    },
    {
        "id": "structured_analyzer",
        "name": "Structured Analyzer",
        "description": "LLM-powered structured extraction — security audit, code quality, architecture analysis",
        "category": "enterprise",
    },
    {
        "id": "memory_store",
        "name": "Memory Store",
        "description": "Store facts, procedures, or episodes in persistent agent memory",
        "category": "enterprise",
    },
    {
        "id": "memory_recall",
        "name": "Memory Recall",
        "description": "Retrieve previously stored memories by key or semantic search",
        "category": "enterprise",
    },
    {
        "id": "memory_forget",
        "name": "Memory Forget",
        "description": "Delete specific memories from agent's persistent store",
        "category": "enterprise",
    },
    {
        "id": "human_approval",
        "name": "Human Approval",
        "description": "Pause execution and wait for human-in-the-loop approval before proceeding",
        "category": "enterprise",
    },
    {
        "id": "agent_step",
        "name": "Agent Step",
        "description": "Delegate a sub-task to another agent with its own system prompt and tools",
        "category": "pipeline",
    },
    {
        "id": "invoke_agent",
        "name": "Invoke Agent",
        "description": "Fire another agent by slug and wait for (or poll) its result. Use for fan-out meta-agents that compose specialists.",
        "category": "pipeline",
    },
    {
        "id": "recall_trajectory",
        "name": "Recall Trajectory",
        "description": "Search prior agent runs by intent/term overlap and recall what worked. Returns a list of past trajectories with success signals.",
        "category": "pipeline",
    },
    {
        "id": "narrate",
        "name": "Narrate",
        "description": "Publish a one-line progress event to the trader-facing narration feed (tone: step | finding | alert | done). Lets meta-agents commentate their plan + findings in real time.",
        "category": "pipeline",
    },
    {
        "id": "financial_calculator",
        "name": "Financial Calculator",
        "description": "Calculate LCOE, IRR, NPV, VaR, debt sizing, and amortization schedules",
        "category": "finance",
    },
    {
        "id": "risk_analyzer",
        "name": "Risk Analyzer",
        "description": "Score and categorize risks with Monte Carlo simulation and sensitivity analysis",
        "category": "finance",
    },
    {
        "id": "market_data",
        "name": "Market Data",
        "description": "Fetch real-time and historical market data — energy prices, commodities, FX rates",
        "category": "finance",
    },
    {
        "id": "unit_converter",
        "name": "Unit Converter",
        "description": "Convert between units — energy (MWh/kWh), currency, weight, volume, temperature",
        "category": "core",
    },
    {
        "id": "date_calculator",
        "name": "Date Calculator",
        "description": "Date arithmetic — business days, weekdays between dates, holiday-aware scheduling",
        "category": "core",
    },
    {
        "id": "document_extractor",
        "name": "Document Extractor",
        "description": "Extract structured data from documents — tables, key-value pairs, form fields",
        "category": "data",
    },
    {
        "id": "presentation_analyzer",
        "name": "Presentation Analyzer",
        "description": "Read and analyze PowerPoint slides — text, images, speaker notes",
        "category": "data",
    },
    {
        "id": "integration_hub",
        "name": "Integration Hub",
        "description": "Connect to 20+ services: Slack, Teams, Salesforce, HubSpot, Jira, Notion, etc.",
        "category": "integration",
    },
    {
        "id": "speech_to_text",
        "name": "Speech to Text",
        "description": "Transcribe audio files using Whisper — supports 50+ languages",
        "category": "multimodal",
    },
    {
        "id": "text_to_speech",
        "name": "Text to Speech",
        "description": "Generate natural speech audio from text using neural TTS",
        "category": "multimodal",
    },
    {
        "id": "file_system",
        "name": "File System",
        "description": "List directories, read files, glob patterns — recursive traversal with stats",
        "category": "data",
    },
    {
        "id": "pii_redactor",
        "name": "PII Redactor",
        "description": "Detect and redact PII (SSN, credit cards, emails, phone numbers, IPs, dates of birth) from text",
        "category": "data",
    },
    {
        "id": "time_series_analyzer",
        "name": "Time Series Analyzer",
        "description": "Analyze time-series data: moving averages, anomaly detection, linear forecasting, and correlation",
        "category": "data",
    },
    {
        "id": "event_buffer",
        "name": "Event Buffer",
        "description": "Read and consume buffered events from the platform event queue (Redis-backed)",
        "category": "integration",
    },
    {
        "id": "redis_stream_consumer",
        "name": "Redis Stream Consumer",
        "description": "Consume messages from Redis Streams with consumer group support",
        "category": "integration",
    },
    {
        "id": "redis_stream_publisher",
        "name": "Redis Stream Publisher",
        "description": "Publish messages to Redis Streams for inter-agent and event-driven communication",
        "category": "integration",
    },
    {
        "id": "kafka_consumer",
        "name": "Kafka Consumer",
        "description": "Consume messages from Apache Kafka topics for high-throughput event streaming",
        "category": "integration",
    },
    # ML / Models
    {
        "id": "ml_model",
        "name": "ML Model",
        "description": "Run inference on registered ML models (sklearn, PyTorch, ONNX, XGBoost) — list_models / predict / get_model_info operations",
        "category": "ml",
    },
    {
        "id": "ml_model_register",
        "name": "ML Model Register",
        "description": "Register a model file made earlier in the run as a new ML model version, from the workspace's export folder or as base64",
        "category": "ml",
    },
    # Code Runners
    {
        "id": "code_asset",
        "name": "Code Asset",
        "description": "Execute a registered code asset (user-uploaded zip or git repo) with a JSON input — any Python/Node/Go/Rust/Ruby/Java version, runs in sandboxed_job isolation",
        "category": "code",
    },
    # Meeting primitives
    {
        "id": "meeting_join",
        "name": "Meeting Join",
        "description": "Join a LiveKit/Teams/Zoom meeting on the user's behalf — reads authorized scope from Redis",
        "category": "meeting",
    },
    {
        "id": "meeting_listen",
        "name": "Meeting Listen",
        "description": "Stream audio from the meeting; VAD-chunked Whisper STT with early-exit on addressed utterance",
        "category": "meeting",
    },
    {
        "id": "meeting_speak",
        "name": "Meeting Speak",
        "description": "Speak text into the meeting (OpenAI or ElevenLabs TTS); hard consent gate for cloned voices",
        "category": "meeting",
    },
    {
        "id": "meeting_post_chat",
        "name": "Meeting Post Chat",
        "description": "Post a message to the meeting chat/data channel",
        "category": "meeting",
    },
    {
        "id": "meeting_leave",
        "name": "Meeting Leave",
        "description": "Leave the meeting cleanly and persist a summary to the decision log",
        "category": "meeting",
    },
    {
        "id": "scope_gate",
        "name": "Scope Gate",
        "description": "Classify a meeting question as answer/defer/decline against the declared allow-list",
        "category": "meeting",
    },
    {
        "id": "defer_to_human",
        "name": "Defer to Human",
        "description": "Route a question back to the user's inbox; blocks up to hold_seconds for their reply",
        "category": "meeting",
    },
    {
        "id": "persona_rag",
        "name": "Persona RAG",
        "description": "Ring-fenced retrieval from the user's persona KB with hard tenant/user/scope filter",
        "category": "meeting",
    },
    # Sandbox
    {
        "id": "sandboxed_job",
        "name": "Sandboxed Job",
        "description": "Run long-lived code in a sandboxed k8s Job (image allow-list, timeouts)",
        "category": "enterprise",
    },
    # KYC / AML
    {
        "id": "sanctions_screening",
        "name": "Sanctions Screening",
        "description": "Screen a person/entity against OFAC SDN, OFAC Consolidated, EU, UN SC, UK HMT, Canada OSFI, Australia DFAT, Switzerland SECO sanctions lists — fuzzy + AKA match, returns per-list hits with confidence and risk grade",
        "category": "kyc",
    },
    {
        "id": "pep_screening",
        "name": "PEP Screening",
        "description": "Screen against Politically Exposed Persons lists — OpenSanctions (900k+ entries), Wikidata SPARQL, per-country parliamentary rosters; classifies Domestic/Foreign/Intl Org/Family/Associate/Former PEP",
        "category": "kyc",
    },
    {
        "id": "adverse_media",
        "name": "Adverse Media",
        "description": "Negative-news screening fused from Tavily, GDELT, Google News RSS, and direct Reuters/FT scrapes — auto-categorised by FATF risk type (bribery, ML, fraud, sanctions evasion, etc.) with source-tier weights",
        "category": "kyc",
    },
    {
        "id": "ubo_discovery",
        "name": "UBO Discovery",
        "description": "Walk corporate ownership tree to identify Ultimate Beneficial Owners — fuses GLEIF, OpenCorporates, UK PSC, Polish KRS, plus other national registers; configurable ≥20% threshold (AMLD-6) or ≥25% (FinCEN CTA)",
        "category": "kyc",
    },
    {
        "id": "country_risk_index",
        "name": "Country Risk Index",
        "description": "Fused country-risk signals — TI CPI rank, Basel AML Index, FATF grey/black lists, EU tax non-cooperative list, OFAC country programs, World Bank WGI percentiles; outputs MET-style Indicator I score",
        "category": "kyc",
    },
    {
        "id": "legal_existence_verifier",
        "name": "Legal Existence Verifier",
        "description": "Verify a company is legally registered and in good standing — cross-references GLEIF, OpenCorporates, UK Companies House; auto-detects shell patterns, dissolved/struck-off, LEI lapses",
        "category": "kyc",
    },
    {
        "id": "kyc_scorer",
        "name": "KYC Scorer",
        "description": "Deterministic aggregator — takes CPI rank + annual notional + industry + signal flags, outputs MET-style Indicator I/II/III scores, aggregated score, and Simplified/Standard/Enhanced check type",
        "category": "kyc",
    },
    {
        "id": "regulatory_enforcement",
        "name": "Regulatory Enforcement",
        "description": "Primary-source enforcement & litigation lookup — SEC EDGAR, DOJ, FCA, BaFin, ASIC, CourtListener, BAILII; extracts fine amounts, action types, and direct source URLs",
        "category": "kyc",
    },
    {
        "id": "entso_e",
        "name": "ENTSO-E",
        "description": "EU electricity market: day-ahead prices, generation, forecasts, cross-border flows (ENTSO-E Transparency Platform)",
        "category": "finance",
    },
    {
        "id": "ember_climate",
        "name": "Ember Climate",
        "description": "UK electricity + EU ETS carbon prices, renewable generation mix, grid decarbonisation data",
        "category": "finance",
    },
    {
        "id": "ecb_rates",
        "name": "ECB Rates",
        "description": "European Central Bank — FX reference rates, euro-area yields, HICP inflation series",
        "category": "finance",
    },
    {
        "id": "yahoo_finance",
        "name": "Yahoo Finance",
        "description": (
            "Universal Yahoo Finance reader — one tool for every instrument. "
            "Actions: stock_price, company_info, earnings, dividends, "
            "economic_indicator (FRED), commodity_future, fx_rate, "
            "list_aliases. Friendly aliases (gold, silver, platinum, "
            "palladium, copper, wti, brent, natgas_henry_hub, natgas_ttf, "
            "corn, wheat, usdcny, eurusd, vix, sp500 ...) map to Yahoo "
            "symbols. Save (action, args) bundles as named presets in "
            "/admin/tool-presets so any agent or app can pull the same "
            "configured feed by preset slug."
        ),
        "category": "finance",
    },
    {
        "id": "options_data",
        "name": "Options Market Data",
        "description": "Listed options-market signals: at-the-money implied volatility, 25-delta risk reversal (call IV minus put IV — captures skew), put/call open-interest ratio, term-structure slope, and a four-bucket regime label (calm / nervous / skewed-up / skewed-down). Works on any ticker with a Yahoo option chain — futures (CL=F, NG=F, GC=F), indices (^SPX, ^VIX), equities (AAPL, MSFT), FX (EURUSD=X). Three actions: snapshot, term_structure, regime.",
        "category": "finance",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["snapshot", "term_structure", "regime"],
                    "description": "snapshot: ATM IV + skew + OI for one expiry. term_structure: front three expiries' IV + slope. regime: calm/nervous/skewed-up/skewed-down label.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Yahoo ticker. Futures with =F (CL=F crude, NG=F natural gas), indices with ^ (^SPX, ^VIX), equities plain (AAPL), FX with =X (EURUSD=X).",
                },
                "expiry_index": {
                    "type": "integer",
                    "default": 0,
                    "description": "For action=snapshot only. 0 = front month.",
                },
            },
            "required": ["action", "symbol"],
        },
    },
    {
        "id": "eia_open_data",
        "name": "EIA Open Data",
        "description": "US Energy Information Administration time series — Mont Belvieu propane, WTI/Brent spot, Henry Hub gas, US LPG exports. Real, regulator-published, every value cites a series id.",
        "category": "finance",
        "input_schema": {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "description": "Shortcut id (PROPANE_USGC_MB, WTI_SPOT, BRENT_SPOT, HH_NATGAS, US_LPG_EXPORTS, PROPANE_USA) or raw EIA v2 path.",
                },
                "start": {
                    "type": "string",
                    "description": "Optional ISO date (YYYY-MM-DD)",
                },
                "end": {
                    "type": "string",
                    "description": "Optional ISO date (YYYY-MM-DD)",
                },
                "limit": {
                    "type": "integer",
                    "default": 52,
                    "description": "Max data points to return",
                },
            },
            "required": ["series_id"],
        },
    },
    {
        "id": "open_meteo",
        "name": "Open-Meteo Weather",
        "description": "Free weather + marine forecasts (no API key) for any lat/lon or pre-mapped energy hubs (Houston, Rotterdam, Singapore, Chiba, Ras Tanura, etc.). Mode='atmosphere' for wind/temp/precip; mode='marine' for wave height + swell + SST.",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Hub shortcut id or empty if lat/lon set",
                },
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "mode": {
                    "type": "string",
                    "enum": ["atmosphere", "marine"],
                    "default": "atmosphere",
                },
                "horizon_days": {
                    "type": "integer",
                    "default": 7,
                    "minimum": 1,
                    "maximum": 16,
                },
            },
            "required": [],
        },
    },
    {
        "id": "ais_stream",
        "name": "AIS Live Vessels",
        "description": "Sample real-time global vessel positions from AISStream.io. Every MMSI in the response is a real ship that can be looked up on VesselFinder. Filter by bounding box and ship-type code (84 = LPG tanker). Needs AISSTREAM_API_KEY, set under Admin -> Tool Configuration (free registration at aisstream.io).",
        "category": "core",
        "input_schema": {
            "type": "object",
            "properties": {
                "bounding_boxes": {
                    "type": "array",
                    "description": "[[sw_lat, sw_lon], [ne_lat, ne_lon]] pairs",
                    "items": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                    },
                },
                "ship_types": {"type": "array", "items": {"type": "integer"}},
                "max_messages": {
                    "type": "integer",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 200,
                },
                "duration_seconds": {
                    "type": "number",
                    "default": 8.0,
                    "minimum": 1.0,
                    "maximum": 30.0,
                },
            },
            "required": [],
        },
    },
    {
        "id": "bunker_fuel",
        "name": "Bunker Fuel + Freight Estimate",
        "description": "Public bunker-fuel reference (VLSFO at Houston/Rotterdam/Singapore/Fujairah/Tokyo/New York) plus a corridor freight-rate ESTIMATE (bunker-derived, not Baltic-assessed). Pass origin+destination to get a $/MT freight quote for a typical VLGC voyage. Production deployments swap to a Baltic Exchange feed for assessed rates.",
        "category": "finance",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Houston / Rotterdam / Singapore / Fujairah / Tokyo / New York",
                },
                "destination": {"type": "string", "description": "Same set"},
            },
            "required": [],
        },
    },
    {
        "id": "vessel_specs",
        "name": "Vessel Specs + Density",
        "description": "Vessel-class registry (VLGC/MGC/LGC/SGC for LPG, VLCC/Suezmax/Aframax/LR2/LR1/MR2/MR1/Handysize for CPP) plus product density table (propane/butane/ammonia/naphtha/gasoline/jet/ULSD/gasoil/fuel-oil/crude/methanol). Five actions: vessel (spec card), density (kg/L for product), convert (m^3<->MT or $/MT<->$/bbl), capacity (MT a class lifts for a named product), list (every vessel or product). Single source of truth for freight math; every freight-touching agent should pull from here.",
        "category": "finance",
    },
    {
        "id": "refined_products_forwards",
        "name": "Refined Products Forwards + Cracks",
        "description": "Refined-products forward curves + crack spreads from Yahoo continuous futures. Pulls RB=F gasoline, HO=F ULSD/heating oil, CL=F WTI, BZ=F Brent, NG=F Henry Hub. Three actions: curve (front-month settle), crack_spread (3-2-1 or product-vs-crude in $/bbl), history (N days of daily settles). No API key required.",
        "category": "finance",
    },
    {
        "id": "freight_worldscale",
        "name": "Worldscale Freight (CPP)",
        "description": "Worldscale freight calculator for clean-products tankers. Knows the 2025 flat-rate schedule for the main TC routes (TC1 MEG->Japan naphtha, TC2 Cont->USAC gasoline, TC5/6/7/14/17). Computes freight in $/MT as ws_points/100 * flat_rate. Three actions: route (look up flat rate + freight), voyage_cost (full $ given cargo size), list.",
        "category": "finance",
    },
    {
        "id": "freight_baltic_blpg",
        "name": "Baltic BLPG (LPG)",
        "description": "Baltic Exchange BLPG indices for LPG freight: BLPG1 (Ras Tanura->Chiba), BLPG2 (Houston->Flushing), BLPG3 (Houston->Chiba via Panama) in $/MT propane VLGC. Curated Q1-2026 OPEC-MOMR levels; production sets BALTIC_API_KEY+BALTIC_API_URL env to swap to the live subscription feed. Two actions: route (single BLPG mid/low/high), all (all three side-by-side).",
        "category": "finance",
    },
    {
        "id": "port_constraints",
        "name": "Port Constraints (UN/LOCODE)",
        "description": "UN/LOCODE port database with vessel berth-compatibility checks. Knows ~25 liquid-bulk ports (US Gulf, USAC, NW Europe, MED, MEG, Far East, India, Africa, Brazil) plus Suez/Panama canal constraints. Three actions: port (full spec card), list (enumerate all), check (vessel_class + locode -> compatible/borderline/incompatible with breakdown of draught, LOA, beam, air-draught, product handling).",
        "category": "finance",
    },
    {
        "id": "tavily_search",
        "name": "Tavily Search",
        "description": "Real-time web search tuned for research agents — recency bias, source ranking, structured snippets",
        "category": "core",
    },
    {
        "id": "news_feed",
        "name": "News Feed",
        "description": "Curated news from GDELT, Reuters, Bloomberg, Financial Times — category-tagged and deduplicated",
        "category": "core",
    },
    {
        "id": "academic_search",
        "name": "Academic Search",
        "description": "Search ArXiv, Semantic Scholar, Google Scholar for academic papers with citation graph",
        "category": "core",
    },
    {
        "id": "knowledge_search",
        "name": "Knowledge Search",
        "description": "Hybrid vector + graph search over uploaded documents via Cognify (RAG with entity linking)",
        "category": "enterprise",
    },
    {
        "id": "graph_explorer",
        "name": "Graph Explorer",
        "description": "Direct Neo4j traversal — entities, relationships, shortest paths, community detection",
        "category": "enterprise",
    },
    {
        "id": "atlas_describe",
        "name": "Atlas — Describe",
        "description": "Summarise an Atlas graph (counts by kind, top edge labels, most-connected concepts) so the agent has a map of the domain before drilling in.",
        "category": "enterprise",
    },
    {
        "id": "atlas_query",
        "name": "Atlas — Pattern Query",
        "description": "Pattern-match nodes in an Atlas graph by label-like + kind. Returns structured rows; the typed alternative to vector search.",
        "category": "enterprise",
    },
    {
        "id": "atlas_traverse",
        "name": "Atlas — Traverse",
        "description": "Return the 1-hop neighbourhood of a node in an Atlas graph (incoming + outgoing edges). Use after locating a concept to walk to related concepts.",
        "category": "enterprise",
    },
    {
        "id": "atlas_search_grounded",
        "name": "Atlas — Grounded Search",
        "description": "Find KB documents bound to concepts near a target term in the ontology. Better than vector-only when chunks must be tied to a typed concept.",
        "category": "enterprise",
    },
    {
        "id": "atlas_as_of",
        "name": "Atlas — As-Of",
        "description": "Show an Atlas graph as it stood at a past moment, from the newest saved snapshot at or before that time, or the live graph when nothing changed since. For audit and 'what did the ontology say on date X' questions.",
        "category": "enterprise",
    },
    {
        "id": "graph_builder",
        "name": "Graph Builder",
        "description": "Build a structured DAG from nodes + edges with cycle detection and topological layout hints",
        "category": "enterprise",
    },
    {
        "id": "structured_extractor",
        "name": "Structured Extractor",
        "description": "Schema-driven extraction from long documents into strict JSON — generic structured-output tool for any standalone app.",
        "category": "data",
    },
    {
        "id": "document_parser",
        "name": "Document Parser",
        "description": "Lightweight document parser (DOC/DOCX/TXT/PDF) complementing document_extractor with mixed-format support",
        "category": "data",
    },
    {
        "id": "schema_portfolio_tool",
        "name": "Portfolio — Schema-Driven",
        "description": "Schema-driven portfolio tool for PPA / gas / tolling contracts. Reads its schema from portfolio_schemas at runtime so the same tool powers energy desks and any standalone app that registers a schema.",
        "category": "finance",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "list_records | get_record | search | get_summary | get_related | compare_field | discover_fields | query_fields",
                },
                "record_id": {"type": "string"},
                "query": {"type": "string"},
                "table_name": {"type": "string"},
                "section": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["operation"],
        },
    },
    {
        "id": "llm_route",
        "name": "LLM Router",
        "description": "Pipeline step that routes the payload to different downstream nodes based on an LLM classification",
        "category": "pipeline",
    },
    {
        "id": "sentiment_analyzer",
        "name": "Sentiment Analyzer",
        "description": "News / social sentiment scoring for markets, counterparties, or topics — aggregates multiple sources with source-tier weights",
        "category": "data",
    },
    {
        "id": "scenario_planner",
        "name": "Scenario Planner",
        "description": "Builds decision trees of scenarios with probabilities and impact — used by market_simulator + OracleNet",
        "category": "enterprise",
    },
    {
        "id": "weather_simulator",
        "name": "Weather Simulator",
        "description": "Synthetic weather scenario generator for energy / tourism simulations (wind, solar irradiance, temperature, precipitation)",
        "category": "enterprise",
    },
    {
        "id": "api_connector",
        "name": "API Connector",
        "description": "Typed wrapper around http_client with retry, auth (OAuth2/APIKey/Basic), and response schema validation",
        "category": "integration",
    },
    {
        "id": "credit_risk",
        "name": "Credit Risk",
        "description": "Counterparty credit-risk scoring — Altman Z, financial ratios, PD model, public rating lookup",
        "category": "finance",
    },
]


@router.get("")
async def list_tools(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return metadata for all available built-in tools."""
    runtime_schemas = _load_runtime_schemas()
    # Declarations are static, status is read from the resolver per request.
    from app.services import tool_config as _tc

    await _tc.refresh()
    out: list[dict[str, Any]] = []
    for entry in TOOL_CATALOG:
        merged = dict(entry)
        merged["config"] = _tc.tool_config_for(merged["id"], tenant_id=user.tenant_id)
        if not merged.get("input_schema"):
            schema = runtime_schemas.get(merged["id"])
            if schema:
                merged["input_schema"] = schema
        out.append(merged)

    # TOOL_CATALOG above is hand-maintained, so it drifts behind the runtime
    # every time a tool ships without a catalogue entry — and a tool absent
    # here is invisible in the agent AND pipeline designers even though the
    # executor can run it. An audit found 42 such tools (the whole v1.1
    # streaming set, vector_search, browser_automation, plotly_chart, the
    # ratings/filings block, approval_gate/connector_call/sub_pipeline...).
    # Append anything the runtime registers that the catalogue missed, so the
    # designer is complete by construction rather than by diligence.
    known = {e["id"] for e in out}
    for slug in _runtime_tool_slugs():
        if slug in known:
            continue
        out.append(
            {
                "id": slug,
                "name": slug.replace("_", " ").title(),
                "description": (
                    _runtime_tool_description(slug)
                    or f"Runtime tool `{slug}` (no catalogue entry yet)."
                ),
                "category": _guess_category(slug),
                "input_schema": runtime_schemas.get(slug) or {},
                "uncatalogued": True,
                "config": _tc.tool_config_for(slug, tenant_id=user.tenant_id),
            }
        )
    out = [e for e in out if e["id"] != "schema_portfolio_tool"]
    out.extend(await _portfolio_tool_entries(db, user.tenant_id))
    return success(out, meta={"count": len(out)})


async def _portfolio_tool_entries(db: AsyncSession, tenant_id: Any) -> list[dict]:
    """One palette entry per active portfolio schema, the generic tool has no schema to read."""
    try:
        from sqlalchemy import select

        from models.portfolio_schema import PortfolioSchema

        rows = (
            (
                await db.execute(
                    select(PortfolioSchema).where(
                        PortfolioSchema.tenant_id == tenant_id,
                        PortfolioSchema.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
    except Exception as exc:
        logger.debug("portfolio schemas not listed: %s", exc)
        return []
    out = []
    for s in rows:
        nouns = s.record_noun_plural or "records"
        out.append(
            {
                "id": f"portfolio_{s.domain_name}",
                "name": f"Portfolio: {s.label}",
                "description": (
                    s.description
                    or f"Query the {s.label} portfolio: list, search, summarise and compare {nouns}."
                ),
                "category": "data",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "list_records",
                                "get_record",
                                "search",
                                "get_summary",
                                "get_related",
                                "compare_field",
                            ],
                        },
                        "record_id": {"type": "string"},
                        "query": {"type": "string"},
                        "table_name": {"type": "string"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["operation"],
                },
                "portfolio_schema_id": str(s.id),
            }
        )
    return out


@router.post("/{tool_slug}/execute")
async def execute_tool(
    tool_slug: str,
    body: dict | None = None,
    request: Request = None,  # type: ignore[assignment]
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Direct tool execution. Bypasses the agent loop, gated by Redis.

    Every call passes through ``tool_gate.acquire()`` which enforces the
    admin-configured cache, semaphore, rate-limit, circuit breaker and
    daily budget. Tools are instantiated per-call (no shared state) so
    callers do not contend. CPU-heavy work should be routed to the
    runtime pool by setting ``pool='runtime'`` on the tool's config; the
    api-pod path is appropriate for I/O-bound or sub-second tools.
    """
    import time

    from app.core import tool_gate

    started = time.time()
    arguments = (body or {}).get("arguments") or {}
    config = (body or {}).get("config") or {}
    tenant_id = str(user.tenant_id)

    # Gate: cache lookup, semaphore, rate limit, circuit breaker
    decision = await tool_gate.acquire(tool_slug, tenant_id, arguments, db)
    if not decision.allowed:
        await _log_invocation(
            db,
            user,
            tool_slug,
            body,
            None,
            started,
            status="error",
            error_message=decision.reason,
        )
        return error(f"{tool_slug}: {decision.reason}", 429)
    if decision.cached and decision.cached_value:
        await _log_invocation(
            db,
            user,
            tool_slug,
            body,
            None,
            started,
            status="ok",
            cache_hit=True,
        )
        return success(
            {
                "tool_slug": tool_slug,
                "content": decision.cached_value.get("content"),
                "metadata": {
                    **(decision.cached_value.get("metadata") or {}),
                    "cache_hit": True,
                },
                "is_error": False,
            }
        )

    try:
        from engine.agent_executor import get_tool_class

        cls = get_tool_class(tool_slug)
    except Exception as e:
        await tool_gate.release(decision, tool_slug, tenant_id, ok=False)
        logger.exception("registry lookup failed: %s", e)
        return error(f"registry lookup failed: {e}", 500)
    if cls is None:
        await tool_gate.release(decision, tool_slug, tenant_id, ok=False)
        await _log_invocation(
            db,
            user,
            tool_slug,
            body,
            None,
            started,
            status="error",
            error_message=f"unknown tool: {tool_slug}",
        )
        return error(f"unknown tool: {tool_slug}", 404)

    # Pool routing — runtime pool dispatches via Redis Streams to worker pods.
    # Falls back to inline if the worker side isn't responding.
    if decision.config and decision.config.pool == "runtime":
        try:
            from app.core import tool_worker_dispatch

            worker_payload = await tool_worker_dispatch.enqueue_and_wait(
                tool_slug,
                tenant_id,
                arguments,
                config,
                timeout_s=float(decision.config.timeout_seconds or 30),
            )
            is_error = bool(worker_payload.get("is_error"))
            payload = {
                "content": worker_payload.get("content"),
                "metadata": {
                    **(worker_payload.get("metadata") or {}),
                    "via_pool": "runtime",
                    "worker": worker_payload.get("worker"),
                },
            }
            await tool_gate.release(
                decision, tool_slug, tenant_id, ok=not is_error, result_payload=payload
            )
            await _log_invocation(
                db,
                user,
                tool_slug,
                body,
                type(
                    "R",
                    (),
                    {
                        "content": payload["content"],
                        "metadata": payload["metadata"],
                        "is_error": is_error,
                    },
                )(),
                started,
                status="ok" if not is_error else "error",
            )
            return success({"tool_slug": tool_slug, **payload, "is_error": is_error})
        except Exception as e:
            logger.warning("runtime-pool dispatch failed (%s) — falling back inline", e)

    # Try the richest constructor signature first; fall back through
    # progressively narrower ones so tools that accept different kw sets
    # (basic tools vs context tools like ml_model / code_asset) all work.
    import inspect

    try:
        sig = inspect.signature(cls.__init__)
        accepted = set(sig.parameters.keys()) - {"self"}
    except (TypeError, ValueError):
        accepted = set()

    _kb_ids = arguments.get("kb_ids") if isinstance(arguments, dict) else None
    _kb_id = arguments.get("kb_id") if isinstance(arguments, dict) else None
    if _kb_id and not _kb_ids:
        _kb_ids = [_kb_id]
    base_kwargs = {
        "tenant_id": tenant_id,
        "execution_id": "",
        "agent_id": "",
        "api_key": "",
        "api_base": "",
        "db_url": os.environ.get("DATABASE_URL", ""),
        "kb_ids": _kb_ids or [],
        "kb_id": _kb_id or "",
    }
    # Pass only kwargs the constructor actually accepts.
    init_kwargs = {
        k: v for k, v in base_kwargs.items() if not accepted or k in accepted
    }
    # Layer in caller-supplied config last so it can override.
    init_kwargs.update(
        {k: v for k, v in (config or {}).items() if not accepted or k in accepted}
    )

    # Some tools raise ValueError from __init__, not TypeError; catching only
    # TypeError let those escape as a bare 500.
    tool = None
    construct_error: Exception | None = None
    for attempt_kwargs in (init_kwargs, {"tenant_id": tenant_id}, {}):
        try:
            tool = cls(**attempt_kwargs)
            break
        except (TypeError, ValueError) as e:
            if construct_error is None:
                construct_error = e
    if tool is None:
        await tool_gate.release(decision, tool_slug, tenant_id, ok=False)
        await _log_invocation(
            db,
            user,
            tool_slug,
            body,
            None,
            started,
            status="error",
            error_message=str(construct_error),
        )
        # A tool that cannot be built from this request is a bad request, not a
        # server fault.
        return error(
            f"tool {tool_slug} could not be initialised: {construct_error}",
            400,
            "tool_not_configurable",
        )

    tool_started_at = time.time()
    try:
        result = await tool.execute(arguments)
    except asyncio.CancelledError:
        # the caller went away, give the slot back before the cancel unwinds
        await asyncio.shield(
            tool_gate.release(decision, tool_slug, tenant_id, ok=False)
        )
        raise
    except Exception as e:
        await tool_gate.release(decision, tool_slug, tenant_id, ok=False)
        logger.exception("direct tool execute failed: %s", tool_slug)
        try:
            from app.core.telemetry import (
                tool_calls_total,
                tool_execution_duration_seconds,
            )

            tool_calls_total.labels(tool_name=tool_slug, outcome="error").inc()
            tool_execution_duration_seconds.labels(tool_name=tool_slug).observe(
                time.time() - tool_started_at
            )
        except Exception:
            pass
        await _log_invocation(
            db,
            user,
            tool_slug,
            body,
            None,
            started,
            status="error",
            error_message=str(e),
        )
        return error(f"tool {tool_slug} failed: {e}", 500)

    try:
        from app.core.telemetry import (
            tool_calls_total,
            tool_execution_duration_seconds,
        )

        _outcome = "error" if getattr(result, "is_error", False) else "ok"
        tool_calls_total.labels(tool_name=tool_slug, outcome=_outcome).inc()
        tool_execution_duration_seconds.labels(tool_name=tool_slug).observe(
            time.time() - tool_started_at
        )
    except Exception:
        pass

    is_error = getattr(result, "is_error", False)
    payload = {
        "content": getattr(result, "content", None),
        "metadata": getattr(result, "metadata", None),
    }
    await tool_gate.release(
        decision, tool_slug, tenant_id, ok=not is_error, result_payload=payload
    )
    await _log_invocation(
        db,
        user,
        tool_slug,
        body,
        result,
        started,
        status="ok" if not is_error else "error",
    )

    return success(
        {
            "tool_slug": tool_slug,
            **payload,
            "is_error": is_error,
        }
    )


_LOG_TASKS: set = set()
# a log row keeps a preview, a 30 KB state blob per call would make the log the bottleneck
_LOG_KEEP_CHARS = int(os.environ.get("TOOL_LOG_KEEP_CHARS", "4000"))


def _clip(value):
    import json as _json

    if value is None:
        return None
    text = value if isinstance(value, str) else _json.dumps(value, default=str)
    if len(text) <= _LOG_KEEP_CHARS:
        return value
    clipped = {"truncated": True, "size": len(text), "preview": text[:_LOG_KEEP_CHARS]}
    return clipped if not isinstance(value, str) else _json.dumps(clipped)


async def _log_invocation(
    db,
    user,
    tool_slug,
    body,
    result,
    started_at: float,
    *,
    status: str,
    error_message: str | None = None,
    cache_hit: bool = False,
):
    """Record the call after the answer has gone out, on its own session."""
    import asyncio
    import time

    from app.core.deps import async_session
    from models.tool_invocation import ToolInvocation, ToolInvocationStatus

    fields = dict(
        tenant_id=user.tenant_id,
        user_id=user.id,
        via="direct",
        tool_slug=tool_slug,
        arguments=_clip((body or {}).get("arguments")),
        config=(body or {}).get("config"),
        status=ToolInvocationStatus(
            status if status in {"ok", "error", "timeout"} else "error"
        ),
        output=_clip(getattr(result, "content", None)) if result else None,
        output_metadata=getattr(result, "metadata", None) if result else None,
        is_error=getattr(result, "is_error", False) if result else True,
        error_message=error_message,
        duration_ms=int((time.time() - started_at) * 1000),
        requested_via="http",
    )

    async def _write() -> None:
        try:
            async with async_session() as session:
                session.add(ToolInvocation(**fields))
                await session.commit()
        except Exception as _e:
            logger.warning("could not log tool invocation: %s", _e)

    task = asyncio.create_task(_write())
    _LOG_TASKS.add(task)
    task.add_done_callback(_LOG_TASKS.discard)


@router.get("/invocations")
async def list_invocations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tool_slug: str | None = None,
    limit: int = 100,
) -> JSONResponse:
    from sqlalchemy import desc, select
    from models.tool_invocation import ToolInvocation

    q = select(ToolInvocation).where(ToolInvocation.tenant_id == user.tenant_id)
    if tool_slug:
        q = q.where(ToolInvocation.tool_slug == tool_slug)
    q = q.order_by(desc(ToolInvocation.created_at)).limit(min(limit, 500))
    rows = (await db.execute(q)).scalars().all()
    return success(
        [
            {
                "id": str(r.id),
                "tool_slug": r.tool_slug,
                "via": r.via,
                "status": (
                    r.status.value if hasattr(r.status, "value") else str(r.status)
                ),
                "is_error": r.is_error,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    )
