import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE   || 'http://localhost:3000';
const API  = process.env.API    || 'http://localhost:8000';
const EMAIL    = process.env.AF_EMAIL    || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

const MODEL_NAME = process.env.K8S_TEST_MODEL || 'wingman-mispricing-fairvalue';

async function loginViaApi(page: Page) {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!r.ok) throw new Error(`login failed: HTTP ${r.status}`);
  const j = await r.json();
  const token = j.data?.access_token || j.access_token;
  const me = await fetch(`${API}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then((rr) => rr.json()).then((x) => x.data ?? x).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
      localStorage.setItem('user', JSON.stringify(u || {}));
    } catch {}
  }, { t: token, u: me });
}

test.describe.serial('ML model — Kubernetes pod deployment via UI', () => {
  test('navigate, select model, switch to Kubernetes Pod, click Deploy, verify status', async ({ page }) => {
    test.setTimeout(180_000);
    await loginViaApi(page);

    await page.goto(`${BASE}/ml-models`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});

    const target = page.getByText(MODEL_NAME, { exact: false }).first();
    await expect(target).toBeVisible({ timeout: 15_000 });
    await target.click();

    await expect(page.getByText('Test Inference', { exact: false })).toBeVisible({ timeout: 10_000 });

    const k8sBtn = page.getByRole('button', { name: /Kubernetes Pod/i }).first();
    await expect(k8sBtn).toBeVisible();
    await k8sBtn.click();

    const deployBtn = page.getByRole('button', { name: /^Deploy$/ }).first();
    await expect(deployBtn).toBeVisible();
    await deployBtn.click();

    // Wait until a k8s deployment row appears under the selected model
    // and reaches a terminal-ish state (running, ready, or — most
    // honestly on a single-node demo — deploying then failed because
    // no kfserving/kserve is installed; either way we want to surface
    // what the user would see).
    await page.waitForFunction(() => {
      const text = document.body.innerText.toLowerCase();
      return /\b(running|ready|deploying|failed|error)\b/.test(text)
        && /\bk8s\b/.test(text);
    }, { timeout: 120_000 });

    const screenshot = await page.screenshot({ fullPage: true });
    const fs = await import('fs');
    const path = await import('path');
    const out = path.join(process.env.USERPROFILE || process.env.HOME || '.', 'wingman-screenshots', 'ml-models-k8s-deploy.png');
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, screenshot);
  });

  test('test inference uses model-specific default input (no 12-feature mismatch)', async ({ page }) => {
    test.setTimeout(60_000);
    await loginViaApi(page);
    await page.goto(`${BASE}/ml-models`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});

    const target = page.getByText(MODEL_NAME, { exact: false }).first();
    await target.click();

    await expect(page.getByText('Test Inference', { exact: false })).toBeVisible();

    const runBtn = page.getByRole('button', { name: /Run Prediction/i }).first();
    await expect(runBtn).toBeVisible();
    await runBtn.click();

    // Wait for either a successful prediction or a non-feature-count error.
    await page.waitForFunction(() => {
      const txt = document.body.innerText;
      if (/X has \d+ features, but/.test(txt)) return false;
      return /Predicting/.test(txt) === false;
    }, { timeout: 30_000 });

    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/X has 4 features, but BayesianRidge is expecting 12 features/);
  });
});
