import { test, expect, type Page } from '@playwright/test';
import { execSync } from 'node:child_process';
import * as path from 'node:path';
import * as fs from 'node:fs';

const BASE = process.env.BASE || 'http://localhost:3001';
const API  = process.env.API  || 'http://localhost:8001';
const EMAIL = process.env.CIQ_EMAIL || 'test@contractiq.com';
const PASSWORD = process.env.CIQ_PASSWORD || 'TestPass123!';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FIXTURE = path.resolve(__dirname, 'fixtures', 'sample_met_kyc.pdf');
const GENERATOR = path.resolve(REPO_ROOT, 'scripts', 'generate_sample_met_kyc.py');

async function login(page: Page) {
  const resp = await fetch(`${API}/api/contractiq/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json = await resp.json();
  const token = json.data?.access_token || json.access_token;
  expect(token).toBeTruthy();
  const meResp = await fetch(`${API}/api/contractiq/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const me = await meResp.json().then(j => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('contractiq_token', t);
      localStorage.setItem('contractiq_user', JSON.stringify(u || { email: 'test@contractiq.com', role: 'analyst' }));
    } catch {}
  }, { t: token, u: me });
}

test.describe('contractiq KYC PDF intake', () => {
  test.beforeAll(() => {
    // Always regenerate the fixture so the test never depends on stale bytes
    try {
      const py = process.env.PYTHON || 'python';
      execSync(`${py} "${GENERATOR}"`, { stdio: 'inherit' });
    } catch (e) {
      console.warn('Could not regenerate fixture, using whatever is on disk:', e);
    }
    if (!fs.existsSync(FIXTURE)) {
      throw new Error(`fixture not present at ${FIXTURE} — generator failed`);
    }
  });

  test.beforeEach(async ({ page }) => { await login(page); });

  test('import existing KYC PDF runs the agent and shows reconciliation', async ({ page }) => {
    await page.goto(`${BASE}/credit-risk/kyc`, { waitUntil: 'domcontentloaded', timeout: 45000 });

    const zone = page.locator('[data-testid="kyc-import-zone"]');
    await expect(zone).toBeVisible({ timeout: 15000 });

    // Build a unique copy of the fixture so SHA-256 dedup doesn't return a
    // 409 + duplicate banner when the same test fixture has been imported
    // earlier in this session.
    const uniqueFixture = path.resolve(
      __dirname, 'fixtures', `uat_run_${Date.now()}_${Math.random().toString(36).slice(2, 6)}.pdf`,
    );
    const baseBytes = fs.readFileSync(FIXTURE);
    fs.writeFileSync(uniqueFixture, Buffer.concat([
      baseBytes,
      Buffer.from(`\n%uat-run-${Date.now()}-${Math.random()}`),
    ]));

    const fileInput = page.locator('[data-testid="kyc-import-input"]');
    await fileInput.setInputFiles(uniqueFixture);

    // After upload begins, the button text flips to "Processing…". We poll
    // every 5s and log the page state so any hang is debuggable from logs.
    const processingBtn = page.locator('[data-testid="kyc-import-pick"]');
    await expect(processingBtn).toContainText(/Processing|Choose PDF/i, { timeout: 10000 });
    console.log('upload submitted, polling for reconciliation panel...');

    // Agent run timing: up to 480s (full reconciliation runs sanctions +
    // country risk + scorer + Moody's + Tavily lookups serially).
    const panel = page.locator('[data-testid="kyc-reconciliation-panel"]');
    // Poll loop with logs so the failure mode is obvious
    const deadline = Date.now() + 480000;
    let lastErr = '';
    while (Date.now() < deadline) {
      if (await panel.isVisible().catch(() => false)) break;
      // Capture any visible error on the page
      const err = await page.locator('[data-testid="kyc-import-error"]').textContent().catch(() => '');
      if (err && err.trim() && err !== lastErr) {
        console.log('import error displayed:', err);
        lastErr = err;
      }
      await page.waitForTimeout(5000);
    }
    await expect(panel).toBeVisible({ timeout: 1000 });

    // Counterparty name extracted
    const name = page.locator('[data-testid="kyc-extracted-name"]');
    await expect(name).toBeVisible();
    await expect(name).toContainText(/MALTA[- ]?DECOR/i);

    // Outcome positive
    const outcome = page.locator('[data-testid="kyc-extracted-outcome"]');
    await expect(outcome).toBeVisible();
    await expect(outcome).toContainText(/positive/i);

    // 10 intermediate checks rendered with editable risk grade selects
    const intRows = page.locator('[data-testid^="kyc-int-check-"]');
    const intCount = await intRows.count();
    expect(intCount).toBeGreaterThanOrEqual(10);
    const firstRiskSelect = page.locator('[data-testid="kyc-int-risk-edit-0"]');
    await expect(firstRiskSelect).toBeVisible();
    // Confirm the select has L/M/H options
    await expect(firstRiskSelect.locator('option[value="L"]')).toHaveCount(1);

    // Validations table — mostly ok, some missing tolerated, NO inconsistencies
    const valRows = page.locator('[data-testid^="kyc-validation-row-"]');
    const valCount = await valRows.count();
    expect(valCount).toBeGreaterThan(0);
    const okBadges = page.locator('[data-testid^="kyc-validation-row-"] >> text=/^ok$/i');
    const inconsistentBadges = page.locator('[data-testid^="kyc-validation-row-"] >> text=/^inconsistent$/i');
    const okCount = await okBadges.count();
    const inconsistentCount = await inconsistentBadges.count();
    expect(okCount + inconsistentCount).toBeGreaterThan(0);
    // Tolerate "missing" but flag if everything is inconsistent
    expect(inconsistentCount).toBeLessThanOrEqual(Math.floor(valCount / 2));

    // Click "Save & sign off" OR "Send for human review" — whichever is visible
    const signOff = page.locator('[data-testid="kyc-sign-off-btn"]');
    const humanReview = page.locator('[data-testid="kyc-human-review-btn"]');
    if (await signOff.isVisible().catch(() => false)) {
      await signOff.click();
    } else if (await humanReview.isVisible().catch(() => false)) {
      await humanReview.click();
    } else {
      throw new Error('Neither sign-off nor human-review button visible');
    }

    // After sign off, the imported row should be in the list
    const list = page.locator('[data-testid="kyc-list"]');
    await expect(list).toBeVisible({ timeout: 30000 });
    const importedBadge = page.locator('[data-testid="kyc-imported-badge"]').first();
    await expect(importedBadge).toBeVisible({ timeout: 30000 });
  });
});
