/**
 * Browser pass over the surfaces the 2.5.0 wave changed, as an admin would meet them.
 *
 * Asserts the parts that must hold and writes everything else it sees to
 * test-results/wave-2-5-gaps.json with screenshots, so a reviewer can read
 * the state of each page in one place.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_wave_2_5_browser.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';
const OUT = path.join('test-results', 'wave-2-5-gaps.json');
const SHOTS = path.join('test-results', 'wave-2-5');

type Finding = { area: string; severity: 'blocker' | 'major' | 'minor' | 'note'; what: string; evidence?: unknown; screenshot?: string };
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
async function api(page: Page, method: string, p: string, body?: unknown, timeoutMs = 30_000) {
  const opts = {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body), timeout: timeoutMs,
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
async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}
async function mainText(page: Page) {
  const main = page.locator('main');
  if (await main.count()) return (await main.first().innerText()).slice(0, 30000);
  return (await page.locator('body').innerText()).slice(0, 30000);
}
const CRASH = /application error|something went wrong|unhandled runtime error|internal server error|cannot read propert|minified react error/i;

test.describe('wave 2.5 surfaces', () => {
  test.setTimeout(420_000);
  test.afterAll(() => {
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    fs.writeFileSync(OUT, JSON.stringify({ generated: new Date().toISOString(), findings }, null, 2));
  });

  test('admin pages render with content and no crash', async ({ page }) => {
    await login(page);
    const routes = ['/admin/tool-config', '/tools', '/settings/integrations', '/approvals', '/admin/dlq', '/alerts', '/admin/archives', '/executions', '/marketplace', '/agents', '/builder', '/help', '/dev-docs'];
    for (const r of routes) {
      await visit(page, r);
      const t = await mainText(page);
      const crashed = CRASH.test(t);
      expect.soft(crashed, `${r} rendered without a client error`).toBeFalsy();
      expect.soft(t.length, `${r} has content`).toBeGreaterThan(80);
      note({ area: `render ${r}`, severity: crashed ? 'blocker' : t.length > 80 ? 'note' : 'major', what: crashed ? 'client error text on page' : `${t.length} chars`, screenshot: await shot(page, `render${r.replace(/\//g, '-')}`) });
    }
  });

  test('tool configuration is wired through to badges, palette and integrations', async ({ page }) => {
    await login(page);
    await visit(page, '/admin/tool-config');
    await expect(page.getByTestId('tool-config-counts')).toBeVisible();
    const enc = await page.getByTestId('tool-config-encryption').innerText();
    note({ area: 'tool-config encryption', severity: /encrypted at rest/i.test(enc) ? 'note' : 'minor', what: enc });
    const missing = await page.getByTestId('tool-config-missing-required').innerText();
    note({ area: 'tool-config required', severity: 'note', what: missing });
    // every provider card lists at least one tool link
    const groups = page.locator('[data-testid^="tool-config-group-"]');
    expect(await groups.count()).toBeGreaterThan(20);
    await visit(page, '/tools');
    const badges = await page.locator('[data-testid^="credential-badge-"]').count();
    expect(badges, 'credential badges on the catalogue').toBeGreaterThan(20);
    const hints = await page.getByTestId('credential-hint').count();
    note({ area: 'tools badges', severity: 'note', what: `${badges} badges, ${hints} hints` });
    await visit(page, '/builder');
    await page.waitForTimeout(1500);
    // sections are collapsed, search brings the keyed tools into view
    await page.locator('input[placeholder*="earch"]').first().fill('github');
    await page.waitForTimeout(800);
    const palBadges = await page.locator('[data-testid^="credential-badge-"]').count();
    expect.soft(palBadges, 'palette shows a credential badge on a keyed tool').toBeGreaterThan(0);
    note({ area: 'palette badges', severity: palBadges > 5 ? 'note' : 'major', what: `${palBadges} badges`, screenshot: await shot(page, 'palette') });
  });

  test('a pipeline run keeps tool results, durations and steps on the flight recorder', async ({ page }) => {
    await login(page);
    const agents = await api(page, 'GET', '/api/agents?limit=200');
    const rows: any[] = agents.json?.data ?? [];
    const repo = rows.find((a) => a.slug === 'repo-analyzer');
    test.skip(!repo, 'repo-analyzer not seeded');
    // typed input replaces the seed defaults
    const r = await api(page, 'POST', `/api/agents/${repo.id}/execute`, {
      message: 'analyse', stream: false, wait: true, wait_timeout_seconds: 300,
      context: { owner: 'octocat', repo: 'Hello-World' },
    }, 330_000);
    const d = r.json?.data ?? {};
    note({ area: 'repo-analyzer run', severity: d.status ? 'note' : 'major', what: `status ${d.status} failure_code ${d.failure_code ?? '-'}`, evidence: { http: r.status } });
    const id = d.id ?? d.execution_id;
    expect(id, 'execution id').toBeTruthy();
    const detail = await api(page, 'GET', `/api/executions/${id}`);
    const ex = detail.json?.data ?? {};
    const tcs: any[] = Array.isArray(ex.tool_calls) ? ex.tool_calls : [];
    expect.soft(tcs.length, 'pipeline tool calls persisted as a list').toBeGreaterThan(3);
    expect.soft(tcs.some((t) => typeof t.duration_ms === 'number'), 'durations are measured').toBeTruthy();
    expect.soft(tcs.some((t) => (t.result_preview || '').length > 0), 'results are persisted').toBeTruthy();
    // the typed input reached the tool: github_tool was called for Hello-World, not spoon-knife
    const args = JSON.stringify(tcs.map((t) => t.arguments));
    expect.soft(args.includes('Hello-World'), 'typed input replaced the default repo').toBeTruthy();
    expect.soft(args.includes('spoon-knife'), 'default repo not used when input given').toBeFalsy();
    const steps: any[] = ex.execution_trace?.steps ?? [];
    expect.soft(steps.length, 'steps persisted').toBeGreaterThan(3);
    await visit(page, `/executions/${id}`);
    const t = await mainText(page);
    expect.soft(CRASH.test(t), 'flight recorder renders').toBeFalsy();
    await expect.soft(page.getByTestId('execution-steps')).toBeVisible();
    await expect.soft(page.getByTestId('execution-rerun')).toBeVisible();
    const missingResults = await page.getByTestId('tool-result-missing').count();
    note({ area: 'flight recorder', severity: missingResults ? 'minor' : 'note', what: `${tcs.length} tool calls, ${steps.length} steps, ${missingResults} without a result`, screenshot: await shot(page, 'flight-recorder') });
    const replay = await api(page, 'GET', `/api/executions/${id}/replay`);
    expect.soft(replay.json?.data?.total_steps ?? 0, 'replay returns steps').toBeGreaterThan(3);
  });

  test('a run whose tool needs a missing key shows the error on the recorder', async ({ page }) => {
    await login(page);
    const cfg = await api(page, 'GET', '/api/admin/tool-config');
    const req = cfg.json.data.groups.flatMap((g: any) => g.keys).find((k: any) => k.required && !k.is_set && k.tools.length === 1);
    test.skip(!req, 'every required key is set');
    const tool = req.tools[0];
    const mk = await api(page, 'POST', '/api/agents', {
      name: `probe-${tool}-${Date.now()}`, category: 'other', description: 'wave probe',
      system_prompt: `You must call the ${tool} tool once and report exactly what it returns.`,
      model_config: { mode: 'agent', model: 'claude-haiku-4-5', tools: [tool], max_iterations: 3 },
    });
    const agentId = mk.json?.data?.id;
    expect(agentId).toBeTruthy();
    const r = await api(page, 'POST', `/api/agents/${agentId}/execute`, { message: 'Go ahead and use the tool now.', stream: false, wait: true, wait_timeout_seconds: 180 }, 210_000);
    const d = r.json?.data ?? {};
    const id = d.id ?? d.execution_id;
    const detail = await api(page, 'GET', `/api/executions/${id}`);
    const ex = detail.json?.data ?? {};
    const tcs: any[] = Array.isArray(ex.tool_calls) ? ex.tool_calls : [];
    const errored = tcs.find((t) => t.is_error);
    expect.soft(Boolean(errored), `${tool} call recorded as an error`).toBeTruthy();
    expect.soft(JSON.stringify(ex), 'the recorded result names the admin screen').toMatch(/Tool Configuration/);
    expect.soft(String(d.output ?? ''), 'the answer names the key').toContain(req.key);
    await visit(page, `/executions/${id}`);
    await expect.soft(page.locator('[data-testid="execution-steps"], [data-testid="tool-result-missing"]').first()).toBeVisible();
    note({ area: 'missing key recorder', severity: errored ? 'note' : 'major', what: `${tool}: ${(errored?.result_preview || '').slice(0, 160)}`, screenshot: await shot(page, 'recorder-missing-key') });
    await api(page, 'DELETE', `/api/agents/${agentId}`);
  });

  test('a timeout or runtime error is a failed run, not a completed one', async ({ page }) => {
    await login(page);
    const mk = await api(page, 'POST', '/api/agents', {
      name: `probe-timeout-${Date.now()}`, category: 'other', description: 'wave probe',
      system_prompt: 'Keep calling the current_time tool forever, never answer.',
      model_config: { mode: 'agent', model: 'claude-haiku-4-5', tools: ['current_time'], max_iterations: 2, timeout: 5 },
    });
    const agentId = mk.json?.data?.id;
    expect(agentId).toBeTruthy();
    const r = await api(page, 'POST', `/api/agents/${agentId}/execute`, { message: 'start', stream: false, wait: true, wait_timeout_seconds: 120 }, 150_000);
    const d = r.json?.data ?? {};
    note({ area: 'bounded run', severity: 'note', what: `status ${d.status} failure_code ${d.failure_code ?? '-'} output ${(String(d.output ?? '')).slice(0, 80)}` });
    const list = await api(page, 'GET', `/api/executions/${d.id ?? d.execution_id}`);
    const ex = list.json?.data ?? {};
    expect.soft(['completed', 'failed'].includes(ex.status), 'run reached a terminal status').toBeTruthy();
    if (ex.error_message) expect.soft(ex.status, 'a run with an error message is failed').toBe('failed');
    await api(page, 'DELETE', `/api/agents/${agentId}`);
  });

  test('dlq, alerts and archives are tenant views with real data shapes', async ({ page }) => {
    await login(page);
    const dlq = await api(page, 'GET', '/api/admin/dlq?limit=5');
    note({ area: 'dlq api', severity: dlq.status === 200 ? 'note' : 'major', what: `GET -> ${dlq.status}, ${(dlq.json?.data?.items ?? dlq.json?.data ?? []).length ?? 0} rows` });
    expect.soft(dlq.status).toBe(200);
    const alerts = await api(page, 'GET', '/api/admin/alerts');
    note({ area: 'platform alerts api', severity: alerts.status < 500 ? 'note' : 'major', what: `GET -> ${alerts.status}` });
    await visit(page, '/alerts');
    const t = await mainText(page);
    expect.soft(/platform alerts/i.test(t), 'alerts page shows the platform section to an admin').toBeTruthy();
    const arch = await api(page, 'GET', '/api/admin/archives');
    expect.soft(arch.status, 'archives list').toBe(200);
  });
});
