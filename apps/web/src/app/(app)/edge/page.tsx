'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Cpu, Loader2, RefreshCw, Send, X, AlertTriangle, CheckCircle2, Clock, Wifi,
  Copy, ChevronDown, ChevronRight, Package, Terminal, Info,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token') || localStorage.getItem('token');
}

type DeployedAgent = {
  slug: string;
  agent_id: string;
  digest: string;
  deployed_at: string;
};

type Gateway = {
  id: string;
  gateway_id: string;
  name: string;
  endpoint_url: string | null;
  status: string;
  deployed_agents: DeployedAgent[];
  registered_at: string | null;
  last_seen_at: string | null;
};

type AgentRow = {
  id: string;
  name: string;
  slug: string;
  edge_compatible: boolean;
};

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

const VARIANT_TONES: Record<string, { card: string; chip: string; head: string }> = {
  python: {
    card: 'bg-teal-500/5 border-teal-500/30',
    chip: 'bg-teal-500/15 text-teal-300 border-teal-500/30',
    head: 'text-teal-300',
  },
  rust: {
    card: 'bg-orange-500/5 border-orange-500/30',
    chip: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
    head: 'text-orange-300',
  },
  c: {
    card: 'bg-slate-500/5 border-slate-500/40',
    chip: 'bg-slate-700/40 text-slate-200 border-slate-600/40',
    head: 'text-slate-200',
  },
};

function timeAgo(iso: string | null): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const diff = Math.floor((Date.now() - t) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function StatusDot({ status, lastSeen }: { status: string; lastSeen: string | null }) {
  const recent = lastSeen ? Date.now() - Date.parse(lastSeen) < 5 * 60_000 : false;
  const ok = status === 'online' && recent;
  return (
    <span
      title={ok ? 'online' : 'stale'}
      className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-amber-400'}`}
    />
  );
}

export default function EdgePage() {
  const [gateways, setGateways] = useState<Gateway[]>([]);
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [variants, setVariants] = useState<RuntimeVariant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalGatewayId, setModalGatewayId] = useState<string | null>(null);
  const [deploying, setDeploying] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [howOpen, setHowOpen] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [tokenModal, setTokenModal] = useState<{ token: string; pubkey: string; warning: string } | null>(null);
  const [minting, setMinting] = useState(false);

  const mintToken = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setMinting(true);
    try {
      const r = await fetch(`${API_URL}/api/edge/tokens/mint`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: `edge-${new Date().toISOString().slice(0,10)}` }),
      });
      const j = await r.json();
      const d = j?.data;
      if (!r.ok || !d?.platform_token) { setError(j?.error?.message || 'Failed to mint token'); return; }
      setTokenModal({ token: d.platform_token, pubkey: d.signing_pubkey_pem || '', warning: d.warning || '' });
    } finally {
      setMinting(false);
    }
  }, []);

  const copyToClipboard = useCallback((text: string, key: string) => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied((k) => (k === key ? null : k)), 1200);
    }).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) { setLoading(false); setError('Not signed in'); return; }
    setError(null);
    try {
      const [gr, ar, vr] = await Promise.all([
        fetch(`${API_URL}/api/edge/gateways`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/api/agents?limit=500`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/api/edge/runtime/download`),
      ]);
      const gj = await gr.json();
      const aj = await ar.json();
      const vj = await vr.json();
      setGateways(gj?.data?.gateways || []);
      const rawAgents: any[] = aj?.data?.agents || aj?.data?.items || aj?.data || [];
      setAgents(
        rawAgents.map((a: any) => ({
          id: a.id,
          name: a.name,
          slug: a.slug,
          edge_compatible: !!(a.model_config?.edge_compatible),
        }))
      );
      setVariants(vj?.data?.variants || []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const edgeAgents = useMemo(() => agents.filter(a => a.edge_compatible), [agents]);
  const modalGateway = useMemo(
    () => gateways.find(g => g.id === modalGatewayId) || null,
    [modalGatewayId, gateways],
  );

  const deploy = async (gatewayPk: string, agentId: string) => {
    setDeploying(agentId);
    try {
      const token = getToken();
      const r = await fetch(`${API_URL}/api/edge/gateways/${gatewayPk}/deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ agent_id: agentId }),
      });
      const j = await r.json();
      if (j?.error) throw new Error(j.error.message || 'Deploy failed');
      setToast(`Deployed (digest ${(j.data?.bundle_digest || '').slice(0, 12)}…)`);
      setModalGatewayId(null);
      await load();
    } catch (e: any) {
      setToast(`Failed: ${e?.message || e}`);
    }
    setDeploying(null);
    setTimeout(() => setToast(null), 3500);
  };

  if (loading) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-cyan-400" />
      </div>
    );
  }

  return (
    <div className="p-6" data-testid="edge-page">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <Cpu className="w-6 h-6 text-cyan-400" /> Edge Gateways
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Remote pods that pull <code className="text-cyan-300">.agent</code> bundles. Mark an agent as
              edge-compatible in the builder Advanced tab to deploy here.
            </p>
          </div>
          <button
            onClick={load}
            className="px-3 py-1.5 text-xs text-slate-300 bg-slate-800/60 border border-slate-700 rounded-lg flex items-center gap-1.5 hover:bg-slate-700/60"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </header>

        {error && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-rose-200 text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> {error}
          </div>
        )}

        <section className="rounded-lg border border-cyan-700/40 bg-cyan-900/10 p-4 flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-cyan-200 mb-1">Step 1 — Mint a platform token + grab the signing pubkey</div>
            <p className="text-xs text-slate-300">
              Every gateway needs a platform token (so it can <code className="bg-slate-800 px-1 rounded">/register</code> + receive bundles) and the platform&apos;s RSA-PSS signing pubkey (so it verifies bundle signatures). Click below — token is shown once.
            </p>
          </div>
          <button
            onClick={mintToken}
            disabled={minting}
            className="px-3 py-1.5 rounded-md bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm font-medium whitespace-nowrap"
          >
            {minting ? 'Minting…' : 'Mint edge token + pubkey'}
          </button>
        </section>

        <details className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4">
          <summary className="text-sm font-semibold text-slate-200 cursor-pointer">
            Step 0 — What software do I need on the gateway box?
          </summary>
          <div className="mt-3 space-y-3 text-xs text-slate-300">
            <p>Three tiers. Pick by hardware. All three end up registered identically.</p>
            <table className="w-full text-[11.5px] border border-slate-700/40 rounded">
              <thead className="bg-slate-900/60 text-slate-400 uppercase">
                <tr>
                  <th className="text-left px-2 py-1">Tier</th>
                  <th className="text-left px-2 py-1">When</th>
                  <th className="text-left px-2 py-1">Install on the box</th>
                  <th className="text-left px-2 py-1">RAM</th>
                  <th className="text-left px-2 py-1">Disk</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-slate-800">
                  <td className="px-2 py-1 text-cyan-300">K8s (helm)</td>
                  <td className="px-2 py-1">Plant has k3s/k0s fleet, log aggregation</td>
                  <td className="px-2 py-1 font-mono">k3s + helm</td>
                  <td className="px-2 py-1">1 GB</td>
                  <td className="px-2 py-1">4 GB</td>
                </tr>
                <tr className="border-t border-slate-800">
                  <td className="px-2 py-1 text-orange-300">Docker</td>
                  <td className="px-2 py-1">Single industrial PC, NUC, Jetson</td>
                  <td className="px-2 py-1 font-mono">docker 20.10+</td>
                  <td className="px-2 py-1">512 MB</td>
                  <td className="px-2 py-1">1 GB</td>
                </tr>
                <tr className="border-t border-slate-800">
                  <td className="px-2 py-1 text-slate-300">Bare metal</td>
                  <td className="px-2 py-1">PLCs, OpenWRT, Cortex-M, &lt;256 MB RAM boxes</td>
                  <td className="px-2 py-1 font-mono">Rust/C static binary + (optional) systemd</td>
                  <td className="px-2 py-1">32-64 MB</td>
                  <td className="px-2 py-1">5-50 MB</td>
                </tr>
              </tbody>
            </table>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <div className="text-slate-400 mb-1">Quick install — k3s + helm (Tier 1):</div>
                <pre className="bg-slate-950 border border-slate-800 rounded p-2 font-mono text-[10.5px] text-emerald-300 overflow-x-auto">{`curl -sfL https://get.k3s.io | sh -
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash`}</pre>
              </div>
              <div>
                <div className="text-slate-400 mb-1">Quick install — docker only (Tier 2):</div>
                <pre className="bg-slate-950 border border-slate-800 rounded p-2 font-mono text-[10.5px] text-emerald-300 overflow-x-auto">{`curl -fsSL https://get.docker.com | sh`}</pre>
              </div>
            </div>
            <p className="text-slate-400">
              <strong>Network:</strong> outbound TCP 443/8000 to the platform. Optional TCP 1883 for MQTT (falls back to HTTP push). <strong>Not needed:</strong> Python on the box (Rust/C are static), Neo4j, Postgres, GPU drivers. The runtime uses local SQLite only.
            </p>
            <p className="text-slate-400">
              <strong>Optional:</strong> Mosquitto for plant MQTT bus, Ollama for local LLM (air-gapped sites), Chrony for clock sync (bundle signature has a 1h <code className="bg-slate-800 px-1 rounded">issued_at</code> skew tolerance — drift past that rejects bundles).
            </p>
            <p className="text-[11px] text-slate-500">
              Full prereq matrix + add-ons + Helm/Docker/systemd snippets: <a href="/docs?slug=06-deployment%2F05-edge-runtime" target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline">docs &rarr; 06-deployment / 05-edge-runtime</a>.
            </p>
          </div>
        </details>

        {tokenModal && (
          <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={() => setTokenModal(null)}>
            <div className="bg-slate-900 border border-cyan-700/50 rounded-lg max-w-3xl w-full p-5" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold text-cyan-200">Edge token + signing pubkey</h3>
                <button onClick={() => setTokenModal(null)} className="text-slate-400 hover:text-white">close</button>
              </div>
              <div className="rounded bg-amber-900/30 border border-amber-700/40 p-2.5 text-[12px] text-amber-200 mb-3">
                {tokenModal.warning}
              </div>
              <div className="space-y-3 text-[12.5px]">
                <div>
                  <div className="text-slate-400 mb-1">PLATFORM_TOKEN</div>
                  <div className="flex items-center gap-2">
                    <code className="block flex-1 bg-slate-950 border border-slate-800 rounded p-2 font-mono break-all text-emerald-300">{tokenModal.token}</code>
                    <button onClick={() => copyToClipboard(tokenModal.token, 'tok')} className="px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-xs">{copied === 'tok' ? '✓' : 'Copy'}</button>
                  </div>
                </div>
                <div>
                  <div className="text-slate-400 mb-1">SIGNING_PUBKEY (PEM)</div>
                  <div className="flex items-start gap-2">
                    <pre className="block flex-1 bg-slate-950 border border-slate-800 rounded p-2 font-mono text-[11px] text-cyan-300 max-h-40 overflow-y-auto">{tokenModal.pubkey || '(none — set EDGE_SIGNING_KEY_PEM on the api pod first)'}</pre>
                    {tokenModal.pubkey && (
                      <button onClick={() => copyToClipboard(tokenModal.pubkey, 'pub')} className="px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-xs">{copied === 'pub' ? '✓' : 'Copy'}</button>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-slate-400 mb-1">Helm install snippet</div>
                  <pre className="bg-slate-950 border border-slate-800 rounded p-2 font-mono text-[11px] text-slate-200 overflow-x-auto">{`helm install abenix-edge-rust ./infra/helm/edge-runtime-rust \\
  --namespace abenix \\
  --set platform_url=http://abenix-api:8000 \\
  --set platform_token=${tokenModal.token.slice(0,16)}... \\
  --set signing_pubkey="$(cat pub.pem)" \\
  --set mqtt_url=mqtt://abenix-mosquitto:1883 \\
  --set anthropic_api_key=$ANTHROPIC_API_KEY`}</pre>
                </div>
              </div>
            </div>
          </div>
        )}

        <section data-testid="edge-runtime-variants">
          <div className="mb-3">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Package className="w-4 h-4 text-cyan-400" /> Edge runtime — pick your variant
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Drop this on the gateway box. It registers itself, pulls signed bundles, and
              executes agents next to your sensors.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {variants.map((v) => {
              const tone = VARIANT_TONES[v.name] || VARIANT_TONES.python;
              const helmKey = `helm-${v.name}`;
              const dockerKey = `docker-${v.name}`;
              const dockerPull = `docker pull ${v.image}`;
              return (
                <div
                  key={v.name}
                  className={`rounded-lg border p-4 space-y-3 ${tone.card}`}
                  data-testid={`runtime-card-${v.name}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className={`font-semibold text-sm ${tone.head}`}>{v.label}</h3>
                      <p className="text-[11px] text-slate-400 font-mono mt-0.5 break-all">
                        {v.image}
                      </p>
                    </div>
                    <span className={`shrink-0 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${tone.chip}`}>
                      {v.size_mb} MB
                    </span>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Targets</p>
                    <div className="flex flex-wrap gap-1">
                      {v.targets.map((t) => (
                        <span key={t} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800/60 border border-slate-700/60 text-slate-300">
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                      Dependencies
                    </p>
                    {v.deps.length === 0 ? (
                      <span className="text-[11px] text-slate-500 italic">none — single static binary</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {v.deps.map((d) => (
                          <span key={d} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800/60 border border-slate-700/60 text-slate-300">
                            {d}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-300 leading-relaxed">
                    <span className="text-slate-500 uppercase tracking-wider text-[10px]">Use when:&nbsp;</span>
                    {v.use_when}
                  </p>
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    <button
                      onClick={() => copyToClipboard(v.helm_install, helmKey)}
                      className={`text-[11px] px-2 py-1.5 rounded border flex items-center justify-center gap-1.5 hover:opacity-90 ${tone.chip}`}
                      data-testid={`copy-helm-${v.name}`}
                    >
                      {copied === helmKey ? <CheckCircle2 className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                      {copied === helmKey ? 'Copied' : 'Helm install'}
                    </button>
                    <button
                      onClick={() => copyToClipboard(dockerPull, dockerKey)}
                      className={`text-[11px] px-2 py-1.5 rounded border flex items-center justify-center gap-1.5 hover:opacity-90 ${tone.chip}`}
                      data-testid={`copy-docker-${v.name}`}
                    >
                      {copied === dockerKey ? <CheckCircle2 className="w-3 h-3" /> : <Terminal className="w-3 h-3" />}
                      {copied === dockerKey ? 'Copied' : 'Docker pull'}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="rounded-lg border border-slate-700/50 bg-slate-800/30">
          <button
            onClick={() => setHowOpen((o) => !o)}
            className="w-full flex items-center justify-between px-4 py-3 text-sm text-slate-200 hover:bg-slate-800/50 rounded-lg"
            data-testid="how-it-works-toggle"
          >
            <span className="flex items-center gap-2">
              <Info className="w-4 h-4 text-cyan-400" />
              How interactions work
            </span>
            {howOpen ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
          </button>
          {howOpen && (
            <div className="px-4 pb-4 pt-1 text-xs text-slate-300 space-y-2 leading-relaxed border-t border-slate-700/50">
              <ol className="list-decimal list-outside pl-5 space-y-2">
                <li>
                  Gateway registers with the platform via{' '}
                  <code className="text-cyan-300">POST /api/edge/gateways/register</code>{' '}
                  every 60s (auth: <code className="text-cyan-300">af_</code> key).
                </li>
                <li>
                  UI pushes via{' '}
                  <code className="text-cyan-300">POST /api/edge/gateways/{'{id}'}/deploy</code>{' '}
                  → backend tries MQTT first (<code className="text-cyan-300">edge.{'{gateway_id}'}.deploy</code>),
                  HTTP fallback.
                </li>
                <li>
                  Runtime hot-loads the bundle into{' '}
                  <code className="text-cyan-300">/var/edge/agents/{'{slug}'}/</code>.
                </li>
                <li>
                  Caller hits{' '}
                  <code className="text-cyan-300">POST {'{gateway_endpoint}'}/agents/{'{slug}'}/execute</code>{' '}
                  for sync calls; or publishes to{' '}
                  <code className="text-cyan-300">agents.{'{slug}'}.input</code> over MQTT for async.
                </li>
              </ol>
            </div>
          )}
        </section>

        <div className="pt-2">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Wifi className="w-4 h-4 text-cyan-400" /> Registered gateways ({gateways.length})
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Once a gateway boots with the runtime above, it self-registers and shows up here.
          </p>
        </div>

        {gateways.length === 0 ? (
          <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-8 text-center text-sm text-slate-400">
            No edge gateways registered yet. Deploy the <code className="text-cyan-300">edge-runtime</code> helm chart and it will register itself on boot.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {gateways.map(g => (
              <div
                key={g.id}
                className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4 space-y-3"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <StatusDot status={g.status} lastSeen={g.last_seen_at} />
                      <h3 className="text-white font-medium">{g.name || g.gateway_id}</h3>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5 font-mono">{g.gateway_id}</p>
                  </div>
                  <button
                    onClick={() => setModalGatewayId(g.id)}
                    className="px-3 py-1.5 text-xs bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 rounded-lg flex items-center gap-1.5 hover:bg-cyan-500/25"
                  >
                    <Send className="w-3.5 h-3.5" /> Deploy agent
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                  <div className="flex items-center gap-1.5">
                    <Clock className="w-3 h-3" /> Last seen {timeAgo(g.last_seen_at)}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Wifi className="w-3 h-3" /> {g.endpoint_url ? 'reachable' : 'offline-only'}
                  </div>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                    Deployed agents ({g.deployed_agents?.length || 0})
                  </p>
                  {(g.deployed_agents || []).length === 0 ? (
                    <p className="text-xs text-slate-600 italic">none</p>
                  ) : (
                    <ul className="space-y-1">
                      {g.deployed_agents.map(d => (
                        <li
                          key={d.slug}
                          className="text-xs text-slate-300 flex items-center justify-between bg-slate-900/40 rounded px-2 py-1"
                        >
                          <span className="font-mono">{d.slug}</span>
                          <span className="text-[10px] text-slate-500">
                            {d.digest.slice(0, 10)}… · {timeAgo(d.deployed_at)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {modalGateway && (
          <div
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setModalGatewayId(null)}
          >
            <div
              onClick={e => e.stopPropagation()}
              className="w-full max-w-lg bg-slate-900 border border-slate-700 rounded-xl p-5 space-y-4"
            >
              <div className="flex items-center justify-between">
                <h2 className="text-white font-semibold">
                  Deploy to {modalGateway.name}
                </h2>
                <button onClick={() => setModalGatewayId(null)} className="text-slate-400 hover:text-white">
                  <X className="w-4 h-4" />
                </button>
              </div>
              {edgeAgents.length === 0 ? (
                <div className="text-sm text-slate-400 p-4 rounded border border-slate-700/40 bg-slate-800/40">
                  No edge-compatible agents. Open an agent in the builder, switch to the Advanced tab, and toggle &quot;Edge compatible&quot;.
                </div>
              ) : (
                <ul className="space-y-2 max-h-[60vh] overflow-y-auto">
                  {edgeAgents.map(a => (
                    <li
                      key={a.id}
                      className="flex items-center justify-between bg-slate-800/40 rounded-lg px-3 py-2"
                    >
                      <div>
                        <p className="text-sm text-white">{a.name}</p>
                        <p className="text-[11px] text-slate-500 font-mono">{a.slug}</p>
                      </div>
                      <button
                        disabled={deploying === a.id}
                        onClick={() => deploy(modalGateway.id, a.id)}
                        className="px-3 py-1 text-xs bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 rounded hover:bg-cyan-500/25 disabled:opacity-50 flex items-center gap-1.5"
                      >
                        {deploying === a.id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Send className="w-3 h-3" />
                        )}
                        Deploy
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {toast && (
          <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm text-white flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            {toast}
          </div>
        )}
      </div>
    </div>
  );
}
