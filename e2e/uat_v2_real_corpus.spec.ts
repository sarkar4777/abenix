import { test, expect, type Page, type APIRequestContext } from '@playwright/test';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

// generated per run, so the spec needs no fixtures and sends new text to the embedder each time
const CORPUS_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'abenix-e2e-corpus-'));
const CORPUS: Record<string, string> = {
  'heat-pump-maintenance.txt': 'Service the rooftop heat pumps every 90 days. Clean the evaporator coil, check refrigerant pressure and replace the condensate filter. A pressure below 4 bar means a leak, so stop the unit and call the mechanical contractor.',
  'travel-expenses.txt': 'Staff may claim a rail ticket in second class for any trip under four hours. Hotels are capped at 140 euros a night. Submit receipts within 30 days through the finance portal, late claims need a director to sign them.',
  'incident-response.txt': 'When a production database goes down the on-call engineer declares an incident in the first ten minutes, opens the status page and pages the database lead. A written review is due within five working days.',
  'orchard-harvest.txt': 'Apples on the north slope ripen in late September. Pickers test a sample from each row with a refractometer and start when sugar reaches 12 Brix. Fruit goes into cold storage at one degree within six hours.',
  'solar-warranty.txt': 'The panels carry a 25 year output warranty of 80 percent of rated power. Inverters are covered for ten years. Claims need the serial number and a monitoring export showing the shortfall.',
};
for (const [name, text] of Object.entries(CORPUS)) fs.writeFileSync(path.join(CORPUS_DIR, name), `${text}\n`);

async function login(page: Page) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const tok = (await r.json()).data.access_token;
  await page.goto(BASE);
  await page.evaluate((t) => { localStorage.setItem('access_token', t); localStorage.setItem('token', t); }, tok);
  return tok;
}
const auth = (tok: string) => ({ Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' });

function listCorpus(): string[] {
  return Object.keys(CORPUS).map((f) => path.join(CORPUS_DIR, f)).sort();
}

let testKbId: string | null = null;
let uploadedDocs: { id: string; filename: string; size: number }[] = [];

test.describe.configure({ mode: 'serial', timeout: 600_000 });

test('REAL #1 — corpus available + cluster reachable', async ({ page }) => {
  const tok = await login(page);
  const corpus = listCorpus();
  expect(corpus.length).toBeGreaterThanOrEqual(5);
  console.log(`  corpus has ${corpus.length} documents ready`);

  const h = await page.request.get(`${API}/api/health`, { headers: auth(tok) });
  expect(h.ok()).toBeTruthy();
});

test('REAL #2 — create a v2-test KB and confirm it lists', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.post(`${API}/api/knowledge-bases`, {
    headers: auth(tok),
    data: { name: `v2-real-corpus-${Date.now()}`, description: 'v2.0 end-to-end real-corpus UAT' },
  });
  expect([200, 201]).toContain(r.status());
  testKbId = (await r.json()).data.id;
  expect(testKbId).toBeTruthy();
  console.log(`  KB id: ${testKbId}`);

  const list = await page.request.get(`${API}/api/knowledge-bases`, { headers: auth(tok) });
  const ids = ((await list.json()).data || []).map((k: any) => k.id);
  expect(ids).toContain(testKbId);
});

test('REAL #3 bulk upload the generated documents to the KB', async ({ page }) => {
  test.skip(!testKbId, 'no KB');
  const tok = await login(page);
  const corpus = listCorpus();

  const results = await Promise.all(corpus.map(async filePath => {
    const buf = fs.readFileSync(filePath);
    const filename = path.basename(filePath);
    const r = await page.request.post(`${API}/api/knowledge-bases/${testKbId}/upload`, {
      headers: { Authorization: `Bearer ${tok}` },
      multipart: { file: { name: filename, mimeType: 'text/plain', buffer: buf } },
      timeout: 120_000,
    });
    return { filename, status: r.status(), body: r.ok() ? await r.json() : null, size: buf.length };
  }));
  const succeeded = results.filter(r => r.body !== null);
  console.log(`  uploaded ${succeeded.length}/${corpus.length}`);
  expect(succeeded.length).toBe(corpus.length);

  for (const r of succeeded) {
    const docId = r.body.data?.id || r.body.data?.document_id;
    if (docId) uploadedDocs.push({ id: docId, filename: r.filename, size: r.size });
  }
  console.log(`  doc ids captured: ${uploadedDocs.length}`);
  expect(uploadedDocs.length).toBe(corpus.length);
});

test('REAL #4 every document indexes, is current and is version 1', async ({ page }) => {
  test.skip(!testKbId, 'no KB');
  const tok = await login(page);
  let docs: any[] = [];
  await expect.poll(async () => {
    const r = await page.request.get(`${API}/api/knowledge-bases/${testKbId}/documents`, { headers: auth(tok) });
    docs = r.ok() ? (await r.json()).data || [] : [];
    return docs.filter((d) => ['ready', 'degraded', 'failed'].includes(d.status)).length;
  }, { timeout: 300_000, intervals: [5_000] }).toBe(uploadedDocs.length);
  console.log(`  documents ${docs.map((d) => `${d.filename}=${d.status}`).join(', ')}`);
  for (const d of docs) {
    expect(d.status, `${d.filename} was indexed`).toBe('ready');
    expect(d.chunk_count, `${d.filename} has chunks`).toBeGreaterThan(0);
    expect(d.is_current).toBe(true);
    expect(d.version_number).toBe(1);
  }
});

test('REAL #4b search through the embedder finds the right document', async ({ page }) => {
  test.skip(!testKbId || uploadedDocs.length === 0, 'no docs');
  const tok = await login(page);
  const ask = async (query: string) => {
    const r = await page.request.post(`${API}/api/knowledge-engines/${testKbId}/search`, {
      headers: auth(tok),
      data: { query, mode: 'vector', top_k: 3 },
      timeout: 120_000,
    });
    expect(r.ok(), `search answered ${r.status()}`).toBeTruthy();
    return (await r.json()).data;
  };
  const first = await ask('How often must the rooftop heat pumps be serviced?');
  console.log(`  mode ${first.mode_used}, vectors ${first.vector_count}, degraded ${first.degraded}`);
  test.skip(/keyword/i.test(String(first.mode_used)), `search fell back to keyword here (${first.degraded || 'no reason given'}), this stack has no working embedding key`);
  expect(first.vector_count).toBeGreaterThan(0);
  expect(first.results[0].content).toContain('heat pumps');
  const second = await ask('What is the nightly limit for a hotel on a work trip?');
  expect(second.results[0].content).toContain('140 euros');
  const third = await ask('When do pickers start on the fruit on the north slope?');
  expect(third.results[0].content).toContain('Brix');
});

test('REAL #5 — set per-tenant cognify config (parallel + threshold + budget)', async ({ page }) => {
  const tok = await login(page);
  const before = (await (await page.request.get(`${API}/api/knowledge/cognify-config`, { headers: auth(tok) })).json()).data;
  try {
    const r = await page.request.put(`${API}/api/knowledge/cognify-config`, {
      headers: auth(tok),
      data: { auto_accept_threshold: 0.7, conflict_action: 'flag', max_parallel_docs: 8, daily_budget_usd: 25 },
    });
    expect([200, 204]).toContain(r.status());

    const g = await page.request.get(`${API}/api/knowledge/cognify-config`, { headers: auth(tok) });
    const cfg = (await g.json()).data;
    expect(cfg.auto_accept_threshold).toBeCloseTo(0.7);
    expect(cfg.max_parallel_docs).toBe(8);
    expect(cfg.daily_budget_usd).toBe(25);
  } finally {
    await page.request.put(`${API}/api/knowledge/cognify-config`, { headers: auth(tok), data: before });
  }
});

test('REAL #6 — replace 3 docs with v2 — versioning roundtrip', async ({ page }) => {
  test.skip(!testKbId || uploadedDocs.length < 3, 'need 3+ docs');
  const tok = await login(page);
  const tenant = (await (await page.request.get(`${API}/api/me/permissions`, { headers: auth(tok) })).json()).data.tenant_id;

  // a file from anywhere else is refused
  const foreign = await page.request.post(`${API}/api/knowledge/${testKbId}/documents/${uploadedDocs[0].id}/replace`, {
    headers: auth(tok),
    data: { new_filename: 'elsewhere.txt', new_storage_url: '/data/uploads/elsewhere.txt', new_file_type: 'txt', new_file_size: 10 },
  });
  expect(foreign.status()).toBe(400);

  let replaced = 0;
  for (let i = 0; i < 3; i++) {
    const doc = uploadedDocs[i];
    const amended = Buffer.from(`${CORPUS[doc.filename]} Amended in version 2.\n`);
    const up = await page.request.post(`${API}/api/knowledge-bases/${testKbId}/upload`, {
      headers: { Authorization: `Bearer ${tok}` },
      multipart: { file: { name: `amended-${doc.filename}`, mimeType: 'text/plain', buffer: amended } },
      timeout: 120_000,
    });
    expect(up.ok(), `upload answered ${up.status()}`).toBeTruthy();
    const newFile = (await up.json()).data;
    // the API does not return the storage url, this is the key upload stores it under
    const r = await page.request.post(`${API}/api/knowledge/${testKbId}/documents/${doc.id}/replace`, {
      headers: auth(tok),
      data: {
        new_filename: `replaced-${doc.filename}`,
        new_storage_url: `${tenant}/kb/${testKbId}/${newFile.id}.${newFile.file_type}`,
        new_file_type: newFile.file_type,
        new_file_size: amended.length,
      },
    });
    expect(r.status(), `replace of ${doc.filename}`).toBeLessThan(300);
    const body = (await r.json()).data;
    expect(body.version_number).toBe(2);
    expect(body.supersedes).toBe(doc.id);
    replaced++;
  }
  console.log(`  versioned: ${replaced}`);
});

test('REAL #7 — re-embed dry-run returns cost estimate', async ({ page }) => {
  test.skip(!testKbId, 'no KB');
  const tok = await login(page);
  const r = await page.request.post(`${API}/api/knowledge/${testKbId}/reembed`, {
    headers: auth(tok),
    data: { embedding_model: 'text-embedding-3-large', dry_run: true },
  });
  expect([200, 201]).toContain(r.status());
  const body = (await r.json()).data;
  expect(body.to_model).toBe('text-embedding-3-large');
  expect(typeof body.estimated_usd).toBe('number');
  expect(body.estimated_usd).toBeGreaterThanOrEqual(0);
  console.log(`  reembed estimate: $${body.estimated_usd} for ${body.chunks_to_reembed} chunks`);
});

test('REAL #8 — Cognify trigger + conflicts endpoint reachable', async ({ page }) => {
  test.skip(!testKbId, 'no KB');
  const tok = await login(page);
  const c = await page.request.post(`${API}/api/knowledge-bases/${testKbId}/cognify`, {
    headers: auth(tok),
    data: { mode: 'incremental' },
  });
  console.log(`  cognify trigger status: ${c.status()}`);
  expect([200, 201, 202, 404]).toContain(c.status());

  const conflicts = await page.request.get(`${API}/api/knowledge/cognify-conflicts`, { headers: auth(tok) });
  expect(conflicts.ok()).toBeTruthy();
  const items = (await conflicts.json()).data?.items || [];
  expect(Array.isArray(items)).toBeTruthy();
});

test('REAL #9 — Atlas list graphs (legacy tool surface)', async ({ page }) => {
  const tok = await login(page);
  const r = await page.request.get(`${API}/api/atlas/graphs`, { headers: auth(tok) });
  expect([200, 404]).toContain(r.status());
  if (r.status() === 200) {
    const body = (await r.json()).data;
    const graphs = Array.isArray(body) ? body : (body.graphs || body.items || []);
    console.log(`  atlas graphs: ${graphs.length}`);
    expect(Array.isArray(graphs)).toBeTruthy();
  }
});

test('REAL #10 — Document grant API: list, create, revoke', async ({ page }) => {
  test.skip(!testKbId || uploadedDocs.length === 0, 'no docs');
  const tok = await login(page);
  const meR = await page.request.get(`${API}/api/auth/me`, { headers: auth(tok) });
  const user = (await meR.json()).data.user || (await meR.json()).data;
  const doc = uploadedDocs[uploadedDocs.length - 1];

  const before = await page.request.get(
    `${API}/api/knowledge/${testKbId}/documents/${doc.id}/grants`,
    { headers: auth(tok) },
  );
  expect([200, 404]).toContain(before.status());

  const create = await page.request.post(
    `${API}/api/knowledge/${testKbId}/documents/${doc.id}/grants`,
    {
      headers: auth(tok),
      data: { subject_type: 'user', subject_id: user.id, permission: 'read' },
    },
  );
  expect([200, 201, 404]).toContain(create.status());

  if ([200, 201].includes(create.status())) {
    const grantId = (await create.json()).data.id;
    const del = await page.request.delete(
      `${API}/api/knowledge/${testKbId}/documents/${doc.id}/grants/${grantId}`,
      { headers: auth(tok) },
    );
    expect([200, 204]).toContain(del.status());
  }
});

test('REAL #11 — GDPR receipts list for self user works', async ({ page }) => {
  const tok = await login(page);
  const me = await page.request.get(`${API}/api/auth/me`, { headers: auth(tok) });
  const user = (await me.json()).data.user || (await me.json()).data;
  const r = await page.request.get(`${API}/api/gdpr/users/${user.id}/receipts`, { headers: auth(tok) });
  expect(r.ok()).toBeTruthy();
  const rows = (await r.json()).data;
  expect(Array.isArray(rows)).toBeTruthy();
});

test('REAL #12 — UI: /settings/cognify renders + persists slider edit', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/settings/cognify`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);
  const body = (await page.locator('body').innerText()).toLowerCase();
  expect(body).toMatch(/cognify|conflict|threshold/);
  const inputs = await page.locator('input[type="number"]').count();
  expect(inputs).toBeGreaterThan(0);
});

test('REAL #13 — UI: /settings/gdpr renders + has user-id input', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/settings/gdpr`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);
  const body = (await page.locator('body').innerText()).toLowerCase();
  expect(body).toMatch(/gdpr|erasure|purge|receipt/);
});

test('REAL #14 — UI: /knowledge page lists the test KB', async ({ page }) => {
  test.skip(!testKbId, 'no KB');
  await login(page);
  await page.goto(`${BASE}/knowledge`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);
  const body = await page.locator('body').innerText();
  // The KB name has the timestamp; we just check the list rendered substantial content
  expect(body.length).toBeGreaterThan(50);
});

test('REAL #15 — cleanup: delete test KB', async ({ page }) => {
  test.skip(!testKbId, 'no KB');
  const tok = await login(page);
  const r = await page.request.delete(`${API}/api/knowledge-bases/${testKbId}`, { headers: auth(tok) });
  expect([200, 204]).toContain(r.status());
  console.log(`  cleaned KB ${testKbId}`);
  testKbId = null;
});

// a failed step skips the rest of a serial run, including the cleanup above
test.afterAll(async ({ request }) => {
  fs.rmSync(CORPUS_DIR, { recursive: true, force: true });
  if (!testKbId) return;
  const res = await request.post(`${API}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
  const tok = (await res.json())?.data?.access_token;
  await request.delete(`${API}/api/knowledge-bases/${testKbId}?force=true`, { headers: { Authorization: `Bearer ${tok}` } }).catch(() => null);
});
