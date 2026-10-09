'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot,
  Brain,
  Check,
  ChevronDown,
  FileText,
  History,
  Loader2,
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
import ConfirmModal from '@/components/ui/ConfirmModal';
import { holdBlockFrom, type ChatMessage as ChatMsg, type ContentBlock } from '@/stores/chatStore';
import { connectToAgentStream, errorRepeatsReply, type DoneData, type ModerationData, type ToolAutonomyData, type ToolCallData, type ToolResultData } from '@/lib/chat';
import type { HoldView } from '@/components/moderation/HeldNotice';
import { autonomyMetaOf } from '@/lib/autonomy';
import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { usePageTitle } from '@/hooks/usePageTitle';
import { CostValue } from '@/components/shared/CostValue';
import PageHeader from '@/components/layout/PageHeader';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// seeded assistants that suit open-ended chat, first match wins
const DEFAULT_AGENT_SLUGS = ['code-assistant', 'research-assistant'];
const PICKER_LIMIT = 60;
const ATTACH_EXTENSIONS = ['.txt', '.md', '.csv', '.tsv', '.json', '.yaml', '.yml', '.xml', '.log', '.py', '.js', '.ts', '.sql', '.html'];
const ATTACH_MAX_CHARS = 20_000;

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
  model_config?: Record<string, unknown>;
  category: string | null;
  agent_type?: string;
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
  created_at: string | null;
}

interface TextAttachment {
  name: string;
  size: number;
  text: string;
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
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}

function friendlyError(raw: string): string {
  const msg = (raw || '').trim();
  if (!msg || /failed to fetch|networkerror|load failed|stream failed/i.test(msg)) {
    return 'Could not reach the server. Check your connection and send the message again.';
  }
  if (/^HTTP 401/.test(msg)) return 'Your session has expired. Sign in again to keep chatting.';
  if (/^HTTP 403/.test(msg)) return 'You do not have access to this agent. Pick another agent from the list at the top.';
  if (/^HTTP 404/.test(msg)) return 'This agent no longer exists. Pick another agent from the list at the top.';
  if (/^HTTP 429/.test(msg)) return 'You have hit a usage limit. Wait a minute and try again.';
  if (/^HTTP 5\d\d/.test(msg)) return 'The agent ran into a problem on the server. Try again, or pick another agent.';
  return msg;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.round(bytes / 1024)} KB`;
}

function isPipeline(agent: AgentOption | null): boolean {
  return (agent?.model_config as { mode?: string } | undefined)?.mode === 'pipeline';
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
  // set while the server holds the reply back for the moderation check
  const [replyStatus, setReplyStatus] = useState<string | null>(null);
  const [tokenCount, setTokenCount] = useState({ input: 0, output: 0 });
  const [cost, setCost] = useState(0);
  const [chatError, setChatError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // a URL id the page already handled, so a lagging ?id= never reopens or reloads it
  const ignoreUrlIdRef = useRef<string | null>(null);

  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [selectedAgent, setSelectedAgent] = useState<AgentOption | null>(null);
  const [convAgentId, setConvAgentId] = useState<string | null>(null);
  const [showAgentPicker, setShowAgentPicker] = useState(false);
  const [agentQuery, setAgentQuery] = useState('');
  const agentPickerRef = useRef<HTMLDivElement>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [inputValue, setInputValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [attachments, setAttachments] = useState<TextAttachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [editingTitle, setEditingTitle] = useState<string | null>(null);
  const [editTitleValue, setEditTitleValue] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [shareToast, setShareToast] = useState(false);

  const loadConversations = useCallback(async () => {
    try {
      const res = await apiFetch('/api/conversations?per_page=100');
      if (!res.ok) return;
      const json = await res.json();
      if (json.data) setConversations(json.data);
    } catch { /* list refresh is best effort */ }
  }, []);

  const loadAgents = useCallback(async () => {
    setAgentsLoading(true);
    try {
      const { agents: rows } = await fetchAllAgents<AgentOption>();
      setAgents(rows.sort((a, b) => a.name.localeCompare(b.name)));
    } catch { /* empty list shows its own message */ }
    setAgentsLoading(false);
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    loadConversations();
    loadAgents();
  }, [loadConversations, loadAgents]);

  // an opened thread brings back its own agent, otherwise a general assistant
  useEffect(() => {
    if (agents.length === 0) return;
    if (convAgentId) {
      const own = agents.find((a) => a.id === convAgentId);
      if (own) {
        setSelectedAgent(own);
        setConvAgentId(null);
        return;
      }
    }
    if (selectedAgent) return;
    const preferred = DEFAULT_AGENT_SLUGS.map((s) => agents.find((a) => a.slug === s)).find(Boolean)
      || agents.find((a) => a.agent_type === 'oob' && !isPipeline(a))
      || agents[0];
    if (preferred) setSelectedAgent(preferred);
  }, [agents, convAgentId, selectedAgent]);

  const openConversation = useCallback(async (convId: string) => {
    ignoreUrlIdRef.current = null;
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    setStreamingBlocks([]);
    try {
      const res = await apiFetch(`/api/conversations/${convId}`);
      if (!res.ok) {
        setChatError('That conversation could not be opened. It may have been deleted.');
        return;
      }
      const json = await res.json();
      if (!json.data) return;
      const conv = json.data;
      setActiveConvId(convId);
      setChatError(null);
      setMessages((conv.messages || []).map((m: SavedMessage) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        blocks: m.blocks || [{ type: 'text' as const, content: m.content }],
        timestamp: m.created_at ? new Date(m.created_at) : new Date(),
        model: m.model_used || undefined,
      })));
      let totalIn = 0;
      let totalOut = 0;
      let totalCost = 0;
      (conv.messages || []).forEach((m: SavedMessage) => {
        totalIn += m.input_tokens || 0;
        totalOut += m.output_tokens || 0;
        totalCost += Number(m.cost) || 0;
      });
      setTokenCount({ input: totalIn, output: totalOut });
      setCost(totalCost);
      if (conv.agent_id) setConvAgentId(conv.agent_id);
    } catch {
      setChatError('Could not reach the server. Check your connection and try again.');
    }
  }, []);

  useEffect(() => {
    const convId = searchParams.get('id');
    if (convId && convId !== activeConvId && convId !== ignoreUrlIdRef.current) openConversation(convId);
  }, [searchParams, activeConvId, openConversation]);

  const createNewChat = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    // the thread is created on the first message so empty chats do not pile up
    setActiveConvId(null);
    setMessages([]);
    setStreamingBlocks([]);
    setIsStreaming(false);
    setTokenCount({ input: 0, output: 0 });
    setCost(0);
    setChatError(null);
    setAttachments([]);
    setAttachError(null);
    setConvAgentId(null);
    ignoreUrlIdRef.current = activeConvId;
    setHistoryOpen(false);
    router.replace('/chat', { scroll: false });
    textareaRef.current?.focus();
  }, [router, activeConvId]);

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const res = await apiFetch(`/api/conversations/${deleteTarget.id}`, { method: 'DELETE' });
      if (!res.ok) {
        setChatError('The conversation could not be deleted. Try again.');
      } else if (activeConvId === deleteTarget.id) {
        createNewChat();
      }
      await loadConversations();
    } catch {
      setChatError('Could not reach the server, the conversation was not deleted.');
    }
    setDeleting(false);
    setDeleteTarget(null);
  }, [deleteTarget, activeConvId, createNewChat, loadConversations]);

  const saveTitle = useCallback(async (convId: string, title: string) => {
    const clean = title.trim();
    setEditingTitle(null);
    if (!clean) return;
    try {
      await apiFetch(`/api/conversations/${convId}`, { method: 'PUT', body: JSON.stringify({ title: clean }) });
      await loadConversations();
    } catch { /* title stays as it was */ }
  }, [loadConversations]);

  const shareConversation = useCallback(async () => {
    if (!activeConvId) return;
    try {
      const res = await apiFetch(`/api/conversations/${activeConvId}/share`, { method: 'POST' });
      if (!res.ok) {
        setChatError('A share link could not be created. Try again.');
        return;
      }
      const json = await res.json();
      if (json.data?.share_url) {
        await navigator.clipboard.writeText(`${window.location.origin}${json.data.share_url}`);
        setShareToast(true);
        setTimeout(() => setShareToast(false), 2000);
      }
    } catch {
      setChatError('The share link could not be copied to your clipboard.');
    }
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
    } catch { /* the reply still shows, it is just not stored */ }
  }, []);

  // resume sends a message a reviewer released, it is already in the thread
  const sendMessage = useCallback(async (text: string, resume = false) => {
    if (!text.trim() || isStreaming) return;
    const agentId = selectedAgent?.id;
    if (!agentId) {
      setChatError('Pick an agent from the list at the top before sending a message.');
      return;
    }
    setChatError(null);

    let convId = activeConvId;
    if (!convId && resume) return;
    if (!convId) {
      try {
        const res = await apiFetch('/api/conversations', {
          method: 'POST',
          body: JSON.stringify({ title: text.slice(0, 80), agent_id: agentId }),
        });
        if (!res.ok) {
          setChatError('The conversation could not be started. Try sending again.');
          return;
        }
        const json = await res.json();
        convId = json.data.id as string;
        ignoreUrlIdRef.current = convId;
        setActiveConvId(convId);
        router.replace(`/chat?id=${convId}`, { scroll: false });
        loadConversations();
      } catch {
        setChatError('Could not reach the server. Check your connection and send the message again.');
        return;
      }
    }

    // text files go to the agent inside the message, the bubble lists their names
    const files = resume ? [] : attachments;
    const outgoing = files.length
      ? `${text}\n\n${files.map((f) => `[Attached file: ${f.name}]\n\`\`\`\n${f.text}\n\`\`\``).join('\n\n')}`
      : text;
    const shown = files.length
      ? `${text}\n\n_Attached: ${files.map((f) => f.name).join(', ')}_`
      : text;
    const userBlocks: ContentBlock[] = [{ type: 'text', content: shown }];
    const userMsgId = uid();
    if (!resume) {
      setMessages((prev) => [...prev, { id: userMsgId, role: 'user', blocks: userBlocks, timestamp: new Date() }]);
      setAttachments([]);
      setAttachError(null);
    }
    setIsStreaming(true);
    setStreamingBlocks([]);
    setReplyStatus(null);

    if (!resume) await saveMessageToServer(convId, 'user', outgoing, userBlocks);

    let currentBlocks: ContentBlock[] = [];
    const threadId = convId;
    // set when moderation held the message or the reply for a reviewer
    let heldSource: string | null = null;

    const controller = connectToAgentStream(agentId, outgoing, {
      onToken: (tok: string) => {
        if (heldSource) return;
        setReplyStatus(null);
        const blocks = [...currentBlocks];
        const last = blocks[blocks.length - 1];
        if (last && last.type === 'text') {
          blocks[blocks.length - 1] = { ...last, content: last.content + tok };
        } else {
          blocks.push({ type: 'text', content: tok });
        }
        currentBlocks = blocks;
        setStreamingBlocks(blocks);
      },
      onToolCall: (tc: ToolCallData) => {
        currentBlocks = [...currentBlocks, { type: 'tool', name: tc.name, arguments: tc.arguments }];
        setStreamingBlocks(currentBlocks);
      },
      onToolResult: (tr: ToolResultData) => {
        const blocks = [...currentBlocks];
        for (let i = blocks.length - 1; i >= 0; i--) {
          const b = blocks[i];
          if (b.type === 'tool' && b.name === tr.name && b.result === undefined) {
            blocks[i] = { ...b, result: tr.result, autonomy: autonomyMetaOf(tr) ?? b.autonomy };
            break;
          }
        }
        currentBlocks = blocks;
        setStreamingBlocks(blocks);
      },
      onToolAutonomy: (ta: ToolAutonomyData) => {
        const blocks = [...currentBlocks];
        for (let i = blocks.length - 1; i >= 0; i--) {
          const b = blocks[i];
          if (b.type === 'tool' && b.name === ta.name && b.result === undefined) {
            blocks[i] = { ...b, autonomy: ta.autonomy };
            break;
          }
        }
        currentBlocks = blocks;
        setStreamingBlocks(blocks);
      },
      onReplyChecking: () => setReplyStatus('Checking the reply before it is shown…'),
      onModeration: (data: ModerationData) => {
        setReplyStatus(null);
        const hold = holdBlockFrom(data, data.source === 'pre_llm' ? shown : undefined);
        if (hold) {
          heldSource = data.source;
          if (data.source === 'pre_llm' && !resume) {
            // the server swapped the stored message for this card too
            setMessages((prev) => prev.map((m) => (m.id === userMsgId ? { ...m, blocks: [hold] } : m)));
            currentBlocks = [];
          } else {
            currentBlocks = [hold];
          }
          setStreamingBlocks(currentBlocks);
          return;
        }
        if (heldSource) return;
        // a post answer redaction or block replaces the text already streamed
        if (data.source === 'post_llm' && typeof data.content === 'string') {
          currentBlocks = [...currentBlocks.filter((b) => b.type !== 'text'), { type: 'text', content: data.content }];
          setStreamingBlocks(currentBlocks);
        }
      },
      onDone: (data: DoneData) => {
        setReplyStatus(null);
        const usedModel = data.effective_model || data.model;
        if (heldSource) {
          if (currentBlocks.length) {
            setMessages((prev) => [...prev, { id: uid(), role: 'assistant', blocks: currentBlocks, timestamp: new Date() }]);
          }
          setIsStreaming(false);
          setStreamingBlocks([]);
          abortRef.current = null;
          // the server stores the hold card and retitles the thread a moment after done
          setTimeout(loadConversations, 1500);
          return;
        }
        setMessages((prev) => [...prev, {
          id: uid(),
          role: 'assistant',
          blocks: currentBlocks,
          timestamp: new Date(),
          model: usedModel,
          requestedModel: data.requested_model,
          fallbackReason: data.fallback_reason,
          executionId: data.execution_id,
        }]);
        setIsStreaming(false);
        setStreamingBlocks([]);
        abortRef.current = null;
        setTokenCount((prev) => ({
          input: prev.input + (data.input_tokens || 0),
          output: prev.output + (data.output_tokens || 0),
        }));
        setCost((prev) => prev + (data.cost || 0));
        const plainText = currentBlocks
          .filter((b): b is { type: 'text'; content: string } => b.type === 'text')
          .map((b) => b.content)
          .join('');
        saveMessageToServer(threadId, 'assistant', plainText, currentBlocks, {
          input_tokens: data.input_tokens || 0,
          output_tokens: data.output_tokens || 0,
          cost: data.cost || 0,
          model_used: usedModel,
          duration_ms: data.duration_ms,
        }).then(loadConversations);
      },
      onError: (errMsg: string) => {
        setReplyStatus(null);
        if (heldSource) {
          // a held run ends as failed on the queue path, the hold card already explains it
          if (currentBlocks.length) {
            setMessages((prev) => [...prev, { id: uid(), role: 'assistant', blocks: currentBlocks, timestamp: new Date() }]);
          }
          setIsStreaming(false);
          setStreamingBlocks([]);
          abortRef.current = null;
          setTimeout(loadConversations, 1500);
          return;
        }
        if (currentBlocks.length > 0) {
          setMessages((prev) => [...prev, { id: uid(), role: 'assistant', blocks: currentBlocks, timestamp: new Date() }]);
        }
        setIsStreaming(false);
        setStreamingBlocks([]);
        abortRef.current = null;
        // a refusal already shown as the reply does not need a second red copy
        setChatError(errorRepeatsReply(errMsg, currentBlocks) ? null : friendlyError(errMsg));
      },
    }, undefined, convId);

    abortRef.current = controller;
  }, [activeConvId, selectedAgent, isStreaming, attachments, saveMessageToServer, loadConversations, router]);

  // released messages wait here until the current reply finishes
  const [resumeQueue, setResumeQueue] = useState<string[]>([]);
  const onHoldReleased = useCallback((view: HoldView) => {
    if (!view.content || !view.conversation_id || view.conversation_id !== activeConvId) return;
    const text = view.content;
    setResumeQueue((q) => (q.includes(text) ? q : [...q, text]));
  }, [activeConvId]);
  useEffect(() => {
    if (isStreaming || !resumeQueue.length || !selectedAgent) return;
    const [next, ...rest] = resumeQueue;
    setResumeQueue(rest);
    sendMessage(next, true);
  }, [isStreaming, resumeQueue, selectedAgent, sendMessage]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (streamingBlocks.length > 0) {
      setMessages((prev) => [...prev, { id: uid(), role: 'assistant', blocks: streamingBlocks, timestamp: new Date() }]);
      const partial = streamingBlocks
        .filter((b): b is { type: 'text'; content: string } => b.type === 'text')
        .map((b) => b.content)
        .join('');
      // keep the partial reply so the next turn still has it in memory
      if (activeConvId && partial) saveMessageToServer(activeConvId, 'assistant', partial, streamingBlocks);
    }
    setIsStreaming(false);
    setStreamingBlocks([]);
  }, [streamingBlocks, activeConvId, saveMessageToServer]);

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

  const submit = useCallback(() => {
    if (!inputValue.trim() || isStreaming || !selectedAgent) return;
    sendMessage(inputValue);
    setInputValue('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }, [inputValue, isStreaming, selectedAgent, sendMessage]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }, [submit]);

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (!files.length) return;
    let used = attachments.reduce((n, a) => n + a.text.length, 0);
    const added: TextAttachment[] = [];
    const problems: string[] = [];
    for (const file of files) {
      const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : '';
      if (!ATTACH_EXTENSIONS.includes(ext)) {
        problems.push(`${file.name} is not a text file. Only text files such as .txt, .md, .csv or .json can be attached here.`);
        continue;
      }
      const text = await file.text().catch(() => null);
      if (text === null) {
        problems.push(`${file.name} could not be read.`);
        continue;
      }
      if (used + text.length > ATTACH_MAX_CHARS) {
        problems.push(`${file.name} is too long. Attachments can add up to ${ATTACH_MAX_CHARS.toLocaleString()} characters per message.`);
        continue;
      }
      used += text.length;
      added.push({ name: file.name, size: file.size, text });
    }
    if (added.length) setAttachments((prev) => [...prev, ...added]);
    setAttachError(problems.length ? problems.join(' ') : null);
  }, [attachments]);

  const removeAttachment = useCallback((index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const filteredConversations = conversations.filter((c) =>
    c.title.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const matchingAgents = useMemo(() => {
    const q = agentQuery.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter((a) =>
      `${a.name} ${a.slug} ${a.description || ''} ${a.category || ''}`.toLowerCase().includes(q),
    );
  }, [agents, agentQuery]);

  const lastModel = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant' && messages[i].model) return messages[i].model;
    }
    return undefined;
  }, [messages]);

  const totalTokens = tokenCount.input + tokenCount.output;
  const pipelineAgent = isPipeline(selectedAgent);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="-m-3 md:-m-6 flex h-[calc(100vh-3.5rem-1.75rem)] relative overflow-hidden"
    >
      {historyOpen && (
        <div
          className="md:hidden absolute inset-0 bg-black/60 z-40"
          onClick={() => setHistoryOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* conversation history, a drawer below md */}
      <aside
        data-testid="chat-history-panel"
        aria-label="Your conversations"
        className={`${historyOpen ? 'flex' : 'hidden'} md:flex absolute md:static inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-[#0c1322] border-r border-slate-800/50 flex-col shrink-0`}
      >
        <div className="p-3 border-b border-slate-800/50 flex items-center gap-2">
          <button
            onClick={createNewChat}
            data-testid="chat-new"
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium shadow-lg shadow-cyan-500/20 hover:shadow-cyan-500/30 transition-shadow"
          >
            <Plus className="w-4 h-4" />
            New chat
          </button>
          <button
            onClick={() => setHistoryOpen(false)}
            className="md:hidden w-9 h-9 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50"
            aria-label="Close conversation list"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-3 py-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search your conversations"
              aria-label="Search your conversations"
              className="w-full pl-9 pr-3 py-2 bg-slate-800/30 border border-slate-700/30 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5">
          {filteredConversations.length === 0 && (
            <div className="px-3 py-8 text-center">
              <MessageSquare className="w-8 h-8 text-slate-700 mx-auto mb-2" />
              <p className="text-xs text-slate-500">
                {searchQuery ? 'No conversation matches that search.' : 'No conversations yet. Your chats are saved here after the first message.'}
              </p>
            </div>
          )}
          {filteredConversations.map((conv) => (
            <div
              key={conv.id}
              data-testid="chat-history-item"
              className={`group flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
                activeConvId === conv.id
                  ? 'bg-cyan-500/10 border border-cyan-500/20'
                  : 'hover:bg-slate-800/30 border border-transparent'
              }`}
              onClick={() => {
                setHistoryOpen(false);
                if (conv.id !== activeConvId) openConversation(conv.id);
                router.replace(`/chat?id=${conv.id}`, { scroll: false });
              }}
            >
              <MessageSquare className={`w-4 h-4 shrink-0 ${activeConvId === conv.id ? 'text-cyan-400' : 'text-slate-600'}`} />
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
                    aria-label="Conversation title"
                    maxLength={255}
                    className="w-full bg-transparent text-xs text-white focus:outline-none border-b border-cyan-500/50"
                  />
                ) : (
                  <p className={`text-xs font-medium truncate ${activeConvId === conv.id ? 'text-white' : 'text-slate-300'}`}>
                    {conv.title}
                  </p>
                )}
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[10px] text-slate-500">{timeLabel(conv.updated_at)}</span>
                  {conv.message_count > 0 && (
                    <span className="text-[10px] text-slate-500">{conv.message_count} messages</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-0.5 md:opacity-0 md:group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditingTitle(conv.id);
                    setEditTitleValue(conv.title);
                  }}
                  className="w-7 h-7 flex items-center justify-center rounded text-slate-500 hover:text-white hover:bg-slate-700/50"
                  aria-label={`Rename ${conv.title}`}
                  title="Rename"
                >
                  <Pencil className="w-3 h-3" />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteTarget(conv);
                  }}
                  className="w-7 h-7 flex items-center justify-center rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10"
                  aria-label={`Delete ${conv.title}`}
                  title="Delete"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="border-b border-slate-800/50 px-3 sm:px-4 py-3 shrink-0">
          <PageHeader
            compact
            title="Chat"
            icon={MessageSquare}
            purpose="Ask any of your agents a question. Your conversations are saved on the left."
            primaryAction={{ label: 'New chat', onClick: createNewChat, icon: Plus, testId: 'chat-new-header' }}
            steps={[
              'Pick the agent that should answer, then type your message.',
              'Replies show the tools the agent used. Pipelines do not remember earlier messages.',
            ]}
            docSlug="02-runtime/00-agent-execution"
            storageKey="chat"
          />
        </div>
        <div className="h-14 border-b border-slate-800/50 flex items-center justify-between gap-2 px-3 sm:px-4 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={() => setHistoryOpen(true)}
              data-testid="chat-history-toggle"
              className="md:hidden w-9 h-9 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 shrink-0"
              aria-label="Show your conversations"
              title="Your conversations"
            >
              <History className="w-5 h-5" />
            </button>
            <div className="relative min-w-0" ref={agentPickerRef}>
              <button
                onClick={() => setShowAgentPicker(!showAgentPicker)}
                data-testid="chat-agent-picker"
                aria-haspopup="listbox"
                aria-expanded={showAgentPicker}
                title="Choose which agent answers"
                className="flex items-center gap-2 max-w-full px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/50 hover:border-slate-600/50 transition-colors"
              >
                {agentsLoading && !selectedAgent ? (
                  <Loader2 className="w-4 h-4 text-slate-500 animate-spin shrink-0" />
                ) : (
                  <Bot className={`w-4 h-4 shrink-0 ${selectedAgent ? 'text-cyan-400' : 'text-slate-500'}`} />
                )}
                <span className={`text-sm truncate ${selectedAgent ? 'text-white font-medium' : 'text-slate-400'}`}>
                  {selectedAgent ? selectedAgent.name : agentsLoading ? 'Loading agents' : 'Choose an agent'}
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-500 shrink-0" />
              </button>

              <AnimatePresence>
                {showAgentPicker && (
                  <motion.div
                    initial={{ opacity: 0, y: -8, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -8, scale: 0.95 }}
                    transition={{ duration: 0.15 }}
                    className="absolute left-0 top-11 w-80 max-w-[calc(100vw-1.5rem)] bg-slate-800 border border-slate-700/50 rounded-xl shadow-2xl shadow-black/50 overflow-hidden z-50"
                  >
                    <div className="p-2 border-b border-slate-700/40">
                      <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
                        <input
                          autoFocus
                          type="text"
                          value={agentQuery}
                          onChange={(e) => setAgentQuery(e.target.value)}
                          placeholder={`Search ${agents.length} agents by name or topic`}
                          aria-label="Search agents"
                          data-testid="chat-agent-search"
                          className="w-full pl-9 pr-3 py-2 bg-slate-900/50 border border-slate-700/40 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500/50"
                        />
                      </div>
                    </div>
                    <div role="listbox" aria-label="Agents" className="max-h-80 overflow-y-auto divide-y divide-slate-700/30">
                      {matchingAgents.slice(0, PICKER_LIMIT).map((agent) => (
                        <button
                          key={agent.id}
                          role="option"
                          aria-selected={selectedAgent?.id === agent.id}
                          data-testid="chat-agent-option"
                          onClick={() => {
                            setSelectedAgent(agent);
                            setShowAgentPicker(false);
                            setAgentQuery('');
                            setChatError(null);
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
                            {agent.description && (
                              <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{agent.description}</p>
                            )}
                            <div className="flex flex-wrap gap-1 mt-1">
                              {agent.category && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400">{agent.category}</span>
                              )}
                              {isPipeline(agent) && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300">pipeline, no memory</span>
                              )}
                            </div>
                          </div>
                          {selectedAgent?.id === agent.id && <Check className="w-4 h-4 text-cyan-400 shrink-0 mt-1" />}
                        </button>
                      ))}
                      {agentsLoading && agents.length === 0 && (
                        <div className="px-4 py-6 text-center text-xs text-slate-400">Loading your agents</div>
                      )}
                      {!agentsLoading && agents.length === 0 && (
                        <div className="px-4 py-6 text-center text-xs text-slate-400">
                          You have no agents yet. <Link href="/builder" className="text-cyan-400 hover:underline">Create one</Link> to start chatting.
                        </div>
                      )}
                      {agents.length > 0 && matchingAgents.length === 0 && (
                        <div className="px-4 py-6 text-center text-xs text-slate-400">No agent matches &ldquo;{agentQuery}&rdquo;.</div>
                      )}
                    </div>
                    {matchingAgents.length > PICKER_LIMIT && (
                      <p className="px-4 py-2 text-[11px] text-slate-500 border-t border-slate-700/40">
                        Showing {PICKER_LIMIT} of {matchingAgents.length}. Type to narrow the list.
                      </p>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            {lastModel && (
              <span
                data-testid="chat-model"
                className="hidden sm:inline text-xs font-mono text-slate-500 bg-slate-800/50 px-2 py-1 rounded"
                title="Model that wrote the latest reply"
              >
                {lastModel}
              </span>
            )}
            {totalTokens > 0 && (
              <span
                className="hidden lg:inline text-xs text-slate-500 bg-slate-800/50 px-2 py-1 rounded"
                title="Tokens and cost used in this conversation"
              >
                {totalTokens.toLocaleString()} tokens &middot; <CostValue cost={cost} testId="chat-cost" />
              </span>
            )}
            {activeConvId && (
              <button
                onClick={shareConversation}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-white hover:bg-slate-800/50 transition-colors"
                title="Copy a read-only share link"
                aria-label="Copy a read-only share link"
              >
                <Share2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 sm:px-6 py-4 space-y-4">
          {messages.length === 0 && !isStreaming && (
            <div data-testid="chat-empty" className="flex flex-col items-center justify-center min-h-full text-center py-6">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-purple-500/10 flex items-center justify-center mb-4">
                <MessageSquare className="w-7 h-7 text-cyan-400" />
              </div>
              <h2 className="text-lg font-semibold text-white mb-1">
                {selectedAgent ? `Chat with ${selectedAgent.name}` : 'AI Chat'}
              </h2>
              <p className="text-sm text-slate-400 max-w-md mb-5">
                {selectedAgent
                  ? selectedAgent.description || 'Ask a question or describe a task.'
                  : agentsLoading
                    ? 'Loading your agents.'
                    : 'Talk to any of your agents here. Choose one from the list at the top to begin.'}
              </p>
              <ul className="text-left text-xs text-slate-400 space-y-2.5 max-w-md">
                <li className="flex gap-2.5">
                  <Bot className="w-4 h-4 text-cyan-400 shrink-0" />
                  <span>
                    The agent named at the top answers. Click its name to search all {agents.length || 'your'} agents and switch.
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <Brain className="w-4 h-4 text-cyan-400 shrink-0" />
                  <span>
                    {pipelineAgent
                      ? 'This agent is a pipeline. Each message runs it fresh, so it does not use earlier messages. Pick a regular agent for a back and forth conversation.'
                      : 'It remembers this conversation, so you can ask follow-up questions. Very long chats keep the most recent part. Use New chat to start clean.'}
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <FileText className="w-4 h-4 text-cyan-400 shrink-0" />
                  <span>Use the paperclip to add a text file such as .txt, .md, .csv or .json. Its contents are sent with your message.</span>
                </li>
                <li className="flex gap-2.5">
                  <History className="w-4 h-4 text-cyan-400 shrink-0" />
                  <span>Every chat is saved to your conversation list. Only you can see it unless you share a link.</span>
                </li>
              </ul>
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
              messageId={msg.id}
              conversationId={activeConvId}
              agentId={selectedAgent?.id}
              onHoldReleased={onHoldReleased}
            />
          ))}

          {isStreaming && <ChatMessage role="assistant" blocks={streamingBlocks} isStreaming status={replyStatus} />}

          {chatError && (
            <div className="flex justify-center">
              <div role="alert" data-testid="chat-error" className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 text-red-300 text-sm rounded-lg px-4 py-2 max-w-xl">
                <span className="flex-1">{chatError}</span>
                <button onClick={() => setChatError(null)} aria-label="Dismiss error" className="text-red-300/70 hover:text-red-200">
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <div className="border-t border-slate-800/50 p-3 sm:p-4">
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {attachments.map((att, i) => (
                <div key={`${att.name}-${i}`} className="flex items-center gap-2 pl-3 pr-1 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/50">
                  <FileText className="w-3.5 h-3.5 text-slate-400" />
                  <span className="text-xs text-slate-300 max-w-[160px] truncate">{att.name}</span>
                  <span className="text-[10px] text-slate-500">{formatSize(att.size)}</span>
                  <button
                    onClick={() => removeAttachment(i)}
                    className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:text-white hover:bg-slate-700/60"
                    aria-label={`Remove ${att.name}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          {attachError && (
            <p role="alert" className="text-xs text-amber-300 mb-2">{attachError}</p>
          )}

          <div className="flex items-end gap-2 sm:gap-3">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ATTACH_EXTENSIONS.join(',')}
              className="hidden"
              onChange={handleFileSelect}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={!selectedAgent || isStreaming}
              className="w-10 h-10 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors shrink-0 mb-0.5 disabled:opacity-40"
              title="Attach a text file (.txt, .md, .csv, .json and similar). Its contents are sent with your message."
              aria-label="Attach a text file"
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
              placeholder={selectedAgent ? `Message ${selectedAgent.name}. Enter sends, Shift+Enter adds a line.` : 'Choose an agent at the top to start'}
              aria-label="Your message"
              data-testid="chat-input"
              rows={1}
              disabled={!selectedAgent}
              className="flex-1 min-w-0 bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500/50 transition-colors disabled:opacity-50"
            />

            {isStreaming ? (
              <button
                onClick={stopStreaming}
                data-testid="chat-stop"
                className="w-10 h-10 flex items-center justify-center rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors shrink-0 mb-0.5"
                title="Stop the reply"
                aria-label="Stop the reply"
              >
                <div className="w-3.5 h-3.5 rounded-sm bg-red-400" />
              </button>
            ) : (
              <button
                onClick={submit}
                disabled={!inputValue.trim() || !selectedAgent}
                data-testid="chat-send"
                className="w-10 h-10 flex items-center justify-center rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 text-white shadow-lg shadow-cyan-500/25 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none transition-all shrink-0 mb-0.5"
                aria-label="Send message"
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

      <ConfirmModal
        open={!!deleteTarget}
        onClose={() => !deleting && setDeleteTarget(null)}
        onConfirm={confirmDelete}
        loading={deleting}
        title="Delete this conversation?"
        description={`"${deleteTarget?.title || ''}" and all its messages will be removed for good. The agent will no longer remember it.`}
        confirmLabel="Delete conversation"
      />

      <AnimatePresence>
        {shareToast && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            role="status"
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
