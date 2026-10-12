'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft, ArrowRight, Car, Check, CheckCircle2, Cpu, Factory, FileText, Loader2, MapPin, Plus, Radio, RadioTower, Wifi, X,
  type LucideIcon,
} from 'lucide-react';
import { useEscapeToClose } from '@/hooks/useEscapeToClose';
import CollectorForm from './CollectorForm';
import InstallPanel from './InstallPanel';
import {
  checkCollector, keepShown, blurCheck, defaultsFor, duration, edgeCall, telemetryHref, timeAgo,
  type Catalog, type CollectorSpec, type CollectorType, type Gateway, type InstallOut,
} from './model';
import { pluralShown } from '@/lib/plural';

const ICONS: Record<string, LucideIcon> = { can: Car, modbus: Factory, opcua: Cpu, nmea_gps: MapPin, mqtt_bridge: Radio, file_tail: FileText };
const CATEGORY: Record<string, string> = { vehicle: 'Trucks, vans and machines', plc: 'Machinery and PLCs', sensor: 'Sensors and hubs', software: 'Files and programs' };
const STEPS = ['What it collects', 'Settings', 'Install', 'First start', 'First data'] as const;

export interface WizardStart {
  collector?: string | null;
  gateway?: Gateway | null;
  step?: number;
}

function StepBar({ step }: { step: number }) {
  return (
    <ol className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]" aria-label="Steps">
      {STEPS.map((s, i) => (
        <li key={s} className={`flex items-center gap-1 ${i === step ? 'text-cyan-200' : i < step ? 'text-emerald-300' : 'text-slate-500'}`} aria-current={i === step ? 'step' : undefined}>
          <span className={`flex h-4 w-4 items-center justify-center rounded-full border text-[10px] ${i === step ? 'border-cyan-400' : i < step ? 'border-emerald-400' : 'border-slate-600'}`}>
            {i < step ? <Check className="h-2.5 w-2.5" /> : i + 1}
          </span>
          {s}
        </li>
      ))}
    </ol>
  );
}

export default function AddGatewayWizard({ open, onClose, catalog, start, onChanged }: {
  open: boolean;
  onClose: () => void;
  catalog: Catalog | null;
  start: WizardStart;
  onChanged: () => void;
}) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState('');
  const [nameProblem, setNameProblem] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [specs, setSpecs] = useState<CollectorSpec[]>([]);
  const [problems, setProblems] = useState<Record<number, Record<string, string>>>({});
  const [agents, setAgents] = useState(false);
  const [gw, setGw] = useState<Gateway | null>(null);
  const [install, setInstall] = useState<InstallOut | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [waitedS, setWaitedS] = useState(0);
  const [confirmClose, setConfirmClose] = useState(false);
  const types = useMemo(() => new Map((catalog?.types || []).map((t) => [t.type, t] as const)), [catalog]);
  const initialised = useRef(false);

  useEffect(() => {
    if (!open) { initialised.current = false; return; }
    if (initialised.current || !catalog) return;
    initialised.current = true;
    setErr(null);
    setInstall(null);
    setConfirmClose(false);
    if (start.gateway) {
      const g = start.gateway;
      setGw(g);
      setName(g.name);
      setSpecs((g.collectors || []).map((c) => ({ ...c })));
      setPicked(Array.from(new Set((g.collectors || []).map((c) => c.type))));
      setAgents((g.roles || []).includes('agents'));
      setStep(start.step ?? 1);
    } else {
      setGw(null);
      setName('');
      const first = start.collector && types.has(start.collector) ? [start.collector] : [];
      setPicked(first);
      setSpecs(first.map((t) => defaultsFor(types.get(t) as CollectorType, '', 0)));
      setAgents(false);
      setStep(0);
    }
    setProblems({});
  }, [open, catalog, start, types]);

  const dirty = !gw && (picked.length > 0 || name.trim().length > 0);
  const tryClose = useCallback(() => {
    if (dirty && step < 2) setConfirmClose(true);
    else onClose();
  }, [dirty, step, onClose]);
  useEscapeToClose(open, tryClose);

  // poll while waiting for the gateway to start and send
  useEffect(() => {
    if (!open || !gw || step < 3) return;
    const t0 = Date.now();
    const h = setInterval(async () => {
      setWaitedS(Math.floor((Date.now() - t0) / 1000));
      const r = await edgeCall<Gateway>(`/api/edge/gateways/${gw.id}`);
      if (r.data) {
        setGw(r.data);
        if (step === 3 && r.data.enrolled_at && r.data.status === 'online') setStep(4);
      }
    }, 3000);
    return () => clearInterval(h);
  }, [open, gw?.id, step]);

  if (!open) return null;

  const togglePick = (t: CollectorType) => {
    if (picked.includes(t.type)) {
      setPicked(picked.filter((x) => x !== t.type));
      setSpecs(specs.filter((s) => s.type !== t.type));
    } else {
      setPicked([...picked, t.type]);
      setSpecs([...specs, defaultsFor(t, name, specs.filter((s) => s.type === t.type).length)]);
    }
  };

  const addAnother = (t: CollectorType) => setSpecs([...specs, defaultsFor(t, name, specs.filter((s) => s.type === t.type).length)]);

  const validateAll = (): boolean => {
    const all: Record<number, Record<string, string>> = {};
    specs.forEach((c, i) => {
      const t = types.get(c.type);
      if (t) {
        const p = checkCollector(c, t);
        if (Object.keys(p).length) all[i] = p;
      }
    });
    setProblems(all);
    const np = !name.trim() ? 'Give the gateway a name, such as Yard gateway or Truck 12' : name.length > 80 ? 'Keep the name under 80 characters' : null;
    setNameProblem(np);
    return !np && Object.keys(all).length === 0;
  };

  const focusFirstProblem = () => {
    setTimeout(() => {
      const el = document.querySelector<HTMLElement>('[data-testid="edge-wizard"] [aria-invalid="true"]');
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el?.focus({ preventScroll: true });
    }, 50);
  };

  const save = async () => {
    setErr(null);
    if (!validateAll()) {
      setErr('Some settings need a look. They are marked in red.');
      focusFirstProblem();
      return;
    }
    if (specs.length === 0 && !agents) {
      setErr('Pick at least one thing to collect from, or let the gateway run agents.');
      return;
    }
    setSaving(true);
    const roles = [...(specs.length ? ['collect'] : []), ...(agents ? ['agents'] : [])];
    const body = { name: name.trim(), roles, collectors: specs };
    const r = gw
      ? await edgeCall<Gateway>(`/api/edge/gateways/${gw.id}`, 'PATCH', body)
      : await edgeCall<Gateway>('/api/edge/gateways', 'POST', body);
    setSaving(false);
    if (r.error || !r.data) {
      setErr(r.error);
      const det = r.details?.collectors as Record<string, Record<string, string>> | undefined;
      if (det) {
        setProblems(Object.fromEntries(Object.entries(det).map(([k, v]) => [Number(k), v])));
        focusFirstProblem();
      }
      return;
    }
    setGw(r.data);
    onChanged();
    if (gw && gw.enrolled_at) {
      onClose();
      return;
    }
    setStep(2);
  };

  const assets = gw?.assets || [];
  const firstGroup = specs[0]?.asset?.group;

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/70 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-label="Add an edge gateway" data-testid="edge-wizard">
      <div className="flex h-full w-full max-w-4xl flex-col overflow-hidden border-slate-700 bg-slate-900 sm:h-auto sm:max-h-[92vh] sm:rounded-xl sm:border">
        <div className="flex items-start justify-between gap-3 border-b border-slate-800 p-4">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-white">{gw && start.gateway ? `Change ${gw.name}` : 'Add an edge gateway'}</h2>
            <div className="mt-2"><StepBar step={step} /></div>
          </div>
          <button type="button" onClick={tryClose} aria-label="Close" className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white" data-testid="edge-wizard-close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {confirmClose && (
            <div className="mb-3 rounded-md border border-amber-600/40 bg-amber-900/20 p-3 text-sm text-amber-100" role="alertdialog" aria-label="Leave without saving">
              <p>Leave without saving? What you picked here is not kept.</p>
              <div className="mt-2 flex gap-2">
                <button type="button" onClick={onClose} className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500" data-testid="edge-wizard-discard">Leave</button>
                <button type="button" onClick={() => setConfirmClose(false)} className="rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800">Keep going</button>
              </div>
            </div>
          )}

          {step === 0 && (
            <div className="space-y-4">
              <p className="text-sm text-slate-300">
                Abenix Edge is a small program Abenix ships for things that cannot reach Abenix on their own: a vehicle&apos;s CAN bus, a serial Modbus meter, a GPS, or PLCs on a closed site network. It runs on a Linux box next to them, keeps readings on disk while the link is down, and sends them in order when it is back.
              </p>
              <p className="text-xs text-slate-400">
                If your devices or their cloud can already send MQTT, HTTP, Kafka or OPC UA to Abenix, you do not need a gateway. Use <Link href="/telemetry?guide=1" className="text-cyan-300 underline">Telemetry, Get started</Link> instead.
              </p>
              <h3 className="text-sm font-medium text-white">What will this gateway collect from? Pick one or more.</h3>
              {(['vehicle', 'plc', 'sensor', 'software'] as const).map((cat) => {
                const list = (catalog?.types || []).filter((t) => t.category === cat);
                if (!list.length) return null;
                return (
                  <div key={cat}>
                    <p className="mb-1.5 text-[11px] uppercase tracking-wider text-slate-500">{CATEGORY[cat]}</p>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {list.map((t) => {
                        const Icon = ICONS[t.type] || RadioTower;
                        const on = picked.includes(t.type);
                        return (
                          <button key={t.type} type="button" onClick={() => togglePick(t)} aria-pressed={on} className={`flex min-w-0 items-start gap-3 rounded-lg border p-3 text-left transition-colors ${on ? 'border-cyan-500/60 bg-cyan-500/10' : 'border-slate-700 bg-slate-800/40 hover:border-slate-500'}`} data-testid={`edge-pick-${t.type}`}>
                            <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${on ? 'text-cyan-300' : 'text-slate-400'}`} />
                            <span className="min-w-0">
                              <span className="flex items-center gap-1.5 text-sm font-medium text-white">{t.label}{on && <CheckCircle2 className="h-3.5 w-3.5 text-cyan-300" />}</span>
                              <span className="mt-0.5 block text-[11px] leading-snug text-slate-400">{t.description}</span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              <label className="flex items-start gap-2 rounded-lg border border-slate-700 bg-slate-800/30 p-3 text-sm text-slate-200">
                <input type="checkbox" className="mt-1 accent-cyan-500" checked={agents} onChange={(e) => setAgents(e.target.checked)} data-testid="edge-pick-agents" />
                <span>
                  Also run agents on this gateway
                  <span className="block text-[11px] text-slate-400">Edge ready agents can then be sent to it from this page and answer next to the machines, even offline.</span>
                </span>
              </label>
            </div>
          )}

          {step === 1 && catalog && (
            <div className="space-y-4">
              <div className="min-w-0">
                <label htmlFor="edge-gw-name" className="text-xs font-medium text-slate-200">Gateway name <span className="text-rose-300">*</span></label>
                <p className="text-[11px] text-slate-400">The box this runs on. Example: Yard gateway, Truck 12, Line 2 cabinet.</p>
                <input id="edge-gw-name" className={`mt-1 w-full rounded-md border bg-slate-950 px-2.5 py-2 text-sm text-white ${nameProblem ? 'border-rose-500/60' : 'border-slate-700'}`} value={name} onChange={(e) => { setName(e.target.value); setNameProblem(null); }} placeholder="Yard gateway" data-testid="edge-gw-name" aria-invalid={!!nameProblem} maxLength={80} />
                {nameProblem && <p role="alert" className="mt-1 text-[11px] text-rose-300" data-testid="edge-gw-name-problem">{nameProblem}</p>}
              </div>
              {specs.length === 0 && (
                <p className="rounded-md border border-slate-700 bg-slate-800/30 p-3 text-sm text-slate-300">Nothing to collect yet. Go back and pick what the gateway reads, or keep it for agents only.</p>
              )}
              {specs.map((c, i) => {
                const t = types.get(c.type);
                if (!t) return null;
                return (
                  <CollectorForm
                    key={`${c.id || 'new'}-${i}`}
                    t={t}
                    c={c}
                    idx={i}
                    assetHelp={catalog.asset_help}
                    problems={problems[i] || {}}
                    onFieldBlur={(key) => setProblems((prev) => ({ ...prev, [i]: blurCheck(checkCollector(c, t), prev[i], key) }))}
                    onChange={(next) => {
                      const copy = specs.slice();
                      copy[i] = next;
                      setSpecs(copy);
                      if (problems[i]) setProblems({ ...problems, [i]: keepShown(checkCollector(next, t), problems[i]) });
                    }}
                    onRemove={() => {
                      const copy = specs.filter((_, j) => j !== i);
                      setSpecs(copy);
                      setPicked(Array.from(new Set(copy.map((s) => s.type))));
                      setProblems({});
                    }}
                  />
                );
              })}
              {specs.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {Array.from(new Set(specs.map((s) => s.type))).map((tt) => {
                    const t = types.get(tt);
                    return t ? (
                      <button key={tt} type="button" onClick={() => addAnother(t)} className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 hover:border-cyan-500/50 hover:text-cyan-200" data-testid={`edge-add-another-${tt}`}>
                        <Plus className="h-3.5 w-3.5" /> Another {t.label.toLowerCase()}
                      </button>
                    ) : null;
                  })}
                </div>
              )}
            </div>
          )}

          {step === 2 && gw && (
            <div className="space-y-3">
              <p className="text-sm text-slate-300">
                <strong className="text-white">{gw.name}</strong> is saved. Make its install command and run it on the box. The command holds a one-time token, so the gateway can sign in once and get its own key.
              </p>
              <InstallPanel gateway={gw} install={install} onInstall={(o) => { setInstall(o); setGw(o.gateway); onChanged(); }} canManage />
            </div>
          )}

          {step === 3 && gw && (
            <div className="space-y-3" data-testid="edge-waiting" aria-live="polite">
              {gw.enrolled_at ? (
                <p className="flex items-center gap-2 text-sm text-emerald-200"><CheckCircle2 className="h-4 w-4" /> {gw.name} started and enrolled {timeAgo(gw.enrolled_at)}.</p>
              ) : (
                <div className="flex items-start gap-3 rounded-lg border border-sky-500/30 bg-sky-500/5 p-4">
                  <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-sky-300" />
                  <div className="min-w-0 text-sm text-slate-200">
                    <p className="font-medium text-white">Waiting for {gw.name} to start</p>
                    <p className="mt-1 text-xs text-slate-400">This page checks every few seconds. The gateway enrols within seconds of starting.</p>
                    {waitedS > 60 && (
                      <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-300">
                        <li>Look at the gateway&apos;s log: <code className="break-all text-cyan-200">docker logs abenix-edge-{gw.gateway_id}</code>, or <code className="text-cyan-200">journalctl -u abenix-edge</code>.</li>
                        <li>&quot;Could not reach Abenix&quot; means the address in the command does not work from that box.</li>
                        <li>&quot;Enrolment refused&quot; means the token was used or replaced. Go back one step and make a new command.</li>
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {step === 4 && gw && (
            <div className="space-y-3" data-testid="edge-first-data" aria-live="polite">
              <p className="flex items-center gap-2 text-sm text-emerald-200"><Wifi className="h-4 w-4" /> {gw.name} is online{gw.version ? `, Abenix Edge ${gw.version}` : ''}{gw.platform ? ` on ${gw.platform}` : ''}.</p>
              {(gw.collector_health || []).length > 0 && (
                <ul className="space-y-1 text-xs">
                  {gw.collector_health.map((c) => (
                    <li key={c.id} className="rounded border border-slate-800 bg-slate-950/40 px-2 py-1.5">
                      <span className="text-slate-200">{c.name}</span>{' '}
                      <span className={c.status === 'running' ? 'text-emerald-300' : c.status === 'error' ? 'text-rose-300' : 'text-sky-300'}>{c.status === 'running' ? 'running' : c.status === 'error' ? 'needs attention' : c.status}</span>
                      {c.error && <span className="block break-words text-rose-200">{c.error}</span>}
                    </li>
                  ))}
                </ul>
              )}
              {assets.length === 0 ? (
                <div className="flex items-start gap-3 rounded-lg border border-slate-700 bg-slate-800/30 p-4">
                  <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-cyan-300" />
                  <div className="text-sm text-slate-300">
                    <p className="font-medium text-white">Waiting for the first readings in Telemetry</p>
                    <p className="mt-1 text-xs text-slate-400">They show up once a collector reads its device and the first batch is sent, usually within a few seconds.{waitedS > 45 ? ' A collector marked needs attention above says what to fix.' : ''}</p>
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4">
                  <p className="flex items-center gap-2 text-sm font-medium text-emerald-200"><CheckCircle2 className="h-4 w-4" /> Data is flowing. {assets.length} {assets.length === 1 ? 'asset' : 'assets'} in Telemetry.</p>
                  <ul className="mt-2 space-y-1 text-xs">
                    {assets.slice(0, 8).map((a) => (
                      <li key={`${a.group}/${a.node}/${a.device}`}>
                        <Link href={telemetryHref(gw, a)} className="font-mono text-cyan-300 hover:underline">{a.group} / {a.node}{a.device ? ` / ${a.device}` : ''}</Link>
                        <span className="text-slate-500"> · {pluralShown(a.metric_count ?? 0, (a.metric_count ?? 0).toLocaleString('en-US'), 'signal')}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[11px] text-slate-400">Buffer: {pluralShown(gw.buffer?.depth ?? 0, (gw.buffer?.depth ?? 0).toLocaleString('en-US'), 'reading')} waiting, oldest {duration(gw.buffer?.oldest_age_s)}.</p>
                </div>
              )}
            </div>
          )}

          {err && <p role="alert" className="mt-3 text-sm text-rose-300" data-testid="edge-wizard-error">{err}</p>}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-slate-800 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            {step > 0 && step !== 3 && step !== 4 && (
              <button type="button" onClick={() => setStep(step - 1)} className="inline-flex min-h-[40px] w-full items-center justify-center gap-1.5 rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 sm:w-auto" data-testid="edge-wizard-back">
                <ArrowLeft className="h-4 w-4" /> Back
              </button>
            )}
            {step === 3 && (
              <button type="button" onClick={() => setStep(2)} className="inline-flex min-h-[40px] w-full items-center justify-center gap-1.5 rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 sm:w-auto">
                <ArrowLeft className="h-4 w-4" /> Back to the install command
              </button>
            )}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            {step === 0 && (
              <button type="button" disabled={picked.length === 0 && !agents} onClick={() => setStep(1)} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50" data-testid="edge-wizard-next" title={picked.length === 0 && !agents ? 'Pick at least one thing to collect from' : undefined}>
                Next: settings <ArrowRight className="h-4 w-4" />
              </button>
            )}
            {step === 1 && (
              <button type="button" disabled={saving} onClick={save} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50" data-testid="edge-wizard-save">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                {gw?.enrolled_at ? 'Save changes' : 'Save and get the install command'}
              </button>
            )}
            {step === 2 && (
              <button type="button" disabled={!install} onClick={() => setStep(3)} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50" data-testid="edge-wizard-ran" title={!install ? 'Make the install command first' : undefined}>
                I ran it, wait for the gateway <ArrowRight className="h-4 w-4" />
              </button>
            )}
            {step === 4 && (
              <>
                <button type="button" onClick={onClose} className="inline-flex min-h-[40px] items-center justify-center rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">Done</button>
                <Link href={firstGroup ? `/telemetry?grp=${encodeURIComponent(String(firstGroup))}` : '/telemetry'} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500" data-testid="edge-wizard-telemetry">
                  Open in Telemetry <ArrowRight className="h-4 w-4" />
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
