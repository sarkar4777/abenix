'use client';


import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Workflow, Upload, Loader2, Sparkles, Check, X, MessagesSquare,
  Plus, Trash2, ChevronRight, Send, Bot, FileText, Wand2, FlaskConical,
  CheckCircle2, AlertTriangle, ExternalLink, Zap, Cpu, Wrench, ArrowRight,
  Download, Image as ImageIcon, Music, Film, FileType,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface Thread {
  id: string;
  title: string;
  message_count: number;
  last_message_preview: string | null;
  created_at: string;
  updated_at: string;
}

interface Msg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  model_used?: string | null;
  cost?: number;
}

interface AgentSpec {
  name: string;
  slug?: string;
  description: string;
  system_prompt: string;
  model: string;
  category: string;
  lane?: string;
  why?: string;
  tools: string[];
}

type WizardStage = 'idle' | 'fetching' | 'review' | 'synth' | 'creating' | 'testing' | 'done' | 'skipped';

interface WizardStep {
  spec: AgentSpec;
  stage: WizardStage;
  agent?: { id: string; slug: string; name: string };
  synth?: { description: string; input: string };
  test?: { ok: boolean; output?: string; error?: string; cost?: number; duration_ms?: number };
}

function MarkdownRich({ text }: { text: string }) {
  const lines = text.split('\n');
  const els: React.ReactNode[] = [];

  const renderInline = (s: string, key: string): React.ReactNode => {
    const tokens: React.ReactNode[] = [];
    const re = /(\*\*([^*]+?)\*\*|__([^_]+?)__|\*([^*\n]+?)\*|_([^_\n]+?)_|~~([^~]+?)~~|`([^`]+?)`|\[([^\]]+?)\]\(([^)]+?)\))/g;
    let last = 0;
    let k = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(s)) !== null) {
      if (m.index > last) tokens.push(<span key={`${key}-t${k++}`}>{s.slice(last, m.index)}</span>);
      if (m[2] || m[3]) tokens.push(<strong key={`${key}-t${k++}`} className="text-white font-semibold">{m[2] || m[3]}</strong>);
      else if (m[4] || m[5]) tokens.push(<em key={`${key}-t${k++}`} className="italic text-slate-200">{m[4] || m[5]}</em>);
      else if (m[6]) tokens.push(<span key={`${key}-t${k++}`} className="line-through text-slate-500">{m[6]}</span>);
      else if (m[7]) tokens.push(<code key={`${key}-t${k++}`} className="text-emerald-300 bg-slate-800/70 px-1.5 py-0.5 rounded text-[0.92em] font-mono">{m[7]}</code>);
      else if (m[8] && m[9]) tokens.push(<a key={`${key}-t${k++}`} href={m[9]} target="_blank" rel="noreferrer" className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2">{m[8]}</a>);
      last = re.lastIndex;
    }
    if (last < s.length) tokens.push(<span key={`${key}-t${k++}`}>{s.slice(last)}</span>);
    return <>{tokens}</>;
  };

  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    const stripped = ln.trim();

    // Fenced code block
    if (stripped.startsWith('```')) {
      const lang = stripped.slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        buf.push(lines[i]);
        i++;
      }
      i++;
      els.push(
        <div key={`code-${i}`} className="my-3 rounded-lg overflow-hidden border border-slate-700/50 shadow-sm">
          {lang && (
            <div className="bg-slate-800/80 px-3 py-1 text-[10px] uppercase tracking-wider text-slate-400 font-mono border-b border-slate-700/40 flex items-center justify-between">
              <span>{lang}</span>
            </div>
          )}
          <pre className="bg-slate-950/80 px-4 py-3 overflow-x-auto text-[12px] leading-relaxed">
            <code className="text-slate-200 font-mono whitespace-pre">{buf.join('\n')}</code>
          </pre>
        </div>,
      );
      continue;
    }

    // GFM table (one or more `| … |` lines, optional `|---|` alignment row)
    if (stripped.startsWith('|') && stripped.endsWith('|') && stripped.length > 2) {
      const rows: string[][] = [];
      while (i < lines.length) {
        const row = lines[i].trim();
        if (!row.startsWith('|') || !row.endsWith('|')) break;
        const cells = row.slice(1, -1).split('|').map(c => c.trim());
        if (!cells.every(c => /^:?-+:?$/.test(c))) rows.push(cells);
        i++;
      }
      if (rows.length > 0) {
        els.push(
          <div key={`tbl-${i}`} className="overflow-x-auto my-4 rounded-lg border border-slate-700/50 shadow-lg">
            <table className="w-full text-[12px] border-collapse">
              <thead className="bg-gradient-to-r from-violet-500/15 to-cyan-500/10 text-slate-100">
                <tr>{rows[0].map((h, j) => (
                  <th key={j} className="text-left px-3 py-2 font-semibold border-b border-slate-700/60">{renderInline(h, `th-${i}-${j}`)}</th>
                ))}</tr>
              </thead>
              <tbody>{rows.slice(1).map((r, ri) => (
                <tr key={ri} className="border-t border-slate-800/40 hover:bg-slate-800/30 transition-colors">{r.map((c, ci) => (
                  <td key={ci} className="px-3 py-2 text-slate-300 align-top">{renderInline(c, `td-${i}-${ri}-${ci}`)}</td>
                ))}</tr>
              ))}</tbody>
            </table>
          </div>,
        );
      }
      continue;
    }

    // Headings (# .. ######)
    const hMatch = stripped.match(/^(#{1,6})\s+(.+)$/);
    if (hMatch) {
      const level = hMatch[1].length;
      const txt = hMatch[2];
      if (level === 1) els.push(<h1 key={i} className="text-xl font-bold text-white mt-6 mb-3 pb-2 border-b border-slate-700/60">{renderInline(txt, `h1-${i}`)}</h1>);
      else if (level === 2) els.push(<h2 key={i} className="text-lg font-bold text-white mt-5 mb-2 flex items-center gap-2"><span className="w-1 h-5 bg-gradient-to-b from-violet-400 to-cyan-400 rounded" />{renderInline(txt, `h2-${i}`)}</h2>);
      else if (level === 3) els.push(<h3 key={i} className="text-base font-semibold text-violet-200 mt-4 mb-1.5">{renderInline(txt, `h3-${i}`)}</h3>);
      else els.push(<h4 key={i} className="text-sm font-semibold text-cyan-200 mt-3 mb-1">{renderInline(txt, `h4-${i}`)}</h4>);
      i++;
      continue;
    }

    // Blockquote (one or more consecutive `> …` lines)
    if (stripped.startsWith('>')) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        buf.push(lines[i].trim().replace(/^>\s?/, ''));
        i++;
      }
      els.push(
        <blockquote key={`bq-${i}`} className="border-l-2 border-violet-500/60 pl-3 my-3 bg-violet-500/5 py-2 pr-2 rounded-r">
          {buf.map((l, j) => <p key={j} className="text-sm text-slate-300 italic">{renderInline(l, `bq-${i}-${j}`)}</p>)}
        </blockquote>,
      );
      continue;
    }

    // Horizontal rule
    if (/^(\*\*\*+|---+|___+)$/.test(stripped)) {
      els.push(<hr key={i} className="my-4 border-slate-700/60" />);
      i++;
      continue;
    }

    // Unordered list
    if (/^[-*]\s+/.test(stripped)) {
      const buf: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        buf.push(lines[i].trim().replace(/^[-*]\s+/, ''));
        i++;
      }
      els.push(
        <ul key={`ul-${i}`} className="my-2 ml-1 space-y-1">
          {buf.map((item, j) => (
            <li key={j} className="flex gap-2 text-sm text-slate-300 leading-relaxed">
              <span className="text-emerald-400 mt-[7px] text-[6px] shrink-0">●</span>
              <span className="flex-1">{renderInline(item, `li-${i}-${j}`)}</span>
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    // Ordered list
    if (/^\d+\.\s+/.test(stripped)) {
      const buf: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        buf.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
        i++;
      }
      els.push(
        <ol key={`ol-${i}`} className="my-2 ml-1 space-y-1">
          {buf.map((item, j) => (
            <li key={j} className="flex gap-2 text-sm text-slate-300 leading-relaxed">
              <span className="text-cyan-400 font-mono font-semibold min-w-[1.4rem] shrink-0">{j + 1}.</span>
              <span className="flex-1">{renderInline(item, `oli-${i}-${j}`)}</span>
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    // Empty line
    if (stripped === '') {
      els.push(<div key={`sp-${i}`} className="h-2" />);
      i++;
      continue;
    }

    // Paragraph (default)
    els.push(<p key={i} className="text-sm text-slate-300 leading-relaxed my-1.5">{renderInline(ln, `p-${i}`)}</p>);
    i++;
  }

  return <div className="bpm-md">{els}</div>;
}

// Map a MIME type to a friendly icon for the upload-preview chip.
function mimeIcon(mime: string) {
  if (mime.startsWith('image/')) return ImageIcon;
  if (mime.startsWith('audio/')) return Music;
  if (mime.startsWith('video/')) return Film;
  if (mime === 'application/pdf') return FileText;
  return FileType;
}

// ── Page ─────────────────────────────────────────────────────────────

export default function BPMAnalyzerPage() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [model, setModel] = useState('gemini-2.5-pro');
  const [models, setModels] = useState<Array<{ id: string; label?: string; provider?: string }>>([
    { id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro', provider: 'google' },
  ]);
  const [chatInput, setChatInput] = useState('');
  const [sending, setSending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  // ─── Load threads + model list ────────────────────────────────────
  useEffect(() => {
    void (async () => {
      const r = await apiFetch<any>('/api/bpm-analyzer/threads');
      if (r.data?.threads) setThreads(r.data.threads);
      setLoadingThreads(false);
      const m = await apiFetch<any>('/api/bpm-analyzer/models');
      if (m.data) {
        // Master list returns rich model objects; tolerate the older
        // string-only shape too for backwards compatibility.
        const raw = m.data.models || [];
        const normalised = raw.map((x: any) =>
          typeof x === 'string' ? { id: x, label: x } : x,
        );
        setModels(normalised);
        setModel(m.data.default || 'gemini-2.5-pro');
      }
    })();
  }, []);

  // Load messages when thread changes
  useEffect(() => {
    if (!activeId) { setMessages([]); return; }
    void (async () => {
      const r = await apiFetch<any>(`/api/bpm-analyzer/threads/${activeId}`);
      if (r.data?.messages) setMessages(r.data.messages);
    })();
  }, [activeId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const refreshThreads = async () => {
    const r = await apiFetch<any>('/api/bpm-analyzer/threads');
    if (r.data?.threads) setThreads(r.data.threads);
  };

  // Multimodal upload — accepts PDFs, images, audio, video, DOCX, plain text.
  // Audio/video are routed server-side to a Gemini model regardless of the
  // current selection, since Anthropic & OpenAI don't accept those modalities.
  const onUpload = async (file: File) => {
    const mime = file.type || '';
    const name = file.name || '';
    const lower = name.toLowerCase();
    const isPdf = mime === 'application/pdf' || lower.endsWith('.pdf');
    const isImage = mime.startsWith('image/');
    const isAudio = mime.startsWith('audio/');
    const isVideo = mime.startsWith('video/');
    const isDocx = lower.endsWith('.docx') || mime === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    const isText = mime.startsWith('text/') || lower.endsWith('.txt') || lower.endsWith('.md') || lower.endsWith('.csv');
    if (!(isPdf || isImage || isAudio || isVideo || isDocx || isText)) {
      alert('Unsupported file type. Upload a PDF, image, audio, video, DOCX, or plain-text file.');
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      alert('File exceeds 50 MB. Please trim before uploading.');
      return;
    }
    setUploading(true);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('model', model);
    fd.append('title', name.replace(/\.[^.]+$/, ''));
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const tok = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
      const r = await fetch(`${apiUrl}/api/bpm-analyzer/upload`, {
        method: 'POST',
        body: fd,
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      const j = await r.json();
      if (!r.ok || !j.data) throw new Error(j.error?.message || `HTTP ${r.status}`);
      const tid = j.data.thread.id;
      await refreshThreads();
      setActiveId(tid);
    } catch (e: any) {
      alert(`Upload failed: ${e.message}`);
    }
    setUploading(false);
  };

  const downloadPdf = async () => {
    if (!activeId || downloadingPdf) return;
    setDownloadingPdf(true);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const tok = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
      const r = await fetch(`${apiUrl}/api/bpm-analyzer/threads/${activeId}/export-pdf`, {
        method: 'POST',
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j?.error?.message || `HTTP ${r.status}`);
      }
      const blob = await r.blob();
      const cd = r.headers.get('content-disposition') || '';
      const fnameMatch = cd.match(/filename="?([^";]+)"?/i);
      const fname = fnameMatch ? fnameMatch[1] : 'bpm-analysis.pdf';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(`PDF export failed: ${e.message}`);
    }
    setDownloadingPdf(false);
  };

  const sendChat = async () => {
    const txt = chatInput.trim();
    if (!txt || !activeId) return;
    setMessages(prev => [...prev, { id: 'temp', role: 'user', content: txt }]);
    setChatInput('');
    setSending(true);
    const r = await apiFetch<any>(`/api/bpm-analyzer/chat/${activeId}/turn`, {
      method: 'POST',
      body: JSON.stringify({ content: txt }),
    });
    if (r.data) {
      setMessages(prev => {
        const noTemp = prev.filter(m => m.id !== 'temp');
        return [...noTemp, r.data.user_message, r.data.assistant_message];
      });
      void refreshThreads();
    } else {
      setMessages(prev => [...prev.filter(m => m.id !== 'temp'), { id: 'err', role: 'assistant', content: r.error || 'Failed' }]);
    }
    setSending(false);
  };

  const deleteThread = async (id: string) => {
    if (!confirm('Delete this analysis?')) return;
    // Optimistically drop it from the list + clear the open thread so the
    // sidebar updates instantly. We refresh after the DELETE finishes to
    // reconcile against the server's view.
    setThreads(prev => prev.filter(t => t.id !== id));
    if (activeId === id) setActiveId(null);
    const r = await apiFetch(`/api/bpm-analyzer/threads/${id}`, { method: 'DELETE' });
    if (r.error) {
      alert(`Delete failed: ${r.error}`);
    }
    await refreshThreads();
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] flex">
      {/* Sidebar */}
      <aside className="w-72 border-r border-slate-800/50 flex flex-col shrink-0">
        <div className="p-4 border-b border-slate-800/50">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500/30 to-cyan-500/30 border border-violet-500/40 flex items-center justify-center">
              <Workflow className="w-4 h-4 text-violet-300" />
            </div>
            <div>
              <p className="text-sm font-bold text-white leading-none">BPM Analyzer</p>
              <p className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Multimodal agent</p>
            </div>
          </div>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-violet-500/15 border border-violet-500/40 text-violet-200 hover:bg-violet-500/25 disabled:opacity-50 text-xs font-semibold"
          >
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            {uploading ? 'Analyzing…' : 'Upload process artifact'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf,image/*,audio/*,video/*,.docx,.txt,.md,.csv,text/plain,text/markdown,text/csv"
            className="hidden"
            onChange={e => e.target.files && onUpload(e.target.files[0])}
          />
          <p className="text-[9px] text-slate-600 mt-2 leading-snug">
            PDF · image · audio · video · docx · text. Audio/video auto-route to Gemini.
          </p>
          <div className="mt-3">
            <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1">Vision model</label>
            <select
              value={model}
              onChange={e => setModel(e.target.value)}
              className="w-full bg-slate-900/60 border border-slate-700 rounded text-[11px] text-white px-2 py-1.5"
            >
              {models.map(m => (
                <option key={m.id} value={m.id}>
                  {m.label || m.id}{m.provider ? ` · ${m.provider}` : ''}
                </option>
              ))}
            </select>
            <p className="text-[9px] text-slate-600 mt-1">
              Master list — manage at /admin/llm-settings
            </p>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {loadingThreads && <div className="text-center py-6"><Loader2 className="w-4 h-4 text-violet-400 animate-spin mx-auto" /></div>}
          {!loadingThreads && threads.length === 0 && (
            <div className="text-center py-8 text-[11px] text-slate-600">
              <MessagesSquare className="w-6 h-6 mx-auto mb-2 text-slate-700" />
              No analyses yet
            </div>
          )}
          {threads.map(t => (
            <div
              key={t.id}
              onClick={() => setActiveId(t.id)}
              className={`group rounded-lg p-2 cursor-pointer transition-colors mb-1 ${
                activeId === t.id ? 'bg-violet-500/10 border border-violet-500/30' : 'hover:bg-slate-800/40 border border-transparent'
              }`}
            >
              <div className="flex items-start justify-between gap-1">
                <p className="text-[12px] text-slate-200 truncate flex-1" title={t.title}>{t.title}</p>
                <button onClick={e => { e.stopPropagation(); void deleteThread(t.id); }}
                  className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-500 hover:text-rose-400">
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
              {t.last_message_preview && <p className="text-[10px] text-slate-500 truncate mt-0.5">{t.last_message_preview}</p>}
              <p className="text-[9px] text-slate-600 mt-0.5">{t.message_count} msgs · {new Date(t.updated_at).toLocaleDateString()}</p>
            </div>
          ))}
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-800/50 px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-white flex items-center gap-2">
              <Workflow className="w-5 h-5 text-violet-300" /> BPM Process Analyst
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">
              Drop a process artifact in any format — PDF, image, audio, video, DOCX, or text. The multimodal analyst reads it, returns a deep agentification report, and can build &amp; test the suggested agents end-to-end.
            </p>
          </div>
          {activeId && messages.length >= 2 && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => void downloadPdf()}
                disabled={downloadingPdf}
                className="px-3.5 py-2 rounded-lg bg-slate-800/60 border border-slate-700 hover:border-violet-500/50 hover:bg-slate-800 text-slate-200 text-xs font-semibold transition-all inline-flex items-center gap-2 disabled:opacity-50"
                data-testid="download-pdf"
                title="Download the full analysis as a beautifully formatted PDF"
              >
                {downloadingPdf ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                {downloadingPdf ? 'Building PDF…' : 'Download PDF'}
              </button>
              <button
                onClick={() => setWizardOpen(true)}
                className="px-4 py-2 rounded-lg bg-gradient-to-r from-violet-500 to-cyan-500 text-white text-xs font-semibold hover:shadow-lg hover:shadow-violet-500/30 transition-all inline-flex items-center gap-2"
                data-testid="open-wizard"
              >
                <Wand2 className="w-3.5 h-3.5" /> Build Agents
              </button>
            </div>
          )}
        </header>

        {!activeId && (
          <div className="flex-1 flex items-center justify-center p-12">
            <div className="text-center max-w-lg">
              <div className="w-20 h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-violet-500/20 to-cyan-500/20 border border-violet-500/30 flex items-center justify-center">
                <Workflow className="w-10 h-10 text-violet-300" />
              </div>
              <h2 className="text-xl font-bold text-white mb-2">Drop any process artifact</h2>
              <p className="text-sm text-slate-400 mb-6">
                BPMN PDF, flowchart screenshot, whiteboard photo, recorded process walkthrough, screen-capture video, SOP DOCX, or plain text. The multimodal analyst reads it end-to-end, then tells you exactly where AI agents fit, where they don&apos;t, and offers to build them for you.
              </p>
              <div className="flex flex-wrap gap-2 justify-center mb-6 text-[10px] text-slate-500">
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-slate-800/60 border border-slate-700/60"><FileText className="w-3 h-3" /> PDF</span>
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-slate-800/60 border border-slate-700/60"><ImageIcon className="w-3 h-3" /> Image</span>
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-slate-800/60 border border-slate-700/60"><Music className="w-3 h-3" /> Audio</span>
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-slate-800/60 border border-slate-700/60"><Film className="w-3 h-3" /> Video</span>
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-slate-800/60 border border-slate-700/60"><FileType className="w-3 h-3" /> DOCX/TXT</span>
              </div>
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-violet-500 to-cyan-500 text-white font-semibold hover:shadow-lg hover:shadow-violet-500/30 disabled:opacity-50"
              >
                {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                {uploading ? 'Analyzing…' : 'Upload process artifact'}
              </button>
            </div>
          </div>
        )}

        {activeId && (
          <>
            <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
              {messages.map((m, i) => (
                <motion.div
                  key={m.id || i}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`max-w-4xl ${m.role === 'user' ? 'ml-auto' : ''}`}
                >
                  {m.role === 'assistant' ? (
                    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                      <div className="flex items-center gap-2 mb-3 text-[11px] text-slate-500">
                        <Bot className="w-3 h-3 text-violet-400" />
                        BPM PROCESS ANALYST
                        {m.model_used && <span className="text-slate-600">· {m.model_used}</span>}
                        {typeof m.cost === 'number' && <span className="text-slate-600">· ${m.cost.toFixed(4)}</span>}
                      </div>
                      <MarkdownRich text={m.content} />
                    </div>
                  ) : (
                    <div className="bg-violet-500/10 border border-violet-500/30 rounded-xl px-4 py-3 text-sm text-white">
                      {m.content}
                    </div>
                  )}
                </motion.div>
              ))}
              {sending && (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-violet-400" /> Analyzing diagram…
                </div>
              )}
            </div>
            <div className="border-t border-slate-800/50 px-6 py-3">
              <div className="max-w-4xl flex gap-2">
                <input
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !sending && sendChat()}
                  placeholder="Ask a follow-up — e.g. 'drill into the Compliance lane' or 'estimate cost per onboarding'"
                  className="flex-1 bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none"
                  disabled={sending}
                />
                <button onClick={() => void sendChat()} disabled={sending || !chatInput.trim()}
                  className="px-4 py-2.5 rounded-xl bg-violet-500 text-white hover:bg-violet-400 disabled:opacity-50">
                  {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </button>
              </div>
            </div>
          </>
        )}
      </main>

      {wizardOpen && activeId && (
        <BuildAgentsWizard
          threadId={activeId}
          model={model}
          onClose={() => setWizardOpen(false)}
        />
      )}
    </div>
  );
}

// ── The animated wizard ──────────────────────────────────────────────

function BuildAgentsWizard({ threadId, model, onClose }: {
  threadId: string;
  model: string;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<'fetching' | 'review' | 'running' | 'finished'>('fetching');
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<WizardStep[]>([]);
  const [active, setActive] = useState(0);

  // Step 1: fetch suggestions
  useEffect(() => {
    void (async () => {
      const r = await apiFetch<any>(`/api/bpm-analyzer/threads/${threadId}/suggest-agents`, {
        method: 'POST', body: JSON.stringify({ model }),
      });
      if (r.error || !r.data?.agents) {
        setError(r.error || 'Could not extract agent suggestions');
        return;
      }
      const specs: AgentSpec[] = r.data.agents;
      setSteps(specs.map(s => ({ spec: s, stage: 'review' })));
      setPhase('review');
    })();
  }, [threadId, model]);

  const runStep = async (idx: number, action: 'build' | 'skip') => {
    setSteps(prev => prev.map((s, i) => i === idx ? { ...s, stage: action === 'skip' ? 'skipped' : 'synth' } : s));
    if (action === 'skip') {
      goNext(idx);
      return;
    }
    // synth
    await new Promise(r => setTimeout(r, 400)); // let the animation breathe
    setSteps(prev => prev.map((s, i) => i === idx ? { ...s, stage: 'creating' } : s));
    const r = await apiFetch<any>(`/api/bpm-analyzer/threads/${threadId}/build-and-test`, {
      method: 'POST', body: JSON.stringify({ spec: steps[idx].spec }),
    });
    if (r.error || !r.data) {
      setSteps(prev => prev.map((s, i) => i === idx ? {
        ...s, stage: 'done',
        test: { ok: false, error: r.error || 'Build failed' },
      } : s));
      goNext(idx);
      return;
    }
    const data = r.data;
    setSteps(prev => prev.map((s, i) => i === idx ? { ...s, stage: 'testing', agent: data.agent, synth: data.synthetic_input } : s));
    await new Promise(r => setTimeout(r, 500));
    setSteps(prev => prev.map((s, i) => i === idx ? {
      ...s, stage: 'done',
      test: data.test_result,
    } : s));
    goNext(idx);
  };

  const goNext = (idx: number) => {
    if (idx + 1 < steps.length) {
      setTimeout(() => setActive(idx + 1), 800);
    } else {
      setTimeout(() => setPhase('finished'), 500);
    }
  };

  const created = steps.filter(s => s.agent).length;
  const failed = steps.filter(s => s.test && !s.test.ok).length;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-6" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={e => e.stopPropagation()}
        className="bg-[#0B0F19] border border-violet-500/40 rounded-2xl max-w-5xl w-full max-h-[90vh] flex flex-col shadow-2xl shadow-violet-500/20 overflow-hidden"
      >
        {/* Glowing header */}
        <header className="relative p-6 border-b border-slate-800/60 bg-gradient-to-br from-violet-500/10 via-slate-900 to-cyan-500/10 overflow-hidden">
          <motion.div
            className="absolute inset-0 opacity-30"
            animate={{ background: [
              'radial-gradient(circle at 0% 0%, rgba(139,92,246,0.4) 0%, transparent 50%)',
              'radial-gradient(circle at 100% 100%, rgba(6,182,212,0.4) 0%, transparent 50%)',
              'radial-gradient(circle at 0% 0%, rgba(139,92,246,0.4) 0%, transparent 50%)',
            ] }}
            transition={{ duration: 6, repeat: Infinity }}
          />
          <div className="relative flex items-start justify-between">
            <div>
              <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                <Wand2 className="w-6 h-6 text-violet-300" />
                Build Agents from this BPM
              </h2>
              <p className="text-sm text-slate-400 mt-1.5">
                The analyst designs each agent, generates grounded synthetic test data, creates the agent as a draft, and runs a smoke test — all in front of you.
              </p>
            </div>
            <button onClick={onClose} className="p-2 text-slate-500 hover:text-white">
              <X className="w-5 h-5" />
            </button>
          </div>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {phase === 'fetching' && (
            <div className="flex flex-col items-center justify-center py-16">
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
                className="w-16 h-16 rounded-full bg-gradient-to-r from-violet-500 to-cyan-500 flex items-center justify-center"
              >
                <Sparkles className="w-8 h-8 text-white" />
              </motion.div>
              <p className="text-sm text-white mt-4 font-semibold">Reading the diagram…</p>
              <p className="text-xs text-slate-500 mt-1">Extracting structured agent specifications from the analysis</p>
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
              <AlertTriangle className="w-4 h-4 inline mr-2" />
              {error}
            </div>
          )}

          {phase !== 'fetching' && steps.length > 0 && (
            <>
              {/* Progress bar */}
              <div className="mb-6">
                <div className="flex justify-between text-[11px] text-slate-400 mb-1">
                  <span>Agent {Math.min(active + 1, steps.length)} of {steps.length}</span>
                  <span>{created} created · {failed} failed · {steps.filter(s => s.stage === 'skipped').length} skipped</span>
                </div>
                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-gradient-to-r from-violet-500 to-cyan-500"
                    animate={{ width: `${((active + (phase === 'finished' ? 1 : 0)) / steps.length) * 100}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
              </div>

              {/* Stack of agent cards */}
              <div className="space-y-4">
                {steps.map((s, i) => (
                  <AgentStepCard
                    key={i}
                    step={s}
                    active={i === active && phase !== 'finished'}
                    onConfirm={() => runStep(i, 'build')}
                    onSkip={() => runStep(i, 'skip')}
                  />
                ))}
              </div>

              {phase === 'finished' && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="mt-8 rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-6 text-center"
                >
                  <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
                  <h3 className="text-lg font-bold text-white">Done!</h3>
                  <p className="text-sm text-emerald-100 mt-1">
                    Created <strong>{created}</strong> draft agent{created !== 1 ? 's' : ''}
                    {failed > 0 && <> · <span className="text-rose-300">{failed} smoke-test failure{failed !== 1 ? 's' : ''}</span></>}
                  </p>
                  <div className="mt-4 flex gap-2 justify-center">
                    <a href="/agents" className="px-4 py-2 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-100 text-xs font-semibold inline-flex items-center gap-1.5 hover:bg-emerald-500/30">
                      Open Agents <ExternalLink className="w-3 h-3" />
                    </a>
                    <button onClick={onClose} className="px-4 py-2 rounded-lg bg-slate-800/60 border border-slate-700 text-slate-300 text-xs">Close</button>
                  </div>
                </motion.div>
              )}
            </>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function BuildingPipelineViz({
  tools, model, stage, synthInput, output,
}: {
  tools: string[];
  model: string;
  stage: WizardStage;
  synthInput?: string;
  output?: string;
}) {
  // Keep the diagram readable
  const nodes = [
    { kind: 'input' as const, label: 'Input', sub: synthInput?.slice(0, 80) },
    ...(tools.length > 0 ? tools : ['llm_call']).map(t => ({ kind: 'tool' as const, label: t, sub: '' })),
    { kind: 'model' as const, label: model, sub: 'reasoning core' },
    { kind: 'output' as const, label: 'Output', sub: output?.slice(0, 80) },
  ];

  // How many nodes are currently visible — drives the staggered entrance
  const visibleCount = (() => {
    if (stage === 'review' || stage === 'idle') return 0;
    if (stage === 'synth') return 1;
    if (stage === 'creating') return Math.min(nodes.length - 1, 1 + tools.length + 1);
    if (stage === 'testing' || stage === 'done') return nodes.length;
    return 0;
  })();

  const colorFor = (kind: string) => ({
    input: '#06b6d4',
    tool: '#a855f7',
    model: '#f59e0b',
    output: '#10b981',
  }[kind] || '#64748b');

  const iconFor = (kind: string) => ({
    input: ArrowRight,
    tool: Wrench,
    model: Cpu,
    output: CheckCircle2,
  }[kind] || ChevronRight);

  return (
    <div className="mt-3 rounded-xl border border-slate-700/40 bg-slate-950/60 p-4 overflow-hidden">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Live build</div>
      <div className="relative">
        <div className="flex items-center gap-2 flex-wrap">
          {nodes.map((n, i) => {
            const visible = i < visibleCount;
            const Icon = iconFor(n.kind);
            const c = colorFor(n.kind);
            return (
              <div key={i} className="flex items-center gap-2">
                <AnimatePresence>
                  {visible && (
                    <motion.div
                      initial={{ opacity: 0, scale: 0.4, y: 12 }}
                      animate={{ opacity: 1, scale: 1, y: 0 }}
                      exit={{ opacity: 0, scale: 0.4 }}
                      transition={{ type: 'spring', stiffness: 220, damping: 16, delay: i * 0.08 }}
                      className="rounded-lg border px-2.5 py-1.5 min-w-[100px] max-w-[180px] relative"
                      style={{
                        borderColor: c + '66',
                        background: c + '14',
                        boxShadow: stage === 'testing' && i === Math.floor((Date.now() / 800) % nodes.length)
                          ? `0 0 16px ${c}` : `0 0 0 ${c}00`,
                      }}
                    >
                      <div className="flex items-center gap-1.5">
                        <Icon className="w-3 h-3 flex-shrink-0" style={{ color: c }} />
                        <span className="text-[10px] font-mono text-white truncate">{n.label}</span>
                      </div>
                      {n.sub && (
                        <p className="text-[9px] text-slate-500 truncate mt-0.5" title={n.sub}>{n.sub}</p>
                      )}
                      {/* glow pulse on entrance */}
                      <motion.div
                        className="absolute inset-0 rounded-lg pointer-events-none"
                        initial={{ boxShadow: `0 0 0px ${c}` }}
                        animate={{ boxShadow: [`0 0 0px ${c}`, `0 0 18px ${c}99`, `0 0 0px ${c}`] }}
                        transition={{ duration: 1.2, delay: i * 0.08 }}
                      />
                    </motion.div>
                  )}
                </AnimatePresence>
                {/* connector */}
                {visible && i < nodes.length - 1 && (
                  <motion.svg
                    width="28" height="14" viewBox="0 0 28 14"
                    initial={{ opacity: 0 }} animate={{ opacity: i + 1 < visibleCount ? 1 : 0 }}
                    transition={{ duration: 0.4, delay: i * 0.08 + 0.15 }}
                  >
                    <motion.line
                      x1="0" y1="7" x2="22" y2="7"
                      stroke={colorFor(nodes[i + 1].kind)} strokeWidth="1.5" strokeDasharray="4 3"
                      initial={{ pathLength: 0 }} animate={{ pathLength: 1 }}
                      transition={{ duration: 0.5, delay: i * 0.08 + 0.15 }}
                    />
                    <polygon points="22,3 28,7 22,11" fill={colorFor(nodes[i + 1].kind)} />
                  </motion.svg>
                )}
              </div>
            );
          })}
        </div>
        {stage === 'testing' && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="text-[10px] text-amber-300 mt-3 inline-flex items-center gap-1.5"
          >
            <motion.span
              animate={{ x: [0, 6, 0] }} transition={{ duration: 1, repeat: Infinity }}
            >▶</motion.span>
            Synthetic input flowing through the pipeline
          </motion.div>
        )}
      </div>
    </div>
  );
}

function AgentStepCard({ step, active, onConfirm, onSkip }: {
  step: WizardStep;
  active: boolean;
  onConfirm: () => void;
  onSkip: () => void;
}) {
  const { spec, stage, agent, synth, test } = step;
  const stageLabel = {
    idle: 'Queued',
    fetching: 'Loading',
    review: 'Awaiting your decision',
    synth: 'Generating synthetic test data…',
    creating: 'Creating agent…',
    testing: 'Smoke-testing agent…',
    done: test?.ok ? 'Created + smoke-tested' : (test ? 'Created (smoke-test failed)' : 'Done'),
    skipped: 'Skipped',
  }[stage];
  const stageColor = stage === 'done' && test?.ok ? 'emerald' :
                     stage === 'skipped' ? 'slate' :
                     stage === 'done' ? 'amber' : 'violet';

  return (
    <motion.div
      layout
      animate={{
        scale: active ? 1 : 0.98,
        opacity: stage === 'skipped' ? 0.45 : 1,
      }}
      className={`rounded-xl border p-4 transition-all ${
        active ? 'border-violet-500/60 bg-violet-500/5 shadow-lg shadow-violet-500/10'
               : `border-slate-700/60 bg-slate-900/40`
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">{spec.lane || spec.category}</span>
            <span className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-${stageColor}-500/15 text-${stageColor}-300 border border-${stageColor}-500/30`}>
              {stageLabel}
            </span>
          </div>
          <h3 className="text-base font-semibold text-white mt-1">{spec.name}</h3>
          <p className="text-xs text-slate-400 mt-1 line-clamp-2">{spec.description}</p>
          {spec.why && <p className="text-[11px] text-violet-300 mt-1.5"><strong>Why agent:</strong> {spec.why}</p>}
        </div>
        {stage === 'review' && active && (
          <div className="flex flex-col gap-2 shrink-0">
            <button onClick={onConfirm} className="px-3 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 text-xs font-semibold hover:bg-emerald-500/30 inline-flex items-center gap-1">
              <Check className="w-3 h-3" /> Build
            </button>
            <button onClick={onSkip} className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 text-xs hover:text-white inline-flex items-center gap-1">
              <X className="w-3 h-3" /> Skip
            </button>
          </div>
        )}
      </div>

      {/* Spec details */}
      <div className="grid grid-cols-3 gap-2 mt-3 text-[11px]">
        <div className="bg-slate-900/60 border border-slate-700/40 rounded px-2 py-1.5 inline-flex items-center gap-1.5">
          <Cpu className="w-3 h-3 text-cyan-400" />
          <span className="text-slate-300 truncate font-mono">{spec.model}</span>
        </div>
        <div className="bg-slate-900/60 border border-slate-700/40 rounded px-2 py-1.5 inline-flex items-center gap-1.5 col-span-2">
          <Wrench className="w-3 h-3 text-amber-400" />
          <span className="text-slate-400 truncate">{(spec.tools && spec.tools.length > 0) ? spec.tools.join(', ') : 'no tools'}</span>
        </div>
      </div>

      {/* Live progress label */}
      <AnimatePresence>
        {(stage === 'synth' || stage === 'creating' || stage === 'testing') && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-3 flex items-center gap-2 text-[11px] text-violet-300"
          >
            {stage === 'synth' && <FlaskConical className="w-3.5 h-3.5 animate-pulse" />}
            {stage === 'creating' && <Sparkles className="w-3.5 h-3.5 animate-pulse" />}
            {stage === 'testing' && <Zap className="w-3.5 h-3.5 animate-pulse" />}
            <span>{stageLabel}</span>
            <Loader2 className="w-3 h-3 animate-spin ml-auto" />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Stunning live build visualisation — only renders when assembly is active or done */}
      {(stage === 'synth' || stage === 'creating' || stage === 'testing' || stage === 'done') && (
        <BuildingPipelineViz
          tools={spec.tools || []}
          model={spec.model}
          stage={stage}
          synthInput={synth?.input}
          output={test?.output}
        />
      )}

      {/* Result panels */}
      <AnimatePresence>
        {stage === 'done' && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 space-y-2"
          >
            {agent && (
              <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/30 p-2.5 text-[11px] flex items-center gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="text-emerald-100">Created draft <code className="text-emerald-300">{agent.slug}</code></span>
                <a href={`/agents/${agent.id}`} target="_blank" rel="noreferrer" className="ml-auto text-emerald-300 hover:text-emerald-200 inline-flex items-center gap-1">
                  Open <ExternalLink className="w-2.5 h-2.5" />
                </a>
              </div>
            )}
            {synth && (
              <div className="rounded-lg bg-slate-900/60 border border-slate-700/40 p-2.5 text-[11px]">
                <div className="text-slate-500 uppercase tracking-wider text-[9px] mb-1">Synthetic test input</div>
                <p className="text-slate-300 text-[11px] mb-1 italic">{synth.description}</p>
                <pre className="text-slate-400 whitespace-pre-wrap break-words max-h-24 overflow-y-auto">{synth.input}</pre>
              </div>
            )}
            {test && (
              <div className={`rounded-lg p-2.5 text-[11px] border ${
                test.ok ? 'bg-emerald-500/5 border-emerald-500/30' : 'bg-rose-500/10 border-rose-500/40'
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  {test.ok ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />}
                  <span className={test.ok ? 'text-emerald-200' : 'text-rose-200'}>
                    {test.ok ? 'Smoke test passed' : `Smoke test failed: ${test.error}`}
                  </span>
                  {test.ok && (
                    <span className="ml-auto text-slate-500">
                      ${(test.cost || 0).toFixed(4)} · {test.duration_ms}ms
                    </span>
                  )}
                </div>
                {test.ok && test.output && (
                  <pre className="text-slate-300 text-[11px] whitespace-pre-wrap break-words max-h-32 overflow-y-auto bg-slate-950/40 rounded p-2 mt-1">
                    {test.output.slice(0, 600)}{test.output.length > 600 ? '…' : ''}
                  </pre>
                )}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
