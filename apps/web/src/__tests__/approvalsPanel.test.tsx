import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const calls: { path: string; init?: any }[] = [];
let rows: any[] = [];
let signoffReply: any = { data: { ok: true }, error: null };

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock('@/lib/api-client', () => ({
  apiFetch: vi.fn(async (path: string, init?: any) => {
    calls.push({ path, init });
    if (path.includes('/signoff')) return signoffReply;
    if (path.startsWith('/api/approvals')) return { data: rows, error: null };
    return { data: null, error: null };
  }),
}));
vi.mock('@/lib/inbox', async (orig) => {
  const actual = await orig<typeof import('@/lib/inbox')>();
  return { ...actual, refreshInboxCounts: vi.fn(async () => {}) };
});

const toasts: any[][] = [];
vi.mock('@/stores/toastStore', () => ({ toastSuccess: (...a: any[]) => toasts.push(a), toastError: vi.fn() }));

import ApprovalsPanel from '@/components/inbox/ApprovalsPanel';

const ME = { id: 'me' };

function row(over: Record<string, unknown> = {}) {
  return {
    id: 'a1',
    title: 'Publish Site exclusion version 2',
    status: 'pending',
    gate_kind: 'decision_publish',
    payload: { decision_key: 'site.exclusion', version: 2, link: '/decisions/site.exclusion?version=2', summary: 'Ready. 1 golden test pass.' },
    requested_by: 'u2',
    requested_by_name: 'Rita Reviewer',
    change_note: 'Adds the crane rule',
    changes: 4,
    can_sign: true,
    signoffs: [],
    created_at: new Date().toISOString(),
    ...over,
  };
}

function signoffBodies() {
  return calls.filter((c) => c.path.includes('/signoff')).map((c) => JSON.parse(c.init.body));
}

beforeEach(() => {
  calls.length = 0;
  toasts.length = 0;
  rows = [row()];
  signoffReply = { data: { ok: true }, error: null };
});

describe('Needs you approvals', () => {
  it('sends the reason typed in the deny dialog', async () => {
    render(<ApprovalsPanel me={ME} caps={[]} />);
    fireEvent.click(await screen.findByTestId('inbox-deny'));
    fireEvent.change(screen.getByTestId('deny-dialog-reason'), { target: { value: 'The crane rule is wrong' } });
    fireEvent.click(screen.getByTestId('deny-dialog-confirm'));
    await waitFor(() => expect(signoffBodies()).toEqual([{ decision: 'deny', reason: 'The crane rule is wrong' }]));
  });

  it('sends a returned request back with what to change', async () => {
    render(<ApprovalsPanel me={ME} caps={[]} />);
    fireEvent.click(await screen.findByTestId('inbox-return'));
    fireEvent.change(screen.getByTestId('return-dialog-reason'), { target: { value: 'Add a golden test for rain' } });
    fireEvent.click(screen.getByTestId('return-dialog-confirm'));
    await waitFor(() => expect(signoffBodies()).toEqual([{ decision: 'return', reason: 'Add a golden test for rain' }]));
  });

  it('says the reason did not arrive when the server asks for one that was typed', async () => {
    signoffReply = { data: null, error: 'Say why', errorDetail: { error_code: 'REASON_REQUIRED', code: 422 } };
    render(<ApprovalsPanel me={ME} caps={[]} />);
    fireEvent.click(await screen.findByTestId('inbox-deny'));
    fireEvent.change(screen.getByTestId('deny-dialog-reason'), { target: { value: 'Not safe yet' } });
    fireEvent.click(screen.getByTestId('deny-dialog-confirm'));
    expect(await screen.findByText(/Couldn't send your reason, try again/)).toBeInTheDocument();
  });

  it('shows who asked, why, and what changes', async () => {
    render(<ApprovalsPanel me={ME} caps={[]} />);
    expect(await screen.findByTestId('inbox-requester')).toHaveTextContent('Asked by Rita Reviewer');
    expect(screen.getByTestId('inbox-why')).toHaveTextContent('Adds the crane rule');
    expect(screen.getByTestId('inbox-summary')).toHaveTextContent('1 golden test passes. 4 rule changes.');
  });

  it('explains an archive and asks before approving one at high risk', async () => {
    rows = [row({
      id: 'a2', title: 'Archive Site exclusion (high risk)', gate_kind: 'decision_archive', change_note: null, changes: null,
      payload: { decision_key: 'site.exclusion', tier: 'high', reason: 'Replaced by the new rule', link: '/decisions/site.exclusion' },
    })];
    render(<ApprovalsPanel me={ME} caps={[]} />);
    expect(await screen.findByTestId('inbox-kind')).toHaveTextContent('Archive a decision');
    expect(screen.getByTestId('inbox-summary')).toHaveTextContent('Archive site.exclusion, at High risk.');
    expect(screen.getByTestId('inbox-why')).toHaveTextContent('Replaced by the new rule');
    expect(screen.getByTestId('inbox-evidence')).toHaveAttribute('href', '/decisions/site.exclusion');
    fireEvent.click(screen.getByTestId('inbox-approve'));
    expect(signoffBodies()).toEqual([]);
    fireEvent.click(await screen.findByTestId('inbox-approve-confirm'));
    await waitFor(() => expect(signoffBodies()).toEqual([{ decision: 'approve' }]));
  });

  it('asks before a tier lowering takes effect and says what approving did', async () => {
    rows = [row({
      id: 'a3', title: 'Lower Site exclusion from high to low risk', gate_kind: 'decision_tier_change', change_note: null, changes: null,
      payload: { decision_key: 'site.exclusion', from_tier: 'high', to_tier: 'low', reason: 'Sensors stop the machine now', link: '/decisions/site.exclusion' },
    })];
    render(<ApprovalsPanel me={ME} caps={[]} />);
    expect(await screen.findByTestId('inbox-summary')).toHaveTextContent('Lower site.exclusion from High to Low risk.');
    fireEvent.click(screen.getByTestId('inbox-approve'));
    expect(signoffBodies()).toEqual([]);
    expect(await screen.findByText('Lower site.exclusion from High to Low risk?')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('inbox-approve-confirm'));
    await waitFor(() => expect(signoffBodies()).toEqual([{ decision: 'approve' }]));
    await waitFor(() => expect(toasts).toHaveLength(1));
    expect(toasts[0][1]).toMatch(/Low risk/);
  });

  it('tells you about your own requests waiting on someone else', async () => {
    rows = [row({ requested_by: 'me', can_sign: false })];
    render(<ApprovalsPanel me={ME} caps={[]} />);
    expect(await screen.findByTestId('inbox-yours-waiting')).toHaveTextContent('One request of yours is waiting on someone else');
    expect(screen.getByTestId('inbox-approvals-empty')).toBeInTheDocument();
  });
});
