'use client';

import { AlertTriangle, CheckCircle2, CircleDashed, PowerOff, XCircle } from 'lucide-react';
import { describeTest } from '@/lib/telemetry/errors';
import { addressOf, subjectSummary } from '@/lib/telemetry/sources';
import type { Source } from './SourcesTab';
import { pluralShown } from '@/lib/plural';

export type DiagnosisAction = 'turn_on' | 'edit' | 'test' | 'problems' | 'mapping' | 'messages' | 'endpoint';
export interface Diagnosis { tone: 'ok' | 'wait' | 'warn' | 'bad' | 'off'; text: string; action?: { kind: DiagnosisAction; label: string } }

// why a source shows nothing, in one sentence, with the one thing to do about it
export function diagnose(s: Source, opts: { canManage: boolean; assets: number }): Diagnosis {
  const isPush = s.transport === 'http_push';
  const subjects = subjectSummary(s.config, s.topics);
  if (!s.enabled || s.status === 'disabled') {
    return { tone: 'off', text: `${s.name} is turned off, so nothing from it is read.${opts.canManage ? '' : ' An admin can turn it on.'}`, action: opts.canManage ? { kind: 'turn_on', label: 'Turn it on' } : undefined };
  }
  if (s.status === 'error') {
    const why = s.last_error ? describeTest({ ok: false, connected: false, messages: 0, topics_seen: [], error: s.last_error }, addressOf(s.config, s.broker_url) || s.name, s.transport).text : `${s.name} cannot connect.`;
    return { tone: 'bad', text: why, action: opts.canManage ? { kind: 'edit', label: 'Fix the settings' } : undefined };
  }
  if (!s.last_message_at) {
    if (s.status === 'connecting' && !isPush) return { tone: 'wait', text: `${s.name} is still connecting. If it stays like this for more than a minute, test it.`, action: opts.canManage ? { kind: 'test', label: 'Test it' } : undefined };
    if (isPush) return { tone: 'wait', text: `${s.name} is waiting for its first message. Nothing has been posted to its address yet.`, action: opts.canManage ? { kind: 'endpoint', label: 'Send a test message' } : undefined };
    return {
      tone: 'wait',
      text: `${s.name} is connected but nothing has arrived yet${subjects.length ? `. It reads ${subjects.slice(0, 3).join(', ')}` : ''}. Check the sender is running and publishes there, or widen what it reads.`,
      action: opts.canManage ? { kind: 'test', label: 'Test it' } : undefined,
    };
  }
  const pl = s.pipeline;
  if (s.diagnosis?.state === 'filtered' || (pl && (pl.skipped ?? 0) > 0 && !(pl.stored ?? 0))) {
    const why = pl?.last_reasons?.skipped?.reason;
    return { tone: 'warn', text: `Messages arrive from ${s.name}, but its filter skips every one${why ? `, the last because ${why.replace(/\.$/, '').replace(/^./, (c) => c.toLowerCase())}` : ''}. Check which messages the mapping keeps.`, action: { kind: opts.canManage ? 'mapping' : 'messages', label: opts.canManage ? 'Open the filter' : 'See the messages' } };
  }
  if ((s.dlq_count ?? 0) > 0) {
    return { tone: 'warn', text: `Messages arrive from ${s.name}, but ${s.dlq_count} could not be stored. Problems shows each one with the reason.`, action: { kind: 'problems', label: 'See why' } };
  }
  if (opts.assets === 0) {
    return { tone: 'warn', text: `Messages arrive from ${s.name}, but none became an asset, so the mapping keeps nothing from them. Look at one message and what it turned into.`, action: { kind: opts.canManage ? 'mapping' : 'messages', label: opts.canManage ? 'Open the mapping' : 'See the messages' } };
  }
  return { tone: 'ok', text: `${s.name} is delivering.` };
}

const MAX = 4;

const ICON = { ok: CheckCircle2, wait: CircleDashed, warn: AlertTriangle, bad: XCircle, off: PowerOff };
const TONE = {
  ok: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100',
  wait: 'border-slate-600 bg-slate-800/40 text-slate-200',
  warn: 'border-amber-500/30 bg-amber-500/5 text-amber-100',
  bad: 'border-rose-500/30 bg-rose-500/5 text-rose-100',
  off: 'border-slate-600 bg-slate-800/40 text-slate-300',
};

export default function SourceDiagnoses({ sources, canManage, assetsBySource, onAction }: {
  sources: Source[]; canManage: boolean; assetsBySource: (id: string) => number; onAction: (s: Source, a: DiagnosisAction) => void;
}) {
  const items = sources.map((s) => ({ s, d: diagnose(s, { canManage, assets: assetsBySource(s.id) }) })).filter((x) => x.d.tone !== 'ok');
  if (!items.length) return null;
  const rank = { bad: 0, warn: 1, off: 2, wait: 3, ok: 4 };
  const sorted = [...items].sort((a, b) => rank[a.d.tone] - rank[b.d.tone]);
  return (
    <ul className="space-y-2" data-testid="tel-diagnoses">
      {sorted.length > MAX && <li className="text-xs text-slate-400">{pluralShown(sorted.length, (sorted.length).toLocaleString('en-US'), 'source')} need a look, the first {MAX} are below. Sources lists them all.</li>}
      {sorted.slice(0, MAX).map(({ s, d }) => {
        const Icon = ICON[d.tone];
        return (
          <li key={s.id} className={`flex flex-wrap items-start gap-2 rounded-lg border px-3 py-2 text-sm ${TONE[d.tone]}`} data-testid="tel-diagnosis" data-tone={d.tone} data-source={s.name}>
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <p className="min-w-0 flex-1">{d.text}</p>
            {d.action && (
              <button type="button" onClick={() => onAction(s, d.action!.kind)} className="shrink-0 rounded-md border border-slate-500/50 px-2 py-0.5 text-xs hover:bg-white/5" data-testid={`tel-diagnosis-${d.action.kind}`}>
                {d.action.label}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
