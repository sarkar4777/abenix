// JS SDK against the live API. Runs the packed @abenix/sdk the way an app
// installs it. scripts/sdk-e2e.sh packs, installs and runs this file.
import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { Abenix, AbenixError } from '@abenix/sdk';

const BASE = process.env.ABENIX_URL || 'http://localhost:8000';
const KEY_FILE = process.env.SDK_KEY_FILE || '../.sdk-key';
const AGENT_SLUG = process.env.SDK_E2E_AGENT || 'sdk-e2e-assistant';
const ACTION_KEY = 'sample_plant.set_setpoint';
const RUN = randomUUID().slice(0, 8);

let forge;
let agent;

const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));

before(async () => {
  const key = (process.env.ABENIX_API_KEY || (existsSync(KEY_FILE) ? readFileSync(KEY_FILE, 'utf8') : '')).trim();
  assert.ok(key.startsWith('af_'), 'no API key, run e2e/sdk/mint_key.spec.ts first');
  forge = new Abenix({ apiKey: key, baseUrl: BASE, timeout: 240_000 });
  agent = await forge.agents.bySlug(AGENT_SLUG);
  if (!agent) {
    agent = await forge.agents.create({
      name: 'SDK e2e assistant',
      slug: AGENT_SLUG,
      description: 'Answers short questions. Used by the SDK end to end suites.',
      system_prompt: 'You answer in one short sentence. No preamble.',
      model_config: { model: 'claude-haiku-4-5-20251001', temperature: 0, max_tokens: 200, tools: [] },
    });
  }
  assert.equal(agent.slug, AGENT_SLUG);
});

test('identity', async () => {
  const me = await forge.me();
  assert.ok(me.user.email);
  const perms = await forge.permissions();
  assert.ok(perms.role);
  assert.ok(perms.capabilities.length > 0);
  assert.equal(await forge.agents.bySlug(`no-such-agent-${RUN}`), null);
});

test('run, stream and read a run back', async () => {
  const result = await forge.execute(AGENT_SLUG, 'What is the capital of Italy? One word.');
  assert.equal(result.status, 'completed', JSON.stringify(result));
  assert.ok(result.executionId);
  assert.match(result.output.toLowerCase(), /rome/);

  const row = await forge.executions.get(result.executionId);
  assert.equal(row.status, 'completed');
  assert.equal(row.agent_id, agent.id);

  const events = [];
  for await (const ev of forge.stream(agent.id, 'Name the closest star to Earth after the Sun. Short.')) events.push(ev);
  const kinds = events.map((e) => e.type);
  assert.ok(kinds.includes('token'), kinds.join(','));
  assert.equal(kinds.at(-1), 'done');
  assert.deepEqual(events.filter((e) => e.type === 'error'), []);
  const text = events.filter((e) => e.type === 'token').map((e) => e.text).join('');
  assert.match(text.toLowerCase(), /centauri/);
  const streamedId = events.at(-1).executionId;
  assert.ok(streamedId, 'done carries the execution id');

  let streamed = {};
  for (let i = 0; i < 20; i++) {
    streamed = await forge.executions.get(streamedId);
    if (['completed', 'failed'].includes(streamed.status)) break;
    await sleep(1000);
  }
  assert.equal(streamed.status, 'completed');

  const listed = await forge.executions.list({ agentId: agent.id, limit: 20 });
  const ids = new Set(listed.map((r) => r.id));
  assert.ok(ids.has(result.executionId) && ids.has(streamedId));
});

test('approvals: create, wait and decide', async () => {
  const token = `sdk-js-e2e-${RUN}`;
  const created = await forge.approvals.create('SDK JS e2e: pay the supplier', { amount: 900 }, { clientToken: token, expiresSeconds: 600 });
  assert.equal(created.status, 'pending');
  const again = await forge.approvals.create('dup', {}, { clientToken: token });
  assert.equal(again.id, created.id);

  const pending = await forge.approvals.list({ status: 'pending' });
  assert.ok(pending.some((a) => a.id === created.id));
  assert.equal((await forge.approvals.get(created.id)).payload.amount, 900);

  const [waited, approved] = await Promise.all([
    forge.approvals.waitFor(created.id, { timeoutSeconds: 30 }),
    sleep(2000).then(() => forge.approvals.approve(created.id, { reason: 'invoice matches' })),
  ]);
  assert.equal(approved.status, 'approved');
  assert.equal(waited.status, 'approved');

  const second = await forge.approvals.create('SDK JS e2e: wipe the cache', { keys: 4 }, { expiresSeconds: 600 });
  assert.equal((await forge.approvals.deny(second.id, { reason: 'not now' })).status, 'denied');
  await assert.rejects(forge.approvals.returnForChanges(second.id, ' '));
});

test('autonomy: propose, wait and report the outcome', async (t) => {
  const overview = await forge.autonomy.overview();
  if (!overview.grants.some((g) => g.action_type?.key === ACTION_KEY)) {
    t.skip('the sample plant is not installed, use Install sample on /autonomy');
    return;
  }
  const proposed = await forge.actions.propose(
    ACTION_KEY,
    { operation: 'set_setpoint', setpoint_bar: 4.6 },
    { intent: 'nudge pressure up', prediction: { metric: 'pressure_bar', value: 4.6, low: 4.55, high: 4.65 } },
  );
  assert.ok(['run', 'wait'].includes(proposed.decision), JSON.stringify(proposed));
  if (proposed.decision === 'wait') {
    const [cleared] = await Promise.all([
      forge.actions.wait(proposed.action_id, { timeoutSeconds: 30 }),
      sleep(2000).then(() => forge.approvals.approve(proposed.approval_id, { reason: 'fine' })),
    ]);
    assert.equal(cleared.decision, 'run', JSON.stringify(cleared));
    assert.equal(cleared.arguments.setpoint_bar, 4.6);
  }
  await forge.actions.executed(proposed.action_id, true, { resultPreview: 'applied' });
  await forge.actions.reportOutcome(proposed.action_id, 4.62, { note: 'gauge reading' });
  const detail = await forge.actions.get(proposed.action_id);
  const action = detail.action ?? detail;
  assert.equal(action.status, 'executed');
  assert.ok(!['none', 'pending'].includes(action.outcome_status), JSON.stringify(action));

  await assert.rejects(forge.actions.propose('no.such.action', {}), (e) => e instanceof AbenixError && e.status === 404 && e.code === 'UNKNOWN_ACTION');
});

test('lessons and feedback', async () => {
  const result = await forge.execute(agent.id, 'How many sides does a hexagon have? Digits only.');
  assert.ok(result.executionId);
  const lesson = await forge.lessons.report(agent.id, 'Spelled the number out', { expected: '6', executionId: result.executionId });
  assert.ok(lesson.lesson_id);
  const up = await forge.feedback.give(1, { executionId: result.executionId });
  assert.ok(up.id);
  const down = await forge.feedback.give(-1, { executionId: result.executionId, correction: '6' });
  assert.ok(down.id && down.lesson_id, JSON.stringify(down));
  await assert.rejects(forge.feedback.give(0, { executionId: result.executionId }));
  await assert.rejects(forge.lessons.report(agent.id, '  '));
  assert.ok(Array.isArray(await forge.improvements.list({ agentId: agent.id })));
});

test('knowledge: upload and search', async () => {
  const boot = await forge.knowledge.bootstrapProject('sdk-e2e', 'SDK e2e', {
    collections: [{ name: 'SDK e2e notes', slug: 'sdk-e2e-notes' }],
  });
  const kbId = boot.collections[0].id;
  const doc = await forge.knowledge.upload(kbId, `Dock ${RUN} takes deliveries only on Tuesdays and Fridays.`, `dock-${RUN}.txt`, 'text/plain');
  assert.ok(doc.id);
  let status = doc.status;
  for (let i = 0; i < 60 && !['ready', 'failed', 'degraded'].includes(status); i++) {
    await sleep(3000);
    status = (await forge.knowledge.documents(kbId)).find((d) => d.id === doc.id)?.status;
  }
  assert.equal(status, 'ready');
  const found = await forge.knowledge.search(kbId, `Which days does dock ${RUN} take deliveries?`, { mode: 'vector', topK: 5 });
  assert.ok(found.results.some((r) => r.content.includes(RUN)), JSON.stringify(found));
  await assert.rejects(forge.knowledge.upload(kbId, '', 'empty.txt'), (e) => e instanceof AbenixError && e.status === 400);
});
