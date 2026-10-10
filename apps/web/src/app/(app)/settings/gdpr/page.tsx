'use client';

import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, Search, UserX, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PageHeader from '@/components/layout/PageHeader';

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

interface Person {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

const STORE_LABELS: Record<string, string> = {
  postgres: 'Database',
  pinecone: 'Vector store',
  neo4j: 'Knowledge graph',
  blob: 'Uploaded files',
  trajectory: 'Agent memory',
};

const storeLabel = (s: string) => STORE_LABELS[s] || s;
const erased = (p: Person) => p.email.endsWith('@purged.local');

export default function GDPRPage() {
  const [me, setMe] = useState<{ id: string; role: string } | null>(null);
  const [people, setPeople] = useState<Person[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [subject, setSubject] = useState<Person | null>(null);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<Record<string, { status: string; affected?: number; error?: string }> | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    (async () => {
      const m = await apiFetch<{ user: { id: string; role: string; email: string; full_name: string } }>('/api/auth/me', { silent: true });
      const u = m.data?.user;
      if (!u) { setLoadError(m.error || 'Could not load your account.'); return; }
      setMe({ id: u.id, role: u.role });
      if (u.role !== 'admin') {
        // members can only erase themselves
        setPeople([]);
        setSubject({ id: u.id, email: u.email, full_name: u.full_name, role: u.role, is_active: true });
        return;
      }
      const t = await apiFetch<{ members: Person[] }>('/api/team/members', { silent: true });
      if (t.error) setLoadError(t.error);
      setPeople(t.data?.members || []);
    })();
  }, []);

  const isAdmin = me?.role === 'admin';
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !people) return [];
    return people
      .filter((p) => p.id !== me?.id && !erased(p))
      .filter((p) => p.email.toLowerCase().includes(q) || (p.full_name || '').toLowerCase().includes(q))
      .slice(0, 8);
  }, [people, query, me]);

  async function refresh(id = subject?.id) {
    if (!id) return;
    const r = await apiFetch<Receipt[]>(`/api/gdpr/users/${id}/receipts?limit=100`, { silent: true });
    setReceipts(r.data || []);
  }

  useEffect(() => {
    setReceipts([]);
    setLast(null);
    setError(null);
    if (subject) refresh(subject.id);
  }, [subject?.id]);

  async function purge() {
    if (!subject) return;
    setConfirming(false);
    setBusy(true);
    setError(null);
    setLast(null);
    const r = await apiFetch<{ subject_user_id: string; receipt: Record<string, { status: string; affected?: number; error?: string }> }>(
      `/api/gdpr/users/${subject.id}/purge`,
      { method: 'POST', throwOnError: false },
    );
    if (r.data) setLast(r.data.receipt);
    else setError(r.error || 'The erasure could not run.');
    await refresh(subject.id);
    setBusy(false);
  }

  const self = !!subject && subject.id === me?.id;

  return (
    <main className="max-w-5xl mx-auto sm:px-6 py-2 sm:py-8 space-y-6">
      <PageHeader
        title="GDPR erasure"
        icon={UserX}
        iconClassName="text-rose-300"
        purpose="Permanently erase one person's data from every store the platform uses, with a receipt for each step. For admins handling erasure requests."
        primaryAction={{
          label: 'Refresh receipts',
          icon: RefreshCw,
          onClick: () => refresh(),
          disabled: !subject,
          title: subject ? undefined : 'Pick a person first',
        }}
        steps={[
          'Search for the person by name or email. Members can only erase themselves.',
          'Press Erase and confirm. Their account is closed and their data is deleted.',
          'The database, persona vectors, graph entities, uploaded files and run records are cleared. Files still in use are kept.',
          'Each store writes a receipt so you can show the request was carried out.',
        ]}
        docSlug="01-architecture/07-governance"
        storageKey="settings-gdpr"
      />

      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 space-y-3">
        {loadError && <p className="text-red-400 text-xs" role="alert">{loadError}</p>}
        {!me && !loadError && <div className="h-10 max-w-md rounded bg-slate-800/60 animate-pulse" aria-busy="true" />}

        {isAdmin && !subject && (
          <div className="max-w-md">
            <label htmlFor="gdpr-person" className="text-xs text-slate-400">Whose data to erase</label>
            <div className="relative mt-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
              <input
                id="gdpr-person"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search people by name or email"
                autoComplete="off"
                data-testid="gdpr-person-search"
                className="w-full rounded-md bg-slate-800 border border-slate-700 pl-8 pr-3 py-1.5 text-sm text-white"
              />
            </div>
            {query.trim() && people && (
              <ul className="mt-1 rounded-md border border-slate-700 bg-slate-900 divide-y divide-slate-800" role="listbox" aria-label="Matching people">
                {matches.length === 0 ? (
                  <li className="px-3 py-2 text-xs text-slate-500">Nobody matches. You cannot erase your own admin account here.</li>
                ) : matches.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={false}
                      onClick={() => { setSubject(p); setQuery(''); }}
                      className="w-full text-left px-3 py-2 hover:bg-slate-800"
                      data-testid={`gdpr-pick-${p.email}`}
                    >
                      <span className="block text-sm text-white">{p.full_name || p.email}</span>
                      <span className="block text-xs text-slate-500">{p.email}{p.is_active ? '' : ' · removed from the team'}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[11px] text-slate-500 mt-1">Everyone in this workspace is listed, including people already removed from the team.</p>
          </div>
        )}

        {subject && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2 max-w-xl" data-testid="gdpr-subject">
            <UserX className="w-4 h-4 text-rose-300 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-white truncate">{subject.full_name || subject.email}{self ? ' (you)' : ''}</p>
              <p className="text-xs text-slate-500 truncate">{subject.email}{subject.is_active ? '' : ' · removed from the team'}</p>
            </div>
            {isAdmin && (
              <button type="button" onClick={() => setSubject(null)} aria-label="Pick someone else" className="p-1 rounded text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setConfirming(true)}
            disabled={busy || !subject}
            data-testid="gdpr-erase"
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
          >
            {busy ? 'Erasing…' : self ? 'Erase my data' : 'Erase this person’s data'}
          </button>
        </div>
        {error && <p className="text-red-400 text-xs" role="alert">{error}</p>}
      </section>
      <ConfirmModal
        open={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={purge}
        title={self ? 'Erase your own data for good?' : `Erase ${subject?.full_name || subject?.email || 'this person'}'s data for good?`}
        description={`Everything stored for ${subject?.email || 'this person'} is deleted from every store and their account is closed. This cannot be undone. Only the erasure receipts below are kept.`}
        confirmLabel="Erase data"
        variant="danger"
        confirmTestId="gdpr-confirm"
      />

      {last !== null && (
        <section className="rounded-xl border border-emerald-700/40 bg-emerald-950/30 p-5" data-testid="gdpr-receipt">
          <h2 className="text-sm font-semibold text-emerald-300 mb-2">Receipt for this erasure</h2>
          <ul className="text-xs space-y-1">
            {Object.entries(last).map(([store, info]) => (
              <li key={store}>
                <span className="text-slate-400">{storeLabel(store)}:</span>{' '}
                <span className={info.status === 'completed' ? 'text-emerald-300' : 'text-amber-300'}>
                  {info.status === 'completed' ? 'erased' : info.status}
                </span>
                {info.affected !== undefined && (
                  <span className="text-slate-500"> · {info.affected} removed</span>
                )}
                {info.error && <span className="text-rose-300"> · {info.error}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="text-sm font-semibold text-cyan-300 uppercase tracking-wider mb-3">
          Audit history ({receipts.length})
        </h2>
        {!subject ? (
          <p className="text-sm text-slate-500">Pick a person to see their erasure receipts.</p>
        ) : receipts.length === 0 ? (
          <p className="text-sm text-slate-500">No receipts yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-xs" data-testid="gdpr-receipts">
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
                    <td className="py-1.5">{storeLabel(r.store)}</td>
                    <td className={r.status === 'completed' ? 'text-emerald-300' : r.status === 'failed' ? 'text-red-400' : 'text-amber-300'} title={r.error || undefined}>
                      {r.status}
                    </td>
                    <td className="text-slate-500">{r.attempted_at ? new Date(r.attempted_at).toLocaleString() : '—'}</td>
                    <td className="text-slate-500">{r.completed_at ? new Date(r.completed_at).toLocaleString() : '—'}</td>
                    <td className="text-slate-500">{r.affected ?? '—'}</td>
                    <td className="text-slate-500">{r.retries}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
