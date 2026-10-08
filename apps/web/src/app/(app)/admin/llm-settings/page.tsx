'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Cpu, Save, RotateCcw, Sparkles, Shield, BookOpen, Zap, Clock } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { settingTitle } from '@/lib/monitor-format';
import ModelPicker from '@/components/ModelPicker';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';

type Setting = {
  key: string;
  value: string;
  default: string;
  category: string;
  description: string;
  is_default: boolean;
  updated_at?: string | null;
  is_secret?: boolean;
  is_set?: boolean;
  /** "model" renders a picker, "int" a bounded number input. */
  kind?: 'model' | 'int';
  min?: number | null;
  max?: number | null;
};

type SubscriptionStatus = {
  enabled: boolean;
  token_set: boolean;
  token_source: string | null;
  token_masked: string;
  default_model: string;
  exclusive: boolean;
  active: boolean;
  billing: string;
};

// Rendered by its own card below, not the generic model-picker grid.
const SUBSCRIPTION_CATEGORY = 'claude_subscription';

type Model = {
  id: string;
  provider: 'anthropic' | 'google' | 'openai' | string;
  label: string;
  family: string;
};

type ApiResp = {
  categories: Record<string, Setting[]>;
  models: Model[];
};

const CATEGORY_META: Record<string, { label: string; icon: React.ReactNode; hint: string }> = {
  ai_builder:      { label: 'AI Builder',        icon: <Sparkles className="w-4 h-4" />, hint: 'Model the AI Builder uses to turn plain-English descriptions into agents and pipelines.' },
  moderation:      { label: 'Moderation gate',   icon: <Shield className="w-4 h-4" />,   hint: 'Pre-LLM moderation — scans user input before it reaches the agent.' },
  knowledge_engine:{ label: 'Knowledge engine',  icon: <BookOpen className="w-4 h-4" />, hint: 'Model that summarises and indexes documents in Cognify.' },
  sdk_playground:  { label: 'SDK Playground',    icon: <Zap className="w-4 h-4" />,      hint: 'Default model pre-selected when you open the SDK Playground.' },
  triggers:        { label: 'Scheduled triggers',icon: <Clock className="w-4 h-4" />,    hint: 'Default model used by cron-triggered agent runs.' },
  execution:       { label: 'Execution limits',  icon: <Clock className="w-4 h-4" />,    hint: 'Time and iteration budgets for agent and pipeline runs. Raise the pipeline budget if runs with many LLM steps are cut off mid-way.' },
};


function LlmSettingsPage() {
  const [data, setData] = useState<ApiResp | null>(null);
  const [pending, setPending] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sub, setSub] = useState<SubscriptionStatus | null>(null);
  const [tokenDraft, setTokenDraft] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [verifyMsg, setVerifyMsg] = useState<string | null>(null);
  const [verifyOk, setVerifyOk] = useState<boolean | null>(null);

  async function loadSubscription() {
    const r = await apiFetch<SubscriptionStatus>('/api/admin/settings/subscription');
    if (r.data) setSub(r.data);
  }

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const r = await apiFetch<ApiResp>(`/api/admin/settings`);
      if (r.data) {
        setData(r.data);
        setPending({});
        await loadSubscription();
      } else {
        setErr(
          r.error?.toLowerCase().includes('403') || r.error?.toLowerCase().includes('forbidden')
            ? 'Admin role required to view Model Selection.'
            : (r.error || 'Failed to load settings'),
        );
      }
    } catch (e: any) {
      setErr(e?.message || 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const dirty = Object.keys(pending).length > 0;

  async function save() {
    setSaving(true); setMsg(null);
    try {
      for (const [key, value] of Object.entries(pending)) {
        await apiFetch(`/api/admin/settings/${encodeURIComponent(key)}`, {
          method: 'PATCH',
          body: JSON.stringify({ value }),
        });
      }
      setMsg('Saved. New settings take effect within 30 seconds.');
      setPending({});
      await load();
    } catch (e: any) {
      setMsg(e?.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  async function patchSetting(key: string, value: string) {
    const r = await apiFetch(`/api/admin/settings/${encodeURIComponent(key)}`, {
      method: 'PATCH',
      body: JSON.stringify({ value }),
    });
    if (r.error) throw new Error(r.error);
  }

  async function saveToken() {
    setSaving(true);
    setMsg(null);
    setVerifyMsg(null);
    setVerifyOk(null);
    try {
      await patchSetting('llm.subscription.token', tokenDraft.trim());
      setTokenDraft('');
      setMsg(
        tokenDraft.trim()
          ? 'Subscription token saved. Verify it to confirm the plan can serve the selected model.'
          : 'Subscription token cleared.',
      );
      await loadSubscription();
    } catch (e: any) {
      setMsg(e?.message || 'Could not save the token');
    } finally {
      setSaving(false);
    }
  }

  async function toggleSubscription(key: string, next: boolean) {
    setSaving(true);
    setMsg(null);
    try {
      await patchSetting(key, next ? 'true' : 'false');
      await loadSubscription();
      setMsg('Saved. Takes effect across the platform within 30 seconds.');
    } catch (e: any) {
      setMsg(e?.message || 'Could not update subscription mode');
    } finally {
      setSaving(false);
    }
  }

  async function verifySubscription() {
    setVerifying(true);
    setVerifyMsg(null);
    setVerifyOk(null);
    try {
      const r = await apiFetch<{
        ok: boolean;
        model: string;
        reply: string;
        input_tokens: number;
        output_tokens: number;
      }>('/api/admin/settings/subscription/verify', { method: 'POST', body: '{}' });
      if (r.data?.ok) {
        setVerifyOk(true);
        setVerifyMsg(
          `Verified against ${r.data.model} — replied "${r.data.reply}" (${r.data.input_tokens} in / ${r.data.output_tokens} out, $0 marginal).`,
        );
      } else {
        setVerifyOk(false);
        setVerifyMsg(r.error || 'Verification failed');
      }
    } catch (e: any) {
      setVerifyOk(false);
      setVerifyMsg(e?.message || 'Verification failed');
    } finally {
      setVerifying(false);
    }
  }

  async function resetAll() {
    if (!confirm('Reset every LLM setting back to the platform defaults? This cannot be undone without re-applying your changes.')) return;
    setSaving(true); setMsg(null);
    try {
      await apiFetch(`/api/admin/settings/reset`, { method: 'POST', body: '{}' });
      setMsg('All settings reset to defaults.');
      await load();
    } catch (e: any) {
      setMsg(e?.message || 'Reset failed');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="p-6 text-slate-400" data-testid="admin-llm-settings-loading">
        Loading settings…
      </div>
    );
  }

  if (!data || err) {
    return (
      <div className="p-6 max-w-2xl" data-testid="admin-llm-settings-error">
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
          <p className="font-semibold mb-1">Couldn’t load Model Selection</p>
          <p className="text-rose-300/90">{err || 'No settings returned.'}</p>
          <button
            onClick={load}
            className="mt-3 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-100 text-xs"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5" data-testid="admin-llm-settings">
      <PageHeader
        title="Model Selection"
        purpose="Pick which AI model runs each built in feature, for every workspace on the platform. For admins."
        icon={Cpu}
        storageKey="admin-llm-settings"
        docSlug="09-reference/04-platform-settings"
        primaryAction={{
          label: saving ? 'Saving…' : `Save${dirty ? ` (${Object.keys(pending).length})` : ''}`,
          icon: Save,
          onClick: save,
          disabled: !dirty || saving,
          title: !dirty ? 'Change a setting first' : undefined,
          testId: 'save-settings',
        }}
        secondaryAction={{
          label: 'Reset all',
          icon: RotateCcw,
          onClick: resetAll,
          disabled: saving,
          testId: 'reset-settings',
        }}
        steps={[
          'A Claude subscription, if connected, can run every call in place of separate provider keys.',
          'Each card below is one built in feature. Pick the model it should use.',
          'Changes are held until you click Save. They take effect within 30 seconds.',
          'Reset all puts every feature back on its default model.',
        ]}
      />

      {msg && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3 text-sm text-cyan-200">
          {msg}
        </div>
      )}

      {/* Claude subscription — an alternative to per-provider API keys.
          Lives above the per-feature cards because when it's exclusive it
          decides what every one of them actually runs on. */}
      {sub && (
        <div
          data-testid="claude-subscription-section"
          className={`rounded-xl border p-4 space-y-4 ${
            sub.active
              ? 'border-emerald-500/40 bg-emerald-500/[0.05]'
              : 'border-slate-700/60 bg-[#0B0F19]'
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-emerald-400" />
                <h2 className="text-base font-semibold text-white">Claude subscription</h2>
                <span
                  data-testid="subscription-status-badge"
                  className={`text-[9px] uppercase tracking-wider rounded px-1.5 py-0.5 border ${
                    sub.active
                      ? 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10'
                      : 'text-slate-400 border-slate-600/50 bg-slate-700/20'
                  }`}
                >
                  {sub.active ? 'active' : sub.token_set ? 'configured, off' : 'not configured'}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1 max-w-2xl">
                Run the platform on a Claude Pro/Max plan instead of per-call API billing.
                Generate a token with <code className="text-emerald-300">claude setup-token</code>{' '}
                and paste it below. Calls record tokens at $0 marginal cost. If the subscription
                isn’t configured or stops answering, the platform falls back to whichever provider
                API keys are available.
              </p>
            </div>
          </div>

          {/* Token */}
          <div className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-3 space-y-2">
            <p className="text-sm font-medium text-white" title="llm.subscription.token">{settingTitle('llm.subscription.token')}</p>
            <p className="text-[11px] text-slate-500">
              {sub.token_set
                ? `Currently set (${sub.token_masked}) from ${sub.token_source === 'environment' ? 'the environment' : 'platform settings'}. Paste a new value to rotate, or save an empty field to clear it.`
                : 'No token stored. Paste one to enable subscription mode.'}
            </p>
            <div className="flex items-center gap-2">
              <input
                type="password"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
                placeholder="sk-ant-oat01-…"
                autoComplete="off"
                data-testid="subscription-token-input"
                className="flex-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white font-mono focus:outline-none focus:border-emerald-500"
              />
              <button
                onClick={saveToken}
                disabled={saving}
                data-testid="subscription-token-save"
                className="px-3 py-2 rounded-lg bg-emerald-500 text-white text-xs font-semibold hover:bg-emerald-400 disabled:opacity-40"
              >
                {saving ? 'Saving…' : 'Save token'}
              </button>
              <button
                onClick={verifySubscription}
                disabled={verifying || !sub.token_set}
                data-testid="subscription-verify"
                className="px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-800/40 text-slate-200 text-xs hover:bg-slate-800/70 disabled:opacity-40"
              >
                {verifying ? 'Verifying…' : 'Verify'}
              </button>
            </div>
            {verifyMsg && (
              <p
                data-testid="subscription-verify-result"
                className={`text-[11px] ${verifyOk ? 'text-emerald-300' : 'text-rose-300'}`}
              >
                {verifyMsg}
              </p>
            )}
          </div>

          {/* Model the subscription serves */}
          <div className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-3 space-y-2">
            <p className="text-sm font-medium text-white" title="llm.subscription.default_model">
              {settingTitle('llm.subscription.default_model')}
            </p>
            <p className="text-[11px] text-slate-500">
              The model the subscription serves, and the target for non-Claude requests while
              exclusive mode is on.
            </p>
            <div data-testid="select-llm.subscription.default_model">
              <ModelPicker
                value={pending['llm.subscription.default_model'] ?? sub.default_model}
                onChange={(v) => {
                  setPending((p) => {
                    const next = { ...p };
                    if (v === sub.default_model) delete next['llm.subscription.default_model'];
                    else next['llm.subscription.default_model'] = v;
                    return next;
                  });
                }}
              />
            </div>
          </div>

          {/* Switches */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="flex items-start gap-2 rounded-lg border border-slate-700/40 bg-slate-900/40 p-3 cursor-pointer">
              <input
                type="checkbox"
                checked={sub.enabled}
                onChange={(e) => toggleSubscription('llm.subscription.enabled', e.target.checked)}
                disabled={saving || (!sub.token_set && !sub.enabled)}
                data-testid="subscription-enabled-toggle"
                className="mt-0.5 accent-emerald-500"
              />
              <span>
                <span className="block text-xs font-medium text-white">
                  Use the Claude subscription
                </span>
                <span className="block text-[11px] text-slate-500">
                  {sub.token_set
                    ? 'Route LLM traffic through the plan before reaching for API keys.'
                    : 'Save a token first.'}
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 rounded-lg border border-slate-700/40 bg-slate-900/40 p-3 cursor-pointer">
              <input
                type="checkbox"
                checked={sub.exclusive}
                onChange={(e) => toggleSubscription('llm.subscription.exclusive', e.target.checked)}
                disabled={saving}
                data-testid="subscription-exclusive-toggle"
                className="mt-0.5 accent-emerald-500"
              />
              <span>
                <span className="block text-xs font-medium text-white">
                  Use it for every feature
                </span>
                <span className="block text-[11px] text-slate-500">
                  Remap GPT and Gemini requests onto {sub.default_model}. Turn off to use the
                  subscription for Claude models only.
                </span>
              </span>
            </label>
          </div>

          {sub.active && (
            <p className="text-[11px] text-emerald-300" data-testid="subscription-active-note">
              Every agent, pipeline, builder and moderation call is running on{' '}
              <code className="text-emerald-200">{sub.default_model}</code> via the subscription.{' '}
              {sub.billing}
            </p>
          )}
        </div>
      )}

      {/* Builder + Pipeline validation — highlighted at the top because it
          drives both AI Builder previews and the Tier-3 pipeline critic. */}
      {(() => {
        const aiBuilder = data.categories.ai_builder || [];
        const validation = aiBuilder.find((s) => s.key === 'ai_builder.validation.model');
        if (!validation) return null;
        const currentValue = pending[validation.key] ?? validation.value;
        return (
          <div
            data-testid="builder-validation-section"
            className="rounded-xl border border-cyan-500/30 bg-cyan-500/[0.04] p-4 space-y-3"
          >
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              <h2 className="text-base font-semibold text-white">
                Builder + Pipeline validation model
              </h2>
            </div>
            <p className="text-xs text-slate-400">
              Used by the AI Builder for preview / draft generation and by AI Validate
              (Tier-3 LLM critic) on agents and pipelines. Default is
              <code className="text-cyan-300 mx-1">azure-gpt-4o</code>.
            </p>
            <div data-testid="builder-validation-model-select">
              <ModelPicker
                value={currentValue}
                onChange={(v) => {
                  setPending((p) => {
                    const next = { ...p };
                    if (v === validation.value) delete next[validation.key];
                    else next[validation.key] = v;
                    return next;
                  });
                }}
              />
            </div>
            <p className="text-[10px] text-slate-500" data-testid="builder-validation-current">
              Current: <code className="text-slate-300">{currentValue}</code> · Default:{' '}
              <code className="text-slate-400">{validation.default}</code>
            </p>
          </div>
        );
      })()}

      {/* Category cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {Object.entries(data.categories)
          .filter(([cat]) => cat !== SUBSCRIPTION_CATEGORY)
          .map(([cat, items]) => {
          const meta = CATEGORY_META[cat] || { label: cat, icon: <Cpu className="w-4 h-4" />, hint: '' };
          return (
            <motion.div
              key={cat}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-xl border border-slate-700/60 bg-[#0B0F19] p-4"
              data-testid={`category-${cat}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-cyan-400">{meta.icon}</span>
                <h2 className="text-base font-semibold text-white">{meta.label}</h2>
              </div>
              {meta.hint && <p className="text-xs text-slate-500 mb-3">{meta.hint}</p>}

              <div className="space-y-3">
                {items.map((s) => {
                  const currentValue = pending[s.key] ?? s.value;
                  return (
                    <div key={s.key} className="rounded-lg border border-slate-700/40 bg-slate-900/40 p-3">
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <div>
                          <p className="text-sm font-medium text-white" title={s.key}>{settingTitle(s.key)}</p>
                          <p className="text-[11px] text-slate-500">{s.description}</p>
                        </div>
                        {!s.is_default && !pending[s.key] && (
                          <span className="text-[9px] uppercase tracking-wider text-emerald-400 border border-emerald-500/30 bg-emerald-500/10 rounded px-1.5 py-0.5">
                            customised
                          </span>
                        )}
                        {pending[s.key] && (
                          <span className="text-[9px] uppercase tracking-wider text-amber-400 border border-amber-500/30 bg-amber-500/10 rounded px-1.5 py-0.5">
                            unsaved
                          </span>
                        )}
                      </div>
                      {s.kind === 'int' ? (
                        <div data-testid={`number-${s.key}`}>
                          <input
                            type="number"
                            value={currentValue}
                            min={s.min ?? undefined}
                            max={s.max ?? undefined}
                            onChange={(e) => {
                              const v = e.target.value;
                              setPending((p) => {
                                const next = { ...p };
                                if (v === s.value) delete next[s.key]; else next[s.key] = v;
                                return next;
                              });
                            }}
                            className="w-40 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-cyan-500"
                          />
                          {(s.min != null || s.max != null) && (
                            <span className="ml-2 text-[11px] text-slate-500">
                              allowed {s.min ?? '—'} to {s.max ?? '—'}
                            </span>
                          )}
                        </div>
                      ) : (
                      <div data-testid={`select-${s.key}`}>
                        <ModelPicker
                          value={currentValue}
                          onChange={(v) => {
                            setPending((p) => {
                              const next = { ...p };
                              if (v === s.value) delete next[s.key]; else next[s.key] = v;
                              return next;
                            });
                          }}
                        />
                      </div>
                      )}
                      <p className="text-[10px] text-slate-500 mt-1">
                        Platform default: <code className="text-slate-400">{s.default}</code>
                      </p>
                    </div>
                  );
                })}
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* Footer note */}
      <div className="rounded-lg border border-slate-700/40 bg-slate-900/30 p-4 text-xs text-slate-400">
        Settings are cached for 30 seconds on each API pod, so changes propagate within half a
        minute. Custom-selected models need a valid API key configured in{' '}
        <code className="text-slate-300">abenix-secrets</code> for the corresponding provider.
      </div>
    </div>
  );
}

export default function LlmSettingsPageGated() {
  return (
    <AccessGate
      title="Model Selection"
      purpose="Pick which AI model runs each built in feature, for every workspace on the platform. For admins."
      icon={Cpu}
      need={{ feature: 'manage_settings' }}
      instead={{ text: 'You can still pick the model for each of your own agents in the Agent Builder.', href: '/builder', label: 'Open the Agent Builder' }}
    >
      <LlmSettingsPage />
    </AccessGate>
  );
}
