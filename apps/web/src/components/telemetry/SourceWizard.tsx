'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, CheckCircle2, Loader2, Search, XCircle, Zap } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { describeTest, explainTelemetryError, nameProblem } from '@/lib/telemetry/errors';
import {
  BLANK_MAPPING, fieldProblem, initialValues, isSecret, splitList, toPayload, withSubjects, type DecoderDecl, type FieldDecl, type Mapping, type TransportDecl,
} from '@/lib/telemetry/sources';
import type { Connection, ConnectionTest } from '@/lib/telemetry/types';
import { toastSuccess } from '@/stores/toastStore';
import FieldInput from './FieldInput';
import MappingEditor, { mappingProblems } from './MappingEditor';
import PushPanel from './PushPanel';
import { TransportIcon } from './transportIcon';

type Step = 'transport' | 'settings' | 'decoder' | 'mapping' | 'finish';
const STEPS: { id: Step; label: string }[] = [
  { id: 'transport', label: 'Kind' },
  { id: 'settings', label: 'Settings' },
  { id: 'decoder', label: 'Format' },
  { id: 'mapping', label: 'Mapping' },
  { id: 'finish', label: 'Test and turn on' },
];

// a push source is live once saved, so its address and a test message come before the mapping
const PUSH_STEPS: { id: Step; label: string }[] = [
  { id: 'transport', label: 'Kind' },
  { id: 'settings', label: 'Settings' },
  { id: 'decoder', label: 'Format' },
  { id: 'finish', label: 'Address and test' },
  { id: 'mapping', label: 'Mapping' },
];

// decoders that carry their own structure and need no mapping
const SELF_DESCRIBING = new Set(['sparkplug_b', 'can_frames']);

const slug = (s: string) => s.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

export function needsMapping(d: DecoderDecl | undefined): boolean {
  if (!d) return true;
  if (d.uses_mapping !== undefined) return d.uses_mapping;
  if (d.needs_mapping !== undefined) return d.needs_mapping;
  return !SELF_DESCRIBING.has(d.name);
}

export interface WizardStart { source?: Connection; transport?: string; step?: Step; sample?: string; subject?: string; decoder?: string; mapping?: Partial<Mapping>; name?: string; config?: Record<string, unknown> }

function storedSecrets(src: Connection | undefined): Set<string> {
  const s = new Set<string>();
  if (!src) return s;
  const anySrc = src as Connection & { secrets?: Record<string, unknown>; secret_keys?: string[] };
  for (const [k, v] of Object.entries(anySrc.secrets || {})) if (v) s.add(k);
  for (const k of anySrc.secret_keys || []) s.add(k);
  if (src.has_password) s.add('password');
  return s;
}

export default function SourceWizard({ start, existingNames, teams, onClose, onSaved }: {
  start: WizardStart; existingNames: string[]; teams: Array<{ id: string; name: string }>; onClose: () => void; onSaved: () => void;
}) {
  const { data: transports, error: tErr, isLoading: tLoading } = useApi<TransportDecl[]>('/api/telemetry/transports');
  const { data: decoders } = useApi<DecoderDecl[]>('/api/telemetry/decoders');
  const editing = start.source;
  const srcAny = editing as (Connection & { transport?: string; config?: Record<string, unknown>; decoder?: string; decoder_config?: Record<string, unknown>; mapping?: Mapping; strict?: boolean; ingest_url?: string }) | undefined;
  const [step, setStep] = useState<Step>(start.step ?? (editing ? 'settings' : start.transport ? 'settings' : 'transport'));
  const [transportId, setTransportId] = useState(srcAny?.transport ?? start.transport ?? (editing ? 'mqtt' : ''));
  const [name, setName] = useState(editing?.name ?? start.name ?? '');
  const [teamId, setTeamId] = useState(editing?.team_id ?? '');
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [kept, setKept] = useState<Set<string>>(() => storedSecrets(editing));
  const [decoderId, setDecoderId] = useState(srcAny?.decoder ?? start.decoder ?? '');
  const [decValues, setDecValues] = useState<Record<string, unknown>>({});
  const [strict, setStrict] = useState(!!srcAny?.strict);
  const [mapping, setMapping] = useState<Mapping>(() => {
    const m = { ...(start.mapping ?? {}), ...(srcAny?.mapping ?? {}) } as Partial<Mapping>;
    return { ...BLANK_MAPPING, ...m, timestamp: { ...BLANK_MAPPING.timestamp, ...(m.timestamp ?? {}) }, signals: { ...BLANK_MAPPING.signals, ...(m.signals ?? {}) } };
  });
  const [savedId, setSavedId] = useState<string | null>(editing?.id ?? null);
  const [token, setToken] = useState<string | null>(null);
  const [ingestUrl, setIngestUrl] = useState<string | null>(srcAny?.ingest_url ?? null);
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [test, setTest] = useState<{ ok: boolean; text: string; sample?: string } | null>(null);
  const [q, setQ] = useState('');
  const [pushSample, setPushSample] = useState<string | null>(null);

  const transportRaw = transports?.find((t) => t.transport === transportId);
  const transport = useMemo(() => (transportRaw ? { ...transportRaw, config_fields: withSubjects(transportRaw) } : undefined), [transportRaw]);
  const decoderList = useMemo(() => {
    const all = decoders || [];
    const allowed = transport?.decoders;
    return allowed?.length ? all.filter((d) => allowed.includes(d.name)) : all;
  }, [decoders, transport]);
  const decoder = decoderList.find((d) => d.name === decoderId) ?? (decoders || []).find((d) => d.name === decoderId);

  // values start from the declaration, or from the source being changed
  useEffect(() => {
    if (!transport) return;
    const legacy: Record<string, unknown> = editing ? { broker_url: editing.broker_url, subjects: (editing as { subjects?: string[] }).subjects ?? editing.topics, raw_topics: editing.raw_topics, username: editing.username } : {};
    setValues(initialValues(transport.config_fields, { ...legacy, ...(start.config ?? {}), ...(srcAny?.config ?? {}) }));
    if (!decoderId) setDecoderId(transport.default_decoder ?? transport.decoders?.[0] ?? '');
  }, [transport?.transport]);
  useEffect(() => {
    if (decoder) setDecValues(initialValues(decoder.config_fields, srcAny?.decoder_config ?? {}));
  }, [decoder?.name]);

  const nameErr = nameProblem(name, existingNames.filter((n) => n !== editing?.name));
  const fieldErrs = Object.fromEntries((transport?.config_fields || []).map((f) => [f.key, fieldProblem(f, values[f.key], kept.has(f.key))]).filter(([, e]) => e));
  const decErrs = Object.fromEntries((decoder?.config_fields || []).map((f) => [f.key, fieldProblem(f, decValues[f.key], kept.has(f.key))]).filter(([, e]) => e));
  const mapErrs = needsMapping(decoder) ? mappingProblems(mapping) : {};
  const isPush = transportId === 'http_push';

  function payload() {
    const t = transport ? toPayload(transport.config_fields, values, kept) : { config: {}, secrets: {} };
    const d = decoder ? toPayload(decoder.config_fields, decValues, kept) : { config: {}, secrets: {} };
    const subj = values.subjects;
    return {
      name: name.trim(),
      transport: transportId,
      ...(subj !== undefined ? { subjects: splitList(subj) } : {}),
      config: t.config,
      secrets: { ...t.secrets, ...d.secrets },
      decoder: decoderId,
      decoder_config: d.config,
      strict,
      team_id: teamId || null,
    };
  }

  async function testUnsaved() {
    setShown(true);
    if (nameErr || Object.keys(fieldErrs).length) return;
    setBusy('test');
    setTest(null);
    try {
      const p = payload();
      const res = await apiFetch<ConnectionTest & { subjects_seen?: string[]; sample?: unknown }>(editing ? `/api/telemetry/connections/${editing.id}/test` : '/api/telemetry/connections/test', { method: 'POST', body: JSON.stringify(editing ? { config: p.config, secrets: p.secrets } : p) });
      const d = res.data;
      const r = describeTest({ ok: !!d?.ok, connected: !!d?.connected, messages: d?.messages ?? 0, topics_seen: d?.topics_seen ?? d?.subjects_seen ?? [], error: d?.error ?? null }, String(values.broker_url ?? values.url ?? values.bootstrap_servers ?? values.host ?? transport?.label ?? ''));
      setTest({ ...r, sample: d?.sample === undefined || d?.sample === null ? undefined : typeof d.sample === 'string' ? d.sample : JSON.stringify(d.sample, null, 2) });
    } catch (e) {
      setTest({ ok: false, text: explainTelemetryError(e, 'test') });
    } finally {
      setBusy(null);
    }
  }

  async function save(): Promise<boolean> {
    setShown(true);
    if (nameErr || Object.keys(fieldErrs).length || Object.keys(decErrs).length) return false;
    setBusy('save');
    setErr(null);
    try {
      // a push source starts with the asset taken from $.asset, which the test message carries
      const first = isPush && !mapping.node && !start.mapping ? { ...mapping, group: mapping.group || slug(name) || 'http', node: '$.asset' } : mapping;
      const body = savedId ? payload() : { ...payload(), mapping: first, enabled: isPush };
      if (first !== mapping) setMapping(first);
      const res = await apiFetch<Connection & { ingest_token?: string; token?: string; ingest_url?: string }>(savedId ? `/api/telemetry/connections/${savedId}` : '/api/telemetry/connections', { method: savedId ? 'PATCH' : 'POST', body: JSON.stringify(body) });
      if (res.data?.id) setSavedId(res.data.id);
      const tok = res.data?.ingest_token ?? res.data?.token;
      if (tok) setToken(tok);
      if (res.data?.ingest_url) setIngestUrl(res.data.ingest_url);
      onSaved();
      return true;
    } catch (e) {
      setErr(explainTelemetryError(e, 'save'));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function saveMapping(): Promise<boolean> {
    setShown(true);
    if (Object.keys(mapErrs).length || !savedId) return false;
    setBusy('save');
    setErr(null);
    try {
      await apiFetch(`/api/telemetry/connections/${savedId}`, { method: 'PATCH', body: JSON.stringify({ mapping }) });
      onSaved();
      return true;
    } catch (e) {
      setErr(explainTelemetryError(e, 'save'));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function testSaved() {
    if (!savedId) return;
    setBusy('test');
    setTest(null);
    try {
      const res = await apiFetch<ConnectionTest & { subjects_seen?: string[] }>(`/api/telemetry/connections/${savedId}/test`, { method: 'POST' });
      const d = res.data;
      setTest(describeTest({ ok: !!d?.ok, connected: !!d?.connected, messages: d?.messages ?? 0, topics_seen: d?.topics_seen ?? d?.subjects_seen ?? [], error: d?.error ?? null }, String(values.broker_url ?? values.url ?? transport?.label ?? '')));
    } catch (e) {
      setTest({ ok: false, text: explainTelemetryError(e, 'test') });
    } finally {
      setBusy(null);
    }
  }

  async function turnOn() {
    if (!savedId) return;
    setBusy('on');
    setErr(null);
    try {
      await apiFetch(`/api/telemetry/connections/${savedId}`, { method: 'PATCH', body: JSON.stringify({ enabled: true }) });
      toastSuccess(`${name.trim()} is on`, 'Its data shows up on the Assets tab as it arrives.');
      onSaved();
      onClose();
    } catch (e) {
      setErr(explainTelemetryError(e, 'toggle'));
    } finally {
      setBusy(null);
    }
  }

  // the first field with a problem may be scrolled away, bring it into view
  const showFirstProblem = () => setTimeout(() => {
    document.querySelector('[data-testid="tel-wizard"] [role="alert"]')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, 50);

  async function next() {
    setErr(null);
    if (step === 'transport') { if (transportId) { setStep('settings'); setShown(false); } return; }
    if (step === 'settings') {
      setShown(true);
      if (nameErr || Object.keys(fieldErrs).length) { showFirstProblem(); return; }
      setShown(false);
      setStep('decoder');
      return;
    }
    if (step === 'decoder') {
      if (!(await save())) { showFirstProblem(); return; }
      setShown(false);
      setStep(needsMapping(decoder) && !isPush ? 'mapping' : 'finish');
      return;
    }
    if (step === 'mapping') {
      if (!(await saveMapping())) { showFirstProblem(); return; }
      setShown(false);
      if (isPush) { toastSuccess('Mapping saved', 'New messages are stored with it from now on.'); onClose(); return; }
      setStep('finish');
    }
  }

  const order = isPush ? PUSH_STEPS : STEPS;
  const idx = order.findIndex((s) => s.id === step);
  const visibleSteps = order.filter((s) => s.id !== 'mapping' || needsMapping(decoder));
  const filtered = (transports || []).filter((t) => !q.trim() || `${t.label} ${t.transport} ${t.description ?? ''}`.toLowerCase().includes(q.trim().toLowerCase()));
  const groupsOf = (fields: FieldDecl[]) => {
    const g = new Map<string, FieldDecl[]>();
    for (const f of fields) g.set(f.group || '', [...(g.get(f.group || '') ?? []), f]);
    return Array.from(g.entries());
  };

  return (
    <ResponsiveModal open onClose={busy ? () => {} : onClose} title={editing ? `Change ${editing.name}` : 'Add a source'} maxWidth={step === 'mapping' ? 'max-w-5xl' : 'max-w-2xl'}>
      <div className="space-y-4" data-testid="tel-wizard" data-step={step}>
        <ol className="flex flex-wrap items-center gap-1 text-[11px]" aria-label="Steps">
          {visibleSteps.map((s, i) => {
            const pos = order.findIndex((x) => x.id === s.id);
            const done = pos < idx;
            const here = s.id === step;
            return (
              <li key={s.id} className="inline-flex items-center gap-1">
                <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 ${here ? 'border-cyan-400 bg-cyan-500/15 font-medium text-white' : done ? 'border-emerald-500/40 text-emerald-300' : 'border-slate-700 text-slate-500'}`} aria-current={here ? 'step' : undefined} data-testid={`tel-wiz-step-${s.id}`}>
                  {done ? <Check className="h-3 w-3" /> : <span className="tabular-nums">{i + 1}</span>} {s.label}
                </span>
                {i < visibleSteps.length - 1 && <span className="text-slate-600" aria-hidden>›</span>}
              </li>
            );
          })}
        </ol>

        {step === 'transport' && (
          <div className="space-y-3">
            <p className="text-sm text-slate-300">Where does the data come from? Pick how Abenix receives it. Machines, sensors and other software systems all work the same way after this step.</p>
            {(transports?.length ?? 0) > 6 && (
              <label className="relative block">
                <span className="sr-only">Find a kind of source</span>
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Kafka, OPC UA, webhook" className="w-full rounded-lg border border-slate-700 bg-slate-900 py-2 pl-8 pr-2 text-sm text-white placeholder:text-slate-500" />
              </label>
            )}
            {tLoading && !transports ? (
              <div className="grid gap-2 sm:grid-cols-2">{[0, 1, 2, 3].map((i) => <div key={i} className="h-20 animate-pulse rounded-lg bg-slate-800/40" />)}</div>
            ) : tErr || !transports ? (
              <p className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-100" role="alert">Could not load the kinds of source this server supports. Refresh the page, and if it keeps happening an admin can check the Alerts page.</p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Kind of source">
                {filtered.map((t) => (
                  <button key={t.transport} type="button" role="radio" aria-checked={transportId === t.transport} onClick={() => setTransportId(t.transport)} onDoubleClick={() => { setTransportId(t.transport); setStep('settings'); }} className={`flex min-w-0 items-start gap-3 rounded-lg border p-3 text-left ${transportId === t.transport ? 'border-cyan-400 bg-cyan-500/10' : 'border-slate-700 hover:border-slate-500'}`} data-testid={`tel-transport-${t.transport}`}>
                    <TransportIcon transport={t.transport} className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-white">{t.label}</span>
                      {t.description && <span className="mt-0.5 block text-xs text-slate-400">{t.description}</span>}
                      <span className="mt-1 flex flex-wrap gap-1 text-[10px] text-slate-400">
                        {t.capabilities?.receive && <span className="rounded border border-slate-700 px-1">{t.capabilities.receive === 'push' ? 'they send to Abenix' : t.capabilities.receive === 'poll' ? 'Abenix asks every few seconds' : 'Abenix listens'}</span>}
                        {t.capabilities?.write && <span className="rounded border border-slate-700 px-1">can write back</span>}
                      </span>
                    </span>
                  </button>
                ))}
                {!filtered.length && <p className="text-sm text-slate-400">Nothing matches. Clear the search to see every kind.</p>}
              </div>
            )}
          </div>
        )}

        {step === 'settings' && transport && (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm text-slate-300"><TransportIcon transport={transport.transport} className="h-4 w-4 text-cyan-300" /> {transport.label}{transport.description ? `. ${transport.description}` : ''}</p>
            <div>
              <label htmlFor="tel-src-name" className="mb-1 block text-xs font-medium text-slate-300">Name</label>
              <input id="tel-src-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={isPush ? 'Payments webhook' : 'Site broker'} className={`w-full rounded-md border bg-slate-950 px-2.5 py-2 text-sm text-white placeholder:text-slate-600 ${shown && nameErr ? 'border-rose-500/60' : 'border-slate-700'}`} data-testid="tel-src-name" />
              {shown && nameErr && <p className="mt-1 text-xs text-rose-300" role="alert">{nameErr}</p>}
            </div>
            {groupsOf(transport.config_fields).map(([g, fields]) => (
              <fieldset key={g || 'main'} className="space-y-3">
                {g && <legend className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">{g}</legend>}
                {fields.map((f) => (
                  <FieldInput key={f.key} field={f} value={values[f.key]} onChange={(v) => setValues((x) => ({ ...x, [f.key]: v }))} problem={shown ? (fieldErrs[f.key] as string | undefined) : null} stored={kept.has(f.key)} onReplace={() => setKept((k) => { const n = new Set(k); n.delete(f.key); return n; })} />
                ))}
              </fieldset>
            ))}
            <div>
              <label htmlFor="tel-src-team" className="mb-1 block text-xs font-medium text-slate-300">Who sees it</label>
              <select id="tel-src-team" value={teamId} onChange={(e) => setTeamId(e.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-2 text-sm text-white" data-testid="tel-src-team">
                <option value="">The whole workspace</option>
                {teams.map((t) => <option key={t.id} value={t.id}>Team {t.name}</option>)}
              </select>
              <p className="mt-1 text-xs text-slate-400">{teamId ? 'Only this team, admins and you see this source and its assets.' : 'Everyone in the workspace sees it. Teams are permission sets, made under Admin, Permissions.'}</p>
            </div>
            {!isPush && (
              <button type="button" onClick={testUnsaved} disabled={busy === 'test'} className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60" data-testid="tel-src-test">
                {busy === 'test' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} {busy === 'test' ? 'Testing for 5 seconds' : 'Test the connection'}
              </button>
            )}
          </div>
        )}

        {step === 'decoder' && (
          <div className="space-y-3">
            <p className="text-sm text-slate-300">What format are the messages in? Abenix decodes each one, then maps it to an asset and its signals.</p>
            <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Message format">
              {decoderList.map((d) => (
                <button key={d.name} type="button" role="radio" aria-checked={decoderId === d.name} onClick={() => setDecoderId(d.name)} className={`rounded-lg border p-3 text-left ${decoderId === d.name ? 'border-cyan-400 bg-cyan-500/10' : 'border-slate-700 hover:border-slate-500'}`} data-testid={`tel-decoder-${d.name}`}>
                  <span className="block text-sm font-medium text-white">{d.label}</span>
                  {d.description && <span className="mt-0.5 block text-xs text-slate-400">{d.description}</span>}
                </button>
              ))}
              {!decoderList.length && <p className="text-sm text-slate-400">Loading the formats</p>}
            </div>
            {decoder && decoder.config_fields.length > 0 && (
              <div className="space-y-3 rounded-lg border border-slate-700/60 p-3">
                {decoder.config_fields.map((f) => (
                  <FieldInput key={f.key} field={f} idPrefix="tel-dec" value={decValues[f.key]} onChange={(v) => setDecValues((x) => ({ ...x, [f.key]: v }))} problem={shown ? (decErrs[f.key] as string | undefined) : null} stored={isSecret(f) && kept.has(f.key)} onReplace={() => setKept((k) => { const n = new Set(k); n.delete(f.key); return n; })} />
                ))}
              </div>
            )}
            <label className="flex items-start gap-2 text-sm text-slate-200">
              <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} className="mt-1 accent-cyan-500" data-testid="tel-src-strict" />
              <span>Strict signals<span className="block text-xs text-slate-500">A signal the mapping does not know goes to Problems instead of being added. Leave off to let new signals register by themselves.</span></span>
            </label>
          </div>
        )}

        {step === 'mapping' && (
          <MappingEditor sourceId={savedId} decoder={decoderId} mapping={mapping} onChange={setMapping} sample={pushSample ?? test?.sample ?? start.sample ?? ''} subject={start.subject ?? ''} showProblems={shown} />
        )}

        {step === 'finish' && (
          <div className="space-y-3" data-testid="tel-wiz-finish">
            {isPush ? (
              <>
                <PushPanel sourceId={savedId} token={token} ingestUrl={ingestUrl} onSent={(sample) => setPushSample(sample)} testBody={start.sample} />
                {needsMapping(decoder) && (
                  <div className="rounded-lg border border-slate-700/60 p-3 text-sm text-slate-300" data-testid="tel-push-next">
                    {pushSample
                      ? 'Abenix has your test message. Next, say which asset it belongs to and which values to keep.'
                      : 'Once a message arrives, set up the mapping: which asset it belongs to and which values to keep. You can also do it later from Sources.'}
                    <button type="button" onClick={() => { setShown(false); setStep('mapping'); }} className="ml-2 inline-flex items-center gap-1 text-cyan-300 hover:underline" data-testid="tel-push-map">
                      Set up the mapping <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </>
            ) : (
              <>
                <p className="text-sm text-slate-300">{name.trim() || 'The source'} is saved and turned off. Test it, then turn it on to start storing data.</p>
                <button type="button" onClick={testSaved} disabled={busy === 'test'} className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60" data-testid="tel-wiz-test">
                  {busy === 'test' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} {busy === 'test' ? 'Testing for 5 seconds' : 'Test it'}
                </button>
              </>
            )}
          </div>
        )}

        {test && (step === 'settings' || step === 'finish') && (
          <p className={`flex items-start gap-1.5 rounded-lg border px-3 py-2 text-sm ${test.ok ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100' : 'border-rose-500/30 bg-rose-500/5 text-rose-100'}`} role="status" data-testid="tel-src-test-result" data-ok={test.ok ? 'true' : 'false'}>
            {test.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />} {test.text}
          </p>
        )}
        {err && <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert" data-testid="tel-wiz-error">{err}</p>}
        {shown && (Object.keys(fieldErrs).length > 0 || Object.keys(decErrs).length > 0 || (step === 'mapping' && Object.keys(mapErrs).length > 0)) && <p className="text-xs text-rose-300">Fix the fields marked in red, then carry on.</p>}

        <div className="flex flex-col-reverse gap-2 border-t border-slate-800 pt-3 sm:flex-row sm:items-center">
          <button type="button" onClick={onClose} disabled={!!busy} className="min-h-[40px] rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-slate-800">{savedId && step !== 'settings' ? 'Finish later' : 'Cancel'}</button>
          <span className="flex-1" />
          {idx > 0 && step !== 'finish' && !(editing && step === 'settings') && (
            <button type="button" onClick={() => { setErr(null); const prev = order[idx - 1].id; setStep(prev === 'mapping' && !needsMapping(decoder) ? 'decoder' : prev); }} disabled={!!busy} className="inline-flex min-h-[40px] items-center justify-center gap-1 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
              <ArrowLeft className="h-4 w-4" /> Back
            </button>
          )}
          {step !== 'finish' ? (
            <button type="button" onClick={next} disabled={!!busy || (step === 'transport' && !transportId)} title={step === 'transport' && !transportId ? 'Pick a kind of source first' : undefined} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-60" data-testid="tel-wiz-next">
              {busy === 'save' && <Loader2 className="h-4 w-4 animate-spin" />}
              {step === 'decoder' ? (savedId ? 'Save' : 'Save, still turned off') : step === 'mapping' ? 'Save the mapping' : 'Next'} <ArrowRight className="h-4 w-4" />
            </button>
          ) : editing?.enabled || isPush ? (
            <button type="button" onClick={() => { onSaved(); onClose(); }} className="min-h-[40px] rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400" data-testid="tel-wiz-done">Done</button>
          ) : (
            <button type="button" onClick={turnOn} disabled={busy === 'on'} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-400 disabled:opacity-60" data-testid="tel-wiz-turn-on">
              {busy === 'on' && <Loader2 className="h-4 w-4 animate-spin" />} Turn it on
            </button>
          )}
        </div>
      </div>
    </ResponsiveModal>
  );
}
