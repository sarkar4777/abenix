/**
 * A new teammate builds a supplier risk desk, strictly through the UI.
 *
 * The admin invites them from the Team page, they accept the invite and set a
 * password, then everything else is clicks and typing as that user:
 *
 *   1. Code Runner   upload supplier_risk.zip, wait for analysis, test-run it
 *   2. Builder       "Use in Agent", name it, prompt it, save, publish
 *   3. Chat          score three suppliers, open the run on the Flight Recorder
 *   4. Knowledge     create a KB, upload the procurement policy, search it
 *   5. Atlas         create a graph from plain sentences, bind the KB
 *   6. Builder       an analyst agent with knowledge + atlas tools, pinned
 *   7. Chat          ask a question that needs the policy and the graph
 *   8. Pipeline      chain both agents and a summary step, run it
 *   9. SDK playground  run live, generate code, run it in the browser
 *  10. Triggers      webhook test, schedule run-now
 *  11. Executions    re-run from the recorder lands in chat prefilled
 *  12. Agents        share, duplicate, publish options for this role
 *  13. API keys      create and revoke
 *
 * No API calls for setup. Findings go to test-results/user-journey.json with a
 * screenshot per step.
 *
 *   BASE=http://localhost:3100 npx playwright test e2e/uat_user_journey_ui.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };
const STAMP = Date.now().toString().slice(-6);
const USER = { email: `riskdesk.${STAMP}@abenix.dev`, name: `Riya Desk ${STAMP}`, password: 'RiskDesk!2026' };
const FIX = path.join(__dirname, 'fixtures', 'supplier_risk');
const OUT = path.join('test-results', 'user-journey.json');
const SHOTS = path.join('test-results', 'user-journey');

const NAMES = {
  asset: `supplier-risk-${STAMP}`,
  scorer: `Supplier Risk Scorer ${STAMP}`,
  kb: `Procurement Policy ${STAMP}`,
  atlas: `Supply Network ${STAMP}`,
  analyst: `Policy Network Analyst ${STAMP}`,
  pipeline: `Supplier Risk Briefing ${STAMP}`,
  lead: `Supplier Desk Lead ${STAMP}`,
};

const SUPPLIERS = JSON.stringify({
  suppliers: [
    { name: 'Nordtek', current_ratio: 0.8, debt_to_equity: 2.1, on_time_delivery_pct: 86, single_source: true, country_risk: 'medium' },
    { name: 'Alba Castings', current_ratio: 1.9, debt_to_equity: 0.4, on_time_delivery_pct: 99, single_source: false, country_risk: 'low' },
    { name: 'Vistula Polymers', current_ratio: 1.1, debt_to_equity: 1.2, on_time_delivery_pct: 93, single_source: true, country_risk: 'high' },
  ],
});

type Finding = { step: string; ok: boolean; what: string; screenshot?: string };
const findings: Finding[] = [];

async function shot(page: Page, name: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const p = path.join(SHOTS, `${String(findings.length).padStart(2, '0')}-${name}.png`);
  await page.screenshot({ path: p, fullPage: true }).catch(() => {});
  return p;
}

async function record(page: Page, step: string, ok: boolean, what: string) {
  const screenshot = await shot(page, step.replace(/[^a-z0-9]+/gi, '-').toLowerCase());
  findings.push({ step, ok, what, screenshot });
  console.log(`  [${ok ? 'ok' : 'WALL'}] ${step}: ${what}`);
  expect.soft(ok, `${step}: ${what}`).toBeTruthy();
}

async function go(page: Page, route: string) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function mainText(page: Page) {
  const main = page.locator('main');
  return ((await main.count()) ? await main.first().innerText() : await page.locator('body').innerText()).slice(0, 40000);
}

/** Sign in through the landing page form. */
async function signIn(page: Page, email: string, password: string) {
  await go(page, '/');
  const toSignIn = page.getByRole('button', { name: 'Switch to sign in' });
  if (await toSignIn.count()) await toSignIn.click().catch(() => {});
  await page.locator('#auth-email').fill(email);
  await page.locator('#auth-password').fill(password);
  await page.getByTestId('auth-submit').click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

async function signOut(page: Page) {
  const btn = page.locator('button[aria-label="Log out"]').first();
  if (await btn.count()) await btn.click();
  else {
    await page.locator('header button').last().click().catch(() => {});
    await page.locator('button[aria-label="Log out of your account"]').click();
  }
  await page.waitForURL((u) => new URL(u).pathname === '/', { timeout: 20_000 });
}

/** Type into the chat composer, send, and wait until streaming is over. */
async function chat(page: Page, message: string, timeoutMs = 240_000) {
  const input = page.getByTestId('chat-input');
  await expect(input).toBeVisible({ timeout: 30_000 });
  await input.fill(message);
  await page.getByTestId('chat-send').click();
  await expect(page.getByTestId('chat-stop')).toBeVisible({ timeout: 15_000 }).catch(() => {});
  await expect(page.getByTestId('chat-send')).toBeVisible({ timeout: timeoutMs });
  await page.waitForTimeout(1500);
  const replies = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const n = await replies.count();
  return n ? await replies.nth(n - 1).innerText() : '';
}

/** Add a tool from the builder palette by clicking it. */
async function addTool(page: Page, id: string) {
  const search = page.getByPlaceholder('Search tools, descriptions, params...');
  await search.fill(id);
  await page.waitForTimeout(400);
  await page.getByTestId(`palette-tool-${id}`).first().click();
  await search.fill('');
}

async function setAgentBasics(page: Page, name: string, description: string, prompt: string) {
  // the name lives in the top bar, everything else in the right panel
  await page.getByTestId('builder-name-button').click();
  await page.getByTestId('builder-name-input').fill(name);
  await page.getByTestId('builder-name-input').press('Enter');
  await page.getByTestId('config-tab-general').click();
  await page.getByTestId('builder-description').fill(description);
  await page.getByTestId('builder-category').selectOption({ index: 1 });
  await page.getByTestId('config-tab-prompt').click();
  await page.getByTestId('builder-system-prompt').fill(prompt);
}

async function saveAndPublish(page: Page): Promise<string> {
  await page.getByTestId('builder-save-draft').click();
  await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
  await expect(page.getByText('Saved', { exact: false }).first()).toBeVisible({ timeout: 20_000 }).catch(() => {});
  const agentId = new URL(page.url()).searchParams.get('agent') || '';
  await page.getByTestId('builder-publish').click();
  await page.getByTestId('publish-visibility-org').click();
  await page.getByTestId('publish-submit').click();
  await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
  return agentId;
}

test.use({ viewport: { width: 1440, height: 900 } });

test('a new teammate builds a supplier risk desk through the UI', async ({ page }) => {
  test.setTimeout(45 * 60_000);
  page.on('dialog', (d) => d.accept());
  const ids: Record<string, string> = {};

  try {
    // ── 0. the admin invites a teammate ───────────────────────────────────
    await test.step('admin invites a teammate from the Team page', async () => {
      await signIn(page, ADMIN.email, ADMIN.password);
      await go(page, '/settings/team');
      await page.getByRole('button', { name: 'Invite Member' }).click();
      await page.locator('input[placeholder="email@example.com"]').fill(USER.email);
      await page.locator('select').filter({ hasText: /member|user/i }).first().selectOption('user').catch(async () => {
        await page.locator('select').last().selectOption('user');
      });
      await page.getByRole('button', { name: 'Send' }).click();
      const link = page.getByTestId('invite-link');
      await expect(link).toBeVisible({ timeout: 15_000 });
      ids.invite = ((await link.innerText()) || (await link.inputValue().catch(() => ''))).trim();
      await record(page, 'invite', /accept-invite\?token=/.test(ids.invite), `invite link ${ids.invite.slice(0, 60)}`);
      await signOut(page);
    });

    // ── 1. the teammate accepts and lands on the dashboard ────────────────
    await test.step('teammate accepts the invite', async () => {
      const url = ids.invite.startsWith('http') ? ids.invite.replace(/^https?:\/\/[^/]+/, BASE) : `${BASE}${ids.invite}`;
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('#accept-full-name')).toBeVisible({ timeout: 20_000 });
      // the invited address is shown read-only, the user cannot change it
      await expect(page.locator('input[readonly], input[disabled]').first()).toHaveValue(USER.email);
      await page.locator('#accept-full-name').fill(USER.name);
      await page.locator('#accept-password').fill(USER.password);
      await page.getByTestId('accept-submit').click();
      await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
      await record(page, 'accept invite', true, 'signed in as the new teammate');
      // a new user is shown where to start, not an empty dashboard
      const guide = page.getByTestId('start-here');
      await expect(guide).toBeVisible({ timeout: 20_000 });
      const firstDone = await guide.locator('li[data-done]').first().getAttribute('data-done');
      await record(page, 'getting started', firstDone === 'false', `dashboard guides a new user, first step done=${firstDone}`);
      // and they can sign in again with the password they chose
      await signOut(page);
      await signIn(page, USER.email, USER.password);
      await record(page, 'password sign-in', true, 'password sign-in works');
    });

    // ── 2. custom code ────────────────────────────────────────────────────
    await test.step('upload and test the custom scorer in Code Runner', async () => {
      await go(page, '/code-runner');
      await page.getByPlaceholder('Name (e.g. sentiment-scorer)').fill(NAMES.asset);
      await page.getByPlaceholder('Description (optional)').fill('Scores supplier financial risk from ratios, stdin JSON in, JSON out');
      await page.locator('input[type=file][accept=".zip"]').setInputFiles(path.join(FIX, 'supplier_risk.zip'));
      await page.getByRole('button', { name: /Create & analyze/ }).click();
      const item = page.locator(`[data-testid="code-asset-item"][data-name="${NAMES.asset}"]`);
      await expect(item).toBeVisible({ timeout: 30_000 });
      // the list polls on its own while analysis runs, no reload needed
      await expect(item).toHaveAttribute('data-status', /ready|failed/, { timeout: 240_000 });
      await record(page, 'code analysis status', (await item.getAttribute('data-status')) === 'ready', `asset status ${await item.getAttribute('data-status')}`);
      await item.click();
      await page.waitForTimeout(800);
      const detail = await mainText(page);
      await record(page, 'code analysis', /python/i.test(detail) && /main\.py/.test(detail), 'analyzer detected Python and main.py');
      await page.getByTestId('code-test-input').fill(SUPPLIERS);
      await page.getByTestId('code-test-run').click();
      await expect(page.getByTestId('code-test-output')).toContainText('SUPPLIER_RISK_ENGINE_V1', { timeout: 240_000 });
      const out = await page.getByTestId('code-test-output').innerText();
      await record(page, 'code test run', /Nordtek/i.test(out) && /"red"/.test(out), 'test run scored Nordtek red');
      await page.getByTestId('code-use-in-agent').click();
      await page.waitForURL(/\/builder/, { timeout: 20_000 });
    });

    // ── 3. scorer agent ───────────────────────────────────────────────────
    await test.step('build and publish the scorer agent', async () => {
      await expect(page.locator('[data-id="tool-code_asset"], [data-testid*="code_asset"]').first()).toBeVisible({ timeout: 20_000 });
      await setAgentBasics(
        page,
        NAMES.scorer,
        'Scores supplier risk with the supplier-risk code asset and explains the drivers for each supplier.',
        'You are a supplier risk analyst. When given supplier data, ALWAYS call the code_asset tool with input {"suppliers": [...]} exactly as given, ' +
          'then report each supplier with its risk_score, tier and top_drivers, highest risk first. Never compute scores yourself.',
      );
      ids.scorer = await saveAndPublish(page);
      await record(page, 'scorer published', !!ids.scorer, `agent ${ids.scorer}`);
    });

    await test.step('score suppliers in chat and open the run', async () => {
      const text = await chat(page, `Score these suppliers: ${SUPPLIERS}`);
      const ok = /Nordtek/i.test(text) && /red/i.test(text) && /76/.test(text);
      await record(page, 'scorer chat', ok, ok ? 'Nordtek red at 76 from the custom code' : `answer tail: ${text.slice(-300)}`);
      const viewRun = page.getByTestId('chat-view-run').last();
      await expect(viewRun).toBeVisible({ timeout: 20_000 });
      await viewRun.click();
      await page.waitForURL(/\/executions\//, { timeout: 20_000 });
      await expect(page.getByTestId('execution-steps')).toBeVisible({ timeout: 20_000 });
      const rec = await mainText(page);
      await record(page, 'flight recorder', /code_asset/.test(rec) && /SUPPLIER_RISK_ENGINE_V1|risk_score/.test(rec), 'recorder shows the code_asset step and its result');
      ids.scorerRun = page.url().split('/executions/')[1];
    });

    // ── 4. knowledge base ─────────────────────────────────────────────────
    await test.step('create the policy knowledge base and search it', async () => {
      await go(page, '/knowledge');
      await page.getByRole('button', { name: 'New Knowledge Base' }).click();
      await page.getByPlaceholder('e.g. Product Documentation').fill(NAMES.kb);
      await page.getByPlaceholder('What kind of documents will this contain?').fill('Procurement risk policy PRP-7');
      await page.getByRole('button', { name: /^Create$/ }).click();
      // creating opens the new base straight away
      await page.waitForURL(/\/knowledge\?id=[0-9a-f-]{36}/, { timeout: 30_000 });
      await expect(page.getByText(NAMES.kb, { exact: true }).first()).toBeVisible({ timeout: 30_000 });
      await page.getByTestId('kb-dropzone-input').setInputFiles(path.join(FIX, 'procurement_policy.md'));
      const doc = page.locator('[data-testid="kb-doc-row"][data-name="procurement_policy.md"]');
      await expect(doc).toBeVisible({ timeout: 30_000 });
      await expect(doc).toHaveAttribute('data-status', /ready|failed/, { timeout: 300_000 });
      await record(page, 'kb upload', (await doc.getAttribute('data-status')) === 'ready', `document status ${await doc.getAttribute('data-status')}`);
      // search straight from the detail view
      await page.getByTestId('kb-open-engine').click();
      await page.waitForURL(/\/knowledge\/[^/]+\/engine/, { timeout: 20_000 });
      await page.getByTestId('kb-search-input').fill('safety stock for a single-sourced component from a red tier supplier');
      await page.getByTestId('kb-search-button').click();
      await expect(page.getByTestId('kb-search-results')).toContainText(/eight weeks|8 weeks|PRP7_SUPPLIER_POLICY_MARKER/i, { timeout: 60_000 });
      await record(page, 'kb search', true, 'search finds the eight-week safety stock rule');
    });

    // ── 5. atlas ──────────────────────────────────────────────────────────
    await test.step('build the supply network in Atlas and bind the KB', async () => {
      await go(page, '/atlas');
      const create = page.getByRole('button', { name: /New atlas|Create your first atlas/ }).first();
      await create.click();
      await page.getByPlaceholder('e.g. Trade-lifecycle ontology').fill(NAMES.atlas);
      await page.getByRole('button', { name: /^Create$/ }).click();
      await expect(page.locator('body')).toContainText(NAMES.atlas, { timeout: 20_000 });
      const nl = page.locator('input[data-atlas-nl]');
      await nl.fill(
        'Nordtek is a supplier. Nordtek supplies the Hydraulic Pump. The Hydraulic Pump is a component used at the Brno plant. ' +
          'Vistula Polymers is a supplier. Vistula Polymers supplies the Seal Kit. The Seal Kit is used at the Lyon plant.',
      );
      await page.getByRole('button', { name: 'Add to atlas' }).click();
      await page.getByRole('button', { name: 'Apply all' }).click({ timeout: 120_000 });
      const nodes = page.getByTestId('atlas-node-count');
      await expect(nodes).not.toHaveAttribute('data-count', '0', { timeout: 60_000 });
      const n = Number(await nodes.getAttribute('data-count'));
      const e = Number(await page.getByTestId('atlas-edge-count').getAttribute('data-count'));
      await record(page, 'atlas build', n >= 4 && e >= 3, `graph has ${n} nodes and ${e} edges`);
      await page.getByRole('button', { name: 'Bind KB' }).click();
      await page.getByText(NAMES.kb, { exact: true }).last().click();
      await expect(page.locator('body')).toContainText('KB linked', { timeout: 20_000 });
      await record(page, 'atlas bind kb', true, 'policy KB linked to the graph');
    });

    // ── 6. analyst agent with knowledge + atlas ───────────────────────────
    await test.step('build the analyst agent with KB and atlas pinned', async () => {
      await page.getByTestId('atlas-use-in-agent').click();
      await page.waitForURL(/\/builder\?.*atlas=/, { timeout: 20_000 });
      await setAgentBasics(
        page,
        NAMES.analyst,
        'Answers supplier exposure questions from procurement policy PRP-7 and the supply network graph.',
        'You analyse supplier exposure. For any question, call atlas_search_grounded or atlas_describe to find which components a supplier provides ' +
          'and which plant uses them, and call knowledge_search for what policy PRP-7 requires. Name the plant and quote the required action.',
      );
      // the graph and the KB arrive pre-attached, the user only checks them
      await page.locator('.react-flow__node[data-id="agent"]').click();
      await page.getByTestId('config-tab-knowledge').click();
      const kbBox = page.getByLabel(NAMES.kb);
      const graphBox = page.locator('label').filter({ hasText: NAMES.atlas }).locator('input[type=checkbox]');
      await record(page, 'analyst prefilled', (await kbBox.isChecked()) && (await graphBox.isChecked()), 'KB and graph arrived ticked from Atlas');
      if (!(await kbBox.isChecked())) await kbBox.check();
      if (!(await graphBox.isChecked())) await graphBox.check();
      for (const t of ['knowledge_search', 'atlas_search_grounded', 'atlas_describe']) {
        if (!(await page.locator(`.react-flow__node[data-id="tool-${t}"]`).count())) await addTool(page, t);
      }
      ids.analyst = await saveAndPublish(page);
      await record(page, 'analyst published', !!ids.analyst, `agent ${ids.analyst}`);
    });

    await test.step('ask a question that needs the policy and the graph', async () => {
      const text = await chat(page, 'Nordtek just moved to the red tier. Which plant is exposed through the parts Nordtek supplies, and what safety stock does policy PRP-7 require?');
      const ok = /Brno/i.test(text) && /(eight|8)[\s-]*weeks?/i.test(text);
      await record(page, 'analyst chat', ok, ok ? 'answer names Brno and the eight-week rule' : `answer tail: ${text.slice(-400)}`);
    });

    // ── 7. pipeline ───────────────────────────────────────────────────────
    await test.step('chain both agents into a pipeline and run it', async () => {
      await go(page, '/builder');
      await page.getByTestId('builder-mode-pipeline').click();
      await page.getByTestId('builder-name-button').click();
      await page.getByTestId('builder-name-input').fill(NAMES.pipeline);
      await page.getByTestId('builder-name-input').press('Enter');

      const addStep = async (paletteId: string) => {
        await page.getByPlaceholder('Search by name, id, or description…').fill(paletteId);
        await page.getByTestId(`pipeline-palette-${paletteId}`).first().click();
        await page.getByPlaceholder('Search by name, id, or description…').fill('');
        await page.waitForTimeout(400);
      };
      const lastNode = () => page.locator('.react-flow__node').last();
      // options read "Name (slug)", so match on the name prefix
      const pickAgent = async (name: string) => {
        const sel = page.getByTestId('step-agent-select');
        await expect(sel.locator('option', { hasText: name })).toHaveCount(1, { timeout: 15_000 });
        const value = await sel.locator('option', { hasText: name }).getAttribute('value');
        await sel.selectOption(value!);
      };

      await addStep('agent_step');
      await lastNode().click();
      await page.getByTestId('step-label-input').fill('score');
      await pickAgent(NAMES.scorer);
      await page.getByTestId('step-agent-task-input').fill(`Score these suppliers: ${SUPPLIERS}`);

      await addStep('agent_step');
      await lastNode().click();
      await page.getByTestId('step-label-input').fill('exposure');
      await pickAgent(NAMES.analyst);
      await page.getByTestId('step-agent-task-input').fill(
        'For the red tier suppliers in this scoring, which plant is exposed and what does PRP-7 require? Scoring: {{score.response}}',
      );
      await page.locator('[data-testid^="step-dep-"]').first().check();

      await addStep('llm_call');
      await lastNode().click();
      await page.getByTestId('step-label-input').fill('briefing');
      await page.getByTestId('step-open-arguments').click();
      await page.getByTestId('step-prompt-input').fill(
        'Write a five line briefing for the VP of Supply Chain. Start with the line "BRIEFING". Scores: {{score.response}} Exposure: {{exposure.response}}',
      );
      await page.getByRole('button', { name: 'General', exact: true }).click();
      await expect(page.locator('[data-testid^="step-dep-"]')).toHaveCount(2);
      for (const box of await page.locator('[data-testid^="step-dep-"]').all()) await box.check();

      await page.getByTestId('builder-save-draft').click();
      await page.waitForURL(/[?&]agent=/, { timeout: 30_000 });
      ids.pipeline = new URL(page.url()).searchParams.get('agent') || '';
      const chips = await page.locator('[data-testid^="validation-chip-"]').first().getAttribute('data-testid').catch(() => '');
      await record(page, 'pipeline saved', !!ids.pipeline && !/error/.test(chips || ''), `pipeline ${ids.pipeline}, validation ${chips || 'n/a'}`);

      await page.getByTestId('builder-publish').click();
      await page.getByTestId('publish-visibility-org').click();
      await page.getByTestId('publish-submit').click();
      await page.waitForURL(/\/agents\/[^/]+\/chat/, { timeout: 30_000 });
      const text = await chat(page, 'Run the supplier risk briefing.', 600_000);
      const ok = /BRIEFING/.test(text) && /Brno/i.test(text);
      await record(page, 'pipeline run', ok, ok ? 'briefing names Brno' : `answer tail: ${text.slice(-400)}`);
      await page.getByTestId('chat-view-run').last().click();
      await page.waitForURL(/\/executions\//, { timeout: 20_000 });
      await expect(page.locator('main')).toContainText('briefing', { timeout: 30_000 }).catch(() => {});
      const rec = await mainText(page);
      await record(page, 'pipeline recorder', /score/.test(rec) && /exposure/.test(rec) && /briefing/.test(rec), 'recorder lists the three steps');
    });

    // ── 7b. sub-agents ────────────────────────────────────────────────────
    await test.step('a lead agent delegates to both agents as sub-agents', async () => {
      // the slug is what invoke_agent needs, the agent page shows it
      const slugOf = async (id: string) => {
        await go(page, `/agents/${id}/info`);
        const el = page.getByTestId('agent-slug');
        await expect(el).toBeVisible({ timeout: 20_000 });
        return (await el.innerText()).trim();
      };
      ids.scorerSlug = await slugOf(ids.scorer);
      ids.analystSlug = await slugOf(ids.analyst);
      await record(page, 'slugs visible', !!ids.scorerSlug && !!ids.analystSlug, `slugs ${ids.scorerSlug}, ${ids.analystSlug}`);

      await go(page, '/builder');
      await setAgentBasics(
        page,
        NAMES.lead,
        'Runs the supplier risk desk by delegating scoring and exposure analysis to the specialist agents.',
        `You lead the supplier risk desk. You never score or look things up yourself. ` +
          `First call invoke_agent with agent_slug "${ids.scorerSlug}" and input {"message": "Score these suppliers: <the supplier JSON from the user>"}. ` +
          `Then, for every red tier supplier in that result, call invoke_agent with agent_slug "${ids.analystSlug}" and input {"message": "<supplier> is red tier, which plant is exposed and what does PRP-7 require?"}. ` +
          `Finish with a short decision note that names each red supplier, its score, the exposed plant and the required action.`,
      );
      await addTool(page, 'invoke_agent');
      ids.lead = await saveAndPublish(page);
      const text = await chat(page, `Run the desk for these suppliers: ${SUPPLIERS}`, 600_000);
      const ok = /Nordtek/i.test(text) && /Brno/i.test(text) && /(eight|8)[\s-]*weeks?/i.test(text);
      await record(page, 'lead delegates', ok, ok ? 'lead combined both sub-agents: Nordtek, Brno, eight weeks' : `answer tail: ${text.slice(-400)}`);
      await page.getByTestId('chat-view-run').last().click();
      await page.waitForURL(/\/executions\//, { timeout: 20_000 });
      const kids = page.getByTestId('execution-children');
      await expect(kids).toBeVisible({ timeout: 20_000 });
      const links = await kids.locator('a').count();
      await record(page, 'sub-agent runs linked', links >= 2, `${links} sub-agent runs listed under the lead's run`);
      await kids.locator('a').first().click();
      await expect(page.getByTestId('execution-parent-link')).toBeVisible({ timeout: 20_000 });
      await record(page, 'child links to parent', true, 'a sub-agent run links back to the lead');
    });

    // ── 8. SDK playground ─────────────────────────────────────────────────
    await test.step('run the scorer from the SDK playground', async () => {
      await go(page, '/sdk-playground');
      await page.getByPlaceholder('Search agents...').fill(NAMES.scorer);
      await page.getByRole('button', { name: new RegExp(NAMES.scorer) }).first().click();
      const inputs = page.getByTestId('live-inputs-panel');
      await expect(inputs).toBeVisible({ timeout: 20_000 });
      await expect(inputs).not.toContainText('Loading input schema', { timeout: 20_000 });
      const first = inputs.locator('textarea, input').first();
      await first.fill(`Score these suppliers: ${SUPPLIERS}`);
      await page.getByTestId('run-live-button').click();
      await expect(page.getByTestId('live-result-panel')).toContainText(/Nordtek/i, { timeout: 300_000 });
      await record(page, 'sdk run live', true, 'live run from the playground scored Nordtek');
      await page.getByRole('button', { name: 'Python' }).first().click();
      await page.getByTestId('generate-code').click();
      await expect(page.locator('pre').filter({ hasText: /import|abenix/i }).first()).toBeVisible({ timeout: 120_000 });
      await page.getByRole('button', { name: /^Run$/ }).first().click();
      const output = page.locator('section, div').filter({ hasText: /^Output/ }).last();
      await expect(output).toContainText(/Nordtek|completed|risk/i, { timeout: 300_000 });
      await record(page, 'sdk run in browser', true, 'generated Python ran in the browser');
    });

    // ── 9. triggers ───────────────────────────────────────────────────────
    await test.step('webhook and schedule triggers', async () => {
      await go(page, `/triggers?agent=${ids.scorer}`);
      // ?agent= opens the dialog with the agent picked, otherwise open it
      const dialog = page.getByRole('heading', { name: 'Create Trigger' });
      await page.waitForTimeout(1500);
      if (!(await dialog.isVisible().catch(() => false))) await page.getByRole('button', { name: 'New Trigger' }).click();
      await expect(dialog).toBeVisible({ timeout: 10_000 });
      await page.getByRole('button', { name: /Webhook/ }).first().click();
      await page.locator('select').filter({ hasText: 'Select an agent...' }).selectOption({ label: NAMES.scorer });
      await page.getByPlaceholder('Message sent to the agent when triggered').fill(`Score these suppliers: ${SUPPLIERS}`);
      await page.getByRole('button', { name: 'Create Trigger' }).click();
      await page.getByRole('button', { name: 'Test' }).first().click();
      await expect(page.locator('body')).toContainText(/triggered|execution|queued|started/i, { timeout: 30_000 });
      await record(page, 'webhook trigger', true, 'webhook trigger created and tested');

      await page.getByRole('button', { name: 'New Trigger' }).click();
      await page.getByRole('button', { name: /Schedule/ }).first().click();
      await page.locator('select').filter({ hasText: 'Select an agent...' }).selectOption({ label: NAMES.scorer });
      await page.getByPlaceholder('*/5 * * * * (every 5 minutes)').fill('0 7 * * 1');
      await page.getByPlaceholder('Message sent to the agent when triggered').fill(`Weekly scoring: ${SUPPLIERS}`);
      await page.getByRole('button', { name: 'Create Trigger' }).click();
      const runNow = page.locator('[data-testid^="trigger-run-"]').last();
      await runNow.click();
      await expect(page.locator('body')).toContainText(/execution|started|queued/i, { timeout: 30_000 });
      await record(page, 'schedule run now', true, 'schedule trigger ran on demand');
    });

    // ── 10. executions and re-run ─────────────────────────────────────────
    await test.step('executions list and re-run from the recorder', async () => {
      await go(page, '/executions');
      await expect(page.locator(`a[href="/executions/${ids.scorerRun}"]`).first()).toBeVisible({ timeout: 30_000 });
      await record(page, 'executions list', true, 'own runs listed');
      await go(page, `/executions/${ids.scorerRun}`);
      await page.getByTestId('execution-rerun').click();
      await page.waitForURL(/\/chat/, { timeout: 20_000 });
      await expect(page.getByTestId('chat-input')).toHaveValue(/Nordtek/, { timeout: 15_000 });
      await record(page, 'rerun prefill', true, 'chat opened with the original input');
    });

    // ── 11. share, duplicate, publish options ────────────────────────────
    await test.step('share, duplicate and publish options', async () => {
      await go(page, `/agents/${ids.analyst}/info`);
      await page.getByRole('button', { name: 'Share' }).first().click();
      await page.getByTestId('share-email').fill(ADMIN.email);
      await page.getByTestId('share-permission').selectOption('execute').catch(() => {});
      await page.getByTestId('share-submit').click();
      await expect(page.locator('body')).toContainText(ADMIN.email, { timeout: 15_000 });
      await record(page, 'share', true, 'analyst shared with the admin');
      await page.keyboard.press('Escape');
      await page.getByTestId('agent-duplicate').click();
      await page.waitForURL(/\/builder\?agent=/, { timeout: 30_000 });
      const dupName = await page.getByTestId('builder-name-button').innerText().catch(() => '');
      await record(page, 'duplicate', /copy|Policy Network Analyst/i.test(dupName), `duplicate opened as "${dupName}"`);
      await page.getByTestId('builder-publish').click();
      const pub = page.getByTestId('publish-visibility-public');
      await expect(page.getByTestId('publish-visibility-org')).toBeVisible({ timeout: 10_000 });
      // the marketplace is either switched off for the deployment or disabled for this role with a reason
      const absent = (await pub.count()) === 0;
      const disabled = !absent && ((await pub.isDisabled().catch(() => false)) || /cannot publish to the marketplace/i.test(await page.locator('body').innerText()));
      await record(page, 'publish options', absent || disabled, absent ? 'marketplace is off for this deployment, option not offered' : 'marketplace option is off for this role and says why');
      await page.keyboard.press('Escape');
    });

    await test.step('the guide is complete', async () => {
      // a member's guide also asks for a follow-up and feedback, done the way the guide leads
      await go(page, '/dashboard');
      const followUp = page.getByTestId('start-here-follow_up-go');
      if (await followUp.waitFor({ timeout: 10_000 }).then(() => true, () => false)) {
        await followUp.click();
        await page.waitForURL(/\/chat/, { timeout: 20_000 });
        const history = page.getByTestId('chat-history-item').first();
        if (await history.waitFor({ timeout: 5_000 }).then(() => true, () => false)) await history.click();
        const reply = await chat(page, 'Say that again in five words or fewer.');
        await record(page, 'follow up', reply.trim().length > 2, 'the agent answered the follow-up in the same thread');
        await go(page, '/dashboard');
      }
      const feedback = page.getByTestId('start-here-give_feedback-go');
      if (await feedback.waitFor({ timeout: 10_000 }).then(() => true, () => false)) {
        await feedback.click();
        await page.waitForURL(/\/chat/, { timeout: 20_000 });
        const history = page.getByTestId('chat-history-item').first();
        if (await history.waitFor({ timeout: 5_000 }).then(() => true, () => false)) await history.click();
        const bar = page.locator('[data-testid="chat-message"][data-role="assistant"]').last().getByTestId('chat-feedback');
        await expect(bar).toBeVisible({ timeout: 30_000 });
        await bar.getByTestId('chat-feedback-down').click();
        // the correction box opens once the thumbs down is saved
        await expect(bar.getByTestId('chat-feedback-box')).toBeVisible({ timeout: 20_000 });
        await bar.getByTestId('chat-feedback-correction').fill('It should have kept to five words.');
        await expect(bar.getByTestId('chat-feedback-send')).toBeEnabled({ timeout: 20_000 });
        await bar.getByTestId('chat-feedback-send').click();
        // isVisible does not wait, so wait for the confirmation itself
        const thanked = await bar.getByTestId('chat-feedback-thanks').waitFor({ timeout: 20_000 }).then(() => true, () => false);
        await record(page, 'feedback', thanked, 'the thumbs took the correction');
        await go(page, '/dashboard');
      }
      const left = await page.locator('[data-testid^="start-here-"][data-done="false"]').count();
      await record(page, 'getting started done', left === 0 || !(await page.getByTestId('start-here').isVisible()), `${left} steps still open`);
    });

    // ── 12. API keys ──────────────────────────────────────────────────────
    await test.step('create and revoke an API key', async () => {
      await go(page, '/settings/api-keys');
      await page.getByTestId('apikey-generate').click();
      await page.getByTestId('apikey-name').fill(`risk desk ${STAMP}`);
      await page.getByTestId('apikey-create').click();
      await expect(page.getByTestId('apikey-created-value')).toBeVisible({ timeout: 15_000 });
      await record(page, 'api key create', true, 'key created and shown once');
      const revokes = page.locator('[data-testid^="apikey-revoke-"]');
      const before = await revokes.count();
      await revokes.first().click();
      // revoking asks first, since anything using the key stops at once
      await page.getByRole('dialog').getByRole('button', { name: 'Revoke key' }).click();
      await expect(page.locator('body')).toContainText('API key revoked', { timeout: 15_000 });
      await expect(revokes).toHaveCount(before - 1, { timeout: 15_000 }).catch(() => {});
      await record(page, 'api key revoke', (await revokes.count()) === before - 1, 'key revoked and removed from the list');
    });

    // ── 13. the admin sees what was shared ────────────────────────────────
    await test.step('the admin can open the shared analyst', async () => {
      await signOut(page);
      await signIn(page, ADMIN.email, ADMIN.password);
      await go(page, `/agents/${ids.analyst}/chat`);
      await expect(page.getByTestId('chat-input')).toBeVisible({ timeout: 20_000 });
      await record(page, 'shared agent visible', true, 'admin can open the shared analyst');
    });
  } finally {
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    fs.writeFileSync(OUT, JSON.stringify({ generated: new Date().toISOString(), user: USER.email, ids, findings }, null, 2));
  }
});
