'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  AlertTriangle, FileDiff, Globe, Loader2, PauseCircle, PlayCircle, Plus, Radar, RefreshCw, Search, ShieldCheck, X,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import {
  HEALTH_STYLE, HINT_STYLE, KIND_LABEL, ago, cadenceLabel, describeOutcome, when,
  type ChangeSummary, type CheckOutcome, type Health, type Source, type SourceSettings,
} from '@/lib/sources';
import SourceForm from '@/components/sources/SourceForm';
import SourceSettingsDialog from '@/components/sources/SourceSettingsDialog';
import PauseDialog from '@/components/sources/PauseDialog';
import { refreshSourceList } from '@/components/sources/refreshSourceList';
import PageHeader from '@/components/layout/PageHeader';

type Filter = 'all' | Health;

export default function SourcesPage() {
  const router = useRouter();
  const { perms } = useMyPermissions();
  const canManage = holds(perms?.capabilities, 'sources.manage');
  const canSettings = holds(perms?.capabilities, 'risk.manage');
  const { data, error, isLoading, mutate } = useApi<Source[]>('/api/sources', { refreshInterval: 30000 });
  const { data: changes, mutate: refreshChanges } = useApi<ChangeSummary[]>('/api/sources/changes?limit=12', { refreshInterval: 60000 });
  const { data: settings, mutate: refreshSettings } = useApi<SourceSettings>('/api/sources/settings');
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [adding, setAdding] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [pausing, setPausing] = useState<Source | null>(null);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'change' | 'bad'; text: string; href?: string } | null>(null);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data || []).filter(
      (s) =>
        (filter === 'all' || s.health === filter) &&
        (!needle ||
          s.name.toLowerCase().includes(needle) ||
          s.url.toLowerCase().includes(needle) ||
          (s.jurisdiction || '').toLowerCase().includes(needle) ||
          s.tags.some((t) => t.toLowerCase().includes(needle))),
    );
  }, [data, q, filter]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, ok: 0, new: 0, failing: 0, paused: 0, stopped: 0 };
    for (const s of data || []) {
      c.all++;
      c[s.health]++;
    }
    return c;
  }, [data]);
  const weekAgo = Date.now() - 7 * 86400 * 1000;
  const changedThisWeek = (data || []).filter((s) => s.last_changed_at && new Date(s.last_changed_at).getTime() > weekAgo).length;

  async function checkNow(s: Source) {
    setBusy((b) => ({ ...b, [s.id]: 'check' }));
    setNotice(null);
    const r = await apiFetch<{ outcome: CheckOutcome; source: Source }>(`/api/sources/${s.id}/check-now`, { method: 'POST', throwOnError: false });
    setBusy((b) => {
      const n = { ...b };
      delete n[s.id];
      return n;
    });
    if (r.error || !r.data) setNotice({ tone: 'bad', text: `${s.name}: ${r.error || 'the check failed.'}` });
    else {
      const d = describeOutcome(r.data.outcome);
      setNotice({ ...d, text: `${s.name}: ${d.text}`, href: r.data.outcome.change_id ? `/sources/${s.id}?change=${r.data.outcome.change_id}` : undefined });
    }
    mutate();
    refreshChanges();
  }

  async function setActive(s: Source, active: boolean, reason = '') {
    setBusy((b) => ({ ...b, [s.id]: active ? 'resume' : 'pause' }));
    const r = await apiFetch<Source>(`/api/sources/${s.id}/${active ? 'resume' : 'pause'}`, {
      method: 'POST',
      body: active ? undefined : JSON.stringify({ reason }),
      throwOnError: false,
    });
    setBusy((b) => {
      const n = { ...b };
      delete n[s.id];
      return n;
    });
    setPausing(null);
    if (r.error) setNotice({ tone: 'bad', text: r.error });
    else setNotice({ tone: 'ok', text: active ? `${s.name} resumed. It is checked within a minute.` : `${s.name} paused.` });
    mutate();
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      <PageHeader
        className="mb-6"
        title="Source Watch"
        purpose="Watch the policy pages, documents and feeds your work depends on, and see exactly what changed and when. For compliance and research teams."
        icon={Radar}
        storageKey="sources"
        docSlug="08-howto/12-source-watch-and-events"
        steps={[
          'Add a page, PDF, spreadsheet or feed and say how often to check it.',
          'Each check keeps a copy that never changes. The first one is the baseline.',
          'When something changes you see a side by side diff and an event is sent.',
          'Agents can read and quote these copies, and events can start a pipeline.',
        ]}
        primaryAction={canManage
          ? { label: 'Add source', icon: Plus, onClick: () => setAdding(true), testId: 'source-add' }
          : { label: 'Refresh', icon: RefreshCw, onClick: () => { mutate(); refreshChanges(); } }}
        secondaryAction={settings
          ? { label: 'Allowlist and limits', icon: ShieldCheck, onClick: () => setShowSettings(true), testId: 'sources-settings' }
          : undefined}
      />

      {notice && (
        <div
          role="status"
          className={`mb-4 flex items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${
            notice.tone === 'bad' ? 'border-rose-500/30 bg-rose-500/5 text-rose-200' : notice.tone === 'change' ? 'border-amber-500/30 bg-amber-500/5 text-amber-100' : 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200'
          }`}
          data-testid="sources-notice"
        >
          <span>
            {notice.text}{' '}
            {notice.href && <Link href={notice.href} className="underline font-medium">See the diff</Link>}
          </span>
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss" className="opacity-70 hover:opacity-100"><X className="w-4 h-4" /></button>
        </div>
      )}

      {(data || []).length > 0 && (
        <div className="grid gap-3 grid-cols-2 md:grid-cols-4 mb-6">
          {[
            { label: 'Watching', value: counts.ok + counts.new, tone: 'text-emerald-300' },
            { label: 'Changed in the last 7 days', value: changedThisWeek, tone: 'text-amber-300' },
            { label: 'Failing', value: counts.failing, tone: counts.failing ? 'text-amber-300' : 'text-slate-300' },
            { label: 'Paused or stopped', value: counts.paused + counts.stopped, tone: 'text-slate-300' },
          ].map((t) => (
            <div key={t.label} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <div className={`text-2xl font-semibold ${t.tone}`}>{t.value}</div>
              <div className="text-xs text-slate-400 mt-1">{t.label}</div>
            </div>
          ))}
        </div>
      )}

      {(data || []).length > 0 && (
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3 flex-1 min-w-[240px] max-w-md">
            <Search className="w-4 h-4 text-slate-500" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, address, jurisdiction or tag…" className="flex-1 bg-transparent py-2 text-sm text-white outline-none" aria-label="Search sources" />
          </div>
          <div className="inline-flex flex-wrap rounded-lg border border-slate-700 p-0.5 bg-slate-950" role="radiogroup" aria-label="Filter by status">
            {(['all', 'ok', 'new', 'failing', 'paused', 'stopped'] as Filter[]).map((f) =>
              f !== 'all' && f !== 'ok' && counts[f] === 0 ? null : (
                <button key={f} type="button" role="radio" aria-checked={filter === f} onClick={() => setFilter(f)} className={`px-3 py-1.5 text-xs rounded-md ${filter === f ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>
                  {f === 'all' ? 'All' : HEALTH_STYLE[f].label} <span className="text-slate-500">{counts[f]}</span>
                </button>
              ),
            )}
          </div>
        </div>
      )}

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200 flex items-center justify-between gap-3">
          <span>Could not load sources: {error}</span>
          <button type="button" onClick={() => mutate()} className="inline-flex items-center gap-1.5 text-rose-100 underline"><RefreshCw className="w-4 h-4" /> Try again</button>
        </div>
      ) : isLoading && !data ? (
        <div className="space-y-2" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="h-16 rounded-xl bg-slate-800/40 animate-pulse" />)}</div>
      ) : (data || []).length === 0 ? (
        <EmptyState canManage={canManage} onAdd={() => setAdding(true)} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500 py-6">No source matches. <button type="button" className="underline" onClick={() => { setQ(''); setFilter('all'); }}>Clear the search</button></p>
      ) : (
        <div className="rounded-xl border border-slate-800 overflow-x-auto" data-testid="source-list">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-900/70 text-xs text-slate-400 text-left">
              <tr>
                <th className="px-4 py-2.5 font-medium">Source</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 font-medium">Last checked</th>
                <th className="px-3 py-2.5 font-medium">Last changed</th>
                <th className="px-3 py-2.5 font-medium text-right">Failures</th>
                {canManage && <th className="px-3 py-2.5 font-medium text-right">Actions</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map((s) => {
                const hs = HEALTH_STYLE[s.health];
                const b = busy[s.id];
                return (
                  <tr key={s.id} className="hover:bg-slate-900/40 cursor-pointer" onClick={() => router.push(`/sources/${s.id}`)} data-testid={`source-row-${s.name}`}>
                    <td className="px-4 py-3 max-w-[360px]">
                      <Link href={`/sources/${s.id}`} className="font-medium text-white hover:text-cyan-300" onClick={(e) => e.stopPropagation()}>{s.name}</Link>
                      <div className="flex flex-wrap items-center gap-1.5 mt-0.5 text-xs text-slate-500">
                        <Globe className="w-3 h-3" /> <span className="truncate max-w-[200px]">{s.host}</span>
                        <span className="px-1.5 rounded border border-slate-700 text-slate-400">{KIND_LABEL[s.kind]}</span>
                        <span>{cadenceLabel(s.cadence_minutes).toLowerCase()}</span>
                        {s.jurisdiction && <span className="px-1.5 rounded bg-slate-800 text-slate-300">{s.jurisdiction}</span>}
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border ${hs.chip}`} title={s.paused_reason || s.last_error || undefined} data-testid="source-health">
                        <span className={`w-1.5 h-1.5 rounded-full ${hs.dot}`} /> {hs.label}
                      </span>
                      {(s.health === 'failing' || s.health === 'paused') && (s.last_error || s.paused_reason) && (
                        <div className="text-[11px] text-slate-500 mt-1 max-w-[220px] truncate">{s.paused_reason || s.last_error}</div>
                      )}
                    </td>
                    <td className="px-3 py-3 text-slate-300 whitespace-nowrap" title={when(s.last_checked_at)}>
                      {ago(s.last_checked_at)}
                      {s.active && s.next_check_at && <div className="text-[11px] text-slate-500">next {ago(s.next_check_at)}</div>}
                    </td>
                    <td className="px-3 py-3 max-w-[300px]">
                      {s.last_changed_at ? (
                        <>
                          <span className="text-slate-300 whitespace-nowrap" title={when(s.last_changed_at)}>{ago(s.last_changed_at)}</span>
                          {s.latest_change && (
                            <span className={`ml-2 text-[11px] px-1.5 py-0.5 rounded border ${HINT_STYLE[s.latest_change.materiality_hint].chip}`}>{HINT_STYLE[s.latest_change.materiality_hint].label}</span>
                          )}
                          {s.latest_change && <div className="text-[11px] text-slate-500 truncate">{s.latest_change.summary}</div>}
                        </>
                      ) : (
                        <span className="text-slate-500">{s.snapshot_count ? 'No change yet' : 'No snapshot yet'}</span>
                      )}
                    </td>
                    <td className={`px-3 py-3 text-right tabular-nums ${s.consecutive_failures ? 'text-amber-300' : 'text-slate-500'}`}>{s.consecutive_failures}</td>
                    {canManage && (
                      <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          <button type="button" onClick={() => checkNow(s)} disabled={!!b} title={s.health === 'stopped' ? 'A kill switch stopped the last check. Check again once it is cleared.' : 'Check now'} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40" data-testid={`source-check-${s.name}`}>
                            {b === 'check' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />} Check now
                          </button>
                          {s.active ? (
                            <button type="button" onClick={() => setPausing(s)} disabled={!!b} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40">
                              <PauseCircle className="w-3.5 h-3.5" /> Pause
                            </button>
                          ) : (
                            <button type="button" onClick={() => setActive(s, true)} disabled={!!b} className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-emerald-300 hover:bg-slate-800 disabled:opacity-40">
                              {b === 'resume' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />} Resume
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(changes || []).length > 0 && (
        <section className="mt-8" aria-labelledby="recent-changes">
          <h2 id="recent-changes" className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><FileDiff className="w-4 h-4 text-cyan-400" /> Recent changes</h2>
          <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {(changes || []).map((c) => (
              <li key={c.id} className="min-w-0">
                <Link href={`/sources/${c.source_id}?change=${c.id}`} className="block rounded-xl border border-slate-800 bg-slate-900/40 p-3 hover:border-slate-600">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 text-sm font-medium text-white truncate">{c.source_name}</span>
                    <span className={`shrink-0 text-[11px] px-1.5 py-0.5 rounded border ${HINT_STYLE[c.materiality_hint].chip}`}>{HINT_STYLE[c.materiality_hint].label}</span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1 line-clamp-2 break-words">{c.summary}</p>
                  <div className="text-[11px] text-slate-500 mt-1" title={when(c.detected_at)}>{ago(c.detected_at)}</div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {adding && (
        <SourceForm
          onClose={() => setAdding(false)}
          onSaved={async (s) => {
            setAdding(false);
            // refresh the cached list now so going back shows the new source
            await refreshSourceList();
            router.push(`/sources/${s.id}?new=1`);
          }}
        />
      )}
      {showSettings && settings && (
        <SourceSettingsDialog
          settings={settings}
          canEdit={canSettings}
          onClose={() => setShowSettings(false)}
          onSaved={() => {
            setShowSettings(false);
            refreshSettings();
            setNotice({ tone: 'ok', text: 'Source Watch settings saved.' });
          }}
        />
      )}
      {pausing && <PauseDialog name={pausing.name} busy={busy[pausing.id] === 'pause'} onClose={() => setPausing(null)} onConfirm={(r) => setActive(pausing, false, r)} />}
    </div>
  );
}

function EmptyState({ canManage, onAdd }: { canManage: boolean; onAdd: () => void }) {
  const examples = [
    { title: 'A policy or tariff page', text: 'Guidance or a notice page. Narrow it to the main content so menus and dates do not count as changes.' },
    { title: 'A PDF or spreadsheet', text: 'Default values, tariff tables or published lists. Tables are compared row by row.' },
    { title: 'A feed or JSON API', text: 'An RSS or Atom feed, or a JSON document, compared item by item or field by field.' },
  ];
  return (
    <div className="rounded-2xl border border-dashed border-slate-700 p-8" data-testid="sources-empty">
      <h2 className="text-lg font-semibold text-white">Nothing is being watched yet</h2>
      <p className="text-sm text-slate-400 mt-1 max-w-2xl">
        Add the authoritative sources your work depends on. Each check keeps an immutable snapshot, compares it with the
        last one and raises a source.changed event that can start a pipeline or notify a reviewer.
      </p>
      <div className="grid gap-3 md:grid-cols-3 mt-5">
        {examples.map((e) => (
          <div key={e.title} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <div className="text-sm font-medium text-white">{e.title}</div>
            <div className="text-xs text-slate-400 mt-1">{e.text}</div>
          </div>
        ))}
      </div>
      {canManage ? (
        <button type="button" onClick={onAdd} className="mt-5 inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400" data-testid="source-add-empty">
          <Plus className="w-4 h-4" /> Add your first source
        </button>
      ) : (
        <p className="text-xs text-slate-500 mt-4 flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5" /> Adding sources needs Manage sources, which an admin can give you.</p>
      )}
    </div>
  );
}
