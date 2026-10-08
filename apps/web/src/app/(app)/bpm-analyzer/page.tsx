'use client';


import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Workflow, Upload, Loader2, Sparkles, Check, X, MessagesSquare,
  Trash2, ChevronRight, Send, Bot, FileText, Wand2, FlaskConical,
  CheckCircle2, AlertTriangle, ExternalLink, Zap, Cpu, Wrench, ArrowRight,
  Download, Image as ImageIcon, Music, Film, FileType, PanelLeft, Info, PlayCircle,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useAuth } from '@/contexts/AuthContext';
import VisionModelPicker from '@/components/bpm-analyzer/VisionModelPicker';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';

type ThreadStatus = 'empty' | 'analyzing' | 'stalled' | 'failed' | 'ready';

interface Thread {
  id: string;
  title: string;
  message_count: number;
  last_message_preview: string | null;
  created_at: string;
  updated_at: string;
  status?: ThreadStatus;
  has_report?: boolean;
  model_used?: string | null;
}

interface Route {
  provider?: string | null;
  requested_model?: string | null;
  served_model?: string | null;
  fallback_from?: string | null;
  fallback_reason?: string | null;
  route_note?: string | null;
}

interface Msg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  model_used?: string | null;
  cost?: number;
  route?: Route | null;
  created_at?: string | null;
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

interface TestResult {
  ok: boolean;
  skipped?: boolean;
  output?: string;
  error?: string | null;
  cost?: number;
  duration_ms?: number;
}

interface WizardStep {
  spec: AgentSpec;
  stage: WizardStage;
  agent?: { id: string; slug: string; name: string };
  synth?: { description: string; input: string };
  test?: TestResult;
  buildError?: string;
}

type WizardPhase = 'fetching' | 'review' | 'running' | 'finished';

interface WizardState {
  phase: WizardPhase;
  steps: WizardStep[];
  active: number;
}

interface Banner {
  id: number;
  kind: 'error' | 'info' | 'warning';
  text: string;
}

const PROVIDER_NAMES: Record<string, string> = {
  claude_subscription: 'Claude subscription',
  anthropic: 'Anthropic API key',
  openai: 'OpenAI',
  google: 'Google Gemini',
};

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
            <code className="text-slate-200 font-mono whitespace-pre-wrap break-words">{buf.join('\n')}</code>
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
function mimeIcon(name: string) {
  const n = name.toLowerCase();
  if (/\.(png|jpe?g|gif|webp|bmp)$/.test(n)) return ImageIcon;
  if (/\.(mp3|wav|ogg|m4a|flac|aac)$/.test(n)) return Music;
  if (/\.(mp4|webm|mov|avi|mkv)$/.test(n)) return Film;
  if (n.endsWith('.pdf')) return FileText;
  return FileType;
}

// sidebar previews are plain text, older rows stored raw markdown
function stripMd(s: string): string {
  return s
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, '')
    .replace(/^\s*\|?[\s:|-]+\|?\s*$/gm, ' ')
    .replace(/\|/g, ' ')
    .replace(/(\*\*|__|~~)(\S.*?)\1/g, '$2')
    .replace(/(^|[^\w*])\*(\S[^*]*?)\*(?!\w)/g, '$1$2')
    .replace(/\s+/g, ' ')
    .trim();
}

function readThreadParam(): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('thread');
}

function writeThreadParam(id: string | null) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  if (id) url.searchParams.set('thread', id);
  else url.searchParams.delete('thread');
  window.history.replaceState(window.history.state, '', url.toString());
}

function authHeader(): Record<string, string> {
  const tok = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const POLL_MS = 4000;
const SAMPLE_PATH = '/samples/bpm-vendor-invoice-approval.md';

const REPORT_SECTIONS = [
  'A short summary of the process, its lanes and decision points',
  'A step by step table rating each step: no automation, a tool, or an agent',
  'The recommended agents, with inputs, tools, model and guardrails',
  'Where agents do not make sense, and why',
  'Security, audit and human-review placement',
  'A suggested technology stack',
  'A phased rollout plan',
  'Risks and open questions for the process owner',
];

const FOLLOW_UPS = [
  'Which step should we automate first, and why?',
  'Estimate the cost per case for phase 1',
  'Where does a human need to stay in the loop?',
  'What would change if volume doubled?',
];

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const s = Math.max(0, Math.floor((now - since) / 1000));
  const text = s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
  return <span>{text} elapsed</span>;
}

function RouteBadge({ m }: { m: Msg }) {
  const r = m.route;
  if (!r) return null;
  if (r.fallback_from) {
    const from = PROVIDER_NAMES[r.fallback_from] || r.fallback_from;
    const to = PROVIDER_NAMES[r.provider || ''] || r.provider || 'another provider';
    const billed = r.provider && r.provider !== 'claude_subscription' ? ', billed per token' : '';
    return (
      <div className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200 flex items-start gap-2" data-testid="fallback-notice">
        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span>
          {from} was {r.fallback_reason || 'unavailable'}, so this reply came from {r.served_model || 'a fallback model'} on {to}{billed}.
        </span>
      </div>
    );
  }
  if (r.route_note) {
    return (
      <div className="mb-3 rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-2 text-[11px] text-slate-300 flex items-start gap-2">
        <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span>{r.route_note}. This reply came from {r.served_model} on {PROVIDER_NAMES[r.provider || ''] || r.provider}.</span>
      </div>
    );
  }
  return null;
}

// ── Page ─────────────────────────────────────────────────────────────

export default function BPMAnalyzerPage() {
  const { user } = useAuth();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [threadMeta, setThreadMeta] = useState<Thread | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [notices, setNotices] = useState<string[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);
  const [uploadingName, setUploadingName] = useState<string | null>(null);
  const [model, setModel] = useState('');
  const [chatInput, setChatInput] = useState('');
  const [sending, setSending] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [banners, setBanners] = useState<Banner[]>([]);
  const [uploadStartedAt, setUploadStartedAt] = useState(() => Date.now());
  const [sendStartedAt, setSendStartedAt] = useState(() => Date.now());
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<string | null>(null);
  const wizardCache = useRef<Map<string, WizardState>>(new Map());
  const [wizardOpen, setWizardOpen] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  // the analysis that just finished from an upload, for the next steps card
  const [freshId, setFreshId] = useState<string | null>(null);
  const uploading = uploadingName !== null;

  const pushBanner = useCallback((kind: Banner['kind'], text: string) => {
    const id = Date.now() + Math.random();
    setBanners(prev => [...prev.filter(b => b.text !== text), { id, kind, text }]);
    if (kind !== 'error') setTimeout(() => setBanners(prev => prev.filter(b => b.id !== id)), 8000);
  }, []);

  const refreshThreads = useCallback(async () => {
    const r = await apiFetch<{ threads: Thread[] }>('/api/bpm-analyzer/threads', { silent: true });
    if (r.data?.threads) setThreads(r.data.threads);
    return r.data?.threads || [];
  }, []);

  const loadThread = useCallback(async (id: string, quiet = false) => {
    if (!quiet) setLoadingThread(true);
    const r = await apiFetch<{ thread: Thread; messages: Msg[]; notices?: string[] }>(
      `/api/bpm-analyzer/threads/${id}`, { silent: true },
    );
    if (activeRef.current !== id) return null;
    if (!quiet) setLoadingThread(false);
    if (!r.data) {
      if (r.errorDetail?.code === 404) {
        pushBanner('error', 'That analysis was not found. It may have been deleted.');
        setActiveId(null);
      } else if (!quiet) {
        pushBanner('error', r.error || 'Could not load this analysis');
      }
      return null;
    }
    setMessages(r.data.messages || []);
    setThreadMeta(r.data.thread);
    setNotices(r.data.notices || []);
    return r.data.thread;
  }, [pushBanner]);

  // threads, model default, and the thread named in the URL
  useEffect(() => {
    void (async () => {
      await refreshThreads();
      setLoadingThreads(false);
      const m = await apiFetch<{ default?: string }>('/api/bpm-analyzer/models', { silent: true });
      if (m.data?.default) setModel(prev => prev || m.data!.default!);
    })();
    const fromUrl = readThreadParam();
    if (fromUrl) setActiveId(fromUrl);
  }, [refreshThreads]);

  useEffect(() => {
    activeRef.current = activeId;
    writeThreadParam(activeId);
    setConfirmDelete(null);
    if (!activeId) { setMessages([]); setThreadMeta(null); setNotices([]); return; }
    setMessages([]);
    setThreadMeta(null);
    void loadThread(activeId);
  }, [activeId, loadThread]);

  // reload during an analysis lands here: poll until the reply is in
  const analyzing = threadMeta?.status === 'analyzing';
  useEffect(() => {
    if (!activeId || !analyzing || sending) return;
    const t = setTimeout(() => {
      void loadThread(activeId, true).then(th => {
        if (th && th.status !== 'analyzing') void refreshThreads();
      });
    }, POLL_MS);
    return () => clearTimeout(t);
  }, [activeId, analyzing, sending, threadMeta, loadThread, refreshThreads]);

  const pending = sending || analyzing;
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }));
  }, [messages.length, pending, activeId]);

  const openThread = (id: string) => {
    setActiveId(id);
    setDrawerOpen(false);
  };

  // Multimodal upload — accepts PDFs, images, audio, video, DOCX, plain text.
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
      pushBanner('error', `${name} is not a supported file. Upload a PDF, image, audio, video, DOCX or plain-text file.`);
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      pushBanner('error', `${name} is larger than 50 MB. Trim it and upload again.`);
      return;
    }
    const title = name.replace(/\.[^.]+$/, '');
    setUploadStartedAt(Date.now());
    setUploadingName(name);
    setActiveId(null);
    setDrawerOpen(false);
    const startedAt = Date.now();
    let done = false;
    // the thread exists before the reply, open it so the user sees progress
    const pickUp = setTimeout(async () => {
      if (done) return;
      const list = await refreshThreads();
      const t = list.find(x => x.title === title && x.status === 'analyzing'
        && new Date(x.created_at).getTime() >= startedAt - 60_000);
      if (t && !done && activeRef.current === null) setActiveId(t.id);
    }, 2500);
    const fd = new FormData();
    fd.append('file', file);
    if (model) fd.append('model', model);
    fd.append('title', title);
    try {
      const r = await fetch(`${API_URL}/api/bpm-analyzer/upload`, {
        method: 'POST', body: fd, headers: authHeader(),
      });
      const j = await r.json().catch(() => ({}));
      done = true;
      if (!r.ok || !j.data) {
        const tid = j?.error?.details?.thread_id as string | undefined;
        pushBanner('error', j?.error?.message || `Upload failed (HTTP ${r.status})`);
        await refreshThreads();
        if (tid) setActiveId(tid);
      } else {
        const tid = j.data.thread.id as string;
        setFreshId(tid);
        for (const n of (j.data.notices || []) as string[]) pushBanner('warning', n);
        await refreshThreads();
        if (activeRef.current === tid) void loadThread(tid, true);
        else setActiveId(tid);
      }
    } catch (e: unknown) {
      done = true;
      pushBanner('error', `Upload failed: ${e instanceof Error ? e.message : 'network error'}. If the analysis started it will appear in the list.`);
      void refreshThreads();
    } finally {
      clearTimeout(pickUp);
      setUploadingName(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const downloadPdf = async () => {
    if (!activeId || downloadingPdf) return;
    setDownloadingPdf(true);
    try {
      const r = await fetch(`${API_URL}/api/bpm-analyzer/threads/${activeId}/export-pdf`, {
        method: 'POST', headers: authHeader(),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j?.error?.message || `HTTP ${r.status}`);
      }
      const blob = await r.blob();
      const cd = r.headers.get('content-disposition') || '';
      const fnameMatch = cd.match(/filename="?([^";]+)"?/i);
      const fname = fnameMatch ? fnameMatch[1] : `${(threadMeta?.title || 'bpm-analysis').replace(/[^\w.-]+/g, '_')}.pdf`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      pushBanner('error', `PDF export failed: ${e instanceof Error ? e.message : 'unknown error'}`);
    }
    setDownloadingPdf(false);
  };

  const sendChat = async () => {
    const txt = chatInput.trim();
    if (!txt || !activeId || pending) return;
    const tid = activeId;
    setMessages(prev => [...prev, { id: 'temp', role: 'user', content: txt }]);
    setChatInput('');
    setSendStartedAt(Date.now());
    setSending(true);
    const r = await apiFetch<{ thread: Thread; user_message: Msg; assistant_message: Msg }>(
      `/api/bpm-analyzer/chat/${tid}/turn`,
      { method: 'POST', body: JSON.stringify({ content: txt }), throwOnError: false, silent: true },
    );
    setSending(false);
    if (activeRef.current !== tid) { void refreshThreads(); return; }
    if (r.data) {
      setMessages(prev => [...prev.filter(m => m.id !== 'temp'), r.data!.user_message, r.data!.assistant_message]);
      setThreadMeta(r.data.thread);
    } else {
      if (r.errorDetail?.code === 409) {
        setChatInput(txt);
        pushBanner('info', r.error || 'The analyst is still answering the last message.');
      }
      // the server keeps the question and the error reply, show what it stored
      await loadThread(tid, true);
    }
    void refreshThreads();
  };

  const deleteThread = async (id: string) => {
    setConfirmDelete(null);
    setThreads(prev => prev.filter(t => t.id !== id));
    if (activeId === id) setActiveId(null);
    wizardCache.current.delete(id);
    const r = await apiFetch(`/api/bpm-analyzer/threads/${id}`, { method: 'DELETE', throwOnError: false, silent: true });
    if (r.error) pushBanner('error', `Delete failed: ${r.error}`);
    await refreshThreads();
  };

  const trySample = async () => {
    try {
      const r = await fetch(SAMPLE_PATH);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const text = await r.text();
      await onUpload(new File([text], 'Vendor invoice approval (sample).md', { type: 'text/markdown' }));
    } catch {
      pushBanner('error', 'The sample file could not be loaded. Reload the page and try again, or upload your own file.');
    }
  };

  const hasReport = !!threadMeta?.has_report;
  const lastUser = [...messages].reverse().find(m => m.role === 'user');
  const pendingSince = sending
    ? sendStartedAt
    : (lastUser?.created_at ? Date.parse(lastUser.created_at) : uploadStartedAt);
  const UploadIcon = uploadingName ? mimeIcon(uploadingName) : Upload;

  const threadList = (
    <div className="flex-1 min-h-0 overflow-y-auto p-2">
      {loadingThreads && <div className="text-center py-6"><Loader2 className="w-4 h-4 text-violet-400 animate-spin mx-auto" /></div>}
      {!loadingThreads && threads.length === 0 && (
        <div className="text-center py-8 text-[11px] text-slate-500">
          <MessagesSquare className="w-6 h-6 mx-auto mb-2 text-slate-700" />
          No analyses yet. Upload a file to start one.
        </div>
      )}
      {threads.map(t => (
        <div
          key={t.id}
          role="button"
          tabIndex={0}
          onClick={() => openThread(t.id)}
          onKeyDown={e => { if (e.key === 'Enter') openThread(t.id); }}
          className={`group rounded-lg p-2 cursor-pointer transition-colors mb-1 ${
            activeId === t.id ? 'bg-violet-500/10 border border-violet-500/30' : 'hover:bg-slate-800/40 border border-transparent'
          }`}
          data-testid="thread-item"
        >
          {confirmDelete === t.id ? (
            <div className="flex items-center gap-2 text-[11px]" onClick={e => e.stopPropagation()}>
              <span className="text-slate-300 flex-1 truncate">Delete this analysis?</span>
              <button onClick={() => void deleteThread(t.id)} className="px-2 py-0.5 rounded bg-rose-500/20 border border-rose-500/40 text-rose-200 hover:bg-rose-500/30">Delete</button>
              <button onClick={() => setConfirmDelete(null)} className="px-2 py-0.5 rounded border border-slate-700 text-slate-400 hover:text-white">Cancel</button>
            </div>
          ) : (
            <>
              <div className="flex items-start justify-between gap-1">
                <p className="text-[12px] text-slate-200 truncate flex-1" title={t.title}>{t.title}</p>
                <button
                  onClick={e => { e.stopPropagation(); setConfirmDelete(t.id); }}
                  aria-label={`Delete ${t.title}`}
                  className="md:opacity-0 md:group-hover:opacity-100 focus:opacity-100 p-0.5 text-slate-500 hover:text-rose-400"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
              {t.status === 'analyzing' ? (
                <p className="text-[10px] text-violet-300 mt-0.5 inline-flex items-center gap-1"><Loader2 className="w-2.5 h-2.5 animate-spin" /> Analyzing…</p>
              ) : t.last_message_preview ? (
                <p className={`text-[10px] truncate mt-0.5 ${t.status === 'failed' ? 'text-rose-300' : 'text-slate-500'}`}>{stripMd(t.last_message_preview)}</p>
              ) : null}
              <p className="text-[9px] text-slate-600 mt-0.5">{t.message_count} msgs · {new Date(t.updated_at).toLocaleDateString()}</p>
            </>
          )}
        </div>
      ))}
    </div>
  );

  return (
    <div className="-m-3 md:-m-6 h-[calc(100%+1.5rem)] md:h-[calc(100%+3rem)] bg-[#0B0F19] flex relative overflow-hidden">
      {drawerOpen && (
        <div className="md:hidden absolute inset-0 z-20 bg-black/60" onClick={() => setDrawerOpen(false)} aria-hidden />
      )}
      {/* Thread list: a drawer below md, a fixed column above */}
      <aside
        className={`absolute md:static inset-y-0 left-0 z-30 w-72 max-w-[85%] md:max-w-none bg-[#0B0F19] border-r border-slate-800/50 flex flex-col shrink-0 min-h-0 transition-transform duration-200 ${
          drawerOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        }`}
        data-testid="thread-drawer"
      >
        <div className="p-4 border-b border-slate-800/50">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500/30 to-cyan-500/30 border border-violet-500/40 flex items-center justify-center">
              <Workflow className="w-4 h-4 text-violet-300" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-bold text-white leading-none">BPM Analyzer</p>
              <p className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Multimodal agent</p>
            </div>
            <button onClick={() => setDrawerOpen(false)} className="md:hidden p-1 text-slate-500 hover:text-white" aria-label="Close analyses">
              <X className="w-4 h-4" />
            </button>
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
            onChange={e => { const f = e.target.files?.[0]; if (f) void onUpload(f); }}
          />
          <p className="text-[10px] text-slate-500 mt-2 leading-snug">
            PDF (first 20 pages), image, audio, video, DOCX or text up to 50 MB. Audio and video are read by Gemini.
          </p>
          <div className="mt-3">
            <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1">Vision model</label>
            <VisionModelPicker value={model} onChange={setModel} isAdmin={user?.role === 'admin'} />
          </div>
        </div>
        {threadList}
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0 min-h-0">
        <div className="border-b border-slate-800/50 px-4 md:px-6 py-3 md:py-4 shrink-0">
          <button
            onClick={() => setDrawerOpen(true)}
            className="md:hidden mb-2 inline-flex items-center gap-1.5 p-1.5 rounded-lg border border-slate-700 text-slate-300 hover:text-white text-xs"
            aria-label="Show analyses"
            data-testid="open-drawer"
          >
            <PanelLeft className="w-4 h-4" /> Analyses
          </button>
          <PageHeader
            compact
            title={<span className="block truncate">{threadMeta?.title || 'BPM Process Analyst'}</span>}
            purpose="Upload how a business process works and find out which steps an AI agent should handle. For process owners and builders."
            icon={Workflow}
            iconClassName="text-violet-300"
            storageKey="bpm-analyzer"
            docSlug="05-ui/03-page-catalogue"
            steps={[
              'Upload a diagram, a written procedure, or a recorded walkthrough.',
              'The analyst reads it and writes a report in 1 to 3 minutes.',
              'Ask follow up questions about any step in the chat.',
              'Build Agents turns the suggestions into draft agents, each tested once.',
            ]}
            primaryAction={activeId && hasReport
              ? { label: 'Build Agents', icon: Wand2, onClick: () => setWizardOpen(true), disabled: pending, testId: 'open-wizard' }
              : { label: uploading ? 'Analyzing…' : 'Upload a process', icon: uploading ? Loader2 : Upload, busy: uploading, onClick: () => fileInputRef.current?.click(), testId: 'bpm-upload-primary' }}
            secondaryAction={activeId && hasReport
              ? { label: downloadingPdf ? 'Building PDF…' : 'Download PDF', icon: downloadingPdf ? Loader2 : Download, busy: downloadingPdf, onClick: () => void downloadPdf(), title: 'Download the full analysis as a PDF', testId: 'download-pdf' }
              : undefined}
          />
        </div>

        {(banners.length > 0 || notices.length > 0) && (
          <div className="px-4 md:px-6 pt-3 space-y-2 shrink-0" data-testid="bpm-banners">
            {banners.map(b => (
              <div
                key={b.id}
                role={b.kind === 'error' ? 'alert' : 'status'}
                className={`rounded-lg border px-3 py-2 text-xs flex items-start gap-2 ${
                  b.kind === 'error' ? 'border-rose-500/40 bg-rose-500/10 text-rose-200'
                    : b.kind === 'warning' ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
                      : 'border-cyan-500/40 bg-cyan-500/10 text-cyan-100'
                }`}
              >
                {b.kind === 'info' ? <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" /> : <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />}
                <span className="flex-1">{b.text}</span>
                <button onClick={() => setBanners(prev => prev.filter(x => x.id !== b.id))} aria-label="Dismiss" className="opacity-70 hover:opacity-100">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
            {activeId && notices.map(n => (
              <div key={n} className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200 flex items-start gap-2" data-testid="truncation-notice">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{n}</span>
              </div>
            ))}
          </div>
        )}

        {activeId && freshId === activeId && hasReport && (
          <div className="px-4 md:px-6 pt-3 shrink-0">
            <NextSteps
              title="Your analysis is ready. What next?"
              testId="bpm-next-steps"
              onDismiss={() => setFreshId(null)}
              steps={[
                { id: 'build', label: 'Build the agents', hint: 'Turn the suggested agents into tested drafts.', icon: Wand2, onClick: () => { setFreshId(null); setWizardOpen(true); } },
                { id: 'ask', label: 'Ask a follow up', hint: 'Question any step or lane in the chat.', icon: MessagesSquare, onClick: () => { setFreshId(null); inputRef.current?.focus(); } },
                { id: 'pdf', label: 'Download the PDF', hint: 'Share the full report with your team.', icon: Download, onClick: () => { setFreshId(null); void downloadPdf(); } },
              ]}
            />
          </div>
        )}

        {!activeId && uploadingName && (
          <div className="flex-1 flex items-center justify-center p-6">
            <div className="text-center max-w-md">
              <UploadIcon className="w-10 h-10 text-violet-300 mx-auto mb-3" />
              <p className="text-sm text-white font-semibold break-all">Uploading and reading {uploadingName}</p>
              <p className="text-xs text-slate-400 mt-2 inline-flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> <Elapsed since={uploadStartedAt} />
              </p>
              <p className="text-xs text-slate-500 mt-2">
                The thread opens here as soon as the file is read. Writing the report usually takes 1 to 3 minutes, longer for big PDFs or video. You can leave this page and come back, the analysis keeps running.
              </p>
            </div>
          </div>
        )}

        {!activeId && !uploadingName && (
          <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-10" data-testid="bpm-empty-state">
            <div className="max-w-3xl mx-auto">
              <div className="text-center">
                <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-violet-500/20 to-cyan-500/20 border border-violet-500/30 flex items-center justify-center">
                  <Workflow className="w-8 h-8 text-violet-300" />
                </div>
                <h2 className="text-xl font-bold text-white mb-2">Find where AI agents fit in a business process</h2>
                <p className="text-sm text-slate-400">
                  Upload a description of a process. The analyst reads it, judges every step, and tells you which steps an agent should handle, which a simple tool or rule should handle, and which should stay with people. Then it can build the agents it suggests.
                </p>
                <div className="mt-5 flex flex-wrap gap-2 justify-center">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-violet-500 to-cyan-500 text-white text-sm font-semibold hover:shadow-lg hover:shadow-violet-500/30 disabled:opacity-50"
                    data-testid="upload-cta"
                  >
                    <Upload className="w-4 h-4" /> Upload a file
                  </button>
                  <button
                    onClick={() => void trySample()}
                    disabled={uploading}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg border border-violet-500/50 bg-violet-500/10 text-violet-100 text-sm font-semibold hover:bg-violet-500/20 disabled:opacity-50"
                    data-testid="try-sample"
                  >
                    <PlayCircle className="w-4 h-4" /> Try with a sample process
                  </button>
                </div>
                <p className="text-[11px] text-slate-500 mt-2">
                  The sample is a vendor invoice approval procedure.{' '}
                  <a href={SAMPLE_PATH} target="_blank" rel="noreferrer" className="text-violet-300 hover:text-violet-200 underline underline-offset-2">Read it first</a>
                </p>
              </div>

              <div className="grid md:grid-cols-2 gap-3 mt-8 text-left">
                <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
                  <p className="text-xs font-semibold text-white mb-2">What to upload</p>
                  <ul className="space-y-1.5 text-xs text-slate-400">
                    <li className="flex gap-2"><ImageIcon className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-0.5" /> A process diagram, such as a BPMN export or flowchart, as PDF, PNG or JPG. A photo of a whiteboard works too.</li>
                    <li className="flex gap-2"><FileText className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-0.5" /> A written procedure (SOP, runbook, policy) as PDF, DOCX, Markdown or plain text.</li>
                    <li className="flex gap-2"><Film className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-0.5" /> A recorded walkthrough as audio or video. These are read by Gemini.</li>
                  </ul>
                  <p className="text-[11px] text-slate-500 mt-3">Up to 50 MB. For PDFs the first 20 pages are read.</p>
                </div>
                <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
                  <p className="text-xs font-semibold text-white mb-2">What you get back, in 1 to 3 minutes</p>
                  <ol className="space-y-1 text-xs text-slate-400 list-decimal list-inside">
                    {REPORT_SECTIONS.map(s => <li key={s}>{s}</li>)}
                  </ol>
                </div>
              </div>

              <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 mt-3 text-left">
                <p className="text-xs font-semibold text-white mb-2">Then</p>
                <div className="grid sm:grid-cols-3 gap-3 text-xs text-slate-400">
                  <p className="flex gap-2"><MessagesSquare className="w-3.5 h-3.5 text-violet-300 shrink-0 mt-0.5" /> Ask follow-up questions about any step or lane.</p>
                  <p className="flex gap-2"><Wand2 className="w-3.5 h-3.5 text-violet-300 shrink-0 mt-0.5" /> Build the suggested agents as drafts, each tested once with realistic data.</p>
                  <p className="flex gap-2"><Download className="w-3.5 h-3.5 text-violet-300 shrink-0 mt-0.5" /> Download the whole analysis as a PDF to share.</p>
                </div>
                <p className="text-[11px] text-slate-500 mt-3">Your analyses are private to you. Nobody else in your organization can see them.</p>
              </div>
            </div>
          </div>
        )}

        {activeId && (
          <>
            <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-4 md:px-6 py-4 space-y-6" data-testid="bpm-messages">
              {loadingThread && messages.length === 0 && (
                <div className="py-10 text-center"><Loader2 className="w-5 h-5 text-violet-400 animate-spin mx-auto" /></div>
              )}
              {messages.map((m, i) => {
                const isError = m.role === 'assistant' && m.content.startsWith('[error]');
                return (
                  <motion.div
                    key={m.id || i}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={`max-w-4xl ${m.role === 'user' ? 'ml-auto w-fit max-w-full' : ''}`}
                  >
                    {m.role === 'assistant' ? (
                      isError ? (
                        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200 flex items-start gap-2">
                          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                          <span>{m.content.replace(/^\[error\]\s*/, '')}</span>
                        </div>
                      ) : (
                        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 md:p-5 min-w-0">
                          <div className="flex items-center gap-2 mb-3 text-[11px] text-slate-500 flex-wrap">
                            <Bot className="w-3 h-3 text-violet-400" />
                            BPM PROCESS ANALYST
                            {m.model_used && <span className="text-slate-600">· {m.model_used}</span>}
                            {m.route?.provider === 'claude_subscription' && <span className="text-emerald-500/80">· Claude subscription</span>}
                            {typeof m.cost === 'number' && <span className="text-slate-600">· ${m.cost.toFixed(4)}</span>}
                          </div>
                          <RouteBadge m={m} />
                          <MarkdownRich text={m.content} />
                        </div>
                      )
                    ) : (
                      <div className="bg-violet-500/10 border border-violet-500/30 rounded-xl px-4 py-3 text-sm text-white whitespace-pre-wrap break-words">
                        {m.content}
                      </div>
                    )}
                  </motion.div>
                );
              })}
              {pending && (
                <div className="rounded-xl border border-violet-500/30 bg-violet-500/5 px-4 py-3 text-xs text-slate-300 max-w-4xl" data-testid="bpm-pending">
                  <div className="flex items-center gap-2 text-violet-200 font-semibold">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    {sending || messages.some(m => m.role === 'assistant' && !m.content.startsWith('[error]'))
                      ? 'The analyst is answering'
                      : 'Writing the agentification report'}
                    <span className="text-slate-500 font-normal">· <Elapsed since={pendingSince} /></span>
                  </div>
                  <p className="text-slate-400 mt-1">
                    {sending || messages.some(m => m.role === 'assistant' && !m.content.startsWith('[error]'))
                      ? 'Follow-ups usually take 20 to 60 seconds.'
                      : 'A first report usually takes 1 to 3 minutes. You can leave this page, the report will be here when you come back.'}
                  </p>
                </div>
              )}
              {threadMeta?.status === 'stalled' && !pending && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 max-w-4xl">
                  This analysis stopped without a reply, most likely because the server restarted. Ask a follow-up below to retry, or upload the file again.
                </div>
              )}
              {threadMeta?.status === 'failed' && !pending && (
                <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-2 text-xs text-slate-300 max-w-4xl">
                  To retry, ask a follow-up below, pick another model in the list on the left and upload again, or ask an admin to check the model settings if the problem repeats.
                </div>
              )}
              {hasReport && !pending && threadMeta?.status === 'ready' && (
                <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 max-w-4xl" data-testid="next-steps">
                  <p className="text-xs font-semibold text-white mb-3">What next</p>
                  <div className="grid sm:grid-cols-3 gap-2">
                    <button
                      onClick={() => inputRef.current?.focus()}
                      className="text-left rounded-lg border border-slate-700 bg-slate-800/40 hover:border-violet-500/50 px-3 py-2"
                    >
                      <p className="text-xs text-white font-semibold inline-flex items-center gap-1.5"><MessagesSquare className="w-3.5 h-3.5 text-violet-300" /> Ask a follow-up</p>
                      <p className="text-[11px] text-slate-400 mt-0.5">Question any step, lane or recommendation.</p>
                    </button>
                    <button
                      onClick={() => setWizardOpen(true)}
                      className="text-left rounded-lg border border-violet-500/40 bg-violet-500/10 hover:bg-violet-500/20 px-3 py-2"
                    >
                      <p className="text-xs text-white font-semibold inline-flex items-center gap-1.5"><Wand2 className="w-3.5 h-3.5 text-violet-300" /> Build agents</p>
                      <p className="text-[11px] text-slate-400 mt-0.5">Review each suggested agent, create it as a draft and test it once.</p>
                    </button>
                    <button
                      onClick={() => void downloadPdf()}
                      disabled={downloadingPdf}
                      className="text-left rounded-lg border border-slate-700 bg-slate-800/40 hover:border-violet-500/50 px-3 py-2 disabled:opacity-50"
                    >
                      <p className="text-xs text-white font-semibold inline-flex items-center gap-1.5">
                        {downloadingPdf ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5 text-violet-300" />} Download PDF
                      </p>
                      <p className="text-[11px] text-slate-400 mt-0.5">The whole conversation, formatted to share.</p>
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {FOLLOW_UPS.map(q => (
                      <button
                        key={q}
                        onClick={() => { setChatInput(q); inputRef.current?.focus(); }}
                        className="text-[11px] px-2 py-1 rounded-full border border-slate-700 text-slate-300 hover:border-violet-500/50 hover:text-white"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="border-t border-slate-800/50 px-4 md:px-6 py-3 shrink-0">
              <div className="max-w-4xl flex gap-2">
                <input
                  ref={inputRef}
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !pending) void sendChat(); }}
                  placeholder={analyzing ? 'Waiting for the analysis to finish…' : "Ask a follow-up, e.g. 'drill into the Compliance lane'"}
                  className="flex-1 min-w-0 bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-violet-500 focus:outline-none disabled:opacity-60"
                  disabled={pending}
                  aria-label="Follow-up question"
                />
                <button onClick={() => void sendChat()} disabled={pending || !chatInput.trim()}
                  aria-label="Send"
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
          key={activeId}
          threadId={activeId}
          model={model}
          initial={wizardCache.current.get(activeId)}
          onPersist={s => { wizardCache.current.set(activeId, s); }}
          onClose={() => setWizardOpen(false)}
        />
      )}
    </div>
  );
}

// ── The wizard ───────────────────────────────────────────────────────

function BuildAgentsWizard({ threadId, model, initial, onPersist, onClose }: {
  threadId: string;
  model: string;
  initial?: WizardState;
  onPersist: (s: WizardState) => void;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<WizardPhase>(initial?.phase || 'fetching');
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<WizardStep[]>(initial?.steps || []);
  const [active, setActive] = useState(initial?.active || 0);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  const [attempt, setAttempt] = useState(0);
  const [fetchStartedAt, setFetchStartedAt] = useState(() => Date.now());
  const needsFetch = !initial || initial.phase === 'fetching';

  // fetch suggestions once, abort when the wizard closes, reuse them on reopen
  useEffect(() => {
    if (!needsFetch) return;
    const ctl = new AbortController();
    setError(null);
    setFetchStartedAt(Date.now());
    void (async () => {
      const r = await apiFetch<{ agents: AgentSpec[] }>(`/api/bpm-analyzer/threads/${threadId}/suggest-agents`, {
        method: 'POST', body: JSON.stringify({ model }), signal: ctl.signal, throwOnError: false, silent: true,
      });
      if (ctl.signal.aborted) return;
      if (r.error || !r.data?.agents) {
        setError(`${r.error || 'Could not extract agent suggestions'}. Try again, or pick a different vision model on the left first.`);
        return;
      }
      if (r.data.agents.length === 0) {
        setError('The analyst did not suggest any agents for this process. Ask a follow-up about which steps could use one, then try again.');
        return;
      }
      setSteps(r.data.agents.map(s => ({ spec: s, stage: 'review' as WizardStage })));
      setPhase('review');
    })();
    return () => ctl.abort();
  }, [attempt, needsFetch, threadId, model]);

  useEffect(() => {
    if (phase !== 'fetching') onPersist({ phase, steps, active });
  }, [phase, steps, active, onPersist]);

  const patch = (idx: number, p: Partial<WizardStep>) =>
    setSteps(prev => prev.map((s, i) => (i === idx ? { ...s, ...p } : s)));

  const goNext = (idx: number) => {
    if (idx + 1 < stepsRef.current.length) setActive(idx + 1);
    else setPhase('finished');
  };

  const post = <T,>(path: string, body: unknown) =>
    apiFetch<T>(`/api/bpm-analyzer/threads/${threadId}/${path}`, {
      method: 'POST', body: JSON.stringify(body), throwOnError: false, silent: true,
    });

  // each stage is a real request, the card shows whichever one is in flight
  const runStep = async (idx: number, action: 'build' | 'skip', retry = false) => {
    const next = () => { if (!retry) goNext(idx); };
    if (action === 'skip') {
      patch(idx, { stage: 'skipped' });
      next();
      return;
    }
    if (!retry) setPhase('running');
    const spec = stepsRef.current[idx].spec;

    patch(idx, { stage: 'synth', buildError: undefined, test: undefined, agent: undefined, synth: undefined });
    const s = await post<{ synthetic_input: { description: string; input: string } }>('synthetic-input', { spec });
    const synth = s.data?.synthetic_input;
    if (!synth) {
      patch(idx, { stage: 'done', buildError: s.error || 'Could not generate test data' });
      next();
      return;
    }
    patch(idx, { stage: 'creating', synth });

    const c = await post<{ id: string; slug: string; name: string }>('create-agent', spec);
    if (!c.data) {
      patch(idx, { stage: 'done', buildError: c.error || 'Could not create the agent' });
      next();
      return;
    }
    const agent = c.data;
    patch(idx, { stage: 'testing', agent });

    const t = await post<{ test_result: TestResult }>('smoke-test', { agent_id: agent.id, input: synth.input });
    patch(idx, {
      stage: 'done',
      test: t.data?.test_result || { ok: false, error: t.error || 'Smoke test failed' },
    });
    next();
  };

  const created = steps.filter(s => s.agent).length;
  const failed = steps.filter(s => (s.test && !s.test.ok && !s.test.skipped) || s.buildError).length;
  const busy = steps.some(s => s.stage === 'synth' || s.stage === 'creating' || s.stage === 'testing');

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-3 md:p-6" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Build agents"
        className="bg-[#0B0F19] border border-violet-500/40 rounded-2xl max-w-5xl w-full max-h-[90vh] flex flex-col shadow-2xl shadow-violet-500/20 overflow-hidden"
      >
        <header className="relative p-4 md:p-6 border-b border-slate-800/60 bg-gradient-to-br from-violet-500/10 via-slate-900 to-cyan-500/10 overflow-hidden">
          <div className="relative flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg md:text-2xl font-bold text-white flex items-center gap-3">
                <Wand2 className="w-6 h-6 text-violet-300" />
                Build Agents from this BPM
              </h2>
              <p className="text-xs md:text-sm text-slate-400 mt-1.5">
                For each agent you approve, the analyst writes grounded test data, creates the agent as a draft and runs it once.
                {busy && ' Closing this window does not stop a build that is already running.'}
              </p>
            </div>
            <button onClick={onClose} className="p-2 text-slate-500 hover:text-white" aria-label="Close">
              <X className="w-5 h-5" />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 md:p-6">
          {phase === 'fetching' && !error && (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="w-10 h-10 text-violet-300 animate-spin" />
              <p className="text-sm text-white mt-4 font-semibold">Turning the report into agent designs</p>
              <p className="text-xs text-slate-500 mt-1 text-center">
                The analyst re-reads the process and writes one spec per suggested agent. This usually takes 30 to 90 seconds.
              </p>
              <p className="text-[11px] text-slate-600 mt-1"><Elapsed since={fetchStartedAt} /></p>
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200" role="alert">
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                <span className="flex-1">{error}</span>
              </div>
              {phase === 'fetching' && (
                <button
                  onClick={() => setAttempt(a => a + 1)}
                  className="mt-3 px-3 py-1.5 rounded-lg border border-rose-400/50 text-rose-100 text-xs font-semibold hover:bg-rose-500/20"
                >
                  Try again
                </button>
              )}
            </div>
          )}

          {phase === 'review' && active === 0 && steps[0]?.stage === 'review' && (
            <p className="text-xs text-slate-400 mb-4">
              The analyst suggested {steps.length} agent{steps.length !== 1 ? 's' : ''}. For each one, choose Build to create it as a draft and test it, or Skip. Nothing is published, drafts only run when you run them.
            </p>
          )}

          {phase !== 'fetching' && steps.length > 0 && (
            <>
              <div className="mb-6">
                <div className="flex justify-between text-[11px] text-slate-400 mb-1 gap-2 flex-wrap">
                  <span>Agent {Math.min(active + 1, steps.length)} of {steps.length}</span>
                  <span>{created} created · {failed} failed · {steps.filter(s => s.stage === 'skipped').length} skipped</span>
                </div>
                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-gradient-to-r from-violet-500 to-cyan-500"
                    animate={{ width: `${(steps.filter(s => s.stage === 'done' || s.stage === 'skipped').length / steps.length) * 100}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
              </div>

              <div className="space-y-4">
                {steps.map((s, i) => (
                  <AgentStepCard
                    key={i}
                    step={s}
                    active={i === active && phase !== 'finished'}
                    onConfirm={() => void runStep(i, 'build')}
                    onSkip={() => void runStep(i, 'skip')}
                    onRetry={() => void runStep(i, 'build', true)}
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
                  <h3 className="text-lg font-bold text-white">Done</h3>
                  <p className="text-sm text-emerald-100 mt-1">
                    Created <strong>{created}</strong> draft agent{created !== 1 ? 's' : ''}
                    {failed > 0 && <> · <span className="text-rose-300">{failed} failure{failed !== 1 ? 's' : ''}</span></>}
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
  // tools are a set the agent may call in any order, not a linear chain
  const nodes = [
    { kind: 'input' as const, label: 'Test input', sub: synthInput?.slice(0, 80) },
    { kind: 'model' as const, label: model, sub: 'reasoning core' },
    { kind: 'tool' as const, label: 'Available tools', sub: tools.length > 0 ? tools.join(', ') : 'none' },
    { kind: 'output' as const, label: 'Output', sub: output?.slice(0, 80) },
  ];

  const visibleCount = (() => {
    if (stage === 'synth') return 0;
    if (stage === 'creating') return 1;
    if (stage === 'testing') return 3;
    if (stage === 'done') return output ? 4 : 3;
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

  if (visibleCount === 0) return null;
  return (
    <div className="mt-3 rounded-xl border border-slate-700/40 bg-slate-950/60 p-4 overflow-hidden">
      <div className="flex items-center gap-2 flex-wrap">
        {nodes.slice(0, visibleCount).map((n, i) => {
          const Icon = iconFor(n.kind);
          const c = colorFor(n.kind);
          return (
            <div key={i} className="flex items-center gap-2 min-w-0">
              <motion.div
                initial={{ opacity: 0, scale: 0.6, y: 8 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ type: 'spring', stiffness: 220, damping: 18 }}
                className="rounded-lg border px-2.5 py-1.5 min-w-[100px] max-w-[220px]"
                style={{ borderColor: c + '66', background: c + '14' }}
              >
                <div className="flex items-center gap-1.5">
                  <Icon className="w-3 h-3 flex-shrink-0" style={{ color: c }} />
                  <span className="text-[10px] font-mono text-white truncate">{n.label}</span>
                </div>
                {n.sub && <p className="text-[9px] text-slate-500 truncate mt-0.5" title={n.sub}>{n.sub}</p>}
              </motion.div>
              {i < visibleCount - 1 && <ChevronRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const STAGE_BADGE: Record<string, string> = {
  emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  slate: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  amber: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  rose: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  violet: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
};

function AgentStepCard({ step, active, onConfirm, onSkip, onRetry }: {
  step: WizardStep;
  active: boolean;
  onConfirm: () => void;
  onSkip: () => void;
  onRetry: () => void;
}) {
  const { spec, stage, agent, synth, test, buildError } = step;
  const doneLabel = buildError ? 'Build failed'
    : test?.ok ? 'Created and tested'
      : test?.skipped ? 'Created, test skipped'
        : test ? 'Created, test failed' : 'Done';
  const stageLabel = {
    idle: 'Queued',
    fetching: 'Loading',
    review: active ? 'Awaiting your decision' : 'Queued',
    synth: 'Writing realistic test data from your process, about 20 seconds…',
    creating: 'Creating the draft agent, a few seconds…',
    testing: 'Running the agent once with the test data, usually under a minute…',
    done: doneLabel,
    skipped: 'Skipped',
  }[stage];
  const stageColor = buildError ? 'rose'
    : stage === 'done' && test?.ok ? 'emerald'
      : stage === 'skipped' || test?.skipped ? 'slate'
        : stage === 'done' ? 'amber' : 'violet';

  return (
    <motion.div
      layout
      animate={{ opacity: stage === 'skipped' ? 0.45 : 1 }}
      className={`rounded-xl border p-4 transition-all ${
        active ? 'border-violet-500/60 bg-violet-500/5 shadow-lg shadow-violet-500/10'
          : 'border-slate-700/60 bg-slate-900/40'
      }`}
    >
      <div className="flex items-start justify-between gap-4 mb-2 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">{spec.lane || spec.category}</span>
            <span className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border ${STAGE_BADGE[stageColor]}`}>
              {stageLabel}
            </span>
          </div>
          <h3 className="text-base font-semibold text-white mt-1">{spec.name}</h3>
          <p className="text-xs text-slate-400 mt-1 line-clamp-2">{spec.description}</p>
          {spec.why && <p className="text-[11px] text-violet-300 mt-1.5"><strong>Why an agent:</strong> {spec.why}</p>}
        </div>
        {stage === 'review' && active && (
          <div className="flex md:flex-col gap-2 shrink-0">
            <button onClick={onConfirm} className="px-3 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 text-xs font-semibold hover:bg-emerald-500/30 inline-flex items-center gap-1">
              <Check className="w-3 h-3" /> Build
            </button>
            <button onClick={onSkip} className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 text-xs hover:text-white inline-flex items-center gap-1">
              <X className="w-3 h-3" /> Skip
            </button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3 text-[11px]">
        <div className="bg-slate-900/60 border border-slate-700/40 rounded px-2 py-1.5 inline-flex items-center gap-1.5 min-w-0">
          <Cpu className="w-3 h-3 text-cyan-400 shrink-0" />
          <span className="text-slate-300 truncate font-mono">{spec.model}</span>
        </div>
        <div className="bg-slate-900/60 border border-slate-700/40 rounded px-2 py-1.5 inline-flex items-center gap-1.5 sm:col-span-2 min-w-0">
          <Wrench className="w-3 h-3 text-amber-400 shrink-0" />
          <span className="text-slate-400 truncate">
            Available tools: {(spec.tools && spec.tools.length > 0) ? spec.tools.join(', ') : 'none'}
          </span>
        </div>
      </div>

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

      {(stage === 'creating' || stage === 'testing' || (stage === 'done' && agent)) && (
        <BuildingPipelineViz
          tools={spec.tools || []}
          model={spec.model}
          stage={stage}
          synthInput={synth?.input}
          output={test?.output}
        />
      )}

      <AnimatePresence>
        {stage === 'done' && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 space-y-2"
          >
            {buildError && (
              <div className="rounded-lg bg-rose-500/10 border border-rose-500/40 p-2.5 text-[11px] text-rose-200 flex items-center gap-2">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                <span className="flex-1">{buildError}.</span>
                <button onClick={onRetry} className="px-2 py-0.5 rounded border border-rose-400/50 text-rose-100 hover:bg-rose-500/20">Try again</button>
              </div>
            )}
            {agent && (
              <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/30 p-2.5 text-[11px] flex items-center gap-2 flex-wrap">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="text-emerald-100">Created draft <code className="text-emerald-300">{agent.slug}</code></span>
                <span className="ml-auto inline-flex items-center gap-3">
                  <a href={`/agents/${agent.id}/chat`} target="_blank" rel="noreferrer" className="text-cyan-300 hover:text-cyan-200 inline-flex items-center gap-1" data-testid="run-a-test">
                    <PlayCircle className="w-3 h-3" /> Run a test
                  </a>
                  <a href={`/agents/${agent.id}`} target="_blank" rel="noreferrer" className="text-emerald-300 hover:text-emerald-200 inline-flex items-center gap-1">
                    Open <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                </span>
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
                test.ok ? 'bg-emerald-500/5 border-emerald-500/30'
                  : test.skipped ? 'bg-slate-800/40 border-slate-700/60'
                    : 'bg-rose-500/10 border-rose-500/40'
              }`}>
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  {test.ok ? <Check className="w-3.5 h-3.5 text-emerald-400" />
                    : test.skipped ? <Info className="w-3.5 h-3.5 text-slate-400" />
                      : <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />}
                  <span className={test.ok ? 'text-emerald-200' : test.skipped ? 'text-slate-300' : 'text-rose-200'}>
                    {test.ok ? 'Smoke test passed'
                      : test.skipped ? `Smoke test skipped: ${test.error || 'not available here'}`
                        : `Smoke test failed: ${test.error || 'unknown error'}`}
                  </span>
                  {test.ok && (
                    <span className="ml-auto text-slate-500">
                      ${(test.cost || 0).toFixed(4)} · {test.duration_ms}ms
                    </span>
                  )}
                </div>
                {!test.ok && (
                  <p className="text-slate-400 mt-1">
                    The draft is saved. Use Run a test to try it yourself, then adjust its prompt or tools from Open.
                  </p>
                )}
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
