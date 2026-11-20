'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Clock, ListChecks, Loader2, Play, X } from 'lucide-react';

import { StatusBadge } from '@/components/StatusBadge';
import { api, refreshAll, type Platform, type Row, type Stats, type Status } from '@/lib/api';
import { STATUS_SHORT, STATUS_TONE, splitSender } from '@/lib/format';
import { POLL_MS, usePoll } from '@/lib/usePoll';
import { toastError, toastInfo } from '@/stores/toastStore';

const CARDS: Array<'success' | 'clarification' | 'escalated' | 'system_error'> = [
  'success', 'clarification', 'escalated', 'system_error',
];

export default function Inbox() {
  const stats = usePoll<Stats>(api.stats, POLL_MS, 'stats');
  const rows = usePoll<Row[]>(api.emails, POLL_MS, 'emails');
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [filter, setFilter] = useState<Status | null>(null);
  const [starting, setStarting] = useState(false);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [startingSelected, setStartingSelected] = useState(false);

  useEffect(() => {
    void api.platform().then((r) => setPlatform(r.data));
  }, []);

  const s = stats.data;
  const list = (rows.data ?? []).filter((r) => !filter || r.status === filter);
  // Only waiting emails can be processed, so a ticked row that has started
  // (here or from another tab) drops out of the selection on its own.
  const waitingIds = new Set((rows.data ?? []).filter((r) => r.status === 'waiting').map((r) => r.id));
  const selected = (rows.data ?? []).filter((r) => ticked.has(r.id) && waitingIds.has(r.id)).map((r) => r.id);
  const visibleWaiting = list.filter((r) => r.status === 'waiting').map((r) => r.id);
  const allVisibleTicked = visibleWaiting.length > 0 && visibleWaiting.every((id) => ticked.has(id));

  const toggle = (id: string) => setTicked((t) => {
    const next = new Set(t);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAll = () => setTicked((t) => {
    const next = new Set(t);
    visibleWaiting.forEach((id) => (allVisibleTicked ? next.delete(id) : next.add(id)));
    return next;
  });

  const processSelected = async () => {
    setStartingSelected(true);
    const results = await Promise.all(selected.map((id) => api.process(id)));
    setStartingSelected(false);
    const failed = results.filter((r) => r.error);
    if (failed.length) toastError(`${failed.length} of ${results.length} could not start: ${failed[0].error}`);
    setTicked(new Set());
    refreshAll();
  };

  const processNext = async () => {
    setStarting(true);
    const r = await api.processNext();
    setStarting(false);
    if (r.error) {
      (r.status === 409 ? toastInfo : toastError)(r.error === 'every email has been processed'
        ? 'Every email has been processed. Reset the example from the menu to start again.'
        : r.error);
      return;
    }
    refreshAll();
  };

  const platformProblem = platform && (!platform.api_key_set || !platform.reachable
    || !platform.pipeline_registered || !platform.drafter_registered);

  return (
    <main className="mx-auto max-w-[96rem] px-4 sm:px-6 py-6 space-y-6">
      {(rows.error || platformProblem) && (
        <div className="rounded-lg bg-rose-500/10 ring-1 ring-rose-500/30 px-4 py-3 text-sm text-rose-200 flex gap-2" data-testid="platform-problem">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {rows.error
              ?? (!platform?.api_key_set ? 'QUOTEIQ_ABENIX_API_KEY is not set on the QuoteIQ API, so no email can be processed.'
                : `Abenix isn't ready for QuoteIQ: ${platform?.detail ?? 'unknown problem'}`)}
          </span>
        </div>
      )}

      <section className="flex flex-wrap items-center gap-4">
        <div className="mr-auto">
          <h1 className="text-2xl font-bold text-white">Inbox</h1>
          <p className="text-sm text-slate-400 mt-1" data-testid="totals">
            {s ? (
              <>
                {s.emails} emails · {s.processed} processed
                {s.processing > 0 && <> · {s.processing} processing</>} · {s.waiting} waiting
              </>
            ) : 'Loading…'}
          </p>
        </div>
        <button
          onClick={() => void processNext()}
          disabled={starting || !s || s.waiting === 0}
          data-testid="process-next"
          title={s && s.waiting === 0 ? 'Every email has been processed' : 'Send the next waiting email to the RFQ pipeline'}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 px-4 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Process next RFQ email
        </button>
        <button
          onClick={() => void processSelected()}
          disabled={startingSelected || selected.length === 0}
          data-testid="process-selected"
          title={selected.length === 0 ? 'Tick waiting emails in the list to process them' : 'Send the ticked emails to the RFQ pipeline, side by side'}
          className="inline-flex items-center gap-2 rounded-lg ring-1 ring-sky-500/60 text-sky-200 hover:bg-sky-500/10 px-4 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {startingSelected ? <Loader2 className="w-4 h-4 animate-spin" /> : <ListChecks className="w-4 h-4" />}
          Process selected{selected.length > 0 && ` (${selected.length})`}
        </button>
      </section>

      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {CARDS.map((status) => {
          const c = s?.by_status[status];
          const tone = STATUS_TONE[status];
          const active = filter === status;
          return (
            <button
              key={status}
              onClick={() => setFilter(active ? null : status)}
              data-testid={`card-${status}`}
              aria-pressed={active}
              className={`text-left rounded-xl p-4 ring-1 transition-colors ${
                active ? `${tone.bg} ${tone.ring}` : 'bg-slate-900/60 ring-slate-800 hover:ring-slate-600'}`}
            >
              <div className={`flex items-center gap-2 text-[11px] uppercase tracking-wider ${tone.text}`}>
                <span className={`w-2 h-2 rounded-full ${tone.dot}`} /> {STATUS_SHORT[status]}
              </div>
              <div className="flex items-baseline gap-3 mt-2">
                <span className="text-3xl font-bold text-white">{c?.count ?? 0}</span>
                {(c?.awaiting_review ?? 0) > 0 && (
                  <span className="inline-flex items-center gap-1 text-xs text-slate-400">
                    <Clock className="w-3 h-3" /> {c!.awaiting_review} awaiting review
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </section>

      <section className="rounded-xl bg-slate-900/60 ring-1 ring-slate-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2 text-sm">
          <h2 className="font-semibold text-white">Emails</h2>
          {filter && (
            <button onClick={() => setFilter(null)} data-testid="clear-filter"
              className="inline-flex items-center gap-1 text-xs rounded-full px-2 py-0.5 bg-slate-800 text-slate-300 hover:text-white">
              {STATUS_SHORT[filter]} <X className="w-3 h-3" />
            </button>
          )}
          <span className="ml-auto text-xs text-slate-500">A status card filters the list</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-slate-500">
              <tr className="border-b border-slate-800/70">
                <th className="pl-4 py-2 w-8">
                  <HeaderCheckbox
                    checked={allVisibleTicked}
                    indeterminate={!allVisibleTicked && visibleWaiting.some((id) => ticked.has(id))}
                    disabled={visibleWaiting.length === 0}
                    onChange={toggleAll}
                  />
                </th>
                <th className="text-left font-medium px-4 py-2 w-[19rem]">Status</th>
                <th className="text-left font-medium px-4 py-2">From</th>
                <th className="text-left font-medium px-4 py-2">Subject</th>
                <th className="text-right font-medium px-4 py-2 w-28">Lines</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {list.map((r) => (
                <InboxRow key={r.id} row={r} ticked={selected.includes(r.id)} onTick={() => toggle(r.id)} />
              ))}
              {rows.data && list.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-500">
                  {filter ? `No email is ${STATUS_SHORT[filter].toLowerCase()}.` : 'No example emails were found.'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function HeaderCheckbox({ checked, indeterminate, disabled, onChange }: {
  checked: boolean; indeterminate: boolean; disabled: boolean; onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input ref={ref} type="checkbox" checked={checked} disabled={disabled} onChange={onChange}
      aria-label="Select every waiting email" data-testid="select-all"
      className="w-4 h-4 accent-sky-500 disabled:opacity-30 cursor-pointer disabled:cursor-not-allowed" />
  );
}

function InboxRow({ row, ticked, onTick }: { row: Row; ticked: boolean; onTick: () => void }) {
  const [person, company] = splitSender(row.from_name);
  const lines = row.status === 'processing'
    ? <span className="text-sky-300">{row.lines_done ? `${row.lines_done} searched` : '…'}</span>
    : row.line_count ?? <span className="text-slate-600">–</span>;
  const href = `/emails/${encodeURIComponent(row.id)}`;
  return (
    <tr className="hover:bg-slate-800/40 cursor-pointer" data-testid={`row-${row.id}`}>
      <td className="pl-4 py-2.5">
        <input type="checkbox" checked={ticked} onChange={onTick} disabled={row.status !== 'waiting'}
          aria-label={`Select ${row.subject}`} data-testid={`select-${row.id}`}
          title={row.status === 'waiting' ? 'Select to process' : 'Already processed or processing'}
          className="w-4 h-4 accent-sky-500 disabled:opacity-30 cursor-pointer disabled:cursor-not-allowed" />
      </td>
      <td className="px-4 py-2.5"><Link href={href} className="block"><StatusBadge status={row.status} review={row.review} /></Link></td>
      <td className="px-4 py-2.5 max-w-0 w-1/3">
        <Link href={href} className="block truncate">
          <span className="text-slate-100">{person}</span>
          {company && <span className="text-slate-500"> · {company}</span>}
        </Link>
      </td>
      <td className="px-4 py-2.5 max-w-0 w-1/2">
        <Link href={href} className="block truncate text-slate-300">
          {row.subject}
          {row.edited && <span className="ml-2 text-[10px] text-sky-300">edited</span>}
        </Link>
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-slate-300"><Link href={href} className="block">{lines}</Link></td>
    </tr>
  );
}
