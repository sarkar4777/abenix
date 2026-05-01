'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ChevronLeft, ChevronRight, Loader2, Send, Sparkles, Terminal,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Verb {
  name: string;
  intent: 'INSPECT' | 'MUTATE' | 'EXECUTE' | 'GOVERN' | 'LEARN';
  summary: string;
  args: { name: string; typ: string; required: boolean; default: unknown; help: string }[];
  examples: string[];
  risk: string;
}

interface ShellResult {
  kind: 'markdown' | 'json' | 'table' | 'patch_proposal' | 'execution' | 'error';
  title?: string;
  body?: unknown;
  rows?: Record<string, unknown>[];
  id?: string;
  json_patch?: unknown;
  rationale?: string;
  risk_level?: string;
  next_step?: string;
  suggestion?: string;
  expected?: string[];
}

interface HistoryEntry {
  id: string;
  command: string;
  result: ShellResult | null;
  loading: boolean;
  error?: string;
  ts: number;
}

function authHeaders(): HeadersInit {
  const t = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function intentColor(intent: string): string {
  switch (intent) {
    case 'INSPECT': return 'text-cyan-300 bg-cyan-500/10 border-cyan-500/30';
    case 'MUTATE': return 'text-amber-300 bg-amber-500/10 border-amber-500/30';
    case 'EXECUTE': return 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30';
    case 'GOVERN': return 'text-purple-300 bg-purple-500/10 border-purple-500/30';
    case 'LEARN': return 'text-pink-300 bg-pink-500/10 border-pink-500/30';
    default: return 'text-slate-400 bg-slate-700/20 border-slate-700/40';
  }
}

export default function WorkflowShellPage() {
  const params = useParams();
  const router = useRouter();
  const pipelineId = params.id as string;

  const [verbs, setVerbs] = useState<Verb[]>([]);
  const [cheatSheet, setCheatSheet] = useState<string>('');
  const [showCheat, setShowCheat] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [historyCursor, setHistoryCursor] = useState<number>(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autocompleteOpen, setAutocompleteOpen] = useState(false);

  // Load grammar on mount
  useEffect(() => {
    (async () => {
      const res = await fetch(`${API_URL}/api/workflow-shell/grammar`, { headers: authHeaders() });
      const json = await res.json();
      setVerbs(json?.data?.verbs || []);
      setCheatSheet(json?.data?.cheat_sheet || '');
    })();
  }, []);

  // Scroll to bottom on every new message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [history.length]);

  const submit = useCallback(async (cmd: string) => {
    if (!cmd.trim()) return;
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setHistory(prev => [...prev, { id, command: cmd, result: null, loading: true, ts: Date.now() }]);
    setBusy(true);
    setText('');
    setHistoryCursor(-1);
    try {
      const res = await fetch(`${API_URL}/api/workflow-shell/${pipelineId}`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: cmd, nl: cmd.includes('?') || cmd.length > 80 }),
      });
      const json = await res.json();
      const data: ShellResult = json?.data || { kind: 'error', body: json?.error?.message || 'unknown' };
      setHistory(prev => prev.map(h => h.id === id ? { ...h, result: data, loading: false } : h));
    } catch (e: unknown) {
      setHistory(prev => prev.map(h => h.id === id ? {
        ...h, result: { kind: 'error', body: String(e) }, loading: false,
      } : h));
    } finally {
      setBusy(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [pipelineId]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit(text);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      const recents = history.filter(h => h.command).map(h => h.command);
      if (!recents.length) return;
      const next = historyCursor < 0 ? recents.length - 1 : Math.max(0, historyCursor - 1);
      setHistoryCursor(next);
      setText(recents[next]);
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const recents = history.filter(h => h.command).map(h => h.command);
      if (historyCursor < 0) return;
      const next = historyCursor + 1;
      if (next >= recents.length) {
        setHistoryCursor(-1);
        setText('');
      } else {
        setHistoryCursor(next);
        setText(recents[next]);
      }
      return;
    }
    if (e.key === 'Tab') {
      e.preventDefault();
      const head = text.split(' ', 1)[0].toLowerCase();
      const matches = verbs.filter(v => v.name.startsWith(head));
      if (matches.length === 1) {
        const sig = matches[0].args.map(a => a.required ? `<${a.name}>` : `[${a.name}]`).join(' ');
        setText(`${matches[0].name} ${sig}`.trim());
      } else if (matches.length > 1) {
        setAutocompleteOpen(true);
      }
    }
  };

  const head = text.split(' ', 1)[0].toLowerCase();
  const candidates = head ? verbs.filter(v => v.name.startsWith(head)).slice(0, 8) : verbs.slice(0, 8);

  return (
    <div className="p-6 max-w-6xl mx-auto h-[calc(100vh-3.5rem-1.75rem)] flex flex-col">
      <div className="mb-4">
        <button
          onClick={() => router.push(`/agents/${pipelineId}/info`)}
          className="text-xs text-slate-500 hover:text-slate-300 inline-flex items-center gap-1 mb-2"
        >
          <ChevronLeft className="w-3 h-3" /> Back to pipeline
        </button>
        <h1 className="text-2xl font-semibold text-white flex items-center gap-3">
          <Terminal className="w-6 h-6 text-cyan-400" />
          Talk-to-workflow shell
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Drive every aspect of this pipeline with a typed grammar.  Press{' '}
          <kbd className="px-1 py-0.5 bg-slate-800 border border-slate-700 rounded text-[10px]">Tab</kbd>{' '}
          to autocomplete,{' '}
          <kbd className="px-1 py-0.5 bg-slate-800 border border-slate-700 rounded text-[10px]">↑/↓</kbd>{' '}
          for history. Mutating verbs draft a Healing patch — they do not change the workflow directly.
        </p>
      </div>

      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <button
          onClick={() => setShowCheat(!showCheat)}
          className="text-[11px] px-2 py-1 border border-slate-700 hover:bg-slate-800 text-slate-300 rounded"
        >
          {showCheat ? 'Hide' : 'Show'} cheat sheet
        </button>
        <Link
          href={`/agents/${pipelineId}/healing`}
          className="text-[11px] px-2 py-1 border border-cyan-500/30 hover:bg-cyan-500/10 text-cyan-300 rounded inline-flex items-center gap-1"
        >
          <Sparkles className="w-3 h-3" /> Healing
        </Link>
        {(['INSPECT', 'MUTATE', 'EXECUTE', 'GOVERN', 'LEARN'] as const).map(intent => (
          <span key={intent} className={`text-[10px] px-2 py-0.5 rounded-full border ${intentColor(intent)}`}>
            {intent} ({verbs.filter(v => v.intent === intent).length})
          </span>
        ))}
      </div>

      {showCheat && (
        <div className="mb-3 p-4 bg-slate-900/40 border border-slate-800 rounded-xl max-h-64 overflow-auto">
          <div className="prose prose-invert prose-xs max-w-none text-xs text-slate-300">
            <ReactMarkdown>{cheatSheet}</ReactMarkdown>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-auto bg-slate-950/40 border border-slate-800 rounded-xl p-4 space-y-3 mb-3 font-mono text-xs">
        {history.length === 0 && (
          <div className="text-slate-500 text-xs">
            <p className="mb-2">Try one of these:</p>
            <ul className="space-y-1">
              <li className="hover:text-cyan-300 cursor-pointer" onClick={() => submit('show workflow')}>
                <code>show workflow</code> — inspect the DSL
              </li>
              <li className="hover:text-cyan-300 cursor-pointer" onClick={() => submit('show runs')}>
                <code>show runs</code> — list recent executions
              </li>
              <li className="hover:text-cyan-300 cursor-pointer" onClick={() => submit('show patches')}>
                <code>show patches</code> — list draft patches
              </li>
              <li className="hover:text-cyan-300 cursor-pointer" onClick={() => submit('help')}>
                <code>help</code> — full cheat sheet
              </li>
            </ul>
          </div>
        )}
        {history.map(h => (
          <div key={h.id} className="space-y-1">
            <div className="flex items-baseline gap-2 text-cyan-400">
              <span className="text-slate-500">$</span>
              <span>{h.command}</span>
            </div>
            <div className="pl-4">
              {h.loading ? (
                <span className="text-slate-500 inline-flex items-center gap-1">
                  <Loader2 className="w-3 h-3 animate-spin" /> running…
                </span>
              ) : h.result ? <ResultBlock result={h.result} /> : null}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="relative">
        <div className="flex items-center gap-2">
          <span className="text-cyan-400 font-mono">$</span>
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => { setText(e.target.value); setAutocompleteOpen(true); }}
            onKeyDown={onKeyDown}
            onBlur={() => setTimeout(() => setAutocompleteOpen(false), 150)}
            onFocus={() => setAutocompleteOpen(true)}
            placeholder="Type a verb (try `help` or `show workflow`)…"
            className="flex-1 bg-slate-900/80 border border-slate-700 focus:border-cyan-500 text-white text-sm font-mono px-3 py-2.5 rounded-lg outline-none"
            disabled={busy}
            autoFocus
          />
          <button
            onClick={() => submit(text)}
            disabled={busy || !text.trim()}
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-medium rounded-lg disabled:opacity-50"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Run
          </button>
        </div>
        {autocompleteOpen && candidates.length > 0 && head && (
          <div className="absolute bottom-full mb-1 left-6 right-20 max-h-60 overflow-auto bg-slate-900 border border-slate-700 rounded-lg shadow-xl z-50">
            {candidates.map(v => (
              <button
                key={v.name}
                type="button"
                onMouseDown={(e) => { e.preventDefault(); }}
                onClick={() => {
                  const sig = v.args.map(a => a.required ? `<${a.name}>` : `[${a.name}]`).join(' ');
                  setText(`${v.name} ${sig}`.trim());
                  inputRef.current?.focus();
                  setAutocompleteOpen(false);
                }}
                className="w-full text-left px-3 py-2 hover:bg-slate-800 border-b border-slate-800 last:border-b-0"
              >
                <div className="flex items-center gap-2">
                  <span className={`text-[9px] px-1.5 py-0.5 rounded border ${intentColor(v.intent)}`}>
                    {v.intent}
                  </span>
                  <code className="text-cyan-300 text-xs">{v.name}</code>
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">{v.summary}</p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


function ResultBlock({ result }: { result: ShellResult }) {
  if (result.kind === 'error') {
    return (
      <div className="text-red-400">
        <div>error: {String(result.body)}</div>
        {result.suggestion && <div className="text-amber-300 mt-1">did you mean <code>{result.suggestion}</code>?</div>}
        {result.expected && <div className="text-slate-500 mt-1">expected args: {result.expected.join(', ')}</div>}
      </div>
    );
  }
  if (result.kind === 'markdown') {
    return (
      <div className="prose prose-invert prose-xs max-w-none text-xs text-slate-300">
        <ReactMarkdown>{String(result.body || '')}</ReactMarkdown>
      </div>
    );
  }
  if (result.kind === 'json') {
    return (
      <pre className="text-[11px] text-slate-300 bg-slate-950/60 border border-slate-800 rounded-md p-2 overflow-x-auto">
        {JSON.stringify(result.body, null, 2)}
      </pre>
    );
  }
  if (result.kind === 'table') {
    const rows = result.rows || [];
    if (rows.length === 0) return <span className="text-slate-500">(empty)</span>;
    const cols = Object.keys(rows[0]);
    return (
      <div className="overflow-x-auto">
        <table className="text-[11px] text-slate-300 border-collapse">
          <thead>
            <tr>{cols.map(c => <th key={c} className="text-left px-2 py-1 border-b border-slate-700 text-slate-400 font-mono">{c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="hover:bg-slate-800/40">
                {cols.map(c => <td key={c} className="px-2 py-1 border-b border-slate-800/50 truncate max-w-md">{
                  typeof r[c] === 'object' ? JSON.stringify(r[c]) : String(r[c] ?? '')
                }</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (result.kind === 'patch_proposal') {
    return (
      <div className="bg-cyan-500/5 border border-cyan-500/30 rounded-md p-3">
        <div className="flex items-center gap-2 mb-1">
          <Sparkles className="w-3 h-3 text-cyan-400" />
          <strong className="text-cyan-300 text-xs">Draft patch · {result.title}</strong>
          <span className={`text-[9px] px-1.5 py-0.5 rounded border ${
            result.risk_level === 'high' ? 'border-red-500/30 text-red-300 bg-red-500/10'
            : result.risk_level === 'medium' ? 'border-amber-500/30 text-amber-300 bg-amber-500/10'
            : 'border-emerald-500/30 text-emerald-300 bg-emerald-500/10'
          }`}>{result.risk_level} risk</span>
        </div>
        {result.rationale && <p className="text-[11px] text-slate-400 mb-2">{result.rationale}</p>}
        <details>
          <summary className="text-[11px] text-cyan-400 cursor-pointer">JSON-Patch</summary>
          <pre className="text-[10px] text-slate-300 bg-slate-950/60 border border-slate-800 rounded-md p-2 mt-1 overflow-x-auto">
            {JSON.stringify(result.json_patch, null, 2)}
          </pre>
        </details>
        {result.next_step && (
          <p className="text-[11px] text-slate-500 mt-2">{result.next_step}</p>
        )}
      </div>
    );
  }
  if (result.kind === 'execution') {
    return (
      <div className="text-slate-300">
        {String(result.body || '')}
      </div>
    );
  }
  return <pre className="text-slate-300">{JSON.stringify(result, null, 2)}</pre>;
}
