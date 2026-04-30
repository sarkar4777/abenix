'use client';


import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Boxes, CheckCircle2, AlertCircle, RefreshCw, ExternalLink,
  FileCode, Copy, ChevronDown,
} from 'lucide-react';
import { apiFetch, API_URL } from '@/lib/api-client';


interface CodeAsset {
  id: string;
  name: string;
  description?: string;
  detected_language?: string;
  detected_version?: string;
  suggested_image?: string;
  detected_entrypoint?: string;
  status: string;
  input_schema?: Record<string, unknown> | null;
  output_schema?: Record<string, unknown> | null;
}

interface Props {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

const LANG_EMOJI: Record<string, string> = {
  python: '🐍', node: '🟢', javascript: '🟢', typescript: '🔷',
  go: '🐹', rust: '🦀', ruby: '💎', java: '☕', perl: '🐪',
};

export default function CodeAssetConfig({ values, onChange }: Props) {
  const [assets, setAssets] = useState<CodeAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const assetId = (values.code_asset_id as string) || '';
  const selected = assets.find((a) => a.id === assetId) || null;

  const load = async () => {
    setLoading(true); setErr(null);
    try {
      const r = await apiFetch<CodeAsset[]>(`${API_URL}/api/code-assets`);
      const list = Array.isArray(r.data) ? r.data : [];
      // Filter to ready assets only — user can see un-ready ones in the dashboard
      setAssets(list);
    } catch (e: any) {
      setErr(e?.message || 'Failed to load code assets');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const ready = useMemo(() => assets.filter((a) => a.status === 'ready'), [assets]);

  // When the user picks an asset, also seed the `timeout_seconds` default
  const pick = (id: string) => {
    const next: Record<string, unknown> = { ...values, code_asset_id: id };
    if (!('timeout_seconds' in values)) next.timeout_seconds = 120;
    onChange(next);
  };

  // Empty state — no assets at all, or none ready
  if (!loading && ready.length === 0) {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-3">
        <div className="flex items-center gap-2 text-amber-300">
          <AlertCircle className="w-4 h-4" />
          <p className="text-sm font-semibold">You haven't uploaded any code yet</p>
        </div>
        <p className="text-xs text-slate-300 leading-relaxed">
          The <code>code_asset</code> tool runs a previously-uploaded zip in an
          isolated Kubernetes Pod. Upload your code (Python, Node, Go, Rust, Ruby,
          Java, Perl) on the Code Runner page first, then come back — the asset
          will show up in the dropdown with its detected schema.
        </p>
        <Link
          href="/code-runner"
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-cyan-500 text-white text-xs font-semibold hover:bg-cyan-400"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          Go to Code Runner
        </Link>
        {assets.length > 0 && (
          <p className="text-[11px] text-slate-500 pt-2 border-t border-slate-700/40">
            You have {assets.length} asset(s) in non-ready states — check the
            Code Runner page for analysis errors.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="code-asset-config">
      {/* ───── Asset picker ───── */}
      <div>
        <label className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 flex items-center justify-between">
          <span className="flex items-center gap-1.5">
            <Boxes className="w-3 h-3" /> Code asset to run
          </span>
          <button
            onClick={load}
            className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-cyan-400"
            title="Reload"
          >
            <RefreshCw className="w-3 h-3" /> refresh
          </button>
        </label>
        <div className="relative">
          <select
            value={assetId}
            onChange={(e) => pick(e.target.value)}
            className="w-full appearance-none bg-slate-900/60 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
            data-testid="code-asset-select"
          >
            <option value="">— choose an asset —</option>
            {ready.map((a) => (
              <option key={a.id} value={a.id}>
                {LANG_EMOJI[a.detected_language || ''] || '📦'}  {a.name}
                {a.detected_language ? `  ·  ${a.detected_language}` : ''}
                {a.detected_version ? ` ${a.detected_version}` : ''}
              </option>
            ))}
          </select>
          <ChevronDown className="w-4 h-4 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
        <p className="text-[10px] text-slate-500 mt-1">
          UUID is set for you — the LLM never has to think about it.
        </p>
      </div>

      {/* ───── Selected asset details ───── */}
      {selected && (
        <div className="rounded-lg border border-slate-700/50 bg-slate-900/30 p-3 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-white flex items-center gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                {selected.name}
              </p>
              {selected.description && (
                <p className="text-[11px] text-slate-400 mt-0.5">{selected.description}</p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <p className="text-[9px] uppercase tracking-wider text-slate-500">Language</p>
              <p className="text-slate-300 font-mono">
                {selected.detected_language || 'unknown'}
                {selected.detected_version ? ` ${selected.detected_version}` : ''}
              </p>
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-wider text-slate-500">Base image</p>
              <p className="text-slate-300 font-mono truncate" title={selected.suggested_image}>
                {selected.suggested_image || '—'}
              </p>
            </div>
            {selected.detected_entrypoint && (
              <div className="col-span-2">
                <p className="text-[9px] uppercase tracking-wider text-slate-500">Entrypoint</p>
                <p className="text-slate-300 font-mono truncate">{selected.detected_entrypoint}</p>
              </div>
            )}
          </div>

          {/* input_schema preview */}
          {selected.input_schema ? (
            <div className="border-t border-slate-700/40 pt-3">
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] uppercase tracking-wider text-emerald-400 flex items-center gap-1">
                  <FileCode className="w-3 h-3" /> Input contract (abenix.yaml / examples / README)
                </p>
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(JSON.stringify(selected.input_schema, null, 2));
                  }}
                  className="text-[10px] text-slate-400 hover:text-cyan-400 flex items-center gap-1"
                  title="Copy to clipboard"
                >
                  <Copy className="w-3 h-3" /> copy
                </button>
              </div>
              <pre className="text-[10px] text-slate-300 bg-slate-950/50 rounded p-2 overflow-x-auto max-h-40">
                {JSON.stringify(selected.input_schema, null, 2)}
              </pre>
            </div>
          ) : (
            <div className="border-t border-slate-700/40 pt-3">
              <p className="text-[11px] text-amber-400 flex items-center gap-1">
                <AlertCircle className="w-3 h-3" /> No input_schema declared
              </p>
              <p className="text-[10px] text-slate-500 mt-1 leading-relaxed">
                Add an <code>abenix.yaml</code> at the root of your zip, or
                an <code>examples/input.json</code>, or a README with{' '}
                <code>```json input</code> fenced blocks — the platform will
                pick them up on your next upload. Until then, the LLM will have
                to guess the shape.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ───── Timeout ───── */}
      <div>
        <label className="text-[10px] uppercase tracking-wider text-slate-500 mb-1 block">
          Timeout (seconds)
        </label>
        <input
          type="number"
          min={5}
          max={1800}
          value={(values.timeout_seconds as number) ?? 120}
          onChange={(e) => onChange({ ...values, timeout_seconds: Number(e.target.value) })}
          className="w-32 bg-slate-900/60 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white"
          data-testid="code-asset-timeout"
        />
        <p className="text-[10px] text-slate-500 mt-1">
          Kill-after for the pod. Default 120s, max 1800s.
        </p>
      </div>

      {err && (
        <div className="text-[11px] text-rose-400 bg-rose-500/10 border border-rose-500/30 rounded-lg p-2">
          {err}
        </div>
      )}
    </div>
  );
}
