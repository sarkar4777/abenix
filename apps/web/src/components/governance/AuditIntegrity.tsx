'use client';

import { useState } from 'react';
import { CheckCircle2, Download, Loader2, ShieldAlert, ShieldCheck } from 'lucide-react';
import { API_URL, apiFetch } from '@/lib/api-client';

interface Result {
  ok: boolean;
  checked: number;
  redacted?: number;
  pending?: number;
  head?: string | null;
  head_pos?: number;
  verified_at?: string;
  reason?: string;
  broken_at?: { id: string; chain_pos: number; action: string; created_at: string | null };
}

export default function AuditIntegrity({ canVerify }: { canVerify: boolean }) {
  const [exporting, setExporting] = useState(false);
  async function exportLog() {
    setExporting(true);
    try {
      const res = await fetch(`${API_URL}/api/governance/audit/export`, { headers: { Authorization: `Bearer ${localStorage.getItem('access_token') || ''}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `audit-log-${new Date().toISOString().slice(0, 10)}.jsonl`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e: any) {
      setErr(`Export failed: ${e.message}`);
    } finally {
      setExporting(false);
    }
  }
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function verify() {
    setBusy(true);
    setErr(null);
    const r = await apiFetch<Result>('/api/governance/audit/verify');
    setBusy(false);
    if (r.data) setRes(r.data);
    else setErr(r.error || 'Verification failed to run');
  }

  return (
    <div className="space-y-5" data-testid="audit-integrity">
      <p className="text-sm text-slate-400 max-w-3xl">
        Every entry in the activity log is linked to the one before it by a hash, so an edited or deleted entry breaks the
        chain at that point. The database refuses edits and deletes outright, and archiving or retention leaves a
        marker where it cut, so the remaining chain still verifies. Verifying walks the whole chain for this tenant.
      </p>
      <div className="flex flex-wrap items-center gap-2">
      {canVerify ? (
        <button
          type="button"
          onClick={verify}
          disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-50"
          data-testid="audit-verify"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
          {busy ? 'Checking every entry…' : 'Verify the audit log'}
        </button>
      ) : (
        <p className="text-xs text-slate-500">Verifying needs the audit.verify capability.</p>
      )}
        <button type="button" onClick={exportLog} disabled={exporting} className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm border border-slate-700 text-slate-200 hover:bg-slate-800 disabled:opacity-50" data-testid="audit-export">
          {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />} Export with hashes
        </button>
      </div>
      <p className="text-[11px] text-slate-500">The export holds every linked entry with its hashes, so an auditor can check the chain without access to Abenix.</p>
      {err && <p className="text-sm text-rose-300">{err}</p>}
      {res && res.ok && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-5" data-testid="audit-ok" role="status">
          <div className="flex items-center gap-2 text-emerald-300 font-medium">
            <CheckCircle2 className="w-5 h-5" /> Intact. {res.checked.toLocaleString()} entries checked, none altered or missing.
          </div>
          <dl className="mt-3 grid gap-2 sm:grid-cols-3 text-sm">
            <div>
              <dt className="text-slate-500 text-xs">Erased for privacy</dt>
              <dd className="text-slate-200">
                {(res.redacted || 0).toLocaleString()}
                <span className="block text-xs text-slate-500">who did it was removed on request, what was done still verifies</span>
              </dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Waiting to be linked</dt>
              <dd className="text-slate-200">
                {(res.pending || 0).toLocaleString()}
                <span className="block text-xs text-slate-500">entries from the last minute, linked within about 30 seconds</span>
              </dd>
            </div>
            <div>
              <dt className="text-slate-500 text-xs">Latest link</dt>
              <dd className="text-slate-200 font-mono text-xs break-all">{res.head ? `${res.head.slice(0, 16)}…` : 'none yet'}</dd>
            </div>
          </dl>
        </div>
      )}
      {res && !res.ok && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-5" data-testid="audit-broken" role="alert">
          <div className="flex items-center gap-2 text-rose-200 font-medium">
            <ShieldAlert className="w-5 h-5" /> The chain is broken: {res.reason}.
          </div>
          {res.broken_at && (
            <p className="mt-2 text-sm text-rose-100/90">
              At entry {res.broken_at.chain_pos} ({res.broken_at.action}
              {res.broken_at.created_at ? `, ${new Date(res.broken_at.created_at).toLocaleString()}` : ''}), after{' '}
              {res.checked.toLocaleString()} entries that checked out. Treat the log from this point as untrusted and
              compare it with your archived copies.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
