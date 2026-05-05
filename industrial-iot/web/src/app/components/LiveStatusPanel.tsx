'use client';

// Mini status panel rendered on every showcase tab. Polls the
// standalone API for broker / TSDB / connector reachability so a user
// flipping into Live mode sees at a glance whether the wiring is up.
// Falls quietly to all-red when the standalone API is unreachable.

import { useEffect, useState } from 'react';
import { Activity, Database, Plug, Radio } from 'lucide-react';

interface LiveStatusResponse {
  mqtt: { reachable: boolean; broker?: string };
  tsdb: { reachable: boolean; host?: string };
  connectors: { count: number };
}

interface Props {
  liveModeActive: boolean;
  pollSeconds?: number;
}

const DEFAULT_STATUS: LiveStatusResponse = {
  mqtt: { reachable: false },
  tsdb: { reachable: false },
  connectors: { count: 0 },
};

export default function LiveStatusPanel({ liveModeActive, pollSeconds = 30 }: Props) {
  const [status, setStatus] = useState<LiveStatusResponse>(DEFAULT_STATUS);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const tick = async () => {
      try {
        const r = await fetch('/api/industrial-iot/live-status', { cache: 'no-store' });
        if (!r.ok) {
          if (mounted) { setStatus(DEFAULT_STATUS); setLoading(false); }
          return;
        }
        const j = await r.json();
        if (mounted) {
          setStatus(j.data ?? DEFAULT_STATUS);
          setLoading(false);
        }
      } catch {
        if (mounted) { setStatus(DEFAULT_STATUS); setLoading(false); }
      }
    };
    tick();
    const id = setInterval(tick, Math.max(5, pollSeconds) * 1000);
    return () => { mounted = false; clearInterval(id); };
  }, [pollSeconds]);

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
      <span className="text-slate-400 uppercase tracking-wider text-[10px]">Live system</span>
      <Pill icon={Radio} label="MQTT"   ok={status.mqtt.reachable} loading={loading} />
      <Pill icon={Database} label="TSDB" ok={status.tsdb.reachable} loading={loading} />
      <Pill icon={Plug} label={`Connectors ${status.connectors.count}`} ok={status.connectors.count > 0} loading={loading} />
      <Pill icon={Activity} label="Live mode" ok={liveModeActive} loading={false} />
    </div>
  );
}

function Pill({
  icon: Icon, label, ok, loading,
}: { icon: typeof Activity; label: string; ok: boolean; loading: boolean }) {
  const tone = loading
    ? 'text-slate-500 border-slate-700'
    : ok
      ? 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10'
      : 'text-slate-500 border-slate-700';
  const mark = loading ? '…' : ok ? '✓' : '✗';
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border ${tone}`}>
      <Icon className="w-3 h-3" />
      {label}
      <span className="ml-1 font-mono">{mark}</span>
    </span>
  );
}
