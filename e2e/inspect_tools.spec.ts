import { test, expect, type Page } from '@playwright/test';
const BASE = 'http://localhost:3000';
const API = 'http://localhost:8000';

async function login(page: Page) {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@abenix.dev', password: 'Admin123456' }),
  });
  const tok = (await r.json()).data.access_token;
  await page.addInitScript(({ t }) => {
    localStorage.setItem('access_token', t);
    localStorage.setItem('refresh_token', t);
    localStorage.setItem('user', JSON.stringify({}));
  }, { t: tok });
}

test('inspect /tools', async ({ page }) => {
  page.on('console', m => console.log('  >>', m.type(), ':', m.text().substring(0, 200)));
  page.on('pageerror', e => console.log('  PAGE ERROR:', e.message));
  await login(page);
  const r = await page.goto(`${BASE}/tools`, { waitUntil: 'domcontentloaded' });
  console.log('GOTO status', r?.status());
  await page.waitForTimeout(4000);
  const heading = await page.getByRole('heading', { name: /Tools catalogue/i }).isVisible().catch(() => false);
  console.log('heading visible', heading);
  const loading = await page.getByText(/Loading tools/i).isVisible().catch(() => false);
  console.log('loading text visible', loading);
  const error = await page.getByText(/Failed to load/i).isVisible().catch(() => false);
  console.log('error visible', error);
  const liCount = await page.locator('li').count();
  console.log('li count', liCount);
  const monoCount = await page.locator('.font-mono').count();
  console.log('font-mono count', monoCount);
  const buttonCount = await page.locator('button').count();
  console.log('button count', buttonCount);
});
