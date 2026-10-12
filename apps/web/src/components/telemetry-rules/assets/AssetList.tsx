'use client';

import { memo } from 'react';
import { ChevronLeft, ChevronRight, CornerDownRight } from 'lucide-react';
import { StatusDot } from '@/components/telemetry/bits';
import { ago } from '@/lib/telemetry/format';
import { keyFieldsText, locationText, rowKey, statusOf, typeLabel, type AssetRow } from './lib';

const MAX_CHIPS = 3;

function Tags({ tags }: { tags: string[] }) {
  if (!tags?.length) return <span className="text-slate-600">None</span>;
  const shown = tags.slice(0, MAX_CHIPS);
  return (
    <span className="flex min-w-0 flex-wrap gap-1">
      {shown.map((t) => <span key={t} className="max-w-[9rem] truncate rounded-full border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-200">{t}</span>)}
      {tags.length > shown.length && <span className="rounded-full px-1 py-0.5 text-[11px] text-slate-400" title={tags.slice(MAX_CHIPS).join(', ')}>+{tags.length - shown.length}</span>}
    </span>
  );
}

function Unregistered() {
  return <span className="shrink-0 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-200">Unregistered</span>;
}

function Name({ r }: { r: AssetRow }) {
  return (
    <span className="flex min-w-0 items-start gap-1.5">
      {r.device && <CornerDownRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" aria-label="Part" />}
      <span className="min-w-0">
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          {r.display_name
            ? <span className="truncate font-medium text-white">{r.display_name}</span>
            : <span className="break-all font-mono text-slate-200">{r.device || r.node}</span>}
          {!r.registered && <Unregistered />}
        </span>
        <span className="block break-all font-mono text-[11px] text-slate-500">{rowKey(r)}</span>
      </span>
    </span>
  );
}

function Seen({ r, now }: { r: AssetRow; now: number }) {
  const st = statusOf(r);
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-slate-300" title={st.label}>
      <StatusDot status={st.tone} />
      <span className="truncate">{r.last_seen ? ago(r.last_seen, now) : st.label}</span>
    </span>
  );
}

const muted = (s: string, empty = 'Not set') => (s ? <span className="break-words">{s}</span> : <span className="text-slate-600">{empty}</span>);

interface ListProps {
  rows: AssetRow[];
  now: number;
  onOpen: (r: AssetRow) => void;
  canEdit: (r: AssetRow) => boolean;
}

export const AssetTable = memo(function AssetTable({ rows, now, onOpen, canEdit }: ListProps) {
  return (
    <div className="hidden overflow-x-auto rounded-xl border border-slate-700/60 bg-slate-900/40 md:block" data-testid="assets-table">
      <table className="w-full table-fixed text-left text-sm">
        <colgroup>
          <col className="w-[24%]" /><col className="w-[9%]" /><col className="w-[16%]" /><col className="w-[15%]" /><col className="w-[15%]" /><col className="w-[11%]" /><col className="w-[10%]" />
        </colgroup>
        <thead className="border-b border-slate-700 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium">Name</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Tags</th>
            <th className="px-3 py-2 font-medium">Location</th>
            <th className="px-3 py-2 font-medium">Key details</th>
            <th className="px-3 py-2 font-medium">Last seen</th>
            <th className="px-3 py-2 font-medium">Team</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const k = rowKey(r);
            const edit = canEdit(r);
            return (
              <tr key={k} onClick={() => onOpen(r)} className="cursor-pointer border-b border-slate-800/80 align-top last:border-0 hover:bg-slate-800/40" data-testid="assets-row" data-key={k} data-registered={r.registered ? 'true' : 'false'}>
                <td className="px-3 py-2">
                  <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(r); }} className="block w-full min-w-0 rounded text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500" aria-label={`${edit ? (r.registered ? 'Change' : 'Name') : 'View'} ${r.display_name || k}`}>
                    <Name r={r} />
                  </button>
                </td>
                <td className="px-3 py-2 text-slate-200">{muted(typeLabel(r.type))}</td>
                <td className="px-3 py-2"><Tags tags={r.tags} /></td>
                <td className="px-3 py-2 text-xs text-slate-300">{muted(locationText(r.location))}</td>
                <td className="px-3 py-2 text-xs text-slate-300">{muted(keyFieldsText(r.fields), 'None')}</td>
                <td className="px-3 py-2"><Seen r={r} now={now} /></td>
                <td className="truncate px-3 py-2 text-xs text-slate-300">{r.team_name || <span className="text-slate-500">Whole workspace</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
});

export const AssetCards = memo(function AssetCards({ rows, now, onOpen }: ListProps) {
  return (
    <ul className="space-y-2 md:hidden" data-testid="assets-cards">
      {rows.map((r) => {
        const k = rowKey(r);
        const loc = locationText(r.location);
        const fields = keyFieldsText(r.fields);
        return (
          <li key={k}>
            <button type="button" onClick={() => onOpen(r)} className={`block w-full min-w-0 rounded-xl border bg-slate-900/40 p-3 text-left hover:border-slate-500 ${r.registered ? 'border-slate-700/60' : 'border-amber-500/30'}`} data-testid="assets-card" data-key={k}>
              <div className="flex min-w-0 items-start justify-between gap-2">
                <Name r={r} />
                <Seen r={r} now={now} />
              </div>
              <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-300">
                {r.type && <span>{typeLabel(r.type)}</span>}
                {r.team_name && <span className="text-slate-400">{r.team_name}</span>}
                {loc && <span className="min-w-0 break-words text-slate-400">{loc}</span>}
              </div>
              {fields && <p className="mt-1 break-words text-xs text-slate-400">{fields}</p>}
              {r.tags?.length > 0 && <div className="mt-2"><Tags tags={r.tags} /></div>}
            </button>
          </li>
        );
      })}
    </ul>
  );
});

export function Pager({ from, to, total, page, pages, setPage }: { from: number; to: number; total: number; page: number; pages: number; setPage: (p: number) => void }) {
  if (pages <= 1) return null;
  const btn = 'inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40';
  return (
    <nav className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400" aria-label="Pages" data-testid="assets-pager">
      <span>Showing {(from + 1).toLocaleString('en-US')} to {to.toLocaleString('en-US')} of {total.toLocaleString('en-US')}</span>
      <span className="flex items-center gap-2">
        <button type="button" onClick={() => setPage(page - 1)} disabled={page === 0} className={btn} data-testid="assets-prev"><ChevronLeft className="h-3.5 w-3.5" /> Previous</button>
        <span className="tabular-nums">Page {page + 1} of {pages}</span>
        <button type="button" onClick={() => setPage(page + 1)} disabled={page >= pages - 1} className={btn} data-testid="assets-next">Next <ChevronRight className="h-3.5 w-3.5" /></button>
      </span>
    </nav>
  );
}

export function ListSkeleton() {
  return (
    <div className="space-y-2" data-testid="assets-loading" aria-busy="true" aria-label="Loading assets">
      {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-14 animate-pulse rounded-xl border border-slate-800 bg-slate-800/30" />)}
    </div>
  );
}
