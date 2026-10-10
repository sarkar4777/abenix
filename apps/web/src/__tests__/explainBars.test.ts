import { describe, it, expect } from 'vitest';
import { topContributions, type Explanation } from '@/components/ml/ExplainBars';

const e: Explanation = {
  method: 'tree-shap',
  prediction: 7,
  base_value: 2,
  contributions: [
    { feature: 'a', value: 1, baseline: 0, contribution: 0.5 },
    { feature: 'b', value: 2, baseline: 0, contribution: -3 },
    { feature: 'c', value: 3, baseline: 0, contribution: 4 },
    { feature: 'd', value: 4, baseline: 0, contribution: 1.5 },
  ],
};

describe('explanation bars', () => {
  it('orders features by how much they moved the prediction', () => {
    expect(topContributions(e).shown.map((c) => c.feature)).toEqual(['c', 'b', 'd', 'a']);
  });

  it('folds the smallest into one line past the limit', () => {
    const t = topContributions(e, 2);
    expect(t.shown.map((c) => c.feature)).toEqual(['c', 'b']);
    expect(t.restCount).toBe(2);
    expect(t.rest).toBeCloseTo(2);
  });
});
