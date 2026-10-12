'use client';

import { useState } from 'react';
import { COND_INFO, blankCondition, type CondKind, type Condition, type Scope } from './lib';
import GeofenceEditor from './GeofenceEditor';
import SignalPicker, { useSignals } from './SignalPicker';
import { Choice, Field, cls } from './ui';

const KINDS = Object.keys(COND_INFO) as CondKind[];

function NumberInput({ id, value, onChange, error, placeholder, disabled, testId, step = 'any', min }: {
  id: string; value: unknown; onChange: (v: string) => void; error?: string; placeholder?: string; disabled?: boolean; testId: string; step?: string; min?: number;
}) {
  return (
    <input
      id={id}
      type="number"
      inputMode="decimal"
      step={step}
      min={min}
      value={value === null || value === undefined ? '' : String(value)}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className={`${cls(error)} tabular-nums`}
      data-testid={testId}
    />
  );
}

// the form speaks minutes, the rule keeps seconds
function minutes(v: unknown): string {
  const n = Number(v);
  return v === '' || v === null || v === undefined || !Number.isFinite(n) ? '' : String(Math.round((n / 60) * 100) / 100);
}

function seconds(v: string): string {
  const n = Number(v);
  return v.trim() === '' || !Number.isFinite(n) ? '' : String(Math.round(n * 60));
}

const MARGIN_HELP = 'Optional. The rule clears only once the reading is back past the limit by this much, so a value hovering at the limit fires once instead of over and over.';

export default function ConditionEditor({
  cond, scope, onChange, errors, disabled, assetNames,
}: { cond: Condition; scope: Scope; onChange: (c: Condition) => void; errors: Record<string, string>; disabled?: boolean; assetNames: Record<string, string> }) {
  const set = (patch: Partial<Condition>) => onChange({ ...cond, ...patch });
  const [staleOne, setStaleOne] = useState(!!cond.signal);
  const e = (k: string) => errors[`condition.${k}`];
  const { rows: signals } = useSignals(scope);
  const unitOf = (s?: string) => signals?.find((r) => r.signal === s)?.unit;
  const unit = unitOf(cond.signal);
  const u = unit ? ` (${unit})` : '';

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" role="group" aria-label="What to watch for">
        {KINDS.map((k) => (
          <Choice
            key={k}
            active={cond.kind === k}
            disabled={disabled}
            onClick={() => cond.kind !== k && onChange(blankCondition(k, cond.signal || ''))}
            title={COND_INFO[k].label}
            testId={`cond-kind-${k}`}
          />
        ))}
      </div>
      <p className="text-xs text-slate-400" data-testid="cond-help">{COND_INFO[cond.kind].help}</p>
      {e('kind') && <p className="text-xs text-rose-300">{e('kind')}</p>}

      {cond.kind !== 'geofence' && cond.kind !== 'stale' && (
        <SignalPicker
          value={cond.signal || ''}
          onChange={(v) => set({ signal: v })}
          scope={scope}
          label="Signal"
          error={e('signal')}
          testId="cond-signal"
          disabled={disabled}
          prefer={cond.kind === 'state' || cond.kind === 'count' ? 'any' : 'numeric'}
        />
      )}

      {cond.kind === 'threshold' && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Fires when it" htmlFor="cond-op">
            <select id="cond-op" value={cond.op || '>'} disabled={disabled} onChange={(ev) => set({ op: ev.target.value })} className={cls()} data-testid="cond-op">
              <option value=">">goes above</option>
              <option value=">=">reaches or passes</option>
              <option value="<">drops below</option>
              <option value="<=">drops to or below</option>
            </select>
          </Field>
          <Field label={`Limit${u}`} htmlFor="cond-value" error={e('value')}>
            <NumberInput id="cond-value" value={cond.value} onChange={(v) => set({ value: v })} error={e('value')} placeholder="300" disabled={disabled} testId="cond-value" />
          </Field>
          <Field label={`Clear margin${u}`} htmlFor="cond-h" error={e('hysteresis')} help="Optional, see below.">
            <NumberInput id="cond-h" value={cond.hysteresis} onChange={(v) => set({ hysteresis: v })} error={e('hysteresis')} placeholder="10" disabled={disabled} testId="cond-hysteresis" min={0} />
          </Field>
          <p className="text-xs text-slate-500 sm:col-span-3">{MARGIN_HELP}</p>
        </div>
      )}

      {cond.kind === 'range' && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={`Lowest normal${u}`} htmlFor="cond-min" error={e('min')}>
            <NumberInput id="cond-min" value={cond.min} onChange={(v) => set({ min: v })} error={e('min')} placeholder="70" disabled={disabled} testId="cond-min" />
          </Field>
          <Field label={`Highest normal${u}`} htmlFor="cond-max" error={e('max')}>
            <NumberInput id="cond-max" value={cond.max} onChange={(v) => set({ max: v })} error={e('max')} placeholder="105" disabled={disabled} testId="cond-max" />
          </Field>
          <Field label={`Clear margin${u}`} htmlFor="cond-h" error={e('hysteresis')} help="Optional. It clears this far inside the range.">
            <NumberInput id="cond-h" value={cond.hysteresis} onChange={(v) => set({ hysteresis: v })} error={e('hysteresis')} placeholder="2" disabled={disabled} testId="cond-hysteresis" min={0} />
          </Field>
        </div>
      )}

      {cond.kind === 'rate' && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Direction" htmlFor="cond-dir">
            <select id="cond-dir" value={cond.direction || 'either'} disabled={disabled} onChange={(ev) => set({ direction: ev.target.value as Condition['direction'] })} className={cls()} data-testid="cond-direction">
              <option value="either">Rises or falls</option>
              <option value="up">Rises</option>
              <option value="down">Falls</option>
            </select>
          </Field>
          <Field label={`Faster than${u}`} htmlFor="cond-limit" error={e('limit')}>
            <NumberInput id="cond-limit" value={cond.limit} onChange={(v) => set({ limit: v })} error={e('limit')} placeholder="20" disabled={disabled} testId="cond-limit" min={0} />
          </Field>
          <Field label="Per" htmlFor="cond-per">
            <select id="cond-per" value={cond.per || 's'} disabled={disabled} onChange={(ev) => set({ per: ev.target.value as Condition['per'] })} className={cls()} data-testid="cond-per">
              <option value="s">second</option>
              <option value="min">minute</option>
              <option value="h">hour</option>
            </select>
          </Field>
          <Field label="Measured over (seconds)" htmlFor="cond-window" error={e('window_s')} help="The change is taken across this many seconds, which smooths out single noisy readings.">
            <NumberInput id="cond-window" value={cond.window_s} onChange={(v) => set({ window_s: v })} error={e('window_s')} placeholder="10" disabled={disabled} testId="cond-window" min={1} />
          </Field>
          <Field label="Clear margin" htmlFor="cond-h" error={e('hysteresis')} help="Optional. It clears once the speed drops this far under the limit.">
            <NumberInput id="cond-h" value={cond.hysteresis} onChange={(v) => set({ hysteresis: v })} error={e('hysteresis')} placeholder="0" disabled={disabled} testId="cond-hysteresis" min={0} />
          </Field>
        </div>
      )}

      {cond.kind === 'stale' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Watch" htmlFor="cond-stale-what" help={staleOne ? 'Only this signal counts as hearing from the asset.' : 'Any message from the asset counts. This is right for an unplugged PC or a lost connection.'}>
            <select
              id="cond-stale-what"
              value={staleOne ? 'signal' : 'any'}
              disabled={disabled}
              onChange={(ev) => { const one = ev.target.value === 'signal'; setStaleOne(one); if (!one) set({ signal: '' }); }}
              className={cls()}
              data-testid="cond-stale-what"
            >
              <option value="any">Any data from the asset</option>
              <option value="signal">One signal</option>
            </select>
          </Field>
          <Field label="Silent for (seconds)" htmlFor="cond-seconds" error={e('seconds')} help="Checked every second against the last time anything arrived.">
            <NumberInput id="cond-seconds" value={cond.seconds} onChange={(v) => set({ seconds: v })} error={e('seconds')} placeholder="30" disabled={disabled} testId="cond-seconds" min={1} />
          </Field>
          {staleOne && (
            <div className="sm:col-span-2">
              <SignalPicker value={cond.signal || ''} onChange={(v) => set({ signal: v })} scope={scope} label="Signal" error={e('signal')} testId="cond-signal" disabled={disabled} prefer="any"
                help="Some sources only send a signal when it changes. Such a signal can look silent while all is well, so prefer any data for those." />
            </div>
          )}
        </div>
      )}

      {cond.kind === 'state' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Fires when it" htmlFor="cond-state-op">
            <select id="cond-state-op" value={cond.op || 'equals'} disabled={disabled} onChange={(ev) => set({ op: ev.target.value })} className={cls()} data-testid="cond-state-op">
              <option value="equals">is</option>
              <option value="not_equals">is not</option>
            </select>
          </Field>
          <Field label="Value" htmlFor="cond-equals" error={e('equals')} help="Text, a number, or true or false. Case does not matter.">
            <input id="cond-equals" value={cond.equals === null || cond.equals === undefined ? '' : String(cond.equals)} disabled={disabled} onChange={(ev) => set({ equals: ev.target.value })} placeholder="safe" className={cls(e('equals'))} data-testid="cond-equals" />
          </Field>
        </div>
      )}

      {cond.kind === 'geofence' && (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Positions are" htmlFor="cond-frame" help={cond.frame === 'gnss' ? 'GPS latitude and longitude in degrees.' : 'Site x and y, like metres from the site origin.'}>
              <select id="cond-frame" value={cond.frame || 'site'} disabled={disabled} onChange={(ev) => set({ frame: ev.target.value as Condition['frame'], polygon: [] })} className={cls()} data-testid="cond-frame">
                <option value="site">Site x and y</option>
                <option value="gnss">GPS latitude and longitude</option>
              </select>
            </Field>
            <Field label="Fires when it" htmlFor="cond-on">
              <select id="cond-on" value={cond.on || 'exit'} disabled={disabled} onChange={(ev) => set({ on: ev.target.value as Condition['on'] })} className={cls()} data-testid="cond-on">
                <option value="exit">leaves the zone</option>
                <option value="enter">enters the zone</option>
              </select>
            </Field>
            <Field label="Zone name" htmlFor="cond-zone" help="Shown in the alert, like the haul road.">
              <input id="cond-zone" value={cond.zone || ''} maxLength={60} disabled={disabled} onChange={(ev) => set({ zone: ev.target.value })} placeholder="the crane exclusion zone" className={cls()} data-testid="cond-zone" />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <SignalPicker value={cond.x_signal || ''} onChange={(v) => set({ x_signal: v })} scope={scope} label={cond.frame === 'gnss' ? 'Longitude signal' : 'X signal'} error={e('x_signal')} testId="cond-x-signal" disabled={disabled} prefer="numeric" />
            <SignalPicker value={cond.y_signal || ''} onChange={(v) => set({ y_signal: v })} scope={scope} label={cond.frame === 'gnss' ? 'Latitude signal' : 'Y signal'} error={e('y_signal')} testId="cond-y-signal" disabled={disabled} prefer="numeric" />
            <Field label={cond.frame === 'gnss' ? 'Margin (metres)' : 'Margin'} htmlFor="cond-h" error={e('hysteresis')} help="Optional. Counts as outside only this far past the edge, so GPS jitter at the line fires once.">
              <NumberInput id="cond-h" value={cond.hysteresis} onChange={(v) => set({ hysteresis: v })} error={e('hysteresis')} placeholder="2" disabled={disabled} testId="cond-hysteresis" min={0} />
            </Field>
          </div>
          <GeofenceEditor cond={cond} scope={scope} signals={signals} onChange={(polygon) => set({ polygon })} error={e('polygon')} disabled={disabled} assetNames={assetNames} />
        </div>
      )}

      {cond.kind === 'deviation' && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Recent window (minutes)" htmlFor="cond-dev-window" error={e('window_s')} help="The average over this many minutes is compared.">
            <NumberInput id="cond-dev-window" value={minutes(cond.window_s)} onChange={(v) => set({ window_s: seconds(v) })} error={e('window_s')} placeholder="5" disabled={disabled} testId="cond-dev-window" min={0} />
          </Field>
          <Field label="Against the last (minutes)" htmlFor="cond-dev-base" error={e('baseline_s')} help="The normal level, from the time before the recent window.">
            <NumberInput id="cond-dev-base" value={minutes(cond.baseline_s)} onChange={(v) => set({ baseline_s: seconds(v) })} error={e('baseline_s')} placeholder="30" disabled={disabled} testId="cond-dev-baseline" min={0} />
          </Field>
          <Field label="Direction" htmlFor="cond-dev-dir">
            <select id="cond-dev-dir" value={cond.direction || 'up'} disabled={disabled} onChange={(ev) => set({ direction: ev.target.value as Condition['direction'] })} className={cls()} data-testid="cond-dev-direction">
              <option value="up">Runs above normal</option>
              <option value="down">Runs below normal</option>
              <option value="either">Either way</option>
            </select>
          </Field>
          <Field label="Measured as" htmlFor="cond-dev-mode">
            <select
              id="cond-dev-mode"
              value={cond.mode || 'ratio'}
              disabled={disabled}
              onChange={(ev) => {
                const mode = ev.target.value as Condition['mode'];
                set({ mode, threshold: mode === 'ratio' ? (cond.direction === 'down' ? 0.85 : 1.15) : 3, hysteresis: mode === 'ratio' ? 0.05 : 0.5 });
              }}
              className={cls()}
              data-testid="cond-dev-mode"
            >
              <option value="ratio">A percentage of normal</option>
              <option value="zscore">Standard deviations from normal</option>
            </select>
          </Field>
          <Field
            label={(cond.mode || 'ratio') === 'ratio' ? 'Factor' : 'Standard deviations'}
            htmlFor="cond-dev-t"
            error={e('threshold')}
            help={(cond.mode || 'ratio') === 'ratio' ? '1.15 is 15% above normal, 0.85 is 15% below.' : '3 is a big move for most signals, 2 a noticeable one.'}
          >
            <NumberInput id="cond-dev-t" value={cond.threshold} onChange={(v) => set({ threshold: v })} error={e('threshold')} placeholder={(cond.mode || 'ratio') === 'ratio' ? '1.15' : '3'} disabled={disabled} testId="cond-dev-threshold" min={0} />
          </Field>
          <Field label="Clear margin" htmlFor="cond-h" error={e('hysteresis')} help="Optional. It clears once it is back this far inside the limit.">
            <NumberInput id="cond-h" value={cond.hysteresis} onChange={(v) => set({ hysteresis: v })} error={e('hysteresis')} placeholder="0.05" disabled={disabled} testId="cond-hysteresis" min={0} />
          </Field>
          <p className="text-xs text-slate-500 sm:col-span-3">
            It keeps running averages as data streams in, and stays quiet until it has seen half the baseline, so a new rule needs a little time before it can fire.
          </p>
        </div>
      )}

      {cond.kind === 'count' && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Count a reading when it" htmlFor="cond-when" className="sm:col-span-2">
            <select
              id="cond-when"
              value={!cond.when ? 'any' : 'equals' in cond.when ? 'equals' : cond.when.op || '>'}
              disabled={disabled}
              onChange={(ev) => {
                const v = ev.target.value;
                set({ when: v === 'any' ? null : v === 'equals' ? { equals: '' } : { op: v, value: cond.when && !('equals' in cond.when) ? cond.when.value : '' } });
              }}
              className={cls()}
              data-testid="cond-when"
            >
              <option value="any">arrives (every reading or event counts)</option>
              <option value=">">is above</option>
              <option value="<">is below</option>
              <option value="equals">is exactly</option>
            </select>
          </Field>
          {cond.when && (
            <Field label="Value" htmlFor="cond-when-value" error={e('when')} className="sm:col-span-2">
              {'equals' in cond.when ? (
                <input id="cond-when-value" value={cond.when.equals === null || cond.when.equals === undefined ? '' : String(cond.when.equals)} disabled={disabled} onChange={(ev) => set({ when: { equals: ev.target.value } })} placeholder="overload" className={cls(e('when'))} data-testid="cond-when-value" />
              ) : (
                <NumberInput id="cond-when-value" value={cond.when.value} onChange={(v) => set({ when: { op: cond.when && 'op' in cond.when ? cond.when.op : '>', value: v } })} error={e('when')} placeholder="300" disabled={disabled} testId="cond-when-value" />
              )}
            </Field>
          )}
          <Field label="Times" htmlFor="cond-count" error={e('count')} className="sm:col-span-2">
            <NumberInput id="cond-count" value={cond.count} onChange={(v) => set({ count: v })} error={e('count')} placeholder="5" disabled={disabled} testId="cond-count" step="1" min={1} />
          </Field>
          <Field label="Within (seconds)" htmlFor="cond-window" error={e('window_s')} className="sm:col-span-2" help="600 is ten minutes, 3600 an hour.">
            <NumberInput id="cond-window" value={cond.window_s} onChange={(v) => set({ window_s: v })} error={e('window_s')} placeholder="600" disabled={disabled} testId="cond-window" min={1} />
          </Field>
          <p className="text-xs text-slate-500 sm:col-span-4">Software events count too. Pick a signal named event:order.failed to count those events.</p>
        </div>
      )}
    </div>
  );
}
