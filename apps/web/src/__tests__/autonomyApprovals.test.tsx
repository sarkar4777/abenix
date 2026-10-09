import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));

const permsState: { perms: { capabilities: string[] } | undefined; loading: boolean } = {
  perms: { capabilities: ['actions.review'] },
  loading: false,
};
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => permsState };
});

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api-client', () => ({ apiFetch, API_URL: 'http://test' }));

import ApprovalsPage from '@/app/(app)/approvals/page';

const actionRow = {
  id: 'ap-1',
  agent_id: 'ag-1',
  agent_execution_id: 'ex-1',
  title: 'Plant operator wants to Set the plant setpoint',
  payload: {
    action_id: 'act-1',
    action_type: { key: 'sample_plant.set_setpoint', label: 'Set the plant setpoint', reversible: true },
    agent: { id: 'ag-1', name: 'Plant operator (sample)' },
    level: 2,
    arguments: { setpoint_bar: 4.5 },
    intent: 'Pressure is low',
    prediction: { metric: 'pressure_bar', value: 4.4, low: 4.1, high: 4.6 },
    limits: { ok: true },
    record: { text: 'Held 3 of 4 times' },
    editable_arguments: true,
  },
  required_signoffs: 1,
  signoffs: [],
  status: 'pending',
  requested_by: null,
  expires_at: null,
  decided_at: null,
  created_at: new Date().toISOString(),
  gate_kind: 'action:sample_plant.set_setpoint',
};

const plainRow = { ...actionRow, id: 'ap-2', title: 'Generic gate', payload: { foo: 1 }, gate_kind: 'human_approval' };

function route(reviews: unknown = []) {
  apiFetch.mockImplementation(async (path: string, opts?: { method?: string; body?: string }) => {
    if (path.startsWith('/api/approvals?mine=1&status=pending')) return { data: [actionRow, plainRow], error: null };
    if (path.startsWith('/api/approvals?mine=1')) return { data: [actionRow, plainRow], error: null };
    if (path.includes('/signoff')) return { data: { ok: true }, error: null, _body: opts?.body };
    if (path.startsWith('/api/autonomy/reviews')) return { data: reviews, error: null };
    if (path.includes('/review')) return { data: { id: 'w1', card: { action_id: 'w1', intent: 'Raise it', agent: { name: 'Plant operator' }, action_type: { label: 'Set the plant setpoint' } } }, error: null };
    return { data: null, error: 'unexpected' };
  });
}

describe('Approvals with action cards', () => {
  beforeEach(() => {
    apiFetch.mockReset();
    window.history.replaceState(null, '', '/approvals');
  });

  it('renders an action card for action gates and the old card for others', async () => {
    route();
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getAllByTestId('action-card').length).toBeGreaterThan(0));
    expect(screen.getAllByTestId('approval-action-row')[0]).toHaveAttribute('data-approval-id', 'ap-1');
    expect(screen.getAllByTestId('approval-card').length).toBeGreaterThan(0);
  });

  it('sends edited arguments with the approval', async () => {
    route();
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getAllByTestId('action-card-edit').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByTestId('action-card-edit')[0]);
    fireEvent.change(screen.getByTestId('action-card-arg-setpoint_bar'), { target: { value: '4.2' } });
    fireEvent.click(screen.getByTestId('action-card-edit-submit'));
    await waitFor(() => {
      const call = apiFetch.mock.calls.find((c) => String(c[0]).includes('/api/approvals/ap-1/signoff'));
      expect(call).toBeTruthy();
      expect(JSON.parse(call![1].body)).toEqual({ decision: 'approve', reason: 'Approved with edits', edited_arguments: { setpoint_bar: 4.2 } });
    });
  });

  it('keeps an edited fix on screen while it is proved again', async () => {
    const fix = {
      ...actionRow,
      id: 'ap-fix',
      title: 'Release a fix to Temperature helper',
      gate_kind: 'improvement.release',
      payload: {
        id: 'p-1', proposal_id: 'p-1', agent: { id: 'ag-1', name: 'Temperature helper' }, cluster: { id: 'c1', title: 'Kelvin' },
        change_kind: 'prompt_edit', change_label: 'Edit the instructions', diff: { append: 'Use kelvin.' }, rationale: 'Use the asked unit.',
        risk: 'low', state: 'awaiting_approval', progress: {}, proof: {},
      },
    };
    let edited = false;
    apiFetch.mockImplementation(async (path: string) => {
      if (path.includes('/rerun')) {
        edited = true;
        return { data: { ...fix.payload, state: 'proving' }, error: null };
      }
      if (path.startsWith('/api/approvals')) return { data: edited ? [] : [fix], error: null };
      return { data: [], error: null };
    });
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByTestId('improvement-edit-approve')).toBeTruthy());
    fireEvent.click(screen.getByTestId('improvement-edit-approve'));
    fireEvent.change(screen.getByTestId('improvement-approval-edit-text'), { target: { value: '{"append": "Use kelvin please."}' } });
    fireEvent.click(screen.getByTestId('improvement-edit-save'));
    await waitFor(() => expect(screen.getByTestId('improvement-approval-msg')).toHaveTextContent('being proved'));
    await waitFor(() => expect(apiFetch.mock.calls.filter(([p]) => String(p).includes('status=pending')).length).toBeGreaterThan(1));
    const card = screen.getByTestId('improvement-approval-card');
    expect(card).toHaveAttribute('data-approval-id', 'ap-fix');
    expect(screen.getByTestId('improvement-approval-status')).toHaveTextContent('withdrawn');
    expect(screen.queryByTestId('improvement-approve')).toBeNull();
  });

  it('rejects with the note as the reason', async () => {
    route();
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getAllByTestId('action-card-reject').length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByTestId('action-card-reject')[0]);
    fireEvent.change(screen.getByTestId('action-card-reject-note'), { target: { value: 'Not now' } });
    fireEvent.click(screen.getByTestId('action-card-reject-submit'));
    await waitFor(() => {
      const call = apiFetch.mock.calls.find((c) => String(c[0]).includes('/api/approvals/ap-1/signoff'));
      expect(JSON.parse(call![1].body)).toEqual({ decision: 'deny', reason: 'Not now' });
    });
  });

  it('answers watching reviews from the keyboard and reveals the card', async () => {
    route({ items: [
      { id: 'w1', situation: 'Pressure 3.6 bar, demand rising', agent: { name: 'Plant operator' }, action_type: { label: 'Set the plant setpoint' } },
      { id: 'w2', situation: 'Pressure 5.4 bar', agent: { name: 'Plant operator' }, action_type: { label: 'Set the plant setpoint' } },
    ], total: 12 });
    render(<ApprovalsPage />);
    fireEvent.click(screen.getByTestId('approvals-tab-reviews'));
    await waitFor(() => expect(screen.getByTestId('autonomy-review-situation')).toHaveTextContent('Pressure 3.6 bar'));
    expect(screen.getByTestId('autonomy-reviews-left')).toHaveTextContent('12 left');

    await act(async () => { fireEvent.keyDown(window, { key: 'a' }); });
    await waitFor(() => expect(screen.getByTestId('autonomy-review-situation')).toHaveTextContent('Pressure 5.4 bar'));
    const call = apiFetch.mock.calls.find((c) => String(c[0]).includes('/api/autonomy/actions/w1/review'));
    expect(JSON.parse(call![1].body)).toEqual({ answer: 'agree' });
    expect(screen.getByTestId('autonomy-reviews-left')).toHaveTextContent('11 left');
    expect(screen.getByTestId('autonomy-review-revealed')).toHaveTextContent('Raise it');

    await act(async () => { fireEvent.keyDown(window, { key: 'd' }); });
    fireEvent.change(screen.getByTestId('autonomy-review-alternative'), { target: { value: 'Lowered to 4.6' } });
    fireEvent.click(screen.getByTestId('autonomy-review-different-submit'));
    await waitFor(() => {
      const c2 = apiFetch.mock.calls.find((c) => String(c[0]).includes('/api/autonomy/actions/w2/review'));
      expect(JSON.parse(c2![1].body)).toEqual({ answer: 'different', alternative: 'Lowered to 4.6' });
    });
  });

  it.each(['reviews', 'watching'])('opens the watching reviews tab from ?tab=%s', async (tab) => {
    route();
    window.history.replaceState(null, '', `/approvals?tab=${tab}`);
    render(<ApprovalsPage />);
    await waitFor(() => expect(screen.getByTestId('approvals-tab-reviews')).toHaveAttribute('aria-selected', 'true'));
    expect(screen.getByTestId('approvals-tab-pending')).toHaveAttribute('aria-selected', 'false');
  });

  it('explains the missing permission on the reviews tab', async () => {
    route();
    permsState.perms = { capabilities: [] };
    render(<ApprovalsPage />);
    fireEvent.click(screen.getByTestId('approvals-tab-reviews'));
    expect(screen.getByTestId('autonomy-reviews-no-access')).toHaveTextContent('actions.review');
    permsState.perms = { capabilities: ['actions.review'] };
  });
});
