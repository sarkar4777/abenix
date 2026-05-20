import { test, type Page } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

const OUT_DIR = path.resolve(__dirname, '..', 'apps', 'web', 'public', 'docs-screenshots');

async function getToken(): Promise<string> {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const j = await r.json();
  return j.data?.access_token || j.access_token;
}

async function login(page: Page, token: string) {
  const meR = await fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const me = await meR.json().then((j) => j.data ?? j);
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
      localStorage.setItem('user', JSON.stringify(u || {}));
    } catch {}
  }, { t: token, u: me });
}

async function shoot(page: Page, name: string) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(OUT_DIR, name), fullPage: false });
}

test.beforeAll(() => { fs.mkdirSync(OUT_DIR, { recursive: true }); });

test('29-ml-use-in-agent.png — ML Models Use-in-Agent + Edit-metadata CTAs', async ({ page }) => {
  const token = await getToken();
  await login(page, token);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${BASE}/ml-models`);
  await page.waitForLoadState('domcontentloaded');
  const firstModel = page.locator('button').filter({ hasText: /v\d/ }).first();
  await firstModel.click();
  await page.waitForTimeout(800);
  await shoot(page, '29-ml-use-in-agent.png');
});

test('30-ml-k8s-deploy-config.png — k8s replicas + resource preset', async ({ page }) => {
  const token = await getToken();
  await login(page, token);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${BASE}/ml-models`);
  await page.waitForLoadState('domcontentloaded');
  const firstModel = page.locator('button').filter({ hasText: /v\d/ }).first();
  await firstModel.click();
  const k8s = page.getByTestId('deploy-type-k8s');
  if (await k8s.count() > 0) {
    await k8s.click();
    await page.waitForTimeout(400);
  }
  await shoot(page, '30-ml-k8s-deploy-config.png');
});

test('31-code-runner-xor.png — Code Runner zip vs git XOR cue', async ({ page }) => {
  const token = await getToken();
  await login(page, token);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${BASE}/code-runner`);
  await page.waitForLoadState('domcontentloaded');
  await page.getByTestId('code-source-git-url').fill('https://github.com/sarkar4777/abenix');
  await page.waitForTimeout(300);
  await shoot(page, '31-code-runner-xor.png');
});

test('32-kb-multi-upload.png — KB multi-file dropzone', async ({ page }) => {
  const token = await getToken();
  const kbR = await fetch(`${API}/api/knowledge-bases`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ name: `docs-kb-${Date.now()}`, description: 'documentation screenshot fixture', chunk_size: 1000, chunk_overlap: 200 }),
  });
  const kb = (await kbR.json()).data;
  try {
    await login(page, token);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/knowledge?id=${kb.id}`);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(800);
    await shoot(page, '32-kb-multi-upload.png');
  } finally {
    await fetch(`${API}/api/knowledge-bases/${kb.id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
  }
});

test('33-approvals-payload.png — structured approval payload renderer', async ({ page }) => {
  const token = await getToken();
  const r = await fetch(`${API}/api/approvals`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      title: 'docs sample — trade ticket approval',
      payload: { vendor: 'Acme Brokers', amount_usd: 2_400_000, risk_tier: 'high', counterparty_credit_rating: 'BBB', cargo: { product: 'propane', volume_mt: 25_000, corridor: 'USGC-NWE' } },
      required_signoffs: 1,
      expires_seconds: 600,
      gate_kind: 'docs',
    }),
  });
  const approval = (await r.json()).data;
  try {
    await login(page, token);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/approvals`);
    await page.waitForLoadState('domcontentloaded');
    const card = page.locator('div', { hasText: 'docs sample — trade ticket approval' }).first();
    await card.locator('button', { hasText: 'Payload, signoff history' }).first().click();
    await page.waitForTimeout(400);
    await shoot(page, '33-approvals-payload.png');
  } finally {
    await fetch(`${API}/api/approvals/${approval.id}/signoff`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ decision: 'deny', reason: 'docs screenshot teardown' }),
    });
  }
});

test('34-resource-share-dialog.png — generic share dialog', async ({ page }) => {
  const token = await getToken();
  await login(page, token);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${BASE}/ml-models`);
  await page.waitForLoadState('domcontentloaded');
  const firstModel = page.locator('button').filter({ hasText: /v\d/ }).first();
  await firstModel.click();
  await page.getByTestId('ml-share').click();
  await page.waitForTimeout(400);
  await shoot(page, '34-resource-share-dialog.png');
});
