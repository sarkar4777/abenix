/**
 * Source Watch through the UI: add a source with live validation and a test fetch, check it, read the
 * snapshot, see a change and its diff, pause and resume, and the private address refusal.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_source_watch.spec.ts --workers=1
 *
 * Needs outbound internet from the API pod. STABLE_URL (default https://example.com) must not change between
 * two checks. CHANGING_URL (default https://httpbin.org/uuid) must return different JSON on every request, any
 * httpbin-style /uuid endpoint works, for example a local `docker run -p 8088:80 kennethreitz/httpbin` with
 * CHANGING_URL=http://host:8088/uuid and SOURCE_WATCH_ALLOW_PRIVATE_TARGETS=1 on the API.
 */
import { test, expect, type Page } from '@playwright/test';
import { openFromSidebar } from './helpers/sidebar';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const STABLE_URL = process.env.STABLE_URL || 'https://example.com';
const CHANGING_URL = process.env.CHANGING_URL || 'https://httpbin.org/uuid';
const STABLE = 'UAT stable page';
const CHANGING = 'UAT changing feed';

let token = '';

async function login(page: Page) {
  const res = await page.request.post(`${API}/api/auth/login`, { data: ADMIN });
  expect(res.ok(), `login ${ADMIN.email}`).toBeTruthy();
  token = (await res.json())?.data?.access_token;
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('refresh_token', t); }, token);
}

async function api(page: Page, method: string, p: string, body?: unknown) {
  // one retry, a reused keep-alive socket can be closed under us
  const res = await page.request.fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  }).catch(() => page.request.fetch(`${API}${p}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body),
  }));
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function visit(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function cleanUp(page: Page) {
  const r = await api(page, 'GET', '/api/sources');
  for (const s of r.json?.data || []) if (String(s.name).startsWith('UAT ')) await api(page, 'DELETE', `/api/sources/${s.id}`);
}

async function addSource(page: Page, name: string, url: string, kind?: string, selector?: string) {
  await visit(page, '/sources');
  await page.getByTestId(/source-add(-empty)?$/).first().click();
  await page.getByTestId('source-url').fill(url);
  await expect(page.getByTestId('source-url-check')).toContainText('can be watched', { timeout: 20_000 });
  await page.getByTestId('source-name').fill(name);
  if (kind) await page.getByTestId(`source-kind-${kind}`).click();
  if (selector) await page.getByTestId('source-selector').fill(selector);
  await page.getByTestId('source-test-fetch').click();
  await expect(page.getByTestId('source-preview')).toBeVisible({ timeout: 60_000 });
  await page.getByTestId('source-save').click();
  await expect(page.getByTestId('source-title')).toHaveText(name, { timeout: 20_000 });
}

test.describe.configure({ mode: 'serial' });
test.setTimeout(180_000);

test('Source Watch is in the sidebar and explains itself when empty', async ({ page }) => {
  await login(page);
  await cleanUp(page);
  await visit(page, '/dashboard');
  await openFromSidebar(page, '/sources');
  await expect(page.getByRole('heading', { name: 'Source Watch' })).toBeVisible();
  const empty = page.getByTestId('sources-empty');
  if (await empty.isVisible()) await expect(empty).toContainText('Nothing is being watched yet');
});

test('a private address is refused while typing', async ({ page }) => {
  await login(page);
  await visit(page, '/sources');
  await page.getByTestId(/source-add(-empty)?$/).first().click();
  await page.getByTestId('source-url').fill('not a url');
  await expect(page.getByTestId('source-url-check')).toContainText('https://');
  await page.getByTestId('source-url').fill('http://169.254.169.254/latest/meta-data');
  await expect(page.getByTestId('source-url-check')).toContainText('private', { timeout: 20_000 });
  await page.getByTestId('source-name').fill('UAT metadata');
  await expect(page.getByTestId('source-save')).toBeDisabled();
});

test('add a page, test fetch shows clean text, check now keeps a baseline then reports no change', async ({ page }) => {
  await login(page);
  await addSource(page, STABLE, STABLE_URL);
  await expect(page.getByTestId('source-detail-health')).toBeVisible();

  await page.getByTestId('source-check-now').click();
  await expect(page.getByTestId('source-notice')).toContainText(/baseline|no change/i, { timeout: 90_000 });

  await page.getByTestId('source-tab-snapshots').click();
  await expect(page.getByTestId('snapshot-timeline').locator('li')).toHaveCount(1);
  await page.getByTestId('snapshot-view').first().click();
  await expect(page.getByTestId('snapshot-text')).toContainText('for use in documentation examples');
  await expect(page.getByTestId('snapshot-text')).not.toContainText('<html');
  await page.keyboard.press('Escape');

  await page.getByTestId('source-check-now').click();
  await expect(page.getByTestId('source-notice')).toContainText('No change', { timeout: 90_000 });
  await expect(page.getByTestId('snapshot-timeline').locator('li')).toHaveCount(1);
});

test('a JSON source that changes shows a change with a side-by-side diff', async ({ page }) => {
  await login(page);
  await addSource(page, CHANGING, CHANGING_URL, 'json', '/uuid');

  // the scheduler may have taken the baseline already, so the first manual check can be the change
  await page.getByTestId('source-check-now').click();
  const notice = page.getByTestId('source-notice');
  await expect(notice).toContainText(/baseline|Changed/i, { timeout: 90_000 });
  if (!(await notice.innerText()).includes('Changed')) {
    await page.getByTestId('source-check-now').click();
    await expect(notice).toContainText('Changed', { timeout: 90_000 });
  }

  await page.getByTestId('source-tab-changes').click();
  expect(await page.getByTestId('change-list').locator('li').count()).toBeGreaterThan(0);
  const detail = page.getByTestId('change-detail');
  await expect(detail).toContainText('1 line added and 1 removed');
  await expect(page.getByTestId('diff-text').locator('mark').first()).toBeVisible();
  await page.getByTestId('diff-mode-unified').click();
  await expect(page.getByTestId('diff-text')).toContainText('"');

  const changes = await api(page, 'GET', '/api/sources/changes?limit=5');
  expect(changes.json.data.some((c: any) => c.source_name === CHANGING)).toBeTruthy();
});

test('pause with a reason, the list shows it, then resume', async ({ page }) => {
  await login(page);
  await visit(page, '/sources');
  await page.getByTestId(`source-row-${STABLE}`).click();
  await page.getByTestId('source-pause').click();
  await page.getByTestId('pause-reason').fill('UAT pause');
  await page.getByTestId('pause-confirm').click();
  await expect(page.getByTestId('source-detail-health')).toContainText('Paused');
  await expect(page.locator('body')).toContainText('UAT pause');

  await visit(page, '/sources');
  await expect(page.getByTestId(`source-row-${STABLE}`).getByTestId('source-health')).toContainText('Paused');

  await page.getByTestId(`source-row-${STABLE}`).click();
  await page.getByTestId('source-resume').click();
  await expect(page.getByTestId('source-detail-health')).not.toContainText('Paused');
});

test('agents can read the sources through the tools catalogue', async ({ page }) => {
  await login(page);
  const r = await api(page, 'GET', '/api/tools');
  const names = JSON.stringify(r.json?.data || r.json);
  for (const t of ['source_list', 'source_snapshot_get', 'source_diff', 'source_check']) expect(names).toContain(t);
});

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage();
  await login(page);
  await cleanUp(page);
  await page.close();
});
