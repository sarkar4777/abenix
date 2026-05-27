'use client';

/**
 * Interactive Event Timeline (Feature #10 in the spec).
 *
 * Single feed of every contractual event across the user's portfolio,
 * sorted chronologically. Header KPIs (overdue / upcoming-30-days /
 * by-type) help operators triage what to look at first; each row
 * deep-links to the parent contract's detail page where the full
 * clause + event DAG lives.
 */

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Calendar, AlertTriangle, CheckCircle2, Clock, Filter, RefreshCw, ChevronRight } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

type Ev = {
  id: string;
  contract_id: string;
  contract_title: string;
  contract_type: string;
  counterparty_a: string;
  counterparty_b: string;
  event_type: string;
  event_date: string | null;
  description: string;
  status: 'upcoming' | 'passed' | 'triggered' | string;
  is_recurring: boolean;
  notification_days_before: number | null;
};

type Payload = {
  events: Ev[];
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  upcoming_30d: number;
  overdue: number;
};

const TYPE_META: Record<string, { color: string; label: string }> = {
  milestone:           { color: 'cyan',    label: 'Milestone' },
  deadline:            { color: 'amber',   label: 'Deadline' },
  review:              { color: 'violet',  label: 'Review' },
  renewal:             { color: 'emerald', label: 'Renewal' },
  termination_trigger: { color: 'rose',    label: 'Termination Trigger' },
};

const STATUS_META: Record<string, { color: string; Icon: any }> = {
  upcoming:  { color: 'cyan',    Icon: Clock },
  passed:    { color: 'emerald', Icon: CheckCircle2 },
  triggered: { color: 'rose',    Icon: AlertTriangle },
};

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' });
}

function daysFromNow(iso: string | null): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

export default function TimelinePage() {
  return <Inner />;
}

function Inner() {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<{ type: string; status: string }>({ type: '', status: '' });

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null;
      if (!token) { setError('Not signed in.'); return; }
      const qs = new URLSearchParams();
      if (filter.type) qs.set('event_type', filter.type);
      if (filter.status) qs.set('status', filter.status);
      const r = await fetch(`${API_URL}/api/contractiq/timeline?${qs.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      setData((json.data ?? json) as Payload);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, [filter.type, filter.status]);

  const groupedByMonth = useMemo(() => {
    if (!data) return [];
    const groups: Record<string, Ev[]> = {};
    for (const e of data.events) {
      const key = e.event_date
        ? new Date(e.event_date).toLocaleDateString(undefined, { year: 'numeric', month: 'long' })
        : 'Undated';
      (groups[key] ??= []).push(e);
    }
    return Object.entries(groups);
  }, [data]);

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6" data-testid="timeline-page">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">E&C-Copilot · interactive event timeline</p>
          <h1 className="text-3xl font-bold text-white">Event Timeline</h1>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Every milestone, deadline, review, renewal, and termination trigger lifted from
            your contracts — sorted chronologically so it&apos;s instantly clear what&apos;s
            already passed, what&apos;s due in the next 30 days, and what&apos;s overdue.
          </p>
        </div>
        <button
          onClick={() => void refresh()}
          className="px-3 py-2 text-xs rounded-lg border border-slate-700 bg-slate-800/40 hover:bg-slate-800 text-slate-200 inline-flex items-center gap-2"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Kpi label="Total events"   value={data?.total ?? 0}        icon={Calendar}       color="text-cyan-400" />
        <Kpi label="Overdue"        value={data?.overdue ?? 0}      icon={AlertTriangle}  color="text-rose-400" />
        <Kpi label="Upcoming 30d"   value={data?.upcoming_30d ?? 0} icon={Clock}          color="text-amber-400" />
        <Kpi label="Renewals"       value={data?.by_type?.renewal ?? 0} icon={CheckCircle2} color="text-emerald-400" />
        <Kpi label="Term triggers"  value={data?.by_type?.termination_trigger ?? 0} icon={AlertTriangle} color="text-violet-400" />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="timeline-filters">
        <Filter className="w-3.5 h-3.5 text-slate-500" />
        <span className="text-slate-500">Filter:</span>
        <select
          value={filter.type}
          onChange={e => setFilter(f => ({ ...f, type: e.target.value }))}
          className="bg-slate-800/60 border border-slate-700 rounded px-2 py-1 text-slate-200"
        >
          <option value="">All types</option>
          {Object.entries(TYPE_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select
          value={filter.status}
          onChange={e => setFilter(f => ({ ...f, status: e.target.value }))}
          className="bg-slate-800/60 border border-slate-700 rounded px-2 py-1 text-slate-200"
        >
          <option value="">All statuses</option>
          <option value="upcoming">Upcoming</option>
          <option value="passed">Passed</option>
          <option value="triggered">Triggered</option>
        </select>
        {(filter.type || filter.status) && (
          <button
            onClick={() => setFilter({ type: '', status: '' })}
            className="text-cyan-400 hover:underline"
          >
            Clear
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-rose-200 text-sm">
          {error}. <button onClick={() => void refresh()} className="underline">Retry</button>
        </div>
      )}

      {loading && !data && (
        <div className="text-slate-500 text-sm py-12 text-center">Loading timeline…</div>
      )}

      {data && data.events.length === 0 && (
        <div className="rounded-xl border border-slate-700 bg-slate-800/30 p-8 text-center text-slate-400 text-sm">
          No events yet. Upload + analyze a contract on <Link href="/upload" className="text-cyan-400 underline">/upload</Link> — the
          extractor produces milestones, deadlines, reviews, renewals, and termination triggers per clause.
        </div>
      )}

      {/* Vertical timeline grouped by month */}
      <div className="relative">
        {data && data.events.length > 0 && (
          <div className="absolute left-3 top-0 bottom-0 w-px bg-slate-700/60" aria-hidden />
        )}
        <ul className="space-y-6" data-testid="timeline-events">
          {groupedByMonth.map(([month, evs]) => (
            <li key={month}>
              <div className="ml-8 mb-2 text-[11px] uppercase tracking-wider text-slate-500">{month}</div>
              <ul className="space-y-3">
                {evs.map(e => <TimelineRow key={e.id} ev={e} />)}
              </ul>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Kpi({ label, value, icon: Icon, color }: { label: string; value: number; icon: any; color: string }) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/30 p-4 flex items-center gap-3">
      <Icon className={`w-5 h-5 ${color}`} />
      <div>
        <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
        <p className="text-xl font-bold text-white">{value}</p>
      </div>
    </div>
  );
}

function TimelineRow({ ev }: { ev: Ev }) {
  const tm = TYPE_META[ev.event_type] || { color: 'slate', label: ev.event_type };
  const sm = STATUS_META[ev.status] || STATUS_META.upcoming;
  const Icon = sm.Icon;
  const dn = daysFromNow(ev.event_date);
  const overdue = dn !== null && dn < 0 && ev.status !== 'passed';
  const soon = dn !== null && dn >= 0 && dn <= 30;

  return (
    <li className="relative pl-10" data-testid="timeline-row">
      <span
        className={`absolute left-1 top-2 w-5 h-5 rounded-full border-2 flex items-center justify-center bg-slate-900 border-${tm.color}-400/60`}
        aria-hidden
      >
        <Icon className={`w-3 h-3 text-${sm.color}-400`} />
      </span>
      <Link
        href={`/contracts/${ev.contract_id}`}
        className="block group rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/50 p-3.5 transition-colors"
      >
        <div className="flex items-center gap-2 mb-1">
          <span className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-${tm.color}-500/15 text-${tm.color}-300`}>
            {tm.label}
          </span>
          <span className="text-[11px] text-slate-500">·</span>
          <span className="text-[11px] text-slate-400">{formatDate(ev.event_date)}</span>
          {ev.is_recurring && (
            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-700/60 text-slate-300">recurring</span>
          )}
          {overdue && (
            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-300">{Math.abs(dn!)}d overdue</span>
          )}
          {soon && !overdue && (
            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">in {dn}d</span>
          )}
          <span className={`ml-auto text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-${sm.color}-500/15 text-${sm.color}-300`}>
            {ev.status}
          </span>
        </div>
        <p className="text-sm text-slate-200 leading-snug">{ev.description}</p>
        <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-500">
          <span className="truncate">{ev.contract_title}</span>
          <ChevronRight className="w-3 h-3 group-hover:text-slate-300 ml-auto" />
        </div>
      </Link>
    </li>
  );
}
