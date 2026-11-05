import { render, screen } from '@testing-library/react';

vi.mock('reactflow', () => ({ Handle: () => null, Position: { Left: 'left', Right: 'right' } }));

import { AgentNode } from '@/components/builder/nodes';

const node = (data: Record<string, unknown>) => <AgentNode {...({ data, selected: false } as any)} />;

describe('agent node on the builder canvas', () => {
  it('shows no stray zero with no tools and no inputs', () => {
    const { container } = render(node({ name: 'New Agent', model: 'claude-haiku-4-5', status: 'draft', toolCount: 0, inputParamCount: 0 }));
    expect(container.textContent).toBe('New Agentclaude-haiku-4-5');
  });

  it('still shows the summary when there is something to count', () => {
    render(node({ name: 'A', model: 'm', status: 'draft', toolCount: 2, inputParamCount: 0 }));
    expect(screen.getByText('2 tools')).toBeInTheDocument();
  });
});
