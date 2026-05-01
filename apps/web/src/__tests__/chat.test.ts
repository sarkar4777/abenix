import { describe, it, expect, beforeEach, vi } from 'vitest';
import { connectToAgentStream } from '@/lib/chat';
import type { DoneData, ToolCallData, ToolResultData } from '@/lib/chat';

function createMockSSEResponse(events: string[]): Response {
  const encoder = new TextEncoder();
  const chunks = events.map((e) => encoder.encode(e));
  let index = 0;

  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: () => {
          if (index < chunks.length) {
            const value = chunks[index];
            index++;
            return Promise.resolve({ done: false, value });
          }
          return Promise.resolve({ done: true, value: undefined });
        },
      }),
    },
  } as unknown as Response;
}

describe('connectToAgentStream', () => {
  beforeEach(() => {
    localStorage.setItem('access_token', 'test-token');
    vi.restoreAllMocks();
  });

  it('calls onToken for token events', async () => {
    const tokens: string[] = [];
    const mockResponse = createMockSSEResponse([
      'event: token\ndata: {"text":"Hello"}\n\n',
      'event: token\ndata: {"text":" World"}\n\n',
      'event: done\ndata: {"total_tokens":10,"input_tokens":5,"output_tokens":5,"cost":0.001,"duration_ms":100,"model":"test"}\n\n',
    ]);

    globalThis.fetch = vi.fn().mockResolvedValue(mockResponse);

    const done = new Promise<DoneData>((resolve) => {
      connectToAgentStream('agent-1', 'Hi', {
        onToken: (text) => tokens.push(text),
        onToolCall: () => {},
        onToolResult: () => {},
        onDone: resolve,
        onError: () => {},
      });
    });

    const doneData = await done;
    expect(tokens).toEqual(['Hello', ' World']);
    expect(doneData.total_tokens).toBe(10);
  });

  it('calls onToolCall for tool_call events', async () => {
    const toolCalls: ToolCallData[] = [];
    const mockResponse = createMockSSEResponse([
      'event: tool_call\ndata: {"name":"calculator","arguments":{"expression":"2+2"}}\n\n',
      'event: done\ndata: {"total_tokens":5,"input_tokens":3,"output_tokens":2,"cost":0.001,"duration_ms":50,"model":"test"}\n\n',
    ]);

    globalThis.fetch = vi.fn().mockResolvedValue(mockResponse);

    await new Promise<void>((resolve) => {
      connectToAgentStream('agent-1', 'Calculate', {
        onToken: () => {},
        onToolCall: (data) => toolCalls.push(data),
        onToolResult: () => {},
        onDone: () => resolve(),
        onError: () => {},
      });
    });

    expect(toolCalls).toHaveLength(1);
    expect(toolCalls[0].name).toBe('calculator');
  });

  it('calls onError for non-ok response', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ error: { message: 'Not authenticated' } }),
    });

    const errors: string[] = [];
    await new Promise<void>((resolve) => {
      connectToAgentStream('agent-1', 'Hi', {
        onToken: () => {},
        onToolCall: () => {},
        onToolResult: () => {},
        onDone: () => {},
        onError: (msg) => {
          errors.push(msg);
          resolve();
        },
      });
    });

    expect(errors[0]).toBe('Not authenticated');
  });

  it('sends auth header from localStorage', async () => {
    const mockResponse = createMockSSEResponse([
      'event: done\ndata: {"total_tokens":0,"input_tokens":0,"output_tokens":0,"cost":0,"duration_ms":0,"model":"test"}\n\n',
    ]);

    const mockFetch = vi.fn().mockResolvedValue(mockResponse);
    globalThis.fetch = mockFetch;

    await new Promise<void>((resolve) => {
      connectToAgentStream('agent-1', 'Hi', {
        onToken: () => {},
        onToolCall: () => {},
        onToolResult: () => {},
        onDone: () => resolve(),
        onError: () => {},
      });
    });

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/agents/agent-1/execute'),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer test-token',
        }),
      }),
    );
  });

  it('returns AbortController', () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: () => new Promise(() => {}),
        }),
      },
    });

    const controller = connectToAgentStream('agent-1', 'Hi', {
      onToken: () => {},
      onToolCall: () => {},
      onToolResult: () => {},
      onDone: () => {},
      onError: () => {},
    });

    expect(controller).toBeDefined();
    expect(typeof controller.abort).toBe('function');
  });
});
