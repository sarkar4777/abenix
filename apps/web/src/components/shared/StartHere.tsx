'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, CheckCircle2, Compass, Loader2, PartyPopper, X } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';

export interface JourneyStep {
  id: string;
  title: string;
  why: string;
  href: string;
  cta: string;
  done: boolean;
}

export interface Journey {
  role: 'admin' | 'builder' | 'member';
  steps: JourneyStep[];
  done: number;
  total: number;
  complete: boolean;
  dismissed: boolean;
}

export const JOURNEY_PATH = '/api/me/journey';

const ROLE_LINE: Record<Journey['role'], string> = {
  admin: 'Set up the workspace so your team can build and use agents safely.',
  builder: 'Build an agent, prove it works, then let others rely on it.',
  member: 'Get to know the agents your team has built.',
};

function celebratedKey(role: string) {
  return `startHere.celebrated.${role}`;
}

function readFlag(key: string) {
  try {
    return localStorage.getItem(key) === '1';
  } catch {
    return false;
  }
}

function writeFlag(key: string) {
  try {
    localStorage.setItem(key, '1');
  } catch {
    // storage blocked, the celebration may show once more
  }
}

// Role-aware first steps, every tick comes from the server's real data.
export default function StartHere() {
  const { data, error, isLoading, mutate } = useApi<Journey>(JOURNEY_PATH);
  const [local, setLocal] = useState<Journey | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [celebrated, setCelebrated] = useState(true);
  const j = local ?? data;

  // fresh server data wins over what the last save returned
  useEffect(() => setLocal(null), [data]);

  useEffect(() => {
    if (j?.complete) setCelebrated(readFlag(celebratedKey(j.role)));
  }, [j?.complete, j?.role]);

  const setDismissed = async (dismissed: boolean) => {
    setSaving(true);
    setSaveError(null);
    const r = await apiFetch<Journey>(JOURNEY_PATH, {
      method: 'PUT',
      body: JSON.stringify({ dismissed }),
      silent: true,
      throwOnError: false,
    });
    setSaving(false);
    if (r.data) {
      setLocal(r.data);
      mutate();
    } else {
      setSaveError('Could not save that. Try again.');
    }
  };

  if (isLoading && !j) {
    return <div className="h-24 animate-pulse rounded-xl bg-slate-800/40" data-testid="start-here-loading" />;
  }
  if (!j) {
    if (!error) return null;
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-700/50 bg-slate-800/30 p-3 text-sm text-slate-400" data-testid="start-here-error">
        <span>Could not load your first steps.</span>
        <button type="button" onClick={() => mutate()} className="text-cyan-300 underline hover:text-cyan-200">
          Try again
        </button>
      </div>
    );
  }
  if (j.steps.length === 0) return null;

  if (j.dismissed) {
    return (
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setDismissed(false)}
          disabled={saving}
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-cyan-300 disabled:opacity-50"
          data-testid="start-here-restore"
        >
          <Compass className="h-3.5 w-3.5" /> Show the Start here guide
        </button>
      </div>
    );
  }

  if (j.complete) {
    if (celebrated) return null;
    return (
      <section className="flex flex-wrap items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4" data-testid="start-here-complete" role="status">
        <PartyPopper className="h-6 w-6 shrink-0 text-emerald-300" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-emerald-100">You did every first step. Nice work.</p>
          <p className="text-xs text-emerald-200/80">The guide steps aside now. Help and Docs are always in the menu.</p>
        </div>
        <button
          type="button"
          onClick={() => {
            writeFlag(celebratedKey(j.role));
            setCelebrated(true);
          }}
          className="rounded-lg border border-emerald-500/40 px-3 py-1.5 text-xs text-emerald-100 hover:bg-emerald-500/20"
          data-testid="start-here-complete-close"
        >
          Close
        </button>
      </section>
    );
  }

  const pct = Math.round((j.done / Math.max(1, j.total)) * 100);
  const next = j.steps.find((s) => !s.done);

  return (
    <section className="min-w-0 rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4" data-testid="start-here" data-role={j.role}>
      <div className="flex items-start gap-3">
        <Compass className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-white">Start here</h2>
          <p className="text-xs text-slate-400">{ROLE_LINE[j.role]}</p>
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          disabled={saving}
          aria-label="Hide the Start here guide"
          title="Hide this guide. You can bring it back from the dashboard."
          className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-white disabled:opacity-50"
          data-testid="start-here-dismiss"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
        </button>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <div
          className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={j.total}
          aria-valuenow={j.done}
          aria-label="First steps done"
          data-testid="start-here-progress"
        >
          <div className="h-full rounded-full bg-cyan-400 transition-all" style={{ width: `${pct}%` }} />
        </div>
        <span className="shrink-0 text-xs text-slate-400">
          {j.done} of {j.total} done
        </span>
      </div>
      {saveError && <p className="mt-2 text-xs text-rose-300" role="alert">{saveError}</p>}

      <ol className="mt-3 space-y-2">
        {j.steps.map((s, i) => {
          const isNext = next?.id === s.id;
          return (
            <li
              key={s.id}
              className={`flex min-w-0 flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center ${isNext ? 'border-cyan-500/40 bg-slate-900/60' : 'border-slate-700/40 bg-slate-900/30'}`}
              data-testid={`start-here-${s.id}`}
              data-done={s.done ? 'true' : 'false'}
            >
              <div className="flex min-w-0 flex-1 items-start gap-2.5">
                {s.done ? (
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" aria-label="Done" />
                ) : (
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-slate-600 text-[11px] text-slate-400" aria-label="Not done yet">
                    {i + 1}
                  </span>
                )}
                <div className="min-w-0">
                  <p className={`break-words text-sm font-medium ${s.done ? 'text-slate-400 line-through decoration-slate-600' : 'text-white'}`}>{s.title}</p>
                  <p className="break-words text-xs text-slate-400">{s.why}</p>
                </div>
              </div>
              <Link
                href={s.href}
                className={`inline-flex shrink-0 items-center justify-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium ${
                  s.done
                    ? 'text-slate-400 hover:text-cyan-300'
                    : isNext
                      ? 'bg-cyan-500 text-white hover:bg-cyan-400'
                      : 'border border-slate-700 text-slate-200 hover:bg-slate-800'
                }`}
                data-testid={`start-here-${s.id}-go`}
              >
                {s.done ? 'Open' : s.cta} <ArrowRight className="h-3 w-3" />
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
