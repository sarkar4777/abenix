/**
 * Exhaustive tool documentation for ALL 48 Abenix tools.
 * Auto-generated from tool input_schema definitions.
 * Used by: AI Builder, Builder config panel, Agent info page, Marketplace.
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
  'AI & Analysis',
  'Data & Search',
  'Web Search',
  'Financial',
  'Energy Market',
  'Knowledge Graph',
  'Compliance & KYC',
  'File & Document',
  'Code & Transform',
  'Integrations',
  'Communication',
  'Privacy & Safety',
  'Multi-Modal',
] as const;

export const TOOL_DOCS: Record<string, ToolDoc> = {
  agent_step: {
    category: "AI & Analysis",
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
  api_connector: {
    category: "Integrations",
    name: "Api Connector",
    description: "Connect to popular external services: send Slack messages, read/write Airtable records, interact with Notion databases, create Jira tickets, and push data to Google Sheets. Pre-configured connectors with simple interfaces for common integrations.",
    parameters: [
      { name: "service", type: "string", required: true, description: "Service and action to execute", enum: ["slack", "airtable_read", "airtable_write", "notion_query", "notion_create", "jira_create", "jira_search", "google_sheets_read", "google_sheets_append"] },
      { name: "params", type: "object", required: true, description: "Service-specific parameters" },
    ],
  },
  calculator: {
    category: "Code & Transform",
    name: "Calculator",
    description: "Evaluate a mathematical expression safely. Supports basic arithmetic, exponentiation, and math functions (sqrt, log, sin, cos, etc.).",
    parameters: [
      { name: "expression", type: "string", required: true, description: "The mathematical expression to evaluate, e.g. '(2 + 3) * 4'" },
    ],
  },
  cloud_storage: {
    category: "File & Document",
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
  code_executor: {
    category: "AI & Analysis",
    name: "Code Executor",
    description: "Execute Python code safely in a sandboxed environment. Supports complex data transformations, file generation (Excel, PDF, charts, PowerPoint), image processing, and algorithmic operations. Core: pandas, numpy, openpyxl, json, csv, re, math, datetime, collections, statistics, uuid, io, base64. Extended: scipy, matplotlib, seaborn, reportlab, fpdf, Pillow, bs4, pptx, sklearn, plotly, tabulate, xlsxwriter, lxml, zipfile. Can save files via save_export() or open(). Additional modules can be requested via extra_modules (LLM-validated). Does NOT support network or system access.",
    parameters: [
      { name: "code", type: "string", required: true, description: "Python code to execute. Use print() for output. Last expression is captured as result." },
      { name: "variables", type: "object", required: false, description: "Pre-defined variables available in the execution context as globals" },
      { name: "extra_modules", type: "array", required: false, description: "Additional Python modules to allow (LLM-validated for safety). E.g. ['sympy', 'networkx']. Modules with network/system access are rejected.", items: { type: "string" } },
    ],
  },
  csv_analyzer: {
    category: "File & Document",
    name: "Csv Analyzer",
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
    category: "Code & Transform",
    name: "Current Time",
    description: "Get the current date and time in UTC or a specified timezone. Supports IANA timezone names (e.g. 'America/New_York') and common abbreviations (EST, PST, GMT, CET, IST, JST, etc.).",
    parameters: [
      { name: "timezone", type: "string", required: false, description: "Timezone name (e.g. 'UTC', 'America/New_York', 'PST'). Defaults to UTC.", default: "UTC" },
    ],
  },
  data_exporter: {
    category: "File & Document",
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
    category: "Data & Search",
    name: "Data Merger",
    description: "Merge multiple data inputs into a single unified structure. Supports three strategies: 'flat' merges all inputs into one dictionary, 'nested' preserves each input under its original key, and 'comparison' creates a side-by-side labeled view. Ideal for fan-in pipeline steps that combine results from parallel branches.",
    parameters: [
      { name: "merge_strategy", type: "string", required: false, description: "Strategy for merging inputs: flat (single dict), nested (keyed), or comparison (labeled side-by-side)", enum: ["flat", "nested", "comparison"], default: "nested" },
      { name: "labels", type: "object", required: false, description: "Display labels for each input key (used with comparison strategy). Keys should match input keys, values are human-readable labels." },
    ],
  },
  database_query: {
    category: "Integrations",
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
    category: "Integrations",
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
    category: "Code & Transform",
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
  document_extractor: {
    category: "File & Document",
    name: "Document Extractor",
    description: "Extract structured data from documents. Parses tables into rows/columns, extracts key-value pairs (dates, amounts, percentages, names), identifies document sections and clauses, and returns structured JSON output. Works with text content directly or reads from files.",
    parameters: [
      { name: "text", type: "string", required: false, description: "Text content to extract from (use this OR file_path)" },
      { name: "file_path", type: "string", required: false, description: "Path to a file to extract from (use this OR text)" },
      { name: "extract_type", type: "string", required: false, description: "What to extract: tables, key_values, sections, entities, or all", enum: ["tables", "key_values", "sections", "entities", "all"], default: "all" },
      { name: "patterns", type: "array", required: false, description: "Optional custom regex patterns to search for", items: { type: "string" } },
    ],
  },
  email_sender: {
    category: "Communication",
    name: "Email Sender",
    description: "Send emails to one or more recipients with plain text or HTML content. Supports SMTP delivery in production and falls back to local file logging in development mode when SMTP is not configured. Useful for sending reports, notifications, alerts, and agent-generated content to users.",
    parameters: [
      { name: "to", type: "string", required: true, description: "Comma-separated list of recipient email addresses" },
      { name: "subject", type: "string", required: true, description: "Email subject line" },
      { name: "body", type: "string", required: true, description: "Email body content (plain text or HTML)" },
      { name: "format", type: "string", required: false, description: "Email body format", enum: ["text", "html"], default: "text" },
    ],
  },
  event_buffer: {
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
  kafka_consumer: {
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
  redis_stream_consumer: {
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
    name: "Redis Stream Publisher",
    description: "Publish messages to a Redis Stream. Use for inter-agent communication, event broadcasting, and IoT data ingestion pipelines.",
    parameters: [
      { name: "stream", type: "string", required: true, description: "Redis stream name" },
      { name: "data", type: "object", required: true, description: "Message data (key-value pairs)" },
      { name: "maxlen", type: "integer", required: false, description: "Max stream length (oldest trimmed)", default: 10000 },
    ],
  },
  file_reader: {
    category: "File & Document",
    name: "File Reader",
    description: "Read and extract text content from uploaded files. Supports PDF, DOCX, TXT, CSV, MD, and JSON formats.",
    parameters: [
      { name: "file_path", type: "string", required: true, description: "Path to the file to read" },
    ],
  },
  file_system: {
    category: "File & Document",
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
    description: "Perform advanced financial calculations including NPV (net present value), IRR (internal rate of return), LCOE (levelized cost of energy), DCF (discounted cash flow), loan amortization, price escalation modeling, bond pricing, WACC, depreciation schedules, and breakeven analysis. Returns detailed calculation breakdowns.",
    parameters: [
      { name: "calculation", type: "string", required: true, description: "Type of financial calculation to perform", enum: ["npv", "irr", "lcoe", "dcf", "amortization", "escalation", "bond_price", "wacc", "depreciation", "breakeven", "payback_period", "roi", "cagr"] },
      { name: "params", type: "object", required: true, description: "Calculation-specific parameters (see description for each calculation type)" },
    ],
  },
  github_tool: {
    category: "Integrations",
    name: "Github Tool",
    description: "Interact with the GitHub REST API to inspect repositories, read files, search code, list issues and pull requests, view commits, check CI workflows, and compare branches. Requires a GITHUB_TOKEN environment variable.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "GitHub operation to perform", enum: ["get_repo", "list_files", "read_file", "search_code", "list_issues", "list_pull_requests", "get_commits", "get_languages", "get_workflows", "compare_branches"] },
      { name: "owner", type: "string", required: true, description: "Repository owner (user or org)" },
      { name: "repo", type: "string", required: true, description: "Repository name" },
      { name: "path", type: "string", required: false, description: "File path (for read_file)", default: "" },
      { name: "query", type: "string", required: false, description: "Search query (for search_code)", default: "" },
      { name: "branch", type: "string", required: false, description: "Branch name", default: "main" },
      { name: "state", type: "string", required: false, description: "Issue/PR state filter", enum: ["open", "closed", "all"], default: "open" },
      { name: "per_page", type: "integer", required: false, description: "Results per page", default: 30, minimum: 1, maximum: 100 },
      { name: "base", type: "string", required: false, description: "Base branch for comparison", default: "main" },
      { name: "head", type: "string", required: false, description: "Head branch for comparison", default: "" },
    ],
  },
  http_client: {
    category: "Integrations",
    name: "Http Client",
    description: "Make HTTP requests to external APIs and web services. Supports GET, POST, PUT, DELETE, PATCH methods with custom headers and JSON payloads. Useful for integrating with third-party APIs, fetching data from REST endpoints, and interacting with web services. Respects sandbox domain restrictions.",
    parameters: [
      { name: "url", type: "string", required: true, description: "Full URL to request (must be HTTPS)" },
      { name: "method", type: "string", required: false, description: "HTTP method", enum: ["GET", "POST", "PUT", "DELETE", "PATCH"], default: "GET" },
      { name: "headers", type: "object", required: false, description: "Request headers as key-value pairs" },
      { name: "body", type: "object", required: false, description: "JSON request body (for POST/PUT/PATCH)", showWhen: { field: "method", values: ["POST", "PUT", "PATCH"] } },
      { name: "params", type: "object", required: false, description: "URL query parameters as key-value pairs" },
      { name: "bearer_token", type: "string", required: false, description: "Bearer token for Authorization header (convenience — alternatively set headers manually)" },
      { name: "timeout", type: "integer", required: false, description: "Request timeout in seconds", default: 15 },
      { name: "max_retries", type: "integer", required: false, description: "Number of retries on failure (with exponential backoff)", default: 0, minimum: 0, maximum: 5 },
    ],
  },
  human_approval: {
    category: "Privacy & Safety",
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
    category: "File & Document",
    name: "Image Analyzer",
    description: "Analyze images using AI vision models. Capabilities: describe content, extract text (OCR), read charts/graphs, detect objects, analyze diagrams, compare images. Supports URLs and local file paths.",
    parameters: [
      { name: "image_url", type: "string", required: true, description: "URL or local file path to the image (PNG, JPG, GIF, WebP)" },
      { name: "operation", type: "string", required: false, description: "Type of analysis to perform", enum: ["describe", "ocr", "chart_data", "objects", "diagram", "compare", "question"], default: "describe" },
      { name: "question", type: "string", required: false, description: "Specific question to answer about the image" },
      { name: "compare_url", type: "string", required: false, description: "Second image URL for comparison (only for 'compare' operation)" },
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
      { name: "auth_token", type: "string", required: false, description: "Override auth token (optional, uses env var if omitted)" },
    ],
  },
  json_transformer: {
    category: "Code & Transform",
    name: "Json Transformer",
    description: "Transform, query, and manipulate structured JSON data. Operations include: query (extract nested values by path), filter (select items matching conditions), flatten (convert nested structures to flat key-value), aggregate (sum, count, avg over arrays), reshape (pivot, group, transpose), merge (combine multiple objects), and diff (compare two JSON structures).",
    parameters: [
      { name: "data", type: "any", required: true, description: "JSON data to transform (object, array, or JSON string)" },
      { name: "operation", type: "string", required: true, description: "Transformation operation", enum: ["query", "filter", "flatten", "aggregate", "reshape", "merge", "diff", "schema"] },
      { name: "path", type: "string", required: false, description: "Dot-notation path for query (e.g. 'users.0.name', 'items[*].price')" },
      { name: "condition", type: "object", required: false, description: "Filter condition: {field: value} or {field: {op: value}}" },
      { name: "second_data", type: "any", required: false, description: "Second dataset for merge/diff operations" },
      { name: "group_by", type: "string", required: false, description: "Field name to group by for reshape" },
      { name: "agg_field", type: "string", required: false, description: "Field to aggregate" },
      { name: "agg_func", type: "string", required: false, description: "Aggregation function", enum: ["sum", "count", "avg", "min", "max", "list"], default: "sum" },
    ],
  },
  llm_call: {
    category: "AI & Analysis",
    name: "Llm Call",
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
    category: "AI & Analysis",
    name: "Llm Route",
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
  memory_forget: {
    category: "Knowledge Graph",
    name: "Memory Forget",
    description: "Delete a stored memory by key. Use this to remove outdated or incorrect information from the agent's persistent memory.",
    parameters: [
      { name: "key", type: "string", required: true, description: "The memory key to delete" },
    ],
  },
  memory_recall: {
    category: "Knowledge Graph",
    name: "Memory Recall",
    description: "Retrieve stored memories. Search by key, type, or get all memories sorted by importance. Use this at the start of conversations to recall context from previous interactions.",
    parameters: [
      { name: "key", type: "string", required: false, description: "Exact key to retrieve (optional \u2014 omit for search)" },
      { name: "search", type: "string", required: false, description: "Search term to find matching memories by key or value" },
      { name: "memory_type", type: "string", required: false, description: "Filter by memory type", enum: ["factual", "procedural", "episodic"] },
      { name: "limit", type: "integer", required: false, description: "Max memories to return (default 10)", default: 10 },
    ],
  },
  memory_store: {
    category: "Knowledge Graph",
    name: "Memory Store",
    description: "Store a piece of information in persistent memory. Use this to remember facts, procedures, or past events across conversations. Memories are scoped to this agent and persist until explicitly forgotten.",
    parameters: [
      { name: "key", type: "string", required: true, description: "A short, descriptive key for the memory (e.g., 'user_preferred_format', 'last_migration_status')" },
      { name: "value", type: "string", required: true, description: "The information to remember" },
      { name: "memory_type", type: "string", required: false, description: "Type of memory: factual (facts), procedural (how-to), episodic (past events)", enum: ["factual", "procedural", "episodic"], default: "factual" },
      { name: "importance", type: "integer", required: false, description: "Importance level 1-10 (higher = more important, retrieved first)", default: 5, minimum: 1, maximum: 10 },
    ],
  },
  pii_redactor: {
    category: "Privacy & Safety",
    name: "Pii Redactor",
    description: "Detect and redact PII (SSN, credit cards, emails, phone numbers, IPs, dates of birth) from text. Supports mask, hash, and remove strategies.",
    parameters: [
      { name: "text", type: "string", required: true, description: "Text to scan for PII" },
      { name: "strategy", type: "string", required: false, description: "Redaction strategy", enum: ["mask", "remove", "detect_only"], default: "mask" },
      { name: "entity_types", type: "array", required: false, description: "PII types to detect. Default: all types.", items: { type: "string" } },
    ],
  },
  presentation_analyzer: {
    category: "File & Document",
    name: "Presentation Analyzer",
    description: "Analyze PowerPoint presentations (.pptx): extract slide content, speaker notes, images, tables, charts, slide layouts, and master slides. Provides structured overview of presentation flow, content density per slide, and text extraction.",
    parameters: [
      { name: "file_path", type: "string", required: true, description: "Path to the PowerPoint file (.pptx)" },
      { name: "operation", type: "string", required: false, description: "Analysis operation", enum: ["overview", "slide", "all_text", "notes", "tables", "search"], default: "overview" },
      { name: "slide_number", type: "integer", required: false, description: "Specific slide number to analyze (1-indexed)" },
      { name: "search_term", type: "string", required: false, description: "Text to search across slides" },
    ],
  },
  regex_extractor: {
    category: "Code & Transform",
    name: "Regex Extractor",
    description: "Extract data from text using regular expressions. Supports custom regex patterns and preset patterns for common data types: email, url, phone, ip_address, date_us, date_iso, currency_usd, percentage, uuid, ppa_price, energy_capacity, contract_reference. Can also search/replace, split text, and validate patterns.",
    parameters: [
      { name: "text", type: "string", required: true, description: "Text to search in" },
      { name: "operation", type: "string", required: false, description: "Regex operation", enum: ["extract", "extract_preset", "replace", "split", "validate", "list_presets"], default: "extract" },
      { name: "pattern", type: "string", required: false, description: "Custom regex pattern" },
      { name: "preset", type: "string", required: false, description: "Preset pattern name (e.g. 'email', 'currency_usd', 'ppa_price')" },
      { name: "presets", type: "array", required: false, description: "Multiple preset patterns to extract at once", items: { type: "string" } },
      { name: "replacement", type: "string", required: false, description: "Replacement string for replace operation" },
      { name: "flags", type: "array", required: false, description: "Regex flags", items: { type: "string" } },
      { name: "group", type: "integer", required: false, description: "Capture group number to extract (default: 0 = full match)", default: 0 },
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
  speech_to_text: {
    category: "Multi-Modal",
    name: "Speech To Text",
    description: "Transcribe audio files to text using OpenAI Whisper. Supports MP3, WAV, M4A, WebM. Returns transcription with timestamps.",
    parameters: [
      { name: "audio_url", type: "string", required: true, description: "URL or file path to audio file" },
      { name: "language", type: "string", required: false, description: "Language code (e.g., 'en', 'es', 'fr'). Auto-detected if omitted." },
    ],
  },
  spreadsheet_analyzer: {
    category: "File & Document",
    name: "Spreadsheet Analyzer",
    description: "Analyze Excel workbooks and spreadsheets with advanced operations: read multiple sheets, extract cell ranges, analyze formulas, compute cross-sheet references, generate pivot tables, detect data types per column, identify merged cells and formatting patterns, compute statistics across sheets, and extract chart data. Supports .xlsx, .xls, .csv, and .tsv formats.",
    parameters: [
      { name: "file_path", type: "string", required: true, description: "Path to the spreadsheet file" },
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
    category: "AI & Analysis",
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
  sub_pipeline: {
    name: "Sub Pipeline",
    description: "Execute a nested pipeline as a single step within a parent pipeline. Define a set of pipeline nodes with dependencies, conditions, and data flow \u2014 they will be executed as a self-contained DAG. Results from the sub-pipeline are returned as the step output. Useful for composing reusable pipeline fragments and modular workflow design.",
    parameters: [
      { name: "nodes", type: "array", required: true, description: "List of pipeline node definitions for the sub-pipeline", items: { type: "object" } },
      { name: "context", type: "object", required: false, description: "Optional context data passed to the sub-pipeline", default: {} },
      { name: "timeout_seconds", type: "integer", required: false, description: "Timeout for the sub-pipeline execution", default: 60, minimum: 5, maximum: 300 },
    ],
  },
  text_analyzer: {
    category: "File & Document",
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
    name: "Text To Speech",
    description: "Generate speech audio from text using OpenAI TTS. Voices: alloy, echo, fable, onyx, nova, shimmer. Returns MP3 audio as base64 or saves to file.",
    parameters: [
      { name: "text", type: "string", required: true, description: "Text to convert to speech (max 4096 chars)" },
      { name: "voice", type: "string", required: false, description: "Voice to use for speech generation", enum: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"], default: "alloy" },
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
  unit_converter: {
    category: "Code & Transform",
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
    category: "Knowledge Graph",
    name: "Vector Search",
    description: "Search the agent's knowledge base for relevant information. Returns the most relevant document chunks matching the query.",
    parameters: [
      { name: "query", type: "string", required: true, description: "The search query to find relevant documents" },
      { name: "top_k", type: "integer", required: false, description: "Number of results to return (default: 5)", default: 5 },
    ],
  },
  knowledge_search: {
    category: "Knowledge Graph",
    name: "Knowledge Search",
    description: "Hybrid knowledge base search combining vector similarity with knowledge graph traversal (Neo4j). Returns results with relationship context, entity connections, and source provenance. Use for complex questions that require understanding relationships between concepts.",
    parameters: [
      { name: "query", type: "string", required: true, description: "The search query — what information you're looking for" },
      { name: "mode", type: "string", required: false, description: "Search mode: vector (fast), graph (relationship-focused), hybrid (best quality)", enum: ["vector", "graph", "hybrid"], default: "hybrid" },
      { name: "top_k", type: "integer", required: false, description: "Number of results to return", default: 5, minimum: 1, maximum: 20 },
    ],
  },
  knowledge_store: {
    category: "Knowledge Graph",
    name: "Knowledge Store",
    description: "Store content into the knowledge base for future retrieval. Indexes text into vector store (embeddings) and optionally runs Cognify to extract entities and relationships into the knowledge graph (Neo4j). This is the write counterpart to knowledge_search.",
    parameters: [
      { name: "content", type: "string", required: true, description: "The text content to store in the knowledge base" },
      { name: "title", type: "string", required: true, description: "A descriptive title for this content (used as document name)" },
      { name: "metadata", type: "object", required: false, description: "Optional metadata to attach (e.g. source, type, tags)" },
      { name: "cognify", type: "boolean", required: false, description: "Whether to also run Cognify to extract entities into the knowledge graph", default: false },
    ],
  },
  contract_portfolio: {
    category: "Energy Market",
    name: "Contract Portfolio",
    description: "Query the example app contract portfolio for structured data. Supports listing contracts, getting details, searching clauses, viewing risks, discovering fields, querying extracted data, and comparing fields across contracts.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Operation to perform", enum: ["list_contracts", "get_contract_detail", "search_clauses", "get_risks", "get_extracted_data", "get_portfolio_summary", "get_events", "discover_fields", "query_extracted", "compare_field"] },
      { name: "contract_id", type: "string", required: false, description: "Contract UUID for detail operations" },
      { name: "query", type: "string", required: false, description: "Search text for clauses or extracted data" },
      { name: "clause_type", type: "string", required: false, description: "Filter by clause type" },
      { name: "field_name", type: "string", required: false, description: "Field name for compare_field" },
      { name: "section", type: "string", required: false, description: "Extraction section filter" },
      { name: "limit", type: "integer", required: false, description: "Max results", default: 20 },
    ],
  },
  graph_explorer: {
    category: "Knowledge Graph",
    name: "Graph Explorer",
    description: "Explore the Cognify knowledge graph (Neo4j) to find entities and relationships extracted from contracts. Supports entity search, relationship traversal, shortest paths, and graph statistics.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Graph operation", enum: ["find_entity", "entity_relationships", "entity_path", "entities_by_type", "related_contracts", "graph_stats"] },
      { name: "entity_name", type: "string", required: false, description: "Entity name to search (fuzzy match)" },
      { name: "entity_type", type: "string", required: false, description: "Entity type filter (ORGANIZATION, PERSON, LOCATION, etc.)" },
      { name: "target_entity", type: "string", required: false, description: "Target entity for path finding" },
      { name: "max_hops", type: "integer", required: false, description: "Max relationship hops", default: 2 },
    ],
  },
  market_monitor: {
    category: "Energy Market",
    name: "Market Monitor",
    description: "System-level tool for the example app market monitoring. Loads contracts with pricing terms, writes market alerts, updates risk scores, and retrieves recent alerts for deduplication.",
    parameters: [
      { name: "operation", type: "string", required: true, description: "Operation", enum: ["get_all_contracts_with_pricing", "write_market_alert", "update_risk_score", "get_latest_alerts"] },
      { name: "contract_id", type: "string", required: false, description: "Contract UUID" },
      { name: "alert_type", type: "string", required: false, description: "Alert type" },
      { name: "severity", type: "string", required: false, description: "Alert severity", enum: ["info", "warning", "critical"] },
      { name: "title", type: "string", required: false, description: "Alert title" },
      { name: "description", type: "string", required: false, description: "Alert description" },
      { name: "market_risk_score", type: "number", required: false, description: "Updated risk score (0-100)" },
      { name: "hours", type: "integer", required: false, description: "Hours to look back for recent alerts", default: 24 },
    ],
  },
  web_search: {
    category: "Web Search",
    name: "Web Search",
    description: "Search the web for current information. Returns a list of results with titles, URLs, and snippets.",
    parameters: [
      { name: "query", type: "string", required: true, description: "The search query" },
      { name: "max_results", type: "integer", required: false, description: "Maximum number of results to return", default: 5 },
    ],
  },
  weather_simulator: {
    category: "AI & Analysis",
    name: "Weather Simulator",
    description: "Simulate weather scenarios and their operational impact. Generates solar irradiance, wind speed, temperature, and precipitation distributions for any location. Use for energy yield, crop yield, logistics planning, insurance risk, or construction scheduling.",
    parameters: [
      { name: "location", type: "string", required: true, description: "City/region name or lat/lon coordinates" },
      { name: "period_months", type: "integer", required: false, description: "Simulation horizon in months", default: 12 },
      { name: "scenarios", type: "array", required: false, description: "Scenario names to generate", default: ["base", "optimistic", "pessimistic", "extreme"] },
      { name: "parameters", type: "array", required: false, description: "Weather parameters to simulate", default: ["solar_irradiance", "wind_speed", "temperature", "precipitation"] },
      { name: "seed", type: "integer", required: false, description: "Random seed for reproducibility" },
    ],
  },
  sentiment_analyzer: {
    category: "AI & Analysis",
    name: "Sentiment Analyzer",
    description: "Analyze market sentiment from text, news headlines, or analyst reports. Produces sentiment scores, trend direction, volatility indicators, and confidence intervals. Works across any industry domain.",
    parameters: [
      { name: "texts", type: "array", required: true, description: "Array of text strings (headlines, reports, posts) to analyze" },
      { name: "domain", type: "string", required: false, description: "Industry context for better scoring", enum: ["energy", "tech", "healthcare", "commodities", "finance", "real_estate", "general"] },
      { name: "aggregation", type: "string", required: false, description: "How to combine scores", enum: ["simple_average", "weighted_recent", "momentum"], default: "weighted_recent" },
    ],
  },
  scenario_planner: {
    category: "AI & Analysis",
    name: "Scenario Planner",
    description: "Run structured what-if analysis with parameter sweeps. Define base values and variation ranges for any numeric parameters, provide a formula, and get outcomes across all combinations. Use for pricing sensitivity, budget planning, risk assessment, or strategic option evaluation.",
    parameters: [
      { name: "parameters", type: "object", required: true, description: "Parameter definitions: {name: {base, range: [low, high], steps, unit}}" },
      { name: "formula", type: "string", required: true, description: "Expression using parameter names, e.g. 'revenue * (1 - tax_rate) - costs'" },
      { name: "output_name", type: "string", required: false, description: "Label for the computed outcome", default: "outcome" },
      { name: "scenarios", type: "array", required: false, description: "Named preset scenarios with parameter overrides" },
    ],
  },
  graph_builder: {
    category: "AI & Analysis",
    name: "Graph Builder",
    description: "Build a structured dependency graph (DAG) from nodes and edges. Returns visualization-ready JSON with topological ordering, cycle detection, and level assignment. Use for contract clause dependencies, decision provenance, workflow diagrams, or entity-relationship maps.",
    parameters: [
      { name: "title", type: "string", required: true, description: "Graph title displayed in the header" },
      { name: "nodes", type: "array", required: true, description: "Array of {id, label, type, data} objects. 'type' drives color-coding." },
      { name: "edges", type: "array", required: true, description: "Array of {from, to, label} directed edges between node IDs." },
      { name: "layout", type: "string", required: false, description: "Layout hint", enum: ["auto", "horizontal", "vertical", "radial"], default: "auto" },
    ],
  },
  sanctions_screening: {
    category: "Compliance & KYC",
    name: "Sanctions Screening",
    description: "Screen a person or company against the world's major sanctions lists — OFAC SDN, OFAC Consolidated, EU, UN Security Council, UK HMT OFSI, Canada OSFI, Australia DFAT, Switzerland SECO. Uses live public feeds (no paid API required) with fuzzy matching + AKA expansion. Returns per-list hits with confidence 0-100 and an L/M/H risk grade for direct use in KYC forms. Safe, read-only.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Full legal name to screen." },
      { name: "entity_type", type: "string", required: false, description: "Bias by entity type.", enum: ["individual", "entity", "any"], default: "any" },
      { name: "lists", type: "array", required: false, description: "Subset of sanctions lists to check. Omit for all.", items: { type: "string" } },
      { name: "threshold", type: "integer", required: false, description: "Fuzzy match threshold 0-100. 85 good KYC default; 70-80 investigative; 92+ high-precision gate.", default: 85, minimum: 50, maximum: 100 },
      { name: "max_hits_per_list", type: "integer", required: false, description: "Cap hits returned per list.", default: 5, minimum: 1, maximum: 20 },
      { name: "refresh", type: "boolean", required: false, description: "Force re-download of lists bypassing the 6h cache.", default: false },
      { name: "also_check_aliases", type: "array", required: false, description: "Additional spellings / transliterations.", items: { type: "string" } },
    ],
  },
  pep_screening: {
    category: "Compliance & KYC",
    name: "PEP Screening",
    description: "Screen a person against Politically Exposed Persons lists (FATF R.12, EU AMLD-6, BSA, MAS Notice 626). Combines OpenSanctions (900k+ entries), Wikidata SPARQL (live P39 position statements), and per-country parliament rosters. Classifies each hit as Domestic/Foreign PEP, International Organisation PEP, Family PEP, Close Associate PEP, or Former PEP. Safe, read-only.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Full legal name of the person." },
      { name: "jurisdiction", type: "string", required: false, description: "ISO 3166-1 alpha-2 (e.g. 'GB', 'US'). Enables government-roster check and biases Wikidata results." },
      { name: "also_check_aliases", type: "array", required: false, description: "Additional spellings, maiden names, patronymics.", items: { type: "string" } },
      { name: "former_pep_lookback_months", type: "integer", required: false, description: "How far back to flag as Former PEP. 18 is FATF common guidance; 12 is EU minimum.", default: 18, minimum: 0, maximum: 120 },
      { name: "sources", type: "array", required: false, description: "Which sources to query.", items: { type: "string" } },
      { name: "threshold", type: "integer", required: false, description: "Name-match threshold 0-100.", default: 85, minimum: 50, maximum: 100 },
    ],
  },
  adverse_media: {
    category: "Compliance & KYC",
    name: "Adverse Media",
    description: "Negative-news / adverse-media screening fused from four public sources — Tavily AI search, GDELT 2.0, Google News RSS, and Reuters scrape. Auto-classifies each hit by risk category (bribery, money laundering, fraud, sanctions evasion, terrorism financing, etc.), stance (adverse/neutral/positive), recency bucket, and source tier weight 1..5. Outputs L/M/H risk grade. Safe, read-only.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Person or entity name." },
      { name: "search_depth", type: "string", required: false, description: "Tavily search depth.", enum: ["basic", "advanced"], default: "basic" },
      { name: "name_match_threshold", type: "integer", required: false, description: "Drop hits whose title fuzzy-match is below this.", default: 75, minimum: 50, maximum: 100 },
      { name: "min_source_weight", type: "integer", required: false, description: "Require at least this tier weight (1-5).", default: 1, minimum: 1, maximum: 5 },
      { name: "lookback_years", type: "integer", required: false, description: "How far back to search.", default: 3, minimum: 1, maximum: 10 },
      { name: "max_results", type: "integer", required: false, description: "Max hits to return.", default: 30, minimum: 1, maximum: 100 },
      { name: "refresh", type: "boolean", required: false, description: "Bypass 30m cache.", default: false },
    ],
  },
  ubo_discovery: {
    category: "Compliance & KYC",
    name: "UBO Discovery",
    description: "Walk corporate ownership tree to identify Ultimate Beneficial Owners (EU AMLD-6 Art. 3(6)). Fuses GLEIF (2.3M+ LEI records), OpenCorporates (200M+ companies), UK Companies House PSC, Polish KRS + more national registers. Returns a typed ownership tree with effective_pct path-products, UBOs ≥ threshold, and discovery gaps for manual follow-up. Safe, read-only.",
    parameters: [
      { name: "company_name", type: "string", required: true, description: "Legal name of the entity." },
      { name: "country", type: "string", required: false, description: "ISO-2 code. Strongly recommended — reduces GLEIF/OC ambiguity." },
      { name: "lei", type: "string", required: false, description: "Pre-known LEI — skips name search." },
      { name: "registration_number", type: "string", required: false, description: "Pre-known local company number." },
      { name: "ubo_threshold_pct", type: "number", required: false, description: "Min effective % to classify as UBO. 20 EU/AMLD-6, 25 US FinCEN CTA, 10 UK PSC strict.", default: 20, minimum: 1, maximum: 100 },
      { name: "max_depth", type: "integer", required: false, description: "Max tree walk depth.", default: 4, minimum: 1, maximum: 8 },
      { name: "sources", type: "array", required: false, description: "Subset of register sources.", items: { type: "string" } },
    ],
  },
  country_risk_index: {
    category: "Compliance & KYC",
    name: "Country Risk Index",
    description: "Aggregate country-risk signals — Transparency International CPI rank (live from OurWorldInData), FATF grey/black lists (via Wayback), EU non-cooperative tax list, OFAC country programmes, World Bank WGI percentiles (Control of Corruption, Rule of Law, Regulatory Quality). Outputs MET-style Indicator I score + L/M/H jurisdiction-risk grade. Safe, read-only.",
    parameters: [
      { name: "country", type: "string", required: true, description: "ISO 3166-1 alpha-2 code (e.g. 'PL') or full country name." },
      { name: "signals", type: "array", required: false, description: "Subset of signals.", items: { type: "string" } },
    ],
  },
  legal_existence_verifier: {
    category: "Compliance & KYC",
    name: "Legal Existence Verifier",
    description: "Verify a company legally exists, is in good standing, and is not a suspected shell. Cross-references GLEIF, OpenCorporates, UK Companies House + per-jurisdiction registers. Detects shell patterns (recent incorporation, mass-registration addresses), dissolved/struck-off status, lapsed LEIs, unusual legal forms. Returns normalized verdict + red flags + audit trail. Safe, read-only.",
    parameters: [
      { name: "company_name", type: "string", required: true, description: "Legal name." },
      { name: "country", type: "string", required: false, description: "ISO-2 code. Strongly recommended." },
      { name: "registration_number", type: "string", required: false, description: "Pre-known local company number." },
      { name: "lei", type: "string", required: false, description: "Pre-known LEI." },
    ],
  },
  kyc_scorer: {
    category: "Compliance & KYC",
    name: "KYC Scorer",
    description: "Deterministic KYC risk scorer. Takes CPI rank + annual notional USD + industry segment + optional signal flags, outputs Indicator I / II / III scores (MET format), Aggregated Score, Type of Check (Simplified / Standard / Enhanced) and L/M/H KYC grade. Stateless, fully explainable. Based on FATF, ESA JC 2017 37, and Wolfsberg DDQ guidance. Safe.",
    parameters: [
      { name: "cpi_rank", type: "number", required: true, description: "Transparency International CPI rank (1 = cleanest, ~180 = most corrupt)." },
      { name: "annual_notional_usd", type: "number", required: true, description: "Expected annual contracted volume or notional in USD." },
      { name: "industry_segment", type: "string", required: true, description: "Industry key or free-text." },
      { name: "sanctions_hit", type: "boolean", required: false, description: "Whether a sanctions match was found." },
      { name: "pep_match", type: "boolean", required: false, description: "Whether a PEP / family / associate match was found." },
      { name: "adverse_media_grade", type: "string", required: false, description: "Output grade from adverse_media tool.", enum: ["L", "M", "H", "unknown"] },
      { name: "legal_existence_red_flags", type: "array", required: false, description: "Red-flag codes from legal_existence_verifier.", items: { type: "string" } },
      { name: "ubo_discovery_gaps", type: "integer", required: false, description: "Count of unresolved UBO chain gaps." },
    ],
  },
  regulatory_enforcement: {
    category: "Compliance & KYC",
    name: "Regulatory Enforcement",
    description: "Primary-source regulatory enforcement and litigation lookup. Hits SEC EDGAR, DOJ, FCA, BaFin, ASIC, MAS + court indices CourtListener (US federal), BAILII (UK/IE), CanLII. Extracts fines (with currency conversion), action type (fine/settlement/cease-and-desist/criminal/civil/debarment/licence revocation) and direct source URLs. Complements adverse_media — this returns PRIMARY filings, not press. Safe, read-only.",
    parameters: [
      { name: "name", type: "string", required: true, description: "Legal name of person or entity." },
      { name: "sources", type: "array", required: false, description: "Subset of sources to hit.", items: { type: "string" } },
      { name: "min_confidence", type: "integer", required: false, description: "Name-match threshold 0-100.", default: 75, minimum: 50, maximum: 100 },
    ],
  },
  code_asset: {
    category: "Code & Transform",
    name: "Code Asset",
    description:
      "Execute a registered code asset (user-uploaded zip or git repo) in an " +
      "isolated k8s Pod. The asset's language + build + run commands were " +
      "detected at upload time; this tool just supplies the runtime input and " +
      "returns its stdout. If the asset declares input_schema / output_schema " +
      "(via abenix.yaml, examples/, or README fenced blocks), the Builder " +
      "pre-fills the pipeline-node 'input' field from that schema.",
    parameters: [
      { name: "code_asset_id", type: "string", required: true,
        description:
          "UUID of the uploaded asset. Set once in the tool-config parameter " +
          "defaults and the LLM never has to think about it." },
      { name: "input", type: "object", required: true,
        description:
          "JSON payload piped to the asset's stdin. Should match the asset's " +
          "input_schema — the Builder fills the skeleton automatically." },
      { name: "timeout_seconds", type: "integer", required: false, default: 120,
        description: "Hard kill-after for the pod. Defaults to 120s, max 1800.",
        minimum: 5, maximum: 1800 },
    ],
  },
  sandboxed_job: {
    category: "Code & Transform",
    name: "Sandboxed Job",
    description:
      "Run an inline shell command inside a k8s Job using one of the allow-" +
      "listed base images. Like code_asset but for ad-hoc scripts that don't " +
      "deserve their own zip. Network off by default; operators flip " +
      "SANDBOXED_JOB_ALLOW_NETWORK=true to permit pip/go-get/etc.",
    parameters: [
      { name: "image", type: "string", required: true,
        description: "Container image (must be in SANDBOXED_JOB_ALLOWED_IMAGES)." },
      { name: "command", type: "string", required: true,
        description: "Shell command to run. Stdout is returned to the agent." },
      { name: "input", type: "object", required: false,
        description: "Optional JSON payload piped to stdin of the command." },
      { name: "timeout_seconds", type: "integer", required: false, default: 60,
        description: "Pod kill-after. Default 60s, max 1800.",
        minimum: 5, maximum: 1800 },
      { name: "env", type: "object", required: false,
        description: "Extra env vars. Secrets must NOT be inlined here." },
    ],
  },
  ml_model: {
    category: "AI & Analysis",
    name: "ML Model",
    description:
      "Call a trained ML model uploaded to the ML Model Registry. Picks the " +
      "k8s-pod endpoint if one is live, otherwise falls back to in-process " +
      "inference. On upload the platform introspects the model (sklearn " +
      "feature_names_in_, ONNX input/output tensors) and populates input / " +
      "output_schema so the Builder can render the pipeline-node form and " +
      "the LLM sees an accurate tool schema.",
    parameters: [
      { name: "model_id", type: "string", required: true,
        description: "UUID of the deployed model. Set in tool-config defaults." },
      { name: "input_data", type: "array", required: true,
        description:
          "Array of samples. Shape matches the model's input_schema " +
          "(typically array[array[number]] for sklearn)." },
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
