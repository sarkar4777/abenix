/**
 * Abenix Edge, the collect role, through the UI as an admin would use it:
 *   - the guided Add an edge gateway flow: pick, settings with a wrong value caught and fixed, install command
 *   - the gateway waits for its first start, its details show health, Remove asks first
 *   - the demo gateway from deploy.sh edge-demo, when it runs, shows online with collectors and assets
 * Screenshots at 1440 and 390 px go to e2e/uat_edge_collect/.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_edge_collect.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const OUT = path.join(__dirname, 'uat_edge_collect');
const RUN = Date.now().toString(36);

async function login(page: Page) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  const t = (await r.json()).data.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((x) => { localStorage.setItem('access_token', x); localStorage.setItem('refresh_token', x); }, t);
  return t as string;
}

async function noSideScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, 'no sideways scroll').toBeLessThanOrEqual(1);
}

test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));
test.setTimeout(5 * 60_000);

for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`add an edge gateway through the guided flow at ${vp.width} px`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const token = await login(page);
    const failed: string[] = [];
    page.on('response', (r) => { if (r.status() >= 500 && r.url().startsWith(API)) failed.push(`${r.status()} ${r.url()}`); });

    await page.goto(`${BASE}/edge`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('edge-page')).toBeVisible();
    await expect(page.getByTestId('page-purpose')).toBeVisible();
    await page.waitForLoadState('networkidle').catch(() => {});
    await noSideScroll(page);
    await page.screenshot({ path: path.join(OUT, `edge-page-${vp.width}.png`), fullPage: true });

    // the Get started guide's link opens the flow with the collector picked
    await page.goto(`${BASE}/edge?add=gateway&role=collect&collector=modbus`, { waitUntil: 'domcontentloaded' });
    const wiz = page.getByTestId('edge-wizard');
    await expect(wiz).toBeVisible();
    await expect(page.getByTestId('edge-pick-modbus')).toHaveAttribute('aria-pressed', 'true');
    await page.getByTestId('edge-pick-can').click();
    await page.screenshot({ path: path.join(OUT, `wizard-1-pick-${vp.width}.png`) });
    await page.getByTestId('edge-wizard-next').click();

    // nothing filled in: the save says what is missing, next to each field
    await page.getByTestId('edge-wizard-save').click();
    await expect(page.getByTestId('edge-gw-name-problem')).toContainText('Give the gateway a name');
    await expect(page.getByTestId('edge-c0-registers-problem')).toContainText('such as voltage_v');
    await page.getByTestId('edge-gw-name').fill(`UI yard ${RUN}`);
    await page.getByTestId('edge-c0-asset-node').fill('meter.1');
    await page.getByTestId('edge-c0-host').fill('meter.abenix-testbed.svc.cluster.local');
    await page.getByTestId('edge-c0-registers').fill('voltage_v, holding, 0, float32, 1, V');
    await page.getByTestId('edge-c1-name').fill('Truck bus');
    await page.getByTestId('edge-wizard-save').click();
    await expect(page.getByTestId('edge-c0-asset-node-problem')).toContainText('letters, digits, - and _ only');
    await page.screenshot({ path: path.join(OUT, `wizard-2-problems-${vp.width}.png`) });
    await page.getByTestId('edge-c0-asset-node').fill('meter-1');
    await page.getByTestId('edge-c1-asset-node').fill('truck-12');
    await page.getByTestId('edge-wizard-save').click();

    // install: commands carry a one-time token
    await expect(page.getByTestId('edge-install')).toBeVisible({ timeout: 15_000 });
    await page.getByTestId('edge-platform-url').fill('https://abenix.example.com');
    await page.getByTestId('edge-make-install').click();
    const docker = page.getByTestId('edge-install-docker_run');
    await expect(docker).toContainText('ABENIX_ENROLL_TOKEN=etk_');
    await expect(docker).toContainText('--network host');
    await page.getByTestId('edge-install-tab-kubernetes').click();
    await expect(page.getByTestId('edge-install-kubernetes')).toContainText('kind: StatefulSet');
    await page.getByTestId('edge-install-tab-systemd').click();
    await expect(page.getByTestId('edge-install-systemd')).toContainText('systemctl enable --now abenix-edge');
    await page.screenshot({ path: path.join(OUT, `wizard-3-install-${vp.width}.png`) });
    await page.getByTestId('edge-wizard-ran').click();
    await expect(page.getByTestId('edge-waiting')).toContainText('Waiting for');
    await page.screenshot({ path: path.join(OUT, `wizard-4-waiting-${vp.width}.png`) });
    await page.getByTestId('edge-wizard-close').click();

    // the card says it has not started, details say what to do, Remove asks first
    const card = page.locator('[data-testid="edge-gateway-card"]', { hasText: `UI yard ${RUN}` });
    await expect(card.getByTestId('edge-gateway-status')).toContainText('Waiting for first start');
    await card.getByTestId('edge-gateway-open').click();
    await expect(page.getByTestId('edge-detail')).toContainText('Not started yet');
    await page.screenshot({ path: path.join(OUT, `detail-waiting-${vp.width}.png`) });
    await page.getByTestId('edge-detail-remove').click();
    await expect(page.getByRole('heading', { name: new RegExp(`Remove UI yard ${RUN}`) })).toBeVisible();
    await page.getByTestId('edge-remove-confirm').click();
    await expect(card).toHaveCount(0, { timeout: 15_000 });

    // the demo gateway, when deploy.sh edge-demo has run
    const gws = await page.request.get(`${API}/api/edge/gateways`, { headers: { Authorization: `Bearer ${token}` } });
    const demo = ((await gws.json()).data.gateways as Array<{ id: string; name: string; status: string }>).find((g) => g.name === 'Edge demo yard');
    if (demo && demo.status === 'online') {
      await page.goto(`${BASE}/edge?gateway=${demo.id}`, { waitUntil: 'domcontentloaded' });
      const d = page.getByTestId('edge-detail');
      await expect(d.getByTestId('edge-detail-status')).toContainText('Online');
      await expect(d.getByTestId('edge-detail-collector')).toHaveCount(5);
      await expect(d).toContainText('Store and forward buffer');
      await expect(d).toContainText('edge-demo / truck-7 / engine', { timeout: 20_000 });
      await page.waitForTimeout(1000);
      await page.screenshot({ path: path.join(OUT, `detail-demo-${vp.width}.png`), fullPage: true });
      await page.getByTestId('edge-detail-close').click();
      await expect(page.getByTestId('edge-detail')).toHaveCount(0);
      await page.screenshot({ path: path.join(OUT, `edge-page-demo-${vp.width}.png`), fullPage: true });
    }
    expect(failed, 'no server errors').toEqual([]);
    await ctx.close();
  });
}
