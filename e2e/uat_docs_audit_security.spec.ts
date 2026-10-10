import { test, expect, type Page } from '@playwright/test';

/**
 * Docs-audit security fixes, checked in the browser:
 *  - tenant DLP mode applies to chat (mask, then block, then back to detect)
 *  - marketplace switches are locked for an admin who is not a platform operator
 *  - connector writes need an admin, reads stay open
 *  - the unencrypted-secrets banner on Tool Configuration and Connectors
 *  - a redacted moderation event says what was masked
 *
 * BASE=http://localhost:3100 API=http://localhost:8000 \
 *   npx playwright test e2e/uat_docs_audit_security.spec.ts --reporter=list --workers=1
 */

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: 'admin@abenix.dev', password: 'Admin123456' };
const MEMBER = { email: 'demo@abenix.dev', password: 'Demo123456' };

async function token(email: string, password: string): Promise<string> {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const j = await r.json();
  return j.data?.access_token;
}

async function api(method: string, path: string, tok: string, body?: unknown) {
  const r = await fetch(`${API}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tok}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { status: r.status, json: await r.json().catch(() => ({})) };
}

async function signIn(page: Page, email: string, password: string) {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.isVisible().catch(() => false)) await toSignIn.click();
  // the form can re-render once after hydration, so fill and submit until a token lands
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.locator('#auth-email').fill(email);
    await page.locator('#auth-password').fill(password);
    await expect(page.locator('#auth-email')).toHaveValue(email);
    await page.getByTestId('auth-submit').click();
    const ok = await page
      .waitForFunction(() => !!localStorage.getItem('access_token'), null, { timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (ok) {
      // sign-in ends with a redirect away from the landing page, let it finish
      await page.waitForURL((u) => u.pathname !== '/', { timeout: 30_000 }).catch(() => {});
      await page.waitForLoadState('domcontentloaded');
      return;
    }
  }
  throw new Error(`could not sign in as ${email}`);
}

async function setDlp(page: Page, mode: 'detect' | 'mask' | 'block') {
  await page.goto(`${BASE}/settings/data`, { waitUntil: 'domcontentloaded' });
  const enabled = page.getByTestId('dlp-enabled');
  await expect(enabled).toBeEnabled({ timeout: 30_000 });
  if (!(await enabled.isChecked())) await enabled.check();
  await page.getByTestId('dlp-mode').selectOption(mode);
  await expect(page.getByTestId('dlp-mode-help')).toBeVisible();
  await page.getByTestId('data-settings-save').click();
  await expect(page.getByTestId('data-settings-saved')).toBeVisible({ timeout: 45_000 });
}

async function chat(page: Page, text: string) {
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('chat-agent-picker')).not.toContainText(/loading|choose an agent/i, { timeout: 60_000 });
  const before = await page.locator('[data-testid="chat-message"][data-role="assistant"]').count();
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
  return before;
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('DLP mode on chat', () => {
  let original: { mode?: string; enabled?: boolean } = {};
  let adminTok = '';

  test.beforeAll(async () => {
    adminTok = await token(ADMIN.email, ADMIN.password);
    original = (await api('GET', '/api/settings/dlp', adminTok)).json.data || {};
  });

  test.afterAll(async () => {
    await api('PUT', '/api/settings/dlp', adminTok, {
      mode: original.mode || 'detect',
      enabled: original.enabled ?? false,
    });
  });

  test('mask hides the email in the answer, block refuses, detect restores', async ({ page }) => {
    test.setTimeout(300_000);
    await signIn(page, ADMIN.email, ADMIN.password);

    await setDlp(page, 'mask');
    // the model writes an address itself, so this checks the answer is masked, not just the prompt
    const before = await chat(page, 'Reply with only an example email address for someone named Jane at the domain example.com. No other text.');
    const answers = page.locator('[data-testid="chat-message"][data-role="assistant"]');
    await expect(answers).toHaveCount(before + 1, { timeout: 180_000 });
    await expect(page.getByTestId('chat-stop')).toHaveCount(0, { timeout: 180_000 });
    const answer = await answers.last().innerText();
    expect(answer).not.toMatch(/@example\.com/i);
    expect(answer).toContain('EMAIL_MASKED');
    await page.screenshot({ path: 'e2e/test-results/dlp-mask.png', fullPage: true });

    await setDlp(page, 'block');
    await chat(page, 'Please email jane.doe@example.com about the invoice');
    await expect(page.getByText(/not sent because it contains an email address/i).first()).toBeVisible({ timeout: 60_000 });
    await page.screenshot({ path: 'e2e/test-results/dlp-block.png', fullPage: true });

    await setDlp(page, 'detect');
    const st = (await api('GET', '/api/settings/dlp', adminTok)).json.data;
    expect(st.mode).toBe('detect');
  });

  test('only an admin can change the DLP mode', async () => {
    const memberTok = await token(MEMBER.email, MEMBER.password);
    const r = await api('PUT', '/api/settings/dlp', memberTok, { mode: 'detect', enabled: false });
    expect(r.status).toBe(403);
  });
});

test.describe('marketplace switches', () => {
  test('platform admin can flip, another tenant admin sees why not', async ({ page, browser }) => {
    await signIn(page, ADMIN.email, ADMIN.password);
    await page.goto(`${BASE}/admin/marketplace`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('feature-marketplace')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('switch-marketplace')).toBeEnabled({ timeout: 15_000 });
    await expect(page.getByTestId('admin-marketplace-operator-only')).toHaveCount(0);

    const email = `tenant-admin-${Date.now()}@example.com`;
    const reg = await fetch(`${API}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: 'TenantPass123!', full_name: 'Other Admin', tenant_name: `Other ${Date.now()}` }),
    });
    expect(reg.status).toBeLessThan(300);
    const otherTok = await token(email, 'TenantPass123!');
    const put = await api('PUT', '/api/admin/platform-features', otherTok, { marketplace: false });
    expect(put.status).toBe(403);
    expect(put.json.error.error_code).toBe('PLATFORM_OPERATOR_REQUIRED');

    const ctx = await browser.newContext();
    const other = await ctx.newPage();
    await signIn(other, email, 'TenantPass123!');
    await other.goto(`${BASE}/admin/marketplace`, { waitUntil: 'domcontentloaded' });
    await expect(other.getByTestId('admin-marketplace-operator-only')).toBeVisible({ timeout: 30_000 });
    await expect(other.getByTestId('admin-marketplace-operator-only')).toContainText('platform operator');
    await expect(other.getByTestId('switch-marketplace')).toBeDisabled();
    await expect(other.getByTestId('switch-monetization')).toBeDisabled();
    await other.screenshot({ path: 'e2e/test-results/marketplace-operator-only.png', fullPage: true });
    await ctx.close();
  });
});

test.describe('connectors and secrets', () => {
  test('connector writes need an admin, reads stay open', async () => {
    const memberTok = await token(MEMBER.email, MEMBER.password);
    expect((await api('GET', '/api/connectors', memberTok)).status).toBe(200);
    const create = await api('POST', '/api/connectors', memberTok, {
      name: 'nope',
      kind: 'custom',
      base_url: 'https://api.example.com',
      auth_type: 'none',
    });
    expect(create.status).toBe(403);
    expect(create.json.error.message).toMatch(/admin/i);
  });

  test('banner shows on both pages when the cluster has no key', async ({ page }) => {
    await signIn(page, ADMIN.email, ADMIN.password);
    // this cluster has a key, so the real answer hides the banner
    await page.goto(`${BASE}/admin/tool-config`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('tool-config-encryption')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('secrets-unencrypted-banner')).toHaveCount(0);

    // a keyless cluster answers like this
    await page.route('**/api/admin/secret-storage', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            encrypted_at_rest: false,
            message: 'Secrets are stored unencrypted. Set ABENIX_DATA_KEY_KEK_BASE64 to encrypt them.',
            doc_slug: '08-howto/06-encryption-setup',
            environment: 'development',
          },
          error: null,
        }),
      }),
    );
    for (const path of ['/admin/tool-config', '/admin/connectors']) {
      await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
      const banner = page.getByTestId('secrets-unencrypted-banner');
      await expect(banner).toBeVisible({ timeout: 30_000 });
      await expect(banner).toContainText('Set ABENIX_DATA_KEY_KEK_BASE64 to encrypt them');
      await expect(banner.getByRole('link', { name: 'How to set the key' })).toHaveAttribute('href', /06-encryption-setup/);
    }
    await page.screenshot({ path: 'e2e/test-results/secrets-banner.png', fullPage: true });
  });
});

test.describe('moderation redact', () => {
  test('a redacted event says what was masked', async ({ page }) => {
    const tok = await token(ADMIN.email, ADMIN.password);
    const vet = await api('POST', '/api/moderation/vet', tok, {
      content: 'The launch codename is bluebird, keep it quiet.',
      policy_overrides: { default_action: 'redact', custom_patterns: ['\\bbluebird\\b'] },
    });
    expect(vet.status).toBe(200);
    expect(vet.json.data.outcome).toBe('redacted');
    expect(vet.json.data.redacted_content).not.toContain('bluebird');
    const id = vet.json.data.event_id;

    await signIn(page, ADMIN.email, ADMIN.password);
    await page.goto(`${BASE}/moderation`, { waitUntil: 'domcontentloaded' });
    const masked = page.getByTestId(`event-masked-${id}`);
    await expect(masked).toBeVisible({ timeout: 30_000 });
    await expect(masked).toContainText('Masked 1 part');
    await expect(page.getByTestId(`event-row-${id}`)).not.toContainText('bluebird');
  });
});
