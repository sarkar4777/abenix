/**
 * The builder's Edge compatible toggle and constraints survive Save Draft and a reload.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_edge_builder_toggle.spec.ts
 */
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };

async function login(page: Page) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  const tok = (await res.json()).data.access_token as string;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((x) => { localStorage.setItem('access_token', x); localStorage.setItem('refresh_token', x); }, tok);
  return tok;
}

test('Edge compatible and its MQTT topics are saved from the builder', async ({ page }) => {
  const tok = await login(page);
  const headers = { Authorization: `Bearer ${tok}` };
  const created = await page.request.post(`${API}/api/agents`, {
    headers,
    data: { name: `Edge toggle ${Date.now().toString(36)}`, system_prompt: 'edge check', tools: ['code_executor', 'mqtt_publish'] },
  });
  const id = (await created.json()).data.id as string;
  try {
    await page.goto(`${BASE}/builder?agent=${id}`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Advanced', exact: true }).click();
    const block = page.locator('div.border-b', { has: page.getByRole('heading', { name: 'Edge compatible' }) }).last();
    await block.locator('label').first().click();
    await block.locator('label:has-text("MQTT publish topics") + input').fill('site/a/status');
    await page.getByTestId('builder-save-draft').click();

    await expect.poll(async () => {
      const r = await page.request.get(`${API}/api/agents/${id}`, { headers });
      const mc = (await r.json()).data.model_config;
      return [mc.edge_compatible, (mc.edge_constraints || {}).mqtt_publish];
    }, { timeout: 15_000 }).toEqual([true, ['site/a/status']]);

    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Advanced', exact: true }).click();
    await expect(block.locator('input[type=checkbox]')).toBeChecked();
    await expect(block.locator('label:has-text("MQTT publish topics") + input')).toHaveValue('site/a/status');
  } finally {
    await page.request.delete(`${API}/api/agents/${id}`, { headers });
  }
});
