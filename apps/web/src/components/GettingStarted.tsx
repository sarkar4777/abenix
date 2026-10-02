'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Circle, X, Compass } from 'lucide-react';
import { useApi } from '@/hooks/useApi';

// A checklist for someone new to the platform. Each step ticks itself off from
// the user's own data and links to the one place where it is done.

type Row = Record<string, any>;

function rows(data: unknown, ...keys: string[]): Row[] {
  if (Array.isArray(data)) return data as Row[];
  if (data && typeof data === 'object') {
    for (const k of keys) {
      const v = (data as Row)[k];
      if (Array.isArray(v)) return v as Row[];
    }
  }
  return [];
}

// Counts only what the caller owns, not what was shared with them.
const own = (r: Row[]) => r.filter((x) => x.ownership === 'mine');

const DISMISS_KEY = 'abenix.getting-started.dismissed';

export function GettingStarted() {
  const [dismissed, setDismissed] = useState(true);
  useEffect(() => {
    try {
      setDismissed(localStorage.getItem(DISMISS_KEY) === '1');
    } catch {
      setDismissed(false);
    }
  }, []);

  const { data: assets } = useApi<unknown>('/api/code-assets');
  const { data: kbs } = useApi<unknown>('/api/knowledge-bases?limit=100');
  const { data: graphs } = useApi<unknown>('/api/atlas/graphs');
  const { data: agents } = useApi<unknown>('/api/agents?scope=mine&limit=100');
  const { data: execs, meta: execMeta } = useApi<unknown>('/api/executions?limit=1');

  const steps = useMemo(() => {
    const mine = rows(agents, 'agents', 'items');
    const isPipeline = (a: Row) => a.mode === 'pipeline' || a.model_config?.mode === 'pipeline';
    const published = mine.some((a) => String(a.status || '').toLowerCase() === 'active');
    const runs = rows(execs, 'executions', 'items').length > 0 || Number((execMeta as Row | null)?.total || 0) > 0;
    return [
      { id: 'code', label: 'Upload your own code', hint: 'Zip or git repo, analysed and testable in place', href: '/code-runner', done: own(rows(assets, 'assets', 'items')).length > 0 },
      { id: 'kb', label: 'Create a knowledge base', hint: 'Upload documents your agents should cite', href: '/knowledge', done: own(rows(kbs, 'collections', 'items', 'knowledge_bases')).length > 0 },
      { id: 'atlas', label: 'Model your domain in Atlas', hint: 'Type plain sentences, they become a graph', href: '/atlas', done: own(rows(graphs, 'graphs', 'items')).length > 0 },
      { id: 'agent', label: 'Build an agent', hint: 'Start from any of the above with "Use in an agent"', href: '/builder', done: mine.some((a) => !isPipeline(a)) },
      { id: 'publish', label: 'Publish and chat with it', hint: 'Drafts become usable once published', href: '/agents', done: published },
      { id: 'pipeline', label: 'Chain agents into a pipeline', hint: 'Builder, Pipeline mode, add steps and tick dependencies', href: '/builder', done: mine.some(isPipeline) },
      { id: 'sdk', label: 'Call it from code', hint: 'SDK playground runs it live and writes the snippet', href: '/sdk-playground', done: runs && published },
    ];
  }, [assets, kbs, graphs, agents, execs, execMeta]);

  const doneCount = steps.filter((s) => s.done).length;
  const next = steps.find((s) => !s.done);
  if (dismissed || !next) return null;

  return (
    <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4" data-testid="getting-started">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <Compass className="w-4 h-4 text-cyan-400" />
          <h2 className="text-sm font-semibold text-white">Getting started</h2>
          <span className="text-[11px] text-slate-400">{doneCount} of {steps.length} done</span>
        </div>
        <button
          onClick={() => {
            setDismissed(true);
            try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* private mode */ }
          }}
          aria-label="Hide getting started"
          className="p-1 rounded text-slate-500 hover:text-white"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <ol className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2">
        {steps.map((s) => (
          <li key={s.id}>
            <Link
              href={s.href}
              data-testid={`getting-started-${s.id}`}
              data-done={s.done ? 'true' : 'false'}
              className={`flex items-start gap-2 rounded-lg border px-3 py-2 h-full transition-colors ${
                s === next
                  ? 'border-cyan-400/60 bg-cyan-500/10 hover:bg-cyan-500/15'
                  : 'border-slate-700/50 bg-slate-900/30 hover:border-slate-600'
              }`}
            >
              {s.done ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
              ) : (
                <Circle className={`w-4 h-4 shrink-0 mt-0.5 ${s === next ? 'text-cyan-300' : 'text-slate-600'}`} />
              )}
              <span>
                <span className={`block text-xs font-medium ${s.done ? 'text-slate-400 line-through' : 'text-white'}`}>
                  {s.label}
                  {s === next && <span className="ml-2 text-[10px] uppercase tracking-wider text-cyan-300">next</span>}
                </span>
                <span className="block text-[11px] text-slate-500">{s.hint}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}
