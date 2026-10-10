/**
 * Pipeline execute paths, through the builder and the chat.
 *
 * A pipeline whose first step always fails is set to "Carry on" in the builder,
 * then run from the builder (not streamed), from the chat (streamed, on the
 * worker pool and inline) and from the API without streaming. On every path
 * the steps after the failure must run and {{input.region}} must resolve.
 * Last, a step that hangs must stop at pipeline.timeout_seconds with a plain
 * message on both streamed paths.
 *
 * Run: USE_K8S=true npx playwright test e2e/uat_pipeline_execute_paths.spec.ts
 */

import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
// lowering the platform limit touches every run on the cluster for about three minutes
const CHECK_TIMEOUT = process.env.E2E_TIMEOUT_CHECK !== '0';

test.use({ viewport: { width: 1440, height: 900 } });
test.describe.configure({ mode: 'serial' });

const ids: { agent?: string; hang?: string } = {};

let session: { token: string; user: unknown } | null = null;

// one password sign-in for the whole file, repeated logins trip the auth rate limit
async function signIn(page: Page) {
  if (!session) {
    const r = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
    expect(r.ok(), `login HTTP ${r.status()}`).toBeTruthy();
    const d = (await r.json()).data;
    const me = await page.request.get(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${d.access_token}` } });
    const mj = await me.json().catch(() => ({}));
    session = { token: d.access_token, user: mj.data ?? mj };
  }
  await page.addInitScript(({ t, u }) => {
    localStorage.setItem('access_token', t);
    localStorage.setItem('refresh_token', t);
    localStorage.setItem('user', JSON.stringify(u));
  }, { t: session.token, u: session.user });
  await page.goto(`${BASE}/dashboard`, { waitUntil: 'commit' });
}

async function api(page: Page, method: string, p: string, body?: unknown) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const headers: Record<string, string> = { Authorization: `Bearer ${tok}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await page.request.fetch(`${API}${p}`, {
    method,
    headers,
    data: body === undefined ? undefined : JSON.stringify(body),
    timeout: 240_000,
  });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

function pipelineAgent(name: string, nodes: unknown[]) {
  return {
    name,
    description: 'Checks that steps after a failure still run and inputs resolve on every execute path.',
    model_config: {
      mode: 'pipeline',
      tools: ['http_client', 'json_transformer', 'human_approval'],
      pipeline_config: { nodes },
      input_variables: [
        { name: 'region', type: 'string', required: false, default: 'emea', description: 'Sales region' },
      ],
    },
  };
}

const CARRY_ON_NODES = [
  {
    id: 'fetch',
    label: 'Fetch rates',
    tool_name: 'http_client',
    // not http, so it fails at once without touching the network
    arguments: { url: 'ftp://rates.example.invalid/rates.csv', method: 'GET' },
    depends_on: [],
  },
  {
    id: 'report',
    label: 'Report',
    tool_name: 'json_transformer',
    arguments: { operation: 'identity', data: { region: '{{input.region}}', fetch_error: '{{fetch.error}}' } },
    depends_on: ['fetch'],
  },
  {
    id: 'wrap',
    label: 'Wrap up',
    tool_name: 'json_transformer',
    arguments: { operation: 'identity', data: { done: 'yes', region: '{{input.region}}' } },
    depends_on: ['report'],
  },
];

async function latestRun(page: Page, agentId: string, after: string[]) {
  for (let i = 0; i < 90; i++) {
    const list = await api(page, 'GET', `/api/executions?agent_id=${agentId}&limit=5`);
    const rows: any[] = list.json?.data?.executions || list.json?.data || [];
    const fresh = rows.find((r) => !after.includes(r.id) && !['running', 'pending', 'queued'].includes(String(r.status).toLowerCase()));
    if (fresh) {
      const full = await api(page, 'GET', `/api/executions/${fresh.id}`);
      return full.json?.data ?? fresh;
    }
    await page.waitForTimeout(2000);
  }
  throw new Error('no finished run showed up');
}

async function runIds(page: Page, agentId: string): Promise<string[]> {
  const list = await api(page, 'GET', `/api/executions?agent_id=${agentId}&limit=20`);
  const rows: any[] = list.json?.data?.executions || list.json?.data || [];
  return rows.map((r) => r.id);
}

function parsed(v: unknown): any {
  if (typeof v !== 'string') return v;
  try { return JSON.parse(v); } catch { return v; }
}

// the carry-on contract on one finished run
function expectCarriedOn(run: any, region: string, where: string) {
  const nr = run.node_results || run.execution_trace?.node_results || {};
  expect(nr.fetch?.status, `${where}: the fetch step failed`).toBe('failed');
  expect(nr.report?.status, `${where}: the step after the failure ran`).toBe('completed');
  expect(nr.wrap?.status, `${where}: the step after that ran too`).toBe('completed');
  const data = parsed(nr.report?.resolved_arguments?.data) || {};
  expect(data.region, `${where}: {{input.region}} resolved`).toBe(region);
  expect(String(data.fetch_error), `${where}: the error reached the next step`).toMatch(/HTTP/i);
  expect(JSON.stringify(nr)).not.toContain('[not available]');
}

async function chatOnce(page: Page, agentId: string, message: string, timeoutMs = 240_000) {
  await page.goto(`${BASE}/agents/${agentId}/chat`, { waitUntil: 'domcontentloaded' });
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: timeoutMs });
}

async function setPool(page: Page, agentId: string, pool: string) {
  const r = await api(page, 'PATCH', `/api/admin/scaling/agents/${agentId}`, { runtime_pool: pool });
  expect(r.status, `pool set to ${pool}`).toBe(200);
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test('1. builder: set a failing step to carry on and run it, the next steps run with the input', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  const created = await api(page, 'POST', '/api/agents', pipelineAgent(`Carry on check ${RUN}`, CARRY_ON_NODES));
  expect(created.status, JSON.stringify(created.json).slice(0, 300)).toBeLessThan(300);
  ids.agent = created.json.data.id;

  await page.goto(`${BASE}/builder?agent=${ids.agent}`, { waitUntil: 'domcontentloaded' });
  await page.locator('.react-flow__node[data-id="fetch"]').click();
  await page.getByRole('button', { name: 'On failure', exact: true }).click();
  const choice = page.getByTestId('step-on-error');
  await expect(choice).toHaveValue('stop');
  const autosave = page.waitForResponse(
    (r) => r.request().method() === 'PUT' && r.url().includes(`/api/agents/${ids.agent}`),
    { timeout: 30_000 },
  );
  await choice.selectOption('continue');
  await expect(page.getByText(/They can read the failure as \{\{fetch\.error\}\}/)).toBeVisible();
  await autosave;
  const saved = await api(page, 'GET', `/api/agents/${ids.agent}`);
  const fetchNode = saved.json.data.model_config.pipeline_config.nodes.find((n: any) => n.id === 'fetch');
  expect(fetchNode.on_error, 'the builder saved on_error: continue').toBe('continue');

  const before = await runIds(page, ids.agent!);
  await page.getByTestId('pipeline-run-button').click();
  const ask = page.getByTestId('run-inputs-dialog');
  await expect(ask).toBeVisible({ timeout: 10_000 });
  await ask.getByTestId('run-input-region').fill('apac-builder');
  await ask.getByTestId('run-inputs-submit').click();
  await expect(page.getByText(/^Pipeline (completed|failed)$/)).toBeVisible({ timeout: 120_000 });
  await page.screenshot({ path: 'e2e/screenshots/pipeline-carry-on-builder.png', fullPage: true });

  const run = await latestRun(page, ids.agent!, before);
  expectCarriedOn(run, 'apac-builder', 'builder run');
});

test('2. chat, streamed, on the worker pool and inline: same result, input default resolves', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  expect(ids.agent, 'test 1 created the agent').toBeTruthy();

  for (const pool of ['default', 'inline']) {
    await setPool(page, ids.agent!, pool);
    const before = await runIds(page, ids.agent!);
    await chatOnce(page, ids.agent!, `Run the rates report (${pool})`);
    await expect(page.getByTestId('chat-error')).toHaveCount(0);
    const run = await latestRun(page, ids.agent!, before);
    console.log(`streamed on ${pool}: ${run.status}`);
    expectCarriedOn(run, 'emea', `streamed on ${pool}`);
  }
});

test('3. API, not streamed, inline: {{input.x}} resolves from the context', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  expect(ids.agent, 'test 1 created the agent').toBeTruthy();
  await setPool(page, ids.agent!, 'inline');
  const before = await runIds(page, ids.agent!);
  const r = await api(page, 'POST', `/api/agents/${ids.agent}/execute`, {
    message: 'Run the rates report',
    stream: false,
    context: { region: 'latam-api' },
  });
  expect(r.status, JSON.stringify(r.json).slice(0, 300)).toBe(200);
  const run = await latestRun(page, ids.agent!, before);
  expectCarriedOn(run, 'latam-api', 'non-streamed API run');
});

test('4. a hanging step stops at pipeline.timeout_seconds with a plain message, streamed', async ({ page }) => {
  test.skip(!CHECK_TIMEOUT, 'E2E_TIMEOUT_CHECK=0');
  test.setTimeout(12 * 60_000);
  const hang = await api(page, 'POST', '/api/agents', pipelineAgent(`Timeout check ${RUN}`, [
    {
      id: 'slow',
      label: 'Wait for sign-off',
      // nobody answers, so the step waits out its own 150 s
      tool_name: 'human_approval',
      arguments: { action: 'E2E timeout check, leave unanswered', risk_level: 'low', timeout_seconds: 150 },
      depends_on: [],
    },
    {
      id: 'after',
      tool_name: 'json_transformer',
      arguments: { operation: 'identity', data: { region: '{{input.region}}' } },
      depends_on: ['slow'],
    },
  ]));
  expect(hang.status).toBeLessThan(300);
  ids.hang = hang.json.data.id;

  const old = await api(page, 'GET', '/api/admin/settings');
  const cats: Record<string, any[]> = old.json?.data?.categories || {};
  const rows: any[] = Object.values(cats).flat();
  const prev = String(rows.find((r: any) => r.key === 'pipeline.timeout_seconds')?.value ?? '300');
  console.log(`pipeline.timeout_seconds was ${prev}`);
  try {
    const set = await api(page, 'PATCH', '/api/admin/settings/pipeline.timeout_seconds', { value: '60' });
    expect(set.status, JSON.stringify(set.json).slice(0, 200)).toBe(200);
    // the API and the runtime cache settings for 30 s
    await page.waitForTimeout(32_000);

    for (const pool of ['inline', 'default']) {
      await setPool(page, ids.hang!, pool);
      const before = await runIds(page, ids.hang!);
      const t0 = Date.now();
      await chatOnce(page, ids.hang!, `Fetch the slow feed (${pool})`, 150_000);
      const secs = Math.round((Date.now() - t0) / 1000);
      const run = await latestRun(page, ids.hang!, before);
      console.log(`timeout on ${pool}: ${secs}s, ${run.status}, ${run.failure_code}: ${run.error_message}`);
      expect(String(run.status).toLowerCase()).toBe('failed');
      expect(run.error_message, `${pool}: plain message`).toMatch(/ran out of time/i);
      expect(run.error_message).not.toMatch(/Traceback|Exception/);
      expect(run.failure_code).toBe('RUNTIME_TIMEOUT');
      expect(secs, `${pool}: stopped near the 60 s limit, not the step's own 150 s`).toBeLessThan(110);
      const shown = await page.getByTestId('chat-error').innerText().catch(() => '');
      console.log(`  chat shows: ${shown.slice(0, 200)}`);
      expect(shown, `${pool}: the chat names the time limit, not the AI provider`).toMatch(/time limit/i);
    }
  } finally {
    await api(page, 'PATCH', '/api/admin/settings/pipeline.timeout_seconds', { value: prev });
  }
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await signIn(page);
  for (const id of [ids.agent, ids.hang]) if (id) await api(page, 'DELETE', `/api/agents/${id}`);
  await page.close();
});
