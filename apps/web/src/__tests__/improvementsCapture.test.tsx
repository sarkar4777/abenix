import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));

const api = vi.hoisted(() => ({
  feedback: vi.fn(),
  note: vi.fn(),
  acceptCase: vi.fn(),
  dropCase: vi.fn(),
  bulkCases: vi.fn(),
  patchCase: vi.fn(),
  setGate: vi.fn(),
}));
vi.mock('@/lib/improvements', async (orig) => {
  const actual = await orig<typeof import('@/lib/improvements')>();
  return { ...actual, improvementsApi: { ...actual.improvementsApi, ...api } };
});

import FeedbackBar, { THANKS } from '@/components/improvements/FeedbackBar';
import WrongBecause from '@/components/improvements/WrongBecause';
import SuggestedCases from '@/components/improvements/SuggestedCases';
import {
  checkSummary, isServerId, needsConfirmation, plural, severityMeta, trendDirection, trendText, type CaseRow,
} from '@/lib/improvements';

const ok = (data: unknown) => Promise.resolve({ data, error: null });

describe('improvement helpers', () => {
  it('reads trends in words', () => {
    expect(trendText([])).toBe('Nothing new in 14 days');
    const rising = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 2, 1];
    expect(trendDirection(rising)).toBe('up');
    expect(trendText(rising)).toBe('4 new lessons this week, rising');
    expect(trendDirection([3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1])).toBe('down');
  });

  it('knows server ids from local chat ids', () => {
    expect(isServerId('0a1b2c3d-1111-2222-3333-444455556666')).toBe(true);
    expect(isServerId('chat-1700000000000-3')).toBe(false);
    expect(isServerId(undefined)).toBe(false);
  });

  it('labels severity, plurals and checks', () => {
    expect(severityMeta('high').label).toBe('High');
    expect(severityMeta('nonsense').label).toBe('Low');
    expect(plural(1, 'lesson')).toBe('1 lesson');
    expect(plural(3, 'lesson')).toBe('3 lessons');
    expect(checkSummary({ type: 'judge', rubric: 'Use today' })).toBe('Judged against: Use today');
    const long = checkSummary({ type: 'judge', rubric: `${'word '.repeat(40)}agrees with that.` });
    expect(long.endsWith('word…')).toBe(true);
    expect(long.length).toBeLessThanOrEqual('Judged against: '.length + 161);
    expect(needsConfirmation({ tags: ['needs_confirmation'] } as CaseRow)).toBe(true);
  });
});

describe('FeedbackBar', () => {
  beforeEach(() => Object.values(api).forEach((f) => f.mockReset()));

  it('renders nothing without something to rate', () => {
    const { container } = render(<FeedbackBar />);
    expect(container).toBeEmptyDOMElement();
  });

  it('thumbs up thanks the person and links owners to the lessons', async () => {
    api.feedback.mockReturnValue(ok({ id: 'f', lesson_id: 'l', agent_id: 'ag-1', rating: 1, can_view_lessons: true }));
    render(<FeedbackBar executionId="ex-1" />);
    fireEvent.click(screen.getByTestId('feedback-up'));
    await waitFor(() => expect(screen.getByTestId('feedback-thanks')).toHaveTextContent(THANKS));
    expect(api.feedback).toHaveBeenCalledWith({ executionId: 'ex-1', messageId: undefined, conversationId: undefined, agentId: undefined }, 1, undefined);
    expect(screen.getByTestId('feedback-lessons-link')).toHaveAttribute('href', '/agents/ag-1/improvements');
    expect(screen.getByTestId('feedback-up')).toHaveAttribute('aria-pressed', 'true');
  });

  it('thumbs down saves at once, then the optional correction updates it', async () => {
    api.feedback.mockReturnValue(ok({ id: 'f', lesson_id: 'l', agent_id: 'ag-1', rating: -1, can_view_lessons: false }));
    render(<FeedbackBar messageId="m-1" conversationId="c-1" agentId="ag-1" testId="chat-feedback" />);
    fireEvent.click(screen.getByTestId('chat-feedback-down'));
    await waitFor(() => expect(screen.getByTestId('chat-feedback-box')).toBeInTheDocument());
    expect(api.feedback).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('chat-feedback-send')).toBeDisabled();
    fireEvent.change(screen.getByTestId('chat-feedback-correction'), { target: { value: "Use today's price" } });
    fireEvent.click(screen.getByTestId('chat-feedback-send'));
    await waitFor(() => expect(screen.getByTestId('chat-feedback-thanks')).toHaveTextContent('with your correction'));
    expect(api.feedback).toHaveBeenLastCalledWith(
      { executionId: undefined, messageId: 'm-1', conversationId: 'c-1', agentId: 'ag-1' }, -1, "Use today's price",
    );
    expect(screen.queryByTestId('chat-feedback-lessons-link')).toBeNull();
  });

  it('opens the correction box before the thumbs down has saved', async () => {
    let done: (v: unknown) => void = () => {};
    api.feedback.mockReturnValue(new Promise((r) => { done = r; }));
    render(<FeedbackBar executionId="ex-1" />);
    fireEvent.click(screen.getByTestId('feedback-down'));
    expect(screen.getByTestId('feedback-box')).toHaveTextContent('Saving your thumbs down.');
    done({ data: { id: 'f', lesson_id: 'l', agent_id: 'ag-1', rating: -1, can_view_lessons: false }, error: null });
    await waitFor(() => expect(screen.getByTestId('feedback-box')).toHaveTextContent('already saved'));
  });

  it('closes the box when the thumbs down could not be saved', async () => {
    api.feedback.mockReturnValue(Promise.resolve({ data: null, error: 'boom', status: 500 }));
    render(<FeedbackBar executionId="ex-1" />);
    fireEvent.click(screen.getByTestId('feedback-down'));
    await waitFor(() => expect(screen.getByTestId('feedback-error')).toHaveTextContent('not saved'));
    expect(screen.queryByTestId('feedback-box')).toBeNull();
  });

  it('a correction offers See the lesson to people who can view it', async () => {
    api.feedback.mockReturnValue(ok({ id: 'f', lesson_id: 'l', agent_id: 'ag-1', rating: -1, can_view_lessons: true }));
    render(<FeedbackBar executionId="ex-1" />);
    fireEvent.click(screen.getByTestId('feedback-down'));
    await waitFor(() => screen.getByTestId('feedback-box'));
    expect(screen.queryByTestId('feedback-next')).toBeNull();
    fireEvent.change(screen.getByTestId('feedback-correction'), { target: { value: 'Say 8,240' } });
    fireEvent.click(screen.getByTestId('feedback-send'));
    await waitFor(() => expect(screen.getByTestId('feedback-next-lesson')).toHaveAttribute('href', '/agents/ag-1/improvements'));
    expect(screen.getByTestId('feedback-next-lesson')).toHaveTextContent('See the lesson');
    fireEvent.click(screen.getByTestId('feedback-next-dismiss'));
    expect(screen.queryByTestId('feedback-next')).toBeNull();
  });

  it('skip closes the box and the thumbs down stays', async () => {
    api.feedback.mockReturnValue(ok({ id: 'f', lesson_id: 'l', agent_id: 'ag-1', rating: -1, can_view_lessons: true }));
    render(<FeedbackBar executionId="ex-1" />);
    fireEvent.click(screen.getByTestId('feedback-down'));
    await waitFor(() => screen.getByTestId('feedback-skip'));
    fireEvent.click(screen.getByTestId('feedback-skip'));
    expect(screen.getByTestId('feedback-thanks')).toBeInTheDocument();
    expect(api.feedback).toHaveBeenCalledTimes(1);
  });

  it('says plainly when saving failed', async () => {
    api.feedback.mockReturnValue(Promise.resolve({ data: null, error: 'boom', status: 500 }));
    render(<FeedbackBar executionId="ex-1" />);
    fireEvent.click(screen.getByTestId('feedback-up'));
    await waitFor(() => expect(screen.getByTestId('feedback-error')).toHaveTextContent('not saved'));
    expect(screen.queryByTestId('feedback-thanks')).toBeNull();
  });
});

describe('WrongBecause', () => {
  beforeEach(() => Object.values(api).forEach((f) => f.mockReset()));

  it('needs a note, then saves it with the right answer', async () => {
    api.note.mockReturnValue(ok({ lesson_id: 'l', agent_id: 'ag-1' }));
    render(<WrongBecause executionId="ex-1" agentId="ag-1" />);
    fireEvent.click(screen.getByTestId('wrong-because-open'));
    expect(screen.getByTestId('wrong-because-save')).toBeDisabled();
    fireEvent.change(screen.getByTestId('wrong-because-note'), { target: { value: 'old price' } });
    fireEvent.change(screen.getByTestId('wrong-because-expected'), { target: { value: '8,240' } });
    fireEvent.click(screen.getByTestId('wrong-because-save'));
    await waitFor(() => expect(screen.getByTestId('wrong-because-saved')).toBeInTheDocument());
    expect(api.note).toHaveBeenCalledWith({ agent_id: 'ag-1', execution_id: 'ex-1', note: 'old price', expected: '8,240' });
  });
});

const caseRow = (id: string, extra: Partial<CaseRow> = {}): CaseRow => ({
  id,
  suite_id: 's',
  name: `Correction: question ${id}`,
  input_message: `question ${id}`,
  assertions: [{ type: 'judge', rubric: 'Agree with the reference', min_score: 0.7 }],
  reference_output: 'right answer',
  tags: ['improvement'],
  state: 'suggested',
  source_lesson_id: 'l',
  lesson_title: 'Uses last month\'s price',
  ...extra,
});

describe('SuggestedCases', () => {
  beforeEach(() => Object.values(api).forEach((f) => f.mockReset()));

  it('has an empty state', () => {
    render(<SuggestedCases cases={[]} canManage onChanged={() => {}} />);
    expect(screen.getByTestId('improvement-cases-empty')).toBeInTheDocument();
  });

  it('accepts picked cases in bulk and removes them from the list', async () => {
    const changed = vi.fn();
    api.bulkCases.mockReturnValue(ok({ done: [caseRow('a'), caseRow('b')], skipped: [] }));
    render(<SuggestedCases cases={[caseRow('a'), caseRow('b', { tags: ['needs_confirmation'] })]} canManage onChanged={changed} />);
    expect(screen.getByText('Check before accepting')).toBeInTheDocument();
    expect(screen.getByTestId('improvement-cases-accept')).toBeDisabled();
    fireEvent.click(screen.getByTestId('improvement-cases-all'));
    fireEvent.click(screen.getByTestId('improvement-cases-accept'));
    await waitFor(() => expect(screen.getByTestId('improvement-cases-empty')).toBeInTheDocument());
    expect(api.bulkCases).toHaveBeenCalledWith(['a', 'b'], 'accept');
    expect(changed).toHaveBeenCalled();
  });

  it('asks before dropping', async () => {
    api.dropCase.mockReturnValue(ok(caseRow('a', { state: 'dropped' })));
    render(<SuggestedCases cases={[caseRow('a')]} canManage onChanged={() => {}} />);
    fireEvent.click(screen.getByTestId('improvement-case-drop'));
    expect(api.dropCase).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId('improvement-cases-drop-confirm'));
    await waitFor(() => expect(api.dropCase).toHaveBeenCalledWith('a'));
  });

  it('edits the rule before accepting', async () => {
    api.patchCase.mockImplementation((_id: string, body: any) => ok({ ...caseRow('a'), ...body }));
    render(<SuggestedCases cases={[caseRow('a')]} canManage onChanged={() => {}} />);
    fireEvent.click(screen.getByTestId('improvement-case-edit'));
    fireEvent.change(screen.getByTestId('improvement-case-rubric'), { target: { value: 'Quote today' } });
    fireEvent.click(screen.getByTestId('improvement-case-save'));
    await waitFor(() => expect(screen.getByText('Judged against: Quote today')).toBeInTheDocument());
    expect(api.patchCase.mock.calls[0][1].assertions[0].rubric).toBe('Quote today');
  });

  it('explains why someone else cannot act', () => {
    render(<SuggestedCases cases={[caseRow('a')]} canManage={false} onChanged={() => {}} />);
    expect(screen.getByTestId('improvement-case-accept')).toBeDisabled();
    expect(screen.getAllByText(/Only the agent's owner/).length).toBeGreaterThan(0);
  });
});

import GateToggle from '@/components/improvements/GateToggle';
import { gateWarning } from '@/lib/improvements';

describe('GateToggle', () => {
  const setGate = api.setGate;
  beforeEach(() => setGate.mockReset());

  it('warns in words before gating on failing tests', () => {
    expect(gateWarning({ suite_id: 's', gating: false, accepted: 3, failing: 2, last_run_at: null }))
      .toBe('2 tests fail right now, edits to this live agent will be refused until they pass.');
    expect(gateWarning({ suite_id: 's', gating: false, accepted: 1, failing: null, last_run_at: null })).toMatch(/not run yet/);
    expect(gateWarning({ suite_id: 's', gating: false, accepted: 1, failing: 0, last_run_at: null })).toBeNull();
  });

  it('is off by default and asks first when tests fail', async () => {
    const gate = { suite_id: 's', gating: false, accepted: 2, failing: 1, last_run_at: null };
    setGate.mockReturnValue(ok({ ...gate, gating: true }));
    const changed = vi.fn();
    render(<GateToggle agentId="ag-1" gate={gate} canManage onChanged={changed} />);
    const sw = screen.getByTestId('improvement-gate-switch');
    expect(sw).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(sw);
    expect(setGate).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId('improvement-gate-confirm'));
    await waitFor(() => expect(setGate).toHaveBeenCalledWith('ag-1', true));
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({ gating: true }));
  });

  it('turns off at once and is blocked without accepted tests', async () => {
    setGate.mockReturnValue(ok({ suite_id: 's', gating: false, accepted: 2, failing: 0, last_run_at: null }));
    const { unmount } = render(<GateToggle agentId="ag-1" gate={{ suite_id: 's', gating: true, accepted: 2, failing: 0, last_run_at: null }} canManage onChanged={() => {}} />);
    fireEvent.click(screen.getByTestId('improvement-gate-switch'));
    await waitFor(() => expect(setGate).toHaveBeenCalledWith('ag-1', false));
    unmount();
    render(<GateToggle agentId="ag-1" gate={{ suite_id: null, gating: false, accepted: 0, failing: null, last_run_at: null }} canManage onChanged={() => {}} />);
    expect(screen.getByTestId('improvement-gate-switch')).toBeDisabled();
    expect(screen.getByText('Accept at least one suggested case first.')).toBeInTheDocument();
  });
});
