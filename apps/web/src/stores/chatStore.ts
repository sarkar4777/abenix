import { create } from 'zustand';
import {
  connectToAgentStream,
  errorRepeatsReply,
  type DoneData,
  type ToolCallData,
  type ToolResultData,
  type ToolAutonomyData,
  type PipelineNodeStartData,
  type PipelineNodeCompleteData,
  type ModerationData,
} from '@/lib/chat';
import { autonomyMetaOf, type AutonomyMeta } from '@/lib/autonomy';
import { apiFetch } from '@/lib/api-client';

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
  autonomy?: AutonomyMeta | null;
}

export interface PipelineNodeBlock {
  type: 'pipeline_node';
  nodeId: string;
  label?: string;
  toolName: string;
  status: 'running' | 'completed' | 'failed' | 'skipped';
  durationMs?: number;
  error?: string;
}

// content a moderation policy held for a person to review, shown as a live card
export interface HoldBlock {
  type: 'moderation_hold';
  review_id: string;
  source: string;
  // the sender's own words, shown while they wait
  text?: string;
  timeout_minutes?: number;
  timeout_action?: 'reject' | 'release';
}

export type ContentBlock = TextBlock | ToolBlock | PipelineNodeBlock | HoldBlock;

export function holdBlockFrom(data: ModerationData, text?: string): HoldBlock | null {
  if (data.outcome !== 'held' || !data.review_id) return null;
  return {
    type: 'moderation_hold',
    review_id: data.review_id,
    source: data.source,
    text,
    timeout_minutes: data.timeout_minutes,
    timeout_action: data.timeout_action,
  };
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  blocks: ContentBlock[];
  timestamp: Date;
  model?: string;
  requestedModel?: string;
  fallbackReason?: string;
  executionId?: string;
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
  // what the moderation policy did to the last exchange, shown above the composer
  moderationNotice: string | null;
  // set while the server holds the reply back for the moderation check
  replyStatus: string | null;
  abortController: AbortController | null;
  // the saved thread, so follow-ups carry the earlier turns and the chat shows in Chat history
  conversationId: string | null;

  sendMessage: (agentId: string, message: string, context?: Record<string, unknown>) => void;
  setAgentInfo: (info: AgentInfo) => void;
  stopStreaming: () => void;
  clearChat: () => void;
}

// a reply still shows when saving it fails, it is just not in the history
async function saveTurn(
  convId: string,
  role: 'user' | 'assistant',
  content: string,
  blocks: ContentBlock[],
  extra: Record<string, unknown> = {},
): Promise<void> {
  await apiFetch(`/api/conversations/${convId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ role, content, blocks, ...extra }),
    throwOnError: false,
    silent: true,
  });
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
  moderationNotice: null,
  replyStatus: null,
  abortController: null,
  conversationId: null,

  sendMessage: (agentId: string, message: string, context?: Record<string, unknown>) => {
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
      moderationNotice: null,
      replyStatus: null,
    });

    let held = false;
    void (async () => {
      let convId = get().conversationId;
      if (!convId) {
        const res = await apiFetch<{ id: string }>('/api/conversations', {
          method: 'POST',
          body: JSON.stringify({ title: message.slice(0, 80), agent_id: agentId }),
          throwOnError: false,
          silent: true,
        });
        convId = res.data?.id ?? null;
        if (convId) set({ conversationId: convId });
      }
      if (convId) await saveTurn(convId, 'user', message, [{ type: 'text', content: message }]);
      // stopped while the thread was being saved
      if (!get().isStreaming) return;
      const controller = connectToAgentStream(agentId, message, {
        onToken: (text: string) => {
          // A token event carrying no text used to push content: undefined,
          // which then crashed the whole chat page when it rendered.
          if (typeof text !== 'string' || text === '') return;
          // the hold card already says what happens next
          if (held) return;
          if (get().replyStatus) set({ replyStatus: null });
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
              b.isError = Boolean(tr.is_error);
              b.autonomy = autonomyMetaOf(tr) ?? b.autonomy;
              break;
            }
          }
          set({ streamingBlocks: [...blocks] });
        },

        onToolAutonomy: (ta: ToolAutonomyData) => {
          const blocks = [...get().streamingBlocks];
          for (let i = blocks.length - 1; i >= 0; i--) {
            const b = blocks[i];
            if (b.type === 'tool' && b.name === ta.name && b.result === undefined) {
              blocks[i] = { ...b, autonomy: ta.autonomy };
              break;
            }
          }
          set({ streamingBlocks: blocks });
        },

        onNodeStart: (data: PipelineNodeStartData) => {
          const blocks = [...get().streamingBlocks];
          blocks.push({
            type: 'pipeline_node',
            nodeId: data.node_id,
            label: data.label || undefined,
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
              if (data.error) b.error = data.error;
              break;
            }
          }
          set({ streamingBlocks: [...blocks] });
        },

        onReplyChecking: () => set({ replyStatus: 'Checking the reply before it is shown…' }),

        onModeration: (data) => {
          set({ replyStatus: null });
          const hold = holdBlockFrom(data, data.source === 'pre_llm' ? message : undefined);
          if (hold) {
            held = true;
            set({ streamingBlocks: [hold], moderationNotice: null });
            return;
          }
          if (held) return;
          const cats = data.categories && data.categories.length ? ` (${data.categories.join(', ')})` : '';
          if (data.source === 'post_llm' && data.outcome === 'blocked') {
            // the streamed text must not stay on screen
            set({ streamingBlocks: [{ type: 'text', content: data.content || data.message || 'Response blocked by moderation policy.' }] });
          } else if (data.source === 'post_llm' && typeof data.content === 'string') {
            const blocks: ContentBlock[] = get().streamingBlocks.filter((b) => b.type !== 'text');
            blocks.push({ type: 'text', content: data.content });
            set({ streamingBlocks: blocks });
          }
          set({ moderationNotice: `${data.message || `Moderation policy: ${data.outcome}`}${cats}` });
        },

        onDone: (data: DoneData) => {
          set({ replyStatus: null });
          const finalBlocks = get().streamingBlocks;
          if (convId) {
            const text = finalBlocks
              .filter((b): b is { type: 'text'; content: string } => b.type === 'text')
              .map((b) => b.content)
              .join('');
            void saveTurn(convId, 'assistant', text, finalBlocks, {
              input_tokens: data.input_tokens || 0,
              output_tokens: data.output_tokens || 0,
              cost: data.cost || 0,
              model_used: data.effective_model || data.model,
              duration_ms: data.duration_ms,
            });
          }
          const assistantMsg: ChatMessage = {
            id: uid(),
            role: 'assistant',
            blocks: get().streamingBlocks,
            timestamp: new Date(),
            model: data.effective_model || data.model,
            requestedModel: data.requested_model,
            fallbackReason: data.fallback_reason,
            executionId: data.execution_id,
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
          set({ replyStatus: null });
          if (held) {
            // the hold card already explains why the run stopped
            const hb = get().streamingBlocks;
            set((s) => ({
              messages: [...s.messages, { id: uid(), role: 'assistant', blocks: hb, timestamp: new Date() }],
              isStreaming: false,
              streamingBlocks: [],
              abortController: null,
            }));
            return;
          }
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
            error:
              (get().moderationNotice && /moderation policy/i.test(message)) || errorRepeatsReply(message, blocks)
                ? null
                : message,
          });
        },
      }, context, convId ?? undefined);

      set({ abortController: controller });
    })();
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
      conversationId: null,
    }),
}));
