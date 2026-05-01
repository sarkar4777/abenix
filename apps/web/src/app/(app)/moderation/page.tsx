'use client';

import { useEffect, useState } from 'react';
import {
  Shield, AlertTriangle, CheckCircle2, Trash2, Plus, Edit, Save,
  Eye, Ban, Flag, PencilRuler, Loader2, Play,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';

interface Policy {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  pre_llm: boolean;
  post_llm: boolean;
  on_tool_output: boolean;
  provider: string;
  provider_model: string;
  thresholds: Record<string, number>;
  default_threshold: number;
  category_actions: Record<string, string>;
  default_action: string;
  custom_patterns: string[];
  redaction_mask: string;
  created_at: string | null;
  updated_at: string | null;
}

interface Event {
  id: string;
  policy_id: string | null;
  user_id: string | null;
  execution_id: string | null;
  source: string;
  outcome: string;
  content_preview: string | null;
  acted_categories: string[];
  latency_ms: number;
  created_at: string | null;
  provider_error?: string | null;
  provider_response?: any;
}

interface VetResult {
  event_id: string;
  outcome: string;
  action: string;
  flagged: boolean;
  triggered_categories: string[];
  category_scores: Record<string, number>;
  reason: string;
  latency_ms: number;
  policy_id: string | null;
  redacted_content?: string;
  provider_error?: string;
}

export default function ModerationPage() {
  usePageTitle('Moderation');

  const [policies, setPolicies] = useState<Policy[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Create-policy form
  const [form, setForm] = useState({
    name: '',
    description: '',
    pre_llm: true,
    post_llm: true,
    on_tool_output: false,
    default_action: 'block',
    default_threshold: 0.5,
    custom_patterns: '', // newline separated
    redaction_mask: '█████',
  });
  const [creating, setCreating] = useState(false);

  // Vet playground
  const [vetInput, setVetInput] = useState('');
  const [vetStrict, setVetStrict] = useState(false);
  const [vetResult, setVetResult] = useState<VetResult | null>(null);
  const [vetting, setVetting] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [pR, eR] = await Promise.all([
        apiFetch<Policy[]>('/api/moderation/policies'),
        apiFetch<Event[]>('/api/moderation/events?limit=100'),
      ]);
      setPolicies(pR.data || []);
      setEvents(eR.data || []);
    } catch (e: any) {
      setErr(e?.message || 'load failed');
    }
    setLoading(false);
  };

  useEffect(() => { loadAll(); }, []);

  const savePolicy = async () => {
    if (!form.name.trim()) { setErr('Name is required'); return; }
    setCreating(true);
    setErr(null);
    try {
      const custom_patterns = form.custom_patterns
        .split('\n').map((s) => s.trim()).filter(Boolean);
      const body = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        is_active: true,
        pre_llm: form.pre_llm,
        post_llm: form.post_llm,
        on_tool_output: form.on_tool_output,
        default_action: form.default_action,
        default_threshold: Number(form.default_threshold) || 0.5,
        custom_patterns,
        redaction_mask: form.redaction_mask || '█████',
      };
      await apiFetch('/api/moderation/policies', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setForm({
        name: '', description: '',
        pre_llm: true, post_llm: true, on_tool_output: false,
        default_action: 'block', default_threshold: 0.5,
        custom_patterns: '', redaction_mask: '█████',
      });
      await loadAll();
    } catch (e: any) {
      setErr(e?.message || 'create failed');
    }
    setCreating(false);
  };

  const togglePolicy = async (p: Policy) => {
    try {
      await apiFetch(`/api/moderation/policies/${p.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !p.is_active }),
      });
      await loadAll();
    } catch (e: any) {
      setErr(e?.message || 'toggle failed');
    }
  };

  const deletePolicy = async (p: Policy) => {
    if (!confirm(`Delete policy "${p.name}"?`)) return;
    try {
      await apiFetch(`/api/moderation/policies/${p.id}`, { method: 'DELETE' });
      await loadAll();
    } catch (e: any) {
      setErr(e?.message || 'delete failed');
    }
  };

  const runVet = async () => {
    if (!vetInput.trim()) return;
    setVetting(true);
    setVetResult(null);
    setErr(null);
    try {
      const r = await apiFetch<VetResult>('/api/moderation/vet', {
        method: 'POST',
        body: JSON.stringify({ content: vetInput, strict: vetStrict }),
      });
      setVetResult(r.data);
      await loadAll();
    } catch (e: any) {
      setErr(e?.message || 'vet failed');
    }
    setVetting(false);
  };

  const outcomeBadge = (outcome: string) => {
    const color = outcome === 'blocked' ? 'bg-rose-100 text-rose-800 ring-rose-300'
      : outcome === 'flagged' ? 'bg-amber-100 text-amber-800 ring-amber-300'
      : outcome === 'redacted' ? 'bg-violet-100 text-violet-800 ring-violet-300'
      : outcome === 'allowed' ? 'bg-emerald-100 text-emerald-800 ring-emerald-300'
      : 'bg-slate-700/40 text-slate-200 ring-slate-600/50';
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ring-1 ${color}`}>
        {outcome}
      </span>
    );
  };

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6" data-testid="moderation-page">
      <div className="flex items-center gap-3">
        <Shield className="w-6 h-6 text-indigo-400" />
        <h1 className="text-2xl font-bold text-white">Content Moderation</h1>
      </div>
      <p className="text-sm text-slate-400">
        Tenant-wide policies applied automatically pre-LLM, post-LLM, or on tool output.
        The <code className="font-mono text-xs bg-slate-800/60 text-cyan-300 px-1 rounded">moderation_vet</code> tool
        is also available to agents that opt in.
      </p>

      {err && (
        <div className="flex items-start gap-2 bg-rose-500/10 border border-rose-500/30 text-rose-200 rounded-lg p-3 text-sm"
             data-testid="moderation-error">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{err}</span>
        </div>
      )}

      {/* ── Create policy ───────────────────────────────────────── */}
      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5"
               data-testid="create-policy-section">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2 text-white">
          <Plus className="w-4 h-4" /> Create / Activate Policy
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Name</span>
            <input
              data-testid="policy-name-input"
              className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Strict customer-email policy"
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Description</span>
            <input
              data-testid="policy-description-input"
              className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Default action</span>
            <select
              data-testid="policy-default-action"
              className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
              value={form.default_action}
              onChange={(e) => setForm({ ...form, default_action: e.target.value })}
            >
              <option value="block">Block</option>
              <option value="redact">Redact</option>
              <option value="flag">Flag</option>
              <option value="allow">Allow (observe-only)</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Default threshold (0–1)</span>
            <input
              data-testid="policy-threshold"
              type="number" step="0.05" min="0" max="1"
              className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
              value={form.default_threshold}
              onChange={(e) => setForm({ ...form, default_threshold: Number(e.target.value) })}
            />
          </label>
          <label className="md:col-span-2 space-y-1">
            <span className="text-xs text-slate-400">Custom patterns (one per line, regex)</span>
            <textarea
              data-testid="policy-custom-patterns"
              className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm font-mono min-h-[80px] text-white placeholder-slate-500"
              value={form.custom_patterns}
              onChange={(e) => setForm({ ...form, custom_patterns: e.target.value })}
              placeholder={"codename[-_ ]?aurora\ninternal\\s+roadmap"}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Redaction mask</span>
            <input
              data-testid="policy-redaction-mask"
              className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
              value={form.redaction_mask}
              onChange={(e) => setForm({ ...form, redaction_mask: e.target.value })}
            />
          </label>
          <div className="md:col-span-2 flex flex-wrap gap-4 items-end pt-1">
            <label className="inline-flex items-center gap-2 text-sm text-slate-300">
              <input
                data-testid="policy-pre-llm"
                type="checkbox"
                checked={form.pre_llm}
                onChange={(e) => setForm({ ...form, pre_llm: e.target.checked })}
              /> pre-LLM
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-slate-300">
              <input
                data-testid="policy-post-llm"
                type="checkbox"
                checked={form.post_llm}
                onChange={(e) => setForm({ ...form, post_llm: e.target.checked })}
              /> post-LLM
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-slate-300">
              <input
                data-testid="policy-on-tool-output"
                type="checkbox"
                checked={form.on_tool_output}
                onChange={(e) => setForm({ ...form, on_tool_output: e.target.checked })}
              /> tool output
            </label>
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            data-testid="create-policy-button"
            onClick={savePolicy}
            disabled={creating}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm px-4 py-2 rounded-lg inline-flex items-center gap-2 disabled:opacity-50"
          >
            {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save policy
          </button>
        </div>
      </section>

      {/* ── Policy list ─────────────────────────────────────────── */}
      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5"
               data-testid="policies-section">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2 text-white">
          <Shield className="w-4 h-4" /> Policies
          <span className="text-xs text-slate-400 font-normal ml-1">
            ({policies.length} total, {policies.filter((p) => p.is_active).length} active)
          </span>
        </h2>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : policies.length === 0 ? (
          <p className="text-sm text-slate-400" data-testid="policies-empty">
            No policies yet. Create one above to start applying moderation.
          </p>
        ) : (
          <div className="space-y-2" data-testid="policies-list">
            {policies.map((p) => (
              <div key={p.id}
                   data-testid={`policy-row-${p.id}`}
                   className="flex items-start gap-3 border border-slate-700/50 bg-slate-900/40 rounded-lg p-3">
                <div className={`mt-1 w-2 h-2 rounded-full ${p.is_active ? 'bg-emerald-500' : 'bg-slate-600'}`} />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm text-white" data-testid={`policy-name-${p.id}`}>
                      {p.name}
                    </span>
                    <span className="text-xs text-slate-400">
                      · default <b>{p.default_action}</b> · threshold {p.default_threshold.toFixed(2)}
                      {p.pre_llm && ' · pre-LLM'}
                      {p.post_llm && ' · post-LLM'}
                      {p.on_tool_output && ' · tool-output'}
                    </span>
                  </div>
                  {p.description && (
                    <p className="text-xs text-slate-400 mt-0.5">{p.description}</p>
                  )}
                  {p.custom_patterns.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {p.custom_patterns.map((x, i) => (
                        <code key={i}
                              className="text-[11px] bg-slate-800/60 text-slate-300 px-1.5 py-0.5 rounded font-mono">
                          {x}
                        </code>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  data-testid={`policy-toggle-${p.id}`}
                  onClick={() => togglePolicy(p)}
                  className="text-xs text-slate-200 border border-slate-700/60 rounded px-2 py-1 hover:bg-slate-800/60"
                >
                  {p.is_active ? 'Deactivate' : 'Activate'}
                </button>
                <button
                  data-testid={`policy-delete-${p.id}`}
                  onClick={() => deletePolicy(p)}
                  className="text-rose-400 hover:bg-rose-500/10 rounded p-1"
                  title="Delete"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Vet playground ──────────────────────────────────────── */}
      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5"
               data-testid="vet-section">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2 text-white">
          <Play className="w-4 h-4" /> Vet content
        </h2>
        <textarea
          data-testid="vet-input"
          value={vetInput}
          onChange={(e) => setVetInput(e.target.value)}
          placeholder="Paste content to screen against the active policy…"
          className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500 min-h-[100px]"
        />
        <div className="mt-3 flex items-center gap-3">
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              data-testid="vet-strict"
              type="checkbox"
              checked={vetStrict}
              onChange={(e) => setVetStrict(e.target.checked)}
            /> Strict (threshold 0.3 + force block)
          </label>
          <button
            data-testid="vet-button"
            onClick={runVet}
            disabled={vetting || !vetInput.trim()}
            className="ml-auto bg-indigo-600 hover:bg-indigo-700 text-white text-sm px-4 py-2 rounded-lg inline-flex items-center gap-2 disabled:opacity-50"
          >
            {vetting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Run /vet
          </button>
        </div>
        {vetResult && (
          <div className="mt-4 border border-slate-700/50 bg-slate-900/40 rounded-lg p-3" data-testid="vet-result">
            <div className="flex items-center gap-2">
              <span data-testid="vet-result-outcome">{outcomeBadge(vetResult.outcome)}</span>
              <span className="text-sm">
                action <b data-testid="vet-result-action">{vetResult.action}</b>
                {vetResult.triggered_categories.length > 0 && (
                  <> · triggered <span data-testid="vet-result-categories">
                    {vetResult.triggered_categories.join(', ')}
                  </span></>
                )}
                {' · '}{vetResult.latency_ms} ms
              </span>
            </div>
            {vetResult.redacted_content && (
              <div className="mt-2">
                <div className="text-xs text-slate-400">Redacted content:</div>
                <pre className="mt-1 text-xs bg-slate-950/60 border border-slate-700/50 text-slate-200 rounded p-2 whitespace-pre-wrap"
                     data-testid="vet-result-redacted">{vetResult.redacted_content}</pre>
              </div>
            )}
            {vetResult.provider_error && (
              <div className="mt-2 text-xs text-amber-700" data-testid="vet-result-provider-error">
                Provider error: {vetResult.provider_error}
              </div>
            )}
          </div>
        )}
      </section>

      {/* ── Events ──────────────────────────────────────────────── */}
      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5"
               data-testid="events-section">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2 text-white">
          <Flag className="w-4 h-4" /> Recent events
        </h2>
        {events.length === 0 ? (
          <p className="text-sm text-slate-400" data-testid="events-empty">
            No events yet.
          </p>
        ) : (
          <div className="divide-y divide-slate-700/40" data-testid="events-list">
            {events.map((e) => (
              <div key={e.id} className="py-2 flex items-start gap-3" data-testid={`event-row-${e.id}`}>
                {outcomeBadge(e.outcome)}
                <div className="flex-1 text-xs">
                  <div className="text-slate-300">
                    <code className="bg-slate-800/60 text-slate-200 px-1 rounded">{e.source}</code>
                    {e.acted_categories.length > 0 && (
                      <> · <span>{e.acted_categories.slice(0, 4).join(', ')}</span></>
                    )}
                    {' · '}{e.latency_ms} ms
                  </div>
                  {/* Provider-side failure (e.g. OpenAI 429 quota). Shows
                      WHY the gate emitted "error" instead of an actual verdict. */}
                  {e.outcome === 'error' && e.provider_error && (
                    <div className="mt-1 inline-flex items-start gap-1.5 text-[11px] text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded px-1.5 py-0.5"
                         data-testid={`provider-error-${e.id}`}
                         title={e.provider_error}>
                      <span className="font-semibold">provider:</span>
                      <span className="line-clamp-2 break-all">{e.provider_error}</span>
                    </div>
                  )}
                  {e.outcome === 'error' && !e.provider_error && (
                    <div className="mt-1 text-[11px] text-amber-300/80">
                      Gate failed but no provider error was captured (legacy event — re-run to repopulate).
                    </div>
                  )}
                  {e.content_preview && (
                    <pre className="mt-1 text-[11px] text-slate-400 whitespace-pre-wrap break-words line-clamp-3">
                      {e.content_preview}
                    </pre>
                  )}
                </div>
                <span className="text-[11px] text-slate-500">
                  {e.created_at ? new Date(e.created_at).toLocaleString() : ''}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
