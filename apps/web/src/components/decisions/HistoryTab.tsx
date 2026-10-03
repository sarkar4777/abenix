'use client';

import { useEffect, useMemo, useState } from 'react';
import { GitCompare, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { STATE_LABEL, STATE_STYLE, type VersionSummary } from '@/lib/decisions';

interface Diff {
  from: number; to: number; same_content: boolean; mode: 'rules' | 'content';
  added?: string[]; removed?: string[]; changed?: { rule: string; fields: string[] }[];
  facts_added?: string[]; facts_removed?: string[];
  valid_period?: { from: [string | null, string | null]; to: [string | null, string | null] };
}

const day = (s: string | null) => (s ? s.slice(0, 10) : null);

function Timeline({ versions, onOpen }: { versions: VersionSummary[]; onOpen: (n: number) => void }) {
  const shown = versions.filter((v) => v.published_at);
  const dates = shown.flatMap((v) => [v.valid_from, v.valid_to]).filter(Boolean).map((d) => new Date(d!).getTime());
  const now = Date.now();
  const lo = Math.min(...dates, now - 365 * 864e5);
  const hi = Math.max(...dates, now + 365 * 864e5);
  const pct = (t: number) => ((t - lo) / (hi - lo)) * 100;
  if (!shown.length) return <p className="text-sm text-slate-500">Nothing has been published yet. Published versions appear here with the period they cover.</p>;
  return (
    <div className="space-y-2" data-testid="history-timeline">
      <div className="relative h-5 text-[10px] text-slate-500">
        <span className="absolute left-0">{new Date(lo).toISOString().slice(0, 10)}</span>
        <span className="absolute" style={{ left: `${pct(now)}%`, transform: 'translateX(-50%)' }}>today</span>
        <span className="absolute right-0">{new Date(hi).toISOString().slice(0, 10)}</span>
      </div>
      {shown.map((v) => {
        const a = v.valid_from ? pct(new Date(v.valid_from).getTime()) : 0;
        const b = v.valid_to ? pct(new Date(v.valid_to).getTime()) : 100;
        const inForce = v.state === 'published';
        return (
          <button key={v.id} type="button" onClick={() => onOpen(v.version)} className="relative block w-full h-7 rounded bg-slate-900/60 hover:bg-slate-800/60 text-left" title={`Version ${v.version}: ${STATE_LABEL[v.state]}`}>
            <span className="absolute inset-y-1 rounded" style={{ left: `${a}%`, width: `${Math.max(1, b - a)}%`, background: inForce ? 'rgba(16,185,129,.35)' : 'rgba(100,116,139,.35)' }} />
            <span className="absolute left-2 top-1 text-xs text-white">v{v.version}</span>
            <span className="absolute right-2 top-1 text-[10px] text-slate-400">
              {day(v.valid_from) || 'start'} → {day(v.valid_to) || 'open'} · published {day(v.published_at)}{v.superseded_at ? `, replaced ${day(v.superseded_at)}` : ''}
            </span>
          </button>
        );
      })}
      <p className="text-[11px] text-slate-500">
        Bars show when each version applies to the activity. The dates on the right show when the platform published or replaced it, so an evaluation can be repeated as it was known on any day.
      </p>
    </div>
  );
}

export default function HistoryTab({ decisionKey, versions, current, onOpen }: { decisionKey: string; versions: VersionSummary[]; current: number; onOpen: (n: number) => void }) {
  const sorted = useMemo(() => [...versions].sort((a, b) => b.version - a.version), [versions]);
  const [a, setA] = useState<number>(sorted[1]?.version ?? sorted[0]?.version ?? 1);
  const [b, setB] = useState<number>(current);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setB(current), [current]);

  async function compare() {
    setBusy(true);
    const r = await apiFetch<Diff>(`/api/decisions/${encodeURIComponent(decisionKey)}/diff?a=${a}&b=${b}`, { throwOnError: false });
    setBusy(false);
    if (r.data) setDiff(r.data);
  }

  return (
    <div className="space-y-6" data-testid="history-tab">
      <section>
        <h3 className="text-sm font-semibold text-white mb-2">When each version applies</h3>
        <Timeline versions={versions} onOpen={onOpen} />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-white mb-2">All versions</h3>
        <ul className="space-y-1">
          {sorted.map((v) => (
            <li key={v.id}>
              <button type="button" onClick={() => onOpen(v.version)} className={`w-full flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-left hover:border-slate-500 ${v.version === current ? 'border-cyan-500/50' : 'border-slate-800'}`}>
                <span className="text-sm text-white font-medium w-10">v{v.version}</span>
                <span className={`text-[11px] px-1.5 py-0.5 rounded border ${STATE_STYLE[v.state]}`}>{STATE_LABEL[v.state]}</span>
                <span className="text-xs text-slate-400 truncate flex-1">{v.change_note}</span>
                <span className="text-[11px] text-slate-500">{day(v.published_at || v.updated_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      {sorted.length > 1 && (
        <section>
          <h3 className="text-sm font-semibold text-white mb-2">Compare two versions</h3>
          <div className="flex items-center gap-2 text-sm">
            <select value={a} onChange={(e) => setA(Number(e.target.value))} className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-white" aria-label="From version">{sorted.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}</select>
            <span className="text-slate-500">to</span>
            <select value={b} onChange={(e) => setB(Number(e.target.value))} className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-white" aria-label="To version">{sorted.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}</select>
            <button type="button" onClick={compare} disabled={busy || a === b} className="inline-flex items-center gap-1 px-3 py-1 rounded bg-slate-800 text-white text-xs disabled:opacity-40" data-testid="history-compare">
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitCompare className="w-3.5 h-3.5" />} Compare
            </button>
          </div>
          {diff && (
            <div className="mt-3 rounded-xl border border-slate-800 p-4 text-sm space-y-1" data-testid="history-diff">
              {diff.same_content && <p className="text-slate-300">The rules are identical. Only notes or dates differ.</p>}
              {diff.mode === 'content' && !diff.same_content && <p className="text-slate-300">One of these versions was edited in the flow view, so only “changed” can be shown.</p>}
              {diff.added?.length ? <p className="text-emerald-300">Added: {diff.added.join(', ')}</p> : null}
              {diff.removed?.length ? <p className="text-rose-300">Removed: {diff.removed.join(', ')}</p> : null}
              {diff.changed?.map((c) => <p key={c.rule} className="text-amber-200">Changed {c.rule}: {c.fields.join(', ')}</p>)}
              {diff.facts_added?.length ? <p className="text-slate-300">New facts: {diff.facts_added.join(', ')}</p> : null}
              {diff.valid_period && (diff.valid_period.from[0] !== diff.valid_period.from[1] || diff.valid_period.to[0] !== diff.valid_period.to[1]) && (
                <p className="text-slate-300">Valid period: {day(diff.valid_period.from[0]) || 'start'} → {day(diff.valid_period.to[0]) || 'open'} became {day(diff.valid_period.from[1]) || 'start'} → {day(diff.valid_period.to[1]) || 'open'}</p>
              )}
              {!diff.same_content && diff.mode === 'rules' && !diff.added?.length && !diff.removed?.length && !diff.changed?.length && <p className="text-slate-300">Only the facts, outcomes or order changed.</p>}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
