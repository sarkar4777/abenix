'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChevronDown, ChevronRight, EyeOff, Loader2 } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import ProposeButton from '@/components/improvements/proposals/ProposeButton';
import { SeverityPill, TrendBars } from './TrendBars';
import { improvementsApi, plural, type ClusterRow, type LessonRow } from '@/lib/improvements';
import { relTime } from '@/lib/autonomy';

const STATE_TEXT: Record<string, string> = {
  proposing: 'A fix is being drafted',
  proposed: 'A fix is proposed',
  fixed: 'Fixed',
  dismissed: 'Dismissed',
};

function clamp(s: string | null | undefined, n = 220): string {
  const t = (s || '').replace(/\s+/g, ' ').trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

export function LessonItem({ lesson }: { lesson: LessonRow }) {
  return (
    <li className="rounded-lg border border-slate-800 bg-slate-950/40 p-2.5 text-xs" data-testid="improvement-lesson" data-source={lesson.source}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-500">
        <span className={lesson.polarity === 'positive' ? 'text-emerald-300' : 'text-amber-300'}>{lesson.source_label}</span>
        {lesson.by_user_name && <span>by {lesson.by_user_name}</span>}
        {lesson.created_at && <span>{relTime(lesson.created_at)}</span>}
        {lesson.execution_id && (
          <Link href={`/executions/${lesson.execution_id}`} className="text-cyan-300 hover:underline">View run</Link>
        )}
      </div>
      {lesson.input_text && <p className="mt-1 break-words text-slate-200"><span className="text-slate-500">Asked: </span>{clamp(lesson.input_text)}</p>}
      {lesson.output_text && <p className="mt-0.5 break-words text-slate-400"><span className="text-slate-500">It said: </span>{clamp(lesson.output_text, 160)}</p>}
      {lesson.expected && <p className="mt-0.5 break-words text-emerald-200/90"><span className="text-slate-500">Should be: </span>{clamp(lesson.expected)}</p>}
      {lesson.note && <p className="mt-0.5 break-words text-slate-300"><span className="text-slate-500">Note: </span>{clamp(lesson.note)}</p>}
    </li>
  );
}

export default function ClusterCard({ cluster, canManage, onChanged }: { cluster: ClusterRow; canManage: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [lessons, setLessons] = useState<LessonRow[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [dismissOpen, setDismissOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load(before?: string | null) {
    setLoading(true);
    setLoadErr(null);
    const r = await improvementsApi.cluster(cluster.id, before);
    setLoading(false);
    if (r.error || !r.data) { setLoadErr(r.error || 'The lessons did not load.'); return; }
    setLessons((prev) => (before && prev ? [...prev, ...r.data!.lessons] : r.data!.lessons));
    setNext(r.data.next_before);
  }

  function toggle() {
    const v = !open;
    setOpen(v);
    if (v && lessons === null) load();
  }

  async function dismiss() {
    setBusy(true);
    setErr(null);
    const r = await improvementsApi.dismiss(cluster.id, reason.trim());
    setBusy(false);
    if (r.error) { setErr(r.error); return; }
    setDismissOpen(false);
    onChanged();
  }

  const stateText = STATE_TEXT[cluster.state];
  return (
    <article className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4" data-testid="improvement-cluster" data-cluster-id={cluster.id}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityPill severity={cluster.severity} />
            <span className="text-xs text-slate-400" data-testid="improvement-cluster-count">{plural(cluster.negative_count, 'lesson')}</span>
            {stateText && <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-200">{stateText}</span>}
          </div>
          <h3 className="mt-1.5 break-words text-sm font-semibold text-white" data-testid="improvement-cluster-title">{cluster.title}</h3>
          {cluster.summary && <p className="mt-0.5 text-[11px] text-slate-500">{cluster.summary}</p>}
        </div>
        <div className="shrink-0"><TrendBars values={cluster.trend} /></div>
      </div>

      {cluster.examples.length > 0 && (
        <ul className="mt-3 space-y-2">
          {cluster.examples.map((l) => <LessonItem key={l.id} lesson={l} />)}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {canManage && <ProposeButton cluster={cluster} />}
        {cluster.negative_count > cluster.examples.length && (
          <button type="button" onClick={toggle} className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 hover:border-slate-500" aria-expanded={open} data-testid="improvement-cluster-all">
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} All {plural(cluster.negative_count, 'lesson')}
          </button>
        )}
        {canManage && cluster.state === 'open' && (
          <button type="button" onClick={() => setDismissOpen(true)} className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs text-slate-400 hover:text-slate-200" data-testid="improvement-cluster-dismiss">
            <EyeOff className="h-3.5 w-3.5" /> Not a problem
          </button>
        )}
      </div>
      {!canManage && (
        <p className="mt-2 text-[11px] text-slate-500">Only the agent&apos;s owner, or someone with the improvements.propose permission, can act on this.</p>
      )}

      {open && (
        <div className="mt-3" data-testid="improvement-cluster-lessons">
          {loadErr ? (
            <p className="text-xs text-rose-300" role="alert">Could not load the lessons: {loadErr}. <button type="button" className="underline" onClick={() => load()}>Try again</button></p>
          ) : lessons === null ? (
            <div className="h-16 animate-pulse rounded-lg bg-slate-800/50" />
          ) : (
            <>
              <ul className="space-y-2">{lessons.map((l) => <LessonItem key={l.id} lesson={l} />)}</ul>
              {next && (
                <button type="button" disabled={loading} onClick={() => load(next)} className="mt-2 inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline disabled:opacity-50">
                  {loading && <Loader2 className="h-3 w-3 animate-spin" />} Show older lessons
                </button>
              )}
            </>
          )}
        </div>
      )}

      <ConfirmModal
        open={dismissOpen}
        onClose={() => setDismissOpen(false)}
        onConfirm={dismiss}
        title="Mark this as not a problem?"
        description="The group closes and no fix is proposed for it. New lessons still count toward it, so you can see if it comes back."
        confirmLabel="Dismiss"
        variant="warning"
        loading={busy}
        confirmDisabled={!reason.trim()}
        confirmTestId="improvement-cluster-dismiss-confirm"
        icon={EyeOff}
      >
        <label htmlFor={`dismiss-${cluster.id}`} className="text-xs font-medium text-slate-300">Why does it not need fixing?</label>
        <textarea id={`dismiss-${cluster.id}`} rows={3} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-sm text-white" data-testid="improvement-cluster-dismiss-reason" />
        {err && <p className="mt-1 text-xs text-rose-300" role="alert">{err}</p>}
      </ConfirmModal>
    </article>
  );
}
