'use client';

// Compact slide toggle for "Demo / Live" mode on each tab.
// Off by default so demos keep working without any wiring.

import { Radio } from 'lucide-react';

interface Props {
  value: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  hint?: string;
  // True when the last trigger toggle came back as 404 from abenix — i.e.
  // the trigger registry isn't wired on the platform. We still let the user
  // flip the switch (the UI may have a useful local-only loop) but render
  // an amber "demo" badge so they don't think a real MQTT subscription
  // started.
  demoMode?: boolean;
}

export default function LiveModeToggle({ value, onChange, disabled, hint, demoMode }: Props) {
  const showDemo = Boolean(value && demoMode);
  return (
    <div className="inline-flex items-center gap-2">
      <label
        className={`inline-flex items-center gap-2 select-none cursor-pointer ${
          disabled ? 'opacity-50 cursor-not-allowed' : ''
        }`}
        title={hint}
      >
        <Radio
          className={`w-3.5 h-3.5 ${
            showDemo ? 'text-amber-400' : value ? 'text-emerald-400' : 'text-slate-500'
          }`}
        />
        <span className="text-xs text-slate-400">Live mode</span>
        <span
          onClick={() => !disabled && onChange(!value)}
          className={`relative inline-block w-9 h-5 rounded-full transition-colors ${
            showDemo ? 'bg-amber-500/70' : value ? 'bg-emerald-500/70' : 'bg-slate-700'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
              value ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </span>
      </label>
      {showDemo && (
        <span
          className="text-[10px] px-1.5 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-200 whitespace-nowrap"
          title="abenix-api has no trigger registry yet — UI runs in demo mode"
        >
          demo (trigger not wired)
        </span>
      )}
    </div>
  );
}
