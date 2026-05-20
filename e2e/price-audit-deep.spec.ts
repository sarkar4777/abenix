import { test, type Page } from '@playwright/test';

const BASE = process.env.BASE_WM || 'http://localhost:3006';
const PAGES = ['/scenarios', '/desk', '/inbox', '/ops'];

test.describe('Wingman deep price-unit audit', () => {
  for (const path of PAGES) {
    test(`${path} — bare $/gal $/bbl context`, async ({ page }) => {
      await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(4000);
      const body = await page.evaluate(() => document.body.innerText);

      console.log(`\n========= ${path} =========`);
      for (const pat of [/\$\/gal\b/g, /\$\/bbl\b/g]) {
        const matches = [...body.matchAll(pat)];
        console.log(`  pattern=${pat.source}  hits=${matches.length}`);
        for (const m of matches.slice(0, 5)) {
          const i = m.index || 0;
          console.log(`    ctx [${i}]: "${body.slice(Math.max(0, i - 60), i + 30).replace(/\s+/g, ' ')}"`);
        }
      }
    });
  }
});
