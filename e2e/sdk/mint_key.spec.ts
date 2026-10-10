import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// Signs in through the landing page and generates an API key on
// /settings/api-keys, the way a developer gets one. The raw key is written
// to SDK_KEY_FILE for the SDK suites to pick up.

const BASE = process.env.BASE || 'http://localhost:3100';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';
const KEY_FILE = process.env.SDK_KEY_FILE || path.join('e2e', 'sdk', '.sdk-key');

test('developer generates an API key in the UI', async ({ page }) => {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  const signInTab = page.getByRole('button', { name: 'Switch to sign in' });
  if (await signInTab.isVisible().catch(() => false)) await signInTab.click();
  await page.getByLabel('Email address').fill(EMAIL);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL((u) => !u.pathname.match(/^\/?$/), { timeout: 30_000 });

  await page.goto(`${BASE}/settings/api-keys`, { waitUntil: 'domcontentloaded' });
  await page.getByTestId('apikey-generate').first().click();
  const name = `sdk-e2e ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`;
  await page.getByTestId('apikey-name').fill(name);
  await page.getByTestId('apikey-create').click();
  const value = page.getByTestId('apikey-created-value');
  await expect(value).toBeVisible({ timeout: 15_000 });
  const raw = (await value.innerText()).trim();
  expect(raw).toMatch(/^af_/);
  fs.mkdirSync(path.dirname(KEY_FILE), { recursive: true });
  fs.writeFileSync(KEY_FILE, raw, { encoding: 'utf8', mode: 0o600 });
  // the list should now show the key by name
  await expect(page.getByText(name).first()).toBeVisible();
});
