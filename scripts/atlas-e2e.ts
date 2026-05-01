import { chromium, type Browser, type Page } from 'playwright';
import path from 'path';
import fs from 'fs';

const BASE = process.env.ABENIX_URL || 'http://localhost:8088';
const EMAIL = process.env.ABENIX_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.ABENIX_PASSWORD || 'Admin123456';
const OUT_DIR = path.resolve(__dirname, '..', 'docs', 'screenshots', 'atlas-e2e');
const FIXTURE_FILE = path.join(OUT_DIR, '_fixture.txt');

if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });
fs.writeFileSync(FIXTURE_FILE, [
  'Procurement Process Overview',
  '',
  'A Buyer raises a PurchaseRequest for goods or services.',
  'A Manager approves or rejects each PurchaseRequest based on policy.',
  'When approved, the system issues a PurchaseOrder to the chosen Supplier.',
  'The Supplier delivers Goods and submits an Invoice.',
  'The Buyer reconciles the Invoice against the PurchaseOrder before Payment is released.',
  '',
  'Key business rules:',
  '- Every PurchaseOrder must reference exactly one PurchaseRequest.',
  '- A Supplier can fulfil many PurchaseOrders.',
  '- Each Invoice belongs to one PurchaseOrder.',
  '- Payments require a reconciled Invoice.',
].join('\n'));

interface StepResult { name: string; ok: boolean; detail: string; ms: number; }
const results: StepResult[] = [];

async function step<T>(name: string, fn: () => Promise<T>): Promise<T | undefined> {
  const start = Date.now();
  try {
    const out = await fn();
    const ms = Date.now() - start;
    results.push({ name, ok: true, detail: '', ms });
    console.log(`  PASS  ${name}  (${ms} ms)`);
    return out;
  } catch (e: any) {
    const ms = Date.now() - start;
    const detail = (e?.message || String(e)).split('\n')[0].slice(0, 200);
    results.push({ name, ok: false, detail, ms });
    console.log(`  FAIL  ${name}  (${ms} ms)  ${detail}`);
    return undefined;
  }
}

async function snap(page: Page, name: string) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: false });
}

async function login(page: Page) {
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.locator('#auth-email').waitFor({ timeout: 25_000 });
  await page.waitForTimeout(2_000); // let React hydrate fully
  // Framer-motion on this auth card causes Playwright's synthetic click to be
  // swallowed by React 18 occasionally. Use the React fiber to invoke the
  // Admin Demo onClick directly — it calls submitLogin() which hits the
  // login endpoint and redirects to /dashboard.
  const fired = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === 'Admin Demo') as HTMLButtonElement | undefined;
    if (!btn) return 'no Admin Demo button';
    const key = Object.keys(btn).find(k => k.startsWith('__reactProps$'));
    if (!key) return 'no __reactProps key';
    const onClick = (btn as any)[key].onClick;
    if (typeof onClick !== 'function') return 'no onClick';
    onClick();
    return 'fired';
  });
  if (fired !== 'fired') throw new Error(`could not fire Admin Demo onClick: ${fired}`);
  await page.waitForURL((url) => /\/dashboard|\/atlas|\/agents|\/home/.test(url.pathname), { timeout: 30_000 });
  await page.waitForTimeout(2_000);
}

async function dismissPrompt(page: Page, value?: string) {
  const promptInput = page.locator('input').filter({ hasText: '' }).last();
  // The PromptModal renders an input that auto-focuses
  const inp = page.locator('div.fixed.inset-0 input').first();
  await inp.waitFor({ timeout: 5000 });
  if (value) await inp.fill(value);
  // Click the modal's confirm button (any of: Create / OK / Snap / "Add to atlas")
  await page.getByRole('button', { name: /Create|OK|Snap/i }).last().click({ trial: false }).catch(async () => {
    // Fallback: press Enter
    await inp.press('Enter');
  });
  await page.waitForTimeout(800);
}

async function dismissConfirm(page: Page, mode: 'confirm' | 'cancel' = 'confirm') {
  if (mode === 'confirm') {
    await page.getByRole('button', { name: /Delete atlas|Restore|Confirm/i }).last().click().catch(() => {});
  } else {
    await page.getByRole('button', { name: /Cancel/i }).last().click().catch(() => {});
  }
  await page.waitForTimeout(600);
}

async function run() {
  const browser: Browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: 'dark',
    ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();
  page.on('console', msg => {
    if (msg.type() === 'error') console.log(`    [console.error] ${msg.text().slice(0, 200)}`);
  });

  console.log(`\n🧪  Atlas E2E against ${BASE}\n`);
  await step('login', () => login(page));

  await step('navigate to /atlas', async () => {
    await page.goto(`${BASE}/atlas`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2_000);
  });

  // 1. Create a fresh graph
  await step('create new graph via PromptModal', async () => {
    await page.getByRole('button', { name: /New atlas/i }).first().click();
    await page.waitForTimeout(700);
    const inp = page.locator('div.fixed.inset-0 input').first();
    await inp.waitFor({ timeout: 5000 });
    await inp.fill('E2E Smoke Test ' + Date.now());
    await page.getByRole('button', { name: /^Create$/i }).first().click();
    await page.waitForTimeout(2000);
    // Verify the graph is now active — the empty-state onboarding should be visible
    const onboarding = page.getByText(/Your atlas is empty/i);
    if (!(await onboarding.count())) throw new Error('onboarding panel not shown after create');
  });
  await snap(page, '01-after-create');

  // 2. Verify the four onboarding cards render
  await step('verify onboarding cards', async () => {
    for (const cta of [/Browse starters/i, /Pick a file/i, /Focus the input/i, /Add a concept/i]) {
      if (!(await page.getByText(cta).count())) throw new Error(`onboarding CTA missing: ${cta}`);
    }
  });

  // 3. Add a concept manually
  await step('add concept manually', async () => {
    await page.getByRole('button', { name: /^Concept$/i }).first().click();
    await page.waitForTimeout(700);
    const inp = page.locator('div.fixed.inset-0 input').first();
    await inp.fill('Counterparty');
    await page.getByRole('button', { name: /^Create$/i }).first().click();
    await page.waitForTimeout(1500);
    if (!(await page.locator('.react-flow__node').count())) {
      throw new Error('node did not appear on canvas');
    }
  });
  await snap(page, '02-concept-added');

  // 4. Add an instance manually
  await step('add instance manually', async () => {
    await page.getByRole('button', { name: /^Instance$/i }).first().click();
    await page.waitForTimeout(600);
    const inp = page.locator('div.fixed.inset-0 input').first();
    await inp.fill('ACME Corp');
    await page.getByRole('button', { name: /^Create$/i }).first().click();
    await page.waitForTimeout(1500);
    const count = await page.locator('.react-flow__node').count();
    if (count < 2) throw new Error(`expected 2 nodes, got ${count}`);
  });
  await snap(page, '03-instance-added');

  // 5. Type an NL sentence
  await step('NL parse — review ribbon', async () => {
    const nl = page.locator('input[data-atlas-nl]').first();
    await nl.fill('Counterparty has many Trades. Each Trade settles via exactly one SSI.');
    await page.getByRole('button', { name: /Add to atlas/i }).first().click();
    // Wait for the proposed-ops ribbon
    await page.waitForSelector('text=/operation/', { timeout: 60_000 });
  });
  await snap(page, '04-nl-proposed');

  await step('apply NL ops', async () => {
    await page.getByRole('button', { name: /Apply all/i }).first().click();
    await page.waitForTimeout(2500);
    const count = await page.locator('.react-flow__node').count();
    if (count < 4) throw new Error(`expected 4+ nodes after NL apply, got ${count}`);
  });
  await snap(page, '05-nl-applied');

  // 6. Import the FIBO Core starter
  await step('open Starters modal', async () => {
    await page.getByRole('button', { name: /^Starters$/i }).first().click();
    await page.waitForTimeout(800);
    if (!(await page.getByText(/FIBO Core/i).count())) throw new Error('starters list did not load');
  });

  await step('import FIBO Core starter', async () => {
    // Click the Import button on the FIBO row
    const fiboRow = page.getByText(/FIBO Core/i).first().locator('..').locator('..');
    await fiboRow.getByRole('button', { name: /Import/i }).click();
    await page.waitForTimeout(4000);
    const count = await page.locator('.react-flow__node').count();
    if (count < 8) throw new Error(`expected 8+ nodes after FIBO import, got ${count}`);
  });
  await snap(page, '06-fibo-imported');

  // 7. Layout modes
  for (const mode of ['circle', 'grid', 'semantic'] as const) {
    await step(`relayout — ${mode}`, async () => {
      // Find the layout toolbar — look for buttons by title attribute
      const titleMap: Record<string, RegExp> = {
        circle: /Circular layout/i,
        grid: /Grid layout/i,
        semantic: /Semantic layout/i,
      };
      const btn = page.locator(`button[title*="${mode === 'circle' ? 'Circular' : mode === 'grid' ? 'Grid' : 'Semantic'}"]`).first();
      await btn.click();
      await page.waitForTimeout(2500);
    });
    await snap(page, `07-layout-${mode}`);
  }

  // 8. Visual query
  await step('open Visual Query panel', async () => {
    await page.getByRole('button', { name: /^Query$/i }).first().click();
    await page.waitForTimeout(800);
  });

  await step('run visual query', async () => {
    // Type into the first label_like input (the only one initially)
    const input = page.locator('input[placeholder*="Label contains"]').first();
    await input.fill('Trade');
    await page.getByRole('button', { name: /^Run$/i }).first().click();
    await page.waitForTimeout(1500);
    // Should show "match" cards
    if (!(await page.getByText(/match/).count())) throw new Error('no match cards rendered');
  });
  await snap(page, '08-visual-query');

  // close query panel
  await page.keyboard.press('Escape').catch(() => {});

  // 9. Click first node and exercise inspector tabs
  await step('select first node', async () => {
    await page.locator('.react-flow__node').first().click();
    await page.waitForTimeout(600);
  });

  for (const tab of ['relations', 'properties', 'instances', 'lineage', 'schema'] as const) {
    await step(`inspector tab — ${tab}`, async () => {
      await page.getByRole('button', { name: new RegExp(`^${tab}$`, 'i') }).first().click();
      await page.waitForTimeout(400);
    });
  }
  await snap(page, '09-inspector-lineage');

  // 10. Snapshot capture
  await step('capture snapshot', async () => {
    await page.getByRole('button', { name: /^Snap$/i }).first().click();
    await page.waitForTimeout(700);
    const inp = page.locator('div.fixed.inset-0 input').first();
    await inp.fill('e2e checkpoint');
    await page.getByRole('button', { name: /^Snap$/i }).last().click();
    await page.waitForTimeout(1500);
  });

  // 11. Open History panel
  await step('open History panel', async () => {
    await page.getByRole('button', { name: /^History$/i }).first().click();
    await page.waitForTimeout(1000);
    if (!(await page.getByText(/Time slider/i).count())) throw new Error('history panel did not render');
  });
  await snap(page, '10-history');

  // close history
  await page.keyboard.press('Escape').catch(() => {});

  // 12. JSON-LD export
  await step('JSON-LD export download', async () => {
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 15_000 }),
      page.getByRole('button', { name: /^JSON-LD$/i }).first().click(),
    ]);
    const exported = path.join(OUT_DIR, '_export.jsonld');
    await download.saveAs(exported);
    const txt = fs.readFileSync(exported, 'utf-8');
    if (!txt.includes('"@graph"') || !txt.includes('"@context"')) throw new Error('export does not look like JSON-LD');
  });

  // 13. Drop file extraction (simulate by setting input files directly)
  await step('drop-to-extract — file upload', async () => {
    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles(FIXTURE_FILE);
    // Wait for proposal ribbon (LLM call can be slow)
    await page.waitForSelector('text=/Extracted ontology|operation/', { timeout: 90_000 });
  });
  await snap(page, '11-extract-proposed');

  await step('apply extracted ops', async () => {
    await page.getByRole('button', { name: /Apply all/i }).first().click();
    await page.waitForTimeout(3000);
  });
  await snap(page, '12-extract-applied');

  // 14. Test ConfirmModal — try delete, then cancel
  await step('ConfirmModal — cancel deletes nothing', async () => {
    const before = await page.locator('.react-flow__node').count();
    // Sidebar rows have a hover-revealed Trash2 button (icon class is `lucide-trash2`, no hyphen).
    const rows = page.locator('aside.w-64 div.group');
    if (await rows.count() === 0) throw new Error('no graphs in sidebar');
    const activeRow = rows.first();
    await activeRow.hover();
    await page.waitForTimeout(300);
    const trashBtn = activeRow.locator('button:has(svg.lucide-trash2)').first();
    if (await trashBtn.count() === 0) throw new Error('trash button not found');
    await trashBtn.click({ force: true });
    await page.waitForTimeout(700);
    await page.getByRole('button', { name: /^Cancel$/i }).first().click();
    await page.waitForTimeout(1200);
    const after = await page.locator('.react-flow__node').count();
    if (after !== before) throw new Error(`canvas changed unexpectedly: ${before} -> ${after}`);
  });

  // 15. Bind to KB (open the picker, bind to the first KB)
  await step('open KB picker', async () => {
    await page.getByRole('button', { name: /Bind KB|KB linked/i }).first().click();
    await page.waitForTimeout(1500);
    if (!(await page.getByText(/Bind to knowledge collection/i).count())) throw new Error('KB picker did not open');
  });

  await step('bind first KB', async () => {
    // KB rows in the picker each contain a Database icon (lucide-database).
    // We click the FIRST KB row (other than the "— None —" reset button).
    const kbButtons = page.locator('div.fixed.inset-0 button:has(svg.lucide-database)');
    const cnt = await kbButtons.count();
    if (cnt === 0) {
      await page.keyboard.press('Escape').catch(() => {});
      throw new Error('no KBs in tenant — cannot test KB binding');
    }
    await kbButtons.first().click({ force: true });
    await page.waitForTimeout(2500);
    if (!(await page.getByRole('button', { name: /KB linked/i }).count())) {
      throw new Error('KB linked badge did not appear');
    }
  });
  await snap(page, '13-kb-linked');

  // 16. Final delete the test graph (cleanup)
  await step('delete the test graph', async () => {
    const rows = page.locator('aside.w-64 div.group');
    const activeRow = rows.first();
    await activeRow.hover();
    await page.waitForTimeout(300);
    const trashBtn = activeRow.locator('button:has(svg.lucide-trash2)').first();
    await trashBtn.click({ force: true });
    await page.waitForTimeout(700);
    await page.getByRole('button', { name: /Delete atlas/i }).first().click();
    await page.waitForTimeout(2000);
  });

  await browser.close();

  // ── Report ────────────────────────────────────────────────────────
  const passed = results.filter(r => r.ok).length;
  const failed = results.filter(r => !r.ok).length;

  console.log(`\n────────────────────────────────────────`);
  console.log(`  ${passed} passed · ${failed} failed`);
  console.log(`────────────────────────────────────────\n`);

  if (failed) {
    console.log('Failures:');
    for (const r of results.filter(r => !r.ok)) console.log(`  • ${r.name} — ${r.detail}`);
  }

  // Persist a markdown report
  const md = [
    `# Atlas E2E results`,
    ``,
    `**${passed} passed · ${failed} failed**`,
    ``,
    `Run against \`${BASE}\` on ${new Date().toISOString()}.`,
    ``,
    `| # | Step | Result | ms | Detail |`,
    `|---|------|--------|----|--------|`,
    ...results.map((r, i) => `| ${i + 1} | ${r.name} | ${r.ok ? '✅' : '❌'} | ${r.ms} | ${r.detail || ''} |`),
  ].join('\n');
  fs.writeFileSync(path.join(OUT_DIR, 'report.md'), md);

  process.exit(failed === 0 ? 0 : 1);
}

run().catch(err => {
  console.error('Atlas E2E crashed:', err);
  process.exit(2);
});
