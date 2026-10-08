import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import {
  ago, categoryLabel, holdMinutesError, maskAll, maskRange, normaliseSpans, segments, slaText,
} from '@/lib/moderation-review';
import { holdBlockFrom, useChatStore } from '@/stores/chatStore';
import { useNotificationStore } from '@/stores/notificationStore';
import { retentionErrors } from '@/components/moderation/RetentionCard';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }));

describe('review helpers', () => {
  it('cuts text into plain and matched pieces', () => {
    const text = 'call ZX-9 now';
    expect(segments(text, [{ start: 5, end: 9, category: 'custom:0' }])).toEqual([
      { text: 'call ' },
      { text: 'ZX-9', category: 'custom:0' },
      { text: ' now' },
    ]);
    expect(segments(text, [])).toEqual([{ text }]);
  });

  it('joins overlapping spans and clips them to the text', () => {
    expect(normaliseSpans([
      { start: 2, end: 6, category: 'hate' },
      { start: 4, end: 99, category: 'custom:1' },
    ], 10)).toEqual([{ start: 2, end: 10, category: 'hate,custom:1' }]);
  });

  it('masks every match, or a selection', () => {
    expect(maskAll('a ZX b ZX', [{ start: 2, end: 4, category: 'x' }, { start: 7, end: 9, category: 'x' }], '#')).toBe('a # b #');
    expect(maskRange('hello world', 6, 11, '█')).toBe('hello █');
    expect(maskRange('hello', 3, 3, '█')).toBe('hello');
  });

  it('names custom patterns the way the moderation page does', () => {
    expect(categoryLabel('custom:0')).toBe('custom pattern 1');
    expect(categoryLabel('self-harm/intent')).toBe('self-harm / intent');
  });

  it('says when the time limit acts and flags the last ten minutes', () => {
    const now = Date.parse('2026-01-01T10:00:00Z');
    expect(slaText('2026-01-01T10:05:00Z', 'reject', now)).toEqual({ text: 'Rejects on its own in 5 min', urgent: true });
    expect(slaText('2026-01-01T12:00:00Z', 'release', now).text).toBe('Releases on its own in 2 h');
    expect(ago('2026-01-01T09:00:00Z', now)).toBe('1 h ago');
  });

  it('checks the review time limit and retention values', () => {
    expect(holdMinutesError('60')).toBeNull();
    expect(holdMinutesError('')).toMatch(/Enter/);
    expect(holdMinutesError('1.5')).toMatch(/whole number/);
    expect(holdMinutesError('99999')).toMatch(/Between 1 and 10080/);
    const limits = { held_content_days: [0, 365], decision_record_days: [30, 3650], event_preview_days: [1, 365] } as const;
    const lim = limits as unknown as Record<'held_content_days' | 'decision_record_days' | 'event_preview_days', [number, number]>;
    expect(retentionErrors({ held_content_days: '30', decision_record_days: '365', event_preview_days: '30' }, lim)).toEqual({});
    expect(retentionErrors({ held_content_days: '400', decision_record_days: '365', event_preview_days: '0' }, lim)).toEqual({
      held_content_days: 'Between 0 and 365 days.',
      event_preview_days: 'Between 1 and 365 days.',
    });
    expect(retentionErrors({ held_content_days: '90', decision_record_days: '60', event_preview_days: '1' }, lim).held_content_days).toBeTruthy();
  });
});

describe('held content in chat', () => {
  beforeEach(() => {
    apiFetch.mockReset();
    useChatStore.getState().clearChat();
  });
  afterEach(() => vi.useRealTimers());

  it('turns a held moderation event into a hold card', () => {
    expect(holdBlockFrom({ source: 'pre_llm', outcome: 'held', review_id: 'r1', timeout_minutes: 30 }, 'hi')).toEqual({
      type: 'moderation_hold', review_id: 'r1', source: 'pre_llm', text: 'hi', timeout_minutes: 30, timeout_action: undefined,
    });
    expect(holdBlockFrom({ source: 'pre_llm', outcome: 'blocked' })).toBeNull();
  });

  it('shows waiting, then the released text when the decision is pushed', async () => {
    const { default: HeldNotice } = await import('@/components/moderation/HeldNotice');
    apiFetch.mockResolvedValueOnce({
      data: { id: 'r1', status: 'pending', status_label: 'Waiting', source: 'pre_llm', expires_at: null, timeout_action: 'reject', decided_at: null, reason: null, delivered: false, conversation_id: 'c1', content: 'my code ZX-9' },
      error: null,
    });
    const onReleased = vi.fn();
    render(<HeldNotice block={{ type: 'moderation_hold', review_id: 'r1', source: 'pre_llm', timeout_minutes: 60 }} onReleased={onReleased} />);
    expect(await screen.findByText('Your message is waiting for review')).toBeTruthy();
    expect(screen.getByText('my code ZX-9')).toBeTruthy();

    apiFetch.mockResolvedValueOnce({
      data: { id: 'r1', status: 'redacted', status_label: 'Redacted', source: 'pre_llm', expires_at: null, timeout_action: 'reject', decided_at: 'x', reason: null, delivered: false, conversation_id: 'c1', content: 'my code █' },
      error: null,
    });
    act(() => {
      useNotificationStore.setState({ moderationReview: { id: 'r1', status: 'redacted', at: Date.now() } });
    });
    await waitFor(() => expect(screen.getByTestId('held-notice').getAttribute('data-status')).toBe('released'));
    expect(screen.getByTestId('held-notice-content').textContent).toBe('my code █');
    expect(onReleased).toHaveBeenCalledTimes(1);
  });

  it('shows the reviewer reason when a reply is rejected', async () => {
    const { default: HeldNotice } = await import('@/components/moderation/HeldNotice');
    apiFetch.mockResolvedValueOnce({
      data: { id: 'r2', status: 'rejected', status_label: 'Rejected', source: 'post_llm', expires_at: null, timeout_action: 'reject', decided_at: 'x', reason: 'Shares an account number', delivered: false, conversation_id: null, content: null },
      error: null,
    });
    render(<HeldNotice block={{ type: 'moderation_hold', review_id: 'r2', source: 'post_llm' }} />);
    expect(await screen.findByText('The reply was not sent')).toBeTruthy();
    expect(screen.getByTestId('held-notice-reason').textContent).toContain('Shares an account number');
  });
});
