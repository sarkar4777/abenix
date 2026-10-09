/**
 * The governed improvement loop, from the screens only, as a person would use it.
 *
 *   1. Sample        the sample agent with a planted mistake (answers in Fahrenheit when asked for Kelvin)
 *   2. Propose       Propose a fix from its lesson group, watch the proof steps, see fixed and 0 broken
 *   3. Approve       the author sees the self-approval label (or is refused), a second person approves when one is set
 *                    the approval is edited first to plant a worse change, which still passes its proof
 *   4. Release       the release shows in revision history with a link to the proof
 *   5. Regression    three thumbs down on the new version, Check now, it rolls back on its own with the reason
 *   6. Phone width   /improvements and the agent tab have no sideways scroll at 390px
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_improvements_loop_ui.spec.ts --workers=1
 *   SECOND_EMAIL / SECOND_PASSWORD: a teammate in the same workspace with Approve improvements, optional
 */
import { test, expect, type Page } from '@playwright/test';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const SECOND = process.env.SECOND_EMAIL ? { email: process.env.SECOND_EMAIL, password: process.env.SECOND_PASSWORD || '' } : null;
const SAMPLE = 'Temperature helper (sample)';
const GROUP = 'Answers in Fahrenheit when the user asks for Kelvin';
const WORSE = "Start every answer with the words 'Hmm, let me think.'";
const PROOF_MS = 10 * 60_000;
const LLM_MS = 300_000;

const SHOTS = path.join(__dirname, 'uat_improvements_loop_ui', 'shots');
const ids: { agent?: string; proposal?: string; approval?: string } = {};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
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

async function signOut(page: Page) {
  await page.evaluate(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  });
  await page.context().clearCookies();
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

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

async function noSidewaysScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over, 'the page scrolls sideways').toBeLessThanOrEqual(1);
}

async function openAgentTab(page: Page) {
  await go(page, `/agents/${ids.agent}/improvements`);
  await expect(page.getByTestId('agent-improvements')).toBeVisible({ timeout: 30_000 });
}

async function chat(page: Page, message: string) {
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
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

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test('1. the sample agent arrives with its planted mistake and lessons', async ({ page }) => {
  await go(page, '/improvements');
  await expect(page.getByTestId('improvements-page')).toBeVisible({ timeout: 30_000 });
  const sample = page.getByTestId('improvements-sample');
  await expect(sample, 'the Try it on the sample agent button is on the Improvements page').toBeVisible({ timeout: 30_000 });
  await sample.click();
  await expect(page.getByTestId('agent-improvements')).toBeVisible({ timeout: 60_000 });
  ids.agent = page.url().match(/agents\/([0-9a-f-]{36})/)?.[1];
  expect(ids.agent, 'the sample opened its agent tab').toBeTruthy();

  const group = page.getByTestId('improvement-cluster').filter({ hasText: GROUP });
  await expect(group).toBeVisible({ timeout: 30_000 });
  await expect(group).toContainText('Fahrenheit');
  const read = await api(page, 'GET', `/api/agents/${ids.agent}`);
  expect(read.json?.data?.system_prompt || '').toContain('Always give the answer in degrees Fahrenheit');
  await shot(page, '01-sample');
});

test('2. propose a fix and watch the proof: fixed, 0 broken', async ({ page }) => {
  test.setTimeout(PROOF_MS + 120_000);
  await openAgentTab(page);
  const group = page.getByTestId('improvement-cluster').filter({ hasText: GROUP });
  await group.getByTestId('propose-fix').click();
  const live = group.getByTestId('propose-live');
  await expect(live).toBeVisible({ timeout: 30_000 });
  ids.proposal = (await live.getAttribute('data-proposal-id')) || undefined;
  expect(ids.proposal).toBeTruthy();

  // the steps show up with counts while it runs
  await expect(live.getByTestId('proof-steps')).toBeVisible({ timeout: 120_000 }).catch(() => {});
  await live.getByTestId('propose-see-proof').click();
  const item = page.locator(`[data-testid="proposal-item"][data-proposal-id="${ids.proposal}"]`);
  await expect(item).toBeVisible({ timeout: 30_000 });
  await expect(item.getByTestId('proof-step-test_set')).toBeVisible({ timeout: 120_000 });
  await shot(page, '02-proving');

  await expect(item).toHaveAttribute('data-state', /awaiting_approval|failed_proof/, { timeout: PROOF_MS });
  await expect(item).toHaveAttribute('data-state', 'awaiting_approval');
  await expect(item.getByTestId('proof-fixed')).toContainText(/Fixed [1-9]/);
  await expect(item.getByTestId('proof-broken')).toHaveAttribute('data-count', '0');
  await expect(item.getByTestId('proposal-diff')).toBeVisible();
  await expect(item.getByTestId('proof-before-after')).toBeVisible();
  await expect(item.getByTestId('proof-examples')).toContainText(/K|kelvin/i);
  await shot(page, '02-proved');

  const back = await api(page, 'GET', `/api/improvements/proposals/${ids.proposal}`);
  expect(back.json.data.proof.passed_bar).toBe(true);
  expect(back.json.data.proof.broken).toHaveLength(0);
  ids.approval = back.json.data.approval_id;
  expect(ids.approval).toBeTruthy();
});

test('3. separation of duties, then a planted worse change is proved and approved', async ({ page }) => {
  test.setTimeout(PROOF_MS + 180_000);
  await go(page, '/approvals');
  let card = page.locator(`[data-testid="improvement-approval-card"][data-approval-id="${ids.approval}"]`);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.getByTestId('approval-gate-kind')).toContainText('agent improvement');

  // the author built the agent: either a labelled self-approval or a refusal with the way forward
  const label = card.getByTestId('approval-self-approval');
  const labelled = await label.count();
  if (labelled) await expect(label).toContainText(/approve it yourself/);
  else await expect(card).toContainText('not the person who built the agent');

  // plant a worse change: it still fixes Kelvin, so the proof passes, but people will not like it
  await card.getByTestId('improvement-edit-approve').click();
  const editor = card.getByTestId('improvement-approval-edit-text');
  const text = await editor.inputValue();
  const diff = JSON.parse(text);
  if (Array.isArray(diff.edits) && diff.edits.length) {
    diff.edits[diff.edits.length - 1].replace = `${diff.edits[diff.edits.length - 1].replace} ${WORSE}`;
  } else if (Array.isArray(diff.examples)) {
    diff.examples = diff.examples.map((e: { input: string; output: string }) => ({ ...e, output: `Hmm, let me think. ${e.output}` }));
  } else {
    diff.append = WORSE;
  }
  await editor.fill(JSON.stringify(diff, null, 2));
  await card.getByTestId('improvement-edit-save').click();
  await expect(card.getByTestId('improvement-approval-msg')).toContainText('being proved', { timeout: 30_000 });

  // the edited fix is proved again and comes back for approval
  await openAgentTab(page);
  const item = page.locator(`[data-testid="proposal-item"][data-proposal-id="${ids.proposal}"]`);
  await item.getByTestId('proposal-toggle').click().catch(() => {});
  await expect(item).toHaveAttribute('data-state', /awaiting_approval|failed_proof/, { timeout: PROOF_MS });
  await expect(item, 'the edited change still passes its proof').toHaveAttribute('data-state', 'awaiting_approval');
  const back = await api(page, 'GET', `/api/improvements/proposals/${ids.proposal}`);
  ids.approval = back.json.data.approval_id;

  if (SECOND) {
    if (!labelled) {
      await go(page, '/approvals');
      card = page.locator(`[data-testid="improvement-approval-card"][data-approval-id="${ids.approval}"]`);
      await card.getByTestId('improvement-approve').click();
      await expect(card.getByTestId('improvement-approval-msg')).toContainText('someone else');
      await expect(card.getByText('Invite a teammate')).toBeVisible();
    }
    await signOut(page);
    await signIn(page, SECOND);
  }
  await go(page, '/approvals');
  card = page.locator(`[data-testid="improvement-approval-card"][data-approval-id="${ids.approval}"]`);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByTestId('improvement-approve').click();
  await expect(card.getByTestId('improvement-approval-msg')).toContainText('Approved', { timeout: 30_000 });
  await shot(page, '03-approved');

  await expect(async () => {
    const r = await api(page, 'GET', `/api/improvements/proposals/${ids.proposal}`);
    expect(r.json.data.state).toBe('released');
  }).toPass({ timeout: 60_000 });
});

test('4. the release is in revision history with a link to the proof', async ({ page }) => {
  await go(page, `/agents/${ids.agent}/info`);
  await page.getByRole('button', { name: /version history|revisions|history/i }).first().click();
  const proofLink = page.locator('[data-testid^="version-proof-"]').first();
  await expect(proofLink).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[data-testid^="version-source-"]').first()).toContainText(/Improvement/i);
  await proofLink.click();
  await expect(page).toHaveURL(new RegExp(`proposal=${ids.proposal}`));
  const release = page.locator(`[data-testid="release-watch"][data-proposal-id="${ids.proposal}"]`);
  await expect(release).toBeVisible({ timeout: 30_000 });
  await expect(release.getByTestId('release-watch-progress')).toContainText('Watching');
  await shot(page, '04-release');
});

test('5. the forced regression rolls back on its own and says why', async ({ page }) => {
  test.setTimeout(3 * LLM_MS);
  await go(page, '/chat');
  await expect(page.getByTestId('chat-agent-picker')).not.toContainText(/loading|choose an agent/i, { timeout: 60_000 }).catch(() => {});
  await page.getByTestId('chat-agent-picker').click();
  await page.getByTestId('chat-agent-search').fill('Temperature helper');
  await page.getByTestId('chat-agent-option').filter({ hasText: SAMPLE }).first().click();

  for (const q of ['What is 10 degrees Celsius in Kelvin?', 'Convert 30 °C to kelvin', 'And 5 C in K?']) {
    const reply = await chat(page, q);
    const bar = reply.getByTestId('chat-feedback');
    await bar.getByTestId('chat-feedback-down').click();
    const box = bar.getByTestId('chat-feedback-box');
    if (await box.count()) {
      await box.getByTestId('chat-feedback-correction').fill('Just the answer please, no "Hmm, let me think."');
      await box.getByTestId('chat-feedback-send').click();
    }
    await expect(bar.getByTestId('chat-feedback-thanks')).toBeVisible({ timeout: 15_000 });
  }

  await openAgentTab(page);
  const release = page.locator(`[data-testid="release-watch"][data-proposal-id="${ids.proposal}"]`);
  await expect(release).toBeVisible({ timeout: 30_000 });
  await expect(async () => {
    if ((await release.getAttribute('data-outcome')) === 'watching') {
      await release.getByTestId('release-check-now').click();
    }
    await expect(release).toHaveAttribute('data-outcome', 'rolled_back', { timeout: 10_000 });
  }).toPass({ timeout: 180_000 });
  await expect(release.getByTestId('release-rolled-back')).toContainText('Rolled back automatically');
  await expect(release.getByTestId('release-rollback-reason')).toContainText(/Thumbs down rose/);
  await expect(release.getByTestId('release-measures')).toBeVisible();
  await shot(page, '05-rolled-back');

  const back = await api(page, 'GET', `/api/improvements/proposals/${ids.proposal}`);
  expect(back.json.data.state).toBe('rolled_back');
  expect(back.json.data.watch_result.automatic).toBe(true);
  const agent = await api(page, 'GET', `/api/agents/${ids.agent}`);
  expect(agent.json.data.system_prompt).not.toContain('Hmm, let me think');

  // the approver and the owner were told why
  const notes = await api(page, 'GET', '/api/notifications?limit=50');
  const items = (notes.json?.data?.items || notes.json?.data || []) as Array<{ type?: string; message?: string }>;
  expect(items.some((n) => n.type === 'improvement_rolled_back' && /Thumbs down/.test(n.message || ''))).toBe(true);
});

test('6. the Improvements page and the agent tab work at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await go(page, '/improvements');
  await expect(page.getByTestId('improvements-page')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('budget-meter')).toBeVisible({ timeout: 30_000 });
  await noSidewaysScroll(page);
  await shot(page, '06-improvements-390');
  await openAgentTab(page);
  await noSidewaysScroll(page);
  const release = page.locator(`[data-testid="release-watch"][data-proposal-id="${ids.proposal}"]`);
  await release.getByTestId('release-proof-toggle').click();
  await expect(release.getByTestId('proposal-proof')).toBeVisible();
  await noSidewaysScroll(page);
  await shot(page, '06-agent-tab-390');
});
