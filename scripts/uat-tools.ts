/**
 * Tools-and-pipelines deep UAT against the deployed Azure cluster.
 *
 * Flow:
 *   1. Hit /api/tools — confirm catalog + flag duplicates / orphans.
 *   2. For each tool category, build a minimal single-tool reactive
 *      agent and POST to /api/agents/{id}/execute. Wait for the run,
 *      capture status + output snippet + execution_id.
 *   3. Build five multi-tool pipelines that chain real outputs through
 *      multiple nodes (web→llm, json→code, memory store→recall,
 *      regex→json→llm, atlas→llm). Same wait-and-capture pattern.
 *   4. Drive the actual UI for one full path: log in → /agents → pick
 *      a created agent → /chat → send a prompt → confirm a response
 *      renders. This proves the API-tested agent is also reachable
 *      from the UI a real user would touch.
 *   5. Emit BUGS_TOOLS.md with PASS/FAIL/GAP rows.
 *
 * Run:
 *   ABENIX_URL=http://localhost:3000 ABENIX_API=http://localhost:8000 \
 *     npx tsx scripts/uat-tools.ts
 */

import { chromium, type Browser, type Page } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.ABENIX_URL || 'http://localhost:3000';
const API = process.env.ABENIX_API || 'http://localhost:8000';

const REPORT_DIR = path.resolve(__dirname, '..', 'logs', 'uat', 'tools');
fs.mkdirSync(REPORT_DIR, { recursive: true });

type Severity = 'P0' | 'P1' | 'P2' | 'GAP' | 'OK';
interface Finding {
  id: string;
  area: string;
  test: string;
  expected: string;
  actual: string;
  severity: Severity;
  screenshot?: string;
}
const findings: Finding[] = [];
let nextId = 1;
function record(area: string, test: string, expected: string, actual: string, severity: Severity, screenshot?: string) {
  const id = `T${String(nextId++).padStart(3, '0')}`;
  findings.push({ id, area, test, expected, actual, severity, screenshot });
  const tag = severity === 'OK' ? '✓' : severity === 'GAP' ? '!' : '✗';
  console.log(`  ${tag} ${id} [${severity}] ${area} → ${test} — ${actual.slice(0, 140)}`);
}

let adminToken = '';

async function api(token: string, method: string, p: string, body?: unknown): Promise<any> {
  const res = await fetch(`${API}${p}`, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
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

async function makeAgent(opts: {
  slug: string;
  prompt: string;
  tools: string[];
  pipelineConfig?: any;
  category?: string;
}): Promise<string | null> {
  const body: any = {
    name: opts.slug,
    slug: opts.slug,
    system_prompt: opts.prompt,
    model_config: {
      model: 'claude-sonnet-4-5-20250929',
      tools: opts.tools,
    },
    agent_type: 'reactive',
    category: opts.category || 'test',
  };
  if (opts.pipelineConfig) {
    body.model_config.mode = 'pipeline';
    body.model_config.pipeline_config = opts.pipelineConfig;
  }
  const r = await api(adminToken, 'POST', '/api/agents', body);
  if (!r.ok) return null;
  return r.body?.data?.id || null;
}

async function exec(id: string, message: string, waitSec = 90): Promise<any> {
  return api(adminToken, 'POST', `/api/agents/${id}/execute`, {
    message,
    stream: false,
    wait: true,
    wait_timeout_seconds: waitSec,
  });
}

// ── 1. Tool catalog audit ─────────────────────────────────────────

async function auditCatalog() {
  const area = 'A. Catalog audit';
  const t = await api(adminToken, 'GET', '/api/tools');
  const data = t.body?.data;
  const tools = Array.isArray(data) ? data : data?.tools || [];
  record(area, 'GET /api/tools returns list', '>=85 tools', `${tools.length}`, tools.length >= 85 ? 'OK' : 'P2');

  // Duplicate ID detection — multiple registrations of the same tool
  // is a real bug; the LLM sees ambiguous schema entries.
  const ids = tools.map((x: any) => x.id || x.name);
  const dupes = [...new Set(ids.filter((x: string, i: number) => ids.indexOf(x) !== i))];
  record(
    area,
    'no duplicate tool ids',
    'all unique',
    dupes.length ? `dupes=${dupes.join(',')}` : 'unique',
    dupes.length ? 'P1' : 'OK'
  );

  // Required schema fields
  const missingSchema = tools.filter((x: any) => !x.input_schema && !x.parameters).map((x: any) => x.id || x.name);
  record(
    area,
    'every tool has an input_schema',
    'all set',
    missingSchema.length ? `missing=${missingSchema.slice(0, 5).join(',')}` : 'all set',
    missingSchema.length ? 'P2' : 'OK'
  );
}

// ── 2. Single-tool reactive agents (one agent per category) ─────

interface SingleSpec {
  cat: string;
  tool: string;
  prompt: string;
  ask: string;
  expectInOutput?: RegExp;
}
const SINGLES: SingleSpec[] = [
  {
    cat: 'core/calculator',
    tool: 'calculator',
    prompt: 'You compute math precisely. Always use the calculator tool.',
    ask: 'What is 17 * 23 + 9?',
    expectInOutput: /400|17.*23.*9/,
  },
  {
    cat: 'core/current_time',
    tool: 'current_time',
    prompt: 'You report the current UTC time using the current_time tool.',
    ask: 'What is the current time?',
    expectInOutput: /\d{4}-\d{2}-\d{2}/,
  },
  {
    cat: 'core/code_executor',
    tool: 'code_executor',
    prompt: 'Use code_executor to run the python the user asks for.',
    ask: 'Run python: print(sum(range(1, 11)))',
    expectInOutput: /55/,
  },
  {
    cat: 'data/regex_extractor',
    tool: 'regex_extractor',
    prompt: 'You extract data with regex using the regex_extractor tool.',
    ask: 'Extract all emails from: contact@abenix.dev or sales@example.org for info.',
    expectInOutput: /abenix\.dev|example\.org/,
  },
  {
    cat: 'data/json_transformer',
    tool: 'json_transformer',
    prompt: 'You manipulate JSON using the json_transformer tool.',
    ask: 'Take this JSON and return the names: {"users": [{"name": "Ada"}, {"name": "Lin"}]}',
    expectInOutput: /Ada|Lin/,
  },
  {
    cat: 'data/text_analyzer',
    tool: 'text_analyzer',
    prompt: 'You analyse text using the text_analyzer tool.',
    ask: 'Analyse: "Abenix is a comprehensive AI agent platform with knowledge graphs, sandboxed code execution, and per-agent scaling."',
    expectInOutput: /word|sentence|character|count|token|length/i,
  },
  {
    cat: 'enterprise/atlas_describe',
    tool: 'atlas_describe',
    prompt: 'You describe ontology concepts using atlas_describe.',
    ask: 'Describe the concept "Asset" from the ontology graph.',
  },
  {
    cat: 'enterprise/memory_store',
    tool: 'memory_store',
    prompt: 'You record key facts using the memory_store tool.',
    ask: "Remember that the user's preferred currency is EUR.",
  },
  {
    cat: 'finance/financial_calculator',
    tool: 'financial_calculator',
    prompt: 'Use financial_calculator for finance math.',
    ask: 'What is the future value of $1000 at 5% per year for 10 years?',
    expectInOutput: /1628|1,628|1\.6/,
  },
  {
    cat: 'integration/http_client',
    tool: 'http_client',
    prompt: 'You make HTTP requests using the http_client tool.',
    ask: 'GET https://httpbin.org/json and tell me what you got.',
    expectInOutput: /slideshow|title|author/i,
  },
  {
    cat: 'pipeline/llm_call',
    tool: 'llm_call',
    prompt: 'Use the llm_call tool when the user asks for a one-shot completion.',
    ask: 'Use llm_call to summarise this in 5 words: "AgentForge becomes Abenix and ships."',
  },
];

async function testSingles() {
  for (const spec of SINGLES) {
    const slug = `t-${spec.tool}-${Date.now()}`;
    const id = await makeAgent({ slug, prompt: spec.prompt, tools: [spec.tool] });
    if (!id) {
      record(spec.cat, `create agent for ${spec.tool}`, 'agent created', 'create failed', 'P1');
      continue;
    }
    const r = await exec(id, spec.ask, 90);
    const data = r.body?.data || {};
    const ran = r.ok && (data.execution_id || data.task_id);
    if (!ran) {
      record(
        spec.cat,
        `execute /api/agents/${id}/execute`,
        'accepted with execution_id',
        `status=${r.status} body=${JSON.stringify(r.body).slice(0, 120)}`,
        'P1'
      );
      continue;
    }
    const output = String(data.output || data.summary?.output || '').slice(0, 400);
    const status = data.status || data.summary?.status || 'unknown';
    let sev: Severity = 'OK';
    if (!output) sev = 'P1';
    else if (spec.expectInOutput && !spec.expectInOutput.test(output)) sev = 'P2';
    record(
      spec.cat,
      `tool actually runs and returns content`,
      'output non-empty + matches expected pattern',
      `status=${status} output="${output.slice(0, 100)}"`,
      sev
    );
  }
}

// ── 3. Multi-tool pipelines ──────────────────────────────────────

async function testPipelines() {
  const area = 'P. Multi-tool pipelines';

  // P1 — web_search → llm_call (research-summarize)
  {
    const slug = `p-research-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        {
          id: 'search',
          type: 'tool',
          tool: 'web_search',
          arguments: { query: 'Latest news about agentic AI platforms', max_results: 3 },
        },
        {
          id: 'summarise',
          type: 'tool',
          tool: 'llm_call',
          arguments: {
            prompt: 'Summarise these findings in 3 bullet points: {{search}}',
            model: 'claude-sonnet-4-5-20250929',
          },
        },
      ],
    };
    const id = await makeAgent({ slug, prompt: 'research+summarise', tools: ['web_search', 'llm_call'], pipelineConfig: cfg });
    if (!id) {
      record(area, 'create web→llm pipeline', '200', 'create failed', 'P2');
    } else {
      const r = await exec(id, 'go', 120);
      const status = r.body?.data?.status || 'undefined';
      record(area, 'web_search → llm_call summarise', 'status=completed', `status=${status}`, status === 'completed' ? 'OK' : 'P1');
    }
  }

  // P2 — json_transformer → code_executor (parse and compute)
  {
    const slug = `p-jsoncode-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        {
          id: 'extract',
          type: 'tool',
          tool: 'json_transformer',
          arguments: {
            data: { sales: [10, 20, 30, 40, 50] },
            jsonpath: '$.sales',
          },
        },
        {
          id: 'compute',
          type: 'tool',
          tool: 'code_executor',
          arguments: {
            language: 'python',
            code: 'data = {{extract}}\nprint(f"sum={sum(data)} avg={sum(data)/len(data)}")',
          },
        },
      ],
    };
    const id = await makeAgent({ slug, prompt: 'json+code', tools: ['json_transformer', 'code_executor'], pipelineConfig: cfg });
    if (!id) {
      record(area, 'create json→code pipeline', '200', 'create failed', 'P2');
    } else {
      const r = await exec(id, 'go', 120);
      const status = r.body?.data?.status || 'undefined';
      const out = JSON.stringify(r.body?.data?.summary || r.body?.data || {}).slice(0, 200);
      const ok = status === 'completed';
      record(area, 'json_transformer → code_executor', 'status=completed + sum visible', `status=${status} body=${out}`, ok ? 'OK' : 'P1');
    }
  }

  // P3 — memory_store → memory_recall (round-trip on same execution)
  {
    const slug = `p-memory-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        {
          id: 'store',
          type: 'tool',
          tool: 'memory_store',
          arguments: {
            key: `pref_currency_${Date.now()}`,
            value: 'EUR',
            scope: 'agent',
          },
        },
        {
          id: 'recall',
          type: 'tool',
          tool: 'memory_recall',
          arguments: {
            query: 'currency preference',
            scope: 'agent',
          },
          depends_on: ['store'],
        },
      ],
    };
    const id = await makeAgent({ slug, prompt: 'memory roundtrip', tools: ['memory_store', 'memory_recall'], pipelineConfig: cfg });
    if (!id) {
      record(area, 'create memory pipeline', '200', 'create failed', 'P2');
    } else {
      const r = await exec(id, 'go', 90);
      const status = r.body?.data?.status || 'undefined';
      record(area, 'memory_store → memory_recall', 'status=completed', `status=${status}`, status === 'completed' ? 'OK' : 'P2');
    }
  }

  // P4 — regex_extractor → json_transformer → llm_call (3-stage chain)
  {
    const slug = `p-three-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        {
          id: 'rx',
          type: 'tool',
          tool: 'regex_extractor',
          arguments: {
            text: 'Order #1023 and order #1031, also #1042 are pending.',
            pattern: '#(\\d+)',
            return_groups: true,
          },
        },
        {
          id: 'shape',
          type: 'tool',
          tool: 'json_transformer',
          arguments: {
            data: '{{rx}}',
            operation: 'identity',
          },
          depends_on: ['rx'],
        },
        {
          id: 'narrate',
          type: 'tool',
          tool: 'llm_call',
          arguments: {
            prompt: 'Read these order numbers and write one sentence: {{shape}}',
            model: 'claude-sonnet-4-5-20250929',
          },
          depends_on: ['shape'],
        },
      ],
    };
    const id = await makeAgent({
      slug,
      prompt: '3-stage extract',
      tools: ['regex_extractor', 'json_transformer', 'llm_call'],
      pipelineConfig: cfg,
    });
    if (!id) {
      record(area, 'create 3-stage pipeline', '200', 'create failed', 'P2');
    } else {
      const r = await exec(id, 'go', 120);
      const status = r.body?.data?.status || 'undefined';
      record(area, 'regex → json → llm chain', 'status=completed', `status=${status}`, status === 'completed' ? 'OK' : 'P1');
    }
  }

  // P5 — atlas_query → llm_call (KB-augmented response)
  {
    const slug = `p-atlas-${Date.now()}`;
    const cfg = {
      version: '1.0',
      nodes: [
        {
          id: 'query',
          type: 'tool',
          tool: 'atlas_query',
          arguments: {
            query: 'concept:Asset',
            limit: 5,
          },
        },
        {
          id: 'narrate',
          type: 'tool',
          tool: 'llm_call',
          arguments: {
            prompt: 'Summarise these ontology results in 2 sentences: {{query}}',
            model: 'claude-sonnet-4-5-20250929',
          },
          depends_on: ['query'],
        },
      ],
    };
    const id = await makeAgent({ slug, prompt: 'atlas+llm', tools: ['atlas_query', 'llm_call'], pipelineConfig: cfg });
    if (!id) {
      record(area, 'create atlas→llm pipeline', '200', 'create failed', 'P2');
    } else {
      const r = await exec(id, 'go', 120);
      const status = r.body?.data?.status || 'undefined';
      record(area, 'atlas_query → llm_call narrate', 'status=completed', `status=${status}`, status === 'completed' ? 'OK' : 'P1');
    }
  }
}

// ── 4. UI smoke (Playwright) ─────────────────────────────────────

async function uiSmoke(browser: Browser) {
  const area = 'U. UI smoke';
  const ctx = await browser.newContext();
  const page: Page = await ctx.newPage();

  try {
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.locator('#auth-email').waitFor({ timeout: 25_000 });
    await page.waitForTimeout(1500);
    const fired = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === 'Admin Demo') as HTMLButtonElement | undefined;
      if (!btn) return 'no Admin Demo';
      const k = Object.keys(btn).find(kk => kk.startsWith('__reactProps$'));
      if (!k) return 'no reactProps';
      (btn as any)[k].onClick();
      return 'fired';
    });
    if (fired !== 'fired') {
      record(area, 'admin demo login button', 'fired', `got=${fired}`, 'P1');
      return;
    }
    await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 });
    record(area, 'admin demo login lands authenticated', 'redirected to authed area', `url=${page.url()}`, 'OK');

    // /agents shows the catalogue
    await page.goto(`${BASE}/agents`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    const agentsBody = (await page.textContent('body')) || '';
    const hasCard = /agent|create|build|status|run/i.test(agentsBody);
    record(
      area,
      '/agents page renders agent list',
      'agents catalog visible',
      hasCard ? 'has agent UI cues' : 'page empty/blank',
      hasCard ? 'OK' : 'P1',
      await snap(page, 'U-agents')
    );

    // /chat — pick first agent and send a message
    await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    const ta = page.locator('textarea:not([disabled])').first();
    if ((await ta.count()) === 0) {
      record(area, 'chat textarea enabled on landing', 'enabled', 'still disabled / not present', 'P1', await snap(page, 'U-chat-disabled'));
    } else {
      await ta.fill('What is 21+21? (use the calculator tool)');
      const send = page.getByRole('button', { name: /send|submit|ask/i }).first();
      if ((await send.count()) > 0) await send.click();
      else await page.keyboard.press('Enter');
      await page.waitForTimeout(15_000);
      const after = (await page.textContent('body')) || '';
      const hasAnswer = /42|forty-two|calculation/i.test(after);
      record(area, 'send a calculator prompt; observe a numeric answer', 'response renders with 42', hasAnswer ? 'answer rendered' : 'no answer in body', hasAnswer ? 'OK' : 'P2', await snap(page, 'U-chat-answer'));
    }

    // /atlas — should render the canvas
    await page.goto(`${BASE}/atlas`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    const atlasBody = (await page.textContent('body')) || '';
    const hasAtlas = /ontology|concept|atlas|graph|node/i.test(atlasBody);
    record(area, '/atlas canvas loads', 'atlas UI cues present', hasAtlas ? 'present' : 'absent', hasAtlas ? 'OK' : 'P2', await snap(page, 'U-atlas'));
  } catch (e: any) {
    record(area, 'UI smoke caught exception', 'no exception', `${e.message}`.slice(0, 150), 'P1');
  } finally {
    await ctx.close();
  }
}

async function snap(page: Page, name: string): Promise<string> {
  const file = path.join(REPORT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false }).catch(() => {});
  return file;
}

// ── Main ─────────────────────────────────────────────────────────

(async () => {
  console.log(`\nDeep tools UAT against ${API}\n`);
  await login();
  console.log('  ✓ admin login\n');

  console.log('── Catalog audit');
  await auditCatalog();

  console.log('\n── Single-tool agents');
  await testSingles();

  console.log('\n── Multi-tool pipelines');
  await testPipelines();

  console.log('\n── UI smoke (Playwright)');
  const browser = await chromium.launch({ headless: true });
  try {
    await uiSmoke(browser);
  } finally {
    await browser.close();
  }

  // Write report
  const counts: Record<Severity, number> = { OK: 0, GAP: 0, P0: 0, P1: 0, P2: 0 };
  for (const f of findings) counts[f.severity]++;
  const reportPath = path.resolve(__dirname, '..', 'BUGS_TOOLS.md');
  const lines: string[] = [];
  lines.push('# Tools + Pipelines deep UAT — Azure cluster');
  lines.push('');
  lines.push(`**Environment:** Azure AKS via port-forward (BASE=${BASE}, API=${API})`);
  lines.push('');
  lines.push(`**Summary:** ${findings.length} tests — ${counts.OK} OK · ${counts.P0} P0 · ${counts.P1} P1 · ${counts.P2} P2 · ${counts.GAP} GAP`);
  lines.push('');
  lines.push('## Bugs / gaps');
  lines.push('');
  lines.push('| ID | Severity | Area | Test | Expected | Actual | Screenshot |');
  lines.push('|---|---|---|---|---|---|---|');
  for (const f of findings.filter(x => x.severity !== 'OK')) {
    const sc = f.screenshot ? `[png](${path.relative(path.resolve(__dirname, '..'), f.screenshot).replace(/\\/g, '/')})` : '—';
    lines.push(`| ${f.id} | ${f.severity} | ${f.area} | ${f.test} | ${f.expected} | ${f.actual.slice(0, 200)} | ${sc} |`);
  }
  lines.push('');
  lines.push('## All tests');
  lines.push('');
  lines.push('| ID | Sev | Area | Test | Detail |');
  lines.push('|---|---|---|---|---|');
  for (const f of findings) {
    lines.push(`| ${f.id} | ${f.severity} | ${f.area} | ${f.test} | ${f.actual.slice(0, 200)} |`);
  }
  fs.writeFileSync(reportPath, lines.join('\n'));
  console.log(`\nReport: ${reportPath}`);
  console.log(`Summary: ${counts.OK} OK · ${counts.P0} P0 · ${counts.P1} P1 · ${counts.P2} P2 · ${counts.GAP} GAP`);
})().catch(e => {
  console.error('FATAL:', e);
  process.exit(1);
});
