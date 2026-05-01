'use client';

import { useState, useEffect, useCallback } from 'react';
import { Coins, Edit2, Save, X, Loader2, AlertTriangle } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

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
  const [users, setUsers] = useState<UserQuota[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTokens, setEditTokens] = useState<string>('');
  const [editCost, setEditCost] = useState<string>('');
  const [saving, setSaving] = useState(false);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    const res = await apiFetch<UserQuota[]>('/api/analytics/per-user');
    if (res.data && Array.isArray(res.data)) setUsers(res.data);
    setLoading(false);
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const startEdit = (user: UserQuota) => {
    setEditingId(user.id);
    setEditTokens(user.token_allowance !== null ? String(user.token_allowance) : '');
    setEditCost(user.cost_limit !== null ? String(user.cost_limit) : '');
  };

  const saveQuota = async (userId: string) => {
    setSaving(true);
    await apiFetch(`/api/team/members/${userId}/quota`, {
      method: 'PUT',
      body: JSON.stringify({
        token_monthly_allowance: editTokens ? parseInt(editTokens) : null,
        cost_monthly_limit: editCost ? parseFloat(editCost) : null,
      }),
    });
    setEditingId(null);
    setSaving(false);
    await fetchUsers();
  };

  const formatTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
    return String(n);
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <Coins className="w-5 h-5 text-cyan-400" />
          Token Quotas & Usage
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Allocate monthly token budgets and cost limits per team member. Null = unlimited.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase">Team Members</p>
          <p className="text-2xl font-bold text-white mt-1">{users.length}</p>
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase">Total Tokens Used (Month)</p>
          <p className="text-2xl font-bold text-cyan-400 mt-1">
            {formatTokens(users.reduce((sum, u) => sum + (u.tokens_used || 0), 0))}
          </p>
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase">Total Cost (Month)</p>
          <p className="text-2xl font-bold text-emerald-400 mt-1">
            ${users.reduce((sum, u) => sum + (u.cost_used || 0), 0).toFixed(2)}
          </p>
        </div>
      </div>

      {/* User table */}
      <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left py-3 px-4 text-slate-400 font-medium">User</th>
              <th className="text-right py-3 px-4 text-slate-400 font-medium">Token Quota</th>
              <th className="text-right py-3 px-4 text-slate-400 font-medium">Tokens Used</th>
              <th className="text-center py-3 px-4 text-slate-400 font-medium">Usage</th>
              <th className="text-right py-3 px-4 text-slate-400 font-medium">Cost Limit</th>
              <th className="text-right py-3 px-4 text-slate-400 font-medium">Cost Used</th>
              <th className="text-center py-3 px-4 text-slate-400 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-slate-500">
                  <Loader2 className="w-5 h-5 animate-spin inline mr-2" />
                  Loading users...
                </td>
              </tr>
            ) : users.map((u) => (
              <tr key={u.id} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                <td className="py-3 px-4">
                  <div>
                    <span className="text-white text-sm">{u.full_name || u.email}</span>
                    <p className="text-[10px] text-slate-500">{u.email}</p>
                  </div>
                </td>
                <td className="py-3 px-4 text-right">
                  {editingId === u.id ? (
                    <input
                      type="number"
                      value={editTokens}
                      onChange={(e) => setEditTokens(e.target.value)}
                      placeholder="Unlimited"
                      className="w-28 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-white text-right"
                    />
                  ) : (
                    <span className="text-slate-300 font-mono text-xs">
                      {u.token_allowance !== null ? formatTokens(u.token_allowance) : <span className="text-slate-600">Unlimited</span>}
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
                  {editingId === u.id ? (
                    <input
                      type="number"
                      step="0.01"
                      value={editCost}
                      onChange={(e) => setEditCost(e.target.value)}
                      placeholder="Unlimited"
                      className="w-24 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-white text-right"
                    />
                  ) : (
                    <span className="text-slate-300 font-mono text-xs">
                      {u.cost_limit !== null ? `$${u.cost_limit.toFixed(2)}` : <span className="text-slate-600">Unlimited</span>}
                    </span>
                  )}
                </td>
                <td className="py-3 px-4 text-right font-mono text-xs text-emerald-400">
                  ${u.cost_used.toFixed(2)}
                </td>
                <td className="py-3 px-4 text-center">
                  {editingId === u.id ? (
                    <div className="flex items-center justify-center gap-1">
                      <button
                        onClick={() => saveQuota(u.id)}
                        disabled={saving}
                        className="p-1 rounded bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30"
                      >
                        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                      </button>
                      <button onClick={() => setEditingId(null)} className="p-1 rounded bg-slate-700 text-slate-400 hover:text-white">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ) : (
                    <button onClick={() => startEdit(u)} className="p-1 rounded bg-slate-700/50 text-slate-400 hover:text-cyan-400 hover:bg-cyan-500/10">
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-slate-900/40 border border-slate-700/30 rounded-lg p-3">
        <p className="text-[10px] text-slate-500">
          <AlertTriangle className="w-3 h-3 inline mr-1 text-amber-400" />
          Quotas reset automatically on the 1st of each month. Set to empty/blank for unlimited access. Users who exceed their quota will receive a 429 error on their next execution attempt.
        </p>
      </div>
    </div>
  );
}
