'use client';

// Compact slide toggle for "Demo / Live" mode on each tab.
// Off by default so demos keep working without any wiring.

import { Radio } from 'lucide-react';

interface Props {
  value: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  hint?: string;
}

export default function LiveModeToggle({ value, onChange, disabled, hint }: Props) {
  return (
    <label
      className={`inline-flex items-center gap-2 select-none cursor-pointer ${
        disabled ? 'opacity-50 cursor-not-allowed' : ''
      }`}
      title={hint}
    >
      <Radio className={`w-3.5 h-3.5 ${value ? 'text-emerald-400' : 'text-slate-500'}`} />
      <span className="text-xs text-slate-400">Live mode</span>
      <span
        onClick={() => !disabled && onChange(!value)}
        className={`relative inline-block w-9 h-5 rounded-full transition-colors ${
          value ? 'bg-emerald-500/70' : 'bg-slate-700'
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            value ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </span>
    </label>
  );
}
