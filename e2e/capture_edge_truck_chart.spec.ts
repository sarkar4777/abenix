/**
 * The demo truck's engine over 15 minutes in Telemetry, for the Edge film.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/capture_edge_truck_chart.spec.ts --workers=1
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const OUT = path.join(__dirname, 'uat_edge_collect');

test('truck-7 engine, 15 minutes of charts', async ({ browser }) => {
  test.setTimeout(120_000);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1700 } });
  const page = await ctx.newPage();
  const r = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  const t = (await r.json()).data.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((x) => { localStorage.setItem('access_token', x); localStorage.setItem('refresh_token', x); }, t);
  await page.goto(`${BASE}/telemetry?group=edge-demo&node=truck-7&device=engine&focus=charts&range=15m`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await expect(page.getByRole('heading', { name: 'truck-7 / engine' })).toBeVisible({ timeout: 30_000 });
  // torque and fuel next to rpm, coolant and oil pressure, so the duty cycle reads at a glance
  const add = page.getByRole('combobox', { name: 'Add a signal to the chart' });
  for (const sig of ['Engine/Torque_pct', 'Engine/FuelRate_lph']) {
    await add.selectOption({ label: sig });
    await page.waitForTimeout(1500);
  }
  await page.waitForTimeout(6000);
  await page.screenshot({ path: path.join(OUT, 'truck-7-engine-15m.png'), fullPage: true });
  await ctx.close();
});
