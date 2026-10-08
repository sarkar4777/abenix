import { policyForm, policyFromForm, type ActionType } from '@/lib/autonomy';
import { formFromTool, formFromType, matchText, validateStep } from '@/components/autonomy/EnrolWizard';
import { parseAnyValue } from '@/components/builder/pipeline/StepConfigPanel';

describe('thresholds form', () => {
  const effective = {
    to_asks_first: { min_reviews: 20, min_agreement_lb: 0.7 },
    to_within_limits: { min_executed: 50, min_accuracy_lb: 0.85, harm_free_days: 30 },
  };

  it('shows shares as percents', () => {
    const f = policyForm(effective);
    expect(f['to_asks_first.min_reviews']).toBe('20');
    expect(f['to_asks_first.min_agreement_lb']).toBe('70');
    expect(f['to_within_limits.min_no_edit_rate']).toBe('');
  });

  it('turns the form back into overrides and keeps keys it does not show', () => {
    const form = { ...policyForm(effective), 'to_asks_first.min_reviews': '5', 'to_asks_first.min_agreement_lb': '50' };
    const { policy, errors } = policyFromForm(form, { window: 30, to_asks_first: { min_reviews: 9 } });
    expect(errors).toEqual({});
    expect(policy.window).toBe(30);
    expect(policy.to_asks_first).toEqual({ min_reviews: 5, min_agreement_lb: 0.5 });
    expect((policy.to_within_limits as Record<string, number>).harm_free_days).toBe(30);
  });

  it('refuses numbers out of range', () => {
    const { errors } = policyFromForm({ 'to_asks_first.min_reviews': '0', 'to_within_limits.min_accuracy_lb': '120', 'to_within_limits.harm_free_days': '1.5' }, null);
    expect(Object.keys(errors).sort()).toEqual(['to_asks_first.min_reviews', 'to_within_limits.harm_free_days', 'to_within_limits.min_accuracy_lb']);
  });
});

describe('enrol wizard', () => {
  it('prefills which calls from the tool target', () => {
    const f = formFromTool({ tool_name: 'mqtt_publish', effect: { kind: 'publish', label: 'Publish', target_param: 'topic' }, prefill: { label: 'Publish' } });
    expect(f.matchParam).toBe('topic');
    expect(f.matchGlob).toBe('');
    expect(f.reuseKey).toBe('');
  });

  it('reusing an action keeps its key, match and settings', () => {
    const at = {
      id: 't1', key: 'mqtt_publish:controls.b', label: 'Battery command',
      match: { param: 'topic', glob: 'controls.b' },
      world_model: { kind: 'agent_stated', metric: 'eur' },
      outcome_probe: { kind: 'manual', after_s: 60 },
      limits_decision_key: 'battery.limits', max_band_width: 0.5,
    } as ActionType;
    const f = formFromType(at);
    expect(f.reuseKey).toBe('mqtt_publish:controls.b');
    expect(f.matchGlob).toBe('controls.b');
    expect(f.limitsKey).toBe('battery.limits');
    expect(f.bandPct).toBe('50');
  });

  it('says which calls in words and needs an argument for a pattern', () => {
    expect(matchText('topic', '')).toBe('Every call of this tool');
    expect(matchText('topic', 'controls.b')).toBe('Calls where topic is controls.b');
    expect(matchText('topic', 'controls.*')).toBe('Calls where topic matches controls.*');
    const f = { ...formFromTool({ tool_name: 'x', prefill: { label: 'X' } }), matchGlob: 'a.*', matchParam: '' };
    expect(validateStep('judge', f).matchParam).toBeTruthy();
  });
});

describe('pipeline any field', () => {
  it('keeps JSON as an object and other text as text', () => {
    expect(parseAnyValue('{"mw": "{{d.result.mw}}"}')).toEqual({ value: { mw: '{{d.result.mw}}' }, kind: 'json' });
    expect(parseAnyValue('{{d.result}}').kind).toBe('text');
    expect(parseAnyValue('hello').value).toBe('hello');
    expect(parseAnyValue('  ').kind).toBe('empty');
  });
});
