/**
 * ClaimsIQ end-to-end, driven as a user.
 *
 * ClaimsIQ is the only Java app on the platform (Spring Boot + Vaadin, talking
 * to Abenix through the Java SDK), so it exercises a code path nothing else
 * does. The journey is: file a First Notice of Loss, let the 7-node
 * claimsiq-adjudicate pipeline run, then confirm the claim carries a real
 * adjudication and shows up in the adjuster queue.
 *
 * Run: USE_K8S=true npx playwright test e2e/uat_claimsiq_journey.spec.ts
 */

import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

const CIQ = process.env.CLAIMSIQ_URL || 'http://localhost:3005';
const API = `${CIQ}/api/claimsiq`;

type Gaps = { console: string[]; failed: string[] };

function watch(page: Page): Gaps {
  const g: Gaps = { console: [], failed: [] };
  page.on('console', (m) => {
    if (m.type() === 'error' && !/favicon|DevTools/i.test(m.text()))
      g.console.push(m.text().slice(0, 200));
  });
  page.on('response', (r) => {
    if (r.status() >= 400 && !/favicon/i.test(r.url()))
      g.failed.push(`${r.status()} ${r.request().method()} ${r.url().slice(0, 120)}`);
  });
  return g;
}

function report(name: string, g: Gaps) {
  const c = [...new Set(g.console)];
  const f = [...new Set(g.failed)];
  if (c.length) {
    console.log(`  [${name}] console errors:`);
    c.slice(0, 8).forEach((x) => console.log(`      - ${x}`));
  }
  if (f.length) {
    console.log(`  [${name}] failed requests:`);
    f.slice(0, 8).forEach((x) => console.log(`      - ${x}`));
  }
  if (!c.length && !f.length) console.log(`  [${name}] clean`);
}

/** Vaadin renders server-side, so wait for the DOM to settle before reading. */
async function settled(page: Page, timeoutMs = 25_000): Promise<string> {
  let last = -1;
  let stable = 0;
  const deadline = Date.now() + timeoutMs;
  let body = '';
  while (Date.now() < deadline) {
    body = await page.locator('body').innerText().catch(() => '');
    if (body.length === last) {
      if (++stable >= 2) return body;
    } else {
      stable = 0;
      last = body.length;
    }
    await page.waitForTimeout(700);
  }
  return body;
}

async function listClaims(request: APIRequestContext): Promise<Array<Record<string, unknown>>> {
  const r = await request.get(`${API}/claims`);
  if (!r.ok()) return [];
  const j = await r.json().catch(() => null);
  const rows = (j as { data?: unknown } | null)?.data;
  return Array.isArray(rows) ? (rows as Array<Record<string, unknown>>) : [];
}

test('claimsiq: the REST surface answers', async ({ request }) => {
  test.setTimeout(120_000);
  const health = await request.get(`${API}/health`);
  console.log(`  GET /health -> ${health.status()} ${(await health.text()).slice(0, 80)}`);
  expect(health.status(), 'health endpoint').toBe(200);

  const r = await request.get(`${API}/claims`);
  const body = await r.json().catch(() => null);
  console.log(`  GET /claims -> ${r.status()}, ${(body?.data ?? []).length} claim(s)`);
  expect(r.status()).toBe(200);
});

test('claimsiq: every view renders', async ({ page }) => {
  test.setTimeout(300_000);
  const g = watch(page);
  const routes = ['/', '/fnol', '/claims', '/review', '/help'];
  const sizes: number[] = [];
  for (const route of routes) {
    await page.goto(`${CIQ}${route}`, { waitUntil: 'domcontentloaded' });
    const body = await settled(page);
    const fatal = /Whitelabel Error|HTTP Status 5\d\d|Internal Server Error|could not be found/i;
    console.log(`  ${route.padEnd(8)} -> ${body.length} chars`);
    expect(fatal.test(body), `${route}: server error page`).toBeFalsy();
    expect(body.length, `${route}: looks blank`).toBeGreaterThan(200);
    sizes.push(body.length);
  }
  // Identical sizes everywhere would mean routing is not really happening.
  expect(new Set(sizes).size, 'every view rendered the same thing').toBeGreaterThan(1);
  await page.screenshot({ path: 'e2e/screenshots/claimsiq-views.png', fullPage: true });
  report('views', g);
});

test('claimsiq: file an FNOL and adjudicate it end to end', async ({ page, request }) => {
  test.setTimeout(900_000);
  const g = watch(page);

  const before = (await listClaims(request)).length;
  console.log(`  claims before: ${before}`);

  await page.goto(`${CIQ}/fnol`, { waitUntil: 'domcontentloaded' });
  await settled(page);
  await page.screenshot({ path: 'e2e/screenshots/claimsiq-fnol.png', fullPage: true });

  // Vaadin labels the inputs, so target by label rather than position.
  const fill = async (label: string, value: string) => {
    const box = page.getByLabel(label, { exact: false }).first();
    if (await box.count()) {
      await box.fill(value);
      return true;
    }
    console.log(`  (no field labelled "${label}")`);
    return false;
  };
  await fill('Claimant name', 'Dana Whitfield');
  await fill('Policy number', 'POL-4471-AUTO');
  await fill('Channel', 'web');
  await fill(
    'Describe the loss',
    'Rear-ended at a junction in heavy rain. Bumper and tailgate crumpled, ' +
      'rear camera cracked. No injuries. Third party admitted fault at the scene.',
  );

  // The multimodal damage-assessment node needs images.
  const photos = page.getByRole('button', { name: /sample photos/i }).first();
  if (await photos.count()) {
    await photos.click();
    console.log('  attached the sample photos');
    await page.waitForTimeout(1500);
  }

  const submit = page.getByRole('button', { name: /Submit FNOL/i }).first();
  await expect(submit, 'no FNOL submit button').toBeVisible({ timeout: 20_000 });
  await submit.click();
  console.log('  submitted; waiting for the 7-node pipeline');

  // Poll the REST surface rather than trusting the page, so this asserts a real
  // persisted claim rather than optimistic UI.
  const TERMINAL = ['approved', 'partial', 'denied', 'routed_to_human', 'failed'];
  let claims: Array<Record<string, unknown>> = [];
  let status = '';
  for (let i = 0; i < 120; i++) {
    await page.waitForTimeout(6000);
    claims = await listClaims(request);
    if (claims.length > before) {
      status = String(claims[0].status || '');
      if (TERMINAL.includes(status)) break;
      if (i % 10 === 9) console.log(`  ...${(i + 1) * 6}s, status = ${status}`);
    }
  }
  console.log(`  final status: ${status || '(none)'}`);
  console.log(`  claims after: ${claims.length}`);
  expect(claims.length, 'FNOL did not create a claim').toBeGreaterThan(before);

  const claim = claims[0] as Record<string, unknown>;
  console.log(`  newest claim keys: ${Object.keys(claim).join(', ')}`);
  for (const k of [
    'id', 'claimantName', 'policyNumber', 'status', 'decision', 'approvedAmountUsd',
    'fraudRiskTier', 'fraudScore', 'damageSeverity', 'executionId', 'costUsd',
    'durationMs', 'errorMessage',
  ]) {
    if (k in claim) console.log(`    ${k} = ${String(claim[k]).slice(0, 160)}`);
  }

  // The pipeline is what makes this more than a CRUD insert: a real run leaves
  // an execution id behind and a decision on the row.
  expect(claim.executionId, 'claim has no executionId — the pipeline never fired').toBeTruthy();

  // A claim still on a non-terminal status means nobody ever wrote the result
  // back. That used to pass here because "[not available]" reads as truthy.
  expect(TERMINAL, `claim stuck on status=${status}`).toContain(status);

  // "[not available]" is the engine's unresolved-template placeholder. Treating
  // it as a value is what let a collapsed pipeline look like a clean run.
  const placeholder = (v: unknown) => String(v ?? '').trim() === '[not available]';
  for (const k of ['decision', 'draftLetter', 'adjusterNotes', 'fraudRiskTier']) {
    expect(placeholder(claim[k]), `${k} is an unresolved placeholder`).toBeFalsy();
  }

  if (status === 'failed') {
    throw new Error(`adjudication failed: ${String(claim.errorMessage).slice(0, 400)}`);
  }
  if (claim.errorMessage) {
    // routed_to_human with a reason is a legitimate outcome, but a degraded run
    // says so here, so it is not mistaken for a clean adjudication.
    console.log(`  NOTE: degraded -> ${String(claim.errorMessage).slice(0, 300)}`);
  }
  expect(
    Boolean(claim.decision) || status === 'routed_to_human',
    'run completed with no decision at all',
  ).toBeTruthy();

  // And it should be reachable in the UI, not just the API.
  await page.goto(`${CIQ}/claims`, { waitUntil: 'domcontentloaded' });
  const list = await settled(page);
  expect(list, 'claimant missing from the claims list').toContain('Dana Whitfield');
  console.log('  claim visible in /claims');

  await page.goto(`${CIQ}/claims/${claim.id}`, { waitUntil: 'domcontentloaded' });
  const detail = await settled(page);
  console.log(`  /claims/{id} -> ${detail.length} chars`);
  expect(detail.length, 'claim detail looks blank').toBeGreaterThan(400);
  await page.screenshot({ path: 'e2e/screenshots/claimsiq-detail.png', fullPage: true });

  await page.screenshot({ path: 'e2e/screenshots/claimsiq-after-fnol.png', fullPage: true });
  report('fnol', g);
});
