import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { matchesFilters, originHref, originLabel, originNote, startedByText } from '@/lib/run-origin';

let flatRate = false;
vi.mock('@/hooks/useApi', () => ({
  useApi: () => ({ data: { flat_rate_billing: flatRate }, isLoading: false, error: null, meta: null, mutate: () => {} }),
}));

import { CostValue, SubscriptionNote, formatCostValue } from '@/components/shared/CostValue';

describe('started by', () => {
  it('names the trigger and how it fired', () => {
    expect(startedByText({ trigger_kind: 'schedule', trigger_name: 'Nightly', trigger_id: 't1' })).toBe('Nightly (schedule)');
    expect(startedByText({ trigger_kind: 'manual', trigger_name: 'Nightly', trigger_id: 't1' })).toBe('Nightly (run now)');
    expect(startedByText({ trigger_kind: 'webhook', trigger_name: 'Orders hook' })).toBe('Orders hook (webhook)');
    expect(startedByText({ trigger_kind: 'replay', trigger_name: 'Pinned replay' })).toBe('Pinned replay');
  });

  it('falls back to the kind, and says when nothing was recorded', () => {
    expect(startedByText({ trigger_kind: 'chat' })).toBe('Chat');
    expect(startedByText({ trigger_kind: 'api' })).toBe('API');
    expect(startedByText({})).toBe('Not recorded');
    expect(originLabel('brand_new_kind')).toBe('Brand new kind');
  });

  it('links to the trigger, the parent run, or nowhere', () => {
    expect(originHref({ trigger_kind: 'schedule', trigger_id: 't1' })).toBe('/triggers?focus=t1');
    expect(originHref({ trigger_kind: 'pipeline', parent_execution_id: 'p1' })).toBe('/executions/p1');
    expect(originHref({ trigger_kind: 'source_watch' })).toBe('/sources');
    expect(originHref({ trigger_kind: 'chat' })).toBeNull();
  });

  it('explains old runs and deleted triggers', () => {
    expect(originNote({})).toMatch(/older/);
    expect(originNote({ trigger_kind: 'schedule', trigger_name: 'Nightly' })).toMatch(/deleted/);
    expect(originNote({ trigger_kind: 'schedule', trigger_name: 'Nightly', trigger_id: 't' })).toBeNull();
    expect(originNote({ trigger_kind: 'manual' })).toBeNull();
  });
});

describe('rows kept on screen while a filter loads', () => {
  const run = { status: 'completed', input_message: 'Daily report', trigger_kind: 'schedule', trigger_id: 't1' };
  const none = { status: '', search: '', origin: '', triggerId: '' };

  it('drops rows that do not fit the new filters', () => {
    expect(matchesFilters(run, { ...none, status: 'failed' })).toBe(false);
    expect(matchesFilters(run, { ...none, status: 'completed' })).toBe(true);
    expect(matchesFilters(run, { ...none, search: 'daily' })).toBe(true);
    expect(matchesFilters(run, { ...none, search: 'weekly' })).toBe(false);
    expect(matchesFilters(run, { ...none, origin: 'chat,api' })).toBe(false);
    expect(matchesFilters(run, { ...none, origin: 'schedule,webhook,manual' })).toBe(true);
    expect(matchesFilters(run, { ...none, triggerId: 't2' })).toBe(false);
    expect(matchesFilters({ status: 'failed' }, { ...none, origin: 'unknown' })).toBe(true);
  });
});

describe('cost on a Claude subscription', () => {
  it('formats plain dollars when there is no subscription', () => {
    flatRate = false;
    render(<CostValue cost={0.0123} testId="c" />);
    expect(screen.getByTestId('c').textContent).toBe('$0.0123');
    expect(formatCostValue(2.5)).toBe('$2.50');
    expect(formatCostValue(null)).toBe('—');
  });

  it('says Claude subscription on a zero', () => {
    flatRate = true;
    render(<CostValue cost={0} testId="c" />);
    const el = screen.getByTestId('c');
    expect(el.textContent).toContain('Claude subscription');
    expect(el.getAttribute('data-billing')).toBe('subscription');
  });

  it('keeps another provider spend and tags it', () => {
    flatRate = true;
    render(<CostValue cost={1.19} testId="c" />);
    expect(screen.getByTestId('c').textContent).toBe('$1.19+ Claude subscription');
  });

  it('shows the note only on a subscription', () => {
    flatRate = false;
    const { container, rerender } = render(<SubscriptionNote />);
    expect(container.textContent).toBe('');
    rerender(<SubscriptionNote flatRate />);
    expect(screen.getByTestId('subscription-cost-note').textContent).toMatch(/flat-rate subscription/);
  });
});
