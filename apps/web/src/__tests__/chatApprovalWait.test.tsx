import { render, screen } from '@testing-library/react';
import ChatMessage from '@/components/chat/ChatMessage';
import { deniedReason, withToolStatus } from '@/lib/chat';
import type { ContentBlock } from '@/stores/chatStore';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe('chat while a machine command waits (gap 5)', () => {
  const call: ContentBlock = { type: 'tool', name: 'device_command', arguments: { signal: 'Setpoint_kW', value: 30 } };

  it('marks the open call as waiting with its approval', () => {
    const out = withToolStatus([call], { name: 'device_command', status: 'waiting_approval', approval_id: 'ap-1' });
    expect((out[0] as any).waiting).toEqual({ approvalId: 'ap-1', message: null });
  });

  it('shows waiting for approval with a link to that approval', () => {
    const blocks = withToolStatus([call], { name: 'device_command', status: 'waiting_approval', approval_id: 'ap-1' });
    render(<ChatMessage role="assistant" blocks={blocks} isStreaming />);
    expect(screen.getByTestId('tool-call-waiting')).toHaveTextContent('waiting for approval');
    expect(screen.getByTestId('tool-call-open-approvals')).toHaveAttribute('href', '/approvals#ap-1');
  });

  it('says denied with the reason, not failed', () => {
    expect(deniedReason({ name: 'device_command', result: 'x', metadata: { status: 'denied', reason: 'audit only' } })).toBe('audit only');
    expect(deniedReason({ name: 'device_command', result: 'The command was not approved: UX audit test' })).toBe('UX audit test');
    expect(deniedReason({ name: 'device_command', result: 'Sent. The machine acknowledged it.' })).toBeNull();
    const blocks: ContentBlock[] = [{ ...call, result: 'The command was not approved', isError: false, denied: 'UX audit test' } as ContentBlock];
    render(<ChatMessage role="assistant" blocks={blocks} />);
    expect(screen.getByTestId('tool-call-denied')).toHaveTextContent('denied: UX audit test');
    expect(screen.queryByTestId('tool-call-failed')).toBeNull();
  });
});
