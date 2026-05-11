'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Ship, AlertTriangle, Wifi, Loader2, RefreshCw, Cloud } from 'lucide-react';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip from '../components/PipelineStrip';
import ExplainerPanel from '../components/ExplainerPanel';
import { OPS_EXPLAINER } from '../components/explainer-specs';

const OPS_PIPELINE = [
  { id: 'wingman-ops-monitor', label: 'Ops Monitor', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'wingman-ops-monitor agent' },
  { id: 'ais_stream', label: 'AISStream', icon: 'tool' as const, hint: 'real-time AIS positions' },
  { id: 'open_meteo', label: 'Open-Meteo', icon: 'tool' as const, hint: 'port weather + marine forecast' },
  { id: 'current_time', label: 'Time anchor', icon: 'tool' as const },
];

interface Vessel { mmsi: number; name: string; lat: number; lon: number; speed_knots?: number; course_deg?: number; ship_type?: number; }
interface Alert { vessel_mmsi?: number; vessel_name?: string; severity: string; reason?: string; recommendation?: string; }
interface Snapshot {
  vessels?: Vessel[];
  alerts?: Alert[];
  weather?: { hub: string; max_gust_kmh?: number; total_precip_mm?: number; }[];
  narrative?: string;
}

export default function OpsPage() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeExecution, setActiveExecution] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/wingman/ops/snapshot');
      const j = await r.json();
      const data = j.data;
      setSnap(data?.snapshot || {});
      if (data?.execution_id) setActiveExecution(data.execution_id);
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { refresh(); }, []);

  const vessels = snap?.vessels || [];
  const alerts = snap?.alerts || [];
  const weather = snap?.weather || [];

  return (
    <div className="p-6">
      <HeroBar
        eyebrow="OPERATIONS WATCH"
        title="Every vessel, every port, every alert."
        subtitle="Live AIS via AISStream.io · port weather via Open-Meteo · ranked alerts. The bridge for the trader who needs to know which cargo is in trouble before the broker calls."
        rightSlot={
          <div className="flex items-center gap-3 text-[10px]">
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">vessels</span>
              <span className="text-xs font-mono font-semibold text-emerald-300">{vessels.length}</span>
            </span>
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">alerts</span>
              <span className={`text-xs font-mono font-semibold ${alerts.length === 0 ? 'text-slate-300' : 'text-amber-300'}`}>{alerts.length}</span>
            </span>
            <button
              onClick={refresh}
              disabled={loading}
              className="px-3 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 text-xs font-semibold flex items-center gap-2"
            >
              {loading ? <><Loader2 className="w-3 h-3 animate-spin" /> Refreshing...</> : <><RefreshCw className="w-3 h-3" /> Refresh</>}
            </button>
          </div>
        }
      />

      <ExplainerPanel spec={OPS_EXPLAINER} />

      <PipelineStrip
        title="Pipeline · 1 agent · live AIS · port weather"
        subtitle="Refresh fires the ops-monitor pipeline — AISStream + Open-Meteo light up live"
        nodes={OPS_PIPELINE}
        executionId={activeExecution}
      />

      {/* Vessels */}
      <section className="mb-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3 flex items-center gap-2">
          <Wifi className="w-3 h-3 text-emerald-400" /> Live AIS — {vessels.length} vessels
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {vessels.slice(0, 24).map((v) => (
            <motion.div
              key={v.mmsi}
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              className="rounded-lg border border-slate-800 bg-slate-900/40 p-3"
            >
              <div className="flex items-start justify-between mb-2">
                <Ship className="w-4 h-4 text-emerald-400 mt-0.5" />
                <span className="ais-pulse w-2 h-2 rounded-full bg-emerald-400" />
              </div>
              <div className="text-xs font-semibold text-white truncate" title={v.name}>{v.name}</div>
              <div className="text-[9px] font-mono text-slate-600">MMSI {v.mmsi}</div>
              <div className="text-[10px] text-slate-400 mt-1">
                ({v.lat.toFixed(2)}, {v.lon.toFixed(2)})
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">
                {v.speed_knots != null ? `${v.speed_knots} kt` : 'sog —'} · {v.course_deg != null ? `${v.course_deg}°` : 'cog —'}
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Alerts */}
      <section className="mb-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3 flex items-center gap-2">
          <AlertTriangle className="w-3 h-3 text-amber-400" /> Ranked alerts
        </h2>
        {alerts.length === 0 ? (
          <p className="text-xs text-slate-500 italic">No alerts — every vessel and port is currently within tolerance.</p>
        ) : (
          <div className="space-y-2">
            {alerts.map((a, i) => (
              <div key={i} className={`rounded-lg border px-4 py-3 ${
                a.severity === 'critical' ? 'border-rose-500/30 bg-rose-500/5' :
                a.severity === 'warning'  ? 'border-amber-500/30 bg-amber-500/5' :
                'border-slate-700/30 bg-slate-800/20'
              }`}>
                <div className="flex items-center justify-between mb-1">
                  <div className="text-sm font-semibold text-white">{a.vessel_name || `MMSI ${a.vessel_mmsi}`}</div>
                  <span className={`text-[10px] uppercase font-bold ${
                    a.severity === 'critical' ? 'text-rose-300' :
                    a.severity === 'warning' ? 'text-amber-300' : 'text-slate-300'
                  }`}>{a.severity}</span>
                </div>
                {a.reason && <div className="text-xs text-slate-300 mb-1">{a.reason}</div>}
                {a.recommendation && <div className="text-[11px] text-slate-400 italic">→ {a.recommendation}</div>}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Weather */}
      <section className="mb-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3 flex items-center gap-2">
          <Cloud className="w-3 h-3 text-cyan-400" /> Port weather (7-day horizon)
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {weather.map((w, i) => (
            <div key={i} className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
              <div className="text-xs font-semibold text-white">{w.hub}</div>
              {w.max_gust_kmh != null && <div className="text-[10px] text-slate-400 mt-1">peak gust <span className="text-cyan-300">{w.max_gust_kmh} km/h</span></div>}
              {w.total_precip_mm != null && <div className="text-[10px] text-slate-400">precip <span className="text-cyan-300">{w.total_precip_mm} mm</span></div>}
            </div>
          ))}
        </div>
      </section>

      {snap?.narrative && (
        <section className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4 mb-6">
          <div className="text-[10px] uppercase tracking-wider font-semibold text-emerald-300 mb-2">Operations Sentinel narrative</div>
          <p className="text-sm text-slate-200 leading-relaxed">{snap.narrative}</p>
        </section>
      )}

      <DagDrawer executionId={activeExecution} onClose={() => setActiveExecution(null)} />
    </div>
  );
}
