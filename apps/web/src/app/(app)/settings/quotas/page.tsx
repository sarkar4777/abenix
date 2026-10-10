'use client';

import { useState, useEffect, useCallback } from 'react';
import { BarChart3, Coins, Edit2, Save, X, Loader2, AlertTriangle, RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useAuth } from '@/contexts/AuthContext';
import { quotaProblem } from '@/lib/settings-validation';
import { toastSuccess } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';

interface UserQuota {
  id: string;
  email: string;
  full_name: string;
  role: string;
  token_allowance: number | null;
  tokens_used: number;
  cost_limit: number | null;
  cost_used: number;
  usage_pct: number | null;
}

export default function QuotasPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [users, setUsers] = useState<UserQuota[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTokens, setEditTokens] = useState<string>('');
  const [editCost, setEditCost] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    // admins get everyone, a member gets just their own row
    const res = await apiFetch<UserQuota[] | UserQuota>('/api/analytics/per-user', { throwOnError: false });
    if (Array.isArray(res.data)) setUsers(res.data);
    else if (res.data) setUsers([res.data]);
    else setLoadError(res.error || 'Usage could not be loaded.');
    setLoading(false);
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const startEdit = (u: UserQuota) => {
    setEditingId(u.id);
    setSaveError('');
    setEditTokens(u.token_allowance !== null ? String(u.token_allowance) : '');
    setEditCost(u.cost_limit !== null ? String(u.cost_limit) : '');
  };

  const tokenProblem = quotaProblem(editTokens, true);
  const costProblem = quotaProblem(editCost, false);

  const saveQuota = async (u: UserQuota) => {
    if (tokenProblem || costProblem) return;
    setSaving(true);
    setSaveError('');
    const res = await apiFetch(`/api/team/members/${u.id}/quota`, {
      method: 'PUT',
      body: JSON.stringify({
        token_monthly_allowance: editTokens.trim() ? Number(editTokens) : null,
        cost_monthly_limit: editCost.trim() ? Number(editCost) : null,
      }),
      throwOnError: false,
    });
    setSaving(false);
    if (res.error) {
      setSaveError(res.error);
      return;
    }
    setEditingId(null);
    toastSuccess('Limits saved', `${u.full_name || u.email}'s new limits apply to the next run`);
    await fetchUsers();
  };

  const formatTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
    return String(n);
  };

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="Token Quotas & Usage"
        icon={Coins}
        purpose={isAdmin
          ? 'Monthly token and cost limits for each team member, and how much each has used. For workspace admins.'
          : 'Your monthly token and cost limits and how much you have used. An admin sets the limits.'}
        primaryAction={{ label: 'Refresh', icon: RefreshCw, onClick: fetchUsers, busy: loading }}
        secondaryAction={{ label: 'Open Analytics', icon: BarChart3, href: '/analytics' }}
        steps={isAdmin ? [
          'Press Edit on a person to set their monthly token and cost limits.',
          'Leave a limit blank for no limit. Zero stops their runs.',
          'Someone over their limit cannot start new runs until the next reset.',
          'Limits reset on the 1st of each month.',
        ] : [
          'Your row shows your limits and what you used this month.',
          'Over a limit you cannot start new runs until the next reset.',
          'Limits reset on the 1st of each month. Ask an admin to change them.',
        ]}
        storageKey="settings-quotas"
      />

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase">{isAdmin ? 'Team members' : 'People shown'}</p>
          <p className="text-2xl font-bold text-white mt-1">{users.length}</p>
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase">Tokens used this month</p>
          <p className="text-2xl font-bold text-cyan-400 mt-1">
            {formatTokens(users.reduce((sum, u) => sum + (u.tokens_used || 0), 0))}
          </p>
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase">Cost this month</p>
          <p className="text-2xl font-bold text-emerald-400 mt-1">
            ${users.reduce((sum, u) => sum + (u.cost_used || 0), 0).toFixed(2)}
          </p>
        </div>
      </div>

      {loadError && (
        <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">
          {loadError}{' '}
          <button type="button" onClick={fetchUsers} className="text-cyan-300 hover:underline">Try again</button>
        </div>
      )}

      {saveError && (
        <p role="alert" data-testid="quota-error" className="text-xs text-rose-300 flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5" /> {saveError}
        </p>
      )}

      {/* User table */}
      <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm" data-testid="quota-table">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left py-3 px-4 text-slate-400 font-medium">User</th>
              <th className="text-right py-3 px-4 text-slate-400 font-medium">Token limit</th>
              <th className="text-right py-3 px-4 text-slate-400 font-medium">Tokens used</th>
              <th className="text-center py-3 px-4 text-slate-400 font-medium">Usage</th>
              <th className="text-right py-3 px-4 text-slate-400 font-medium">Cost limit</th>
              <th className="text-right py-3 px-4 text-slate-400 font-medium">Cost used</th>
              {isAdmin && <th className="text-center py-3 px-4 text-slate-400 font-medium">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {loading && users.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-slate-500">
                  <Loader2 className="w-5 h-5 animate-spin inline mr-2" />
                  Loading people...
                </td>
              </tr>
            ) : users.length === 0 && !loadError ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-slate-500">No one to show yet.</td>
              </tr>
            ) : users.map((u) => {
              const editing = editingId === u.id;
              const name = u.full_name || u.email;
              return (
                <tr key={u.id} data-testid="quota-row" data-email={u.email} className="border-b border-slate-700/30 hover:bg-slate-700/20 align-top">
                  <td className="py-3 px-4">
                    <span className="text-white text-sm">{name}</span>
                    <p className="text-[10px] text-slate-500">{u.email}</p>
                  </td>
                  <td className="py-3 px-4 text-right">
                    {editing ? (
                      <>
                        <input
                          inputMode="numeric"
                          value={editTokens}
                          onChange={(e) => { setEditTokens(e.target.value); setSaveError(''); }}
                          placeholder="No limit"
                          aria-label={`Monthly token limit for ${name}`}
                          aria-invalid={!!tokenProblem}
                          data-testid="quota-tokens"
                          className={`w-28 bg-slate-900 border rounded px-2 py-1 text-xs text-white text-right ${tokenProblem ? 'border-rose-500/70' : 'border-slate-600'}`}
                        />
                        {tokenProblem && <p className="text-[10px] text-rose-300 mt-0.5">{tokenProblem}</p>}
                      </>
                    ) : (
                      <span className="text-slate-300 font-mono text-xs">
                        {u.token_allowance !== null ? formatTokens(u.token_allowance) : <span className="text-slate-500">No limit</span>}
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right font-mono text-xs text-cyan-400">
                    {formatTokens(u.tokens_used)}
                  </td>
                  <td className="py-3 px-4">
                    {u.token_allowance !== null ? (
                      <div className="w-20 mx-auto">
                        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              (u.usage_pct || 0) > 90 ? 'bg-red-500' :
                              (u.usage_pct || 0) > 70 ? 'bg-amber-500' : 'bg-cyan-500'
                            }`}
                            style={{ width: `${Math.min(u.usage_pct || 0, 100)}%` }}
                          />
                        </div>
                        <p className="text-[9px] text-slate-500 text-center mt-0.5">{u.usage_pct?.toFixed(0)}%</p>
                      </div>
                    ) : (
                      <p className="text-[9px] text-slate-600 text-center">&mdash;</p>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right">
                    {editing ? (
                      <>
                        <input
                          inputMode="decimal"
                          value={editCost}
                          onChange={(e) => { setEditCost(e.target.value); setSaveError(''); }}
                          placeholder="No limit"
                          aria-label={`Monthly cost limit in dollars for ${name}`}
                          aria-invalid={!!costProblem}
                          data-testid="quota-cost"
                          className={`w-24 bg-slate-900 border rounded px-2 py-1 text-xs text-white text-right ${costProblem ? 'border-rose-500/70' : 'border-slate-600'}`}
                        />
                        {costProblem && <p className="text-[10px] text-rose-300 mt-0.5">{costProblem}</p>}
                      </>
                    ) : (
                      <span className="text-slate-300 font-mono text-xs">
                        {u.cost_limit !== null ? `$${u.cost_limit.toFixed(2)}` : <span className="text-slate-500">No limit</span>}
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right font-mono text-xs text-emerald-400">
                    ${u.cost_used.toFixed(2)}
                  </td>
                  {isAdmin && (
                    <td className="py-3 px-4 text-center">
                      {editing ? (
                        <div className="flex items-center justify-center gap-1">
                          <button
                            onClick={() => saveQuota(u)}
                            disabled={saving || !!tokenProblem || !!costProblem}
                            aria-label={`Save limits for ${name}`}
                            data-testid="quota-save"
                            className="p-1 rounded bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 disabled:opacity-50"
                          >
                            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                          </button>
                          <button onClick={() => { setEditingId(null); setSaveError(''); }} aria-label="Cancel" className="p-1 rounded bg-slate-700 text-slate-400 hover:text-white">
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => startEdit(u)}
                          aria-label={`Edit limits for ${name}`}
                          data-testid="quota-edit"
                          className="p-1 rounded bg-slate-700/50 text-slate-400 hover:text-cyan-400 hover:bg-cyan-500/10"
                        >
                          <Edit2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="bg-slate-900/40 border border-slate-700/30 rounded-lg p-3">
        <p className="text-[11px] text-slate-400">
          <AlertTriangle className="w-3 h-3 inline mr-1 text-amber-400" />
          Limits reset on the 1st of each month. Leave a field blank for no limit. Someone who goes over their limit cannot start new runs until the next reset.
        </p>
      </div>
    </div>
  );
}
