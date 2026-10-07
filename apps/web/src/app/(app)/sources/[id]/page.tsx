'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import {
  AlertTriangle, ArrowLeft, Database, Download, ExternalLink, FileDiff, FileText, History, Loader2, OctagonX,
  PauseCircle, Pencil, PlayCircle, Radar, RefreshCw, Trash2, X,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { TIER_STYLE } from '@/components/governance/TierPolicies';
import ConfirmModal from '@/components/ui/ConfirmModal';
import DiffView from '@/components/sources/DiffView';
import SourceForm from '@/components/sources/SourceForm';
import PauseDialog from '@/components/sources/PauseDialog';
import SnapshotViewer from '@/components/sources/SnapshotViewer';
import { refreshSourceList } from '@/components/sources/refreshSourceList';
import {
  HEALTH_STYLE, HINT_STYLE, KIND_LABEL, STATUS_TEXT, ago, bytes, cadenceLabel, describeOutcome, downloadRaw, when,
  type ChangeDetail, type ChangeSummary, type CheckOutcome, type Snapshot, type Source,
} from '@/lib/sources';

type Tab = 'changes' | 'snapshots';

function pausedText(reason: string | null | undefined): string {
  const r = (reason || '').trim();
  if (!r) return 'Paused.';
  return /[.!?]$/.test(r) ? `Paused: ${r}` : `Paused: ${r}.`;
}

function Stat({ label, value, title }: { label: string; value: ReactNode; title?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3" title={title}>
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-sm text-slate-200 mt-1">{value}</div>
    </div>
  );
}

function stats(c: ChangeSummary): string {
  const s = c.stats || {};
  if ('rows_added' in s) {
    const parts = [];
    if (s.rows_added) parts.push(`+${s.rows_added} rows`);
    if (s.rows_removed) parts.push(`−${s.rows_removed} rows`);
    if (s.rows_changed) parts.push(`~${s.rows_changed} rows`);
    return parts.join(' ');
  }
  return `+${s.added ?? 0} −${s.removed ?? 0}`;
}

export default function SourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const { perms } = useMyPermissions();
  const canManage = holds(perms?.capabilities, 'sources.manage');
  const { data: source, error, isLoading, mutate } = useApi<Source>(`/api/sources/${id}`, { refreshInterval: 30000 });
  const { data: changes, isLoading: changesLoading, mutate: refreshChanges } = useApi<ChangeSummary[]>(`/api/sources/${id}/changes`);
  const { data: snapshots, isLoading: snapsLoading, mutate: refreshSnaps } = useApi<Snapshot[]>(`/api/sources/${id}/snapshots`);
  const [tab, setTab] = useState<Tab>(search.get('snapshot') ? 'snapshots' : 'changes');
  const [changeId, setChangeId] = useState<string | null>(search.get('change'));
  const [snapshotId, setSnapshotId] = useState<string | null>(search.get('snapshot'));
  const [detail, setDetail] = useState<ChangeDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'change' | 'bad'; text: string; changeId?: string } | null>(null);
  const [editing, setEditing] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const syncUrl = useCallback(
    (params: Record<string, string | null>) => {
      const sp = new URLSearchParams(window.location.search);
      for (const [k, v] of Object.entries(params)) {
        if (v) sp.set(k, v);
        else sp.delete(k);
      }
      const qs = sp.toString();
      window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
    },
    [],
  );

  useEffect(() => {
    if (!changeId && changes && changes.length && tab === 'changes') setChangeId(changes[0].id);
  }, [changes, changeId, tab]);

  useEffect(() => {
    if (!changeId) {
      setDetail(null);
      return;
    }
    let live = true;
    setDetail(null);
    setDetailErr(null);
    apiFetch<ChangeDetail>(`/api/sources/changes/${changeId}`, { throwOnError: false }).then((r) => {
      if (!live) return;
      if (r.error || !r.data) setDetailErr(r.error || 'Could not load the change.');
      else setDetail(r.data);
    });
    return () => {
      live = false;
    };
  }, [changeId]);

  function pickChange(cid: string) {
    setChangeId(cid);
    syncUrl({ change: cid });
  }

  function openSnapshot(sid: string | null) {
    setSnapshotId(sid);
    syncUrl({ snapshot: sid });
  }

  function refreshAll() {
    mutate();
    void refreshSourceList();
    refreshChanges();
    refreshSnaps();
  }

  async function checkNow() {
    setBusy('check');
    setNotice(null);
    const r = await apiFetch<{ outcome: CheckOutcome; source: Source }>(`/api/sources/${id}/check-now`, { method: 'POST', throwOnError: false });
    setBusy(null);
    if (r.error || !r.data) setNotice({ tone: 'bad', text: r.error || 'The check failed.' });
    else {
      const d = describeOutcome(r.data.outcome);
      setNotice({ ...d, changeId: r.data.outcome.change_id });
      if (r.data.outcome.change_id) {
        setTab('changes');
        pickChange(r.data.outcome.change_id);
      }
      if (r.data.outcome.kb_error) setNotice({ tone: 'bad', text: `${d.text} Adding it to the knowledge base failed: ${r.data.outcome.kb_error}` });
    }
    refreshAll();
  }

  async function setActive(active: boolean, reason = '') {
    setBusy(active ? 'resume' : 'pause');
    const r = await apiFetch<Source>(`/api/sources/${id}/${active ? 'resume' : 'pause'}`, {
      method: 'POST',
      body: active ? undefined : JSON.stringify({ reason }),
      throwOnError: false,
    });
    setBusy(null);
    setPausing(false);
    if (r.error) setNotice({ tone: 'bad', text: r.error });
    else setNotice({ tone: 'ok', text: active ? 'Resumed. The next check runs within a minute.' : 'Paused. Scheduled checks are off until you resume.' });
    mutate();
    void refreshSourceList();
  }

  async function remove() {
    setBusy('delete');
    const r = await apiFetch(`/api/sources/${id}`, { method: 'DELETE', throwOnError: false });
    setBusy(null);
    if (r.error) {
      setDeleting(false);
      setNotice({ tone: 'bad', text: r.error });
    } else {
      await refreshSourceList();
      router.push('/sources');
    }
  }

  if (error) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 text-center">
        <Radar className="w-10 h-10 text-slate-500 mx-auto mb-3" />
        <h1 className="text-xl font-semibold text-white">Source not available</h1>
        <p className="text-slate-400 mt-2">{error}</p>
        <Link href="/sources" className="mt-4 inline-flex items-center gap-1.5 text-cyan-300 hover:underline"><ArrowLeft className="w-4 h-4" /> Back to Source Watch</Link>
      </div>
    );
  }
  if (isLoading && !source) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-4" aria-busy="true">
        <div className="h-10 w-80 rounded bg-slate-800/50 animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{[0, 1, 2, 3].map((i) => <div key={i} className="h-16 rounded-xl bg-slate-800/40 animate-pulse" />)}</div>
        <div className="h-80 rounded-xl bg-slate-800/40 animate-pulse" />
      </div>
    );
  }
  if (!source) return null;

  const hs = HEALTH_STYLE[source.health];
  const baseline = (snapshots || []).length ? (snapshots || [])[(snapshots || []).length - 1] : null;

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <Link href="/sources" className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white mb-4"><ArrowLeft className="w-4 h-4" /> Source Watch</Link>

      <header className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold text-white" data-testid="source-title">{source.name}</h1>
            <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border ${hs.chip}`} data-testid="source-detail-health"><span className={`w-1.5 h-1.5 rounded-full ${hs.dot}`} /> {hs.label}</span>
            <span className={`text-[11px] px-1.5 py-0.5 rounded border ${TIER_STYLE[source.risk_tier]?.chip}`}>{TIER_STYLE[source.risk_tier]?.label} risk</span>
          </div>
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-sm text-cyan-300 hover:underline break-all">
            {source.url} <ExternalLink className="w-3.5 h-3.5 shrink-0" />
          </a>
          <div className="flex flex-wrap items-center gap-1.5 mt-2 text-xs text-slate-400">
            <span className="px-1.5 py-0.5 rounded border border-slate-700">{KIND_LABEL[source.kind]}</span>
            <span>{cadenceLabel(source.cadence_minutes)}</span>
            {source.selector && <span className="font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300" title="Only this part is watched">{source.selector}</span>}
            {source.jurisdiction && <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">{source.jurisdiction}</span>}
            {source.tags.map((t) => <span key={t} className="px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-400">#{t}</span>)}
          </div>
          {source.description && <p className="text-sm text-slate-400 mt-2 max-w-3xl">{source.description}</p>}
        </div>
        {canManage && (
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={checkNow} disabled={!!busy} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="source-check-now">
              {busy === 'check' ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} {busy === 'check' ? 'Checking…' : 'Check now'}
            </button>
            {source.active ? (
              <button type="button" onClick={() => setPausing(true)} disabled={!!busy} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm text-slate-200 border border-slate-700 hover:bg-slate-800 disabled:opacity-40" data-testid="source-pause">
                <PauseCircle className="w-4 h-4" /> Pause
              </button>
            ) : (
              <button type="button" onClick={() => setActive(true)} disabled={!!busy} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm text-emerald-200 border border-emerald-500/40 hover:bg-emerald-500/10 disabled:opacity-40" data-testid="source-resume">
                {busy === 'resume' ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />} Resume
              </button>
            )}
            <button type="button" onClick={() => setEditing(true)} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm text-slate-200 border border-slate-700 hover:bg-slate-800" data-testid="source-edit">
              <Pencil className="w-4 h-4" /> Edit
            </button>
            <button type="button" onClick={() => setDeleting(true)} aria-label="Delete source" className="p-2 rounded-md text-slate-400 border border-slate-700 hover:text-rose-300 hover:border-rose-500/40">
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        )}
      </header>

      {notice && (
        <div role="status" className={`mb-4 flex items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${notice.tone === 'bad' ? 'border-rose-500/30 bg-rose-500/5 text-rose-200' : notice.tone === 'change' ? 'border-amber-500/30 bg-amber-500/5 text-amber-100' : 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200'}`} data-testid="source-notice">
          <span>{notice.text}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss" className="opacity-70 hover:opacity-100"><X className="w-4 h-4" /></button>
        </div>
      )}
      {source.health === 'stopped' && (
        <div className="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/5 px-4 py-3 text-sm text-rose-200 flex items-start gap-2">
          <OctagonX className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{source.last_error || 'A kill switch stops this source.'} <Link href="/admin/risk#switches" className="underline">Kill switches</Link></span>
        </div>
      )}
      {!source.active && source.health !== 'stopped' && (
        <div className="mb-4 rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-3 text-sm text-slate-300 flex items-start gap-2">
          <PauseCircle className="w-4 h-4 mt-0.5 shrink-0 text-amber-300" />
          <span>{pausedText(source.paused_reason)} Scheduled checks are off.{canManage ? ' Resume it when the source is ready to be checked again.' : ''}</span>
        </div>
      )}
      {source.active && source.consecutive_failures > 0 && (
        <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-100 flex items-start gap-2" data-testid="source-failing">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>The last {source.consecutive_failures} check{source.consecutive_failures === 1 ? '' : 's'} failed: {source.last_error}</span>
        </div>
      )}

      <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6 mb-6">
        <Stat label="Last checked" value={<>{ago(source.last_checked_at)}{source.last_status && <div className="text-[11px] text-slate-500">{STATUS_TEXT[source.last_status] || source.last_status}</div>}</>} title={when(source.last_checked_at)} />
        <Stat label="Next check" value={source.active ? ago(source.next_check_at) : 'paused'} title={when(source.next_check_at)} />
        <Stat label="Last changed" value={source.last_changed_at ? ago(source.last_changed_at) : 'not yet'} title={when(source.last_changed_at)} />
        <Stat label="Snapshots" value={source.snapshot_count ?? 0} />
        <Stat label="Changes" value={source.change_count ?? 0} />
        <Stat
          label="Knowledge base"
          value={source.ingest_to_kb ? <span className="inline-flex items-center gap-1"><Database className="w-3.5 h-3.5 text-cyan-300" /> {source.kb_name || 'linked'}</span> : <span className="text-slate-500">not linked</span>}
        />
      </div>

      <div className="flex gap-1 border-b border-slate-800 mb-4" role="tablist" aria-label="Source history">
        {([['changes', 'Changes', FileDiff, source.change_count], ['snapshots', 'Snapshot timeline', History, source.snapshot_count]] as const).map(([t, label, Icon, n]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px transition ${tab === t ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'}`} data-testid={`source-tab-${t}`}>
            <Icon className="w-4 h-4" /> {label} <span className="text-slate-500">{n ?? 0}</span>
          </button>
        ))}
      </div>

      {tab === 'changes' ? (
        changesLoading && !changes ? (
          <div className="h-64 rounded-xl bg-slate-800/40 animate-pulse" />
        ) : !(changes || []).length ? (
          <div className="rounded-2xl border border-dashed border-slate-700 p-8 text-center" data-testid="changes-empty">
            <FileDiff className="w-8 h-8 text-slate-500 mx-auto mb-2" />
            <h2 className="text-base font-semibold text-white">No changes detected</h2>
            <p className="text-sm text-slate-400 mt-1 max-w-xl mx-auto">
              {baseline
                ? `The baseline was captured ${ago(baseline.fetched_at)}. Every later check is compared with the latest snapshot, and a change shows up here with a diff.`
                : source.last_error
                  ? `No snapshot yet, the first check failed: ${source.last_error}`
                  : 'No snapshot yet. The first check captures a baseline, usually within a minute of adding the source.'}
            </p>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
            <ul className="space-y-1.5 lg:max-h-[70vh] lg:overflow-y-auto pr-1" aria-label="Changes" data-testid="change-list">
              {(changes || []).map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => pickChange(c.id)} aria-current={changeId === c.id} className={`w-full text-left rounded-xl border p-3 transition ${changeId === c.id ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-slate-800 bg-slate-900/40 hover:border-slate-600'}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-slate-300" title={when(c.detected_at)}>{when(c.detected_at)}</span>
                      <span className={`text-[11px] px-1.5 py-0.5 rounded border ${HINT_STYLE[c.materiality_hint].chip}`}>{HINT_STYLE[c.materiality_hint].label}</span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1 line-clamp-2">{c.summary}</p>
                    <div className="text-[11px] font-mono text-slate-500 mt-1">{stats(c)}</div>
                  </button>
                </li>
              ))}
            </ul>
            <div className="min-w-0" data-testid="change-detail">
              {detailErr ? (
                <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">{detailErr}</div>
              ) : !detail ? (
                <div className="h-64 rounded-xl bg-slate-800/40 animate-pulse" />
              ) : (
                <div>
                  <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 mb-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-medium text-white">{detail.summary}</div>
                      <span className={`text-[11px] px-1.5 py-0.5 rounded border ${HINT_STYLE[detail.materiality_hint].chip}`} title="A first sort by size and wording, not a judgement">{HINT_STYLE[detail.materiality_hint].label}</span>
                    </div>
                    <div className="grid sm:grid-cols-2 gap-2 mt-3 text-xs">
                      {[['Before', detail.from_snapshot], ['After', detail.to_snapshot]].map(([label, s]) => {
                        const snap = s as Snapshot | null;
                        return (
                          <div key={label as string} className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
                            <div className="text-slate-500">{label as string}</div>
                            {snap ? (
                              <>
                                <div className="text-slate-200">{when(snap.fetched_at)}</div>
                                <div className="font-mono text-slate-500 truncate" title={snap.content_sha256}>sha256 {snap.content_sha256.slice(0, 16)}…</div>
                                <div className="flex gap-3 mt-1">
                                  <button type="button" onClick={() => openSnapshot(snap.id)} className="text-cyan-300 hover:underline inline-flex items-center gap-1"><FileText className="w-3 h-3" /> Text</button>
                                  <button type="button" onClick={async () => { const e = await downloadRaw(snap.id); if (e) setNotice({ tone: 'bad', text: e }); }} className="text-cyan-300 hover:underline inline-flex items-center gap-1"><Download className="w-3 h-3" /> Original</button>
                                </div>
                              </>
                            ) : (
                              <div className="text-slate-500">no longer kept</div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <DiffView diff={detail.diff} />
                </div>
              )}
            </div>
          </div>
        )
      ) : snapsLoading && !snapshots ? (
        <div className="h-64 rounded-xl bg-slate-800/40 animate-pulse" />
      ) : !(snapshots || []).length ? (
        <div className="rounded-2xl border border-dashed border-slate-700 p-8 text-center" data-testid="snapshots-empty">
          <History className="w-8 h-8 text-slate-500 mx-auto mb-2" />
          <h2 className="text-base font-semibold text-white">No snapshots yet</h2>
          <p className="text-sm text-slate-400 mt-1">{source.last_error ? `The last check failed: ${source.last_error}` : 'The first check captures the baseline snapshot.'}</p>
        </div>
      ) : (
        <ol className="relative border-l border-slate-800 ml-3 space-y-4" data-testid="snapshot-timeline">
          {(snapshots || []).map((s) => {
            const kind = s.change ? 'changed' : 'baseline';
            return (
              <li key={s.id} className="ml-5">
                <span className={`absolute -left-[7px] mt-1.5 w-3.5 h-3.5 rounded-full border-2 border-slate-950 ${s.change ? 'bg-amber-400' : 'bg-cyan-400'}`} aria-hidden />
                <div className={`rounded-xl border p-3 ${s.current ? 'border-cyan-500/40 bg-cyan-500/5' : 'border-slate-800 bg-slate-900/40'}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-white">{when(s.fetched_at)}</span>
                    {s.current && <span className="text-[11px] px-1.5 py-0.5 rounded border border-cyan-500/40 text-cyan-200">Current</span>}
                    <span className={`text-[11px] px-1.5 py-0.5 rounded border ${kind === 'changed' ? 'border-amber-500/30 text-amber-300' : 'border-slate-700 text-slate-400'}`}>{kind === 'changed' ? 'Change' : 'Baseline'}</span>
                    <span className="text-xs text-slate-500">{ago(s.fetched_at)}</span>
                  </div>
                  {s.title && <div className="text-sm text-slate-300 mt-1">{s.title}</div>}
                  {s.change && (
                    <button type="button" onClick={() => { setTab('changes'); pickChange(s.change!.id); }} className="text-xs text-amber-200 hover:underline mt-1 text-left">{s.change.summary}</button>
                  )}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[11px] text-slate-500">
                    <span className="font-mono" title={s.content_sha256}>sha256 {s.content_sha256.slice(0, 12)}…</span>
                    <span>HTTP {s.http_status}</span>
                    <span>{bytes(s.bytes)}</span>
                    <span>{(s.text_chars || 0).toLocaleString()} characters</span>
                    <span>reader {s.parser_version}</span>
                    <button type="button" onClick={() => openSnapshot(s.id)} className="text-cyan-300 hover:underline inline-flex items-center gap-1" data-testid="snapshot-view"><FileText className="w-3 h-3" /> View text</button>
                    <button type="button" onClick={async () => { const e = await downloadRaw(s.id); if (e) setNotice({ tone: 'bad', text: e }); }} className="text-cyan-300 hover:underline inline-flex items-center gap-1"><Download className="w-3 h-3" /> Original</button>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {snapshotId && <SnapshotViewer id={snapshotId} onClose={() => openSnapshot(null)} />}
      {editing && (
        <SourceForm
          initial={source}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            setNotice({ tone: 'ok', text: 'Saved. If the address or what is watched changed, the next check runs within a minute.' });
            refreshAll();
          }}
        />
      )}
      {pausing && <PauseDialog name={source.name} busy={busy === 'pause'} onClose={() => setPausing(false)} onConfirm={(r) => setActive(false, r)} />}
      <ConfirmModal
        open={deleting}
        onClose={() => setDeleting(false)}
        onConfirm={remove}
        loading={busy === 'delete'}
        title={`Delete ${source.name}?`}
        description="This stops watching it and deletes its snapshots and change history. Events already sent are not affected. This cannot be undone."
        confirmLabel="Delete source"
      />
    </div>
  );
}
