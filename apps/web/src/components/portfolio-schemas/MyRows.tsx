'use client';

import { Loader2, RefreshCw } from 'lucide-react';
import { useApi } from '@/hooks/useApi';

interface RowsData {
  table: string;
  total: number;
  columns: { name: string; label: string }[];
  rows: unknown[][];
}

function show(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  const s = String(v);
  return /^\d{4}-\d{2}-\d{2}T00:00:00/.test(s) ? s.slice(0, 10) : s;
}

export default function MyRows({ schemaId, noun }: { schemaId: string; noun: string }) {
  const { data, error, isLoading, mutate } = useApi<RowsData>(`/api/portfolio-schemas/${schemaId}/rows?limit=25`);

  if (isLoading && !data) {
    return <p className="text-xs text-slate-500 inline-flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading your rows…</p>;
  }
  if (error && !data) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-xs text-red-300 break-words">
        <p>{error}</p>
        <button onClick={() => mutate()} className="mt-2 inline-flex items-center gap-1 text-red-200 underline"><RefreshCw className="w-3 h-3" /> Retry</button>
      </div>
    );
  }
  if (!data) return null;
  if (data.total === 0) {
    return (
      <p className="text-xs text-slate-400">
        You have no {noun} in this table yet. Other people&apos;s rows are not shown to you or to agents acting for you. Use Add rows to upload yours.
      </p>
    );
  }
  const cols = data.columns.filter(c => c.name !== 'created_at');
  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-slate-700/50 max-h-[420px] overflow-y-auto">
        <table className="min-w-full text-[11px]">
          <thead className="bg-slate-900/80 text-slate-400 sticky top-0">
            <tr>{cols.map(c => <th key={c.name} className="px-2 py-1.5 text-left font-medium whitespace-nowrap">{c.label}</th>)}</tr>
          </thead>
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-800">
                {cols.map(c => {
                  const idx = data.columns.findIndex(x => x.name === c.name);
                  return <td key={c.name} className="px-2 py-1 text-slate-300 whitespace-nowrap max-w-[16rem] truncate">{show(r[idx])}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-slate-500 mt-1">
        Showing {data.rows.length} of your {data.total.toLocaleString()} {noun}. Stored in table <code className="text-slate-400">{data.table}</code>.
      </p>
    </div>
  );
}
