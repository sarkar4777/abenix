'use client';

import { useEffect, useState } from 'react';
import {
  Archive, RefreshCw, Play, Download, CheckCircle2, XCircle,
  Clock, Settings2, Save, Loader2,
} from 'lucide-react';
import { apiFetch, API_URL } from '@/lib/api-client';
import ConfirmModal from '@/components/ui/ConfirmModal';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';

// Plain <a href> drops the bearer token, so fetch the dump and hand it over as a blob
async function downloadArchive(run: ArchiveRun): Promise<string | null> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  const res = await fetch(`${API_URL}/api/admin/archives/${run.id}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.error?.message || body?.detail || detail;
    } catch {/* non-json body */}
    return detail;
  }
  const blob = await res.blob();
  const name = run.file_uri?.split(/[\/]/).pop() || `${run.source_table}-${run.id}.jsonl.gz`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return null;
}

interface ArchiveRun {
  id: string;
  source_table: string;
  status: string;
  is_manual: boolean;
  started_at?: string;
  completed_at?: string;
  cutoff_at?: string;
  rows_archived: number;
  rows_deleted: number;
  file_uri?: string;
  file_size_bytes: number;
  file_sha256?: string;
  oldest_row_at?: string;
  newest_row_at?: string;
  error_message?: string;
}

interface RetentionPolicy {
  source_table: string;
  retention_days: number;
  enabled: boolean;
  description?: string;
  updated_at?: string;
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function fmtDate(iso?: string): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function AdminArchivesPage() {
  const [runs, setRuns] = useState<ArchiveRun[]>([]);
  const [tables, setTables] = useState<string[]>([]);
  const [policies, setPolicies] = useState<RetentionPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [savingPolicy, setSavingPolicy] = useState<string | null>(null);
  const [confirmTable, setConfirmTable] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiFetch<{ items: ArchiveRun[]; archivable_tables: string[] }>('/api/admin/archives');
      setRuns(r.data?.items || []);
      setTables(r.data?.archivable_tables || []);
      const p = await apiFetch<{ items: RetentionPolicy[] }>('/api/admin/archives/retention-policies');
      setPolicies(p.data?.items || []);
    } catch {/* silent */}
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const triggerArchive = async (table: string) => {
    setConfirmTable(null);
    setTriggering(table);
    setNotice(null);
    const r = await apiFetch('/api/admin/archives/trigger', {
      method: 'POST',
      body: JSON.stringify({ table }),
      throwOnError: false,
    });
    setNotice(r.error ? { ok: false, text: `Could not archive ${table}. ${r.error}` } : { ok: true, text: `Archive of ${table} started. It shows under Recent runs.` });
    await load();
    setTriggering(null);
  };

  const updatePolicy = async (p: RetentionPolicy) => {
    setSavingPolicy(p.source_table);
    setNotice(null);
    const r = await apiFetch(`/api/admin/archives/retention-policies/${p.source_table}`, {
      method: 'PUT',
      body: JSON.stringify({
        retention_days: p.retention_days,
        enabled: p.enabled,
        description: p.description,
      }),
      throwOnError: false,
    });
    setNotice(r.error ? { ok: false, text: `Could not save ${p.source_table}. ${r.error}` } : { ok: true, text: `Saved. ${p.source_table} keeps ${p.retention_days} days${p.enabled ? '' : ', nightly archiving is off'}.` });
    await load();
    setSavingPolicy(null);
  };
  const confirmPolicy = policies.find((p) => p.source_table === confirmTable);

  return (
    <div className="p-6 space-y-6 max-w-6xl">
      <PageHeader
        title="Archives"
        purpose="Decide how long run and activity records stay in the live database and download the old ones once they are archived. For admins."
        icon={Archive}
        storageKey="admin-archives"
        docSlug="06-deployment/disaster-recovery"
        primaryAction={{ label: 'Refresh', icon: RefreshCw, onClick: load, busy: loading, title: 'Refresh' }}
        steps={[
          'Every night at 02:00 UTC, rows older than the retention for their table are written to a dump file and removed from the live table.',
          'Set how many days each table keeps. Defaults are 30 days for invocations, 60 for executions and 90 for audit logs.',
          'Click a table under Manual trigger to archive it right now.',
          'Each run shows under Recent runs, where you can download its dump file.',
        ]}
      />

      <section>
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Settings2 className="w-4 h-4" /> Retention policies
        </h2>
        {notice && (
          <p role="status" data-testid="archives-notice" className={`mb-2 text-xs ${notice.ok ? 'text-emerald-300' : 'text-rose-300'}`}>{notice.text}</p>
        )}
        <div className="rounded-xl border border-slate-700 bg-slate-900/30 overflow-x-auto">
         <div className="min-w-[640px]">
          <div className="grid grid-cols-12 gap-2 px-4 py-2 border-b border-slate-700 text-[10px] uppercase tracking-wider text-slate-500 bg-slate-900/60">
            <div className="col-span-4">Table</div>
            <div className="col-span-2">Retention (days)</div>
            <div className="col-span-2">Enabled</div>
            <div className="col-span-3">Description</div>
            <div className="col-span-1 text-right">Save</div>
          </div>
          {policies.map((p) => (
            <PolicyRow key={p.source_table} policy={p} onSave={updatePolicy} saving={savingPolicy === p.source_table} />
          ))}
         </div>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Play className="w-4 h-4" /> Manual trigger
        </h2>
        <div className="flex flex-wrap gap-2">
          {tables.map((t) => (
            <button
              key={t}
              onClick={() => setConfirmTable(t)}
              disabled={triggering === t}
              className="px-3 py-1.5 rounded-lg border border-cyan-500/30 bg-cyan-500/5 hover:bg-cyan-500/15 text-cyan-300 text-xs font-mono flex items-center gap-2"
              data-testid={`archive-trigger-${t}`}
            >
              {triggering === t ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
              {t}
            </button>
          ))}
        </div>
      </section>

      <ConfirmModal
        open={!!confirmTable}
        onClose={() => setConfirmTable(null)}
        onConfirm={() => confirmTable && triggerArchive(confirmTable)}
        title={`Archive ${confirmTable} now?`}
        description={`Rows older than ${confirmPolicy?.retention_days ?? 'the retention'} days are written to a dump file under /data/archives/ and then deleted from the live table. You can download the dump from Recent runs.`}
        confirmLabel="Archive now"
        variant="danger"
      />

      <section>
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Clock className="w-4 h-4" /> Recent runs
        </h2>
        <div className="rounded-xl border border-slate-700 bg-slate-900/30 overflow-hidden" data-testid="archive-runs-list">
          {runs.length === 0 && !loading && (
            <div className="px-4 py-8 text-center text-[11px] text-slate-500">
              No archive runs yet. Nightly job kicks at 02:00 UTC; click a table above to trigger now.
            </div>
          )}
          {runs.map((r) => (
            <RunRow key={r.id} run={r} />
          ))}
        </div>
      </section>
    </div>
  );
}

function PolicyRow({ policy, onSave, saving }: { policy: RetentionPolicy; onSave: (p: RetentionPolicy) => void; saving: boolean }) {
  const [local, setLocal] = useState(policy);
  useEffect(() => setLocal(policy), [policy]);
  const dirty = local.retention_days !== policy.retention_days || local.enabled !== policy.enabled || local.description !== policy.description;
  return (
    <div className="grid grid-cols-12 gap-2 px-4 py-2 border-b border-slate-800/40 text-[11px] items-center">
      <div className="col-span-4 font-mono text-slate-300">{policy.source_table}</div>
      <div className="col-span-2">
        <input
          type="number" min={1} max={3650}
          aria-label={`Retention days for ${policy.source_table}`}
          data-testid={`retention-days-${policy.source_table}`}
          value={local.retention_days}
          onChange={(e) => setLocal({ ...local, retention_days: parseInt(e.target.value || '30') })}
          className="w-20 px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs text-white"
        />
      </div>
      <div className="col-span-2">
        <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-300">
          <input type="checkbox" aria-label={`Archive ${policy.source_table} nightly`} checked={local.enabled} onChange={(e) => setLocal({ ...local, enabled: e.target.checked })} />
          {local.enabled ? 'on' : 'off'}
        </label>
      </div>
      <div className="col-span-3">
        <input
          type="text"
          value={local.description || ''}
          onChange={(e) => setLocal({ ...local, description: e.target.value })}
          placeholder="optional"
          className="w-full px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs text-white"
        />
      </div>
      <div className="col-span-1 flex justify-end">
        <button
          disabled={!dirty || saving}
          onClick={() => onSave(local)}
          className="p-1 rounded text-emerald-400 hover:bg-emerald-500/10 disabled:opacity-30"
          aria-label={`Save ${policy.source_table}`}
          data-testid={`retention-save-${policy.source_table}`}
          title="Save"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
}

function RunRow({ run }: { run: ArchiveRun }) {
  const [downloading, setDownloading] = useState(false);
  const [downloadErr, setDownloadErr] = useState<string | null>(null);
  const onDownload = async () => {
    setDownloading(true);
    setDownloadErr(null);
    const err = await downloadArchive(run).catch((e: unknown) => (e instanceof Error ? e.message : 'Download failed'));
    if (err) setDownloadErr(err);
    setDownloading(false);
  };
  const StatusIcon = run.status === 'completed' ? CheckCircle2 :
                     run.status === 'failed' ? XCircle :
                     Clock;
  const color = run.status === 'completed' ? 'text-emerald-400' :
                run.status === 'failed' ? 'text-rose-400' :
                'text-amber-400';
  return (
    <div className="px-4 py-3 border-b border-slate-800/40 text-[11px]">
      <div className="flex items-center gap-3">
        <StatusIcon className={`w-4 h-4 ${color}`} />
        <span className="font-mono text-slate-300">{run.source_table}</span>
        <span className="text-slate-500">{fmtDate(run.started_at)}</span>
        {run.is_manual && <span className="text-[9px] uppercase tracking-wider text-cyan-400 bg-cyan-500/10 px-1.5 py-0.5 rounded">manual</span>}
        <span className="ml-auto flex items-center gap-3">
          <span className="text-emerald-300 font-mono">{run.rows_archived.toLocaleString()} archived</span>
          <span className="text-rose-300 font-mono">{run.rows_deleted.toLocaleString()} deleted</span>
          <span className="text-slate-400 font-mono">{fmtBytes(run.file_size_bytes)}</span>
          {run.file_uri && (
            <button
              type="button"
              onClick={onDownload}
              disabled={downloading}
              className="text-cyan-400 hover:underline flex items-center gap-1 disabled:opacity-50"
              data-testid={`archive-download-${run.id}`}
            >
              {downloading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />} dump
            </button>
          )}
        </span>
      </div>
      {downloadErr && (
        <p className="mt-1 ml-7 text-[10px] text-rose-300">{downloadErr}</p>
      )}
      {run.error_message && (
        <pre className="mt-2 ml-7 text-rose-200 bg-rose-500/10 border border-rose-500/30 rounded p-2 text-[10px] whitespace-pre-wrap max-h-24 overflow-auto">{run.error_message}</pre>
      )}
      {run.file_sha256 && (
        <div className="ml-7 mt-1 text-[9px] text-slate-600 font-mono">sha256: {run.file_sha256}</div>
      )}
    </div>
  );
}

export default function AdminArchivesPageGated() {
  return (
    <AccessGate
      title="Archives"
      purpose="Decide how long run and activity records stay in the live database and download the old ones once they are archived. For admins."
      icon={Archive}
      need={{ admin: true }}
      instead={{ text: 'You can follow your own runs and how long they take on Executions.', href: '/executions', label: 'Open Executions' }}
    >
      <AdminArchivesPage />
    </AccessGate>
  );
}
