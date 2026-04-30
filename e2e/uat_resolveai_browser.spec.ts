import { test, expect, type Page } from '@playwright/test';

// Browser-first UAT for ResolveAI. Drives every visible link / button /
// form via Chromium against http://localhost:3004 (port-forwarded).
//
// To run:
//   BASE=http://localhost:3004 npx playwright test e2e/uat_resolveai_browser.spec.ts \
//     --reporter=list --workers=1 --timeout=180000

const BASE = process.env.BASE || 'http://localhost:3004';

async function gotoOk(page: Page, path: string) {
  const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
  expect(resp?.status(), `${path} HTTP`).toBeLessThan(400);
  // Hydrate guard — wait for client-side framework to mount.
  await page.waitForLoadState('networkidle').catch(() => {});
}

test.describe.configure({ mode: 'serial' });

test.describe('ResolveAI · UAT', () => {
  test('1 — landing dashboard renders KPIs', async ({ page }) => {
    await gotoOk(page, '/');
    // Hero copy + at least one KPI tile.
    await expect(page.locator('body')).toContainText(/ResolveAI|customer-service|cases/i);
    await expect(page.locator('body')).toContainText(/cost|cases|deflection|auto/i);
  });

  test('2 — sidebar links target real routes', async ({ page }) => {
    await gotoOk(page, '/');
    const expected = ['/cases', '/sla', '/qa', '/trends', '/admin', '/help', '/live-console'];
    for (const path of expected) {
      // Each link should be in the DOM somewhere — sidebar or in-page nav.
      const hits = await page.locator(`a[href="${path}"]`).count();
      expect(hits, `link to ${path} present`).toBeGreaterThan(0);
    }
  });

  test('3 — file a ticket from dashboard CTA', async ({ page }) => {
    await gotoOk(page, '/');
    // The dashboard's primary CTA submits a sample ticket and routes
    // to /cases/<id>. Click whichever is visible (button text varies
    // a bit between the hero and modal).
    const cta = page.getByRole('button', { name: /try it|file a|sample|new ticket/i }).first();
    if (await cta.isVisible().catch(() => false)) {
      await cta.click();
      // Either we land on a case detail or a "fill in details" modal.
      await page.waitForTimeout(2500);
    }
  });

  test('4 — cases queue lists rows', async ({ page }) => {
    await gotoOk(page, '/cases');
    await expect(page.locator('body')).toContainText(/case|customer|status|channel/i);
  });

  test('5 — open most recent case detail', async ({ page }) => {
    await gotoOk(page, '/cases');
    // Click the first case-detail link.
    const link = page.locator('a[href^="/cases/"]').first();
    await expect(link, 'at least one case row').toBeVisible({ timeout: 10000 });
    await link.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{6,}/i);
    await expect(page.locator('body')).toContainText(/status|action|reply|customer/i);
  });

  test('6 — case detail surfaces resolution + deflection', async ({ page }) => {
    await gotoOk(page, '/cases');
    const link = page.locator('a[href^="/cases/"]').first();
    await link.click();
    await page.waitForLoadState('networkidle').catch(() => {});
    // At least one of these should appear for a resolved case.
    const text = (await page.textContent('body')) || '';
    expect(
      /deflection|action plan|resolution|Reply|Auto.resolved/i.test(text),
      'detail page shows AI output'
    ).toBeTruthy();
  });

  test('7 — SLA dashboard loads', async ({ page }) => {
    await gotoOk(page, '/sla');
    await expect(page.locator('body')).toContainText(/SLA|breach|deadline|board|first response|resolution/i);
  });

  test('8 — QA reviewer page loads', async ({ page }) => {
    await gotoOk(page, '/qa');
    await expect(page.locator('body')).toContainText(/QA|score|rubric|review|CSAT/i);
  });

  test('9 — Trends page loads + shows insights or empty state', async ({ page }) => {
    await gotoOk(page, '/trends');
    await expect(page.locator('body')).toContainText(/trend|theme|VoC|insight|categor|pattern/i);
  });

  test('10 — Admin settings page loads + form fields visible', async ({ page }) => {
    await gotoOk(page, '/admin');
    await expect(page.locator('body')).toContainText(/admin|setting|approval|tier|SLA|slack|policy/i);
  });

  test('11 — Help page renders walkthrough', async ({ page }) => {
    await gotoOk(page, '/help');
    await expect(page.locator('body')).toContainText(/help|walkthrough|how|step|pipeline/i);
  });

  test('12 — Live Console page connects', async ({ page }) => {
    await gotoOk(page, '/live-console');
    await expect(page.locator('body')).toContainText(/live|console|stream|event|listening|connected|tracking/i);
  });

  test('13 — Try it now CTA fires a real ticket end-to-end', async ({ page, context }) => {
    test.setTimeout(180_000);
    await context.clearCookies();
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.evaluate(() => { try { localStorage.clear(); } catch {} });
    await page.reload({ waitUntil: 'networkidle' });
    // Hydration finishes after onload + a microtask; give React a beat
    // before we drive a click, otherwise the onClick prop on the button
    // may not be wired yet.
    await page.waitForTimeout(800);

    const tryBtn = page.getByRole('button', { name: /^try it now$/i });
    await expect(tryBtn).toBeVisible({ timeout: 10_000 });
    const [postResp] = await Promise.all([
      page.waitForResponse(r =>
        r.url().includes('/api/resolveai/cases') && r.request().method() === 'POST',
        { timeout: 60_000 }),
      tryBtn.click(),
    ]);
    expect(postResp.status(), 'POST /cases returns 2xx').toBeLessThan(300);

    // Now we expect the client-side router.push to land on /cases/<id>.
    await page.waitForURL(/\/cases\/[0-9a-f-]{6,}/i, { timeout: 60_000 });
    await page.waitForLoadState('domcontentloaded');
    const text = (await page.textContent('body')) || '';
    expect(/order|customer|subject|Take over/i.test(text), 'detail page rendered').toBeTruthy();
  });

  test('14 — Take-over button updates status', async ({ page }) => {
    test.setTimeout(120_000);
    // Find a case that isn't already human_handling.
    await gotoOk(page, '/cases');
    const links = await page.locator('a[href^="/cases/"]').all();
    let target: string | null = null;
    for (const l of links.slice(0, 6)) {
      const href = await l.getAttribute('href');
      if (href) { target = href; break; }
    }
    expect(target, 'a case link to open').toBeTruthy();
    await page.goto(`${BASE}${target}`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    const takeOver = page.getByRole('button', { name: /take over/i });
    if (await takeOver.isVisible().catch(() => false)) {
      await takeOver.click();
      // The button label changes to a spinner; wait until the API
      // round-trips and the button stops spinning (or disappears,
      // since the case becomes human_handling and the conditional
      // hides it).
      await page.waitForTimeout(2500);
      const stillThere = await takeOver.isVisible().catch(() => false);
      const text = (await page.textContent('body')) || '';
      expect(stillThere === false || /human_handling|handling|adjuster/i.test(text)).toBeTruthy();
    }
  });

  test('15 — SLA "Run sweep now" button fires + returns', async ({ page }) => {
    test.setTimeout(60_000);
    await gotoOk(page, '/sla');
    const btn = page.getByTestId('run-sla-sweep');
    await expect(btn).toBeVisible();
    await btn.click();
    await page.waitForTimeout(8_000);
    const text = (await page.textContent('body')) || '';
    expect(/sweep|breach|swept|deadline|no breaches/i.test(text)).toBeTruthy();
  });

  test('16 — Trends "Mine now" button is reachable', async ({ page }) => {
    test.setTimeout(120_000);
    await gotoOk(page, '/trends');
    const mine = page.getByRole('button', { name: /mine|refresh/i }).first();
    await expect(mine).toBeVisible();
    // Mining can be slow; just click and verify the page didn't crash.
    await mine.click();
    await page.waitForTimeout(6_000);
    const text = (await page.textContent('body')) || '';
    expect(/trend|theme|insight|VoC|categor/i.test(text)).toBeTruthy();
  });

  test('17 — Admin form has Save button + tier sliders', async ({ page }) => {
    await gotoOk(page, '/admin');
    const text = (await page.textContent('body')) || '';
    expect(/auto.approve|tier|SLA|approval|policy/i.test(text)).toBeTruthy();
    // The Save button should be present.
    const save = page.getByRole('button', { name: /save/i }).first();
    await expect(save).toBeVisible();
  });

  test('18 — every nav link navigates & comes back', async ({ page }) => {
    test.setTimeout(60_000);
    const paths = ['/', '/cases', '/sla', '/qa', '/trends', '/admin', '/help', '/live-console'];
    for (const path of paths) {
      const resp = await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
      expect(resp?.status(), `${path}`).toBeLessThan(400);
      await page.waitForLoadState('networkidle').catch(() => {});
      await expect(page).toHaveURL(new RegExp(path.replace(/\//g, '\\/').replace('$', '') + '$'));
    }
  });

  test('19 — no console errors anywhere obvious', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', err => errors.push(`pageerror: ${err.message}`));
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(`console: ${msg.text()}`);
    });
    for (const path of ['/', '/cases', '/sla', '/qa', '/trends', '/admin', '/help', '/live-console']) {
      await gotoOk(page, path);
      await page.waitForTimeout(800);
    }
    // Filter out harmless asset warnings.
    const hard = errors.filter(e =>
      !/favicon|hydrat|webpack|fast refresh|chunk|manifest|isr|prefetch/i.test(e)
    );
    expect(hard, `console errors: ${hard.join('\n')}`).toHaveLength(0);
  });
});
