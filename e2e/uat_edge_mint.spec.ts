import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function login(page: Page) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const tok = (await r.json()).data.access_token;
  await page.goto(BASE);
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('token', t); }, tok);
}

test('Edge mint button: click reveals token + pubkey in modal', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/edge`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  const mintBtn = page.locator('button', { hasText: /Mint edge token/i });
  await expect(mintBtn).toBeVisible({ timeout: 5000 });
  await mintBtn.click();

  await page.waitForTimeout(3500);

  const html = await page.locator('body').innerText();
  expect(html).toMatch(/PLATFORM_TOKEN/i);
  expect(html).toMatch(/SIGNING_PUBKEY|BEGIN PUBLIC KEY/i);
  expect(html).toMatch(/af_/);

  await page.screenshot({ path: 'test-results/uat-edge-mint-modal.png', fullPage: true });
  console.log('Edge mint modal rendered with token + pubkey');
});
