import type { AutonomyMeta } from '@/lib/autonomy';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface ToolCallData {
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolResultData {
  name: string;
  result: string;
  is_error?: boolean;
  metadata?: Record<string, unknown>;
  autonomy?: AutonomyMeta;
}

// sent while an action waits on a person, before its result
export interface ToolAutonomyData {
  name: string;
  autonomy: AutonomyMeta;
}

export interface DoneData {
  execution_id?: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  duration_ms: number;
  model: string;
  effective_model?: string;
  requested_model?: string;
  fallback_reason?: string;
  confidence_score?: number;
  pipeline_status?: string;
  execution_path?: string[];
  failed_nodes?: string[];
  moderation_held?: boolean;
  moderation_review_id?: string;
}

export interface PipelineNodeStartData {
  node_id: string;
  tool_name: string;
  label?: string;
}

export interface PipelineNodeCompleteData {
  node_id: string;
  status: string;
  duration_ms: number;
  error?: string;
}

export interface ModerationData {
  source: string;
  outcome: string;
  categories?: string[];
  content?: string;
  message?: string;
  // set when outcome is held, the review the chat follows
  review_id?: string;
  timeout_minutes?: number;
  timeout_action?: 'reject' | 'release';
}

// an error that only repeats the reply already on screen, such as a moderation refusal
export function errorRepeatsReply(message: string, blocks: Array<{ type: string; content?: unknown }>): boolean {
  const said = blocks
    .filter((b) => b.type === 'text' && typeof b.content === 'string')
    .map((b) => b.content as string)
    .join('')
    .trim();
  const err = (message || '').trim();
  return !!err && !!said && said.includes(err);
}

interface StreamCallbacks {
  onToken: (text: string) => void;
  onModeration?: (data: ModerationData) => void;
  // the reply is withheld until the moderation check on it decides
  onReplyChecking?: (message: string) => void;
  onToolCall: (data: ToolCallData) => void;
  onToolResult: (data: ToolResultData) => void;
  onToolAutonomy?: (data: ToolAutonomyData) => void;
  onDone: (data: DoneData) => void;
  onError: (message: string) => void;
  onNodeStart?: (data: PipelineNodeStartData) => void;
  onNodeComplete?: (data: PipelineNodeCompleteData) => void;
}

export function connectToAgentStream(
  agentId: string,
  message: string,
  callbacks: StreamCallbacks,
  context?: Record<string, unknown>,
  conversationId?: string,
): AbortController {
  const controller = new AbortController();
  const token = localStorage.getItem('access_token');

  (async () => {
    try {
      const res = await fetch(`${API_URL}/api/agents/${agentId}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message,
          stream: true,
          source: 'chat',
          ...(context && Object.keys(context).length ? { context } : {}),
          // the server loads this thread's earlier turns as the agent's memory
          ...(conversationId ? { conversation_id: conversationId } : {}),
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        callbacks.onError(body?.error?.message || `HTTP ${res.status}`);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        callbacks.onError('No response body');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';
      // an event line and its data line can land in different chunks
      let currentEvent = '';
      let finished = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith('data: ') && currentEvent) {
            const data = JSON.parse(line.slice(6));
            switch (currentEvent) {
              case 'token':
                callbacks.onToken(data.text);
                break;
              case 'tool_call':
                callbacks.onToolCall(data as ToolCallData);
                break;
              case 'tool_result':
                callbacks.onToolResult(data as ToolResultData);
                break;
              case 'action_pending':
              case 'tool_autonomy':
                if (data && data.autonomy) callbacks.onToolAutonomy?.(data as ToolAutonomyData);
                break;
              case 'done':
                finished = true;
                callbacks.onDone(data as DoneData);
                break;
              case 'error':
                finished = true;
                callbacks.onError(data.message);
                break;
              case 'moderation':
                callbacks.onModeration?.(data as ModerationData);
                break;
              case 'reply_checking':
                callbacks.onReplyChecking?.(String(data?.message || ''));
                break;
              case 'moderation_block':
                callbacks.onModeration?.({ source: data.source || 'pre_llm', outcome: 'blocked', message: data.message } as ModerationData);
                break;
              case 'node_start':
                callbacks.onNodeStart?.(data as PipelineNodeStartData);
                break;
              case 'node_complete':
                callbacks.onNodeComplete?.(data as PipelineNodeCompleteData);
                break;
            }
            currentEvent = '';
          }
        }
      }
      if (!finished) callbacks.onError('The connection closed before the reply finished. Try sending again.');
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      callbacks.onError(err instanceof Error ? err.message : 'Stream failed');
    }
  })();

  return controller;
}
