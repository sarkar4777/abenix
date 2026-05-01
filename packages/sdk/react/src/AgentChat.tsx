/**
 * Abenix React SDK — drop-in chat component for embedding agents.
 *
 * Usage:
 *   import { AgentChat } from '@abenix/react';
 *
 *   <AgentChat
 *     apiKey="af_your_key_here"
 *     agentSlug="deep-research"
 *     baseUrl="https://api.abenix.dev"
 *     theme="dark"
 *   />
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';

interface AgentChatProps {
  apiKey: string;
  agentSlug: string;
  baseUrl?: string;
  theme?: 'dark' | 'light';
  height?: string;
  placeholder?: string;
  onMessage?: (message: { role: string; content: string }) => void;
  onError?: (error: string) => void;
  onCostUpdate?: (cost: { inputTokens: number; outputTokens: number; cost: number }) => void;
  className?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: Array<{ name: string; status: string }>;
  isStreaming?: boolean;
}

export function AgentChat({
  apiKey,
  agentSlug,
  baseUrl = 'http://localhost:8000',
  theme = 'dark',
  height = '600px',
  placeholder = 'Ask the agent anything...',
  onMessage,
  onError,
  onCostUpdate,
  className = '',
}: AgentChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [agentId, setAgentId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Resolve agent slug to ID
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${baseUrl}/api/agents`, {
          headers: { 'X-API-Key': apiKey },
        });
        const data = await res.json();
        const agent = data.data?.find((a: { slug: string; id: string }) => a.slug === agentSlug);
        if (agent) setAgentId(agent.id);
      } catch (e) {
        onError?.(`Failed to resolve agent: ${e}`);
      }
    })();
  }, [apiKey, agentSlug, baseUrl, onError]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    if (!input.trim() || !agentId || isStreaming) return;

    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
    };
    setMessages(prev => [...prev, userMsg]);
    onMessage?.({ role: 'user', content: input.trim() });
    setInput('');
    setIsStreaming(true);

    const assistantMsg: Message = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: '',
      toolCalls: [],
      isStreaming: true,
    };
    setMessages(prev => [...prev, assistantMsg]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${baseUrl}/api/agents/${agentId}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({ message: userMsg.content, stream: true }),
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = '';

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
            if (currentEvent === 'token') {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === 'assistant') {
                  last.content += data.text;
                }
                return updated;
              });
            } else if (currentEvent === 'tool_call') {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === 'assistant') {
                  last.toolCalls = [...(last.toolCalls || []), { name: data.name, status: 'running' }];
                }
                return updated;
              });
            } else if (currentEvent === 'done') {
              onCostUpdate?.({
                inputTokens: data.input_tokens,
                outputTokens: data.output_tokens,
                cost: data.cost,
              });
            } else if (currentEvent === 'error') {
              onError?.(data.message);
            }
            currentEvent = '';
          }
        }
      }

      setMessages(prev => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last.role === 'assistant') {
          last.isStreaming = false;
          onMessage?.({ role: 'assistant', content: last.content });
        }
        return updated;
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      onError?.(e instanceof Error ? e.message : 'Stream failed');
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [input, agentId, isStreaming, apiKey, baseUrl, onMessage, onError, onCostUpdate]);

  const isDark = theme === 'dark';

  const styles = {
    container: {
      display: 'flex',
      flexDirection: 'column' as const,
      height,
      backgroundColor: isDark ? '#0B0F19' : '#ffffff',
      borderRadius: '12px',
      border: `1px solid ${isDark ? '#334155' : '#e2e8f0'}`,
      overflow: 'hidden',
      fontFamily: 'Inter, system-ui, sans-serif',
    },
    messages: {
      flex: 1,
      overflowY: 'auto' as const,
      padding: '16px',
      display: 'flex',
      flexDirection: 'column' as const,
      gap: '12px',
    },
    userMsg: {
      alignSelf: 'flex-end' as const,
      backgroundColor: isDark ? 'rgba(6, 182, 212, 0.15)' : '#e0f2fe',
      color: isDark ? '#ffffff' : '#0f172a',
      padding: '10px 16px',
      borderRadius: '16px 16px 4px 16px',
      maxWidth: '70%',
      fontSize: '14px',
      lineHeight: '1.5',
    },
    assistantMsg: {
      alignSelf: 'flex-start' as const,
      backgroundColor: isDark ? 'rgba(30, 41, 59, 0.5)' : '#f8fafc',
      color: isDark ? '#e2e8f0' : '#1e293b',
      padding: '10px 16px',
      borderRadius: '16px 16px 16px 4px',
      maxWidth: '80%',
      fontSize: '14px',
      lineHeight: '1.5',
      whiteSpace: 'pre-wrap' as const,
    },
    inputArea: {
      display: 'flex',
      gap: '8px',
      padding: '12px 16px',
      borderTop: `1px solid ${isDark ? '#1e293b' : '#e2e8f0'}`,
      backgroundColor: isDark ? '#0F172A' : '#f8fafc',
    },
    input: {
      flex: 1,
      padding: '10px 16px',
      borderRadius: '8px',
      border: `1px solid ${isDark ? '#334155' : '#cbd5e1'}`,
      backgroundColor: isDark ? 'rgba(30, 41, 59, 0.5)' : '#ffffff',
      color: isDark ? '#e2e8f0' : '#1e293b',
      fontSize: '14px',
      outline: 'none',
    },
    button: {
      padding: '10px 20px',
      borderRadius: '8px',
      border: 'none',
      background: 'linear-gradient(135deg, #06b6d4, #a855f7)',
      color: '#ffffff',
      fontSize: '14px',
      fontWeight: '600' as const,
      cursor: 'pointer',
      opacity: isStreaming || !input.trim() ? 0.5 : 1,
    },
  };

  return (
    <div style={styles.container} className={className}>
      <div style={styles.messages}>
        {messages.map(msg => (
          <div key={msg.id} style={msg.role === 'user' ? styles.userMsg : styles.assistantMsg}>
            {msg.content}
            {msg.isStreaming && <span style={{ animation: 'blink 1s infinite' }}>▊</span>}
            {msg.toolCalls?.map((tc, i) => (
              <div key={i} style={{ fontSize: '12px', color: isDark ? '#06b6d4' : '#0284c7', marginTop: '4px' }}>
                🔧 {tc.name} — {tc.status}
              </div>
            ))}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div style={styles.inputArea}>
        <input
          style={styles.input}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
          placeholder={placeholder}
          disabled={isStreaming}
        />
        <button style={styles.button} onClick={sendMessage} disabled={isStreaming || !input.trim()}>
          {isStreaming ? 'Stop' : 'Send'}
        </button>
      </div>
    </div>
  );
}

export default AgentChat;
