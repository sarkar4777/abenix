'use client';

import { useEffect, useState } from 'react';
import {
  Shield, AlertTriangle, CheckCircle2, Trash2, Plus, Edit, Save,
  Eye, Ban, Flag, PencilRuler, Loader2, Play,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';
import { MODERATION_SOURCE_LABEL, moderationCategoryLabel } from '@/lib/nav-walk';
import Link from 'next/link';
import { useApi } from '@/hooks/useApi';
import RetentionCard from '@/components/moderation/RetentionCard';
import MaskedText from '@/components/moderation/MaskedText';
import { holdMinutesError } from '@/lib/moderation-review';
import { readableInput } from '@/lib/readable-input';

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
  hold_timeout_minutes?: number;
  hold_timeout_action?: 'reject' | 'release';
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

const SOURCE_LABEL = MODERATION_SOURCE_LABEL;

function categoryLabel(cat: string, policy?: Policy): string {
  return moderationCategoryLabel(cat, policy?.custom_patterns);
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
    hold_timeout_minutes: '60',
    hold_timeout_action: 'reject',
  });
  const [creating, setCreating] = useState(false);
  const [saved, setSaved] = useState<{ hold: boolean; first: boolean } | null>(null);
  const holdError = form.default_action === 'hold' ? holdMinutesError(form.hold_timeout_minutes) : null;
  const { data: reviewCount } = useApi<{ pending: number; can_review: boolean }>('/api/moderation/reviews/count');

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
    if (holdError) { setErr(holdError); return; }
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
        ...(form.default_action === 'hold'
          ? { hold_timeout_minutes: Number(form.hold_timeout_minutes), hold_timeout_action: form.hold_timeout_action }
          : {}),
      };
      await apiFetch('/api/moderation/policies', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setSaved({ hold: form.default_action === 'hold', first: policies.length === 0 });
      setForm({
        name: '', description: '',
        pre_llm: true, post_llm: true, on_tool_output: false,
        default_action: 'block', default_threshold: 0.5,
        custom_patterns: '', redaction_mask: '█████',
        hold_timeout_minutes: '60', hold_timeout_action: 'reject',
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

  const jumpTo = (sectionId: string, inputTestId?: string) => {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (inputTestId) document.querySelector<HTMLElement>(`[data-testid="${inputTestId}"]`)?.focus({ preventScroll: true });
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
      : outcome === 'held' ? 'bg-sky-100 text-sky-800 ring-sky-300'
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
      <PageHeader
        title="Content Moderation"
        purpose="Set rules that check what goes into and comes out of every agent, and block, mask, flag or hold anything that breaks them. For admins."
        icon={Shield}
        iconClassName="text-indigo-400"
        storageKey="moderation"
        docSlug="02-runtime/13-moderation-gate"
        primaryAction={{ label: 'New policy', icon: Plus, onClick: () => jumpTo('create-policy', 'policy-name-input') }}
        secondaryAction={{ label: 'Test content', icon: Play, onClick: () => jumpTo('vet-section', 'vet-input') }}
        steps={[
          { title: 'Create a policy', body: 'Pick what happens to a match: block, mask, flag, hold for review or just record it.' },
          { title: 'Choose where it checks', body: 'Before the model sees a message, on the reply, and on tool output if you want.' },
          { title: 'Test it', body: 'Paste sample text to see what the active policy would do with it.' },
          { title: 'Watch events', body: 'Every check is recorded under Recent events. Held items wait in the review inbox.' },
        ]}
        howItWorks={
          <p className="text-xs text-slate-400">
            Agents can also check text on demand with the moderation check tool, if you add it to them.
          </p>
        }
      />

      {reviewCount?.can_review && (
        <Link
          href="/review-queue?tab=held"
          data-testid="moderation-review-link"
          className="flex flex-wrap items-center gap-2 rounded-lg border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-sm text-sky-100 hover:bg-sky-500/10"
        >
          <Eye className="w-4 h-4" />
          {reviewCount.pending > 0
            ? `${reviewCount.pending} ${reviewCount.pending === 1 ? 'item is' : 'items are'} waiting in the review inbox`
            : 'Nothing is waiting in the review inbox'}
          <span className="ml-auto text-xs text-sky-300 underline">Open the review inbox</span>
        </Link>
      )}

      {err && (
        <div className="flex items-start gap-2 bg-rose-500/10 border border-rose-500/30 text-rose-200 rounded-lg p-3 text-sm"
             data-testid="moderation-error">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{err}</span>
        </div>
      )}

      {/* ── Create policy ───────────────────────────────────────── */}
      <section id="create-policy" className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 scroll-mt-20"
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
              <option value="hold">Hold for review</option>
              <option value="flag">Flag</option>
              <option value="allow">Allow (observe-only)</option>
            </select>
          </label>
          {form.default_action === 'hold' && (
            <div className="md:col-span-2 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 grid grid-cols-1 sm:grid-cols-2 gap-3" data-testid="policy-hold-settings">
              <p className="sm:col-span-2 text-xs text-slate-300 leading-relaxed">
                Matching messages and replies wait in the <Link href="/review-queue?tab=held" className="text-cyan-300 hover:underline">review inbox</Link> until
                someone with the Review held content permission releases, redacts or rejects them. The person sees that it is waiting.
              </p>
              <label className="space-y-1">
                <span className="text-xs text-slate-400">Reviewers have this many minutes</span>
                <input
                  data-testid="policy-hold-minutes"
                  inputMode="numeric"
                  aria-invalid={!!holdError}
                  className={`w-full bg-slate-900/50 border rounded px-3 py-2 text-sm text-white ${holdError ? 'border-rose-500/60' : 'border-slate-700/50'}`}
                  value={form.hold_timeout_minutes}
                  onChange={(e) => setForm({ ...form, hold_timeout_minutes: e.target.value })}
                />
                {holdError && <span className="block text-xs text-rose-300">{holdError}</span>}
              </label>
              <label className="space-y-1">
                <span className="text-xs text-slate-400">If nobody decides in time</span>
                <select
                  data-testid="policy-hold-timeout-action"
                  className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white"
                  value={form.hold_timeout_action}
                  onChange={(e) => setForm({ ...form, hold_timeout_action: e.target.value })}
                >
                  <option value="reject">Reject it, nothing is sent (safer)</option>
                  <option value="release">Release it as written</option>
                </select>
              </label>
            </div>
          )}
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
            disabled={creating || !!holdError}
            title={holdError || undefined}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm px-4 py-2 rounded-lg inline-flex items-center gap-2 disabled:opacity-50"
          >
            {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save policy
          </button>
        </div>
      </section>

      {saved && (
        <NextSteps
          title={saved.first ? 'Your first policy is on. What next?' : 'Policy saved. What next?'}
          testId="moderation-next-steps"
          onDismiss={() => setSaved(null)}
          steps={[
            { id: 'test', label: 'Try sample text', hint: 'Paste some text and see what the policy does.', icon: Play, onClick: () => { setSaved(null); jumpTo('vet-section', 'vet-input'); } },
            ...(saved.hold && reviewCount?.can_review
              ? [{ id: 'review', label: 'Open the review inbox', hint: 'Held messages wait here for a decision.', icon: Eye, href: '/review-queue?tab=held' }]
              : []),
            { id: 'chat', label: 'Try it in a chat', hint: 'Send a message to an agent and watch the policy act.', icon: Shield, href: '/chat' },
            { id: 'events', label: 'Watch events', hint: 'Every check the policy makes is listed here.', icon: Flag, onClick: () => { setSaved(null); jumpTo('events-section'); } },
          ]}
        />
      )}

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
                   className="flex flex-wrap items-start gap-x-3 gap-y-2 border border-slate-700/50 bg-slate-900/40 rounded-lg p-3">
                <div className={`mt-1 w-2 h-2 shrink-0 rounded-full ${p.is_active ? 'bg-emerald-500' : 'bg-slate-600'}`} />
                <div className="flex-1 min-w-[min(14rem,100%)]">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className="font-medium text-sm text-white break-words" data-testid={`policy-name-${p.id}`}>
                      {p.name}
                    </span>
                    <span className="text-xs text-slate-400">
                      · default <b>{p.default_action === 'hold' ? 'hold for review' : p.default_action}</b> · threshold {p.default_threshold.toFixed(2)}
                      {p.default_action === 'hold' && ` · ${p.hold_timeout_action === 'release' ? 'releases' : 'rejects'} after ${p.hold_timeout_minutes ?? 60} min`}
                      {p.pre_llm && ' · pre-LLM'}
                      {p.post_llm && ' · post-LLM'}
                      {p.on_tool_output && ' · tool-output'}
                    </span>
                  </div>
                  {p.description && (
                    <p className="text-xs text-slate-400 mt-0.5 break-words">{p.description}</p>
                  )}
                  {p.custom_patterns.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {p.custom_patterns.map((x, i) => (
                        <code key={i}
                              className="text-[11px] bg-slate-800/60 text-slate-300 px-1.5 py-0.5 rounded font-mono break-all">
                          {x}
                        </code>
                      ))}
                    </div>
                  )}
                </div>
                <div className="ml-auto flex shrink-0 items-center gap-1">
                  <button
                    data-testid={`policy-toggle-${p.id}`}
                    onClick={() => togglePolicy(p)}
                    className="shrink-0 text-xs text-slate-200 border border-slate-700/60 rounded px-2 py-1 hover:bg-slate-800/60"
                  >
                    {p.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                  <button
                    data-testid={`policy-delete-${p.id}`}
                    onClick={() => deletePolicy(p)}
                    className="shrink-0 text-rose-400 hover:bg-rose-500/10 rounded p-1"
                    title="Delete"
                    aria-label={`Delete ${p.name}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <RetentionCard />

      {/* ── Vet playground ──────────────────────────────────────── */}
      <section id="vet-section" className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 scroll-mt-20"
               data-testid="vet-section">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2 text-white">
          <Play className="w-4 h-4" /> Test content
        </h2>
        <p className="text-xs text-slate-400 mb-3">
          Checks the text against the active policy, exactly as an agent run would, and records the result under Recent events.
        </p>
        <textarea
          data-testid="vet-input"
          value={vetInput}
          onChange={(e) => setVetInput(e.target.value)}
          aria-label="Content to test"
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
            Test it
          </button>
        </div>
        {vetResult && (
          <div className="mt-4 border border-slate-700/50 bg-slate-900/40 rounded-lg p-3" data-testid="vet-result">
            <div className="flex flex-wrap items-center gap-2">
              <span data-testid="vet-result-outcome">{outcomeBadge(vetResult.outcome)}</span>
              <span className="text-sm text-slate-200 break-words min-w-0">
                action <b data-testid="vet-result-action">{vetResult.action}</b>
                {vetResult.triggered_categories.length > 0 && (
                  <> · matched <span data-testid="vet-result-categories">
                    {vetResult.triggered_categories.map((c) => categoryLabel(c, policies.find((p) => p.id === vetResult.policy_id))).join(', ')}
                  </span></>
                )}
                {' · '}{vetResult.latency_ms} ms
              </span>
            </div>
            {vetResult.outcome === 'held' && (
              <p className="mt-2 text-xs text-sky-200" data-testid="vet-result-held">
                In a real run this would wait in the review inbox for a person to release, redact or reject it. Tests here are not sent for review.
              </p>
            )}
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
      <section id="events-section" className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 scroll-mt-20"
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
              <div key={e.id} className="py-2 flex flex-wrap sm:flex-nowrap items-start gap-3" data-testid={`event-row-${e.id}`}>
                {outcomeBadge(e.outcome)}
                <div className="flex-1 min-w-0 text-xs">
                  <div className="text-slate-300 break-words">
                    <span className="bg-slate-800/60 text-slate-200 px-1 rounded" title={e.source}>{SOURCE_LABEL[e.source] || e.source}</span>
                    {e.acted_categories.length > 0 && (
                      <> · <span>{e.acted_categories.slice(0, 4).map((c) => categoryLabel(c, policies.find((p) => p.id === e.policy_id))).join(', ')}</span></>
                    )}
                    {' · '}{e.latency_ms} ms
                    {e.execution_id && (
                      <>
                        {' · '}
                        <a href={`/executions/${e.execution_id}`} className="text-cyan-300 hover:underline" data-testid={`event-run-${e.id}`}>View run</a>
                      </>
                    )}
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
                      <MaskedText text={readableInput(e.content_preview)} />
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
