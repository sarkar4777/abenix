import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const API_URL = process.env.API_URL || 'http://localhost:8001';
const BASE_URL = process.env.BASE_URL || 'http://localhost:3001';

const TEST_EMAIL = process.env.TEST_EMAIL || 'test@contractiq.com';
const TEST_PASSWORD = process.env.TEST_PASSWORD || 'TestPass123!';

test.describe('ContractIQ MET-template KYC UAT', () => {
  test('Full flow: login -> open /credit-risk/kyc -> fill MET form -> Run -> assert tri-indicator + tier + 10-row checklist + outcome -> Export PDF', async ({ page, request }) => {
    test.setTimeout(480_000);

    // ── 1. Ensure user exists + login via API ──
    try {
      await request.post(`${API_URL}/api/contractiq/auth/register`, {
        data: {
          email: TEST_EMAIL,
          password: TEST_PASSWORD,
          full_name: 'ContractIQ Test User',
          organization: 'ContractIQ UAT',
        },
      });
    } catch { /* already exists */ }

    const loginResp = await request.post(`${API_URL}/api/contractiq/auth/login`, {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD },
    });
    expect(loginResp.status()).toBe(200);
    const loginBody = await loginResp.json();
    const token: string = loginBody.data?.access_token;
    expect(token).toBeTruthy();

    // ── 2. Seed token into browser localStorage and open the KYC page ──
    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState('domcontentloaded');
    await page.evaluate((t) => localStorage.setItem('contractiq_token', t), token);

    await page.goto(`${BASE_URL}/credit-risk/kyc`);
    if (!(await page.locator('[data-testid="kyc-met-form"]').isVisible({ timeout: 30_000 }).catch(() => false))) {
      // UI login fallback
      await page.goto(`${BASE_URL}/`);
      await page.waitForLoadState('networkidle');
      try {
        await page.getByRole('button', { name: 'Sign In' }).first().click({ timeout: 5000 });
        await page.fill('input[type="email"]', TEST_EMAIL);
        await page.fill('input[type="password"]', TEST_PASSWORD);
        await page.locator('form button[type="submit"], form button:has-text("Sign In")').last().click();
        await page.waitForURL('**/dashboard', { timeout: 10000 });
      } catch { /* swallow */ }
      await page.goto(`${BASE_URL}/credit-risk/kyc`);
    }
    await expect(page.locator('[data-testid="kyc-met-form"]')).toBeVisible({ timeout: 30_000 });

    // ── 3. Fill the MET form ──
    await page.locator('[data-testid="kyc-trigger-Pre-Check"]').click();
    await page.locator('[data-testid="kyc-relationship-Noncore"]').click();
    await page.fill('[data-testid="kyc-name"]', 'MALTA-DECOR SP. Z O.O.');
    await page.fill('[data-testid="kyc-address"]', 'WOLKOWYSKA 32 61-132 POZNAN Poland');
    await page.selectOption('[data-testid="kyc-country"]', 'PL');
    // Industry options load via /kyc/industry-options which round-trips 26
    // tool calls to Abenix; can take 10-15s on a cold runtime. Wait for the
    // target option to appear before selecting it.
    await page.locator('[data-testid="kyc-industry"] option[value="wood_furniture_paper"]')
      .waitFor({ state: 'attached', timeout: 120_000 });
    await page.selectOption('[data-testid="kyc-industry"]', 'wood_furniture_paper');
    await page.fill('[data-testid="kyc-notional"]', '20000000');

    // Sanctions pre-screen banner renders once /kyc/prescreen returns; the
    // endpoint hits country_risk_index via Abenix and can ReadTimeout under
    // load — best-effort assertion only, don't block the run flow on it.
    await page.locator('[data-testid="kyc-sanctions-prescreen-banner"]')
      .waitFor({ state: 'visible', timeout: 5_000 })
      .catch(() => { /* prescreen race — banner is decorative */ });

    // ── 4. Click Run KYC. Tri-indicator panel must show within 5s (it renders
    //      with loading state while `running=true`) and then either resolve to
    //      a fully-populated row, OR the live agent failed and we fall back to
    //      a previously-completed row visible in the list.
    await page.locator('[data-testid="kyc-run"]').click();

    // The tri-indicator panel appears immediately because `running=true`
    await expect(page.locator('[data-testid="kyc-tri-indicator"]')).toBeVisible({ timeout: 10_000 });

    // Wait up to 300s for the outcome panel to render (live agent path
    // only). FALLBACK PATH DISABLED — the test must fail loudly if the live
    // agent does not produce an outcome.
    const usedFallback = false;
    // The new layout (MUST FIX 17) renders an outcome-top section above the
    // tri-indicator. Wait for the OUTCOME pill itself rather than the panel
    // because the panel renders while running=true even before any data.
    // The kyc-standard-check agent fans out to 8+ tools and routinely takes
    // 60-180s; allow generous headroom for first-run / cold-cache cases.
    await expect(page.locator('[data-testid="kyc-outcome-pill"]'))
      .toBeVisible({ timeout: 300_000 });

    // ── 5. Assert tri-indicator panel: 3 indicator scores + aggregated ──
    if (!usedFallback) {
      const i = page.locator('[data-testid="kyc-score-i"]');
      const ii = page.locator('[data-testid="kyc-score-ii"]');
      const iii = page.locator('[data-testid="kyc-score-iii"]');
      const agg = page.locator('[data-testid="kyc-score-aggregated"]');
      for (const cell of [i, ii, iii, agg]) {
        await expect(cell).toBeVisible();
        const text = (await cell.innerText()).replace(/\s+/g, ' ').trim();
        expect(text, `cell text should contain a number: ${text}`).toMatch(/\d+/);
      }

      // ── 6. Assert check_tier shows Standard / Enhanced / Special ──
      const tierBox = page.locator('[data-testid="kyc-check-tier"]');
      await expect(tierBox).toBeVisible();
      const tierText = (await tierBox.innerText()).trim();
      expect(tierText).toMatch(/Standard|Enhanced|Special/);

      // ── 7. Assert intermediate checklist matrix has 10 rows ──
      const matrix = page.locator('[data-testid="kyc-checklist-matrix"]');
      await expect(matrix).toBeVisible({ timeout: 30_000 });
      const rows = page.locator('[data-testid="kyc-checklist-row"]');
      await expect(rows).toHaveCount(10, { timeout: 30_000 });

      // ── 8. Assert outcome pill is positive / negative / pending ──
      const pill = page.locator('[data-testid="kyc-outcome-pill"]');
      await expect(pill).toBeVisible();
      const pillText = (await pill.innerText()).trim().toUpperCase();
      expect(pillText).toMatch(/POSITIVE|NEGATIVE|PENDING/);

      // ── 9. Export PDF and assert a .pdf download starts ──
      const downloadPromise = page.waitForEvent('download', { timeout: 60_000 });
      await page.locator('[data-testid="kyc-export-pdf"]').first().click();
      const download = await downloadPromise;
      const suggested = download.suggestedFilename();
      expect(suggested.toLowerCase()).toContain('.pdf');

      const tmp = path.join(__dirname, '..', 'test-results', `kyc_${Date.now()}.pdf`);
      fs.mkdirSync(path.dirname(tmp), { recursive: true });
      await download.saveAs(tmp);
      const stat = fs.statSync(tmp);
      expect(stat.size).toBeGreaterThan(1000);

      const fd = fs.openSync(tmp, 'r');
      const buf = Buffer.alloc(4);
      fs.readSync(fd, buf, 0, 4, 0);
      fs.closeSync(fd);
      expect(buf.toString()).toBe('%PDF');
    } else {
      // Fallback path: we're on /credit-risk/kyc/{id} (the detail page).
      // The detail page reads the same row schema — assert tier + 10 rows +
      // outcome + PDF download via the detail page's Export PDF button.
      await page.waitForLoadState('domcontentloaded');

      // Tier is rendered as a coloured pill on the detail page hero header.
      // Look for any text matching the three tier names.
      const bodyText = await page.locator('main, body').first().innerText();
      expect(bodyText).toMatch(/Standard|Enhanced|Special/);

      // Outcome row on detail page is the same OUTCOME pill via OUTCOME_STYLE.
      // We just assert a positive or negative word appears.
      expect(bodyText.toLowerCase()).toMatch(/positive|negative|pending/);

      // 10 intermediate items rendered (each has unique label). Count occurrences
      // of any standard label.
      const checklistLabels = [
        'Shareholders',
        'UBOs identified',
        'Sanctions check on counterparty',
        'Sanctions check on UBOs',
        'Negative news',
        'Regulatory',
        'PEP',
      ];
      let labelHits = 0;
      for (const lab of checklistLabels) {
        if (bodyText.includes(lab)) labelHits += 1;
      }
      expect(labelHits, `expected several MET checklist labels visible; only saw ${labelHits}`).toBeGreaterThanOrEqual(4);

      // ── Export PDF via detail-page button ──
      const downloadPromise = page.waitForEvent('download', { timeout: 60_000 });
      await page.locator('[data-testid="kyc-export-pdf"]').first().click();
      const download = await downloadPromise;
      const suggested = download.suggestedFilename();
      expect(suggested.toLowerCase()).toContain('.pdf');

      const tmp = path.join(__dirname, '..', 'test-results', `kyc_${Date.now()}.pdf`);
      fs.mkdirSync(path.dirname(tmp), { recursive: true });
      await download.saveAs(tmp);
      const stat = fs.statSync(tmp);
      expect(stat.size).toBeGreaterThan(1000);

      const fd = fs.openSync(tmp, 'r');
      const buf = Buffer.alloc(4);
      fs.readSync(fd, buf, 0, 4, 0);
      fs.closeSync(fd);
      expect(buf.toString()).toBe('%PDF');
    }
  });
});
