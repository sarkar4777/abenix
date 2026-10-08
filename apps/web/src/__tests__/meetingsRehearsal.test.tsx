import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock('@/lib/api-client', () => ({ apiFetch: api.fetch }));

import RehearsalPanel from '@/components/meetings/RehearsalPanel';
import {
  joinBlockReason, rehearseBlockReason, startBlockReason, summaryState,
} from '@/components/meetings/meeting-logic';

const meeting = {
  id: 'm1',
  title: 'ACME sync',
  status: 'authorized',
  display_name: 'Rep',
  scope_allow: ['roadmap'],
  scope_defer: ['pricing'],
  persona_scopes: ['self'],
};

describe('meeting button reasons', () => {
  const ready = { livekit_ready: true };
  it('says why the bot cannot start', () => {
    expect(startBlockReason({ ...meeting, provider: 'livekit', scope_allow: [] }, ready)).toMatch(/at least one topic/);
    expect(startBlockReason({ ...meeting, provider: 'livekit' }, { livekit_ready: false })).toMatch(/LiveKit keys/);
    expect(startBlockReason({ ...meeting, provider: 'livekit' }, ready)).toBeNull();
  });
  it('blocks join and rehearse only when they cannot work', () => {
    expect(joinBlockReason({ ...meeting, provider: 'livekit', status: 'done' }, ready)).toMatch(/ended/);
    expect(joinBlockReason({ ...meeting, provider: 'teams' }, ready)).toMatch(/teams/);
    expect(joinBlockReason({ ...meeting, provider: 'livekit' }, ready)).toBeNull();
    expect(rehearseBlockReason({ ...meeting, provider: 'livekit', status: 'live' })).toMatch(/live meeting/);
  });
  it('tracks the summary after the meeting', () => {
    const base = { ...meeting, provider: 'livekit' };
    expect(summaryState({ ...base, status: 'live' })).toBeNull();
    const ended = new Date().toISOString();
    expect(summaryState({ ...base, status: 'done', ended_at: ended })).toBe('writing');
    // the bot closing its session is not the end, the saved row is
    expect(summaryState({ ...base, status: 'done', ended_at: ended, bot_status: 'closed' })).toBe('writing');
    expect(summaryState({ ...base, status: 'done', ended_at: ended, finalized: true })).toBe('none');
    expect(summaryState({ ...base, status: 'done', ended_at: '2020-01-01T00:00:00Z' })).toBe('none');
    expect(summaryState({ ...base, status: 'done', summary: 'ok' })).toBe('summary');
  });
});

describe('RehearsalPanel', () => {
  beforeEach(() => api.fetch.mockReset());

  it('shows the banner and starts a rehearsal', async () => {
    api.fetch.mockImplementation(async (url: string, opts?: any) => {
      if (opts?.method === 'POST') return { data: { active: true, status: 'starting', transcript: [], decisions: [], deferrals: [] }, error: null };
      return { data: { active: false, available: true }, error: null };
    });
    render(<RehearsalPanel meeting={meeting} />);
    expect(screen.getByTestId('rehearsal-banner').textContent).toMatch(/This is a rehearsal/);
    fireEvent.click(await screen.findByTestId('rehearsal-start'));
    await waitFor(() => expect(screen.getByTestId('rehearsal-status').dataset.status).toBe('starting'));
    expect(api.fetch).toHaveBeenCalledWith('/api/meetings/m1/rehearsal', expect.objectContaining({ method: 'POST' }));
  });

  it('cannot start without a topic and says why', async () => {
    api.fetch.mockResolvedValue({ data: { active: false, available: true }, error: null });
    render(<RehearsalPanel meeting={{ ...meeting, scope_allow: [] }} />);
    expect(await screen.findByTestId('rehearsal-start')).toBeDisabled();
    expect(screen.getByTestId('rehearsal-blocked').textContent).toMatch(/at least one topic/);
  });

  it('renders scope, citations, a pending hand-back and reply latency', async () => {
    const t0 = Date.now();
    api.fetch.mockResolvedValue({
      error: null,
      data: {
        active: true,
        status: 'live',
        transcript: [
          { participant: 'Dana (chat)', text: 'Roadmap?', ts_ms: t0, via: 'chat', addressed: true },
          { participant: 'Rep', text: 'Q3 ships auth.', ts_ms: t0 + 4, bot: true, latency_ms: 2300 },
        ],
        decisions: [
          { kind: 'answer', summary: 'Scope check: inside the topics you allowed', ts_ms: t0 + 1, detail: { tool: 'scope_gate' } },
          { kind: 'cite', summary: 'Persona search found 1 source', ts_ms: t0 + 2, detail: { tool: 'persona_rag', citations: [{ title: 'Roadmap notes', score: 0.8 }] } },
          { kind: 'decline', summary: 'Scope check: outside the topics you allowed, will decline', ts_ms: t0 + 5, detail: { tool: 'scope_gate' } },
        ],
        deferrals: [{ id: 'd1', question: 'Can we get pricing?', context: null, answer: null, status: 'pending', created_at_ms: t0 + 6 }],
        queued_turns: 0,
      },
    });
    render(<RehearsalPanel meeting={meeting} />);
    expect(await screen.findByTestId('rehearsal-latency')).toHaveTextContent('replied in 2.3 s');
    expect(screen.getAllByTestId('rehearsal-scope').map(e => e.dataset.decision)).toEqual(['answer', 'decline']);
    expect(screen.getByTestId('rehearsal-citations')).toHaveTextContent('Roadmap notes');
    expect(screen.getByTestId('rehearsal-deferral')).toHaveTextContent('Can we get pricing?');
    expect(screen.getByTestId('rehearsal-send')).toBeDisabled();
  });
});
