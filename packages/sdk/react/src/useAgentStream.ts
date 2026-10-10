import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Abenix, type ActingSubject } from '@abenix/sdk';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls: Array<{ name: string; status: 'running' | 'done' }>;
  isStreaming: boolean;
  executionId?: string;
  error?: string;
}

export interface UseAgentStreamOptions {
  /** an SDK client, or apiKey and baseUrl to build one */
  client?: Abenix;
  apiKey?: string;
  baseUrl?: string;
  agentSlug: string;
  actAs?: ActingSubject;
  onCostUpdate?: (cost: { inputTokens: number; outputTokens: number; cost: number }) => void;
  onError?: (error: string) => void;
}

export interface UseAgentStream {
  messages: ChatMessage[];
  /** resolving the agent: loading, ready, or missing when the slug is unknown or the key cannot see it */
  agentState: 'loading' | 'ready' | 'missing';
  agentName: string | null;
  isStreaming: boolean;
  error: string | null;
  send: (text: string) => Promise<void>;
  stop: () => void;
  reset: () => void;
}

let seq = 0;
const nextId = (p: string) => `${p}-${Date.now()}-${++seq}`;

/** Stream an agent's replies into a message list. Thin over @abenix/sdk. */
export function useAgentStream(opts: UseAgentStreamOptions): UseAgentStream {
  const { client, apiKey, baseUrl, agentSlug, actAs } = opts;
  const forge = useMemo(
    () => client ?? new Abenix({ apiKey: apiKey ?? '', baseUrl, timeout: 600_000 }),
    [client, apiKey, baseUrl],
  );
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [agentName, setAgentName] = useState<string | null>(null);
  const [agentState, setAgentState] = useState<'loading' | 'ready' | 'missing'>('loading');
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stopRef = useRef(false);
  const cbs = useRef({ onCostUpdate: opts.onCostUpdate, onError: opts.onError });
  cbs.current = { onCostUpdate: opts.onCostUpdate, onError: opts.onError };

  const fail = useCallback((msg: string) => {
    setError(msg);
    cbs.current.onError?.(msg);
  }, []);

  useEffect(() => {
    let live = true;
    setAgentState('loading');
    setAgentId(null);
    forge.agents
      .bySlug(agentSlug)
      .then((a) => {
        if (!live) return;
        if (a) {
          setAgentId(a.id);
          setAgentName(a.name);
          setAgentState('ready');
        } else {
          setAgentState('missing');
          fail(`No agent called ${agentSlug} is visible to this key.`);
        }
      })
      .catch((e: unknown) => {
        if (!live) return;
        setAgentState('missing');
        fail(e instanceof Error ? e.message : String(e));
      });
    return () => {
      live = false;
    };
  }, [forge, agentSlug, fail]);

  const patchLast = useCallback((fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => {
      if (!prev.length) return prev;
      const last = prev[prev.length - 1];
      if (last.role !== 'assistant') return prev;
      return [...prev.slice(0, -1), fn(last)];
    });
  }, []);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || !agentId || isStreaming) return;
      setError(null);
      stopRef.current = false;
      setIsStreaming(true);
      setMessages((prev) => [
        ...prev,
        { id: nextId('user'), role: 'user', content, toolCalls: [], isStreaming: false },
        { id: nextId('assistant'), role: 'assistant', content: '', toolCalls: [], isStreaming: true },
      ]);
      try {
        for await (const ev of forge.stream(agentId, content, { actAs })) {
          if (stopRef.current) break;
          if (ev.type === 'token' && ev.text) {
            const t = ev.text;
            patchLast((m) => ({ ...m, content: m.content + t }));
          } else if (ev.type === 'tool_call' && ev.name) {
            const n = ev.name;
            patchLast((m) => ({ ...m, toolCalls: [...m.toolCalls, { name: n, status: 'running' }] }));
          } else if (ev.type === 'tool_result' && ev.name) {
            const n = ev.name;
            patchLast((m) => ({
              ...m,
              toolCalls: m.toolCalls.map((tc) => (tc.name === n && tc.status === 'running' ? { ...tc, status: 'done' } : tc)),
            }));
          } else if (ev.type === 'done') {
            const id = ev.executionId;
            patchLast((m) => ({ ...m, executionId: id }));
            cbs.current.onCostUpdate?.({
              inputTokens: ev.inputTokens ?? 0,
              outputTokens: ev.outputTokens ?? 0,
              cost: ev.cost ?? 0,
            });
          } else if (ev.type === 'error') {
            const msg = ev.message || 'The agent stopped with an error.';
            patchLast((m) => ({ ...m, error: msg }));
            fail(msg);
          }
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'The stream failed.';
        patchLast((m) => ({ ...m, error: msg }));
        fail(msg);
      } finally {
        patchLast((m) => ({ ...m, isStreaming: false }));
        setIsStreaming(false);
      }
    },
    [agentId, isStreaming, forge, actAs, patchLast, fail],
  );

  const stop = useCallback(() => {
    stopRef.current = true;
  }, []);

  const reset = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return { messages, agentState, agentName, isStreaming, error, send, stop, reset };
}
