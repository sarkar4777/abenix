'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Wrench, CheckCircle2, AlertCircle, Sparkles, ArrowRight, Maximize2, Minimize2 } from 'lucide-react';
import { NarrationEvent } from './useNarrationStream';

interface Props {
  events: NarrationEvent[];
  rootExecutionId: string;
  height?: number;
}

interface FeedRow {
  id: string;
  ts: number;
  phase: NarrationEvent['phase'];
  primary: string;
  secondary?: string;
  tone?: NarrationEvent['tone'];
  is_error?: boolean;
  agent?: string;
}

const PHASE_COLOR: Record<string, string> = {
  tool_call: 'text-cyan-300',
  tool_result: 'text-emerald-300',
  sub_started: 'text-violet-300',
  sub_finished: 'text-emerald-300',
  sub_timeout: 'text-rose-300',
  narration: 'text-amber-300',
};

const TONE_COLOR: Record<string, string> = {
  info: 'text-slate-300',
  step: 'text-cyan-300',
  finding: 'text-emerald-300',
  alert: 'text-amber-300',
  done: 'text-emerald-200',
};

function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function shortLabel(slug: string | undefined): string {
  if (!slug) return '';
  return slug.replace(/^ciq-/, '');
}

export default function DeskNarrationFeed({ events, rootExecutionId, height = 360 }: Props) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const effectiveHeight = expanded && typeof window !== 'undefined'
    ? Math.max(window.innerHeight - 140, 480)
    : height;

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [expanded]);

  const rows: FeedRow[] = useMemo(() => {
    const out: FeedRow[] = [];
    for (const [i, e] of events.entries()) {
      const id = `${e.ts}-${i}`;
      if (e.phase === 'narration') {
        out.push({
          id, ts: e.ts, phase: e.phase, tone: e.tone,
          primary: e.message || '',
          secondary: shortLabel(e.agent_slug),
          agent: e.agent_slug,
        });
      } else if (e.phase === 'tool_call') {
        out.push({
          id, ts: e.ts, phase: e.phase,
          primary: `calling ${e.tool}`,
          secondary: e.arguments_preview ? `${e.arguments_preview}` : undefined,
          agent: e.agent_id,
        });
      } else if (e.phase === 'tool_result') {
        const ms = e.duration_ms ? `${(e.duration_ms / 1000).toFixed(1)}s` : '';
        out.push({
          id, ts: e.ts, phase: e.phase,
          is_error: e.is_error,
          primary: `${e.tool} ${e.is_error ? 'failed' : 'returned'}${ms ? ` (${ms})` : ''}`,
          secondary: e.result_preview,
          agent: e.agent_id,
        });
      } else if (e.phase === 'sub_started') {
        out.push({
          id, ts: e.ts, phase: e.phase,
          primary: `spawning ${shortLabel(e.agent_slug) || 'specialist'}`,
          secondary: e.sub_execution_id ? `#${e.sub_execution_id.slice(0, 8)}` : undefined,
          agent: e.agent_slug,
        });
      } else if (e.phase === 'sub_finished') {
        const ms = e.duration_ms ? `${(e.duration_ms / 1000).toFixed(1)}s` : '';
        out.push({
          id, ts: e.ts, phase: e.phase,
          primary: `${shortLabel(e.agent_slug)} ${e.status || 'finished'}${ms ? ` (${ms})` : ''}`,
          secondary: e.cost_usd != null ? `$${Number(e.cost_usd).toFixed(4)}` : undefined,
          agent: e.agent_slug,
        });
      }
    }
    return out;
  }, [events]);

  useEffect(() => {
    if (!autoScroll || !scrollerRef.current) return;
    scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  }, [rows.length, autoScroll]);

  const onScroll = () => {
    const el = scrollerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(atBottom);
  };

  const wrapperClass = expanded
    ? 'fixed inset-3 z-50 rounded-xl border border-emerald-500/30 bg-slate-950/95 backdrop-blur-xl overflow-hidden shadow-2xl flex flex-col'
    : 'rounded-xl border border-slate-800 bg-slate-950/60 overflow-hidden';
  return (
    <div className={wrapperClass} data-testid="desk-narration-feed">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-800/60">
        <Activity className="w-3 h-3 text-emerald-400" />
        <span className="text-[10px] uppercase tracking-[0.18em] text-emerald-300 font-semibold">Narration · live</span>
        <span className="text-[10px] font-mono text-slate-500">#{rootExecutionId.slice(0, 8)}</span>
        <span className="flex-1" />
        <span className="text-[10px] text-slate-500">{rows.length} events</span>
        {!autoScroll && (
          <button
            onClick={() => { setAutoScroll(true); if (scrollerRef.current) scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight; }}
            className="text-[10px] text-cyan-300 hover:text-cyan-200"
          >
            jump to live
          </button>
        )}
        <button
          onClick={() => setExpanded((v) => !v)}
          title={expanded ? 'Collapse (esc)' : 'Expand'}
          className="ml-1 p-1 rounded text-slate-400 hover:text-emerald-300 hover:bg-slate-800/60"
          aria-label={expanded ? 'collapse' : 'expand'}
        >
          {expanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
        </button>
      </div>
      <div
        ref={scrollerRef}
        onScroll={onScroll}
        className={expanded ? 'overflow-y-auto px-3 py-2 font-mono text-[11px] space-y-1 flex-1' : 'overflow-y-auto px-3 py-2 font-mono text-[11px] space-y-1'}
        style={expanded ? undefined : { height: effectiveHeight }}
      >
        {rows.length === 0 && (
          <div className="text-slate-600 italic px-2 py-4 flex items-center gap-2">
            <Sparkles className="w-3 h-3" /> waiting for the meta-agent to fire its first move…
          </div>
        )}
        {rows.map((r) => {
          const Icon =
            r.phase === 'tool_call' ? Wrench :
            r.phase === 'tool_result' ? (r.is_error ? AlertCircle : CheckCircle2) :
            r.phase === 'narration' ? Sparkles :
            r.phase === 'sub_started' ? ArrowRight :
            r.phase === 'sub_finished' ? CheckCircle2 :
            Activity;
          const colorClass = r.phase === 'narration'
            ? (TONE_COLOR[r.tone || 'info'] || 'text-slate-300')
            : (PHASE_COLOR[r.phase] || 'text-slate-300');
          return (
            <div key={r.id} className="px-2 py-1 rounded hover:bg-slate-900/50">
              <div className={`flex items-center gap-1.5 ${colorClass}`}>
                <Icon className="w-3 h-3 shrink-0" />
                <span className="text-slate-500 font-mono text-[10px]">{formatTs(r.ts)}</span>
                {r.agent && (
                  <span className="text-slate-400 text-[10px] font-semibold">{shortLabel(r.agent)}</span>
                )}
                <span className="text-[10px] uppercase tracking-wider opacity-70">{r.phase.replace('_', ' ')}</span>
                <span className="font-semibold">{r.primary}</span>
              </div>
              {r.secondary && (
                <div className="text-slate-500 ml-6 truncate" title={r.secondary}>{r.secondary}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
