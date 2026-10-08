'use client';

import { useEffect, useState } from 'react';
import { BookOpen, Network } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';

interface Config {
  auto_accept_threshold: number;
  conflict_action: 'flag' | 'split' | 'lower_conf_wins' | 'higher_conf_wins';
  max_parallel_docs: number;
  daily_budget_usd: number | null;
  is_default?: boolean;
}

interface Conflict {
  id: string;
  entity: string;
  property: string;
  source_a: { doc_id: string; value: string; confidence: number };
  source_b: { doc_id: string; value: string; confidence: number };
  status: string;
}

export default function CognifyConfigPage() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch<Config>('/api/knowledge/cognify-config', { silent: true })
      .then(r => {
        if (r.data) setCfg(r.data);
        else setError(r.error || 'Could not load the settings.');
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
    apiFetch<{ items: Conflict[] }>('/api/knowledge/cognify-conflicts')
      .then(r => setConflicts(r.data?.items || []))
      .catch(() => {});
  }, []);

  async function save() {
    if (!cfg) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    const r = await apiFetch('/api/knowledge/cognify-config', { method: 'PUT', body: JSON.stringify(cfg), throwOnError: false });
    if (r.error) setError(r.error);
    else setSaved(true);
    setSaving(false);
  }

  async function resolve(id: string, value: string) {
    setError(null);
    try {
      await apiFetch(`/api/knowledge/cognify-conflicts/${id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ resolved_value: value }),
      });
      setConflicts(prev => prev.filter(c => c.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (cfg === null) {
    return (
      <main className="max-w-5xl mx-auto sm:px-6 py-2 sm:py-8 text-slate-300">
        {error ? (
          <p className="text-red-400 text-sm" role="alert" data-testid="cognify-load-error">Could not load the Cognify settings. {error}</p>
        ) : (
          <div className="h-40 rounded-xl bg-slate-800/40 animate-pulse" aria-busy="true" />
        )}
      </main>
    );
  }

  return (
    <main className="max-w-5xl mx-auto sm:px-6 py-2 sm:py-8 space-y-8">
      <PageHeader
        title="Cognify (knowledge graph)"
        icon={Network}
        purpose="Tune how facts pulled from your documents are let into the knowledge graph, and settle cases where two sources disagree. For knowledge base owners."
        primaryAction={{ label: 'Open knowledge bases', icon: BookOpen, href: '/knowledge' }}
        steps={[
          'Set how sure the extractor must be before a fact goes into the graph.',
          'Pick what happens when two documents disagree on the same fact.',
          'Cap how many documents run at once and how much a day may cost, then save.',
          'Settle open conflicts below by accepting one of the two values.',
        ]}
        docSlug="02-runtime/15-v2-knowledge-enterprise"
        storageKey="settings-cognify"
      />

      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 space-y-4">
        <h2 className="text-sm font-semibold text-cyan-300 uppercase tracking-wider">Acceptance + budget</h2>

        <label className="block">
          <span className="block text-xs text-slate-400">Auto-accept confidence threshold, from 0 to 1</span>
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={cfg.auto_accept_threshold}
            onChange={e => { setSaved(false); setCfg({ ...cfg, auto_accept_threshold: parseFloat(e.target.value) }); }}
            className="mt-1 w-32 rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white"
          />
          <span className="block mt-1 text-xs text-slate-500">
            Entities and relationships the extractor rates below this are left out of the graph and counted in the job report.
          </span>
        </label>

        <label className="block">
          <span className="text-xs text-slate-400">Conflict action</span>
          <select
            value={cfg.conflict_action}
            onChange={e => setCfg({ ...cfg, conflict_action: e.target.value as Config['conflict_action'] })}
            className="mt-1 w-56 rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white"
          >
            <option value="flag">Flag for human review (default)</option>
            <option value="split">Keep both, link as variants</option>
            <option value="lower_conf_wins">Lower-confidence value wins</option>
            <option value="higher_conf_wins">Higher-confidence value wins</option>
          </select>
        </label>

        <label className="block">
          <span className="text-xs text-slate-400">Max parallel docs per cognify job</span>
          <input
            type="number"
            min={1}
            max={64}
            value={cfg.max_parallel_docs}
            onChange={e => setCfg({ ...cfg, max_parallel_docs: parseInt(e.target.value, 10) || 1 })}
            className="mt-1 w-32 rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white"
          />
        </label>

        <label className="block">
          <span className="text-xs text-slate-400">Daily budget cap (USD, leave blank for none)</span>
          <input
            type="number"
            min={0}
            step={1}
            value={cfg.daily_budget_usd ?? ''}
            onChange={e => setCfg({ ...cfg, daily_budget_usd: e.target.value === '' ? null : parseFloat(e.target.value) })}
            className="mt-1 w-32 rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white"
          />
        </label>

        <button
          onClick={save}
          disabled={saving}
          className="rounded-md bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save config'}
        </button>
        {error && <p className="text-red-400 text-xs mt-2" role="alert">{error}</p>}
        {saved && !error && <p className="text-emerald-300 text-xs mt-2" role="status" data-testid="cognify-saved">Saved. The next cognify job uses these settings.</p>}
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="text-sm font-semibold text-cyan-300 uppercase tracking-wider mb-3">
          Open conflicts ({conflicts.length})
        </h2>
        {conflicts.length === 0 ? (
          <p className="text-sm text-slate-500">No open conflicts. Sources are coherent.</p>
        ) : (
          <ul className="space-y-3">
            {conflicts.map(c => (
              <li key={c.id} className="rounded-md border border-slate-800 bg-slate-950/60 p-4">
                <p className="text-sm text-white">
                  <span className="text-cyan-300">{c.entity}</span> · <span className="font-mono text-xs text-slate-400">{c.property}</span>
                </p>
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div className="text-xs text-slate-300">
                    <p className="text-slate-500 mb-1">Source A · conf {c.source_a.confidence.toFixed(2)}</p>
                    <p className="font-mono">{c.source_a.value}</p>
                    <button
                      onClick={() => resolve(c.id, c.source_a.value)}
                      className="mt-2 rounded bg-slate-800 hover:bg-slate-700 px-2 py-1 text-[10px] text-slate-200"
                    >
                      Accept A
                    </button>
                  </div>
                  <div className="text-xs text-slate-300">
                    <p className="text-slate-500 mb-1">Source B · conf {c.source_b.confidence.toFixed(2)}</p>
                    <p className="font-mono">{c.source_b.value}</p>
                    <button
                      onClick={() => resolve(c.id, c.source_b.value)}
                      className="mt-2 rounded bg-slate-800 hover:bg-slate-700 px-2 py-1 text-[10px] text-slate-200"
                    >
                      Accept B
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
