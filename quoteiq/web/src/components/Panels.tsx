'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, Lock, ShieldAlert } from 'lucide-react';

import type { Draft, Email } from '@/lib/api';
import { OUTCOME_LABEL, asText, clock } from '@/lib/format';

/** The pipeline's escalation: internal, with the SKUs staff need. */
export function EscalationPanel({ email }: { email: Email }) {
  const esc = email.escalation;
  if (!esc) return null;
  return (
    <div className="rounded-lg bg-violet-500/5 ring-1 ring-violet-500/25 p-4 space-y-3" data-testid="escalation-panel">
      <div className="flex items-center gap-2">
        <ShieldAlert className="w-4 h-4 text-violet-300" />
        <span className="text-sm font-semibold text-white">Escalated to staff</span>
        <span className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider bg-slate-800 text-slate-300">
          <Lock className="w-3 h-3" /> Internal, not sent to the customer
        </span>
      </div>
      {esc.summary && <p className="text-sm text-slate-200">{esc.summary}</p>}
      <ul className="space-y-2">
        {(esc.items ?? []).map((item, i) => (
          <li key={i} className="rounded-md bg-slate-950/50 ring-1 ring-slate-800 p-3 text-xs space-y-1">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-slate-100 whitespace-pre-wrap">{item.customer_reference}</span>
              {item.outcome && (
                <span className="text-slate-400">
                  {OUTCOME_LABEL[item.outcome as keyof typeof OUTCOME_LABEL] ?? item.outcome}
                </span>
              )}
              {item.skus && item.skus.length > 0 && (
                <span className="font-mono text-violet-200">{item.skus.join(', ')}</span>
              )}
            </div>
            {item.reason && <div className="text-slate-300">{item.reason}</div>}
            {item.problem && <div className="text-rose-200">{item.problem}</div>}
            {item.nearest_products && item.nearest_products.length > 0 && (
              <div className="text-slate-400">
                Nearest products:
                <ul className="mt-1 space-y-0.5">
                  {item.nearest_products.map((p, j) => (
                    <li key={j}>
                      <span className="font-mono text-slate-500 mr-2">{p.sku}</span>
                      <span className="text-slate-300">{asText(p.name ?? p.standard_part_number)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

const DECISION_WORDS = { send: 'sent it', ask: 'asked the customer instead', escalate: 'escalated it' };

/** Drafts before the current one, with what the reviewer decided. */
export function EarlierDrafts({ drafts }: { drafts: Draft[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!drafts.length) return null;
  return (
    <ul className="space-y-1.5 text-xs" data-testid="earlier-drafts">
      {drafts.map((d) => (
        <li key={d.n}>
          <button onClick={() => setOpen(open === d.n ? null : d.n)} className="inline-flex items-start gap-1 text-left text-slate-300 hover:text-white">
            {open === d.n ? <ChevronDown className="w-3.5 h-3.5 mt-px shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 mt-px shrink-0" />}
            <span>
              Draft {d.n}, {d.kind === 'redraft' ? 'redrafted clarification' : d.kind}
              {d.decision && <>: {d.decision.by} {DECISION_WORDS[d.decision.action]}{d.decision.note && <> (“{d.decision.note}”)</>}</>}
              {!d.decision && d.approval?.status && d.approval.status !== 'pending' && <>: review {d.approval.status}</>}
            </span>
          </button>
          {open === d.n && (
            <pre className="mt-1.5 ml-5 whitespace-pre-wrap rounded-md bg-slate-950/50 ring-1 ring-slate-800 p-3 text-slate-300 font-sans">
              {d.ai.subject}{'\n\n'}{d.ai.greeting}{'\n\n'}{d.ai.body}{'\n\n'}{d.ai.closing}
            </pre>
          )}
        </li>
      ))}
    </ul>
  );
}

export function History({ email }: { email: Email }) {
  if (!email.history.length) return <p className="text-xs text-slate-500">Nothing has happened to this email yet.</p>;
  return (
    <ol className="space-y-1 text-xs" data-testid="history">
      {email.history.map((h, i) => (
        <li key={i} className="flex gap-3">
          <span className="text-slate-500 tabular-nums w-24 shrink-0">{clock(h.at)}</span>
          <span className="text-slate-300">{h.summary}</span>
        </li>
      ))}
    </ol>
  );
}
