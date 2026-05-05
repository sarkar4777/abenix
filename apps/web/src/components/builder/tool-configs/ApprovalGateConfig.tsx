'use client';

import { ShieldCheck } from 'lucide-react';

interface ApprovalGateConfigProps {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export default function ApprovalGateConfig({ values, onChange }: ApprovalGateConfigProps) {
  const required = Number(values.required_signoffs) || 1;
  const expires = Number(values.expires_seconds) || 1800;
  const title = (values.title as string) || '';

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-2.5">
        <ShieldCheck className="w-4 h-4 text-cyan-400" />
        <p className="text-[11px] text-slate-300">
          Pauses the agent until N humans sign off. The payload is the exact thing they're approving.
        </p>
      </div>

      <div>
        <label className="text-[10px] text-slate-400 mb-1 block">
          <span className="font-mono text-slate-500">title</span>
          <span className="ml-2 text-slate-500">(optional, shown on the approval card)</span>
        </label>
        <input
          value={title}
          onChange={e => onChange({ ...values, title: e.target.value })}
          placeholder="Reset PLC alarms on Pump 4"
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[10px] text-slate-400 mb-1 block">
            <span className="font-mono text-slate-500">required_signoffs</span>
          </label>
          <input
            type="number"
            min={1}
            max={10}
            value={required}
            onChange={e => onChange({ ...values, required_signoffs: Number(e.target.value) || 1 })}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500"
          />
        </div>
        <div>
          <label className="text-[10px] text-slate-400 mb-1 block">
            <span className="font-mono text-slate-500">expires_seconds</span>
          </label>
          <input
            type="number"
            min={30}
            max={604800}
            value={expires}
            onChange={e => onChange({ ...values, expires_seconds: Number(e.target.value) || 1800 })}
            className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500"
          />
        </div>
      </div>

      <div>
        <p className="text-[10px] text-slate-500 leading-relaxed bg-slate-900/40 border border-slate-700/50 rounded-lg p-2.5">
          The payload is built by upstream pipeline nodes or by the LLM at runtime. After approval, the tool
          returns <code className="text-cyan-300">{`{status, signoffs}`}</code>. Branch on
          <code className="text-cyan-300"> status </code> to either continue or abort the flow.
        </p>
      </div>
    </div>
  );
}
