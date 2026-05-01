'use client';

import { useEffect, useState } from 'react';
import { Box, AlertCircle, Check, Loader2, Plus, X, ShieldOff, Wifi, WifiOff, Power } from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';

interface SandboxConfig {
  effective: { enabled: boolean; allow_network: boolean; allowed_images: string[] };
  env_defaults: { enabled: boolean; allow_network: boolean; allowed_images: string[] };
  tenant_overrides: { enabled: boolean | null; allow_network: boolean | null; allowed_images: string[] | null };
}

export default function SandboxSettingsPage() {
  usePageTitle('Sandbox Settings');
  const [cfg, setCfg] = useState<SandboxConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [newImage, setNewImage] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiFetch<SandboxConfig>('/api/settings/sandbox');
      setCfg(r.data || null);
    } catch (e: any) {
      setErr(e?.message || 'load failed');
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const update = async (body: Partial<SandboxConfig['tenant_overrides']>) => {
    setSaving(true);
    setErr(null);
    try {
      const r = await apiFetch<SandboxConfig>('/api/settings/sandbox', {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      if ((r as any)?.error) throw new Error(String(((r as any).error?.message) || (r as any).error));
      setCfg(r.data || null);
      setSavedAt(Date.now());
      setTimeout(() => setSavedAt(null), 1500);
    } catch (e: any) {
      setErr(e?.message || 'save failed');
    }
    setSaving(false);
  };

  const flipEnabled = () => update({ enabled: !cfg?.effective.enabled });
  const flipNetwork = () => update({ allow_network: !cfg?.effective.allow_network });
  const clearOverride = (key: keyof SandboxConfig['tenant_overrides']) =>
    update({ [key]: null } as any);

  const addImage = async () => {
    const img = newImage.trim();
    if (!img) return;
    const next = Array.from(new Set([...(cfg?.effective.allowed_images || []), img])).sort();
    setNewImage('');
    await update({ allowed_images: next });
  };
  const removeImage = async (img: string) => {
    const next = (cfg?.effective.allowed_images || []).filter((i) => i !== img);
    await update({ allowed_images: next });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-cyan-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Box className="w-6 h-6 text-cyan-400" /> Sandbox
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Controls the <code className="bg-slate-800 px-1 rounded">sandboxed_job</code> tool — one-shot containers (k8s Job in cluster, Docker locally) that agents can launch for binaries, untrusted code, or jobs that shouldn't share the API process.
        </p>
        <p className="text-xs text-slate-500 mt-2">
          Tenant overrides win over the host env defaults set at deploy time. Clear an override to fall back to the env default.
        </p>
      </div>

      {err && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm px-4 py-2.5 flex items-center gap-2">
          <AlertCircle className="w-4 h-4" /> {err}
        </div>
      )}

      {/* Master enable */}
      <div className="rounded-xl bg-slate-900/50 border border-slate-800/50 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Power className={`w-4 h-4 ${cfg?.effective.enabled ? 'text-emerald-400' : 'text-slate-500'}`} />
              Sandbox enabled
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              When OFF, every <code className="bg-slate-800 px-1 rounded">sandboxed_job</code> call returns a friendly "disabled" error before launching anything.
              {' '}Env default: <strong className={cfg?.env_defaults.enabled ? 'text-emerald-300' : 'text-slate-400'}>{String(cfg?.env_defaults.enabled)}</strong>.
              {' '}Tenant override: <strong className="text-cyan-300">{cfg?.tenant_overrides.enabled === null ? 'inherit' : String(cfg?.tenant_overrides.enabled)}</strong>.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <button
              onClick={flipEnabled}
              disabled={saving}
              className={`px-3 py-1.5 rounded-lg border text-xs font-medium ${
                cfg?.effective.enabled
                  ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/20'
                  : 'bg-slate-800 border-slate-600 text-slate-400 hover:bg-slate-700'
              } disabled:opacity-50`}
            >
              {cfg?.effective.enabled ? 'ON' : 'OFF'}
            </button>
            {cfg?.tenant_overrides.enabled !== null && (
              <button onClick={() => clearOverride('enabled')} className="text-[11px] text-slate-500 hover:text-cyan-400 underline">
                clear override
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Network opt-in */}
      <div className="rounded-xl bg-slate-900/50 border border-slate-800/50 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              {cfg?.effective.allow_network
                ? <Wifi className="w-4 h-4 text-amber-400" />
                : <WifiOff className="w-4 h-4 text-emerald-400" />}
              Allow network from sandboxed jobs
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              When OFF (recommended), every container launches with <code className="bg-slate-800 px-1 rounded">--network none</code> regardless of what the agent asks. Turn ON only when you have a job that genuinely needs to call the internet from inside the sandbox.
              {' '}Env default: <strong className={cfg?.env_defaults.allow_network ? 'text-amber-300' : 'text-emerald-300'}>{String(cfg?.env_defaults.allow_network)}</strong>.
              {' '}Tenant override: <strong className="text-cyan-300">{cfg?.tenant_overrides.allow_network === null ? 'inherit' : String(cfg?.tenant_overrides.allow_network)}</strong>.
            </p>
            <p className="text-[11px] text-slate-500 mt-2">
              Two-lock model: even with this ON, individual jobs still default to network-off and must pass <code className="bg-slate-800 px-1 rounded">network: true</code> per call.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <button
              onClick={flipNetwork}
              disabled={saving}
              className={`px-3 py-1.5 rounded-lg border text-xs font-medium ${
                cfg?.effective.allow_network
                  ? 'bg-amber-500/10 border-amber-500/40 text-amber-300 hover:bg-amber-500/20'
                  : 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/20'
              } disabled:opacity-50`}
            >
              {cfg?.effective.allow_network ? 'NETWORK ON' : 'NETWORK OFF'}
            </button>
            {cfg?.tenant_overrides.allow_network !== null && (
              <button onClick={() => clearOverride('allow_network')} className="text-[11px] text-slate-500 hover:text-cyan-400 underline">
                clear override
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Allowed images */}
      <div className="rounded-xl bg-slate-900/50 border border-slate-800/50 p-5">
        <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-2">
          <ShieldOff className="w-4 h-4 text-cyan-400" /> Allowed container images
        </h2>
        <p className="text-xs text-slate-500 mb-3">
          Hard allow-list. Any <code className="bg-slate-800 px-1 rounded">sandboxed_job</code> call referencing an image not on this list is rejected before pull. Keep this small and pinned.
          {cfg?.tenant_overrides.allowed_images === null && (
            <> Currently inheriting the env default (<strong className="text-slate-300">{cfg?.env_defaults.allowed_images.length}</strong> images).</>
          )}
        </p>
        <div className="flex flex-wrap gap-2 mb-3">
          {(cfg?.effective.allowed_images || []).map((img) => (
            <span key={img} className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-slate-800 border border-slate-700 text-xs text-slate-200 font-mono">
              {img}
              <button onClick={() => removeImage(img)} disabled={saving} className="text-slate-500 hover:text-red-400">
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
          {(cfg?.effective.allowed_images || []).length === 0 && (
            <span className="text-xs text-amber-300">No images allow-listed — sandboxed_job will reject every call.</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={newImage}
            onChange={(e) => setNewImage(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addImage()}
            placeholder="alpine:3.20 — image:tag"
            className="flex-1 bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-cyan-500"
          />
          <button
            onClick={addImage}
            disabled={saving || !newImage.trim()}
            className="px-3 py-2 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 text-xs font-medium hover:bg-cyan-500/30 disabled:opacity-50 inline-flex items-center gap-1"
          >
            <Plus className="w-3 h-3" /> Add
          </button>
          {cfg?.tenant_overrides.allowed_images !== null && (
            <button onClick={() => clearOverride('allowed_images')} className="text-[11px] text-slate-500 hover:text-cyan-400 underline whitespace-nowrap">
              clear override
            </button>
          )}
        </div>
      </div>

      {savedAt && (
        <div className="text-xs text-emerald-400 inline-flex items-center gap-1">
          <Check className="w-3 h-3" /> Saved
        </div>
      )}
    </div>
  );
}
