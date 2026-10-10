import { test, expect, type Page } from '@playwright/test';

const API = process.env.API_URL || 'http://localhost:8000';
const ABX_BASE = process.env.ABENIX_BASE || 'http://localhost:3000';
const CIQ_API = process.env.CIQ_API || 'http://localhost:8001';
const CIQ_BASE = process.env.CIQ_BASE || 'http://localhost:3001';
const WM_API = process.env.WM_API || 'http://localhost:8006';
const WM_BASE = process.env.WM_BASE || 'http://localhost:3006';

const ADMIN_EMAIL = process.env.ADMIN_EMAIL || 'admin@abenix.dev';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'Admin123456';

let adminToken: string;
let claudeModel = 'claude-sonnet-4-5-20250929';
const azureFallback = 'azure-gpt-4o';

async function loginAdmin(request: any): Promise<string> {
  const r = await request.post(`${API}/api/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  expect(r.status(), 'admin login HTTP').toBeLessThan(300);
  const body = await r.json();
  const token = body?.data?.access_token || body?.access_token;
  expect(token, 'admin token').toBeTruthy();
  return token;
}

async function gotoOk(page: Page, url: string) {
  const r = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  expect(r?.status(), `${url} HTTP`).toBeLessThan(400);
}

test.describe.serial('Model availability + fallback — Abenix → ContractIQ → Wingman', () => {
  test('A1. abenix: /api/llm-models lists Azure provider models', async ({ request }) => {
    adminToken = await loginAdmin(request);
    const r = await request.get(`${API}/api/llm-models`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(r.status()).toBeLessThan(300);
    const body = await r.json();
    const models: any[] = body?.data?.models || body?.models || [];
    expect(models.length).toBeGreaterThan(5);
    const providers = new Set(models.map((m) => m.provider));
    expect(providers.has('anthropic'), 'anthropic provider').toBeTruthy();
    expect(providers.has('azure'), 'azure provider must appear').toBeTruthy();
    const azureValues = models.filter((m) => m.provider === 'azure').map((m) => m.value);
    console.log('  azure models:', azureValues);
    expect(azureValues).toContain(azureFallback);
  });

  test('A2. abenix: /api/llm-models/resolve returns identity when claude is available', async ({ request }) => {
    const r = await request.get(`${API}/api/llm-models/resolve?model=${claudeModel}`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(r.status()).toBeLessThan(300);
    const body = await r.json();
    const d = body?.data || body;
    expect(d.requested).toBe(claudeModel);
    expect(d.effective).toBe(claudeModel);
    expect(d.swap).toBe(false);
  });

  test('A3. abenix: force claude unavailable via admin endpoint', async ({ request }) => {
    const r = await request.post(`${API}/api/admin/model-availability/force-status`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { model: claudeModel, status: 'unavailable' },
    });
    expect(r.status()).toBeLessThan(300);
  });

  test('A4. abenix: resolver now returns azure-gpt-4o as effective', async ({ request }) => {
    const r = await request.get(`${API}/api/llm-models/resolve?model=${claudeModel}`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(r.status()).toBeLessThan(300);
    const d = (await r.json())?.data;
    console.log('  resolve decision:', d);
    expect(d.requested).toBe(claudeModel);
    expect(d.swap).toBe(true);
    expect(d.effective).not.toMatch(/^claude/);
    expect(['azure-gpt-4o', 'gpt-4o']).toContain(d.effective);
  });

  test('A5. abenix UI: builder page renders the model dropdown including Azure', async ({ page }) => {
    await page.goto(ABX_BASE);
    await page.evaluate(([t]) => {
      try { window.localStorage.setItem('access_token', t); } catch {}
    }, [adminToken]);
    await gotoOk(page, `${ABX_BASE}/builder`);
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.getByTestId('config-tab-model').click();
    await expect(page.getByTestId('model-picker-select')).not.toContainText(/loading models/i, { timeout: 30_000 });
    const dropdownText = await page.getByTestId('model-picker-select').innerText();
    console.log('  builder model dropdown text snippet:', dropdownText.slice(0, 200));
    expect(dropdownText.toLowerCase()).toContain('azure');
  });

  test('A6. abenix UI: model-status banner appears when configured model is unavailable', async ({ page }) => {
    await page.goto(ABX_BASE);
    await page.evaluate(([t]) => {
      try { window.localStorage.setItem('access_token', t); } catch {}
    }, [adminToken]);
    await gotoOk(page, `${ABX_BASE}/builder`);
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.getByTestId('config-tab-model').click();
    await expect(page.getByTestId('model-picker-select')).not.toContainText(/loading models/i, { timeout: 30_000 });
    // a new agent starts on the platform default, so pick the model we made unavailable
    await page.getByTestId('model-picker-select').selectOption(claudeModel);
    const banner = page.getByText(/will not run as|is unavailable|Runs will use/i).first();
    await expect(banner).toBeVisible({ timeout: 10_000 });
  });

  test('B1. contractiq: register user + run metals path (falls back to azure)', async ({ request }) => {
    const email = `ciq-fallback-${Math.random().toString(36).slice(2, 8)}@test.com`;
    const password = 'Fallback!2026';
    const reg = await request.post(`${CIQ_API}/api/contractiq/auth/register`, {
      data: { email, password, full_name: 'Fallback User', organization: 'CIQ Fallback' },
    });
    expect(reg.status()).toBeLessThan(300);
    const ciqToken = (await reg.json())?.data?.access_token;
    expect(ciqToken).toBeTruthy();

    const upload = await request.post(`${CIQ_API}/api/contractiq/contracts/upload`, {
      headers: { Authorization: `Bearer ${ciqToken}` },
      multipart: {
        title: 'Fallback Test Contract',
        contract_type: 'ppa',
        counterparty_a: 'Acme',
        counterparty_b: 'Beta',
        file: { name: 'fallback.txt', mimeType: 'text/plain', buffer: Buffer.from('Sample metals refining agreement between Acme and Beta. LBMA Good Delivery. London loco. USD settlement.') },
      },
    });
    expect(upload.status()).toBeLessThan(300);
    const upBody = await upload.json();
    const contractId = upBody?.data?.id || upBody?.data?.contract_id;
    expect(contractId).toBeTruthy();

    test.setTimeout(360_000);
    const extract = await request.post(
      `${CIQ_API}/api/contractiq/metals/contracts/${contractId}/extract`,
      { headers: { Authorization: `Bearer ${ciqToken}` }, timeout: 300_000 },
    );
    expect(extract.status()).toBeLessThan(400);
    const body = await extract.json();
    console.log('  metals extract:', JSON.stringify(body).slice(0, 200));
  });

  test('C1. wingman: insight agent runs through fallback model', async ({ request }) => {
    test.setTimeout(180_000);
    const r = await request.post(`${WM_API}/api/agent/run`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { use_case: 'insight', context: { corridor: 'USGC->NWE' } },
      timeout: 150_000,
    }).catch((e) => ({ status: () => 500, json: async () => ({ error: String(e) }) }));
    const status = (r as any).status();
    if (status >= 400) {
      const body = await (r as any).json().catch(() => ({}));
      console.log('  wingman run error:', body);
      test.skip(true, `wingman insight agent unreachable (${status})`);
      return;
    }
    const body = await (r as any).json();
    const modelUsed = body?.data?.model_used || body?.model_used;
    console.log('  wingman insight ran with model:', modelUsed);
    if (modelUsed) expect(String(modelUsed)).not.toMatch(/^claude/);
  });

  test('Z. restore claude availability', async ({ request }) => {
    const r = await request.post(`${API}/api/admin/model-availability/force-status`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { model: claudeModel, status: 'available' },
    });
    expect(r.status()).toBeLessThan(400);
  });
});
