/**
 * Exploratory pass over the platform the way a new user meets it.
 *
 * This is not a pass/fail gate. It walks the surfaces, runs real agents, and
 * writes what it found to test-results/platform-gaps.json so the gaps can be
 * read in one place. A test here only fails when the platform is unreachable.
 *
 * What it looks at, in order of how often a new user hits it:
 *   1. Can I tell which tools need an API key, and where do I add one?
 *   2. What happens when I run an agent whose tool has no key?
 *   3. Do the three tool catalogues agree with the registry?
 *   4. Do the most complex seeded agents actually run on a fresh install?
 *   5. Does the execution detail page explain a multi-tool run?
 *
 *   USE_K8S=true npx playwright test e2e/uat_gaps_exploratory.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';
const OUT = path.join('test-results', 'platform-gaps.json');
const SHOTS = path.join('test-results', 'gaps');

type Finding = {
  area: string;
  severity: 'blocker' | 'major' | 'minor' | 'note';
  what: string;
  evidence?: unknown;
  screenshot?: string;
};
const findings: Finding[] = [];
function note(f: Finding) { findings.push(f); console.log(`  [${f.severity}] ${f.area}: ${f.what}`); }

let token = '';

async function login(page: Page) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  expect(res.ok(), 'login').toBeTruthy();
  token = (await res.json())?.data?.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('refresh_token', t); }, token);
}

// Playwright's request context gives up after 15 seconds by default. A run
// that asks the server to hold the connection for five minutes needs longer,
// otherwise the client times out and reports a fault the server never had.
async function api(page: Page, method: string, p: string, body?: unknown, timeoutMs = 30_000) {
  const opts = {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
    timeout: timeoutMs,
  };
  let res;
  try {
    res = await page.request.fetch(`${API}${p}`, opts);
  } catch (e: any) {
    // retry once on a dropped connection, a reused keep-alive socket can close under the request
    if (!/socket hang up|ECONNRESET|fetch failed/i.test(String(e?.message))) throw e;
    res = await page.request.fetch(`${API}${p}`, opts);
  }
  let json: any = null; try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const p = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function bodyText(page: Page) { return (await page.locator('body').innerText()).slice(0, 30000); }

/**
 * The page without its chrome. The sidebar has a link called "API Keys", so a
 * regex for "api key" over the whole body matches on every page and said the
 * tools catalogue explains credentials when it does not.
 */
async function mainText(page: Page) {
  const main = page.locator('main');
  if (await main.count()) return (await main.first().innerText()).slice(0, 30000);
  return (await page.locator('body').innerText()).replace(/API Keys/g, '').slice(0, 30000);
}

async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

/** Run an agent and return what a user would get back. */
async function runAgent(page: Page, agentId: string, message: string, timeoutS = 240) {
  const r = await api(page, 'POST', `/api/agents/${agentId}/execute`, {
    message, stream: false, wait: true, wait_timeout_seconds: timeoutS,
  }, (timeoutS + 30) * 1000);
  const d = r.json?.data ?? {};
  // The execute endpoint hands back a parsed object when the agent's answer
  // is JSON. String() on that is "[object Object]", which looked like a bug.
  const raw = d.output ?? d.final_output ?? d.result ?? '';
  return {
    http: r.status, status: d.status, failure_code: d.failure_code,
    output: (typeof raw === 'string' ? raw : JSON.stringify(raw)).slice(0, 1200),
    error: String(d.error ?? d.error_message ?? '').slice(0, 600),
    execution_id: d.id ?? d.execution_id,
  };
}

/** Tools we know need a credential this cluster does not have. */
// Each of these reads a credential this cluster does not have. They were
// chosen because the tools handle the absence four different ways, and the
// point is to see which of those a user can actually act on.
const MISSING_KEY_TOOLS: Record<string, { env: string; prompt: string; expects: string }> = {
  ais_stream:      { env: 'AISSTREAM_API_KEY',      expects: 'hard error, names the var, says edit a k8s Secret',
                     prompt: 'Show me live vessel positions near Rotterdam right now.' },
  credit_risk:     { env: 'FMP_API_KEY',            expects: 'hard error, names the var, says run export in a shell',
                     prompt: 'Assess the credit risk of Shell plc using the credit_risk tool.' },
  companies_house: { env: 'COMPANIES_HOUSE_API_KEY', expects: 'needs_configuration, points at a platform Integrations store that cannot take a key',
                     prompt: 'Look up Shell plc on Companies House and give me its registration details.' },
  github_tool:     { env: 'GITHUB_TOKEN',           expects: 'public reads work unauthenticated, writes should fail',
                     prompt: 'Create an issue titled "probe" on the repository sarkar4777/abenix.' },
  ubo_discovery:   { env: 'OPENCORPORATES_API_KEY', expects: 'calls the API unauthenticated and may return empty',
                     prompt: 'Who are the ultimate beneficial owners of Shell plc?' },
  translation:     { env: 'DEEPL_API_KEY',          expects: 'falls back to LibreTranslate, which is also unset',
                     prompt: 'Translate "good morning, the shipment is delayed" into German using the translation tool.' },
  twilio_sms:      { env: 'TWILIO_AUTH_TOKEN',      expects: 'graceful no-op that may read as success',
                     prompt: 'Send an SMS to +15555550100 saying the report is ready.' },
  email_sender:    { env: 'SMTP_HOST',              expects: 'unknown',
                     prompt: 'Email ops@example.com with the subject "test" and body "hello".' },
};

/** Complex seeded agents, matched loosely by slug or name. */
const COMPLEX_AGENTS = [
  'kyc_standard_check', 'cq_adjudicate_pipeline', 'cq_fraud_screener', 'repo_analyzer',
  'credit_risk_assessor', 'data_pipeline_engineer', 'oraclenet', 'action_executor',
];

test.describe.serial('platform gaps, exploratory', () => {
  test.setTimeout(20 * 60 * 1000);

  test.afterAll(() => {
    fs.mkdirSync('test-results', { recursive: true });
    fs.writeFileSync(OUT, JSON.stringify({ generated: new Date().toISOString(), findings }, null, 2));
    console.log(`\n  ${findings.length} findings -> ${OUT}`);
  });

  test('1. where does a user learn a tool needs a key, and where do they add one', async ({ page }) => {
    await login(page);

    // Tools catalogue. Does any tool say it needs a credential?
    await visit(page, '/tools');
    const toolsShot = await shot(page, '01-tools-catalogue');
    const toolsText = await mainText(page);
    const mentionsKey = /api key|api_key|credential|requires .*key|not configured|needs key|optional key|key set/i.test(toolsText);
    expect.soft(mentionsKey, 'tools catalogue shows credential badges').toBeTruthy();
    const regCfg = await api(page, 'GET', '/api/tools');
    const regRows: any[] = Array.isArray(regCfg.json?.data) ? regCfg.json.data : regCfg.json?.data?.tools ?? [];
    expect.soft(regRows.filter(t => t.config && t.config.status !== 'none').length, '/api/tools carries config for keyed tools').toBeGreaterThan(30);
    note({
      area: 'tools catalogue', severity: mentionsKey ? 'note' : 'major',
      what: mentionsKey ? 'catalogue mentions keys somewhere' : 'no tool in the catalogue says it needs a credential or where to add one',
      evidence: { chars: toolsText.length }, screenshot: toolsShot,
    });

    // Open a key-dependent tool and see what the detail says.
    const github = page.getByText(/github/i).first();
    if (await github.count()) {
      await github.click().catch(() => {});
      await page.waitForTimeout(600);
      const detail = await mainText(page);
      const d = /token|api key|credential|GITHUB_TOKEN/i.test(detail);
      note({
        area: 'tools catalogue / github_tool detail', severity: d ? 'note' : 'major',
        what: d ? 'github_tool detail mentions a token' : 'github_tool detail never mentions that GITHUB_TOKEN is required',
        screenshot: await shot(page, '02-tools-github-detail'),
      });
    }

    // Integrations page. Is there any control to ADD a key, or only instructions?
    await visit(page, '/settings/integrations');
    const intShot = await shot(page, '03-integrations');
    const intText = await bodyText(page);
    const hasInput = await page.locator('input[type="password"], input[name*="key" i], input[placeholder*="key" i]').count();
    const hasSave = await page.getByRole('button', { name: /save|add key|connect|configure/i }).count();
    note({
      area: 'integrations page', severity: hasInput || hasSave ? 'note' : 'blocker',
      what: hasInput || hasSave
        ? 'page offers a way to enter a key'
        : 'page is read-only. A user is handed kubectl and helm commands, with no way to add a key from the product. Keys cannot be added at runtime.',
      evidence: { passwordInputs: hasInput, saveButtons: hasSave, mentionsKubectl: /kubectl/.test(intText), mentionsHelm: /helm upgrade/.test(intText) },
      screenshot: intShot,
    });

    // Since 2.5 the way to add a key is Admin -> Tool Configuration. The integrations page links to it.
    expect.soft(/Tool Configuration/i.test(intText), 'integrations page points at Admin -> Tool Configuration').toBeTruthy();
    expect.soft(/kubectl create secret/.test(intText), 'integrations page no longer hands out kubectl').toBeFalsy();
    await visit(page, '/admin/tool-config');
    const cfgInputs = await page.locator('input[type="password"]').count();
    const cfgSave = await page.getByRole('button', { name: /^save$/i }).count();
    expect.soft(cfgInputs, 'tool-config has secret inputs').toBeGreaterThan(10);
    expect.soft(cfgSave, 'tool-config has save buttons').toBeGreaterThan(10);
    note({ area: 'admin tool-config', severity: cfgInputs && cfgSave ? 'note' : 'blocker', what: `${cfgInputs} secret inputs, ${cfgSave} save buttons`, screenshot: await shot(page, '03b-admin-tool-config') });
    await visit(page, '/settings/integrations');

    // Which of the tool keys does the integrations page even list?
    const listed = (intText.match(/[A-Z][A-Z0-9_]+_(API_KEY|TOKEN|SECRET|KEY|SID|URL)/g) || []);
    const listedSet = new Set(listed);
    const expectedKeys = ['TAVILY_API_KEY','BRAVE_SEARCH_API_KEY','SERPAPI_API_KEY','SERPER_API_KEY','NEWS_API_KEY','MEDIASTACK_API_KEY',
      'FRED_API_KEY','EIA_API_KEY','ALPHA_VANTAGE_API_KEY','ENTSOE_API_KEY','AISSTREAM_API_KEY','BALTIC_API_KEY','GITHUB_TOKEN',
      'DEEPL_API_KEY','TWILIO_AUTH_TOKEN','OPENCORPORATES_API_KEY','OPENSANCTIONS_API_KEY','COMPANIES_HOUSE_API_KEY','FMP_API_KEY',
      'MOODYS_API_KEY','SPG_RATINGS_API_KEY','FITCH_CONNECT_API_KEY','COINGECKO_API_KEY','ELEVENLABS_API_KEY','ZAPIER_NLA_KEY',
      'AIRTABLE_API_KEY','NOTION_API_KEY','JIRA_TOKEN'];
    const absent = expectedKeys.filter(k => !listedSet.has(k));
    expect.soft(absent, 'every key a tool reads is on the integrations page').toEqual([]);
    note({
      area: 'integrations page coverage', severity: absent.length > 5 ? 'major' : 'minor',
      what: `${absent.length} of ${expectedKeys.length} credentials that tools read are not on the integrations page at all`,
      evidence: { absent },
    });
    if (/ENTSO_E_TOKEN/.test(intText)) {
      note({ area: 'integrations page', severity: 'major',
        what: 'ENTSO-E row names ENTSO_E_TOKEN but the tool reads ENTSOE_API_KEY, so the status badge is wrong either way' });
    }

    // Agent builder palette. Pick a key-dependent tool and see if anything warns.
    await visit(page, '/builder');
    await page.waitForTimeout(1200);
    await page.locator('input[placeholder*="earch"]').first().fill('github').catch(() => {});
    await page.waitForTimeout(800);
    const palText = await mainText(page);
    const warns = /api key|credential|not configured|requires|needs key|optional key|key set/i.test(palText);
    expect.soft(warns, 'builder palette shows a credential badge on github_tool').toBeTruthy();
    note({
      area: 'agent builder', severity: warns ? 'note' : 'major',
      what: warns ? 'builder mentions credentials' : 'builder lets you add a key-dependent tool with no warning that the key is missing',
      screenshot: await shot(page, '04-agent-builder'),
    });

    // The in-product help. If a tool needs a key, is there anywhere that says so in plain words?
    for (const route of ['/help', '/dev-docs']) {
      await visit(page, route);
      const t = await bodyText(page);
      const explains = /api key|integrations/i.test(t);
      const saysWhere = /settings\/integrations|\/integrations|admin|kubectl|helm|\.env/i.test(t);
      note({
        area: `help ${route}`, severity: explains ? 'note' : 'minor',
        what: explains
          ? `mentions keys/integrations${saysWhere ? ' and says where' : ' but not where to add one'}`
          : 'never mentions that any tool needs a credential',
        screenshot: await shot(page, `04b-help${route.replace(/\//g, '-')}`),
      });
    }

    // Is there a runtime settings surface at all? Admin -> LLM Settings stores a secret token already.
    await visit(page, '/admin/llm-settings');
    const llmText = await bodyText(page);
    note({
      area: 'admin llm-settings', severity: 'note',
      what: /subscription|token/i.test(llmText)
        ? 'a DB-backed, masked, runtime secret store already exists here for the subscription token. Tool keys do not use it.'
        : 'llm-settings page rendered without the subscription section',
      screenshot: await shot(page, '05-admin-llm-settings'),
    });
  });

  test('2. three catalogues versus the registry', async ({ page }) => {
    await login(page);
    const reg = await api(page, 'GET', '/api/tools');
    const tools: any[] = Array.isArray(reg.json?.data) ? reg.json.data : (reg.json?.data?.tools ?? []);
    // The slug is `id`. `name` is the display label, so matching on it found
    // nothing and reported every probe tool as unregistered.
    const names = new Set(tools.map(t => t.id ?? t.name));
    note({ area: 'registry', severity: 'note', what: `${names.size} tools registered`, evidence: { fields: Object.keys(tools[0] ?? {}) } });
    const hasKeyField = tools.some(t => t.config && Array.isArray(t.config.fields) && t.config.fields.length > 0);
    expect.soft(hasKeyField, '/api/tools carries config.fields').toBeTruthy();
    note({
      area: 'registry', severity: hasKeyField ? 'note' : 'major',
      what: hasKeyField ? 'registry records credential needs' : '/api/tools carries no field saying which tools need a credential, so no UI can know',
    });

    // Builder palette ids, read from the page module the way the browser does.
    await visit(page, '/builder');
    const palette = await page.evaluate(() => {
      const out: string[] = [];
      document.querySelectorAll('[data-tool-id], [draggable="true"]').forEach(el => {
        const id = el.getAttribute('data-tool-id') || el.textContent?.trim();
        if (id) out.push(id);
      });
      return out;
    });
    note({ area: 'builder palette', severity: 'note', what: `${palette.length} draggable items found on /builder`, screenshot: await shot(page, '06-builder') });
  });

  test('3. what the user gets when a tool has no key', async ({ page }) => {
    await login(page);
    const reg = await api(page, 'GET', '/api/tools');
    const tools: any[] = Array.isArray(reg.json?.data) ? reg.json.data : (reg.json?.data?.tools ?? []);
    const registered = new Set(tools.map(t => t.id ?? t.name));

    for (const [tool, spec] of Object.entries(MISSING_KEY_TOOLS)) {
      if (!registered.has(tool)) {
        note({ area: `missing key / ${tool}`, severity: 'minor', what: `${tool} is not in the registry, skipped` });
        continue;
      }
      const mk = await api(page, 'POST', '/api/agents', {
        name: `probe-${tool}-${Date.now()}`, category: 'other',
        description: `Probe for ${tool} without ${spec.env}`,
        system_prompt: `You must use the ${tool} tool to answer. Report exactly what the tool returns. Do not invent data.`,
        model_config: { mode: 'agent', model: 'claude-haiku-4-5', tools: [tool], max_iterations: 4 },
      });
      const id = (mk.json?.data ?? {}).id;
      if (!id) { note({ area: `missing key / ${tool}`, severity: 'major', what: `could not create probe agent (${mk.status})`, evidence: mk.json }); continue; }

      const r = await runAgent(page, id, spec.prompt, 180);

      // What the tool actually returned, separately from what the model then
      // said. The executor records content_preview and is_error per call, and
      // the gap is usually in the distance between the two.
      // Per-tool output is not on the execution row. It is rebuilt by the
      // replay endpoint, so read all three and match across them.
      const [tree, detail, replay, live] = await Promise.all([
        api(page, 'GET', `/api/executions/tree/${r.execution_id}`),
        api(page, 'GET', `/api/executions/${r.execution_id}`),
        api(page, 'GET', `/api/executions/${r.execution_id}/replay`),
        api(page, 'GET', `/api/executions/live/${r.execution_id}`),
      ]);
      const rawNodes = [tree, detail, replay, live].map(x => JSON.stringify(x.json ?? {})).join('');
      // The executor records the tool's text as content_preview in the trace
      // and as result_preview in the live event stream. Take either.
      const toolCalls = (rawNodes.match(/"(content_preview|result_preview)":"((?:[^"\\]|\\.)*)"/g) || [])
        .map(s => s.replace(/^"(content_preview|result_preview)":"/, '').slice(0, -1).replace(/\\n/g, ' ').slice(0, 300));
      const toolErrored = /"is_error":\s*true/.test(rawNodes);
      const toolSkipped = /"skipped":\s*true|not configured|needs_configuration|not set/i.test(rawNodes);

      const text = `${r.output} ${r.error}`;
      const namesEnv = text.includes(spec.env);
      const saysMissing = /not (set|configured)|is not configured|no .{0,40}(provider|key|credential)s? (is|are) configured|not translated|not sent|missing|no api key|requires? (an? )?(api )?key|unavailable|not available|could not|unable to|needs? to (be )?configure/i.test(text);
      const toolSaidNo = toolErrored || toolSkipped;
      let severity: Finding['severity'] = 'note';
      let what = '';
      if (r.status === 'failed') {
        severity = 'major';
        what = `run FAILED (${r.failure_code}). The user gets a failed execution rather than an answer`;
      } else if (toolSaidNo && !saysMissing) {
        // The worst case. The tool reported a problem and the answer hid it.
        severity = 'blocker';
        what = `the tool reported it could not run, but the answer the user sees does not say so`;
      } else if (namesEnv) {
        what = `answer names ${spec.env}. Whether a user can act on that depends on what it tells them to do with it`;
        if (/kubectl|secret|export |helm/i.test(text)) { severity = 'major'; what += ' — and it tells a web user to edit a Kubernetes Secret or run a shell command'; }
        if (/platform Integrations|secrets store/i.test(text)) { severity = 'major'; what += ' — and it points at an Integrations page that cannot take a key'; }
      } else if (saysMissing) {
        severity = 'major';
        what = `answer says the tool is unavailable but never names ${spec.env} or where to add it`;
      } else if (!toolSaidNo) {
        what = `tool ran without the key (public tier or unauthenticated), answer looks normal`;
      } else {
        severity = 'major';
        what = `no clear signal about the missing key`;
      }
      const pointsToScreen = /Tool Configuration/i.test(text) || /Tool Configuration/i.test(rawNodes);
      const namesAKey = namesEnv || /[A-Z][A-Z0-9_]{3,}_(API_KEY|TOKEN|SECRET|SID|HOST|KEY)/.test(text);
      expect.soft(severity, `${tool}: ${what}`).not.toBe('blocker');
      if (toolSaidNo) {
        // the model sometimes paraphrases the key name, the screen reference is the part a user acts on
        expect.soft(namesAKey || pointsToScreen, `${tool}: the answer names the key or the admin screen`).toBeTruthy();
        expect.soft(pointsToScreen, `${tool}: the answer or the trace points at Admin -> Tool Configuration`).toBeTruthy();
        expect.soft(/kubectl|helm|export [A-Z_]+=/i.test(text), `${tool}: no shell instructions for a web user`).toBeFalsy();
      }
      // only meaningful when the model called the tool at all
      const persisted = Array.isArray(detail.json?.data?.tool_calls) ? detail.json.data.tool_calls.length : 0;
      if (persisted > 0) expect.soft(toolCalls.length > 0, `${tool}: the tool's result is persisted on the execution`).toBeTruthy();
      note({ area: `missing key / ${tool}`, severity, what,
        evidence: { expected: spec.expects, status: r.status, failure_code: r.failure_code,
          tool_returned: toolCalls.slice(0, 3), tool_is_error: toolErrored, tool_skipped: toolSkipped,
          user_saw: r.output.slice(0, 500), error: r.error } });
      await api(page, 'DELETE', `/api/agents/${id}`);
    }
  });

  test('3b. silent answers, where a missing key can read as a real result', async ({ page }) => {
    await login(page);
    const probes = [
      {
        tool: 'translation', env: 'DEEPL_API_KEY',
        prompt: 'Translate exactly this into German and give me only the translation: "the shipment is delayed"',
        // With no provider the tool hands back the input unchanged, and only
        // metadata says skipped. The model never sees metadata.
        bad: (out: string) => /the shipment is delayed/i.test(out) && !/not configured|no translation provider|could not translate|unable/i.test(out),
        badWhat: 'returned the untranslated English as if it were the translation',
      },
      {
        tool: 'legal_existence_verifier', env: 'COMPANIES_HOUSE_API_KEY',
        prompt: 'Verify whether "Shell plc" legally exists and is in good standing in the United Kingdom.',
        // Companies House lookup returns [] silently without its key. A "does
        // not exist" or "not found" here would be a false negative.
        bad: (out: string) => /not found|does not exist|no record|could not find|unverified/i.test(out) && !/companies house.*(not configured|unavailable|skipped|no key)|without.*companies house/i.test(out),
        badWhat: 'reported the company as not found while the Companies House source was silently skipped',
      },
      {
        tool: 'pep_screening', env: 'OPENSANCTIONS_API_KEY',
        prompt: 'Screen the name "Emmanuel Macron" for politically exposed person status.',
        // A sitting head of state must hit. An empty result here means the
        // unauthenticated OpenSanctions call failed and nothing said so.
        bad: (out: string) => /no (pep )?(match|hit|result)|not a pep|clear|no exposure/i.test(out) && !/warning|unavailable|could not|rate.?limit|unauthenticated/i.test(out),
        badWhat: 'cleared a sitting head of state as not a PEP, with no warning that a source was unavailable',
      },
    ];
    for (const p of probes) {
      const mk = await api(page, 'POST', '/api/agents', {
        name: `probe-silent-${p.tool}-${Date.now()}`, category: 'other', description: 'silent answer probe',
        system_prompt: `Use the ${p.tool} tool and report its result faithfully. If the tool reports a problem, say so.`,
        model_config: { mode: 'agent', model: 'claude-haiku-4-5', tools: [p.tool], max_iterations: 4 },
      });
      const id = (mk.json?.data ?? {}).id;
      if (!id) { note({ area: `silent / ${p.tool}`, severity: 'minor', what: `could not create probe (${mk.status})` }); continue; }
      const r = await runAgent(page, id, p.prompt, 180);
      const [tree, replay, live] = await Promise.all([
        api(page, 'GET', `/api/executions/tree/${r.execution_id}`),
        api(page, 'GET', `/api/executions/${r.execution_id}/replay`),
        api(page, 'GET', `/api/executions/live/${r.execution_id}`),
      ]);
      const raw = [tree, replay, live].map(x => JSON.stringify(x.json ?? {})).join('');
      const toolCalls = (raw.match(/"(content_preview|result_preview)":"((?:[^"\\]|\\.)*)"/g) || [])
        .map(s => s.replace(/^"(content_preview|result_preview)":"/, '').slice(0, -1).replace(/\\n/g, ' ').slice(0, 300));
      const isBad = r.status === 'completed' && p.bad(r.output);
      note({ area: `silent / ${p.tool}`, severity: isBad ? 'blocker' : r.status === 'failed' ? 'major' : 'note',
        what: isBad ? p.badWhat : r.status === 'failed' ? `run failed (${r.failure_code})` : 'answer did not read as a silent false result',
        evidence: { env: p.env, status: r.status, tool_returned: toolCalls.slice(0, 3), user_saw: r.output.slice(0, 500) } });
      await api(page, 'DELETE', `/api/agents/${id}`);
    }
  });

  test('4. the complex seeded agents on a fresh install', async ({ page }) => {
    await login(page);
    const all: any[] = [];
    for (let off = 0; off < 400; off += 100) {
      const r = await api(page, 'GET', `/api/agents?limit=100&offset=${off}`);
      const rows = r.json?.data ?? [];
      if (!rows.length) break;
      all.push(...rows);
    }
    const norm = (s: string) => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    for (const want of COMPLEX_AGENTS) {
      const hit = all.find(a => norm(a.slug).includes(norm(want)) || norm(a.name).includes(norm(want)));
      if (!hit) { note({ area: `complex / ${want}`, severity: 'minor', what: 'not found among seeded agents' }); continue; }
      const toolsUsed: string[] = hit.model_config?.tools ?? [];
      const prompt = want.includes('kyc') || want.includes('fraud') || want.includes('adjudicate')
        ? 'Run a standard check on the company "Shell plc", registered in the United Kingdom.'
        : want.includes('repo') ? 'Analyse the repository sarkar4777/abenix and summarise its structure.'
        : want.includes('credit') ? 'Assess the credit risk of Shell plc.'
        : 'Give me a short worked example of what you do, using your tools.';
      const r = await runAgent(page, hit.id, prompt, 300);
      const sev: Finding['severity'] = r.status === 'failed' ? 'major' : r.status === 'completed' ? 'note' : 'major';
      note({ area: `complex / ${hit.slug ?? hit.name}`, severity: sev,
        what: `${toolsUsed.length} tools, run ${r.status}${r.failure_code ? ` (${r.failure_code})` : ''}`,
        evidence: { tools: toolsUsed, output: r.output.slice(0, 600), error: r.error, execution_id: r.execution_id } });

      // Look at the execution page the way a user would, for the first one that ran.
      if (r.execution_id && !findings.some(f => f.area === 'execution detail')) {
        await visit(page, `/executions/${r.execution_id}`);
        const t = await bodyText(page);
        const showsTools = /tool|step|node|trace/i.test(t);
        const showsError = r.status === 'failed' ? /error|fail/i.test(t) : true;
        note({ area: 'execution detail', severity: showsTools && showsError ? 'note' : 'major',
          what: `${showsTools ? 'shows' : 'does not show'} tool steps, ${showsError ? 'shows' : 'hides'} the failure`,
          screenshot: await shot(page, '07-execution-detail') });
      }
    }
  });

  test('5. the rest of the surfaces render with content', async ({ page }) => {
    await login(page);
    const routes = ['/dashboard', '/agents', '/builder', '/knowledge', '/atlas', '/code-runner', '/ml-models',
      '/triggers', '/approvals', '/mcp', '/executions', '/analytics', '/alerts', '/edge', '/marketplace',
      '/persona', '/meetings', '/bpm-analyzer', '/portfolio-schemas', '/admin/scaling', '/admin/rbac',
      '/settings/api-keys', '/help'];
    for (const r of routes) {
      await visit(page, r);
      const t = await bodyText(page);
      // Anchor on error UI, not on digits. A bare "500" matched "1500ms" on
      // the scaling console and called a healthy page broken.
      const err = /application error|something went wrong|unhandled runtime error|internal server error|cannot read propert|minified react error|\berror:\s*5\d\d\b/i.test(t);
      const thin = t.trim().length < 150;
      if (err || thin) {
        note({ area: `page ${r}`, severity: err ? 'major' : 'minor',
          what: err ? 'renders an error' : `renders almost nothing (${t.trim().length} chars)`,
          screenshot: await shot(page, `08-page${r.replace(/\//g, '-')}`) });
      }
    }
    note({ area: 'pages', severity: 'note', what: `${routes.length} routes visited` });
  });
});
