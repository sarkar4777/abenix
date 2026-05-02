'use client';

/**
 * /admin — tenant settings editor + pending approvals queue.
 * Backs the Phase-2 admin surface described in docs/RESOLVEAI_DESIGN.md.
 */
import { useState } from 'react';
import { Check, X, Loader2, Settings as SettingsIcon, Shield, Save } from 'lucide-react';
import { useResolveAIFetch, resolveAIPost } from '@/lib/api';
import { toastError, toastSuccess } from '@/stores/toastStore';

type Settings = {
  approval_tiers?: {
    auto_ceiling_usd?: number;
    t1_ceiling_usd?: number;
    manager_ceiling_usd?: number;
  };
  sla_first_response_minutes?: number;
  sla_resolution_minutes?: number;
  slack_escalation_url?: string | null;
  moderation_policy_id?: string | null;
  integrations?: Record<string, string>;
};

type Pending = {
  case_id?: string;
  customer_id?: string;
  action_id?: string;
  action_type?: string;
  amount_usd?: number | null;
  approval_tier?: string;
  rationale?: string;
  subject?: string;
};

const DEFAULT_SETTINGS: Settings = {
  approval_tiers: { auto_ceiling_usd: 25, t1_ceiling_usd: 250, manager_ceiling_usd: 5000 },
  sla_first_response_minutes: 15,
  sla_resolution_minutes: 1440,
  slack_escalation_url: '',
  moderation_policy_id: null,
  integrations: {},
};

export default function Admin() {
  const settingsReq = useResolveAIFetch<Settings>('/api/resolveai/admin/settings');
  const pendingReq = useResolveAIFetch<Pending[]>('/api/resolveai/admin/pending-approvals');

  const [local, setLocal] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // One-time seed of the editable form from the fetched settings.
  const effective = local ?? settingsReq.data ?? (settingsReq.error ? DEFAULT_SETTINGS : null);
  const tiers = effective?.approval_tiers ?? DEFAULT_SETTINGS.approval_tiers!;

  const pending = Array.isArray(pendingReq.data) ? pendingReq.data : [];

  function update(patch: Partial<Settings>) {
    const base = effective ?? DEFAULT_SETTINGS;
    setLocal({ ...base, ...patch });
  }
  function updateTiers(patch: Partial<NonNullable<Settings['approval_tiers']>>) {
    const base = effective ?? DEFAULT_SETTINGS;
    setLocal({ ...base, approval_tiers: { ...(base.approval_tiers ?? {}), ...patch } });
  }

  async function save() {
    if (!effective) return;
    setSaving(true);
    setMsg(null);
    const { error } = await resolveAIPost('/api/resolveai/admin/settings', effective);
    setSaving(false);
    if (error) {
      const detail = `Couldn't save: ${error}`;
      setMsg(detail);
      toastError(detail);
    } else {
      const okMsg = 'Settings saved — approval ceilings apply to the next pipeline run.';
      setMsg(okMsg);
      toastSuccess('Settings saved');
      void settingsReq.refetch();
    }
  }

  async function decide(caseId: string | undefined, actionId: string | undefined, approve: boolean) {
    if (!caseId || !actionId) return;
    setActing(actionId);
    setMsg(null);
    const path = approve ? 'approve' : 'reject';
    const { error } = await resolveAIPost(
      `/api/resolveai/cases/${caseId}/${path}`,
      { action_id: actionId },
    );
    setActing(null);
    if (error) {
      const detail = `Action failed: ${error}`;
      setMsg(detail);
      toastError(detail);
    } else {
      const okMsg = `${approve ? 'Approved' : 'Rejected'} action ${actionId.slice(0, 8)}.`;
      setMsg(okMsg);
      toastSuccess(okMsg);
      void pendingReq.refetch();
    }
  }

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI · admin</p>
        <h1 className="text-2xl font-bold text-white">Admin</h1>
        <p className="text-sm text-slate-400 mt-1">Tenant settings, approval queue, and escalation wiring.</p>
      </div>

      {msg && <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3 text-sm text-cyan-200">{msg}</div>}
      {settingsReq.error && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          Couldn&apos;t load current settings ({settingsReq.error}). Showing platform defaults — saving will create them.
        </div>
      )}

      {/* Settings */}
      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4" data-testid="admin-settings">
        <h2 className="text-sm font-semibold text-white flex items-center gap-2">
          <SettingsIcon className="w-4 h-4 text-cyan-400" /> Approval tiers & SLAs
        </h2>
        {!effective && settingsReq.isLoading ? (
          <p className="text-xs text-slate-500">Loading…</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-3">
              <NumInput label="Auto-approve ceiling ($)"
                value={Number(tiers.auto_ceiling_usd ?? 0)}
                onChange={(v) => updateTiers({ auto_ceiling_usd: v })} />
              <NumInput label="T1 lead ceiling ($)"
                value={Number(tiers.t1_ceiling_usd ?? 0)}
                onChange={(v) => updateTiers({ t1_ceiling_usd: v })} />
              <NumInput label="Manager ceiling ($)"
                value={Number(tiers.manager_ceiling_usd ?? 0)}
                onChange={(v) => updateTiers({ manager_ceiling_usd: v })} />
              <NumInput label="SLA first-response (min)"
                value={Number(effective?.sla_first_response_minutes ?? 0)}
                onChange={(v) => update({ sla_first_response_minutes: v })} />
              <NumInput label="SLA resolution (min)"
                value={Number(effective?.sla_resolution_minutes ?? 0)}
                onChange={(v) => update({ sla_resolution_minutes: v })} />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">Slack escalation webhook</label>
              <input
                value={effective?.slack_escalation_url || ''}
                onChange={(e) => update({ slack_escalation_url: e.target.value })}
                placeholder="https://hooks.slack.com/services/…"
                className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white font-mono placeholder-slate-600"
              />
            </div>
            <button
              onClick={save}
              disabled={saving}
              data-testid="save-settings"
              className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-sm font-semibold rounded-lg disabled:opacity-60"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Save
            </button>
          </>
        )}
      </section>

      {/* Pending approvals */}
      <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5" data-testid="pending-approvals">
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Shield className="w-4 h-4 text-amber-400" /> Pending approvals ({pending.length})
        </h2>
        {pendingReq.error ? (
          <p className="text-xs text-rose-300">Couldn&apos;t load the queue: {pendingReq.error}</p>
        ) : pending.length === 0 ? (
          <p className="text-xs text-slate-500">Nothing awaiting sign-off.</p>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="text-left py-2">Case</th>
                <th className="text-left py-2">Action</th>
                <th className="text-right py-2">Amount</th>
                <th className="text-left py-2">Tier</th>
                <th className="text-left py-2">Rationale</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pending.map((p, idx) => (
                <tr key={p.action_id || `p-${idx}`} className="border-t border-slate-800/70">
                  <td className="py-2 font-mono text-slate-500">{(p.case_id || '').slice(0, 8)}</td>
                  <td className="py-2 text-slate-200">{p.action_type || '—'}</td>
                  <td className="py-2 text-right tabular-nums text-slate-200">
                    {p.amount_usd != null ? `$${p.amount_usd}` : '—'}
                  </td>
                  <td className="py-2">
                    <span className="px-2 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-300 text-[10px]">
                      {p.approval_tier || 'none'}
                    </span>
                  </td>
                  <td className="py-2 text-slate-400 max-w-[300px] truncate">{p.rationale || ''}</td>
                  <td className="py-2 flex gap-1 justify-end">
                    <button
                      onClick={() => void decide(p.case_id, p.action_id, true)}
                      disabled={acting === p.action_id}
                      className="p-1.5 rounded bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-50"
                    >
                      {acting === p.action_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                    </button>
                    <button
                      onClick={() => void decide(p.case_id, p.action_id, false)}
                      disabled={acting === p.action_id}
                      className="p-1.5 rounded bg-rose-500/20 text-rose-300 hover:bg-rose-500/30 disabled:opacity-50"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function NumInput({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">{label}</label>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => {
          const n = Number(e.target.value);
          onChange(Number.isFinite(n) ? n : 0);
        }}
        className="w-full bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white font-mono"
      />
    </div>
  );
}
