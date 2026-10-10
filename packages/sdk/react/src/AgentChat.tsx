/**
 * Abenix React SDK, a drop-in chat component for embedding agents.
 *
 *   import { AgentChat } from '@abenix/react';
 *
 *   <AgentChat apiKey="af_your_key_here" agentSlug="deep-research" baseUrl="https://api.abenix.dev" />
 *
 * Built on useAgentStream, which you can use directly for your own UI.
 */

import React, { useEffect, useRef, useState } from 'react';
import type { Abenix, ActingSubject } from '@abenix/sdk';
import { useAgentStream } from './useAgentStream';

export interface AgentChatProps {
  apiKey?: string;
  /** an existing SDK client instead of apiKey and baseUrl */
  client?: Abenix;
  agentSlug: string;
  baseUrl?: string;
  actAs?: ActingSubject;
  theme?: 'dark' | 'light';
  height?: string;
  placeholder?: string;
  onMessage?: (message: { role: string; content: string; executionId?: string }) => void;
  onError?: (error: string) => void;
  onCostUpdate?: (cost: { inputTokens: number; outputTokens: number; cost: number }) => void;
  className?: string;
}

export function AgentChat({
  apiKey,
  client,
  agentSlug,
  baseUrl = 'http://localhost:8000',
  actAs,
  theme = 'dark',
  height = '600px',
  placeholder = 'Ask the agent anything...',
  onMessage,
  onError,
  onCostUpdate,
  className = '',
}: AgentChatProps) {
  const chat = useAgentStream({ client, apiKey, baseUrl, agentSlug, actAs, onError, onCostUpdate });
  const [input, setInput] = useState('');
  const endRef = useRef<HTMLDivElement>(null);
  const reported = useRef(new Set<string>());

  useEffect(() => {
    // jsdom and some embeds have no scrollIntoView
    endRef.current?.scrollIntoView?.({ behavior: 'smooth' });
    for (const m of chat.messages) {
      if (m.isStreaming || reported.current.has(m.id)) continue;
      reported.current.add(m.id);
      onMessage?.({ role: m.role, content: m.content, executionId: m.executionId });
    }
  }, [chat.messages, onMessage]);

  const ready = chat.agentState === 'ready';
  const canSend = ready && !chat.isStreaming && !!input.trim();
  const submit = () => {
    if (!canSend) return;
    const text = input;
    setInput('');
    void chat.send(text);
  };

  const isDark = theme === 'dark';
  const muted = isDark ? '#94a3b8' : '#64748b';
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
      overflowWrap: 'anywhere' as const,
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
      overflowWrap: 'anywhere' as const,
    },
    notice: { fontSize: '13px', color: muted, textAlign: 'center' as const, margin: 'auto 0' },
    error: { fontSize: '12px', color: isDark ? '#fca5a5' : '#b91c1c', marginTop: '6px' },
    inputArea: {
      display: 'flex',
      gap: '8px',
      padding: '12px 16px',
      borderTop: `1px solid ${isDark ? '#1e293b' : '#e2e8f0'}`,
      backgroundColor: isDark ? '#0F172A' : '#f8fafc',
    },
    input: {
      flex: 1,
      minWidth: 0,
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
      opacity: chat.isStreaming || canSend ? 1 : 0.5,
    },
  };

  return (
    <div style={styles.container} className={className} data-testid="abenix-agent-chat">
      <div style={styles.messages} role="log" aria-live="polite">
        {chat.agentState === 'loading' && <p style={styles.notice}>Connecting to the agent...</p>}
        {chat.agentState === 'missing' && (
          <p style={styles.notice} role="alert">
            {chat.error || `The agent ${agentSlug} could not be found.`}
          </p>
        )}
        {ready && chat.messages.length === 0 && (
          <p style={styles.notice}>Ask {chat.agentName || 'the agent'} something to start.</p>
        )}
        {chat.messages.map((msg) => (
          <div
            key={msg.id}
            style={msg.role === 'user' ? styles.userMsg : styles.assistantMsg}
            data-role={msg.role}
            data-streaming={msg.isStreaming ? 'true' : 'false'}
          >
            {msg.content || (msg.isStreaming ? 'Thinking...' : '')}
            {msg.toolCalls.map((tc, i) => (
              <div key={i} style={{ fontSize: '12px', color: isDark ? '#06b6d4' : '#0284c7', marginTop: '4px' }}>
                Tool {tc.name}: {tc.status === 'running' ? 'running' : 'done'}
              </div>
            ))}
            {msg.error && (
              <div style={styles.error} role="alert">
                {msg.error}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <div style={styles.inputArea}>
        <input
          style={styles.input}
          value={input}
          aria-label="Message"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) submit();
          }}
          placeholder={ready ? placeholder : 'Waiting for the agent...'}
          disabled={!ready || chat.isStreaming}
        />
        {chat.isStreaming ? (
          <button type="button" style={styles.button} onClick={chat.stop}>
            Stop
          </button>
        ) : (
          <button type="button" style={styles.button} onClick={submit} disabled={!canSend}>
            Send
          </button>
        )}
      </div>
    </div>
  );
}

export default AgentChat;
