import { test, type Page } from '@playwright/test';
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

test('inspect tool names', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/builder`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3500);
  const cats = await page.locator('button').filter({ hasText: /\(\d+\)\d+$/ }).all();
  for (const c of cats) await c.click().catch(() => {});
  await page.waitForTimeout(800);
  const palette = page.locator('aside, [class*="palette" i]').first();
  const tools = await palette.locator('button[draggable="true"]').all();
  console.log('draggable tools', tools.length);
  for (let i = 0; i < Math.min(tools.length, 30); i++) {
    const txt = (await tools[i].textContent()) || '';
    console.log(`  [${i}] "${txt.replace(/\s+/g, ' ').trim().substring(0, 100)}"`);
  }
});
