// The flow editor loads its own zod through an override, so check it really opens.
import { test, expect } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };

test('the decision flow editor draws a saved decision without errors', async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));

  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  expect(res.ok()).toBeTruthy();
  const tok = (await res.json()).data.access_token as string;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((x) => { localStorage.setItem('access_token', x); localStorage.setItem('refresh_token', x); }, tok);

  const list = await page.request.get(`${API}/api/decisions`, { headers: { Authorization: `Bearer ${tok}` } });
  expect(list.ok()).toBeTruthy();
  const models = (await list.json()).data as Array<{ key: string }>;
  expect(models.length, 'a decision to open').toBeGreaterThan(0);

  await page.goto(`${BASE}/decisions/${models[0].key}?tab=flow`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('flow-view')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.react-flow__node').first()).toBeVisible({ timeout: 60_000 });
  expect(errors, errors.join('\n')).toEqual([]);
});
