import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const sendMessage = vi.fn();

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'a1' }),
  usePathname: () => '/agents/a1/chat',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/hooks/useMediaQuery', () => ({ useIsMobile: () => false }));
vi.mock('@/hooks/usePageTitle', () => ({ usePageTitle: () => {} }));
vi.mock('@/components/chat/AgentDetailSidebar', () => ({ default: () => null }));
const agent = {
  id: 'a1',
  name: 'Price checker',
  slug: 'price',
  model_config: {
    model: 'm',
    tools: [],
    input_variables: [{ name: 'page_url', type: 'url', description: 'Page address', required: true }],
  },
};
vi.mock('@/hooks/useApi', () => ({
  useApi: (path: string | null) => ({
    data: path === '/api/agents/a1' ? agent : null,
    isLoading: false,
    error: null,
    meta: null,
    mutate: vi.fn(),
  }),
}));
const chatState = {
  messages: [],
  isStreaming: false,
  streamingBlocks: [],
  tokenCount: { input: 0, output: 0 },
  cost: 0,
  confidenceScore: null,
  agentInfo: null,
  error: null,
  sendMessage,
  setAgentInfo: vi.fn(),
  stopStreaming: vi.fn(),
  clearChat: vi.fn(),
  moderationNotice: null,
  replyStatus: null,
};
vi.mock('@/stores/chatStore', () => ({
  useChatStore: Object.assign((sel?: (s: typeof chatState) => unknown) => (sel ? sel(chatState) : chatState), {
    getState: () => chatState,
  }),
}));

import AgentChatPage from '@/app/(app)/agents/[id]/chat/page';

describe('agent chat with a required input', () => {
  beforeEach(() => {
    sendMessage.mockClear();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('points at the field inline, keeps the message and sends once it is filled', async () => {
    render(<AgentChatPage />);
    const input = screen.getByTestId('chat-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'Check this page' } });
    fireEvent.click(screen.getByTestId('chat-send'));

    const alert = await screen.findByTestId('chat-params-missing');
    expect(screen.getByText('Missing required parameters')).toBeInTheDocument();
    expect(alert).toHaveTextContent('page_url');
    const field = screen.getByTestId('chat-param-page_url');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(sendMessage).not.toHaveBeenCalled();
    expect(input.value).toBe('Check this page');
    await waitFor(() => expect(document.activeElement).toBe(field));

    fireEvent.change(field, { target: { value: 'https://example.com' } });
    expect(screen.queryByTestId('chat-params-missing')).toBeNull();
    fireEvent.click(screen.getByTestId('chat-send'));
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage.mock.calls[0][1]).toContain('Check this page');
    expect(sendMessage.mock.calls[0][2]).toEqual({ page_url: 'https://example.com' });
  });
});
