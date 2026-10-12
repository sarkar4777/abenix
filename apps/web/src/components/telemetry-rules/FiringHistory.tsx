'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import useSWR from 'swr';
import { CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Clock, ExternalLink, MinusCircle, RefreshCw, XCircle } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { ACTION_INFO, ago, dayTime, fmt, type ActionKind, type ActionOutcome, type Firing } from './lib';
import { Badge } from './ui';

function fetcher(url: string) {
  return apiFetch<Firing[]>(url, { silent: true });
}

function StepIcon({ status }: { status: string }) {
  if (status === 'ok') return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" aria-label="Done" />;
  if (status === 'failed') return <XCircle className="h-3.5 w-3.5 shrink-0 text-rose-400" aria-label="Failed" />;
  if (status === 'skipped') return <MinusCircle className="h-3.5 w-3.5 shrink-0 text-slate-500" aria-label="Skipped" />;
  return <CircleDashed className="h-3.5 w-3.5 shrink-0 animate-spin text-cyan-300" aria-label="Running" />;
}

function show(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  return JSON.stringify(v, null, 2);
}

function took(ms?: number): string | null {
  if (ms === undefined || ms === null) return null;
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function StepRow({ a, i }: { a: ActionOutcome; i: number }) {
  const [open, setOpen] = useState(false);
  const link = (a.ref && typeof a.ref === 'object' && typeof (a.ref as { link?: unknown }).link === 'string') ? (a.ref as { link: string }).link : null;
  const has = (a.input && Object.keys(a.input).length > 0) || (a.output !== undefined && a.output !== null);
  const dur = took(a.duration_ms);
  return (
    <li className="text-xs" data-testid="firing-step" data-kind={a.kind} data-status={a.status}>
      <div className="flex items-start gap-2">
        <StepIcon status={a.status} />
        <span className="min-w-0 flex-1">
          <span className="text-slate-500">{i + 1}. </span>
          <span className="text-slate-400">{ACTION_INFO[a.kind as ActionKind]?.label ?? a.kind}: </span>
          <span className={a.status === 'failed' ? 'text-rose-200' : 'text-slate-200'}>{a.message}</span>
          {dur && <span className="ml-1 text-slate-500">({dur})</span>}
          {link && (
            <Link href={link} className="ml-1 inline-flex items-center gap-0.5 text-cyan-300 hover:underline" data-testid="firing-step-link">
              open the run <ExternalLink className="h-3 w-3" />
            </Link>
          )}
        </span>
        {has && (
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex shrink-0 items-center gap-0.5 rounded px-1.5 py-0.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200" data-testid="firing-step-toggle">
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} {open ? 'Hide' : 'In and out'}
          </button>
        )}
      </div>
      {open && (
        <div className="mt-1.5 grid gap-2 pl-5 sm:grid-cols-2" data-testid="firing-step-detail">
          <div className="min-w-0">
            <p className="mb-0.5 text-[11px] text-slate-500">Given</p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-900/80 p-2 text-[11px] text-slate-300">{show(a.input) || 'Nothing'}</pre>
          </div>
          <div className="min-w-0">
            <p className="mb-0.5 text-[11px] text-slate-500">Gave back, use it as {`{steps.${i + 1}.output}`}</p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-900/80 p-2 text-[11px] text-slate-300" data-testid="firing-step-output">{show(a.output) || 'Nothing'}</pre>
          </div>
        </div>
      )}
    </li>
  );
}

export function FiringRow({ f, showRule, now }: { f: Firing; showRule?: boolean; now: number }) {
  const failed = f.actions.filter((a) => a.status === 'failed').length;
  return (
    <li className="min-w-0 rounded-lg border border-slate-700/60 bg-slate-950/40 p-3 [overflow-wrap:anywhere]" data-testid="firing" data-status={f.status} data-firing-id={f.id}>
      <div className="flex flex-wrap items-center gap-2">
        {f.status === 'firing' ? (
          <Badge tone="rose">Firing now</Badge>
        ) : f.status === 'test' ? (
          <Badge tone="cyan">Test</Badge>
        ) : (
          <Badge tone="emerald">Cleared {f.cleared_at ? ago(f.cleared_at, now) : ''}</Badge>
        )}
        {failed > 0 && <Badge tone="amber">{failed} step{failed === 1 ? '' : 's'} failed</Badge>}
        <span className="inline-flex items-center gap-1 text-xs text-slate-400" title={dayTime(f.fired_at)}>
          <Clock className="h-3 w-3" /> {dayTime(f.fired_at)}, {ago(f.fired_at, now)}
        </span>
        {showRule && f.rule_id && (
          <Link href={`/telemetry/rules/${f.rule_id}`} className="ml-auto text-xs text-cyan-300 hover:underline">{f.rule}</Link>
        )}
      </div>
      <p className="mt-1.5 text-sm text-slate-100">{f.detail}</p>
      {f.value !== null && f.value !== undefined && f.signal && (
        <p className="mt-0.5 text-xs text-slate-500"><span className="font-mono">{f.signal}</span> = {Array.isArray(f.value) ? f.value.map((v) => fmt(v)).join(', ') : fmt(f.value)}</p>
      )}
      {f.actions.length > 0 ? (
        <ol className="mt-2 space-y-1" data-testid="firing-steps">
          {f.actions.map((a, i) => <StepRow key={i} a={a} i={i} />)}
        </ol>
      ) : (
        <p className="mt-2 text-xs text-slate-500">No steps. It was recorded and sent to webhooks as telemetry.rule_fired.</p>
      )}
    </li>
  );
}

export default function FiringHistory({ ruleId, showRule, now, emptyHint }: { ruleId?: string; showRule?: boolean; now: number; emptyHint?: string }) {
  const [status, setStatus] = useState('');
  const [limit, setLimit] = useState(30);
  const url = useMemo(() => {
    const q = new URLSearchParams({ limit: String(limit), include: 'outputs' });
    if (ruleId) q.set('rule_id', ruleId);
    if (status) q.set('status', status);
    return `/api/telemetry/rules/firings?${q.toString()}`;
  }, [ruleId, status, limit]);
  const res = useSWR(url, fetcher, { refreshInterval: 4000, revalidateOnFocus: false, keepPreviousData: true });
  const rows = Array.isArray(res.data?.data) ? (res.data!.data as Firing[]) : null;
  const error = res.data?.error || (res.error ? 'The firing history could not load.' : null);

  return (
    <div className="space-y-3" data-testid="firing-history">
      <div className="flex flex-wrap items-center gap-2">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Which firings" className="min-h-[36px] rounded-lg border border-slate-700 bg-slate-900 px-2 text-sm text-slate-200" data-testid="firings-status">
          <option value="">All firings</option>
          <option value="firing">Firing now</option>
          <option value="cleared">Cleared</option>
          <option value="test">Tests</option>
        </select>
        <button type="button" onClick={() => void res.mutate()} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-slate-700 px-3 text-xs text-slate-300 hover:bg-slate-800" aria-label="Refresh firings">
          <RefreshCw className={`h-3.5 w-3.5 ${res.isValidating ? 'animate-spin' : ''}`} /> Refresh
        </button>
        <span className="text-xs text-slate-500">Updates every few seconds.</span>
      </div>
      {error && !rows ? (
        <p className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-100" role="alert">{error}</p>
      ) : !rows ? (
        <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded-lg bg-slate-800/40" />)}</div>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-700 p-4 text-sm text-slate-400" data-testid="firings-empty">
          {status ? 'No firings of this kind.' : emptyHint || 'No firings yet. When a rule fires, each firing and what every step did shows here.'}
        </p>
      ) : (
        <>
          <ul className="space-y-2">{rows.map((f) => <FiringRow key={f.id} f={f} showRule={showRule} now={now} />)}</ul>
          {rows.length >= limit && (
            <button type="button" onClick={() => setLimit((l) => Math.min(500, l + 50))} className="min-h-[36px] w-full rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800" data-testid="firings-more">
              Show older firings
            </button>
          )}
        </>
      )}
    </div>
  );
}
