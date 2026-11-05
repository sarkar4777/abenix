import { render, screen } from '@testing-library/react';

const state: { execution: Record<string, unknown> } = { execution: {} };

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'e1' }),
  usePathname: () => '/executions/e1',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/hooks/usePageTitle', () => ({ usePageTitle: () => {} }));
vi.mock('@/hooks/useApi', () => ({
  useApi: (path: string | null) => ({ data: path === '/api/executions/e1' ? state.execution : null, error: null, isLoading: false, meta: null, mutate: vi.fn() }),
}));

import ExecutionDetailPage from '@/app/(app)/executions/[id]/page';

const RUN = {
  id: 'e1', agent_id: 'a1', agent_name: 'Echo', status: 'completed', input_message: 'hello', output_message: 'answer here',
  input_tokens: 1, output_tokens: 1, cost: 0, duration_ms: 10, tool_calls: [], created_at: '2026-01-01T00:00:00Z',
};

class SilentEventSource {
  onmessage = null;
  onerror = null;
  addEventListener() {}
  removeEventListener() {}
  close() {}
}

beforeEach(() => vi.stubGlobal('EventSource', SilentEventSource));
afterEach(() => vi.unstubAllGlobals());

describe('run details', () => {
  it('renders for a member the API sends no prompt or tool config to', () => {
    state.execution = RUN;
    render(<ExecutionDetailPage />);
    expect(screen.getByTestId('page-header')).toBeInTheDocument();
    expect(screen.getAllByText(/completed/i).length).toBeGreaterThan(0);
    expect(screen.queryByText('System Prompt (sent to LLM)')).toBeNull();
    expect(screen.queryByText('Tool Configuration (injected into prompt)')).toBeNull();
  });

  it('shows them to someone the API does send them to', () => {
    state.execution = { ...RUN, system_prompt: 'You are terse.', tool_config: { web_search: {} } };
    render(<ExecutionDetailPage />);
    expect(screen.getByText('System Prompt (sent to LLM)')).toBeInTheDocument();
  });
});
