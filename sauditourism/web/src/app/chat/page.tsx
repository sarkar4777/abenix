'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { MessageSquare, Send, Loader2, Trash2, Palmtree } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('st_token') || ''; }

async function safeFetch(url: string, opts?: any) {
  const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(600000) });
  const text = await res.text();
  try { return JSON.parse(text); } catch { return { data: null, error: { message: text.slice(0, 200) } }; }
}

const SUGGESTIONS = [
  'Which region had the highest visitor count in 2024?',
  'What is the average hotel occupancy rate?',
  'Compare revenue between Riyadh and Makkah',
  'What are the top 5 source countries for international visitors?',
  'How does summer heat affect tourism?',
  'What does Vision 2030 target for total visits?',
];

export default function ChatPage() {
  const [messages, setMessages] = useState<any[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/st/chat/history`, { headers: { Authorization: `Bearer ${getToken()}` } });
        const json = await res.json();
        if (json.data) setMessages(json.data);
      } catch { }
    })();
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  async function sendMessage(text?: string) {
    const msg = text || input.trim();
    if (!msg || sending) return;
    setInput('');
    setMessages(prev => [...prev, { id: Date.now(), role: 'user', content: msg }]);
    setSending(true);
    try {
      const json = await safeFetch(`${API_URL}/api/st/chat/message`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      });
      if (json.data) {
        setMessages(prev => [...prev, { id: Date.now() + 1, role: 'assistant', content: json.data.message }]);
      }
    } catch { } finally { setSending(false); }
  }

  async function clearHistory() {
    await fetch(`${API_URL}/api/st/chat/history`, { method: 'DELETE', headers: { Authorization: `Bearer ${getToken()}` } });
    setMessages([]);
  }

  return (
    <div className="flex flex-col h-[calc(100vh-0px)]">
      {/* Header */}
      <div className="px-6 py-4 border-b border-green-900/40 flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-lg font-bold flex items-center gap-2"><MessageSquare className="w-5 h-5 text-green-400" /> Tourism Chat</h1>
          <p className="text-xs text-green-300/30">Ask questions about your tourism datasets — powered by Abenix st-chat agent</p>
        </div>
        <button onClick={clearHistory} className="text-xs text-green-500/30 hover:text-red-400 flex items-center gap-1 transition-colors">
          <Trash2 className="w-3.5 h-3.5" /> Clear
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && !sending && (
          <div className="flex flex-col items-center justify-center h-full">
            <Palmtree className="w-12 h-12 text-green-600/20 mb-4" />
            <p className="text-green-300/30 mb-6">Ask anything about Saudi Arabia tourism</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-w-2xl">
              {SUGGESTIONS.map(s => (
                <button key={s} onClick={() => sendMessage(s)}
                  className="text-left px-4 py-3 rounded-xl border border-green-800/30 bg-[#0A2818]/30 text-xs text-green-300/50 hover:border-green-600/50 hover:text-white transition-all">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(m => (
          <motion.div key={m.id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}
            className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${m.role === 'user' ? 'bg-green-700/30 border border-green-600/30' : 'bg-[#0A2818]/70 border border-green-800/40'}`}>
              {m.role === 'user' ? (
                <p className="text-sm text-white">{m.content}</p>
              ) : (
                <div className="prose prose-sm prose-invert max-w-none
                  prose-headings:text-green-300 prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1
                  prose-h2:text-base prose-h3:text-sm prose-h4:text-xs
                  prose-p:text-white/90 prose-p:my-1 prose-p:leading-relaxed
                  prose-strong:text-green-300
                  prose-table:text-xs prose-th:text-green-400 prose-th:px-2 prose-th:py-1 prose-th:border-green-800/50
                  prose-td:px-2 prose-td:py-1 prose-td:border-green-800/30 prose-td:text-white/80
                  prose-li:text-white/90 prose-li:my-0
                  prose-code:text-green-300 prose-code:bg-green-900/30 prose-code:px-1 prose-code:rounded
                  prose-a:text-green-400 prose-a:no-underline hover:prose-a:underline
                  prose-blockquote:border-green-700/50 prose-blockquote:text-green-300/70
                  prose-hr:border-green-800/40
                  [&_table]:border [&_table]:border-green-800/40 [&_table]:rounded-lg [&_table]:overflow-hidden
                  [&_thead]:bg-green-900/30
                ">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                </div>
              )}
            </div>
          </motion.div>
        ))}

        {sending && (
          <div className="flex justify-start">
            <div className="rounded-2xl px-4 py-3 bg-[#0A2818]/70 border border-green-800/40">
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin text-green-400" />
                <span className="text-sm text-green-300/40">st-chat agent analyzing...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-green-900/40 shrink-0">
        <form onSubmit={e => { e.preventDefault(); sendMessage(); }} className="flex items-center gap-3">
          <input value={input} onChange={e => setInput(e.target.value)}
            placeholder="Ask about visitors, revenue, regions, satisfaction..."
            className="flex-1 bg-green-900/20 border border-green-700/40 rounded-xl px-4 py-3 text-white text-sm placeholder-green-600/30 focus:border-green-500 focus:outline-none transition-colors" />
          <button type="submit" disabled={sending || !input.trim()}
            className="px-4 py-3 rounded-xl bg-gradient-to-r from-green-600 to-green-700 text-white hover:shadow-lg hover:shadow-green-600/25 transition-all disabled:opacity-30">
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}
