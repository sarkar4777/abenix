/**
 * Notification delivery from the screens only: the workspace Slack channel is the dev webhook
 * catcher, email lands in Mailpit.
 *
 *   1. Channels       the admin connects the Slack channel (a private address is refused first),
 *                     sends a test post, and keeps email copies on
 *   2. Teammate       an invite is emailed, the teammate joins from the link in the email
 *   3. Failed run     a run the moderation policy stops reaches Slack and email as a failure,
 *                     with a link back to the agent
 *   4. Approval       a high risk decision is proposed, the teammate is asked to sign off in Slack
 *                     and by email, and the email link opens the Approvals page
 *   5. Harm flag      the teammate flags harm on one of the admin's autonomous actions, the admin
 *                     hears about it in Slack and by email
 *   6. Preferences    Run failed turned off stops every copy, email turned off stops only email
 *   7. Screens        the notifications page at 1440 and 390 wide
 *
 * The API is only used to read state back and to put the admin's settings back afterwards.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_notifications_delivery_ui.spec.ts --workers=1
 */
import { test, expect, type Browser, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { caught, firstLink, mailsTo, waitForMail, waitForPost } from './uat_helpers/catchers';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const HOOK_PATH = `/hooks/notif-${RUN}`;
const HOOK = `http://abenix-webhook-catcher:8080${HOOK_PATH}`;
const MATE = { name: `Morgan Mate ${RUN}`, email: `mate-${RUN}@example.com`, password: `Mate-${RUN}-pw` };
const AGENT = `Notify probe ${RUN}`;
const DECISION = `uat.notify.${RUN}`;
const PII = 'Please file this. My SSN is 123-45-6789.';
const SHOTS = path.join(__dirname, 'uat_notifications_delivery_ui', 'shots');

const state: { agentId?: string; before?: any; slackWasSet?: boolean; mateId?: string; grantId?: string } = {};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });
test.setTimeout(12 * 60_000);

// the route announcer is an empty alert on every page
function alertIn(page: Page) {
  return page.locator('[role="alert"]:not(#__next-route-announcer__)').first();
}

async function go(page: Page, route: string) {
  await page.goto(route.startsWith('http') ? route : `${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

async function signIn(page: Page, creds = ADMIN) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click();
  await page.locator('#auth-email').fill(creds.email);
  await page.locator('#auth-password').fill(creds.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function api(page: Page, method: string, p: string, body?: unknown) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const opts = { method, headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' }, data: body === undefined ? undefined : JSON.stringify(body) };
  const res = await page.request.fetch(`${API}${p}`, opts).catch(() => page.request.fetch(`${API}${p}`, opts));
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), data: json?.data ?? null };
}

async function newPage(browser: Browser, width = 1440) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 600 ? 844 : 900 } });
  return { ctx, page: await ctx.newPage() };
}

async function savePrefs(page: Page) {
  const save = page.getByTestId('notif-save');
  if (await save.isEnabled()) {
    await save.click();
    await expect(page.getByText('Preferences saved').first()).toBeVisible({ timeout: 15_000 });
  }
}

async function setSwitch(page: Page, id: string, on: boolean) {
  const sw = page.getByTestId(id);
  if ((await sw.getAttribute('aria-checked')) !== String(on)) await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', String(on));
}

// a run the default moderation policy stops before the model sees it
async function failARun(page: Page) {
  await go(page, `/agents/${state.agentId}/chat`);
  await expect(page.getByTestId('chat-input')).toBeEnabled({ timeout: 30_000 });
  await page.getByTestId('chat-input').fill(PII);
  await page.getByTestId('chat-send').click();
  await expect(page.locator('[data-testid="chat-message"][data-role="assistant"]').last()).toBeVisible({ timeout: 120_000 });
  await page.waitForTimeout(2_000);
}

function failedPost(c: { json: any }) {
  return typeof c.json?.text === 'string' && c.json.text.includes(`${AGENT} failed`);
}

test.beforeAll(async ({ browser }) => {
  const { ctx, page } = await newPage(browser);
  await signIn(page);
  state.before = (await api(page, 'GET', '/api/settings/notifications')).data;
  state.slackWasSet = !!(await api(page, 'GET', '/api/settings/tenant')).data?.slack_webhook_is_set;
  await ctx.close();
});

test('1. the admin connects Slack and keeps email copies on', async ({ page }) => {
  await signIn(page);
  await go(page, '/settings/notifications');
  const input = page.getByTestId('slack-webhook-input');
  // the production guard still refuses private addresses nobody named
  await input.fill('https://10.20.30.40/hooks/x');
  await page.getByTestId('slack-webhook-save').click();
  await expect(page.getByTestId('slack-webhook-error')).toContainText('private address');
  await input.fill('http://localhost:9999/hook');
  await page.getByTestId('slack-webhook-save').click();
  await expect(page.getByTestId('slack-webhook-error')).toContainText('https://');

  await input.fill(HOOK);
  await page.getByTestId('slack-webhook-save').click();
  await expect(page.getByTestId('slack-webhook-source')).toContainText('A Slack channel is connected', { timeout: 15_000 });
  await expect(input).toHaveValue(/abenix-webhook-catcher:8080\/…/);
  await page.getByTestId('slack-test-send').click();
  await expect(page.getByText('Sent. Check your Slack channel.')).toBeVisible({ timeout: 20_000 });
  const test1 = await waitForPost(page.request, HOOK_PATH, (c) => String(c.json?.text || '').includes('Abenix test notification'));
  expect(test1.headers?.['content-type'] || '').toContain('application/json');

  await page.reload();
  await setSwitch(page, 'pref-execution_failed', true);
  await setSwitch(page, 'pref-autonomy_updates', true);
  await expect(page.getByTestId('chan-slack')).toBeEnabled();
  await expect(page.getByTestId('chan-email')).toBeEnabled();
  await setSwitch(page, 'chan-slack', true);
  await setSwitch(page, 'chan-email', true);
  await savePrefs(page);
  await expect(page.locator('#chan-email-desc')).toContainText(ADMIN.email);
  await shot(page, '01-notifications-connected');
});

test('2. an emailed invite brings in a teammate', async ({ page, browser }) => {
  await signIn(page);
  await go(page, '/settings/team');
  await page.getByRole('button', { name: /Invite/ }).first().click();
  await page.getByPlaceholder(/email/i).first().fill(MATE.email);
  const role = page.locator('select').filter({ has: page.locator('option[value="creator"]') }).first();
  await role.selectOption('creator');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByTestId('invite-result')).toContainText(`Invite emailed to ${MATE.email}`, { timeout: 20_000 });
  await shot(page, '02-invite-emailed');

  const mail = await waitForMail(page.request, MATE.email, /invited you to/);
  expect(mail.text).toContain('as creator');
  const link = firstLink(mail.text, '/auth/accept-invite?token=');
  expect(link.startsWith(`${BASE}/auth/accept-invite`)).toBeTruthy();

  const { ctx, page: mate } = await newPage(browser);
  await go(mate, link);
  await expect(mate.getByTestId('accept-title')).toBeVisible();
  await mate.locator('#accept-full-name').fill(MATE.name);
  await mate.locator('#accept-password').fill(MATE.password);
  await mate.getByTestId('accept-submit').click();
  await mate.waitForURL(/\/dashboard/, { timeout: 30_000 });
  const me = await api(mate, 'GET', '/api/auth/me');
  expect(me.data.user.role).toBe('creator');
  state.mateId = me.data.user.id;
  await ctx.close();
});

test('3. a failed run reaches Slack and email with a link back', async ({ page }) => {
  await signIn(page);
  // a small agent of our own, built in the builder
  await go(page, '/builder');
  await page.getByTestId('builder-name-button').click({ timeout: 30_000 });
  await page.getByTestId('builder-name-input').fill(AGENT);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill('You file short notes for the team. Reply in one sentence.');
  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  state.agentId = new URL(page.url()).searchParams.get('agent') || undefined;
  expect(state.agentId).toBeTruthy();

  const mailsBefore = (await mailsTo(page.request, ADMIN.email)).map((m) => m.ID);
  await failARun(page);
  await shot(page, '03-run-stopped');

  const post = await waitForPost(page.request, HOOK_PATH, failedPost, 90_000);
  expect(post.json.text).toContain(`*Abenix — ${AGENT} failed*`);
  expect(post.json.text).toContain(`<${BASE}/agents/${state.agentId}/chat|Open in Abenix>`);
  expect(post.json.attachments?.[0]?.actions?.[0]?.url).toBe(`${BASE}/agents/${state.agentId}/chat`);

  const mail = await waitForMail(page.request, ADMIN.email, new RegExp(`Abenix: ${AGENT} failed`), { after: mailsBefore });
  expect(mail.text).toContain(`Open it in Abenix: ${BASE}/agents/${state.agentId}/chat`);
  expect(mail.text).toContain(`${BASE}/settings/notifications`);
  await go(page, firstLink(mail.text, `/agents/${state.agentId}/chat`));
  await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 30_000 });

  const bell = await api(page, 'GET', '/api/notifications?limit=10');
  const items = Array.isArray(bell.data) ? bell.data : bell.data?.items || [];
  expect(items.some((n: any) => n.type === 'execution_failed' && n.title === `${AGENT} failed`)).toBeTruthy();
});

test('4. a high risk decision asks the teammate to sign off in Slack and by email', async ({ page, browser }) => {
  await signIn(page);
  await go(page, '/decisions');
  await page.getByTestId('decision-new').or(page.getByTestId('decision-start-blank')).first().click();
  await page.getByTestId('decision-name').fill(`Notify surcharge ${RUN}`);
  await page.getByTestId('decision-key').fill(DECISION);
  await page.getByTestId('decision-create').click();
  await expect(page.getByTestId('lifecycle-bar')).toContainText('Propose', { timeout: 30_000 });

  await page.getByTestId('import-open').click();
  await page.getByTestId('import-json').fill(JSON.stringify({
    ruleKey: 'notify.heavy.parcel',
    requiresFacts: ['shipment.weightKg'],
    when: { all: [{ gt: [{ fact: 'shipment.weightKg' }, 50] }] },
    then: { surcharge: 'HEAVY' },
    provenance: { citations: ['Tariff 2026, section 1'] },
  }));
  await page.getByTestId('import-go').click();
  await expect(page.getByTestId('rule-card-0')).toContainText('notify.heavy.parcel', { timeout: 15_000 });
  await expect(page.getByTestId('save-state')).toHaveText(/All changes saved/, { timeout: 15_000 });

  const panel = page.getByTestId('try-panel');
  await panel.getByRole('button', { name: /JSON/ }).click();
  await page.getByTestId('try-json').fill(JSON.stringify({ shipment: { weightKg: 80 } }));
  await expect(panel.getByTestId('try-result-value')).toContainText('HEAVY', { timeout: 15_000 });
  await page.getByTestId('try-test-name').fill('Heavy parcel');
  await page.getByTestId('try-save-test').click();
  await expect(panel).toContainText('Saved as a golden test');

  // the tier picker next to the title
  const tier = page.locator('select').filter({ has: page.locator('option[value="high"]') }).first();
  await tier.selectOption('high');
  await expect(tier).toHaveValue('high');
  await page.waitForTimeout(1_500);
  await page.getByTestId('check').click();
  await page.getByTestId('propose').click();
  await expect(page.getByTestId('workspace-notice')).toContainText(/sign-off/i, { timeout: 20_000 });
  await shot(page, '04-decision-sent-for-signoff');

  const title = `Publish Notify surcharge ${RUN} version 1`;
  const post = await waitForPost(page.request, HOOK_PATH, (c) => String(c.json?.text || '').includes(title));
  expect(post.json.text).toContain(`<${BASE}/approvals|Open in Abenix>`);
  // one post for the channel, not one per member
  await page.waitForTimeout(3_000);
  expect((await caught(page.request, HOOK_PATH)).filter((c) => String(c.json?.text || '').includes(title))).toHaveLength(1);

  const mail = await waitForMail(page.request, MATE.email, new RegExp(`Abenix: Publish Notify surcharge ${RUN}`));
  expect(mail.text).toContain('requested approval');
  const { ctx, page: mate } = await newPage(browser);
  await signIn(mate, MATE);
  await go(mate, firstLink(mail.text, '/approvals'));
  await expect(mate.getByText(title).first()).toBeVisible({ timeout: 30_000 });
  await shot(mate, '05-mate-approvals');
  await ctx.close();
});

test('5. a harm flag from the teammate reaches the admin', async ({ page, browser }) => {
  await signIn(page);
  // the admin's grant with an executed action nobody flagged yet
  const ov = await api(page, 'GET', '/api/autonomy/overview');
  for (const g of ov.data?.grants || []) {
    const acts = await api(page, 'GET', `/api/autonomy/grants/${g.id}/actions?status=executed&limit=100`);
    if ((acts.data?.items || []).some((a: any) => !a.harm)) { state.grantId = g.id; break; }
  }
  test.skip(!state.grantId, 'no executed autonomous action to flag on this cluster, run uat_autonomy_ui first');
  const mailsBefore = (await mailsTo(page.request, ADMIN.email)).map((m) => m.ID);

  const { ctx, page: mate } = await newPage(browser);
  await signIn(mate, MATE);
  await go(mate, `/autonomy/${state.grantId}`);
  await expect(mate.getByTestId('autonomy-grant-page')).toBeVisible({ timeout: 30_000 });
  const done = mate.locator('[data-testid="action-card"][data-status="executed"]').filter({ has: mate.getByTestId('action-card-flag-harm') }).first();
  await expect(done).toBeVisible({ timeout: 30_000 });
  await done.getByTestId('action-card-flag-harm').click();
  await done.getByTestId('action-card-harm-note').fill(`Valve left open overnight (${RUN})`);
  await done.getByTestId('action-card-harm-confirm').click();
  await expect(mate.getByTestId('action-card-harm').first()).toBeVisible({ timeout: 20_000 });
  await ctx.close();

  const post = await waitForPost(page.request, HOOK_PATH, (c) => String(c.json?.text || '').includes(`Valve left open overnight (${RUN})`));
  expect(post.json.text).toMatch(/Harm flagged|moved down/);
  expect(post.json.text).toContain(`<${BASE}/autonomy/${state.grantId}|Open in Abenix>`);
  const mail = await waitForMail(page.request, ADMIN.email, /Harm flagged|moved down/, { after: mailsBefore });
  expect(mail.text).toContain(`Valve left open overnight (${RUN})`);
  expect(mail.text).toContain(`${BASE}/autonomy/${state.grantId}`);
});

test('6. turning a preference off stops delivery', async ({ page }) => {
  await signIn(page);
  await go(page, '/settings/notifications');
  await setSwitch(page, 'pref-execution_failed', false);
  await savePrefs(page);
  const mailsBefore = (await mailsTo(page.request, ADMIN.email)).map((m) => m.ID);
  const postsBefore = (await caught(page.request, HOOK_PATH)).filter(failedPost).length;
  await failARun(page);
  await page.waitForTimeout(15_000);
  expect((await caught(page.request, HOOK_PATH)).filter(failedPost).length).toBe(postsBefore);
  expect((await mailsTo(page.request, ADMIN.email)).filter((m) => !mailsBefore.includes(m.ID) && m.Subject.includes(`${AGENT} failed`))).toHaveLength(0);

  // email off, Slack on: only the channel hears about it
  await go(page, '/settings/notifications');
  await setSwitch(page, 'pref-execution_failed', true);
  await setSwitch(page, 'chan-email', false);
  await savePrefs(page);
  await failARun(page);
  await expect.poll(async () => (await caught(page.request, HOOK_PATH)).filter(failedPost).length, { timeout: 60_000 }).toBe(postsBefore + 1);
  await page.waitForTimeout(5_000);
  expect((await mailsTo(page.request, ADMIN.email)).filter((m) => !mailsBefore.includes(m.ID) && m.Subject.includes(`${AGENT} failed`))).toHaveLength(0);
});

for (const width of [1440, 390]) {
  test(`7. notifications page at ${width} wide`, async ({ browser }) => {
    const { ctx, page } = await newPage(browser, width);
    await signIn(page);
    await go(page, '/settings/notifications');
    await expect(page.getByTestId('slack-webhook-section')).toBeVisible();
    await shot(page, `w${width}-notifications`);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(over).toBeLessThanOrEqual(1);
    await ctx.close();
  });
}

test.afterAll(async ({ browser }) => {
  const { ctx, page } = await newPage(browser);
  await signIn(page);
  if (state.before) {
    const { delivery: _d, ...prefs } = state.before;
    await api(page, 'PUT', '/api/settings/notifications', prefs);
  }
  if (!state.slackWasSet) await api(page, 'PUT', '/api/settings/tenant', { slack_webhook_url: '' });
  await api(page, 'DELETE', `/api/decisions/${DECISION}`);
  if (state.agentId) await api(page, 'DELETE', `/api/agents/${state.agentId}`);
  if (state.mateId) await api(page, 'DELETE', `/api/team/members/${state.mateId}`);
  await ctx.close();
});
