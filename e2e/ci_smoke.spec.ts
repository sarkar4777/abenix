/**
 * CI smoke: sign in, the dashboard, build an agent in the builder and chat with it.
 *
 * CI runs the API with ABENIX_LLM_STUB=1, so the model echoes "Stub reply: <message>" and no
 * provider key is needed. Against a real stack the reply is whatever the model says, so the
 * echo is only asserted when STUB_LLM=1.
 *
 *   USE_K8S=true BASE=http://localhost:3000 API=http://localhost:8000 STUB_LLM=1 npx playwright test e2e/ci_smoke.spec.ts
 */
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const STUB = process.env.STUB_LLM === '1';
const RUN = Date.now().toString(36);
let agentId = '';

test.describe.configure({ mode: 'serial', timeout: 120_000 });
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

test.afterAll(async ({ playwright }) => {
  if (!agentId) return;
  const req = await playwright.request.newContext();
  const tok = (await (await req.post(`${API}/api/auth/login`, { data: ADMIN })).json())?.data?.access_token;
  await req.delete(`${API}/api/agents/${agentId}`, { headers: { Authorization: `Bearer ${tok}` } }).catch(() => {});
  await req.dispose();
});

test('a wrong password is refused and the right one signs in', async ({ page }) => {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(ADMIN.email);
  await page.locator('#auth-password').fill('not-the-password-1');
  await page.getByTestId('auth-submit').click();
  await expect(page.getByRole('alert').first()).toBeVisible({ timeout: 15_000 });
  await expect(page).not.toHaveURL(/\/dashboard/);
  await signIn(page);
});

test('the dashboard loads with its header and the sidebar', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await signIn(page);
  await expect(page.getByTestId('page-header').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId('sidebar-mode-toggle').first()).toBeVisible();
  await expect(page.locator('aside a[href="/agents"]').first()).toBeVisible();
  expect(errors, 'script errors on the dashboard').toEqual([]);
});

test('an agent is built and published in the builder, then answers in chat', async ({ page }) => {
  test.setTimeout(240_000);
  page.on('dialog', (d) => d.accept());
  await signIn(page);
  await go(page, '/builder');
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(`CI smoke ${RUN}`);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill('Answers in one short sentence.');
  await page.getByTestId('builder-category').selectOption({ index: 1 });
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill('You answer in one short sentence.');
  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  agentId = new URL(page.url()).searchParams.get('agent') || '';
  expect(agentId, 'saved agent id').toBeTruthy();
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-visibility-org').click();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });

  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const before = await replies.count();
  const message = `ping ${RUN}`;
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: 180_000 });
  await expect(page.getByTestId('chat-error')).toHaveCount(0);
  await expect(replies).toHaveCount(before + 1, { timeout: 30_000 });
  const reply = await replies.nth(before).innerText();
  if (STUB) expect(reply).toContain(`Stub reply: ${message}`);
  else expect(reply.trim().length).toBeGreaterThan(0);
});
