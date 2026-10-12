'use client';

import { useRef, useState } from 'react';
import { CheckCircle2, FileUp, Loader2, Trash2, X } from 'lucide-react';
import { MASK, edgeCall, fieldKeyOf, requiredNow, shown, type CollectorSpec, type CollectorType, type FieldDecl } from './model';
import { pluralShown } from '@/lib/plural';

const INPUT = 'w-full min-w-0 rounded-md border bg-slate-950 px-2.5 py-2 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-cyan-500';

function Label({ id, text, required, help, example, choice }: { id: string; text: string; required?: boolean; help?: string; example?: string; choice?: boolean }) {
  return (
    <div className="mb-1">
      <label htmlFor={id} className="text-xs font-medium text-slate-200">
        {text}
        {required ? <span className="text-rose-300"> *</span> : choice ? null : <span className="text-slate-500"> (optional)</span>}
      </label>
      {help && <p className="mt-0.5 text-[11px] leading-snug text-slate-400">{help}</p>}
      {example && !help?.includes(example) && (
        <p className="mt-0.5 break-words text-[11px] text-slate-500">
          Example: <code className="whitespace-pre-wrap text-slate-300">{example.split('\n')[0]}</code>
        </p>
      )}
    </div>
  );
}

function Problem({ id, text }: { id: string; text?: string }) {
  if (!text) return null;
  return (
    <p id={`${id}-problem`} role="alert" className="mt-1 text-[11px] text-rose-300" data-testid={`${id}-problem`}>
      {text}
    </p>
  );
}

interface DbcSummary { ok: boolean; error: string | null; count: number; messages: { name: string; pgn: number | null; signals: { name: string }[] }[] }

function DbcField({ id, value, onChange, stored, disabled }: { id: string; value: string; onChange: (v: string | undefined) => void; stored?: number; disabled?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  const [name, setName] = useState<string | null>(null);
  const [check, setCheck] = useState<DbcSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const pick = (f: File) => {
    setErr(null);
    setCheck(null);
    if (f.size > 2 * 1024 * 1024) { setErr('That file is over 2 MB. Pick the DBC for this bus only.'); return; }
    const r = new FileReader();
    r.onload = async () => {
      const text = String(r.result || '');
      setName(f.name);
      onChange(text);
      setBusy(true);
      const res = await edgeCall<DbcSummary>('/api/edge/dbc/check', 'POST', { dbc: text });
      setBusy(false);
      if (res.error) setErr(res.error);
      else setCheck(res.data);
    };
    r.onerror = () => setErr('Could not read that file. Try again or pick another one.');
    r.readAsText(f);
  };

  return (
    <div>
      <input ref={ref} id={id} type="file" accept=".dbc,text/plain" className="sr-only" onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])} data-testid={id} disabled={disabled} />
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={disabled} onClick={() => ref.current?.click()} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800/60 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700/60 disabled:opacity-50">
          <FileUp className="h-3.5 w-3.5" /> {value || stored ? 'Choose another DBC file' : 'Choose a DBC file'}
        </button>
        {(name || stored || value) && (
          <span className="min-w-0 break-all text-[11px] text-slate-400">
            {name || (stored ? `DBC stored, ${Math.round(stored / 1024)} KB` : 'DBC added')}
          </span>
        )}
        {(value || stored) && !disabled && (
          <button type="button" onClick={() => { onChange(undefined); setName(null); setCheck(null); }} className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-rose-300" aria-label="Remove the DBC file">
            <X className="h-3 w-3" /> Remove
          </button>
        )}
      </div>
      {busy && <p className="mt-1 flex items-center gap-1 text-[11px] text-slate-400"><Loader2 className="h-3 w-3 animate-spin" /> Checking the file</p>}
      {err && <p role="alert" className="mt-1 text-[11px] text-rose-300">{err}</p>}
      {check && !check.ok && <p role="alert" className="mt-1 text-[11px] text-rose-300">{check.error}</p>}
      {check?.ok && (
        <p className="mt-1 flex items-start gap-1 text-[11px] text-emerald-300" data-testid={`${id}-ok`}>
          <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" />
          <span className="min-w-0 break-words">
            {pluralShown(check.count, (check.count).toLocaleString('en-US'), 'message')}, such as {check.messages.slice(0, 3).map((m) => `${m.name}${m.pgn ? ` (PGN ${m.pgn})` : ''}`).join(', ')}
          </span>
        </p>
      )}
    </div>
  );
}

export function FieldControl({ f, c, t, idPrefix, problem, onChange, disabled }: {
  f: FieldDecl; c: CollectorSpec; t: CollectorType; idPrefix: string; problem?: string; onChange: (v: unknown) => void; disabled?: boolean;
}) {
  const id = `${idPrefix}-${f.key}`;
  const v = c[f.key];
  const req = requiredNow(f, c, t);
  const cls = `${INPUT} ${problem ? 'border-rose-500/60' : 'border-slate-700'}`;
  const aria = { 'aria-invalid': !!problem, 'aria-describedby': problem ? `${id}-problem` : undefined };
  if (f.kind === 'bool') {
    return (
      <div>
        <label className="flex items-start gap-2 text-sm text-slate-200">
          <input id={id} type="checkbox" className="mt-1 accent-cyan-500" checked={!!v} onChange={(e) => onChange(e.target.checked)} data-testid={id} disabled={disabled} />
          <span>
            {f.label}
            {f.help && <span className="block text-[11px] text-slate-400">{f.help}</span>}
          </span>
        </label>
      </div>
    );
  }
  let input: React.ReactNode;
  if (f.kind === 'select') {
    input = (
      <select id={id} className={cls} value={String(v ?? f.default ?? '')} onChange={(e) => onChange(e.target.value)} data-testid={id} disabled={disabled} {...aria}>
        {(f.options || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else if (f.kind === 'text') {
    input = (
      <textarea id={id} rows={f.rows || 4} className={`${cls} font-mono text-xs`} value={String(v ?? '')} placeholder={f.example} onChange={(e) => onChange(e.target.value)} data-testid={id} disabled={disabled} spellCheck={false} {...aria} />
    );
  } else if (f.kind === 'file') {
    input = <DbcField id={id} value={typeof v === 'string' ? v : ''} stored={c.dbc_bytes} onChange={onChange} disabled={disabled} />;
  } else if (f.kind === 'secret' && v === MASK) {
    input = (
      <div className="flex items-center gap-2 text-xs text-slate-300">
        <span className="font-mono">••••••••</span> stored, never shown
        {!disabled && <button type="button" className="text-cyan-300 hover:underline" onClick={() => onChange('')}>Replace</button>}
      </div>
    );
  } else {
    const num = f.kind === 'int' || f.kind === 'number';
    input = (
      <input
        id={id}
        type={f.kind === 'secret' ? 'password' : num ? 'number' : 'text'}
        inputMode={num ? 'decimal' : undefined}
        step={f.kind === 'number' ? 'any' : undefined}
        min={f.min}
        max={f.max}
        autoComplete={f.kind === 'secret' ? 'new-password' : 'off'}
        className={cls}
        value={v === undefined || v === null ? '' : String(v)}
        placeholder={f.example || (f.default !== undefined && f.default !== null ? String(f.default) : '')}
        onChange={(e) => onChange(e.target.value)}
        data-testid={id}
        disabled={disabled}
        {...aria}
      />
    );
  }
  return (
    <div className="min-w-0">
      <Label id={id} text={f.label} required={req} help={f.help} example={f.kind === 'file' ? undefined : f.example} choice={f.kind === 'select'} />
      {input}
      <Problem id={id} text={problem} />
    </div>
  );
}

export default function CollectorForm({ t, c, onChange, problems, idx, onRemove, disabled, assetHelp, onFieldBlur }: {
  t: CollectorType;
  c: CollectorSpec;
  onChange: (next: CollectorSpec) => void;
  problems: Record<string, string>;
  idx: number;
  onRemove?: () => void;
  disabled?: boolean;
  assetHelp: string;
  onFieldBlur?: (key: string) => void;
}) {
  const p = `edge-c${idx}`;
  const set = (k: string, v: unknown) => onChange({ ...c, [k]: v });
  const setAsset = (k: 'group' | 'node' | 'device', v: string) => onChange({ ...c, asset: { ...c.asset, [k]: v } });
  const fields = t.fields.filter((f) => shown(f, c, t));
  const basic = fields.filter((f) => f.kind === 'text' || f.kind === 'file' || requiredNow(f, c, t) || f.kind === 'select');
  const more = fields.filter((f) => !basic.includes(f));
  const [open, setOpen] = useState(Object.keys(problems).some((k) => more.some((f) => f.key === k)));
  const partLabel = t.device_from_bus ? 'Part (empty names each ECU)' : 'Part';

  return (
    <section
      className="rounded-lg border border-slate-700/60 bg-slate-900/40 p-3 sm:p-4"
      data-testid={`edge-collector-${idx}`}
      aria-label={`${t.label} settings`}
      onBlur={(e) => {
        const key = fieldKeyOf((e.target as HTMLElement).getAttribute('data-testid') || '', p);
        if (key && onFieldBlur) onFieldBlur(key);
      }}
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wider text-cyan-300">{t.label}</p>
          <p className="text-[11px] text-slate-400">{t.short}</p>
        </div>
        {onRemove && !disabled && (
          <button type="button" onClick={onRemove} className="inline-flex shrink-0 items-center gap-1 rounded px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 hover:text-rose-300" data-testid={`${p}-drop`}>
            <Trash2 className="h-3.5 w-3.5" /> Take out
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="min-w-0 sm:col-span-2">
          <Label id={`${p}-name`} text="Name" required help="Shown on the gateway's health and in its log." example="Truck 12 engine bus" />
          <input id={`${p}-name`} className={`${INPUT} ${problems.name ? 'border-rose-500/60' : 'border-slate-700'}`} value={c.name} onChange={(e) => set('name', e.target.value)} data-testid={`${p}-name`} disabled={disabled} aria-invalid={!!problems.name} />
          <Problem id={`${p}-name`} text={problems.name} />
        </div>
        <fieldset className="min-w-0 rounded-md border border-slate-800 p-2.5 sm:col-span-2">
          <legend className="px-1 text-xs font-medium text-slate-200">Where the readings land in Telemetry</legend>
          <p className="mb-2 text-[11px] text-slate-400">{assetHelp}{t.asset_templates ? ' {topic.1} takes the second part of the topic, so one broker can feed many assets.' : ''}</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {(['group', 'node', 'device'] as const).map((k) => (
              <div key={k} className="min-w-0">
                <label htmlFor={`${p}-asset-${k}`} className="text-[11px] text-slate-300">{k === 'group' ? 'Group' : k === 'node' ? 'Asset' : partLabel}</label>
                <input id={`${p}-asset-${k}`} className={`${INPUT} ${problems[`asset.${k}`] ? 'border-rose-500/60' : 'border-slate-700'}`} value={String(c.asset?.[k] ?? '')} placeholder={t.asset_hint[k] || (k === 'device' ? 'engine' : '')} onChange={(e) => setAsset(k, e.target.value)} data-testid={`${p}-asset-${k}`} disabled={disabled} aria-invalid={!!problems[`asset.${k}`]} />
                <Problem id={`${p}-asset-${k}`} text={problems[`asset.${k}`]} />
              </div>
            ))}
          </div>
        </fieldset>
        {basic.map((f) => (
          <div key={f.key} className={f.kind === 'text' || f.kind === 'file' ? 'min-w-0 sm:col-span-2' : 'min-w-0'}>
            <FieldControl f={f} c={c} t={t} idPrefix={p} problem={problems[f.key]} onChange={(v) => set(f.key, v)} disabled={disabled} />
          </div>
        ))}
      </div>
      <details className="mt-3" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer text-xs text-slate-300">More settings</summary>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="min-w-0">
            <Label id={`${p}-interval`} text="Send every (seconds)" help="Fast signals are sampled to their newest value this often. Polled devices are read this often." example={String(t.default_interval_s)} />
            <input id={`${p}-interval`} type="number" step="any" min={0.1} max={3600} className={`${INPUT} ${problems.interval_s ? 'border-rose-500/60' : 'border-slate-700'}`} value={String(c.interval_s ?? '')} onChange={(e) => set('interval_s', e.target.value)} data-testid={`${p}-interval`} disabled={disabled} />
            <Problem id={`${p}-interval`} text={problems.interval_s} />
          </div>
          {more.map((f) => (
            <div key={f.key} className="min-w-0">
              <FieldControl f={f} c={c} t={t} idPrefix={p} problem={problems[f.key]} onChange={(v) => set(f.key, v)} disabled={disabled} />
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}
