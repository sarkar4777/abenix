import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));

const api = vi.hoisted(() => ({ outcome: vi.fn(), harm: vi.fn() }));
vi.mock('@/lib/autonomy', async (orig) => {
  const actual = await orig<typeof import('@/lib/autonomy')>();
  return { ...actual, autonomyApi: { ...actual.autonomyApi, outcome: api.outcome, harm: api.harm } };
});

import ActionCard from '@/components/autonomy/ActionCard';
import { parseDrafts, initialDrafts } from '@/components/autonomy/ArgumentForm';
import type { ActionCardData } from '@/lib/autonomy';

const card: ActionCardData = {
  action_id: 'act-1',
  action_type: { key: 'sample_plant.set_setpoint', label: 'Set the plant setpoint', reversible: true },
  agent: { id: 'ag-1', name: 'Plant operator (sample)' },
  level: 2,
  level_label: 'Asks first',
  target: 'plant',
  arguments: { setpoint_bar: 4.5, operation: 'set_setpoint', dry_run: false, tags: ['a'] },
  intent: 'Pressure is low',
  prediction: { metric: 'pressure_bar', value: 4.4, low: 4.1, high: 4.6, horizon_s: 30, source: 'agent_stated' },
  limits: { ok: true, decision_key: 'sample_plant_limits', reasons: [] },
  record: { held: 47, scored: 50, text: 'Held 47 of 50 times' },
  editable_arguments: true,
};

describe('argument drafts', () => {
  it('round trips typed values and flags bad input', () => {
    const args = { n: 1.5, s: 'x', b: true, o: { k: 1 } };
    const d = initialDrafts(args);
    expect(parseDrafts(args, d)).toEqual({ value: args, errors: {} });
    const bad = parseDrafts(args, { ...d, n: 'abc', o: '{nope' });
    expect(Object.keys(bad.errors).sort()).toEqual(['n', 'o']);
  });
});

describe('ActionCard', () => {
  beforeEach(() => {
    api.outcome.mockReset();
    api.harm.mockReset();
  });

  it('shows what, why, prediction, limits and record', () => {
    render(<ActionCard card={card} context="readonly" />);
    expect(screen.getByTestId('action-card')).toHaveAttribute('data-action-id', 'act-1');
    expect(screen.getByText('Pressure is low')).toBeInTheDocument();
    expect(screen.getByTestId('action-card-prediction')).toHaveTextContent('pressure bar 4.4 (between 4.1 and 4.6) in 30 seconds');
    expect(screen.getByTestId('action-card-limits-ok')).toBeInTheDocument();
    expect(screen.getByTestId('action-card-record')).toHaveTextContent('Held 47 of 50 times');
    expect(screen.queryByTestId('action-card-approve')).toBeNull();
  });

  it('shows limit breaches in red and the fallback reason', () => {
    render(<ActionCard card={{ ...card, limits: { ok: false, reasons: ['setpoint 7.2 is above the 6.0 limit'] }, fallback_reason: 'The prediction timed out' }} />);
    expect(screen.getByTestId('action-card-limits-breach')).toHaveTextContent('setpoint 7.2 is above the 6.0 limit');
    expect(screen.getByTestId('action-card-fallback')).toHaveTextContent('the prediction timed out');
  });

  it('approves as is', () => {
    const onApprove = vi.fn();
    render(<ActionCard card={card} context="approval" onApprove={onApprove} />);
    fireEvent.click(screen.getByTestId('action-card-approve'));
    expect(onApprove).toHaveBeenCalledWith();
  });

  it('edits with typed fields and sends the edited arguments', () => {
    const onApprove = vi.fn();
    render(<ActionCard card={card} context="approval" onApprove={onApprove} />);
    fireEvent.click(screen.getByTestId('action-card-edit'));
    const sp = screen.getByTestId('action-card-arg-setpoint_bar') as HTMLInputElement;
    expect(sp.type).toBe('number');
    expect((screen.getByTestId('action-card-arg-dry_run') as HTMLSelectElement).tagName).toBe('SELECT');
    fireEvent.change(sp, { target: { value: '' } });
    expect(screen.getByTestId('action-card-edit-submit')).toBeDisabled();
    fireEvent.change(sp, { target: { value: '4.2' } });
    fireEvent.click(screen.getByTestId('action-card-edit-submit'));
    expect(onApprove).toHaveBeenCalledWith({ setpoint_bar: 4.2, operation: 'set_setpoint', dry_run: false, tags: ['a'] });
  });

  it('needs a note to reject', () => {
    const onReject = vi.fn();
    render(<ActionCard card={card} context="approval" onReject={onReject} />);
    fireEvent.click(screen.getByTestId('action-card-reject'));
    const submit = screen.getByTestId('action-card-reject-submit');
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId('action-card-reject-note'), { target: { value: 'Too high for night shift' } });
    fireEvent.click(submit);
    expect(onReject).toHaveBeenCalledWith('Too high for night shift');
  });

  it('asks what the reviewer did when they answer Different', () => {
    const onReview = vi.fn();
    render(<ActionCard card={card} context="review" onReview={onReview} />);
    fireEvent.click(screen.getByTestId('autonomy-review-agree'));
    expect(onReview).toHaveBeenCalledWith('agree');
    fireEvent.click(screen.getByTestId('autonomy-review-different'));
    fireEvent.change(screen.getByTestId('autonomy-review-alternative'), { target: { value: 'Set 4.8' } });
    fireEvent.click(screen.getByTestId('autonomy-review-different-submit'));
    expect(onReview).toHaveBeenLastCalledWith('different', 'Set 4.8');
  });

  it('shows the outcome against the band', () => {
    render(
      <ActionCard
        card={card}
        action={{ id: 'act-1', status: 'executed', outcome: { metric: 'pressure_bar', value: 4.35, source: 'tool' }, outcome_status: 'observed', score: { within_band: true, band_ok: true } }}
        context="timeline"
        canFollowUp
      />,
    );
    expect(screen.getByTestId('action-card-outcome')).toHaveTextContent('Actual pressure bar 4.35.');
    expect(screen.getByTestId('action-card-outcome')).toHaveTextContent('Inside the predicted band.');
    expect(screen.queryByTestId('action-card-enter-outcome')).toBeNull();
    expect(screen.getByTestId('action-card-flag-harm')).toBeInTheDocument();
  });

  it('enters an outcome and flags harm with a note', async () => {
    const onChanged = vi.fn();
    api.outcome.mockResolvedValue({ data: { id: 'act-1', outcome_status: 'manual' }, error: null });
    api.harm.mockResolvedValue({ data: { id: 'act-1', harm: true }, error: null });
    render(
      <ActionCard card={card} action={{ id: 'act-1', status: 'executed', outcome_status: 'pending' }} context="timeline" canFollowUp onChanged={onChanged} />,
    );
    fireEvent.click(screen.getByTestId('action-card-enter-outcome'));
    fireEvent.change(screen.getByTestId('action-card-outcome-value'), { target: { value: '4.3' } });
    fireEvent.click(screen.getByTestId('action-card-outcome-submit'));
    await waitFor(() => expect(api.outcome).toHaveBeenCalledWith('act-1', 4.3));

    fireEvent.click(screen.getByTestId('action-card-flag-harm'));
    expect(screen.getByTestId('action-card-harm-confirm')).toBeDisabled();
    fireEvent.change(screen.getByTestId('action-card-harm-note'), { target: { value: 'Alarm tripped' } });
    fireEvent.click(screen.getByTestId('action-card-harm-confirm'));
    await waitFor(() => expect(api.harm).toHaveBeenCalledWith('act-1', 'Alarm tripped'));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
  });

  it('hides follow ups from people without the review permission', () => {
    render(<ActionCard card={card} action={{ id: 'act-1', status: 'executed', outcome_status: 'pending' }} context="timeline" />);
    expect(screen.queryByTestId('action-card-flag-harm')).toBeNull();
    expect(screen.queryByTestId('action-card-enter-outcome')).toBeNull();
  });
});
