'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChevronDown, ChevronRight, Fingerprint, Loader2, RotateCcw } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { TIER_STYLE, type Tier } from './TierPolicies';

interface Provenance {
  execution_id: string;
  agent_revision: number | null;
  prompt_hash: string | null;
  risk_tier: Tier | null;
  risk_reasons: { tier: string; source: string; detail: string }[];
  provenance: { config_hash?: string; model?: string; tools?: string[]; agent_version?: string; replay_of?: string };
  snapshot: { system_prompt: string; model_config: any } | null;
  changed_since: string[];
  agent_deleted: boolean;
}

interface ReplayResult {
  execution_id: string;
  mode: string;
  same_output: boolean;
  same_tools: boolean;
  original: { output: string | null; model: string | null; tools: string[] };
  replay: { output: string | null; model: string | null; tools: string[]; error: string | null };
}

export default function ProvenancePanel({ executionId, isPipeline }: { executionId: string; isPipeline: boolean }) {
  const { perms } = useMyPermissions();
  const canReplay = holds(perms?.capabilities, 'runs.replay');
  const { data } = useApi<Provenance>(canReplay ? `/api/governance/runs/${executionId}/provenance` : null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [res, setRes] = useState<ReplayResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (!canReplay || !data) return null;
  const tier = (data.risk_tier || 'low') as Tier;

  async function replay(mode: 'pinned' | 'current') {
    setBusy(mode);
    setErr(null);
    setRes(null);
    const r = await apiFetch<ReplayResult>(`/api/governance/runs/${executionId}/replay`, { method: 'POST', body: JSON.stringify({ mode }), throwOnError: false });
    setBusy(null);
    if (r.data) setRes(r.data);
    else setErr(r.error || 'Replay failed');
  }

  return (
    <div className="bg-slate-800/30 backdrop-blur-xl border border-slate-700/50 rounded-xl p-4" data-testid="execution-provenance">
      <button type="button" onClick={() => setOpen((o) => !o)} className="w-full flex flex-wrap items-center gap-2 text-left">
        {open ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
        <Fingerprint className="w-4 h-4 text-cyan-400" />
        <span className="text-sm font-semibold text-white">What this run used</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${TIER_STYLE[tier].chip}`} data-testid="execution-risk-tier">{TIER_STYLE[tier].label} risk</span>
        {data.provenance?.replay_of && <span className="text-[10px] text-slate-400">replay of {data.provenance.replay_of.slice(0, 8)}</span>}
        {data.changed_since.length > 0 && <span className="text-[11px] text-amber-300">agent changed since: {data.changed_since.join(', ')}</span>}
      </button>
      {open && (
        <div className="mt-3 space-y-3 text-xs">
          <dl className="grid gap-2 sm:grid-cols-4">
            <div><dt className="text-slate-500">Model</dt><dd className="text-slate-200">{data.provenance?.model || '—'}</dd></div>
            <div><dt className="text-slate-500">Agent revision</dt><dd className="text-slate-200">{data.agent_revision ?? '—'}</dd></div>
            <div><dt className="text-slate-500">Prompt hash</dt><dd className="text-slate-200 font-mono">{data.prompt_hash ? `${data.prompt_hash.slice(0, 12)}…` : '—'}</dd></div>
            <div><dt className="text-slate-500">Config hash</dt><dd className="text-slate-200 font-mono">{data.provenance?.config_hash ? `${data.provenance.config_hash.slice(0, 12)}…` : '—'}</dd></div>
          </dl>
          {data.risk_reasons.length > 0 && (
            <div>
              <div className="text-slate-500 mb-1">Why it reached {TIER_STYLE[tier].label.toLowerCase()} risk</div>
              <ul className="space-y-0.5">{data.risk_reasons.map((r, i) => <li key={i} className="text-slate-300">{r.source} raised it to {r.tier}{r.detail ? `, ${r.detail}` : ''}</li>)}</ul>
            </div>
          )}
          {data.provenance?.tools && data.provenance.tools.length > 0 && <div className="text-slate-400">Tools available: {data.provenance.tools.join(', ')}</div>}
          {data.agent_deleted ? (
            <p className="text-slate-500">The agent was deleted, so this run cannot be replayed.</p>
          ) : isPipeline ? (
            <p className="text-slate-500">Pipeline runs replay from a step, using the Replay button on a step below.</p>
          ) : (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button type="button" onClick={() => replay('pinned')} disabled={!!busy || !data.snapshot} title={data.snapshot ? '' : 'This run predates recorded configurations'} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-700 text-white hover:bg-slate-600 disabled:opacity-40" data-testid="replay-pinned">
                {busy === 'pinned' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />} Replay exactly as it ran
              </button>
              <button type="button" onClick={() => replay('current')} disabled={!!busy} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-slate-600 text-slate-200 hover:bg-slate-800 disabled:opacity-40" data-testid="replay-current">
                {busy === 'current' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />} Replay on the agent as it is now
              </button>
              <span className="text-slate-500">Uses the same input. Model calls are billed again.</span>
            </div>
          )}
          {err && <p className="text-rose-300">{err}</p>}
          {res && (
            <div className="rounded-lg border border-slate-700 p-3 space-y-2" data-testid="replay-result">
              <div className="flex flex-wrap gap-3">
                <span className={res.same_output ? 'text-emerald-300' : 'text-amber-300'}>{res.same_output ? 'Same answer' : 'Different answer'}</span>
                <span className={res.same_tools ? 'text-emerald-300' : 'text-amber-300'}>{res.same_tools ? 'Same tool calls' : `Tools: ${res.original.tools.join(' → ') || 'none'} became ${res.replay.tools.join(' → ') || 'none'}`}</span>
                <Link href={`/executions/${res.execution_id}`} className="text-cyan-300 hover:underline">Open the replay</Link>
              </div>
              {res.replay.error && <p className="text-rose-300">{res.replay.error}</p>}
              {!res.same_output && (
                <div className="grid gap-2 md:grid-cols-2">
                  <div><div className="text-slate-500 mb-0.5">Original</div><pre className="whitespace-pre-wrap text-slate-300 max-h-48 overflow-auto">{res.original.output}</pre></div>
                  <div><div className="text-slate-500 mb-0.5">Replay</div><pre className="whitespace-pre-wrap text-slate-200 max-h-48 overflow-auto">{res.replay.output}</pre></div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
