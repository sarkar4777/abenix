/**
 * Monitor, admin and workspace pages, walked from the sidebar as a demanding new admin would use them.
 *
 *   1. Monitor       observability links, executions filters + open + replay with Live Debug watching, analytics, load playground
 *   2. Platform      cluster, scaling, tool scaling, pipeline scaling, archives, dead letters
 *   3. Settings      model selection, tool config key set and cleared, LLM pricing row, connector create/test/delete
 *   4. Events        a webhook subscription, a test send, the delivery in the log
 *   5. Risk          change a tier policy and put it back
 *   6. People        invite, accept, permission set, sign in as them, role change, remove, GDPR erase
 *   7. API keys      create, read with it, revoke, refused after
 *   8. Workspace     cognify, integrations, settings, help, developer docs with link checks
 *   9. Phone width   no sideways scroll on every page at 390px
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   USE_K8S=true BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_nav_monitor_admin_ui.spec.ts --workers=1
 */
import { test, expect, type Page, type Browser } from '@playwright/test';
import * as fs from 'fs';
import { revealSidebarLink, setSidebarMode, sidebarToggle } from './helpers/sidebar';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const DIR = path.join(__dirname, 'uat_nav_monitor_admin_ui');
const SHOTS = path.join(DIR, 'shots');
const LLM_MS = 300_000;
const REPO_BLOB = 'https://github.com/sarkar4777/abenix/blob/main';

const PERSON = { email: `uat-nav-${RUN}@example.com`, name: `Nav Tester ${RUN}`, password: `NavTest-${RUN}-9!` };
const PERMSET = `UAT event managers ${RUN}`;
const HOOK = `UAT hook ${RUN}`;
const CONNECTOR = `UAT connector ${RUN}`;
const PRICE_MODEL = `uat-model-${RUN}`;
const KEY_NAME = `uat-key-${RUN}`;
// read-only tools, safe to run again on a replay or a tiny load
const SAFE_TOOLS = new Set(['current_time', 'knowledge_search', 'text_analyzer', 'calculator', 'date_calculator', 'financial_calculator', 'atlas_search_grounded', 'atlas_describe', 'decision_list', 'decision_explain', 'persona_rag']);

const ids: { asana?: boolean; webhook?: string; connector?: string; price?: string; permset?: string; userId?: string; apiKey?: string; invite?: string } = {};

test.describe.configure({ mode: 'default' });
test.use({ viewport: { width: 1440, height: 900 } });
fs.mkdirSync(SHOTS, { recursive: true });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

// open a page the way a person does, from its sidebar link
async function nav(page: Page, href: string) {
  if (!page.url().startsWith(BASE) || page.url().includes('/auth')) await go(page, '/dashboard');
  // click scrolls the link into view itself and retries if the sidebar re-renders under it
  await (await revealSidebarLink(page, href)).click();
  await page.waitForURL((u) => u.pathname.startsWith(href), { timeout: 20_000 });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

async function signIn(page: Page, who = ADMIN) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(who.email);
  await page.locator('#auth-password').fill(who.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function api(page: Page, method: string, p: string, body?: unknown, headers: Record<string, string> = {}) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const h: Record<string, string> = { Authorization: `Bearer ${tok}`, ...headers };
  if (headers['X-API-Key']) delete h.Authorization;
  if (body !== undefined) h['Content-Type'] = 'application/json';
  const res = await page.request.fetch(`${API}${p}`, { method, headers: h, data: body === undefined ? undefined : JSON.stringify(body) });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

// nothing a person should never see: raw stack traces, JSON dumps, placeholders
async function expectReadable(page: Page) {
  const text = await page.locator('main').first().innerText().catch(() => page.locator('body').innerText());
  expect(text).not.toMatch(/Traceback|File "[^"]+", line \d+|\[object Object\]|undefined undefined|\bNaN\b|lorem ipsum/i);
}

// a run that only used read-only tools, still has its agent and a recorded config
async function safeRun(page: Page) {
  const list = ((await api(page, 'GET', '/api/executions?status=completed&limit=100')).json?.data || []) as any[];
  const seen = new Map<string, any>();
  for (const ex of list) {
    if (!ex.agent_id || !ex.input_message || ex.input_message.length < 8) continue;
    if (!seen.has(ex.agent_id)) seen.set(ex.agent_id, (await api(page, 'GET', `/api/agents/${ex.agent_id}`)).json?.data || null);
    const a = seen.get(ex.agent_id);
    const mc = a?.model_config || {};
    if (!a || mc.mode === 'pipeline') continue;
    if (!(mc.tools || []).every((t: string) => SAFE_TOOLS.has(t))) continue;
    const prov = (await api(page, 'GET', `/api/governance/runs/${ex.id}/provenance`)).json?.data;
    if (!prov?.snapshot || prov.agent_deleted) continue;
    return { ex, agent: a };
  }
  return null;
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test('Sidebar: Show all tools opens the full list and the choice survives a reload', async ({ page }) => {
  await go(page, '/dashboard');
  const toggle = sidebarToggle(page);
  await expect(toggle).toBeVisible({ timeout: 20_000 });
  const startMode = (await toggle.getAttribute('data-mode')) as 'all' | 'essentials';

  // Essentials: the short list, monitor and admin pages are a click away
  await setSidebarMode(page, 'essentials');
  await expect(page.locator('aside a[href="/dashboard"]')).toBeVisible();
  for (const href of ['/observability', '/analytics', '/load-playground']) {
    await expect(page.locator(`aside a[href="${href}"]`), `${href} hidden in Essentials`).toHaveCount(0);
  }
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
  await expect(sidebarToggle(page)).toHaveAttribute('data-mode', 'essentials', { timeout: 20_000 });

  // Show all tools brings every page back
  await setSidebarMode(page, 'all');
  for (const href of ['/observability', '/analytics', '/load-playground', '/admin/cluster']) {
    await expect(page.locator(`aside a[href="${href}"]`), `${href} in all tools`).toBeAttached();
  }
  await shot(page, '00-sidebar-all-tools');

  // and stays that way after a reload
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
  await expect(sidebarToggle(page)).toHaveAttribute('data-mode', 'all', { timeout: 20_000 });
  await expect(page.getByTestId('sidebar-all').first()).toBeVisible();
  await expect(page.locator('aside a[href="/observability"]')).toBeAttached();

  // put the admin's choice back
  await setSidebarMode(page, startMode === 'all' ? 'all' : 'essentials');
});

test('Observability: each layer links somewhere that works', async ({ page }) => {
  await nav(page, '/observability');
  await expect(page.getByRole('heading', { name: 'Observability' })).toBeVisible();
  for (const label of ['Open Executions', 'Open Analytics', 'Live Debug stream', 'Open Alerts']) {
    const link = page.getByRole('link', { name: label }).first();
    await expect(link).toBeVisible();
    const href = await link.getAttribute('href');
    expect(href, label).toBeTruthy();
    if (href!.startsWith('/')) {
      const res = await page.request.get(`${BASE}${href}`);
      expect(res.status(), `${label} -> ${href}`).toBeLessThan(400);
    }
  }
  await shot(page, '01-observability');
  await page.getByRole('link', { name: 'Open Executions' }).first().click();
  await page.waitForURL(/\/executions/);
});

test('Executions: filter, search, open a run, replay it while Live Debug watches', async ({ page, context }) => {
  test.setTimeout(8 * 60_000);
  await nav(page, '/executions');
  await expect(page.getByRole('heading', { name: 'Execution History' })).toBeVisible();

  // KPI cards match the server
  const all = await api(page, 'GET', '/api/executions?limit=1');
  const totalCard = page.locator('p:text-is("Total") + p');
  await expect(totalCard).toHaveText(String(all.json.meta.total), { timeout: 20_000 });

  // status filter shows only failed runs and the count follows
  await page.locator('select').filter({ hasText: 'All Status' }).selectOption({ label: 'Failed' });
  const rows = page.getByTestId('execution-row');
  const list = page.getByTestId('execution-list');
  await expect(list).toHaveAttribute('aria-busy', 'false', { timeout: 20_000 });
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  const statuses = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-status')));
  expect(new Set(statuses)).toEqual(new Set(['failed']));
  const failed = await api(page, 'GET', '/api/executions?status=failed&limit=1');
  await expect(page.getByText(new RegExp(`of ${failed.json.meta.total}$`))).toBeVisible();
  // failure reasons read as words, not codes
  const chips = await page.locator('[data-testid^="execution-failure-code-"]').allInnerTexts();
  for (const c of chips) expect(c, 'failure chip').not.toMatch(/^[A-Z0-9_]+$/);
  await shot(page, '02-executions-failed');

  // pick a run that is safe to replay
  await page.locator('select').filter({ hasText: 'All Status' }).selectOption({ label: 'All Status' });
  const pick = await safeRun(page);
  test.skip(!pick, 'no completed run with read-only tools and a recorded config to replay');
  const { ex, agent } = pick!;

  // searching must not throw the page into a skeleton, the box keeps focus while typing
  const search = page.getByPlaceholder('Search by agent or input...');
  const needle = ex.input_message.slice(0, 24);
  await search.click();
  await search.pressSequentially(needle, { delay: 15 });
  await expect(search).toBeFocused();
  await expect(search).toHaveValue(needle);
  await expect(list).toHaveAttribute('aria-busy', 'false', { timeout: 20_000 });
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });
  // rows summarise the input, so check them against what the server matched rather than the raw text
  const hits = await api(page, 'GET', `/api/executions?search=${encodeURIComponent(needle)}&limit=100`);
  const hitIds = new Set(((hits.json?.data || []) as any[]).map((e) => String(e.id)));
  expect(hitIds.has(String(ex.id)), 'the picked run matches its own input').toBe(true);
  // the agent's name finds its runs too
  const byName = await api(page, 'GET', `/api/executions?search=${encodeURIComponent(agent.name)}&limit=100`);
  expect(((byName.json?.data || []) as any[]).some((e) => String(e.agent_id) === String(agent.id)), 'searching the agent name finds its runs').toBe(true);
  const shown = await list.locator('a[href^="/executions/"]').evaluateAll((els) => els.map((e) => (e.getAttribute('href') || '').split('/')[2]));
  expect(shown.length).toBeGreaterThan(0);
  for (const id of shown) expect(hitIds, `row ${id} is a search hit`).toContain(id);

  // a search with no hits says so and offers a way back
  await search.fill(`zz-no-such-run-${RUN}`);
  await expect(page.getByText('Nothing matches these filters.')).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('exec-clear-filters').click();
  await expect(search).toHaveValue('');
  await expect(rows.first()).toBeVisible({ timeout: 20_000 });

  // newest and oldest really reorder
  const newestFirst = await rows.first().innerText();
  await page.locator('select').filter({ hasText: 'Newest' }).selectOption({ label: 'Oldest' });
  await expect(async () => expect(await rows.first().innerText()).not.toBe(newestFirst)).toPass({ timeout: 20_000 });
  await page.locator('select').filter({ hasText: 'Newest' }).selectOption({ label: 'Newest' });

  // open the run from the list
  await search.fill(needle);
  await page.locator(`a[href="/executions/${ex.id}"]`).first().click();
  await page.waitForURL(new RegExp(`/executions/${ex.id}`));
  await expect(page.getByRole('heading', { name: 'Execution Flight Recorder' })).toBeVisible({ timeout: 20_000 });
  const prov = page.getByTestId('execution-provenance');
  await expect(prov).toBeVisible({ timeout: 20_000 });
  await prov.getByRole('button', { name: /What this run used/ }).click();
  await shot(page, '03-execution-detail');

  // Live Debug in a second tab watches the replay
  const live = await context.newPage();
  await live.goto(`${BASE}/executions/live`, { waitUntil: 'domcontentloaded' });
  await expect(live.getByRole('heading', { name: 'Live Debug' })).toBeVisible();
  await expect(live.getByText('Listening')).toBeVisible({ timeout: 20_000 });
  // a replay can finish inside one poll, so it shows as running or under Just finished
  const runningCard = live.locator(`[data-testid="live-running-run"][data-agent-id="${agent.id}"]`);
  const finishedRows = live.locator(`[data-testid="live-recent-run"][data-agent-id="${agent.id}"][data-kind="replay"] a`);
  const before = new Set(await finishedRows.evaluateAll((els) => els.map((e) => e.getAttribute('href'))));
  // another run of this agent already on screen does not count
  await expect(runningCard).toHaveCount(0, { timeout: 30_000 });
  let seenRunning = false;
  const seenFinished = new Set<string>();
  let stop = false;
  const watcher = (async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < LLM_MS && !stop) {
      if (await runningCard.count()) seenRunning = true;
      for (const h of await finishedRows.evaluateAll((els) => els.map((e) => e.getAttribute('href')))) {
        if (h && !before.has(h)) seenFinished.add(h);
      }
      if (seenFinished.size) break;
      await live.waitForTimeout(500);
    }
  })();

  await page.getByTestId('replay-pinned').click();
  const result = page.getByTestId('replay-result');
  await expect(result).toBeVisible({ timeout: LLM_MS });
  await expect(result).toContainText(/Same answer|Different answer/);
  await Promise.race([watcher, live.waitForTimeout(6_000)]);
  stop = true;
  await live.screenshot({ path: path.join(SHOTS, '04-live-debug.png'), fullPage: true });
  // once done, Live Debug goes back to its empty state or at least drops this run
  await expect(async () => {
    const running = ((await api(live, 'GET', '/api/executions/live')).json?.data || []) as any[];
    expect(running.some((r) => r.agent_id === agent.id)).toBe(false);
  }).toPass({ timeout: 30_000 });
  await live.close();

  // the replay is a real run linked back to the original
  await result.getByRole('link', { name: 'Open the replay' }).click();
  // the page is already on a run, wait for the replay's own
  await page.waitForURL((u) => /\/executions\/[0-9a-f-]{36}/.test(u.pathname) && !u.pathname.includes(ex.id), { timeout: 20_000 });
  const replayId = page.url().split('/executions/')[1].split(/[?#]/)[0];
  expect(replayId).not.toBe(ex.id);
  // Live Debug showed this replay, running or just finished
  expect(seenRunning || seenFinished.has(`/executions/${replayId}`), 'the replay showed on Live Debug').toBe(true);
  const back = await api(page, 'GET', `/api/executions/${replayId}`);
  expect(back.json.data.parent_execution_id).toBe(ex.id);
  expect(['completed', 'failed']).toContain(String(back.json.data.status).toLowerCase());
  await expect(page.getByTestId('execution-parent-link')).toBeVisible({ timeout: 20_000 });
  await shot(page, '05-replay');

  // a run that does not exist is a dead end no more
  await go(page, '/executions/00000000-0000-4000-8000-000000000000');
  await expect(page.getByTestId('execution-not-found')).toBeVisible({ timeout: 20_000 });
  await page.getByRole('link', { name: 'Back to all runs' }).click();
  await page.waitForURL(/\/executions$/);
});

test('Analytics: totals match the server, ranges switch, drift reads as words', async ({ page }) => {
  await nav(page, '/analytics');
  await expect(page.getByRole('heading', { name: 'Analytics' })).toBeVisible();
  for (const period of ['7d', '30d', '90d']) {
    await page.getByRole('button', { name: period, exact: true }).click();
    // other runs land while we look, so read the server and the card together until they agree
    await expect(async () => {
      const ov = (await api(page, 'GET', `/api/analytics/overview?period=${period}`)).json?.data;
      const card = await page.getByText('TOTAL EXECUTIONS', { exact: false }).locator('..').locator('..').innerText();
      const shown = Number((card.match(/[\d,]+/) || ['0'])[0].replace(/,/g, ''));
      expect(Math.abs(shown - ov.total_executions)).toBeLessThanOrEqual(5);
    }).toPass({ timeout: 30_000 });
  }
  await page.getByRole('button', { name: '30d', exact: true }).click();

  // the leaderboard ranks by real use, a row with tokens comes before idle ones
  const costs = (await api(page, 'GET', '/api/analytics/costs?period=30d')).json?.data?.by_agent || [];
  if (costs.some((a: any) => a.total_tokens > 0 || a.cost > 0)) {
    expect(costs[0].total_tokens > 0 || costs[0].cost > 0, 'top agent has usage').toBe(true);
  }

  // drift lines never show a percent off a zero baseline
  const drift = page.locator('#drift-alerts');
  await drift.scrollIntoViewIfNeeded();
  await expect(drift.getByText(/No drift alerts|Acknowledge/).first()).toBeVisible({ timeout: 20_000 });
  for (const line of await drift.getByTestId('drift-change').allInnerTexts()) {
    expect(line).not.toMatch(/\d{4,}(\.\d+)?%/);
    expect(line).not.toMatch(/_/);
  }
  await drift.getByLabel('Severity').selectOption('critical');
  await expect(drift.getByRole('listitem').or(drift.getByText(/No drift alerts/)).first()).toBeVisible({ timeout: 20_000 });
  await expect(async () => {
    for (const item of await drift.getByRole('listitem').allInnerTexts()) expect(item.toLowerCase()).toContain('critical');
  }).toPass({ timeout: 20_000 });
  await expectReadable(page);
  await shot(page, '06-analytics');
});

test('Load Playground: a tiny load against a read-only agent reports latency', async ({ page }) => {
  test.setTimeout(10 * 60_000);
  await nav(page, '/load-playground');
  await expect(page.getByRole('heading', { name: /Load Test Playground/ })).toBeVisible();
  const target = page.getByLabel('Agent / Pipeline');
  await expect(target).toBeEnabled({ timeout: 30_000 });
  const options = await target.locator('option').evaluateAll((els) => els.map((e) => ({ v: (e as HTMLOptionElement).value, t: e.textContent || '' })));
  // every agent is offered, not just the newest hundred
  const listed = await api(page, 'GET', '/api/agents?limit=1');
  expect(options.length).toBe(listed.json.meta.total);
  let chosen: string | null = null;
  for (const o of options) {
    const a = (await api(page, 'GET', `/api/agents/${o.v}`)).json?.data;
    const mc = a?.model_config || {};
    if (a && mc.mode !== 'pipeline' && a.status === 'active' && (mc.tools || []).every((t: string) => SAFE_TOOLS.has(t))) { chosen = o.v; break; }
  }
  test.skip(!chosen, 'no active agent with read-only tools to load');
  await target.selectOption(chosen!);
  await page.getByLabel('Message sample (what every request sends)').fill('Reply with the word ok.');
  await page.getByLabel('Total requests').fill('3');
  await page.getByLabel('Concurrency').fill('1');
  await page.getByRole('button', { name: 'Generate script' }).click();
  await expect(page.getByRole('heading', { name: 'Generated load test' })).toBeVisible({ timeout: LLM_MS });
  await page.getByRole('button', { name: 'Run', exact: true }).click();
  const out = page.getByTestId('lp-output');
  await expect(out).toContainText(/done \(exit \d+\)/, { timeout: LLM_MS });
  const text = await out.innerText();
  console.log(`\n--- load output ---\n${text.slice(-1500)}\n---`);
  expect(text).toContain('done (exit 0)');
  expect(text.toLowerCase()).toMatch(/p50|p95|latency/);
  await shot(page, '07-load-playground');
});

test('Cluster, scaling, tool and pipeline scaling: real numbers, edits that stick and are put back', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await nav(page, '/admin/cluster');
  await expect(page.getByRole('heading', { name: 'Cluster Health' })).toBeVisible();
  const sum = (await api(page, 'GET', '/api/admin/cluster/summary')).json.data;
  const pods = Object.values(sum.pods as Record<string, number>).reduce((a, b) => a + b, 0);
  await expect(page.getByText('Pods', { exact: true }).locator('..')).toContainText(String(pods), { timeout: 20_000 });
  const realNodes = (sum.nodes as any[]).filter((n) => n.name).length;
  await expect(page.getByTestId('cluster-node-count')).toHaveText(realNodes ? String(realNodes) : '—');
  if (!realNodes) await expect(page.getByTestId('cluster-nodes-empty')).not.toContainText(/HTTPHeaderDict|Reason:/);
  await page.getByTestId('cluster-refresh').click();
  // the database card names itself and finishes loading, its size sits next to the heading
  const dbCard = page.getByTestId('cluster-database');
  await expect(dbCard.getByRole('heading', { name: /^Database/ })).toBeVisible({ timeout: 20_000 });
  await expect(dbCard.locator('.animate-pulse')).toHaveCount(0, { timeout: 20_000 });
  await expectReadable(page);
  await shot(page, '08-cluster');

  // scaling: the counts cover every agent, search reaches past the first 500
  await nav(page, '/admin/scaling');
  await expect(page.getByRole('heading', { name: 'Scaling Console' })).toBeVisible();
  const fleet = (await api(page, 'GET', '/api/admin/scaling/agents?limit=1')).json.data;
  await expect(page.getByTestId('scaling-kpis')).toContainText(Number(fleet.total).toLocaleString());
  const last = (await api(page, 'GET', `/api/admin/scaling/agents?limit=500`)).json.data.agents as any[];
  // an agent past the first 500 by name is still found by search
  if (fleet.total > 500) {
    const tail = (await api(page, 'GET', '/api/admin/scaling/agents?limit=500&q=wingman')).json.data.agents as any[];
    if (tail.length) {
      await page.getByTestId('agent-search').fill(tail[0].name);
      await expect(page.getByTestId(`agent-row-${tail[0].slug}`)).toBeVisible({ timeout: 20_000 });
      await page.getByTestId('agent-search').fill('');
    }
  }
  // an archived probe nobody runs, so changing it cannot disturb other work
  const probe = last.find((a) => a.status === 'archived' && /probe/i.test(a.name)) || last.find((a) => a.status === 'archived');
  test.skip(!probe, 'no archived agent to edit safely');
  await page.getByTestId('agent-search').fill(probe.name);
  await expect(page.getByTestId(`agent-row-${probe.slug}`)).toBeVisible({ timeout: 20_000 });
  await page.getByTestId(`edit-${probe.slug}`).click();
  const modal = page.getByTestId('scale-modal');
  await expect(modal).toBeVisible();
  const before = probe.concurrency_per_replica;
  const next = before === 4 ? 5 : 4;
  await modal.getByTestId('edit-conc').locator('input').first().fill(String(next)).catch(async () => {
    await modal.getByTestId('edit-conc').fill(String(next));
  });
  await page.getByTestId('scale-save').click();
  await expect(modal).toHaveCount(0, { timeout: 20_000 });
  const after = ((await api(page, 'GET', `/api/admin/scaling/agents?limit=5&q=${encodeURIComponent(probe.slug)}`)).json.data.agents as any[]).find((a) => a.id === probe.id);
  expect(after.concurrency_per_replica).toBe(next);
  // put it back the same way
  await page.getByTestId(`edit-${probe.slug}`).click();
  await modal.getByTestId('edit-conc').locator('input').first().fill(String(before)).catch(async () => {
    await modal.getByTestId('edit-conc').fill(String(before));
  });
  await page.getByTestId('scale-save').click();
  await expect(modal).toHaveCount(0, { timeout: 20_000 });
  const restored = ((await api(page, 'GET', `/api/admin/scaling/agents?limit=5&q=${encodeURIComponent(probe.slug)}`)).json.data.agents as any[]).find((a) => a.id === probe.id);
  expect(restored.concurrency_per_replica).toBe(before);
  await shot(page, '09-scaling');

  // tool scaling: change one cap on a rarely used tool, then restore it
  await nav(page, '/admin/tool-scaling');
  await expect(page.getByRole('heading', { name: /Tool runtime scaling/i })).toBeVisible();
  const tools = (await api(page, 'GET', '/api/admin/tool-runtime')).json.data;
  const rows: any[] = Array.isArray(tools) ? tools : tools.rows || tools.tools || [];
  const tool = rows.find((r) => r.slug === 'academic_search') || rows[rows.length - 1];
  await page.getByRole('button', { name: `Edit ${tool.slug}` }).first().click();
  const capField = page.getByLabel('Inflight cap (per tenant)');
  const capBefore = Number(await capField.inputValue());
  await capField.fill(String(capBefore + 1));
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByLabel('Inflight cap (per tenant)')).toHaveCount(0, { timeout: 20_000 });
  const toolsAfter = (await api(page, 'GET', '/api/admin/tool-runtime')).json.data;
  const t2 = (Array.isArray(toolsAfter) ? toolsAfter : toolsAfter.rows || toolsAfter.tools).find((r: any) => r.slug === tool.slug);
  expect(t2.max_inflight_per_tenant).toBe(capBefore + 1);
  await page.getByRole('button', { name: `Edit ${tool.slug}` }).first().click();
  await page.getByLabel('Inflight cap (per tenant)').fill(String(capBefore));
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByLabel('Inflight cap (per tenant)')).toHaveCount(0, { timeout: 20_000 });
  await shot(page, '10-tool-scaling');

  await nav(page, '/admin/pipeline-scaling');
  await expect(page.getByRole('heading', { name: /Pipeline scaling/i })).toBeVisible();
  await expect(page.getByText(/pipeline pool:/).first()).toBeVisible({ timeout: 20_000 });
  await expectReadable(page);
  await shot(page, '11-pipeline-scaling');
});

test('Archives and dead letters: retention edit with feedback, put back, manual run asks first', async ({ page }) => {
  await nav(page, '/admin/archives');
  await expect(page.getByRole('heading', { name: 'Archives' })).toBeVisible();
  const pols = (await api(page, 'GET', '/api/admin/archives/retention-policies')).json.data.items as any[];
  const pol = pols.find((p) => p.source_table === 'kb_query_invocations') || pols[0];
  const days = page.getByTestId(`retention-days-${pol.source_table}`);
  await days.fill(String(pol.retention_days + 1));
  await page.getByTestId(`retention-save-${pol.source_table}`).click();
  await expect(page.getByTestId('archives-notice')).toContainText(`keeps ${pol.retention_days + 1} days`, { timeout: 20_000 });
  const mid = ((await api(page, 'GET', '/api/admin/archives/retention-policies')).json.data.items as any[]).find((p) => p.source_table === pol.source_table);
  expect(mid.retention_days).toBe(pol.retention_days + 1);
  await page.getByTestId(`retention-days-${pol.source_table}`).fill(String(pol.retention_days));
  await page.getByTestId(`retention-save-${pol.source_table}`).click();
  await expect(page.getByTestId('archives-notice')).toContainText(`keeps ${pol.retention_days} days`, { timeout: 20_000 });

  // a manual archive deletes rows, so it must ask, and cancel must do nothing
  const runsBefore = ((await api(page, 'GET', '/api/admin/archives')).json.data.items as any[]).length;
  await page.getByTestId(`archive-trigger-${pol.source_table}`).click();
  await expect(page.getByRole('dialog')).toContainText(`Archive ${pol.source_table} now?`);
  await shot(page, '12-archives-confirm');
  await page.getByRole('button', { name: 'Cancel' }).click();
  const runsAfter = ((await api(page, 'GET', '/api/admin/archives')).json.data.items as any[]).length;
  expect(runsAfter).toBe(runsBefore);

  await nav(page, '/admin/dlq');
  await expect(page.getByRole('heading', { name: 'Dead Letter Queue' })).toBeVisible();
  await expect(page.getByText(/DLQ is empty|Replay/).first()).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: 'Refresh' }).click();
  await expectReadable(page);
  await shot(page, '13-dlq');
});

test('Model selection, tool config key, LLM pricing row, connector', async ({ page }) => {
  await nav(page, '/admin/llm-settings');
  await expect(page.getByRole('heading', { name: 'Model Selection' })).toBeVisible();
  // settings are named, not shown as dotted keys
  await expect(page.locator('main').getByText('ai_builder.critic.model', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Builder critic model')).toBeVisible({ timeout: 20_000 });
  // no two choices in a picker read the same
  const pickers = page.getByTestId('model-picker-select');
  await expect(pickers.first()).toBeEnabled({ timeout: 20_000 });
  const labels = await pickers.first().locator('option').allInnerTexts();
  const dupes = labels.filter((l, i) => labels.indexOf(l) !== i);
  expect(dupes, dupes.join(', ')).toEqual([]);
  const verify = page.getByTestId('subscription-verify');
  if (await verify.isEnabled()) {
    await verify.click();
    await expect(page.getByTestId('subscription-verify-result')).toBeVisible({ timeout: 60_000 });
  }
  await shot(page, '14-llm-settings');

  // a harmless optional key on this tenant, set then cleared
  await nav(page, '/admin/tool-config');
  await page.getByTestId('tool-config-scope-tenant').click();
  await page.getByTestId('tool-config-search').fill('ASANA_TOKEN');
  const row = page.getByTestId('tool-config-row-ASANA_TOKEN');
  await expect(row).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('tool-config-source-ASANA_TOKEN')).toContainText(/not set/i);
  await page.getByTestId('tool-config-input-ASANA_TOKEN').fill(`uat-dummy-${RUN}`);
  await page.getByTestId('tool-config-save-ASANA_TOKEN').click();
  ids.asana = true;
  await expect(page.getByTestId('tool-config-msg-ASANA_TOKEN')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('tool-config-source-ASANA_TOKEN')).not.toContainText(/not set/i);
  const tc = (await api(page, 'GET', '/api/admin/tool-config?scope=tenant')).json.data;
  expect(JSON.stringify(tc)).not.toContain(`uat-dummy-${RUN}`);
  await shot(page, '15-tool-config-set');
  await page.getByTestId('tool-config-clear-ASANA_TOKEN').click();
  await expect(page.getByTestId('tool-config-msg-ASANA_TOKEN')).toContainText('Cleared', { timeout: 20_000 });
  await expect(page.getByTestId('tool-config-source-ASANA_TOKEN')).toContainText(/not set/i);
  ids.asana = false;

  // a pricing row for a made-up model, added and deleted
  await nav(page, '/admin/llm-pricing');
  await expect(page.getByRole('heading', { name: 'LLM Pricing' })).toBeVisible();
  await page.getByTestId('add-pricing-submit').click();
  await expect(page.getByText('Enter a model id, an input price and an output price.')).toBeVisible();
  await page.getByLabel('Model id').fill(PRICE_MODEL);
  await page.getByLabel('Provider').selectOption('other');
  await page.getByLabel('Price per million input tokens ($)', { exact: true }).fill('1.5');
  await page.getByLabel('Price per million output tokens ($)', { exact: true }).fill('6');
  await page.getByTestId('add-pricing-submit').click();
  await expect(page.getByText(`Added pricing for ${PRICE_MODEL}.`)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId(`row-${PRICE_MODEL}`)).toBeVisible();
  const prow = ((await api(page, 'GET', '/api/admin/llm-pricing')).json.data.rows as any[]).find((r) => r.model === PRICE_MODEL);
  ids.price = prow.id;
  expect(Number(prow.input_per_m)).toBe(1.5);
  await expect(page.getByText(/_calc_cost|llm_router\.py/)).toHaveCount(0);
  await page.getByRole('button', { name: `Delete pricing for ${PRICE_MODEL}` }).click();
  await expect(page.getByTestId(`row-${PRICE_MODEL}`)).toHaveCount(0, { timeout: 20_000 });
  ids.price = undefined;
  await shot(page, '16-llm-pricing');

  // a connector to a public echo service with a write-only secret, tested, deleted
  await nav(page, '/admin/connectors');
  await expect(page.getByRole('heading', { name: 'Connectors' })).toBeVisible();
  await page.getByRole('button', { name: 'New connector' }).click();
  await page.getByLabel('Name').fill(CONNECTOR);
  await page.getByLabel('Kind').selectOption('custom');
  await page.getByLabel('Auth type').selectOption('bearer');
  await page.getByLabel('Base URL').fill('https://httpbin.org/get');
  const secretBox = page.getByLabel('Secret', { exact: true });
  await expect(secretBox).toHaveAttribute('type', 'password');
  const SECRET = `uat-secret-${RUN}`;
  await secretBox.fill(SECRET);
  await expect(page.getByText('Write-only, it is never shown again.', { exact: false })).toBeVisible();
  await page.getByLabel('Config JSON').fill('{ not json');
  await page.getByRole('button', { name: 'Create connector' }).click();
  await expect(page.getByTestId('connector-form-error')).toContainText('valid JSON');
  await page.getByLabel('Config JSON').fill('{}');
  await page.getByRole('button', { name: 'Create connector' }).click();
  const crow = page.getByTestId(`connector-row-${CONNECTOR}`);
  await expect(crow).toBeVisible({ timeout: 20_000 });
  const listed = await api(page, 'GET', '/api/connectors');
  expect(JSON.stringify(listed.json)).not.toContain(SECRET);
  const made = (listed.json.data as any[]).find((c) => c.name === CONNECTOR);
  ids.connector = made?.id;
  expect(made.has_secret).toBe(true);
  expect(made.needs_secret).toBe(false);
  // editing shows the secret is saved, never the value
  await page.getByRole('button', { name: `Edit ${CONNECTOR}` }).click();
  await expect(page.getByTestId('connector-secret-saved')).toContainText('Saved, hidden');
  await expect(page.locator(`input[value="${SECRET}"]`)).toHaveCount(0);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: `Test ${CONNECTOR}` }).click();
  const result = page.getByTestId(`connector-test-result-${CONNECTOR}`);
  await expect(result).toContainText(/Reached it, HTTP 200|Could not reach it/, { timeout: 30_000 });
  const said = await result.innerText();
  expect(said).not.toMatch(/Traceback|httpx|Errno|\[object Object\]|\bundefined\b/);
  expect(said).not.toContain(SECRET);
  const after = ((await api(page, 'GET', '/api/connectors')).json.data as any[]).find((c) => c.id === ids.connector);
  expect(after.last_test_at).toBeTruthy();
  expect(after.last_test_ok).toBe(/Reached it/.test(said));
  await shot(page, '17-connector-tested');
  await page.getByRole('button', { name: `Delete ${CONNECTOR}` }).click();
  await expect(crow).toHaveCount(0, { timeout: 20_000 });
  ids.connector = undefined;
});

test('Events: subscribe a webhook, send a test, see it delivered', async ({ page }) => {
  test.setTimeout(4 * 60_000);
  await nav(page, '/settings/webhooks');
  await expect(page.getByRole('heading', { name: 'Events', exact: true })).toBeVisible();
  await page.getByTestId('sub-new').click();
  await page.getByTestId('sub-name').fill(HOOK);
  await page.getByTestId('sub-event-execution.completed').check();
  await page.getByTestId('sub-url').fill('not a url');
  await expect(page.getByText('Enter a full http or https URL.')).toBeVisible();
  await expect(page.getByTestId('sub-create')).toBeDisabled();
  await page.getByTestId('sub-url').fill('https://httpbin.org/post');
  await page.getByTestId('sub-create').click();
  await expect(page.getByTestId('sub-secret')).toBeVisible({ timeout: 20_000 });
  const sub = ((await api(page, 'GET', '/api/webhooks')).json.data as any[]).find((s) => s.name === HOOK);
  expect(sub).toBeTruthy();
  ids.webhook = sub.id;
  expect(sub.events).toEqual(['execution.completed']);

  await page.getByTestId(`sub-test-${HOOK}`).click();
  const card = page.getByTestId(`sub-${HOOK}`);
  await expect(card.getByRole('status')).toContainText('is on its way');
  const log = page.getByTestId(`deliveries-${sub.id}`);
  await expect(log).toContainText('delivered', { timeout: 90_000 });
  await expect(log).toContainText('HTTP 200');
  const dl = ((await api(page, 'GET', `/api/webhooks/${sub.id}/deliveries`)).json.data as any[]);
  expect(dl[0].status).toBe('delivered');
  await shot(page, '18-webhook-delivered');

  await card.getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('dialog').getByRole('button', { name: /Delete|Confirm/ }).last().click();
  await expect(card).toHaveCount(0, { timeout: 20_000 });
  ids.webhook = undefined;
});

test('Risk: change a tier policy, see it saved, put it back', async ({ page }) => {
  await nav(page, '/admin/risk');
  await expect(page.getByRole('heading', { name: 'Risk and Controls' })).toBeVisible();
  const before = ((await api(page, 'GET', '/api/governance/risk')).json.data.tiers as any[]).find((t) => t.tier === 'low');
  const wasDefault = !Object.keys(before.overrides || {}).length;
  const hours = before.effective.publish_approvals.escalate_after_hours ?? 0;
  const card = page.getByTestId('tier-card-low');
  await card.getByTestId('tier-escalate-low').fill(String(hours + 3));
  await card.getByTestId('tier-save-low').click();
  await expect(card.getByTestId('tier-msg-low')).toContainText('Saved', { timeout: 20_000 });
  const mid = ((await api(page, 'GET', '/api/governance/risk')).json.data.tiers as any[]).find((t) => t.tier === 'low');
  expect(mid.effective.publish_approvals.escalate_after_hours).toBe(hours + 3);
  await expect(card.getByText('customised')).toBeVisible();
  await shot(page, '19-risk-changed');

  if (wasDefault) {
    await card.getByTestId('tier-reset-low').click();
    await page.getByRole('dialog').getByRole('button').last().click();
    await expect(card.getByTestId('tier-msg-low')).toContainText('Back to the platform defaults', { timeout: 20_000 });
  } else {
    await card.getByTestId('tier-escalate-low').fill(String(hours));
    await card.getByTestId('tier-save-low').click();
    await expect(card.getByTestId('tier-msg-low')).toContainText('Saved', { timeout: 20_000 });
  }
  const end = ((await api(page, 'GET', '/api/governance/risk')).json.data.tiers as any[]).find((t) => t.tier === 'low');
  expect(end.effective).toEqual(before.effective);
});

async function personContext(browser: Browser) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  return { ctx, p };
}

test('People: invite, accept, permission set, sidebar as them, role change, remove, GDPR erase', async ({ page, browser }) => {
  test.setTimeout(8 * 60_000);
  await nav(page, '/settings/team');
  await expect(page.getByRole('heading', { name: 'Team', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Invite Member' }).click();
  await page.getByPlaceholder('email@example.com').fill(PERSON.email);
  await page.locator('select').filter({ hasText: 'Creator' }).first().selectOption({ label: 'Member' });
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  const link = await page.getByTestId('invite-link').innerText({ timeout: 20_000 });
  expect(link).toContain(`${BASE}/auth/accept-invite?token=`);
  // other runs may have invites pending too, so read this person's row
  const inviteRow = page.getByTestId(`invite-${PERSON.email}`);
  await expect(inviteRow).toContainText(PERSON.email);
  await expect(inviteRow).toContainText('Pending');
  await expect(inviteRow.getByText('Invited as Member', { exact: true })).toBeVisible();
  await shot(page, '20-team-invited');

  // they accept in their own browser
  const { ctx, p } = await personContext(browser);
  await p.goto(link, { waitUntil: 'domcontentloaded' });
  await expect(p.getByTestId('accept-title')).toBeVisible({ timeout: 20_000 });
  await p.locator('#accept-full-name').fill(PERSON.name);
  await p.locator('#accept-password').fill(PERSON.password);
  await p.getByTestId('accept-submit').click();
  await p.waitForURL(/\/dashboard/, { timeout: 30_000 });
  const me = (await api(p, 'GET', '/api/auth/me')).json.data.user;
  ids.userId = me.id;
  expect(me.role).toBe('user');
  // a member does not get the Events page yet, not even in the full list
  await expect(p.locator('aside a[href="/dashboard"]')).toBeVisible({ timeout: 20_000 });
  await setSidebarMode(p, 'all');
  await expect(p.locator('aside a[href="/settings/webhooks"]')).toHaveCount(0);
  await expect(p.locator('aside a[href="/admin/cluster"]')).toHaveCount(0);

  // a permission set that adds event management, given to them
  await nav(page, '/admin/permissions');
  await expect(page.getByRole('heading', { name: 'Permissions' })).toBeVisible();
  await page.getByTestId('permset-new').click();
  await page.getByTestId('permset-name').fill(PERMSET);
  await page.getByPlaceholder('People who approve rule changes before they go live').fill('Can wire platform events to their systems.');
  await page.getByLabel('Filter capabilities').fill('event');
  await page.getByTestId('permset-cap-events.manage').check();
  await page.getByTestId('permset-save').click();
  const setCard = page.getByTestId(`permset-${PERMSET}`);
  await expect(setCard).toBeVisible({ timeout: 20_000 });
  await page.getByTestId(`permset-add-${PERMSET}`).fill(PERSON.email);
  await setCard.getByRole('option', { name: new RegExp(PERSON.email) }).click();
  await expect(setCard).toContainText(PERSON.name, { timeout: 20_000 });
  const sets = (await api(page, 'GET', '/api/governance/permission-sets')).json.data as any[];
  const mine = sets.find((s) => s.name === PERMSET);
  ids.permset = mine.id;
  expect(mine.capabilities).toContain('events.manage');
  await shot(page, '21-permset');

  // they now see Events and can use it, and still no admin pages
  await expect(async () => {
    await p.reload({ waitUntil: 'domcontentloaded' });
    // the full list they chose is remembered
    await expect(sidebarToggle(p)).toHaveAttribute('data-mode', 'all', { timeout: 5_000 });
    await expect(p.locator('aside a[href="/settings/webhooks"]')).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 60_000 });
  await expect(p.locator('aside a[href="/admin/cluster"]')).toHaveCount(0);
  await nav(p, '/settings/webhooks');
  await expect(p.getByTestId('sub-new')).toBeVisible({ timeout: 20_000 });
  await expect(p.getByTestId('events-no-access')).toHaveCount(0);
  await p.screenshot({ path: path.join(SHOTS, '22-person-sees-events.png'), fullPage: true });

  // role change shows the same names the menu uses
  await nav(page, '/settings/team');
  const row = page.getByTestId(`member-${PERSON.email}`);
  await expect(row.getByTestId('member-role')).toHaveText('Member', { timeout: 20_000 });
  await row.getByRole('button', { name: `Actions for ${PERSON.email}` }).click();
  await row.getByRole('button', { name: 'Set as Creator' }).click();
  await expect(row.getByTestId('member-role')).toHaveText('Creator', { timeout: 20_000 });
  const m1 = ((await api(page, 'GET', '/api/team/members')).json.data.members as any[]).find((m) => m.email === PERSON.email);
  expect(m1.role).toBe('creator');

  // changing your own role is refused with a reason, not a vague failure
  const meRow = page.getByTestId(`member-${ADMIN.email}`);
  await meRow.getByRole('button', { name: `Actions for ${ADMIN.email}` }).click();
  await meRow.getByRole('button', { name: 'Set as Creator' }).click();
  await expect(page.getByText('Cannot change your own role')).toBeVisible({ timeout: 10_000 });
  const self = ((await api(page, 'GET', '/api/team/members')).json.data.members as any[]).find((m) => m.email === ADMIN.email);
  expect(self.role).toBe('admin');

  // remove them
  await row.getByRole('button', { name: `Actions for ${PERSON.email}` }).click();
  await row.getByRole('button', { name: 'Remove member' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Remove' }).click();
  await expect(row).toHaveCount(0, { timeout: 20_000 });
  const m2 = ((await api(page, 'GET', '/api/team/members')).json.data.members as any[]).find((m) => m.email === PERSON.email);
  expect(m2.is_active).toBe(false);
  await shot(page, '23-team-removed');
  // once removed they are signed out of everything
  await p.reload({ waitUntil: 'domcontentloaded' });
  const res = await api(p, 'GET', '/api/auth/me');
  expect(res.status).toBe(401);
  await ctx.close();

  // erase them, picked by name, no IDs to copy
  await nav(page, '/settings/gdpr');
  await expect(page.getByRole('heading', { name: 'GDPR erasure' })).toBeVisible();
  await expect(page.getByText('Subject user ID (UUID)')).toHaveCount(0);
  await page.getByTestId('gdpr-person-search').fill(PERSON.name);
  await page.getByTestId(`gdpr-pick-${PERSON.email}`).click();
  await expect(page.getByTestId('gdpr-subject')).toContainText('removed from the team');
  await page.getByTestId('gdpr-erase').click();
  await page.getByTestId('gdpr-confirm').click();
  const receipt = page.getByTestId('gdpr-receipt');
  await expect(receipt).toBeVisible({ timeout: 120_000 });
  await expect(receipt).toContainText('Database');
  await expect(receipt).not.toContainText(/postgres|pinecone|neo4j/);
  await expect(page.getByTestId('gdpr-receipts')).toBeVisible({ timeout: 20_000 });
  const rec = (await api(page, 'GET', `/api/gdpr/users/${ids.userId}/receipts`)).json.data as any[];
  expect(rec.some((r) => r.store === 'postgres' && r.status === 'completed')).toBe(true);
  // the admin cannot pick themselves
  await page.getByRole('button', { name: 'Pick someone else' }).click();
  await page.getByTestId('gdpr-person-search').fill(ADMIN.email);
  await expect(page.getByTestId(`gdpr-pick-${ADMIN.email}`)).toHaveCount(0);
  await shot(page, '24-gdpr-erased');

  // clean the set up through its own page
  await nav(page, '/admin/permissions');
  await page.getByRole('button', { name: `Delete ${PERMSET}` }).click();
  await page.getByRole('dialog').getByRole('button').last().click();
  await expect(page.getByTestId(`permset-${PERMSET}`)).toHaveCount(0, { timeout: 20_000 });
  ids.permset = undefined;
});

test('API keys: create one, read with it, revoke it, refused after', async ({ page }) => {
  await nav(page, '/settings/api-keys');
  await expect(page.getByRole('heading', { name: 'API Keys' })).toBeVisible();
  await page.getByTestId('apikey-generate').click();
  await page.getByTestId('apikey-name').fill(KEY_NAME);
  await page.getByTestId('apikey-create').click();
  const raw = (await page.getByTestId('apikey-created-value').innerText({ timeout: 20_000 })).trim();
  expect(raw).toMatch(/^af_/);
  const keys = (await api(page, 'GET', '/api/api-keys')).json.data as any[];
  const k = keys.find((x) => x.name === KEY_NAME);
  ids.apiKey = k.id;
  const ok = await api(page, 'GET', '/api/agents?limit=1', undefined, { 'X-API-Key': raw });
  expect(ok.status).toBe(200);
  expect(ok.json.data.length).toBeGreaterThan(0);
  await shot(page, '25-apikey-created');
  await page.getByTestId(`apikey-revoke-${k.id}`).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke key' }).click();
  await expect(page.getByTestId(`apikey-revoke-${k.id}`)).toHaveCount(0, { timeout: 20_000 });
  ids.apiKey = undefined;
  const refused = await api(page, 'GET', '/api/agents?limit=1', undefined, { 'X-API-Key': raw });
  expect(refused.status).toBe(401);
});

test('Cognify, integrations, settings and help', async ({ page }) => {
  await nav(page, '/settings/cognify');
  await expect(page.getByRole('heading', { name: /Cognify/ })).toBeVisible();
  const cfg = (await api(page, 'GET', '/api/knowledge/cognify-config')).json.data;
  await page.getByRole('button', { name: 'Save config' }).click();
  await expect(page.getByTestId('cognify-saved')).toBeVisible({ timeout: 20_000 });
  const cfg2 = (await api(page, 'GET', '/api/knowledge/cognify-config')).json.data;
  expect(cfg2.auto_accept_threshold).toBe(cfg.auto_accept_threshold);
  await shot(page, '26-cognify');

  await nav(page, '/settings/integrations');
  await expect(page.getByRole('heading', { name: 'Integrations' })).toBeVisible();
  await expect(page.getByText('->')).toHaveCount(0);
  await page.getByTestId('integrations-admin-link').click();
  await page.waitForURL(/\/admin\/tool-config/);
  await expect(page.getByTestId('tool-config-search')).toBeVisible({ timeout: 20_000 });

  await nav(page, '/settings');
  await page.waitForURL(/\/settings\/profile/);
  await expect(page.getByText('Change password')).toBeVisible();

  await nav(page, '/help');
  await expect(page.getByText('User guide').first()).toBeVisible();
  // the topic list entry, the phone topic picker holds a hidden option with the same name
  await page.getByText('Earned Autonomy', { exact: true }).locator('visible=true').first().click();
  await expect(page.getByTestId('help-earned-autonomy')).toBeVisible({ timeout: 20_000 });
  await expectReadable(page);
  await shot(page, '27-help');
});

test('Developer docs: pages open, earned autonomy docs included, every link resolves', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  const manifest = await (await page.request.get(`${BASE}/dev-docs/manifest.json`)).json();
  const slugs = new Set<string>(manifest.sections.flatMap((s: any) => s.docs.map((d: any) => d.slug)));
  for (const s of ['02-runtime/21-earned-autonomy', '04-data-model/08-autonomy', '08-howto/13-earned-autonomy']) expect(slugs.has(s), s).toBe(true);

  // the sidebar link opens docs in a new tab, it sits in the full list
  await go(page, '/dashboard');
  const link = await revealSidebarLink(page, '/docs');
  await expect(link).toBeVisible();
  await go(page, '/docs');
  await expect(page.getByRole('heading', { name: 'Abenix Developer Documentation' })).toBeVisible({ timeout: 20_000 });

  const broken: string[] = [];
  const pagesToOpen = ['README', '08-howto/13-earned-autonomy', '02-runtime/21-earned-autonomy', '04-data-model/08-autonomy', '01-architecture/07-governance', '08-howto/04-debugging'];
  for (const slug of pagesToOpen) {
    if (slug !== 'README') {
      const title = manifest.sections.flatMap((s: any) => s.docs).find((d: any) => d.slug === slug)?.title;
      await page.locator('aside').getByRole('button', { name: title, exact: true }).click();
      await page.waitForURL(new RegExp(`slug=${encodeURIComponent(slug)}`));
    }
    const article = page.locator('article');
    await expect(article.locator('h1').first()).toBeVisible({ timeout: 20_000 });
    await expect(article).not.toContainText('# Not found');
    const hrefs = await article.locator('a[href]').evaluateAll((els) => els.map((e) => e.getAttribute('href') || ''));
    for (const h of hrefs) {
      if (h.startsWith('#') || h.startsWith('mailto:')) continue;
      if (h.startsWith('?slug=')) {
        const target = decodeURIComponent(h.slice(6).split('#')[0]);
        const r = await page.request.get(`${BASE}/dev-docs/${target}.md`);
        if (r.status() >= 400) broken.push(`${slug} -> ${target}`);
      } else if (h.startsWith(REPO_BLOB)) {
        // source links open on GitHub, the file must exist in this checkout
        const rel = h.slice(REPO_BLOB.length + 1).split('#')[0];
        if (!fs.existsSync(path.join(__dirname, '..', rel))) broken.push(`${slug} -> ${rel} (no such file)`);
      } else if (/^https?:/.test(h)) {
        continue;
      } else {
        broken.push(`${slug} -> ${h} (not a doc page)`);
      }
    }
    const imgs = await article.locator('img').evaluateAll((els) => els.map((e) => (e as HTMLImageElement).naturalWidth));
    if (imgs.some((w) => w === 0)) broken.push(`${slug} has a broken image`);
  }
  await shot(page, '28-docs-earned-autonomy');
  expect(broken, broken.join('\n')).toEqual([]);

  // search finds the new docs
  await page.getByTestId('devdocs-search').fill('earned autonomy');
  await expect(page.locator('aside').getByText(/\d+ results?/)).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('aside').getByRole('button', { name: /autonomy/i }).first()).toBeVisible();
});

test('Phone width: no sideways scroll on any of these pages', async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  const routes = ['/observability', '/executions', '/executions/live', '/analytics', '/load-playground', '/admin/cluster', '/admin/scaling', '/admin/tool-scaling', '/admin/pipeline-scaling', '/admin/archives', '/admin/dlq', '/admin/llm-settings', '/admin/tool-config', '/admin/llm-pricing', '/admin/connectors', '/settings/webhooks', '/admin/risk', '/settings/team', '/admin/permissions', '/settings/api-keys', '/settings/cognify', '/settings/gdpr', '/settings/integrations', '/settings/profile', '/help', '/docs'];
  const wide: string[] = [];
  for (const [i, route] of routes.entries()) {
    await go(page, route);
    await page.waitForTimeout(1_500);
    const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
    await shot(page, `${30 + i}-phone${route.replace(/\//g, '-')}`);
    if (m.sw > m.iw + 1) wide.push(`${route} scrollWidth=${m.sw} innerWidth=${m.iw}`);
  }
  // the invite form and connector form open wide, check them too
  await go(page, '/settings/team');
  await page.getByRole('button', { name: 'Invite Member' }).click();
  let m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  if (m.sw > m.iw + 1) wide.push(`/settings/team invite form scrollWidth=${m.sw}`);
  await go(page, '/admin/connectors');
  await page.getByRole('button', { name: 'New connector' }).click();
  m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  if (m.sw > m.iw + 1) wide.push(`/admin/connectors form scrollWidth=${m.sw}`);
  expect(wide, wide.join('\n')).toEqual([]);
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await signIn(page);
  if (ids.webhook) await api(page, 'DELETE', `/api/webhooks/${ids.webhook}`);
  if (ids.connector) await api(page, 'DELETE', `/api/connectors/${ids.connector}`);
  if (ids.price) await api(page, 'DELETE', `/api/admin/llm-pricing/${ids.price}`);
  if (ids.apiKey) await api(page, 'DELETE', `/api/api-keys/${ids.apiKey}`);
  const sets = ((await api(page, 'GET', '/api/governance/permission-sets')).json?.data || []) as any[];
  for (const s of sets) if (s.name === PERMSET) await api(page, 'DELETE', `/api/governance/permission-sets/${s.id}`);
  // the tenant key, only if this run set it and stopped before clearing
  if (ids.asana) await api(page, 'DELETE', '/api/admin/tool-config/ASANA_TOKEN?scope=tenant');
  const team = ((await api(page, 'GET', '/api/team/members')).json?.data || {}) as any;
  for (const inv of team.pending_invites || []) if (inv.email === PERSON.email) await api(page, 'DELETE', `/api/team/invites/${inv.id}`);
  const left = (team.members || []).find((m: any) => m.email === PERSON.email && m.is_active);
  if (left) await api(page, 'DELETE', `/api/team/members/${left.id}`);
  // a throwaway account this run made is erased, never left behind
  const mine = (team.members || []).find((m: any) => m.email === PERSON.email);
  if (mine) await api(page, 'POST', `/api/gdpr/users/${mine.id}/purge`);
  await page.close();
});
