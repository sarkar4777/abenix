'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, Compass, Edit3, Inbox, KeyRound, Loader2, Power, PowerOff, Search, Share2, Shuffle, Trash2, Users, Webhook, XCircle, Zap } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import ResourceShareDialog from '@/components/share/ResourceShareDialog';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import UnencryptedSecretsBanner from '@/components/shared/UnencryptedSecretsBanner';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { describeTest, explainTelemetryError, statusText } from '@/lib/telemetry/errors';
import { ago, rate } from '@/lib/telemetry/format';
import { addressOf, subjectSummary, type DecoderDecl, type Mapping, type TransportDecl } from '@/lib/telemetry/sources';
import type { Connection, ConnectionTest } from '@/lib/telemetry/types';
import { toastError, toastSuccess } from '@/stores/toastStore';
import SourceWizard, { type WizardStart } from './SourceWizard';
import PushPanel from './PushPanel';
import KeysPanel from './KeysPanel';
import { forgetKept } from '@/lib/telemetry/kept';
import { TransportIcon } from './transportIcon';
import type { TestbedInfo } from '@/lib/telemetry/testbed';

export type Source = Connection & {
  transport?: string;
  config?: Record<string, unknown>;
  decoder?: string;
  dlq_count?: number | null;
  clock_skew_ms?: number | null;
  ingest_url?: string | null;
  pipeline?: { received?: number; stored?: number; skipped?: number; failed?: number; last_reasons?: { skipped?: { reason?: string } } } | null;
  diagnosis?: { state?: string; text?: string } | null;
};

export function shareText(c: Connection, teamNames: Record<string, string> = {}): string {
  const team = c.team_name || (c.team_id ? teamNames[c.team_id] : null);
  if (team) return `Team ${team}`;
  if (c.team_id) return 'One team';
  if (c.share_count) return `Shared with ${c.share_count} ${c.share_count === 1 ? 'person' : 'people'}`;
  return 'Whole workspace';
}

function Tone({ tone, children }: { tone: 'ok' | 'wait' | 'bad' | 'off'; children: React.ReactNode }) {
  const cls = tone === 'ok' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : tone === 'bad' ? 'border-rose-500/40 bg-rose-500/10 text-rose-200' : tone === 'wait' ? 'border-amber-500/40 bg-amber-500/10 text-amber-200' : 'border-slate-600 bg-slate-800 text-slate-300';
  return <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>;
}

const btn = 'inline-flex min-h-[34px] items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-60';

export default function SourcesTab({
  rows, loading, error, reload, canManage, addRequest, onAddHandled, openMessages, now, focus, onFocusHandled, openGuide, testbed, onTestbed,
}: {
  rows: Source[] | null; loading: boolean; error: string | null; reload: () => void; canManage: boolean;
  // set by the page header or an empty state, a transport to start with or "any"
  addRequest: string | null; onAddHandled: () => void; openMessages: (sourceId: string, problems?: boolean) => void; now: number;
  // a source to open, from a diagnosis elsewhere on the page
  focus?: { id: string; action: 'edit' | 'mapping' | 'test' | 'endpoint' } | null;
  onFocusHandled?: () => void;
  openGuide?: () => void;
  testbed?: TestbedInfo | null;
  onTestbed?: () => void;
}) {
  const [wizard, setWizard] = useState<WizardStart | null>(null);
  const [tests, setTests] = useState<Record<string, { busy: boolean; ok?: boolean; text?: string }>>({});
  const [confirm, setConfirm] = useState<{ kind: 'delete' | 'off'; c: Source } | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [share, setShare] = useState<Source | null>(null);
  const [push, setPush] = useState<Source | null>(null);
  const [keysFor, setKeysFor] = useState<Source | null>(null);
  const [q, setQ] = useState('');
  const list = useMemo(() => rows || [], [rows]);
  const { data: teams } = useApi<Array<{ id: string; name: string }>>('/api/telemetry/teams');
  const { data: transports } = useApi<TransportDecl[]>('/api/telemetry/transports');
  const { data: decoders } = useApi<DecoderDecl[]>('/api/telemetry/decoders');
  const teamNames = useMemo(() => Object.fromEntries((teams || []).map((t) => [t.id, t.name])), [teams]);
  const tLabel = (t?: string) => transports?.find((x) => x.transport === t)?.label ?? (t === 'mqtt' || !t ? 'MQTT' : t);
  const dLabel = (d?: string) => decoders?.find((x) => x.name === d)?.label ?? (d === 'sparkplug_b' || !d ? 'Sparkplug B' : d);

  useEffect(() => {
    if (addRequest && canManage) {
      setWizard(addRequest === 'any' ? {} : { transport: addRequest });
      onAddHandled();
    }
  }, [addRequest, canManage, onAddHandled]);

  useEffect(() => {
    if (!focus || !rows) return;
    const c = rows.find((r) => r.id === focus.id);
    if (c && canManage) {
      if (focus.action === 'edit') setWizard({ source: c });
      else if (focus.action === 'mapping') setWizard({ source: c, step: 'mapping' });
      else if (focus.action === 'endpoint') setPush(c);
      else void runTest(c);
    }
    onFocusHandled?.();
  }, [focus?.id, focus?.action, rows === null]);

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? list.filter((c) => `${c.name} ${addressOf(c.config, c.broker_url)} ${subjectSummary(c.config, c.topics).join(' ')} ${c.team_name ?? ''} ${c.transport ?? ''}`.toLowerCase().includes(s)) : list;
  }, [list, q]);

  async function runTest(c: Source) {
    setTests((t) => ({ ...t, [c.id]: { busy: true } }));
    try {
      const res = await apiFetch<ConnectionTest & { subjects_seen?: string[] }>(`/api/telemetry/connections/${c.id}/test`, { method: 'POST' });
      const d = res.data;
      const r = describeTest({ ok: !!d?.ok, connected: !!d?.connected, messages: d?.messages ?? 0, topics_seen: d?.topics_seen ?? d?.subjects_seen ?? [], error: d?.error ?? null }, addressOf(c.config, c.broker_url) || c.name, c.transport);
      setTests((t) => ({ ...t, [c.id]: { busy: false, ok: r.ok, text: r.text } }));
    } catch (e) {
      setTests((t) => ({ ...t, [c.id]: { busy: false, ok: false, text: explainTelemetryError(e, 'test') } }));
    }
  }

  async function doConfirm() {
    if (!confirm) return;
    setBusy(true);
    setActionErr(null);
    const { kind, c } = confirm;
    try {
      if (kind === 'delete') await apiFetch(`/api/telemetry/connections/${c.id}`, { method: 'DELETE' });
      else await apiFetch(`/api/telemetry/connections/${c.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: false }) });
      toastSuccess(kind === 'delete' ? `${c.name} deleted` : `${c.name} turned off`, kind === 'delete' ? undefined : 'Abenix stops reading it within 5 seconds.');
      setConfirm(null);
      reload();
    } catch (e) {
      setActionErr(explainTelemetryError(e, kind === 'delete' ? 'delete' : 'toggle'));
    } finally {
      setBusy(false);
    }
  }

  async function turnOn(c: Source) {
    try {
      await apiFetch(`/api/telemetry/connections/${c.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: true }) });
      toastSuccess(`${c.name} turned on`, 'Abenix starts reading it within 5 seconds.');
      reload();
    } catch (e) {
      toastError(`Could not turn on ${c.name}`, explainTelemetryError(e, 'toggle'));
    }
  }

  return (
    <div className="space-y-3">
      {canManage ? <UnencryptedSecretsBanner /> : (
        <ViewOnlyBanner testId="tel-connections-view-only">
          You can see where data comes from and whether each source is healthy, for the sources shared with you or your team. Adding or changing them needs Manage telemetry brokers, which admins have.
        </ViewOnlyBanner>
      )}

      {canManage && testbed?.installed && list.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-emerald-600/40 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-100" data-testid="tel-sources-testbed">
          <Zap className="h-4 w-4 shrink-0 text-emerald-300" aria-hidden />
          <span className="min-w-0 flex-1">
            The testbed runs {testbed.services?.length ?? 'some'} sample {testbed.services?.length === 1 ? 'stream' : 'streams'} in this cluster. Add them all as sources, or pick &quot;Use the testbed&apos;s details&quot; when you add one.
          </span>
          {onTestbed && (
            <button type="button" onClick={onTestbed} className="rounded-md border border-emerald-500/50 px-2.5 py-1 text-xs font-medium text-emerald-100 hover:bg-emerald-500/10" data-testid="tel-sources-testbed-add">
              Add the testbed sources
            </button>
          )}
        </div>
      )}

      {list.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {list.length > 6 && (
            <label className="relative min-w-[12rem] flex-1 sm:max-w-xs">
              <span className="sr-only">Search sources</span>
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, address, topic or team" className="w-full rounded-lg border border-slate-700 bg-slate-900 py-2 pl-8 pr-2 text-sm text-white placeholder:text-slate-500" data-testid="tel-conn-search" />
            </label>
          )}
          <p className="flex-1 text-xs text-slate-400">{list.length} source{list.length === 1 ? '' : 's'}. Changes reach the ingest service within 5 seconds.</p>
        </div>
      )}

      {error && !rows ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-100" role="alert" data-testid="tel-conn-error">
          {error} <button type="button" onClick={reload} className="ml-1 text-cyan-300 hover:underline">Try again</button>
        </div>
      ) : loading && !rows ? (
        <div className="space-y-2" aria-busy="true">{[0, 1].map((i) => <div key={i} className="h-28 animate-pulse rounded-xl bg-slate-800/40" />)}</div>
      ) : !list.length ? (
        <FirstSources canManage={canManage} onPick={(t) => (t === 'guide' ? openGuide?.() : t === 'testbed' ? onTestbed?.() : setWizard(t === 'any' ? {} : { transport: t }))} transports={transports} testbed={testbed} />
      ) : (
        <ul className="space-y-2" data-testid="tel-conn-list">
          {shown.map((c) => {
            const st = statusText(c);
            const t = tests[c.id];
            const manage = canManage && c.can_manage !== false && c.can_edit !== false;
            const isPush = c.transport === 'http_push';
            const subjects = subjectSummary(c.config, c.topics);
            const raw = c.raw_topics || [];
            const addr = isPush ? 'Systems send to Abenix over HTTPS' : addressOf(c.config, c.broker_url);
            const user = c.username || (c.config?.username as string | undefined);
            return (
              <li key={c.id} className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-3" data-testid="tel-conn-row" data-name={c.name} data-status={c.status ?? (c.enabled ? 'connecting' : 'disabled')}>
                <div className="flex min-w-0 flex-wrap items-start gap-2">
                  <TransportIcon transport={c.transport ?? 'mqtt'} className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" />
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-semibold text-white">{c.name}</h3>
                      <Tone tone={st.tone}>{st.tone === 'ok' ? <CheckCircle2 className="h-3 w-3" /> : st.tone === 'bad' ? <XCircle className="h-3 w-3" /> : null}{st.label}</Tone>
                      <span className="text-[11px] text-slate-400" data-testid="tel-conn-kind">{tLabel(c.transport)} · {dLabel(c.decoder)}</span>
                      <span className="inline-flex items-center gap-1 rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300" data-testid="tel-conn-share"><Users className="h-3 w-3" /> {shareText(c, teamNames)}</span>
                    </div>
                    <p className="mt-1 break-all font-mono text-xs text-slate-300" data-testid="tel-conn-url">
                      {addr}
                      {user ? <span className="text-slate-500"> as {user}{c.has_password || c.password ? ', password ••••••' : ''}</span> : null}
                    </p>
                    {(subjects.length > 0 || raw.length > 0) && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {subjects.map((tp) => <code key={tp} className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-300">{tp}</code>)}
                        {raw.map((tp) => <code key={tp} className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-amber-200" title="raw CAN frames">{tp}</code>)}
                      </div>
                    )}
                  </div>
                  <dl className="grid shrink-0 grid-cols-2 gap-3 text-right text-xs sm:grid-cols-3">
                    <div><dt className="text-[10px] uppercase tracking-wide text-slate-500">msg/s</dt><dd className="font-semibold tabular-nums text-white">{rate(c.messages_per_second ?? 0)}</dd></div>
                    <div><dt className="text-[10px] uppercase tracking-wide text-slate-500">Last message</dt><dd className="tabular-nums text-slate-300">{ago(c.last_message_at ?? null, now)}</dd></div>
                    <div className="hidden sm:block"><dt className="text-[10px] uppercase tracking-wide text-slate-500">Problems</dt><dd>
                      {c.dlq_count ? <button type="button" onClick={() => openMessages(c.id, true)} className="font-semibold tabular-nums text-amber-200 hover:underline" data-testid="tel-conn-dlq">{c.dlq_count}</button> : <span className="tabular-nums text-slate-400">0</span>}
                    </dd></div>
                  </dl>
                </div>
                {c.enabled && c.status === 'error' && c.last_error && (
                  <p className="mt-2 rounded-md border border-rose-500/30 bg-rose-500/5 px-2 py-1.5 text-xs text-rose-100" data-testid="tel-conn-last-error">{describeTest({ ok: false, connected: false, messages: 0, topics_seen: [], error: c.last_error }, addressOf(c.config, c.broker_url) || c.name, c.transport).text}</p>
                )}
                {c.clock_skew_ms && Math.abs(c.clock_skew_ms) > 5000 ? (
                  <p className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-xs text-amber-100">Times in its messages are {Math.round(Math.abs(c.clock_skew_ms) / 1000)} s {c.clock_skew_ms > 0 ? 'ahead of' : 'behind'} the time they arrive. Check the sender&apos;s clock, or the time format in the mapping.</p>
                ) : null}
                {t && !t.busy && t.text && (
                  <p className={`mt-2 flex items-start gap-1.5 rounded-md border px-2 py-1.5 text-xs ${t.ok ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100' : 'border-rose-500/30 bg-rose-500/5 text-rose-100'}`} role="status" data-testid="tel-conn-test-result" data-ok={t.ok ? 'true' : 'false'}>
                    {t.ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />} {t.text}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <button type="button" onClick={() => openMessages(c.id)} className={btn} data-testid="tel-conn-messages"><Inbox className="h-3.5 w-3.5" /> Messages</button>
                  {manage && (
                    <>
                      {!isPush && (
                        <button type="button" onClick={() => runTest(c)} disabled={t?.busy} className={btn} data-testid="tel-conn-test">
                          {t?.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />} {t?.busy ? 'Testing for 5 seconds' : 'Test'}
                        </button>
                      )}
                      {isPush && <button type="button" onClick={() => setPush(c)} className={btn} data-testid="tel-conn-endpoint"><Webhook className="h-3.5 w-3.5" /> Endpoint and token</button>}
                      {isPush && <button type="button" onClick={() => setKeysFor(c)} className={btn} data-testid="tel-conn-keys"><KeyRound className="h-3.5 w-3.5" /> Device keys</button>}
                      <button type="button" onClick={() => setWizard({ source: c })} className={btn} data-testid="tel-conn-edit"><Edit3 className="h-3.5 w-3.5" /> Edit</button>
                      <button type="button" onClick={() => setWizard({ source: c, step: 'mapping' })} className={btn} data-testid="tel-conn-mapping"><Shuffle className="h-3.5 w-3.5" /> Mapping</button>
                      {c.enabled ? (
                        <button type="button" onClick={() => { setConfirm({ kind: 'off', c }); setActionErr(null); }} className={btn} data-testid="tel-conn-disable"><PowerOff className="h-3.5 w-3.5" /> Turn off</button>
                      ) : (
                        <button type="button" onClick={() => turnOn(c)} className="inline-flex min-h-[34px] items-center gap-1 rounded-md border border-emerald-600/50 px-2.5 py-1 text-xs text-emerald-200 hover:bg-emerald-500/10" data-testid="tel-conn-enable"><Power className="h-3.5 w-3.5" /> Turn on</button>
                      )}
                      <button type="button" onClick={() => setShare(c)} className={btn} data-testid="tel-conn-share-open"><Share2 className="h-3.5 w-3.5" /> Share</button>
                      <button type="button" onClick={() => { setConfirm({ kind: 'delete', c }); setActionErr(null); }} className="inline-flex min-h-[34px] items-center gap-1 rounded-md border border-rose-600/40 px-2.5 py-1 text-xs text-rose-200 hover:bg-rose-500/10" data-testid="tel-conn-delete"><Trash2 className="h-3.5 w-3.5" /> Delete</button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
          {!shown.length && <li className="rounded-xl border border-slate-700/60 p-4 text-sm text-slate-300">No source matches. <button type="button" className="text-cyan-300 hover:underline" onClick={() => setQ('')}>Clear the search</button></li>}
        </ul>
      )}

      {wizard && (
        <SourceWizard start={wizard} existingNames={list.map((c) => c.name)} teams={teams || []} onClose={() => setWizard(null)} onSaved={reload} />
      )}

      {push && (
        <ResponsiveModal open onClose={() => { forgetKept(`push:${push.id}`); setPush(null); }} title={`Send data to ${push.name}`} icon={<Webhook className="h-4 w-4" />} maxWidth="max-w-xl">
          <PushPanel sourceId={push.id} token={null} ingestUrl={push.ingest_url} mapping={(push as Source & { mapping?: Partial<Mapping> }).mapping} />
        </ResponsiveModal>
      )}

      {keysFor && (
        <ResponsiveModal open onClose={() => { forgetKept(`keys:${keysFor.id}`); setKeysFor(null); }} title={`Device keys for ${keysFor.name}`} icon={<KeyRound className="h-4 w-4" />} maxWidth="max-w-2xl">
          <KeysPanel sourceId={keysFor.id} sourceName={keysFor.name} ingestUrl={keysFor.ingest_url} />
        </ResponsiveModal>
      )}

      {confirm && (
        <ConfirmModal
          open
          onClose={() => !busy && setConfirm(null)}
          onConfirm={doConfirm}
          loading={busy}
          variant={confirm.kind === 'delete' ? 'danger' : 'warning'}
          icon={confirm.kind === 'delete' ? Trash2 : PowerOff}
          title={confirm.kind === 'delete' ? `Delete ${confirm.c.name}?` : `Turn off ${confirm.c.name}?`}
          description={confirm.kind === 'delete'
            ? 'Abenix stops reading this source and forgets its settings and secrets. Its assets show as offline. History already stored is kept until it ages out. This cannot be undone, you would add the source again.'
            : 'Abenix stops reading this source within 5 seconds. Its assets show as offline until you turn it back on. Nothing is deleted.'}
          confirmLabel={confirm.kind === 'delete' ? 'Delete source' : 'Turn off'}
          confirmTestId={confirm.kind === 'delete' ? 'tel-conn-delete-confirm' : 'tel-conn-disable-confirm'}
        >
          {actionErr && <p className="text-xs text-rose-300" role="alert">{actionErr}</p>}
        </ConfirmModal>
      )}

      {share && (
        <ResourceShareDialog open onClose={() => { setShare(null); reload(); }} resourceType="telemetry_connection" resourceId={share.id} resourceName={share.name} />
      )}

      {list.length > 0 && (
        <p className="text-xs text-slate-500">
          An asset going offline raises an alert on the <Link href="/alerts" className="text-cyan-300 hover:underline">Alerts page</Link>, and the events go out to anything subscribed under <Link href="/settings/webhooks" className="text-cyan-300 hover:underline">Events</Link>.
        </p>
      )}
    </div>
  );
}

const FIRST: Array<{ transport: string; title: string; text: string }> = [
  { transport: 'http_push', title: 'Push over HTTP', text: 'The quickest start. Get an address and a token, then send a test message from this page.' },
  { transport: 'mqtt', title: 'Connect a broker', text: 'Machines and gateways on MQTT, with Sparkplug B or plain JSON.' },
  { transport: 'kafka', title: 'Stream from Kafka', text: 'Events from your own services, on Kafka, Redpanda or Event Hubs.' },
];

export type { TestbedInfo };

export function FirstSources({ canManage, onPick, transports, testbed }: { canManage: boolean; onPick: (t: string) => void; transports?: TransportDecl[] | null; testbed?: TestbedInfo | null }) {
  const have = (t: string) => !transports || transports.some((x) => x.transport === t);
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-5 sm:p-8" data-testid="tel-empty-no-source">
      <h2 className="text-center text-base font-semibold text-white">Bring in your first stream</h2>
      <p className="mx-auto mt-1 max-w-xl text-center text-sm text-slate-300">
        Telemetry takes live data from vehicles, machines, sensors, products and software systems. Every kind ends up the same here, as assets with live signals and history.
      </p>
      <div className="mt-3 text-center">
        <button type="button" onClick={() => onPick('guide')} className="inline-flex min-h-[40px] items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400" data-testid="tel-first-guide">
          <Compass className="h-4 w-4" /> Help me choose
        </button>
        <p className="mt-1 text-xs text-slate-500">Or pick a way in below if you already know it.</p>
      </div>
      {canManage ? (
        <div className="mx-auto mt-4 grid max-w-3xl gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {testbed?.installed && (
            <button type="button" onClick={() => onPick('testbed')} className="flex flex-col items-start gap-1 rounded-lg border border-emerald-600/50 bg-emerald-500/5 p-3 text-left hover:border-emerald-400" data-testid="tel-first-testbed">
              <Zap className="h-5 w-5 text-emerald-300" />
              <span className="text-sm font-medium text-white">Try the testbed</span>
              <span className="text-xs text-slate-400">One click. Adds the sample streams running in this cluster as sources.</span>
              {testbed.services?.length ? (
                <span className="mt-1 flex flex-wrap gap-1" data-testid="tel-testbed-services">
                  {testbed.services.map((s) => (
                    <span key={s.name} className={`rounded border px-1 text-[10px] ${s.reachable === false ? 'border-rose-500/40 text-rose-200' : 'border-emerald-500/40 text-emerald-200'}`} title={s.reachable === false ? `${s.name} is not answering, its source will show why` : `${s.name} is answering`}>
                      {s.name}{s.reachable === false ? ', not answering' : ''}
                    </span>
                  ))}
                </span>
              ) : null}
            </button>
          )}
          {FIRST.filter((f) => have(f.transport)).map((f) => (
            <button key={f.transport} type="button" onClick={() => onPick(f.transport)} className="flex flex-col items-start gap-1 rounded-lg border border-slate-700 p-3 text-left hover:border-cyan-500/60" data-testid={`tel-first-${f.transport}`}>
              <TransportIcon transport={f.transport} className="h-5 w-5 text-cyan-300" />
              <span className="text-sm font-medium text-white">{f.title}</span>
              <span className="text-xs text-slate-400">{f.text}</span>
            </button>
          ))}
          <button type="button" onClick={() => onPick('any')} className="flex flex-col items-start gap-1 rounded-lg border border-slate-700 p-3 text-left hover:border-cyan-500/60" data-testid="tel-first-other">
            <Shuffle className="h-5 w-5 text-cyan-300" />
            <span className="text-sm font-medium text-white">Something else</span>
            <span className="text-xs text-slate-400">RabbitMQ, NATS, OPC UA, Modbus, WebSockets and more.</span>
          </button>
        </div>
      ) : (
        <p className="mx-auto mt-3 max-w-md text-center text-sm text-slate-400" data-testid="tel-empty-ask-admin">
          No source is connected yet, or none is shared with you or your team. Adding and sharing sources is for admins. Ask an admin to connect your broker, stream or system under Telemetry, Sources, or to share an existing one with you.
        </p>
      )}
    </div>
  );
}
