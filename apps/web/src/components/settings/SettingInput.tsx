'use client';

import ModelPicker from '@/components/ModelPicker';

export type SettingChoice = string | { value: string; label?: string; description?: string };

export interface SettingSpec {
  key: string;
  value: string;
  kind?: string;
  min?: number | null;
  max?: number | null;
  choices?: SettingChoice[] | null;
}

// plain names for choice values the platform uses, anything else is shown tidied up
const CHOICE_LABELS: Record<string, string> = {
  inprocess: 'Inside the ingest service',
  pool: 'A separate pool of workers',
  auto: 'Work it out',
  on: 'On',
  off: 'Off',
};

export function choiceLabel(c: SettingChoice): string {
  if (typeof c !== 'string') return c.label || CHOICE_LABELS[c.value] || tidy(c.value);
  return CHOICE_LABELS[c] || tidy(c);
}

const tidy = (v: string) => {
  const s = v.replace(/[_-]+/g, ' ').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : v;
};

const choiceValue = (c: SettingChoice) => (typeof c === 'string' ? c : c.value);

const KNOWN = new Set(['model', 'int', 'choice', 'string']);

// one setting's input by its kind; a kind this page does not know gets a text box and says so
export default function SettingInput({ spec, value, onChange }: { spec: SettingSpec; value: string; onChange: (v: string) => void }) {
  const kind = spec.kind ?? 'model';
  const box = 'bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500';
  if (kind === 'int') {
    return (
      <div data-testid={`number-${spec.key}`}>
        <input type="number" value={value} min={spec.min ?? undefined} max={spec.max ?? undefined} onChange={(e) => onChange(e.target.value)} className={`w-40 font-mono ${box}`} aria-label={spec.key} />
        {(spec.min != null || spec.max != null) && <span className="ml-2 text-[11px] text-slate-500">allowed {spec.min ?? 'any'} to {spec.max ?? 'any'}</span>}
      </div>
    );
  }
  if (kind === 'choice') {
    const choices = spec.choices ?? [];
    const known = choices.some((c) => choiceValue(c) === value);
    return (
      <div data-testid={`choice-${spec.key}`}>
        <select value={value} onChange={(e) => onChange(e.target.value)} className={`min-w-[14rem] ${box}`} aria-label={spec.key}>
          {!known && <option value={value}>{value ? `${value} (not one of the choices)` : 'Pick one'}</option>}
          {choices.map((c) => <option key={choiceValue(c)} value={choiceValue(c)}>{choiceLabel(c)}</option>)}
        </select>
        {choices.map((c) => (typeof c !== 'string' && c.description && choiceValue(c) === value ? <p key="d" className="mt-1 text-[11px] text-slate-400">{c.description}</p> : null))}
      </div>
    );
  }
  if (kind === 'model') {
    return (
      <div data-testid={`select-${spec.key}`}>
        <ModelPicker value={value} onChange={onChange} />
      </div>
    );
  }
  return (
    <div data-testid={`text-${spec.key}`}>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)} className={`w-full max-w-md font-mono ${box}`} aria-label={spec.key} />
      {!KNOWN.has(kind) && <p className="mt-1 text-[11px] text-amber-200">This page does not have a special editor for this kind of setting ({kind}), so it is edited as text. Check the docs for the values it takes.</p>}
    </div>
  );
}
