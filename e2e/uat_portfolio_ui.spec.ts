/**
 * Portfolio schemas from the screens only.
 *
 *   1. sign in on the landing page form
 *   2. Portfolio Schemas   Try with a sample makes an Energy trading book with 40 trades the user owns
 *   3. Use in an agent     the builder opens with portfolio_energy_trading_book and a starter prompt, save and publish
 *   4. Chat                ask for the MWh bought at TTF, the answer must match the sample (11,200 MWh)
 *   5. Run page            the portfolio tool call is on the flight recorder
 *   6. Spreadsheet         upload a small CSV, rename a column, untick one, import, see the rows, delete with its table
 *
 * The API is only used to read state back for assertions and to clean up.
 *
 *   BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_portfolio_ui.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE || 'http://localhost:3100';
const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const RUN = Date.now().toString(36);
const AGENT = `Trading book assistant ${RUN}`;
const TOOL = 'portfolio_energy_trading_book';
const DOMAIN = `fleet_${RUN}`.replace(/[^a-z0-9_]/g, '');

const ids: { agent?: string } = {};

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1440, height: 900 } });

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function signIn(page: Page) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(ADMIN.email);
  await page.locator('#auth-password').fill(ADMIN.password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function api(page: Page, method: string, p: string) {
  const tok = await page.evaluate(() => localStorage.getItem('access_token') || '');
  const res = await page.request.fetch(`${API}${p}`, { method, headers: { Authorization: `Bearer ${tok}` } });
  let json: any = null;
  try { json = await res.json(); } catch {}
  return { status: res.status(), json };
}

async function chat(page: Page, message: string, timeoutMs = 300_000) {
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const before = await replies.count();
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: timeoutMs });
  const err = page.getByTestId('chat-error');
  if (await err.count()) throw new Error(`the run failed in chat: ${await err.innerText()}`);
  await expect(replies).toHaveCount(before + 1, { timeout: 30_000 });
  return replies.nth(before).innerText();
}

test.beforeEach(async ({ page }) => {
  page.on('dialog', (d) => d.accept());
  await signIn(page);
});

test('Try with a sample makes a trading book the user owns', async ({ page }) => {
  await go(page, '/portfolio-schemas');
  await expect(page.getByTestId('ps-howto')).toBeVisible();
  await page.getByTestId('ps-try-sample').click();
  const next = page.getByTestId('ps-next-step');
  await expect(next).toBeVisible({ timeout: 60_000 });
  await expect(next).toContainText('40 trades');
  await expect(page.locator('main')).toContainText(TOOL);
  // the rows table lists the user's own sample trades
  await expect(page.locator('main')).toContainText(/Showing \d+ of your 40 trades/, { timeout: 20_000 });
  await expect(page.locator('main')).toContainText('TRD-10');

  const list = await api(page, 'GET', '/api/portfolio-schemas');
  const s = (list.json?.data || []).find((x: any) => x.domain_name === 'energy_trading_book');
  expect(s?.source).toBe('spreadsheet');
  expect(s?.my_rows).toBe(40);
  const tools = await api(page, 'GET', '/api/tools');
  const ids_ = (tools.json?.data || []).map((t: any) => t.id);
  expect(ids_).toContain(TOOL);
});

test('Use in an agent opens the builder with the tool and a prompt, and it publishes', async ({ page }) => {
  await go(page, '/portfolio-schemas');
  await page.getByTestId('ps-card-energy_trading_book').click();
  await page.getByTestId('ps-use-in-agent').first().click();
  await page.waitForURL(new RegExp(`/builder\\?.*tool=${TOOL}`), { timeout: 20_000 });
  await expect(page.locator(`.react-flow__node[data-id="tool-${TOOL}"]`)).toBeVisible({ timeout: 20_000 });

  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(AGENT);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill('Answers questions about my power and gas trades from the trading book.');
  await page.getByTestId('builder-category').selectOption({ index: 1 });
  await page.getByTestId('config-tab-prompt').click();
  await expect(page.getByTestId('builder-system-prompt')).toHaveValue(new RegExp(TOOL));

  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  ids.agent = new URL(page.url()).searchParams.get('agent') || '';
  expect(ids.agent).toBeTruthy();
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-visibility-org').click();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });

  const a = await api(page, 'GET', `/api/agents/${ids.agent}`);
  expect(a.json.data.model_config.tools).toContain(TOOL);
});

test('the agent answers from the data and the portfolio call is on the run page', async ({ page }) => {
  test.setTimeout(8 * 60_000);
  await go(page, `/agents/${ids.agent}/chat`);
  const answer = await chat(page, 'What is the total volume in MWh I bought at the TTF hub? Give one number.');
  console.log(`\n--- answer ---\n${answer}\n---`);
  expect(answer.replace(/[,\s ]/g, '')).toMatch(/11200(\.0+)?/);

  const viewRun = page.getByTestId('chat-view-run').last();
  await expect(viewRun).toBeVisible({ timeout: 20_000 });
  await viewRun.click();
  await page.waitForURL(/\/executions\//, { timeout: 20_000 });
  await expect(page.locator(`[data-testid="tool-call"][data-tool="${TOOL}"]`).first()).toBeVisible({ timeout: 30_000 });
});

test('a spreadsheet becomes a schema, shows its rows and can be deleted with its table', async ({ page }) => {
  const csv = [
    'Vehicle ID,Make,Odometer (km),Last service,In service',
    'VAN-01,Ford,"120,500",2026-05-02,yes',
    'VAN-02,Renault,98000,2026-04-18,no',
    'VAN-03,Iveco,not read,2026-06-11,yes',
    'VAN-04,Ford,45210,2026-07-30,yes',
  ].join('\n');
  await go(page, '/portfolio-schemas');
  await page.getByTestId('ps-create-from-sheet').click();
  await page.getByTestId('ps-import-file-input').setInputFiles({ name: 'fleet.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });

  await expect(page.getByText('4 rows · 5 columns')).toBeVisible({ timeout: 30_000 });
  await page.locator('#ps-import-label').fill(`Fleet ${RUN}`);
  await page.locator('#ps-import-domain').fill(DOMAIN);
  await page.locator('#ps-import-nouns').fill('vans');
  await page.locator('#ps-import-noun').fill('van');
  // the odometer column holds one bad value, so the guess is text, set it to number
  await expect(page.getByLabel('Type for Odometer (km)')).toHaveValue('text');
  await page.getByLabel('Type for Odometer (km)').selectOption('number');
  await expect(page.getByLabel('Type for Last service')).toHaveValue('date');
  await expect(page.getByLabel('Type for In service')).toHaveValue('boolean');
  await page.getByLabel('Column name for Odometer (km)').fill('odometer');
  await page.getByLabel('Import Make').uncheck();
  await page.getByTestId('ps-import-submit').click();

  const done = page.getByTestId('ps-import-done');
  await expect(done).toBeVisible({ timeout: 60_000 });
  await expect(done).toContainText('Imported 3 rows');
  await expect(done).toContainText('Skipped 1');
  await done.getByText(/Why 1 row was skipped/).click();
  await expect(done).toContainText('"not read" in Odometer (km) is not a number');
  await expect(done.getByTestId('ps-use-in-agent')).toHaveAttribute('href', new RegExp(`tool=portfolio_${DOMAIN}`));

  await done.getByRole('button', { name: 'View the schema and my rows' }).click();
  await expect(page.locator('main')).toContainText('Showing 3 of your 3 vans', { timeout: 20_000 });
  await expect(page.locator('main')).toContainText('120,500');

  const list = await api(page, 'GET', '/api/portfolio-schemas');
  const s = (list.json?.data || []).find((x: any) => x.domain_name === DOMAIN);
  expect(Object.keys(s.schema_json.main_table.columns)).toEqual(expect.arrayContaining(['vehicle_id', 'odometer', 'last_service', 'in_service']));
  expect(Object.keys(s.schema_json.main_table.columns)).not.toContain('make');

  await page.getByRole('button', { name: `Delete Fleet ${RUN}` }).last().click();
  await page.getByTestId('ps-delete-drop-table').check();
  await page.getByTestId('ps-delete-confirm').click();
  await expect(page.getByTestId(`ps-card-${DOMAIN}`)).toHaveCount(0, { timeout: 20_000 });
  const after = await api(page, 'GET', '/api/portfolio-schemas');
  expect((after.json?.data || []).some((x: any) => x.domain_name === DOMAIN)).toBe(false);
});

test.afterAll(async ({ browser }) => {
  if (!ids.agent) return;
  const page = await browser.newPage();
  await signIn(page);
  await api(page, 'DELETE', `/api/agents/${ids.agent}`);
  await page.close();
});
