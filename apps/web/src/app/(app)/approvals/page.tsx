'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  CheckCircle2, XCircle, Clock, Loader2, ShieldCheck, AlertTriangle,
  RefreshCw, ChevronDown, ChevronRight,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface SignoffEntry {
  user_id: string;
  user_email: string;
  decision: 'approve' | 'deny';
  reason: string;
  at: string;
}

interface ApprovalRow {
  id: string;
  agent_id: string | null;
  agent_execution_id: string | null;
  title: string;
  payload: Record<string, unknown>;
  required_signoffs: number;
  signoffs: SignoffEntry[];
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'returned';
  requested_by: string | null;
  expires_at: string | null;
  decided_at: string | null;
  created_at: string | null;
  gate_kind?: string | null;
  policy?: { exclude_requester?: boolean; capability?: string } | null;
}

const GATE_KIND_LABEL: Record<string, string> = {
  human_approval: 'agent gate',
  decision_publish: 'rule change',
};

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  denied: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  expired: 'bg-slate-500/15 text-slate-400 border-slate-500/40',
  returned: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
};

function PayloadView({ payload }: { payload: unknown }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!payload || typeof payload !== 'object') {
    return (
      <pre className="text-[11px] text-slate-300 bg-slate-900/60 border border-slate-800 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words max-h-56">
        {JSON.stringify(payload, null, 2)}
      </pre>
    );
  }
  const entries = Object.entries(payload as Record<string, unknown>);
  if (entries.length === 0) {
    return <p className="text-[11px] text-slate-400 italic">Empty payload.</p>;
  }
  return (
    <div className="space-y-1.5" data-testid="approval-payload-view">
      {entries.map(([key, value]) => (
        <PayloadRow key={key} k={key} v={value} depth={0} />
      ))}
      <button
        type="button"
        onClick={() => setShowRaw((v) => !v)}
        className="mt-2 text-[10px] text-slate-400 hover:text-slate-200"
      >
        {showRaw ? 'Hide raw JSON' : 'Show raw JSON'}
      </button>
      {showRaw && (
        <pre className="text-[10px] text-slate-400 bg-slate-900/40 border border-slate-800/70 rounded p-2 overflow-x-auto whitespace-pre-wrap break-words max-h-48 mt-1">
          {JSON.stringify(payload, null, 2)}
        </pre>
      )}
    </div>
  );
}

function PayloadRow({ k, v, depth }: { k: string; v: unknown; depth: number }) {
  const label = k.replace(/_/g, ' ');
  if (v === null || v === undefined) {
    return (
      <div className="flex items-baseline gap-2 text-[11px]" style={{ paddingLeft: depth * 12 }}>
        <span className="text-slate-500 uppercase tracking-wide text-[10px] min-w-[120px]">{label}</span>
        <span className="text-slate-600 italic">—</span>
      </div>
    );
  }
  if (typeof v === 'object' && !Array.isArray(v)) {
    const entries = Object.entries(v as Record<string, unknown>);
    return (
      <div style={{ paddingLeft: depth * 12 }}>
        <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-1 mt-1">{label}</p>
        <div className="space-y-1">
          {entries.map(([k2, v2]) => (
            <PayloadRow key={k2} k={k2} v={v2} depth={depth + 1} />
          ))}
        </div>
      </div>
    );
  }
  if (Array.isArray(v)) {
    return (
      <div style={{ paddingLeft: depth * 12 }}>
        <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-1 mt-1">{label} <span className="text-slate-500 normal-case">({v.length} item{v.length === 1 ? '' : 's'})</span></p>
        <div className="space-y-1">
          {v.slice(0, 8).map((item, idx) => (
            <PayloadRow key={idx} k={`#${idx}`} v={item} depth={depth + 1} />
          ))}
          {v.length > 8 && (
            <p className="text-[10px] text-slate-600 italic" style={{ paddingLeft: (depth + 1) * 12 }}>
              {v.length - 8} more…
            </p>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-baseline gap-2 text-[11px]" style={{ paddingLeft: depth * 12 }}>
      <span className="text-slate-500 uppercase tracking-wide text-[10px] min-w-[120px]">{label}</span>
      <span className="text-slate-200 font-mono break-words">{String(v)}</span>
    </div>
  );
}

function relTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso).getTime();
  const diff = Math.max(0, Date.now() - d);
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function expiryString(iso: string | null, nowMs: number): string {
  if (!iso) return '';
  const target = new Date(iso).getTime();
  const remaining = target - nowMs;
  if (remaining <= 0) return 'expired';
  if (remaining < 60_000) return `${Math.ceil(remaining / 1000)}s left`;
  const m = Math.floor(remaining / 60000);
  if (m < 60) return `${m}m left`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h left`;
  return `${Math.floor(h / 24)}d left`;
}

function useLiveClock(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

function ApprovalCard({ row, onDecide, busy }: { row: ApprovalRow; onDecide: (id: string, decision: 'approve' | 'deny' | 'return', reason?: string) => Promise<string | null>; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [decideErr, setDecideErr] = useState<string | null>(null);
  async function decide(d: 'approve' | 'deny' | 'return') {
    setDecideErr(null);
    if (d === 'return' && !reason.trim()) {
      setOpen(true);
      setDecideErr('Say what needs to change in the reason box, then press Return again.');
      return;
    }
    const e = await onDecide(row.id, d, reason);
    if (e) setDecideErr(e);
  }
  const isPending = row.status === 'pending';
  const approveCount = row.signoffs.filter(s => s.decision === 'approve').length;
  const now = useLiveClock(isPending && row.expires_at ? 1000 : 60_000);

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 mb-3" data-testid="approval-card" data-approval-id={row.id} data-status={row.status}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-[240px]">
          <div className="flex items-center gap-2 mb-1.5">
            <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0" />
            <h3 className="text-sm font-semibold text-white truncate">{row.title || 'Approval requested'}</h3>
            <span className={`text-[10px] px-2 py-0.5 rounded-full border uppercase tracking-wider ${STATUS_BADGE[row.status]}`}>
              {row.status}
            </span>
            {row.gate_kind && (
              <span
                className="text-[10px] px-2 py-0.5 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 tracking-wide"
                data-testid="approval-gate-kind"
                title={row.gate_kind}
              >
                {GATE_KIND_LABEL[row.gate_kind] || row.gate_kind}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-3 text-[11px] text-slate-500">
            <span>Created {relTime(row.created_at)}</span>
            <span>{approveCount}/{row.required_signoffs} approvals</span>
            {row.expires_at && row.status === 'pending' && (
              <span className="text-amber-300/80 flex items-center gap-1" data-testid="approval-expiry">
                <Clock className="w-3 h-3" /> {expiryString(row.expires_at, now)}
              </span>
            )}
            {row.agent_execution_id && (
              <span className="font-mono text-slate-600">exec {row.agent_execution_id.slice(0, 8)}</span>
            )}
          </div>
          {row.gate_kind === 'decision_publish' && (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px]" data-testid="approval-decision">
              {typeof row.payload?.link === 'string' && (
                <a href={row.payload.link as string} className="text-cyan-300 hover:underline">Review the rules and what changes</a>
              )}
              {typeof row.payload?.summary === 'string' && <span className="text-slate-400">{row.payload.summary as string}</span>}
              <span className="text-slate-500">
                Needs decisions.review{row.policy ? ` and ${row.policy.capability || 'approvals.sign'}` : ''}{row.policy?.exclude_requester ? ', and not the person who proposed it' : ''}
              </span>
            </div>
          )}
        </div>
        {isPending && (
          <div className="flex flex-col sm:flex-row gap-2 shrink-0 w-full sm:w-auto">
            <button
              disabled={busy}
              onClick={() => decide('approve')}
              className="px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs font-medium hover:bg-emerald-500/25 disabled:opacity-50 flex items-center gap-1.5 justify-center"
            >
              <CheckCircle2 className="w-3.5 h-3.5" /> Approve
            </button>
            <button
              disabled={busy}
              onClick={() => decide('deny')}
              className="px-3 py-1.5 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs font-medium hover:bg-rose-500/25 disabled:opacity-50 flex items-center gap-1.5 justify-center"
            >
              <XCircle className="w-3.5 h-3.5" /> Deny
            </button>
            {!row.id.startsWith('hitl:') && (
              <button
                disabled={busy}
                onClick={() => decide('return')}
                className="px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/40 text-amber-300 text-xs font-medium hover:bg-amber-500/20 disabled:opacity-50 flex items-center gap-1.5 justify-center"
                data-testid="approval-return"
              >
                Return for changes
              </button>
            )}
          </div>
        )}
        {decideErr && <p className="basis-full text-xs text-rose-300" role="alert" data-testid="approval-error">{decideErr}</p>}
      </div>
      <button
        onClick={() => setOpen(o => !o)}
        className="mt-3 flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-white"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        Payload, signoff history
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Payload</p>
            <PayloadView payload={row.payload} />
          </div>
          {row.signoffs.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Signoffs</p>
              <div className="space-y-1">
                {row.signoffs.map((s, idx) => (
                  <div key={idx} className="flex flex-wrap items-center gap-2 text-[11px] bg-slate-900/40 border border-slate-800 rounded-md px-2 py-1.5">
                    {s.decision === 'approve' ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <XCircle className="w-3.5 h-3.5 text-rose-400" />
                    )}
                    <span className="text-white font-medium">{s.user_email || s.user_id.slice(0, 8)}</span>
                    <span className="text-slate-500">{s.decision}</span>
                    {s.reason && <span className="text-slate-400 italic truncate max-w-xs">"{s.reason}"</span>}
                    <span className="text-slate-600 ml-auto">{relTime(s.at)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {isPending && (
            <div>
              <label className="text-[10px] uppercase tracking-wider text-slate-500">Reason (needed to return it)</label>
              <input
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="Why are you approving, denying or returning it?"
                className="mt-1 w-full px-2 py-1.5 text-[11px] bg-slate-900/60 border border-slate-700 rounded-md text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500/50"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ApprovalsPage() {
  const [pending, setPending] = useState<ApprovalRow[]>([]);
  const [recent, setRecent] = useState<ApprovalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const pendingRes = await apiFetch<ApprovalRow[]>('/api/approvals?mine=1&status=pending', { silent: true });
    const recentRes = await apiFetch<ApprovalRow[]>('/api/approvals?mine=1', { silent: true });
    if (pendingRes.error && !pendingRes.data) {
      setError(pendingRes.error);
    } else {
      setError(null);
      setPending(pendingRes.data || []);
    }
    const all = recentRes.data || [];
    setRecent(all.filter(a => a.status !== 'pending').slice(0, 50));
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const handleDecide = async (id: string, decision: 'approve' | 'deny' | 'return', reason?: string): Promise<string | null> => {
    setBusyId(id);
    // ids are opaque strings, agent gates look like hitl:{execution}:{gate}
    const r = await apiFetch(`/api/approvals/${encodeURIComponent(id)}/signoff`, {
      method: 'POST',
      body: JSON.stringify({ decision, reason }),
      throwOnError: false,
    });
    setBusyId(null);
    await load();
    return r.error;
  };

  return (
    <div className="max-w-5xl mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center">
            <ShieldCheck className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Approvals</h1>
            <p className="text-sm text-slate-500">Sign off on agent actions that require human review.</p>
          </div>
          <button
            onClick={load}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs text-slate-300 hover:text-white"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 flex items-center gap-2 text-sm text-rose-200">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <section className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-white uppercase tracking-wider">Pending</h2>
          <span className="text-[11px] text-slate-400">{pending.length} requests</span>
        </div>
        {loading && pending.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-8 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading approvals
          </div>
        ) : pending.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-400/40 mx-auto mb-2" />
            <p className="text-sm text-slate-400">No approvals waiting on you. Nice.</p>
          </div>
        ) : (
          pending.map(a => (
            <ApprovalCard key={a.id} row={a} onDecide={handleDecide} busy={busyId === a.id} />
          ))
        )}
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-white uppercase tracking-wider">Recent decisions</h2>
          <span className="text-[11px] text-slate-400">{recent.length} resolved</span>
        </div>
        {recent.length === 0 ? (
          <p className="text-xs text-slate-600">No decisions yet.</p>
        ) : (
          recent.map(a => (
            <ApprovalCard key={a.id} row={a} onDecide={handleDecide} busy={busyId === a.id} />
          ))
        )}
      </section>
    </div>
  );
}
