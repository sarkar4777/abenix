import { create } from 'zustand';
import {
  connectToAgentStream,
  type DoneData,
  type ToolCallData,
  type ToolResultData,
  type PipelineNodeStartData,
  type PipelineNodeCompleteData,
} from '@/lib/chat';

export interface TextBlock {
  type: 'text';
  content: string;
}

export interface ToolBlock {
  type: 'tool';
  name: string;
  arguments: Record<string, unknown>;
  result?: string;
  isError?: boolean;
}

export interface PipelineNodeBlock {
  type: 'pipeline_node';
  nodeId: string;
  toolName: string;
  status: 'running' | 'completed' | 'failed' | 'skipped';
  durationMs?: number;
}

export type ContentBlock = TextBlock | ToolBlock | PipelineNodeBlock;

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  blocks: ContentBlock[];
  timestamp: Date;
}

export interface AgentInfo {
  id: string;
  name: string;
  slug: string;
  description: string;
  system_prompt?: string;
  model_config: {
    model: string;
    temperature: number;
    tools: string[];
  };
  category?: string;
  version?: string;
}

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingBlocks: ContentBlock[];
  tokenCount: { input: number; output: number };
  cost: number;
  confidenceScore: number | null;
  agentInfo: AgentInfo | null;
  error: string | null;
  abortController: AbortController | null;

  sendMessage: (agentId: string, message: string) => void;
  setAgentInfo: (info: AgentInfo) => void;
  stopStreaming: () => void;
  clearChat: () => void;
}

let messageCounter = 0;

function uid(): string {
  messageCounter += 1;
  return `msg-${Date.now()}-${messageCounter}`;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  streamingBlocks: [],
  tokenCount: { input: 0, output: 0 },
  cost: 0,
  confidenceScore: null,
  agentInfo: null,
  error: null,
  abortController: null,

  sendMessage: (agentId: string, message: string) => {
    const userMsg: ChatMessage = {
      id: uid(),
      role: 'user',
      blocks: [{ type: 'text', content: message }],
      timestamp: new Date(),
    };

    set({
      messages: [...get().messages, userMsg],
      isStreaming: true,
      streamingBlocks: [],
      error: null,
    });

    const controller = connectToAgentStream(agentId, message, {
      onToken: (text: string) => {
        const blocks = [...get().streamingBlocks];
        const last = blocks[blocks.length - 1];
        if (last && last.type === 'text') {
          last.content += text;
          set({ streamingBlocks: [...blocks] });
        } else {
          blocks.push({ type: 'text', content: text });
          set({ streamingBlocks: blocks });
        }
      },

      onToolCall: (tc: ToolCallData) => {
        const blocks = [...get().streamingBlocks];
        blocks.push({
          type: 'tool',
          name: tc.name,
          arguments: tc.arguments,
        });
        set({ streamingBlocks: blocks });
      },

      onToolResult: (tr: ToolResultData) => {
        const blocks = [...get().streamingBlocks];
        for (let i = blocks.length - 1; i >= 0; i--) {
          const b = blocks[i];
          if (b.type === 'tool' && b.name === tr.name && b.result === undefined) {
            b.result = tr.result;
            break;
          }
        }
        set({ streamingBlocks: [...blocks] });
      },

      onNodeStart: (data: PipelineNodeStartData) => {
        const blocks = [...get().streamingBlocks];
        blocks.push({
          type: 'pipeline_node',
          nodeId: data.node_id,
          toolName: data.tool_name,
          status: 'running',
        });
        set({ streamingBlocks: blocks });
      },

      onNodeComplete: (data: PipelineNodeCompleteData) => {
        const blocks = [...get().streamingBlocks];
        for (let i = blocks.length - 1; i >= 0; i--) {
          const b = blocks[i];
          if (
            b.type === 'pipeline_node' &&
            b.nodeId === data.node_id &&
            b.status === 'running'
          ) {
            b.status = data.status as PipelineNodeBlock['status'];
            b.durationMs = data.duration_ms;
            break;
          }
        }
        set({ streamingBlocks: [...blocks] });
      },

      onDone: (data: DoneData) => {
        const assistantMsg: ChatMessage = {
          id: uid(),
          role: 'assistant',
          blocks: get().streamingBlocks,
          timestamp: new Date(),
        };
        set({
          messages: [...get().messages, assistantMsg],
          isStreaming: false,
          streamingBlocks: [],
          abortController: null,
          tokenCount: {
            input: get().tokenCount.input + data.input_tokens,
            output: get().tokenCount.output + data.output_tokens,
          },
          cost: get().cost + data.cost,
          confidenceScore: data.confidence_score ?? null,
        });
      },

      onError: (message: string) => {
        const blocks = get().streamingBlocks;
        if (blocks.length > 0) {
          const assistantMsg: ChatMessage = {
            id: uid(),
            role: 'assistant',
            blocks,
            timestamp: new Date(),
          };
          set((s) => ({ messages: [...s.messages, assistantMsg] }));
        }
        set({
          isStreaming: false,
          streamingBlocks: [],
          abortController: null,
          error: message,
        });
      },
    });

    set({ abortController: controller });
  },

  setAgentInfo: (info: AgentInfo) => set({ agentInfo: info }),

  stopStreaming: () => {
    const { abortController } = get();
    if (abortController) abortController.abort();
    const blocks = get().streamingBlocks;
    if (blocks.length > 0) {
      const assistantMsg: ChatMessage = {
        id: uid(),
        role: 'assistant',
        blocks,
        timestamp: new Date(),
      };
      set((s) => ({ messages: [...s.messages, assistantMsg] }));
    }
    set({ isStreaming: false, streamingBlocks: [], abortController: null });
  },

  clearChat: () =>
    set({
      messages: [],
      isStreaming: false,
      streamingBlocks: [],
      tokenCount: { input: 0, output: 0 },
      cost: 0,
      confidenceScore: null,
      error: null,
    }),
}));
