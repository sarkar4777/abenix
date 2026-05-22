import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const API_URL = process.env.API_URL || 'http://localhost:8001';
const BASE_URL = process.env.BASE_URL || 'http://localhost:3001';
const uid = () => Math.random().toString(36).slice(2, 8);

const TEST_EMAIL = `ciq-metals-${uid()}@test.com`;
const TEST_PASSWORD = 'Metals!2026';
const TEST_NAME = 'Metals Test User';

const CONTRACTS_DIR = path.resolve(__dirname, '..', 'test-contracts');
const DORE_CONTRACT = 'precious_metals_dore_intake.txt';

test.describe.serial('Precious Metals module — end-to-end', () => {
  let token: string;
  let contractId: string;

  test('1. register a user via the ContractIQ API', async ({ request }) => {
    const resp = await request.post(`${API_URL}/api/contractiq/auth/register`, {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD, full_name: TEST_NAME, organization: 'Metals Test Co' },
    });
    expect(resp.status()).toBeLessThan(300);
    const body = await resp.json();
    expect(body.data?.access_token).toBeTruthy();
    token = body.data.access_token;
  });

  test('2. upload the dore-intake test contract', async ({ request }) => {
    const filePath = path.join(CONTRACTS_DIR, DORE_CONTRACT);
    expect(fs.existsSync(filePath)).toBe(true);

    const form = new FormData();
    const fileBlob = new Blob([fs.readFileSync(filePath)], { type: 'text/plain' });
    form.append('file', fileBlob, DORE_CONTRACT);

    const resp = await request.post(`${API_URL}/api/contractiq/contracts/upload`, {
      headers: { Authorization: `Bearer ${token}` },
      multipart: {
        title: 'Dore Intake and Refining Agreement',
        contract_type: 'ppa',
        counterparty_a: 'Andean Prima Mining S.A.',
        counterparty_b: 'Helvetia Metals Refining AG',
        file: { name: DORE_CONTRACT, mimeType: 'text/plain', buffer: fs.readFileSync(filePath) },
      },
    });
    expect(resp.status()).toBeLessThan(300);
    const body = await resp.json();
    contractId = body.data?.contract_id || body.data?.id;
    expect(contractId).toBeTruthy();
  });

  test('3. trigger standard extraction and wait for the contract to become analyzed', async ({ request }) => {
    test.setTimeout(180_000);
    // extract streams SSE — fire with a tight timeout so the request returns
    // immediately. The server keeps extracting in the background.
    try {
      await request.post(`${API_URL}/api/contractiq/contracts/${contractId}/extract`, {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 2000,
      });
    } catch (_e) {}
    for (let i = 0; i < 60; i++) {
      const r = await request.get(`${API_URL}/api/contractiq/contracts/${contractId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const j = await r.json();
      if (j.data?.status === 'analyzed' || j.data?.status === 'error') break;
      await new Promise((res) => setTimeout(res, 3000));
    }
    const r = await request.get(`${API_URL}/api/contractiq/contracts/${contractId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect((await r.json()).data?.status).toBe('analyzed');
  });

  test('4. metals overview returns a zero-state without crashing', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/metals/overview`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBeLessThan(300);
    const j = await r.json();
    expect(j.data).toBeTruthy();
    expect(j.data.contracts_with_extraction).toBe(0);
  });

  test('5. run the metals extractor on the contract', async ({ request }) => {
    test.setTimeout(300_000);
    const r = await request.post(
      `${API_URL}/api/contractiq/metals/contracts/${contractId}/extract`,
      { headers: { Authorization: `Bearer ${token}` }, timeout: 280_000 },
    );
    expect(r.status()).toBeLessThan(300);
    const j = await r.json();
    expect(j.data?.contract_id).toBeTruthy();
    // Real LLMs vary on which fields they populate. Require at least 4 of
    // the headline fields to be non-null so we know context-injection +
    // parsing both worked.
    const populated = [
      j.data?.material, j.data?.loco, j.data?.pricing_reference,
      j.data?.settlement_currency, j.data?.good_delivery_standard,
      j.data?.assay_tolerance_pct, j.data?.material_form,
    ].filter((v) => v != null && v !== '').length;
    console.log('  populated headline fields:', populated);
    expect(populated).toBeGreaterThanOrEqual(4);
  });

  test('6. metals overview now reports the extraction', async ({ request }) => {
    const r = await request.get(`${API_URL}/api/contractiq/metals/overview`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const j = await r.json();
    expect(j.data?.contracts_with_extraction).toBeGreaterThanOrEqual(1);
  });

  test('7. compliance audit produces a verdict list', async ({ request }) => {
    test.setTimeout(600_000);
    const r = await request.post(
      `${API_URL}/api/contractiq/metals/contracts/${contractId}/compliance-audit`,
      { headers: { Authorization: `Bearer ${token}` }, timeout: 580_000 },
    );
    expect(r.status()).toBeLessThan(300);
    const j = await r.json();
    expect(Array.isArray(j.data?.verdicts)).toBe(true);
    expect(j.data.verdicts.length).toBeGreaterThan(0);
  });

  test('8. dispute risk scorer produces a tier and expected loss', async ({ request }) => {
    test.setTimeout(300_000);
    const r = await request.post(
      `${API_URL}/api/contractiq/metals/contracts/${contractId}/dispute-risk`,
      { headers: { Authorization: `Bearer ${token}` }, timeout: 280_000 },
    );
    expect(r.status()).toBeLessThan(300);
    const j = await r.json();
    expect(j.data?.contract_id).toBeTruthy();
    expect(['low', 'elevated', 'high']).toContain(j.data?.tier);
    expect(typeof j.data?.expected_loss_usd).toBe('number');
    expect(j.data.expected_loss_usd).toBeGreaterThan(0);
  });

  async function gotoWithRetry(page: any, url: string, attempts = 3) {
    for (let i = 0; i < attempts; i++) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        return;
      } catch (e) {
        if (i === attempts - 1) throw e;
        await new Promise((res) => setTimeout(res, 2000));
      }
    }
  }

  test('9. features tour page renders for the user', async ({ page }) => {
    await gotoWithRetry(page, `${BASE_URL}/`);
    await page.evaluate(([t, e]) => {
      try {
        localStorage.setItem('contractiq_token', t);
        localStorage.setItem('contractiq_user', JSON.stringify({ email: e }));
      } catch (_e) {}
    }, [token, TEST_EMAIL]);
    await gotoWithRetry(page, `${BASE_URL}/features`);
    await expect(page.getByText('Every feature, every agent, every output')).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('Precious Metals', { exact: false }).first()).toBeVisible();
  });

  test('10. metals hub page renders for the authenticated user', async ({ page }) => {
    await gotoWithRetry(page, `${BASE_URL}/`);
    await page.evaluate(([t, e]) => {
      try {
        localStorage.setItem('contractiq_token', t);
        localStorage.setItem('contractiq_user', JSON.stringify({ email: e }));
      } catch (_e) {}
    }, [token, TEST_EMAIL]);
    await gotoWithRetry(page, `${BASE_URL}/metals`);
    await expect(page.getByRole('heading', { name: /Precious Metals/i })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('Metals Extraction').first()).toBeVisible();
    await expect(page.getByText('Refiner Watch').first()).toBeVisible();
  });
});
