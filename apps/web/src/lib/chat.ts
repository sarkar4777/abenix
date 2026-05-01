const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface ToolCallData {
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolResultData {
  name: string;
  result: string;
}

export interface DoneData {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  duration_ms: number;
  model: string;
  confidence_score?: number;
  pipeline_status?: string;
  execution_path?: string[];
  failed_nodes?: string[];
}

export interface PipelineNodeStartData {
  node_id: string;
  tool_name: string;
}

export interface PipelineNodeCompleteData {
  node_id: string;
  status: string;
  duration_ms: number;
}

interface StreamCallbacks {
  onToken: (text: string) => void;
  onToolCall: (data: ToolCallData) => void;
  onToolResult: (data: ToolResultData) => void;
  onDone: (data: DoneData) => void;
  onError: (message: string) => void;
  onNodeStart?: (data: PipelineNodeStartData) => void;
  onNodeComplete?: (data: PipelineNodeCompleteData) => void;
}

export function connectToAgentStream(
  agentId: string,
  message: string,
  callbacks: StreamCallbacks,
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
        body: JSON.stringify({ message, stream: true }),
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

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent = '';
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
              case 'done':
                callbacks.onDone(data as DoneData);
                break;
              case 'error':
                callbacks.onError(data.message);
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
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      callbacks.onError(err instanceof Error ? err.message : 'Stream failed');
    }
  })();

  return controller;
}
