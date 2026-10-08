'use client';

import { useEffect, useState } from 'react';
import { Play } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';

export interface RunInput {
  name: string;
  type: string;
  description?: string;
  required?: boolean;
  default?: unknown;
}

interface Props {
  open: boolean;
  inputs: RunInput[];
  onClose: () => void;
  onRun: (context: Record<string, unknown>) => void;
}

function coerce(type: string, raw: string): unknown {
  if (type === 'number') {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  if (type === 'boolean') return raw === 'true';
  return raw;
}

export default function RunInputsDialog({ open, inputs, onClose, onRun }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setValues((prev) => {
      const next = { ...prev };
      for (const v of inputs) {
        if (next[v.name] === undefined && v.default != null) next[v.name] = String(v.default);
      }
      return next;
    });
  }, [open, inputs]);

  const submit = () => {
    const missing = inputs.filter((v) => v.required && !(values[v.name] || '').trim());
    if (missing.length) {
      setError(`Fill in ${missing.map((m) => m.name).join(', ')} to run the pipeline.`);
      return;
    }
    const context: Record<string, unknown> = {};
    for (const v of inputs) {
      const raw = (values[v.name] || '').trim();
      if (raw) context[v.name] = coerce(v.type, raw);
    }
    onRun(context);
  };

  return (
    <ResponsiveModal open={open} onClose={onClose} title="Run with inputs" icon={<Play className="w-4 h-4 text-emerald-400" />}>
      <form
        data-testid="run-inputs-dialog"
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <p className="text-xs text-slate-400">The pipeline reads these values as {'{{context.name}}'}. They are used for this run only.</p>
        {inputs.map((v) => (
          <div key={v.name}>
            <label htmlFor={`run-input-${v.name}`} className="block text-xs text-slate-300 mb-1">
              {v.name}
              {v.required && <span className="text-red-400 ml-0.5">*</span>}
              {v.description && <span className="block text-[10px] text-slate-500">{v.description}</span>}
            </label>
            {v.type === 'boolean' ? (
              <select
                id={`run-input-${v.name}`}
                data-testid={`run-input-${v.name}`}
                value={values[v.name] || ''}
                onChange={(e) => setValues((p) => ({ ...p, [v.name]: e.target.value }))}
                className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
              >
                <option value="">Not set</option>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <input
                id={`run-input-${v.name}`}
                data-testid={`run-input-${v.name}`}
                type={v.type === 'number' ? 'number' : 'text'}
                value={values[v.name] || ''}
                placeholder={v.type === 'url' ? 'https://...' : ''}
                onChange={(e) => setValues((p) => ({ ...p, [v.name]: e.target.value }))}
                className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            )}
          </div>
        ))}
        {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
        <button
          type="submit"
          data-testid="run-inputs-submit"
          className="w-full py-2.5 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-sm font-medium rounded-lg flex items-center justify-center gap-2"
        >
          <Play className="w-4 h-4" /> Run pipeline
        </button>
      </form>
    </ResponsiveModal>
  );
}
