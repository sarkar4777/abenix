'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Download, Loader2, RefreshCw, ScrollText, ShieldCheck, X } from 'lucide-react';
import { apiFetch, API_URL } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';
import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/contexts/AuthContext';

interface AuditEvent {
  id: string;
  seq: number;
  action: string;
  actor_id: string | null;
  actor_email: string | null;
  actor_name: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string | null;
  chained: boolean;
}

interface AuditPage {
  items: AuditEvent[];
  next_before: number | null;
  actions: string[];
}

interface Member { id: string; email: string; full_name?: string | null }

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  if (diff < 0) return new Date(iso).toLocaleString();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function summary(details: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(details).slice(0, 4)) {
    const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
    parts.push(`${k.replace(/_/g, ' ')}: ${val.length > 60 ? `${val.slice(0, 60)}…` : val}`);
  }
  return parts.join(' · ');
}

const RANGES: Record<string, number | null> = { '24h': 1, '7d': 7, '30d': 30, all: null };

function AuditLogPage() {
  const { user: me } = useAuth();
  const { data: team } = useApi<{ members: Member[] }>('/api/team/members');
  const [actor, setActor] = useState('');
  const [action, setAction] = useState('');
  const [q, setQ] = useState('');
  const [range, setRange] = useState('7d');
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [actions, setActions] = useState<string[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [verify, setVerify] = useState<{ ok: boolean; text: string } | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [exporting, setExporting] = useState(false);

  const query = useCallback((before?: number | null) => {
    const p = new URLSearchParams({ limit: '50' });
    if (actor) p.set('actor_id', actor);
    if (action) p.set('action', action);
    if (q.trim()) p.set('q', q.trim());
    const days = RANGES[range];
    if (days) p.set('since', new Date(Date.now() - days * 86400_000).toISOString());
    if (before) p.set('before', String(before));
    return `/api/governance/audit/events?${p.toString()}`;
  }, [actor, action, q, range]);

  const load = useCallback(async () => {
    setLoading(true);
    const r = await apiFetch<AuditPage>(query(), { silent: true, throwOnError: false });
    if (r.error) { setErr(r.error); setItems([]); }
    else {
      setErr(null);
      setItems(r.data?.items || []);
      setNext(r.data?.next_before ?? null);
      if (r.data?.actions?.length) setActions(r.data.actions);
    }
    setLoading(false);
  }, [query]);

  // text search waits for a pause in typing
  useEffect(() => {
    const t = setTimeout(() => { void load(); }, q ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  const more = async () => {
    if (!next) return;
    setLoading(true);
    const r = await apiFetch<AuditPage>(query(next), { silent: true, throwOnError: false });
    if (!r.error) {
      setItems((prev) => [...prev, ...(r.data?.items || [])]);
      setNext(r.data?.next_before ?? null);
    }
    setLoading(false);
  };

  const runVerify = async () => {
    setVerifying(true);
    const r = await apiFetch<{ ok: boolean; checked: number; reason?: string }>('/api/governance/audit/verify', { silent: true, throwOnError: false });
    setVerify(r.error
      ? { ok: false, text: `Could not check the trail. ${r.error}` }
      : r.data?.ok
        ? { ok: true, text: `Intact. ${r.data.checked.toLocaleString()} entries checked, none changed or missing.` }
        : { ok: false, text: `The trail does not check out. ${r.data?.reason || ''}` });
    setVerifying(false);
    void load();
  };

  const runExport = async () => {
    setExporting(true);
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
      const days = RANGES[range];
      const qs = days ? `?since=${encodeURIComponent(new Date(Date.now() - days * 86400_000).toISOString())}` : '';
      const res = await fetch(`${API_URL}/api/governance/audit/export${qs}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) { setVerify({ ok: false, text: `Export failed (HTTP ${res.status}).` }); return; }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url; a.download = 'audit-log.jsonl';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally { setExporting(false); }
  };

  const filtered = !!(actor || action || q || range !== 'all');
  const clear = () => { setActor(''); setAction(''); setQ(''); setRange('all'); };
  const sel = 'w-full min-w-0 px-3 py-2 bg-slate-800/60 border border-slate-700 rounded-lg text-sm text-slate-100 outline-none focus:border-cyan-500';

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="admin-audit">
      <PageHeader
        className="mb-6"
        title="Audit Log"
        purpose="Who did what in this workspace and when, from the tamper-evident activity trail. For admins."
        icon={ScrollText}
        storageKey="admin-audit"
        docSlug="08-howto/11-governance"
        primaryAction={{ label: 'Refresh', icon: RefreshCw, busy: loading, onClick: () => void load(), testId: 'audit-refresh' }}
        extraActions={
          <>
            <button onClick={runVerify} disabled={verifying} data-testid="audit-verify" className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs text-emerald-300 border border-emerald-500/30 hover:border-emerald-400 rounded-lg disabled:opacity-50">
              {verifying ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />} Check nothing was changed
            </button>
            <button onClick={runExport} disabled={exporting} data-testid="audit-export" className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs text-slate-300 border border-slate-600/40 hover:border-slate-500 rounded-lg disabled:opacity-50">
              {exporting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />} Export
            </button>
          </>
        }
        steps={[
          'Every sign-in, setting change, share, approval and deletion lands here, newest first.',
          'Filter by person, kind of action, words in the details, or time.',
          'Check nothing was changed walks the hash chain and says whether any entry was edited or removed.',
        ]}
      />

      <div className="grid grid-cols-[minmax(0,1fr)] sm:grid-cols-[repeat(2,minmax(0,1fr))] lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)_auto_auto] items-end gap-2 mb-4" data-testid="audit-filters">
        <label className="flex flex-col gap-1 text-[11px] text-slate-400 min-w-0">
          Who
          <select value={actor} onChange={(e) => setActor(e.target.value)} className={sel} data-testid="audit-filter-actor">
            <option value="">Everyone</option>
            {me && <option value={me.id}>Me ({me.email})</option>}
            {(team?.members || []).filter((m) => m.id !== me?.id).map((m) => (
              <option key={m.id} value={m.id}>{m.full_name ? `${m.full_name} · ${m.email}` : m.email}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-slate-400 min-w-0">
          Action
          <select value={action} onChange={(e) => setAction(e.target.value)} className={sel} data-testid="audit-filter-action">
            <option value="">Any action</option>
            {actions.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-slate-400 min-w-0">
          Contains
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="a name, an id, an email…" className={sel} data-testid="audit-filter-q" />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-slate-400 min-w-0">
          When
          <select value={range} onChange={(e) => setRange(e.target.value)} className={sel} data-testid="audit-filter-range">
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="all">Any time</option>
          </select>
        </label>
        {filtered && (
          <button onClick={clear} className="flex items-center gap-1 px-3 py-2 text-xs text-slate-400 hover:text-white" data-testid="audit-filter-clear">
            <X className="w-3 h-3" /> Clear
          </button>
        )}
      </div>

      {verify && (
        <p role="status" data-testid="audit-verify-result" className={`mb-4 text-xs rounded-lg border px-3 py-2 ${verify.ok ? 'text-emerald-300 border-emerald-500/30 bg-emerald-500/5' : 'text-rose-300 border-rose-500/30 bg-rose-500/5'}`}>{verify.text}</p>
      )}

      {err && (
        <div className="mb-4 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold mb-1">Couldn&apos;t load the audit log</div>
            <div className="text-xs opacity-80">{err}</div>
          </div>
        </div>
      )}

      <div className="space-y-2" data-testid="audit-list">
        {loading && items.length === 0 && (
          <div className="flex items-center justify-center gap-2 text-sm text-slate-500 py-10"><Loader2 className="w-4 h-4 animate-spin" /> Loading</div>
        )}
        {!loading && items.length === 0 && !err && (
          <div className="rounded-xl border border-dashed border-slate-700/50 p-8 text-center text-sm text-slate-500" data-testid="audit-empty">
            {filtered ? 'Nothing matches these filters.' : 'No activity recorded yet.'}
            {filtered && <button onClick={clear} className="ml-2 text-cyan-400 hover:underline">Clear filters</button>}
          </div>
        )}
        {items.map((r) => (
          <div key={r.id} data-testid="audit-row" data-action={r.action} data-actor={r.actor_id || ''} className="rounded-xl border border-slate-700/50 bg-slate-900/40 px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">{r.action}</span>
              <span className="text-xs text-slate-200">{r.actor_name || r.actor_email || 'System'}</span>
              {r.actor_email && r.actor_name && <span className="text-[11px] text-slate-500">{r.actor_email}</span>}
              <span className="ml-auto text-[11px] text-slate-500" title={r.created_at ? new Date(r.created_at).toLocaleString() : ''}>{relTime(r.created_at)}</span>
            </div>
            {Object.keys(r.details).length > 0 && (
              <p className="mt-1 text-[11px] text-slate-400 break-words">{summary(r.details)}</p>
            )}
            {r.ip_address && <p className="mt-0.5 text-[10px] text-slate-600">from {r.ip_address}</p>}
          </div>
        ))}
        {next && (
          <button onClick={more} disabled={loading} className="w-full py-2 text-xs text-slate-400 hover:text-white border border-slate-700/50 rounded-lg disabled:opacity-50" data-testid="audit-more">
            {loading ? 'Loading…' : 'Show older'}
          </button>
        )}
      </div>
    </div>
  );
}

export default function AuditLogPageGated() {
  return (
    <AccessGate
      title="Audit Log"
      purpose="Who did what in this workspace and when, from the tamper-evident activity trail. For admins."
      icon={ScrollText}
      need={{ admin: true }}
    >
      <AuditLogPage />
    </AccessGate>
  );
}
