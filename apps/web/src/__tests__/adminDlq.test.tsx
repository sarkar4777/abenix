import { render, screen, waitFor } from '@testing-library/react';

vi.mock('@/components/layout/PageHeader', () => ({ default: ({ title }: { title: string }) => <h1>{title}</h1> }));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => ({ perms: null, loading: false }) };
});

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api-client', () => ({ apiFetch, API_URL: 'http://test' }));

import DlqPage from '@/app/(app)/admin/dlq/page';

const RAW_CODE = /\b[A-Z]+(?:_[A-Z]+)*_(?:ERROR|FAILED|TIMEOUT|EXCEEDED)\b/;

function row(failure_code: string, error_message: string) {
  return {
    id: `r-${failure_code}`, execution_id: `e-${failure_code}-0000`, agent_id: 'a-1', agent_name: 'Plant operator',
    failure_code, error_message, original_input: { message: 'hi' }, runtime_pool: 'default', is_pipeline: false,
    replay_count: 0, last_replay_at: null, replay_execution_id: null, resolved: false, created_at: new Date().toISOString(),
  };
}

// text a person reads, code and pre count as secondary detail
function readableText(root: HTMLElement): string {
  const clone = root.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('code, pre').forEach((el) => el.remove());
  return clone.textContent || '';
}

describe('DLQ page failure reasons', () => {
  it('names the failure in words and keeps the code as a reference', async () => {
    apiFetch.mockResolvedValue({
      data: [
        row('LLM_AUTH_ERROR', "Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error'}}"),
        row('INFRA_AUTH_ERROR', 'OAuth access token has been revoked.'),
        row('SOME_NEW_THING_FAILED', 'boom'),
      ],
    });
    const { container } = render(<DlqPage />);
    await waitFor(() => expect(screen.getAllByTestId('dlq-card')).toHaveLength(3));
    const reasons = screen.getAllByTestId('dlq-reason').map((el) => el.textContent);
    expect(reasons).toEqual(['AI provider sign-in failed', 'AI provider sign-in failed', 'Some new thing failed']);
    expect(screen.getAllByTestId('dlq-code').map((el) => el.textContent)).toContain('LLM_AUTH_ERROR');
    expect(readableText(container)).not.toMatch(RAW_CODE);
  });
});
