'use client';

import { Plus, X } from 'lucide-react';

export interface InputVariable {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'file' | 'url' | 'select' | 'connection_string';
  description: string;
  required: boolean;
  default?: string | number | boolean;
  placeholder?: string;
  options?: string[];
}

const TYPE_HELP: Record<InputVariable['type'], string> = {
  string: 'Free-form text input',
  number: 'Numeric value (integer or decimal)',
  boolean: 'Yes/No toggle switch',
  url: 'URL with http:// or https://',
  file: 'User selects a file — content read as text and passed to agent',
  connection_string: 'Database connection string (masked input)',
  select: 'Dropdown — add options in Default value (comma-separated)',
};

export default function InputVariablesEditor({
  value,
  onChange,
  subject = 'agent or pipeline',
  templateHint,
}: {
  value: InputVariable[];
  onChange: (vars: InputVariable[]) => void;
  subject?: string;
  templateHint?: boolean;
}) {
  const set = (idx: number, patch: Partial<InputVariable>) => {
    const vars = [...value];
    vars[idx] = { ...vars[idx], ...patch };
    onChange(vars);
  };
  const names = value.map((v) => v.name.trim());

  return (
    <div data-testid="input-vars">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h4 className="text-xs font-semibold text-white">Input Parameters</h4>
          <p className="text-[10px] text-slate-500">Define variables that users must provide when running this {subject}</p>
        </div>
        <button
          type="button"
          onClick={() => onChange([...value, { name: '', type: 'string', description: '', required: false }])}
          className="flex items-center gap-1 px-2 py-1 text-[10px] text-cyan-400 bg-cyan-500/10 rounded hover:bg-cyan-500/20 transition-colors"
          data-testid="input-var-add"
        >
          <Plus className="w-3 h-3" />
          Add Parameter
        </button>
      </div>

      {value.length === 0 && (
        <p className="text-[10px] text-slate-600 italic">No input parameters defined. Users will only provide a chat message.</p>
      )}
      {templateHint && value.some((v) => v.name.trim()) && (
        <p className="text-[10px] text-slate-500 mb-2">
          Use them in step arguments as {value.filter((v) => v.name.trim()).slice(0, 2).map((v) => `{{input.${v.name.trim()}}}`).join(', ')}.
        </p>
      )}

      <div className="space-y-2">
        {value.map((v, idx) => {
          const dup = !!v.name.trim() && names.indexOf(v.name.trim()) !== idx;
          return (
            <div key={idx} className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-2.5 space-y-2" data-testid={`input-var-${idx}`}>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={v.name}
                  placeholder="Parameter name"
                  aria-label={`Parameter ${idx + 1} name`}
                  onChange={(e) => set(idx, { name: e.target.value.replace(/\s+/g, '_').toLowerCase() })}
                  className={`flex-1 min-w-0 px-2 py-1 text-xs bg-slate-900/50 border rounded text-white focus:outline-none focus:border-cyan-500 ${dup ? 'border-rose-500/60' : 'border-slate-700'}`}
                  data-testid={`input-var-name-${idx}`}
                />
                <select
                  value={v.type}
                  aria-label={`Parameter ${idx + 1} type`}
                  onChange={(e) => set(idx, { type: e.target.value as InputVariable['type'] })}
                  className="w-[110px] shrink-0 px-2 py-1 text-xs bg-slate-900/50 border border-slate-700 rounded text-white focus:outline-none focus:border-cyan-500 truncate"
                  data-testid={`input-var-type-${idx}`}
                >
                  <option value="string">Text</option>
                  <option value="number">Number</option>
                  <option value="boolean">Yes/No</option>
                  <option value="url">URL</option>
                  <option value="file">File</option>
                  <option value="connection_string">DB Conn</option>
                  <option value="select">Dropdown</option>
                </select>
                <button
                  type="button"
                  onClick={() => onChange(value.filter((_, i) => i !== idx))}
                  className="px-1.5 text-red-400 hover:text-red-300"
                  aria-label={`Remove parameter ${v.name || idx + 1}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              {dup ? (
                <p className="text-[9px] text-rose-300 px-1" role="alert">Another parameter already uses this name.</p>
              ) : (
                <p className="text-[9px] text-slate-600 px-1">{TYPE_HELP[v.type] || ''}</p>
              )}
              <input
                type="text"
                value={v.description}
                placeholder="Description (shown to users)"
                aria-label={`Parameter ${idx + 1} description`}
                onChange={(e) => set(idx, { description: e.target.value })}
                className="w-full px-2 py-1 text-xs bg-slate-900/50 border border-slate-700 rounded text-slate-300 focus:outline-none focus:border-cyan-500"
                data-testid={`input-var-desc-${idx}`}
              />
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1 text-[10px] text-slate-400">
                  <input
                    type="checkbox"
                    checked={v.required}
                    onChange={(e) => set(idx, { required: e.target.checked })}
                    className="rounded border-slate-600"
                    data-testid={`input-var-required-${idx}`}
                  />
                  Required
                </label>
                <input
                  type="text"
                  value={(v.default as string) || ''}
                  placeholder="Default value"
                  aria-label={`Parameter ${idx + 1} default value`}
                  onChange={(e) => set(idx, { default: e.target.value })}
                  className="flex-1 min-w-0 px-2 py-0.5 text-[10px] bg-slate-900/50 border border-slate-700 rounded text-slate-400 focus:outline-none focus:border-cyan-500"
                  data-testid={`input-var-default-${idx}`}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
