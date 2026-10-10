/**
 * Account and security from the screens only, on a brand new workspace.
 *
 *   1. Sign up             a new account lands on the dashboard as the workspace admin
 *   2. Forgot password     the reset email reaches Mailpit, the link works once, the new password signs in
 *   3. Change password     on Profile, the old password stops working, the new one works
 *   4. Devices             a second browser shows up under Security, signing it out kills its token
 *   5. Sign out            the token the browser held is dead afterwards
 *   6. Two-step sign-in    enrol with a code made here, sign in with a code, a recovery code works once
 *   7. SSO                 the admin points the workspace at the mock OIDC provider, a new person signs in
 *                          through it and joins this workspace with the chosen role
 *   9. Privacy             the data export downloads and holds the account's data
 *  10. Quotas              limits are validated, saved and shown, a member can only read them
 *  11. Sandbox             image names are checked, images added and removed, overrides cleared
 *  12. DLP                 mask, block and detect on a real agent run
 *  13. Billing             monetization off is explained, not a dead end
 *  14. Screens             each screen at 1440 and 390 wide
 *
 * The API is only used to read state back.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_account_security_ui.spec.ts --workers=1
 */
import { test, expect, type Browser, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { firstLink, freshTotp, totpStep, waitForMail } from './uat_helpers/catchers';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const RUN = Date.now().toString(36);
const SHOTS = path.join(__dirname, 'uat_account_security_ui', 'shots');
const OWNER = { name: `Avery Account ${RUN}`, email: `acct-${RUN}@example.com` };
const PW = { first: `First-${RUN}-pw`, reset: `Reset-${RUN}-pw`, changed: `Changed-${RUN}-pw` };
const SSO_DOMAIN = `sso-${RUN}.dev`;
const ISSUER = process.env.MOCK_OIDC_ISSUER || 'http://localhost:8090/default';

const state: { password: string; tenantId?: string; secret?: string; lastStep: number | null; recovery: string[] } = {
  password: PW.first,
  lastStep: null,
  recovery: [],
};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });
test.setTimeout(10 * 60_000);

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

async function token(page: Page) {
  // the dashboard can still be settling right after a redirect
  for (let i = 0; ; i++) {
    try {
      await page.waitForLoadState('domcontentloaded');
      return await page.evaluate(() => localStorage.getItem('access_token') || '');
    } catch (e) {
      if (i >= 4) throw e;
      await page.waitForTimeout(500);
    }
  }
}

async function me(page: Page, tok?: string) {
  const t = tok ?? (await token(page));
  const r = await page.request.get(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${t}` } });
  let body: any = null;
  try { body = await r.json(); } catch {}
  return { status: r.status(), user: body?.data?.user };
}

async function openSignIn(page: Page) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click();
}

async function passwordStep(page: Page, email: string, password: string) {
  await openSignIn(page);
  await page.locator('#auth-email').fill(email);
  await page.locator('#auth-password').fill(password);
  await page.getByTestId('auth-submit').click();
}

async function signIn(page: Page, email = OWNER.email, password = state.password) {
  await passwordStep(page, email, password);
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Log out' }).first().click();
  await page.waitForURL((u) => u.pathname === '/', { timeout: 20_000 });
}

async function newPage(browser: Browser, width = 1440) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 600 ? 844 : 900 } });
  return { ctx, page: await ctx.newPage() };
}

test('1. sign up creates a workspace and its admin', async ({ page }) => {
  await go(page, '/');
  await page.getByRole('button', { name: 'Switch to register' }).click();
  await page.locator('#auth-full-name').fill(OWNER.name);
  await page.locator('#auth-email').fill(OWNER.email);
  await page.locator('#auth-password').fill(PW.first);
  await shot(page, '01-sign-up');
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
  const who = await me(page);
  expect(who.status).toBe(200);
  expect(who.user.email).toBe(OWNER.email);
  expect(who.user.role).toBe('admin');
  state.tenantId = who.user.tenant_id;

  // signing up again with the same email says so plainly
  const { ctx, page: other } = await newPage(page.context().browser()!);
  await go(other, '/');
  await other.getByRole('button', { name: 'Switch to register' }).click();
  await other.locator('#auth-full-name').fill('Someone Else');
  await other.locator('#auth-email').fill(OWNER.email);
  await other.locator('#auth-password').fill('Another-pw-123');
  await other.getByTestId('auth-submit').click();
  await expect(alertIn(other)).toContainText('Email already registered');
  await ctx.close();
});

test('2. forgot password sends a working one-time link', async ({ page }) => {
  await signIn(page);
  await signOut(page);
  await page.locator('#auth-email').fill(OWNER.email);
  await page.getByTestId('auth-forgot-link').click();
  await page.waitForURL(/\/auth\/forgot/);
  await expect(page.locator('#forgot-email')).toHaveValue(OWNER.email);
  await shot(page, '02-forgot');
  await page.getByTestId('forgot-submit').click();
  await expect(page.getByTestId('forgot-sent')).toContainText(OWNER.email);
  await expect(page.getByTestId('forgot-sent')).not.toContainText('cannot send email');
  await shot(page, '03-forgot-sent');

  const mail = await waitForMail(page.request, OWNER.email, /Reset your Abenix password/);
  expect(mail.text).toContain('30 minutes');
  const link = firstLink(mail.text, '/auth/reset?token=');
  // the link points at the web the user actually uses
  expect(link.startsWith(`${BASE}/auth/reset?token=`)).toBeTruthy();
  await go(page, `http://localhost:8025/view/${mail.id}`);
  await shot(page, '04-mailpit-reset-email');

  await go(page, link);
  await expect(page.getByTestId('reset-title')).toBeVisible();
  await page.locator('#reset-password').fill('short');
  await expect(page.getByText('At least 8 characters')).toBeVisible();
  await page.locator('#reset-password').fill(PW.reset);
  await page.locator('#reset-confirm').fill(`${PW.reset}x`);
  await expect(page.getByText('The two passwords are not the same')).toBeVisible();
  await expect(page.getByTestId('reset-submit')).toBeDisabled();
  await page.locator('#reset-confirm').fill(PW.reset);
  await shot(page, '05-reset');
  await page.getByTestId('reset-submit').click();
  await page.waitForURL(/reset=done/);
  await expect(page.getByTestId('auth-notice')).toContainText('Your password was changed');
  await expect(page.locator('#auth-email')).toHaveValue(OWNER.email);
  state.password = PW.reset;

  // the old password is gone, the new one works
  await passwordStep(page, OWNER.email, PW.first);
  await expect(alertIn(page)).toContainText('Invalid email or password');
  await signIn(page);

  // the same link does not work twice
  const { ctx, page: again } = await newPage(page.context().browser()!);
  await go(again, link);
  await again.locator('#reset-password').fill('Yet-another-pw-1');
  await again.locator('#reset-confirm').fill('Yet-another-pw-1');
  await again.getByTestId('reset-submit').click();
  await expect(again.getByTestId('reset-link-broken')).toContainText('expired or was already used');
  await ctx.close();

  // an unknown email gets the same answer, nothing leaks
  await go(page, '/auth/forgot');
  await page.locator('#forgot-email').fill(`nobody-${RUN}@example.com`);
  await page.getByTestId('forgot-submit').click();
  await expect(page.getByTestId('forgot-sent')).toBeVisible();
});

test('3. change password on Profile', async ({ page }) => {
  await signIn(page);
  await go(page, '/settings/profile');
  await page.locator('#pw-current').fill('not-my-password');
  await page.locator('#pw-new').fill(PW.changed);
  await page.locator('#pw-confirm').fill(PW.changed);
  await page.getByRole('button', { name: /Update password/ }).click();
  await expect(page.getByTestId('pw-message')).toContainText('Current password is incorrect');

  await page.locator('#pw-current').fill(state.password);
  await page.locator('#pw-new').fill(PW.changed);
  await page.locator('#pw-confirm').fill(PW.changed);
  await page.getByRole('button', { name: /Update password/ }).click();
  await expect(page.getByTestId('pw-message')).toContainText('Password changed');
  await shot(page, '06-password-changed');
  const old = state.password;
  state.password = PW.changed;

  await signOut(page);
  await passwordStep(page, OWNER.email, old);
  await expect(alertIn(page)).toContainText('Invalid email or password');
  await signIn(page);
});

test('4. Security lists each device and signs one out', async ({ page, browser }) => {
  await signIn(page);
  const { ctx, page: phone } = await newPage(browser, 390);
  await signIn(phone);
  const phoneToken = await token(phone);
  expect((await me(phone)).status).toBe(200);

  await go(page, '/settings/security');
  const panel = page.getByTestId('sessions-panel');
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId('session-row').first()).toContainText('This device');
  await expect.poll(() => panel.getByTestId('session-row').count()).toBeGreaterThanOrEqual(2);
  await shot(page, '07-security-devices');

  const before = await panel.getByTestId('session-row').count();
  await panel.getByTestId('session-revoke').first().click();
  await expect(page.getByText('That device is signed out')).toBeVisible();
  await expect.poll(() => panel.getByTestId('session-row').count()).toBe(before - 1);

  // signed out right away, not when the token expires
  await expect.poll(async () => (await me(phone, phoneToken)).status).toBe(401);
  await go(phone, '/settings/security');
  await phone.waitForURL((u) => u.pathname === '/', { timeout: 30_000 });
  await ctx.close();

  // sign out everywhere else, this tab keeps working
  const { ctx: c2, page: laptop } = await newPage(browser);
  await signIn(laptop);
  const laptopToken = await token(laptop);
  await go(page, '/settings/security');
  await page.getByTestId('sessions-revoke-others').click();
  await expect(page.getByText('Every other device is signed out')).toBeVisible();
  await expect.poll(async () => (await me(laptop, laptopToken)).status).toBe(401);
  expect((await me(page)).status).toBe(200);
  await c2.close();
});

test('5. signing out kills the token the browser held', async ({ page }) => {
  await signIn(page);
  const access = await token(page);
  const refresh = await page.evaluate(() => localStorage.getItem('refresh_token') || '');
  expect((await me(page, access)).status).toBe(200);
  await signOut(page);
  expect(await token(page)).toBe('');
  expect((await me(page, access)).status).toBe(401);
  const r = await page.request.post(`${API}/api/auth/refresh`, { data: { refresh_token: refresh } });
  expect(r.status()).toBe(401);
});

test('6. two-step sign-in with an authenticator code', async ({ page }) => {
  await signIn(page);
  await go(page, '/settings/security');
  const panel = page.getByTestId('twofa-panel');
  await expect(panel.getByTestId('twofa-state')).toHaveText('Off');
  await expect(panel.getByTestId('twofa-start')).toBeDisabled();
  await panel.locator('#twofa-password').fill('wrong-password');
  await panel.getByTestId('twofa-start').click();
  await expect(panel.getByRole('alert')).toContainText('Your password is not right');
  await panel.locator('#twofa-password').fill(state.password);
  await panel.getByTestId('twofa-start').click();
  await expect(panel.getByTestId('twofa-setup')).toBeVisible();
  await expect(panel.getByRole('img', { name: /QR code/ })).toBeVisible();
  state.secret = (await panel.getByTestId('twofa-secret').innerText()).replace(/\s+/g, '');
  await shot(page, '08-twofa-setup');

  await panel.locator('#twofa-code').fill('000000');
  await panel.getByTestId('twofa-enable-confirm').click();
  await expect(panel.getByRole('alert')).toContainText('did not match');
  const { code, step } = await freshTotp(state.secret!, null);
  await panel.locator('#twofa-code').fill(code);
  await panel.getByTestId('twofa-enable-confirm').click();
  state.lastStep = step;
  await expect(panel.getByTestId('twofa-recovery')).toBeVisible();
  state.recovery = await panel.getByTestId('twofa-recovery-code').allInnerTexts();
  expect(state.recovery).toHaveLength(8);
  await shot(page, '09-twofa-recovery');
  await panel.getByTestId('twofa-recovery-done').click();
  await expect(panel.getByTestId('twofa-state')).toHaveText('On');

  // the password alone is no longer enough
  await signOut(page);
  await passwordStep(page, OWNER.email, state.password);
  await expect(page.getByTestId('auth-2fa-form')).toBeVisible();
  expect(await token(page)).toBe('');
  await shot(page, '10-twofa-signin');
  await page.locator('#auth-2fa-code').fill('123456');
  await page.getByTestId('auth-2fa-submit').click();
  await expect(alertIn(page)).toContainText('did not match');
  const next = await freshTotp(state.secret!, state.lastStep);
  await page.locator('#auth-2fa-code').fill(next.code);
  await page.getByTestId('auth-2fa-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
  state.lastStep = next.step;

  // a recovery code works once
  await signOut(page);
  await passwordStep(page, OWNER.email, state.password);
  await page.locator('#auth-2fa-code').fill(state.recovery[0]);
  await page.getByTestId('auth-2fa-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await signOut(page);
  await passwordStep(page, OWNER.email, state.password);
  await page.locator('#auth-2fa-code').fill(state.recovery[0]);
  await page.getByTestId('auth-2fa-submit').click();
  await expect(alertIn(page)).toContainText('did not match');

  // turn it off again from Security
  const again = await freshTotp(state.secret!, state.lastStep);
  await page.locator('#auth-2fa-code').fill(again.code);
  await page.getByTestId('auth-2fa-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
  state.lastStep = again.step;
  await go(page, '/settings/security');
  await page.getByTestId('twofa-disable').click();
  await page.locator('#twofa-off-password').fill(state.password);
  await page.locator('#twofa-off-code').fill(state.recovery[1]);
  await page.getByTestId('twofa-disable-confirm').click();
  await expect(page.getByTestId('twofa-state')).toHaveText('Off');
  expect(totpStep()).toBeGreaterThan(0);
});

test('7. single sign-on against the mock provider', async ({ page, browser }) => {
  await signIn(page);
  await go(page, '/settings/sso');
  await expect(page.getByTestId('sso-page')).toBeVisible();
  await expect(page.getByTestId('sso-status')).toHaveText('Not set up');
  await expect(page.getByTestId('sso-redirect-uri')).toContainText('/api/auth/sso/');
  // a private issuer that nobody mapped is refused
  await page.locator('#sso-issuer').fill('https://10.0.0.7/realm');
  await page.getByTestId('sso-test').click();
  await expect(page.getByTestId('sso-error')).toContainText(/private address|does not resolve/);

  await page.locator('#sso-issuer').fill(ISSUER);
  await page.locator('#sso-client-id').fill(`abenix-uat-${RUN}`);
  await page.locator('#sso-client-secret').fill('mock-secret');
  await page.locator('#sso-domains').fill(SSO_DOMAIN);
  await page.locator('#sso-role').selectOption('creator');
  await page.locator('#sso-label').fill('UAT mock login');
  await page.getByTestId('sso-test').click();
  await expect(page.getByTestId('sso-test-result')).toContainText('/default/authorize');
  await page.getByTestId('sso-save').click();
  await expect(page.getByTestId('sso-status')).toHaveText('On');
  await shot(page, '11-sso-settings');

  const { ctx, page: sso } = await newPage(browser);
  await openSignIn(sso);
  await sso.getByTestId('auth-sso-toggle').click();
  // a domain nobody set up gets a plain answer
  await sso.locator('#auth-sso-email').fill(`someone@nobody-${RUN}.dev`);
  await sso.getByTestId('auth-sso-submit').click();
  await expect(alertIn(sso)).toContainText('Use your password instead');
  const pat = `pat-${RUN}@${SSO_DOMAIN}`;
  await sso.locator('#auth-sso-email').fill(pat);
  await shot(sso, '12-sso-signin');
  await sso.getByTestId('auth-sso-submit').click();

  // the mock provider's own login form
  await sso.waitForURL(/localhost:8090\/default\/authorize/, { timeout: 30_000 });
  await sso.locator('input[name="username"]').fill(`pat-${RUN}`);
  await sso.locator('textarea[name="claims"]').fill(JSON.stringify({ email: pat, name: 'Pat Single' }));
  await shot(sso, '13-mock-provider');
  await sso.locator('input[type="submit"], button[type="submit"]').first().click();
  await sso.waitForURL(/\/dashboard/, { timeout: 45_000 });

  const who = await me(sso);
  expect(who.status).toBe(200);
  expect(who.user.email).toBe(pat);
  expect(who.user.full_name).toBe('Pat Single');
  expect(who.user.role).toBe('creator');
  expect(who.user.tenant_id).toBe(state.tenantId);
  const firstId = who.user.id;

  // Pat signs in through SSO again and is the same person
  await signOut(sso);
  await sso.getByTestId('auth-sso-toggle').click();
  await sso.locator('#auth-sso-email').fill(pat);
  await sso.getByTestId('auth-sso-submit').click();
  await sso.waitForURL(/localhost:8090\/default\/authorize/, { timeout: 30_000 });
  await sso.locator('input[name="username"]').fill(`pat-${RUN}`);
  await sso.locator('textarea[name="claims"]').fill(JSON.stringify({ email: pat, name: 'Pat Single' }));
  await sso.locator('input[type="submit"], button[type="submit"]').first().click();
  await sso.waitForURL(/\/dashboard/, { timeout: 45_000 });
  expect((await me(sso)).user.id).toBe(firstId);

  // the admin sees Pat on the team with the role SSO gave
  await go(page, '/settings/team');
  await expect(page.getByText(pat).first()).toBeVisible({ timeout: 20_000 });
  await go(page, '/settings/security');
  await expect(page.getByText(/Single sign-on saved/).first()).toBeVisible();
  await ctx.close();
});

async function ssoSignIn(page: Page, email: string, user: string) {
  await openSignIn(page);
  await page.getByTestId('auth-sso-toggle').click();
  await page.locator('#auth-sso-email').fill(email);
  await page.getByTestId('auth-sso-submit').click();
  await page.waitForURL(/localhost:8090\/default\/authorize/, { timeout: 30_000 });
  await page.locator('input[name="username"]').fill(user);
  await page.locator('textarea[name="claims"]').fill(JSON.stringify({ email, name: 'Pat Single' }));
  await page.locator('input[type="submit"], button[type="submit"]').first().click();
  await page.waitForURL(/\/dashboard/, { timeout: 45_000 });
}

test('9. privacy: the data export downloads and holds my data', async ({ page }) => {
  await signIn(page);
  await go(page, '/settings/privacy');
  await expect(page.getByTestId('privacy-retention')).toContainText('days');
  await expect(page.getByTestId('privacy-retention').getByRole('link', { name: /Data & DLP/ })).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('export-data').click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^abenix-data-export-\d{4}-\d{2}-\d{2}\.json$/);
  const file = await download.path();
  const data = JSON.parse(fs.readFileSync(file!, 'utf-8'));
  expect(data.format_version).toBe('1.1');
  expect(data.profile.email).toBe(OWNER.email);
  expect(data.profile.full_name).toBe(OWNER.name);
  for (const key of ['agents', 'executions', 'conversations', 'messages', 'api_keys', 'sessions', 'activity']) {
    expect(Array.isArray(data[key]), key).toBeTruthy();
  }
  expect(data.sessions.length).toBeGreaterThan(0);
  expect(data.activity.some((a: any) => a.action === 'password.changed')).toBeTruthy();
  expect(JSON.stringify(data)).not.toContain('password_hash');
  await expect(page.getByTestId('export-summary')).toContainText('sign-ins');
  await shot(page, '14-privacy-export');
});

test('10. quotas: limits are checked, saved and shown, a member only reads', async ({ page, browser }) => {
  await signIn(page);
  await go(page, '/settings/quotas');
  const pat = `pat-${RUN}@${SSO_DOMAIN}`;
  const row = page.locator(`[data-testid="quota-row"][data-email="${pat}"]`);
  await expect(row).toBeVisible({ timeout: 20_000 });
  await row.getByTestId('quota-edit').click();
  await row.getByTestId('quota-tokens').fill('-5');
  await expect(row).toContainText('Cannot be negative');
  await expect(row.getByTestId('quota-save')).toBeDisabled();
  await row.getByTestId('quota-tokens').fill('1.5');
  await expect(row).toContainText('Use a whole number');
  await row.getByTestId('quota-tokens').fill('250000');
  await row.getByTestId('quota-cost').fill('12.5');
  await row.getByTestId('quota-save').click();
  await expect(page.getByText('Limits saved').first()).toBeVisible();
  await expect(row).toContainText('250K');
  await expect(row).toContainText('$12.50');
  const back = await page.request.get(`${API}/api/analytics/per-user`, { headers: { Authorization: `Bearer ${await token(page)}` } });
  const mine = ((await back.json()).data as any[]).find((u) => u.email === pat);
  expect(mine.token_allowance).toBe(250000);
  expect(mine.cost_limit).toBe(12.5);
  await shot(page, '15-quotas');

  const { ctx, page: member } = await newPage(browser);
  await ssoSignIn(member, pat, `pat-${RUN}`);
  await go(member, '/settings/quotas');
  await expect(member.getByTestId('quota-table')).toContainText('250K');
  await expect(member.getByTestId('quota-edit')).toHaveCount(0);
  await go(member, '/settings/data');
  await expect(member.getByTestId('data-settings-readonly')).toBeVisible();
  await expect(member.getByTestId('data-settings-save')).toBeDisabled();
  await go(member, '/settings/sandbox');
  await expect(member.getByTestId('sandbox-readonly')).toBeVisible();
  await go(member, '/settings/sso');
  await expect(member.getByText('Only workspace admins can set up single sign-on.')).toBeVisible();
  await ctx.close();
});

test('11. sandbox: images are checked, added and removed, overrides clear', async ({ page }) => {
  await signIn(page);
  await go(page, '/settings/sandbox');
  const input = page.getByTestId('sandbox-image-input');
  await input.fill('alpine 3.20');
  await page.getByTestId('sandbox-add-image').click();
  await expect(page.getByText(/is not a container image/)).toBeVisible();
  const img = 'busybox:1.36.1';
  await input.fill(img);
  await page.getByTestId('sandbox-add-image').click();
  await expect(page.getByText(img, { exact: true })).toBeVisible();
  await expect(page.getByText(/clear override/).first()).toBeVisible();
  await page.getByRole('button', { name: `Remove ${img}` }).click();
  await expect(page.getByText(img, { exact: true })).toHaveCount(0);
  const net = page.getByTestId('sandbox-network');
  const was = await net.getAttribute('aria-checked');
  await net.click();
  await expect(net).not.toHaveAttribute('aria-checked', String(was));
  await shot(page, '16-sandbox');
  // back to the platform defaults
  for (let i = 0; i < 3 && (await page.getByText('clear override').count()); i++) {
    await page.getByText('clear override').first().click();
    await page.waitForTimeout(800);
  }
  await expect(page.getByText(/Currently inheriting the env default/)).toBeVisible();
});

test('12. DLP: detect, mask and block on a real run', async ({ page }) => {
  test.setTimeout(15 * 60_000);
  await signIn(page);
  await go(page, '/settings/data');
  const audit = page.getByTestId('ret-audit_log_retention_days');
  await audit.fill('4');
  await expect(page.getByText('Use 365 days or more')).toBeVisible();
  await expect(page.getByTestId('data-settings-save')).toBeDisabled();
  await audit.fill('400');
  await expect(page.getByTestId('data-settings-save')).toBeEnabled();

  // an agent to talk to
  await go(page, '/builder');
  await page.getByTestId('builder-name-button').click({ timeout: 30_000 });
  await page.getByTestId('builder-name-input').fill(`Echo desk ${RUN}`);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill('Repeat the user message back word for word and add nothing else.');
  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  const agentId = new URL(page.url()).searchParams.get('agent');

  const ask = async (text: string) => {
    await go(page, `/agents/${agentId}/chat`);
    await expect(page.getByTestId('chat-input')).toBeEnabled({ timeout: 30_000 });
    await page.getByTestId('chat-input').fill(text);
    await page.getByTestId('chat-send').click();
  };
  const reply = async () => {
    const last = page.locator('[data-testid="chat-message"][data-role="assistant"]').last();
    await expect(last).toBeVisible({ timeout: 4 * 60_000 });
    await expect(page.getByTestId('chat-stop')).toHaveCount(0, { timeout: 4 * 60_000 });
    return (await last.innerText()).trim();
  };
  const setMode = async (mode: string) => {
    await go(page, '/settings/data');
    const box = page.getByTestId('dlp-enabled');
    if (!(await box.isChecked())) await box.check();
    await page.getByTestId('dlp-mode').selectOption(mode);
    await expect(page.getByTestId('dlp-mode-help')).not.toBeEmpty();
    await page.getByTestId('data-settings-save').click();
    await expect(page.getByTestId('data-settings-saved')).toBeVisible();
  };
  const email = `pat.private-${RUN}@example.org`;

  await setMode('mask');
  await shot(page, '17-dlp-mask');
  await ask(`Please repeat: my email is ${email}`);
  const masked = await reply();
  expect(masked).toContain('[EMAIL_MASKED]');
  expect(masked).not.toContain(email);
  await shot(page, '18-dlp-masked-run');

  await setMode('block');
  await ask(`Please repeat: my email is ${email}`);
  await expect(page.getByTestId('chat-error').or(page.locator('[data-testid="chat-message"][data-role="assistant"]').last())).toContainText(/personal data|email/i, { timeout: 60_000 });
  await shot(page, '19-dlp-blocked');

  await setMode('detect');
  await ask(`Please repeat: my email is ${email}`);
  expect(await reply()).toContain(email);

  // leave it off for the next test run
  await go(page, '/settings/data');
  await page.getByTestId('dlp-enabled').uncheck();
  await page.getByTestId('data-settings-save').click();
  await expect(page.getByTestId('data-settings-saved')).toBeVisible();
});

test('13. billing with monetization off says so plainly', async ({ page }) => {
  await signIn(page);
  await go(page, '/settings/profile');
  await expect(page.locator('aside').getByRole('link', { name: 'Billing' })).toHaveCount(0);
  await go(page, '/settings/billing');
  await expect(page.getByTestId('billing-off')).toContainText('Monetization is turned off');
  await expect(page.getByTestId('billing-off').getByRole('link', { name: 'Analytics', exact: true })).toBeVisible();
  await shot(page, '20-billing-off');
});

const SCREENS: [string, string, boolean][] = [
  ['sign-in', '/', false],
  ['forgot', '/auth/forgot', false],
  ['reset-broken', '/auth/reset', false],
  ['security', '/settings/security', true],
  ['sso', '/settings/sso', true],
  ['profile', '/settings/profile', true],
  ['privacy', '/settings/privacy', true],
  ['data', '/settings/data', true],
  ['quotas', '/settings/quotas', true],
  ['sandbox', '/settings/sandbox', true],
  ['billing', '/settings/billing', true],
];

for (const width of [1440, 390]) {
  test(`14. account screens at ${width} wide`, async ({ browser }) => {
    const { ctx, page } = await newPage(browser, width);
    await signIn(page);
    for (const [name, route, authed] of SCREENS) {
      if (!authed) {
        const { ctx: anon, page: p } = await newPage(browser, width);
        await go(p, route);
        await shot(p, `w${width}-${name}`);
        const over = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(over, `${name} scrolls sideways at ${width}`).toBeLessThanOrEqual(1);
        await anon.close();
        continue;
      }
      await go(page, route);
      await page.waitForTimeout(800);
      await shot(page, `w${width}-${name}`);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(over, `${name} scrolls sideways at ${width}`).toBeLessThanOrEqual(1);
    }
    await ctx.close();
  });
}
