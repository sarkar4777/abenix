import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('next/navigation', () => ({ useParams: () => ({ grantId: 'g-1' }) }));
vi.mock('@/hooks/usePageTitle', () => ({ usePageTitle: () => {} }));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return {
    ...actual,
    useMyPermissions: () => ({ perms: { capabilities: ['autonomy.view', 'autonomy.manage', 'actions.review'] }, loading: false }),
  };
});

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api-client', () => ({ apiFetch, API_URL: 'http://test' }));

import GrantPage from '@/app/(app)/autonomy/[grantId]/page';

const grant = {
  id: 'g-1',
  agent: { id: 'ag-1', name: 'Plant operator' },
  action_type: { id: 'at-1', key: 'sample_plant.set_setpoint', label: 'Set the plant setpoint', is_sample: true },
  level: 1,
  state: 'active',
  stats: {},
  next: {},
  changes: [],
};

const watched = (id: string, exec: string) => ({
  id, execution_id: exec, status: 'watching', agent: grant.agent,
  action_type: { key: grant.action_type.key, label: grant.action_type.label }, arguments: { setpoint_bar: 4.5 },
});

describe('grant page sample runs', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    apiFetch.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it('replaces the spinner with a summary and filters to the reviews', async () => {
    let after = false;
    apiFetch.mockImplementation(async (path: string) => {
      if (path.startsWith('/api/autonomy/grants/g-1/actions')) {
        const items = after ? [watched('n1', 'e1'), watched('n2', 'e2'), watched('old', 'x')] : [watched('old', 'x')];
        if (path.includes('status=watching')) return { data: { items: items.filter((a) => a.id !== 'old') }, error: null };
        return { data: { items }, error: null };
      }
      if (path.startsWith('/api/autonomy/grants/g-1')) return { data: grant, error: null };
      if (path === '/api/autonomy/sample/run') { after = true; return { data: { execution_ids: ['e1', 'e2', 'e3'] }, error: null }; }
      if (path.startsWith('/api/executions/e3')) return { data: { status: 'failed' }, error: null };
      if (path.startsWith('/api/executions/')) return { data: { status: 'completed', output_message: 'Done.' }, error: null };
      return { data: null, error: 'unexpected' };
    });

    render(<GrantPage />);
    await waitFor(() => expect(screen.getByTestId('autonomy-run-sample-3')).not.toBeDisabled());
    fireEvent.click(screen.getByTestId('autonomy-run-sample-3'));
    await waitFor(() => expect(screen.getByTestId('autonomy-run-status')).toBeInTheDocument());

    await act(async () => { await vi.advanceTimersByTimeAsync(5100); });
    await waitFor(() => expect(screen.getByTestId('autonomy-run-summary')).toHaveTextContent('3 runs finished. 2 new actions below.'));
    expect(screen.queryByTestId('autonomy-run-status')).toBeNull();
    expect(screen.getByTestId('autonomy-run-failed')).toHaveTextContent('1 run failed');
    expect(screen.getByRole('link', { name: 'e3' })).toHaveAttribute('href', '/executions/e3');

    fireEvent.click(screen.getByTestId('autonomy-timeline-review'));
    await waitFor(() => expect(screen.getByTestId('autonomy-filter-watching')).toHaveAttribute('aria-pressed', 'true'));
    await waitFor(() => expect(screen.getAllByTestId('autonomy-review-agree').length).toBe(2));
  });
});
