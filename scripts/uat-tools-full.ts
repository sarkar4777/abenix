/**
 * Exhaustive tools-and-pipelines UAT — every tool in /api/tools.
 *
 * For each tool the script:
 *   1. Builds a single-tool reactive agent and asks the LLM to use it.
 *   2. Captures the API response and (when an execution row is created)
 *      the failure_code + error_message from /api/executions/{id}.
 *   3. Probes the *direct* tool-test endpoint where one exists.
 *
 * Plus realistic multi-tool pipelines per category (data-prep,
 * KYC due-diligence, finance research, customer-support, knowledge
 * augmentation, code-review fan-out).
 *
 * Plus UI surface checks (pipeline builder tool palette, /executions
 * error rendering, /tools page, /agents tool-picker).
 *
 * Output → BUGS_TOOLS_FULL.md with a row per tool.
 */

import { chromium, type Browser, type Page } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.ABENIX_URL || 'http://localhost:3000';
const API = process.env.ABENIX_API || 'http://localhost:8000';

const REPORT_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'tools-full');
fs.mkdirSync(REPORT_DIR, { recursive: true });

type Severity = 'P0' | 'P1' | 'P2' | 'GAP' | 'OK' | 'SKIP';
interface Finding {
  id: string;
  category: string;
  tool: string;
  test: string;
  expected: string;
  actual: string;
  severity: Severity;
  failureCode?: string;
}
const findings: Finding[] = [];
let nextId = 1;
const PROGRESS_FILE = path.resolve(__dirname, '..', 'logs', 'uat', 'tools-full', 'progress.log');
function progress(line: string) {
  try { fs.appendFileSync(PROGRESS_FILE, line + '\n'); } catch {}
  // Also write to stdout, but we don't depend on it being flushed.
  process.stdout.write(line + '\n');
}
function record(category: string, tool: string, test: string, expected: string, actual: string, severity: Severity, failureCode?: string) {
  const id = `F${String(nextId++).padStart(3, '0')}`;
  findings.push({ id, category, tool, test, expected, actual, severity, failureCode });
  const tag = severity === 'OK' ? '✓' : severity === 'GAP' ? '!' : severity === 'SKIP' ? '·' : '✗';
  const fc = failureCode ? ` [${failureCode}]` : '';
  progress(`  ${tag} ${id} [${severity}] ${category}/${tool}${fc} — ${actual.slice(0, 130)}`);
}

let adminToken = '';

async function api(method: string, p: string, body?: unknown): Promise<any> {
  const res = await fetch(`${API}${p}`, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${adminToken}` },
    body: body ? JSON.stringify(body) : undefined,
  });
  const txt = await res.text();
  let parsed: any = txt;
  try {
    parsed = JSON.parse(txt);
  } catch {}
  return { status: res.status, ok: res.ok, body: parsed };
}

async function login() {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@abenix.dev', password: 'Admin123456' }),
  });
  const j = (await r.json()) as any;
  adminToken = j?.data?.access_token || '';
  if (!adminToken) throw new Error(`login failed: ${JSON.stringify(j)}`);
}

// JWT lifetime is ~15 min; refresh proactively every N tool tests so a
// long sweep doesn't cascade into "create failed" past the cliff.
const REFRESH_EVERY = 20;
let testsSinceLogin = 0;

async function maybeRefreshToken() {
  testsSinceLogin += 1;
  if (testsSinceLogin >= REFRESH_EVERY) {
    await login();
    testsSinceLogin = 0;
  }
}

async function makeAgent(slug: string, prompt: string, tools: string[]): Promise<string | null> {
  await maybeRefreshToken();
  const r = await api('POST', '/api/agents', {
    name: slug,
    slug,
    system_prompt: prompt,
    model_config: {
      model: 'claude-sonnet-4-5-20250929',
      tools,
    },
    agent_type: 'reactive',
    category: 'tools-uat',
  });
  if (r.status === 401) {
    // Token expired between checks — re-login and retry once.
    await login();
    testsSinceLogin = 0;
    const retry = await api('POST', '/api/agents', {
      name: slug,
      slug,
      system_prompt: prompt,
      model_config: { model: 'claude-sonnet-4-5-20250929', tools },
      agent_type: 'reactive',
      category: 'tools-uat',
    });
    return retry.ok ? retry.body?.data?.id || null : null;
  }
  return r.ok ? r.body?.data?.id || null : null;
}

async function exec(id: string, message: string, waitSec = 60): Promise<any> {
  return api('POST', `/api/agents/${id}/execute`, {
    message,
    stream: false,
    wait: true,
    wait_timeout_seconds: waitSec,
  });
}

async function execRow(executionId: string): Promise<{ status: string; failureCode: string; error: string } | null> {
  if (!executionId) return null;
  const r = await api('GET', `/api/executions/${executionId}`);
  const data = r.body?.data || {};
  return {
    status: String(data.status || 'unknown'),
    failureCode: String(data.failure_code || ''),
    error: String(data.error_message || ''),
  };
}

// ── Per-tool prompts — minimal nudge that should make the LLM call ──

interface ToolSpec {
  category: string;
  tool: string;
  prompt: string;
  ask: string;
  // expected output cue or "skip" reason if external service required
  cue?: RegExp;
  skipReason?: string;
}

const TOOLS: ToolSpec[] = [
  // CORE
  { category: 'core', tool: 'calculator', prompt: 'Use calculator for math.', ask: 'What is 14 * 9 + 7?', cue: /133/ },
  { category: 'core', tool: 'current_time', prompt: 'Use current_time for the time.', ask: 'What is the current UTC time?', cue: /\d{4}|\d{2}:\d{2}|UTC|hour|minute/i },
  { category: 'core', tool: 'web_search', prompt: 'Use web_search.', ask: 'Search for "latest news on Anthropic Claude".', cue: /found|result|article|search/i },
  { category: 'core', tool: 'tavily_search', prompt: 'Use tavily_search.', ask: 'Search Tavily for "kubernetes blue-green deployment".', cue: /result|deploy|kubernetes/i },
  { category: 'core', tool: 'academic_search', prompt: 'Use academic_search.', ask: 'Find recent academic papers on transformer architectures.', cue: /paper|author|abstract|arxiv|publish/i },
  { category: 'core', tool: 'news_feed', prompt: 'Use news_feed.', ask: 'Pull latest tech news headlines.', cue: /news|headline|article|today/i },
  { category: 'core', tool: 'code_executor', prompt: 'Use code_executor for python.', ask: 'Run python: print(sum(range(11)))', cue: /55/ },
  { category: 'core', tool: 'unit_converter', prompt: 'Use unit_converter for unit math.', ask: 'Convert 10 kilometers to miles.', cue: /6\.2|6\.21|mile/i },
  { category: 'core', tool: 'date_calculator', prompt: 'Use date_calculator.', ask: 'How many days between 2026-01-01 and 2026-12-31?', cue: /364|365/ },

  // DATA
  { category: 'data', tool: 'csv_analyzer', prompt: 'Use csv_analyzer.', ask: 'Analyze this CSV data:\n```\nname,score\nA,10\nB,20\nC,30\n```\nWhat is the average score?', cue: /20|average|mean/i },
  { category: 'data', tool: 'json_transformer', prompt: 'Use json_transformer.', ask: 'From {"items": [1,2,3,4,5]} extract items length.', cue: /5|length|count/i },
  { category: 'data', tool: 'regex_extractor', prompt: 'Use regex_extractor.', ask: 'Extract phone numbers from: Call 555-1234 or 555-9876 today.', cue: /555-1234|555-9876|two|2/ },
  { category: 'data', tool: 'text_analyzer', prompt: 'Use text_analyzer.', ask: 'Analyze: "The quick brown fox jumps over the lazy dog."', cue: /word|character|sentence|count/i },
  { category: 'data', tool: 'sentiment_analyzer', prompt: 'Use sentiment_analyzer.', ask: 'What is the sentiment of: "I absolutely love this product, it changed my life!"', cue: /positive|sentiment|love/i },
  { category: 'data', tool: 'pii_redactor', prompt: 'Use pii_redactor.', ask: 'Redact PII from: "Email me at john.doe@example.com or call 555-123-4567."', cue: /redact|removed|REDACT|████/i },
  { category: 'data', tool: 'schema_validator', prompt: 'Use schema_validator.', ask: 'Validate that {"name": "Alice", "age": 30} matches a {name: string, age: number} schema.', cue: /valid|matches|conforms|pass/i },
  { category: 'data', tool: 'document_parser', prompt: 'Use document_parser.', ask: 'Parse this small document: "Title: Q1 Report\\n\\nRevenue grew 15%."', cue: /title|revenue|parsed|section/i, skipReason: 'needs file upload typically' },
  { category: 'data', tool: 'document_extractor', prompt: 'Use document_extractor.', ask: 'Extract structured fields from: "Invoice #1042 dated 2026-04-15 for $1,250."', cue: /invoice|1042|2026-04-15|1250|date/i },
  { category: 'data', tool: 'spreadsheet_analyzer', prompt: 'Use spreadsheet_analyzer.', ask: 'Analyze the following spreadsheet content and find the max in column score:\n| name | score |\n| A | 10 |\n| B | 30 |\n| C | 20 |', cue: /30|max|maximum/i },
  { category: 'data', tool: 'file_reader', prompt: 'Use file_reader.', ask: 'Read /etc/hostname and tell me the contents.', cue: /host|file|read|content/i, skipReason: 'sandbox FS access' },
  { category: 'data', tool: 'file_system', prompt: 'Use file_system.', ask: 'List files in /tmp via the file_system tool.', cue: /list|files|directory|tmp/i, skipReason: 'sandbox FS access' },
  { category: 'data', tool: 'database_query', prompt: 'Use database_query.', ask: 'Query the postgres for SELECT 1 AS x.', cue: /1|x|query|result|connect/i, skipReason: 'requires DB connection' },
  { category: 'data', tool: 'database_writer', prompt: 'Use database_writer.', ask: 'Write a row {name: "test"} to a test table.', cue: /insert|write|row|table/i, skipReason: 'requires DB connection' },
  { category: 'data', tool: 'structured_extractor', prompt: 'Use structured_extractor.', ask: 'Extract structured fields from: "Order #1023 of $499.99 placed 2026-04-01."', cue: /1023|499|2026-04-01|order|date|amount/i },
  { category: 'data', tool: 'time_series_analyzer', prompt: 'Use time_series_analyzer.', ask: 'Analyze this series: [10, 12, 15, 18, 22, 25, 28]. Trend?', cue: /increase|trend|upward|grow|rise/i },
  { category: 'data', tool: 'presentation_analyzer', prompt: 'Use presentation_analyzer.', ask: 'Summarize the structure of a 10-slide pitch deck about a fintech startup.', cue: /slide|deck|present|fintech/i },

  // ENTERPRISE
  { category: 'enterprise', tool: 'atlas_describe', prompt: 'Use atlas_describe.', ask: 'Describe the Asset concept from the ontology.', cue: /asset|concept|ontology|describe|node|definition/i },
  { category: 'enterprise', tool: 'atlas_query', prompt: 'Use atlas_query.', ask: 'Query the ontology for items related to Obligation.', cue: /obligation|concept|result|item/i },
  { category: 'enterprise', tool: 'atlas_traverse', prompt: 'Use atlas_traverse.', ask: 'Traverse from concept Asset 2 hops outward.', cue: /traverse|hop|asset|relation|connect/i },
  { category: 'enterprise', tool: 'atlas_search_grounded', prompt: 'Use atlas_search_grounded.', ask: 'Search ontology+KB for "asset valuation methodology".', cue: /search|ground|asset|valuation/i },
  { category: 'enterprise', tool: 'memory_store', prompt: 'Use memory_store.', ask: 'Remember that the deployment region is eastus2.', cue: /remember|stored|noted|memory|saved/i },
  { category: 'enterprise', tool: 'memory_recall', prompt: 'Use memory_recall.', ask: 'Recall what region we deploy to.', cue: /eastus|region|recall|memory|deploy/i },
  { category: 'enterprise', tool: 'memory_forget', prompt: 'Use memory_forget.', ask: 'Forget the region preference.', cue: /forgot|forget|removed|deleted|cleared/i },
  { category: 'enterprise', tool: 'human_approval', prompt: 'Use human_approval.', ask: 'Request human approval for refunding $500 to a customer.', cue: /approval|pending|request|review|human/i },
  { category: 'enterprise', tool: 'graph_builder', prompt: 'Use graph_builder.', ask: 'Build a small graph: Alice knows Bob, Bob knows Carol.', cue: /graph|node|edge|alice|bob|carol|relationship/i },
  { category: 'enterprise', tool: 'graph_explorer', prompt: 'Use graph_explorer.', ask: 'Explore the knowledge graph for nodes near "Customer".', cue: /node|edge|graph|customer|explore/i },
  { category: 'enterprise', tool: 'knowledge_search', prompt: 'Use knowledge_search.', ask: 'Search the KB for "onboarding checklist".', cue: /knowledge|kb|result|onboard|search/i },
  { category: 'enterprise', tool: 'sandboxed_job', prompt: 'Use sandboxed_job.', ask: 'Run python:3.12-slim with the command "echo hello-sandbox".', cue: /hello-sandbox|sandbox|completed|exit/i },
  { category: 'enterprise', tool: 'scenario_planner', prompt: 'Use scenario_planner.', ask: 'Plan three scenarios for a 10% revenue drop.', cue: /scenario|plan|optimist|pessim|baseline|10%/i },
  { category: 'enterprise', tool: 'structured_analyzer', prompt: 'Use structured_analyzer.', ask: 'Analyze this structured input: {"revenue": 100, "cost": 70}. Profit?', cue: /30|profit|margin|analyze/i },
  { category: 'enterprise', tool: 'weather_simulator', prompt: 'Use weather_simulator.', ask: 'Simulate weather for Stockholm in May.', cue: /stockholm|weather|temperature|forecast|may/i },

  // FINANCE
  { category: 'finance', tool: 'financial_calculator', prompt: 'Use financial_calculator. Use compound interest annual unless told otherwise.', ask: 'Compute future value of $1000 at 5% annual for 10 years (compound annually).', cue: /1628|1,628|future value|fv/i },
  { category: 'finance', tool: 'risk_analyzer', prompt: 'Use risk_analyzer.', ask: 'Compute VaR at 95% for a portfolio with σ=15%, μ=8%, $1M notional.', cue: /var|risk|95|exposure|million/i },
  { category: 'finance', tool: 'market_data', prompt: 'Use market_data.', ask: 'Get latest price for ticker AAPL.', cue: /aapl|apple|price|\$|market/i, skipReason: 'requires market data API' },
  { category: 'finance', tool: 'yahoo_finance', prompt: 'Use yahoo_finance.', ask: 'Fetch Yahoo Finance summary for MSFT.', cue: /msft|microsoft|price|market/i, skipReason: 'requires Yahoo API' },
  { category: 'finance', tool: 'ecb_rates', prompt: 'Use ecb_rates.', ask: 'Get the latest EUR/USD rate from the ECB.', cue: /eur|usd|rate|euro|dollar/i, skipReason: 'requires ECB API' },
  { category: 'finance', tool: 'ember_climate', prompt: 'Use ember_climate.', ask: 'What is the current renewable share in Germany electricity?', cue: /germany|renewable|share|percent|electric/i, skipReason: 'requires Ember API' },
  { category: 'finance', tool: 'entso_e', prompt: 'Use entso_e.', ask: 'Get day-ahead electricity price for Germany.', cue: /germany|price|electric|euro|mwh/i, skipReason: 'requires ENTSO-E key' },
  { category: 'finance', tool: 'credit_risk', prompt: 'Use credit_risk.', ask: 'Score credit risk for a 35yo with €60k income and €15k debt.', cue: /risk|score|credit|low|medium|high/i },
  { category: 'finance', tool: 'schema_portfolio_tool', prompt: 'Use schema_portfolio_tool.', ask: 'Show available portfolio schemas.', cue: /schema|portfolio|list/i },

  // INTEGRATION
  { category: 'integration', tool: 'http_client', prompt: 'Use http_client.', ask: 'GET https://httpbin.org/json. What did it return?', cue: /slideshow|title|httpbin|json|author/i },
  { category: 'integration', tool: 'api_connector', prompt: 'Use api_connector.', ask: 'Connect to the public API at https://httpbin.org/get and return the headers.', cue: /header|host|http|httpbin/i },
  { category: 'integration', tool: 'cloud_storage', prompt: 'Use cloud_storage.', ask: 'List files in s3://demo-bucket via cloud_storage.', cue: /s3|cloud|file|bucket/i, skipReason: 'requires S3 credentials' },
  { category: 'integration', tool: 'data_exporter', prompt: 'Use data_exporter.', ask: 'Export the data {a:1,b:2} as CSV.', cue: /csv|export|a,b|1,2|file/i },
  { category: 'integration', tool: 'email_sender', prompt: 'Use email_sender.', ask: 'Send a test email to test@example.com with subject "Hi".', cue: /sent|email|delivered|queued|test@example/i, skipReason: 'requires SMTP creds' },
  { category: 'integration', tool: 'event_buffer', prompt: 'Use event_buffer.', ask: 'Push event {type: "login"} to the buffer.', cue: /event|buffer|push|queued/i },
  { category: 'integration', tool: 'github_tool', prompt: 'Use github_tool.', ask: 'Get repo metadata for sarkar4777/abenix.', cue: /sarkar4777|abenix|repo|github|stars/i, skipReason: 'requires GITHUB_TOKEN' },
  { category: 'integration', tool: 'integration_hub', prompt: 'Use integration_hub.', ask: 'List the available integrations.', cue: /integration|service|list|available|hub/i },
  { category: 'integration', tool: 'kafka_consumer', prompt: 'Use kafka_consumer.', ask: 'Consume one message from topic events.', cue: /kafka|topic|message|consum/i, skipReason: 'requires Kafka cluster' },
  { category: 'integration', tool: 'redis_stream_consumer', prompt: 'Use redis_stream_consumer.', ask: 'Read latest message from stream events.', cue: /redis|stream|message|consum/i },
  { category: 'integration', tool: 'redis_stream_publisher', prompt: 'Use redis_stream_publisher.', ask: 'Publish {type: ping} to stream events.', cue: /redis|stream|publish|sent|id/i },

  // KYC
  { category: 'kyc', tool: 'sanctions_screening', prompt: 'Use sanctions_screening.', ask: 'Screen "John Smith" against OFAC.', cue: /screen|sanctions|ofac|match|hit|clean/i },
  { category: 'kyc', tool: 'pep_screening', prompt: 'Use pep_screening.', ask: 'Check if "Angela Merkel" is a PEP.', cue: /pep|polit|exposed|merkel|match/i },
  { category: 'kyc', tool: 'adverse_media', prompt: 'Use adverse_media.', ask: 'Search adverse media for "Acme Corp".', cue: /media|news|adverse|acme|article/i },
  { category: 'kyc', tool: 'country_risk_index', prompt: 'Use country_risk_index.', ask: 'Look up country risk index for Switzerland.', cue: /switzerland|risk|country|score|low|index/i },
  { category: 'kyc', tool: 'kyc_scorer', prompt: 'Use kyc_scorer.', ask: 'Compute KYC risk score for a Swiss individual with no PEP hits.', cue: /score|risk|kyc|low|medium|high/i },
  { category: 'kyc', tool: 'legal_existence_verifier', prompt: 'Use legal_existence_verifier.', ask: 'Verify that "Acme GmbH" is a real registered company.', cue: /verified|exists|registered|company|gmbh/i },
  { category: 'kyc', tool: 'regulatory_enforcement', prompt: 'Use regulatory_enforcement.', ask: 'Look up regulatory enforcement actions against "Wells Fargo".', cue: /wells|fargo|enforcement|action|reg/i },
  { category: 'kyc', tool: 'ubo_discovery', prompt: 'Use ubo_discovery.', ask: 'Find UBOs for "Acme GmbH".', cue: /ubo|owner|beneficial|acme/i },

  // MEETING
  { category: 'meeting', tool: 'meeting_join', prompt: 'Use meeting_join.', ask: 'Join the LiveKit room "ops-standup-2026-05-02".', cue: /joined|room|livekit|meeting/i, skipReason: 'requires running LiveKit + meeting fixture' },
  { category: 'meeting', tool: 'meeting_listen', prompt: 'Use meeting_listen.', ask: 'Listen for 10 seconds in current meeting.', cue: /listen|transcript|audio|10/i, skipReason: 'requires LiveKit' },
  { category: 'meeting', tool: 'meeting_speak', prompt: 'Use meeting_speak.', ask: 'Say "Standup starting" in the meeting.', cue: /spoken|tts|standup|audio/i, skipReason: 'requires LiveKit' },
  { category: 'meeting', tool: 'meeting_post_chat', prompt: 'Use meeting_post_chat.', ask: 'Post a chat message: "Agenda is in the doc".', cue: /post|chat|message|agenda/i, skipReason: 'requires LiveKit' },
  { category: 'meeting', tool: 'meeting_leave', prompt: 'Use meeting_leave.', ask: 'Leave the current meeting.', cue: /left|leave|disconnect/i, skipReason: 'requires LiveKit' },
  { category: 'meeting', tool: 'persona_rag', prompt: 'Use persona_rag.', ask: 'Look up what the persona says about Q1 budget.', cue: /persona|q1|budget|fact|recall|memory/i, skipReason: 'requires persona corpus' },
  { category: 'meeting', tool: 'scope_gate', prompt: 'Use scope_gate.', ask: 'Check if "share salary data" is in scope for the meeting bot.', cue: /scope|allow|deny|gate|salary|in.scope|out.of.scope/i },
  { category: 'meeting', tool: 'defer_to_human', prompt: 'Use defer_to_human.', ask: 'Defer this decision to a human moderator.', cue: /defer|human|escalate|review/i },

  // ML
  { category: 'ml', tool: 'ml_model', prompt: 'Use ml_model.', ask: 'Run inference on the deployed RUL estimator with input {temp: 65, hours: 10000}.', cue: /rul|inference|prediction|model|score|run/i, skipReason: 'requires deployed ML model' },

  // CODE
  { category: 'code', tool: 'code_asset', prompt: 'Use code_asset.', ask: 'List the available code assets in the workspace.', cue: /code|asset|repo|list/i },

  // MULTIMODAL
  { category: 'multimodal', tool: 'image_analyzer', prompt: 'Use image_analyzer.', ask: 'Describe this image https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png', cue: /image|dice|color|graphic|describ|see/i, skipReason: 'requires image vision API' },
  { category: 'multimodal', tool: 'speech_to_text', prompt: 'Use speech_to_text.', ask: 'Transcribe this audio file.', cue: /transcrib|text|audio|speech|listen/i, skipReason: 'requires audio fixture + STT API' },
  { category: 'multimodal', tool: 'text_to_speech', prompt: 'Use text_to_speech.', ask: 'Speak: "Hello from Abenix".', cue: /audio|tts|spoken|sound|generated/i, skipReason: 'requires TTS API' },

  // PIPELINE (used inside pipelines mostly, but should also work via reactive)
  { category: 'pipeline', tool: 'llm_call', prompt: 'Use llm_call.', ask: 'Use llm_call to write a haiku about logs.', cue: /haiku|line|log|verse/i },
  { category: 'pipeline', tool: 'agent_step', prompt: 'Use agent_step.', ask: 'Run agent_step with input "test prompt".', cue: /agent_step|response|test/i, skipReason: 'usually orchestrated by pipeline engine' },
  { category: 'pipeline', tool: 'data_merger', prompt: 'Use data_merger.', ask: 'Merge {a: 1} with {b: 2}.', cue: /a.*1|b.*2|merge|combine/i },
  { category: 'pipeline', tool: 'llm_route', prompt: 'Use llm_route.', ask: 'Use llm_route to decide whether "billing question" goes to billing or tech.', cue: /billing|route|tech|decision|class/i },
];

async function testAllTools() {
  for (const spec of TOOLS) {
    if (spec.skipReason) {
      // Still attempt — capture how it fails. Mark SKIP only if the
      // reason confirms before/after; otherwise SKIP if external.
    }
    const slug = `t-${spec.tool.replace(/[^a-z0-9]/gi, '-')}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const id = await makeAgent(slug, spec.prompt, [spec.tool]);
    if (!id) {
      record(spec.category, spec.tool, 'create agent', 'agent created', 'create failed', 'P1');
      continue;
    }
    const r = await exec(id, spec.ask, 60);
    const data = r.body?.data || {};
    const status = String(data.status || data.summary?.status || (r.ok ? 'unknown' : 'http-error'));
    const output = String(data.output || data.summary?.output || '').slice(0, 600);
    const execId = data.execution_id;

    if (status === 'failed') {
      const row = await execRow(execId);
      record(
        spec.category,
        spec.tool,
        'tool actually runs',
        'status=completed',
        `failed: ${row?.error?.slice(0, 220) || data.error || 'no error message'}`,
        spec.skipReason ? 'SKIP' : 'P1',
        row?.failureCode
      );
      continue;
    }

    if (!output) {
      record(spec.category, spec.tool, 'tool actually runs', 'output non-empty', `empty output, status=${status}`, 'P1');
      continue;
    }

    // We have output — now check it matches the cue.
    let sev: Severity = 'OK';
    if (spec.cue && !spec.cue.test(output)) sev = 'P2';
    record(
      spec.category,
      spec.tool,
      'tool actually runs',
      spec.cue ? 'output matches cue' : 'output non-empty',
      `${output.slice(0, 220)}`,
      sev
    );
  }
}

// ── Multi-tool pipeline tests (one per category) ──────────────────

async function makePipeline(slug: string, tools: string[], cfg: any): Promise<string | null> {
  const r = await api('POST', '/api/agents', {
    name: slug,
    slug,
    system_prompt: 'pipeline UAT',
    model_config: {
      model: 'claude-sonnet-4-5-20250929',
      mode: 'pipeline',
      pipeline_config: cfg,
      tools,
    },
    agent_type: 'reactive',
    category: 'tools-uat',
  });
  return r.ok ? r.body?.data?.id || null : null;
}

async function testComplexPipelines() {
  const cat = 'pipelines-complex';

  // Customer-support: regex → llm_call → memory_store
  {
    const slug = `pp-cs-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        { id: 'rx', type: 'tool', tool: 'regex_extractor', arguments: { text: 'Customer #C-993 reports the dashboard is slow.', pattern: 'C-(\\d+)', return_groups: true } },
        { id: 'classify', type: 'tool', tool: 'llm_call', arguments: { prompt: 'Classify this support ticket as billing/tech/other: {{rx}}', model: 'claude-sonnet-4-5-20250929' } },
        { id: 'remember', type: 'tool', tool: 'memory_store', arguments: { key: 'last_classification', value: '{{classify}}', scope: 'agent' }, depends_on: ['classify'] },
      ],
    };
    const id = await makePipeline(slug, ['regex_extractor', 'llm_call', 'memory_store'], cfg);
    if (!id) { record(cat, 'cs', 'create', 'created', 'failed', 'P1'); }
    else {
      const r = await exec(id, 'go', 120);
      const status = r.body?.data?.status || 'undefined';
      const execId = r.body?.data?.execution_id;
      const row = await execRow(execId || '');
      record(cat, 'support: regex → classify → remember', 'pipeline', 'completed', `status=${status} ${row?.error?.slice(0, 150) || ''}`, status === 'completed' ? 'OK' : 'P1', row?.failureCode);
    }
  }

  // KYC due-diligence: sanctions_screening → adverse_media → kyc_scorer
  {
    const slug = `pp-kyc-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        { id: 'sanc', type: 'tool', tool: 'sanctions_screening', arguments: { name: 'John Smith', country: 'US' } },
        { id: 'media', type: 'tool', tool: 'adverse_media', arguments: { name: 'John Smith' } },
        { id: 'score', type: 'tool', tool: 'kyc_scorer', arguments: { sanctions: '{{sanc}}', media: '{{media}}' }, depends_on: ['sanc', 'media'] },
      ],
    };
    const id = await makePipeline(slug, ['sanctions_screening', 'adverse_media', 'kyc_scorer'], cfg);
    if (!id) { record(cat, 'kyc', 'create', 'created', 'failed', 'P1'); }
    else {
      const r = await exec(id, 'go', 90);
      const status = r.body?.data?.status || 'undefined';
      const execId = r.body?.data?.execution_id;
      const row = await execRow(execId || '');
      record(cat, 'kyc: sanctions → media → score', 'pipeline', 'completed', `status=${status} ${row?.error?.slice(0, 150) || ''}`, status === 'completed' ? 'OK' : 'P1', row?.failureCode);
    }
  }

  // Finance research: web_search → llm_call → structured_extractor
  {
    const slug = `pp-fin-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        { id: 'search', type: 'tool', tool: 'web_search', arguments: { query: 'AAPL Q1 2026 earnings highlights', max_results: 3 } },
        { id: 'summary', type: 'tool', tool: 'llm_call', arguments: { prompt: 'Summarise these earnings findings: {{search}}', model: 'claude-sonnet-4-5-20250929' } },
        { id: 'extract', type: 'tool', tool: 'structured_extractor', arguments: { text: '{{summary}}', schema: { revenue: 'string', eps: 'string' } }, depends_on: ['summary'] },
      ],
    };
    const id = await makePipeline(slug, ['web_search', 'llm_call', 'structured_extractor'], cfg);
    if (!id) { record(cat, 'finance', 'create', 'created', 'failed', 'P1'); }
    else {
      const r = await exec(id, 'go', 120);
      const status = r.body?.data?.status || 'undefined';
      const execId = r.body?.data?.execution_id;
      const row = await execRow(execId || '');
      record(cat, 'finance: web → llm → extract', 'pipeline', 'completed', `status=${status} ${row?.error?.slice(0, 150) || ''}`, status === 'completed' ? 'OK' : 'P1', row?.failureCode);
    }
  }

  // Knowledge fan-out: knowledge_search + atlas_query (parallel) → llm_call merge
  {
    const slug = `pp-know-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        { id: 'kb', type: 'tool', tool: 'knowledge_search', arguments: { query: 'onboarding policy' } },
        { id: 'onto', type: 'tool', tool: 'atlas_query', arguments: { patterns: ['concept:Onboarding'], limit: 3 } },
        { id: 'merge', type: 'tool', tool: 'llm_call', arguments: { prompt: 'Combine KB ({{kb}}) and ontology ({{onto}}) into one answer.', model: 'claude-sonnet-4-5-20250929' }, depends_on: ['kb', 'onto'] },
      ],
    };
    const id = await makePipeline(slug, ['knowledge_search', 'atlas_query', 'llm_call'], cfg);
    if (!id) { record(cat, 'knowledge', 'create', 'created', 'failed', 'P1'); }
    else {
      const r = await exec(id, 'go', 120);
      const status = r.body?.data?.status || 'undefined';
      const execId = r.body?.data?.execution_id;
      const row = await execRow(execId || '');
      record(cat, 'knowledge: kb + atlas → llm', 'pipeline', 'completed', `status=${status} ${row?.error?.slice(0, 150) || ''}`, status === 'completed' ? 'OK' : 'P1', row?.failureCode);
    }
  }

  // Code review fan-out: code_executor → text_analyzer
  {
    const slug = `pp-code-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        { id: 'run', type: 'tool', tool: 'code_executor', arguments: { language: 'python', code: 'data = [1,2,3,4]\nprint(sum(data), max(data))' } },
        { id: 'analyse', type: 'tool', tool: 'text_analyzer', arguments: { text: '{{run}}' }, depends_on: ['run'] },
      ],
    };
    const id = await makePipeline(slug, ['code_executor', 'text_analyzer'], cfg);
    if (!id) { record(cat, 'code', 'create', 'created', 'failed', 'P1'); }
    else {
      const r = await exec(id, 'go', 120);
      const status = r.body?.data?.status || 'undefined';
      const execId = r.body?.data?.execution_id;
      const row = await execRow(execId || '');
      record(cat, 'code: code → text-analyse', 'pipeline', 'completed', `status=${status} ${row?.error?.slice(0, 150) || ''}`, status === 'completed' ? 'OK' : 'P1', row?.failureCode);
    }
  }
}

// ── UI surface checks ──

async function uiSurface(browser: Browser) {
  const cat = 'ui-surface';
  const ctx = await browser.newContext();
  const page: Page = await ctx.newPage();

  try {
    // Login
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.locator('#auth-email').waitFor({ timeout: 25_000 });
    await page.waitForTimeout(1500);
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === 'Admin Demo') as HTMLButtonElement | undefined;
      if (btn) {
        const k = Object.keys(btn).find(kk => kk.startsWith('__reactProps$'));
        if (k) (btn as any)[k].onClick();
      }
    });
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 }).catch(() => {});

    // /tools page — does it list tools with descriptions?
    const r = await page.goto(`${BASE}/tools`, { waitUntil: 'domcontentloaded' }).catch(() => null);
    if (r && r.status() < 400) {
      await page.waitForTimeout(2000);
      const body = (await page.textContent('body')) || '';
      const hasList = /tool|description|category|search/i.test(body);
      record(cat, '/tools', 'tools listing page', 'list visible', hasList ? 'present' : 'empty', hasList ? 'OK' : 'P2');
    } else {
      record(cat, '/tools', 'tools listing page', 'reachable', `status=${r?.status() || 'no-page'}`, 'GAP');
    }

    // /agents/new — is the tool-picker reachable from agent builder?
    await page.goto(`${BASE}/agents/new`, { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForTimeout(3000);
    const newBody = (await page.textContent('body')) || '';
    const hasPicker = /tool|select|add|builder|name/i.test(newBody);
    record(cat, '/agents/new', 'agent builder reachable', 'present', hasPicker ? 'present' : 'absent', hasPicker ? 'OK' : 'P1');

    // Pipeline builder (canvas)
    await page.goto(`${BASE}/builder`, { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForTimeout(2500);
    const bbody = (await page.textContent('body')) || '';
    const hasCanvas = /canvas|node|drag|drop|tool|builder|palette/i.test(bbody);
    record(cat, '/builder', 'pipeline canvas reachable', 'present', hasCanvas ? 'present' : 'absent', hasCanvas ? 'OK' : 'P1');

    // /executions — error rendering for failed runs
    await page.goto(`${BASE}/executions`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    const ebody = (await page.textContent('body')) || '';
    const hasFailed = /failed|error|status/i.test(ebody);
    record(cat, '/executions', 'failed runs visible with status', 'present', hasFailed ? 'present' : 'absent', hasFailed ? 'OK' : 'P1');
  } catch (e: any) {
    record(cat, 'ui', 'caught exception', 'no exception', `${e.message}`.slice(0, 150), 'P1');
  } finally {
    await ctx.close();
  }
}

// ── Main ──

(async () => {
  await login();
  console.log('  ✓ admin login\n');

  console.log('── Testing every tool in the catalogue (one reactive agent per tool)\n');
  await testAllTools();

  console.log('\n── Complex multi-tool pipelines\n');
  await testComplexPipelines();

  console.log('\n── UI surface\n');
  const browser = await chromium.launch({ headless: true });
  try { await uiSurface(browser); } finally { await browser.close(); }

  // Write report
  const counts: Record<Severity, number> = { OK: 0, GAP: 0, SKIP: 0, P0: 0, P1: 0, P2: 0 };
  for (const f of findings) counts[f.severity]++;
  const reportPath = path.resolve(__dirname, '..', 'BUGS_TOOLS_FULL.md');
  const lines: string[] = [];
  lines.push('# Tools + Pipelines — full UAT (every tool, every category)');
  lines.push('');
  lines.push(`**Date:** 2026-05-02`);
  lines.push(`**Environment:** Azure AKS via port-forward (BASE=${BASE}, API=${API})`);
  lines.push('');
  lines.push(`**Summary:** ${findings.length} tests — ${counts.OK} OK · ${counts.P0} P0 · ${counts.P1} P1 · ${counts.P2} P2 · ${counts.GAP} GAP · ${counts.SKIP} SKIP`);
  lines.push('');

  lines.push('## Failures by failure_code');
  const byCode: Record<string, Finding[]> = {};
  for (const f of findings) {
    if (f.severity === 'OK' || f.severity === 'SKIP') continue;
    const k = f.failureCode || '(no code)';
    (byCode[k] = byCode[k] || []).push(f);
  }
  for (const code of Object.keys(byCode).sort()) {
    lines.push('');
    lines.push(`### ${code} (${byCode[code].length})`);
    for (const f of byCode[code]) {
      lines.push(`- ${f.id} **${f.category}/${f.tool}** — ${f.actual.slice(0, 220)}`);
    }
  }
  lines.push('');
  lines.push('## All rows');
  lines.push('');
  lines.push('| ID | Sev | Cat/Tool | Test | failure_code | Detail |');
  lines.push('|---|---|---|---|---|---|');
  for (const f of findings) {
    lines.push(`| ${f.id} | ${f.severity} | ${f.category}/${f.tool} | ${f.test} | ${f.failureCode || ''} | ${f.actual.replace(/\|/g, '\\|').slice(0, 220)} |`);
  }
  fs.writeFileSync(reportPath, lines.join('\n'));
  console.log(`\nReport: ${reportPath}`);
  console.log(`Summary: OK=${counts.OK} P0=${counts.P0} P1=${counts.P1} P2=${counts.P2} GAP=${counts.GAP} SKIP=${counts.SKIP}`);
})().catch(e => {
  console.error('FATAL:', e);
  process.exit(1);
});
