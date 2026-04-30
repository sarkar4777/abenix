'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot,
  Check,
  ChevronDown,
  MessageSquare,
  Paperclip,
  Pencil,
  Plus,
  Search,
  Share2,
  Trash2,
  X,
} from 'lucide-react';
import ChatMessage from '@/components/chat/ChatMessage';
import type { ChatMessage as ChatMsg, ContentBlock } from '@/stores/chatStore';
import { connectToAgentStream, type DoneData, type ToolCallData, type ToolResultData } from '@/lib/chat';
import { usePageTitle } from '@/hooks/usePageTitle';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ConversationSummary {
  id: string;
  title: string;
  agent_id: string | null;
  model_used: string | null;
  message_count: number;
  updated_at: string | null;
  is_shared: boolean;
}

interface AgentOption {
  id: string;
  name: string;
  slug: string;
  description: string;
  model_config_: Record<string, unknown>;
  category: string | null;
  icon_url: string | null;
}

interface SavedMessage {
  id: string;
  role: string;
  content: string;
  blocks: ContentBlock[] | null;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  model_used: string | null;
  duration_ms: number | null;
  attachments: FileAttachment[] | null;
  created_at: string | null;
}

interface FileAttachment {
  name: string;
  type: string;
  size: number;
  url?: string;
  preview?: string;
}

function getToken(): string | null {
  return typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(opts.headers || {}) },
  });
}

function timeLabel(dateStr: string | null): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}

let msgCounter = 0;
function uid(): string {
  msgCounter += 1;
  return `chat-${Date.now()}-${msgCounter}`;
}

export default function ChatPage() {
  usePageTitle('AI Chat');
  const router = useRouter();
  const searchParams = useSearchParams();

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingBlocks, setStreamingBlocks] = useState<ContentBlock[]>([]);
  const [tokenCount, setTokenCount] = useState({ input: 0, output: 0 });
  const [cost, setCost] = useState(0);
  const [chatError, setChatError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<AgentOption | null>(null);
  const [showAgentPicker, setShowAgentPicker] = useState(false);
  const agentPickerRef = useRef<HTMLDivElement>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [inputValue, setInputValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [attachments, setAttachments] = useState<FileAttachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [editingTitle, setEditingTitle] = useState<string | null>(null);
  const [editTitleValue, setEditTitleValue] = useState('');

  const [shareToast, setShareToast] = useState(false);

  const loadConversations = useCallback(async () => {
    try {
      const res = await apiFetch('/api/conversations?per_page=100');
      if (!res.ok) return;
      const json = await res.json();
      if (json.data) setConversations(json.data);
    } catch { /* network error */ }
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      const res = await apiFetch('/api/agents');
      if (!res.ok) return;
      const json = await res.json();
      if (json.data) setAgents(json.data);
    } catch { /* network error */ }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    loadConversations();
    loadAgents();
  }, [loadConversations, loadAgents]);

  const openConversation = useCallback(async (convId: string) => {
    try {
      const res = await apiFetch(`/api/conversations/${convId}`);
      if (!res.ok) return;
      const json = await res.json();
      if (!json.data) return;

      const conv = json.data;
      setActiveConvId(convId);
      setTokenCount({ input: 0, output: 0 });
      setCost(0);
      setChatError(null);

      const loaded: ChatMsg[] = (conv.messages || []).map((m: SavedMessage) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        blocks: m.blocks || [{ type: 'text' as const, content: m.content }],
        timestamp: m.created_at ? new Date(m.created_at) : new Date(),
      }));
      setMessages(loaded);

      let totalIn = 0;
      let totalOut = 0;
      let totalCost = 0;
      (conv.messages || []).forEach((m: SavedMessage) => {
        totalIn += m.input_tokens || 0;
        totalOut += m.output_tokens || 0;
        totalCost += m.cost || 0;
      });
      setTokenCount({ input: totalIn, output: totalOut });
      setCost(totalCost);

      if (conv.agent_id) {
        const agent = agents.find((a: AgentOption) => a.id === conv.agent_id);
        if (agent) setSelectedAgent(agent);
      }
    } catch { /* network error */ }
  }, [agents]);

  useEffect(() => {
    const convId = searchParams.get('id');
    if (convId && convId !== activeConvId) {
      openConversation(convId);
    }
  }, [searchParams, activeConvId, openConversation]);

  const createNewChat = useCallback(async () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }

    try {
      const body: Record<string, string> = { title: 'New Chat' };
      if (selectedAgent) body.agent_id = selectedAgent.id;
      const res = await apiFetch('/api/conversations', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (!res.ok) return;
      const json = await res.json();
      if (json.data) {
        setActiveConvId(json.data.id);
        setMessages([]);
        setStreamingBlocks([]);
        setIsStreaming(false);
        setTokenCount({ input: 0, output: 0 });
        setCost(0);
        setChatError(null);
        setAttachments([]);
        await loadConversations();
        router.replace(`/chat?id=${json.data.id}`, { scroll: false });
      }
    } catch { /* network error */ }
  }, [selectedAgent, loadConversations, router]);

  const deleteConversation = useCallback(async (convId: string) => {
    try {
      await apiFetch(`/api/conversations/${convId}`, { method: 'DELETE' });
      if (activeConvId === convId) {
        setActiveConvId(null);
        setMessages([]);
        router.replace('/chat', { scroll: false });
      }
      await loadConversations();
    } catch { /* network error */ }
  }, [activeConvId, loadConversations, router]);

  const saveTitle = useCallback(async (convId: string, title: string) => {
    try {
      await apiFetch(`/api/conversations/${convId}`, {
        method: 'PUT',
        body: JSON.stringify({ title }),
      });
      setEditingTitle(null);
      await loadConversations();
    } catch { /* network error */ }
  }, [loadConversations]);

  const shareConversation = useCallback(async () => {
    if (!activeConvId) return;
    try {
      const res = await apiFetch(`/api/conversations/${activeConvId}/share`, { method: 'POST' });
      if (!res.ok) return;
      const json = await res.json();
      if (json.data?.share_url) {
        const fullUrl = `${window.location.origin}${json.data.share_url}`;
        await navigator.clipboard.writeText(fullUrl);
        setShareToast(true);
        setTimeout(() => setShareToast(false), 2000);
      }
    } catch { /* network error */ }
  }, [activeConvId]);

  const saveMessageToServer = useCallback(async (
    convId: string,
    role: string,
    content: string,
    blocks: ContentBlock[] | null,
    opts: { input_tokens?: number; output_tokens?: number; cost?: number; model_used?: string; duration_ms?: number } = {},
  ) => {
    try {
      await apiFetch(`/api/conversations/${convId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ role, content, blocks, ...opts }),
      });
    } catch { /* network error */ }
  }, []);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return;

    const agentId = selectedAgent?.id;
    if (!agentId) {
      setChatError('Select an agent to start chatting');
      return;
    }

    let convId = activeConvId;
    if (!convId) {
      const body: Record<string, string> = { title: text.slice(0, 80) };
      if (selectedAgent) body.agent_id = selectedAgent.id;
      try {
        const res = await apiFetch('/api/conversations', {
          method: 'POST',
          body: JSON.stringify(body),
        });
        if (!res.ok) return;
        const json = await res.json();
        convId = json.data.id;
        setActiveConvId(convId);
        router.replace(`/chat?id=${convId}`, { scroll: false });
        loadConversations();
      } catch {
        return;
      }
    }

    const userMsg: ChatMsg = {
      id: uid(),
      role: 'user',
      blocks: [{ type: 'text', content: text }],
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);
    setStreamingBlocks([]);
    setChatError(null);

    saveMessageToServer(convId!, 'user', text, [{ type: 'text', content: text }]);

    let currentBlocks: ContentBlock[] = [];

    const controller = connectToAgentStream(agentId, text, {
      onToken: (tok: string) => {
        const blocks = [...currentBlocks];
        const last = blocks[blocks.length - 1];
        if (last && last.type === 'text') {
          last.content += tok;
          currentBlocks = [...blocks];
        } else {
          blocks.push({ type: 'text', content: tok });
          currentBlocks = blocks;
        }
        setStreamingBlocks([...currentBlocks]);
      },
      onToolCall: (tc: ToolCallData) => {
        currentBlocks = [...currentBlocks, { type: 'tool', name: tc.name, arguments: tc.arguments }];
        setStreamingBlocks([...currentBlocks]);
      },
      onToolResult: (tr: ToolResultData) => {
        const blocks = [...currentBlocks];
        for (let i = blocks.length - 1; i >= 0; i--) {
          const b = blocks[i];
          if (b.type === 'tool' && b.name === tr.name && b.result === undefined) {
            b.result = tr.result;
            break;
          }
        }
        currentBlocks = [...blocks];
        setStreamingBlocks([...currentBlocks]);
      },
      onDone: (data: DoneData) => {
        const assistantMsg: ChatMsg = {
          id: uid(),
          role: 'assistant',
          blocks: currentBlocks,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setIsStreaming(false);
        setStreamingBlocks([]);
        abortRef.current = null;
        setTokenCount((prev) => ({
          input: prev.input + data.input_tokens,
          output: prev.output + data.output_tokens,
        }));
        setCost((prev) => prev + data.cost);

        const plainText = currentBlocks
          .filter((b): b is { type: 'text'; content: string } => b.type === 'text')
          .map((b) => b.content)
          .join('');

        saveMessageToServer(convId!, 'assistant', plainText, currentBlocks, {
          input_tokens: data.input_tokens,
          output_tokens: data.output_tokens,
          cost: data.cost,
          model_used: data.model,
          duration_ms: data.duration_ms,
        });

        loadConversations();
      },
      onError: (errMsg: string) => {
        if (currentBlocks.length > 0) {
          const assistantMsg: ChatMsg = {
            id: uid(),
            role: 'assistant',
            blocks: currentBlocks,
            timestamp: new Date(),
          };
          setMessages((prev) => [...prev, assistantMsg]);
        }
        setIsStreaming(false);
        setStreamingBlocks([]);
        abortRef.current = null;
        setChatError(errMsg);
      },
    });

    abortRef.current = controller;
  }, [activeConvId, selectedAgent, isStreaming, saveMessageToServer, loadConversations, router]);

  const stopStreaming = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    if (streamingBlocks.length > 0) {
      const assistantMsg: ChatMsg = {
        id: uid(),
        role: 'assistant',
        blocks: streamingBlocks,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    }
    setIsStreaming(false);
    setStreamingBlocks([]);
    abortRef.current = null;
  }, [streamingBlocks]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingBlocks]);

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (agentPickerRef.current && !agentPickerRef.current.contains(e.target as Node)) {
        setShowAgentPicker(false);
      }
    }
    if (showAgentPicker) document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, [showAgentPicker]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputValue);
      setInputValue('');
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
    }
  }, [inputValue, sendMessage]);

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const newAttachments: FileAttachment[] = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const attachment: FileAttachment = {
        name: file.name,
        type: file.type,
        size: file.size,
      };
      if (file.type.startsWith('image/')) {
        attachment.preview = URL.createObjectURL(file);
      }
      newAttachments.push(attachment);
    }
    setAttachments((prev) => [...prev, ...newAttachments]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  const removeAttachment = useCallback((index: number) => {
    setAttachments((prev) => {
      const next = [...prev];
      if (next[index]?.preview) URL.revokeObjectURL(next[index].preview!);
      next.splice(index, 1);
      return next;
    });
  }, []);

  const filteredConversations = conversations.filter((c) =>
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const model = (selectedAgent?.model_config_?.model as string) || 'claude-sonnet-4-5-20250929';
  const totalTokens = tokenCount.input + tokenCount.output;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="-m-6 flex h-[calc(100vh-3.5rem-1.75rem)]"
    >
      {/* Left panel: conversation history */}
      <div className="w-72 bg-[#0c1322] border-r border-slate-800/50 flex flex-col shrink-0">
        <div className="p-3 border-b border-slate-800/50">
          <button
            onClick={createNewChat}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium shadow-lg shadow-cyan-500/20 hover:shadow-cyan-500/30 transition-shadow"
          >
            <Plus className="w-4 h-4" />
            New Chat
          </button>
        </div>

        <div className="px-3 py-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search conversations..."
              className="w-full pl-9 pr-3 py-2 bg-slate-800/30 border border-slate-700/30 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5">
          {filteredConversations.length === 0 && (
            <div className="px-3 py-8 text-center">
              <MessageSquare className="w-8 h-8 text-slate-700 mx-auto mb-2" />
              <p className="text-xs text-slate-600">No conversations yet</p>
            </div>
          )}
          {filteredConversations.map((conv) => (
            <div
              key={conv.id}
              className={`group flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
                activeConvId === conv.id
                  ? 'bg-cyan-500/10 border border-cyan-500/20'
                  : 'hover:bg-slate-800/30 border border-transparent'
              }`}
              onClick={() => {
                openConversation(conv.id);
                router.replace(`/chat?id=${conv.id}`, { scroll: false });
              }}
            >
              <MessageSquare className={`w-4 h-4 shrink-0 ${
                activeConvId === conv.id ? 'text-cyan-400' : 'text-slate-600'
              }`} />
              <div className="flex-1 min-w-0">
                {editingTitle === conv.id ? (
                  <input
                    autoFocus
                    value={editTitleValue}
                    onChange={(e) => setEditTitleValue(e.target.value)}
                    onBlur={() => saveTitle(conv.id, editTitleValue)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveTitle(conv.id, editTitleValue);
                      if (e.key === 'Escape') setEditingTitle(null);
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="w-full bg-transparent text-xs text-white focus:outline-none border-b border-cyan-500/50"
                  />
                ) : (
                  <p className={`text-xs font-medium truncate ${
                    activeConvId === conv.id ? 'text-white' : 'text-slate-300'
                  }`}>
                    {conv.title}
                  </p>
                )}
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[10px] text-slate-600">{timeLabel(conv.updated_at)}</span>
                  {conv.message_count > 0 && (
                    <span className="text-[10px] text-slate-600">{conv.message_count} msgs</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditingTitle(conv.id);
                    setEditTitleValue(conv.title);
                  }}
                  className="w-6 h-6 flex items-center justify-center rounded text-slate-500 hover:text-white hover:bg-slate-700/50"
                >
                  <Pencil className="w-3 h-3" />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteConversation(conv.id);
                  }}
                  className="w-6 h-6 flex items-center justify-center rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar with agent selector */}
        <div className="h-14 border-b border-slate-800/50 flex items-center justify-between px-4 shrink-0">
          <div className="relative" ref={agentPickerRef}>
            <button
              onClick={() => setShowAgentPicker(!showAgentPicker)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/50 hover:border-slate-600/50 transition-colors"
            >
              {selectedAgent ? (
                <>
                  <Bot className="w-4 h-4 text-cyan-400" />
                  <span className="text-sm text-white font-medium">{selectedAgent.name}</span>
                </>
              ) : (
                <>
                  <Bot className="w-4 h-4 text-slate-500" />
                  <span className="text-sm text-slate-400">Select Agent</span>
                </>
              )}
              <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
            </button>

            <AnimatePresence>
              {showAgentPicker && (
                <motion.div
                  initial={{ opacity: 0, y: -8, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -8, scale: 0.95 }}
                  transition={{ duration: 0.15 }}
                  className="absolute left-0 top-11 w-72 bg-slate-800 border border-slate-700/50 rounded-xl shadow-2xl shadow-black/50 overflow-hidden z-50"
                >
                  <div className="max-h-80 overflow-y-auto divide-y divide-slate-700/30">
                    {agents.map((agent) => (
                      <button
                        key={agent.id}
                        onClick={() => {
                          setSelectedAgent(agent);
                          setShowAgentPicker(false);
                        }}
                        className={`w-full flex items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-700/30 ${
                          selectedAgent?.id === agent.id ? 'bg-cyan-500/5' : ''
                        }`}
                      >
                        <div className="w-8 h-8 rounded-lg bg-cyan-500/10 flex items-center justify-center shrink-0 mt-0.5">
                          <Bot className="w-4 h-4 text-cyan-400" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-white truncate">{agent.name}</p>
                          <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{agent.description}</p>
                          {agent.category && (
                            <span className="inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400">
                              {agent.category}
                            </span>
                          )}
                        </div>
                        {selectedAgent?.id === agent.id && (
                          <Check className="w-4 h-4 text-cyan-400 shrink-0 mt-1" />
                        )}
                      </button>
                    ))}
                    {agents.length === 0 && (
                      <div className="px-4 py-6 text-center">
                        <p className="text-xs text-slate-500">No agents available</p>
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <div className="flex items-center gap-1.5">
            {model && (
              <span className="text-xs font-mono text-slate-600 bg-slate-800/50 px-2 py-1 rounded">
                {model}
              </span>
            )}
            {totalTokens > 0 && (
              <span className="text-xs text-slate-600 bg-slate-800/50 px-2 py-1 rounded">
                {totalTokens.toLocaleString()} tokens &middot; ${cost.toFixed(4)}
              </span>
            )}
            {activeConvId && (
              <button
                onClick={shareConversation}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-white hover:bg-slate-800/50 transition-colors"
                title="Share conversation"
              >
                <Share2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && !isStreaming && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-purple-500/10 flex items-center justify-center mb-4">
                <MessageSquare className="w-8 h-8 text-cyan-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-1">
                {selectedAgent ? selectedAgent.name : 'AI Chat'}
              </h3>
              <p className="text-sm text-slate-500 max-w-md">
                {selectedAgent
                  ? selectedAgent.description || 'Send a message to start the conversation.'
                  : 'Select an agent and start chatting.'}
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <ChatMessage key={msg.id} role={msg.role} blocks={msg.blocks} />
          ))}

          {isStreaming && (
            <ChatMessage role="assistant" blocks={streamingBlocks} isStreaming />
          )}

          {chatError && (
            <div className="flex justify-center">
              <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg px-4 py-2">
                {chatError}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-slate-800/50 p-4">
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {attachments.map((att, i) => (
                <div key={i} className="relative group">
                  {att.preview ? (
                    <div className="w-16 h-16 rounded-lg overflow-hidden border border-slate-700/50">
                      <img src={att.preview} alt={att.name} className="w-full h-full object-cover" />
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700/50">
                      <Paperclip className="w-3.5 h-3.5 text-slate-500" />
                      <span className="text-xs text-slate-300 max-w-[120px] truncate">{att.name}</span>
                    </div>
                  )}
                  <button
                    onClick={() => removeAttachment(i)}
                    className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-slate-700 border border-slate-600 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="w-3 h-3 text-slate-300" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-end gap-3">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,.pdf,.txt,.csv,.json,.md"
              className="hidden"
              onChange={handleFileSelect}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-10 h-10 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors shrink-0 mb-0.5"
              title="Attach file"
            >
              <Paperclip className="w-5 h-5" />
            </button>

            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => {
                setInputValue(e.target.value);
                handleInput();
              }}
              onKeyDown={handleKeyDown}
              placeholder={selectedAgent ? `Message ${selectedAgent.name}...` : 'Select an agent to chat...'}
              rows={1}
              disabled={!selectedAgent}
              className="flex-1 bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500/50 transition-colors disabled:opacity-50"
            />

            {isStreaming ? (
              <button
                onClick={stopStreaming}
                className="w-10 h-10 flex items-center justify-center rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors shrink-0 mb-0.5"
                title="Stop generating"
              >
                <div className="w-3.5 h-3.5 rounded-sm bg-red-400" />
              </button>
            ) : (
              <button
                onClick={() => {
                  sendMessage(inputValue);
                  setInputValue('');
                  if (textareaRef.current) textareaRef.current.style.height = 'auto';
                }}
                disabled={!inputValue.trim() || !selectedAgent}
                className="w-10 h-10 flex items-center justify-center rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 text-white shadow-lg shadow-cyan-500/25 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none transition-all shrink-0 mb-0.5"
                title="Send message"
              >
                <svg viewBox="0 0 24 24" fill="none" className="w-5 h-5">
                  <path d="M7 11L12 6L17 11M12 18V7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Share toast */}
      <AnimatePresence>
        {shareToast && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="fixed bottom-6 right-6 flex items-center gap-2 px-4 py-2.5 bg-emerald-500/20 border border-emerald-500/30 rounded-xl text-sm text-emerald-400 z-50"
          >
            <Check className="w-4 h-4" />
            Share link copied to clipboard
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
