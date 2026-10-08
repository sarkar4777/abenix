'use client';

import { explainRunError } from '@/lib/run-errors';
import Link from 'next/link';

import { useEffect, useRef, useCallback, useState, Suspense, lazy } from 'react';
import { useParams } from 'next/navigation';
import { motion } from 'framer-motion';
import { BookOpen, FlaskConical, MessageSquare, Info, Loader2, ShieldCheck, Zap } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';
import ChatMessage from '@/components/chat/ChatMessage';
import ChatInput from '@/components/chat/ChatInput';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { useChatStore } from '@/stores/chatStore';
import { toastWarning } from '@/stores/toastStore';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { useIsMobile } from '@/hooks/useMediaQuery';

// Lazy so the sidebar's per-agent fetches don't block first paint of the chat shell.
const AgentDetailSidebar = lazy(() => import('@/components/chat/AgentDetailSidebar'));

function SidebarSpinner() {
  return (
    <div className="flex items-center justify-center w-80 border-l border-slate-800 text-slate-500">
      <Loader2 className="w-5 h-5 animate-spin" />
    </div>
  );
}

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

  // Clear chat when switching between agents. Deferred until after first paint
  // so the chat shell renders immediately even on a cold agent fetch.
  useEffect(() => {
    const raf = requestAnimationFrame(() => clearChat());
    return () => cancelAnimationFrame(raf);
  }, [agentId]);

  usePageTitle(agentInfo?.name ? `Chat - ${agentInfo.name}` : 'Chat');

  const { data: agentData, mutate: refetchAgent } = useApi<Record<string, unknown>>(
    agentId ? `/api/agents/${agentId}` : null,
  );

  useEffect(() => {
    if (!agentData) return;
    // Push the store write out of the commit so the chat shell can paint first.
    const raf = requestAnimationFrame(() => {
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
    });
    return () => cancelAnimationFrame(raf);
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
  const moderationNotice = useChatStore((st) => st.moderationNotice);
  const replyStatus = useChatStore((st) => st.replyStatus);
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [showParams, setShowParams] = useState(true);

  // defaults are real values, not placeholders, so a required variable with a default passes the check
  useEffect(() => {
    if (!inputVars?.length) return;
    setParamValues((prev) => {
      const next = { ...prev };
      for (const v of inputVars) if (next[v.name] === undefined && v.default != null && v.default !== '') next[v.name] = String(v.default);
      return next;
    });
  }, [inputVars]);

  // ?prefill= from the Flight Recorder's Re-run button
  const [prefill, setPrefill] = useState<string | null>(null);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const q = new URLSearchParams(window.location.search).get('prefill');
    if (q) setPrefill(q);
  }, []);

  // ?published=1 from the builder, dropped from the URL so a reload doesn't show it again
  const [justPublished, setJustPublished] = useState(false);
  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.get('published') !== '1') return;
    setJustPublished(true);
    url.searchParams.delete('published');
    window.history.replaceState(null, '', url.pathname + url.search);
  }, []);

  const coerceParam = (type: string, raw: string): unknown => {
    if (type === 'number') { const n = Number(raw); return Number.isFinite(n) ? n : raw; }
    if (type === 'boolean') return raw === 'true' || raw === '1';
    const t = raw.trim();
    if (t.startsWith('{') || t.startsWith('[')) { try { return JSON.parse(t); } catch { return raw; } }
    return raw;
  };

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
          return false;
        }
      }

      // Include input variables as context if any are filled
      const filledParams = Object.fromEntries(
        Object.entries(paramValues).filter(([, v]) => v.trim() !== '')
      );
      if (Object.keys(filledParams).length > 0) {
        // typed context for the pipeline, plus the text block agents relied on before 2.5
        const context: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(filledParams)) {
          const decl = inputVars?.find((iv) => iv.name === k);
          context[k] = coerceParam(decl?.type || 'string', v);
        }
        const contextStr = Object.entries(filledParams)
          .map(([k, v]) => `${k}: ${v}`)
          .join('\n');
        sendMessage(agentId, `${message}\n\n[Input Parameters]\n${contextStr}`, context);
        setShowParams(false);
      } else {
        sendMessage(agentId, message);
      }
    },
    [agentId, sendMessage, paramValues, inputVars, messages.length],
  );

  const model = agentInfo?.model_config?.model || 'claude-sonnet-4-5-20250929';

  return (
    <motion.div
      initial={false}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.12 }}
      className="-m-3 md:-m-6 flex h-[calc(100vh-3.5rem-1.75rem)]"
    >
      <div className="flex-1 flex flex-col min-w-0">
        <div className="border-b border-slate-800 px-4 md:px-6 py-3 shrink-0">
          <PageHeader
            compact
            title={agentInfo?.name || 'Loading...'}
            icon={MessageSquare}
            purpose="Talk to this agent and watch which tools it uses to answer."
            meta={agentInfo ? <span className="break-all text-xs text-slate-500">{agentInfo.slug}</span> : undefined}
            primaryAction={{ label: 'Agent info', href: `/agents/${agentId}/info`, icon: Info }}
            extraActions={
              isMobile && agentInfo ? (
                <button
                  onClick={() => setShowAgentInfo(true)}
                  className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg border border-slate-700 px-3 text-sm text-slate-300 hover:bg-slate-800 hover:text-white"
                  title="Agent details"
                >
                  <Info className="w-4 h-4" /> Details
                </button>
              ) : undefined
            }
            steps={[
              'Fill any input parameters, then type a message.',
              'Each reply shows the tools it called. Open a run to see the full trace.',
            ]}
            docSlug="02-runtime/00-agent-execution"
            storageKey="agent-chat"
          />
        </div>

        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 space-y-4">
          {justPublished && (
            <NextSteps
              title="Published. Try it below, then"
              testId="agent-published-next"
              onDismiss={() => setJustPublished(false)}
              steps={[
                { id: 'evals', label: 'Add tests', hint: 'Create a test suite so changes never break it.', icon: FlaskConical, href: '/evals' },
                { id: 'knowledge', label: 'Give it knowledge', hint: 'Upload documents it can search.', icon: BookOpen, href: '/knowledge' },
                { id: 'autonomy', label: 'Enrol its actions', hint: 'Let it act alone once it earns trust.', icon: ShieldCheck, href: '/autonomy' },
                { id: 'schedule', label: 'Run it on a schedule', hint: 'Add a webhook or timed trigger.', icon: Zap, href: `/triggers?agent=${agentId}` },
              ]}
            />
          )}
          {messages.length === 0 && !isStreaming && (
            <div className={`flex flex-col items-center justify-center text-center ${justPublished ? 'py-8' : 'h-full'}`}>
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
            <ChatMessage
              key={msg.id}
              role={msg.role}
              blocks={msg.blocks}
              model={msg.model}
              requestedModel={msg.requestedModel}
              fallbackReason={msg.fallbackReason}
              executionId={msg.executionId}
              onHoldReleased={(view) => {
                // a reviewer released the message, it goes on to the agent once
                if (view.content && !useChatStore.getState().isStreaming) sendMessage(agentId, view.content);
              }}
            />
          ))}

          {isStreaming && (
            <ChatMessage
              role="assistant"
              blocks={streamingBlocks}
              isStreaming
              status={replyStatus}
            />
          )}

          {moderationNotice && (
            <div className="flex justify-center">
              <div className="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs rounded-lg px-4 py-2 flex items-center gap-2" data-testid="moderation-notice">
                <span className="uppercase tracking-wider text-[10px] font-semibold">Moderation</span>
                <span>{moderationNotice}</span>
                <Link href="/moderation" className="underline hover:text-white">policy</Link>
              </div>
            </div>
          )}
          {error && (
            <div className="flex justify-center">
              <div role="alert" data-testid="chat-error" className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg px-4 py-2 max-w-2xl">
                {(() => {
                  const known = explainRunError(error);
                  if (!known) return error;
                  return (
                    <>
                      <p className="text-red-300">{known.title}</p>
                      <p className="text-xs text-red-400/80 mt-0.5">{known.hint}</p>
                      <details className="mt-1 text-[11px] text-red-400/70">
                        <summary className="cursor-pointer">Details</summary>
                        <p className="mt-1 break-all font-mono">{error}</p>
                      </details>
                    </>
                  );
                })()}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Parameters Form (shown when agent defines input_variables) */}
        {inputVars && inputVars.length > 0 && !showParams && messages.length > 0 && (
          <div className="border-t border-slate-800 bg-slate-900/50 px-4 py-2 text-xs text-slate-400">
            <button type="button" onClick={() => setShowParams(true)} className="text-cyan-300 hover:underline" data-testid="chat-params-open">
              Change the input parameters
            </button>
            <span className="ml-2 text-slate-500">The next message runs with them.</span>
          </div>
        )}
        {inputVars && inputVars.length > 0 && showParams && (
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
                      aria-label={v.name}
                      data-testid={`chat-param-${v.name}`}
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
                        data-testid={`chat-param-${v.name}`}
                        checked={paramValues[v.name] === 'true'}
                        onChange={(e) => setParamValues((prev) => ({ ...prev, [v.name]: e.target.checked ? 'true' : 'false' }))}
                        className="rounded border-slate-600"
                      />
                      {v.name}
                    </label>
                  ) : v.type === 'string' || v.type === 'text' ? (
                    // pasted tables and lists keep their line breaks
                    <textarea
                      aria-label={v.name}
                      data-testid={`chat-param-${v.name}`}
                      rows={2}
                      value={paramValues[v.name] || (v.default as string) || ''}
                      placeholder={`Enter ${v.name}`}
                      onChange={(e) => setParamValues((prev) => ({ ...prev, [v.name]: e.target.value }))}
                      className="w-full px-2 py-1.5 text-xs bg-slate-800/50 border border-slate-700 rounded text-white focus:border-cyan-500 focus:outline-none resize-y"
                    />
                  ) : (
                    <input
                      aria-label={v.name}
                      data-testid={`chat-param-${v.name}`}
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
            <p className="text-[9px] text-slate-600 mt-1.5">These parameters are sent with each message. Via SDK: <code className="bg-slate-800 px-1 rounded">forge.execute(id, msg, {'{'} context: {'{'} ... {'}'} {'}'})</code></p>
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
          initialValue={prefill}
        />
      </div>

      {/* Desktop: inline sidebar */}
      {!isMobile && agentInfo && (
        <Suspense fallback={<SidebarSpinner />}>
          <AgentDetailSidebar
            agent={agentInfo}
            onClearChat={clearChat}
            onAgentUpdated={refetchAgent}
            isOOB={agentData?.agent_type === 'oob'}
          />
        </Suspense>
      )}

      {/* Mobile: sidebar in a modal */}
      {isMobile && agentInfo && (
        <ResponsiveModal
          open={showAgentInfo}
          onClose={() => setShowAgentInfo(false)}
          title="Agent Details"
        >
          <Suspense fallback={<SidebarSpinner />}>
            <AgentDetailSidebar
              agent={agentInfo}
              onClearChat={clearChat}
              onAgentUpdated={refetchAgent}
              isOOB={agentData?.agent_type === 'oob'}
            />
          </Suspense>
        </ResponsiveModal>
      )}
    </motion.div>
  );
}
