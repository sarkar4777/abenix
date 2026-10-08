'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, Copy, FileText, Loader2, RefreshCw, Search, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useEscapeToClose } from '@/hooks/useEscapeToClose';
import {
  agoText, fmtAge, logFilter, secondsSince, splitLogLine, type PodDetail, type PodLogs,
} from '@/lib/cluster';

const LINE_CHOICES = [100, 200, 500, 1000];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="text-xs text-slate-200 break-words">{children}</div>
    </div>
  );
}

export default function PodDrawer({ pod, onClose }: { pod: string | null; onClose: () => void }) {
  const [detail, setDetail] = useState<PodDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [container, setContainer] = useState('');
  const [lines, setLines] = useState(200);
  const [previous, setPrevious] = useState(false);
  const [logs, setLogs] = useState<PodLogs | null>(null);
  const [logErr, setLogErr] = useState<string | null>(null);
  const [logLoading, setLogLoading] = useState(false);
  const [q, setQ] = useState('');
  const [copied, setCopied] = useState(false);
  const logRef = useRef<HTMLPreElement>(null);
  const open = !!pod;
  useEscapeToClose(open, onClose);

  useEffect(() => {
    if (!pod) return;
    let cancelled = false;
    setDetail(null);
    setDetailErr(null);
    setLogs(null);
    setLogErr(null);
    setPrevious(false);
    setQ('');
    setDetailLoading(true);
    apiFetch<PodDetail>(`/api/admin/cluster/pods/${encodeURIComponent(pod)}`, { silent: true })
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error || !data) setDetailErr(error || 'Could not load this pod.');
        else {
          setDetail(data);
          const main = data.containers.find((c) => !c.init) || data.containers[0];
          setContainer(main?.name || '');
        }
      })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [pod]);

  const loadLogs = useCallback(async () => {
    if (!pod || !container) return;
    setLogLoading(true);
    setLogErr(null);
    const qs = new URLSearchParams({ container, lines: String(lines), previous: String(previous) });
    const { data, error } = await apiFetch<PodLogs>(`/api/admin/cluster/pods/${encodeURIComponent(pod)}/logs?${qs}`, { silent: true });
    if (error || !data) {
      setLogErr(error || 'Could not load logs.');
      setLogs(null);
    } else setLogs(data);
    setLogLoading(false);
  }, [pod, container, lines, previous]);

  useEffect(() => { if (detail) void loadLogs(); }, [detail, loadLogs]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  const shown = useMemo(() => logFilter(logs?.lines || [], q), [logs, q]);
  const current = detail?.containers.find((c) => c.name === container);
  const canPrevious = (current?.restarts || 0) > 0;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shown.join('\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={`Pod ${pod}`}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <aside className="relative z-10 h-full w-full md:w-[720px] bg-[#0B1220] border-l border-slate-800 flex flex-col" data-testid="pod-drawer">
        <header className="flex items-start justify-between gap-3 px-4 py-3 border-b border-slate-800">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Pod</div>
            <h2 className="font-mono text-sm text-white break-all" data-testid="pod-drawer-name">{pod}</h2>
            {detail && (
              <div className={`text-xs mt-0.5 ${detail.ready ? 'text-emerald-300' : 'text-amber-300'}`}>
                {detail.status} · {detail.containers_ready}/{detail.containers_total} containers ready
              </div>
            )}
          </div>
          <button type="button" onClick={onClose} className="p-2 -m-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800" aria-label="Close" data-testid="pod-drawer-close">
            <X className="w-5 h-5" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
          {detailLoading && (
            <div className="space-y-2" data-testid="pod-drawer-loading">
              {[0, 1, 2].map((i) => <div key={i} className="h-10 rounded-lg bg-slate-800/60 animate-pulse" />)}
            </div>
          )}
          {detailErr && (
            <div className="p-3 rounded-lg border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex gap-2" data-testid="pod-drawer-error">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> {detailErr}
            </div>
          )}

          {detail && (
            <>
              <section className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <Field label="Service">{detail.owner || '—'}</Field>
                <Field label="Node">{detail.node || '—'}</Field>
                <Field label="Age">{fmtAge(detail.age_seconds)}</Field>
                <Field label="Restarts">{detail.restarts}</Field>
                <Field label="Pod IP">{detail.ip || '—'}</Field>
                <Field label="QoS">{detail.qos || '—'}</Field>
              </section>

              <section>
                <h3 className="text-xs font-semibold text-slate-300 mb-2">Containers</h3>
                <div className="space-y-2">
                  {detail.containers.map((c) => (
                    <div key={c.name} className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-xs" data-testid="pod-container">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${c.ready || (c.init && c.state === 'terminated') ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                        <span className="font-medium text-white">{c.name}</span>
                        {c.init && <span className="text-[10px] px-1.5 rounded bg-slate-800 text-slate-400">init</span>}
                        <code className="text-[11px] text-slate-400 break-all">{c.tag}</code>
                        <span className="ml-auto text-slate-400">{c.state}{c.state_reason ? ` · ${c.state_reason}` : ''}</span>
                      </div>
                      {c.state_message && <div className="mt-1 text-amber-300/90 break-words">{c.state_message}</div>}
                      <div className="mt-1 text-slate-500">
                        {c.restarts} restarts
                        {c.requests.cpu || c.requests.memory ? ` · asks ${c.requests.cpu || '—'} CPU, ${c.requests.memory || '—'} memory` : ''}
                        {c.limits.memory ? ` · limit ${c.limits.memory}` : ''}
                      </div>
                      {c.last_termination && (
                        <div className="mt-1 text-slate-400">
                          Last stop: <span className={c.last_termination.reason === 'OOMKilled' ? 'text-red-300' : 'text-slate-300'}>{c.last_termination.reason || 'exited'}</span>
                          {c.last_termination.exit_code != null && ` (exit ${c.last_termination.exit_code})`}
                          {c.last_termination.at && `, ${agoText(secondsSince(c.last_termination.at))}`}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </section>

              <section data-testid="pod-logs-section">
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <h3 className="text-xs font-semibold text-slate-300 mr-auto inline-flex items-center gap-1.5"><FileText className="w-3.5 h-3.5" /> Log tail</h3>
                  {detail.containers.length > 1 && (
                    <select
                      value={container}
                      onChange={(e) => { setContainer(e.target.value); setPrevious(false); }}
                      className="text-xs bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-slate-200"
                      aria-label="Container"
                      data-testid="pod-logs-container"
                    >
                      {detail.containers.map((c) => <option key={c.name} value={c.name}>{c.name}{c.init ? ' (init)' : ''}</option>)}
                    </select>
                  )}
                  <select
                    value={lines}
                    onChange={(e) => setLines(Number(e.target.value))}
                    className="text-xs bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-slate-200"
                    aria-label="Lines"
                    data-testid="pod-logs-lines"
                  >
                    {LINE_CHOICES.map((n) => <option key={n} value={n}>Last {n} lines</option>)}
                  </select>
                  <label
                    className={`inline-flex items-center gap-1.5 text-xs ${canPrevious ? 'text-slate-300 cursor-pointer' : 'text-slate-600 cursor-not-allowed'}`}
                    title={canPrevious ? 'Show the run before the last restart' : 'This container has not restarted, so there is no earlier run to show'}
                  >
                    <input type="checkbox" checked={previous} disabled={!canPrevious} onChange={(e) => setPrevious(e.target.checked)} data-testid="pod-logs-previous" />
                    Before last restart
                  </label>
                  <button type="button" onClick={() => void loadLogs()} disabled={logLoading} className="inline-flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-50" data-testid="pod-logs-refresh">
                    <RefreshCw className={`w-3 h-3 ${logLoading ? 'animate-spin' : ''}`} /> Refresh
                  </button>
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="relative flex-1">
                    <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
                    <input
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                      placeholder="Filter lines"
                      className="w-full text-xs bg-slate-900 border border-slate-700 rounded-md pl-7 pr-2 py-1.5 text-slate-200 placeholder:text-slate-600"
                      aria-label="Filter log lines"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={copy}
                    disabled={!shown.length}
                    title={shown.length ? 'Copy the lines shown' : 'Nothing to copy yet'}
                    className="inline-flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40"
                  >
                    {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />} {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
                {logErr ? (
                  <div className="p-3 rounded-lg border border-amber-500/40 bg-amber-500/10 text-amber-300 text-xs" data-testid="pod-logs-error">{logErr}</div>
                ) : logLoading && !logs ? (
                  <div className="h-48 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-center text-xs text-slate-500" data-testid="pod-logs-loading">
                    <Loader2 className="w-4 h-4 animate-spin mr-2" /> Reading logs
                  </div>
                ) : (
                  <pre
                    ref={logRef}
                    className="h-72 md:h-96 overflow-auto rounded-lg bg-black/60 border border-slate-800 p-3 text-[11px] leading-relaxed font-mono text-slate-300 whitespace-pre-wrap break-all"
                    data-testid="pod-logs"
                    data-lines={logs?.lines.length ?? 0}
                  >
                    {shown.length
                      ? shown.map((l, i) => {
                          const { time, text } = splitLogLine(l);
                          return (
                            <div key={i}>
                              {time && <span className="text-slate-600 select-none">{time} </span>}
                              {text}
                            </div>
                          );
                        })
                      : <span className="text-slate-500">{q ? 'No lines match the filter.' : 'This container has written no log lines yet.'}</span>}
                  </pre>
                )}
                {logs && (
                  <div className="mt-1 text-[10px] text-slate-500">
                    {logs.lines.length} line{logs.lines.length === 1 ? '' : 's'}{logs.truncated ? ', cut at 512 KB' : ''}{logs.previous ? ', from the run before the last restart' : ''}. Reading logs is recorded in the audit log.
                  </div>
                )}
              </section>
              <section data-testid="pod-events">
                <h3 className="text-xs font-semibold text-slate-300 mb-2">Events</h3>
                {detail.events_error ? (
                  <div className="text-xs text-amber-300">{detail.events_error}</div>
                ) : detail.events.length ? (
                  <ol className="space-y-1.5">
                    {detail.events.map((e, i) => (
                      <li key={i} className="flex gap-2 text-xs" data-testid="pod-event">
                        <span className={`mt-1 w-1.5 h-1.5 rounded-full shrink-0 ${e.type === 'Warning' ? 'bg-amber-400' : 'bg-slate-500'}`} />
                        <div className="min-w-0">
                          <span className={e.type === 'Warning' ? 'text-amber-300' : 'text-slate-300'}>{e.reason}</span>
                          {e.count > 1 && <span className="text-slate-500"> ×{e.count}</span>}
                          <span className="text-slate-500"> · {agoText(e.age_seconds)}</span>
                          <div className="text-slate-400 break-words">{e.message}</div>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div className="text-xs text-slate-500" data-testid="pod-events-empty">
                    No recent events. Kubernetes keeps events for about an hour, so a quiet pod has none.
                  </div>
                )}
              </section>

            </>
          )}
        </div>
      </aside>
    </div>
  );
}
