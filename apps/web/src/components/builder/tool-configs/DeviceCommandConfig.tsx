'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Loader2, Plus, RefreshCw, ShieldCheck, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import {
  APPROVAL_MODES, TIERS, patternProblem, policyProblems, policySentence, readPolicy,
  type CommandPolicy, type Target, type TargetSignal,
} from '@/lib/telemetry/commandPolicy';

interface Props {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  disabled?: boolean;
}

interface Targets {
  assets: Target[];
  total: number;
  tags: Array<{ tag: string; count: number }>;
  types: string[];
  tiers: Record<string, string>;
  can_command: boolean;
}

const inputCls = 'w-full px-3 py-2 bg-slate-900/50 border rounded-lg text-xs text-white placeholder-slate-600 focus:outline-none disabled:opacity-60';
const TIER_WORDS: Record<string, string> = { allow: 'runs without asking', approval: 'asks a person first', block: 'blocks the call' };

function Chips({ items, onRemove, testId, disabled }: { items: string[]; onRemove: (v: string) => void; testId: string; disabled?: boolean }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5" data-testid={testId}>
      {items.map((v) => (
        <span key={v} className="inline-flex max-w-full items-center gap-1 rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-100">
          <span className="truncate font-mono">{v}</span>
          {!disabled && (
            <button type="button" onClick={() => onRemove(v)} aria-label={`Remove ${v}`} className="rounded-full p-0.5 hover:bg-cyan-500/20">
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

export default function DeviceCommandConfig({ values, onChange, disabled }: Props) {
  const policy = useMemo(() => readPolicy(values.policy), [values.policy]);
  const [targets, setTargets] = useState<Targets | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [assetPick, setAssetPick] = useState('');
  const [customAsset, setCustomAsset] = useState('');
  const [customSignal, setCustomSignal] = useState('');
  const [signals, setSignals] = useState<TargetSignal[] | null>(null);
  const [signalNote, setSignalNote] = useState('');
  const [signalsFor, setSignalsFor] = useState('');
  const problems = policyProblems(policy);

  const set = useCallback((p: Partial<CommandPolicy>) => {
    onChange({ ...values, policy: { ...policy, ...p } });
  }, [onChange, policy, values]);

  const load = useCallback(async () => {
    setLoadError(null);
    const res = await apiFetch<Targets>('/api/telemetry/loop/command-targets', { silent: true });
    if (res.data) setTargets(res.data);
    else setLoadError(res.error || 'Could not load the assets.');
  }, []);

  useEffect(() => { void load(); }, [load]);

  // the first named asset feeds the signal list
  const firstAsset = useMemo(() => policy.assets.find((a) => !a.includes('*') && !a.includes(':') && a.split('/').length >= 2) || '', [policy.assets]);
  useEffect(() => {
    if (!firstAsset || firstAsset === signalsFor) return;
    const [g, n] = firstAsset.split('/');
    setSignalsFor(firstAsset);
    setSignals(null);
    void apiFetch<TargetSignal[]>(`/api/telemetry/loop/command-targets/signals?group=${encodeURIComponent(g)}&node=${encodeURIComponent(n)}`, { silent: true })
      .then((res) => {
        setSignals(res.data || []);
        setSignalNote(res.data ? String((res.meta as Record<string, unknown> | null)?.note || '') : res.error || 'Could not load its signals.');
      });
  }, [firstAsset, signalsFor]);

  const addAsset = (v: string) => {
    const s = v.trim();
    if (!s || policy.assets.includes(s) || patternProblem(s)) return;
    set({ assets: [...policy.assets, s] });
  };
  const addSignal = (v: string) => {
    const s = v.trim();
    if (!s || policy.signals.includes(s) || patternProblem(s)) return;
    set({ signals: [...policy.signals, s] });
  };

  const assetErr = customAsset ? patternProblem(customAsset) : null;
  const signalErr = customSignal ? patternProblem(customSignal) : null;
  const tierAction = targets?.tiers?.[policy.tier] || 'allow';

  return (
    <div className="space-y-4" data-testid="device-command-policy">
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2.5">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
        <p className="text-[11px] leading-relaxed text-amber-100">
          This tool changes real assets. The agent may only command what you pick here, everything else is refused with a plain message. It runs as the person the agent runs for, who needs Send machine commands.
        </p>
      </div>

      {targets && !targets.can_command && (
        <p className="rounded-lg border border-slate-700 bg-slate-900/50 p-2.5 text-[11px] text-slate-300" data-testid="policy-no-command">
          You do not have Send machine commands yourself, so runs you start will be refused. An admin can add you to Machine operators under Admin, Permissions.
        </p>
      )}

      <section className="space-y-2">
        <p className="text-xs font-medium text-slate-200">What it may touch</p>
        <p className="text-[10px] text-slate-500">Assets by key, all parts of an asset, a tag or a type. A * matches anything, like groundwork/ipc-*.</p>
        <Chips items={policy.assets} onRemove={(v) => set({ assets: policy.assets.filter((x) => x !== v) })} testId="policy-assets" disabled={disabled} />
        {!targets && !loadError && (
          <p className="flex items-center gap-1.5 text-[11px] text-slate-400"><Loader2 className="h-3 w-3 animate-spin" /> Loading streaming assets</p>
        )}
        {loadError && (
          <div className="flex items-center justify-between gap-2 rounded-lg border border-rose-500/30 bg-rose-500/5 p-2 text-[11px] text-rose-200" role="alert">
            <span>{loadError}</span>
            <button type="button" onClick={() => void load()} className="inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-rose-500/10"><RefreshCw className="h-3 w-3" /> Retry</button>
          </div>
        )}
        {targets && targets.assets.length === 0 && (
          <p className="rounded-lg border border-dashed border-slate-700 p-2.5 text-[11px] text-slate-400" data-testid="policy-no-assets">
            No assets are streaming yet. <Link href="/telemetry" className="text-cyan-300 hover:underline">Connect a source on Telemetry</Link>, or type a key below.
          </p>
        )}
        {targets && targets.assets.length > 0 && !disabled && (
          <div className="flex gap-1.5">
            <select value={assetPick} onChange={(e) => setAssetPick(e.target.value)} className={`${inputCls} border-slate-700`} aria-label="Pick an asset, tag or type" data-testid="policy-asset-pick">
              <option value="">Pick an asset, tag or type</option>
              <optgroup label="Assets, with all their parts">
                {targets.assets.map((a) => (
                  <option key={a.key} value={`${a.group}/${a.node}`}>{a.name} ({a.group}/{a.node}){a.online === false ? ', offline' : ''}</option>
                ))}
              </optgroup>
              {targets.tags.length > 0 && (
                <optgroup label="Every asset with a tag">
                  {targets.tags.map((t) => <option key={t.tag} value={`tag:${t.tag}`}>tag: {t.tag} ({t.count})</option>)}
                </optgroup>
              )}
              <optgroup label="Every asset of a type">
                {targets.types.map((t) => <option key={t} value={`type:${t}`}>type: {t}</option>)}
              </optgroup>
            </select>
            <button type="button" disabled={!assetPick} onClick={() => { addAsset(assetPick); setAssetPick(''); }} title={assetPick ? 'Add it' : 'Pick something first'}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-700 px-2.5 text-xs text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50" data-testid="policy-asset-add">
              <Plus className="h-3.5 w-3.5" /> Add
            </button>
          </div>
        )}
        {!disabled && (
          <div>
            <div className="flex gap-1.5">
              <input value={customAsset} onChange={(e) => setCustomAsset(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !assetErr) { e.preventDefault(); addAsset(customAsset); setCustomAsset(''); } }}
                placeholder="or type one, like testbed/modbus-meter/plc" aria-label="Asset pattern" className={`${inputCls} ${assetErr ? 'border-rose-500/70' : 'border-slate-700'}`} data-testid="policy-asset-input" />
              <button type="button" disabled={!customAsset.trim() || !!assetErr} title={assetErr || (customAsset.trim() ? 'Add it' : 'Type a key or pattern first')} onClick={() => { addAsset(customAsset); setCustomAsset(''); }}
                className="inline-flex shrink-0 items-center rounded-lg border border-slate-700 px-2.5 text-xs text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50" data-testid="policy-asset-input-add">Add</button>
            </div>
            {assetErr && <p className="mt-1 text-[10px] text-rose-300" role="alert">{assetErr}</p>}
          </div>
        )}
        {problems.assets && <p className="text-[10px] text-amber-300" role="alert" data-testid="policy-assets-problem">{problems.assets}</p>}
      </section>

      <section className="space-y-2">
        <p className="text-xs font-medium text-slate-200">Signals it may set</p>
        <Chips items={policy.signals} onRemove={(v) => set({ signals: policy.signals.filter((x) => x !== v) })} testId="policy-signals" disabled={disabled} />
        {firstAsset && signals === null && <p className="flex items-center gap-1.5 text-[11px] text-slate-400"><Loader2 className="h-3 w-3 animate-spin" /> Reading what {firstAsset} reports</p>}
        {firstAsset && signals && !disabled && (
          <div>
            <p className="mb-1 text-[10px] text-slate-500">{signalNote || `What ${firstAsset} reports now.`}</p>
            {signals.filter((s) => s.writable).length === 0 ? (
              <p className="text-[11px] text-slate-400">No writable signals on {firstAsset}. Declare them in its source&apos;s mapping, or type one below.</p>
            ) : (
              <div className="flex max-h-40 flex-wrap gap-1.5 overflow-auto" data-testid="policy-signal-options">
                {signals.filter((s) => s.writable).slice(0, 60).map((s) => {
                  const on = policy.signals.includes(s.signal);
                  return (
                    <button key={`${s.part}/${s.signal}`} type="button" disabled={on} onClick={() => addSignal(s.signal)} title={on ? 'Already allowed' : `Allow ${s.signal}${s.part ? ` on ${s.part}` : ''}`}
                      className="rounded-full border border-slate-700 px-2 py-0.5 font-mono text-[10px] text-slate-300 hover:border-cyan-500/60 disabled:cursor-default disabled:opacity-40">
                      {s.signal}{s.part ? <span className="text-slate-500"> · {s.part}</span> : null}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
        {!firstAsset && <p className="text-[10px] text-slate-500">Add one named asset above to pick from what it reports, or type signal names.</p>}
        {!disabled && (
          <div>
            <div className="flex gap-1.5">
              <input value={customSignal} onChange={(e) => setCustomSignal(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !signalErr) { e.preventDefault(); addSignal(customSignal); setCustomSignal(''); } }}
                placeholder="like Mode/Set or Setpoint*" aria-label="Signal name or pattern" className={`${inputCls} ${signalErr ? 'border-rose-500/70' : 'border-slate-700'}`} data-testid="policy-signal-input" />
              <button type="button" disabled={!customSignal.trim() || !!signalErr} title={signalErr || (customSignal.trim() ? 'Add it' : 'Type a signal first')} onClick={() => { addSignal(customSignal); setCustomSignal(''); }}
                className="inline-flex shrink-0 items-center rounded-lg border border-slate-700 px-2.5 text-xs text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50" data-testid="policy-signal-input-add">Add</button>
            </div>
            {signalErr && <p className="mt-1 text-[10px] text-rose-300" role="alert">{signalErr}</p>}
          </div>
        )}
        {problems.signals && <p className="text-[10px] text-amber-300" role="alert" data-testid="policy-signals-problem">{problems.signals}</p>}
      </section>

      <section className="space-y-2">
        <p className="text-xs font-medium text-slate-200">When a person approves</p>
        <div className="space-y-1.5" role="radiogroup" aria-label="When a person approves">
          {APPROVAL_MODES.map((m) => (
            <label key={m.value} className={`flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-2 ${policy.approval === m.value ? 'border-cyan-500/60 bg-cyan-500/10' : 'border-slate-700'}`}>
              <input type="radio" className="mt-0.5 accent-cyan-500" checked={policy.approval === m.value} disabled={disabled} onChange={() => set({ approval: m.value })} data-testid={`policy-approval-${m.value}`} />
              <span>
                <span className="block text-xs text-slate-100">{m.label}</span>
                <span className="block text-[10px] text-slate-400">{m.help}</span>
              </span>
            </label>
          ))}
        </div>
        {policy.approval === 'tier' && (
          <div>
            <label className="mb-1 block text-[10px] text-slate-400" htmlFor="policy-tier">It counts as</label>
            <select id="policy-tier" value={policy.tier} disabled={disabled} onChange={(e) => set({ tier: e.target.value as CommandPolicy['tier'] })} className={`${inputCls} border-slate-700`} data-testid="policy-tier">
              {TIERS.map((t) => <option key={t} value={t}>{t} risk</option>)}
            </select>
            <p className="mt-1 text-[10px] text-slate-400" data-testid="policy-tier-rule">
              {targets ? <>Your workspace {TIER_WORDS[tierAction] || tierAction} at {policy.tier} risk. Admins set it under <Link href="/admin/risk" className="text-cyan-300 hover:underline">Risk tiers</Link>.</> : 'Reading your workspace rule'}
            </p>
          </div>
        )}
        <p className="flex items-start gap-1.5 text-[10px] text-slate-500">
          <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0" />
          <span>Approvals show on <Link href="/approvals" className="text-cyan-300 hover:underline">Approvals</Link> with the asset, the value, the agent&apos;s reason and recent history. Once the agent earns an <Link href="/autonomy" className="text-cyan-300 hover:underline">Earned Autonomy</Link> grant for device_command, the grant&apos;s level decides instead.</span>
        </p>
      </section>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-[10px] text-slate-400" htmlFor="policy-rate">Commands a minute, at most</label>
          <input id="policy-rate" type="number" min={1} max={600} value={policy.rate_per_minute} disabled={disabled}
            onChange={(e) => set({ rate_per_minute: Number(e.target.value) })} className={`${inputCls} ${problems.rate_per_minute ? 'border-rose-500/70' : 'border-slate-700'}`} data-testid="policy-rate" />
          {problems.rate_per_minute && <p className="mt-1 text-[10px] text-rose-300" role="alert">{problems.rate_per_minute}</p>}
        </div>
        <div>
          <label className="mb-1 block text-[10px] text-slate-400" htmlFor="policy-confirm">Wait for confirmation (ms)</label>
          <input id="policy-confirm" type="number" min={0} max={10000} step={500} value={policy.confirm_timeout_ms} disabled={disabled}
            onChange={(e) => set({ confirm_timeout_ms: Number(e.target.value) })} className={`${inputCls} ${problems.confirm_timeout_ms ? 'border-rose-500/70' : 'border-slate-700'}`} data-testid="policy-confirm" />
          {problems.confirm_timeout_ms && <p className="mt-1 text-[10px] text-rose-300" role="alert">{problems.confirm_timeout_ms}</p>}
        </div>
      </div>
      <p className="text-[10px] text-slate-500">Confirmation waits for the asset to report the new value back. 0 answers as soon as the command is published.</p>

      <p className="rounded-lg border border-slate-700/60 bg-slate-900/40 p-2.5 text-[11px] text-slate-300" data-testid="policy-summary">{policySentence(policy)}</p>
    </div>
  );
}
