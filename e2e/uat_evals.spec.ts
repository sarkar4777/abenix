/**
 * Evaluation suites as a real user: create a suite, add cases with the assertion builder, run it,
 * read the results, save a past run as a case, and watch the gate block and then allow a publish.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_evals.spec.ts --workers=1
 *
 * The first test is deterministic. The run tests execute the agent for real, so they need a working
 * LLM credential (Claude Haiku 4.5 by default, override with EVAL_MODEL). Set SKIP_LIVE_LLM=1 to skip them.
 */
import { test, expect, type Page } from '@playwright/test';
import { openFromSidebar } from './helpers/sidebar';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const MODEL = process.env.EVAL_MODEL || 'claude-haiku-4-5-20251001';
const LIVE = !process.env.SKIP_LIVE_LLM;
const STAMP = Date.now().toString(36);

let token = '';
let agentId = '';
let suiteId = '';

async function login(page: Page) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  expect(res.ok(), `login ${ADMIN.email}`).toBeTruthy();
  token = (await res.json())?.data?.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('refresh_token', t); }, token);
}

async function api(page: Page, method: string, p: string, body?: unknown) {
  // one retry, a reused keep-alive socket can be closed under us
  const res = await page.request.fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  }).catch(() => page.request.fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  }));
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function latestRunId(page: Page): Promise<string | null> {
  const r = await api(page, 'GET', `/api/evals/suites/${suiteId}/runs?limit=1`);
  return r.json?.data?.[0]?.id ?? null;
}

// waits for a run newer than the one before the click, the old one is already finished
async function waitForRun(page: Page, before: string | null, timeoutMs = 240_000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    const r = await api(page, 'GET', `/api/evals/suites/${suiteId}/runs?limit=1`);
    const run = r.json?.data?.[0];
    if (run && run.id !== before && !['queued', 'running'].includes(run.status)) return run;
    await page.waitForTimeout(3000);
  }
  throw new Error('the evaluation run did not finish in time');
}

async function addCase(page: Page, name: string, input: string, needle: string) {
  await page.getByTestId('eval-add-case').click();
  const ed = page.getByTestId('eval-case-editor').first();
  await ed.getByTestId('eval-case-name').fill(name);
  await ed.getByTestId('eval-case-input').fill(input);
  await ed.getByTestId('assertion-add').click();
  await page.getByTestId('assertion-add-contains').click();
  const value = ed.getByTestId('a0-value');
  await expect(ed.getByRole('alert')).toContainText('required');
  await value.fill(needle);
  await expect(ed.getByRole('alert')).toHaveCount(0);
  await ed.getByTestId('eval-case-save').click();
  await expect(page.getByTestId('eval-cases')).toContainText(name);
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await login(page);
  const r = await api(page, 'POST', '/api/agents', {
    name: `Eval echo ${STAMP}`,
    system_prompt: 'You are a test agent. Reply with exactly the single word PONG and nothing else.',
    model_config: {
      model: MODEL,
      temperature: 0,
      tools: [],
      max_tokens: 64,
      risk_tier: 'high',
      output_schema: { type: 'string' },
    },
  });
  expect(r.status, JSON.stringify(r.json)).toBeLessThan(300);
  agentId = r.json.data.id;
  await page.close();
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await login(page);
  if (suiteId) await api(page, 'DELETE', `/api/evals/suites/${suiteId}`);
  if (agentId) await api(page, 'DELETE', `/api/agents/${agentId}`);
  await page.close();
});

test('a gating suite is created from the sidebar and blocks publishing before it has run', async ({ page }) => {
  await login(page);
  await visit(page, '/dashboard');
  await openFromSidebar(page, '/evals');
  await expect(page.getByRole('heading', { name: 'Evaluations' })).toBeVisible();

  await page.getByTestId('eval-new-suite').click();
  await page.getByTestId('eval-suite-agent').selectOption(agentId);
  await expect(page.getByTestId('eval-suite-gating')).toBeChecked();
  await page.getByTestId('eval-suite-name').fill(`Echo golden ${STAMP}`);
  await page.getByTestId('eval-suite-create').click();
  await expect(page.getByTestId('eval-suite-title')).toHaveText(`Echo golden ${STAMP}`);
  suiteId = page.url().split('/evals/')[1].split(/[?#]/)[0];

  await expect(page.getByTestId('eval-run-now')).toBeDisabled();
  await addCase(page, 'Says pong', 'ping', 'PONG');
  await addCase(page, 'Mentions the moon', 'ping', 'MOON');
  await expect(page.getByTestId('eval-run-now')).toBeEnabled();

  await expect(page.getByTestId('eval-gate-banner')).toHaveAttribute('data-state', 'not_run');
  const pub = await api(page, 'POST', `/api/agents/${agentId}/publish`, { visibility: 'tenant' });
  expect(pub.status).toBe(409);
  expect(pub.json.error.error_code).toBe('EVAL_GATE');
  expect(pub.json.error.message).toContain('has not been run');
});

test('the assertion builder previews against a sample answer', async ({ page }) => {
  await login(page);
  await visit(page, `/evals/${suiteId}`);
  await page.getByTestId('eval-add-case').click();
  const ed = page.getByTestId('eval-case-editor').first();
  await ed.locator('summary', { hasText: 'sample answer' }).click();
  await ed.getByTestId('eval-case-sample').fill('{"decision": "refuse"}');
  await ed.getByTestId('assertion-add').click();
  await page.getByTestId('assertion-add-json_path_equals').click();
  await ed.getByTestId('a0-path').fill('decision');
  await ed.getByTestId('a0-value').fill('approve');
  await expect(ed.getByTestId('assertion-0')).toContainText('Fails', { timeout: 10_000 });
  await ed.getByTestId('a0-value').fill('refuse');
  await expect(ed.getByTestId('assertion-0')).toContainText('Holds', { timeout: 10_000 });
  await expect(ed.getByTestId('assertion-preview-summary')).toContainText('1 of 1');
  await ed.getByRole('button', { name: 'Cancel' }).click();
});

test('a run executes every case, shows reasons per case and still blocks publishing', async ({ page }) => {
  test.skip(!LIVE, 'needs a live LLM');
  test.setTimeout(300_000);
  await login(page);
  await visit(page, `/evals/${suiteId}`);
  const before = await latestRunId(page);
  await page.getByTestId('eval-run-now').click();
  await expect(page.getByTestId('eval-active-run')).toBeVisible();
  const run = await waitForRun(page, before);
  const why = JSON.stringify((await api(page, 'GET', `/api/evals/runs/${run.id}`)).json?.data?.results, null, 1)?.slice(0, 3000);
  expect(run.status, why).toBe('completed');
  expect(run.passed, why).toBe(1);
  expect(run.threshold_met).toBe(false);

  await visit(page, `/evals/runs/${run.id}`);
  await expect(page.getByTestId('eval-run-score')).toHaveText('50%');
  await expect(page.getByTestId('eval-run-verdict')).toHaveText('Below threshold');
  const failed = page.getByTestId('eval-run-results').locator('[data-testid^="eval-result-"]', { hasText: 'Mentions the moon' });
  await expect(failed).toContainText('is not in the output');
  await failed.getByRole('button').first().click();
  await expect(failed.getByTestId('eval-result-execution')).toBeVisible();

  const pub = await api(page, 'POST', `/api/agents/${agentId}/publish`, { visibility: 'tenant' });
  expect(pub.status).toBe(409);
  expect(pub.json.error.message).toContain('Mentions the moon');
  await visit(page, `/evals/${suiteId}`);
  await expect(page.getByTestId('eval-gate-banner')).toHaveAttribute('data-state', 'failed');
  await expect(page.getByTestId('eval-gate-run')).toBeVisible();
});

test('a past run is saved as a case from the execution page', async ({ page }) => {
  test.skip(!LIVE, 'needs a live LLM');
  await login(page);
  const runs = await api(page, 'GET', `/api/evals/suites/${suiteId}/runs?limit=1`);
  const detail = await api(page, 'GET', `/api/evals/runs/${runs.json.data[0].id}`);
  const exId = detail.json.data.results.find((r: any) => r.execution_id).execution_id;
  await visit(page, `/executions/${exId}`);
  await page.getByTestId('execution-save-eval-case').click();
  await page.getByRole('radio', { name: new RegExp(`Echo golden ${STAMP}`) }).check();
  await page.getByTestId('save-case-confirm').click();
  await page.getByTestId('save-case-open-suite').click();
  await expect(page.getByTestId('eval-cases')).toContainText('ping');
  const s = await api(page, 'GET', `/api/evals/suites/${suiteId}`);
  const saved = s.json.data.cases.find((c: any) => c.source_execution_id === exId);
  expect(saved.assertions.length).toBeGreaterThan(0);
  await api(page, 'DELETE', `/api/evals/cases/${saved.id}`);
});

test('fixing the suite and running again lets the agent publish', async ({ page }) => {
  test.skip(!LIVE, 'needs a live LLM');
  test.setTimeout(300_000);
  await login(page);
  await visit(page, `/evals/${suiteId}`);
  const moon = page.getByTestId('eval-cases').locator('[data-testid^="eval-case-"]', { hasText: 'Mentions the moon' });
  await moon.getByRole('button').first().click();
  await moon.getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('button', { name: 'Delete case' }).click();
  await expect(page.getByTestId('eval-cases')).not.toContainText('Mentions the moon');

  const before = await latestRunId(page);
  await page.getByTestId('eval-gate-run').click();
  const run = await waitForRun(page, before);
  const detail = await api(page, 'GET', `/api/evals/runs/${run.id}`);
  expect(run.threshold_met, JSON.stringify(detail.json?.data, null, 1)?.slice(0, 4000)).toBe(true);
  await visit(page, `/evals/${suiteId}`);
  await expect(page.getByTestId('eval-gate-banner')).toHaveAttribute('data-state', 'passed');

  await page.getByTestId('eval-tab-runs').click();
  await expect(page.getByTestId('runs-chart')).toBeVisible();
  await expect(page.getByTestId('eval-runs-table')).toContainText('Passed');

  const pub = await api(page, 'POST', `/api/agents/${agentId}/publish`, { visibility: 'tenant' });
  expect(pub.status, JSON.stringify(pub.json)).toBe(200);
});
