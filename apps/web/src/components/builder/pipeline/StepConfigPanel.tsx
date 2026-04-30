'use client';

import { useState, type ChangeEvent } from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  Plus,
  Trash2,
  Zap,
  GitBranch,
  Flag,
  Settings2,
} from 'lucide-react';
import type { PipelineStep, PipelineCondition, SwitchConfig } from './pipelineUtils';
import { validatePipeline } from './pipelineUtils';
import { usePipelineStore, type ValidationError } from './usePipelineStore';
import { TOOL_DOCS, type ToolParam } from '@/lib/tool-docs';

// Props

interface StepConfigPanelProps {
  step: PipelineStep | null;
  allSteps: PipelineStep[];
  onUpdate: (stepId: string, updates: Partial<PipelineStep>) => void;
  onClose: () => void;
}

// Constants

const MODELS = [
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-3-5-20241022', label: 'Claude Haiku 3.5' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
];

const CONDITION_OPERATORS: { value: PipelineCondition['operator']; label: string }[] = [
  { value: 'eq', label: 'Equals (==)' },
  { value: 'neq', label: 'Not Equals (!=)' },
  { value: 'gt', label: 'Greater Than (>)' },
  { value: 'lt', label: 'Less Than (<)' },
  { value: 'gte', label: 'Greater or Equal (>=)' },
  { value: 'lte', label: 'Less or Equal (<=)' },
  { value: 'contains', label: 'Contains' },
  { value: 'not_contains', label: 'Not Contains' },
  { value: 'in', label: 'In' },
  { value: 'not_in', label: 'Not In' },
];

type Tab = 'general' | 'arguments' | 'inputs' | 'condition' | 'retry';

// HelpTip — contextual tooltip component

function HelpTip({ text }: { text: string }) {
  const [show, setShow] = useState(false);
  return (
    <span className="relative inline-block ml-1">
      <button
        type="button"
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        onClick={() => setShow(!show)}
        className="w-3.5 h-3.5 rounded-full bg-slate-700 text-slate-400 text-[9px] font-bold inline-flex items-center justify-center hover:bg-cyan-500/20 hover:text-cyan-400 transition-colors"
        aria-label="Help"
      >
        ?
      </button>
      {show && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-2.5 rounded-lg bg-slate-800 border border-slate-700 shadow-xl text-[10px] text-slate-300 leading-relaxed">
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2 -mt-px border-4 border-transparent border-t-slate-700" />
        </div>
      )}
    </span>
  );
}

// Tool name formatter

function formatToolName(toolName: string): string {
  return toolName
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// TemplatePreview — shows a visual breakdown of {{variable}} placeholders

function TemplatePreview({ value }: { value: string }) {
  if (!value || !value.includes('{{')) return null;
  return (
    <div className="mt-1.5 p-2 bg-slate-950/50 rounded text-[10px] text-slate-400 break-words leading-relaxed">
      <p className="text-[9px] text-slate-600 uppercase mb-1">Template Preview</p>
      {value.split(/(\{\{[^}]+\}\})/).map((part, i) =>
        part.startsWith('{{') ? (
          <span key={i} className="text-cyan-400 bg-cyan-500/10 px-1 py-0.5 rounded font-mono text-[10px]">{part}</span>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </div>
  );
}

// FieldError — inline validation error display next to a form field

/** Find the first matching validation error for a given field path.
 * Matches exact field paths and their sub-paths (e.g. "arguments.prompt"
 * matches "arguments.prompt.foo") but never substrings like
 * "arguments.prompt" matching "arguments.prompt_template". */
function findFieldError(
  stepErrors: ValidationError[],
  field: string,
): ValidationError | null {
  return (
    stepErrors.find(
      (e) => e.field === field || e.field.startsWith(`${field}.`),
    ) ?? null
  );
}

function FieldError({
  stepErrors,
  field,
}: {
  stepErrors: ValidationError[];
  field: string;
}) {
  const match = findFieldError(stepErrors, field);
  if (!match) return null;
  const isWarn = match.severity === 'warning';
  const wrap = isWarn
    ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
    : 'bg-red-500/10 border-red-500/20 text-red-400';
  return (
    <div
      className={`flex items-start gap-1.5 mt-1.5 px-2 py-1.5 border rounded text-[10px] ${wrap}`}
      data-testid={`field-error-${field}`}
    >
      <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
      <div className="min-w-0">
        <div className="font-medium">{match.message}</div>
        {match.suggestion && (
          <div className="opacity-70 mt-0.5">{match.suggestion}</div>
        )}
      </div>
    </div>
  );
}

function FieldErrorGroup({
  stepErrors,
  prefix,
  exclude = [],
}: {
  stepErrors: ValidationError[];
  prefix: string;
  exclude?: string[];
}) {
  const matches = stepErrors.filter(
    (e) =>
      (e.field === prefix || e.field.startsWith(`${prefix}.`)) &&
      !exclude.some((x) => e.field === x || e.field === `${prefix}.${x}`),
  );
  if (matches.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {matches.map((m, i) => {
        const isWarn = m.severity === 'warning';
        const wrap = isWarn
          ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
          : 'bg-red-500/10 border-red-500/20 text-red-400';
        return (
          <div
            key={`${m.field}-${i}`}
            className={`flex items-start gap-1.5 px-2 py-1.5 border rounded text-[10px] ${wrap}`}
          >
            <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
            <div className="min-w-0">
              <div className="font-medium">{m.message}</div>
              {m.suggestion && (
                <div className="opacity-70 mt-0.5">{m.suggestion}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Pipeline Overview (when no step is selected)

function PipelineOverview({
  allSteps,
  onClose,
}: {
  allSteps: PipelineStep[];
  onClose: () => void;
}) {
  const validation = validatePipeline(allSteps);

  return (
    <div className="w-[320px] border-l border-slate-800 bg-[#0F172A] flex flex-col shrink-0 overflow-hidden">
      <div className="border-b border-slate-800/50 p-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center shrink-0">
            <Settings2 className="w-5 h-5 text-emerald-400" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white">Pipeline Settings</p>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">
              Overview
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Summary */}
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">Total Steps</label>
          <div className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white">
            {allSteps.length} {allSteps.length === 1 ? 'step' : 'steps'}
          </div>
        </div>

        {/* Tools used */}
        {allSteps.length > 0 && (
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Tools Used</label>
            <div className="space-y-1">
              {Array.from(new Set(allSteps.map((s) => s.toolName)))
                .sort()
                .map((tool) => (
                  <div
                    key={tool}
                    className="px-3 py-1.5 bg-slate-800/50 border border-slate-700 rounded-lg text-xs text-slate-300"
                  >
                    {formatToolName(tool)}
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Validation status */}
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">Validation</label>
          {validation.valid ? (
            <div className="flex items-center gap-2 px-3 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span className="text-xs text-emerald-400">Pipeline is valid</span>
            </div>
          ) : (
            <div className="space-y-2">
              {validation.errors.map((error, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg"
                >
                  <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
                  <span className="text-xs text-red-400">{error}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Info */}
        <div className="pt-2 border-t border-slate-800">
          <p className="text-[10px] text-slate-600">
            Select a step on the canvas to configure its arguments, inputs, and
            conditions.
          </p>
        </div>
      </div>
    </div>
  );
}

// LLM Call Arguments Form

function LLMCallArgumentsForm({
  args,
  onChange,
  stepErrors,
}: {
  args: Record<string, unknown>;
  onChange: (args: Record<string, unknown>) => void;
  stepErrors: ValidationError[];
}) {
  const model = (args.model as string) || 'claude-sonnet-4-5-20250929';
  const prompt = (args.prompt as string) || '';
  const systemPrompt = (args.system_prompt as string) || '';
  const temperature = typeof args.temperature === 'number' ? args.temperature : 0.7;
  const maxTokens = typeof args.max_tokens === 'number' ? args.max_tokens : 4096;

  const tempLabels = ['Precise', 'Balanced', 'Creative'];
  const tempIdx = temperature <= 0.3 ? 0 : temperature >= 1.2 ? 2 : 1;

  return (
    <div className="space-y-4">
      {/* Model */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Model<HelpTip text="Which LLM to use. Sonnet is best for complex research and reasoning. Haiku is faster and cheaper for simple tasks." /></label>
        <select
          value={model}
          onChange={(e) => onChange({ ...args, model: e.target.value })}
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
        >
          {MODELS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        <FieldError stepErrors={stepErrors} field="arguments.model" />
      </div>

      {/* Prompt */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Prompt<HelpTip text="The prompt sent to the LLM. Use {{node_id.response}} to inject upstream outputs. This is a single LLM call — no tool loop. Good for parsing, summarizing, or generating structured output." /></label>
        <textarea
          value={prompt}
          onChange={(e) => onChange({ ...args, prompt: e.target.value })}
          placeholder="Enter your prompt... Use {{step_id.field}} for template variables."
          rows={10}
          className="w-full px-3 py-2 bg-slate-950/50 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-emerald-500 leading-relaxed"
        />
        <p className="text-[10px] text-slate-600 mt-1">
          {prompt.length} characters
        </p>
        <TemplatePreview value={prompt} />
        <FieldError stepErrors={stepErrors} field="arguments.prompt" />
      </div>

      {/* System Prompt */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">System Prompt<HelpTip text="Sets the LLM's role and behavior for this call. Example: 'You are a JSON parser. Extract structured data from the input. Output ONLY valid JSON.'" /></label>
        <textarea
          value={systemPrompt}
          onChange={(e) => onChange({ ...args, system_prompt: e.target.value })}
          placeholder="You are a helpful assistant that..."
          rows={5}
          className="w-full px-3 py-2 bg-slate-950/50 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-emerald-500 leading-relaxed"
        />
        <TemplatePreview value={systemPrompt} />
        <FieldError stepErrors={stepErrors} field="arguments.system_prompt" />
      </div>

      {/* Temperature */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs text-slate-400">Temperature<HelpTip text="Controls randomness. 0 = deterministic (same input → same output). 0.7 = balanced. 1.0+ = creative/varied. Use 0.3-0.5 for factual tasks, 0.7-1.0 for creative." /></label>
          <span className="text-xs font-mono text-emerald-400">
            {temperature.toFixed(1)}
          </span>
        </div>
        <input
          type="range"
          min="0"
          max="2"
          step="0.1"
          value={temperature}
          onChange={(e) =>
            onChange({ ...args, temperature: parseFloat(e.target.value) })
          }
          className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
        />
        <div className="flex justify-between mt-1">
          {tempLabels.map((l, i) => (
            <span
              key={l}
              className={`text-[10px] ${i === tempIdx ? 'text-emerald-400' : 'text-slate-600'}`}
            >
              {l}
            </span>
          ))}
        </div>
      </div>

      {/* Max Tokens */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Max Tokens<HelpTip text="Maximum tokens the LLM can generate. 1000 for short answers, 4096 for detailed analysis, 8192 for comprehensive reports." /></label>
        <input
          type="number"
          value={maxTokens}
          onChange={(e) =>
            onChange({ ...args, max_tokens: parseInt(e.target.value) || 4096 })
          }
          min={1}
          max={32000}
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
        />
      </div>
    </div>
  );
}

// Generic JSON Arguments Editor

function GenericArgumentsEditor({
  args,
  onChange,
  stepErrors,
}: {
  args: Record<string, unknown>;
  onChange: (args: Record<string, unknown>) => void;
  stepErrors: ValidationError[];
}) {
  const [jsonText, setJsonText] = useState(() =>
    JSON.stringify(args, null, 2),
  );
  const [parseError, setParseError] = useState<string | null>(null);

  const handleBlur = () => {
    try {
      const parsed = JSON.parse(jsonText);
      if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
        onChange(parsed as Record<string, unknown>);
        setParseError(null);
      } else {
        setParseError('Arguments must be a JSON object');
      }
    } catch (e) {
      setParseError('Invalid JSON syntax');
    }
  };

  return (
    <div className="space-y-2">
      {/* Aggregate backend errors for any `arguments.*` field */}
      <FieldErrorGroup stepErrors={stepErrors} prefix="arguments" />
      <label className="block text-xs text-slate-400">Arguments (JSON)</label>
      <textarea
        value={jsonText}
        onChange={(e) => {
          setJsonText(e.target.value);
          setParseError(null);
        }}
        onBlur={handleBlur}
        rows={16}
        spellCheck={false}
        className="w-full px-3 py-2 bg-slate-950/50 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-emerald-500 leading-relaxed"
      />
      {parseError && (
        <div className="flex items-center gap-1.5 text-xs text-red-400">
          <AlertTriangle className="w-3 h-3" />
          {parseError}
        </div>
      )}
      <p className="text-[10px] text-slate-600">
        Edit the raw JSON arguments for this step. Changes apply on blur.
      </p>
    </div>
  );
}

// Schema-driven Arguments Form — auto-generates fields for ALL 50+ tools

function formatParamLabel(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function isLongTextField(param: ToolParam): boolean {
  const longNames = [
    'prompt', 'message', 'code', 'body', 'content', 'text',
    'query', 'description', 'system_prompt', 'input_message',
  ];
  return longNames.some((n) => param.name.toLowerCase().includes(n));
}

function SchemaArgumentsForm({
  toolName,
  args,
  onArgsChange,
  stepErrors,
}: {
  toolName: string;
  args: Record<string, unknown>;
  onArgsChange: (args: Record<string, unknown>) => void;
  stepErrors: ValidationError[];
}) {
  const toolDoc = TOOL_DOCS[toolName];

  if (!toolDoc || !toolDoc.parameters || toolDoc.parameters.length === 0) {
    // No schema available — fall back to raw JSON editor
    return (
      <GenericArgumentsEditor
        args={args}
        onChange={onArgsChange}
        stepErrors={stepErrors}
      />
    );
  }

  const params = toolDoc.parameters;

  const updateField = (name: string, value: unknown) => {
    onArgsChange({ ...args, [name]: value });
  };

  return (
    <div className="space-y-4">
      <FieldErrorGroup stepErrors={stepErrors} prefix="arguments" />

      {toolDoc && (
        <div className="bg-slate-900/40 border border-slate-700/30 rounded-lg p-3 mb-3">
          <p className="text-xs text-white font-medium">{toolDoc.name}</p>
          <p className="text-[10px] text-slate-400 mt-0.5">{toolDoc.description}</p>
        </div>
      )}

      {params.map((param) => {
        // Handle showWhen conditional visibility
        if (param.showWhen) {
          const depValue = String(args[param.showWhen.field] || '');
          if (!param.showWhen.values.includes(depValue)) return null;
        }

        const value = args[param.name];
        const fieldId = `arg-${toolName}-${param.name}`;

        return (
          <div key={param.name}>
            <label
              htmlFor={fieldId}
              className="flex items-center gap-1 text-xs text-slate-400 mb-1.5"
            >
              {formatParamLabel(param.name)}
              {param.required && <span className="text-cyan-400">*</span>}
            </label>

            {/* ENUM -> Dropdown */}
            {param.enum ? (
              <select
                id={fieldId}
                value={String(value ?? param.default ?? '')}
                onChange={(e) => updateField(param.name, e.target.value)}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
              >
                <option value="" className="text-slate-600">
                  Select {formatParamLabel(param.name)}...
                </option>
                {param.enum.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            ) : /* BOOLEAN -> Toggle switch */
            param.type === 'boolean' ? (
              <button
                type="button"
                id={fieldId}
                onClick={() => updateField(param.name, !value)}
                className={`relative w-10 h-5 rounded-full transition-colors ${
                  value ? 'bg-cyan-500' : 'bg-slate-700'
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    value ? 'translate-x-5' : ''
                  }`}
                />
              </button>
            ) : /* INTEGER/NUMBER with min & max -> Range slider */
            (param.type === 'integer' || param.type === 'number') &&
              param.minimum !== undefined &&
              param.maximum !== undefined ? (
              <div className="flex items-center gap-3">
                <input
                  id={fieldId}
                  type="range"
                  min={param.minimum}
                  max={param.maximum}
                  step={param.type === 'integer' ? 1 : 0.1}
                  value={Number(value ?? param.default ?? param.minimum)}
                  onChange={(e) =>
                    updateField(
                      param.name,
                      param.type === 'integer'
                        ? parseInt(e.target.value)
                        : parseFloat(e.target.value),
                    )
                  }
                  className="flex-1 accent-cyan-500"
                />
                <span className="text-xs text-cyan-400 font-mono w-10 text-right">
                  {String(value ?? param.default ?? param.minimum)}
                </span>
              </div>
            ) : /* INTEGER/NUMBER without range -> Number input */
            param.type === 'integer' || param.type === 'number' ? (
              <input
                id={fieldId}
                type="number"
                value={String(value ?? param.default ?? '')}
                onChange={(e) =>
                  updateField(
                    param.name,
                    param.type === 'integer'
                      ? parseInt(e.target.value)
                      : parseFloat(e.target.value),
                  )
                }
                placeholder={
                  param.default !== undefined ? String(param.default) : ''
                }
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-cyan-500 focus:outline-none"
              />
            ) : /* STRING (long / prompt-like) -> Textarea */
            param.type === 'string' && isLongTextField(param) ? (
              <>
                <textarea
                  id={fieldId}
                  value={String(value || '')}
                  onChange={(e) => updateField(param.name, e.target.value)}
                  placeholder={
                    param.default ? String(param.default) : param.description
                  }
                  rows={
                    param.name.includes('prompt') || param.name.includes('code')
                      ? 6
                      : 4
                  }
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white resize-none focus:border-cyan-500 focus:outline-none"
                />
                <TemplatePreview value={String(value || '')} />
              </>
            ) : /* STRING (short) -> Text input */
            param.type === 'string' ? (
              <>
                <input
                  id={fieldId}
                  type="text"
                  value={String(value || '')}
                  onChange={(e) => updateField(param.name, e.target.value)}
                  placeholder={
                    param.default ? String(param.default) : param.description
                  }
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
                />
                <TemplatePreview value={String(value || '')} />
              </>
            ) : /* ARRAY of strings -> Comma-separated input with chips */
            param.type === 'array' ? (
              <div>
                <input
                  id={fieldId}
                  type="text"
                  value={
                    Array.isArray(value)
                      ? (value as string[]).join(', ')
                      : String(value || '')
                  }
                  onChange={(e) =>
                    updateField(
                      param.name,
                      e.target.value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean),
                    )
                  }
                  placeholder={param.description}
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-cyan-500 focus:outline-none"
                />
                {Array.isArray(value) && (value as string[]).length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {(value as string[]).map((item, i) => (
                      <span
                        key={i}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-cyan-400 border border-slate-700/50 font-mono"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : /* OBJECT -> Small JSON textarea */
            param.type === 'object' ? (
              <textarea
                id={fieldId}
                value={
                  typeof value === 'object'
                    ? JSON.stringify(value, null, 2)
                    : String(value || '{}')
                }
                onChange={(e) => {
                  try {
                    updateField(param.name, JSON.parse(e.target.value));
                  } catch {
                  }
                }}
                rows={4}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-white resize-none focus:border-cyan-500 focus:outline-none"
              />
            ) : (
              <input
                id={fieldId}
                type="text"
                value={String(value || '')}
                onChange={(e) => updateField(param.name, e.target.value)}
                placeholder={param.description}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
              />
            )}

            {/* Field description */}
            <p className="text-[10px] text-slate-600 mt-1">{param.description}</p>
            <FieldError
              stepErrors={stepErrors}
              field={`arguments.${param.name}`}
            />
          </div>
        );
      })}
    </div>
  );
}

// Inputs Tab

function InputsTab({
  step,
  allSteps,
  onUpdate,
}: {
  step: PipelineStep;
  allSteps: PipelineStep[];
  onUpdate: (stepId: string, updates: Partial<PipelineStep>) => void;
}) {
  // Find upstream steps (those in dependsOn)
  const upstreamSteps = allSteps.filter((s) => step.dependsOn.includes(s.id));

  const mappingEntries = Object.entries(step.inputMappings);

  const handleAddMapping = () => {
    const defaultSource = upstreamSteps.length > 0 ? upstreamSteps[0].id : '';
    const newKey = `input_${mappingEntries.length}`;
    onUpdate(step.id, {
      inputMappings: {
        ...step.inputMappings,
        [newKey]: { sourceNode: defaultSource, sourceField: '__all__' },
      },
    });
  };

  const handleRemoveMapping = (key: string) => {
    const updated = { ...step.inputMappings };
    delete updated[key];
    onUpdate(step.id, { inputMappings: updated });
  };

  const handleUpdateMappingKey = (oldKey: string, newKey: string) => {
    if (oldKey === newKey) return;
    const updated = { ...step.inputMappings };
    const value = updated[oldKey];
    delete updated[oldKey];
    updated[newKey] = value;
    onUpdate(step.id, { inputMappings: updated });
  };

  const handleUpdateMappingSource = (
    key: string,
    sourceNode: string,
    sourceField: string,
  ) => {
    onUpdate(step.id, {
      inputMappings: {
        ...step.inputMappings,
        [key]: { sourceNode, sourceField },
      },
    });
  };

  return (
    <div className="space-y-4">
      <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-3 mb-3">
        <p className="text-[10px] text-cyan-400 font-medium mb-1">When to use Input Mappings</p>
        <p className="text-[10px] text-slate-400">Input Mappings are an advanced alternative to template variables ({'{'}{'{'} node.response {'}'}{'}'}). Use them when you need to map a specific field from an upstream node&apos;s output to a specific argument of this node. Most users should use template variables in the Arguments tab instead.</p>
      </div>
      {/* Upstream dependencies summary */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">
          Upstream Dependencies
        </label>
        {upstreamSteps.length === 0 ? (
          <p className="text-[10px] text-slate-600 px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg">
            No upstream dependencies. Connect other steps to this one to create
            input mappings.
          </p>
        ) : (
          <div className="space-y-1">
            {upstreamSteps.map((upstream) => (
              <div
                key={upstream.id}
                className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 border border-slate-700 rounded-lg"
              >
                <Zap className="w-3 h-3 text-emerald-400 shrink-0" />
                <span className="text-xs text-white truncate">
                  {upstream.label}
                </span>
                <span className="text-[10px] text-slate-500 truncate">
                  ({formatToolName(upstream.toolName)})
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Input mappings */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">
          Input Mappings
        </label>
        {mappingEntries.length === 0 ? (
          <p className="text-[10px] text-slate-600 px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg">
            No input mappings defined. Add mappings to pass data between steps.
          </p>
        ) : (
          <div className="space-y-2">
            {mappingEntries.map(([key, mapping]) => (
              <div
                key={key}
                className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg space-y-2"
              >
                {/* Source step */}
                <div>
                  <label className="block text-[10px] text-slate-500 mb-1">
                    Source Step
                  </label>
                  <select
                    value={mapping.sourceNode}
                    onChange={(e) =>
                      handleUpdateMappingSource(
                        key,
                        e.target.value,
                        mapping.sourceField,
                      )
                    }
                    className="w-full px-2 py-1.5 bg-slate-900/50 border border-slate-700 rounded text-xs text-white focus:outline-none focus:border-emerald-500"
                  >
                    <option value="">Select source step</option>
                    {upstreamSteps.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label} ({formatToolName(s.toolName)})
                      </option>
                    ))}
                  </select>
                </div>

                {/* Argument name (the key) */}
                <div>
                  <label className="block text-[10px] text-slate-500 mb-1">
                    Input Argument Name
                  </label>
                  <input
                    type="text"
                    value={key}
                    onBlur={(e) => {
                      const trimmed = e.target.value.trim();
                      if (trimmed && trimmed !== key) {
                        handleUpdateMappingKey(key, trimmed);
                      }
                    }}
                    onChange={() => {
                    }}
                    defaultValue={key}
                    className="w-full px-2 py-1.5 bg-slate-900/50 border border-slate-700 rounded text-xs font-mono text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Source field */}
                <div>
                  <label className="block text-[10px] text-slate-500 mb-1">
                    Source Field
                  </label>
                  <input
                    type="text"
                    value={mapping.sourceField}
                    onChange={(e) =>
                      handleUpdateMappingSource(
                        key,
                        mapping.sourceNode,
                        e.target.value,
                      )
                    }
                    placeholder="__all__"
                    className="w-full px-2 py-1.5 bg-slate-900/50 border border-slate-700 rounded text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Delete mapping */}
                <button
                  onClick={() => handleRemoveMapping(key)}
                  className="flex items-center gap-1 text-[10px] text-red-400 hover:text-red-300 transition-colors"
                >
                  <Trash2 className="w-3 h-3" />
                  Remove mapping
                </button>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={handleAddMapping}
          disabled={upstreamSteps.length === 0}
          className="w-full mt-2 flex items-center justify-center gap-1.5 py-2 rounded-lg border border-dashed border-slate-700 text-xs text-slate-400 hover:border-emerald-500/40 hover:text-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Input Mapping
        </button>
      </div>
    </div>
  );
}

// Condition Tab

function ConditionTab({
  step,
  allSteps,
  onUpdate,
}: {
  step: PipelineStep;
  allSteps: PipelineStep[];
  onUpdate: (stepId: string, updates: Partial<PipelineStep>) => void;
}) {
  // Only upstream (dependency) steps can be used as condition sources
  const upstreamSteps = allSteps.filter((s) => step.dependsOn.includes(s.id));
  const condition = step.condition;

  const handleAddCondition = () => {
    const defaultSource = upstreamSteps.length > 0 ? upstreamSteps[0].id : '';
    onUpdate(step.id, {
      condition: {
        sourceNode: defaultSource,
        field: '',
        operator: 'eq',
        value: '',
      },
    });
  };

  const handleRemoveCondition = () => {
    onUpdate(step.id, { condition: null });
  };

  const handleUpdateCondition = (updates: Partial<PipelineCondition>) => {
    if (!condition) return;
    onUpdate(step.id, {
      condition: { ...condition, ...updates },
    });
  };

  if (!condition) {
    return (
      <div className="space-y-4">
        <div className="bg-slate-900/40 border border-slate-700/30 rounded-lg p-3 mb-3">
          <p className="text-[10px] text-slate-400">Skip this step based on an upstream node&apos;s output. Example: only run the &apos;email_sender&apos; step if the previous step&apos;s &apos;should_notify&apos; field equals &apos;true&apos;.</p>
        </div>
        <div>
          <p className="text-xs text-slate-400 mb-2">
            Add a condition gate to control when this step executes. The step
            will only run when the condition is met.
          </p>
          <button
            onClick={handleAddCondition}
            className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-lg border border-dashed border-slate-700 text-xs text-slate-400 hover:border-emerald-500/40 hover:text-emerald-400 transition-all"
          >
            <GitBranch className="w-3.5 h-3.5" />
            Add Condition
          </button>
        </div>
        <div className="pt-2 border-t border-slate-800">
          <p className="text-[10px] text-slate-600">
            Without a condition, this step will always execute when its
            dependencies are fulfilled.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-slate-900/40 border border-slate-700/30 rounded-lg p-3 mb-3">
        <p className="text-[10px] text-slate-400">Skip this step based on an upstream node&apos;s output. Example: only run the &apos;email_sender&apos; step if the previous step&apos;s &apos;should_notify&apos; field equals &apos;true&apos;.</p>
      </div>
      {/* Source Node */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Source Node</label>
        <select
          value={condition.sourceNode}
          onChange={(e) => handleUpdateCondition({ sourceNode: e.target.value })}
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
        >
          <option value="">Select source step</option>
          {upstreamSteps.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label} ({formatToolName(s.toolName)})
            </option>
          ))}
        </select>
      </div>

      {/* Field */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Field</label>
        <input
          type="text"
          value={condition.field}
          onChange={(e) => handleUpdateCondition({ field: e.target.value })}
          placeholder="e.g. score, result.status"
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm font-mono text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
        />
        <p className="text-[10px] text-slate-600 mt-1">
          Dot-path to the field in the source output
        </p>
      </div>

      {/* Operator */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Operator</label>
        <select
          value={condition.operator}
          onChange={(e) =>
            handleUpdateCondition({
              operator: e.target.value as PipelineCondition['operator'],
            })
          }
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
        >
          {CONDITION_OPERATORS.map((op) => (
            <option key={op.value} value={op.value}>
              {op.label}
            </option>
          ))}
        </select>
      </div>

      {/* Value */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Value</label>
        <input
          type="text"
          value={String(condition.value ?? '')}
          onChange={(e) => handleUpdateCondition({ value: e.target.value })}
          placeholder="Comparison value"
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
        />
        <p className="text-[10px] text-slate-600 mt-1">
          The value to compare against. For &quot;in&quot; / &quot;not_in&quot;,
          use comma-separated values.
        </p>
      </div>

      {/* Remove condition */}
      <button
        onClick={handleRemoveCondition}
        className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-red-500/30 text-xs text-red-400 hover:bg-red-500/10 transition-all"
      >
        <Trash2 className="w-3.5 h-3.5" />
        Remove Condition
      </button>
    </div>
  );
}

// Retry Tab

function RetryTab({
  step,
  onUpdate,
}: {
  step: PipelineStep;
  onUpdate: (stepId: string, updates: Partial<PipelineStep>) => void;
}) {
  const maxRetries = step.maxRetries ?? 0;
  const retryDelayMs = step.retryDelayMs ?? 1000;

  return (
    <div className="space-y-4">
      <div className="bg-slate-900/40 border border-slate-700/30 rounded-lg p-3 mb-3">
        <p className="text-[10px] text-slate-400">Automatically retry this step if it fails. Uses exponential backoff — each retry waits longer than the last. Good for external API calls (web search, HTTP) that may have transient failures.</p>
      </div>
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs text-slate-400">Max Retries</label>
          <span className="text-xs font-mono text-emerald-400">{maxRetries}</span>
        </div>
        <input
          type="range"
          min="0"
          max="5"
          step="1"
          value={maxRetries}
          onChange={(e) =>
            onUpdate(step.id, { maxRetries: parseInt(e.target.value) })
          }
          className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
        />
        <div className="flex justify-between mt-1">
          <span className="text-[10px] text-slate-600">0 (no retry)</span>
          <span className="text-[10px] text-slate-600">5</span>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs text-slate-400">Base Delay</label>
          <span className="text-xs font-mono text-emerald-400">{retryDelayMs}ms</span>
        </div>
        <input
          type="range"
          min="100"
          max="30000"
          step="100"
          value={retryDelayMs}
          onChange={(e) =>
            onUpdate(step.id, { retryDelayMs: parseInt(e.target.value) })
          }
          className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
        />
        <div className="flex justify-between mt-1">
          <span className="text-[10px] text-slate-600">100ms</span>
          <span className="text-[10px] text-slate-600">30s</span>
        </div>
      </div>

      {maxRetries > 0 && (
        <div className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg">
          <p className="text-[10px] text-slate-400">
            Retry schedule (exponential backoff):
          </p>
          <div className="mt-1 space-y-0.5">
            {Array.from({ length: maxRetries }, (_, i) => {
              const delay = retryDelayMs * Math.pow(2, i);
              return (
                <p key={i} className="text-[10px] text-slate-500 font-mono">
                  Attempt {i + 2}: after {delay >= 1000 ? `${(delay / 1000).toFixed(1)}s` : `${delay}ms`}
                </p>
              );
            })}
          </div>
        </div>
      )}

      <div className="pt-2 border-t border-slate-800">
        <p className="text-[10px] text-slate-600">
          When a step fails, it will be retried with exponential backoff.
          The delay doubles after each attempt.
        </p>
      </div>
    </div>
  );
}

// GitHub Tool Arguments Form

const GITHUB_OPERATIONS = [
  { value: 'get_repo', label: 'Get Repository Info' },
  { value: 'list_files', label: 'List Files' },
  { value: 'read_file', label: 'Read File' },
  { value: 'search_code', label: 'Search Code' },
  { value: 'list_issues', label: 'List Issues' },
  { value: 'list_pull_requests', label: 'List Pull Requests' },
  { value: 'get_commits', label: 'Get Commits' },
  { value: 'get_languages', label: 'Get Languages' },
  { value: 'get_workflows', label: 'Get CI/CD Workflows' },
  { value: 'compare_branches', label: 'Compare Branches' },
];

function GitHubToolArgumentsForm({
  args,
  onChange,
  stepErrors,
}: {
  args: Record<string, unknown>;
  onChange: (args: Record<string, unknown>) => void;
  stepErrors: ValidationError[];
}) {
  const operation = (args.operation as string) || 'get_repo';
  const owner = (args.owner as string) || '';
  const repo = (args.repo as string) || '';

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Operation</label>
        <select
          value={operation}
          onChange={(e) => onChange({ ...args, operation: e.target.value })}
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
        >
          {GITHUB_OPERATIONS.map((op) => (
            <option key={op.value} value={op.value}>{op.label}</option>
          ))}
        </select>
        <FieldError stepErrors={stepErrors} field="arguments.operation" />
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Owner</label>
        <input
          type="text"
          value={owner}
          onChange={(e) => onChange({ ...args, owner: e.target.value })}
          placeholder="e.g. anthropics"
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
        />
        <FieldError stepErrors={stepErrors} field="arguments.owner" />
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Repository</label>
        <input
          type="text"
          value={repo}
          onChange={(e) => onChange({ ...args, repo: e.target.value })}
          placeholder="e.g. claude-code"
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
        />
        <FieldError stepErrors={stepErrors} field="arguments.repo" />
      </div>

      {(operation === 'read_file' || operation === 'search_code') && (
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">
            {operation === 'read_file' ? 'File Path' : 'Search Query'}
          </label>
          <input
            type="text"
            value={(args[operation === 'read_file' ? 'path' : 'query'] as string) || ''}
            onChange={(e) =>
              onChange({
                ...args,
                [operation === 'read_file' ? 'path' : 'query']: e.target.value,
              })
            }
            placeholder={operation === 'read_file' ? 'e.g. src/index.ts' : 'e.g. function handleAuth'}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
          />
          <FieldError
            stepErrors={stepErrors}
            field={operation === 'read_file' ? 'arguments.path' : 'arguments.query'}
          />
        </div>
      )}

      {(operation === 'list_issues' || operation === 'list_pull_requests') && (
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">State</label>
          <select
            value={(args.state as string) || 'open'}
            onChange={(e) => onChange({ ...args, state: e.target.value })}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
          >
            <option value="open">Open</option>
            <option value="closed">Closed</option>
            <option value="all">All</option>
          </select>
        </div>
      )}

      {operation === 'compare_branches' && (
        <>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Base Branch</label>
            <input
              type="text"
              value={(args.base as string) || 'main'}
              onChange={(e) => onChange({ ...args, base: e.target.value })}
              placeholder="main"
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Head Branch</label>
            <input
              type="text"
              value={(args.head as string) || ''}
              onChange={(e) => onChange({ ...args, head: e.target.value })}
              placeholder="feature-branch"
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
            />
          </div>
        </>
      )}
    </div>
  );
}

// Agent Step Arguments Form

function AgentStepArgumentsForm({
  args,
  onChange,
  stepErrors,
}: {
  args: Record<string, unknown>;
  onChange: (args: Record<string, unknown>) => void;
  stepErrors: ValidationError[];
}) {
  const inputMessage = (args.input_message as string) || '';
  const systemPrompt = (args.system_prompt as string) || '';
  const model = (args.model as string) || 'claude-sonnet-4-5-20250929';
  const maxIterations = typeof args.max_iterations === 'number' ? args.max_iterations : 10;
  const temperature = typeof args.temperature === 'number' ? args.temperature : 0.7;

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Task / Input Message<HelpTip text="The task or question this agent will work on. Use {{node_id.response}} to inject outputs from upstream nodes. Example: 'Find historical analogies for: {{decision_parser.response}}'" /></label>
        <textarea
          value={inputMessage}
          onChange={(e) => onChange({ ...args, input_message: e.target.value })}
          placeholder="Describe the task for the agent..."
          rows={4}
          className="w-full px-3 py-2 bg-slate-950/50 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-emerald-500 leading-relaxed"
        />
        <TemplatePreview value={inputMessage} />
        <FieldError stepErrors={stepErrors} field="arguments.input_message" />
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1.5">System Prompt<HelpTip text="Defines the agent's role, expertise, and behavior. This is the 'personality' of the sub-agent. Be specific about what the agent should do, what tools to use, and what format to output." /></label>
        <textarea
          value={systemPrompt}
          onChange={(e) => onChange({ ...args, system_prompt: e.target.value })}
          placeholder="You are a helpful assistant that..."
          rows={5}
          className="w-full px-3 py-2 bg-slate-950/50 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-emerald-500 leading-relaxed"
        />
        <TemplatePreview value={systemPrompt} />
        <FieldError stepErrors={stepErrors} field="arguments.system_prompt" />
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1.5">Model<HelpTip text="Which LLM to use. Sonnet is best for complex research and reasoning. Haiku is faster and cheaper for simple tasks." /></label>
        <select
          value={model}
          onChange={(e) => onChange({ ...args, model: e.target.value })}
          className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
        >
          {MODELS.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
        <FieldError stepErrors={stepErrors} field="arguments.model" />
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs text-slate-400">Max Iterations<HelpTip text="How many LLM reasoning loops the agent can do. More iterations = deeper analysis but higher cost. 10 is good for research agents, 3-5 for simple tasks." /></label>
          <span className="text-xs font-mono text-emerald-400">{maxIterations}</span>
        </div>
        <input
          type="range"
          min="1"
          max="25"
          step="1"
          value={maxIterations}
          onChange={(e) => onChange({ ...args, max_iterations: parseInt(e.target.value) })}
          className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs text-slate-400">Temperature<HelpTip text="Controls randomness. 0 = deterministic (same input → same output). 0.7 = balanced. 1.0+ = creative/varied. Use 0.3-0.5 for factual tasks, 0.7-1.0 for creative." /></label>
          <span className="text-xs font-mono text-emerald-400">{temperature.toFixed(1)}</span>
        </div>
        <input
          type="range"
          min="0"
          max="2"
          step="0.1"
          value={temperature}
          onChange={(e) => onChange({ ...args, temperature: parseFloat(e.target.value) })}
          className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
        />
      </div>

      {/* Tools available to this agent */}
      <div>
        <label className="text-xs text-slate-400 block mb-1.5">Tools Available to Agent<HelpTip text="Comma-separated tool names the agent can use. Only listed tools are available — the agent cannot call unlisted tools. Example: tavily_search,http_client,code_executor" /></label>
        <input
          type="text"
          value={(args.tools as string) || ''}
          onChange={(e) => onChange({ ...args, tools: e.target.value })}
          placeholder="e.g., tavily_search,http_client,academic_search"
          className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-cyan-500 focus:outline-none"
        />
        <p className="text-[10px] text-slate-600 mt-1">Comma-separated tool names. Only listed tools will be available to the sub-agent during execution.</p>
        {(args.tools as string) && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {String(args.tools).split(',').map((t: string) => t.trim()).filter(Boolean).map((t: string) => (
              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-mono">{t}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// Switch Case Editor — config UI for __switch__ nodes

const SWITCH_OPERATORS = [
  { value: 'eq', label: '= (equals)' },
  { value: 'neq', label: '!= (not equals)' },
  { value: 'gt', label: '> (greater)' },
  { value: 'lt', label: '< (less)' },
  { value: 'gte', label: '>= (gte)' },
  { value: 'lte', label: '<= (lte)' },
  { value: 'contains', label: 'contains' },
  { value: 'not_contains', label: 'not contains' },
  { value: 'in', label: 'in (list)' },
  { value: 'not_in', label: 'not in (list)' },
];

function SwitchCaseEditor({
  step,
  allSteps,
  onUpdate,
}: {
  step: PipelineStep;
  allSteps: PipelineStep[];
  onUpdate: (id: string, updates: Partial<PipelineStep>) => void;
}) {
  const config: SwitchConfig = step.switchConfig || {
    sourceNode: step.dependsOn[0] || '',
    field: 'response',
    cases: [],
    defaultNode: null,
  };

  const updateConfig = (patch: Partial<SwitchConfig>) => {
    onUpdate(step.id, { switchConfig: { ...config, ...patch } });
  };

  const addCase = () => {
    updateConfig({
      cases: [...config.cases, { operator: 'eq', value: '', targetNode: '' }],
    });
  };

  const updateCase = (idx: number, patch: Record<string, unknown>) => {
    const next = [...config.cases];
    next[idx] = { ...next[idx], ...patch } as typeof next[0];
    updateConfig({ cases: next });
  };

  const removeCase = (idx: number) => {
    updateConfig({ cases: config.cases.filter((_, i) => i !== idx) });
  };

  const upstreamOptions = allSteps.filter((s) => s.id !== step.id);

  return (
    <div className="space-y-4" data-testid="switch-case-editor">
      <div>
        <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">
          Source node
        </label>
        <select
          data-testid="switch-source-node"
          value={config.sourceNode}
          onChange={(e) => updateConfig({ sourceNode: e.target.value })}
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200"
        >
          <option value="">Select upstream step…</option>
          {upstreamOptions.map((s) => (
            <option key={s.id} value={s.id}>{s.label} ({s.id})</option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">
          Field to evaluate
        </label>
        <input
          data-testid="switch-field"
          value={config.field}
          onChange={(e) => updateConfig({ field: e.target.value })}
          placeholder="response"
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono"
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">
            Cases ({config.cases.length})
          </label>
          <button
            onClick={addCase}
            data-testid="switch-add-case"
            className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
          >
            <Plus className="w-3 h-3" /> Add case
          </button>
        </div>
        <div className="space-y-2">
          {config.cases.map((c, i) => (
            <div key={i} className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-2.5 space-y-1.5"
                 data-testid={`switch-case-${i}`}>
              <div className="flex items-center gap-1.5">
                <select
                  value={c.operator}
                  onChange={(e) => updateCase(i, { operator: e.target.value })}
                  className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[10px] text-slate-200"
                >
                  {SWITCH_OPERATORS.map((op) => (
                    <option key={op.value} value={op.value}>{op.label}</option>
                  ))}
                </select>
                <input
                  value={String(c.value)}
                  onChange={(e) => updateCase(i, { value: e.target.value })}
                  placeholder="value"
                  className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[10px] text-slate-200 font-mono"
                />
                <button onClick={() => removeCase(i)} className="text-slate-500 hover:text-rose-400">
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
              <select
                value={c.targetNode}
                onChange={(e) => updateCase(i, { targetNode: e.target.value })}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[10px] text-slate-200"
              >
                <option value="">→ Target step…</option>
                {upstreamOptions.map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            </div>
          ))}
          {config.cases.length === 0 && (
            <p className="text-[10px] text-slate-500 text-center py-3">
              No cases yet. Add one to start routing.
            </p>
          )}
        </div>
      </div>

      <div>
        <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">
          Default branch (unmatched)
        </label>
        <select
          data-testid="switch-default-node"
          value={config.defaultNode || ''}
          onChange={(e) => updateConfig({ defaultNode: e.target.value || null })}
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200"
        >
          <option value="">(none — skip if unmatched)</option>
          {upstreamOptions.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
}

// Step type icon resolver

function getStepIcon(toolName: string): {
  icon: typeof Zap;
  color: string;
  bg: string;
} {
  // Condition and output types get special treatment
  if (toolName === 'condition') {
    return { icon: GitBranch, color: 'text-amber-400', bg: 'bg-amber-500/10' };
  }
  if (toolName === '__switch__') {
    return { icon: GitBranch, color: 'text-purple-400', bg: 'bg-purple-500/10' };
  }
  if (toolName === '__merge__') {
    return { icon: GitBranch, color: 'text-teal-400', bg: 'bg-teal-500/10' };
  }
  if (toolName === 'output') {
    return { icon: Flag, color: 'text-purple-400', bg: 'bg-purple-500/10' };
  }
  return { icon: Zap, color: 'text-emerald-400', bg: 'bg-emerald-500/10' };
}

// StepConfigPanel

export default function StepConfigPanel({
  step,
  allSteps,
  onUpdate,
  onClose,
}: StepConfigPanelProps) {
  const [tab, setTab] = useState<Tab>('general');

  // Pull backend validation errors for this step. Selector returns a new
  // array per call so we return the underlying arrays from state directly
  // and filter below to avoid a re-render loop.
  const allErrors = usePipelineStore((s) => s.validation.errors);
  const allWarnings = usePipelineStore((s) => s.validation.warnings);
  const stepErrors: ValidationError[] = step
    ? [
        ...allErrors.filter((e) => e.node_id === step.id),
        ...allWarnings.filter((w) => w.node_id === step.id),
      ]
    : [];

  // Show pipeline overview when no step is selected
  if (!step) {
    return <PipelineOverview allSteps={allSteps} onClose={onClose} />;
  }

  const stepIcon = getStepIcon(step.toolName);
  const Icon = stepIcon.icon;

  const isSwitch = step.toolName === '__switch__';
  const tabs: { key: Tab; label: string }[] = [
    { key: 'general', label: 'General' },
    ...(isSwitch ? [] : [{ key: 'arguments' as Tab, label: 'Arguments' }]),
    { key: 'inputs', label: 'Inputs' },
    ...(isSwitch ? [{ key: 'arguments' as Tab, label: 'Switch Cases' }] : []),
    { key: 'condition', label: 'Condition' },
    { key: 'retry', label: 'Retry' },
  ];

  const handleLabelChange = (e: ChangeEvent<HTMLInputElement>) => {
    onUpdate(step.id, { label: e.target.value });
  };

  const handleArgumentsChange = (args: Record<string, unknown>) => {
    onUpdate(step.id, { arguments: args });
  };

  return (
    <div className="w-[320px] border-l border-slate-800 bg-[#0F172A] flex flex-col shrink-0 overflow-hidden">
      {/* Header */}
      <div className="border-b border-slate-800/50 p-3">
        <button
          onClick={onClose}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors mb-3"
        >
          <ArrowLeft className="w-3 h-3" />
          Back to Pipeline Settings
        </button>
        <div className="flex items-center gap-3">
          <div
            className={`w-10 h-10 rounded-lg ${stepIcon.bg} flex items-center justify-center shrink-0`}
          >
            <Icon className={`w-5 h-5 ${stepIcon.color}`} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white truncate">
              {step.label}
            </p>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">
              {formatToolName(step.toolName)}
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800/50">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2.5 text-xs font-medium transition-colors flex items-center justify-center ${
              tab === t.key
                ? 'text-emerald-400 border-b-2 border-emerald-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* General tab */}
        {tab === 'general' && (
          <>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Step Label<HelpTip text="A human-readable name for this step. Shown on the canvas and in execution logs. Make it descriptive — 'Historian Agent' is better than 'Step 3'." />
              </label>
              <input
                type="text"
                value={step.label}
                onChange={handleLabelChange}
                placeholder="Step name"
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Tool</label>
              <p className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white">
                {formatToolName(step.toolName)}
              </p>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Step ID<HelpTip text="Unique identifier for this step. Use this in template variables: {{step_id.response}} to reference this step's output in downstream nodes." />
              </label>
              <p className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-[10px] font-mono text-slate-500 select-all">
                {step.id}
              </p>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                Dependencies<HelpTip text="Steps that must complete before this one runs. Data flows from dependencies to this step via template variables like {{dependency_id.response}}." />
              </label>
              {step.dependsOn.length === 0 ? (
                <p className="px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-xs text-slate-500">
                  No dependencies (root step)
                </p>
              ) : (
                <div className="space-y-1">
                  {step.dependsOn.map((depId) => {
                    const depStep = allSteps.find((s) => s.id === depId);
                    return (
                      <div
                        key={depId}
                        className="px-3 py-1.5 bg-slate-800/50 border border-slate-700 rounded-lg text-xs text-slate-300"
                      >
                        {depStep ? depStep.label : depId}
                      </div>
                    );
                  })}
                </div>
              )}
              <FieldError stepErrors={stepErrors} field="depends_on" />
            </div>
            {/* Agent Configuration Summary */}
            {step.toolName === 'agent_step' && (step.arguments?.system_prompt || step.arguments?.tools || step.arguments?.input_message) && (
              <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-3 space-y-2 mt-3">
                <p className="text-xs text-cyan-400 font-semibold">Agent Configuration</p>
                {Boolean(step.arguments.system_prompt) && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-0.5">Role</p>
                    <p className="text-[11px] text-slate-300 line-clamp-2">{String(step.arguments.system_prompt).split('\n').filter(Boolean)[0]}</p>
                  </div>
                )}
                {Boolean(step.arguments.tools) && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-0.5">Tools</p>
                    <div className="flex flex-wrap gap-1">
                      {String(step.arguments.tools).split(',').map((t: string) => t.trim()).filter(Boolean).map((t: string) => (
                        <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-cyan-400 border border-slate-700/50 font-mono">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
                {Boolean(step.arguments.input_message) && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-0.5">Input</p>
                    <p className="text-[10px] text-slate-400 font-mono truncate">{String(step.arguments.input_message).slice(0, 100)}{String(step.arguments.input_message).length > 100 ? '...' : ''}</p>
                  </div>
                )}
                {Boolean(step.arguments.model) && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-0.5">Model</p>
                    <p className="text-[10px] text-slate-300">{String(step.arguments.model)}</p>
                  </div>
                )}
              </div>
            )}
            {/* LLM Call Configuration Summary */}
            {step.toolName === 'llm_call' && (step.arguments?.system_prompt || step.arguments?.prompt) && (
              <div className="bg-purple-500/5 border border-purple-500/20 rounded-lg p-3 space-y-2 mt-3">
                <p className="text-xs text-purple-400 font-semibold">LLM Call Configuration</p>
                {Boolean(step.arguments.system_prompt) && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-0.5">System Prompt</p>
                    <p className="text-[11px] text-slate-300 line-clamp-2">{String(step.arguments.system_prompt).split('\n').filter(Boolean)[0]}</p>
                  </div>
                )}
                {Boolean(step.arguments.prompt) && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-0.5">Prompt Template</p>
                    <p className="text-[10px] text-slate-400 font-mono truncate">{String(step.arguments.prompt).slice(0, 100)}...</p>
                  </div>
                )}
              </div>
            )}
            {/* Advanced: engine-DSL passthroughs. These map to the YAML
                fields the pipeline parser understands but the UI used
                to hide — required_if gates the whole step on a
                template expression, agent_slug lets an agent_step node
                reference a seeded agent by slug so its system_prompt /
                model / tools are pulled live. */}
            <details className="mt-3 border-t border-slate-800/40 pt-3">
              <summary className="cursor-pointer text-[10px] font-semibold text-slate-500 uppercase tracking-wider select-none hover:text-slate-300">
                Advanced · Engine DSL
              </summary>
              <div className="mt-3 space-y-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Run only if
                    <HelpTip text="A template expression that gates the whole step. Evaluated before the tool runs — when the resolved value is empty, 'false', '[]', 'null', or '[not available]', the step is skipped. Example: {{plan.actions.0.requires_approval}}." />
                  </label>
                  <input
                    type="text"
                    value={step.requiredIf || ''}
                    placeholder="{{plan.actions.0.requires_approval}}"
                    onChange={(e) => onUpdate(step.id, { requiredIf: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
                  />
                  <p className="text-[9px] text-slate-600 mt-1">
                    Optional. Leave blank to always run.
                  </p>
                </div>
                {step.toolName === 'agent_step' && (
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">
                      Agent slug (live reference)
                      <HelpTip text="When set, the engine fetches system_prompt / model / tools from the seeded agent with this slug at execution time. Leaves the inline Arguments (system_prompt/model/tools) as a fallback. Use this when you want edits to the referenced agent to flow through to this pipeline automatically." />
                    </label>
                    <input
                      type="text"
                      value={step.agentSlug || ''}
                      placeholder="e.g. resolveai-triage"
                      onChange={(e) => onUpdate(step.id, { agentSlug: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-xs font-mono text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500"
                    />
                    <p className="text-[9px] text-slate-600 mt-1">
                      Optional. Leaves inline Arguments as a fallback when unset.
                    </p>
                  </div>
                )}
              </div>
            </details>
            {/* Backend errors for tool/id fields (general-tab scope) */}
            <FieldError stepErrors={stepErrors} field="tool" />
            <FieldError stepErrors={stepErrors} field="id" />
          </>
        )}

        {/* Switch Cases tab — only for __switch__ nodes */}
        {tab === 'arguments' && isSwitch && (
          <SwitchCaseEditor step={step} allSteps={allSteps} onUpdate={onUpdate} />
        )}

        {/* Arguments tab (normal tools) */}
        {tab === 'arguments' && !isSwitch && (
          <>
            {/* Aggregated template-reference errors at top of tab.
                These are reported by the validator against field "arguments"
                (not a specific arg) and include {{unknown_node.field}} errors. */}
            <FieldErrorGroup
              stepErrors={stepErrors}
              prefix="arguments"
              exclude={[
                'prompt',
                'system_prompt',
                'model',
                'operation',
                'owner',
                'repo',
                'path',
                'query',
                'input_message',
              ]}
            />
            {/* Available upstream variables */}
            {step.dependsOn && step.dependsOn.length > 0 && (
              <div className="mb-2">
                <p className="text-[10px] text-slate-500 mb-1">Available from upstream:</p>
                <div className="flex flex-col gap-1.5">
                  {step.dependsOn.filter(Boolean).map((depId: string) => {
                    const upstream = allSteps?.find((s: PipelineStep) => s.id === depId);
                    const label = upstream?.label || depId;
                    return (
                      <div key={depId} className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => {
                            // Insert at cursor or append
                            const ref = `{{${depId}.response}}`;
                            const field = 'input_message' in (step.arguments || {}) ? 'input_message' : 'prompt';
                            const current = (step.arguments?.[field] as string) || '';
                            onUpdate(step.id, {
                              arguments: {
                                ...step.arguments,
                                [field]: current ? `${current}\n${ref}` : ref,
                              },
                            });
                          }}
                          className="text-[10px] px-2 py-1 rounded-md bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 font-mono transition-colors"
                        >
                          {`{{${depId}.response}}`}
                        </button>
                        <span className="text-[9px] text-slate-600">{'\u2190'} {label}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {step.toolName === 'llm_call' ? (
              <LLMCallArgumentsForm
                args={step.arguments}
                onChange={handleArgumentsChange}
                stepErrors={stepErrors}
              />
            ) : step.toolName === 'github_tool' ? (
              <GitHubToolArgumentsForm
                args={step.arguments}
                onChange={handleArgumentsChange}
                stepErrors={stepErrors}
              />
            ) : step.toolName === 'agent_step' ? (
              <AgentStepArgumentsForm
                args={step.arguments}
                onChange={handleArgumentsChange}
                stepErrors={stepErrors}
              />
            ) : (
              <SchemaArgumentsForm
                toolName={step.toolName}
                args={step.arguments || {}}
                onArgsChange={handleArgumentsChange}
                stepErrors={stepErrors}
              />
            )}
          </>
        )}

        {/* Inputs tab */}
        {tab === 'inputs' && (
          <InputsTab step={step} allSteps={allSteps} onUpdate={onUpdate} />
        )}

        {/* Condition tab */}
        {tab === 'condition' && (
          <ConditionTab step={step} allSteps={allSteps} onUpdate={onUpdate} />
        )}

        {/* Retry tab */}
        {tab === 'retry' && (
          <RetryTab step={step} onUpdate={onUpdate} />
        )}
      </div>
    </div>
  );
}
