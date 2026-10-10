import { describe, it, expect, vi, beforeEach } from 'vitest';

const calls: { agentId: string; message: string; conversationId?: string }[] = [];
const fetches: { path: string; body: any }[] = [];

vi.mock('@/lib/chat', async (orig) => {
  const actual: any = await orig();
  return {
    ...actual,
    connectToAgentStream: (agentId: string, message: string, cb: any, _ctx?: any, conversationId?: string) => {
      calls.push({ agentId, message, conversationId });
      setTimeout(() => {
        cb.onToken('hello');
        cb.onDone({ input_tokens: 1, output_tokens: 1, cost: 0, model: 'm', duration_ms: 5 });
      }, 0);
      return new AbortController();
    },
  };
});

vi.mock('@/lib/api-client', () => ({
  apiFetch: async (path: string, opts: any = {}) => {
    fetches.push({ path, body: opts.body ? JSON.parse(opts.body) : null });
    if (path === '/api/conversations') return { data: { id: 'conv-1' }, error: null };
    return { data: {}, error: null };
  },
}));

import { useChatStore } from '@/stores/chatStore';

const settle = () => new Promise((r) => setTimeout(r, 20));

describe('agent chat page threads', () => {
  beforeEach(() => {
    calls.length = 0;
    fetches.length = 0;
    useChatStore.getState().clearChat();
  });

  it('saves the chat as a thread and sends follow-ups with it', async () => {
    useChatStore.getState().sendMessage('a1', 'first question');
    await settle();
    useChatStore.getState().sendMessage('a1', 'and a follow-up');
    await settle();
    expect(fetches.filter((f) => f.path === '/api/conversations')).toHaveLength(1);
    expect(calls.map((c) => c.conversationId)).toEqual(['conv-1', 'conv-1']);
    const saved = fetches.filter((f) => f.path === '/api/conversations/conv-1/messages').map((f) => f.body.role);
    expect(saved).toEqual(['user', 'assistant', 'user', 'assistant']);
  });

  it('starts a new thread after New chat', async () => {
    useChatStore.getState().sendMessage('a1', 'one');
    await settle();
    useChatStore.getState().clearChat();
    expect(useChatStore.getState().conversationId).toBeNull();
    useChatStore.getState().sendMessage('a1', 'two');
    await settle();
    expect(fetches.filter((f) => f.path === '/api/conversations')).toHaveLength(2);
  });
});
