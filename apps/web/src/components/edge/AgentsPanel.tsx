'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Copy, Cpu, Loader2, Package, Send, Terminal, X } from 'lucide-react';
import { fetchAllAgents } from '@/lib/fetch-all-agents';
import { useEscapeToClose } from '@/hooks/useEscapeToClose';
import { toastError, toastSuccess } from '@/stores/toastStore';
import { edgeCall, type Gateway } from './model';

type AgentRow = { id: string; name: string; slug: string; edge_compatible: boolean };

type RuntimeVariant = {
  name: 'python' | 'rust' | 'c';
  label: string;
  image: string;
  size_mb: number;
  helm_chart: string;
  helm_install: string;
  docker_run: string;
  targets: string[];
  deps: string[];
  use_when: string;
};

const TONES: Record<string, { card: string; chip: string; head: string }> = {
  python: { card: 'bg-teal-500/5 border-teal-500/30', chip: 'bg-teal-500/15 text-teal-300 border-teal-500/30', head: 'text-teal-300' },
  rust: { card: 'bg-orange-500/5 border-orange-500/30', chip: 'bg-orange-500/15 text-orange-300 border-orange-500/30', head: 'text-orange-300' },
  c: { card: 'bg-slate-500/5 border-slate-500/40', chip: 'bg-slate-700/40 text-slate-200 border-slate-600/40', head: 'text-slate-200' },
};

export function DeployModal({ gateway, onClose, onDeployed }: { gateway: Gateway; onClose: () => void; onDeployed: (agentId: string) => void }) {
  const [agents, setAgents] = useState<AgentRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [deploying, setDeploying] = useState<string | null>(null);
  useEscapeToClose(true, onClose);

  useEffect(() => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') || localStorage.getItem('token') : null;
    if (!token) { setErr('You are signed out. Sign in again to deploy agents.'); return; }
    fetchAllAgents({ token }).then((res) => {
      const raw: Array<Record<string, unknown>> = Array.isArray(res.agents) ? (res.agents as Array<Record<string, unknown>>) : [];
      setAgents(raw.map((a) => ({
        id: String(a.id),
        name: String(a.name || ''),
        slug: String(a.slug || ''),
        edge_compatible: !!((a.model_config as Record<string, unknown> | undefined)?.edge_compatible),
      })).filter((a) => a.edge_compatible));
    }).catch(() => setErr('Could not load your agents. Try again.'));
  }, []);

  const deploy = async (agentId: string) => {
    setDeploying(agentId);
    const r = await edgeCall<{ bundle_digest: string }>(`/api/edge/gateways/${gateway.id}/deploy`, 'POST', { agent_id: agentId });
    setDeploying(null);
    if (r.error) { toastError('Deploy failed', r.error); return; }
    toastSuccess('Agent sent', `Signed bundle ${(r.data?.bundle_digest || '').slice(0, 12)} is on its way to ${gateway.name}.`);
    onDeployed(agentId);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-label={`Deploy to ${gateway.name}`}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-lg space-y-4 rounded-xl border border-slate-700 bg-slate-900 p-5">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-white">Deploy to {gateway.name}</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        {err && <p role="alert" className="text-sm text-rose-300">{err}</p>}
        {!agents && !err && <p className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Loading your agents</p>}
        {agents && agents.length === 0 && (
          <p className="rounded border border-slate-700/40 bg-slate-800/40 p-4 text-sm text-slate-400">No edge ready agents yet. Open an agent in the builder, go to the Advanced tab and turn on Edge compatible.</p>
        )}
        {agents && agents.length > 0 && (
          <ul className="max-h-[60vh] space-y-2 overflow-y-auto">
            {agents.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2 rounded-lg bg-slate-800/40 px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm text-white">{a.name}</p>
                  <p className="truncate font-mono text-[11px] text-slate-500">{a.slug}</p>
                </div>
                <button type="button" disabled={deploying === a.id} onClick={() => deploy(a.id)} className="flex items-center gap-1.5 rounded border border-cyan-500/30 bg-cyan-500/15 px-3 py-1 text-xs text-cyan-300 hover:bg-cyan-500/25 disabled:opacity-50">
                  {deploying === a.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />} Deploy
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function AgentsPanel({ canManage }: { canManage: boolean }) {
  const [variants, setVariants] = useState<RuntimeVariant[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [tokenModal, setTokenModal] = useState<{ token: string; pubkey: string; warning: string; name: string } | null>(null);
  const [minting, setMinting] = useState(false);
  const closeTokenModal = useCallback(() => setTokenModal(null), []);
  useEscapeToClose(!!tokenModal, closeTokenModal);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    edgeCall<{ variants: RuntimeVariant[] }>('/api/edge/runtime/download').then((r) => {
      if (r.error) setLoadErr(r.error);
      else setVariants(r.data?.variants || []);
    });
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, []);

  const copy = (text: string, key: string) => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      timer.current = setTimeout(() => setCopied((k) => (k === key ? null : k)), 1200);
    }).catch(() => {});
  };

  const mint = async () => {
    setMinting(true);
    const keyName = `edge gateway ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`;
    const r = await edgeCall<{ platform_token: string; signing_pubkey_pem: string; warning: string }>('/api/edge/tokens/mint', 'POST', { name: keyName });
    setMinting(false);
    if (r.error || !r.data?.platform_token) { toastError('Could not mint an edge token', r.error || 'Try again.'); return; }
    setTokenModal({ token: r.data.platform_token, pubkey: r.data.signing_pubkey_pem || '', warning: r.data.warning || '', name: keyName });
  };

  const sorted = useMemo(() => variants, [variants]);

  return (
    <section className="space-y-4" aria-labelledby="edge-agents-title">
      <div>
        <h2 id="edge-agents-title" className="flex items-center gap-2 text-lg font-semibold text-white"><Package className="h-4 w-4 text-cyan-400" /> Run agents on gateways</h2>
        <p className="mt-1 text-xs text-slate-400">
          Agents marked Edge compatible can run on a gateway, next to the machines they watch, and keep answering when the site is offline. A collecting gateway can do this too, tick Also run agents when you add it. For a box that only runs agents, pick a runtime below.
        </p>
      </div>

      {canManage && (
        <div className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-cyan-700/40 bg-cyan-900/10 p-4 sm:flex-nowrap">
          <div className="min-w-0 flex-1">
            <div className="mb-1 text-sm font-semibold text-cyan-200">Gateway token and signing key, for the agents-only runtimes</div>
            <p className="text-xs text-slate-300">The runtime signs in with the token and checks every bundle against the platform&apos;s signing key. The token is shown once and saved as an API key you can revoke under Settings, API keys.</p>
          </div>
          <button type="button" onClick={mint} data-testid="edge-mint" disabled={minting} className="whitespace-nowrap rounded-md bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50">
            {minting ? 'Minting…' : 'Mint edge token + pubkey'}
          </button>
        </div>
      )}

      {tokenModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setTokenModal(null)} role="dialog" aria-modal="true" aria-label="Edge token and signing key">
          <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-cyan-700/50 bg-slate-900 p-5" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-cyan-200">Edge token and signing key</h3>
              <button type="button" onClick={() => setTokenModal(null)} aria-label="Close" className="text-sm text-slate-400 hover:text-white">Close</button>
            </div>
            <p className="mb-3 text-xs text-slate-300" data-testid="edge-token-key-name">
              Saved as the API key <strong>{tokenModal.name}</strong>. Revoke it under <a href="/settings/api-keys" className="text-cyan-300 underline">Settings, API keys</a> when the gateway is retired.
            </p>
            <div className="mb-3 rounded border border-amber-700/40 bg-amber-900/30 p-2.5 text-[12px] text-amber-200">{tokenModal.warning}</div>
            <div className="space-y-3 text-[12.5px]">
              <div>
                <div className="mb-1 text-slate-400">PLATFORM_TOKEN</div>
                <div className="flex items-center gap-2">
                  <code data-testid="edge-token-value" className="block min-w-0 flex-1 break-all rounded border border-slate-800 bg-slate-950 p-2 font-mono text-emerald-300">{tokenModal.token}</code>
                  <button type="button" onClick={() => copy(tokenModal.token, 'tok')} className="rounded bg-slate-800 px-2 py-1 text-xs hover:bg-slate-700">{copied === 'tok' ? 'Copied' : 'Copy'}</button>
                </div>
              </div>
              <div>
                <div className="mb-1 text-slate-400">SIGNING_PUBKEY (PEM)</div>
                <div className="flex items-start gap-2">
                  <pre data-testid="edge-pubkey" className="block max-h-40 min-w-0 flex-1 overflow-auto rounded border border-slate-800 bg-slate-950 p-2 font-mono text-[11px] text-cyan-300">{tokenModal.pubkey || 'No signing key yet. Set EDGE_SIGNING_KEY_PEM on the API first.'}</pre>
                  {tokenModal.pubkey && <button type="button" onClick={() => copy(tokenModal.pubkey, 'pub')} className="rounded bg-slate-800 px-2 py-1 text-xs hover:bg-slate-700">{copied === 'pub' ? 'Copied' : 'Copy'}</button>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div data-testid="edge-runtime-variants">
        {loadErr && <p role="alert" className="text-sm text-rose-300">{loadErr}</p>}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {sorted.map((v) => {
            const tone = TONES[v.name] || TONES.python;
            return (
              <div key={v.name} className={`min-w-0 space-y-3 rounded-lg border p-4 ${tone.card}`} data-testid={`runtime-card-${v.name}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className={`text-sm font-semibold ${tone.head}`}>{v.label}</h3>
                    <p className="mt-0.5 break-all font-mono text-[11px] text-slate-400">{v.image}</p>
                  </div>
                  <span className={`shrink-0 rounded border px-2 py-0.5 text-[10px] uppercase tracking-wider ${tone.chip}`}>{v.size_mb} MB</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {v.targets.map((t) => <span key={t} className="rounded border border-slate-700/60 bg-slate-800/60 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">{t}</span>)}
                </div>
                <p className="text-[11px] leading-relaxed text-slate-300"><span className="text-[10px] uppercase tracking-wider text-slate-500">Use when:&nbsp;</span>{v.use_when}</p>
                <div className="grid grid-cols-2 gap-2 pt-1">
                  <button type="button" onClick={() => copy(v.helm_install, `helm-${v.name}`)} className={`flex items-center justify-center gap-1.5 rounded border px-2 py-1.5 text-[11px] hover:opacity-90 ${tone.chip}`} data-testid={`copy-helm-${v.name}`}>
                    {copied === `helm-${v.name}` ? <CheckCircle2 className="h-3 w-3" /> : <Copy className="h-3 w-3" />}{copied === `helm-${v.name}` ? 'Copied' : 'Helm install'}
                  </button>
                  <button type="button" onClick={() => copy(`docker pull ${v.image}`, `docker-${v.name}`)} className={`flex items-center justify-center gap-1.5 rounded border px-2 py-1.5 text-[11px] hover:opacity-90 ${tone.chip}`} data-testid={`copy-docker-${v.name}`}>
                    {copied === `docker-${v.name}` ? <CheckCircle2 className="h-3 w-3" /> : <Terminal className="h-3 w-3" />}{copied === `docker-${v.name}` ? 'Copied' : 'Docker pull'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <p className="flex items-start gap-1.5 text-[11px] text-slate-500"><Cpu className="mt-0.5 h-3 w-3 shrink-0" /> To make an agent edge ready, open it in the builder, Advanced tab, and turn on Edge compatible.</p>
    </section>
  );
}
