'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, ChevronDown, CircleDashed, Plus, Sparkles, Trash2, XCircle } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { useSelectableModels } from '@/lib/models';
import { fieldProblem, type Assertion, type AssertionField, type AssertionResult, type AssertionType } from '@/lib/evals';

interface Catalog {
  types: AssertionType[];
  default_judge_model: string;
  source_tools: string[];
}

export function useAssertionCatalog() {
  const { data } = useApi<Catalog>('/api/evals/assertion-types');
  return data;
}

const STARTERS: Record<string, Partial<Assertion>> = {
  regex: { mode: 'match' },
  required_tools_called: { tools: [], mode: 'all' },
  cited_sources_present: { min_count: 1, accept_source_tools: true },
  judge: { min_score: 0.7 },
  schema_valid: { schema: { type: 'object', required: [], properties: {} } },
};

export function describe(a: Assertion, types: AssertionType[] | undefined): string {
  const t = types?.find((x) => x.type === a.type);
  const label = t?.label || a.type;
  switch (a.type) {
    case 'json_path_equals':
      return `${a.path || '…'} = ${JSON.stringify(a.value ?? '…')}`;
    case 'json_path_contains':
      return `${a.path || '…'} contains ${JSON.stringify(a.value ?? '…')}`;
    case 'regex':
      return `${a.mode === 'no_match' ? 'never matches' : 'matches'} /${a.pattern || '…'}/`;
    case 'contains':
      return `contains “${a.value || '…'}”`;
    case 'not_contains':
      return `never says “${a.value || '…'}”`;
    case 'required_tools_called':
      return `calls ${(a.tools || []).join(a.mode === 'any' ? ' or ' : ' and ') || '…'}`;
    case 'max_cost':
      return `costs at most $${a.max ?? '…'}`;
    case 'max_duration_ms':
      return `finishes within ${a.max ?? '…'} ms`;
    case 'judge':
      return `judged: ${(a.rubric || '…').slice(0, 60)}`;
    default:
      return label;
  }
}

export default function AssertionBuilder({
  value,
  onChange,
  caseId,
  output,
  disabled,
}: {
  value: Assertion[];
  onChange: (next: Assertion[]) => void;
  caseId?: string | null;
  output?: string | null;
  disabled?: boolean;
}) {
  const catalog = useAssertionCatalog();
  const types = catalog?.types;
  const [adding, setAdding] = useState(false);
  const [preview, setPreview] = useState<{ source: string | null; results: AssertionResult[] } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const canPreview = !!caseId || !!output;

  useEffect(() => {
    if (!canPreview || value.length === 0) {
      setPreview(null);
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      setPreviewing(true);
      const r = await apiFetch<{ source: string | null; results: AssertionResult[] }>('/api/evals/assertions/check', {
        method: 'POST',
        body: JSON.stringify({ assertions: value, case_id: output ? null : caseId, output: output ?? null }),
        throwOnError: false,
        silent: true,
      });
      setPreviewing(false);
      if (r.data) setPreview(r.data);
    }, 600);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [JSON.stringify(value), caseId, output, canPreview]);

  function update(i: number, patch: Partial<Assertion>) {
    onChange(value.map((a, j) => (j === i ? ({ ...a, ...patch } as Assertion) : a)));
  }

  function add(type: string) {
    onChange([...value, { type, ...(STARTERS[type] || {}) } as Assertion]);
    setAdding(false);
  }

  const passing = preview?.results.filter((r) => r.passed === true).length ?? 0;
  const checkable = preview?.results.filter((r) => r.passed !== null).length ?? 0;

  return (
    <div className="space-y-2" data-testid="assertion-builder">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium text-slate-200">Assertions</div>
        {canPreview && value.length > 0 && (
          <div className="text-xs text-slate-400" data-testid="assertion-preview-summary">
            {previewing ? 'Checking…' : preview?.source ? (
              <>
                <span className={passing === checkable ? 'text-emerald-300' : 'text-amber-300'}>{passing} of {checkable}</span> hold on the {preview.source}
              </>
            ) : 'No earlier output to check against yet'}
          </div>
        )}
      </div>
      {value.length === 0 && (
        <p className="text-xs text-slate-500 rounded-lg border border-dashed border-slate-700 px-3 py-3">
          No assertions yet. With none, a case passes whenever the run finishes. Add checks on fields, wording, tools, cost or sources.
        </p>
      )}
      {value.map((a, i) => (
        <AssertionCard
          key={i}
          index={i}
          a={a}
          types={types}
          defaultJudge={catalog?.default_judge_model}
          sourceTools={catalog?.source_tools}
          result={preview?.results[i]}
          disabled={disabled}
          onChange={(p) => update(i, p)}
          onType={(t) => onChange(value.map((x, j) => (j === i ? ({ type: t, ...(STARTERS[t] || {}) } as Assertion) : x)))}
          onRemove={() => onChange(value.filter((_, j) => j !== i))}
        />
      ))}
      {!disabled && (
        <div className="relative">
          <button
            type="button"
            onClick={() => setAdding((v) => !v)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/10"
            data-testid="assertion-add"
            aria-expanded={adding}
          >
            <Plus className="w-3.5 h-3.5" /> Add assertion <ChevronDown className="w-3 h-3" />
          </button>
          {adding && types && (
            <div className="absolute z-20 mt-1 w-80 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl p-1" role="menu">
              {types.map((t) => (
                <button
                  key={t.type}
                  type="button"
                  role="menuitem"
                  onClick={() => add(t.type)}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-800"
                  data-testid={`assertion-add-${t.type}`}
                >
                  <div className="text-sm text-white flex items-center gap-1.5">
                    {t.label}
                    {t.deterministic === false && <Sparkles className="w-3 h-3 text-violet-300" aria-label="uses a model" />}
                  </div>
                  <div className="text-[11px] text-slate-400">{t.help}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultChip({ r }: { r?: AssertionResult }) {
  if (!r) return null;
  if (r.passed === null || r.skipped)
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-slate-400" title={r.reason}>
        <CircleDashed className="w-3.5 h-3.5" /> Checked during runs
      </span>
    );
  return r.passed ? (
    <span className="inline-flex items-center gap-1 text-[11px] text-emerald-300" title={r.reason}>
      <CheckCircle2 className="w-3.5 h-3.5" /> Holds
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[11px] text-rose-300" title={r.reason}>
      <XCircle className="w-3.5 h-3.5" /> Fails
    </span>
  );
}

function AssertionCard({
  index,
  a,
  types,
  defaultJudge,
  sourceTools,
  result,
  disabled,
  onChange,
  onType,
  onRemove,
}: {
  index: number;
  a: Assertion;
  types?: AssertionType[];
  defaultJudge?: string;
  sourceTools?: string[];
  result?: AssertionResult;
  disabled?: boolean;
  onChange: (p: Partial<Assertion>) => void;
  onType: (t: string) => void;
  onRemove: () => void;
}) {
  const t = types?.find((x) => x.type === a.type);
  return (
    <div className="rounded-lg border border-slate-700/70 bg-slate-950/60 p-3" data-testid={`assertion-${index}`}>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={a.type}
          onChange={(e) => onType(e.target.value)}
          disabled={disabled}
          className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-xs text-white"
          aria-label="Assertion type"
          data-testid={`assertion-type-${index}`}
        >
          {(types || [{ type: a.type, label: a.type } as AssertionType]).map((x) => (
            <option key={x.type} value={x.type}>{x.label}</option>
          ))}
        </select>
        {t?.deterministic === false && (
          <span className="text-[10px] px-1.5 py-0.5 rounded border border-violet-500/30 text-violet-300 bg-violet-500/10">model judged</span>
        )}
        <div className="flex-1" />
        <ResultChip r={result} />
        {!disabled && (
          <button type="button" onClick={onRemove} className="p-1 text-slate-500 hover:text-rose-300" aria-label="Remove assertion">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {result && result.passed === false && <p className="mt-1.5 text-[11px] text-rose-200/80">{result.reason}</p>}
      {result && result.passed === true && <p className="mt-1.5 text-[11px] text-slate-500">{result.reason}</p>}
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {(t?.fields || []).map((f) => (
          <FieldInput
            key={f.key}
            f={f}
            value={a[f.key]}
            id={`a${index}-${f.key}`}
            disabled={disabled}
            defaultJudge={defaultJudge}
            sourceTools={sourceTools}
            onChange={(v) => onChange({ [f.key]: v })}
          />
        ))}
      </div>
    </div>
  );
}

function FieldInput({
  f,
  value,
  id,
  disabled,
  defaultJudge,
  sourceTools,
  onChange,
}: {
  f: AssertionField;
  value: any;
  id: string;
  disabled?: boolean;
  defaultJudge?: string;
  sourceTools?: string[];
  onChange: (v: any) => void;
}) {
  const problem = fieldProblem(f, value);
  const wide = ['textarea', 'schema', 'list', 'json'].includes(f.kind) || f.key === 'pattern';
  const cls = 'w-full bg-slate-900 border rounded-md px-2.5 py-1.5 text-sm text-white ' + (problem ? 'border-rose-500/60' : 'border-slate-700');
  let input: React.ReactNode;
  if (f.kind === 'bool') {
    return (
      <label className="inline-flex items-center gap-2 text-xs text-slate-300 self-end py-1.5">
        <input type="checkbox" checked={!!(value ?? (f.key === 'accept_source_tools'))} onChange={(e) => onChange(e.target.checked)} disabled={disabled} className="accent-cyan-500" data-testid={`${id}`} />
        {f.label}
      </label>
    );
  }
  if (f.kind === 'select') {
    input = (
      <div className="inline-flex rounded-md border border-slate-700 p-0.5 bg-slate-900" role="radiogroup" aria-label={f.label}>
        {(f.options || []).map((o) => {
          const on = (value ?? f.options?.[0]) === o;
          return (
            <button key={o} type="button" role="radio" aria-checked={on} disabled={disabled} onClick={() => onChange(o)} className={`px-2.5 py-1 text-xs rounded ${on ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>
              {o.replace('_', ' ')}
            </button>
          );
        })}
      </div>
    );
  } else if (f.kind === 'json') {
    input = <JsonValue value={value} onChange={onChange} id={id} disabled={disabled} cls={cls} />;
  } else if (f.kind === 'schema') {
    input = <SchemaValue value={value} onChange={onChange} id={id} disabled={disabled} />;
  } else if (f.kind === 'list') {
    input = <ListValue value={value || []} onChange={onChange} id={id} disabled={disabled} suggestions={f.key === 'tools' ? sourceTools : undefined} />;
  } else if (f.kind === 'textarea') {
    input = <textarea id={id} value={value || ''} onChange={(e) => onChange(e.target.value)} rows={3} disabled={disabled} className={cls} placeholder="The answer cites a source for every figure and makes no claim the sources do not support." data-testid={id} />;
  } else if (f.kind === 'model') {
    input = <ModelSelect id={id} value={value || ''} onChange={onChange} disabled={disabled} placeholder={`Default, ${defaultJudge || 'Haiku 4.5'}`} />;
  } else if (f.kind === 'number') {
    input = (
      <input
        id={id}
        type="number"
        step="any"
        min={0}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
        disabled={disabled}
        className={cls}
        data-testid={id}
      />
    );
  } else {
    input = (
      <input
        id={id}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={cls + (f.kind === 'path' || f.kind === 'regex' ? ' font-mono' : '')}
        placeholder={f.kind === 'path' ? 'decision or items[0].sku' : f.kind === 'regex' ? '\\bapproved?\\b' : ''}
        data-testid={id}
      />
    );
  }
  return (
    <div className={wide ? 'sm:col-span-2' : ''}>
      <label htmlFor={id} className="block text-[11px] font-medium text-slate-400 mb-1">
        {f.label}
        {f.required && <span className="text-rose-300"> *</span>}
      </label>
      {input}
      {problem && <p className="mt-1 text-[11px] text-rose-300" role="alert">{problem}</p>}
    </div>
  );
}

function asText(v: any): string {
  if (v === undefined) return '';
  return typeof v === 'string' ? v : JSON.stringify(v);
}

function JsonValue({ value, onChange, id, disabled, cls }: { value: any; onChange: (v: any) => void; id: string; disabled?: boolean; cls: string }) {
  const [text, setText] = useState(asText(value));
  useEffect(() => {
    if (asText(value) !== text && !(typeof value === 'string' && text === value)) setText(asText(value));
  }, [value]);
  const kind = value === undefined ? null : value === null ? 'null' : Array.isArray(value) ? 'list' : typeof value;
  return (
    <>
      <input
        id={id}
        value={text}
        disabled={disabled}
        onChange={(e) => {
          const t = e.target.value;
          setText(t);
          if (!t.trim()) return onChange(undefined);
          try {
            onChange(JSON.parse(t));
          } catch {
            onChange(t);
          }
        }}
        className={cls + ' font-mono'}
        placeholder='approve, 42, true or ["a","b"]'
        data-testid={id}
      />
      {kind && <p className="mt-1 text-[11px] text-slate-500">Read as {kind === 'string' ? 'text' : kind}{kind === 'string' && /^\d/.test(text) ? '. Wrap numbers in quotes only to compare as text' : ''}.</p>}
    </>
  );
}

function SchemaValue({ value, onChange, id, disabled }: { value: any; onChange: (v: any) => void; id: string; disabled?: boolean }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [err, setErr] = useState<string | null>(null);
  return (
    <>
      <textarea
        id={id}
        rows={6}
        spellCheck={false}
        value={text}
        disabled={disabled}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed = JSON.parse(e.target.value);
            setErr(null);
            onChange(parsed);
          } catch (x: any) {
            setErr(`Not valid JSON yet: ${x.message}`);
          }
        }}
        className={`w-full bg-slate-900 border rounded-md px-2.5 py-1.5 text-xs text-slate-200 font-mono ${err ? 'border-rose-500/60' : 'border-slate-700'}`}
        data-testid={id}
      />
      {err && <p className="mt-1 text-[11px] text-rose-300">{err}</p>}
    </>
  );
}

function ListValue({ value, onChange, id, disabled, suggestions }: { value: string[]; onChange: (v: string[]) => void; id: string; disabled?: boolean; suggestions?: string[] }) {
  const [draft, setDraft] = useState('');
  const commit = (raw: string) => {
    const parts = raw.split(',').map((s) => s.trim()).filter(Boolean).filter((s) => !value.includes(s));
    if (parts.length) onChange([...value, ...parts]);
    setDraft('');
  };
  const listId = `${id}-options`;
  return (
    <div className="flex flex-wrap items-center gap-1.5 bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5">
      {value.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 text-xs font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-200">
          {v}
          {!disabled && (
            <button type="button" onClick={() => onChange(value.filter((x) => x !== v))} className="text-slate-500 hover:text-rose-300" aria-label={`Remove ${v}`}>
              ×
            </button>
          )}
        </span>
      ))}
      <input
        id={id}
        value={draft}
        list={suggestions ? listId : undefined}
        disabled={disabled}
        onChange={(e) => (e.target.value.endsWith(',') ? commit(e.target.value) : setDraft(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit(draft);
          } else if (e.key === 'Backspace' && !draft && value.length) onChange(value.slice(0, -1));
        }}
        onBlur={() => draft && commit(draft)}
        placeholder={value.length ? '' : 'knowledge_search, then Enter'}
        className="flex-1 min-w-[8rem] bg-transparent text-sm text-white outline-none font-mono"
        data-testid={id}
      />
      {suggestions && (
        <datalist id={listId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
    </div>
  );
}

export function ModelSelect({ id, value, onChange, disabled, placeholder }: { id?: string; value: string; onChange: (v: string) => void; disabled?: boolean; placeholder: string }) {
  const models = useSelectableModels();
  const options = useMemo(() => models.map((m) => ({ value: m.value, label: m.label })), [models]);
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className="w-full bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-sm text-white" data-testid={id}>
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}
