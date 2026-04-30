'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { useParams } from 'next/navigation';
import { motion } from 'framer-motion';
import { MessageSquare, Info } from 'lucide-react';
import ChatMessage from '@/components/chat/ChatMessage';
import ChatInput from '@/components/chat/ChatInput';
import AgentDetailSidebar from '@/components/chat/AgentDetailSidebar';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { useChatStore } from '@/stores/chatStore';
import { toastWarning } from '@/stores/toastStore';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { useIsMobile } from '@/hooks/useMediaQuery';

export default function AgentChatPage() {
  const params = useParams();
  const agentId = params.id as string;
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const isMobile = useIsMobile();
  const [showAgentInfo, setShowAgentInfo] = useState(false);

  const {
    messages,
    isStreaming,
    streamingBlocks,
    tokenCount,
    cost,
    confidenceScore,
    agentInfo,
    error,
    sendMessage,
    setAgentInfo,
    stopStreaming,
    clearChat,
  } = useChatStore();

  // Clear chat when switching between agents
  useEffect(() => {
    clearChat();
  }, [agentId]); // eslint-disable-line react-hooks/exhaustive-deps

  usePageTitle(agentInfo?.name ? `Chat - ${agentInfo.name}` : 'Chat');

  const { data: agentData, mutate: refetchAgent } = useApi<Record<string, unknown>>(
    agentId ? `/api/agents/${agentId}` : null,
  );

  useEffect(() => {
    if (agentData) {
      setAgentInfo({
        id: agentData.id as string,
        name: agentData.name as string,
        slug: agentData.slug as string,
        description: (agentData.description as string) || '',
        model_config: (agentData.model_config as { model: string; temperature: number; tools: string[] }) || {
          model: 'claude-sonnet-4-5-20250929',
          temperature: 0.7,
          tools: [],
        },
        category: agentData.category as string | undefined,
        version: agentData.version as string | undefined,
      });
    }
  }, [agentData, setAgentInfo]);

  useEffect(() => {
    return () => {
      useChatStore.getState().stopStreaming();
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingBlocks]);

  // Input variables for this agent (if defined by creator)
  const inputVars = (agentData?.model_config as Record<string, unknown>)?.input_variables as Array<{
    name: string; type: string; description: string; required: boolean; default?: string; options?: string[];
  }> | undefined;
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [showParams, setShowParams] = useState(true);

  const handleSend = useCallback(
    (message: string) => {
      // Validate required input variables
      if (inputVars && inputVars.length > 0 && messages.length === 0) {
        const missing = inputVars.filter(
          (v) => v.required && (!paramValues[v.name] || paramValues[v.name].trim() === '')
        );
        if (missing.length > 0) {
          toastWarning(
            'Missing required parameters',
            missing.map((m) => m.name).join(', '),
          );
          setShowParams(true);
          return;
        }
      }

      // Include input variables as context if any are filled
      const filledParams = Object.fromEntries(
        Object.entries(paramValues).filter(([, v]) => v.trim() !== '')
      );
      if (Object.keys(filledParams).length > 0) {
        const contextStr = Object.entries(filledParams)
          .map(([k, v]) => `${k}: ${v}`)
          .join('\n');
        sendMessage(agentId, `${message}\n\n[Input Parameters]\n${contextStr}`);
      } else {
        sendMessage(agentId, message);
      }
    },
    [agentId, sendMessage, paramValues, inputVars, messages.length],
  );

  const model = agentInfo?.model_config?.model || 'claude-sonnet-4-5-20250929';

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="-m-3 md:-m-6 flex h-[calc(100vh-3.5rem-1.75rem)]"
    >
      <div className="flex-1 flex flex-col min-w-0">
        <div className="h-14 border-b border-slate-800 flex items-center justify-between px-4 md:px-6 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 flex items-center justify-center">
              <MessageSquare className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">
                {agentInfo?.name || 'Loading...'}
              </h2>
              {agentInfo && (
                <p className="text-xs text-slate-500">{agentInfo.slug}</p>
              )}
            </div>
          </div>
          {isMobile && agentInfo && (
            <button
              onClick={() => setShowAgentInfo(true)}
              className="w-9 h-9 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
              title="Agent details"
            >
              <Info className="w-5 h-5" />
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 space-y-4">
          {messages.length === 0 && !isStreaming && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-16 h-16 rounded-2xl bg-cyan-500/10 flex items-center justify-center mb-4">
                <MessageSquare className="w-8 h-8 text-cyan-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-1">
                {agentInfo?.name || 'Agent Chat'}
              </h3>
              <p className="text-sm text-slate-500 max-w-md">
                {agentInfo?.description || 'Send a message to start the conversation.'}
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <ChatMessage key={msg.id} role={msg.role} blocks={msg.blocks} />
          ))}

          {isStreaming && (
            <ChatMessage
              role="assistant"
              blocks={streamingBlocks}
              isStreaming
            />
          )}

          {error && (
            <div className="flex justify-center">
              <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg px-4 py-2">
                {error}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Parameters Form (shown when agent defines input_variables) */}
        {inputVars && inputVars.length > 0 && showParams && messages.length === 0 && (
          <div className="border-t border-slate-800 bg-slate-900/50 px-4 py-3">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs font-semibold text-cyan-400">Input Parameters</h4>
              <button onClick={() => setShowParams(false)} className="text-[10px] text-slate-500 hover:text-slate-300">&times; Hide</button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {inputVars.map((v) => (
                <div key={v.name}>
                  <label className="block text-[10px] text-slate-400 mb-0.5">
                    {v.description || v.name}
                    {v.required && <span className="text-red-400 ml-0.5">*</span>}
                  </label>
                  {v.type === 'select' && v.options ? (
                    <select
                      value={paramValues[v.name] || (v.default as string) || ''}
                      onChange={(e) => setParamValues((prev) => ({ ...prev, [v.name]: e.target.value }))}
                      className="w-full px-2 py-1.5 text-xs bg-slate-800/50 border border-slate-700 rounded text-white focus:border-cyan-500 focus:outline-none"
                    >
                      <option value="">Select...</option>
                      {v.options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                  ) : v.type === 'boolean' ? (
                    <label className="flex items-center gap-2 text-xs text-slate-300">
                      <input
                        type="checkbox"
                        checked={paramValues[v.name] === 'true'}
                        onChange={(e) => setParamValues((prev) => ({ ...prev, [v.name]: e.target.checked ? 'true' : 'false' }))}
                        className="rounded border-slate-600"
                      />
                      {v.name}
                    </label>
                  ) : (
                    <input
                      type={v.type === 'number' ? 'number' : 'text'}
                      value={paramValues[v.name] || (v.default as string) || ''}
                      placeholder={v.type === 'connection_string' ? 'postgresql://user:pass@host:5432/db' : v.type === 'url' ? 'https://...' : `Enter ${v.name}`}
                      onChange={(e) => setParamValues((prev) => ({ ...prev, [v.name]: e.target.value }))}
                      className="w-full px-2 py-1.5 text-xs bg-slate-800/50 border border-slate-700 rounded text-white focus:border-cyan-500 focus:outline-none"
                    />
                  )}
                </div>
              ))}
            </div>
            <p className="text-[9px] text-slate-600 mt-1.5">These parameters are sent with your first message. Via SDK: <code className="bg-slate-800 px-1 rounded">forge.execute(id, msg, {'{'} context: {'{'} ... {'}'} {'}'})</code></p>
          </div>
        )}

        <ChatInput
          onSend={handleSend}
          onStop={stopStreaming}
          isStreaming={isStreaming}
          model={model}
          tokenCount={tokenCount}
          cost={cost}
          confidenceScore={confidenceScore}
        />
      </div>

      {/* Desktop: inline sidebar */}
      {!isMobile && agentInfo && (
        <AgentDetailSidebar
          agent={agentInfo}
          onClearChat={clearChat}
          onAgentUpdated={refetchAgent}
          isOOB={agentData?.agent_type === 'oob'}
        />
      )}

      {/* Mobile: sidebar in a modal */}
      {isMobile && agentInfo && (
        <ResponsiveModal
          open={showAgentInfo}
          onClose={() => setShowAgentInfo(false)}
          title="Agent Details"
        >
          <AgentDetailSidebar
            agent={agentInfo}
            onClearChat={clearChat}
            onAgentUpdated={refetchAgent}
            isOOB={agentData?.agent_type === 'oob'}
          />
        </ResponsiveModal>
      )}
    </motion.div>
  );
}
