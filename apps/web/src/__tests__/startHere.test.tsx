import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Journey } from '@/components/shared/StartHere';

let journey: Journey | null = null;
const apiFetch = vi.fn();
vi.mock('@/hooks/useApi', () => ({
  useApi: () => ({ data: journey, isLoading: false, error: null, meta: null, mutate: () => {} }),
}));
vi.mock('@/lib/api-client', () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }));

import StartHere from '@/components/shared/StartHere';

const steps = [
  { id: 'build_agent', title: 'Build your first agent', why: 'w', href: '/builder', cta: 'Open the builder', done: true },
  { id: 'run_agent', title: 'Run it', why: 'w', href: '/agents/a1/chat', cta: 'Try it in chat', done: false },
  { id: 'add_tests', title: 'Add tests', why: 'w', href: '/evals', cta: 'Add a test suite', done: false },
];

describe('StartHere', () => {
  beforeEach(() => {
    localStorage.clear();
    apiFetch.mockReset();
  });

  it('shows the steps, the progress and links each to its place', () => {
    journey = { role: 'builder', steps, done: 1, total: 3, complete: false, dismissed: false };
    render(<StartHere />);
    expect(screen.getByTestId('start-here')).toHaveAttribute('data-role', 'builder');
    expect(screen.getByTestId('start-here-progress')).toHaveAttribute('aria-valuenow', '1');
    expect(screen.getByText('1 of 3 done')).toBeInTheDocument();
    expect(screen.getByTestId('start-here-build_agent')).toHaveAttribute('data-done', 'true');
    expect(screen.getByTestId('start-here-run_agent')).toHaveAttribute('data-done', 'false');
    expect(screen.getByTestId('start-here-run_agent-go')).toHaveAttribute('href', '/agents/a1/chat');
  });

  it('dismisses through the API and offers to bring it back', async () => {
    journey = { role: 'builder', steps, done: 1, total: 3, complete: false, dismissed: false };
    apiFetch.mockResolvedValueOnce({ data: { ...journey, dismissed: true }, error: null });
    render(<StartHere />);
    fireEvent.click(screen.getByTestId('start-here-dismiss'));
    await waitFor(() => expect(screen.getByTestId('start-here-restore')).toBeInTheDocument());
    expect(apiFetch).toHaveBeenCalledWith('/api/me/journey', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ dismissed: true }) }));
  });

  it('celebrates once when everything is done', () => {
    journey = { role: 'member', steps: steps.map((s) => ({ ...s, done: true })), done: 3, total: 3, complete: true, dismissed: false };
    const { unmount } = render(<StartHere />);
    expect(screen.getByTestId('start-here-complete')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('start-here-complete-close'));
    expect(screen.queryByTestId('start-here-complete')).not.toBeInTheDocument();
    unmount();
    render(<StartHere />);
    expect(screen.queryByTestId('start-here-complete')).not.toBeInTheDocument();
  });
});
