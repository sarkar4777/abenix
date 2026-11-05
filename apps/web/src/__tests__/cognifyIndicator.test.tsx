import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

import CognifyIndicator from '@/components/layout/CognifyIndicator';

const FAILED = { id: 'job-1', kb_id: 'kb-1', kb_name: 'Manuals', status: 'failed', documents_processed: 0, entities_extracted: 0, relationships_extracted: 0, tokens_used: 0, cost_usd: 0, duration_seconds: null, created_at: null, completed_at: null, error_message: 'No model key' };

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('access_token', 't');
  push.mockClear();
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { running: [], recent: [FAILED] } }) } as Response)) as unknown as typeof fetch;
});

describe('Cognify header badge', () => {
  it('links a failure to its job on the engine page', async () => {
    render(<CognifyIndicator />);
    fireEvent.click(await screen.findByTestId('cognify-indicator'));
    fireEvent.click(await screen.findByTestId('cognify-job-failed'));
    expect(push).toHaveBeenCalledWith('/knowledge/kb-1/engine#cognify-job-job-1');
  });

  it('goes away when the failure is dismissed and stays away on the next load', async () => {
    const { unmount } = render(<CognifyIndicator />);
    fireEvent.click(await screen.findByTestId('cognify-indicator'));
    fireEvent.click(await screen.findByTestId('cognify-dismiss'));
    await waitFor(() => expect(screen.queryByTestId('cognify-indicator')).toBeNull());
    unmount();

    render(<CognifyIndicator />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('cognify-indicator')).toBeNull();
  });

  it('comes back for a new failure', async () => {
    localStorage.setItem('cognify.dismissed', JSON.stringify(['an-older-job']));
    render(<CognifyIndicator />);
    expect(await screen.findByTestId('cognify-indicator')).toHaveTextContent('1 failed');
  });
});
