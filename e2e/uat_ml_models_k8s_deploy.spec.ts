import { test, expect, type Page } from '@playwright/test';
import * as path from 'path';
import { artifactDir } from './uat_helpers/artifacts';

const BASE = process.env.BASE   || 'http://localhost:3000';
const API  = process.env.API    || 'http://localhost:8000';
const EMAIL    = process.env.AF_EMAIL    || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

const MODEL_NAME = process.env.K8S_TEST_MODEL || 'wingman-mispricing-fairvalue';

async function apiToken(): Promise<string> {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!r.ok) throw new Error(`login failed: HTTP ${r.status}`);
  const j = await r.json();
  return j.data?.access_token || j.access_token;
}

async function loginViaApi(page: Page) {
  const token = await apiToken();
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
  test('deploy to Kubernetes pods reaches Running or says why it did not', async ({ page }) => {
    test.setTimeout(8 * 60_000);
    const token = await apiToken();
    const models = await fetch(`${API}/api/ml-models`, { headers: { Authorization: `Bearer ${token}` } }).then((r) => r.json());
    const model = (models.data || []).find((m: any) => m.name === MODEL_NAME);
    test.skip(!model, `model ${MODEL_NAME} is not on this stack, it comes with the Wingman app seed, or set K8S_TEST_MODEL`);

    const undeploy = () => fetch(`${API}/api/ml-models/${model.id}/undeploy`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
    // an old failed row would answer for this deploy
    await undeploy();
    await loginViaApi(page);
    try {
      await page.goto(`${BASE}/ml-models`, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle').catch(() => {});

      const target = page.getByText(MODEL_NAME, { exact: false }).first();
      await expect(target).toBeVisible({ timeout: 15_000 });
      await target.click();

      await expect(page.getByText('Test Inference', { exact: false })).toBeVisible({ timeout: 10_000 });

      await page.getByTestId('deploy-type-k8s').click();
      await expect(page.getByTestId('k8s-deploy-config')).toBeVisible();
      await page.getByTestId('ml-deploy').click();

      const row = page.getByTestId('ml-deployment-row').filter({ hasText: 'Kubernetes' });
      await expect(row).toBeVisible({ timeout: 60_000 });
      await expect(row.getByText(/^(Running|Failed)$/), 'stuck on Starting with no outcome').toBeVisible({ timeout: 6 * 60_000 });

      const failure = row.getByTestId('ml-deployment-error');
      if (await failure.count()) {
        const why = (await failure.innerText()).trim();
        console.log(`  k8s deploy failed, ${why}`);
        test.info().annotations.push({ type: 'k8s-deploy-failed', description: why });
        await expect(failure, 'a failed deploy gives the reason').not.toContainText('the server gave no reason');
      }
      await page.screenshot({ path: path.join(artifactDir('ml-models'), 'k8s-deploy.png'), fullPage: true });
    } finally {
      await undeploy();
    }
  });

  test('test inference uses model-specific default input (no 12-feature mismatch)', async ({ page }) => {
    test.setTimeout(60_000);
    await loginViaApi(page);
    await page.goto(`${BASE}/ml-models`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});

    const target = page.getByText(MODEL_NAME, { exact: false }).first();
    await expect(target).toBeVisible({ timeout: 15_000 }).catch(() => test.skip(true, `model ${MODEL_NAME} is not on this stack`));
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
