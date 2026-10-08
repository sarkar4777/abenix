import { test, expect, type Page } from '@playwright/test';
import { execSync } from 'child_process';

/*
 * Admin cluster view against the real cluster. kubectl (read only) is the oracle.
 *
 *   BASE=http://localhost:3100 NS=abenix \
 *   npx playwright test e2e/uat_cluster_view_ui.spec.ts --reporter=list --workers=1
 */

const BASE = process.env.BASE || 'http://localhost:3100';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';
const NS = process.env.NS || 'abenix';
const RELEASE = process.env.RELEASE || 'abenix';

test.describe.configure({ mode: 'serial' });

function kubectl<T>(args: string): T {
  return JSON.parse(execSync(`kubectl ${args} -o json`, { encoding: 'utf-8', maxBuffer: 64 * 1024 * 1024 })) as T;
}

function cores(q: string): number {
  return q.endsWith('m') ? Number(q.slice(0, -1)) / 1000 : Number(q);
}

type Item = { metadata: { name: string }; spec: { replicas?: number }; status: { readyReplicas?: number; capacity?: Record<string, string> } };

const CORE = ['api', 'web', 'worker', 'agent-runtime-default', 'postgresql', 'redis-master', 'nats'].map((n) => `${RELEASE}-${n}`);

async function signIn(page: Page) {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(EMAIL);
  await page.locator('#auth-password').fill(PASSWORD);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function openCluster(page: Page) {
  await page.goto(`${BASE}/admin/cluster`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('cluster-verdict')).toBeVisible({ timeout: 60_000 });
}

test('node count and cores match the cluster, nothing is hidden', async ({ page }) => {
  test.setTimeout(3 * 60_000);
  const nodes = kubectl<{ items: Item[] }>('get nodes').items;
  const totalCores = nodes.reduce((a, n) => a + cores(n.status.capacity?.cpu || '0'), 0);

  await signIn(page);
  await openCluster(page);

  await expect(page.getByTestId('cluster-access-panel')).toHaveCount(0);
  await expect(page.getByTestId('cluster-node-count')).toHaveText(String(nodes.length));
  const shownCores = Number(await page.getByTestId('cluster-core-count').getAttribute('data-cores'));
  expect(shownCores).toBeCloseTo(totalCores, 1);
  await expect(page.getByTestId('cluster-core-count')).toContainText('cores');
  await expect(page.getByTestId('node-card')).toHaveCount(nodes.length);
  for (const n of nodes) {
    await expect(page.locator(`[data-testid="node-card"][data-node="${n.metadata.name}"]`)).toBeVisible();
  }

  const verdict = await page.getByTestId('cluster-verdict').getAttribute('data-state');
  expect(['healthy', 'degraded', 'critical']).toContain(verdict);
  await expect(page.getByTestId('cluster-verdict-reason').first()).toBeVisible();
  await expect(page.getByTestId('cluster-updated')).toContainText(/Updated/);
});

test('every core service is listed with the ready count the cluster reports', async ({ page }) => {
  test.setTimeout(3 * 60_000);
  const deploys = kubectl<{ items: Item[] }>(`get deploy -n ${NS}`).items;
  const sts = kubectl<{ items: Item[] }>(`get sts -n ${NS}`).items;
  const byName = new Map([...deploys, ...sts].map((w) => [w.metadata.name, w]));
  const present = CORE.filter((n) => byName.has(n));
  expect(present.length).toBeGreaterThanOrEqual(5);

  await signIn(page);
  await openCluster(page);

  for (const name of present) {
    const w = byName.get(name)!;
    const row = page.locator(`[data-testid="service-row"][data-service="${name}"]`);
    await expect(row, `${name} is listed`).toBeVisible();
    const desired = w.spec.replicas ?? 1;
    const ready = w.status.readyReplicas ?? 0;
    await expect(row).toHaveAttribute('data-desired', String(desired));
    await expect(row).toHaveAttribute('data-ready', String(ready));
    await expect(row.getByTestId('service-ready')).toHaveText(`${ready}/${desired}`);
    await expect(row.getByTestId('service-image')).not.toHaveText('—');
  }
  await expect(page.locator(`[data-testid="service-row"][data-service="${RELEASE}-api"]`)).toHaveAttribute('data-group', 'Core');
  await expect(page.locator(`[data-testid="service-row"][data-service="${RELEASE}-postgresql"]`)).toHaveAttribute('data-group', 'Data');

  // filters narrow the list and say so when nothing matches
  await page.getByTestId('cluster-group-data').click();
  const groups = await page.getByTestId('service-row').evaluateAll((els) => els.map((e) => e.getAttribute('data-group')));
  expect(new Set(groups)).toEqual(new Set(['Data']));
  await page.getByTestId('cluster-group-all').click();
  await page.getByTestId('cluster-search').fill('no-such-service-anywhere');
  await expect(page.getByTestId('cluster-services-nomatch')).toBeVisible();
  await page.getByText('Clear filters').click();

  // pause stops the refresh and says so
  await page.getByTestId('cluster-pause').click();
  await expect(page.getByTestId('cluster-updated')).toContainText('paused');
  await page.getByTestId('cluster-pause').click();
});

test('opening a pod shows its events and its log tail', async ({ page }) => {
  test.setTimeout(3 * 60_000);
  await signIn(page);
  await openCluster(page);

  const row = page.locator(`[data-testid="service-row"][data-service="${RELEASE}-api"]`);
  await row.getByTestId('service-toggle').click();
  const podRow = row.getByTestId('pod-row').first();
  await expect(podRow).toBeVisible();
  const podName = await podRow.getAttribute('data-pod');
  await podRow.click();

  const drawer = page.getByTestId('pod-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByTestId('pod-drawer-name')).toHaveText(podName!);
  await expect(drawer.getByTestId('pod-container').first()).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByTestId('pod-events')).toBeVisible();
  await expect(drawer.getByTestId('pod-event').or(drawer.getByTestId('pod-events-empty')).first()).toBeVisible();

  const logs = drawer.getByTestId('pod-logs');
  await expect(logs).toBeVisible({ timeout: 30_000 });
  // the api writes a line per request, so a real tail has many lines and no escaped newlines
  await expect.poll(async () => Number(await logs.getAttribute('data-lines')), { timeout: 30_000 }).toBeGreaterThan(5);
  await expect(logs).not.toContainText(String.fromCharCode(92) + 'n2026-');
  await expect(logs).not.toContainText(String.fromCharCode(27));
  await drawer.getByTestId('pod-logs-lines').selectOption('100');
  await expect.poll(async () => Number(await logs.getAttribute('data-lines'))).toBeLessThanOrEqual(100);

  // the drawer is linkable and closes with Escape
  await expect(page).toHaveURL(new RegExp(`pod=${podName}`));
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
});

test('works on a phone', async ({ page }) => {
  test.setTimeout(3 * 60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  await openCluster(page);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page.getByTestId('cluster-node-count')).toBeVisible();
  await expect(page.getByTestId('node-card').first()).toBeVisible();
  const row = page.locator(`[data-testid="service-row"][data-service="${RELEASE}-api"]`);
  await row.scrollIntoViewIfNeeded();
  await expect(row.getByTestId('service-ready')).toBeVisible();

  await row.getByTestId('service-toggle').click();
  await row.getByTestId('pod-row').first().click();
  const drawer = page.getByTestId('pod-drawer');
  await expect(drawer).toBeVisible();
  const box = await drawer.boundingBox();
  expect(box!.width).toBeGreaterThanOrEqual(380);
  await expect(drawer.getByTestId('pod-logs')).toBeVisible({ timeout: 30_000 });
  await drawer.getByTestId('pod-drawer-close').click();
  await expect(drawer).toHaveCount(0);
});
