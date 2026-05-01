import { chromium } from 'playwright';
const BASE = 'http://localhost:3000';

async function main() {
  const browser = await chromium.launch({ headless: true, args: ['--disable-web-security'] });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.locator('#auth-email').waitFor({ timeout: 25_000 });
  await page.waitForTimeout(1_500);
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === 'Admin Demo') as HTMLButtonElement | undefined;
    const k = btn && Object.keys(btn).find(k => k.startsWith('__reactProps$'));
    if (btn && k) (btn as any)[k].onClick();
  });
  await page.waitForURL(/\/(dashboard|atlas|agents|home)/, { timeout: 30_000 });
  await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5_000);
  const ta = page.locator('textarea').first();
  const disabled = await ta.getAttribute('disabled');
  const placeholder = await ta.getAttribute('placeholder');
  console.log(`textarea disabled attr: ${disabled === null ? 'null (enabled)' : disabled}`);
  console.log(`textarea placeholder:   ${placeholder}`);
  if (disabled === null && placeholder && /Message /i.test(placeholder)) {
    console.log('PASS — textarea enabled with agent placeholder');
  } else {
    console.log('FAIL — textarea still disabled or placeholder is "Select an agent..."');
  }
  await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
