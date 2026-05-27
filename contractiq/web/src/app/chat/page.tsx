'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  FileSearch, Upload, BarChart3, MessageSquare, FileText, TrendingUp,
  LogOut, Send, Loader2, Sparkles, AlertCircle, Database, Shield,
  FileBarChart, Zap, Scale, Bot, Plus, Trash2, MessagesSquare,
} from 'lucide-react';
import { apiFetch } from '@/lib/api';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('contractiq_token');
}
function getUser() {
  if (typeof window === 'undefined') return null;
  try { return JSON.parse(localStorage.getItem('contractiq_user') || 'null'); } catch { return null; }
}

const NAV_ITEMS = [
  { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
  { label: 'Upload Contract', icon: Upload, href: '/upload' },
  { label: 'My Contracts', icon: FileText, href: '/contracts' },
  { label: 'Compare', icon: TrendingUp, href: '/compare' },
  { label: 'Chat', icon: MessageSquare, href: '/chat' },
];

const SUGGESTIONS = [
  { text: 'Which contract has the weakest curtailment protection?', icon: Shield },
  { text: 'Compare pricing and escalation across all my PPAs', icon: Scale },
  { text: "What's my total MW exposure expiring before 2030?", icon: Zap },
  { text: 'Which contracts have force majeure clauses and what do they cover?', icon: AlertCircle },
  { text: 'Summarize key risks across all contracts with mitigation recommendations', icon: FileBarChart },
  { text: 'What are the payment terms and settlement periods across my portfolio?', icon: Database },
];

interface Message {
  role: 'user' | 'assistant';
  content: string;
  sources?: { id: string; title: string; type: string }[];
  meta?: { contracts_analyzed?: number; clauses_searched?: number };
}

interface Thread {
  id: string;
  title: string;
  message_count: number;
  last_message_preview: string | null;
  updated_at: string;
}

function RichText({ text }: { text: string }) {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;
  let tableRows: string[][] = [];
  let inTable = false;

  const renderInline = (line: string, key: string) => {
    // Bold **text** and *italic*
    const parts = line.split(/(\*\*.*?\*\*|\*.*?\*|`[^`]+`)/g);
    return (
      <span key={key}>
        {parts.map((p, j) => {
          if (p.startsWith('**') && p.endsWith('**'))
            return <strong key={j} className="text-white font-semibold">{p.slice(2, -2)}</strong>;
          if (p.startsWith('*') && p.endsWith('*'))
            return <em key={j} className="text-slate-300">{p.slice(1, -1)}</em>;
          if (p.startsWith('`') && p.endsWith('`'))
            return <code key={j} className="px-1 py-0.5 bg-slate-700/50 rounded text-emerald-300 text-xs">{p.slice(1, -1)}</code>;
          return <span key={j}>{p}</span>;
        })}
      </span>
    );
  };

  while (i < lines.length) {
    const line = lines[i];

    // Table rows
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      if (!inTable) { inTable = true; tableRows = []; }
      const cells = line.split('|').filter(Boolean).map(c => c.trim());
      if (!cells.every(c => /^[-:]+$/.test(c))) tableRows.push(cells);
      i++;
      continue;
    } else if (inTable) {
      inTable = false;
      elements.push(
        <div key={`table-${i}`} className="overflow-x-auto my-2">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-600">
                {(tableRows[0] || []).map((h, j) => (
                  <th key={j} className="text-left py-1.5 px-2 text-slate-300 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableRows.slice(1).map((row, ri) => (
                <tr key={ri} className="border-b border-slate-700/30">
                  {row.map((cell, ci) => (
                    <td key={ci} className="py-1.5 px-2 text-slate-400">{renderInline(cell, `tc-${ri}-${ci}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      tableRows = [];
    }

    // Headers
    if (line.startsWith('### ')) {
      elements.push(<h4 key={i} className="text-sm font-semibold text-white mt-3 mb-1">{line.slice(4)}</h4>);
    } else if (line.startsWith('## ')) {
      elements.push(<h3 key={i} className="text-sm font-bold text-white mt-3 mb-1">{line.slice(3)}</h3>);
    } else if (line.startsWith('# ')) {
      elements.push(<h2 key={i} className="text-base font-bold text-white mt-3 mb-1">{line.slice(2)}</h2>);
    }
    // Bullet points
    else if (line.match(/^[-*] /)) {
      elements.push(
        <div key={i} className="flex items-start gap-2 ml-2 my-0.5">
          <span className="text-emerald-400 mt-1.5 text-[6px]">●</span>
          <span className="text-slate-300 text-sm leading-relaxed">{renderInline(line.slice(2), `bl-${i}`)}</span>
        </div>
      );
    }
    // Numbered lists
    else if (line.match(/^\d+\.\s/)) {
      const num = line.match(/^(\d+)\./)?.[1];
      const rest = line.replace(/^\d+\.\s*/, '');
      elements.push(
        <div key={i} className="flex items-start gap-2 ml-2 my-0.5">
          <span className="text-cyan-400 text-xs font-mono mt-0.5 min-w-[1.2rem]">{num}.</span>
          <span className="text-slate-300 text-sm leading-relaxed">{renderInline(rest, `nl-${i}`)}</span>
        </div>
      );
    }
    // Empty line
    else if (line.trim() === '') {
      elements.push(<div key={i} className="h-2" />);
    }
    // Normal text
    else {
      elements.push(<p key={i} className="text-slate-300 text-sm leading-relaxed my-0.5">{renderInline(line, `p-${i}`)}</p>);
    }

    i++;
  }

  // Flush remaining table
  if (inTable && tableRows.length > 0) {
    elements.push(
      <div key="table-final" className="overflow-x-auto my-2">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-600">
              {(tableRows[0] || []).map((h, j) => (
                <th key={j} className="text-left py-1.5 px-2 text-slate-300 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableRows.slice(1).map((row, ri) => (
              <tr key={ri} className="border-b border-slate-700/30">
                {row.map((cell, ci) => (
                  <td key={ci} className="py-1.5 px-2 text-slate-400">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return <div>{elements}</div>;
}

export default function ContractIQChatPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [loadingThreads, setLoadingThreads] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());
  }, [router]);

  // Load threads on mount
  useEffect(() => {
    if (!user) return;
    void loadThreads();
  }, [user]);

  // Load thread messages when activeThreadId changes
  useEffect(() => {
    if (!activeThreadId) { setMessages([]); return; }
    void loadThreadMessages(activeThreadId);
  }, [activeThreadId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const loadThreads = async () => {
    setLoadingThreads(true);
    const token = getToken();
    const res = await apiFetch<any>(`${API_URL}/api/contractiq/chat/threads`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok && res.data?.data?.threads) {
      setThreads(res.data.data.threads);
    }
    setLoadingThreads(false);
  };

  const loadThreadMessages = async (threadId: string) => {
    const token = getToken();
    const res = await apiFetch<any>(`${API_URL}/api/contractiq/chat/threads/${threadId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok && res.data?.data?.messages) {
      setMessages(res.data.data.messages.map((m: any) => ({
        role: m.role,
        content: m.content,
      })));
    }
  };

  const newChat = () => {
    setActiveThreadId(null);
    setMessages([]);
  };

  const deleteThread = async (threadId: string) => {
    if (!confirm('Delete this conversation?')) return;
    const token = getToken();
    await apiFetch(`${API_URL}/api/contractiq/chat/threads/${threadId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (activeThreadId === threadId) newChat();
    void loadThreads();
  };

  const sendMessage = async (text?: string) => {
    const msg = (text || input).trim();
    if (!msg) return;
    setMessages(prev => [...prev, { role: 'user', content: msg }]);
    setInput('');
    setLoading(true);
    const token = getToken();
    const res = await apiFetch<any>(`${API_URL}/api/contractiq/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ query: msg, thread_id: activeThreadId }),
    });
    if (res.ok && res.data?.data) {
      const data = res.data.data;
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.answer || 'No response received.',
        sources: data.sources,
        meta: { contracts_analyzed: data.contracts_analyzed },
      }]);
      // Pin the thread id (auto-created server-side on first turn) and refresh sidebar
      if (data.thread_id && data.thread_id !== activeThreadId) {
        setActiveThreadId(data.thread_id);
      }
      void loadThreads();
    } else {
      setMessages(prev => [...prev, { role: 'assistant', content: res.error || 'Failed to get response. Please try again.' }]);
    }
    setLoading(false);
  };

  const logout = () => { localStorage.removeItem('contractiq_token'); localStorage.removeItem('contractiq_refresh_token'); localStorage.removeItem('contractiq_user'); router.replace('/'); };

  if (!user) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>;

  return (
    <div className="min-h-screen bg-[#0B0F19] flex">
      {/* Thread sidebar */}
      <aside className="w-64 border-r border-slate-800/50 flex flex-col shrink-0">
        <div className="p-3 border-b border-slate-800/50">
          <button
            onClick={newChat}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20 transition-colors text-xs font-medium"
          >
            <Plus className="w-3.5 h-3.5" /> New chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loadingThreads && (
            <div className="text-center py-6">
              <Loader2 className="w-4 h-4 text-emerald-400 animate-spin mx-auto" />
            </div>
          )}
          {!loadingThreads && threads.length === 0 && (
            <div className="text-center py-6 text-[11px] text-slate-600">
              <MessagesSquare className="w-6 h-6 mx-auto mb-2 text-slate-700" />
              No conversations yet
            </div>
          )}
          {threads.map(t => (
            <div
              key={t.id}
              onClick={() => setActiveThreadId(t.id)}
              className={`group rounded-lg p-2 cursor-pointer transition-colors ${
                activeThreadId === t.id
                  ? 'bg-emerald-500/10 border border-emerald-500/30'
                  : 'hover:bg-slate-800/40 border border-transparent'
              }`}
            >
              <div className="flex items-start justify-between gap-1">
                <p className="text-[12px] text-slate-200 truncate flex-1" title={t.title}>{t.title}</p>
                <button
                  onClick={e => { e.stopPropagation(); void deleteThread(t.id); }}
                  className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-500 hover:text-rose-400 transition-opacity"
                  title="Delete"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
              {t.last_message_preview && (
                <p className="text-[10px] text-slate-500 truncate mt-0.5">{t.last_message_preview}</p>
              )}
              <p className="text-[9px] text-slate-600 mt-0.5">
                {t.message_count} msg{t.message_count !== 1 ? 's' : ''} · {new Date(t.updated_at).toLocaleDateString()}
              </p>
            </div>
          ))}
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="border-b border-slate-800/50 px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-white flex items-center gap-2">
              <Bot className="w-5 h-5 text-emerald-400" /> Cross-Contract Intelligence
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">
              AI-powered analysis across your entire contract portfolio
              {activeThreadId && <span className="text-emerald-400 ml-2">· Continuing thread</span>}
            </p>
          </div>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 flex items-center justify-center mb-4">
                <Sparkles className="w-8 h-8 text-emerald-400" />
              </div>
              <h2 className="text-base font-semibold text-white mb-1">Contract Intelligence Assistant</h2>
              <p className="text-sm text-slate-400 mb-6 max-w-md text-center">
                Ask anything about your contract portfolio — pricing, risks, clauses, counterparties, and more.
              </p>
              <div className="grid grid-cols-2 gap-2 max-w-2xl w-full">
                {SUGGESTIONS.map(s => (
                  <button key={s.text} onClick={() => sendMessage(s.text)}
                    className="text-left px-4 py-3 bg-slate-800/30 border border-slate-700/50 rounded-lg text-sm text-slate-300 hover:border-emerald-500/30 hover:bg-slate-800/50 transition-colors flex items-start gap-3">
                    <s.icon className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
                    <span>{s.text}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[75%] ${msg.role === 'user' ? '' : 'w-full max-w-[75%]'}`}>
                {msg.role === 'assistant' && (
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className="w-5 h-5 rounded-full bg-emerald-500/20 flex items-center justify-center">
                      <Bot className="w-3 h-3 text-emerald-400" />
                    </div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider">E&C-Copilot</span>
                    {msg.meta?.contracts_analyzed && (
                      <span className="text-[10px] text-slate-600">
                        ({msg.meta.contracts_analyzed} contracts, {msg.meta.clauses_searched} clauses searched)
                      </span>
                    )}
                  </div>
                )}
                <div className={`px-4 py-3 rounded-xl text-sm leading-relaxed ${
                  msg.role === 'user' ? 'bg-emerald-500/10 border border-emerald-500/20 text-white'
                    : 'bg-slate-800/50 border border-slate-700/50'
                }`}>
                  {msg.role === 'assistant' ? <RichText text={msg.content} /> : msg.content}
                </div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2 ml-1">
                    {msg.sources.map(s => (
                      <a key={s.id} href={`/contracts/${s.id}`}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-800/50 border border-slate-700/30 text-[10px] text-slate-400 hover:text-emerald-400 hover:border-emerald-500/30 transition-colors">
                        <FileText className="w-2.5 h-2.5" />
                        {s.title}
                        <span className={`ml-0.5 px-1 rounded text-[8px] ${
                          s.type === 'ppa' ? 'bg-emerald-500/10 text-emerald-400' :
                          s.type === 'gas' ? 'bg-amber-500/10 text-amber-400' : 'bg-slate-500/10 text-slate-400'
                        }`}>{s.type.toUpperCase()}</span>
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          ))}
          {loading && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
              <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
                <Loader2 className="w-4 h-4 text-emerald-400 animate-spin" />
                <span className="text-xs text-slate-400">Analyzing your portfolio...</span>
              </div>
            </motion.div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-slate-800/50 px-6 py-4">
          <div className="max-w-3xl mx-auto flex gap-2">
            <input type="text" value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !loading && sendMessage()}
              placeholder="Ask about your contracts — pricing, risks, clauses, counterparties..."
              disabled={loading}
              className="flex-1 bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none disabled:opacity-50" />
            <button onClick={() => sendMessage()} disabled={loading || !input.trim()}
              className="px-5 py-3 rounded-xl bg-emerald-500 text-white hover:bg-emerald-400 disabled:opacity-50 transition-colors">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
