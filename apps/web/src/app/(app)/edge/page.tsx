'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Cpu, Loader2, RefreshCw, Send, X, AlertTriangle, CheckCircle2, Clock, Wifi,
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalGatewayId, setModalGatewayId] = useState<string | null>(null);
  const [deploying, setDeploying] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) { setLoading(false); setError('Not signed in'); return; }
    setError(null);
    try {
      const [gr, ar] = await Promise.all([
        fetch(`${API_URL}/api/edge/gateways`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/api/agents?limit=500`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      const gj = await gr.json();
      const aj = await ar.json();
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
