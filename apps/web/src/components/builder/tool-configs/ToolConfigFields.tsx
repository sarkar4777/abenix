'use client';


import { useCallback } from 'react';
import { ChevronDown, Info } from 'lucide-react';
import type { ToolParam } from '@/lib/tool-docs';

interface ToolConfigFieldsProps {
  params: ToolParam[];
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

// Heuristic: fields with these names should render as textareas
const TEXTAREA_FIELDS = new Set([
  'prompt', 'system_prompt', 'input_message', 'body', 'code',
  'query', 'content', 'email_body', 'message', 'text',
  'classification_prompt', 'context', 'description', 'instructions',
]);

function shouldUseTextarea(name: string, description: string): boolean {
  if (TEXTAREA_FIELDS.has(name)) return true;
  const d = description.toLowerCase();
  return d.includes('prompt') || d.includes('code to execute') || d.includes('multi-line');
}

export default function ToolConfigFields({ params, values, onChange }: ToolConfigFieldsProps) {
  const setValue = useCallback((name: string, value: unknown) => {
    onChange({ ...values, [name]: value });
  }, [values, onChange]);

  const isVisible = useCallback((param: ToolParam): boolean => {
    if (!param.showWhen) return true;
    const depValue = values[param.showWhen.field];
    return param.showWhen.values.includes(String(depValue ?? ''));
  }, [values]);

  if (params.length === 0) return null;

  // Separate required and optional params
  const required = params.filter((p) => p.required);
  const optional = params.filter((p) => !p.required);

  return (
    <div className="space-y-3">
      {required.length > 0 && (
        <>
          <p className="text-[9px] text-slate-500 uppercase tracking-wider font-medium">Required Parameters</p>
          {required.map((param) => isVisible(param) && (
            <FieldRenderer key={param.name} param={param} value={values[param.name]} onChange={setValue} />
          ))}
        </>
      )}
      {optional.length > 0 && (
        <>
          <p className="text-[9px] text-slate-500 uppercase tracking-wider font-medium mt-3">Optional Parameters</p>
          {optional.map((param) => isVisible(param) && (
            <FieldRenderer key={param.name} param={param} value={values[param.name]} onChange={setValue} />
          ))}
        </>
      )}
    </div>
  );
}

// ─── Individual Field Renderer ────────────────────────────────────────────────

function FieldRenderer({
  param,
  value,
  onChange,
}: {
  param: ToolParam;
  value: unknown;
  onChange: (name: string, value: unknown) => void;
}) {
  const strVal = value != null ? String(value) : '';

  // ── Enum → Dropdown ────────────────────────────────────────────────────
  if (param.enum && param.enum.length > 0) {
    return (
      <FieldWrapper param={param}>
        <div className="relative">
          <select
            value={strVal || (param.default != null ? String(param.default) : '')}
            onChange={(e) => onChange(param.name, e.target.value)}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500 appearance-none pr-8"
          >
            <option value="">Select {param.name.replace(/_/g, ' ')}...</option>
            {param.enum.map((opt) => (
              <option key={opt} value={opt}>
                {opt.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
        </div>
      </FieldWrapper>
    );
  }

  // ── Boolean → Toggle ───────────────────────────────────────────────────
  if (param.type === 'boolean') {
    const checked = value === true || value === 'true';
    return (
      <FieldWrapper param={param} inline>
        <button
          type="button"
          onClick={() => onChange(param.name, !checked)}
          className="flex items-center gap-3 w-full text-left group"
        >
          <div className={`w-9 h-5 rounded-full transition-colors relative shrink-0 ${checked ? 'bg-cyan-500' : 'bg-slate-700'}`}>
            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </div>
          <div>
            <span className="text-xs text-slate-300 group-hover:text-white">
              {param.name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
              {param.required && <span className="text-red-400 ml-0.5">*</span>}
            </span>
            <p className="text-[9px] text-slate-600">{param.description}</p>
          </div>
        </button>
      </FieldWrapper>
    );
  }

  // ── Number with min/max → Slider + Input ───────────────────────────────
  if ((param.type === 'number' || param.type === 'integer') && param.minimum != null && param.maximum != null) {
    const numVal = value != null ? Number(value) : (param.default != null ? Number(param.default) : param.minimum);
    const step = param.type === 'integer' ? 1 : 0.1;
    return (
      <FieldWrapper param={param}>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={param.minimum}
            max={param.maximum}
            step={step}
            value={numVal}
            onChange={(e) => onChange(param.name, param.type === 'integer' ? parseInt(e.target.value) : parseFloat(e.target.value))}
            className="flex-1 h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-cyan-500"
          />
          <input
            type="number"
            min={param.minimum}
            max={param.maximum}
            step={step}
            value={numVal}
            onChange={(e) => onChange(param.name, param.type === 'integer' ? parseInt(e.target.value) || 0 : parseFloat(e.target.value) || 0)}
            className="w-16 px-2 py-1 bg-slate-900/50 border border-slate-700 rounded text-xs text-white text-center focus:outline-none focus:border-cyan-500"
          />
        </div>
      </FieldWrapper>
    );
  }

  // ── Number without range → Simple number input ─────────────────────────
  if (param.type === 'number' || param.type === 'integer') {
    return (
      <FieldWrapper param={param}>
        <input
          type="number"
          value={strVal || (param.default != null ? String(param.default) : '')}
          onChange={(e) => onChange(param.name, param.type === 'integer' ? parseInt(e.target.value) || 0 : parseFloat(e.target.value) || 0)}
          placeholder={param.default != null ? `Default: ${param.default}` : `Enter ${param.name}...`}
          min={param.minimum}
          max={param.maximum}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
        />
      </FieldWrapper>
    );
  }

  // ── Array of strings → Tag input ───────────────────────────────────────
  if (param.type === 'array') {
    const items: string[] = Array.isArray(value) ? value as string[] : [];
    return (
      <FieldWrapper param={param}>
        <div className="space-y-1.5">
          {items.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {items.map((item, i) => (
                <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-cyan-500/10 text-cyan-400 rounded text-[10px]">
                  {item}
                  <button
                    onClick={() => {
                      const next = items.filter((_, j) => j !== i);
                      onChange(param.name, next);
                    }}
                    className="text-cyan-400/50 hover:text-red-400"
                  >×</button>
                </span>
              ))}
            </div>
          )}
          {param.enum ? (
            // Array with enum options → multi-select checkboxes
            <div className="max-h-32 overflow-y-auto space-y-1 bg-slate-900/30 rounded-lg p-2">
              {param.enum.map((opt) => (
                <label key={opt} className="flex items-center gap-2 cursor-pointer text-[10px]">
                  <input
                    type="checkbox"
                    checked={items.includes(opt)}
                    onChange={(e) => {
                      const next = e.target.checked ? [...items, opt] : items.filter((v) => v !== opt);
                      onChange(param.name, next);
                    }}
                    className="w-3 h-3 rounded border-slate-600 bg-slate-900 text-cyan-500"
                  />
                  <span className="text-slate-300">{opt}</span>
                </label>
              ))}
            </div>
          ) : (
            // Free-form array input
            <input
              type="text"
              placeholder="Type and press Enter to add..."
              className="w-full px-3 py-1.5 bg-slate-900/50 border border-slate-700 rounded text-[10px] text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const input = e.currentTarget;
                  const val = input.value.trim();
                  if (val) {
                    onChange(param.name, [...items, val]);
                    input.value = '';
                  }
                  e.preventDefault();
                }
              }}
            />
          )}
        </div>
      </FieldWrapper>
    );
  }

  // ── Object → JSON editor ───────────────────────────────────────────────
  if (param.type === 'object') {
    const jsonStr = typeof value === 'string' ? value : (value ? JSON.stringify(value, null, 2) : '');
    return (
      <FieldWrapper param={param}>
        <textarea
          value={jsonStr}
          onChange={(e) => {
            try {
              const parsed = JSON.parse(e.target.value);
              onChange(param.name, parsed);
            } catch {
              onChange(param.name, e.target.value);
            }
          }}
          placeholder={`{\n  "key": "value"\n}`}
          rows={4}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-[10px] font-mono text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500"
        />
      </FieldWrapper>
    );
  }

  // ── String with textarea heuristic ─────────────────────────────────────
  if (shouldUseTextarea(param.name, param.description)) {
    return (
      <FieldWrapper param={param}>
        <textarea
          value={strVal}
          onChange={(e) => onChange(param.name, e.target.value)}
          placeholder={param.default != null ? `Default: ${param.default}` : param.description}
          rows={param.name === 'code' ? 8 : 4}
          className={`w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500 ${param.name === 'code' ? 'font-mono text-[10px]' : ''}`}
        />
      </FieldWrapper>
    );
  }

  // ── Default: text input ────────────────────────────────────────────────
  return (
    <FieldWrapper param={param}>
      <input
        type="text"
        value={strVal}
        onChange={(e) => onChange(param.name, e.target.value)}
        placeholder={param.default != null ? `Default: ${param.default}` : param.description}
        className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
      />
    </FieldWrapper>
  );
}

// ─── Field Wrapper with Label ─────────────────────────────────────────────────

function FieldWrapper({
  param,
  children,
  inline,
}: {
  param: ToolParam;
  children: React.ReactNode;
  inline?: boolean;
}) {
  if (inline) return <div>{children}</div>;

  return (
    <div>
      <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1 group">
        <span className="font-mono text-slate-500">{param.name}</span>
        {param.required && <span className="text-red-400 text-[8px]">required</span>}
        {param.default != null && !param.required && (
          <span className="text-slate-600 text-[8px]">default: {String(param.default)}</span>
        )}
        <span className="relative ml-auto">
          <Info className="w-3 h-3 text-slate-600 cursor-help" />
          <span className="absolute bottom-full right-0 mb-1 w-48 p-2 bg-slate-800 border border-slate-700 rounded-lg text-[9px] text-slate-300 hidden group-hover:block z-50 shadow-xl">
            {param.description}
          </span>
        </span>
      </label>
      {children}
    </div>
  );
}
