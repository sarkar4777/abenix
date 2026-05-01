import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useChatStore } from '@/stores/chatStore';
import type { ChatMessage, AgentInfo } from '@/stores/chatStore';

describe('chatStore', () => {
  beforeEach(() => {
    useChatStore.getState().clearChat();
  });

  it('initializes with empty state', () => {
    const state = useChatStore.getState();
    expect(state.messages).toEqual([]);
    expect(state.isStreaming).toBe(false);
    expect(state.streamingBlocks).toEqual([]);
    expect(state.tokenCount).toEqual({ input: 0, output: 0 });
    expect(state.cost).toBe(0);
    expect(state.agentInfo).toBeNull();
    expect(state.error).toBeNull();
  });

  it('sets agent info', () => {
    const info: AgentInfo = {
      id: 'agent-1',
      name: 'Test Agent',
      slug: 'test-agent',
      description: 'A test agent',
      model_config: {
        model: 'claude-sonnet-4-5-20250929',
        temperature: 0.7,
        tools: ['calculator'],
      },
    };
    useChatStore.getState().setAgentInfo(info);
    expect(useChatStore.getState().agentInfo).toEqual(info);
  });

  it('clears chat resets messages and counters', () => {
    const info: AgentInfo = {
      id: 'agent-1',
      name: 'Test',
      slug: 'test',
      description: 'Test',
      model_config: { model: 'claude-sonnet-4-5-20250929', temperature: 0.7, tools: [] },
    };
    useChatStore.getState().setAgentInfo(info);
    useChatStore.getState().clearChat();

    const state = useChatStore.getState();
    expect(state.messages).toEqual([]);
    expect(state.isStreaming).toBe(false);
    expect(state.error).toBeNull();
    expect(state.cost).toBe(0);
    expect(state.agentInfo).toEqual(info);
  });

  it('sendMessage adds user message to state', () => {
    localStorage.setItem('access_token', 'test-token');

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn().mockResolvedValue({ done: true, value: undefined }),
        }),
      },
    });
    globalThis.fetch = mockFetch;

    useChatStore.getState().sendMessage('agent-1', 'Hello');

    const state = useChatStore.getState();
    expect(state.messages.length).toBe(1);
    expect(state.messages[0].role).toBe('user');
    expect(state.messages[0].blocks[0]).toEqual({
      type: 'text',
      content: 'Hello',
    });
    expect(state.isStreaming).toBe(true);
  });

  it('stopStreaming sets isStreaming to false', () => {
    localStorage.setItem('access_token', 'test-token');

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn().mockResolvedValue({ done: true, value: undefined }),
        }),
      },
    });
    globalThis.fetch = mockFetch;

    useChatStore.getState().sendMessage('agent-1', 'Test');
    useChatStore.getState().stopStreaming();

    expect(useChatStore.getState().isStreaming).toBe(false);
  });
});
