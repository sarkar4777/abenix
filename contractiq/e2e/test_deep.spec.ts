
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const API_URL = process.env.API_URL || 'http://localhost:8001';
const BASE_URL = process.env.BASE_URL || 'http://localhost:3001';
const uid = () => Math.random().toString(36).slice(2, 8);

// Test user credentials
const TEST_EMAIL = `ciq-deep-${uid()}@test.com`;
const TEST_PASSWORD = 'DeepTest!2026';
const TEST_NAME = 'Deep Test User';

// Contract files
const TEST_CONTRACTS_DIR = path.resolve(__dirname, '..', 'test-contracts');

test.describe.serial('ContractIQ Deep E2E', () => {
  let token: string;
  let contractIds: string[] = [];

  // ─── 1. Authentication ──────────────────────────────────────────────

  test('1.1 Register a new user via API', async ({ request }) => {
    const resp = await request.post(`${API_URL}/api/contractiq/auth/register`, {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD, full_name: TEST_NAME, organization: 'DeepTest Corp' },
    });
    expect(resp.status()).toBeLessThan(300);
    const body = await resp.json();
    expect(body.data?.access_token).toBeTruthy();
    expect(body.data?.user?.email).toBe(TEST_EMAIL);
    expect(body.data?.user?.role).toBe('analyst');
    token = body.data.access_token;
  });

  test('1.2 Login via API', async ({ request }) => {
    const resp = await request.post(`${API_URL}/api/contractiq/auth/login`, {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD },
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.data?.access_token).toBeTruthy();
    token = body.data.access_token;
  });

  test('1.3 Get current user profile', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.data?.full_name).toBe(TEST_NAME);
    expect(body.data?.organization).toBe('DeepTest Corp');
  });

  test('1.4 Login page renders in browser', async ({ page }) => {
    await page.goto(`${BASE_URL}`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('text=ContractIQ').first()).toBeVisible();
    // Landing page is a marketing page with auth-as-modal — click "Sign In" to open it.
    await page.getByRole('button', { name: 'Sign In' }).first().click();
    await expect(page.locator('input[type="email"]')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('input[type="password"]')).toBeVisible();
  });

  test('1.5 Login via browser UI', async ({ page }) => {
    await page.goto(`${BASE_URL}`);
    await page.waitForLoadState('networkidle');

    // Open the auth modal
    await page.getByRole('button', { name: 'Sign In' }).first().click();
    await expect(page.locator('input[type="email"]')).toBeVisible({ timeout: 5000 });

    // Fill login form
    await page.fill('input[type="email"]', TEST_EMAIL);
    await page.fill('input[type="password"]', TEST_PASSWORD);

    // Click the form submit button (not the tab)
    await page.locator('form button[type="submit"], form button:has-text("Sign In")').last().click();

    // Should redirect to dashboard
    await page.waitForURL('**/dashboard', { timeout: 10000 });
    await expect(page.locator('text=Dashboard').first()).toBeVisible();
  });

  // ─── 2. Upload & Extraction ─────────────────────────────────────────

  test('2.1 Upload Solar PPA via API', async ({ request }) => {
    const filePath = path.join(TEST_CONTRACTS_DIR, 'solar_ppa_uae_250mw.txt');
    if (!fs.existsSync(filePath)) {
      test.skip();
      return;
    }

    const resp = await request.post(`${API_URL}/api/contractiq/contracts/upload`, {
      headers: { Authorization: `Bearer ${token}` },
      multipart: {
        file: { name: 'solar_ppa_uae_250mw.txt', mimeType: 'text/plain', buffer: fs.readFileSync(filePath) },
        title: 'Solar PPA UAE 250MW',
        contract_type: 'ppa',
        counterparty_a: 'Al Dhafra Solar Energy',
        counterparty_b: 'Abu Dhabi Distribution Company',
      },
    });
    expect(resp.status()).toBeLessThan(300);
    const body = await resp.json();
    expect(body.data?.id).toBeTruthy();
    expect(body.data?.status).toBe('uploaded');
    expect(body.data?.page_count).toBeGreaterThan(0);
    contractIds.push(body.data.id);
  });

  test('2.2 Trigger extraction and wait for completion', async ({ request }) => {
    if (!contractIds[0]) { test.skip(); return; }

    // Trigger extraction (SSE endpoint)
    const resp = await request.post(`${API_URL}/api/contractiq/contracts/${contractIds[0]}/extract`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 120000,
    });
    expect(resp.status()).toBe(200);

    // Poll until analyzed (extraction may still be streaming)
    let status = 'uploaded';
    for (let i = 0; i < 20; i++) {
      await new Promise(r => setTimeout(r, 3000));
      const check = await request.get(`${API_URL}/api/contractiq/contracts/${contractIds[0]}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await check.json();
      status = body.data?.status || 'uploaded';
      if (status === 'analyzed') break;
    }
    expect(status).toBe('analyzed');
  });

  test('2.3 Upload Wind PPA via API', async ({ request }) => {
    const filePath = path.join(TEST_CONTRACTS_DIR, 'wind_ppa_uk_350mw.txt');
    if (!fs.existsSync(filePath)) { test.skip(); return; }

    const resp = await request.post(`${API_URL}/api/contractiq/contracts/upload`, {
      headers: { Authorization: `Bearer ${token}` },
      multipart: {
        file: { name: 'wind_ppa_uk_350mw.txt', mimeType: 'text/plain', buffer: fs.readFileSync(filePath) },
        title: 'Wind PPA UK 350MW',
        contract_type: 'ppa',
      },
    });
    const body = await resp.json();
    expect(body.data?.id).toBeTruthy();
    contractIds.push(body.data.id);

    // Extract and poll
    await request.post(`${API_URL}/api/contractiq/contracts/${body.data.id}/extract`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 120000,
    });
    for (let i = 0; i < 20; i++) {
      await new Promise(r => setTimeout(r, 3000));
      const check = await request.get(`${API_URL}/api/contractiq/contracts/${body.data.id}`, { headers: { Authorization: `Bearer ${token}` } });
      if ((await check.json()).data?.status === 'analyzed') break;
    }
  });

  test('2.4 Upload Gas Supply Agreement via API', async ({ request }) => {
    const filePath = path.join(TEST_CONTRACTS_DIR, 'gas_supply_agreement_eu.txt');
    if (!fs.existsSync(filePath)) { test.skip(); return; }

    const resp = await request.post(`${API_URL}/api/contractiq/contracts/upload`, {
      headers: { Authorization: `Bearer ${token}` },
      multipart: {
        file: { name: 'gas_supply_agreement_eu.txt', mimeType: 'text/plain', buffer: fs.readFileSync(filePath) },
        title: 'EU Gas Supply Agreement',
        contract_type: 'gas',
      },
    });
    const body = await resp.json();
    expect(body.data?.id).toBeTruthy();
    contractIds.push(body.data.id);

    await request.post(`${API_URL}/api/contractiq/contracts/${body.data.id}/extract`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 120000,
    });
    for (let i = 0; i < 20; i++) {
      await new Promise(r => setTimeout(r, 3000));
      const check = await request.get(`${API_URL}/api/contractiq/contracts/${body.data.id}`, { headers: { Authorization: `Bearer ${token}` } });
      if ((await check.json()).data?.status === 'analyzed') break;
    }
  });

  // ─── 3. Data Quality Validation ─────────────────────────────────────

  test('3.1 Verify extraction produced clauses', async ({ request }) => {
    if (!contractIds[0]) { test.skip(); return; }

    const resp = await request.get(`${API_URL}/api/contractiq/contracts/${contractIds[0]}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await resp.json();
    const contract = body.data;

    expect(contract.status).toBe('analyzed');
    expect(contract.clauses.length).toBeGreaterThanOrEqual(5);
    expect(contract.extracted_data.length).toBeGreaterThanOrEqual(5);
    expect(contract.risk_analyses.length).toBeGreaterThanOrEqual(3);

    // Validate clause structure
    for (const clause of contract.clauses) {
      expect(clause.title).toBeTruthy();
      expect(clause.type).toBeTruthy();
      expect(['low', 'medium', 'high', 'critical']).toContain(clause.risk_level);
    }

    // Validate risk analyses
    for (const risk of contract.risk_analyses) {
      expect(risk.category).toBeTruthy();
      expect(risk.score).toBeGreaterThanOrEqual(0);
      expect(risk.score).toBeLessThanOrEqual(100);
      expect(risk.description).toBeTruthy();
    }
  });

  test('3.2 Verify contract metadata was extracted', async ({ request }) => {
    if (!contractIds[0]) { test.skip(); return; }

    const resp = await request.get(`${API_URL}/api/contractiq/contracts/${contractIds[0]}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const contract = resp.json().then(b => b.data);
    const c = await contract;

    // Should have extracted parties
    expect(c.counterparty_a).toBeTruthy();
    expect(c.counterparty_b).toBeTruthy();

    // Should have risk score
    expect(c.risk_score).toBeGreaterThan(0);
    expect(c.risk_score).toBeLessThanOrEqual(100);
  });

  test('3.3 All 3 contracts are analyzed', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/contracts?limit=100`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await resp.json();
    const analyzed = (body.data || []).filter((c: any) => c.status === 'analyzed');
    expect(analyzed.length).toBeGreaterThanOrEqual(3);
  });

  // ─── 4. Dashboard ───────────────────────────────────────────────────

  test('4.1 Portfolio analytics API returns rich data', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/analytics/portfolio`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    const data = body.data;

    expect(data.total_contracts).toBeGreaterThanOrEqual(3);
    expect(data.total_capacity_mw).toBeGreaterThan(0);
    expect(data.avg_risk_score).toBeGreaterThan(0);
    expect(data.by_type.length).toBeGreaterThan(0);
    expect(data.risk_by_category.length).toBeGreaterThan(0);
    expect(data.contracts.length).toBeGreaterThanOrEqual(3);
    expect(data.clause_distribution.length).toBeGreaterThan(0);
    expect(data.upcoming_events.length).toBeGreaterThan(0);
  });

  test('4.2 Dashboard page renders with charts', async ({ page }) => {
    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));
    await page.goto(`${BASE_URL}/dashboard`);
    await page.waitForLoadState('networkidle');

    // KPI cards should show real data
    await expect(page.locator('text=Total Contracts').first()).toBeVisible();
    await expect(page.locator('text=Total Capacity').first()).toBeVisible();
    await expect(page.locator('text=Portfolio Value').first()).toBeVisible();

    // Charts should render (recharts renders SVGs)
    await page.waitForTimeout(2000); // Wait for chart animation
    const svgs = await page.locator('.recharts-wrapper svg').count();
    expect(svgs).toBeGreaterThan(0);
  });

  // ─── 5. Contracts List ──────────────────────────────────────────────

  test('5.1 Contracts list page loads with data', async ({ page }) => {
    // Set auth token
    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    await page.goto(`${BASE_URL}/contracts`);
    await page.waitForLoadState('networkidle');

    // Should show contracts
    await expect(page.locator('text=My Contracts').first()).toBeVisible();

    // Quick stats bar should show
    await expect(page.locator('text=Total Capacity').first()).toBeVisible();
  });

  test('5.2 Search filters contracts', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/contracts?search=Solar`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await resp.json();
    expect(body.data.length).toBeGreaterThanOrEqual(1);
    expect(body.data[0].title).toContain('Solar');
  });

  test('5.3 Type filter works', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/contracts?contract_type=gas`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await resp.json();
    for (const c of body.data) {
      expect(c.contract_type).toBe('gas');
    }
  });

  test('5.4 Sort by risk works', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/contracts?sort=risk`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await resp.json();
    const scores = body.data.filter((c: any) => c.risk_score != null).map((c: any) => c.risk_score);
    // Should be sorted descending
    for (let i = 1; i < scores.length; i++) {
      expect(scores[i]).toBeLessThanOrEqual(scores[i - 1]);
    }
  });

  // ─── 6. Contract Detail ─────────────────────────────────────────────

  test('6.1 Contract detail page loads with all tabs', async ({ page }) => {
    if (!contractIds[0]) { test.skip(); return; }

    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    await page.goto(`${BASE_URL}/contracts/${contractIds[0]}`);
    await page.waitForLoadState('networkidle');

    // Header should show contract title
    await expect(page.locator('text=Solar PPA').first()).toBeVisible({ timeout: 10000 });

    // All 7 tabs should exist
    const tabs = ['Overview', 'Clauses', 'Assets', 'Risk Analysis', 'Events', 'Extracted Data', 'Chat'];
    for (const tab of tabs) {
      await expect(page.locator(`button:has-text("${tab}")`)).toBeVisible();
    }
  });

  test('6.2 Clauses tab shows extracted clauses', async ({ page }) => {
    if (!contractIds[0]) { test.skip(); return; }

    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    await page.goto(`${BASE_URL}/contracts/${contractIds[0]}`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    // Click Clauses tab
    await page.locator('button:has-text("Clauses")').click();
    await page.waitForTimeout(1000);

    // Should show clause cards with risk levels
    // Look for risk level badges which are always present on clause cards
    const clauseCards = await page.locator('text=/low|medium|high|critical/i').count();
    expect(clauseCards).toBeGreaterThan(0);
  });

  test('6.3 Risk Analysis tab shows radar chart', async ({ page }) => {
    if (!contractIds[0]) { test.skip(); return; }

    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    await page.goto(`${BASE_URL}/contracts/${contractIds[0]}`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    await page.locator('button:has-text("Risk Analysis")').click();
    await page.waitForTimeout(1500);

    // Risk content should render — either recharts wrapper or risk score text
    const recharts = await page.locator('.recharts-wrapper').count();
    const scoreText = await page.locator('text=/\\/100/').count();
    expect(recharts + scoreText).toBeGreaterThan(0);
  });

  // ─── 7. Contract Comparison ─────────────────────────────────────────

  test('7.1 Compare API works', async ({ request }) => {
    if (contractIds.length < 2) { test.skip(); return; }

    const resp = await request.post(`${API_URL}/api/contractiq/compare`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { contract_ids: contractIds.slice(0, 2), comparison_type: 'side_by_side' },
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.data?.contracts?.length).toBe(2);
  });

  test('7.2 Compare page loads', async ({ page }) => {
    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    await page.goto(`${BASE_URL}/compare`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('text=Contract Comparison').first()).toBeVisible();
    // Should show selectable contract cards
    await expect(page.locator('text=Solar PPA').first()).toBeVisible({ timeout: 10000 });
  });

  // ─── 8. Chat ────────────────────────────────────────────────────────

  test('8.1 Chat API returns structured response', async ({ request }) => {
    const resp = await request.post(`${API_URL}/api/contractiq/chat`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { query: 'How many contracts do I have and what is the total capacity?' },
      timeout: 90000,
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.data?.answer).toBeTruthy();
    expect(body.data?.answer.length).toBeGreaterThan(50);
    expect(body.data?.contracts_analyzed).toBeGreaterThanOrEqual(3);
  });

  test('8.2 Chat page loads with suggestions', async ({ page }) => {
    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('text=Cross-Contract Intelligence').first()).toBeVisible();
    // Suggestion buttons should exist
    await expect(page.locator('text=curtailment').first()).toBeVisible({ timeout: 5000 });
  });

  // ─── 9. Market & Risk ──────────────────────────────────────────────

  test('9.1 Market data API returns exposure data', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/market-data`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 30000,
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.data?.timestamp).toBeTruthy();
    expect(body.data?.exposure?.contracts?.length).toBeGreaterThanOrEqual(3);
    expect(body.data?.exposure?.totals).toBeTruthy();
  });

  test('9.2 Market page loads with PnL data', async ({ page }) => {
    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    await page.goto(`${BASE_URL}/market`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    await expect(page.locator('text=Market & Risk Monitor').first()).toBeVisible();
    await expect(page.locator('text=Annual PnL').first()).toBeVisible();
  });

  // ─── 10. Help Page ──────────────────────────────────────────────────

  test('10.1 Help page loads with all sections', async ({ page }) => {
    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    await page.goto(`${BASE_URL}/help`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('text=ContractIQ Documentation').first()).toBeVisible();

    // Check that key sections exist (updated for rewritten help page).
    const sections = [
      'Getting Started',
      'Supported Contract Types',
      'Agentic Workflows',
      'Contract Upload',
      'Architecture',
      'Generic Platform Tools',
      'Market & Risk Monitor',
      'Cross-Contract Chat',
      'Troubleshooting',
    ];
    for (const section of sections) {
      await expect(page.locator(`text=${section}`).first()).toBeVisible();
    }
  });

  // ─── 11. Cognify Status ─────────────────────────────────────────────

  test('11.1 Cognify status endpoint works', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/cognify-status`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.data?.kb_id).toBeTruthy();
    expect(body.data?.total_analyzed_contracts).toBeGreaterThanOrEqual(3);
  });

  // ─── 12. Alerts API ─────────────────────────────────────────────────

  test('12.1 Alerts endpoint returns (may be empty)', async ({ request }) => {
    const resp = await request.get(`${API_URL}/api/contractiq/alerts`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(Array.isArray(body.data)).toBe(true);
  });

  // ─── 13. Deep Extraction ────────────────────────────────────────────

  test('13.1 Deep extraction endpoint exists', async ({ request }) => {
    if (!contractIds[0]) { test.skip(); return; }

    // Just check the endpoint returns 200 (actual extraction takes too long for CI)
    const resp = await request.post(`${API_URL}/api/contractiq/contracts/${contractIds[0]}/deep-extract`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 180000,
    });
    // Should start streaming (200) or return data
    expect(resp.status()).toBe(200);
  });

  // ─── 14. Delete & Cleanup ──────────────────────────────────────────

  test('14.1 Delete a contract', async ({ request }) => {
    if (!contractIds[0]) { test.skip(); return; }

    const resp = await request.delete(`${API_URL}/api/contractiq/contracts/${contractIds[0]}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.data?.deleted).toBe(true);

    // Verify it's gone
    const checkResp = await request.get(`${API_URL}/api/contractiq/contracts/${contractIds[0]}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const checkBody = await checkResp.json();
    expect(checkBody.error).toBeTruthy();
  });

  // ─── 15. Navigation & Layout ────────────────────────────────────────

  test('15.1 Sidebar navigation works across all pages', async ({ page }) => {
    await page.goto(`${BASE_URL}`);
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);
    await page.evaluate(() => localStorage.setItem('contractiq_user', JSON.stringify({ full_name: 'Test', email: 'test@test.com' })));

    const pages = [
      { nav: 'Dashboard', url: '/dashboard', check: 'Portfolio Analytics' },
      { nav: 'Upload Contract', url: '/upload', check: 'Upload Contract' },
      { nav: 'My Contracts', url: '/contracts', check: 'My Contracts' },
      { nav: 'Compare', url: '/compare', check: 'Contract Comparison' },
      { nav: 'Chat', url: '/chat', check: 'Cross-Contract Intelligence' },
      { nav: 'Help', url: '/help', check: 'ContractIQ Documentation' },
    ];

    for (const p of pages) {
      await page.goto(`${BASE_URL}${p.url}`);
      await page.waitForLoadState('networkidle');
      await expect(page.locator(`text=${p.check}`).first()).toBeVisible({ timeout: 10000 });
    }
  });
});
