/**
 * Tool documentation for every Abenix runtime tool.
 * Used by: AI Builder, Builder config panel, Agent info page, Marketplace.
 *
 * TOOL_CATEGORIES and TOOL_DOCS are generated from the runtime tool classes.
 * Do not edit them by hand, run `python scripts/gen-tool-docs.py --write`.
 * CI runs the same script with --check.
 */

export interface ToolParam {
  name: string;
  type: string;
  required: boolean;
  description: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  items?: { type: string };
  showWhen?: { field: string; values: string[] };
}

export interface ToolDoc {
  name: string;
  description: string;
  category?: string;
  parameters: ToolParam[];
}

export const TOOL_CATEGORIES = [
  'Core',
  'Code & Transform',
  'Data & Search',
  'Financial',
  'Integrations',
  'Enterprise',
  'Compliance & KYC',
  'Pipeline',
  'Meetings',
  'Multi-Modal',
  'ML Models',
  'Knowledge Graph',
  'Privacy & Safety',
  'Decisions & Rules',
  'Sources & Watch',
] as const;

export const TOOL_DOCS: Record<string, ToolDoc> = {
  academic_search: {
    category: "Core",
    name: "Academic Search",
    description: "Search academic papers and research publications. Uses Semantic Scholar and arXiv APIs.",
    parameters: [
      { name: "query", type: "string", required: true, description: "Research query" },
      { name: "source", type: "string", required: false, description: "", enum: ["semantic_scholar", "arxiv", "both"], default: "both" },
      { name: "year_from", type: "integer", required: false, description: "Filter papers from this year" },
      { name: "year_to", type: "integer", required: false, description: "Filter papers to this year" },
      { name: "max_results", type: "integer", required: false, description: "", default: 10 },
    ],
  },
  address_normalize: {
    category: "Compliance & KYC",
    name: "Address Normalize",
    description: "Parse a free-text address into structured fields (street, city, state, postal_code, country) and emit a canonical single-line form. US/UK/CA/EU heuristics. Useful as a pre-step to geocoding or for deduplication.",
    parameters: [
      { name: "address", type: "string | array", required: true, description: "A single address string OR an array of address strings (batch mode)." },
    ],
  },
  adverse_media: {
    category: "Compliance & KYC",
    name: "Adverse Media",
    description: "Adverse-media / negative-news screening for KYC and third-party due diligence. Fuses four independent sources so it still delivers when any one is rate-limited or offline: (1) Tavily AI news search, (2) GDELT Events 2.0 (public, multilingual, 3-year window), (3) Google News RSS (public, no key), (4) direct HTML scraping of tier-1 outlets like Reuters. Each hit is auto-classified by risk category (bribery, money laundering, fraud, sanctions evasion, terrorism financing, human trafficking, tax evasion, narcotics, environmental crime, cyber crime, market manipulation, regulatory breach, violent/organised crime, ESG governance), stance (adverse / neutral / positive), recency bucket (30d, 90d, 1y, 3y, older), and source tier weight 1..5 (5 = SEC/DOJ/FCA/other regulator, 4 = Reuters/Bloomberg/FT/WSJ, 3 = national paper, 2 = trade press, 1 = unverified). Returns a de-duplicated, fuzzy-matched list plus an L/M/H risk grade (H = any regulator-tier adverse hit OR 3+ independent tier-3+ adverse hits within 2y; M = 1-2 tier-3+ adverse hits in 2y; L = otherwise). Use cases: KYC onboarding, periodic CDD refresh, vendor risk, M&A due diligence, correspondent banking, insurance underwriting, journalism investigations. Requires TAVILY_API_KEY for the Tavily source; other sources work keyless.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Person or entity name." },
      { name: "search_depth", type: "string", required: false, description: "Tavily search depth. 'advanced' costs more tokens but surfaces deeper results.", enum: ["basic", "advanced"], default: "basic" },
      { name: "name_match_threshold", type: "integer", required: false, description: "Drop hits whose title fuzzy-match is below this.", default: 75, minimum: 50, maximum: 100 },
      { name: "min_source_weight", type: "integer", required: false, description: "Require at least this source-tier weight (1-5).", default: 1, minimum: 1, maximum: 5 },
      { name: "lookback_years", type: "integer", required: false, description: "", default: 3, minimum: 1, maximum: 10 },
      { name: "max_results", type: "integer", required: false, description: "", default: 30, minimum: 1, maximum: 100 },
      { name: "refresh", type: "boolean", required: false, description: "", default: false },
    ],
  },
  agent_step: {
    category: "Pipeline",
    name: "Agent Step",
    description: "Run a full AI agent as a pipeline step. The agent has its own LLM loop, can use tools, and iterates autonomously until it produces a final answer. Use this to chain agents within a pipeline \u2014 the output of one agent can feed into another. Supports all available tools and LLM models.",
    parameters: [
      { name: "input_message", type: "string", required: true, description: "The task or prompt for the agent to work on" },
      { name: "system_prompt", type: "string", required: true, description: "System prompt defining the agent's role and behavior" },
      { name: "tools", type: "array", required: false, description: "List of tool names available to the agent", items: { type: "string" }, default: [] },
      { name: "model", type: "string", required: false, description: "LLM model to use", default: "claude-sonnet-4-5-20250929" },
      { name: "max_iterations", type: "integer", required: false, description: "Maximum number of LLM reasoning loops", default: 10, minimum: 1, maximum: 25 },
      { name: "temperature", type: "number", required: false, description: "Sampling temperature", default: 0.7, minimum: 0, maximum: 2 },
    ],
  },
  ais_stream: {
    category: "Core",
    name: "AIS Live Vessels",
    description: "Sample live vessel positions from the global AIS feed (AISStream.io). Returns up to N most-recent PositionReport / ShipStaticData messages within an optional bounding box and ship-type filter. Real, identifiable MMSIs and ship names \u2014 every vessel in the response can be looked up on VesselFinder for verification. Use ship_types=[80,84] for LPG/tanker traffic, [70,71,72,73,74,75,76,77,78,79] for cargo. The call opens a short subscription (default 8s) and closes \u2014 it does NOT keep streaming. An admin sets AISSTREAM_API_KEY under Admin -> Tool Configuration.",
    parameters: [
      { name: "bounding_boxes", type: "array", required: false, description: "List of bounding boxes, each [[sw_lat, sw_lon], [ne_lat, ne_lon]]. Default: worldwide. Smaller boxes = denser sampling for the subscription window.", items: { type: "array" } },
      { name: "ship_types", type: "array", required: false, description: "AIS ship type codes (e.g. [80,84] for tankers + LPG). Empty = all.", items: { type: "integer" } },
      { name: "max_messages", type: "integer", required: false, description: "Stop after this many messages collected.", default: 30, minimum: 1, maximum: 200 },
      { name: "duration_seconds", type: "number", required: false, description: "Max subscription window in seconds.", default: 8.0, minimum: 1.0, maximum: 30.0 },
    ],
  },
  api_connector: {
    category: "Integrations",
    name: "API Connector",
    description: "Connect to popular external services: send Slack messages, read/write Airtable records, interact with Notion databases, create Jira tickets, and push data to Google Sheets. Pre-configured connectors with simple interfaces for common integrations.",
    parameters: [
      { name: "service", type: "string", required: true, description: "Service and action to execute", enum: ["slack", "airtable_read", "airtable_write", "notion_query", "notion_create", "jira_create", "jira_search", "google_sheets_read", "google_sheets_append"] },
      { name: "params", type: "object", required: true, description: "Service-specific parameters" },
    ],
  },
  approval_gate: {
    category: "Pipeline",
    name: "Approval Gate",
    description: "Pause the agent until a human (or N humans) sign off on a payload. Returns {status: approved|denied|expired, signoffs: [...]}. The agent should branch on status \u2014 denied/expired means do not proceed.",
    parameters: [
      { name: "title", type: "string", required: false, description: "Short, human-readable label for the approval card" },
      { name: "payload", type: "object", required: true, description: "What the human needs to approve (action, params, context)" },
      { name: "required_signoffs", type: "integer", required: false, description: "How many distinct approvers must approve", default: 1, minimum: 1 },
      { name: "expires_seconds", type: "integer", required: false, description: "Seconds until the approval auto-expires (max 7 days)", default: 1800 },
      { name: "kind", type: "string", required: false, description: "Optional discriminator (e.g. device.remote_reset, claim.adjudicate) so reviewer UIs and SDK consumers can dispatch handlers per gate type" },
      { name: "agent_execution_id", type: "string", required: false, description: "Execution UUID, filled from the running agent when left out" },
      { name: "agent_id", type: "string", required: false, description: "Agent UUID, filled from the running agent when left out" },
      { name: "auth_token", type: "string", required: false, description: "JWT or API key for the API call, by default a short-lived token for the user the run belongs to" },
    ],
  },
  atlas_as_of: {
    category: "Enterprise",
    name: "Atlas \u2014 As-Of",
    description: "Show an atlas graph as it stood at a past moment. Reads the newest saved snapshot taken at or before the timestamp, or the live graph when nothing changed since then, and honours valid_from / valid_to on live rows. Use for 'what did the ontology say on date X' and audit questions. Optionally narrow to nodes whose label contains a term.",
    parameters: [
      { name: "graph_id", type: "string", required: false, description: "Optional. Defaults to the agent's primary atlas." },
      { name: "as_of", type: "string", required: false, description: "ISO-8601 date or timestamp, UTC when no offset is given. Defaults to now." },
      { name: "label_like", type: "string", required: false, description: "Only nodes whose label contains this text (case-insensitive), plus their edges." },
      { name: "kind", type: "string", required: false, description: "", enum: ["concept", "instance", "document", "property"] },
      { name: "limit", type: "integer", required: false, description: "Max nodes and max edges returned.", default: 100, minimum: 1, maximum: 1000 },
    ],
  },
  atlas_describe: {
    category: "Enterprise",
    name: "Atlas \u2014 Describe",
    description: "Summarise an atlas graph: total nodes/edges per kind, top edge labels, and the most-connected concepts. Use as the first step when the user asks 'what do you know about X?' \u2014 gives the agent a map of the domain before it dives into specifics.",
    parameters: [
      { name: "graph_id", type: "string", required: false, description: "Optional. Defaults to the agent's primary atlas." },
      { name: "top_n", type: "integer", required: false, description: "", default: 10, minimum: 1, maximum: 50 },
    ],
  },
  atlas_query: {
    category: "Enterprise",
    name: "Atlas \u2014 Pattern Query",
    description: "Search the Atlas ontology graph by node pattern. Each pattern is a {label_like, kind?} object. Returns matching nodes (and edges, if traversals are supplied). Use when the user asks about a typed concept (Counterparty, Trade, etc.) and you want structured rows instead of a vector search.",
    parameters: [
      { name: "patterns", type: "array", required: true, description: "One or more node patterns to match.", items: { type: "object" } },
      { name: "graph_id", type: "string", required: false, description: "Optional. UUID of the atlas graph to query. Defaults to the agent's primary atlas." },
      { name: "limit", type: "integer", required: false, description: "", default: 25, minimum: 1, maximum: 200 },
    ],
  },
  atlas_search_grounded: {
    category: "Enterprise",
    name: "Atlas \u2014 Grounded Search",
    description: "Find KB documents that are linked (as document-kind nodes) to concepts near a target term in the ontology. Use this instead of vector-only `knowledge_search` when the user asks about a typed concept and you want chunks that are *bound* to that concept, not just lexically similar.",
    parameters: [
      { name: "near_label", type: "string", required: true, description: "Concept label to ground retrieval around (e.g. 'Counterparty')." },
      { name: "graph_id", type: "string", required: false, description: "" },
      { name: "max_docs", type: "integer", required: false, description: "", default: 10, minimum: 1, maximum: 50 },
    ],
  },
  atlas_traverse: {
    category: "Enterprise",
    name: "Atlas \u2014 Traverse",
    description: "Return the 1-hop neighbourhood of a node (incoming + outgoing edges and the nodes on the other end). Pick the node by exact label match, or by id if you already have it. Use when you've located a concept and want to walk to related concepts.",
    parameters: [
      { name: "label", type: "string", required: false, description: "Exact label of the node (case-insensitive)." },
      { name: "node_id", type: "string", required: false, description: "Or pass a node UUID directly." },
      { name: "graph_id", type: "string", required: false, description: "" },
      { name: "max_edges", type: "integer", required: false, description: "", default: 50, minimum: 1, maximum: 200 },
    ],
  },
  browser_automation: {
    category: "Integrations",
    name: "Browser Automation",
    description: "Headless Chromium via Playwright for sites that need JS rendering, login flows, or click-throughs. Operations: get_text (full visible text of a page), get_html (rendered HTML), screenshot (PNG bytes base64), click_and_get (navigate + click a CSS selector + extract). Domains gated via BROWSER_AUTOMATION_ALLOWED_HOSTS env (comma list, or '*' in dev). Requires `pip install playwright && playwright install chromium`.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "", enum: ["get_text", "get_html", "screenshot", "click_and_get"], default: "get_text" },
      { name: "url", type: "string", required: true, description: "Target URL (must pass the allow-list)." },
      { name: "wait_for_selector", type: "string", required: false, description: "Optional CSS selector to wait for before extracting." },
      { name: "click_selector", type: "string", required: false, description: "click_and_get only \u2014 the CSS selector to click first." },
      { name: "timeout_ms", type: "integer", required: false, description: "", default: 15000, minimum: 1000, maximum: 60000 },
      { name: "max_chars", type: "integer", required: false, description: "Cap text/HTML output to keep token cost sane.", default: 6000, minimum: 100, maximum: 50000 },
    ],
  },
  bundesanzeiger_filings: {
    category: "Financial",
    name: "Bundesanzeiger Filings",
    description: "Search Bundesanzeiger for filings linked to a DE-incorporated counterparty. Returns the result-list of annual accounts and management reports with publication date + HTML detail-page link. No mock data \u2014 returns no_matches if the search yields nothing.",
    parameters: [
      { name: "legal_name", type: "string", required: true, description: "" },
      { name: "max_results", type: "integer", required: false, description: "", default: 25, minimum: 1, maximum: 100 },
    ],
  },
  bunker_fuel: {
    category: "Financial",
    name: "Bunker Fuel + Freight Estimate",
    description: "Free bunker-fuel price proxy + corridor freight-rate estimator. Returns current VLSFO bunker prices at the major ports (Houston, Rotterdam, Singapore, Fujairah, Tokyo, New York) and, when both origin+destination are passed, computes a freight-rate estimate in $/MT for a typical VLGC voyage. NOT a Baltic Exchange BLPG assessed rate \u2014 clearly labeled as 'bunker-derived'. Swap to a Baltic feed in production for assessed rates; the agent layer doesn't change.",
    parameters: [
      { name: "origin", type: "string", required: false, description: "Origin port (Houston, Rotterdam, Singapore, Fujairah, Tokyo, New York). Optional." },
      { name: "destination", type: "string", required: false, description: "Destination port (same set). Optional." },
    ],
  },
  calculator: {
    category: "Core",
    name: "Calculator",
    description: "Evaluate a mathematical expression safely. Supports basic arithmetic, exponentiation, and math functions (sqrt, log, sin, cos, etc.).",
    parameters: [
      { name: "expression", type: "string", required: true, description: "The mathematical expression to evaluate, e.g. '(2 + 3) * 4'" },
    ],
  },
  cloud_cost: {
    category: "Core",
    name: "Cloud Cost",
    description: "Read current-month cloud spend grouped by service from AWS Cost Explorer, GCP BigQuery billing export, and Azure Consumption. Each provider is skipped gracefully when its credentials or SDK aren't present. Operation 'all' aggregates whatever's configured.",
    parameters: [
      { name: "operation", type: "string", required: false, description: "", enum: ["aws_summary", "gcp_summary", "azure_summary", "all"], default: "all" },
    ],
  },
  cloud_storage: {
    category: "Integrations",
    name: "Cloud Storage",
    description: "Perform operations on cloud storage: S3, GCS, Azure Blob, or local filesystem. Supports list, read, write, and delete operations. Use URL schemes: s3://bucket/key, gs://bucket/key, az://container/blob, file:///path.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Storage operation to perform", enum: ["list_objects", "read_object", "write_object", "delete_object", "get_info"] },
      { name: "path", type: "string", required: true, description: "Storage path (e.g., s3://my-bucket/data/file.csv)" },
      { name: "content", type: "string", required: false, description: "Content to write (for write_object only)" },
      { name: "prefix", type: "string", required: false, description: "Prefix filter for list_objects" },
      { name: "max_keys", type: "integer", required: false, description: "Max objects to list (default: 100)", default: 100 },
    ],
  },
  code_asset: {
    category: "Code & Transform",
    name: "Code Asset",
    description: "Execute a registered code asset (a user-uploaded zip/git repo) with a JSON input. Runs inside the sandboxed_job isolation layer using the asset's suggested image + build + run commands. Returns the parsed JSON output (or {raw: stdout} if the asset's output isn't JSON). Register assets via POST /api/code-assets.",
    parameters: [
      { name: "code_asset_id", type: "string", required: true, description: "UUID of the registered code asset." },
      { name: "input", type: "object", required: false, description: "JSON object passed to the asset on stdin. Shape must match the asset's declared input_schema. Always an object, never a bare string or number \u2014 wrap the payload in {field: value} form." },
      { name: "timeout_seconds", type: "integer", required: false, description: "", default: 120, minimum: 10, maximum: 900 },
      { name: "memory_mb", type: "integer", required: false, description: "", default: 1024, minimum: 128, maximum: 4096 },
      { name: "allow_network", type: "boolean", required: false, description: "Needed if the asset calls external APIs (also requires SANDBOXED_JOB_ALLOW_NETWORK=true).", default: false },
    ],
  },
  code_executor: {
    category: "Core",
    name: "Code Executor",
    description: "Execute Python code safely in a sandboxed environment. Supports complex data transformations, statistical computations, file generation (Excel, PDF, charts, PowerPoint), image processing, and algorithmic operations. Core libraries always available: pandas, numpy, openpyxl, json, csv, re, math, datetime, collections, itertools, statistics, uuid, io, base64. Extended libraries available: scipy, matplotlib, seaborn, reportlab, fpdf, Pillow (PIL), beautifulsoup4 (bs4), python-pptx (pptx), scikit-learn (sklearn), plotly, tabulate, xlsxwriter, lxml, zipfile, gzip. Can save files to the export directory using open('file.ext', 'wb') or save_export('file.ext', bytes_data). Pipeline data available via context['node_id']. Does NOT support network calls, system commands, or arbitrary file system access. Additional modules can be requested via extra_modules \u2014 they are LLM-validated for safety.",
    parameters: [
      { name: "code", type: "string", required: true, description: "Python code to execute. Use print() for output. Last expression is captured as result." },
      { name: "variables", type: "object", required: false, description: "Pre-defined variables available in the execution context as globals" },
      { name: "extra_modules", type: "array", required: false, description: "Additional Python modules to allow for this execution. These are validated by an LLM safety review before being permitted. Example: ['networkx', 'sympy', 'shapely']. Modules that provide network access, system commands, or code execution are rejected.", items: { type: "string" } },
    ],
  },
  companies_house: {
    category: "Compliance & KYC",
    name: "Companies House",
    description: "Look up a UK-incorporated counterparty in Companies House. Returns the company profile (incorporation date, status, SIC codes, registered office) and filing index for recent annual accounts. Needs COMPANIES_HOUSE_API_KEY, set under Admin -> Tool Configuration (free signup at developer.company-information.service.gov.uk); returns needs_configuration if unset \u2014 never mocked data.",
    parameters: [
      { name: "company_number", type: "string", required: false, description: "Companies House 8-digit number (preferred)" },
      { name: "legal_name", type: "string", required: false, description: "Used to search if company_number not provided" },
    ],
  },
  connector_call: {
    category: "Integrations",
    name: "Connector Call",
    description: "Execute an operation against one of the tenant's configured connectors (CMMS, HRIS, telematics, weather, cost data). The operation, URL template, and body shape come from the connector's preset. Pass parameters as a flat object.",
    parameters: [
      { name: "connector_id", type: "string", required: true, description: "UUID of the configured connector to call" },
      { name: "operation", type: "string", required: true, description: "Preset operation name (e.g. create_work_order, get_forecast)" },
      { name: "parameters", type: "object", required: false, description: "Operation parameters keyed by name from the preset" },
    ],
  },
  country_cpi_lookup: {
    category: "Data & Search",
    name: "Country Cpi Lookup",
    description: "Pull the Transparency International Corruption Perceptions Index (CPI) rank and score for any country. Accepts ISO-2, ISO-3, or a free-text country name. Fetches the live OurWorldInData + datahub CSV export of TI CPI; if both are unreachable, falls back to a small in-tool cached CSV (CPI 2024) and clearly marks the response as `live=false, stale=true`. Returns rank, score, year, source URL, and a one-line rationale. Used by KYC Indicator I (country corruption risk) and any jurisdiction-due-diligence flow.",
    parameters: [
      { name: "country", type: "string", required: true, description: "ISO-2, ISO-3, or country name (e.g. 'PL', 'POL', 'Poland')." },
    ],
  },
  country_risk_index: {
    category: "Compliance & KYC",
    name: "Country Risk Index",
    description: "Aggregate every major public country-risk signal into a single structured view. Fused indices: Transparency International CPI (180-country corruption perceptions, used directly as MET Indicator I), Basel AML Index (0-10 ML/TF risk), FATF grey & black lists (jurisdictions under increased monitoring + call-for-action), EU Annex I non-cooperative tax jurisdictions, OECD AEOI participants, World Bank Worldwide Governance Indicators (Control of Corruption, Rule of Law, Regulatory Quality percentile ranks), OFAC country programmes (comprehensive vs. selective), US State Dept travel advisories 1-4, Global Peace Index 1-5. Outputs: `cpi_rank`, `cpi_score`, FATF classification (clear / grey / black), sanctions regime, WGI percentiles, an L/M/H jurisdiction risk grade, and an already-computed MET-style Indicator I score. Accepts ISO 3166-1 alpha-2 codes or country names. Cached 24h per country. Used by KYC onboarding, sanctions compliance, tax-team jurisdiction reviews, supply-chain geo-risk, trade credit insurance, export licence decisions, and any Enhanced Due Diligence that needs a jurisdiction-risk rationale.",
    parameters: [
      { name: "country", type: "string", required: true, description: "ISO 3166-1 alpha-2 code (e.g. 'PL', 'GB', 'IR') OR full country name." },
      { name: "signals", type: "array", required: false, description: "Subset of signals to fetch; 'all' by default.", items: { type: "string" } },
    ],
  },
  credit_risk: {
    category: "Financial",
    name: "Credit Risk",
    description: "Assess counterparty credit risk for publicly-listed companies. Uses the Financial Modeling Prep (FMP) API to fetch credit ratings (A++ to D-), financial ratios (debt/equity, current ratio, interest coverage, net debt/EBITDA, ROE), balance sheet and income statement data. Computes Altman Z-Score (Safe/Grey/Distress zones) and probability of default. Returns a comprehensive credit risk report. Needs FMP_API_KEY, set under Admin -> Tool Configuration (free tier: 250 calls/day at financialmodelingprep.com).",
    parameters: [
      { name: "company_name", type: "string", required: true, description: "Company name to look up (e.g. 'Apple Inc' or 'TSLA')." },
      { name: "operation", type: "string", required: false, description: "Assessment depth: 'full_assessment' (default) returns everything; 'quick_score' returns Altman Z and PD only; 'financial_ratios' returns key ratios only.", enum: ["full_assessment", "quick_score", "financial_ratios"], default: "full_assessment" },
    ],
  },
  crypto_market: {
    category: "Financial",
    name: "Crypto Market",
    description: "Crypto market data from CoinGecko: spot price, 24h change, market cap, and OHLC history for any coin. Free tier (~30 req/min). Set COINGECKO_API_KEY for the pro tier.",
    parameters: [
      { name: "operation", type: "string", required: false, description: "", enum: ["price", "ohlc", "trending", "search"], default: "price" },
      { name: "coin_id", type: "string", required: false, description: "CoinGecko coin id ('bitcoin', 'ethereum', 'solana'). Use operation=search to discover ids." },
      { name: "vs_currency", type: "string", required: false, description: "", default: "usd" },
      { name: "days", type: "integer", required: false, description: "Lookback for ohlc operation.", default: 7, minimum: 1, maximum: 365 },
      { name: "query", type: "string", required: false, description: "Free-text search for operation=search" },
    ],
  },
  csv_analyzer: {
    category: "Data & Search",
    name: "CSV Analyzer",
    description: "Analyze CSV and tabular data with advanced operations: descriptive statistics, filtering, sorting, grouping/aggregation, pivot tables, correlation analysis, outlier detection, and data quality assessment. Can read CSV files or accept inline CSV text.",
    parameters: [
      { name: "file_path", type: "string", required: false, description: "Path to CSV file to analyze" },
      { name: "csv_text", type: "string", required: false, description: "Inline CSV text to analyze (use this OR file_path)" },
      { name: "operation", type: "string", required: false, description: "Analysis operation to perform", enum: ["describe", "filter", "sort", "group_by", "correlate", "outliers", "quality", "head", "unique", "frequency"], default: "describe" },
      { name: "columns", type: "array", required: false, description: "Columns to operate on (default: all numeric)", items: { type: "string" } },
      { name: "filter_expr", type: "string", required: false, description: "Filter expression, e.g. 'price > 100' or 'status == active'" },
      { name: "sort_by", type: "string", required: false, description: "Column name to sort by" },
      { name: "sort_desc", type: "boolean", required: false, description: "Sort descending (default: false)", default: false },
      { name: "group_column", type: "string", required: false, description: "Column to group by for aggregation" },
      { name: "agg_func", type: "string", required: false, description: "Aggregation function for group_by", enum: ["sum", "mean", "count", "min", "max", "median"], default: "sum" },
      { name: "limit", type: "integer", required: false, description: "Max rows to return (default: 500)", default: 500 },
    ],
  },
  current_time: {
    category: "Core",
    name: "Current Time",
    description: "Get the current date and time in UTC or a specified timezone. Supports IANA timezone names (e.g. 'America/New_York') and common abbreviations (EST, PST, GMT, CET, IST, JST, etc.).",
    parameters: [
      { name: "timezone", type: "string", required: false, description: "Timezone name (e.g. 'UTC', 'America/New_York', 'PST'). Defaults to UTC.", default: "UTC" },
    ],
  },
  data_exporter: {
    category: "Integrations",
    name: "Data Exporter",
    description: "Export and deliver data to various destinations: save as file (JSON, CSV, TXT, Markdown, HTML, XLSX Excel, PDF report), send via email with attachments, upload to S3, push to webhooks, or write to databases. Supports binary formats like Excel (.xlsx) and PDF natively. Useful for delivering agent analysis results, reports, and processed data to external systems.",
    parameters: [
      { name: "destination", type: "string", required: true, description: "Export destination", enum: ["file", "email", "s3", "webhook", "database"] },
      { name: "data", type: "any", required: true, description: "Data to export (string, object, or array)" },
      { name: "format", type: "string", required: false, description: "Output format. Use xlsx for Excel spreadsheets, pdf for PDF reports.", enum: ["json", "csv", "txt", "markdown", "html", "xlsx", "pdf"], default: "json" },
      { name: "filename", type: "string", required: false, description: "Output filename (auto-generated if omitted)" },
      { name: "email_to", type: "string", required: false, description: "Recipient email address(es), comma-separated", showWhen: { field: "destination", values: ["email"] } },
      { name: "email_subject", type: "string", required: false, description: "Email subject line", showWhen: { field: "destination", values: ["email"] } },
      { name: "email_body", type: "string", required: false, description: "Email body text (the data will be attached)", showWhen: { field: "destination", values: ["email"] } },
      { name: "s3_bucket", type: "string", required: false, description: "S3 bucket name", showWhen: { field: "destination", values: ["s3"] } },
      { name: "s3_key", type: "string", required: false, description: "S3 object key/path", showWhen: { field: "destination", values: ["s3"] } },
      { name: "webhook_url", type: "string", required: false, description: "Webhook URL to POST data to", showWhen: { field: "destination", values: ["webhook"] } },
      { name: "webhook_headers", type: "object", required: false, description: "Additional headers for webhook", showWhen: { field: "destination", values: ["webhook"] } },
      { name: "db_connection_string", type: "string", required: false, description: "Database connection string", showWhen: { field: "destination", values: ["database"] } },
      { name: "db_table", type: "string", required: false, description: "Database table name", showWhen: { field: "destination", values: ["database"] } },
    ],
  },
  data_merger: {
    category: "Pipeline",
    name: "Data Merger",
    description: "Merge multiple data inputs into a single unified structure. Supports three strategies: 'flat' merges all inputs into one dictionary, 'nested' preserves each input under its original key, and 'comparison' creates a side-by-side labeled view. Ideal for fan-in pipeline steps that combine results from parallel branches.",
    parameters: [
      { name: "merge_strategy", type: "string", required: false, description: "Strategy for merging inputs: flat (single dict), nested (keyed), or comparison (labeled side-by-side)", enum: ["flat", "nested", "comparison"], default: "nested" },
      { name: "labels", type: "object", required: false, description: "Display labels for each input key (used with comparison strategy). Keys should match input keys, values are human-readable labels." },
    ],
  },
  database_query: {
    category: "Data & Search",
    name: "Database Query",
    description: "Execute read-only SQL queries against PostgreSQL databases. Read-only (SELECT only), parameterized, 30s timeout. Returns up to 10,000 rows.",
    parameters: [
      { name: "query", type: "string", required: true, description: "SQL query to execute (SELECT only)" },
      { name: "connection_string", type: "string", required: false, description: "Database connection string (e.g., postgresql://user:pass@host:5432/db). If omitted, uses the platform database." },
      { name: "max_rows", type: "integer", required: false, description: "Maximum rows to return (default: 1000, max: 10000)", default: 1000 },
      { name: "params", type: "object", required: false, description: "Query parameters for parameterized queries", default: {} },
    ],
  },
  database_writer: {
    category: "Data & Search",
    name: "Database Writer",
    description: "Write data to PostgreSQL tables (INSERT or UPSERT). Tables must be prefixed with 'af_' for safety. Max 10,000 rows per call. Can also CREATE TABLE IF NOT EXISTS.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Write operation to perform", enum: ["insert", "upsert", "create_table"] },
      { name: "table", type: "string", required: true, description: "Table name (must start with 'af_')" },
      { name: "rows", type: "array", required: false, description: "Array of row objects to insert (for insert/upsert)", items: { type: "object" } },
      { name: "columns", type: "object", required: false, description: "Column definitions for create_table: {name: type}" },
      { name: "conflict_column", type: "string", required: false, description: "Column for ON CONFLICT (upsert only)" },
      { name: "connection_string", type: "string", required: false, description: "PostgreSQL connection string (optional, uses platform DB if omitted)" },
    ],
  },
  date_calculator: {
    category: "Core",
    name: "Date Calculator",
    description: "Perform date calculations: add/subtract days/months/years, compute business days between dates (excluding weekends and US holidays), calculate contract terms and milestones, find days until deadlines, compute age/duration, and work with time zones.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Date operation to perform", enum: ["add", "subtract", "difference", "business_days", "business_days_between", "contract_milestones", "days_until", "format"] },
      { name: "date", type: "string", required: false, description: "Date in YYYY-MM-DD format" },
      { name: "second_date", type: "string", required: false, description: "Second date for difference/between operations" },
      { name: "days", type: "integer", required: false, description: "Number of days to add/subtract" },
      { name: "months", type: "integer", required: false, description: "Number of months to add/subtract" },
      { name: "years", type: "integer", required: false, description: "Number of years to add/subtract" },
      { name: "business_days", type: "integer", required: false, description: "Number of business days to add" },
      { name: "contract_start", type: "string", required: false, description: "Contract start date for milestone calculation" },
      { name: "contract_years", type: "integer", required: false, description: "Contract duration in years" },
      { name: "timezone", type: "string", required: false, description: "Timezone for formatting (e.g. 'America/New_York')" },
    ],
  },
  decision_compare: {
    category: "Decisions & Rules",
    name: "Decision Compare",
    description: "Evaluate the same facts under several rule versions or dates and report what changes, for example this year's rules against next year's, or a planning version against the assured one.",
    parameters: [
      { name: "decision", type: "string", required: true, description: "" },
      { name: "facts", type: "object", required: true, description: "Facts as a nested object. Paths such as shipment.postcode mean {\"shipment\": {\"postcode\": ...}}." },
      { name: "targets", type: "array", required: true, description: "", items: { type: "object" } },
    ],
  },
  decision_evaluate: {
    category: "Decisions & Rules",
    name: "Decision Evaluate",
    description: "Evaluate a published business rule decision against facts and get a deterministic result, the rules that applied, and a trace. If facts are missing or have the wrong type it says which, instead of guessing. Use as_of for a past or future date and known_at to see what was in force as known then.",
    parameters: [
      { name: "decision", type: "string", required: true, description: "The decision key, from decision_list" },
      { name: "facts", type: "object", required: true, description: "Facts as a nested object. Paths such as shipment.postcode mean {\"shipment\": {\"postcode\": ...}}." },
      { name: "as_of", type: "string", required: false, description: "The date the activity happens, like 2026-03-01. Default today." },
      { name: "known_at", type: "string", required: false, description: "Optional. Evaluate with the rules as they were known on this date." },
      { name: "record", type: "boolean", required: false, description: "Keep an auditable record of this evaluation. Inside an agent or pipeline run it is kept unless this is false." },
    ],
  },
  decision_explain: {
    category: "Decisions & Rules",
    name: "Decision Explain",
    description: "Explain in plain words why a decision came out the way it did for these facts: which rules applied, the values they looked at, and the sources cited for each rule.",
    parameters: [
      { name: "decision", type: "string", required: true, description: "The decision key, from decision_list" },
      { name: "facts", type: "object", required: true, description: "Facts as a nested object. Paths such as shipment.postcode mean {\"shipment\": {\"postcode\": ...}}." },
      { name: "as_of", type: "string", required: false, description: "The date the activity happens, like 2026-03-01. Default today." },
      { name: "known_at", type: "string", required: false, description: "Optional. Evaluate with the rules as they were known on this date." },
      { name: "record", type: "boolean", required: false, description: "Keep an auditable record of this evaluation. Inside an agent or pipeline run it is kept unless this is false." },
    ],
  },
  decision_list: {
    category: "Decisions & Rules",
    name: "Decision List",
    description: "List the business rule decisions this tenant has published, with the facts each one needs and their types. Call this first to find the right decision key and the facts to gather.",
    parameters: [
      { name: "query", type: "string", required: false, description: "Optional words to filter by name or key" },
    ],
  },
  decision_propose: {
    category: "Decisions & Rules",
    name: "Decision Propose",
    description: "Propose new or changed business rules for a decision, as typed JSON rules with ruleKey, requiresFacts, when (all/any conditions such as {\"gte\": [{\"fact\": \"shipment.date\"}, \"2026-01-01\"]}), then and provenance with citations. The proposal is validated and golden tested, then waits for people to approve it. Agents cannot publish.",
    parameters: [
      { name: "decision", type: "string", required: true, description: "" },
      { name: "rules", type: "any", required: true, description: "One rule or a list of rules in the typed JSON format" },
      { name: "note", type: "string", required: true, description: "What changed and why, with the source" },
    ],
  },
  decision_test: {
    category: "Decisions & Rules",
    name: "Decision Test",
    description: "Run a decision's golden test cases against a version and report which pass.",
    parameters: [
      { name: "decision", type: "string", required: true, description: "" },
      { name: "version", type: "integer", required: false, description: "Default is the latest version" },
    ],
  },
  defer_to_human: {
    category: "Meetings",
    name: "Defer to Human",
    description: "Route a question back to the human the agent is representing. Call this whenever: (a) the question is outside the meeting's declared topic allow-list, (b) the question asks for a new commitment, (c) the answer isn't in the persona KB with enough confidence. Blocks up to hold_seconds waiting for the user's reply; returns their answer, or a graceful 'let me get back to you' if they don't reply in time.",
    parameters: [
      { name: "meeting_id", type: "string", required: true, description: "" },
      { name: "question", type: "string", required: true, description: "" },
      { name: "context", type: "string", required: false, description: "Why the agent is deferring (for the user's inbox).", default: "" },
      { name: "hold_seconds", type: "integer", required: false, description: "How long to wait for the user's reply before returning the fallback.", default: 30, minimum: 5, maximum: 180 },
      { name: "fallback", type: "string", required: false, description: "", default: "Let me check on that and come back to you." },
    ],
  },
  document_extractor: {
    category: "Data & Search",
    name: "Document Extractor",
    description: "Extract structured data from documents. Parses tables into rows/columns, extracts key-value pairs (dates, amounts, percentages, names), identifies document sections and clauses, and returns structured JSON output. Works with text content directly or reads from files.",
    parameters: [
      { name: "text", type: "string", required: false, description: "Text content to extract from (use this OR file_path)" },
      { name: "file_path", type: "string", required: false, description: "Path to a file to extract from (use this OR text)" },
      { name: "extract_type", type: "string", required: false, description: "What to extract: tables, key_values, sections, entities, or all", enum: ["tables", "key_values", "sections", "entities", "all"], default: "all" },
      { name: "patterns", type: "array", required: false, description: "Optional custom regex patterns to search for", items: { type: "string" } },
    ],
  },
  document_parser: {
    category: "Data & Search",
    name: "Document Parser",
    description: "Extract plain text from documents (PDF, DOCX, TXT, CSV, HTML, Markdown). Returns the full text content ready for analysis. Use as the first step before structured_extractor or any text analysis.",
    parameters: [
      { name: "file_path", type: "string", required: false, description: "Path to the file on the shared /data mount" },
      { name: "max_chars", type: "integer", required: false, description: "Maximum characters to return (default 100000)", default: 100000 },
      { name: "page_range", type: "string", required: false, description: "For PDFs only -- limit extraction to a page range, e.g. '1-5' or '3' for a single page. Pages are 1-indexed." },
    ],
  },
  ecb_rates: {
    category: "Financial",
    name: "ECB Rates",
    description: "Fetch foreign exchange rates, inflation data, and interest rates from the European Central Bank Statistical Data Warehouse.",
    parameters: [
      { name: "data_type", type: "string", required: true, description: "Type of data", enum: ["fx_rate", "inflation", "interest_rate"] },
      { name: "currency_pair", type: "string", required: false, description: "For fx_rate: EUR/USD, EUR/GBP, etc.", default: "EUR/USD" },
      { name: "date_from", type: "string", required: false, description: "Start date (YYYY-MM-DD)" },
    ],
  },
  edgar_filings: {
    category: "Financial",
    name: "Edgar Filings",
    description: "Fetch the last 5 fiscal years of GAAP/IFRS-mapped financial statements for a US-listed issuer from SEC EDGAR XBRL company-facts API. Input: ticker (e.g. 'XOM') or cik (10-digit int). Output: statements keyed by fiscal year with revenue / EBITDA / net income / balance-sheet / cash-flow line items in USD millions, plus per-concept provenance citing the XBRL concept + filing accession number.",
    parameters: [
      { name: "ticker", type: "string", required: false, description: "Stock ticker (case-insensitive). Use this OR cik." },
      { name: "cik", type: "integer", required: false, description: "SEC Central Index Key (10-digit int). Use this OR ticker." },
      { name: "n_years", type: "integer", required: false, description: "", default: 5, minimum: 1, maximum: 10 },
    ],
  },
  eex_public_summary: {
    category: "Financial",
    name: "Eex Public Summary",
    description: "Documented-degraded TTF data fetcher. Always returns status='unavailable' because no free machine-readable TTF settle feed exists today. The agent must fall back to monte_carlo_curve + realized_vol_calc against a TTF proxy (yahoo_finance NG=F or eia_open_data HH_NATGAS). Kept in the toolchain so the agent honestly records 'live-data not available' provenance.",
    parameters: [
      { name: "hub", type: "string", required: false, description: "Hub code. Ignored (no hub is live).", default: "TTF" },
      { name: "lookback_days", type: "integer", required: false, description: "Unused \u2014 kept for signature stability.", default: 30 },
      { name: "tenor_months", type: "integer", required: false, description: "Unused \u2014 kept for signature stability.", default: 12 },
    ],
  },
  eia_open_data: {
    category: "Financial",
    name: "EIA Open Data",
    description: "Fetch energy market time series from the US Energy Information Administration (EIA) Open Data API v2. Use one of the shortcut ids (PROPANE_USGC_MB, WTI_SPOT, BRENT_SPOT, HH_NATGAS, US_LPG_EXPORTS, PROPANE_USA) for the common cases, or pass a raw EIA series path. Returns the most recent N data points with their dates, plus min/max/mean and unit metadata. Real, citable, regulator-published numbers \u2014 every value comes with the EIA series id for audit.",
    parameters: [
      { name: "series_id", type: "string", required: true, description: "One of the shortcut ids (PROPANE_USGC_MB, WTI_SPOT, BRENT_SPOT, HH_NATGAS, US_LPG_EXPORTS, PROPANE_USA) or a raw EIA v2 path like 'petroleum/pri/spt/data/'." },
      { name: "start", type: "string", required: false, description: "Optional ISO date (YYYY-MM-DD) \u2014 defaults to 'last 52 weeks'." },
      { name: "end", type: "string", required: false, description: "Optional ISO date (YYYY-MM-DD) \u2014 defaults to today." },
      { name: "limit", type: "integer", required: false, description: "Max number of data points to return (newest first).", default: 52 },
    ],
  },
  email_sender: {
    category: "Integrations",
    name: "Email Sender",
    description: "Send emails to one or more recipients with plain text or HTML content. Supports SMTP delivery in production and falls back to local file logging in development mode when SMTP is not configured. Useful for sending reports, notifications, alerts, and agent-generated content to users.",
    parameters: [
      { name: "to", type: "string", required: true, description: "Comma-separated list of recipient email addresses" },
      { name: "subject", type: "string", required: true, description: "Email subject line" },
      { name: "body", type: "string", required: true, description: "Email body content (plain text or HTML)" },
      { name: "format", type: "string", required: false, description: "Email body format", enum: ["text", "html"], default: "text" },
    ],
  },
  ember_climate: {
    category: "Financial",
    name: "Ember Climate",
    description: "Fetch power-sector data from Ember's API (api.ember-energy.org): electricity generation mix by source, carbon intensity (gCO2/kWh), electricity demand. Note: Ember's public API does NOT serve EU/UK ETS carbon PRICES \u2014 only carbon intensity. Use a market-data feed for actual ETS prices.",
    parameters: [
      { name: "data_type", type: "string", required: true, description: "Type of data. 'carbon_price' is a compatibility alias that returns carbon INTENSITY (gCO2/kWh) \u2014 Ember doesn't serve ETS prices. 'power_price' returns electricity demand (Ember doesn't serve wholesale prices either).", enum: ["carbon_price", "carbon_intensity", "electricity_generation", "power_price", "electricity_demand"] },
      { name: "country", type: "string", required: false, description: "ISO 3-letter country code (entity_code)", default: "GBR" },
      { name: "year", type: "integer", required: false, description: "Year for data (e.g., 2024). If omitted, defaults to last 12 months." },
      { name: "temporal_resolution", type: "string", required: false, description: "Granularity of returned records.", enum: ["monthly", "yearly"], default: "monthly" },
    ],
  },
  entso_e: {
    category: "Financial",
    name: "ENTSO-E",
    description: "Fetch European electricity market data from ENTSO-E Transparency Platform. Day-ahead prices, wind/solar generation, load forecasts.",
    parameters: [
      { name: "data_type", type: "string", required: true, description: "Type of data to fetch", enum: ["day_ahead_price", "generation", "load_forecast", "installed_capacity"] },
      { name: "area", type: "string", required: false, description: "Country/bidding zone code (e.g., DE_LU, FR, ES, IT, NL, GB)", default: "DE_LU" },
      { name: "date_from", type: "string", required: false, description: "Start date (YYYY-MM-DD)" },
      { name: "date_to", type: "string", required: false, description: "End date (YYYY-MM-DD)" },
    ],
  },
  epa_echo: {
    category: "Core",
    name: "Epa Echo",
    description: "Look up a counterparty in EPA ECHO. Returns matching facilities with Title V air, NPDES water, and RCRA hazardous-waste permits, current enforcement actions, and violation history. Public free API. No mock data \u2014 returns no_matches if ECHO has no records.",
    parameters: [
      { name: "legal_name", type: "string", required: true, description: "" },
      { name: "state", type: "string", required: false, description: "Optional US state code (e.g. TX, CA)" },
      { name: "max_results", type: "integer", required: false, description: "", default: 20, minimum: 1, maximum: 100 },
    ],
  },
  event_buffer: {
    category: "Integrations",
    name: "Event Buffer",
    description: "Read and consume buffered events from the platform event queue. Events arrive via webhook triggers and accumulate until consumed. Supports filtering by event type and time window.",
    parameters: [
      { name: "source", type: "string", required: false, description: "Event source identifier (trigger name or 'all')" },
      { name: "event_type", type: "string", required: false, description: "Filter by event type (optional)" },
      { name: "limit", type: "integer", required: false, description: "Max events to read", default: 100 },
      { name: "since_seconds", type: "integer", required: false, description: "Only events from last N seconds", default: 3600 },
      { name: "consume", type: "boolean", required: false, description: "Mark events as consumed after reading", default: true },
    ],
  },
  ferc_elibrary: {
    category: "Financial",
    name: "Ferc Elibrary",
    description: "Search FERC eLibrary for filings linked to a counterparty name. Returns matching dockets (ER, EL, QF, ES, PR types) with filing dates and a source URL into the docket sheet. Classifies dockets into permit categories (MBR, enforcement, qualifying facility). No mock data \u2014 empty if FERC returns no matches. Source: https://elibrary.ferc.gov/eLibrary/search",
    parameters: [
      { name: "legal_name", type: "string", required: true, description: "" },
      { name: "max_results", type: "integer", required: false, description: "", default: 25, minimum: 1, maximum: 100 },
      { name: "from_date", type: "string", required: false, description: "ISO YYYY-MM-DD; default = 5y ago" },
    ],
  },
  file_reader: {
    category: "Data & Search",
    name: "File Reader",
    description: "Read and extract text content from a file. Pass either `file_path` (an on-disk file the agent has access to) OR `text` (inline content that the tool will save to a temp file first). Supports PDF, DOCX, TXT, CSV, MD, and JSON formats.",
    parameters: [
      { name: "file_path", type: "string", required: false, description: "Path to the file to read." },
      { name: "text", type: "string", required: false, description: "Inline content to read. Use this when the document is provided in the chat directly rather than as an upload. The tool writes it to a temp file before parsing." },
      { name: "format", type: "string", required: false, description: "Format hint when supplying `text` (pdf, docx, txt, csv, md, json). Auto-detected from file_path otherwise.", enum: ["pdf", "docx", "txt", "csv", "md", "json"] },
    ],
  },
  file_system: {
    category: "Data & Search",
    name: "File System",
    description: "Traverse directories, list files recursively, read file contents, and match glob patterns. Works with local filesystem, mounted NFS/SMB shares, and Docker volumes.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Filesystem operation to perform", enum: ["list_recursive", "read_file", "glob", "stat"] },
      { name: "path", type: "string", required: true, description: "Directory or file path" },
      { name: "pattern", type: "string", required: false, description: "Glob pattern for 'glob' operation (e.g., '**/*.py', 'src/**/*.java')" },
      { name: "max_files", type: "integer", required: false, description: "Max files to return (default: 500)", default: 500 },
      { name: "max_size_kb", type: "integer", required: false, description: "Max file size to read in KB (default: 500)", default: 500 },
    ],
  },
  financial_calculator: {
    category: "Financial",
    name: "Financial Calculator",
    description: "Run a finance calculation immediately \u2014 never ask the user clarifying questions about compounding/frequency; assume annual compounding and frequency=1 unless they say otherwise.\nSupported `calculation` values:\n  \u2022 future_value  \u2014 params: {present, rate, years, [compounding=annual]}\n  \u2022 present_value \u2014 params: {future, rate, years, [compounding=annual]}\n  \u2022 compound_interest \u2014 params: {principal, rate, years, [n=1]}\n  \u2022 npv  \u2014 params: {discount_rate, cash_flows[], initial_investment}\n  \u2022 irr  \u2014 params: {cash_flows[]}\n  \u2022 lcoe / dcf / amortization / escalation / bond_price / wacc /\n    depreciation / breakeven / payback_period / roi / cagr \u2014 see schema.\nReturns numeric result + breakdown.",
    parameters: [
      { name: "calculation", type: "string", required: true, description: "Type of financial calculation to perform", enum: ["future_value", "present_value", "compound_interest", "npv", "irr", "lcoe", "dcf", "amortization", "escalation", "bond_price", "wacc", "depreciation", "breakeven", "payback_period", "roi", "cagr"] },
      { name: "params", type: "object", required: true, description: "Calculation-specific parameters (see description for each calculation type)" },
    ],
  },
  fitch_connect: {
    category: "Financial",
    name: "Fitch Connect",
    description: "Fetch current issuer credit rating from Fitch Connect. Requires FITCH_CONNECT_API_KEY and FITCH_CONNECT_API_URL, set under Admin -> Tool Configuration. Without them returns needs_configuration; never mocked.",
    parameters: [
      { name: "legal_name", type: "string", required: false, description: "" },
      { name: "ticker", type: "string", required: false, description: "" },
      { name: "lei", type: "string", required: false, description: "" },
    ],
  },
  fred_economic: {
    category: "Data & Search",
    name: "Fred Economic",
    description: "US macroeconomic time-series from FRED (St. Louis Fed) \u2014 interest rates, CPI, unemployment, GDP, oil/gas/gold prices. Set FRED_API_KEY for full access; falls back to public CSV for popular series without a key.",
    parameters: [
      { name: "series_id", type: "string", required: true, description: "Either a friendly alias (fed_funds_rate, ten_year_treasury, cpi, unemployment, gdp, wti_oil, natural_gas, gold, ...) or a raw FRED series id (e.g. 'DGS30')." },
      { name: "start_date", type: "string", required: false, description: "ISO date YYYY-MM-DD. Default: 12 months back." },
      { name: "end_date", type: "string", required: false, description: "ISO date YYYY-MM-DD. Default: today." },
      { name: "limit", type: "integer", required: false, description: "Most recent N observations to return.", default: 50, minimum: 1, maximum: 1000 },
    ],
  },
  freight_baltic_blpg: {
    category: "Financial",
    name: "Baltic BLPG (LPG)",
    description: "Baltic Exchange BLPG indices for LPG freight ($/MT propane VLGC). Exposes BLPG1 (Ras Tanura -> Chiba), BLPG2 (Houston -> Flushing) and BLPG3 (Houston -> Chiba via Panama) with mid / low / high for the route. Calibrated to Q1-2026 OPEC-MOMR public-domain levels; production deployments set BALTIC_API_KEY + BALTIC_API_URL under Admin -> Tool Configuration to swap to the live subscription feed without any agent-side code change. Two actions: route (single BLPG with mid/low/high), all (all three routes side-by-side).",
    parameters: [
      { name: "action", type: "string", required: true, description: "", enum: ["route", "all"] },
      { name: "route_code", type: "string", required: false, description: "BLPG1, BLPG2 or BLPG3" },
    ],
  },
  freight_worldscale: {
    category: "Financial",
    name: "Worldscale Freight (CPP)",
    description: "Worldscale freight calculator for clean-products (CPP) tankers. Computes voyage freight in $/MT using the industry-standard formula ws_points / 100 * flat_rate. Knows the 2025 flat-rate schedule for the main TC routes (TC1 MEG->Japan naphtha, TC2 Cont->USAC gasoline, TC5 MEG->Japan naphtha LR1, TC6 Algeria->France, TC7 SG->Sydney, TC14 USAC->Cont, TC17 MEG->East Africa). Three actions: route (look up flat rate + freight given WS points), voyage_cost (full $-amount given cargo size), list (enumerate every TC route).",
    parameters: [
      { name: "action", type: "string", required: true, description: "", enum: ["route", "voyage_cost", "list"] },
      { name: "route_code", type: "string", required: false, description: "TC1 / TC2 / TC5 / TC6 / TC7 / TC14 / TC17" },
      { name: "ws_points", type: "number", required: false, description: "Worldscale points quoted by broker (e.g. 180 means WS180)." },
      { name: "cargo_mt", type: "number", required: false, description: "Override cargo size in MT (default uses route's standard)." },
    ],
  },
  geocoding: {
    category: "Compliance & KYC",
    name: "Geocoding",
    description: "Convert addresses to coordinates (forward) or coordinates to addresses (reverse) using OpenStreetMap Nominatim. Free, no API key. For batch / commercial use, swap to a paid provider.",
    parameters: [
      { name: "operation", type: "string", required: false, description: "forward = address -> coords, reverse = coords -> address", enum: ["forward", "reverse"], default: "forward" },
      { name: "query", type: "string", required: true, description: "Address (forward) or 'lat,lon' (reverse)." },
      { name: "limit", type: "integer", required: false, description: "", default: 5, minimum: 1, maximum: 20 },
    ],
  },
  github_tool: {
    category: "Integrations",
    name: "GitHub Tool",
    description: "Interact with the GitHub REST API to inspect repositories, read files, search code, list issues and pull requests, view commits, check CI workflows, and compare branches. Read only. Public repositories work without a token at GitHub's unauthenticated rate limit. Private repositories and a higher rate limit need GITHUB_TOKEN.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "GitHub operation to perform", enum: ["get_repo", "list_files", "read_file", "search_code", "list_issues", "list_pull_requests", "get_commits", "get_languages", "get_workflows", "compare_branches"] },
      { name: "owner", type: "string", required: true, description: "Repository owner (user or org)" },
      { name: "repo", type: "string", required: true, description: "Repository name" },
      { name: "path", type: "string", required: false, description: "File path (for read_file)", default: "" },
      { name: "query", type: "string", required: false, description: "Search query (for search_code)", default: "" },
      { name: "branch", type: "string", required: false, description: "Branch name", default: "main" },
      { name: "state", type: "string", required: false, description: "", enum: ["open", "closed", "all"], default: "open" },
      { name: "per_page", type: "integer", required: false, description: "Results per page", default: 30, minimum: 1, maximum: 100 },
      { name: "base", type: "string", required: false, description: "Base branch for comparison", default: "main" },
      { name: "head", type: "string", required: false, description: "Head branch for comparison", default: "" },
    ],
  },
  gov_data_us: {
    category: "Data & Search",
    name: "Gov Data Us",
    description: "US government data: SEC EDGAR company filings lookup. Free, no key. Operations: lookup_company (CIK + recent filings by name/ticker), get_filing_text (pull a specific filing's body for LLM analysis).",
    parameters: [
      { name: "operation", type: "string", required: true, description: "", enum: ["lookup_company", "get_filing_text"], default: "lookup_company" },
      { name: "query", type: "string", required: false, description: "Company name or ticker for lookup_company; CIK for get_filing_text." },
      { name: "form_type", type: "string", required: false, description: "Optional filter for lookup_company (e.g. '10-K', '10-Q', '8-K')." },
      { name: "limit", type: "integer", required: false, description: "", default: 10, minimum: 1, maximum: 50 },
      { name: "accession_number", type: "string", required: false, description: "For get_filing_text \u2014 the accession number from lookup_company." },
      { name: "primary_document", type: "string", required: false, description: "For get_filing_text \u2014 the primary document filename." },
    ],
  },
  graph_builder: {
    category: "Enterprise",
    name: "Graph Builder",
    description: "Build a structured graph (DAG) from nodes and edges. Returns a visualization-ready JSON with layout hints, cycle detection, and topological ordering. Use for dependency graphs, provenance chains, workflow diagrams, or any entity-relationship map.",
    parameters: [
      { name: "title", type: "string", required: true, description: "Graph title (shown in the header)." },
      { name: "nodes", type: "array", required: true, description: "List of graph nodes.", items: { type: "object" } },
      { name: "edges", type: "array", required: true, description: "List of directed edges.", items: { type: "object" } },
      { name: "layout", type: "string", required: false, description: "Layout algorithm hint: 'auto' (topological), 'horizontal', 'vertical', 'radial'.", default: "auto" },
    ],
  },
  graph_explorer: {
    category: "Enterprise",
    name: "Graph Explorer",
    description: "Explore a knowledge graph (Neo4j) to find entities and relationships extracted from your documents via Cognify. Domain-agnostic. Use 'find_entity' to search for any entity by name. Use 'entity_relationships' to see how an entity connects to others. Use 'entity_path' to find the shortest connection between two entities. Use 'entities_by_type' to list all entities of a type (ORGANIZATION, LOCATION, etc.). Use 'related_documents' to find which source documents reference a given entity. Use 'graph_stats' to see how many entities and relationships exist.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Which graph operation to perform", enum: ["find_entity", "entity_relationships", "entity_path", "entities_by_type", "related_documents", "graph_stats"] },
      { name: "entity_name", type: "string", required: false, description: "Entity name to search for (fuzzy matching supported)" },
      { name: "entity_type", type: "string", required: false, description: "Entity type filter (e.g. ORGANIZATION, PERSON, LOCATION, CONTRACT_TERM, ASSET, REGULATION)" },
      { name: "target_entity", type: "string", required: false, description: "Target entity for entity_path operation" },
      { name: "max_hops", type: "integer", required: false, description: "Maximum relationship hops for traversal (default 2)", default: 2 },
    ],
  },
  http_client: {
    category: "Integrations",
    name: "HTTP Client",
    description: "Make HTTP requests to external APIs and web services. Supports GET, POST, PUT, DELETE methods with custom headers and JSON payloads. Useful for integrating with third-party APIs, fetching data from REST endpoints, and interacting with web services. Respects sandbox domain restrictions.",
    parameters: [
      { name: "url", type: "string", required: true, description: "Full http or https URL to request" },
      { name: "method", type: "string", required: false, description: "HTTP method", enum: ["GET", "POST", "PUT", "DELETE", "PATCH"], default: "GET" },
      { name: "headers", type: "object", required: false, description: "Request headers as key-value pairs" },
      { name: "body", type: "object", required: false, description: "JSON request body (for POST/PUT/PATCH)", showWhen: { field: "method", values: ["POST", "PUT", "PATCH"] } },
      { name: "params", type: "object", required: false, description: "URL query parameters as key-value pairs" },
      { name: "timeout", type: "integer", required: false, description: "Request timeout in seconds (default: 15)", default: 15 },
    ],
  },
  human_approval: {
    category: "Enterprise",
    name: "Human Approval",
    description: "Pauses execution and requests human approval before proceeding. Use this for high-risk operations like production deployments, data deletions, or financial transactions. The execution will wait until a human approves or rejects, or until timeout.",
    parameters: [
      { name: "action", type: "string", required: true, description: "Short description of the action requiring approval" },
      { name: "details", type: "string", required: false, description: "Detailed context about what will happen if approved" },
      { name: "risk_level", type: "string", required: false, description: "Risk level of the action", enum: ["low", "medium", "high", "critical"], default: "medium" },
      { name: "timeout_seconds", type: "integer", required: false, description: "Max seconds to wait for approval (default 3600 = 1 hour)", default: 3600 },
    ],
  },
  image_analyzer: {
    category: "Multi-Modal",
    name: "Image Analyzer",
    description: "Analyze images using AI vision models. Capabilities: describe content, extract text (OCR), read charts/graphs, detect objects, analyze diagrams, compare images. Supports URLs and local file paths.",
    parameters: [
      { name: "image_url", type: "string", required: true, description: "URL or local file path to the image (PNG, JPG, GIF, WebP)" },
      { name: "operation", type: "string", required: false, description: "Type of analysis to perform", enum: ["describe", "ocr", "chart_data", "objects", "diagram", "compare", "question"], default: "describe" },
      { name: "question", type: "string", required: false, description: "Specific question to answer about the image" },
      { name: "compare_url", type: "string", required: false, description: "Second image URL for comparison (only for 'compare' operation)" },
    ],
  },
  industry_segment_risk: {
    category: "Core",
    name: "Industry Segment Risk",
    description: "Look up the AML/KYC risk weight for any industry segment string. Accepts free-text labels (e.g. 'Wood, Furniture & Paper Manufacturing'), the internal enum keys used by kyc_scorer (e.g. 'wood_furniture_paper'), or NACE codes (e.g. '16.10'). Returns a 5-25 score, FATF class (low/medium/high/very_high), one-line rationale, and source citation (FATF NRA, Basel AML Index, Wolfsberg DDQ). Used as KYC Indicator III and by any sector-risk-rating flow. Pure function \u2014 no network calls.",
    parameters: [
      { name: "industry_segment", type: "string", required: false, description: "Free-text industry label, kyc_scorer enum key, or NACE code." },
      { name: "list_all", type: "boolean", required: false, description: "If true, return the full catalogue (keys, labels, scores, fatf_class, source_url) instead of matching a single segment." },
    ],
  },
  integration_hub: {
    category: "Integrations",
    name: "Integration Hub",
    description: "Connect to 20+ enterprise services: Slack, Teams, Gmail, Salesforce, HubSpot, Zendesk, Jira, Google Sheets, Notion, Airtable, Asana, Linear, Intercom, Twilio, SendGrid, PagerDuty, Snowflake, Stripe, AWS SES/Lambda. Unified interface for sending messages, creating records, and querying data.",
    parameters: [
      { name: "service", type: "string", required: true, description: "Target service to interact with", enum: ["slack", "teams", "gmail", "salesforce", "hubspot", "zendesk", "jira", "google_sheets", "notion", "airtable", "asana", "linear", "intercom", "twilio", "sendgrid", "pagerduty", "snowflake", "stripe", "aws_ses", "aws_lambda"] },
      { name: "action", type: "string", required: true, description: "Action to perform (send_message, create_record, query, update, etc.)" },
      { name: "data", type: "object", required: false, description: "Action-specific data (channel, message, record fields, query, etc.)" },
      { name: "auth_token", type: "string", required: false, description: "Override auth token (optional, uses the configured value if omitted)" },
    ],
  },
  invoke_agent: {
    category: "Pipeline",
    name: "Invoke Agent",
    description: "Invoke a registered platform agent by slug. The platform enqueues the sub-execution, runs it on the appropriate runtime pool, and this tool returns the parsed JSON envelope. Use it to fan a desk-level question out across the specialised sub-agents and synthesise a unified brief from their outputs.",
    parameters: [
      { name: "agent_slug", type: "string", required: true, description: "Slug of the registered agent to invoke (e.g. 'arb-analyzer')." },
      { name: "input", type: "object", required: true, description: "JSON object passed as the input to the sub-agent." },
      { name: "wait_timeout_seconds", type: "integer", required: false, description: "", default: 240, minimum: 30, maximum: 600 },
    ],
  },
  json_transformer: {
    category: "Data & Search",
    name: "JSON Transformer",
    description: "Transform, query, and manipulate structured JSON data. Always specify `operation` \u2014 one of: query (extract by path), filter (predicate), flatten (nest\u2192flat), aggregate (sum/avg/count over arrays), reshape (pivot/group/transpose), merge (combine objects), diff (compare two structures), schema (infer JSON schema), or identity (pass-through for round-tripping). Defaults to identity if omitted.",
    parameters: [
      { name: "data", type: "any", required: true, description: "JSON data to transform (object, array, or JSON string)" },
      { name: "operation", type: "string", required: false, description: "Transformation operation. Use 'identity' (or omit) for pass-through.", enum: ["query", "filter", "flatten", "aggregate", "reshape", "merge", "diff", "schema", "identity"], default: "identity" },
      { name: "path", type: "string", required: false, description: "Dot-notation path for query (e.g. 'users.0.name', 'items[*].price')" },
      { name: "condition", type: "object", required: false, description: "Filter condition: {field: value} or {field: {op: value}}" },
      { name: "second_data", type: "any", required: false, description: "Second dataset for merge/diff operations" },
      { name: "group_by", type: "string", required: false, description: "Field name to group by for reshape" },
      { name: "agg_field", type: "string", required: false, description: "Field to aggregate" },
      { name: "agg_func", type: "string", required: false, description: "Aggregation function", enum: ["sum", "count", "avg", "min", "max", "list"], default: "sum" },
    ],
  },
  kafka_consumer: {
    category: "Integrations",
    name: "Kafka Consumer",
    description: "Consume messages from Kafka topics. For high-throughput event streaming: IoT telemetry, financial transactions, log aggregation. Requires KAFKA_BOOTSTRAP_SERVERS env var.",
    parameters: [
      { name: "topic", type: "string", required: true, description: "Kafka topic to consume from" },
      { name: "group_id", type: "string", required: false, description: "Consumer group ID", default: "abenix" },
      { name: "max_messages", type: "integer", required: false, description: "Max messages to consume", default: 10 },
      { name: "timeout_ms", type: "integer", required: false, description: "Poll timeout in milliseconds", default: 5000 },
      { name: "from_beginning", type: "boolean", required: false, description: "Start from beginning of topic", default: false },
    ],
  },
  knowledge_search: {
    category: "Enterprise",
    name: "Knowledge Search",
    description: "Search the agent's knowledge base using hybrid retrieval that combines vector similarity with knowledge graph traversal. Returns results with relationship context, entity connections, and source provenance. Supports three modes: 'vector' (fast semantic search), 'graph' (relationship-based), or 'hybrid' (best quality \u2014 combines both). Use for complex questions that require understanding relationships between concepts.",
    parameters: [
      { name: "query", type: "string", required: true, description: "The search query \u2014 what information you're looking for" },
      { name: "mode", type: "string", required: false, description: "Search mode: vector (fast), graph (relationship-focused), hybrid (best quality)", enum: ["vector", "graph", "hybrid"], default: "hybrid" },
      { name: "top_k", type: "integer", required: false, description: "Number of results to return", default: 5, minimum: 1, maximum: 20 },
    ],
  },
  knowledge_store: {
    category: "Data & Search",
    name: "Knowledge Store",
    description: "Store content into the knowledge base for future retrieval. Use this to save extracted data, analysis results, documents, or any structured/unstructured text into the agent's knowledge base. Content is indexed for vector similarity search and optionally processed through Cognify to extract entities and relationships into the knowledge graph (Neo4j). Returns the document ID and indexing status.",
    parameters: [
      { name: "content", type: "string", required: true, description: "The text content to store in the knowledge base" },
      { name: "title", type: "string", required: true, description: "A descriptive title for this content (used as document name)" },
      { name: "metadata", type: "object", required: false, description: "Optional metadata to attach (e.g. source, type, tags)", default: {} },
      { name: "cognify", type: "boolean", required: false, description: "Whether to also run Cognify to extract entities into the knowledge graph", default: false },
    ],
  },
  kyc_met_pdf_extractor: {
    category: "Core",
    name: "Kyc Met Pdf Extractor",
    description: "Extract a MET-template KYC Standard Check PDF into the strict MET-shaped JSON identical to what the kyc-standard-check agent emits. Runs Claude vision over every page, parses fields into {value, confidence, raw_snippet} envelopes. Never fabricates.",
    parameters: [
      { name: "pdf_path", type: "string", required: false, description: "Filesystem path to the PDF inside the agent's sandbox." },
      { name: "pdf_base64", type: "string", required: false, description: "Base64-encoded PDF content (use when no path is available)." },
    ],
  },
  kyc_scorer: {
    category: "Compliance & KYC",
    name: "KYC Scorer",
    description: "Deterministic KYC risk scorer \u2014 turns the three header indicators (Country Corruption Index rank, Annual Contracted Volume / Notional, Industry Segment) plus any adverse signals from sanctions, PEP, adverse-media, UBO-gap, or legal-existence checks into an Aggregated Score, a Type of Check (Simplified / Standard / Enhanced) and a top-line L/M/H KYC grade. Uses published guidance from FATF, ESA Joint Guidelines (JC 2017 37) and the Wolfsberg DDQ. Industry rubric covers 20+ sectors \u2014 arms/defence, crypto VASP, gambling, mining/extractives, oil & gas, shipping, MSB, real estate, precious metals, construction, energy trading, wood/furniture/paper, manufacturing, utilities, regulated banks/insurers/healthcare, public sector, etc. Volume bands align with common banking templates ($500k, $5M, $50M, $250M, $1B cut-offs). Extra-signal logic: any sanctions hit, PEP match, adverse-media H-grade, critical legal-existence red flag, or UBO discovery gap auto-bumps the Type of Check one level. Stateless and explainable \u2014 every output includes the rubric text that drove each score, suitable for audit. Use this as the final step of a KYC workflow or standalone for rapid 'what check type does this counterparty need?' decisions.",
    parameters: [
      { name: "cpi_rank", type: "number", required: true, description: "Transparency International CPI rank (1 = cleanest, ~180 = most corrupt). Get via `country_risk_index` tool." },
      { name: "annual_notional_usd", type: "number", required: true, description: "Expected annual contracted volume or notional in USD." },
      { name: "industry_segment", type: "string", required: true, description: "Industry key \u2014 use one of: arms_defence, gambling_casinos, crypto_vasp, mining_extractives, oil_gas, shipping_maritime, cash_intensive_retail, money_service_business, real_estate, precious_metals_stones, construction, telecoms, energy_trading, wood_furniture_paper, manufacturing, wholesale_distribution, professional_services, agriculture, utility_regulated, public_sector, education, healthcare_regulated, technology_saas, insurance_regulated, banking_regulated, other. Free-text also accepted \u2014 we'll fuzzy match." },
      { name: "sanctions_hit", type: "boolean", required: false, description: "Has a sanctions match been found?" },
      { name: "pep_match", type: "boolean", required: false, description: "Is the counterparty or UBO a PEP / family / associate?" },
      { name: "adverse_media_grade", type: "string", required: false, description: "Output grade from `adverse_media` tool.", enum: ["L", "M", "H", "unknown"] },
      { name: "legal_existence_red_flags", type: "array", required: false, description: "Red-flag codes from `legal_existence_verifier`.", items: { type: "string" } },
      { name: "ubo_discovery_gaps", type: "integer", required: false, description: "Count of unresolved UBO chain gaps." },
    ],
  },
  legal_existence_verifier: {
    category: "Compliance & KYC",
    name: "Legal Existence Verifier",
    description: "Verify that a counterparty legally exists, is in good standing, and is not a suspected shell. Cross-references GLEIF (2.3M+ LEI records), OpenCorporates (200M+ companies across 140+ jurisdictions), UK Companies House, and per-country registers. Returns a normalized verdict: `exists` (true/false/unknown), `status` (active / dissolved / liquidated / struck_off / inactive / unknown), LEI, registration number, legal form, incorporation date, jurisdiction, registered address, and a confidence score. Auto-detects common AML red flags: shell patterns (recent incorporation, mass-registration addresses, dormant filings), dissolved / struck-off status, jurisdiction mismatches (incorporated in one country, operating from another), lapsed LEIs, and legal forms typical of tax-shelter structures. Each finding is paired with a `verification_trail[]` of (source, url, evidence) entries suitable for pasting into a KYC audit log. Use this as the 'Basic Compliance Check \u2014 Verification of Legal Existence' step on every KYC file, and as the entry point for supplier/vendor onboarding, procurement due diligence, and invoice-fraud checks. Requires COMPANIES_HOUSE_API_KEY for UK gold-standard lookups (free basic auth).",
    parameters: [
      { name: "company_name", type: "string", required: true, description: "" },
      { name: "country", type: "string", required: false, description: "ISO 3166-1 alpha-2 code. Strongly recommended." },
      { name: "registration_number", type: "string", required: false, description: "Pre-known local company number \u2014 reduces ambiguity." },
      { name: "lei", type: "string", required: false, description: "Pre-known LEI \u2014 skips GLEIF name search." },
    ],
  },
  llm_call: {
    category: "Pipeline",
    name: "LLM Call",
    description: "Make a sub-call to a large language model within a pipeline. Supports multiple providers and models including Claude, GPT-4o, and Gemini. Useful for summarization, classification, extraction, rewriting, translation, and any other LLM-powered transformation step within an agent workflow.",
    parameters: [
      { name: "prompt", type: "string", required: true, description: "The user prompt to send to the LLM" },
      { name: "system_prompt", type: "string", required: false, description: "Optional system prompt to set LLM behavior and context", default: "" },
      { name: "model", type: "string", required: false, description: "Model to use for the completion", enum: ["claude-sonnet-4-5-20250929", "claude-haiku-3-5-20241022", "gpt-4o", "gpt-4o-mini", "gemini-2.0-flash"], default: "claude-sonnet-4-5-20250929" },
      { name: "temperature", type: "number", required: false, description: "Sampling temperature (0-2). Lower is more deterministic.", default: 0.7, minimum: 0, maximum: 2 },
      { name: "max_tokens", type: "integer", required: false, description: "Maximum number of tokens to generate", default: 4096 },
    ],
  },
  llm_route: {
    category: "Pipeline",
    name: "LLM Router",
    description: "Use an LLM to analyze input and route to one of N named branches. Provide a classification prompt, a list of branch names, and optional context. The LLM will return a JSON object with 'route' (the chosen branch) and 'confidence' (0-1 score). Use this with a Switch node for intelligent routing.",
    parameters: [
      { name: "prompt", type: "string", required: true, description: "Classification instruction for the LLM (e.g., 'Classify this ticket as: billing, technical, escalation')" },
      { name: "branches", type: "array", required: true, description: "List of valid branch/category names to choose from", items: { type: "string" } },
      { name: "context", type: "string", required: false, description: "The content to classify (e.g., the ticket text, email body)", default: "" },
      { name: "model", type: "string", required: false, description: "LLM model to use", default: "claude-sonnet-4-5-20250929" },
    ],
  },
  market_data: {
    category: "Financial",
    name: "Market Data",
    description: "Fetch real-time and historical market data including stock prices, commodities (oil, gas, metals), energy market prices (electricity, renewable energy certificates), forex rates, and economic indicators. Uses Alpha Vantage and EIA APIs.",
    parameters: [
      { name: "data_type", type: "string", required: true, description: "Type of market data to fetch", enum: ["stock_quote", "stock_history", "forex", "commodity", "energy_price", "economic_indicator"] },
      { name: "symbol", type: "string", required: false, description: "Ticker/symbol (e.g. 'AAPL', 'EUR/USD', 'WTI')" },
      { name: "period", type: "string", required: false, description: "Time period for historical data", enum: ["daily", "weekly", "monthly"], default: "daily" },
      { name: "series_id", type: "string", required: false, description: "EIA series ID for energy data (e.g. 'ELEC.PRICE.US-ALL.M')" },
    ],
  },
  meeting_join: {
    category: "Meetings",
    name: "Meeting Join",
    description: "Join a meeting on the user's behalf via LiveKit (or Teams / Zoom where enabled). The join plays a consent disclosure, records the start of the session, and returns a session_id used by other meeting_* tools. The bot will refuse to join if the meeting has not been pre-authorized by the user via the /meetings UI.",
    parameters: [
      { name: "meeting_id", type: "string", required: true, description: "Abenix internal meeting id (UUID) \u2014 matches /api/meetings/<id>." },
      { name: "provider", type: "string", required: false, description: "", enum: ["livekit", "teams", "zoom"], default: "livekit" },
      { name: "room", type: "string", required: true, description: "Provider room/meeting id." },
      { name: "url", type: "string", required: false, description: "Optional override for provider URL." },
      { name: "token", type: "string", required: false, description: "Optional pre-minted provider token." },
      { name: "display_name", type: "string", required: false, description: "Name shown in the participant list.", default: "Abenix Assistant" },
      { name: "announce_consent", type: "boolean", required: false, description: "If true, speak a short consent disclosure immediately after joining. Recommended for any human-facing meeting.", default: true },
    ],
  },
  meeting_leave: {
    category: "Meetings",
    name: "Meeting Leave",
    description: "Leave the joined meeting. Optionally posts a short farewell to the meeting chat before disconnecting, and logs a final decision summarising what the bot did.",
    parameters: [
      { name: "meeting_id", type: "string", required: true, description: "" },
      { name: "farewell", type: "string", required: false, description: "", default: "Thanks everyone \u2014 I'll send a summary afterwards." },
      { name: "post_farewell", type: "boolean", required: false, description: "", default: true },
      { name: "summary", type: "string", required: false, description: "Optional one-paragraph summary persisted to the decision log.", default: "" },
    ],
  },
  meeting_listen: {
    category: "Meetings",
    name: "Meeting Listen",
    description: "Stream audio from the joined meeting for a bounded window, run Whisper STT on utterance boundaries (VAD-based), and return the transcript. Utterances publish to the meeting's Redis event stream AS THEY CLOSE \u2014 so the UI sees text flow in real time, not in 10-second batches. Honors 'bot leave' voice commands and flags utterances that address the bot directly (addressed=true). Every addressed utterance carries scope: answer, defer or decline, already checked against the meeting's topics. Follow it: defer goes to defer_to_human, decline gets a polite refusal.",
    parameters: [
      { name: "meeting_id", type: "string", required: true, description: "" },
      { name: "duration_seconds", type: "integer", required: false, description: "Maximum listen window. Loop EXITS EARLY the moment an addressed utterance (voice or chat) is fully transcribed, so typical turn-around is under 2s, not `duration_seconds`.", default: 8, minimum: 3, maximum: 60 },
      { name: "stt_provider", type: "string", required: false, description: "'none' returns VAD-chunked audio stats only (debug).", enum: ["openai", "none"], default: "openai" },
      { name: "min_words_for_entry", type: "integer", required: false, description: "", default: 1, minimum: 0 },
      { name: "display_name", type: "string", required: false, description: "Bot display name \u2014 utterances containing it are flagged addressed=true.", default: "" },
      { name: "early_exit_on_addressed", type: "boolean", required: false, description: "When true (default), return as soon as an addressed utterance closes. Set false to force-wait the full window.", default: true },
    ],
  },
  meeting_post_chat: {
    category: "Meetings",
    name: "Meeting Post Chat",
    description: "Post a text message to the meeting chat without speaking out loud. Good for links, long-form answers, summaries, or when the user asked the bot to stay quiet but still participate in chat.",
    parameters: [
      { name: "meeting_id", type: "string", required: true, description: "" },
      { name: "text", type: "string", required: true, description: "" },
    ],
  },
  meeting_speak: {
    category: "Meetings",
    name: "Meeting Speak",
    description: "Speak text into the joined meeting. Supports OpenAI neutral voices OR ElevenLabs cloned voices (if the user has a consented voice_id). Every call mirrors the text to the meeting chat. Keep utterances short (< 280 chars); longer text is auto-split on sentence boundaries.",
    parameters: [
      { name: "meeting_id", type: "string", required: true, description: "" },
      { name: "text", type: "string", required: true, description: "" },
      { name: "voice", type: "string", required: false, description: "OpenAI voice when provider='openai' or falling back.", enum: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"], default: "alloy" },
      { name: "voice_id", type: "string", required: false, description: "ElevenLabs voice_id. When provided AND ELEVENLABS_API_KEY is set, uses ElevenLabs TTS. If the voice_id is the session user's own cloned voice, requires consent recorded on their account.", default: "" },
      { name: "mirror_to_chat", type: "boolean", required: false, description: "", default: true },
    ],
  },
  memory_forget: {
    category: "Enterprise",
    name: "Memory Forget",
    description: "Delete a stored memory by key. Use this to remove outdated or incorrect information from the agent's persistent memory.",
    parameters: [
      { name: "key", type: "string", required: true, description: "The memory key to delete" },
      { name: "scope", type: "string", required: false, description: "Delete scope: single memory, category, or entire wing", enum: ["room", "hall", "wing"], default: "room" },
      { name: "wing", type: "string", required: false, description: "Wing name (required for wing scope)" },
    ],
  },
  memory_recall: {
    category: "Enterprise",
    name: "Memory Recall",
    description: "Retrieve stored memories. Search by key, type, or get all memories sorted by importance. Use this at the start of conversations to recall context from previous interactions.",
    parameters: [
      { name: "key", type: "string", required: false, description: "Exact key to retrieve (optional \u2014 omit for search)" },
      { name: "search", type: "string", required: false, description: "Search term to find matching memories by key or value" },
      { name: "memory_type", type: "string", required: false, description: "Filter by memory type", enum: ["factual", "procedural", "episodic"] },
      { name: "limit", type: "integer", required: false, description: "Max memories to return (default 10)", default: 10 },
      { name: "mode", type: "string", required: false, description: "Recall mode: exact key lookup, text search, or semantic similarity", enum: ["exact", "search", "semantic"], default: "search" },
      { name: "wing", type: "string", required: false, description: "Filter by memory wing" },
    ],
  },
  memory_store: {
    category: "Enterprise",
    name: "Memory Store",
    description: "Store a piece of information in persistent memory. Use this to remember facts, procedures, or past events across conversations. Memories are scoped to this agent and persist until explicitly forgotten.",
    parameters: [
      { name: "key", type: "string", required: true, description: "A short, descriptive key for the memory (e.g., 'user_preferred_format', 'last_migration_status')" },
      { name: "value", type: "string", required: true, description: "The information to remember" },
      { name: "memory_type", type: "string", required: false, description: "Type of memory: factual (facts), procedural (how-to), episodic (past events)", enum: ["factual", "procedural", "episodic"], default: "factual" },
      { name: "importance", type: "integer", required: false, description: "Importance level 1-10 (higher = more important, retrieved first)", default: 5, minimum: 1, maximum: 10 },
      { name: "wing", type: "string", required: false, description: "Memory wing/category (e.g., 'project-alpha', 'user-preferences')", default: "general" },
      { name: "hall_type", type: "string", required: false, description: "", enum: ["factual", "procedural", "episodic", "emotional", "decision"], default: "factual" },
    ],
  },
  mermaid_diagram: {
    category: "Multi-Modal",
    name: "Mermaid Diagram",
    description: "Produce a Mermaid diagram source block from structured input. Supports: flowchart (nodes + edges), sequence (actor messages), pie (label + value), gantt (task + start + duration). The output is the textual ```mermaid``` block \u2014 a viewer/UI renders it.",
    parameters: [
      { name: "diagram_type", type: "string", required: true, description: "", enum: ["flowchart", "sequence", "pie", "gantt"], default: "flowchart" },
      { name: "title", type: "string", required: false, description: "Optional title above the diagram." },
      { name: "direction", type: "string", required: false, description: "Flowchart direction (top-down, left-right, ...).", enum: ["TD", "LR", "BT", "RL"], default: "LR" },
      { name: "nodes", type: "array", required: false, description: "Flowchart only: [{id, label, shape?: round|stadium|cylinder|diamond}].", items: { type: "object" } },
      { name: "edges", type: "array", required: false, description: "Flowchart only: [{from, to, label?}].", items: { type: "object" } },
      { name: "messages", type: "array", required: false, description: "Sequence only: [{from, to, message, type?: sync|async|note}].", items: { type: "object" } },
      { name: "slices", type: "array", required: false, description: "Pie only: [{label, value}].", items: { type: "object" } },
      { name: "tasks", type: "array", required: false, description: "Gantt only: [{task, start (YYYY-MM-DD), duration (e.g. '5d')}].", items: { type: "object" } },
    ],
  },
  ml_model: {
    category: "ML Models",
    name: "ML Model",
    description: "Run inference on registered ML models (sklearn, PyTorch, ONNX, XGBoost). Operations: 'list_models' (catalog), 'predict' (single inference), 'predict_proba' (classifier probabilities), 'batch_predict' (vectorised inference on N rows), 'get_model_info' (schemas + metrics), 'get_metrics' (just training metrics), 'explain' (feature importance / linear coefficients), 'health_check' (verify a model is reachable + warm).",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Which operation to perform", enum: ["list_models", "predict", "predict_proba", "batch_predict", "get_model_info", "get_metrics", "explain", "health_check"] },
      { name: "model_name", type: "string", required: false, description: "Name of the model (required for everything except list_models)" },
      { name: "model_version", type: "string", required: false, description: "Version of the model (default: latest)", default: "latest" },
      { name: "input_data", type: "object", required: false, description: "Input features for prediction. Usually {features: [1.0, 2.0, ...]} or {col1: val1, col2: val2}. For batch_predict pass {batch: [[...], [...], ...]} or {rows: [{...}, {...}]}" },
    ],
  },
  moderation_vet: {
    category: "Core",
    name: "Moderation Vet",
    description: "Screen text content for policy violations (hate, harassment, violence, sexual, self-harm, illicit). Returns {outcome, action, triggered_categories, category_scores, reason}. Use before sending user-visible output or acting on user input.",
    parameters: [
      { name: "content", type: "string", required: true, description: "Text to screen. Max 30000 characters; longer input is truncated." },
      { name: "strict", type: "boolean", required: false, description: "If true, use threshold 0.3 instead of 0.5 and treat any provider flag as blocked. Use when drafting regulated communications.", default: false },
    ],
  },
  monte_carlo_curve: {
    category: "Financial",
    name: "Monte Carlo Curve",
    description: "Simulate a forward curve via mean-reverting GBM with optional seasonal overlay. Returns the expected curve plus P10/P90 band points at monthly tenors. Use for natural gas / power / refined products where realised vol is observable but the forward is illiquid.",
    parameters: [
      { name: "spot", type: "number", required: true, description: "Current spot price (e.g. TTF M+1 in EUR/MWh)." },
      { name: "vol", type: "number", required: true, description: "Annualised realized volatility as a decimal (0.45 = 45%)." },
      { name: "mean_reversion", type: "number", required: false, description: "Mean-reversion strength toward long-run mean. 0 disables.", default: 0.15 },
      { name: "long_run_mean", type: "number", required: false, description: "Long-run mean price. Defaults to spot if omitted." },
      { name: "seasonality_amplitude", type: "number", required: false, description: "Peak-to-trough seasonal swing as a fraction of spot (0.2 = 20%).", default: 0.0 },
      { name: "seasonality_peak_month", type: "integer", required: false, description: "Calendar month of the seasonal peak (1=Jan). Gas peaks in winter.", default: 1 },
      { name: "tenor_months", type: "integer", required: false, description: "Number of monthly tenor points to simulate.", default: 24 },
      { name: "paths", type: "integer", required: false, description: "Number of MC paths. Capped at 10000.", default: 1000 },
      { name: "drift", type: "number", required: false, description: "Annualised drift (decimal). Use sparingly.", default: 0.0 },
      { name: "start_month", type: "integer", required: false, description: "Calendar month of the first tenor point (1-12).", default: 1 },
      { name: "seed", type: "integer", required: false, description: "Optional explicit RNG seed for deterministic output. When omitted, a stable seed is derived from commodity+region+as_of_date so the same logical input always returns the same curve (cache-friendly)." },
      { name: "commodity", type: "string", required: false, description: "Optional commodity tag used for seed derivation only." },
      { name: "region", type: "string", required: false, description: "Optional region/product tag used for seed derivation only." },
      { name: "as_of_date", type: "string", required: false, description: "Optional ISO date used for seed derivation only." },
      { name: "absolute_floor", type: "number", required: false, description: "Optional absolute lower bound (in the curve's price unit). When the expected curve dips below this, the tool returns degraded instead of fabricated numbers. Use historical floors (Brent: 20 USD/bbl)." },
      { name: "absolute_ceiling", type: "number", required: false, description: "Optional absolute upper bound (in the curve's price unit). When the expected curve exceeds this, the tool returns degraded. Use historical ceilings (Brent: 200 USD/bbl)." },
    ],
  },
  moodys_api: {
    category: "Financial",
    name: "Moodys Api",
    description: "Fetch current issuer credit rating + outlook from Moody's Investors Service. Needs MOODYS_API_KEY and MOODYS_API_URL, set under Admin -> Tool Configuration. Without them returns needs_configuration; never returns mocked data.",
    parameters: [
      { name: "legal_name", type: "string", required: false, description: "" },
      { name: "ticker", type: "string", required: false, description: "" },
      { name: "lei", type: "string", required: false, description: "" },
    ],
  },
  moodys_orbis_lookup: {
    category: "Financial",
    name: "Moodys Orbis Lookup",
    description: "Look up a counterparty in Moody's Orbis (BvD). This environment is not provisioned for Orbis; the tool always returns {status:'unavailable', honest_banner:true}. Caller agents must fall back to GLEIF, Companies House, Bundesanzeiger, EDGAR, and tavily_search via ubo_discovery + legal_existence_verifier, and must NOT cite Moody's, BvD, Orbis, or D&B as a source.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Counterparty legal name." },
      { name: "country_iso2", type: "string", required: false, description: "ISO-2 country code (optional but recommended)." },
      { name: "lei", type: "string", required: false, description: "LEI code (optional)." },
    ],
  },
  mqtt_publish: {
    category: "Integrations",
    name: "Mqtt Publish",
    description: "Publish a JSON payload to an MQTT topic on the platform broker. Use for write-back to PLC bridges, SCADA gateways, or downstream agents. QoS 0/1/2 supported, retain flag supported.",
    parameters: [
      { name: "topic", type: "string", required: true, description: "MQTT topic (e.g. 'plant/pump1/cmd')." },
      { name: "payload", type: "any", required: true, description: "Message \u2014 string or JSON-serialisable object." },
      { name: "qos", type: "integer", required: false, description: "0=fire-and-forget, 1=at-least-once, 2=exactly-once.", enum: ["0", "1", "2"], default: 0 },
      { name: "retain", type: "boolean", required: false, description: "Persist as topic's last-known value.", default: false },
    ],
  },
  narrate: {
    category: "Pipeline",
    name: "Narrate",
    description: "Emit a single short progress line so the trader watching the live Desk Copilot canvas can see what you are doing right now. Use this at decision points: 'planning to fan out to mispricing + scenarios', 'pulling EIA Mont Belvieu propane history', 'fair value is $28.40 / MT, residual is 1.7 sigma rich'. Keep each call under 140 characters. Calling this does NOT count against your tool budget for actual work.",
    parameters: [
      { name: "message", type: "string", required: true, description: "One short human-readable line for the live narration feed." },
      { name: "tone", type: "string", required: false, description: "Visual category. 'finding' = numeric result, 'alert' = warning, 'done' = wrap-up.", enum: ["info", "step", "finding", "alert", "done"], default: "step" },
    ],
  },
  news_feed: {
    category: "Core",
    name: "News Feed",
    description: "Search recent news articles from multiple providers. Use for current events, market news, and trend monitoring.",
    parameters: [
      { name: "query", type: "string", required: true, description: "News search query" },
      { name: "category", type: "string", required: false, description: "", enum: ["business", "technology", "science", "health", "general"], default: "general" },
      { name: "language", type: "string", required: false, description: "", default: "en" },
      { name: "from_date", type: "string", required: false, description: "Start date (YYYY-MM-DD)" },
      { name: "max_results", type: "integer", required: false, description: "", default: 10 },
      { name: "sort_by", type: "string", required: false, description: "", enum: ["relevancy", "popularity", "publishedAt"], default: "relevancy" },
    ],
  },
  notional_volume_score: {
    category: "Financial",
    name: "Notional Volume Score",
    description: "Pure-function KYC Indicator II tool. Takes annual contracted volume or notional in USD plus an optional commodity label and returns an integer 5-25 score, a rationale, and the band cut-off used. Bands: <$1M=5, $1-10M=10, $10-50M=15, $50-250M=20, >$250M=25. A small set of higher-risk commodities (arms, dual-use, crypto, precious metals, oil & gas) get a multiplier so a smaller absolute notional still maps to a higher KYC band. No external calls; deterministic and explainable.",
    parameters: [
      { name: "annual_notional_usd", type: "number", required: true, description: "Expected annual contracted volume or notional, in USD." },
      { name: "commodity", type: "string", required: false, description: "Optional free-text commodity / product (e.g. 'LNG', 'wood', 'arms')." },
    ],
  },
  open_meteo: {
    category: "Core",
    name: "Open-Meteo Weather",
    description: "Fetch free weather and marine forecasts from Open-Meteo. Use one of the shortcut location ids (USGC_HOUSTON, USGC_MONT_BELVIEU, NWE_ROTTERDAM, NWE_ANTWERP, FE_CHIBA, FE_SINGAPORE, ME_RAS_TANURA, etc.) for the common energy-trading hubs, or pass lat/lon for any point on earth. Set mode='marine' for wave height + swell + sea surface temp; default mode='atmosphere' for wind + temp + precipitation. Useful for: port-closure risk, hurricane funnel windows, vessel-routing impact, terminal slot disruption forecasts.",
    parameters: [
      { name: "location", type: "string", required: false, description: "Shortcut id (USGC_HOUSTON, NWE_ROTTERDAM, FE_CHIBA, ME_RAS_TANURA, etc.) or empty if you pass lat/lon." },
      { name: "lat", type: "number", required: false, description: "Latitude (omit if location set)." },
      { name: "lon", type: "number", required: false, description: "Longitude (omit if location set)." },
      { name: "mode", type: "string", required: false, description: "'atmosphere' returns wind, temperature, precipitation, pressure (the default). 'marine' returns wave height, wave period, swell, sea-surface temperature.", enum: ["atmosphere", "marine"], default: "atmosphere" },
      { name: "horizon_days", type: "integer", required: false, description: "Forecast horizon in days (1\u201316).", default: 7, minimum: 1, maximum: 16 },
    ],
  },
  options_data: {
    category: "Financial",
    name: "Options Market Data",
    description: "Listed options-market data: at-the-money implied volatility, 25-delta risk reversal (call IV minus put IV), put/call open-interest ratio, and a calm/nervous/skewed-up/skewed-down regime label. Works on any ticker with a public Yahoo option chain: futures (CL=F crude, NG=F natural gas, GC=F gold), equity indices (^SPX, ^VIX, SPY, QQQ), single stocks (AAPL, MSFT), and FX pairs that expose option data (EURUSD=X).",
    parameters: [
      { name: "action", type: "string", required: true, description: "snapshot: single expiry summary. term_structure: front three expiries' ATM IV + slope. regime: four-bucket market-state label for a UI badge.", enum: ["snapshot", "term_structure", "regime"] },
      { name: "symbol", type: "string", required: true, description: "Yahoo ticker. Futures use the =F suffix (CL=F for crude, NG=F for natural gas). Indices use the ^ prefix (^SPX, ^VIX). Equities are the plain ticker (AAPL). FX uses the =X suffix (EURUSD=X)." },
      { name: "expiry_index", type: "integer", required: false, description: "For action=snapshot only. Which expiry to read, indexed from 0 (front month). Ignored for term_structure and regime.", default: 0 },
    ],
  },
  patents_trademarks: {
    category: "Core",
    name: "Patents Trademarks",
    description: "Search granted US patents via USPTO PatentsView. Free, no API key. Filter by query text, assignee, inventor, date range. Returns title, abstract, grant date, assignee, and patent number.",
    parameters: [
      { name: "query", type: "string", required: false, description: "Free-text search of patent titles + abstracts." },
      { name: "assignee", type: "string", required: false, description: "Optional company / organization name filter." },
      { name: "inventor", type: "string", required: false, description: "Optional inventor name filter." },
      { name: "from_date", type: "string", required: false, description: "Earliest grant date YYYY-MM-DD." },
      { name: "to_date", type: "string", required: false, description: "Latest grant date YYYY-MM-DD." },
      { name: "limit", type: "integer", required: false, description: "", default: 10, minimum: 1, maximum: 50 },
    ],
  },
  pep_screening: {
    category: "Compliance & KYC",
    name: "PEP Screening",
    description: "Screen a person against Politically Exposed Persons (PEP) lists \u2014 heads of state, cabinet, parliamentarians, senior judges, central bank governors, senior military, state-owned enterprise execs, ambassadors, plus family members and close associates. Mandated by FATF Rec. 12, EU AMLD-6, UK MLR 2017, BSA/PATRIOT Act, MAS Notice 626, Canada PCMLTFA, and every comparable AML regime. Combines three independent signal sources \u2014 OpenSanctions PEP dataset (900k+ entries, 180+ jurisdictions, CC-BY), Wikidata SPARQL (live P39 position statements \u2014 catches newly-elected officials faster than bulk feeds), and per-country government roster scrapers (UK Parliament API, US congress.gov, bundestag.de, assemblee-nationale.fr, europarl.europa.eu, parlament.ch, riksdagen.se). Classifies each hit as Domestic / Foreign / International Organisation / Family / Close Associate / Former PEP (configurable 12-24 month lookback) / Not PEP. Returns name, position, jurisdiction, office dates, and confidence 0-100. Also produces an L/M/H risk grade. Set OPENSANCTIONS_API_KEY for higher rate limits; CONGRESS_GOV_API_KEY for US congress coverage. Use cases: KYC onboarding, correspondent banking, private banking client acceptance, insurance underwriting, real-estate agent due diligence, lawyer/notary client screening, casino enhanced DD.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Full legal name of the person to screen." },
      { name: "jurisdiction", type: "string", required: false, description: "ISO 3166-1 alpha-2 code (e.g. 'GB', 'US', 'DE') of the country where the screened party resides or operates. Biases Wikidata + enables government-roster check." },
      { name: "also_check_aliases", type: "array", required: false, description: "Additional spellings, maiden names, patronymics, transliterations.", items: { type: "string" } },
      { name: "former_pep_lookback_months", type: "integer", required: false, description: "How far back to still flag someone as Former PEP after leaving office. 18 months is FATF's common guidance; EU requires 'at least 12 months'. Set 0 to drop former PEPs entirely.", default: 18, minimum: 0, maximum: 120 },
      { name: "sources", type: "array", required: false, description: "Which sources to query. Omit for ALL.", items: { type: "string" } },
      { name: "threshold", type: "integer", required: false, description: "", default: 85, minimum: 50, maximum: 100 },
    ],
  },
  persona_rag: {
    category: "Meetings",
    name: "Persona RAG",
    description: "Retrieve from the executing user's own persona knowledge. Use this when the agent needs to answer AS the user (their notes, files, meeting context). Only the user's own items are ever searched. Inside a meeting only the scopes authorized for that meeting are allowed, and any other scope is denied. Returns text chunks with source citations.",
    parameters: [
      { name: "query", type: "string", required: true, description: "What you're looking for, phrased as a question or topic." },
      { name: "scope", type: "string", required: false, description: "Persona scope to query, for example 'self' or 'client:acme'. In a meeting it must be one of the meeting's authorized scopes, otherwise the result carries 'scope_denied'.", default: "self" },
      { name: "top_k", type: "integer", required: false, description: "", default: 5, minimum: 1, maximum: 15 },
      { name: "meeting_id", type: "string", required: false, description: "Optional. The meeting this lookup is for. A meeting bound to this run is enforced whether or not this is set." },
    ],
  },
  phmsa_lookup: {
    category: "Core",
    name: "Phmsa Lookup",
    description: "Search PHMSA for a US pipeline operator by name. Returns the operator ID(s) + a link to the public operator profile. Public free endpoint, no key. No mock data.",
    parameters: [
      { name: "legal_name", type: "string", required: true, description: "" },
      { name: "max_results", type: "integer", required: false, description: "", default: 10, minimum: 1, maximum: 50 },
    ],
  },
  pii_redactor: {
    category: "Data & Search",
    name: "PII Redactor",
    description: "Detect and redact PII (SSN, credit cards, emails, phone numbers, IPs, dates of birth) from text. Supports mask, hash, and remove strategies.",
    parameters: [
      { name: "text", type: "string", required: true, description: "Text to scan for PII" },
      { name: "strategy", type: "string", required: false, description: "", enum: ["mask", "remove", "detect_only"], default: "mask" },
      { name: "entity_types", type: "array", required: false, description: "PII types to detect. Default: all types.", items: { type: "string" } },
    ],
  },
  plotly_chart: {
    category: "Multi-Modal",
    name: "Plotly Chart",
    description: "Build a Plotly figure spec (JSON) from structured data \u2014 line, bar, scatter, pie/donut, heatmap. Returns the spec; the UI / notebook / exporter renders it. Use this when an agent needs to show a trend visually rather than as a number table.",
    parameters: [
      { name: "chart_type", type: "string", required: true, description: "", enum: ["line", "bar", "scatter", "pie", "heatmap"], default: "line" },
      { name: "title", type: "string", required: false, description: "" },
      { name: "x_label", type: "string", required: false, description: "" },
      { name: "y_label", type: "string", required: false, description: "" },
      { name: "series", type: "array", required: false, description: "line/bar: [{name, x:[], y:[], smooth?}]", items: { type: "object" } },
      { name: "points", type: "array", required: false, description: "scatter: [{x, y, label?}]", items: { type: "object" } },
      { name: "slices", type: "array", required: false, description: "pie: [{label, value}]", items: { type: "object" } },
      { name: "donut", type: "boolean", required: false, description: "pie only \u2014 render as donut." },
      { name: "z", type: "any", required: false, description: "heatmap: 2D array of values." },
      { name: "x", type: "any", required: false, description: "heatmap x labels (optional)." },
      { name: "y", type: "any", required: false, description: "heatmap y labels (optional)." },
      { name: "colorscale", type: "string", required: false, description: "heatmap colorscale name." },
    ],
  },
  port_constraints: {
    category: "Financial",
    name: "Port Constraints (UN/LOCODE)",
    description: "UN/LOCODE port database with vessel-level berth compatibility checks. Knows ~25 liquid-bulk ports (US Gulf, USAC, NW Europe, MED, MEG, Far East, India, Africa) plus Suez/Panama canal transit constraints. Three actions: port (full spec card), list (enumerate all), check (compatibility for a vessel_class + locode: returns compatible/borderline/incompatible with a breakdown of draught, LOA, beam, air-draught, product-handling).",
    parameters: [
      { name: "action", type: "string", required: true, description: "", enum: ["port", "list", "check"] },
      { name: "locode", type: "string", required: false, description: "UN/LOCODE \u2014 e.g. USHOU, NLRTM, SGSIN, JPYOK" },
      { name: "vessel_class", type: "string", required: false, description: "VLGC, MGC, VLCC, Suezmax, Aframax, LR2, LR1, MR2, etc." },
      { name: "product", type: "string", required: false, description: "Optional \u2014 confirms the port handles this product (lpg, gasoline, diesel, etc.)." },
    ],
  },
  presentation_analyzer: {
    category: "Data & Search",
    name: "Presentation Analyzer",
    description: "Analyze PowerPoint presentations (.pptx): extract slide content, speaker notes, images, tables, charts, slide layouts, and master slides. Provides structured overview of presentation flow, content density per slide, and text extraction.",
    parameters: [
      { name: "file_path", type: "string", required: false, description: "Path to the PowerPoint file (.pptx)" },
      { name: "operation", type: "string", required: false, description: "Analysis operation", enum: ["overview", "slide", "all_text", "notes", "tables", "search"], default: "overview" },
      { name: "slide_number", type: "integer", required: false, description: "Specific slide number to analyze (1-indexed)" },
      { name: "search_term", type: "string", required: false, description: "Text to search across slides" },
    ],
  },
  realized_vol_calc: {
    category: "Financial",
    name: "Realized Vol Calc",
    description: "Compute realized volatility (annualized), 4-week momentum and a naive drift estimate from a price history array. Inputs are daily closes. Use to calibrate Monte Carlo forward curves on illiquid hubs.",
    parameters: [
      { name: "prices", type: "array", required: true, description: "Daily closing prices, oldest first.", items: { type: "number" } },
      { name: "lookback_days", type: "integer", required: false, description: "Window for vol/drift. 60 \u2248 3 trading months.", default: 60 },
      { name: "periods_per_year", type: "integer", required: false, description: "Trading periods per year for annualisation.", default: 252 },
    ],
  },
  recall_trajectory: {
    category: "Pipeline",
    name: "Recall Trajectory",
    description: "Retrieve up to K past trajectories whose stored intent text overlaps the new query. Use it before planning a multi-step fan-out: if a near-identical question was previously answered with N successful sub-agent calls, adapt that plan instead of re-discovering it. Returns each trajectory's intent, the agents that were invoked, and a short summary of the synthesised brief.",
    parameters: [
      { name: "query", type: "string", required: true, description: "Plain-English description of the new task." },
      { name: "top_k", type: "integer", required: false, description: "", default: 3, minimum: 1, maximum: 10 },
      { name: "min_overlap_terms", type: "integer", required: false, description: "", default: 2, minimum: 1, maximum: 10 },
    ],
  },
  redis_stream_consumer: {
    category: "Integrations",
    name: "Redis Stream Consumer",
    description: "Consume messages from a Redis Stream. Ideal for real-time event processing, IoT sensor data, and inter-agent communication. Supports consumer groups for load balancing.",
    parameters: [
      { name: "stream", type: "string", required: true, description: "Redis stream name (e.g., 'sensor:temperature', 'orders:new')" },
      { name: "group", type: "string", required: false, description: "Consumer group name (created if not exists)" },
      { name: "consumer", type: "string", required: false, description: "Consumer name within the group" },
      { name: "count", type: "integer", required: false, description: "Max messages to read", default: 10 },
      { name: "block_ms", type: "integer", required: false, description: "Block for N ms waiting for messages (0 = no block)", default: 0 },
      { name: "acknowledge", type: "boolean", required: false, description: "Acknowledge messages after reading", default: true },
    ],
  },
  redis_stream_publisher: {
    category: "Integrations",
    name: "Redis Stream Publisher",
    description: "Publish messages to a Redis Stream. Use for inter-agent communication, event broadcasting, and IoT data ingestion pipelines.",
    parameters: [
      { name: "stream", type: "string", required: true, description: "Redis stream name" },
      { name: "data", type: "object", required: true, description: "Message data (key-value pairs)" },
      { name: "maxlen", type: "integer", required: false, description: "Max stream length (oldest trimmed)", default: 10000 },
    ],
  },
  refined_products_forwards: {
    category: "Financial",
    name: "Refined Products Forwards + Cracks",
    description: "Refined-products forward curves and crack spreads. Pulls continuous-front futures from Yahoo (RB=F gasoline, HO=F ULSD/heating oil, CL=F WTI, BZ=F Brent, NG=F Henry Hub) and computes the standard 3-2-1 crack spread or a 1-1 single-product crack. Three actions: curve (front-month settle for a product), crack_spread (3-2-1 or product-vs-crude in $/bbl), history (N days of daily settles). Real, citable Yahoo Finance values; no API key required.",
    parameters: [
      { name: "action", type: "string", required: true, description: "", enum: ["curve", "crack_spread", "history"] },
      { name: "product", type: "string", required: false, description: "rbob/gasoline, heating_oil/ulsd/diesel/gasoil, wti/crude_wti, brent/crude_brent, natural_gas, propane, naphtha" },
      { name: "crack_type", type: "string", required: false, description: "", enum: ["3-2-1", "gasoline-vs-wti", "diesel-vs-wti", "gasoline-vs-brent", "diesel-vs-brent"], default: "3-2-1" },
      { name: "lookback_days", type: "integer", required: false, description: "", default: 30, minimum: 5, maximum: 365 },
    ],
  },
  regex_extractor: {
    category: "Data & Search",
    name: "Regex Extractor",
    description: "Extract data from text using regular expressions. Supports custom regex patterns and preset patterns for common data types: email, url, phone, ip_address, date_us, date_iso, currency (prices in $, \u00a3, \u20ac, \u00a5 or \u20b9), currency_usd, percentage, uuid, ppa_price, energy_capacity, contract_reference. Can also search/replace, split text, and validate patterns.",
    parameters: [
      { name: "text", type: "string", required: true, description: "Text to search in" },
      { name: "operation", type: "string", required: false, description: "Regex operation", enum: ["extract", "extract_preset", "replace", "split", "validate", "list_presets"], default: "extract" },
      { name: "pattern", type: "string", required: false, description: "Custom regex pattern" },
      { name: "preset", type: "string", required: false, description: "Preset pattern name (e.g. 'email', 'currency' for prices in any currency, 'currency_usd' for dollars only, 'ppa_price')" },
      { name: "presets", type: "array", required: false, description: "Multiple preset patterns to extract at once", items: { type: "string" } },
      { name: "replacement", type: "string", required: false, description: "Replacement string for replace operation" },
      { name: "flags", type: "array", required: false, description: "Regex flags", items: { type: "string" } },
      { name: "group", type: "integer", required: false, description: "Capture group number to extract (default: 0 = full match)", default: 0 },
    ],
  },
  regulatory_enforcement: {
    category: "Compliance & KYC",
    name: "Regulatory Enforcement",
    description: "Primary-source regulatory enforcement and litigation lookup. Hits authoritative regulator and court bulletins directly \u2014 SEC EDGAR litigation releases, DOJ press releases, FCA final notices/decisions, BaFin sanctions register, ASIC enforceable undertakings, MAS regulatory actions, CJEU judgments \u2014 and public court-litigation indices (CourtListener RECAP, BAILII UK/IE, CanLII, EU Curia). Each hit is structured with `authority`, `action_type` (fine / settlement / cease-and-desist / criminal charge / civil suit / debarment / licence revocation / judgment), `date`, `fine_amount_usd` where extractable, `title`, `summary`, a direct `primary_source_url` to the filing, and a 0-100 name-match confidence. Complements `adverse_media`: adverse media covers press reporting on wrongdoing; this tool surfaces the primary-source filings themselves. Use for enhanced DD on regulated sectors (financial services, energy, healthcare, defence), litigation screening in M&A due diligence, vendor onboarding for any regulated counterparty, and sanctions-package exposure mapping. No paid APIs \u2014 all sources are free and public. Name matching uses fuzzy SequenceMatcher with substring boost; default 70 threshold filters out accidental name overlap.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Legal name of person or entity to screen." },
      { name: "sources", type: "array", required: false, description: "Subset of sources. 'all' by default.", items: { type: "string" } },
      { name: "min_confidence", type: "integer", required: false, description: "", default: 75, minimum: 50, maximum: 100 },
    ],
  },
  risk_analyzer: {
    category: "Financial",
    name: "Risk Analyzer",
    description: "Perform quantitative risk analysis including Monte Carlo simulation, sensitivity analysis (tornado diagrams), scenario modeling (best/base/worst), risk scoring matrices, probability distributions, and Value at Risk (VaR). Useful for evaluating financial risks, project risks, and contract exposures.",
    parameters: [
      { name: "analysis_type", type: "string", required: true, description: "Type of risk analysis to perform", enum: ["monte_carlo", "sensitivity", "scenario", "risk_matrix", "var", "expected_value"] },
      { name: "params", type: "object", required: true, description: "Analysis-specific parameters" },
    ],
  },
  sample_plant: {
    category: "Core",
    name: "Sample Plant",
    description: "A simulated plant for trying autonomy. 'read' returns pressure_bar, setpoint_bar, demand, any alarm and a note on how it responds. 'set_setpoint' sets setpoint_bar. Pressure settles to about setpoint_bar x demand within 30 seconds, give or take 0.1 bar, and demand drifts slowly on its own. Normal pressure is 4.0 to 5.0 bar.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "read the plant, or set a new pressure setpoint", enum: ["read", "set_setpoint"] },
      { name: "setpoint_bar", type: "number", required: false, description: "New pressure setpoint in bar, for set_setpoint" },
    ],
  },
  sanctions_screening: {
    category: "Compliance & KYC",
    name: "Sanctions Screening",
    description: "Screen a person or company name against the world's major sanctions lists \u2014 OFAC SDN, OFAC Consolidated (non-SDN), EU Consolidated, UN Security Council, UK HMT OFSI, Canada OSFI, Australia DFAT, Switzerland SECO. Uses public authoritative feeds (no paid API) with fuzzy matching (token-sort + sequence ratio) and AKA alias expansion so that 'Smith, John' matches 'John Smith' and reordered transliterations are caught. Returns per-list hits with confidence 0-100, matched alias, sanctions programmes, and source URLs for audit. Use for: KYC onboarding, ongoing counterparty monitoring, vendor screening, payment screening, pre-trade checks, and any jurisdiction requiring AML/CFT compliance (FATF Rec. 6). Set `threshold` lower (70-80) for investigative sweeps, higher (90+) for high-precision gates. Lists are cached 6 hours per source; override with `refresh=true`.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Full legal name of the entity or individual to screen." },
      { name: "entity_type", type: "string", required: false, description: "Filter by entity type. Use 'any' unless you have high confidence the target is strictly one.", enum: ["individual", "entity", "any"], default: "any" },
      { name: "lists", type: "array", required: false, description: "Subset of lists to check. Omit for ALL.", items: { type: "string" } },
      { name: "threshold", type: "integer", required: false, description: "Minimum fuzzy match score (0-100) to report as a hit. 85 = good KYC default; 70-80 for exploratory sweeps; 92+ for high-precision gating.", default: 85, minimum: 50, maximum: 100 },
      { name: "max_hits_per_list", type: "integer", required: false, description: "", default: 5, minimum: 1, maximum: 20 },
      { name: "refresh", type: "boolean", required: false, description: "Force re-download even if cache is fresh.", default: false },
      { name: "also_check_aliases", type: "array", required: false, description: "Additional names/spellings to also screen (e.g. trading names, Cyrillic/Arabic transliterations).", items: { type: "string" } },
    ],
  },
  sandboxed_job: {
    category: "Enterprise",
    name: "Sandboxed Job",
    description: "Run a one-shot command in an isolated container. Auto-selects Kubernetes Jobs when running inside a cluster, or local Docker otherwise \u2014 same interface, same result shape. Hardened by default: read-only FS, no capabilities, no network (unless SANDBOXED_JOB_ALLOW_NETWORK=true), cpu+memory limits, activeDeadline timeout. Requires SANDBOXED_JOB_ENABLED=true and image must be in SANDBOXED_JOB_ALLOWED_IMAGES.",
    parameters: [
      { name: "image", type: "string", required: true, description: "Container image (must be in the allow-list). Examples: 'python:3.12-slim', 'alpine:3.20', 'pandoc/core:3.5'." },
      { name: "command", type: "string", required: true, description: "Shell command to run inside the container." },
      { name: "timeout_seconds", type: "integer", required: false, description: "", default: 60, minimum: 5, maximum: 1800 },
      { name: "memory_mb", type: "integer", required: false, description: "", default: 512, minimum: 64, maximum: 8192 },
      { name: "cpu_limit", type: "number", required: false, description: "", default: 1.0, minimum: 0.1, maximum: 4.0 },
      { name: "network", type: "boolean", required: false, description: "Allow network. Only effective if SANDBOXED_JOB_ALLOW_NETWORK=true on the host.", default: false },
      { name: "env", type: "object", required: false, description: "Env vars to set inside the container. Keys must be valid shell identifiers." },
      { name: "stdin", type: "string", required: false, description: "Optional stdin piped into the command." },
      { name: "stdin_bytes_b64", type: "string", required: false, description: "Binary stdin payload, base64-encoded. Takes precedence over `stdin`. Used by code_asset to deliver a tar.gz of the asset contents without needing HTTP access." },
    ],
  },
  scenario_planner: {
    category: "Enterprise",
    name: "Scenario Planner",
    description: "Run structured what-if scenario analysis with parameter sweeps. Define base values and variations for any set of numeric parameters, then compute outcomes across all combinations. Use for pricing sensitivity, budget planning, risk assessment, or strategic option evaluation.",
    parameters: [
      { name: "parameters", type: "object", required: true, description: "Parameter definitions. Each key is a parameter name, value is an object with: base (number, required), range ([low, high], optional), steps (int, optional, default 5), unit (string, optional). Example: {\"revenue\": {\"base\": 1000000, \"range\": [800000, 1200000], \"steps\": 5, \"unit\": \"USD\"}}" },
      { name: "formula", type: "string", required: true, description: "Expression using parameter names and basic math operators (+, -, *, /, **, min, max, abs). Example: \"revenue * (1 - tax_rate) - costs\"" },
      { name: "output_name", type: "string", required: false, description: "Label for the computed value (default: 'outcome')" },
      { name: "scenarios", type: "array", required: false, description: "Named scenario presets with parameter overrides. Example: [{\"name\": \"bull\", \"overrides\": {\"revenue\": 1500000}}]", items: { type: "object" } },
    ],
  },
  schema_portfolio_tool: {
    category: "Financial",
    name: "Portfolio \u2014 Schema-Driven",
    description: "Schema-driven portfolio tool for PPA / gas / tolling contracts. Reads its schema from portfolio_schemas at runtime so the same tool powers energy desks and any standalone app that registers a schema.",
    parameters: [],
  },
  schema_validator: {
    category: "Data & Search",
    name: "Schema Validator",
    description: "Validate JSON data against a schema, generate schema from sample data, or coerce data to match a schema. Ensures pipeline outputs are well-formed.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Operation to perform", enum: ["validate", "generate_schema", "coerce"] },
      { name: "data", type: "any", required: true, description: "The data to validate or analyze" },
      { name: "schema", type: "object", required: false, description: "JSON Schema to validate against (for 'validate' and 'coerce')" },
    ],
  },
  scope_gate: {
    category: "Meetings",
    name: "Scope Gate",
    description: "Check whether a meeting question is inside the user-declared topic allow-list. Returns {decision: 'answer'|'defer'|'decline', reason: str}. Call this BEFORE formulating an answer \u2014 if the decision is 'defer', call defer_to_human; if 'decline', call meeting_speak with a polite decline.",
    parameters: [
      { name: "meeting_id", type: "string", required: true, description: "" },
      { name: "question", type: "string", required: true, description: "" },
    ],
  },
  semantic_diff: {
    category: "Data & Search",
    name: "Semantic Diff",
    description: "Diff two strings or two JSON objects, producing structured add/remove/change records. Text mode also returns a unified diff + similarity ratio. Use this BEFORE asking an LLM 'what changed' \u2014 it cuts the LLM's input down by 10x.",
    parameters: [
      { name: "mode", type: "string", required: false, description: "", enum: ["text", "json"], default: "text" },
      { name: "left", type: "any", required: true, description: "Original (text or JSON object)." },
      { name: "right", type: "any", required: true, description: "Updated (text or JSON object)." },
      { name: "label_left", type: "string", required: false, description: "", default: "v1" },
      { name: "label_right", type: "string", required: false, description: "", default: "v2" },
    ],
  },
  sentiment_analyzer: {
    category: "Data & Search",
    name: "Sentiment Analyzer",
    description: "Analyze market sentiment from text, news, or structured data. Produces sentiment scores, trend direction, volatility indicators, and confidence intervals. Use for trading signals, risk assessment, competitive intelligence, or public opinion tracking.",
    parameters: [
      { name: "texts", type: "array", required: true, description: "News headlines, analyst reports, social media posts, or any text corpus to analyze", items: { type: "string" } },
      { name: "domain", type: "string", required: false, description: "Industry context for domain-specific scoring adjustments (e.g. 'energy', 'tech', 'healthcare', 'commodities', 'finance', 'agriculture', 'real_estate')" },
      { name: "aggregation", type: "string", required: false, description: "How to combine individual scores: simple_average, weighted_recent (recency-weighted), or momentum (emphasizes direction of change). Default: weighted_recent", enum: ["simple_average", "weighted_recent", "momentum"] },
    ],
  },
  source_check: {
    category: "Sources & Watch",
    name: "Source Check",
    description: "Ask for a watched source to be checked now instead of waiting for its schedule, and wait for the result: unchanged, changed (with a summary and change_id for source_diff) or an error. Paused sources are not checked, a person must resume them.",
    parameters: [
      { name: "source", type: "string", required: true, description: "The source id, or its exact name, from source_list" },
      { name: "wait_seconds", type: "integer", required: false, description: "How long to wait for the result, up to 120", default: 60 },
    ],
  },
  source_diff: {
    category: "Sources & Watch",
    name: "Source Diff",
    description: "Show what changed in a watched source: lines added and removed for text, or rows added, removed and changed for tables, with a summary, a materiality hint and citations for both snapshots. Give change_id, or a source to get its latest change and a list of earlier ones.",
    parameters: [
      { name: "change_id", type: "string", required: false, description: "A change id, from a source.changed event or an earlier call" },
      { name: "source", type: "string", required: false, description: "The source id, or its exact name, from source_list" },
      { name: "max_lines", type: "integer", required: false, description: "How many changed lines or rows to return, up to 2000", default: 400 },
    ],
  },
  source_list: {
    category: "Sources & Watch",
    name: "Source List",
    description: "List the authoritative sources this tenant watches for changes, such as policy and tariff pages, guidance PDFs, data files and feeds, with when each was last checked and last changed. Call this first to find a source id for source_snapshot_get, source_diff or source_check.",
    parameters: [
      { name: "query", type: "string", required: false, description: "Optional words to match in the name or URL" },
      { name: "jurisdiction", type: "string", required: false, description: "Optional jurisdiction, such as EU" },
      { name: "tag", type: "string", required: false, description: "Optional tag" },
      { name: "changed_since", type: "string", required: false, description: "Optional ISO date. Only sources that changed on or after it." },
    ],
  },
  source_snapshot_get: {
    category: "Sources & Watch",
    name: "Source Snapshot Get",
    description: "Read the retained text of a watched source, the latest snapshot by default or a given one, with citation details (URL, retrieval time, SHA-256). Quote and cite from this rather than the live page, because snapshots never change. Long texts come in pages, use offset to continue.",
    parameters: [
      { name: "source", type: "string", required: false, description: "The source id, or its exact name, from source_list" },
      { name: "snapshot_id", type: "string", required: false, description: "Optional snapshot id. Without it the latest snapshot is used." },
      { name: "offset", type: "integer", required: false, description: "Character offset to start from", default: 0 },
      { name: "max_chars", type: "integer", required: false, description: "How many characters to return, up to 60000", default: 20000 },
      { name: "find", type: "string", required: false, description: "Optional words to look for. The page returned starts a little before the first match." },
    ],
  },
  speech_to_text: {
    category: "Multi-Modal",
    name: "Speech to Text",
    description: "Transcribe audio files to text using OpenAI Whisper. Supports MP3, WAV, M4A, WebM. Returns transcription with timestamps.",
    parameters: [
      { name: "audio_url", type: "string", required: true, description: "URL or file path to audio file" },
      { name: "language", type: "string", required: false, description: "Language code (e.g., 'en', 'es', 'fr'). Auto-detected if omitted." },
    ],
  },
  spg_ratings_api: {
    category: "Financial",
    name: "Spg Ratings Api",
    description: "Fetch current issuer credit rating + outlook from S&P Global Ratings. Needs SPG_RATINGS_API_KEY and SPG_RATINGS_API_URL, set under Admin -> Tool Configuration, (provided by S&P under a Capital IQ contract). Without keys the tool returns needs_configuration; never fabricates a rating.",
    parameters: [
      { name: "legal_name", type: "string", required: false, description: "" },
      { name: "ticker", type: "string", required: false, description: "" },
      { name: "lei", type: "string", required: false, description: "20-char Legal Entity Identifier" },
    ],
  },
  spreadsheet_analyzer: {
    category: "Data & Search",
    name: "Spreadsheet Analyzer",
    description: "Analyze Excel workbooks and spreadsheets with advanced operations: read multiple sheets, extract cell ranges, analyze formulas, compute cross-sheet references, generate pivot tables, detect data types per column, identify merged cells and formatting patterns, compute statistics across sheets, and extract chart data. Supports .xlsx, .xls, .csv, and .tsv formats.",
    parameters: [
      { name: "file_path", type: "string", required: false, description: "Path to the spreadsheet file" },
      { name: "operation", type: "string", required: false, description: "Analysis operation to perform", enum: ["overview", "read_sheet", "read_range", "formulas", "statistics", "pivot", "compare_sheets", "search"], default: "overview" },
      { name: "sheet_name", type: "string", required: false, description: "Sheet name to analyze (default: first sheet)" },
      { name: "cell_range", type: "string", required: false, description: "Cell range to read (e.g. 'A1:D10', 'B:B')" },
      { name: "search_term", type: "string", required: false, description: "Text to search for across all sheets" },
      { name: "pivot_rows", type: "string", required: false, description: "Column name for pivot table rows" },
      { name: "pivot_values", type: "string", required: false, description: "Column name for pivot table values" },
      { name: "pivot_func", type: "string", required: false, description: "Aggregation function for pivot", enum: ["sum", "count", "avg", "min", "max"], default: "sum" },
      { name: "max_rows", type: "integer", required: false, description: "Max rows to return (default: 100)", default: 100 },
    ],
  },
  structured_analyzer: {
    category: "Enterprise",
    name: "Structured Analyzer",
    description: "Extract structured data from ANY content using LLM analysis. Supports code (all languages), documents, and images. 10+ pre-built analysis types: security_audit, code_quality, architecture, dependencies, business_context, api_surface, test_coverage, documentation, compliance, performance, custom. Outputs structured JSON.",
    parameters: [
      { name: "content", type: "string", required: true, description: "The content to analyze (code, text, or description)" },
      { name: "analysis_type", type: "string", required: false, description: "Type of analysis to perform", enum: ["security_audit", "code_quality", "architecture", "dependencies", "business_context", "api_surface", "test_coverage", "documentation", "compliance", "performance", "custom"], default: "code_quality" },
      { name: "language", type: "string", required: false, description: "Programming language (auto-detected if omitted)" },
      { name: "custom_prompt", type: "string", required: false, description: "Custom analysis instructions (for 'custom' type)" },
      { name: "output_schema", type: "object", required: false, description: "Target JSON schema for output (optional, helps structure results)" },
    ],
  },
  structured_extractor: {
    category: "Data & Search",
    name: "Structured Extractor",
    description: "Extract structured data from unstructured text using a provided JSON schema. The tool calls an LLM to analyze the text and produce output matching your schema. Use for contract analysis, invoice processing, resume parsing, medical record extraction, or any document-to-data conversion.",
    parameters: [
      { name: "text", type: "string", required: true, description: "The source text to extract from (up to 100K characters)" },
      { name: "schema", type: "object", required: true, description: "A JSON object describing the output structure. Example: {\"company_name\": \"string\", \"revenue\": \"number\", \"employees\": [{\"name\": \"string\", \"role\": \"string\"}]}" },
      { name: "instructions", type: "string", required: false, description: "Additional extraction guidelines, e.g. 'Focus on financial terms. Use ISO dates. Extract ALL clauses, not just the first few.'" },
      { name: "model", type: "string", required: false, description: "LLM model to use for extraction", default: "claude-sonnet-4-5-20250929" },
      { name: "max_tokens", type: "integer", required: false, description: "Maximum output tokens for the LLM response", default: 8000 },
    ],
  },
  sub_pipeline: {
    category: "Pipeline",
    name: "Sub Pipeline",
    description: "Execute a nested pipeline as a single step within a parent pipeline. Define a set of pipeline nodes with dependencies, conditions, and data flow \u2014 they will be executed as a self-contained DAG. Results from the sub-pipeline are returned as the step output. Useful for composing reusable pipeline fragments and modular workflow design.",
    parameters: [
      { name: "nodes", type: "array", required: true, description: "List of pipeline node definitions for the sub-pipeline", items: { type: "object" } },
      { name: "context", type: "object", required: false, description: "Optional context data passed to the sub-pipeline", default: {} },
      { name: "timeout_seconds", type: "integer", required: false, description: "Timeout for the sub-pipeline execution", default: 60, minimum: 5, maximum: 300 },
    ],
  },
  subscribed_feed: {
    category: "Integrations",
    name: "Subscribed Feed",
    description: "Read the latest cached sample of a live feed (MQTT topic, Kafka stream, or HTTP poller). The feed itself is refreshed by a platform background job; this tool is the read side.",
    parameters: [
      { name: "feed_id", type: "string", required: true, description: "Identifier of a registered feed." },
      { name: "max_age_seconds", type: "integer", required: false, description: "Treat samples older than this as stale.", default: 60 },
      { name: "tenant_id", type: "string", required: false, description: "Tenant scope override \u2014 runtime injects via env normally." },
    ],
  },
  tavily_search: {
    category: "Core",
    name: "Tavily Search",
    description: "Advanced web search with AI-generated answers. Supports Tavily, Brave, SerpAPI, and Serper providers.",
    parameters: [
      { name: "query", type: "string", required: true, description: "Search query (1-6 words optimal)" },
      { name: "max_results", type: "integer", required: false, description: "", default: 5 },
      { name: "search_depth", type: "string", required: false, description: "", enum: ["basic", "advanced"], default: "basic" },
      { name: "topic", type: "string", required: false, description: "", enum: ["general", "news", "finance"], default: "general" },
      { name: "time_range", type: "string", required: false, description: "Optional time filter", enum: ["day", "week", "month", "year"] },
      { name: "include_answer", type: "boolean", required: false, description: "Include AI-generated answer (Tavily only)", default: true },
    ],
  },
  text_analyzer: {
    category: "Data & Search",
    name: "Text Analyzer",
    description: "Analyze text content: extract keywords and phrases, compute readability metrics, compare two texts for similarity, extract named entities (names, organizations, locations), parse document sections, compute word/sentence statistics, and generate text summaries with key points.",
    parameters: [
      { name: "text", type: "string", required: true, description: "Primary text to analyze" },
      { name: "second_text", type: "string", required: false, description: "Second text for comparison operations" },
      { name: "operation", type: "string", required: false, description: "Analysis operation to perform", enum: ["keywords", "statistics", "readability", "compare", "entities", "sections", "ngrams", "sentiment_words"], default: "statistics" },
      { name: "top_n", type: "integer", required: false, description: "Number of top results to return", default: 20 },
    ],
  },
  text_to_speech: {
    category: "Multi-Modal",
    name: "Text to Speech",
    description: "Generate speech audio from text using OpenAI TTS. Voices: alloy, echo, fable, onyx, nova, shimmer. Returns MP3 audio as base64 or saves to file.",
    parameters: [
      { name: "text", type: "string", required: true, description: "Text to convert to speech (max 4096 chars)" },
      { name: "voice", type: "string", required: false, description: "", enum: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"], default: "alloy" },
      { name: "output_path", type: "string", required: false, description: "File path to save audio (optional, returns base64 if omitted)" },
    ],
  },
  time_series_analyzer: {
    category: "Data & Search",
    name: "Time Series Analyzer",
    description: "Analyze time-series data: moving averages, anomaly detection (z-score), linear forecasting, trend decomposition, and correlation analysis.",
    parameters: [
      { name: "data", type: "array", required: true, description: "Array of numeric values (time-ordered)", items: { type: "number" } },
      { name: "timestamps", type: "array", required: false, description: "Optional ISO timestamps for each data point", items: { type: "string" } },
      { name: "operation", type: "string", required: true, description: "Analysis to perform", enum: ["moving_average", "anomaly_detection", "forecast", "statistics", "correlation"] },
      { name: "window", type: "integer", required: false, description: "Window size for moving average", default: 7 },
      { name: "forecast_periods", type: "integer", required: false, description: "Number of periods to forecast", default: 10 },
      { name: "z_threshold", type: "number", required: false, description: "Z-score threshold for anomaly detection", default: 2.0 },
      { name: "compare_data", type: "array", required: false, description: "Second series for correlation analysis", items: { type: "number" } },
    ],
  },
  translation: {
    category: "Multi-Modal",
    name: "Translation",
    description: "Translate text to a target language. Uses DeepL when DEEPL_API_KEY is set (best quality), falls back to LibreTranslate via LIBRETRANSLATE_URL. With no provider configured it returns an empty translation and a clear 'skipped' status \u2014 the caller agent should treat that as a recoverable condition.",
    parameters: [
      { name: "text", type: "string", required: true, description: "Text to translate." },
      { name: "target_lang", type: "string", required: true, description: "ISO 639-1 code: 'en', 'de', 'fr', 'es', 'ja', 'zh', etc." },
      { name: "source_lang", type: "string", required: false, description: "Optional source language (auto-detect if omitted)." },
      { name: "formality", type: "string", required: false, description: "DeepL only \u2014 formality hint.", enum: ["default", "more", "less", "prefer_more", "prefer_less"] },
    ],
  },
  tsdb_query: {
    category: "Integrations",
    name: "Tsdb Query",
    description: "Query the platform time-series store (TimescaleDB) for a metric over a time window. Supports raw rows or 5-min/1-hour aggregations. Connects via the TSDB_URL env var.",
    parameters: [
      { name: "metric", type: "string", required: true, description: "Metric name (e.g. 'vibration_rms', 'temp_c')." },
      { name: "asset_id", type: "string", required: false, description: "Asset identifier \u2014 usually equipment tag." },
      { name: "since", type: "string", required: true, description: "ISO-8601 lower bound, inclusive." },
      { name: "until", type: "string", required: false, description: "ISO-8601 upper bound, exclusive. Defaults to now." },
      { name: "aggregation", type: "string", required: false, description: "Aggregation bucket \u2014 none returns raw points.", enum: ["none", "avg_5m", "max_1h", "last"], default: "none" },
      { name: "table", type: "string", required: false, description: "Override target table name (defaults to 'metrics').", default: "metrics" },
      { name: "limit", type: "integer", required: false, description: "Maximum rows to return (caps at 10000).", default: 1000 },
    ],
  },
  twilio_sms: {
    category: "Integrations",
    name: "Twilio Sms",
    description: "Send SMS or WhatsApp messages via Twilio. Requires TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN; sender controlled by TWILIO_FROM_NUMBER (SMS) or TWILIO_WHATSAPP_FROM (WhatsApp). Without credentials it returns a 'not configured \u2014 would have sent' structured response so dev pipelines still progress.",
    parameters: [
      { name: "to", type: "string", required: true, description: "E.164 phone number ('+447700900123') or 'whatsapp:+447700900123'." },
      { name: "body", type: "string", required: true, description: "Message text. Max 1600 chars for SMS, longer for WhatsApp." },
      { name: "channel", type: "string", required: false, description: "", enum: ["sms", "whatsapp"], default: "sms" },
      { name: "media_url", type: "string", required: false, description: "Optional MMS/WhatsApp media URL (publicly reachable)." },
    ],
  },
  ubo_discovery: {
    category: "Compliance & KYC",
    name: "UBO Discovery",
    description: "Discover the Ultimate Beneficial Owners (UBOs) of a legal entity by walking the corporate ownership tree. Fuses four independent data feeds: (1) GLEIF (Global LEI Foundation, free, 2.3M+ entities with direct+ultimate parent relationships); (2) OpenCorporates (largest open company register, 200M+ companies, free tier 500/mo without key); (3) OpenOwnership cross-jurisdiction beneficial owner register; (4) per-jurisdiction registers \u2014 UK PSC (Companies House), Polish KRS, Dutch KvK, German Handelsregister, French INPI, Italian Registro Imprese, Spanish Registro Mercantil, Danish CVR, Finnish PRH, Swiss Zefix, Czech ARES, Indian MCA, Hong Kong CR, Australia ASIC, NZ Companies Office. Returns a structured ownership tree \u2014 nodes = entities/persons, edges = ownership %, with `effective_pct` computed as the path product for indirect holdings. Natural-person leaves are auto-classified UBO whenever effective_pct >= the configurable threshold (default 20% per EU AMLD-6 Art. 3(6); use 25% for US FinCEN CTA, 10% for UK PSC strict / Singapore enhanced DD). Chain gaps (bearer shares, trusts, unknown holders) are surfaced as `discovery_gaps` so a human knows exactly where to follow up. Also gives a flat list of UBOs for direct form filling. Uses OPENCORPORATES_API_KEY (optional, boosts 500\u219210k calls/mo) and COMPANIES_HOUSE_API_KEY (free, required for UK PSC lookups).",
    parameters: [
      { name: "company_name", type: "string", required: true, description: "Legal name of the entity to investigate." },
      { name: "country", type: "string", required: false, description: "ISO 3166-1 alpha-2 country code (e.g. 'GB', 'PL', 'NL'). Strongly recommended \u2014 massively reduces false positives in the GLEIF/OpenCorporates matches." },
      { name: "lei", type: "string", required: false, description: "Pre-known LEI if you have it \u2014 skips name disambiguation." },
      { name: "registration_number", type: "string", required: false, description: "Pre-known local registration number (e.g. UK company number, KRS number)." },
      { name: "ubo_threshold_pct", type: "number", required: false, description: "Minimum effective ownership % to classify a natural person as a UBO. Defaults 20 (EU AMLD-6). Use 25 for FinCEN CTA, 10 for UK PSC strict / enhanced DD.", default: 20.0, minimum: 1.0, maximum: 100.0 },
      { name: "max_depth", type: "integer", required: false, description: "Max ownership-tree depth to walk. 4 is enough for most private groups; 6+ for complex holding structures.", default: 4, minimum: 1, maximum: 8 },
      { name: "sources", type: "array", required: false, description: "Subset of sources to query. Defaults to ALL.", items: { type: "string" } },
    ],
  },
  unit_converter: {
    category: "Core",
    name: "Unit Converter",
    description: "Convert between units across multiple categories: energy (kWh, MWh, GWh, BTU, toe, boe), power (W, kW, MW, GW, hp), length, area (ha, acre), volume (L, bbl, gal), mass (kg, t, lb), temperature (C, F, K), pressure, speed, data storage, time, and carbon emissions (tCO2, kgCO2). Particularly useful for energy industry calculations involving PPAs and renewable energy projects.",
    parameters: [
      { name: "value", type: "number", required: true, description: "The numeric value to convert" },
      { name: "from_unit", type: "string", required: true, description: "Source unit (e.g. 'MWh', 'kg', 'acre')" },
      { name: "to_unit", type: "string", required: true, description: "Target unit (e.g. 'kWh', 'lb', 'ha')" },
      { name: "category", type: "string", required: false, description: "Unit category (auto-detected if omitted)" },
    ],
  },
  vector_search: {
    category: "Data & Search",
    name: "Vector Search",
    description: "Search the agent's knowledge base for relevant information. Returns the most relevant document chunks matching the query.",
    parameters: [
      { name: "query", type: "string", required: true, description: "The search query to find relevant documents" },
      { name: "top_k", type: "integer", required: false, description: "Number of results to return (default: 5)", default: 5 },
    ],
  },
  vessel_specs: {
    category: "Financial",
    name: "Vessel Specs + Density",
    description: "Vessel-class registry + product density table + volume/mass converter. Single source of truth for the arithmetic every freight-touching agent gets wrong: vessels are sold in m^3, cargoes are priced in MT, and the conversion factor (density) differs by product. Five actions: vessel (spec card for one class \u2014 VLGC/MGC/LGC/SGC for LPG, VLCC/Suezmax/Aframax/LR2/LR1/MR2/MR1/Handysize for CPP), density (kg/L for propane/butane/ammonia/naphtha/gasoline/jet/ULSD/gasoil/fuel oil/crude/methanol), convert (m^3<->MT or $/MT<->$/bbl for a named product), capacity (MT a class lifts for a named product), list (every supported vessel class or product). All values cited.",
    parameters: [
      { name: "action", type: "string", required: true, description: "vessel: spec card. density: kg/L for a product. convert: unit conversion (m^3<->MT or $/MT<->$/bbl). capacity: MT a vessel class lifts for a named product. list: enumerate classes or products.", enum: ["vessel", "density", "convert", "capacity", "list"] },
      { name: "vessel_class", type: "string", required: false, description: "VLGC, MGC, LGC, SGC, VLCC, Suezmax, Aframax, LR2, LR1, MR2, MR1, Handysize" },
      { name: "product", type: "string", required: false, description: "propane, butane, ammonia, lpg_mix, naphtha, gasoline, jet, ulsd, gasoil, fuel_oil, crude_wti, crude_brent, methanol" },
      { name: "from_unit", type: "string", required: false, description: "", enum: ["cbm", "mt", "bbl", "usd_per_mt", "usd_per_bbl"] },
      { name: "to_unit", type: "string", required: false, description: "", enum: ["cbm", "mt", "bbl", "usd_per_mt", "usd_per_bbl"] },
      { name: "value", type: "number", required: false, description: "" },
      { name: "list_kind", type: "string", required: false, description: "", enum: ["vessels", "products"], default: "vessels" },
    ],
  },
  weather: {
    category: "Core",
    name: "Weather",
    description: "Current weather and forecast for any location worldwide. Free, no API key. Accepts city names ('Berlin'), 'City, Country' ('Tokyo, Japan'), or raw 'lat,lon' coordinates. Returns temperature, wind, precipitation, and an N-day forecast with daily highs/lows.",
    parameters: [
      { name: "location", type: "string", required: true, description: "City name or 'lat,lon'" },
      { name: "forecast_days", type: "integer", required: false, description: "Number of forecast days (0 = current only).", default: 3, minimum: 0, maximum: 16 },
      { name: "units", type: "string", required: false, description: "metric = Celsius/km/h, imperial = Fahrenheit/mph.", enum: ["metric", "imperial"], default: "metric" },
    ],
  },
  weather_simulator: {
    category: "Enterprise",
    name: "Weather Simulator",
    description: "Simulate weather scenarios and their impact on operations. Generates solar irradiance, wind speed, temperature, precipitation, and extreme event probabilities for any location and time period. Use for energy yield, crop yield, logistics planning, insurance risk, or construction scheduling.",
    parameters: [
      { name: "location", type: "string", required: true, description: "City/region name or lat/lon pair (e.g. 'Berlin', '52.52,13.405')" },
      { name: "period_months", type: "integer", required: false, description: "Simulation horizon in months (default 12)", default: 12 },
      { name: "scenarios", type: "array", required: false, description: "Which scenarios to simulate. Options: base, optimistic, pessimistic, extreme (default: all four)", items: { type: "string" } },
      { name: "parameters", type: "array", required: false, description: "Weather parameters to include. Options: solar_irradiance, wind_speed, temperature, precipitation (default: all four)", items: { type: "string" } },
      { name: "seed", type: "integer", required: false, description: "Random seed for reproducibility (optional)" },
    ],
  },
  web_search: {
    category: "Core",
    name: "Web Search",
    description: "Search the web for current information. Returns a list of results with titles, URLs, and snippets.",
    parameters: [
      { name: "query", type: "string", required: true, description: "The search query" },
      { name: "max_results", type: "integer", required: false, description: "Maximum number of results to return", default: 5 },
    ],
  },
  windowed_state: {
    category: "Integrations",
    name: "Windowed State",
    description: "Per-asset sliding-window state primitive. Operations: append, query, count, pattern_match. Backed by Redis sorted-sets keyed by tenant + asset + window-name.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Which window operation to perform.", enum: ["append", "query", "count", "pattern_match"] },
      { name: "asset_id", type: "string", required: true, description: "Asset/tag identifier." },
      { name: "name", type: "string", required: true, description: "Window name (e.g. 'vibration', 'alarm_chain')." },
      { name: "payload", type: "any", required: false, description: "JSON payload (append). May include a 'label' field used by pattern_match." },
      { name: "since", type: "string", required: false, description: "ISO-8601 lower bound (query/count)." },
      { name: "until", type: "string", required: false, description: "ISO-8601 upper bound (query). Defaults to now." },
      { name: "pattern_seq", type: "array", required: false, description: "Expected suffix of recent labels (pattern_match).", items: { type: "string" } },
      { name: "max_age_seconds", type: "integer", required: false, description: "Auto-trim members older than this on append. Default 24h.", default: 86400 },
      { name: "tenant_id", type: "string", required: false, description: "Tenant scope override \u2014 runtime injects via env normally." },
    ],
  },
  world_bank: {
    category: "Data & Search",
    name: "World Bank",
    description: "Country-level macro/development indicators from the World Bank (GDP, population, inflation, CO2, renewables share, etc.). Free, no API key. Use ISO3 country codes ('USA', 'DEU', 'IND').",
    parameters: [
      { name: "country_code", type: "string", required: true, description: "ISO3 country code, e.g. USA, DEU, IND, ZAF. Use 'WLD' for world total." },
      { name: "indicator", type: "string", required: true, description: "Either a friendly alias (gdp_usd, gdp_per_capita, population, inflation, unemployment, co2_per_capita, renewable_pct, internet_users_pct, life_expectancy) or a raw World Bank indicator code (e.g. 'EN.ATM.CO2E.KT')." },
      { name: "start_year", type: "integer", required: false, description: "", default: 2018 },
      { name: "end_year", type: "integer", required: false, description: "", default: 2024 },
    ],
  },
  yahoo_finance: {
    category: "Financial",
    name: "Yahoo Finance",
    description: "Generic Yahoo Finance reader. One tool, every instrument: equities, indices, futures, FX, ETFs, FRED macro series. Use action='commodity_future' with a friendly alias (gold/silver/wti/brent/natgas_henry_hub/natgas_ttf/copper/corn/wheat/usdcny ...) or pass any raw Yahoo symbol. Configure per-tenant presets in /admin/tool-presets.",
    parameters: [
      { name: "action", type: "string", required: true, description: "stock_price/company_info/earnings/dividends for equities; economic_indicator for FRED (needs FRED_API_KEY); commodity_future for any commodity by alias or =F symbol; fx_rate for FX (alias or =X symbol); list_aliases returns the named-alias dictionary.", enum: ["stock_price", "company_info", "earnings", "dividends", "economic_indicator", "market_index", "commodity_future", "fx_rate", "list_aliases"] },
      { name: "symbol", type: "string", required: false, description: "Stock ticker (AAPL), FRED series (GDP, UNRATE), Yahoo future (CL=F, GC=F, NG=F), FX (CNY=X, EURUSD=X), or friendly alias (gold, wti, brent, natgas_henry_hub, natgas_ttf, corn, usdcny). Run action=list_aliases to see them all." },
      { name: "period", type: "string", required: false, description: "History period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max. Default 1y for equities, 90d for commodity_future/fx_rate (realized_vol_calc needs >=60 closes for its 60-day mean)." },
      { name: "history_days", type: "integer", required: false, description: "Optional shortcut for commodity_future/fx_rate: window in days. Overrides period; floored at 60 so the realized-vol 60-day mean has data." },
      { name: "region", type: "string", required: false, description: "Optional region tag for commodity_future/fx_rate spot cache isolation (e.g. EU, US, ASIA). Sharpens the cache key when the same ticker serves multiple regions." },
      { name: "as_of", type: "string", required: false, description: "Optional ISO date (YYYY-MM-DD) for spot cache partitioning. Defaults to today (UTC) so yesterday's value never bleeds into today's run." },
    ],
  },
  zapier_pass_through: {
    category: "Integrations",
    name: "Zapier Pass Through",
    description: "Pass-through to Zapier \u2014 list / run AI Actions (any of 6,000+ connector apps the user has exposed), or fire a Zapier 'Catch Hook' webhook. NLA needs ZAPIER_NLA_KEY; webhooks just need the URL the user copied from their Zap.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "", enum: ["list_actions", "run_action", "fire_webhook"], default: "list_actions" },
      { name: "action_id", type: "string", required: false, description: "run_action \u2014 the id from list_actions output." },
      { name: "instructions", type: "string", required: false, description: "run_action \u2014 natural-language instructions for the action." },
      { name: "params", type: "object", required: false, description: "run_action \u2014 explicit param overrides; merged with NL instructions." },
      { name: "webhook_url", type: "string", required: false, description: "fire_webhook \u2014 the full Zapier Catch Hook URL." },
      { name: "payload", type: "object", required: false, description: "fire_webhook \u2014 JSON payload to POST. Defaults to {}." },
    ],
  },
};

export function getToolDoc(toolId: string): ToolDoc | null {
  return TOOL_DOCS[toolId] || null;
}

export function getToolDescription(toolId: string): string {
  return TOOL_DOCS[toolId]?.description || toolId.replace(/_/g, " ");
}

export function getAllToolNames(): string[] {
  return Object.keys(TOOL_DOCS);
}

export function searchTools(query: string): string[] {
  if (!query) return Object.keys(TOOL_DOCS);
  const q = query.toLowerCase();
  const scored: { id: string; score: number }[] = [];

  for (const [id, doc] of Object.entries(TOOL_DOCS)) {
    let score = 0;
    if (id.toLowerCase().includes(q)) score += 10;
    if (doc.name.toLowerCase().includes(q)) score += 8;
    if (doc.category?.toLowerCase().includes(q)) score += 6;
    if (doc.description.toLowerCase().includes(q)) score += 4;
    if (doc.parameters.some(p => p.name.toLowerCase().includes(q))) score += 2;
    if (doc.parameters.some(p => p.description.toLowerCase().includes(q))) score += 1;
    if (doc.parameters.some(p => p.enum?.some(e => e.toLowerCase().includes(q)))) score += 1;
    if (score > 0) scored.push({ id, score });
  }

  return scored.sort((a, b) => b.score - a.score).map(s => s.id);
}

export function getToolsByCategory(): Record<string, { id: string; doc: ToolDoc }[]> {
  const result: Record<string, { id: string; doc: ToolDoc }[]> = {};
  for (const [id, doc] of Object.entries(TOOL_DOCS)) {
    const cat = doc.category || 'Other';
    if (!result[cat]) result[cat] = [];
    result[cat].push({ id, doc });
  }
  // Sort categories by TOOL_CATEGORIES order
  const ordered: Record<string, { id: string; doc: ToolDoc }[]> = {};
  for (const cat of TOOL_CATEGORIES) {
    if (result[cat]) ordered[cat] = result[cat];
  }
  if (result['Other']) ordered['Other'] = result['Other'];
  return ordered;
}

export function getToolCategory(toolId: string): string {
  return TOOL_DOCS[toolId]?.category || 'Other';
}

export function formatToolDocsForLLM(): string {
  return Object.entries(TOOL_DOCS).map(([id, doc]) => {
    const params = doc.parameters.map(p => {
      let line = `  - ${p.name} (${p.type}${p.required ? ", required" : ""}): ${p.description}`;
      if (p.enum) {
        line += ` [values: ${p.enum.join(", ")}]`;
      }
      if (p.default !== undefined) {
        line += ` (default: ${JSON.stringify(p.default)})`;
      }
      return line;
    }).join("\n");
    return `${id}: ${doc.description}\nParameters:\n${params}`;
  }).join("\n\n");
}
