/**
 * Earned Autonomy from the screens only, the whole ladder on the sample plant.
 *
 *   1. Autonomy page    empty state or overview, open the sample plant
 *   2. Watching         run the sample, proposals are recorded and nothing changes the plant
 *   3. Reviews          answer them under Approvals with the keyboard
 *   4. Promote          the checklist turns green, Promote, self-approve the sample, now Asks first
 *   5. Asks first       approve, edit and reject proposals in place on the timeline
 *   6. Outcomes         the plant's real pressure comes back and is scored against the prediction
 *   7. Acts within limits  promote again, runs act without asking
 *   8. Harm             flag harm on an action, the level drops to Asks first at once
 *   9. Elsewhere        flight recorder badge, agent page Actions, help, phone width
 *
 * The API is only used to read state back for assertions.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_autonomy_ui.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const SHOTS = path.join(__dirname, 'uat_autonomy_ui', 'shots');
const LLM_WAIT = 6 * 60_000;

const state: { grantId?: string } = {};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });
test.setTimeout(30 * 60_000);

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });
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

async function api(page: Page, p: string) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const res = await page.request.get(`${API}${p}`, { headers: { Authorization: `Bearer ${tok}` } });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), data: json?.data ?? json };
}

async function grant(page: Page) {
  return (await api(page, `/api/autonomy/grants/${state.grantId}`)).data;
}

async function actions(page: Page, status = '') {
  const q = status ? `?status=${status}&limit=100` : '?limit=100';
  return ((await api(page, `/api/autonomy/grants/${state.grantId}/actions${q}`)).data?.items || []) as any[];
}

async function openGrant(page: Page) {
  await go(page, `/autonomy/${state.grantId}`);
  await expect(page.getByTestId('autonomy-grant-page')).toBeVisible({ timeout: 30_000 });
}

// starts runs from the sample banner and waits for the summary that replaces the spinner
async function runSample(page: Page, n: 1 | 3 | 5) {
  await openGrant(page);
  const id = n === 1 ? 'autonomy-run-sample' : `autonomy-run-sample-${n}`;
  await page.getByTestId(id).click();
  await expect(page.getByTestId('autonomy-run-status')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('autonomy-run-summary')).toBeVisible({ timeout: LLM_WAIT });
  return (await page.getByTestId('autonomy-run-summary').innerText()).trim();
}

async function levelOf(page: Page) {
  return Number((await grant(page))?.level ?? -1);
}

async function promoteAndSelfApprove(page: Page, toLabel: string) {
  await openGrant(page);
  const promote = page.getByTestId('autonomy-promote');
  await expect(promote).toBeEnabled({ timeout: 30_000 });
  await promote.click();
  const panel = page.getByTestId('autonomy-self-approval');
  await expect(panel).toBeVisible({ timeout: 20_000 });
  // the sample says why the author may approve it
  await expect(panel).toContainText('sample');
  await page.getByTestId('autonomy-self-approve').click();
  await expect(page.getByTestId('autonomy-promote-message')).toContainText('self-approved', { timeout: 20_000 });
  await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText(toLabel, { timeout: 20_000 });
}

test('the autonomy page opens the sample plant', async ({ page }) => {
  await signIn(page);
  await go(page, '/autonomy');
  await expect(page.getByTestId('autonomy-page')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('autonomy-how-it-works')).toBeVisible();
  await shot(page, '01-autonomy-page');

  const start = page.getByTestId('autonomy-sample-start');
  if (await start.count()) {
    await start.click();
  } else {
    // the grid row is the agent, its cell is the action
    await page.locator('tr', { hasText: 'Plant operator (sample)' }).getByTestId('autonomy-grid-cell').first().click();
  }
  await page.waitForURL(/\/autonomy\/[0-9a-f-]{36}/, { timeout: 60_000 });
  state.grantId = page.url().split('/autonomy/')[1].split(/[?#]/)[0];
  await expect(page.getByTestId('autonomy-ladder')).toBeVisible();
  await expect(page.getByTestId('autonomy-sample-banner')).toBeVisible();

  // limits that cannot be checked block everything, the page says so and offers the fix
  if (await page.getByTestId('autonomy-limits-problem').count()) {
    await shot(page, '01b-limits-problem');
    await page.getByTestId('autonomy-repair-sample').click();
    await expect(page.getByTestId('autonomy-limits-problem')).toHaveCount(0, { timeout: 30_000 });
  }

  // a rerun starts from Watching again, through the Demote control
  if ((await levelOf(page)) !== 1) {
    await page.getByTestId('autonomy-demote').click();
    await page.getByTestId('autonomy-demote-to').selectOption('1');
    await page.getByTestId('autonomy-demote-reason').fill('Starting the UI journey from Watching');
    await page.getByTestId('autonomy-demote-confirm').click();
    await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText('Watching', { timeout: 20_000 });
  }
  await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText('Watching');
  await expect(page.getByTestId('autonomy-next-step')).toBeVisible();
  await shot(page, '02-grant-watching');
});

test('watching runs record proposals and change nothing', async ({ page }) => {
  await signIn(page);
  const before = (await actions(page, 'watching')).length;
  let watching = before;
  for (let i = 0; i < 3 && watching - before < 5; i++) {
    const summary = await runSample(page, 5);
    test.info().annotations.push({ type: 'run-summary', description: summary });
    watching = (await actions(page, 'watching')).length;
  }
  expect(watching - before).toBeGreaterThanOrEqual(5);
  const card = page.locator('[data-testid="action-card"][data-status="watching"]').first();
  await expect(card).toBeVisible();
  await expect(card).toContainText('would');
  await expect(card.getByTestId('action-card-prediction')).toBeVisible();
  await shot(page, '03-watching-actions');
  // nothing was executed while watching
  const executed = (await actions(page)).filter((a) => a.status === 'executed' && a.level_at_time === 1);
  expect(executed).toHaveLength(0);
});

test('reviews are answered under Approvals with the keyboard', async ({ page }) => {
  await signIn(page);
  await go(page, '/approvals?tab=watching');
  await expect(page.getByTestId('autonomy-reviews')).toBeVisible({ timeout: 30_000 });
  await shot(page, '04-reviews');
  for (let i = 0; i < 12; i++) {
    if (await page.getByTestId('autonomy-reviews-empty').count()) break;
    const agree = page.getByTestId('autonomy-review-agree').first();
    if (!(await agree.count())) break;
    await expect(agree).toBeVisible();
    await page.keyboard.press('a');
    await page.waitForTimeout(800);
  }
  const g = await grant(page);
  expect(Number(g.stats?.reviews ?? 0)).toBeGreaterThanOrEqual(5);
});

test('the checklist turns green and the sample is promoted to Asks first', async ({ page }) => {
  await signIn(page);
  await openGrant(page);
  await expect(page.getByTestId('autonomy-requirements')).toBeVisible();
  await shot(page, '05-ready-to-promote');
  await promoteAndSelfApprove(page, 'Asks first');
  await expect(page.getByTestId('autonomy-history')).toContainText('Self-approved', { timeout: 20_000 });
  expect(await levelOf(page)).toBe(2);
  await shot(page, '06-asks-first');
});

test('asks first: approve, edit and reject in place on the timeline', async ({ page }) => {
  await signIn(page);
  await openGrant(page);
  await page.getByTestId('autonomy-run-sample-3').click();
  // each run waits for a person, so the cards appear while the runs are still going
  const pending = page.locator('[data-testid="action-card"][data-status="pending"]');

  // a run that reads the plant already on target proposes nothing, so a person runs it once more
  async function nextPending() {
    const until = Date.now() + LLM_WAIT;
    while (Date.now() < until) {
      if (await pending.first().isVisible().catch(() => false)) return;
      const idle = !(await page.getByTestId('autonomy-run-status').isVisible().catch(() => false));
      if (idle && await page.getByTestId('autonomy-run-summary').isVisible().catch(() => false)) {
        test.info().annotations.push({ type: 'top-up', description: (await page.getByTestId('autonomy-run-summary').innerText()).trim() });
        await page.getByTestId('autonomy-run-sample').click();
        await expect(page.getByTestId('autonomy-run-status')).toBeVisible({ timeout: 30_000 });
      }
      await page.waitForTimeout(2_000);
    }
    await expect(pending.first()).toBeVisible({ timeout: 5_000 });
  }

  await nextPending();
  await shot(page, '07-pending-in-timeline');

  const decided: string[] = [];
  for (const how of ['approve', 'edit', 'reject'] as const) {
    await nextPending();
    const card = pending.first();
    const id = (await card.getAttribute('data-action-id')) || '';
    if (how === 'approve') {
      await card.getByTestId('action-card-approve').click();
    } else if (how === 'edit') {
      await card.getByTestId('action-card-edit').click();
      const field = card.getByTestId('action-card-arg-setpoint_bar');
      await expect(field).toBeVisible();
      await field.fill('4.5');
      await card.getByTestId('action-card-edit-submit').click();
    } else {
      await card.getByTestId('action-card-reject').click();
      await card.getByTestId('action-card-reject-note').fill('Pressure is fine, leave it');
      await card.getByTestId('action-card-reject-submit').click();
    }
    decided.push(id);
    await expect(page.locator(`[data-testid="action-card"][data-action-id="${id}"]`)).not.toHaveAttribute('data-status', 'pending', { timeout: 60_000 });
  }
  await expect(page.getByTestId('autonomy-run-summary')).toBeVisible({ timeout: LLM_WAIT });
  const rows = await actions(page);
  const byId = Object.fromEntries(rows.map((a) => [a.id, a]));
  expect(byId[decided[0]]?.status).toBe('executed');
  expect(['executed', 'edited']).toContain(byId[decided[1]]?.status);
  expect(byId[decided[1]]?.arguments?.setpoint_bar).toBe(4.5);
  expect(byId[decided[2]]?.status).toBe('rejected');
  await shot(page, '08-decided-in-place');
});

test('outcomes come back from the plant and are scored', async ({ page }) => {
  await signIn(page);
  // the probe reads the plant 30 s after the change and the job runs every 30 s
  await expect.poll(async () => (await actions(page)).filter((a) => a.outcome_status === 'observed').length, { timeout: 4 * 60_000, intervals: [10_000] }).toBeGreaterThan(0);
  await openGrant(page);
  const scored = page.locator('[data-testid="action-card"]').filter({ has: page.getByTestId('action-card-outcome') }).first();
  await expect(scored).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('autonomy-chart')).toBeVisible();
  await expect(page.locator('[data-testid="autonomy-chart-dot"]').first()).toBeVisible();
  await shot(page, '09-outcomes-and-chart');
});

test('enough approved actions promote it to Acts within limits, then it acts without asking', async ({ page }) => {
  await signIn(page);
  // approve batches until the checklist for the next level is green
  for (let round = 0; round < 6; round++) {
    const g = await grant(page);
    if (g?.next?.ready) break;
    await openGrant(page);
    await page.getByTestId('autonomy-run-sample-3').click();
    const pending = page.locator('[data-testid="action-card"][data-status="pending"]');
    const deadline = Date.now() + LLM_WAIT;
    while (Date.now() < deadline) {
      if (await page.getByTestId('autonomy-run-summary').count()) break;
      if (await pending.count()) {
        const card = pending.first();
        const id = (await card.getAttribute('data-action-id')) || '';
        await card.getByTestId('action-card-approve').click();
        await expect(page.locator(`[data-testid="action-card"][data-action-id="${id}"]`)).not.toHaveAttribute('data-status', 'pending', { timeout: 60_000 });
      } else {
        await page.waitForTimeout(3000);
      }
    }
    // let the outcomes land before checking the numbers again
    await page.waitForTimeout(75_000);
  }
  const g = await grant(page);
  if (!g?.next?.ready) {
    await openGrant(page);
    await shot(page, '10-not-ready');
    const missing = (g?.next?.requirements || []).filter((r: any) => !r.met).map((r: any) => r.label).join(' | ');
    throw new Error(`Not ready for Acts within limits after 6 rounds: ${missing}`);
  }
  await promoteAndSelfApprove(page, 'Acts within limits');
  expect(await levelOf(page)).toBe(3);
  await shot(page, '10-within-limits');

  const before = (await actions(page)).filter((a) => a.mode === 'auto').length;
  await runSample(page, 3);
  const auto = (await actions(page)).filter((a) => a.mode === 'auto');
  const fallbacks = (await actions(page)).filter((a) => a.level_at_time === 3 && a.status === 'pending');
  expect(auto.length + fallbacks.length).toBeGreaterThan(before);
  // anything it did not do alone says why on its card
  for (const f of fallbacks.slice(0, 1)) {
    await expect(page.locator(`[data-testid="action-card"][data-action-id="${f.id}"]`).getByTestId('action-card-fallback')).toBeVisible();
  }
  await shot(page, '11-acting-alone');
});

test('flagging harm drops it to Asks first at once', async ({ page }) => {
  await signIn(page);
  await openGrant(page);
  const done = page.locator('[data-testid="action-card"][data-status="executed"]').first();
  await expect(done).toBeVisible({ timeout: 30_000 });
  await done.getByTestId('action-card-flag-harm').click();
  await done.getByTestId('action-card-harm-note').fill('Pressure overshot after this change');
  await done.getByTestId('action-card-harm-confirm').click();
  await expect.poll(() => levelOf(page), { timeout: 30_000 }).toBeLessThanOrEqual(2);
  await openGrant(page);
  await expect(page.getByTestId('autonomy-grant-level-pill')).toContainText('Asks first');
  await expect(page.getByTestId('autonomy-history')).toContainText(/harm/i);
  await go(page, '/autonomy');
  await expect(page.getByTestId('autonomy-demoted')).toContainText('Plant operator (sample)', { timeout: 30_000 });
  await shot(page, '12-demoted-after-harm');
});

test('the flight recorder, agent page and help show autonomy', async ({ page }) => {
  await signIn(page);
  const withRun = (await actions(page)).find((a) => a.execution_id);
  expect(withRun).toBeTruthy();
  await go(page, `/executions/${withRun.execution_id}`);
  await expect(page.getByTestId('autonomy-step-badge').first()).toBeVisible({ timeout: 30_000 });
  await shot(page, '13-flight-recorder');

  const g = await grant(page);
  await go(page, `/agents/${g.agent.id}/info`);
  await expect(page.getByTestId('autonomy-agent-actions')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('autonomy-agent-action-sample_plant')).toBeVisible();
  await shot(page, '14-agent-actions');

  await go(page, '/help');
  await expect(page.getByTestId('help-earned-autonomy')).toBeAttached({ timeout: 30_000 });
});

test('phone width: autonomy pages do not scroll sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  for (const route of ['/autonomy', `/autonomy/${state.grantId}`, '/approvals?tab=reviews']) {
    await go(page, route);
    await page.waitForTimeout(1500);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide, `${route} scrolls sideways by ${wide}px`).toBeLessThanOrEqual(1);
    await shot(page, `15-phone${route.replace(/[/?=]/g, '-')}`);
  }
});
