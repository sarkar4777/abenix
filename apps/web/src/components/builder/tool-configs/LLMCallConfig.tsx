'use client';

/**
 * LLMCallConfig — Specialized config for the `llm_call` tool.
 *
 * Shows: model dropdown, prompt textarea, system_prompt textarea,
 * temperature slider, max_tokens input.
 */

import { ChevronDown } from 'lucide-react';

const MODELS = [
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-3-5-20241022', label: 'Claude Haiku 3.5' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
];

interface LLMCallConfigProps {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export default function LLMCallConfig({ values, onChange }: LLMCallConfigProps) {
  const model = (values.model as string) || 'claude-sonnet-4-5-20250929';
  const temperature = typeof values.temperature === 'number' ? values.temperature : 0.7;
  const maxTokens = typeof values.max_tokens === 'number' ? values.max_tokens : 4096;

  return (
    <div className="space-y-4">
      {/* Prompt */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">prompt</span>
          <span className="text-red-400 text-[8px]">required</span>
        </label>
        <textarea
          value={(values.prompt as string) || ''}
          onChange={(e) => onChange({ ...values, prompt: e.target.value })}
          placeholder="The prompt to send to the LLM. Use {{node_id.field}} or {{node_id.__all__}} for template variables from upstream pipeline nodes."
          rows={5}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500"
        />
        <p className="text-[8px] text-slate-600 mt-0.5">
          Template variables: <code className="text-cyan-500/70">{'{{node_id.field}}'}</code> or <code className="text-cyan-500/70">{'{{node_id.__all__}}'}</code>
        </p>
      </div>

      {/* System Prompt */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">system_prompt</span>
          <span className="text-slate-600 text-[8px]">optional</span>
        </label>
        <textarea
          value={(values.system_prompt as string) || ''}
          onChange={(e) => onChange({ ...values, system_prompt: e.target.value })}
          placeholder="You are a helpful assistant that..."
          rows={3}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500"
        />
      </div>

      {/* Model */}
      <div>
        <label className="text-[10px] text-slate-400 mb-1 block">
          <span className="font-mono text-slate-500">model</span>
        </label>
        <div className="relative">
          <select
            value={model}
            onChange={(e) => onChange({ ...values, model: e.target.value })}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500 appearance-none pr-8"
          >
            {MODELS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
        </div>
      </div>

      {/* Temperature */}
      <div>
        <label className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">temperature</span>
          <span className="text-slate-300">{temperature.toFixed(1)}</span>
        </label>
        <input
          type="range"
          min={0}
          max={2}
          step={0.1}
          value={temperature}
          onChange={(e) => onChange({ ...values, temperature: parseFloat(e.target.value) })}
          className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-cyan-500"
        />
        <div className="flex justify-between text-[8px] text-slate-600 mt-0.5">
          <span>Precise</span>
          <span>Balanced</span>
          <span>Creative</span>
        </div>
      </div>

      {/* Max tokens */}
      <div>
        <label className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">max_tokens</span>
          <span className="text-slate-300">{maxTokens.toLocaleString()}</span>
        </label>
        <input
          type="number"
          value={maxTokens}
          onChange={(e) => onChange({ ...values, max_tokens: parseInt(e.target.value) || 4096 })}
          min={1}
          max={32000}
          step={256}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
        />
      </div>
    </div>
  );
}
