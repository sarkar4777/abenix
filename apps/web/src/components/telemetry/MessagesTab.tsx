'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Inbox, Loader2, Pause, Play, RotateCcw, Shuffle, Trash2 } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { explainTelemetryError } from '@/lib/telemetry/errors';
import { clock, toMs } from '@/lib/telemetry/format';
import type { InspectorMessage } from '@/lib/telemetry/sources';
import type { NodeEntry } from '@/lib/telemetry/store';
import { toastSuccess } from '@/stores/toastStore';
import FramesTab from './FramesTab';
import SourceWizard, { type WizardStart } from './SourceWizard';
import type { Source } from './SourcesTab';
import { TransportIcon } from './transportIcon';
import { diagnose } from './SourceDiagnosis';
import { pluralShown } from '@/lib/plural';

export type MessagesView = 'recent' | 'problems' | 'frames';

const POLL_MS = 1500;

function pretty(payload: string | undefined, encoding?: string): string {
  if (!payload) return '';
  if (encoding && encoding !== 'utf-8' && encoding !== 'utf8' && encoding !== 'text') return payload;
  try { return JSON.stringify(JSON.parse(payload), null, 2); } catch { return payload; }
}

export function messageList(data: unknown): InspectorMessage[] {
  if (Array.isArray(data)) return data as InspectorMessage[];
  if (data && typeof data === 'object') {
    const o = data as Record<string, unknown>;
    for (const k of ['messages', 'items', 'dlq']) if (Array.isArray(o[k])) return o[k] as InspectorMessage[];
  }
  return [];
}

function MessageRow({ m, problem, canFix, onFix }: { m: InspectorMessage; problem?: boolean; canFix: boolean; onFix: (m: InspectorMessage) => void }) {
  const [open, setOpen] = useState(false);
  const ms = toMs(m.t ?? m.t_recv ?? null);
  const first = m.result?.[0];
  const bad = problem || m.ok === false || !!m.error;
  const why = m.reason || m.error;
  return (
    <li className="border-b border-slate-800/80 last:border-0" data-testid={problem ? 'tel-dlq-row' : 'tel-msg-row'} data-ok={bad ? 'false' : 'true'}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full min-w-0 items-start gap-2 px-3 py-2 text-left hover:bg-slate-800/40">
        {open ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />}
        <span className="w-[5.5rem] shrink-0 font-mono text-xs tabular-nums text-slate-500">{ms ? clock(ms, true).slice(0, 12) : ''}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-xs text-slate-200">{m.subject || 'no subject'}</span>
          {bad ? (
            <span className="mt-0.5 flex items-start gap-1 text-xs text-amber-200"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /> {why || 'Could not be decoded or mapped.'}</span>
          ) : (
            <span className="mt-0.5 flex min-w-0 items-center gap-1 text-xs text-emerald-200"><CheckCircle2 className="h-3 w-3 shrink-0" /> <span className="truncate">{m.records ?? 0} record{m.records === 1 ? '' : 's'}{first ? ` for ${[first.group, first.node, first.device].filter(Boolean).join(' · ')}${first.metrics?.length ? `, ${first.metrics.length} signal${first.metrics.length === 1 ? '' : 's'}` : ''}${first.frames ? `, ${first.frames} frames` : ''}${first.event ? `, event ${first.event}` : ''}` : ''}</span></span>
          )}
        </span>
        {m.size ? <span className="hidden shrink-0 text-[11px] tabular-nums text-slate-500 sm:inline">{m.size < 1024 ? `${m.size} B` : `${(m.size / 1024).toFixed(1)} kB`}</span> : null}
      </button>
      {open && (
        <div className="space-y-2 px-3 pb-3 pl-9">
          {m.headers && Object.keys(m.headers).length > 0 && (
            <p className="break-all font-mono text-[11px] text-slate-400">{Object.entries(m.headers).map(([k, v]) => `${k}: ${String(v)}`).join('  ·  ')}</p>
          )}
          {(m.encoding ?? m.payload_encoding) === 'base64' && <p className="text-[11px] text-slate-500">Binary message, shown as base64.</p>}
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-md border border-slate-800 bg-slate-950 p-2 font-mono text-[11px] text-slate-200">{pretty(m.payload, m.encoding ?? m.payload_encoding) || 'Empty message'}</pre>
          {canFix && (
            <button type="button" onClick={() => onFix(m)} className="inline-flex items-center gap-1 rounded-md border border-cyan-500/50 px-2 py-1 text-xs text-cyan-200 hover:bg-cyan-500/10" data-testid="tel-fix-mapping">
              <Shuffle className="h-3.5 w-3.5" /> {bad ? 'Fix mapping' : 'Map with this message'}
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export default function MessagesTab({
  sources, sourceId, setSource, view, setView, nodes, group, node, setNode, canManage, openSources, active, reloadSources,
}: {
  sources: Source[]; sourceId: string; setSource: (id: string) => void; view: MessagesView; setView: (v: MessagesView) => void;
  nodes: NodeEntry[]; group: string; node: string; setNode: (g: string, n: string) => void; canManage: boolean; openSources: () => void; active: boolean; reloadSources: () => void;
}) {
  const src = sources.find((s) => s.id === sourceId) ?? sources[0];
  const hasFrames = !!src && (src.decoder === 'can_frames' || (src.raw_topics?.length ?? 0) > 0 || (src as { decoders?: string[] }).decoders?.includes('can_frames'));
  const [paused, setPaused] = useState(false);
  const [msgs, setMsgs] = useState<InspectorMessage[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [onlyBad, setOnlyBad] = useState(false);
  const [fix, setFix] = useState<WizardStart | null>(null);
  const [confirmReplay, setConfirmReplay] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [replayErr, setReplayErr] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const { data: teams } = useApi<Array<{ id: string; name: string }>>(canManage ? '/api/telemetry/teams' : null);
  const v: MessagesView = view;

  const path = src ? (v === 'problems' ? `/api/telemetry/connections/${src.id}/dlq?limit=200` : `/api/telemetry/connections/${src.id}/inspector?limit=200`) : null;

  const load = useCallback(async () => {
    if (!path) return;
    const res = await apiFetch<unknown>(path, { silent: true });
    if (res.error) {
      setErr(explainTelemetryError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'load'));
      setMsgs((m) => m ?? []);
      return;
    }
    setErr(null);
    // newest first
    setMsgs(messageList(res.data).slice().sort((a, b) => (toMs(b.t ?? b.t_recv ?? null) ?? 0) - (toMs(a.t ?? a.t_recv ?? null) ?? 0)));
  }, [path]);

  useEffect(() => {
    setMsgs(null);
    setErr(null);
  }, [path]);

  useEffect(() => {
    if (!active || !path || v === 'frames') return;
    void load();
    if (paused) return;
    const h = setInterval(load, v === 'problems' ? POLL_MS * 4 : POLL_MS);
    return () => clearInterval(h);
  }, [active, path, paused, v, load]);

  const shown = useMemo(() => (msgs || []).filter((m) => !onlyBad || m.ok === false || !!m.error), [msgs, onlyBad]);
  const problemCount = src?.dlq_count ?? (v === 'problems' ? msgs?.length ?? 0 : 0);

  async function replay() {
    if (!src) return;
    setReplaying(true);
    setReplayErr(null);
    try {
      const res = await apiFetch<{ replayed?: number; still_failing?: unknown[] | number; remaining?: number }>(`/api/telemetry/connections/${src.id}/dlq/replay`, { method: 'POST', body: JSON.stringify({}) });
      const ok = res.data?.replayed ?? 0;
      const sf = res.data?.still_failing;
      const failed = Array.isArray(sf) ? sf.length : typeof sf === 'number' ? sf : 0;
      toastSuccess(`Replayed through the current mapping`, failed ? `${ok} stored, ${failed} still have a problem and stay in the list.` : `${ok} stored.`);
      setConfirmReplay(false);
      void load();
      reloadSources();
    } catch (e) {
      setReplayErr(explainTelemetryError(e, 'save'));
    } finally {
      setReplaying(false);
    }
  }

  if (!sources.length) {
    return (
      <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center text-sm text-slate-300" data-testid="tel-msgs-no-source">
        <Inbox className="mx-auto h-8 w-8 text-cyan-400" />
        <p className="mt-2 font-medium text-white">No sources yet, so there are no messages to look at.</p>
        <p className="mt-1">Each source keeps its last 500 raw messages here with what they turned into, and any that failed.</p>
        <button type="button" onClick={openSources} className="mt-3 text-cyan-300 hover:underline">{canManage ? 'Add a source' : 'See the sources'}</button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2" data-testid="tel-msgs-toolbar">
        <label className="min-w-[12rem]">
          <span className="sr-only">Source</span>
          <select value={src?.id ?? ''} onChange={(e) => setSource(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200" data-testid="tel-msgs-source">
            {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <div className="inline-flex rounded-lg border border-slate-700 p-0.5" role="tablist" aria-label="What to show">
          <button type="button" role="tab" aria-selected={v === 'recent'} onClick={() => setView('recent')} className={`rounded-md px-2.5 py-1 text-xs ${v === 'recent' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid="tel-msgs-recent">Recent</button>
          <button type="button" role="tab" aria-selected={v === 'problems'} onClick={() => setView('problems')} className={`rounded-md px-2.5 py-1 text-xs ${v === 'problems' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid="tel-msgs-problems">
            Problems{problemCount ? <span className="ml-1 rounded-full bg-amber-500/20 px-1.5 text-amber-200">{problemCount}</span> : null}
          </button>
          {(hasFrames || v === 'frames') && <button type="button" role="tab" aria-selected={v === 'frames'} onClick={() => setView('frames')} className={`rounded-md px-2.5 py-1 text-xs ${v === 'frames' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid="tel-msgs-frames">CAN frames</button>}
        </div>
        {v === 'recent' && (
          <>
            <button type="button" onClick={() => setPaused((p) => !p)} className={`inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border px-3 py-1 text-xs ${paused ? 'border-amber-500/50 bg-amber-500/10 text-amber-100' : 'border-slate-700 text-slate-200 hover:bg-slate-800'}`} data-testid="tel-msgs-pause">
              {paused ? <><Play className="h-3.5 w-3.5" /> Resume</> : <><Pause className="h-3.5 w-3.5" /> Pause</>}
            </button>
            <label className="flex items-center gap-1.5 text-xs text-slate-300">
              <input type="checkbox" checked={onlyBad} onChange={(e) => setOnlyBad(e.target.checked)} className="accent-cyan-500" /> Only the ones that failed
            </label>
          </>
        )}
        {v === 'problems' && canManage && (msgs?.length ?? 0) > 0 && (
          <button type="button" onClick={() => { setConfirmClear(true); setReplayErr(null); }} className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:bg-slate-800" data-testid="tel-dlq-clear">
            <Trash2 className="h-3.5 w-3.5" /> Clear the list
          </button>
        )}
        {v === 'problems' && canManage && (msgs?.length ?? 0) > 0 && (
          <button type="button" onClick={() => { setConfirmReplay(true); setReplayErr(null); }} className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border border-cyan-500/50 px-3 py-1 text-xs text-cyan-200 hover:bg-cyan-500/10" data-testid="tel-dlq-replay">
            <RotateCcw className="h-3.5 w-3.5" /> Replay through the current mapping
          </button>
        )}
        {src && <span className="ml-auto inline-flex items-center gap-1 text-xs text-slate-400"><TransportIcon transport={src.transport ?? 'mqtt'} className="h-3.5 w-3.5" /> {msgs ? `${shown.length} shown` : ''}</span>}
      </div>

      {v === 'frames' ? (
        <FramesTab nodes={nodes} group={group} node={node} setNode={setNode} canManage={canManage} openConnections={openSources} active={active} />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-700/60 bg-slate-950/60" data-testid={v === 'problems' ? 'tel-dlq' : 'tel-msgs'}>
          {v === 'problems' && (
            <p className="border-b border-slate-800 px-3 py-2 text-xs text-slate-400">
              {canManage
                ? 'Messages that could not be decoded or mapped wait here with the reason. Fix the mapping from one of them, then replay them all.'
                : 'Messages that could not be decoded or mapped wait here with the reason. You can open each one to see what arrived and why it failed, and send that to whoever manages the source. Fixing the mapping and replaying needs Manage telemetry brokers.'}
            </p>
          )}
          {err && !(msgs && msgs.length) ? (
            <p className="p-4 text-sm text-rose-200" role="alert" data-testid="tel-msgs-error">{err}</p>
          ) : msgs === null ? (
            <p className="flex items-center gap-2 p-4 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Reading the latest messages</p>
          ) : !shown.length ? (
            <p className="p-4 text-sm text-slate-300" data-testid={v === 'problems' ? 'tel-dlq-empty' : 'tel-msgs-empty'}>
              {v === 'problems'
                ? 'No problems. Every message from this source was decoded and stored.'
                : onlyBad ? 'None of the recent messages failed.' : src ? `${diagnose(src, { canManage, assets: 1 }).text} Messages show here as they arrive.` : 'Nothing yet.'}
            </p>
          ) : (
            <ul className="max-h-[560px] overflow-y-auto">
              {shown.slice(0, 200).map((m, i) => (
                <MessageRow key={m.id ?? `${m.t ?? m.t_recv}-${i}`} m={m} problem={v === 'problems'} canFix={canManage} onFix={(x) => src && setFix({ source: src, step: 'mapping', sample: pretty(x.payload, x.encoding ?? x.payload_encoding), subject: x.subject })} />
              ))}
            </ul>
          )}
        </div>
      )}

      {fix && (
        <SourceWizard start={fix} existingNames={sources.map((s) => s.name)} teams={teams || []} onClose={() => setFix(null)} onSaved={reloadSources} />
      )}

      {confirmClear && src && (
        <ConfirmModal
          open
          onClose={() => !replaying && setConfirmClear(false)}
          onConfirm={async () => {
            setReplaying(true);
            try {
              await apiFetch(`/api/telemetry/connections/${src.id}/dlq`, { method: 'DELETE' });
              toastSuccess('Problems cleared', 'Those messages are gone and will not be replayed.');
              setConfirmClear(false);
              void load();
              reloadSources();
            } catch (e) {
              setReplayErr(explainTelemetryError(e, 'delete'));
            } finally {
              setReplaying(false);
            }
          }}
          loading={replaying}
          icon={Trash2}
          title={`Clear the problems from ${src.name}?`}
          description={`The ${pluralShown(msgs?.length ?? 0, (msgs?.length ?? 0).toLocaleString('en-US'), 'message')} waiting here are deleted and cannot be replayed afterwards. Do this when they are not needed, for example after a test. This is recorded in the audit log.`}
          confirmLabel="Clear them"
          confirmTestId="tel-dlq-clear-confirm"
        >
          {replayErr && <p className="text-xs text-rose-300" role="alert">{replayErr}</p>}
        </ConfirmModal>
      )}

      {confirmReplay && src && (
        <ConfirmModal
          open
          onClose={() => !replaying && setConfirmReplay(false)}
          onConfirm={replay}
          loading={replaying}
          variant="warning"
          icon={RotateCcw}
          title={`Replay the problems from ${src.name}?`}
          description={`Each of the ${pluralShown(msgs?.length ?? 0, (msgs?.length ?? 0).toLocaleString('en-US'), 'message')} goes through the current mapping again. The ones that now work are stored with their own times, the rest stay here with the new reason. This is recorded in the audit log.`}
          confirmLabel="Replay them"
          confirmTestId="tel-dlq-replay-confirm"
        >
          {replayErr && <p className="text-xs text-rose-300" role="alert">{replayErr}</p>}
        </ConfirmModal>
      )}
    </div>
  );
}
