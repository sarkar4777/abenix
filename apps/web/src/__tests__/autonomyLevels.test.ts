import {
  LEVELS, levelMeta, levelLabel, requirementProgress, predictionText, probeText, worldModelText,
  scopeText, autonomyMetaOf, autonomyBadgeText, autonomyBadgeHref, isActionGate, executionIdsOf,
  reviewItemsOf, missingRequirements,
} from '@/lib/autonomy';

describe('level metadata', () => {
  it('has five levels with the contract labels in order', () => {
    expect(LEVELS.map((l) => l.label)).toEqual(['Off', 'Watching', 'Asks first', 'Acts within limits', 'Acts and reports']);
    expect(LEVELS.map((l) => l.key)).toEqual(['off', 'watching', 'asks_first', 'within_limits', 'acts_reports']);
    LEVELS.forEach((l, i) => {
      expect(l.level).toBe(i);
      expect(l.help.length).toBeGreaterThan(10);
      expect(l.fill).toMatch(/^bg-/);
    });
  });

  it('clamps out of range levels and never shows a bare number', () => {
    expect(levelMeta(-3).label).toBe('Off');
    expect(levelMeta(9).label).toBe('Acts and reports');
    expect(levelMeta(undefined).label).toBe('Off');
    expect(levelLabel(null)).toBe('Not enrolled');
    expect(levelLabel(2)).toBe('Asks first');
  });
});

describe('requirement progress', () => {
  it('scales count requirements and caps unmet ones below 100', () => {
    expect(requirementProgress({ key: 'min_executed', label: '34 of 50', current: 34, needed: 50, met: false })).toBe(68);
    expect(requirementProgress({ key: 'min_executed', label: '50 of 50', current: 50, needed: 50, met: true })).toBe(100);
    expect(requirementProgress({ key: 'min_executed', label: 'x', current: 60, needed: 50, met: false })).toBe(99);
  });

  it('inverts rates where lower is better', () => {
    expect(requirementProgress({ key: 'max_unknown_rate', label: 'u', current: 0.4, needed: 0.2, met: false })).toBe(50);
  });

  it('treats non numbers as no progress', () => {
    expect(requirementProgress({ key: 'eval', label: 'Eval suite passing', current: 'failing', needed: 'passing', met: false })).toBe(0);
  });

  it('lists only the missing ones', () => {
    const m = missingRequirements({
      requirements: [
        { key: 'a', label: 'A', met: true },
        { key: 'b', label: 'B', met: false },
      ],
    });
    expect(m.map((r) => r.key)).toEqual(['b']);
    expect(missingRequirements(null)).toEqual([]);
  });
});

describe('plain words', () => {
  it('describes a prediction with its band', () => {
    expect(predictionText({ metric: 'pressure_bar', value: 4.4, low: 4.1, high: 4.6, horizon_s: 60 }))
      .toBe('pressure bar 4.4 (between 4.1 and 4.6) in 1 minute');
    expect(predictionText(null)).toBe('No prediction');
    expect(predictionText({ source: 'none', value: 3 })).toBe('No prediction');
  });

  it('describes probes, world models and scopes', () => {
    expect(probeText({ kind: 'tool', tool: 'sample_plant', after_s: 30, metric: 'pressure_bar' }))
      .toBe('We read pressure bar with the sample_plant tool 30 seconds after the action.');
    expect(worldModelText({ kind: 'decision', ref: 'plant_model', metric: 'pressure_bar' })).toContain('plant_model');
    expect(scopeText(null)).toBe('Everywhere');
    expect(scopeText({ param: 'site', equals: 'A' })).toBe('Only when site is A');
  });
});

describe('autonomy metadata on tool steps', () => {
  it('reads it at the top or under metadata', () => {
    expect(autonomyMetaOf({ autonomy: { level: 2 } })).toEqual({ level: 2 });
    expect(autonomyMetaOf({ metadata: { autonomy: { level: 1 } } })).toEqual({ level: 1 });
    expect(autonomyMetaOf({ metadata: {} })).toBeNull();
    expect(autonomyMetaOf(null)).toBeNull();
  });

  it('points a pending action at Approvals', () => {
    const m = { level: 2, status: 'pending', grant_id: 'g1' };
    expect(autonomyBadgeText(m)).toBe('Asks first, waiting in Approvals');
    expect(autonomyBadgeHref(m)).toBe('/approvals');
    expect(autonomyBadgeHref({ level: 1, status: 'watching', grant_id: 'g1' })).toBe('/autonomy/g1');
  });

  it('spots action gates', () => {
    expect(isActionGate('action:sample_plant.set_setpoint')).toBe(true);
    expect(isActionGate('autonomy.promote')).toBe(false);
    expect(isActionGate(null)).toBe(false);
  });
});

describe('loose response shapes', () => {
  it('accepts either a list or an object for run ids and reviews', () => {
    expect(executionIdsOf(['a', 'b'])).toEqual(['a', 'b']);
    expect(executionIdsOf({ execution_ids: ['x'] })).toEqual(['x']);
    expect(executionIdsOf([{ id: 'y' }])).toEqual(['y']);
    expect(executionIdsOf(null)).toEqual([]);
    expect(reviewItemsOf([{ id: '1' }]).total).toBe(1);
    expect(reviewItemsOf({ items: [{ id: '1' }], total: 12 })).toEqual({ items: [{ id: '1' }], total: 12 });
  });
});
