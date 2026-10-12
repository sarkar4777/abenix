import { describe, expect, it } from 'vitest';
import {
  blankCondition, blankDraft, conditionPayload, draftPayload, draftProblems, pointInPolygon, previewReady, ruleSentence, typedValue, type RuleDraft,
} from '@/components/telemetry-rules/lib';

function ex1(): RuleDraft {
  return {
    ...blankDraft(),
    name: 'EX1 pump',
    scope: { kind: 'asset', group: 'groundwork', node: 'ipc-ex1', device: 'hydraulics' },
    condition: { kind: 'threshold', signal: 'Hydraulics/Pump1Pressure_bar', op: '>', value: '300', hysteresis: '10' },
    actions: [{ kind: 'alert', severity: null }, { kind: 'command', signal: 'Safety/Hold', value: 'true' }],
  };
}

describe('signal rule drafts', () => {
  it('reads like the server sentence', () => {
    expect(ruleSentence(ex1(), { 'groundwork/ipc-ex1/': 'Excavator EX1' })).toBe(
      'When Hydraulics/Pump1Pressure_bar goes above 300 (clears at or below 290) on Excavator EX1 part hydraulics, raise an alert and set Safety/Hold to true.',
    );
  });

  it('sends numbers as numbers and typed values as their type', () => {
    const p = draftPayload(ex1());
    expect(p.condition).toEqual({ kind: 'threshold', signal: 'Hydraulics/Pump1Pressure_bar', op: '>', value: 300, hysteresis: 10 });
    expect((p.actions as Array<{ value?: unknown }>)[1].value).toBe(true);
    expect(typedValue('12.5')).toBe(12.5);
    expect(typedValue('safe')).toBe('safe');
  });

  it('explains each missing field', () => {
    const d = { ...blankDraft(), condition: blankCondition('range') };
    const p = draftProblems(d, true);
    expect(p.name).toMatch(/Give the rule a name/);
    expect(p['scope.node']).toMatch(/Pick the asset/);
    expect(p['condition.signal']).toMatch(/Pick the signal/);
    expect(p['condition.min']).toBeTruthy();
  });

  it('blocks a command step without the capability and duplicate names', () => {
    const p = draftProblems(ex1(), false, ['ex1 PUMP']);
    expect(p['actions.1.kind']).toMatch(/Send machine commands/);
    expect(p.name).toMatch(/already has this name/);
  });

  it('previews once scope and condition are complete', () => {
    const d = ex1();
    expect(previewReady(d)).toBe(true);
    expect(previewReady({ ...d, condition: { ...d.condition, value: '' } })).toBe(false);
  });

  it('builds count and geofence payloads', () => {
    expect(conditionPayload({ ...blankCondition('count', 'p'), count: '3', window_s: '60', when: { op: '>', value: '5' } })).toEqual({
      kind: 'count', signal: 'p', count: 3, window_s: 60, when: { op: '>', value: 5 },
    });
    expect(conditionPayload({ ...blankCondition('count', 'p'), count: 3, window_s: 60, when: { op: '>', value: '' } }).when).toBeNull();
    const g = conditionPayload({ ...blankCondition('geofence'), x_signal: 'GNSS/X_m', y_signal: 'GNSS/Y_m', polygon: [[0, 0], [1, 0], [1, 1]] });
    expect(g).toMatchObject({ frame: 'site', on: 'exit', polygon: [[0, 0], [1, 0], [1, 1]] });
  });

  it('says a drift from normal like the server and checks its factor', () => {
    const c = blankCondition('deviation', 'Hydraulics/Pump1Pressure_bar');
    expect(ruleSentence({ ...ex1(), condition: c, actions: [{ kind: 'alert', severity: null }] })).toBe(
      'When the last 5 min of Hydraulics/Pump1Pressure_bar run 15% above the last 30 min on ipc-ex1 part hydraulics, raise an alert.',
    );
    expect(conditionPayload(c)).toEqual({
      kind: 'deviation', signal: 'Hydraulics/Pump1Pressure_bar', window_s: 300, baseline_s: 1800, mode: 'ratio', direction: 'up', threshold: 1.15, hysteresis: 0.05,
    });
    expect(draftProblems({ ...ex1(), condition: { ...c, threshold: 0.9 } }, true)['condition.threshold']).toMatch(/more than 1/);
    expect(draftProblems({ ...ex1(), condition: { ...c, baseline_s: 120 } }, true)['condition.baseline_s']).toBeTruthy();
  });

  it('knows inside from outside', () => {
    const sq = [[0, 0], [4, 0], [4, 4], [0, 4]];
    expect(pointInPolygon(2, 2, sq)).toBe(true);
    expect(pointInPolygon(5, 2, sq)).toBe(false);
  });
});
