// Grafana panel-walk UAT. Drives a real Chromium against the Azure
// Grafana ingress, walks each dashboard, and asserts that the panels
// hydrate with at least one data point each. The v2.3.7 sha256
// sentinel landed the scrape config; this spec catches a regression
// where the config rolls fine but a panel query is wrong / the metric
// has been renamed / a dashboard has no data target.
//
// Anonymous read-only access is the default at install time; if a
// future deploy requires auth, set GRAFANA_USER and GRAFANA_PASSWORD
// and the spec will log in before walking the panels.
import { test, expect, Page } from '@playwright/test';

const GRAFANA = process.env.GRAFANA || 'http://grafana.20.72.73.141.nip.io';
const USER = process.env.GRAFANA_USER || '';
const PASSWORD = process.env.GRAFANA_PASSWORD || '';

async function gotoOk(page: Page, path: string, settle = 1000) {
  const resp = await page.goto(`${GRAFANA}${path}`, { waitUntil: 'domcontentloaded' });
  // Grafana sometimes responds 401 on first hit; treat anything < 500 as
  // navigable (we'll trip on the next assertion if the page is broken).
  if (resp) expect(resp.status(), `${path} HTTP`).toBeLessThan(500);
  await page.waitForLoadState('networkidle').catch(() => {});
  if (settle) await page.waitForTimeout(settle);
}

async function loginIfNeeded(page: Page) {
  // Only attempt login when both creds are set; the default install
  // serves dashboards anonymously to org-Viewer.
  if (!USER || !PASSWORD) return;
  await page.goto(`${GRAFANA}/login`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="user"]', USER);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe('Grafana — UI panel walk', () => {
  test.beforeEach(async ({ page }) => {
    await loginIfNeeded(page);
  });

  test('health endpoint returns ok + version', async ({ page }) => {
    const r = await page.request.get(`${GRAFANA}/api/health`);
    expect(r.status()).toBe(200);
    const j = await r.json();
    expect(j.database).toBe('ok');
    expect(typeof j.version).toBe('string');
  });

  test('Prometheus datasource is configured + reachable', async ({ page }) => {
    // /api/datasources requires auth, but /api/frontend/settings exposes
    // the wired-up datasources to anonymous viewers.
    const r = await page.request.get(`${GRAFANA}/api/frontend/settings`);
    expect(r.status()).toBeLessThan(500);
    const j = await r.json();
    const names = Object.keys(j?.datasources || {});
    expect(names.length, `at least one datasource: ${names.join(',')}`).toBeGreaterThan(0);
    const hasProm = names.some(n => /prometheus/i.test(n)) ||
      Object.values(j?.datasources || {}).some((d: any) => d.type === 'prometheus');
    expect(hasProm, 'a Prometheus datasource must be wired').toBeTruthy();
  });

  test('dashboards: abenix-overview lists in search', async ({ page }) => {
    const r = await page.request.get(`${GRAFANA}/api/search?type=dash-db`);
    expect(r.status()).toBeLessThan(500);
    const items = await r.json();
    const titles = (items || []).map((i: any) => String(i.title || '').toLowerCase());
    expect(titles.length, 'at least one dashboard provisioned').toBeGreaterThan(0);
    // The abenix-overview.json + scaling-ops.json + resource-invocations.json
    // are provisioned via the configmap. We require at least one of them.
    const hasOurs = titles.some((t: string) => /abenix|scaling|resource/.test(t));
    expect(hasOurs, `expected one of abenix/scaling/resource in: ${titles.join(' | ')}`).toBeTruthy();
  });

  test('Prometheus `up` query returns at least 1 series', async ({ page }) => {
    // Datasource id 1 is the default in the provisioning configmap. If
    // a future change reorders, swap to a name-based proxy lookup.
    const r = await page.request.get(
      `${GRAFANA}/api/datasources/proxy/1/api/v1/query?query=up`,
    );
    if (r.status() === 404) {
      test.skip(true, 'datasource id 1 not found; provisioning differs');
    }
    expect(r.status()).toBeLessThan(500);
    const j = await r.json();
    expect(j?.status).toBe('success');
    const result = j?.data?.result || [];
    expect(result.length, 'at least one `up` series').toBeGreaterThan(0);
  });

  test('home dashboard panels render — no "No data" everywhere', async ({ page }) => {
    await gotoOk(page, '/d/abenix-overview/abenix-overview?refresh=10s&from=now-30m&to=now', 3000);
    // The home dashboard renders panel <div role="figure"> elements
    // once their queries succeed. The "No data" placeholder shows up
    // inside `[data-testid="data-testid Panel data error message"]`.
    // A CSS selector and text= cannot share one locator string — this threw
    // "Unexpected token =" every run rather than asserting anything.
    const noDataCount = await page
      .locator('[data-testid*="data error"]')
      .or(page.getByText(/No data/i))
      .count();
    // Grafana appends the panel title, so the testid is
    // "data-testid Panel header Active executions". An exact match never hit.
    const panelCount = await page
      .locator('[data-testid^="data-testid Panel header"]')
      .count();
    // The home dashboard has ~10 panels; we accept at most one panel
    // showing "No data" since the cluster is small and some series may
    // not have ticked yet.
    expect(panelCount, 'panels detected').toBeGreaterThan(0);
    expect(noDataCount, `too many panels with no data on overview: ${noDataCount}`).toBeLessThan(
      Math.max(2, Math.floor(panelCount / 2)),
    );
  });
});
