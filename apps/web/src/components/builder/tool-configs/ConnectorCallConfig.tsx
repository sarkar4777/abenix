'use client';

import { useEffect, useMemo, useState } from 'react';
import { Plug, Loader2, AlertCircle, ExternalLink } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface ConnectorOption {
  id: string;
  name: string;
  kind: string;
  preset_key: string | null;
  base_url: string;
  operations: string[];
}

interface ConnectorCallConfigProps {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export default function ConnectorCallConfig({ values, onChange }: ConnectorCallConfigProps) {
  const [connectors, setConnectors] = useState<ConnectorOption[]>([]);
  const [loading, setLoading] = useState(true);
  const selectedId = (values.connector_id as string) || '';
  const operation = (values.operation as string) || '';

  useEffect(() => {
    (async () => {
      const res = await apiFetch<ConnectorOption[]>('/api/connectors', { silent: true });
      setConnectors(res.data || []);
      setLoading(false);
    })();
  }, []);

  const selected = useMemo(
    () => connectors.find(c => c.id === selectedId) || null,
    [connectors, selectedId]
  );

  return (
    <div className="space-y-4">
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <Plug className="w-3 h-3 text-cyan-400" />
          <span className="font-mono text-slate-500">connector_id</span>
          <span className="text-red-400 text-[8px]">required</span>
        </label>
        <select
          value={selectedId}
          onChange={(e) => onChange({ ...values, connector_id: e.target.value, operation: '' })}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500"
        >
          <option value="">Select a connector...</option>
          {connectors.map(c => (
            <option key={c.id} value={c.id}>{c.name} ({c.kind})</option>
          ))}
        </select>
        {!loading && connectors.length === 0 && (
          <p className="mt-1 text-[10px] text-amber-300 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            No connectors configured. Add one at <a href="/admin/connectors" className="underline ml-1">Admin → Connectors</a>.
          </p>
        )}
        {loading && <Loader2 className="w-3 h-3 animate-spin text-cyan-400 mt-1" />}
      </div>

      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">operation</span>
          <span className="text-red-400 text-[8px]">required</span>
        </label>
        <select
          value={operation}
          onChange={(e) => onChange({ ...values, operation: e.target.value })}
          disabled={!selected}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-cyan-500 disabled:opacity-50"
        >
          <option value="">{selected ? 'Select operation...' : 'Pick a connector first'}</option>
          {selected?.operations.map(op => (
            <option key={op} value={op}>{op}</option>
          ))}
        </select>
        {selected && (
          <p className="mt-1 text-[10px] text-slate-500">
            {selected.preset_key ? `Preset: ${selected.preset_key}` : 'Custom connector'} —
            <a href={`/admin/connectors`} className="ml-1 underline inline-flex items-center gap-0.5">
              edit <ExternalLink className="w-2.5 h-2.5" />
            </a>
          </p>
        )}
      </div>

      <div>
        <label className="text-[10px] text-slate-400 mb-1 block">
          <span className="font-mono text-slate-500">parameters</span>
          <span className="ml-2 text-slate-500">(supplied at runtime)</span>
        </label>
        <p className="text-[10px] text-slate-500 leading-relaxed bg-slate-900/40 border border-slate-700/50 rounded-lg p-2.5">
          Operation parameters are filled in by the calling step (or the LLM) at runtime. The connector preset
          decides which parameter names are valid for each operation.
        </p>
      </div>
    </div>
  );
}
