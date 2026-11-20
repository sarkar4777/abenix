'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  AlertTriangle, ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, Loader2, Play, RotateCcw, ShieldAlert,
} from 'lucide-react';

import { DraftPanel, SentPanel } from '@/components/DraftPanel';
import { EarlierDrafts, EscalationPanel, History } from '@/components/Panels';
import { ClarificationChoices, LinesTable, StepTracker } from '@/components/RunView';
import { StatusBadge } from '@/components/StatusBadge';
import { api, refreshAll, type Email } from '@/lib/api';
import { clock, splitSender } from '@/lib/format';
import { POLL_MS, usePoll } from '@/lib/usePoll';
import { toastError, toastSuccess } from '@/stores/toastStore';

function Card({ title, children, right, testId }: {
  title: string; children: React.ReactNode; right?: React.ReactNode; testId?: string;
}) {
  return (
    <section className="min-w-0 rounded-xl bg-slate-900/60 ring-1 ring-slate-800" data-testid={testId}>
      <div className="px-4 py-2.5 border-b border-slate-800 flex items-center gap-2">
        <h2 className="text-[11px] uppercase tracking-wider text-slate-400">{title}</h2>
        {right && <div className="ml-auto">{right}</div>}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

export default function EmailPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params?.id ?? '');
  const router = useRouter();
  const load = useCallback(() => api.email(id), [id]);
  const { data: email, error, status } = usePoll<Email>(load, POLL_MS, id);

  // ← and → move between emails, unless the reviewer is typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest('input, textarea, [role="dialog"]') || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'ArrowLeft' && email?.prev_id) router.push(`/emails/${encodeURIComponent(email.prev_id)}`);
      if (e.key === 'ArrowRight' && email?.next_id) router.push(`/emails/${encodeURIComponent(email.next_id)}`);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [email?.prev_id, email?.next_id, router]);

  if (status === 404) {
    return (
      <main className="mx-auto max-w-3xl p-8 text-center text-slate-400">
        No email with the id “{id}”. <Link href="/" className="text-sky-300">Back to the inbox</Link>
      </main>
    );
  }
  if (!email) {
    return (
      <main className="mx-auto max-w-3xl p-8 text-center text-slate-400">
        {error ?? <Loader2 className="w-5 h-5 animate-spin inline" />}
      </main>
    );
  }

  const [person, company] = splitSender(email.from_name);
  const draft = email.drafts.at(-1) ?? null;
  // Escalated or being redrafted, the last draft is history too.
  const showDraft = Boolean(draft) && email.status !== 'escalated' && email.review !== 'redrafting';
  const earlier = showDraft ? email.drafts.slice(0, -1) : email.drafts;

  return (
    <main className="mx-auto max-w-[96rem] px-4 sm:px-6 py-5 space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Link href="/" className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-white" data-testid="back">
          <ArrowLeft className="w-4 h-4" /> Inbox
        </Link>
        <h1 className="min-w-0 flex-1 truncate text-lg font-semibold text-white">
          {email.subject} <span className="font-normal text-slate-400">· {person}{company && `, ${company}`}</span>
        </h1>
        <nav className="flex items-center gap-1" aria-label="Move between emails">
          <NavButton id={email.prev_id} label="prev" />
          <NavButton id={email.next_id} label="next" />
        </nav>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <StatusBadge status={email.status} review={email.review} long />
        <ProcessButton email={email} />
        {email.run_url && (
          <a href={email.run_url} target="_blank" rel="noreferrer" data-testid="run-link"
            className="ml-auto inline-flex items-center gap-1 text-xs text-sky-300 hover:text-sky-200">
            Open run in Abenix <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,4fr)_minmax(0,9fr)] items-start">
        <Card title="The email, as received" testId="received">
          {/* Monospace, as a mail client shows plain text, so the customers' column layouts line up. */}
          <pre className="whitespace-pre overflow-x-auto font-mono text-[12px] text-slate-300 leading-relaxed" data-testid="received-text">
            {email.received_text}
          </pre>
        </Card>

        <div className="space-y-4 min-w-0">
          <Card title="Progress"><StepTracker email={email} /></Card>
          {email.status !== 'waiting' && <Card title="Lines" testId="lines"><LinesTable email={email} /></Card>}
          <StatePanel email={email} />
          {draft && showDraft && (
            <Card title={email.review === 'sent' ? 'Email sent' : 'Draft email'}>
              {email.review === 'sent' && draft.sent ? <SentPanel draft={draft} /> : <DraftPanel key={draft.n} email={email} draft={draft} />}
            </Card>
          )}
          {earlier.length > 0 && <Card title="Earlier drafts"><EarlierDrafts drafts={earlier} /></Card>}
          <Card title="History"><History email={email} /></Card>
        </div>
      </div>
    </main>
  );
}

/** Send this email to the pipeline. Only a waiting email can be processed. */
function ProcessButton({ email }: { email: Email }) {
  const [busy, setBusy] = useState(false);
  const waiting = email.status === 'waiting';
  const process = async () => {
    setBusy(true);
    const r = await api.process(email.id);
    setBusy(false);
    if (r.error) toastError(r.error);
    refreshAll();
  };
  const why = email.status === 'processing' ? 'This email is being processed'
    : waiting ? 'Send this email to the RFQ pipeline' : 'This email has been processed';
  return (
    <button onClick={() => void process()} disabled={!waiting || busy} title={why} data-testid="process-email"
      className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 px-3 py-1 text-xs font-semibold disabled:bg-slate-800 disabled:text-slate-500 disabled:cursor-not-allowed">
      {busy || email.status === 'processing' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
      Process
    </button>
  );
}

function NavButton({ id, label }: { id: string | null; label: 'prev' | 'next' }) {
  const Icon = label === 'prev' ? ChevronLeft : ChevronRight;
  const cls = 'inline-flex items-center gap-0.5 rounded-lg px-2 py-1 text-sm';
  if (!id) return <span className={`${cls} text-slate-700`}>{label === 'prev' && <Icon className="w-4 h-4" />}{label}{label === 'next' && <Icon className="w-4 h-4" />}</span>;
  return (
    <Link href={`/emails/${encodeURIComponent(id)}`} className={`${cls} text-slate-300 hover:bg-slate-800`} data-testid={label}
      title={`${label === 'prev' ? 'Previous' : 'Next'} email (${label === 'prev' ? '←' : '→'})`}>
      {label === 'prev' && <Icon className="w-4 h-4" />}{label}{label === 'next' && <Icon className="w-4 h-4" />}
    </Link>
  );
}

/** What the right-hand side shows besides the draft, by state. */
function StatePanel({ email }: { email: Email }) {
  const [retrying, setRetrying] = useState(false);
  const draft = email.drafts.at(-1);

  if (email.status === 'waiting') {
    return (
      <p className="rounded-xl bg-slate-900/60 ring-1 ring-slate-800 px-4 py-3 text-sm text-slate-400">
        Waiting to be processed. Press <span className="text-slate-200">Process</span> above to send it to the RFQ
        pipeline now, or let <Link href="/" className="text-sky-300">Process next RFQ email</Link> reach it in turn.
      </p>
    );
  }

  if (email.status === 'system_error') {
    const retry = async () => {
      setRetrying(true);
      const r = await api.retry(email.id);
      setRetrying(false);
      if (r.error) toastError(r.error);
      else toastSuccess(email.error_step === 'redraft' ? 'Redrafting again.' : 'Sent to the pipeline again.');
      refreshAll();
    };
    return (
      <div className="rounded-xl bg-rose-500/5 ring-1 ring-rose-500/30 p-4 flex flex-wrap items-start gap-3" data-testid="error-panel">
        <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
        <div className="flex-1 min-w-[14rem]">
          <div className="text-sm font-semibold text-white">
            System error in the {email.error_step === 'redraft' ? 'redraft' : 'pipeline run'}
          </div>
          <p className="text-sm text-rose-200/90 mt-1 [overflow-wrap:anywhere]">{email.error}</p>
        </div>
        <button onClick={() => void retry()} disabled={retrying} data-testid="retry"
          className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 px-3 py-1.5 text-sm font-medium disabled:opacity-50">
          {retrying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
          Retry {email.error_step === 'redraft' ? 'the redraft' : 'the pipeline'}
        </button>
      </div>
    );
  }

  if (email.status === 'escalated') {
    if (email.escalation) return <EscalationPanel email={email} />;
    const decision = draft?.decision;
    return (
      <div className="rounded-xl bg-violet-500/5 ring-1 ring-violet-500/25 p-4 space-y-1" data-testid="reviewer-escalation">
        <div className="flex items-center gap-2 text-sm font-semibold text-white">
          <ShieldAlert className="w-4 h-4 text-violet-300" /> Escalated by {decision?.by ?? 'the reviewer'}
          {decision && !decision.in_app && <span className="font-normal text-slate-400">in Abenix</span>}
          {decision?.at && <span className="font-normal text-slate-500 text-xs">{clock(decision.at)}</span>}
        </div>
        {decision?.note && <p className="text-sm text-slate-200">“{decision.note}”</p>}
        <p className="text-xs text-slate-500">Nothing was sent to the customer. The last draft is under Earlier drafts.</p>
      </div>
    );
  }

  if (email.review === 'redrafting') {
    return (
      <div className="rounded-xl bg-amber-500/5 ring-1 ring-amber-500/25 p-4 text-sm" data-testid="redrafting">
        <div className="flex items-center gap-2 text-amber-100">
          <Loader2 className="w-4 h-4 animate-spin" /> Drafting a new clarification from your note…
        </div>
        {email.redraft?.note && <p className="mt-1 text-slate-300">“{email.redraft.note}”</p>}
      </div>
    );
  }

  if (email.status === 'clarification' && email.review !== 'sent') {
    const hasChoices = email.lines.some((l) => l.outcome === 'needs_clarification');
    return hasChoices ? <Card title="Choices to offer the customer"><ClarificationChoices email={email} /></Card> : null;
  }
  return null;
}
