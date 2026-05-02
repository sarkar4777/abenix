"""Tool metadata API — returns descriptions and schemas for all built-in tools."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.deps import get_current_user
from app.core.responses import success

from models.user import User

router = APIRouter(prefix="/api/tools", tags=["tools"])

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
        "description": "Brent, JKM, TTF, EUA carbon, equities and other financial futures — spot + forward curves",
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
        "id": "graph_builder",
        "name": "Graph Builder",
        "description": "Build a structured DAG from nodes + edges with cycle detection and topological layout hints",
        "category": "enterprise",
    },
    {
        "id": "structured_extractor",
        "name": "Structured Extractor",
        "description": "Schema-driven extraction from long documents into strict JSON — used by the example app extractor",
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
        "description": "Schema-driven portfolio tool for PPA / gas / tolling contracts. Reads its schema from portfolio_schemas at runtime so the same tool powers the example app, custom energy desks, and new verticals.",
        "category": "finance",
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
) -> JSONResponse:
    """Return metadata for all available built-in tools."""
    return success(TOOL_CATALOG, meta={"count": len(TOOL_CATALOG)})
