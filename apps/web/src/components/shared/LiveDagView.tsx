'use client';


import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  XCircle,
  Zap,
} from 'lucide-react';

// ─── Types (mirror the Java/Python SDK DagSnapshot records) ─────────────────

interface Node {
  id: string;
  label: string;
  tool_name?: string;
  agent_slug?: string | null;
  status: 'pending' | 'running' | 'completed' | 'skipped' | 'failed';
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  input?: Record<string, unknown>;
  output?: unknown;
  cost?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  error?: string | null;
}

interface Edge { from: string; to: string; field?: string | null }

export interface DagSnapshot {
  execution_id: string;
  agent_id?: string;
  agent_name?: string;
  mode: 'pipeline' | 'agent';
  status: 'queued' | 'running' | 'completed' | 'failed';
  started_at?: string | null;
  completed_at?: string | null;
  current_node_id?: string | null;
  progress: { completed: number; total: number };
  cost_so_far: number;
  tokens: { in: number; out: number };
  nodes: Node[];
  edges: Edge[];
}

interface Props {
  executionId: string;
  apiUrl?: string;
  watchPath?: (id: string) => string;
  token?: string | null;
  palette?: Partial<Palette>;
}

interface Palette {
  bg: string;           // card background
  border: string;       // card border
  text: string;         // body text
  subtle: string;       // muted text
  accent: string;       // running accent
  success: string;
  warning: string;
  danger: string;
}

const DEFAULT_PALETTE: Palette = {
  bg: 'rgba(15,23,42,0.6)',
  border: 'rgba(71,85,105,0.4)',
  text: '#e2e8f0',
  subtle: '#94a3b8',
  accent: '#06b6d4',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
};

// ─── Helpers ────────────────────────────────────────────────────────────────

function statusMeta(status: string, p: Palette): { color: string; bg: string; Icon: React.ElementType } {
  switch (status) {
    case 'completed': return { color: p.success, bg: `${p.success}1A`, Icon: CheckCircle2 };
    case 'running':   return { color: p.accent,  bg: `${p.accent}1A`,  Icon: Loader2 };
    case 'failed':    return { color: p.danger,  bg: `${p.danger}1A`,  Icon: XCircle };
    case 'skipped':   return { color: p.subtle,  bg: `${p.subtle}1A`,  Icon: Clock };
    default:          return { color: p.subtle,  bg: `${p.subtle}0D`,  Icon: Clock };
  }
}

function formatMs(ms?: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
}

function formatCost(c?: number | null): string {
  if (c == null) return '—';
  if (c < 0.01) return `$${c.toFixed(4)}`;
  return `$${c.toFixed(3)}`;
}

function preview(value: unknown, max = 220): string {
  if (value == null) return '';
  if (typeof value === 'string') return value.length > max ? `${value.slice(0, max)}…` : value;
  try {
    const s = JSON.stringify(value, null, 2);
    return s.length > max ? `${s.slice(0, max)}…` : s;
  } catch {
    return String(value);
  }
}

// ─── Component ──────────────────────────────────────────────────────────────

export function LiveDagView({ executionId, apiUrl, watchPath, token, palette }: Props) {
  const p: Palette = { ...DEFAULT_PALETTE, ...(palette || {}) };
  const [snap, setSnap] = useState<DagSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const esRef = useRef<EventSource | null>(null);

  const buildPath = watchPath || ((id: string) => `/api/executions/${id}/watch`);
  const url = useMemo(() => {
    const base = (apiUrl || '').replace(/\/$/, '');
    const path = buildPath(executionId);
    // SSE doesn't allow custom headers via EventSource — if the caller
    // passed a bearer token, fall back to a query-param hand-off that
    // the corresponding server MUST accept (most of our proxy endpoints
    // already do). Same-origin cookies are the cleaner path.
    const qs = token ? `${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}` : '';
    return `${base}${path}${qs}`;
  }, [apiUrl, executionId, token, buildPath]);

  useEffect(() => {
    setError(null);
    setConnected(false);
    const es = new EventSource(url, { withCredentials: true });
    esRef.current = es;

    const onSnapshot = (evt: MessageEvent) => {
      try {
        const parsed = JSON.parse(evt.data) as DagSnapshot;
        setSnap(parsed);
        setConnected(true);
      } catch (e) {
        setError(`Bad snapshot payload: ${(e as Error).message}`);
      }
    };
    const onEnd = () => { es.close(); setConnected(false); };
    const onError = () => { setError('Connection to the live stream was interrupted.'); setConnected(false); };

    es.addEventListener('snapshot', onSnapshot as EventListener);
    es.addEventListener('end', onEnd as EventListener);
    es.addEventListener('error', onError as EventListener);
    // Generic message handler for servers that don't set an event name.
    es.onmessage = onSnapshot as EventListener;

    return () => {
      es.removeEventListener('snapshot', onSnapshot as EventListener);
      es.removeEventListener('end', onEnd as EventListener);
      es.removeEventListener('error', onError as EventListener);
      es.close();
    };
  }, [url]);

  if (!snap && error) {
    return (
      <div className="flex items-start gap-2 rounded-lg border px-3 py-2" style={{ borderColor: `${p.danger}40`, background: `${p.danger}0D`, color: p.danger }}>
        <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <div className="text-xs">{error}</div>
      </div>
    );
  }

  if (!snap) {
    return (
      <div className="flex items-center gap-2 px-3 py-3 rounded-lg" style={{ background: p.bg, border: `1px solid ${p.border}`, color: p.subtle }}>
        <Loader2 className="w-4 h-4 animate-spin" style={{ color: p.accent }} />
        <span className="text-xs">Waiting for the first snapshot from the pipeline…</span>
      </div>
    );
  }

  const totalPct = snap.progress.total === 0 ? 0 : (snap.progress.completed / snap.progress.total) * 100;
  const overall = statusMeta(snap.status, p);

  return (
    <div className="flex flex-col gap-3">
      {/* Header — execution-level status + progress bar */}
      <div className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg" style={{ background: p.bg, border: `1px solid ${p.border}` }}>
        <div className="flex items-center gap-2 min-w-0">
          <overall.Icon className={`w-4 h-4 flex-shrink-0 ${snap.status === 'running' ? 'animate-spin' : ''}`} style={{ color: overall.color }} />
          <span className="text-sm font-semibold truncate" style={{ color: p.text }}>
            {snap.agent_name || snap.execution_id.slice(0, 8)}
          </span>
          <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded" style={{ background: overall.bg, color: overall.color }}>
            {snap.status}
          </span>
          {connected && snap.status === 'running' && (
            <span className="flex items-center gap-1 text-[10px]" style={{ color: p.accent }}>
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: p.accent }} />
              live
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[11px]" style={{ color: p.subtle }}>
          <span>{snap.progress.completed}/{snap.progress.total} nodes</span>
          <span>{formatCost(snap.cost_so_far)}</span>
          <span>{snap.tokens.in.toLocaleString()} in · {snap.tokens.out.toLocaleString()} out</span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1 w-full rounded-full overflow-hidden" style={{ background: p.border }}>
        <div className="h-full transition-all duration-300" style={{ width: `${totalPct}%`, background: overall.color }} />
      </div>

      {/* Node list */}
      <div className="flex flex-col gap-2">
        {snap.nodes.map((n) => {
          const meta = statusMeta(n.status, p);
          const isExpanded = expanded[n.id] ?? n.status === 'running';
          const running = n.status === 'running';
          const hasIO = n.input || n.output != null || n.error;
          return (
            <div
              key={n.id}
              className="rounded-lg transition-shadow"
              style={{
                background: p.bg,
                border: `1px solid ${running ? meta.color : p.border}`,
                boxShadow: running ? `0 0 0 1px ${meta.color}40, 0 0 16px ${meta.color}20` : 'none',
              }}
            >
              <button
                type="button"
                onClick={() => setExpanded({ ...expanded, [n.id]: !isExpanded })}
                className="flex items-center gap-2 w-full px-3 py-2 text-left"
                disabled={!hasIO}
                style={{ opacity: n.status === 'skipped' ? 0.55 : 1 }}
              >
                <meta.Icon className={`w-4 h-4 flex-shrink-0 ${running ? 'animate-spin' : ''}`} style={{ color: meta.color }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate" style={{ color: p.text }}>{n.label}</span>
                    {n.tool_name && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: p.border, color: p.subtle }}>
                        {n.tool_name === '__structured__' ? 'structured' : n.tool_name}
                      </span>
                    )}
                    {n.agent_slug && (
                      <span className="text-[10px]" style={{ color: p.subtle }}>
                        <Zap className="w-3 h-3 inline -mt-0.5 mr-0.5" />{n.agent_slug}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3 text-[11px] flex-shrink-0" style={{ color: p.subtle }}>
                  <span>{formatMs(n.duration_ms)}</span>
                  <span>{formatCost(n.cost)}</span>
                  {hasIO && (isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />)}
                </div>
              </button>

              {isExpanded && hasIO && (
                <div className="px-3 pb-3 pt-1 border-t flex flex-col gap-2" style={{ borderColor: p.border }}>
                  {n.input && Object.keys(n.input).length > 0 && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: p.subtle }}>Input</div>
                      <pre className="text-[11px] font-mono overflow-x-auto whitespace-pre-wrap rounded px-2 py-1.5" style={{ background: `${p.border}40`, color: p.text }}>
                        {preview(n.input, 400)}
                      </pre>
                    </div>
                  )}
                  {n.output != null && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: p.subtle }}>Output</div>
                      <pre className="text-[11px] font-mono overflow-x-auto whitespace-pre-wrap rounded px-2 py-1.5" style={{ background: `${p.border}40`, color: p.text }}>
                        {preview(n.output, 600)}
                      </pre>
                    </div>
                  )}
                  {n.error && (
                    <div>
                      <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: p.danger }}>Error</div>
                      <pre className="text-[11px] font-mono overflow-x-auto whitespace-pre-wrap rounded px-2 py-1.5" style={{ background: `${p.danger}1A`, color: p.danger }}>
                        {n.error}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {error && connected === false && snap.status !== 'completed' && snap.status !== 'failed' && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs" style={{ background: `${p.warning}1A`, color: p.warning, border: `1px solid ${p.warning}40` }}>
          <AlertCircle className="w-4 h-4" />
          <span>{error} — the pipeline may still be running; refresh to reconnect.</span>
        </div>
      )}
    </div>
  );
}

export default LiveDagView;
