import { test, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
const BASE = process.env.BASE_WM || 'http://localhost:3006';
const DIR = process.env.WINGMAN_SHOTS_DIR || './shots';
fs.mkdirSync(DIR, { recursive: true });

const VIEWPORT = { width: 1600, height: 1100 };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(DIR, name + '.png'), fullPage: true });
}

test.use({ viewport: VIEWPORT });

test.describe.serial('12 features visual', () => {
  test('home: nav grid + todays signals + architecture matrix', async ({ page }) => {
    await page.goto(`${BASE}/home`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(5000);
    await shot(page, '01-home-collapsed');
    // expand architecture matrix
    const archBtn = page.locator('[data-testid="architecture-matrix"] button').first();
    if (await archBtn.isVisible().catch(() => false)) {
      await archBtn.click();
      await page.waitForTimeout(800);
      await shot(page, '02-home-arch-matrix-open');
    }
  });

  test('mispricing: compare view + 4 corridors', async ({ page }) => {
    await page.goto(`${BASE}/mispricing`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(4000);
    await shot(page, '03-mispricing-page');
    const compare = page.locator('[data-testid="compare-corridors"] button').first();
    if (await compare.isVisible().catch(() => false)) {
      await compare.click();
      await page.waitForTimeout(800);
      await shot(page, '04-mispricing-compare-open');
    }
  });

  test('workbench: cost preview on Run button', async ({ page }) => {
    await page.goto(`${BASE}/workbench`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(4000);
    await shot(page, '05-workbench');
  });

  test('lab: sticky tabs', async ({ page }) => {
    await page.goto(`${BASE}/lab`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, '06-lab-tabs');
  });

  test('scenarios: sliders', async ({ page }) => {
    await page.goto(`${BASE}/scenarios`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, '07-scenarios');
  });

  test('inbox: composer', async ({ page }) => {
    await page.goto(`${BASE}/inbox`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, '08-inbox-composer');
  });

  test('approvals: empty state + bulk', async ({ page }) => {
    await page.goto(`${BASE}/approvals`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, '09-approvals');
  });

  test('graph: sample query cards', async ({ page }) => {
    await page.goto(`${BASE}/graph`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, '10-graph-samples');
  });

  test('copilot: empty state 4-step', async ({ page }) => {
    await page.goto(`${BASE}/desk`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, '11-copilot');
  });
});
