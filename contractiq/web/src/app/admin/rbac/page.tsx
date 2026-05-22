'use client';

import { useEffect, useState } from 'react';
import { Users, ShieldCheck, Plus } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

type Role = { id: string; name: string; description: string; permissions: Record<string, string[]>; is_system: boolean };

export default function RBACAdminPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [me, setMe] = useState<any>(null);
  const [assignTarget, setAssignTarget] = useState('');
  const [assignRole, setAssignRole] = useState('');

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const [r, m] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/rbac/roles`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/rbac/me`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setRoles((await r.json()).data || []);
    setMe((await m.json()).data || null);
  };
  useEffect(() => { load(); }, []);

  const assign = async () => {
    if (!assignTarget || !assignRole) return;
    const token = getToken();
    await fetch(`${API_URL}/api/contractiq/rbac/assign`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: assignTarget, role: assignRole }),
    });
    setAssignTarget(''); setAssignRole('');
    await load();
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <div className="flex items-center gap-3 mb-6">
          <ShieldCheck className="w-7 h-7 text-emerald-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Access Control</h1>
            <p className="text-sm text-slate-400">Six personas. Permissions matrix. Four-eyes approval is enforced server-side for rule changes.</p>
          </div>
        </div>

        {me && (
          <div className="mb-6 p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-2 flex items-center gap-1.5"><Users className="w-3.5 h-3.5" /> Your access</div>
            <div className="text-sm">{me.email} — roles: <span className="font-semibold text-emerald-300">{(me.roles || []).join(', ') || me.legacy_role || 'none'}</span></div>
            <details className="mt-2 text-xs">
              <summary className="text-slate-400 cursor-pointer">Show permissions matrix ({Object.keys(me.permissions || {}).length} capabilities)</summary>
              <pre className="mt-2 p-2 bg-slate-800/40 rounded font-mono text-[10px] overflow-x-auto">{JSON.stringify(me.permissions, null, 2)}</pre>
            </details>
          </div>
        )}

        <div className="space-y-3 mb-8">
          <div className="text-xs uppercase tracking-wide text-slate-500">System roles ({roles.length})</div>
          {roles.map(r => (
            <div key={r.id} className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="text-sm font-bold text-emerald-300">{r.name}</div>
                  <div className="text-xs text-slate-400 mt-0.5">{r.description}</div>
                </div>
                {r.is_system && <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800/60 text-slate-400 uppercase">system</span>}
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5 mt-3">
                {Object.entries(r.permissions || {}).map(([cap, acts]) => (
                  <div key={cap} className="px-2 py-1 rounded bg-slate-800/40 border border-slate-800 text-[10px]">
                    <span className="text-slate-300 font-mono">{cap}</span>
                    <span className="text-slate-500"> · {(acts as string[]).join(', ')}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="p-4 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
          <div className="text-xs uppercase tracking-wide text-emerald-300 mb-2 flex items-center gap-1.5"><Plus className="w-3.5 h-3.5" /> Assign role</div>
          <div className="flex items-center gap-2">
            <input
              placeholder="User UUID"
              value={assignTarget}
              onChange={e => setAssignTarget(e.target.value)}
              className="flex-1 px-3 py-2 text-xs rounded bg-slate-800/60 border border-slate-700 text-slate-200 font-mono"
            />
            <select
              value={assignRole}
              onChange={e => setAssignRole(e.target.value)}
              className="px-3 py-2 text-xs rounded bg-slate-800/60 border border-slate-700 text-slate-200"
            >
              <option value="">Pick role</option>
              {roles.map(r => <option key={r.id} value={r.name}>{r.name}</option>)}
            </select>
            <button
              onClick={assign}
              disabled={!assignTarget || !assignRole}
              className="px-4 py-2 text-xs rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
            >
              Assign
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
