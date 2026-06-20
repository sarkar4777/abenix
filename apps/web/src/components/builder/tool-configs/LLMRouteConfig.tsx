'use client';

/**
 * LLMRouteConfig — Specialized config for the `llm_route` tool.
 *
 * Shows: classification prompt textarea, branches list editor,
 * context textarea, model dropdown.
 */

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';

import ModelPicker from '@/components/ModelPicker';
import { ModelStatusBanner } from '@/components/ModelStatusBanner';

interface LLMRouteConfigProps {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export default function LLMRouteConfig({ values, onChange }: LLMRouteConfigProps) {
  const [newBranch, setNewBranch] = useState('');
  const branches = Array.isArray(values.branches) ? values.branches as string[] : [];
  const model = (values.model as string) || 'claude-sonnet-4-5-20250929';

  const addBranch = () => {
    const b = newBranch.trim();
    if (b && !branches.includes(b)) {
      onChange({ ...values, branches: [...branches, b] });
      setNewBranch('');
    }
  };

  return (
    <div className="space-y-4">
      {/* Classification Prompt */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">classification_prompt</span>
          <span className="text-red-400 text-[8px]">required</span>
        </label>
        <textarea
          value={(values.classification_prompt as string) || ''}
          onChange={(e) => onChange({ ...values, classification_prompt: e.target.value })}
          placeholder="Classify the following input into one of these categories: billing, technical, general. Consider the tone and content."
          rows={4}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500"
        />
      </div>

      {/* Branches */}
      <div>
        <label className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-slate-500">branches</span>
            <span className="text-red-400 text-[8px]">required</span>
          </div>
          <span className="text-slate-600">{branches.length} branches</span>
        </label>
        {branches.length > 0 && (
          <div className="space-y-1 mb-2">
            {branches.map((branch, i) => (
              <div key={i} className="flex items-center gap-2 bg-slate-800/30 border border-slate-700/30 rounded px-2.5 py-1.5">
                <div className="w-5 h-5 rounded bg-cyan-500/10 flex items-center justify-center shrink-0">
                  <span className="text-[9px] text-cyan-400 font-bold">{i + 1}</span>
                </div>
                <span className="text-[10px] text-slate-300 font-mono flex-1">{branch}</span>
                <button
                  onClick={() => onChange({ ...values, branches: branches.filter((_, j) => j !== i) })}
                  className="p-0.5 text-slate-500 hover:text-red-400"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-1.5">
          <input
            type="text"
            value={newBranch}
            onChange={(e) => setNewBranch(e.target.value)}
            placeholder="Branch name (e.g. billing, technical)"
            className="flex-1 px-3 py-1.5 bg-slate-900/50 border border-slate-700 rounded text-[10px] text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
            onKeyDown={(e) => e.key === 'Enter' && addBranch()}
          />
          <button
            onClick={addBranch}
            disabled={!newBranch.trim()}
            className="px-2 py-1.5 bg-cyan-500/10 text-cyan-400 rounded hover:bg-cyan-500/20 disabled:opacity-30 transition-colors"
          >
            <Plus className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Context */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">context</span>
          <span className="text-slate-600 text-[8px]">optional</span>
        </label>
        <textarea
          value={(values.context as string) || ''}
          onChange={(e) => onChange({ ...values, context: e.target.value })}
          placeholder="Additional context for the classifier. Use {{node_id.field}} for pipeline data."
          rows={3}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 resize-none focus:outline-none focus:border-cyan-500"
        />
      </div>

      {/* Model */}
      <div>
        <ModelPicker
          value={model}
          onChange={(v) => onChange({ ...values, model: v })}
          label="model"
        />
        <ModelStatusBanner model={model} compact />
      </div>

      {/* Output hint */}
      <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-2.5">
        <p className="text-[9px] text-cyan-400 font-medium mb-1">Output Format</p>
        <p className="text-[8px] text-slate-400">
          Returns <code className="text-cyan-400/80">{'{"route": "branch_name", "confidence": 0.95}'}</code>. Use with a Switch node for conditional pipeline branching.
        </p>
      </div>
    </div>
  );
}
