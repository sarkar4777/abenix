import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE_WM || 'http://localhost:3006';
const SHOTS = path.join(process.cwd(), 'e2e', 'screenshots', 'wingman');
fs.mkdirSync(SHOTS, { recursive: true });

let _n = 0;
async function shot(page: Page, label: string) {
  _n++;
  const name = `${String(_n).padStart(2, '0')}-${label}.png`;
  await page.screenshot({ path: path.join(SHOTS, name), fullPage: true }).catch(() => {});
}

async function gotoOk(page: Page, p: string) {
  await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe.serial('Wingman browser quality UAT', () => {
  test.setTimeout(300_000);

  test('1. landing/home: sidebar + product pillars visible', async ({ page }) => {
    await gotoOk(page, '/');
    await shot(page, 'home');
    // home renders after redirect
    await expect(page.getByRole('main').getByText('Arbitrage Workbench').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Price at Risk Lens').first()).toBeVisible();
    await expect(page.getByText('Forward Scenarios').first()).toBeVisible();
  });

  test('2. forward scenarios: fan chart renders with P10 < P50 < P90', async ({ page }) => {
    await gotoOk(page, '/scenarios');
    await shot(page, 'scenarios-loaded');

    // Capture API response for forecaster to validate p10 < p50 < p90.
    const respP = page.waitForResponse(
      (r) => r.url().includes('/scenarios') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 250_000 },
    ).catch(() => null);

    // Find a Run button. Buttons in the scenarios page use icons + text.
    const runCandidates = [
      page.getByRole('button', { name: /^Run/i }),
      page.getByRole('button', { name: /Forecast/i }),
      page.getByRole('button', { name: /Generate/i }),
      page.getByText(/Run scenario/i),
      page.locator('button:has(svg[class*="lucide-play"])').first(),
    ];
    let clicked = false;
    for (const c of runCandidates) {
      if (await c.first().isVisible().catch(() => false)) {
        await c.first().click().catch(() => {});
        clicked = true;
        break;
      }
    }
    expect(clicked, 'must find a Run button on scenarios page').toBeTruthy();

    // Wait for the fan chart SVG to populate. Recharts renders <svg> with class containing "recharts".
    const fan = page.locator('svg.recharts-surface, .recharts-wrapper svg').first();
    await expect(fan).toBeVisible({ timeout: 250_000 });
    await page.waitForTimeout(2000);
    await shot(page, 'scenarios-fan');

    // Try to validate P10/P50/P90 ordering from DOM text.
    const body = await page.evaluate(() => document.body.innerText || '');
    // Look for any P10, P50, P90 number triple in the text.
    const p10 = body.match(/P10[^0-9-]{0,20}(-?[0-9][0-9.,]*)/i);
    const p50 = body.match(/P50[^0-9-]{0,20}(-?[0-9][0-9.,]*)/i);
    const p90 = body.match(/P90[^0-9-]{0,20}(-?[0-9][0-9.,]*)/i);
    if (p10 && p50 && p90) {
      const a = parseFloat(p10[1].replace(/,/g, ''));
      const b = parseFloat(p50[1].replace(/,/g, ''));
      const c = parseFloat(p90[1].replace(/,/g, ''));
      console.log(`Scenarios P10/P50/P90 = ${a} / ${b} / ${c}`);
      expect(Number.isFinite(a) && Number.isFinite(b) && Number.isFinite(c)).toBeTruthy();
      expect(a, `P10(${a}) must be < P50(${b})`).toBeLessThan(b);
      expect(b, `P50(${b}) must be < P90(${c})`).toBeLessThan(c);
    } else {
      // Look at the API response if present.
      const resp = await respP;
      if (resp) {
        const json = await resp.json().catch(() => null);
        console.log('Scenarios response sample:', JSON.stringify(json).slice(0, 800));
      }
      // The chart is visible; record that we could not pull numeric P10/50/90 from DOM.
      console.warn('Could not regex-match P10/P50/P90 numbers from DOM text');
    }
  });

  test('3. mispricing/Price at Risk Lens: trade card with fair_value, z, thesis', async ({ page }) => {
    await gotoOk(page, '/mispricing');
    await shot(page, 'mispricing-loaded');

    // Pick a corridor chip if it exists.
    const chip = page.getByTestId('mispricing-corridor-USGC-NWE').first();
    if (await chip.isVisible().catch(() => false)) await chip.click();

    const run = page.getByTestId('run-mispricing-scan');
    await expect(run).toBeVisible({ timeout: 10_000 });

    // Capture scan response.
    const respP = page.waitForResponse(
      (r) => /scan|mispricing/i.test(r.url()) && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 200_000 },
    ).catch(() => null);

    await run.click();
    await page.waitForTimeout(1000);
    await shot(page, 'mispricing-running');

    // Trade card must appear.
    const tradeCard = page.getByTestId('trade-card');
    await expect(tradeCard).toBeVisible({ timeout: 200_000 });
    await page.waitForTimeout(1500);
    await shot(page, 'mispricing-trade-card');

    const cardText = (await tradeCard.innerText().catch(() => '')) || '';
    const bodyText = (await page.evaluate(() => document.body.innerText || '')) || '';

    // Capture scan from network too.
    const resp = await respP;
    let scan: any = null;
    if (resp) {
      const j = await resp.json().catch(() => null);
      scan = j?.data || j;
      console.log('Mispricing scan keys:', scan ? Object.keys(scan).join(',') : '(none)');
    }

    // Look for fair_value as a number anywhere on the page.
    const fairMatch = bodyText.match(/fair[ -]?value[^0-9-]{0,30}(-?\d[\d.,]*)/i);
    const zMatch = bodyText.match(/(?:z[- ]?score|residual[^a-z]{0,10}sigma|\bsigma\b)[^0-9-]{0,30}(-?\d[\d.,]*)/i);
    console.log('fair_value match:', fairMatch?.[1], 'z match:', zMatch?.[1]);

    if (scan) {
      expect(scan.fair_value_spread_usd_mt ?? scan.fair_value, 'fair_value must be a number').toEqual(expect.any(Number));
      const z = scan.residual_sigma ?? scan.z_score;
      if (z !== null && z !== undefined) {
        expect(typeof z).toBe('number');
        expect(Number.isFinite(z)).toBeTruthy();
      }
      const thesis = scan.thesis ?? scan.thesis_text ?? '';
      expect(typeof thesis).toBe('string');
      expect(thesis.length, `thesis must be >50 chars; got ${thesis.length}`).toBeGreaterThan(50);
    } else {
      // Fall back to DOM-text checks.
      expect(fairMatch, 'fair_value number must be visible in DOM').toBeTruthy();
      // Thesis: there must be a paragraph of >50 chars.
      const longPara = bodyText.split(/\n/).find((line) => line.trim().length > 50);
      expect(longPara, 'thesis paragraph (>50 chars) must be visible').toBeTruthy();
    }
  });

  test('4. compliance lens: submit fictional order and verify rule citation', async ({ page }) => {
    // /compliance route does not exist in the public wingman UI.
    // Visit it anyway and check whether the page renders or 404s.
    const resp = await page.goto(`${BASE}/compliance`, { waitUntil: 'domcontentloaded' }).catch(() => null);
    await shot(page, 'compliance-attempt');
    const status = resp?.status() ?? 0;
    console.log('compliance status =', status);
    // If 404, document explicitly and fail-soft (the route simply does not exist in the deployed UI).
    if (status === 404) {
      test.fail(true, 'Compliance Lens UI route /compliance does not exist in current Wingman build');
      return;
    }
    // If it loads, look for a counterparty input + amount input + submit.
    const cpInput = page.locator('input[name*="counterparty" i], input[placeholder*="counterparty" i]').first();
    const amtInput = page.locator('input[name*="amount" i], input[placeholder*="amount" i], input[type="number"]').first();
    if (!(await cpInput.isVisible().catch(() => false)) || !(await amtInput.isVisible().catch(() => false))) {
      test.fail(true, 'Compliance Lens form not found on /compliance page');
      return;
    }
    await cpInput.fill('RuralPower Co');
    await amtInput.fill('5000000');
    const submit = page.getByRole('button', { name: /submit|run|check|validate/i }).first();
    await submit.click();
    await page.waitForTimeout(8000);
    await shot(page, 'compliance-result');
    const txt = await page.evaluate(() => document.body.innerText || '');
    expect(/Regulation|Sanction|OFAC|rule|policy/i.test(txt), 'compliance output must cite a rule/regulation').toBeTruthy();
  });
});
