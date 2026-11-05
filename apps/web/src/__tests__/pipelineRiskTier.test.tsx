import { fireEvent, render, screen } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/hooks/useApi', () => ({
  useApi: () => ({
    data: {
      tiers: [{ tier: 'critical', guide: 'g', effective: { publish_approvals: { min_approvers: 2, exclude_author: true }, require_output_schema: true, allowed_models: [], tool_call_action: 'allow' } }],
      tools: [],
    },
    isLoading: false,
    error: null,
    meta: null,
    mutate: vi.fn(),
  }),
}));

import StepConfigPanel from '@/components/builder/pipeline/StepConfigPanel';

const panel = (extra: Record<string, unknown> = {}) => (
  <StepConfigPanel step={null} allSteps={[]} onUpdate={vi.fn()} onClose={vi.fn()} onRiskTierChange={vi.fn()} onOutputSchemaChange={vi.fn()} {...extra} />
);

describe('pipeline risk tier', () => {
  it('is on the pipeline settings and reports a change', () => {
    const onRiskTierChange = vi.fn();
    render(panel({ riskTier: 'low', onRiskTierChange }));
    fireEvent.click(screen.getByTestId('risk-tier-critical'));
    expect(onRiskTierChange).toHaveBeenCalledWith('critical');
  });

  it('says what the tier needs and points at the schema box in the same panel', () => {
    render(panel({ riskTier: 'critical' }));
    expect(screen.getByTestId('risk-tier-effects')).toHaveTextContent('sign-off');
    expect(screen.getByTestId('risk-tier-needs-schema')).toHaveTextContent('before the pipeline can go live. Add one below.');
    expect(screen.getByTestId('pipeline-output-schema')).toBeInTheDocument();
  });

  it('counts a typed schema', () => {
    render(panel({ riskTier: 'critical', outputSchema: '{"type":"object"}' }));
    expect(screen.queryByTestId('risk-tier-needs-schema')).toBeNull();
  });
});
