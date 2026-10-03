'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { TIER_STYLE } from '@/components/governance/TierPolicies';
import { SCHEDULES, pct, type Tier } from '@/lib/evals';

interface AgentOption {
  id: string;
  name: string;
  model_config?: { mode?: string; risk_tier?: Tier; model?: string };
}

export default function CreateSuiteDialog({ onClose, agentId }: { onClose: () => void; agentId?: string }) {
  const router = useRouter();
  const { data: agents } = useApi<AgentOption[]>('/api/agents?limit=100');
  const [agent, setAgent] = useState(agentId || '');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [threshold, setThreshold] = useState(0.9);
  const [gating, setGating] = useState(false);
  const [cron, setCron] = useState<string | null>(null);
  const [rerun, setRerun] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const picked = (agents || []).find((a) => a.id === agent);
  const tier = (picked?.model_config?.risk_tier || 'low') as Tier;
  const isPipeline = picked?.model_config?.mode === 'pipeline';

  async function create() {
    setBusy(true);
    setErr(null);
    const r = await apiFetch<{ id: string }>('/api/evals/suites', {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), description, agent_id: agent, pass_threshold: threshold, gating, schedule_cron: cron, rerun_on_model_change: rerun && !isPipeline }),
      throwOnError: false,
    });
    setBusy(false);
    if (r.error || !r.data) setErr(r.error || 'The suite could not be created.');
    else router.push(`/evals/${r.data.id}`);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="new-suite-title">
      <div className="w-full max-w-xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="new-suite-title" className="text-lg font-semibold text-white">New evaluation suite</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <div>
            <label htmlFor="es-agent" className="block text-sm font-medium text-slate-200 mb-1.5">Agent or pipeline</label>
            <select id="es-agent" value={agent} onChange={(e) => { setAgent(e.target.value); const a = (agents || []).find((x) => x.id === e.target.value); if (a && !name) setName(`${a.name} golden cases`); const t = a?.model_config?.risk_tier; setGating(t === 'high' || t === 'critical'); }} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" data-testid="eval-suite-agent">
              <option value="">Pick one…</option>
              {(agents || []).map((a) => (
                <option key={a.id} value={a.id}>{a.name}{a.model_config?.mode === 'pipeline' ? ' (pipeline)' : ''}</option>
              ))}
            </select>
            {picked && <p className="mt-1 text-xs text-slate-500">{TIER_STYLE[tier].label} risk{isPipeline ? ', pipeline' : `, runs on ${picked.model_config?.model || 'the default model'}`}.</p>}
          </div>
          <div>
            <label htmlFor="es-name" className="block text-sm font-medium text-slate-200 mb-1.5">Name</label>
            <input id="es-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Underwriting golden cases" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" data-testid="eval-suite-name" />
          </div>
          <div>
            <label htmlFor="es-desc" className="block text-sm font-medium text-slate-200 mb-1.5">What it covers <span className="text-slate-500 font-normal">optional</span></label>
            <input id="es-desc" value={description} onChange={(e) => setDescription(e.target.value)} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <label htmlFor="es-th" className="flex items-center justify-between text-sm font-medium text-slate-200 mb-1.5">
              Pass threshold <span className="tabular-nums text-cyan-300">{pct(threshold)}</span>
            </label>
            <input id="es-th" type="range" min={0} max={1} step={0.05} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} className="w-full accent-cyan-500" />
            <p className="text-xs text-slate-500">The weighted share of cases that must pass for the run to pass.</p>
          </div>
          <label className="flex items-start gap-2 rounded-lg border border-slate-700 p-3 cursor-pointer">
            <input type="checkbox" checked={gating} onChange={(e) => setGating(e.target.checked)} className="accent-cyan-500 mt-0.5" data-testid="eval-suite-gating" />
            <span>
              <span className="block text-sm text-white">Gate publishing on this suite</span>
              <span className="block text-xs text-slate-400">When the risk policy for this agent&apos;s tier requires passing evaluations, high and critical by default, a new version publishes only after this suite passes against it.</span>
            </span>
          </label>
          <div>
            <label htmlFor="es-cron" className="block text-sm font-medium text-slate-200 mb-1.5">Schedule</label>
            <select id="es-cron" value={cron ?? ''} onChange={(e) => setCron(e.target.value || null)} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white">
              {SCHEDULES.map((s) => (
                <option key={s.label} value={s.cron ?? ''}>{s.label}</option>
              ))}
            </select>
          </div>
          {!isPipeline && (
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" checked={rerun} onChange={(e) => setRerun(e.target.checked)} className="accent-cyan-500" />
              Run again whenever the agent&apos;s model changes
            </label>
          )}
          {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={create} disabled={!agent || !name.trim() || busy} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="eval-suite-create">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Create and add cases
          </button>
        </div>
      </div>
    </div>
  );
}
