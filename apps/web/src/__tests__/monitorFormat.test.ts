import { describe, expect, it } from 'vitest';
import { driftChange, failureLabel, metricLabel, roleLabel } from '@/lib/monitor-format';

describe('failureLabel', () => {
  it('names known codes in plain words', () => {
    expect(failureLabel('PIPELINE_NODE_FAILED')).toBe('A pipeline step failed');
    expect(failureLabel('LLM_RATE_LIMIT')).toBe('AI provider rate limit');
  });
  it('turns an unknown code into a sentence', () => {
    expect(failureLabel('WEIRD_NEW_THING')).toBe('Weird new thing');
  });
  it('is empty for no code', () => {
    expect(failureLabel(null)).toBe('');
  });
});

describe('driftChange', () => {
  it('drops the percent when the baseline was zero', () => {
    const s = driftChange({ metric_name: 'confidence', baseline_value: 0, current_value: 1, deviation_pct: 5000 });
    expect(s).toBe('Confidence rose from 0 to 1, there was no usual level yet');
    expect(s).not.toContain('%');
  });
  it('gives a percent against a real baseline', () => {
    expect(driftChange({ metric_name: 'output_tokens', baseline_value: 383.6, current_value: 148, deviation_pct: -61.4 }))
      .toBe('Output tokens fell 61%, from a usual 384 to 148');
  });
  it('uses a multiple for huge jumps', () => {
    expect(driftChange({ metric_name: 'cost', baseline_value: 0.02, current_value: 1, deviation_pct: 4900 })).toContain('49x');
  });
});

describe('labels', () => {
  it('reads metric names', () => {
    expect(metricLabel('output_length')).toBe('Answer length');
    expect(metricLabel('queue_depth')).toBe('Queue depth');
  });
  it('calls the user role Member, as the menus do', () => {
    expect(roleLabel('user')).toBe('Member');
    expect(roleLabel('creator')).toBe('Creator');
  });
});

describe('settingTitle', async () => {
  const { settingTitle } = await import('@/lib/monitor-format');
  it('names known settings', () => {
    expect(settingTitle('llm.subscription.token')).toBe('Subscription token');
  });
  it('reads an unknown key as words', () => {
    expect(settingTitle('foo.bar_baz')).toBe('Foo bar baz');
  });
});
