/**
 * Free marketplace with monetization off, from the screens only.
 *
 *   1. Admin turns the marketplace on and monetization off on Admin > Marketplace & Billing
 *   2. Admin invites a creator and a member from Settings > Team, both accept
 *   3. The creator builds an agent and lists it for free from Creator Hub
 *   4. Admin approves it in the review inbox
 *   5. The member finds it in the store and installs it, Creator Hub counts the install
 *   6. Admin turns the marketplace off and it disappears everywhere, then the switches go back
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_marketplace_ui.spec.ts --workers=1
 */
import { test, expect, type Browser, type Page } from '@playwright/test';
import { showAllTools, sidebarToggle } from './helpers/sidebar';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const CREATOR = { email: `mkt-creator-${RUN}@example.com`, name: `Creator ${RUN}`, password: 'MarketPass123!' };
const MEMBER = { email: `mkt-member-${RUN}@example.com`, name: `Member ${RUN}`, password: 'MarketPass123!' };
const AGENT = `Free helper ${RUN}`;

const SHOTS = path.join(__dirname, 'uat_marketplace_ui', 'shots');

const state: { agentId?: string; before?: { marketplace: boolean; monetization: boolean }; members: string[] } = {
  members: [],
};

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

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

async function asUser(browser: Browser, who: { email: string; password: string }) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  p.on('dialog', (d) => d.accept());
  await signIn(p, who);
  return { ctx, p };
}

// set a switch from the admin page, confirming when it turns something off
async function setSwitch(page: Page, which: 'marketplace' | 'monetization', on: boolean) {
  await go(page, '/admin/marketplace');
  const sw = page.getByTestId(`switch-${which}`);
  await expect(sw).toBeVisible({ timeout: 20_000 });
  if ((await sw.getAttribute('aria-checked')) === String(on)) return;
  await sw.click();
  if (!on) {
    await page.getByTestId('confirm-turn-off').click();
    await expect(page.getByTestId('confirm-turn-off')).toHaveCount(0, { timeout: 20_000 });
  }
  await expect(sw).toHaveAttribute('aria-checked', String(on), { timeout: 20_000 });
  await expect(page.getByTestId(`state-${which}`)).toHaveText(on ? 'On' : 'Off');
}

async function invite(page: Page, browser: Browser, who: typeof CREATOR, role: 'Creator' | 'Member') {
  await go(page, '/settings/team');
  await page.getByRole('button', { name: 'Invite Member' }).click();
  await page.getByTestId('invite-email').fill(who.email);
  await page.getByTestId('invite-role').selectOption({ label: role });
  await page.getByTestId('invite-send').click();
  const link = (await page.getByTestId('invite-link').innerText({ timeout: 20_000 })).trim();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  await p.goto(link, { waitUntil: 'domcontentloaded' });
  await expect(p.getByTestId('accept-title')).toBeVisible({ timeout: 30_000 });
  await p.locator('#accept-full-name').fill(who.name);
  await p.locator('#accept-password').fill(who.password);
  await p.getByTestId('accept-submit').click();
  await p.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await ctx.close();
  const members = (await api(page, 'GET', '/api/team/members')).json?.data?.members || [];
  const id = members.find((m: any) => m.email === who.email)?.id;
  if (id) state.members.push(id);
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test('Admin: marketplace on, monetization off, no billing anywhere', async ({ page }) => {
  const now = (await api(page, 'GET', '/api/platform/features')).json?.data;
  state.before = { marketplace: !!now?.marketplace, monetization: !!now?.monetization };

  await go(page, '/admin/marketplace');
  await expect(page.getByRole('heading', { name: 'Marketplace & Billing' })).toBeVisible();
  await setSwitch(page, 'marketplace', true);
  await setSwitch(page, 'monetization', false);
  await shot(page, '01-admin-switches');

  const read = (await api(page, 'GET', '/api/platform/features')).json.data;
  expect(read.marketplace).toBe(true);
  expect(read.monetization).toBe(false);

  // the store is in the sidebar's full list, Billing is gone from settings and the user menu
  await go(page, '/dashboard');
  await showAllTools(page);
  await expect(page.locator('aside a[href="/marketplace"]')).toHaveCount(1, { timeout: 20_000 });
  // the full list is remembered after a reload
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(sidebarToggle(page)).toHaveAttribute('data-mode', 'all', { timeout: 20_000 });
  await expect(page.locator('aside a[href="/marketplace"]')).toHaveCount(1, { timeout: 20_000 });
  await go(page, '/settings/profile');
  await expect(page.locator('a[href="/settings/billing"]')).toHaveCount(0);
  await go(page, '/settings/billing');
  await expect(page.getByTestId('billing-off')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('billing-off')).toContainText('Monetization is turned off');

  // the API refuses monetized routes in plain words
  const plans = await api(page, 'GET', '/api/billing/plans');
  expect(plans.status).toBe(404);
  expect(plans.json.error.message).toBe('Monetization is turned off on this deployment.');
});

test('A creator lists an agent for free, admin approves, a member installs it', async ({ page, browser }) => {
  test.setTimeout(8 * 60_000);
  await invite(page, browser, CREATOR, 'Creator');
  await invite(page, browser, MEMBER, 'Member');

  // the creator builds an agent
  const { ctx: cctx, p: creator } = await asUser(browser, CREATOR);
  try {
    await go(creator, '/creator');
    await expect(creator.getByTestId('creator-hub')).toBeVisible({ timeout: 20_000 });
    await expect(creator.getByTestId('creator-revenue')).toHaveCount(0);
    await expect(creator.getByText('Connect with Stripe')).toHaveCount(0);

    await go(creator, '/builder');
    await creator.getByTestId('builder-name-button').click();
    await creator.getByTestId('builder-name-input').fill(AGENT);
    await creator.getByTestId('builder-name-input').press('Enter');
    await creator.getByTestId('config-tab-general').click();
    await creator.getByTestId('builder-description').fill('Turns a messy note into three tidy bullet points.');
    await creator.getByTestId('config-tab-prompt').click();
    await creator.getByTestId('builder-system-prompt').fill('Rewrite what the user sends as three short bullet points.');
    await creator.getByTestId('builder-save-draft').click();
    await creator.waitForURL(/[?&]agent=/, { timeout: 30_000 });
    state.agentId = new URL(creator.url()).searchParams.get('agent') || '';
    expect(state.agentId).toBeTruthy();

    // list it from Creator Hub
    await go(creator, '/creator');
    const form = creator.getByTestId('creator-list-form');
    await expect(form).toBeVisible({ timeout: 20_000 });
    await expect(form).toContainText('Listing costs nothing');
    await expect(form).toContainText('Installing is free too');
    await creator.getByTestId('creator-list-agent').selectOption({ label: AGENT });
    await creator.getByTestId('creator-list-category').selectOption('productivity');
    await creator.getByTestId('creator-list-submit').click();
    const row = creator.locator(`[data-testid="creator-listing"][data-name="${AGENT}"]`);
    await expect(row).toHaveAttribute('data-state', 'pending', { timeout: 20_000 });
    await expect(row).toContainText('Waiting for review');
    await expect(creator.getByTestId('creator-list-error')).toHaveCount(0);
    await shot(creator, '02-creator-pending');
  } finally {
    await cctx.close();
  }

  const pending = (await api(page, 'GET', `/api/agents/${state.agentId}`)).json?.data;
  expect(pending.status).toBe('pending_review');

  // admin approves it in the review inbox
  await go(page, '/review-queue');
  await page.getByTestId('review-tab-marketplace').click();
  const panel = page.getByTestId('marketplace-submissions');
  await expect(panel).toBeVisible({ timeout: 30_000 });
  const approve = page.getByRole('button', { name: 'Approve', exact: true });
  const card = panel.locator('div').filter({ hasText: AGENT }).filter({ has: approve }).last();
  await expect(card).toBeVisible({ timeout: 30_000 });
  await shot(page, '03-review-inbox');
  await card.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect.poll(async () => (await api(page, 'GET', `/api/agents/${state.agentId}`)).json?.data?.status, {
    timeout: 30_000,
  }).toBe('active');

  // the member finds it in the store and installs it
  const { ctx: mctx, p: member } = await asUser(browser, MEMBER);
  try {
    await go(member, '/marketplace');
    await member.getByTestId('marketplace-search').fill(AGENT);
    const tile = member.getByTestId('market-card').filter({ hasText: AGENT });
    await expect(tile).toBeVisible({ timeout: 30_000 });
    await expect(tile).toContainText('Free');
    await expect(member.getByText(/\$\d+(\.\d+)?\/mo/)).toHaveCount(0);
    // a member cannot list, so the store does not offer it
    await expect(member.getByTestId('marketplace-list-agent')).toHaveCount(0);
    await shot(member, '04-store');
    await member.setViewportSize({ width: 390, height: 844 });
    await go(member, '/marketplace');
    await expect(member.getByTestId('market-card').first()).toBeVisible({ timeout: 20_000 });
    await noSideScroll(member);
    await shot(member, '04b-store-390');
    await member.setViewportSize({ width: 1440, height: 900 });
    // the reload cleared the search, find it again
    await member.getByTestId('marketplace-search').fill(AGENT);
    await expect(tile).toBeVisible({ timeout: 30_000 });
    await tile.click();
    await member.waitForURL(/\/marketplace\/[0-9a-f-]+/, { timeout: 20_000 });
    await member.getByTestId('market-install').click();
    await expect(member.getByTestId('market-open-chat')).toBeVisible({ timeout: 20_000 });
    await expect(member.getByTestId('market-install-error')).toHaveCount(0);
    await expect(member.getByText('1 install', { exact: true })).toBeVisible({ timeout: 20_000 });
    await shot(member, '05-installed');
    await member.getByTestId('market-open-chat').click();
    await member.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
    await expect(member.getByTestId('chat-input')).toBeVisible({ timeout: 30_000 });
  } finally {
    await mctx.close();
  }

  // Creator Hub counts the install
  const { ctx: c2, p: creator2 } = await asUser(browser, CREATOR);
  try {
    await go(creator2, '/creator');
    const live = creator2.locator(`[data-testid="creator-listing"][data-name="${AGENT}"]`);
    await expect(live).toHaveAttribute('data-state', 'live', { timeout: 20_000 });
    await expect(live.getByTestId('listing-installs')).toHaveText('1 install');
    const listings = (await api(creator2, 'GET', '/api/creator/listings')).json.data;
    const mine = listings.listings.find((l: any) => l.id === state.agentId);
    expect(mine.installs).toBe(1);
    expect(mine.price).toBeUndefined();
    await shot(creator2, '06-creator-live');
    await creator2.setViewportSize({ width: 390, height: 844 });
    await go(creator2, '/creator');
    await expect(live).toBeVisible({ timeout: 20_000 });
    await noSideScroll(creator2);
    await shot(creator2, '06b-creator-390');
  } finally {
    await c2.close();
  }
});

test('Turning the marketplace off hides it everywhere', async ({ page, browser }) => {
  await setSwitch(page, 'marketplace', false);
  await shot(page, '07-marketplace-off');

  await go(page, '/dashboard');
  await showAllTools(page);
  await expect(page.locator('aside a[href="/dashboard"]')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('aside a[href="/marketplace"]')).toHaveCount(0);
  await expect(page.locator('aside a[href="/creator"]')).toHaveCount(0);

  await go(page, '/marketplace');
  await expect(page.getByTestId('marketplace-page-off')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('market-card')).toHaveCount(0);
  await go(page, '/agents');
  await expect(page.getByRole('button', { name: 'Marketplace', exact: true })).toHaveCount(0);

  const browse = await api(page, 'GET', '/api/marketplace');
  expect(browse.status).toBe(404);
  expect(browse.json.error.message).toBe('The marketplace is turned off on this deployment.');

  // the creator sees it gone too, with no dead link
  const { ctx, p: creator } = await asUser(browser, CREATOR);
  try {
    await showAllTools(creator);
    await expect(creator.locator('aside a[href="/creator"]')).toHaveCount(0, { timeout: 20_000 });
    await go(creator, '/creator');
    await expect(creator.getByTestId('creator-off')).toBeVisible({ timeout: 20_000 });
    await expect(creator.getByTestId('marketplace-off')).toContainText('An admin can turn it on');
  } finally {
    await ctx.close();
  }

  // phone width keeps the admin page usable
  await page.setViewportSize({ width: 390, height: 844 });
  await go(page, '/admin/marketplace');
  await expect(page.getByTestId('switch-marketplace')).toBeVisible({ timeout: 20_000 });
  await noSideScroll(page);
  await shot(page, '08-admin-390');
});

test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await signIn(page);
  if (state.before) await api(page, 'PUT', '/api/admin/platform-features', state.before);
  if (state.agentId) await api(page, 'DELETE', `/api/agents/${state.agentId}?force=true`);
  for (const id of state.members) await api(page, 'DELETE', `/api/team/members/${id}`);
  await ctx.close();
});
