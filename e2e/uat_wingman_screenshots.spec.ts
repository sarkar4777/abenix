import { test, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE_WM || 'http://localhost:3006';
const SHOTS_DIR = process.env.WINGMAN_SHOTS_DIR
  || path.join(process.env.USERPROFILE || process.env.HOME || '.', 'wingman-screenshots');
fs.mkdirSync(SHOTS_DIR, { recursive: true });

let _i = 0;
async function shot(page: Page, label: string) {
  _i++;
  const name = `${String(_i).padStart(2, '0')}-${label}.png`;
  await page.screenshot({ path: path.join(SHOTS_DIR, name), fullPage: true });
}

async function gotoOk(page: Page, p: string) {
  await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe.serial('Wingman — 12 demo screenshots', () => {
  test('01 sidebar shell on workbench', async ({ page }) => {
    await gotoOk(page, '/workbench');
    await page.waitForTimeout(2500);
    await shot(page, 'sidebar-shell');
  });

  test('02 workbench market brief + corridors', async ({ page }) => {
    await gotoOk(page, '/workbench');
    await page.waitForTimeout(4000);
    await shot(page, 'workbench-market-brief');
  });

  test('03 workbench Run analysis fires DAG', async ({ page }) => {
    await gotoOk(page, '/workbench');
    await page.waitForTimeout(2500);
    const btn = page.getByRole('button', { name: /Run.*analysis|Re-run.*analysis/i }).first();
    if (await btn.isVisible().catch(() => false)) {
      await btn.click();
      await page.waitForTimeout(8000);
    }
    await shot(page, 'workbench-dag-drawer');
  });

  test('04 forward scenarios landing', async ({ page }) => {
    await gotoOk(page, '/scenarios');
    await page.waitForTimeout(3000);
    await shot(page, 'scenarios-landing');
  });

  test('05 forward scenarios Run forecast', async ({ page }) => {
    await gotoOk(page, '/scenarios');
    await page.waitForTimeout(2000);
    const run = page.getByTestId('run-forecast');
    if (await run.isVisible().catch(() => false)) {
      await run.click();
      await page.waitForTimeout(8000);
    }
    await shot(page, 'scenarios-running');
  });

  test('06 broker inbox landing', async ({ page }) => {
    await gotoOk(page, '/inbox');
    await page.waitForTimeout(3000);
    await shot(page, 'inbox-landing');
  });

  test('07 broker inbox classify', async ({ page }) => {
    await gotoOk(page, '/inbox');
    await page.waitForTimeout(2000);
    const classify = page.getByRole('button', { name: /Classify intent/i }).first();
    if (await classify.isVisible().catch(() => false)) {
      await classify.click();
      await page.waitForTimeout(15000);
    }
    await shot(page, 'inbox-classify');
  });

  test('08 broker inbox parse', async ({ page }) => {
    await gotoOk(page, '/inbox');
    await page.waitForTimeout(2000);
    const parse = page.getByRole('button', { name: /Extract structured offer/i }).first();
    if (await parse.isVisible().catch(() => false)) {
      await parse.click();
      await page.waitForTimeout(20000);
    }
    await shot(page, 'inbox-structured-offer');
  });

  test('09 approvals queue', async ({ page }) => {
    await gotoOk(page, '/approvals');
    await page.waitForTimeout(3000);
    await shot(page, 'approvals-queue');
  });

  test('10 operations watch live AIS', async ({ page }) => {
    await gotoOk(page, '/ops');
    await page.waitForTimeout(15000);
    await shot(page, 'ops-live-ais');
  });

  test('11 mispricing lens landing', async ({ page }) => {
    await gotoOk(page, '/mispricing');
    await page.waitForTimeout(3500);
    await shot(page, 'mispricing-landing');
  });

  test('12 mispricing lens scored', async ({ page }) => {
    await gotoOk(page, '/mispricing');
    await page.waitForTimeout(2500);
    const run = page.getByTestId('run-mispricing-scan');
    if (await run.isVisible().catch(() => false)) {
      await run.click();
      await page.waitForTimeout(45000);
    }
    await shot(page, 'mispricing-scored');
  });
});
