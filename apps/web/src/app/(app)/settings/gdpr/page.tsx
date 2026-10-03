'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api-client';

interface Receipt {
  id: string;
  store: string;
  status: string;
  error: string | null;
  retries: number;
  affected: number | null;
  attempted_at: string;
  completed_at: string | null;
  requested_by: string | null;
}

export default function GDPRPage() {
  const [userId, setUserId] = useState('');
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<Record<string, { status: string; affected?: number }> | null>(null);

  async function purge() {
    if (!userId.trim()) return;
    setBusy(true);
    setError(null);
    setLast(null);
    try {
      const r = await apiFetch<{ subject_user_id: string; receipt: Record<string, { status: string; affected?: number }> }>(
        `/api/gdpr/users/${userId}/purge`,
        { method: 'POST' },
      );
      if (r.data) setLast(r.data.receipt);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (!userId.trim()) return;
    try {
      const r = await apiFetch<Receipt[]>(`/api/gdpr/users/${userId}/receipts?limit=100`);
      setReceipts(r.data || []);
    } catch {
      setReceipts([]);
    }
  }

  useEffect(() => {
    refresh();
  }, [userId]);

  return (
    <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">
      <header>
        <h1 className="text-3xl font-semibold text-white">GDPR — right to erasure</h1>
        <p className="text-slate-400 mt-2 max-w-3xl">
          Cascade-delete one user's data across Postgres, Pinecone, Neo4j, blob storage,
          and trajectory memory. Every store-level attempt is logged for audit.
        </p>
      </header>

      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 space-y-3">
        <label className="block">
          <span className="text-xs text-slate-400">Subject user ID (UUID)</span>
          <input
            type="text"
            value={userId}
            onChange={e => setUserId(e.target.value)}
            placeholder="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            className="mt-1 w-full max-w-md rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-white font-mono text-xs"
          />
        </label>
        <div className="flex gap-2">
          <button
            onClick={purge}
            disabled={busy || !userId.trim()}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
          >
            {busy ? 'Purging…' : 'Execute purge'}
          </button>
          <button
            onClick={refresh}
            disabled={!userId.trim()}
            className="rounded-md bg-slate-700 px-3 py-2 text-xs text-slate-200 hover:bg-slate-600 disabled:opacity-50"
          >
            Refresh receipts
          </button>
        </div>
        {error && <p className="text-red-400 text-xs">{error}</p>}
      </section>

      {last !== null && (
        <section className="rounded-xl border border-emerald-700/40 bg-emerald-950/30 p-5">
          <h2 className="text-sm font-semibold text-emerald-300 mb-2">Receipt for this purge</h2>
          <ul className="text-xs font-mono space-y-1">
            {Object.entries(last).map(([store, info]) => (
              <li key={store}>
                <span className="text-slate-400">{store}:</span>{' '}
                <span className={info.status === 'completed' ? 'text-emerald-300' : 'text-amber-300'}>
                  {info.status}
                </span>
                {info.affected !== undefined && (
                  <span className="text-slate-500"> · {info.affected} affected</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="text-sm font-semibold text-cyan-300 uppercase tracking-wider mb-3">
          Audit history ({receipts.length})
        </h2>
        {receipts.length === 0 ? (
          <p className="text-sm text-slate-500">No receipts yet.</p>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-slate-400">
              <tr className="border-b border-slate-800">
                <th className="text-left py-2">Store</th>
                <th className="text-left py-2">Status</th>
                <th className="text-left py-2">Attempted</th>
                <th className="text-left py-2">Completed</th>
                <th className="text-left py-2">Removed</th>
                <th className="text-left py-2">Retries</th>
              </tr>
            </thead>
            <tbody>
              {receipts.map(r => (
                <tr key={r.id} className="border-b border-slate-800/50">
                  <td className="py-1.5 font-mono">{r.store}</td>
                  <td className={r.status === 'completed' ? 'text-emerald-300' : r.status === 'failed' ? 'text-red-400' : 'text-amber-300'}>
                    {r.status}
                  </td>
                  <td className="text-slate-500">{r.attempted_at?.slice(0, 19)}</td>
                  <td className="text-slate-500">{r.completed_at?.slice(0, 19) || '—'}</td>
                  <td className="text-slate-500">{r.affected ?? '—'}</td>
                  <td className="text-slate-500">{r.retries}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
