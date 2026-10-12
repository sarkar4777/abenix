'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, CheckCircle2, Loader2, Send, ShieldAlert } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { apiFetch } from '@/lib/api-client';
import { WRITABLE, commandPreview, datatypeFor, kindFor, parseValue, type WritableMetric } from '@/lib/telemetry/command';
import { explainTelemetryError, reasonProblem, REASON_MIN } from '@/lib/telemetry/errors';
import { clock, deviceKey, formatValue, splitMetric } from '@/lib/telemetry/format';
import { useTelemetry } from '@/lib/telemetry/store';
import type { Metric, MetricValue } from '@/lib/telemetry/types';

type Step = 'form' | 'confirm' | 'sent';

// signals the source declares writable come first, then the well known ones it reports, then the rest
export function optionsFor(metrics: Record<string, Metric> | undefined): { writable: WritableMetric[]; others: WritableMetric[] } {
  const list = Object.values(metrics || {}).sort((a, b) => a.name.localeCompare(b.name));
  const preset = new Map(WRITABLE.map((w) => [w.name, w]));
  const asOption = (m: Metric, help: string): WritableMetric => {
    const p = preset.get(m.name);
    if (p) return p;
    const kind = kindFor(m.type, m.value);
    const { label, unit } = splitMetric(m.name);
    return { name: m.name, label: `${label}${unit ? ` (${unit})` : ''}`, kind, datatype: datatypeFor(kind, m.type), help };
  };
  if (!list.length) return { writable: WRITABLE, others: [] };
  const flagged = list.filter((m) => m.writable === true || preset.has(m.name));
  const rest = list.filter((m) => !flagged.includes(m));
  return {
    writable: flagged.map((m) => asOption(m, 'This signal accepts writes.')),
    others: rest.map((m) => asOption(m, 'This signal is not declared writable, so the source may ignore it or refuse it.')),
  };
}

export default function SendCommandDialog({
  open, onClose, group, node, device, online, initialMetric,
}: { open: boolean; onClose: () => void; group: string; node: string; device: string; online: boolean; initialMetric?: string }) {
  const metrics = useTelemetry((s) => s.metrics[deviceKey(group, node, device)]);
  const groups = useMemo(() => optionsFor(metrics), [metrics]);
  const options = useMemo(() => [...groups.writable, ...groups.others], [groups]);
  const [metric, setMetric] = useState(initialMetric && options.some((o) => o.name === initialMetric) ? initialMetric : (groups.writable[0] ?? options[0] ?? WRITABLE[0]).name);
  const opt = options.find((o) => o.name === metric) ?? options[0] ?? WRITABLE[0];
  const [raw, setRaw] = useState(opt.kind === 'boolean' ? 'true' : opt.kind === 'choice' ? opt.choices?.[0].value ?? '' : '');
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const [step, setStep] = useState<Step>('form');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [sentValue, setSentValue] = useState<MetricValue>(null);
  // the server's own rendering of the exact message, from a dry run
  const [exact, setExact] = useState<{ topic: string; payload: string } | null>(null);
  const [checking, setChecking] = useState(false);

  const parsed = parseValue(opt.kind, raw, opt.choices);
  const rProblem = reasonProblem(reason);
  const valueKey = JSON.stringify(parsed.value);

  // asks the server for the exact message whenever the signal or value changes
  useEffect(() => {
    if (step !== 'form' || parsed.problem || !online) return;
    let stop = false;
    const t = setTimeout(async () => {
      const res = await apiFetch<{ topic?: string; target?: string; payload?: unknown }>('/api/telemetry/command', {
        method: 'POST',
        body: JSON.stringify({ group, node, device, signal: opt.name, metric: opt.name, value: JSON.parse(valueKey), reason: '', dry_run: true }),
        throwOnError: false,
        silent: true,
      });
      if (stop) return;
      const d = res.data;
      const to = d?.topic ?? d?.target;
      setExact(to && d?.payload !== undefined ? { topic: to, payload: typeof d.payload === 'string' ? d.payload : JSON.stringify(d.payload, null, 2) } : null);
    }, 400);
    return () => { stop = true; clearTimeout(t); };
  }, [step, opt.name, valueKey, parsed.problem, online, group, node, device]);
  const target = device ? `${node} / ${device}` : node;
  const preview = commandPreview({ group, node, device, metric: opt.name, datatype: opt.datatype, value: parsed.value });
  const reported = metrics?.[opt.name];

  function pick(name: string) {
    setMetric(name);
    const o = options.find((x) => x.name === name);
    const cur = metrics?.[name]?.value;
    setRaw(o?.kind === 'boolean' ? (cur === true ? 'false' : 'true') : o?.kind === 'choice' ? o.choices?.[0].value ?? '' : cur !== undefined && cur !== null && typeof cur !== 'boolean' ? String(cur) : '');
    setErr(null);
  }

  async function review() {
    setTouched(true);
    if (parsed.problem || rProblem) return;
    setErr(null);
    setExact(null);
    setChecking(true);
    try {
      const res = await apiFetch<{ topic?: string; payload?: unknown }>('/api/telemetry/command', {
        method: 'POST',
        body: JSON.stringify({ group, node, device, signal: opt.name, metric: opt.name, value: parsed.value, reason: reason.trim(), dry_run: true }),
      });
      const d = res.data;
      if (d?.topic && d.payload !== undefined) setExact({ topic: d.topic, payload: typeof d.payload === 'string' ? d.payload : JSON.stringify(d.payload, null, 2) });
    } catch (e) {
      // the same refusal would come back on send, say it now
      setErr(explainTelemetryError(e, 'command', { node, device }));
    } finally {
      setChecking(false);
      setStep('confirm');
    }
  }

  async function send() {
    setBusy(true);
    setErr(null);
    try {
      await apiFetch('/api/telemetry/command', {
        method: 'POST',
        body: JSON.stringify({ group, node, device, signal: opt.name, metric: opt.name, value: parsed.value, reason: reason.trim() }),
      });
      setSentAt(Date.now());
      setSentValue(parsed.value);
      setStep('sent');
    } catch (e) {
      setErr(explainTelemetryError(e, 'command', { node, device }));
    } finally {
      setBusy(false);
    }
  }

  const inputCls = 'w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-2 text-sm text-white placeholder:text-slate-600';
  const confirmed = step === 'sent' && reported !== undefined && JSON.stringify(reported.value) === JSON.stringify(sentValue);
  const [waited, setWaited] = useState(false);
  useEffect(() => {
    if (step !== 'sent') { setWaited(false); return; }
    const t = setTimeout(() => setWaited(true), 10_000);
    return () => clearTimeout(t);
  }, [step, sentAt]);

  return (
    <ResponsiveModal open={open} onClose={busy ? () => {} : onClose} title={`Send a command to ${target}`} icon={<Send className="h-4 w-4" />} maxWidth="max-w-xl">
      <div className="space-y-4" data-testid="tel-command-dialog" data-step={step}>
        {step === 'form' && (
          <>
            {!online && (
              <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100" role="note">
                {target} is offline right now. A command can only be sent once it is back online.
              </p>
            )}
            <div>
              <label htmlFor="tel-cmd-metric" className="mb-1 block text-xs font-medium text-slate-300">What to change</label>
              <select id="tel-cmd-metric" value={opt.name} onChange={(e) => pick(e.target.value)} className={inputCls} data-testid="tel-cmd-metric">
                {groups.writable.length > 0 && (
                  <optgroup label="Signals that accept writes">
                    {groups.writable.map((w) => <option key={w.name} value={w.name}>{w.label} ({w.name})</option>)}
                  </optgroup>
                )}
                {groups.others.length > 0 && (
                  <optgroup label="Other signals">
                    {groups.others.map((w) => <option key={w.name} value={w.name}>{w.label} ({w.name})</option>)}
                  </optgroup>
                )}
              </select>
              <p className="mt-1 text-xs text-slate-400">{opt.help}{reported ? ` It reports ${formatValue(reported.value)} now.` : ''}</p>
            </div>

            <div>
              <label htmlFor="tel-cmd-value" className="mb-1 block text-xs font-medium text-slate-300">New value</label>
              {opt.kind === 'boolean' ? (
                <div className="flex gap-2" role="radiogroup" aria-label="New value" id="tel-cmd-value">
                  {[['true', 'On'], ['false', 'Off']].map(([v, l]) => (
                    <button key={v} type="button" role="radio" aria-checked={raw === v} onClick={() => setRaw(v)} className={`min-h-[40px] flex-1 rounded-md border px-3 py-2 text-sm ${raw === v ? 'border-cyan-400 bg-cyan-500/15 text-white' : 'border-slate-700 text-slate-300 hover:bg-slate-800'}`} data-testid={`tel-cmd-bool-${v}`}>
                      {l}
                    </button>
                  ))}
                </div>
              ) : opt.kind === 'choice' ? (
                <select id="tel-cmd-value" value={raw} onChange={(e) => setRaw(e.target.value)} className={inputCls} data-testid="tel-cmd-value">
                  {opt.choices?.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              ) : opt.kind === 'json' ? (
                <textarea id="tel-cmd-value" value={raw} onChange={(e) => setRaw(e.target.value)} rows={3} placeholder='{"task": "dig", "zone": "A3"}' className={`${inputCls} font-mono`} data-testid="tel-cmd-value" />
              ) : (
                <input id="tel-cmd-value" value={raw} onChange={(e) => setRaw(e.target.value)} inputMode={opt.kind === 'text' ? 'text' : 'decimal'} className={inputCls} data-testid="tel-cmd-value" />
              )}
              {touched && parsed.problem && <p className="mt-1 text-xs text-rose-300" role="alert" data-testid="tel-cmd-value-problem">{parsed.problem}</p>}
            </div>

            <div>
              <label htmlFor="tel-cmd-reason" className="mb-1 block text-xs font-medium text-slate-300">Why (required)</label>
              <textarea id="tel-cmd-reason" value={reason} onChange={(e) => setReason(e.target.value)} onBlur={() => setTouched(true)} rows={2} placeholder="for example: worker reported in the swing zone" className={inputCls} data-testid="tel-cmd-reason" />
              {touched && rProblem ? (
                <p className="mt-1 text-xs text-rose-300" role="alert" data-testid="tel-cmd-reason-problem">{rProblem}</p>
              ) : (
                <p className="mt-1 text-xs text-slate-500">At least {REASON_MIN} characters. It goes on the audit log with your name and the value.</p>
              )}
            </div>

            <Preview topic={exact?.topic ?? preview.topic} payload={exact?.payload ?? preview.payload} kind={preview.kind} exact={!!exact} />

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">Cancel</button>
              {online ? (
                <button type="button" onClick={review} disabled={checking} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-60" data-testid="tel-cmd-review">
                  {checking && <Loader2 className="h-4 w-4 animate-spin" />} Review and send
                </button>
              ) : (
                <p className="text-xs text-slate-400 sm:max-w-[16rem] sm:text-right">Sending opens again when {target} is back online.</p>
              )}
            </div>
          </>
        )}

        {step === 'confirm' && (
          <>
            <div className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
              <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
              <div className="min-w-0 text-sm text-amber-50">
                <p className="font-semibold text-white" data-testid="tel-cmd-confirm-title">Set {opt.label} to {formatValue(parsed.value)} on {target}?</p>
                {opt.effect && <p className="mt-1">{opt.effect(parsed.value)}</p>}
                <p className="mt-1 text-amber-100/90">This goes to the machine straight away. It does not wait for an approval. Your name, your reason and the value are recorded in the audit log.</p>
                <p className="mt-1 text-amber-100/90">Reason: <span className="italic">{reason.trim()}</span></p>
              </div>
            </div>
            <Preview topic={exact?.topic ?? preview.topic} payload={exact?.payload ?? preview.payload} kind={preview.kind} exact={!!exact} />
            {err && <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert" data-testid="tel-cmd-error">{err}</p>}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" disabled={busy} onClick={() => setStep('form')} className="inline-flex min-h-[40px] items-center justify-center gap-1 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50">
                <ArrowLeft className="h-4 w-4" /> Back
              </button>
              <button type="button" disabled={busy} onClick={send} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white hover:bg-amber-400 disabled:opacity-60" data-testid="tel-cmd-send">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Send now
              </button>
            </div>
          </>
        )}

        {step === 'sent' && (
          <>
            <div className="flex items-start gap-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-50" role="status" data-testid="tel-cmd-sent">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300" />
              <div>
                <p className="font-semibold text-white">Sent at {sentAt ? clock(sentAt) : ''}.</p>
                <p className="mt-1" data-testid="tel-cmd-echo">
                  {confirmed
                    ? `${target} now reports ${opt.label} as ${formatValue(reported?.value ?? null)}.`
                    : waited
                      ? `${target} has not reported the new value 10 seconds after sending. It may not accept writes to this signal, or it only reports changes now and then. Check the value in the table, and the Messages tab for this source.`
                      : `Waiting for ${target} to report the new value. It shows in the table when it does.`}
                </p>
                <p className="mt-1 text-emerald-100/80">The audit log has your name, the reason and the value.</p>
              </div>
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => { setStep('form'); setReason(''); setTouched(false); }} className="min-h-[40px] rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800" data-testid="tel-cmd-another">Send another</button>
              <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400" data-testid="tel-cmd-close">Done</button>
            </div>
          </>
        )}
      </div>
    </ResponsiveModal>
  );
}

function Preview({ topic, payload, kind, exact }: { topic: string; payload: string; kind: string; exact?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950/70" data-testid="tel-cmd-preview">
      <p className="border-b border-slate-800 px-3 py-1.5 text-[11px] uppercase tracking-wide text-slate-400">
        {exact ? 'Exactly what will be sent' : `What will be sent, as a Sparkplug B ${kind} until Abenix confirms it`}
      </p>
      <div className="space-y-1 px-3 py-2 text-xs">
        <p className="text-slate-400">To <code className="break-all text-cyan-200" data-testid="tel-cmd-topic">{topic}</code></p>
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-slate-200" data-testid="tel-cmd-payload">{payload}</pre>
        <p className="text-[11px] text-slate-500">
          {exact ? 'Encoded for this source the way it goes on the wire, shown here as JSON.' : 'Abenix works out the exact message for this source as you change the value.'}
        </p>
      </div>
    </div>
  );
}
