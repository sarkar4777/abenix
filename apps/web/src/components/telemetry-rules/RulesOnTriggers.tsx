'use client';

import Link from 'next/link';
import useSWR from 'swr';
import { ChevronRight, Zap } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { ago } from './lib';
import { Badge } from './ui';

interface Row { id: string; name: string; enabled: boolean; summary: string; runs: string[]; fire_count: number; last_fired_at: string | null; link: string }

function fetcher(url: string) {
  return apiFetch<Row[]>(url, { silent: true });
}

// signal rules start runs too, so the Triggers page lists them next to webhooks and schedules
export default function RulesOnTriggers() {
  const { perms } = useMyPermissions();
  const can = holds(perms?.capabilities, 'telemetry.view');
  const res = useSWR(can ? '/api/telemetry/rules/as-triggers/list' : null, fetcher, { revalidateOnFocus: false, refreshInterval: 30_000 });
  const rows = Array.isArray(res.data?.data) ? (res.data!.data as Row[]) : [];
  if (!can || !rows.length) return null;
  return (
    <section className="mt-8" data-testid="triggers-signal-rules">
      <div className="mb-3 flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-white">Signal rules</h2>
        <p className="text-xs text-slate-400">They fire on live telemetry and can run an agent or pipeline. Change them under Signal rules.</p>
        <Link href="/telemetry/rules" className="ml-auto text-xs text-cyan-300 hover:underline">All signal rules</Link>
      </div>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.id}>
            <Link href={`/telemetry/rules/${r.id}`} className="flex items-start gap-3 rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 hover:border-slate-600" data-testid="triggers-signal-rule">
              <Zap className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" aria-hidden />
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-white">{r.name}</span>
                  <Badge tone={r.enabled ? 'emerald' : 'slate'}>{r.enabled ? 'On' : 'Off'}</Badge>
                  {r.runs.length > 0 && <Badge tone="cyan">Runs {r.runs.join(', ')}</Badge>}
                </span>
                <span className="mt-0.5 block text-xs text-slate-400">{r.summary}</span>
                <span className="mt-0.5 block text-[11px] text-slate-500">
                  {r.fire_count ? `Fired ${r.fire_count} ${r.fire_count === 1 ? 'time' : 'times'}, last ${ago(r.last_fired_at)}` : 'Has not fired yet'}
                </span>
              </span>
              <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
