/**
 * Governed self-improvement, capture side, from the screens only, as a new user would use it.
 *
 *   1. Chat         ask a question, thumbs down, write what it should have said
 *   2. Again        ask the same thing in other words, thumbs down with a similar correction
 *   3. Agent tab    the See lessons link opens the agent's Improvements tab, the two lessons are one group
 *   4. Cases        the group suggests test cases, pick all and accept them in bulk
 *   5. Run page     thumbs and "This was wrong because" on the run behind the answer
 *   6. Phone width  /improvements and the agent tab at 390px with no sideways scroll
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_improvements_capture_ui.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const AGENT_SEARCH = process.env.IMPROVE_AGENT || 'code assistant';
const RUN = Date.now().toString(36).replace(/[0-9]/g, '');
// made-up words keep this run's lessons apart, most of the eight grouping keywords must be new each run
const WORD = `zorblat${RUN}`;
const NAME = [WORD, `quillen${RUN}`, `marvex${RUN}`, `tandry${RUN}`, `oskel${RUN}`].join(' ');
const Q1 = `What does the ${NAME} setting control? Answer in one sentence.`;
const Q2 = `In one sentence, what does the ${NAME} setting control?`;
const FIX1 = `The ${WORD} setting controls the retry budget for outbound calls.`;
const FIX2 = `It controls the retry budget for outbound calls, the ${WORD} setting.`;

const SHOTS = path.join(__dirname, 'uat_improvements_capture_ui', 'shots');
const LLM_MS = 300_000;

const state: { agentId?: string; suiteExisted?: boolean; suiteId?: string; caseIds: string[]; clusterId?: string; executionId?: string } = { caseIds: [] };

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

async function signIn(page: Page) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(ADMIN.email);
  await page.locator('#auth-password').fill(ADMIN.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function api(page: Page, method: string, p: string, body?: unknown) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const headers: Record<string, string> = { Authorization: `Bearer ${tok}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await page.request.fetch(`${API}${p}`, {
    method,
    headers,
    data: body === undefined ? undefined : JSON.stringify(body),
  });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function send(page: Page, message: string) {
  const input = page.getByTestId('chat-input');
  await expect(input).toBeEnabled({ timeout: 30_000 });
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const before = await replies.count();
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: LLM_MS });
  const err = page.getByTestId('chat-error');
  if (await err.count()) throw new Error(`the run failed in chat: ${await err.innerText()}`);
  await expect(replies).toHaveCount(before + 1, { timeout: 30_000 });
  return replies.nth(before);
}

async function thumbsDownWith(page: Page, reply: ReturnType<Page['locator']>, correction: string) {
  const bar = reply.getByTestId('chat-feedback');
  await expect(bar).toBeVisible({ timeout: 30_000 });
  await bar.getByTestId('chat-feedback-down').click();
  const box = bar.getByTestId('chat-feedback-box');
  await expect(box).toBeVisible();
  await expect(box).toContainText('What should it have said or done?');
  await expect(box).toContainText('Optional');
  await box.getByTestId('chat-feedback-correction').fill(correction);
  await box.getByTestId('chat-feedback-send').click();
  await expect(bar.getByTestId('chat-feedback-thanks')).toContainText("Thanks, this goes into the agent's lessons");
  await expect(bar.getByTestId('chat-feedback-thanks')).toContainText('with your correction');
  return bar;
}

async function noSideScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over).toBeLessThanOrEqual(1);
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  try {
    await signIn(page);
    for (const id of state.caseIds) await api(page, 'DELETE', `/api/evals/cases/${id}`);
    if (state.suiteId && !state.suiteExisted) await api(page, 'DELETE', `/api/evals/suites/${state.suiteId}`);
    if (state.clusterId) await api(page, 'POST', `/api/improvements/clusters/${state.clusterId}/dismiss`, { reason: 'UAT cleanup' });
  } finally {
    await page.close();
  }
});

test('a thumbs down with a correction becomes a lesson, groups with a similar one and gives cases to accept', async ({ page }) => {
  test.setTimeout(15 * 60_000);

  // 1. chat, pick the agent the way a person does
  await go(page, '/chat');
  await expect(page.getByTestId('chat-agent-picker')).not.toContainText(/loading|choose an agent/i, { timeout: 60_000 });
  await page.getByTestId('chat-agent-picker').click();
  await page.getByTestId('chat-agent-search').fill(AGENT_SEARCH);
  await page.getByTestId('chat-agent-option').first().click();

  const first = await send(page, Q1);
  const bar = await thumbsDownWith(page, first, FIX1);

  // the owner link goes to the agent's tab, remember the agent for read back
  const link = bar.getByTestId('chat-feedback-lessons-link');
  await expect(link).toBeVisible();
  const href = (await link.getAttribute('href')) || '';
  state.agentId = href.split('/')[2];
  expect(state.agentId).toBeTruthy();
  const suites = await api(page, 'GET', `/api/evals/suites?agent_id=${state.agentId}`);
  const items: any[] = suites.json?.data?.items || suites.json?.data || [];
  const existing = items.find((s: any) => s.name === 'Improvement tests');
  state.suiteExisted = !!existing;
  state.suiteId = existing?.id;

  // 2. the same question in other words, with a similar correction
  const second = await send(page, Q2);
  await thumbsDownWith(page, second, FIX2);
  await shot(page, '01-chat-feedback');

  // 3. the agent tab, through the link a person sees
  await bar.getByTestId('chat-feedback-lessons-link').click();
  await page.waitForURL(/\/agents\/[^/]+\/improvements/, { timeout: 30_000 });
  await expect(page.getByTestId('agent-improvements')).toBeVisible({ timeout: 30_000 });

  // grouping runs right after feedback and every two minutes, reload until it shows
  const group = page.getByTestId('improvement-cluster').filter({ hasText: WORD });
  await expect(async () => {
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(group).toBeVisible({ timeout: 5_000 });
    await expect(group.getByTestId('improvement-cluster-count')).toContainText('2 lessons', { timeout: 2_000 });
  }).toPass({ timeout: 4 * 60_000, intervals: [5_000, 10_000, 15_000] });
  state.clusterId = (await group.getAttribute('data-cluster-id')) || undefined;
  await expect(group.getByTestId('improvement-cluster-title')).not.toBeEmpty();
  await expect(group.getByTestId('improvement-severity')).toHaveAttribute('data-severity', /medium|high/);
  const lessons = group.getByTestId('improvement-lesson');
  await expect(lessons).toHaveCount(2);
  await expect(group).toContainText('Should be:');
  await expect(group).toContainText('retry budget');
  await expect(group.getByTestId('improvement-trend')).toContainText(/2 new lessons this week/);

  // read back: two correction lessons on this agent, grouped together
  const detail = await api(page, 'GET', `/api/improvements/clusters/${state.clusterId}`);
  expect(detail.status).toBe(200);
  const sources = (detail.json.data.lessons as any[]).map((l) => l.source);
  expect(sources).toEqual(['correction', 'correction']);

  // 4. suggested cases from this group, accepted in bulk
  const cases = page.getByTestId('improvement-case').filter({ hasText: WORD });
  await expect(cases.first()).toBeVisible({ timeout: 30_000 });
  const count = await cases.count();
  expect(count).toBeGreaterThanOrEqual(1);
  await expect(cases.first()).toContainText('Right answer:');
  for (let i = 0; i < count; i++) {
    const id = await cases.nth(i).getAttribute('data-case-id');
    if (id) state.caseIds.push(id);
    await cases.nth(i).getByTestId('improvement-case-pick').check();
  }
  await shot(page, '02-agent-tab');
  await page.getByTestId('improvement-cases-accept').click();
  await expect(page.getByText(/case(s)? accepted/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('improvement-case').filter({ hasText: WORD })).toHaveCount(0, { timeout: 15_000 });

  const after = await api(page, 'GET', `/api/improvements/agents/${state.agentId}`);
  const stillSuggested = (after.json.data.suggested_cases as any[]).filter((c) => state.caseIds.includes(c.id));
  expect(stillSuggested).toHaveLength(0);
  if (!state.suiteId) {
    const listed = await api(page, 'GET', `/api/evals/suites?agent_id=${state.agentId}`);
    const all: any[] = listed.json?.data?.items || listed.json?.data || [];
    state.suiteId = all.find((s: any) => s.name === 'Improvement tests')?.id;
  }
  const suiteId = state.suiteId;
  expect(suiteId).toBeTruthy();
  if (suiteId) {
    const suite = await api(page, 'GET', `/api/evals/suites/${suiteId}`);
    const accepted = ((suite.json?.data?.cases || []) as any[]).map((c) => c.id);
    for (const id of state.caseIds) expect(accepted).toContain(id);
    // accepting never gates, the owner turns that on
    expect(suite.json?.data?.suite?.gating ?? suite.json?.data?.gating).toBe(false);
  }

  await expect(page.getByTestId('improvement-gate-switch')).toHaveAttribute('aria-checked', 'false');
  await expect(page.getByTestId('improvement-gate')).toContainText('Require these tests to pass before changes go live');

  // the Improvements page lists the agent
  await go(page, '/improvements');
  await expect(page.getByTestId('improvements-page')).toBeVisible();
  await expect(page.getByTestId('improvements-counts')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('improvements-agent-row').first()).toBeVisible();
});

test('the run page takes thumbs and a "this was wrong because" note', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  test.skip(!state.clusterId, 'needs the lessons from the first test');
  const detail = await api(page, 'GET', `/api/improvements/clusters/${state.clusterId}`);
  state.executionId = (detail.json.data.lessons as any[]).find((l) => l.execution_id)?.execution_id;
  test.skip(!state.executionId, 'the chat answer carried no run id');

  // the lesson links to its run, as a person would follow it
  await go(page, `/agents/${state.agentId}/improvements`);
  const group = page.getByTestId('improvement-cluster').filter({ hasText: WORD });
  await group.getByRole('link', { name: 'View run' }).first().click();
  await page.waitForURL(/\/executions\//, { timeout: 30_000 });

  await expect(page.getByTestId('run-feedback')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('wrong-because-open').click();
  await expect(page.getByTestId('wrong-because-save')).toBeDisabled();
  await page.getByTestId('wrong-because-note').fill(`It guessed what ${WORD} means instead of saying it did not know.`);
  await page.getByTestId('wrong-because-save').click();
  await expect(page.getByTestId('wrong-because-saved')).toContainText("Thanks, this goes into the agent's lessons");

  const notes = await api(page, 'GET', `/api/improvements/lessons?agent_id=${state.agentId}&source=note`);
  expect((notes.json.data.items as any[]).some((l) => (l.note || '').includes(WORD))).toBe(true);
});

test('Improvements and the agent tab work at 390px', async ({ page }) => {
  test.skip(!state.agentId, 'needs the agent from the first test');
  await page.setViewportSize({ width: 390, height: 844 });
  await go(page, '/improvements');
  await expect(page.getByTestId('improvements-page')).toBeVisible();
  await expect(page.getByTestId('improvements-counts')).toBeVisible({ timeout: 30_000 });
  await noSideScroll(page);
  await shot(page, '03-improvements-390');
  await go(page, `/agents/${state.agentId}/improvements`);
  await expect(page.getByTestId('agent-improvements')).toBeVisible({ timeout: 30_000 });
  await noSideScroll(page);
  await shot(page, '04-agent-tab-390');
});
