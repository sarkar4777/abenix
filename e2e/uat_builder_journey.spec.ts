/**
 * End-to-end builder journey, entirely through the UI.
 *
 * Describe a problem → let the AI builder assemble a pipeline → apply it to the
 * canvas → save → publish → run it → read the answer. This is the path a real
 * user takes, and every step here failed at least once during development.
 *
 * Run: USE_K8S=true npx playwright test e2e/uat_builder_journey.spec.ts
 */

import { test, expect, type Page } from '@playwright/test';

const WEB = process.env.BASE_URL || 'http://localhost:3100';
const API = process.env.API_URL || 'http://localhost:8000';
const EMAIL = process.env.UAT_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.UAT_PASSWORD || 'Admin123456';

const PROBLEM =
  'Search the web for recent news about a named LNG supplier, score how financially ' +
  'distressed it looks on a 0-100 scale, and recommend hold, hedge or escalate with reasons.';

async function signIn(page: Page): Promise<string> {
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!r.ok) throw new Error(`login failed: HTTP ${r.status}`);
  const d = (await r.json()).data;
  const me = await fetch(`${API}/api/auth/me`, {
    headers: { Authorization: `Bearer ${d.access_token}` },
  })
    .then((x) => x.json())
    .then((j) => j.data ?? j)
    .catch(() => ({}));
  await page.addInitScript(
    ({ t, u }: { t: string; u: unknown }) => {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
      localStorage.setItem('user', JSON.stringify(u));
    },
    { t: d.access_token, u: me },
  );
  return d.access_token;
}

test('builder journey: describe, build, save, publish and run through the UI', async ({ page }) => {
  test.setTimeout(1_700_000);
  const problems: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error' && !/favicon|DevTools|_next\/static/i.test(m.text()))
      problems.push(`console: ${m.text().slice(0, 200)}`);
  });
  page.on('response', (r) => {
    if (r.status() >= 400 && !/favicon|_next\/static|auth\/refresh/i.test(r.url()))
      problems.push(`${r.status()} ${r.request().method()} ${r.url().slice(0, 140)}`);
  });

  const token = await signIn(page);
  await page.goto(`${WEB}/builder`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);

  // ── 1. Describe it ─────────────────────────────────────────────────────
  await page.getByRole('button', { name: /Build with AI/i }).first().click();
  await page.waitForTimeout(2500);
  const dialog = page.locator('div.fixed.inset-0.z-50').first();
  await page.locator('textarea:visible').first().fill(PROBLEM);
  await page.getByTestId('ai-builder-mode-pipeline').click();
  await page.getByTestId('iterative-toggle').click();
  await page.waitForTimeout(400);
  const slider = page.getByTestId('iteration-budget').locator('input[type="range"]');
  if (await slider.count()) await slider.fill('2');
  await page.getByRole('button', { name: /Generate Agent \/ Pipeline/i }).first().click();
  console.log('STEP 1: generating...');

  const apply = dialog.getByRole('button', { name: /Apply|Use this|Add to canvas/i }).first();
  let built = false;
  for (let i = 0; i < 120; i++) {
    await page.waitForTimeout(5000);
    if (await apply.count()) {
      built = true;
      break;
    }
    // Surface why it is not finishing instead of spinning silently.
    if (i % 12 === 11) {
      const tl = await dialog.getByTestId('iterative-timeline').innerText().catch(() => '');
      console.log(`  ...${(i + 1) * 5}s, last: ${tl.split('\n').slice(-1)[0] || '(no timeline)'}`);
    }
  }
  if (!built) {
    console.log('DIALOG STATE:\n' + (await dialog.innerText().catch(() => '(gone)')).slice(0, 1500));
  }
  expect(built, 'builder produced nothing to apply').toBeTruthy();

  const timeline = await dialog.getByTestId('iterative-timeline').innerText().catch(() => '');
  console.log(timeline.split('\n').filter((l) => /generated|judge|critic|validation/i.test(l)).join('\n'));

  await apply.click();
  await page.waitForTimeout(6000);
  console.log('STEP 2: applied to canvas');

  // ── 3. Save, which is what unlocks publishing ──────────────────────────
  await page.getByRole('button', { name: /Save Draft/i }).first().click();
  await page.waitForTimeout(15_000);
  const publish = page.getByRole('button', { name: /^Publish/i }).first();
  const gated = await publish.isDisabled().catch(() => true);
  console.log(`STEP 3: saved; publish enabled = ${!gated}`);
  expect(gated, 'Publish still gated after saving the draft').toBeFalsy();

  // ── 4. Publish ─────────────────────────────────────────────────────────
  await publish.click();
  await page.waitForTimeout(3000);
  const pubDlg = page.locator('div.fixed.inset-0').last();
  const confirm = pubDlg.getByRole('button', { name: /^(Publish|Confirm)/i }).last();
  if (await confirm.count()) {
    await confirm.click();
    await page.waitForTimeout(10_000);
  }
  console.log(`STEP 4: published; url = ${page.url()}`);
  await page.screenshot({ path: 'e2e/screenshots/journey-publish.png', fullPage: true });

  // ── 5. Run it and read the answer ──────────────────────────────────────
  const agents = await fetch(`${API}/api/agents?limit=3`, {
    headers: { Authorization: `Bearer ${token}` },
  })
    .then((r) => r.json())
    .then((j) => j.data ?? []);
  const mine = agents[0];
  console.log(`STEP 5: newest agent = ${mine?.name} (${mine?.id})`);
  expect(mine, 'no agent to run').toBeTruthy();

  await page.goto(`${WEB}/agents/${mine.id}/chat`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(6000);
  const box = page.locator('textarea, input[type="text"]').first();
  await expect(box, 'no input on the agent chat page').toBeVisible({ timeout: 20_000 });
  await box.fill('Assess supplier Venture Global LNG for Q1 delivery risk.');
  await box.press('Enter');
  console.log('  asked the agent; waiting for the answer...');

  let answer = '';
  for (let i = 0; i < 90; i++) {
    await page.waitForTimeout(5000);
    const t = await page.locator('body').innerText().catch(() => '');
    if (/hold|hedge|escalate|risk score|recommend/i.test(t) && t.length > 1200) {
      answer = t;
      break;
    }
  }
  await page.screenshot({ path: 'e2e/screenshots/journey-answer.png', fullPage: true });
  const tail = answer.slice(-1800);
  console.log('\n===== the answer =====');
  console.log(tail || '(no answer rendered in time)');

  console.log('\n===== problems across the journey =====');
  [...new Set(problems)].forEach((p) => console.log('  ' + p));
  expect(answer.length, 'agent produced no visible answer').toBeGreaterThan(0);
});
