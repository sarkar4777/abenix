'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Cpu, Save, RotateCcw, Sparkles, Shield, BookOpen, Zap, Clock } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

type Setting = {
  key: string;
  value: string;
  default: string;
  category: string;
  description: string;
  is_default: boolean;
  updated_at?: string | null;
};

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
};


export default function LlmSettingsPage() {
  const [data, setData] = useState<ApiResp | null>(null);
  const [pending, setPending] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const r = await apiFetch<ApiResp>(`/api/admin/settings`);
      if (r.data) {
        setData(r.data);
        setPending({});
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
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Admin · platform</p>
          <h1 className="text-2xl font-semibold text-white flex items-center gap-2">
            <Cpu className="w-6 h-6 text-cyan-400" />
            Model Selection
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Pick which LLM powers each built-in Abenix feature. Applies across all tenants.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={resetAll}
            disabled={saving}
            data-testid="reset-settings"
            className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700/60 bg-slate-800/30 text-slate-300 text-sm hover:bg-slate-800/60 disabled:opacity-50"
          >
            <RotateCcw className="w-4 h-4" />
            Reset all
          </button>
          <button
            onClick={save}
            disabled={!dirty || saving}
            data-testid="save-settings"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-500 text-white text-sm font-semibold hover:bg-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Save className="w-4 h-4" />
            {saving ? 'Saving…' : `Save ${dirty ? `(${Object.keys(pending).length})` : ''}`}
          </button>
        </div>
      </div>

      {msg && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3 text-sm text-cyan-200">
          {msg}
        </div>
      )}

      {/* Category cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {Object.entries(data.categories).map(([cat, items]) => {
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
                          <p className="text-sm font-medium text-white font-mono">{s.key}</p>
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
                      <select
                        value={currentValue}
                        onChange={(e) => {
                          const v = e.target.value;
                          setPending((p) => {
                            const next = { ...p };
                            if (v === s.value) delete next[s.key]; else next[s.key] = v;
                            return next;
                          });
                        }}
                        data-testid={`select-${s.key}`}
                        className="w-full bg-slate-950/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white"
                      >
                        {['anthropic', 'google', 'openai'].map((prov) => {
                          const provModels = data.models.filter((m) => m.provider === prov);
                          if (provModels.length === 0) return null;
                          return (
                            <optgroup key={prov} label={prov.toUpperCase()}>
                              {provModels.map((m) => (
                                <option key={m.id} value={m.id}>{m.label}  ({m.id})</option>
                              ))}
                            </optgroup>
                          );
                        })}
                      </select>
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
