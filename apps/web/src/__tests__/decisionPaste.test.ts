import { describe, expect, it } from 'vitest';
import type { RuleDoc } from '@/lib/decisions';
import { applyPaste, newColumns, planPaste, splitPasted, type PasteColumn } from '@/lib/decisionPaste';

const empty = (): RuleDoc => ({ kind: 'rules', hit_policy: 'first', facts: [], outputs: [], rules: [] });

const GW = [
  'rule\tmachine.tip_speed_ms\tworker.clearance_m\taction\tmargin_m\treason\tsources',
  'stop.fast_swing\t>= 2\t< 4\tstop\t4\tWorker inside the swing radius plus 4 m while the tip moves over 2 m/s\tSite safety plan, section 3.2',
  'stop.medium_swing\t>= 0.5\t< 3\tstop\t3\tWorker inside the swing radius plus 3 m while the tip moves\tSite safety plan, section 3.2',
  'stop.any\t\t< 2\tstop\t2\tWorker inside the swing radius plus 2 m\tSite safety plan, section 3.2',
  'warn.approach\t\t< 7\twarn\t7\tWorker approaching the exclusion zone\tSite safety plan, section 3.3; Toolbox talk 12',
  'ok.clear\t\t>= 7\tok\t7\t""\t',
].join('\n');

describe('splitting pasted cells', () => {
  it('keeps quoted cells with tabs and line breaks together', () => {
    expect(splitPasted('a\t"b\tc"\n"multi\nline"\td\n\n')).toEqual([['a', 'b\tc'], ['multi\nline', 'd']]);
  });
});

describe('pasting into an empty decision', () => {
  it('reads the header row and works out each column', () => {
    const plan = planPaste(GW, empty(), []);
    expect(plan.hasHeader).toBe(true);
    expect(plan.rows).toHaveLength(5);
    const by = Object.fromEntries(plan.columns.map((c) => [c.header, c]));
    expect(by.rule.role).toBe('rule');
    expect(by['machine.tip_speed_ms']).toMatchObject({ role: 'fact', type: 'number', exists: false });
    expect(by['worker.clearance_m']).toMatchObject({ role: 'fact', type: 'number' });
    expect(by.action).toMatchObject({ role: 'outcome', type: 'string' });
    expect(by.margin_m).toMatchObject({ role: 'outcome', type: 'number' });
    expect(by.reason).toMatchObject({ role: 'outcome', type: 'string' });
    expect(by.sources.role).toBe('sources');
    expect(newColumns(plan)).toHaveLength(5);
  });

  it('creates the facts, outcomes and rules', () => {
    const { doc, added } = applyPaste(empty(), planPaste(GW, empty(), []));
    expect(added).toBe(5);
    expect(doc.facts.map((f) => [f.path, f.type, f.required])).toEqual([['machine.tip_speed_ms', 'number', true], ['worker.clearance_m', 'number', true]]);
    expect(doc.rules[0].requires).toEqual(['machine.tip_speed_ms', 'worker.clearance_m']);
    expect(doc.rules[2].requires).toEqual(['worker.clearance_m']);
    expect(doc.outputs.map((o) => [o.field, o.type])).toEqual([['action', 'string'], ['margin_m', 'number'], ['reason', 'string']]);
    const [fast, medium, , warn, ok] = doc.rules;
    expect(fast.key).toBe('stop.fast_swing');
    expect(fast.when.all).toEqual([
      { fact: 'machine.tip_speed_ms', op: 'gte', value: 2 },
      { fact: 'worker.clearance_m', op: 'lt', value: 4 },
    ]);
    expect(medium.when.all![0]).toEqual({ fact: 'machine.tip_speed_ms', op: 'gte', value: 0.5 });
    expect(fast.then).toEqual({ action: { value: 'stop' }, margin_m: { value: 4 }, reason: { value: 'Worker inside the swing radius plus 4 m while the tip moves over 2 m/s' } });
    expect(warn.provenance?.citations).toEqual(['Site safety plan, section 3.3', 'Toolbox talk 12']);
    expect(ok.then.reason).toEqual({ value: '' });
    expect(ok.when.all).toEqual([{ fact: 'worker.clearance_m', op: 'gte', value: 7 }]);
  });

  it('asks for a header row when there is nothing to go on', () => {
    const plan = planPaste('4\tstop\n3\twarn', empty(), []);
    expect(plan.hasHeader).toBe(false);
    expect(plan.columns).toHaveLength(0);
  });
});

describe('pasting into a decision that has columns', () => {
  const base = (): RuleDoc => applyPaste(empty(), planPaste(GW, empty(), [])).doc;

  it('updates rules by key and offers to create unknown columns', () => {
    const d = base();
    const plan = planPaste('rule\tworker.clearance_m\tsite.zone\taction\nstop.any\t< 2.5\tA, B\tstop', d, []);
    const zone = plan.columns.find((c) => c.header === 'site.zone')!;
    expect(zone).toMatchObject({ role: 'fact', exists: false });
    const r = applyPaste(d, plan);
    expect(r.updated).toBe(1);
    expect(r.doc.rules.find((x) => x.key === 'stop.any')!.when.all).toEqual([
      { fact: 'worker.clearance_m', op: 'lt', value: 2.5 },
      { fact: 'site.zone', op: 'in', values: ['A', 'B'] },
    ]);
  });

  it('follows the table columns when there is no header', () => {
    const d = base();
    const defaults: PasteColumn[] = [
      { header: 'rule', role: 'rule', target: '', type: 'string', exists: true },
      { header: 'worker.clearance_m', role: 'fact', target: 'worker.clearance_m', type: 'number', exists: true },
      { header: 'margin_m', role: 'outcome', target: 'margin_m', type: 'number', exists: true },
    ];
    const plan = planPaste('new.rule\t< 9\t9.5', d, defaults);
    expect(plan.hasHeader).toBe(false);
    const r = applyPaste(d, plan);
    const added = r.doc.rules[r.doc.rules.length - 1];
    expect(added.key).toBe('new.rule');
    expect(added.then.margin_m).toEqual({ value: 9.5 });
  });
});

describe('fact names typed with spaces', () => {
  it('become a name a rule can use', async () => {
    const { toPath } = await import('@/lib/decisionPaste');
    expect(toPath('tip speed')).toBe('tip_speed');
    expect(toPath('Worker clearance (m)')).toBe('worker_clearance_m');
    expect(toPath('machine.tip_speed_ms')).toBe('machine.tip_speed_ms');
    expect(toPath('!!!')).toBe('');
    expect(toPath('Clearance')).toBe('clearance');
    expect(toPath('Action')).toBe('action');
    expect(toPath('shipment.weightKg')).toBe('shipment.weightKg');
    expect(toPath('Machine.TipSpeed')).toBe('machine.tip_speed');
  });
});

describe('pasted headers with capitals', () => {
  it('get lowercase keys and keep the header as the label', async () => {
    const { planPaste, applyPaste } = await import('@/lib/decisionPaste');
    const empty: any = { facts: [], outputs: [], rules: [], hit_policy: 'first' };
    const text = [['Rule', 'Tip speed', 'Clearance', 'Action', 'Margin'], ['stop.close', '>= 2', '< 4', 'stop', '4'], ['clear', '', '', 'go', '0.5']].map((r) => r.join(String.fromCharCode(9))).join(String.fromCharCode(10));
    const plan = planPaste(text, empty, []);
    expect(plan.columns.map((c) => c.target)).toEqual(['', 'tip_speed', 'clearance', 'action', 'margin']);
    const r = applyPaste(empty, plan);
    expect(r.doc.outputs.map((o: any) => [o.field, o.label])).toEqual([['action', 'Action'], ['margin', 'Margin']]);
    expect(r.doc.facts.map((f: any) => [f.path, f.label])).toEqual([['tip_speed', 'Tip speed'], ['clearance', 'Clearance']]);
  });
});
