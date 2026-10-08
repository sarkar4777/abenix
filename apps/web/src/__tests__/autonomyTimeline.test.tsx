import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api-client', () => ({ apiFetch, API_URL: 'http://test' }));

import TimelineAction from '@/components/autonomy/TimelineAction';
import SampleRunSummary from '@/components/autonomy/SampleRunSummary';
import { runSummaryText, summarizeRuns, type ActionRow, type RunSummary } from '@/lib/autonomy';

const base: ActionRow = {
  id: 'act-1',
  agent: { id: 'ag-1', name: 'Plant operator' },
  action_type: { key: 'sample_plant.set_setpoint', label: 'Set the plant setpoint' },
  arguments: { setpoint_bar: 4.5 },
  intent: 'Pressure is low',
  level_at_time: 2,
};

const bodyOf = (match: string) => {
  const call = apiFetch.mock.calls.find((c) => String(c[0]).includes(match));
  return call ? JSON.parse(call[1].body) : null;
};

describe('timeline acts in place', () => {
  beforeEach(() => apiFetch.mockReset());

  it('approves a waiting action through the approval signoff and refreshes', async () => {
    apiFetch.mockResolvedValue({ data: { ok: true }, error: null });
    const onRefresh = vi.fn();
    render(<TimelineAction action={{ ...base, status: 'pending', approval_id: 'ap-9' }} onChanged={vi.fn()} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByTestId('action-card-approve'));
    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
    expect(bodyOf('/api/approvals/ap-9/signoff')).toEqual({ decision: 'approve' });
  });

  it('sends edited arguments like the Approvals page', async () => {
    apiFetch.mockResolvedValue({ data: { ok: true }, error: null });
    render(<TimelineAction action={{ ...base, status: 'pending', approval_id: 'ap-9' }} onChanged={vi.fn()} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByTestId('action-card-edit'));
    fireEvent.change(screen.getByTestId('action-card-arg-setpoint_bar'), { target: { value: '4.2' } });
    fireEvent.click(screen.getByTestId('action-card-edit-submit'));
    await waitFor(() => expect(bodyOf('/signoff')).toEqual({ decision: 'approve', reason: 'Approved with edits', edited_arguments: { setpoint_bar: 4.2 } }));

  });

  it('rejects with the note as the reason', async () => {
    apiFetch.mockResolvedValue({ data: { ok: true }, error: null });
    render(<TimelineAction action={{ ...base, status: 'pending', approval_id: 'ap-9' }} onChanged={vi.fn()} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByTestId('action-card-reject'));
    fireEvent.change(screen.getByTestId('action-card-reject-note'), { target: { value: 'Too high' } });
    fireEvent.click(screen.getByTestId('action-card-reject-submit'));
    await waitFor(() => expect(bodyOf('/signoff')).toEqual({ decision: 'deny', reason: 'Too high' }));
  });

  it('explains a 403 inline and does not refresh', async () => {
    apiFetch.mockResolvedValue({ data: null, error: 'Forbidden', errorDetail: { code: 403, message: 'Forbidden' } });
    const onRefresh = vi.fn();
    render(<TimelineAction action={{ ...base, status: 'pending', approval_id: 'ap-9' }} onChanged={vi.fn()} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByTestId('action-card-approve'));
    await waitFor(() => expect(screen.getByTestId('action-card-error')).toHaveTextContent('You need the approvals permission for this'));
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it('answers an unreviewed watched action with the review call', async () => {
    apiFetch.mockResolvedValue({ data: { ...base, status: 'watching', reviewer_answer: 'agree' }, error: null });
    const onChanged = vi.fn();
    render(<TimelineAction action={{ ...base, status: 'watching' }} onChanged={onChanged} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByTestId('autonomy-review-agree'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(bodyOf('/api/autonomy/actions/act-1/review')).toEqual({ answer: 'agree' });
  });

  it('leaves everything else as it was', () => {
    const { rerender } = render(<TimelineAction action={{ ...base, status: 'watching', reviewer_answer: 'agree' }} onChanged={vi.fn()} onRefresh={vi.fn()} />);
    expect(screen.queryByTestId('autonomy-review-agree')).toBeNull();
    rerender(<TimelineAction action={{ ...base, status: 'pending' }} onChanged={vi.fn()} onRefresh={vi.fn()} />);
    expect(screen.queryByTestId('action-card-approve')).toBeNull();
    rerender(<TimelineAction action={{ ...base, status: 'executed' }} onChanged={vi.fn()} onRefresh={vi.fn()} />);
    expect(screen.queryByTestId('action-card-approve')).toBeNull();
    expect(screen.queryByTestId('autonomy-review-agree')).toBeNull();
  });
});

describe('sample run summary', () => {
  const results = {
    e1: { id: 'e1', status: 'completed', output: 'Raised the setpoint.' },
    e2: { id: 'e2', status: 'completed', output: 'Raised it again.' },
    e3: { id: 'e3', status: 'completed', output: 'The plant is already at 4.5 bar, so I changed nothing. All good.' },
  };

  it('counts new actions against the snapshot and names the quiet run', () => {
    const s = summarizeRuns({
      runIds: ['e1', 'e2', 'e3'],
      results,
      beforeIds: ['old'],
      after: [
        { id: 'n1', execution_id: 'e1', status: 'watching' },
        { id: 'n2', execution_id: 'e2', status: 'watching' },
        { id: 'old', status: 'watching' },
      ],
      level: 1,
      timedOut: false,
    });
    expect(s).toMatchObject({ finished: 3, newActions: 2, quiet: 1, reviewStatus: 'watching', reviewCount: 2, failed: [] });
    expect(runSummaryText(s)).toBe('3 runs finished. 2 new actions below. 1 run changed nothing: "The plant is already at 4.5 bar, so I changed nothing."');
  });

  it('uses pending for level 2 and reports failures and timeouts', () => {
    const s = summarizeRuns({
      runIds: ['e1', 'e4', 'e5'],
      results: { e1: results.e1, e4: { id: 'e4', status: 'failed' } },
      beforeIds: [],
      after: [{ id: 'n1', execution_id: 'e1', status: 'pending' }],
      level: 2,
      timedOut: true,
    });
    expect(s).toMatchObject({ reviewStatus: 'pending', reviewCount: 1, failed: ['e4'], newActions: 1 });
    expect(runSummaryText(s)).toBe('Stopped watching after 4 minutes. 2 of 3 runs finished. 1 new action below.');
  });

  it('says nothing changed when no actions came in', () => {
    const s = summarizeRuns({ runIds: ['e3'], results, beforeIds: ['a'], after: [{ id: 'a' }], level: 1, timedOut: false });
    expect(s.newActions).toBe(0);
    expect(runSummaryText(s)).toBe('1 run finished. The agent found nothing to change. It said: "The plant is already at 4.5 bar, so I changed nothing."');
  });

  const summary = (over: Partial<RunSummary>): RunSummary => ({
    total: 3, finished: 3, timedOut: false, failed: [], newActions: 2, quiet: 0, quietSaid: null,
    reviewStatus: 'watching', reviewCount: 2, ...over,
  });

  it('offers review here and no run again when actions came in', () => {
    const onReview = vi.fn();
    render(<SampleRunSummary summary={summary({})} canRun runBusy={false} onRunAgain={vi.fn()} onReview={onReview} />);
    expect(screen.getByTestId('autonomy-run-summary')).toHaveTextContent('2 waiting for your review');
    expect(screen.queryByTestId('autonomy-run-again')).toBeNull();
    fireEvent.click(screen.getByTestId('autonomy-timeline-review'));
    expect(onReview).toHaveBeenCalledWith('watching');
  });

  it('offers run again and links failed runs', () => {
    const onRunAgain = vi.fn();
    render(<SampleRunSummary summary={summary({ newActions: 0, reviewCount: 0, failed: ['abcdef123456'] })} canRun runBusy={false} onRunAgain={onRunAgain} onReview={vi.fn()} />);
    expect(screen.queryByTestId('autonomy-timeline-review')).toBeNull();
    expect(screen.getByTestId('autonomy-run-failed')).toHaveTextContent('1 run failed');
    expect(screen.getByRole('link', { name: 'abcdef12' })).toHaveAttribute('href', '/executions/abcdef123456');
    fireEvent.click(screen.getByTestId('autonomy-run-again'));
    expect(onRunAgain).toHaveBeenCalled();
  });
});
