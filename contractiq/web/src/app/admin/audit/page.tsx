'use client';

import { useEffect, useState } from 'react';
import { FileCheck2 } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

type Event = {
  id: string; user_id: string | null; kind: string; resource_type: string | null;
  resource_id: string | null; action: string; before: any; after: any;
  calc_signature?: string | null; created_at: string;
};

export default function AuditPage() {
  const [events, setEvents] = useState<Event[]>([]);
  const [kind, setKind] = useState('');
  useEffect(() => {
    const load = async () => {
      const token = getToken();
      const q = kind ? `?kind=${encodeURIComponent(kind)}` : '';
      const r = await fetch(`${API_URL}/api/contractiq/audit/events${q}`, { headers: { Authorization: `Bearer ${token}` } });
      setEvents((await r.json()).data || []);
    };
    load();
  }, [kind]);
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <div className="flex items-center gap-3 mb-6">
          <FileCheck2 className="w-7 h-7 text-violet-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Audit Log</h1>
            <p className="text-sm text-slate-400">Immutable event ledger. Every rule change, role grant, dispute decision is recorded with before/after state.</p>
          </div>
        </div>
        <div className="mb-4 flex items-center gap-2">
          <span className="text-xs text-slate-500">filter by kind:</span>
          {['', 'rule', 'rbac', 'whatif', 'risk', 'dispute'].map(k => (
            <button key={k || 'all'} onClick={() => setKind(k)}
              className={`px-2 py-1 text-xs rounded ${kind === k ? 'bg-violet-500/20 text-violet-200 border border-violet-500/40' : 'bg-slate-800/60 text-slate-400 border border-slate-700'}`}>
              {k || 'all'}
            </button>
          ))}
        </div>
        <div className="rounded-xl bg-slate-900/60 border border-slate-800/80 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/80 text-slate-500 uppercase text-[10px]">
              <tr>
                <th className="text-left p-3">When</th>
                <th className="text-left p-3">Kind</th>
                <th className="text-left p-3">Action</th>
                <th className="text-left p-3">Resource</th>
                <th className="text-left p-3">Signature</th>
              </tr>
            </thead>
            <tbody>
              {events.map(e => (
                <tr key={e.id} className="border-t border-slate-800/60">
                  <td className="p-3 text-slate-400">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="p-3"><span className="px-2 py-0.5 rounded bg-slate-800/60 text-violet-300 text-[10px]">{e.kind}</span></td>
                  <td className="p-3 text-slate-300">{e.action}</td>
                  <td className="p-3 text-slate-400 font-mono text-[11px]">{e.resource_type}/{e.resource_id}</td>
                  <td className="p-3 text-slate-500 font-mono text-[10px]">{e.calc_signature?.slice(0, 12) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {events.length === 0 && <div className="p-8 text-center text-sm text-slate-500">No events yet.</div>}
        </div>
      </div>
    </div>
  );
}
