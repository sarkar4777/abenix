'use client';

import { Fragment, useEffect, useState } from 'react';
import { CheckCircle2, ChevronDown, ChevronRight, Circle, Loader2, XCircle } from 'lucide-react';

import type { Email, Line, Price, StepState } from '@/lib/api';
import {
  COLOUR_CODES, OUTCOME_LABEL, OUTCOME_TONE, asText, keyLabel, leadTime, money, qty, seconds, unit, valueLabel,
} from '@/lib/format';

// ── the step tracker ─────────────────────────────────────────────────────

function StepIcon({ state }: { state: StepState }) {
  if (state === 'done') return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
  if (state === 'running') return <Loader2 className="w-3.5 h-3.5 text-sky-300 animate-spin" />;
  if (state === 'failed') return <XCircle className="w-3.5 h-3.5 text-rose-400" />;
  return <Circle className="w-3.5 h-3.5 text-slate-600" />;
}

/** extract → search n/N → decide → draft (or escalate), live while the run goes. */
export function StepTracker({ email }: { email: Email }) {
  const run = email.run;
  const [now, setNow] = useState(Date.now());
  const running = email.status === 'processing';
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  if (!run) {
    return <p className="text-xs text-slate-500">{running ? 'Starting the run…' : 'Not processed yet.'}</p>;
  }
  const steps = run.steps ?? {};
  const finished = email.lines.length;
  const searchNote = running
    ? `${run.lines_done || 0} line${run.lines_done === 1 ? '' : 's'} searched`
    : finished ? `${finished}/${finished}` : '';
  const lastStep = steps.escalation && steps.escalation !== 'skipped' && steps.escalation !== 'pending'
    ? { key: 'escalation', label: 'escalate' }
    : { key: 'draft_email', label: 'draft' };
  const items = [
    { key: 'extract', label: 'extract' },
    { key: 'search', label: 'search', note: searchNote },
    { key: 'decide', label: 'decide' },
    lastStep,
  ];
  const elapsed = run.duration_ms
    ?? (run.started_at ? (run.finished_at ? Date.parse(run.finished_at) : now) - Date.parse(run.started_at) : null);

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs" data-testid="step-tracker">
      {items.map((step, i) => (
        <Fragment key={step.key}>
          {i > 0 && <span className="text-slate-600">→</span>}
          <span className={`inline-flex items-center gap-1 ${steps[step.key] === 'running' ? 'text-sky-200' : 'text-slate-300'}`}>
            {step.label}
            {'note' in step && step.note && <span className="text-slate-400 tabular-nums">{step.note}</span>}
            <StepIcon state={steps[step.key] ?? 'pending'} />
          </span>
        </Fragment>
      ))}
      {elapsed !== null && elapsed >= 0 && (
        <span className="ml-auto text-slate-500 tabular-nums">{seconds(elapsed)}</span>
      )}
    </div>
  );
}

// ── the lines ────────────────────────────────────────────────────────────

function Prices({ line }: { line: Line }) {
  const p = line.pricing;
  const prices = p?.prices ?? [];
  if (!prices.length) return null;
  const u = unit(p?.uom);
  return (
    <div className="space-y-0.5">
      {prices.map((price: Price, i) => (
        <div key={i} className="grid grid-cols-[4.5rem_5.5rem_6rem] justify-end gap-2 tabular-nums">
          <span className="text-right">
            {qty(price.quoted_qty)} {u}{price.moq_applied && <span className="text-amber-300">*</span>}
          </span>
          <span className="text-right text-slate-300">
            {money(price.net_unit_price, p?.currency, true)}
          </span>
          <span className="text-right text-white">{money(price.line_total, p?.currency)}</span>
        </div>
      ))}
    </div>
  );
}

function Chips({ data }: { data?: Record<string, unknown> | null }) {
  const entries = Object.entries(data ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (!entries.length) return <span className="text-slate-600">none</span>;
  return (
    <span className="flex flex-wrap gap-1.5">
      {entries.map(([k, v]) => (
        <span key={k} className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px]">
          <span className="text-slate-500">{keyLabel(k)}</span> <span className="text-slate-200">{valueLabel(k, v)}</span>
        </span>
      ))}
    </span>
  );
}

function ProductRef({ p }: { p: { sku?: string; name?: string; standard_part_number?: string | null } }) {
  return (
    <li className="text-slate-300">
      {p.sku && <span className="font-mono text-[11px] text-slate-500 mr-2">{p.sku}</span>}
      {asText(p.name ?? p.standard_part_number)}
    </li>
  );
}

/** What the matcher understood, the filters it sent, and what came back. */
function HowMatched({ line }: { line: Line }) {
  return (
    <div className="space-y-2 text-xs" data-testid={`how-${line.line_ref}`}>
      <div className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-2">
        <span className="text-slate-500">Understood</span><Chips data={line.understood} />
        <span className="text-slate-500">Filters sent</span><Chips data={line.filters} />
        {typeof line.candidates_total === 'number' && (
          <>
            <span className="text-slate-500">Fitted</span>
            <span className="text-slate-300">
              {line.candidates_total} product{line.candidates_total === 1 ? '' : 's'}
            </span>
          </>
        )}
        {line.product?.sku && (
          <>
            <span className="text-slate-500">Product</span>
            <ul><ProductRef p={line.product} /></ul>
          </>
        )}
        {line.differs_on && Object.keys(line.differs_on).length > 0 && (
          <>
            <span className="text-slate-500">They differ on</span>
            <Chips data={line.differs_on} />
          </>
        )}
        {line.problem && (
          <>
            <span className="text-slate-500">Record problem</span>
            <span className="text-rose-200">{line.problem}</span>
          </>
        )}
        {line.skus && line.skus.length > 0 && !line.product?.sku && (
          <>
            <span className="text-slate-500">Records</span>
            <span className="font-mono text-slate-300">{line.skus.join(', ')}</span>
          </>
        )}
        {line.nearest && line.nearest.length > 0 && (
          <>
            <span className="text-slate-500">Nearest products</span>
            <ul className="space-y-0.5">{line.nearest.map((p, i) => <ProductRef key={i} p={p} />)}</ul>
          </>
        )}
        {line.reason && (
          <>
            <span className="text-slate-500">Reason</span>
            <span className="text-slate-300">{line.reason}</span>
          </>
        )}
      </div>
    </div>
  );
}

export function LinesTable({ email }: { email: Email }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const lines = email.lines;
  if (!lines.length) {
    return (
      <p className="text-xs text-slate-500">
        {email.status === 'processing'
          ? `The lines appear when the run finishes. ${email.run?.lines_done || 0} searched so far.`
          : 'No lines.'}
      </p>
    );
  }
  const raised = lines.flatMap((l) => (l.pricing?.prices ?? []).filter((p) => p.moq_applied).map((p) => ({ l, p })));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="text-left font-medium py-2 pr-2 w-6">#</th>
            <th className="text-left font-medium py-2 pr-3">Customer reference</th>
            <th className="text-left font-medium py-2 pr-3">Outcome</th>
            <th className="text-left font-medium py-2 pr-3">Product</th>
            <th className="text-right font-medium py-2 pr-1">
              <div className="grid grid-cols-[4.5rem_5.5rem_6rem] justify-end gap-2">
                <span>Qty</span><span>Net / unit</span><span>Total</span>
              </div>
            </th>
            <th className="text-right font-medium py-2 pl-3">Lead time</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const isOpen = Boolean(open[line.line_ref]);
            const product = line.product;
            return (
              <Fragment key={line.line_ref}>
                <tr className="border-t border-slate-800/70 align-top" data-testid={`line-${line.line_ref}`}>
                  <td className="py-2 pr-2 text-slate-500 tabular-nums">{line.line_ref}</td>
                  <td className="py-2 pr-3 min-w-[11rem] max-w-[18rem]">
                    <div className="text-slate-100 whitespace-pre-wrap [overflow-wrap:anywhere]">{line.customer_reference}</div>
                    <button onClick={() => setOpen({ ...open, [line.line_ref]: !isOpen })}
                      className="mt-1 inline-flex items-center gap-0.5 text-[11px] text-sky-300/80 hover:text-sky-200"
                      data-testid={`toggle-how-${line.line_ref}`}>
                      {isOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      How it was matched
                    </button>
                  </td>
                  <td className="py-2 pr-3">
                    <span className={`inline-block rounded px-1.5 py-0.5 ring-1 text-[11px] leading-snug ${OUTCOME_TONE[line.outcome]}`}>
                      {OUTCOME_LABEL[line.outcome]}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-slate-300 min-w-[10rem]">
                    {product?.name ? asText(product.name) : <span className="text-slate-600">–</span>}
                    {product?.standard_part_number && (
                      <div className="text-[11px] text-slate-500">{product.standard_part_number}</div>
                    )}
                  </td>
                  <td className="py-2 pr-1"><Prices line={line} /></td>
                  <td className="py-2 pl-3 text-right text-slate-300 whitespace-nowrap">
                    {line.pricing ? leadTime(line.pricing.lead_time_days) : ''}
                  </td>
                </tr>
                {isOpen && (
                  <tr className="bg-slate-950/40">
                    <td />
                    <td colSpan={5} className="py-3 pr-3"><HowMatched line={line} /></td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {raised.length > 0 && (
        <ul className="mt-2 text-[11px] text-slate-400 space-y-0.5">
          {raised.map(({ l, p }, i) => (
            <li key={i}>
              <span className="text-amber-300">*</span> Line {l.line_ref} raised to the minimum order quantity
              ({qty(l.pricing?.moq)} {unit(l.pricing?.uom)})
              {p.requested_qty ? `. ${qty(p.requested_qty)} ${unit(l.pricing?.uom)} was asked for` : '. No quantity was given'}.
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** For a clarification: what each unclear line could be, as the customer will be asked. */
export function ClarificationChoices({ email }: { email: Email }) {
  const unclear = email.lines.filter((l) => l.outcome === 'needs_clarification');
  if (!unclear.length) return null;
  return (
    <div className="space-y-2" data-testid="clarification-choices">
      {unclear.map((line) => (
        <div key={line.line_ref} className="rounded-lg bg-amber-500/5 ring-1 ring-amber-500/20 p-3 text-xs">
          <div className="text-amber-200">
            Line {line.line_ref}: {line.candidates_total ?? 'several'} products fit “{line.customer_reference}”
          </div>
          <div className="mt-2 space-y-1">
            {Object.entries(line.differs_on ?? {}).map(([k, values]) => (
              <div key={k} className="flex gap-2">
                <span className="text-slate-500 w-24 shrink-0">{keyLabel(k)}</span>
                <span className="text-slate-200">
                  {(Array.isArray(values) ? values : [values]).map((v) => (k === 'colour_code' && COLOUR_CODES[String(v)]
                    ? COLOUR_CODES[String(v)] : String(v))).join(', ')}
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
