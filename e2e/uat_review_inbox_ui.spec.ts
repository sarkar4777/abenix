/**
 * Hold for review and moderation retention, from the screens only.
 *
 *   1. Hold policy     an admin creates a Hold for review policy, invites a member and a reviewer,
 *                      and gives the reviewer the Review held content permission in Permissions
 *   2. Waiting         the member's chat trips the policy and shows Waiting for review
 *   3. Redact          the reviewer claims it, redacts and releases it, the member sees the redacted text
 *   4. Reject          another held message is rejected with a reason the member reads in the chat
 *   5. Retention       the retention card validates, saves with an audit line, and event previews are masked
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_review_inbox_ui.spec.ts --workers=1
 */
import { test, expect, type Browser, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const TOKEN = `HOLDME-${RUN}`;
const PATTERN = `${TOKEN}-\\d+`;
const POLICY = `Hold for review ${RUN}`;
const PERMSET = `Content reviewers ${RUN}`;
const FIRST = `Please process ticket ${TOKEN}-1234 for me today.`;
const SECOND = `Second request about ${TOKEN}-5678, thanks.`;
const REASON = `It quotes an internal ticket number ${RUN}`;

const DIR = path.join(__dirname, 'uat_review_inbox_ui');
const SHOTS = path.join(DIR, 'shots');
const STATE = path.join(DIR, `state.json`);

interface Person { email: string; password: string; name: string; id?: string }
interface State {
  previousPolicy?: string | null;
  holdPolicy?: string;
  permset?: string;
  member?: Person;
  reviewer?: Person;
  retention?: Record<string, number>;
}
const state: State = fs.existsSync(STATE) ? JSON.parse(fs.readFileSync(STATE, 'utf-8')) : {};
const save = () => {
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(STATE, JSON.stringify(state, null, 2));
};

test.describe.configure({ mode: 'serial', timeout: 10 * 60_000 });
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

async function signInAs(page: Page, who: { email: string; password: string }) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(who.email);
  await page.locator('#auth-password').fill(who.password);
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

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

async function as(browser: Browser, who: Person) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('dialog', (d) => d.accept());
  await signInAs(page, who);
  return { ctx, page };
}

// invite from Settings, accept the link in a fresh browser
async function invite(page: Page, browser: Browser, who: Person) {
  await go(page, '/settings/team');
  await page.getByRole('button', { name: 'Invite Member' }).click();
  await page.getByPlaceholder('email@example.com').fill(who.email);
  await page.getByTestId('invite-role').selectOption('user');
  await page.getByTestId('invite-send').click();
  const link = page.getByTestId('invite-link');
  await expect(link).toBeVisible({ timeout: 20_000 });
  const url = (await link.innerText()).trim();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const p2 = await ctx.newPage();
  await p2.goto(url, { waitUntil: 'domcontentloaded' });
  await expect(p2.getByTestId('accept-title')).toBeVisible({ timeout: 30_000 });
  await p2.locator('#accept-full-name').fill(who.name);
  await p2.locator('#accept-password').fill(who.password);
  await p2.getByTestId('accept-submit').click();
  await p2.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await ctx.close();
}

// send a chat message as the member, the first agent in the picker is fine since the hold fires before the model
async function memberSends(page: Page, text: string, navigate = true) {
  if (navigate) await go(page, '/chat');
  await page.getByTestId('chat-new').click().catch(() => {});
  const picker = page.getByTestId('chat-agent-picker');
  await expect(picker).toBeVisible({ timeout: 30_000 });
  const input = page.getByTestId('chat-input');
  if (await input.isDisabled().catch(() => false)) {
    await picker.click();
    await page.getByTestId('chat-agent-option').first().click();
  }
  await input.fill(text);
  await page.getByTestId('chat-send').click();
}

function heldCard(page: Page) {
  return page.getByTestId('held-notice').last();
}

// the member's newest thread says which review holds this run's message, older runs may have left others
async function heldReviewId(memberPage: Page, source: 'pre_llm' | 'post_llm'): Promise<string> {
  let id = '';
  await expect(async () => {
    const convs = (await api(memberPage, 'GET', '/api/conversations?per_page=5')).json?.data || [];
    expect(convs.length).toBeGreaterThan(0);
    const conv = (await api(memberPage, 'GET', `/api/conversations/${convs[0].id}`)).json?.data;
    const blocks = (conv?.messages || []).flatMap((m: any) => m.blocks || []);
    const hold = blocks.reverse().find((b: any) => b.type === 'moderation_hold' && b.source === source && b.review_id);
    expect(hold?.review_id, `a ${source} hold in the newest thread`).toBeTruthy();
    id = hold.review_id;
  }).toPass({ timeout: 60_000 });
  return id;
}

async function openHeld(page: Page, author: string, preview: RegExp, reviewId: string) {
  await go(page, '/review-queue?tab=held');
  await expect(page.getByTestId('held-inbox')).toBeVisible({ timeout: 30_000 });
  const row = page.locator(`[data-testid="held-row"][data-review-id="${reviewId}"]`).filter({ hasText: author }).filter({ hasText: preview });
  await expect(row.first()).toBeVisible({ timeout: 60_000 });
  await row.first().getByRole('button').first().click();
  await expect(page.getByTestId('held-detail')).toContainText(author);
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signInAs(page, ADMIN);
});

// the held tests need this run's hold policy, its pattern carries this run's token
async function expectHoldPolicyLive(page: Page) {
  const list = (await api(page, 'GET', '/api/moderation/policies')).json?.data || [];
  const live = list.find((p: any) => p.id === state.holdPolicy);
  expect(live?.name, 'the hold policy from the first test of this run, run the whole spec').toBe(POLICY);
  expect(live?.is_active, 'the hold policy is the active one').toBe(true);
}

// cleanup signs in through the API so a broken screen never leaves the tenant without its default policy
test.afterAll(async ({ playwright }) => {
  const req = await playwright.request.newContext();
  try {
    const login = await req.post(`${API}/api/auth/login`, { data: { email: ADMIN.email, password: ADMIN.password } });
    const tok = (await login.json())?.data?.access_token;
    const headers = { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' };
    const call = async (method: string, p: string, body?: unknown) => {
      try {
        await req.fetch(`${API}${p}`, { method, headers, data: body === undefined ? undefined : JSON.stringify(body) });
      } catch (e) {
        console.warn(`cleanup ${method} ${p} failed: ${e}`);
      }
    };
    try {
      if (state.holdPolicy) await call('PATCH', `/api/moderation/policies/${state.holdPolicy}`, { is_active: false });
    } finally {
      try {
        if (state.previousPolicy) await call('PATCH', `/api/moderation/policies/${state.previousPolicy}`, { is_active: true });
      } finally {
        if (state.retention) await call('PUT', '/api/moderation/retention', state.retention);
        if (state.permset) await call('DELETE', `/api/governance/permission-sets/${state.permset}`);
      }
    }
  } finally {
    await req.dispose();
  }
});

test('Hold policy: created from the moderation page, a reviewer is given the permission in Permissions', async ({ page, browser }) => {
  test.setTimeout(6 * 60_000);
  const before = (await api(page, 'GET', '/api/moderation/policies')).json?.data || [];
  state.previousPolicy = before.find((p: any) => p.is_active)?.id || null;
  save();

  await go(page, '/moderation');
  await page.getByTestId('policy-name-input').fill(POLICY);
  await page.getByTestId('policy-default-action').selectOption('hold');
  const hold = page.getByTestId('policy-hold-settings');
  await expect(hold).toContainText('review inbox');
  // a bad time limit is explained and blocks saving
  await page.getByTestId('policy-hold-minutes').fill('0');
  await expect(hold).toContainText('Between 1 and 10080 minutes');
  await expect(page.getByTestId('create-policy-button')).toBeDisabled();
  await page.getByTestId('policy-hold-minutes').fill('60');
  await page.getByTestId('policy-hold-timeout-action').selectOption('reject');
  await page.getByTestId('policy-custom-patterns').fill(PATTERN);
  // pre and post: the member's message and the agent's reply are both checked
  await expect(page.getByTestId('policy-pre-llm')).toBeChecked();
  await expect(page.getByTestId('policy-post-llm')).toBeChecked();
  await shot(page, '01-hold-policy-form');
  await page.getByTestId('create-policy-button').click();
  await expect(page.getByTestId('policies-list')).toContainText(POLICY, { timeout: 20_000 });
  await expect(page.getByTestId('policies-list')).toContainText('hold for review');

  const after = (await api(page, 'GET', '/api/moderation/policies')).json?.data || [];
  const mine = after.find((p: any) => p.name === POLICY);
  expect(mine?.is_active).toBe(true);
  expect(mine?.default_action).toBe('hold');
  expect(mine?.hold_timeout_minutes).toBe(60);
  state.holdPolicy = mine.id;
  save();

  if (!state.member) {
    state.member = { email: `member-${RUN}@example.com`, password: `Member-${RUN}-9`, name: `Member ${RUN}` };
    await invite(page, browser, state.member);
    save();
  }
  if (!state.reviewer) {
    state.reviewer = { email: `reviewer-${RUN}@example.com`, password: `Reviewer-${RUN}-9`, name: `Reviewer ${RUN}` };
    await invite(page, browser, state.reviewer);
    save();
  }

  // the reviewer cannot see held content until they are given the permission
  {
    const { ctx, page: r } = await as(browser, state.reviewer);
    await go(r, '/review-queue');
    await expect(r.getByTestId('review-no-access')).toContainText('Review held content permission');
    await shot(r, '02-reviewer-before-permission');
    await ctx.close();
  }

  await go(page, '/admin/permissions');
  await page.getByTestId('permset-new').click();
  await page.getByTestId('permset-name').fill(PERMSET);
  await page.getByTestId('permset-cap-moderation.review').click();
  await page.getByTestId('permset-save').click();
  const set = page.getByTestId(`permset-${PERMSET}`);
  await expect(set).toBeVisible({ timeout: 20_000 });
  await page.getByTestId(`permset-add-${PERMSET}`).fill(state.reviewer.email);
  await set.getByRole('option').filter({ hasText: state.reviewer.email }).click();
  await expect(set).toContainText(state.reviewer.email, { timeout: 20_000 });
  await shot(page, '03-reviewer-permission');
  const sets = (await api(page, 'GET', '/api/governance/permission-sets')).json?.data || [];
  state.permset = sets.find((s: any) => s.name === PERMSET)?.id;
  save();
});

test('Waiting, then redacted: the member waits, the reviewer claims, redacts and releases', async ({ page, browser }) => {
  test.setTimeout(10 * 60_000);
  await expectHoldPolicyLive(page);
  const member = await as(browser, state.member!);
  const reviewer = await as(browser, state.reviewer!);
  try {
    await memberSends(member.page, FIRST);
    const card = heldCard(member.page);
    await expect(card).toHaveAttribute('data-status', 'pending', { timeout: 60_000 });
    await expect(card).toContainText('Your message is waiting for review');
    await expect(card).toContainText('it will not be sent');
    await expect(member.page.getByTestId('chat-error')).toHaveCount(0);
    await shot(member.page, '04-member-waiting');

    // the reviewer sees it in the sidebar count and the inbox, the token highlighted
    await go(reviewer.page, '/dashboard');
    await expect(reviewer.page.getByTestId('sidebar-review-count').first()).toBeVisible({ timeout: 60_000 });
    await openHeld(reviewer.page, state.member!.name, /Please process ticket/, await heldReviewId(member.page, 'pre_llm'));
    const content = reviewer.page.getByTestId('held-detail-content');
    await expect(content.locator('mark')).toHaveText(`${TOKEN}-1234`);
    await expect(reviewer.page.getByTestId('held-detail')).toContainText('custom pattern 1');
    await shot(reviewer.page, '05-reviewer-detail');

    await reviewer.page.getByTestId('held-claim').click();
    await expect(reviewer.page.getByTestId('held-detail')).toContainText('Claimed by');
    await expect(reviewer.page.getByTestId('held-detail')).toContainText('You');
    await reviewer.page.getByTestId('held-redact').click();
    const editor = reviewer.page.getByTestId('held-redact-text');
    await expect(editor).toHaveValue(/Please process ticket █████ for me today\./);
    await shot(reviewer.page, '06-redaction-editor');
    await reviewer.page.getByTestId('held-redact-submit').click();
    await reviewer.page.getByTestId('held-confirm-redact').click();
    await expect(reviewer.page.getByTestId('held-detail-status')).toHaveText('Redacted and released', { timeout: 20_000 });
    await reviewer.page.getByTestId('held-history').locator('summary').click();
    await expect(reviewer.page.getByTestId('held-history')).toContainText(`Redacted and released by ${state.reviewer!.name}`);
    await shot(reviewer.page, '07-reviewer-redacted');

    // the member's card turns into the redacted message without a reload
    await expect(card).toHaveAttribute('data-status', 'released', { timeout: 90_000 });
    await expect(card.getByTestId('held-notice-content')).toHaveText('Please process ticket █████ for me today.');
    await expect(member.page.getByText(`${TOKEN}-1234`)).toHaveCount(0);
    await shot(member.page, '08-member-redacted');

    // the stored thread shows the redacted text too
    await member.page.reload({ waitUntil: 'domcontentloaded' });
    await expect(heldCard(member.page)).toHaveAttribute('data-status', 'released', { timeout: 60_000 });
    await expect(member.page.getByText(`${TOKEN}-1234`)).toHaveCount(0);
  } finally {
    await member.ctx.close();
    await reviewer.ctx.close();
  }
});

test('Reject: another held message is rejected with a reason the member reads', async ({ page, browser }) => {
  test.setTimeout(8 * 60_000);
  await expectHoldPolicyLive(page);
  const member = await as(browser, state.member!);
  const reviewer = await as(browser, state.reviewer!);
  try {
    await memberSends(member.page, SECOND);
    const card = heldCard(member.page);
    await expect(card).toHaveAttribute('data-status', 'pending', { timeout: 60_000 });

    await openHeld(reviewer.page, state.member!.name, /Second request/, await heldReviewId(member.page, 'pre_llm'));
    await reviewer.page.getByTestId('held-reject').click();
    // no reason, no reject
    await expect(reviewer.page.getByTestId('held-confirm-reject')).toBeDisabled();
    await reviewer.page.getByTestId('held-reject-reason').fill(REASON);
    await reviewer.page.getByTestId('held-confirm-reject').click();
    await expect(reviewer.page.getByTestId('held-detail-status')).toHaveText('Rejected', { timeout: 20_000 });
    await shot(reviewer.page, '09-reviewer-rejected');

    await expect(card).toHaveAttribute('data-status', 'rejected', { timeout: 90_000 });
    await expect(card.getByTestId('held-notice-reason')).toContainText(REASON);
    await expect(member.page.getByText(`${TOKEN}-5678`)).toHaveCount(0);
    await shot(member.page, '10-member-rejected');
  } finally {
    await member.ctx.close();
    await reviewer.ctx.close();
  }
});

test('Held reply: the member never sees a reply the policy holds, only the waiting card', async ({ page, browser }) => {
  test.setTimeout(10 * 60_000);
  await expectHoldPolicyLive(page);
  const member = await as(browser, state.member!);
  const reviewer = await as(browser, state.reviewer!);
  try {
    // the question does not match the pattern, the reply it asks for does
    const ask = `Reply with only these two parts joined by a hyphen and nothing else: ${TOKEN} and 9999`;
    await go(member.page, '/chat');
    // watch every change to the page for the reply text from before the message is sent
    await member.page.evaluate((needle) => {
      const w = window as unknown as { __sawHeld: boolean; __sawChecking: boolean };
      w.__sawHeld = false;
      w.__sawChecking = false;
      const look = () => {
        const t = document.body.innerText;
        if (t.includes(needle)) w.__sawHeld = true;
        if (t.includes('Checking the reply')) w.__sawChecking = true;
      };
      new MutationObserver(look).observe(document.body, { subtree: true, childList: true, characterData: true });
    }, `${TOKEN}-9999`);
    await memberSends(member.page, ask, false);
    const card = member.page.getByTestId('held-notice').filter({ hasText: 'The reply' }).last();
    await expect(card).toHaveAttribute('data-status', 'pending', { timeout: 300_000 });
    await expect(card).toContainText('The reply is waiting for review');
    await shot(member.page, '10a-member-reply-held');
    const seen = await member.page.evaluate(() => {
      const w = window as unknown as { __sawHeld: boolean; __sawChecking: boolean };
      return { held: w.__sawHeld, checking: w.__sawChecking };
    });
    expect(seen.held, 'the held reply text reached the member page').toBe(false);
    expect(seen.checking, 'the member saw the checking state while the reply was withheld').toBe(true);

    // the stored thread has the card too, never the reply
    await member.page.reload({ waitUntil: 'domcontentloaded' });
    await expect(member.page.getByTestId('held-notice').filter({ hasText: 'The reply' }).last()).toBeVisible({ timeout: 60_000 });
    await expect(member.page.getByText(`${TOKEN}-9999`)).toHaveCount(0);

    // the reviewer sees it as an agent reply and rejects it
    await openHeld(reviewer.page, state.member!.name, /Agent reply/, await heldReviewId(member.page, 'post_llm'));
    await expect(reviewer.page.getByTestId('held-detail')).toContainText('Agent reply');
    await reviewer.page.getByTestId('held-reject').click();
    await reviewer.page.getByTestId('held-reject-reason').fill(REASON);
    await reviewer.page.getByTestId('held-confirm-reject').click();
    await expect(reviewer.page.getByTestId('held-detail-status')).toHaveText('Rejected', { timeout: 20_000 });
    const after = member.page.getByTestId('held-notice').filter({ hasText: 'The reply' }).last();
    await expect(after).toHaveAttribute('data-status', 'rejected', { timeout: 90_000 });
    await expect(member.page.getByText(`${TOKEN}-9999`)).toHaveCount(0);
    await shot(member.page, '10b-member-reply-rejected');
  } finally {
    await member.ctx.close();
    await reviewer.ctx.close();
  }
});

test('Retention: the card validates, saves with an audit line, and previews are masked', async ({ page }) => {
  test.setTimeout(4 * 60_000);
  const before = (await api(page, 'GET', '/api/moderation/retention')).json?.data;
  state.retention = {
    held_content_days: before.held_content_days,
    decision_record_days: before.decision_record_days,
    event_preview_days: before.event_preview_days,
  };
  save();

  await go(page, '/moderation');
  const card = page.getByTestId('retention-card');
  await expect(card).toContainText('What we keep and for how long');
  await expect(page.getByTestId('retention-save')).toBeDisabled();

  await page.getByTestId('retention-event_preview_days').fill('0');
  await expect(page.getByTestId('retention-event_preview_days-error')).toHaveText('Between 1 and 365 days.');
  await expect(page.getByTestId('retention-save')).toBeDisabled();
  await page.getByTestId('retention-held_content_days').fill('400');
  await expect(page.getByTestId('retention-held_content_days-error')).toBeVisible();

  const next = before.event_preview_days === 14 ? 21 : 14;
  await page.getByTestId('retention-held_content_days').fill('7');
  await page.getByTestId('retention-event_preview_days').fill(String(next));
  await page.getByTestId('retention-save').click();
  await expect(page.getByTestId('retention-saved')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('retention-audit')).toContainText('Last changed by');
  await shot(page, '11-retention-saved');

  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('retention-event_preview_days')).toHaveValue(String(next), { timeout: 20_000 });
  await expect(page.getByTestId('retention-held_content_days')).toHaveValue('7');
  const saved = (await api(page, 'GET', '/api/moderation/retention')).json?.data;
  expect(saved.event_preview_days).toBe(next);

  // the held events are listed with the token masked
  const events = page.getByTestId('events-list');
  await expect(events).toBeVisible({ timeout: 20_000 });
  const held = events.locator('[data-testid^="event-row-"]').filter({ hasText: 'held' }).filter({ hasText: 'Please process ticket' });
  await expect(held.first()).toBeVisible();
  await expect(held.first()).toContainText('█████');
  await expect(events).not.toContainText(`${TOKEN}-1234`);
  await expect(events).not.toContainText(`${TOKEN}-5678`);
  const raw = (await api(page, 'GET', '/api/moderation/events?outcome=held&limit=50')).json?.data || [];
  expect(raw.length).toBeGreaterThan(0);
  for (const e of raw) expect(String(e.content_preview || '')).not.toContain(TOKEN);
  await shot(page, '12-events-masked');

  // phone width: no sideways scroll on the inbox or the moderation page
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ['/review-queue?tab=held', '/moderation']) {
    await go(page, route);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${route} scrolls sideways at 390px`).toBeLessThanOrEqual(1);
    if (route.includes('review')) {
      // the tab asked for in the link is the one open, also on a phone
      await expect(page.getByTestId('review-tab-held')).toHaveAttribute('aria-selected', 'true');
      await expect(page.getByTestId('held-inbox')).toBeVisible();
    }
    await shot(page, `13-phone-${route.includes('review') ? 'inbox' : 'moderation'}`);
  }
});
