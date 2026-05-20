import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE_WM || 'http://localhost:3006';

const PAGES = ['/home', '/workbench', '/mispricing', '/lab', '/scenarios', '/desk', '/inbox', '/ops', '/strategy', '/approvals', '/graph'];

test.describe('Wingman price-unit audit', () => {
  for (const path of PAGES) {
    test(`${path} — count price units`, async ({ page }) => {
      await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(4000); // let live tickers & cached scans render

      const body = await page.evaluate(() => document.body.innerText);

      const gal = (body.match(/\$\/gal\b/g) || []).length;
      const bbl = (body.match(/\$\/bbl\b/g) || []).length;
      const mt  = (body.match(/\$\/MT\b/g) || []).length;
      const mmbtu = (body.match(/\$\/MMBtu\b/g) || []).length;

      const priceContexts: string[] = [];
      for (const m of body.matchAll(/(\$[0-9][\d,]*\.?\d*\s*\/(?:gal|bbl|MT|MMBtu))/g)) {
        const i = m.index || 0;
        priceContexts.push(body.slice(Math.max(0, i - 40), i + 30).replace(/\s+/g, ' '));
      }

      console.log(`\n========= ${path} =========`);
      console.log(`  $/gal: ${gal}   $/bbl: ${bbl}   $/MT: ${mt}   $/MMBtu: ${mmbtu}`);
      console.log(`  price snippets (first 15):`);
      for (const ctx of priceContexts.slice(0, 15)) console.log(`    … ${ctx}`);
    });
  }
});
