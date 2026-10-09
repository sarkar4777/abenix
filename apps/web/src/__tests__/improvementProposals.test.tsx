import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import {
  asProposal, fixedText, meterTone, money, parseDiff, pct, seconds, stepText, watchLeft, wordDiff, editableDiff,
} from '@/lib/improvement-proposals';
import ProofBody from '@/components/improvements/proposals/ProofBody';
import ReleaseWatch, { measureRows } from '@/components/improvements/proposals/ReleaseWatch';
import ImprovementApprovalCard, { type Decided } from '@/components/improvements/proposals/ImprovementApprovalCard';
import ReleasedNext from '@/components/improvements/proposals/ReleasedNext';
import BudgetMeter from '@/components/improvements/proposals/BudgetMeter';
import { BeforeAfter } from '@/components/improvements/proposals/parts';
import type { ProposalRow } from '@/lib/improvements';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }));
vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));

const proof = {
  fixed: [{ lesson_id: 'l1', title: 'What is 25 degrees Celsius in Kelvin?' }],
  broken: [],
  still_failing: [],
  target_lessons: 4,
  cases_run: 6,
  scores: {
    before: { runs: 6, pass_rate: 0.33, quality: 0.33, cost_usd: 0.0004, latency_ms: 900, tool_calls: 0 },
    after: { runs: 6, pass_rate: 1, quality: 1, cost_usd: 0.00041, latency_ms: 950, tool_calls: 0 },
  },
  replay: { sampled: 0, changed: 0, watching_effects: 0 },
  examples: [{ input: '0 C in K', before: '0 °C is 32 °F.', after: '0 °C is 273.15 K.', verdict: 'fixed' }],
  passed_bar: true,
  bar_reasons: [],
};

const row = {
  id: 'p1',
  agent: { id: 'a1', name: 'Temperature helper (sample)' },
  cluster: { id: 'c1', title: 'Answers in Fahrenheit when the user asks for Kelvin' },
  change_kind: 'prompt_edit',
  change_label: 'Edit the instructions',
  diff: {
    edits: [{ find: 'Always give the answer in degrees Fahrenheit.', replace: 'Answer in the unit asked for.' }],
    preview: { what: 'instructions', lines: [{ op: 'remove', text: 'Always give the answer in degrees Fahrenheit.' }, { op: 'add', text: 'Answer in the unit asked for.' }] },
  },
  rationale: 'People asked for Kelvin and got Fahrenheit.',
  risk: 'low',
  state: 'awaiting_approval',
  state_label: 'Waiting for approval',
  progress: { phase: 'done', steps: [] },
  proof,
  approval_id: 'ap1',
  released_revision_id: null,
  watch_until: null,
  watch_result: null,
  created_at: '2026-10-08T10:00:00Z',
};

beforeEach(() => apiFetch.mockReset());

describe('proposal helpers', () => {
  it('reads loose rows and fills the gaps', () => {
    const p = asProposal({ id: 'x', state: 'weird', progress: [] });
    expect(p.state).toBe('drafting');
    expect(p.proof).toBeNull();
    expect(p.change_label).toBe('Not drafted yet');
    expect(asProposal(row).proof?.fixed.length).toBe(1);
  });

  it('says what was fixed in plain words', () => {
    expect(fixedText(asProposal(row).proof)).toBe('Fixed 1 of 4, broke 0');
    expect(fixedText(null)).toBe('No proof yet');
  });

  it('formats numbers and steps', () => {
    expect(pct(0.256)).toBe('26%');
    expect(pct(null)).toBe('n/a');
    expect(money(0.0004)).toBe('$0.0004');
    expect(seconds(1500)).toBe('1.5 s');
    expect(stepText({ key: 'test_set', label: 'Test set', state: 'running', done: 2, total: 6 })).toBe('Test set 2 of 6');
    expect(stepText({ key: 'done', label: 'Done', state: 'done', done: 1, total: 1 })).toBe('Done');
    expect(meterTone(5, 10)).toBe('bg-emerald-400');
    expect(meterTone(10, 10)).toBe('bg-rose-400');
  });

  it('marks new words in the fixed answer', () => {
    const marks = wordDiff('0 °C is 32 °F.', '0 °C is 273.15 K.').filter((w) => w.added).map((w) => w.text);
    expect(marks).toEqual(['273.15', 'K.']);
  });

  it('checks an edited change before sending it', () => {
    expect(parseDiff('{"append": "x"}').diff).toEqual({ append: 'x' });
    expect(parseDiff('[1]').error).toMatch(/object/);
    expect(parseDiff('{nope').error).toMatch(/not valid JSON/);
    expect(editableDiff(asProposal(row))).not.toContain('preview');
  });

  it('counts the watch down', () => {
    const now = Date.parse('2026-10-08T10:00:00Z');
    expect(watchLeft('2026-10-10T10:00:00Z', now)).toBe('2 days left');
    expect(watchLeft('2026-10-08T12:00:00Z', now)).toBe('2 h left');
    expect(watchLeft('2026-10-08T09:00:00Z', now)).toBe('ends at the next check');
  });
});

describe('proof view', () => {
  it('shows fixed, zero broken, the diff and a real example', () => {
    render(<ProofBody p={asProposal(row)} />);
    expect(screen.getByTestId('proof-fixed').textContent).toContain('Fixed 1 of 4 lessons');
    expect(screen.getByTestId('proof-broken').getAttribute('data-count')).toBe('0');
    expect(screen.getByTestId('proposal-diff').textContent).toContain('Answer in the unit asked for.');
    expect(screen.getByTestId('proof-examples').textContent).toContain('273.15');
    expect(screen.getByTestId('proof-approval-link')).toBeTruthy();
  });

  it('keeps a failing proof with its reasons and never offers approval', () => {
    const failed = asProposal({
      ...row,
      state: 'failed_proof',
      state_label: 'Did not pass',
      approval_id: null,
      proof: { ...proof, passed_bar: false, broken: [{ case_id: 'c2', name: 'Good: 212 F', why: 'Output does not contain 100' }], bar_reasons: ['It broke 1 case that passed before.'] },
    });
    render(<ProofBody p={failed} />);
    expect(screen.getByTestId('proof-failed').textContent).toContain('It broke 1 case that passed before.');
    expect(screen.getByTestId('proof-broken').textContent).toContain('Good: 212 F');
    expect(screen.queryByTestId('proof-awaiting')).toBeNull();
    expect(screen.getByTestId('proof-rerun')).toBeTruthy();
  });

  it('shows each proof step with counts while it runs', () => {
    const running = asProposal({
      ...row,
      state: 'proving',
      proof: {},
      progress: {
        phase: 'test_set',
        message: 'Running 6 test cases on the current and the new version.',
        steps: [
          { key: 'test_set', label: 'Test set', state: 'running', done: 2, total: 6 },
          { key: 'replay', label: 'Replay of real inputs', state: 'pending', done: 0, total: 0 },
          { key: 'comparing', label: 'Comparing', state: 'pending', done: 0, total: 0 },
          { key: 'done', label: 'Done', state: 'pending', done: 0, total: 0 },
        ],
      },
    });
    render(<ProofBody p={running} />);
    expect(screen.getByTestId('proof-step-test_set').textContent).toContain('Test set 2 of 6');
    expect(screen.getByTestId('proof-step-replay').getAttribute('data-step-state')).toBe('pending');
  });
});

describe('release watch', () => {
  const rolled = {
    ...row,
    state: 'rolled_back',
    state_label: 'Rolled back',
    watch_runs_target: 20,
    watch_result: {
      outcome: 'rolled_back',
      automatic: true,
      reason: 'Thumbs down rose from 0% to 100% (3 of 3).',
      old: { runs: 4, failures: 0, cost_avg: 0.0004, thumbs_total: 0, thumbs_down: 0 },
      new: { runs: 3, failures: 0, cost_avg: 0.0004, thumbs_total: 3, thumbs_down: 3 },
      worse: ['Thumbs down rose from 0% to 100% (3 of 3).'],
    },
  };

  it('shows the automatic rollback and why', () => {
    render(<ReleaseWatch proposal={rolled as unknown as ProposalRow} />);
    expect(screen.getByTestId('release-rolled-back').textContent).toContain('Rolled back automatically');
    expect(screen.getByTestId('release-rollback-reason').textContent).toContain('Thumbs down rose');
    expect(screen.queryByTestId('release-rollback')).toBeNull();
  });

  it('marks the measure that got worse', () => {
    const rows = measureRows(rolled.watch_result as never);
    const thumbs = rows.find((r) => r.label === 'Thumbs down')!;
    expect(thumbs.worse).toBe(true);
    expect(thumbs.after).toBe('100% of 3');
    expect(rows.find((r) => r.label === 'Failed runs')!.worse).toBe(false);
  });
});

describe('approval card', () => {
  const approval = {
    id: 'ap1',
    title: 'Release a fix to Temperature helper (sample): Answers in Fahrenheit when the user asks for Kelvin',
    status: 'pending',
    gate_kind: 'improvement.release',
    payload: { ...row, proposal_id: 'p1', self_approval: null },
  };

  it('tells the author someone else approves and offers the fix', async () => {
    apiFetch.mockResolvedValue({
      data: null,
      error: 'You built this agent, so someone else has to approve this fix.',
      errorDetail: { message: 'x', code: 403, error_code: 'AUTHOR_CANNOT_APPROVE' },
    });
    render(<ImprovementApprovalCard approval={approval} />);
    fireEvent.click(screen.getByTestId('improvement-approve'));
    await waitFor(() => expect(screen.getByTestId('improvement-approval-msg').textContent).toContain('someone else'));
    expect(screen.getByText('Invite a teammate')).toBeTruthy();
  });

  it('hands the release link up after an approval, for Watch the release', async () => {
    apiFetch.mockResolvedValue({ data: { id: 'ap1', status: 'approved' }, error: null });
    const onDecided = vi.fn();
    const link = '/agents/a1/improvements?proposal=p1';
    render(<ImprovementApprovalCard approval={{ ...approval, payload: { ...approval.payload, link } }} onDecided={onDecided} />);
    fireEvent.click(screen.getByTestId('improvement-approve'));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    const d: Decided = onDecided.mock.calls[0][0];
    expect(d.decision).toBe('approve');
    expect(d.link).toBe(link);
    render(<ReleasedNext decided={d} onDismiss={() => {}} />);
    expect(screen.getByTestId('release-next-watch')).toHaveAttribute('href', link);
    expect(screen.getByTestId('release-next-watch').textContent).toContain('Watch the release');
  });

  it('shows no release steps after a rejection', () => {
    const { container } = render(<ReleasedNext decided={{ decision: 'deny', link: '/x', agentName: null }} onDismiss={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('needs a reason to reject', async () => {
    render(<ImprovementApprovalCard approval={approval} />);
    fireEvent.click(screen.getByTestId('improvement-reject'));
    fireEvent.click(screen.getByTestId('improvement-reject-confirm'));
    expect(screen.getByTestId('improvement-approval-msg').textContent).toContain('Say why');
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it('labels a self-approval', () => {
    render(<ImprovementApprovalCard approval={{ ...approval, payload: { ...approval.payload, self_approval: 'This is the sample, so you can approve it yourself.' } }} />);
    expect(screen.getByTestId('approval-self-approval').textContent).toContain('sample');
  });
});

describe('before and after', () => {
  const sc = { pass_rate: 1, quality: 1, cost_usd: 0, latency_ms: 1500, tool_calls: 0 };

  it('says when speed was not judged', () => {
    render(<BeforeAfter before={{ ...sc, timed_runs: 4 }} after={{ ...sc, latency_ms: 1990, timed_runs: 4 }} />);
    expect(screen.getByTestId('proof-speed-not-judged').textContent).toContain('fewer than 10 runs');
  });

  it('stays quiet when enough runs were timed', () => {
    render(<BeforeAfter before={{ ...sc, timed_runs: 12 }} after={{ ...sc, timed_runs: 12 }} />);
    expect(screen.queryByTestId('proof-speed-not-judged')).toBeNull();
  });
});

describe('budget meter', () => {
  it('shows real numbers from the API', async () => {
    apiFetch.mockResolvedValue({
      data: { tokens_today: 1200, tokens_limit: 400000, proofs_today: 2, proofs_limit: 20, queue_depth: 1, stopped: null },
      error: null,
    });
    render(<BudgetMeter />);
    await waitFor(() => expect(screen.getByTestId('budget-meter')).toBeTruthy());
    expect(screen.getByTestId('budget-proofs').textContent).toContain('2 of 20');
    expect(screen.getByTestId('budget-queue').textContent).toBe('1 in line');
  });

  it('tells a person their fix still runs when automatic proposals spent the total', async () => {
    apiFetch.mockResolvedValue({
      data: { tokens_today: 2_879_136, tokens_limit: 400000, proofs_today: 9, proofs_limit: 20, tokens_left: 196_760, proofs_left: 11, queue_depth: 7, stopped: null },
      error: null,
    });
    render(<BudgetMeter />);
    await waitFor(() => expect(screen.getByTestId('budget-note')).toBeTruthy());
    expect(screen.getByTestId('budget-note').getAttribute('data-tone')).toBe('auto');
    expect(screen.getByTestId('budget-note').textContent).toContain('Fixes you ask for still run');
  });

  it('says the day is spent when nothing is left for people', async () => {
    apiFetch.mockResolvedValue({
      data: { tokens_today: 400000, tokens_limit: 400000, proofs_today: 4, proofs_limit: 20, tokens_left: 0, proofs_left: 16, queue_depth: 0, stopped: null },
      error: null,
    });
    render(<BudgetMeter />);
    await waitFor(() => expect(screen.getByTestId('budget-note')).toBeTruthy());
    expect(screen.getByTestId('budget-note').getAttribute('data-tone')).toBe('spent');
  });

  it('says plainly when the budget cannot load', async () => {
    apiFetch.mockResolvedValue({ data: null, error: 'boom', errorDetail: { message: 'boom', code: 500 } });
    render(<BudgetMeter />);
    await waitFor(() => expect(screen.getByTestId('budget-meter-error').textContent).toContain('could not be loaded'));
  });
});
