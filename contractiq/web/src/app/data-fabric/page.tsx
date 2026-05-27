'use client';

import { useMemo, useState } from 'react';
import {
  Database, Activity, AlertTriangle, CheckCircle2, RefreshCw,
  Globe2, Cloud, Radio, Newspaper, Building2, FlaskConical,
} from 'lucide-react';

type ConnectorStatus = 'healthy' | 'lagging' | 'stale' | 'failed';

interface Connector {
  id: string;
  name: string;
  category: 'exchange' | 'tso' | 'weather' | 'scada' | 'news' | 'macro' | 'asset' | 'client';
  icon: any;
  status: ConnectorStatus;
  lagSeconds: number;
  rowsPerHour: number;
  quality: number;
  lastIngestAt: string;
  hubs?: string[];
}

const CATEGORY_LABEL: Record<Connector['category'], string> = {
  exchange: 'Exchange',
  tso: 'TSO / TSO-equivalent',
  weather: 'Weather',
  scada: 'SCADA / Telemetry',
  news: 'Geopolitical',
  macro: 'Economic',
  asset: 'Infrastructure',
  client: 'Client offtake',
};

const CATEGORY_ICON: Record<Connector['category'], any> = {
  exchange: Activity,
  tso: Radio,
  weather: Cloud,
  scada: Radio,
  news: Newspaper,
  macro: Building2,
  asset: Globe2,
  client: Database,
};

const CONNECTORS: Connector[] = [
  { id: 'eex', name: 'EEX', category: 'exchange', icon: Activity, status: 'healthy', lagSeconds: 3, rowsPerHour: 4_200, quality: 99.8, lastIngestAt: '2 s ago', hubs: ['TTF', 'THE', 'CEGH', 'PEG'] },
  { id: 'ice-endex', name: 'ICE Endex', category: 'exchange', icon: Activity, status: 'healthy', lagSeconds: 4, rowsPerHour: 2_900, quality: 99.7, lastIngestAt: '3 s ago', hubs: ['TTF', 'NBP'] },
  { id: 'nord-pool', name: 'Nord Pool', category: 'exchange', icon: Activity, status: 'healthy', lagSeconds: 2, rowsPerHour: 6_300, quality: 99.9, lastIngestAt: '1 s ago', hubs: ['Nordic', 'Baltic'] },
  { id: 'epex-spot', name: 'EPEX SPOT', category: 'exchange', icon: Activity, status: 'lagging', lagSeconds: 47, rowsPerHour: 5_100, quality: 98.4, lastIngestAt: '47 s ago', hubs: ['DE', 'FR', 'NL', 'BE'] },
  { id: 'pegas', name: 'PEGAS', category: 'exchange', icon: Activity, status: 'healthy', lagSeconds: 5, rowsPerHour: 1_800, quality: 99.5, lastIngestAt: '5 s ago', hubs: ['TTF', 'PEG', 'NCG'] },
  { id: 'entsog', name: 'ENTSOG Transparency', category: 'tso', icon: Radio, status: 'healthy', lagSeconds: 120, rowsPerHour: 880, quality: 99.1, lastIngestAt: '2 m ago' },
  { id: 'entsoe', name: 'ENTSO-E Transparency', category: 'tso', icon: Radio, status: 'healthy', lagSeconds: 60, rowsPerHour: 2_400, quality: 99.3, lastIngestAt: '1 m ago' },
  { id: 'open-grid', name: 'Open Grid Europe', category: 'tso', icon: Radio, status: 'stale', lagSeconds: 3_600, rowsPerHour: 240, quality: 92.1, lastIngestAt: '1 h ago' },
  { id: 'snam', name: 'Snam Italy', category: 'tso', icon: Radio, status: 'healthy', lagSeconds: 180, rowsPerHour: 220, quality: 99.0, lastIngestAt: '3 m ago' },
  { id: 'ecmwf', name: 'ECMWF', category: 'weather', icon: Cloud, status: 'healthy', lagSeconds: 900, rowsPerHour: 50_000, quality: 99.95, lastIngestAt: '15 m ago' },
  { id: 'meteologica', name: 'Meteologica', category: 'weather', icon: Cloud, status: 'healthy', lagSeconds: 600, rowsPerHour: 12_000, quality: 99.7, lastIngestAt: '10 m ago' },
  { id: 'scada-storage', name: 'Storage SCADA', category: 'scada', icon: Radio, status: 'healthy', lagSeconds: 30, rowsPerHour: 18_000, quality: 99.6, lastIngestAt: '30 s ago' },
  { id: 'scada-ccgt', name: 'CCGT Plant Telemetry', category: 'scada', icon: Radio, status: 'healthy', lagSeconds: 15, rowsPerHour: 28_000, quality: 99.8, lastIngestAt: '15 s ago' },
  { id: 'scada-bess', name: 'BESS Telemetry', category: 'scada', icon: Radio, status: 'healthy', lagSeconds: 10, rowsPerHour: 36_000, quality: 99.9, lastIngestAt: '10 s ago' },
  { id: 'reuters', name: 'Reuters Energy', category: 'news', icon: Newspaper, status: 'healthy', lagSeconds: 90, rowsPerHour: 320, quality: 99.0, lastIngestAt: '1 m ago' },
  { id: 'bloomberg', name: 'Bloomberg Commodities', category: 'news', icon: Newspaper, status: 'healthy', lagSeconds: 45, rowsPerHour: 410, quality: 99.4, lastIngestAt: '45 s ago' },
  { id: 'ecb-macro', name: 'ECB Macro', category: 'macro', icon: Building2, status: 'healthy', lagSeconds: 86_400, rowsPerHour: 6, quality: 99.99, lastIngestAt: '1 d ago' },
  { id: 'eurostat', name: 'Eurostat Industrial', category: 'macro', icon: Building2, status: 'healthy', lagSeconds: 86_400, rowsPerHour: 4, quality: 99.99, lastIngestAt: '1 d ago' },
  { id: 'storage-bookings', name: 'Storage Bookings', category: 'asset', icon: Globe2, status: 'healthy', lagSeconds: 1_800, rowsPerHour: 35, quality: 99.5, lastIngestAt: '30 m ago' },
  { id: 'lng-slots', name: 'LNG Slot Calendar', category: 'asset', icon: Globe2, status: 'healthy', lagSeconds: 3_600, rowsPerHour: 15, quality: 99.8, lastIngestAt: '1 h ago' },
  { id: 'retail-load', name: 'Retail Smart-Meter Stream', category: 'client', icon: Database, status: 'healthy', lagSeconds: 300, rowsPerHour: 240_000, quality: 99.3, lastIngestAt: '5 m ago' },
  { id: 'b2b-baseload', name: 'B2B Baseload Profiles', category: 'client', icon: Database, status: 'lagging', lagSeconds: 1_200, rowsPerHour: 18_000, quality: 97.2, lastIngestAt: '20 m ago' },
];

const STATUS_STYLES: Record<ConnectorStatus, string> = {
  healthy: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  lagging: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  stale: 'bg-orange-500/10 text-orange-300 border-orange-500/30',
  failed: 'bg-red-500/10 text-red-300 border-red-500/30',
};

const STATUS_ICON: Record<ConnectorStatus, any> = {
  healthy: CheckCircle2,
  lagging: RefreshCw,
  stale: AlertTriangle,
  failed: AlertTriangle,
};

function fmtNum(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} k`;
  return `${n}`;
}

export default function DataFabricPage() {
  const [filter, setFilter] = useState<Connector['category'] | 'all'>('all');

  const stats = useMemo(() => {
    const total = CONNECTORS.length;
    const healthy = CONNECTORS.filter(c => c.status === 'healthy').length;
    const rows = CONNECTORS.reduce((a, c) => a + c.rowsPerHour, 0);
    const avgQuality = CONNECTORS.reduce((a, c) => a + c.quality, 0) / CONNECTORS.length;
    return { total, healthy, rows, avgQuality };
  }, []);

  const view = filter === 'all' ? CONNECTORS : CONNECTORS.filter(c => c.category === filter);

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <Database className="w-7 h-7 text-cyan-400" />
          <h1 className="text-3xl font-bold text-white">Data Fabric &amp; Harmonization</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Every external + internal source pipes into one canonical, point-in-time lakehouse.
          Anomaly detection, imputation, and feature engineering run before downstream engines see a byte.
        </p>
      </header>

      <section className="grid grid-cols-4 gap-4 mb-8">
        {[
          { label: 'Connectors', value: stats.total, sub: `${stats.healthy} healthy`, accent: 'emerald' },
          { label: 'Rows / hour', value: fmtNum(stats.rows), sub: 'cross-source aggregate', accent: 'cyan' },
          { label: 'Avg quality', value: `${stats.avgQuality.toFixed(2)}%`, sub: 'rolling 24h', accent: 'violet' },
          { label: 'Lakehouse', value: 'OK', sub: 'Timescale + Parquet', accent: 'sky' },
        ].map(stat => (
          <div key={stat.label} className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <p className="text-[11px] text-slate-500 uppercase tracking-wider">{stat.label}</p>
            <p className="text-2xl font-bold text-white mt-1.5">{stat.value}</p>
            <p className="text-[11px] text-slate-500 mt-0.5">{stat.sub}</p>
          </div>
        ))}
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 mb-8">
        <h2 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
          <FlaskConical className="w-4 h-4 text-cyan-400" /> Pipeline schematic
        </h2>
        <svg viewBox="0 0 1100 320" className="w-full h-auto">
          <defs>
            <marker id="df-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
            </marker>
            <linearGradient id="df-grad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#10b981" />
              <stop offset="100%" stopColor="#06b6d4" />
            </linearGradient>
          </defs>
          {[
            { x: 30,  y: 30, label: 'Exchanges' },
            { x: 30,  y: 90, label: 'TSOs' },
            { x: 30,  y: 150, label: 'Weather' },
            { x: 30,  y: 210, label: 'SCADA' },
            { x: 30,  y: 270, label: 'Client offtake' },
          ].map((s, i) => (
            <g key={i}>
              <rect x={s.x} y={s.y} width="140" height="42" rx="8" fill="#0f172a" stroke="#06b6d4" />
              <text x={s.x + 70} y={s.y + 26} textAnchor="middle" fill="#a5f3fc" fontSize="12">{s.label}</text>
              <line x1={s.x + 140} y1={s.y + 21} x2="290" y2="160" stroke="#475569" strokeWidth="1" markerEnd="url(#df-arr)" />
            </g>
          ))}
          <rect x="290" y="120" width="200" height="80" rx="10" fill="#0f172a" stroke="url(#df-grad)" strokeWidth="2" />
          <text x="390" y="148" textAnchor="middle" fill="#e2e8f0" fontSize="13" fontWeight="bold">Adapter Registry</text>
          <text x="390" y="170" textAnchor="middle" fill="#94a3b8" fontSize="10">market_data + MQTT ingest</text>
          <text x="390" y="186" textAnchor="middle" fill="#94a3b8" fontSize="10">22 connectors</text>
          <line x1="490" y1="160" x2="600" y2="160" stroke="#475569" strokeWidth="1.5" markerEnd="url(#df-arr)" />
          <rect x="600" y="120" width="200" height="80" rx="10" fill="#0f172a" stroke="#7c3aed" />
          <text x="700" y="148" textAnchor="middle" fill="#e9d5ff" fontSize="13" fontWeight="bold">Cleansing + Imputation</text>
          <text x="700" y="170" textAnchor="middle" fill="#94a3b8" fontSize="10">IsolationForest outliers</text>
          <text x="700" y="186" textAnchor="middle" fill="#94a3b8" fontSize="10">KNN + spline imputation</text>
          <line x1="800" y1="160" x2="910" y2="160" stroke="#475569" strokeWidth="1.5" markerEnd="url(#df-arr)" />
          <rect x="910" y="100" width="160" height="120" rx="10" fill="#0f172a" stroke="#10b981" />
          <text x="990" y="130" textAnchor="middle" fill="#bbf7d0" fontSize="13" fontWeight="bold">Energy Lakehouse</text>
          <text x="990" y="152" textAnchor="middle" fill="#94a3b8" fontSize="10">TimescaleDB hot tier</text>
          <text x="990" y="168" textAnchor="middle" fill="#94a3b8" fontSize="10">Parquet cold tier</text>
          <text x="990" y="184" textAnchor="middle" fill="#94a3b8" fontSize="10">Feature store</text>
          <text x="990" y="200" textAnchor="middle" fill="#94a3b8" fontSize="10">Point-in-time joins</text>
        </svg>
      </section>

      <section className="mb-4 flex flex-wrap gap-2">
        {(['all', 'exchange', 'tso', 'weather', 'scada', 'news', 'macro', 'asset', 'client'] as const).map(c => (
          <button
            key={c}
            onClick={() => setFilter(c)}
            className={`px-3 py-1.5 rounded-md text-xs border transition-colors ${
              filter === c
                ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/40'
                : 'bg-slate-900/40 text-slate-400 border-slate-800 hover:bg-slate-800/60 hover:text-white'
            }`}
          >
            {c === 'all' ? 'All sources' : CATEGORY_LABEL[c]}
          </button>
        ))}
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/80 text-[10px] text-slate-500 uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-2.5">Connector</th>
              <th className="text-left px-4 py-2.5">Category</th>
              <th className="text-left px-4 py-2.5">Status</th>
              <th className="text-right px-4 py-2.5">Lag</th>
              <th className="text-right px-4 py-2.5">Rows / hour</th>
              <th className="text-right px-4 py-2.5">Quality</th>
              <th className="text-left px-4 py-2.5">Last ingest</th>
              <th className="text-left px-4 py-2.5">Hubs</th>
            </tr>
          </thead>
          <tbody>
            {view.map(c => {
              const SI = STATUS_ICON[c.status];
              const CI = CATEGORY_ICON[c.category];
              return (
                <tr key={c.id} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-4 py-3 font-medium text-white">{c.name}</td>
                  <td className="px-4 py-3 text-slate-400">
                    <span className="inline-flex items-center gap-1.5"><CI className="w-3.5 h-3.5 text-slate-500" />{CATEGORY_LABEL[c.category]}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border ${STATUS_STYLES[c.status]}`}>
                      <SI className="w-3 h-3" /> {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-slate-300 font-mono text-xs">
                    {c.lagSeconds < 60 ? `${c.lagSeconds}s` : c.lagSeconds < 3600 ? `${(c.lagSeconds / 60).toFixed(0)}m` : `${(c.lagSeconds / 3600).toFixed(1)}h`}
                  </td>
                  <td className="px-4 py-3 text-right text-slate-300 font-mono text-xs">{fmtNum(c.rowsPerHour)}</td>
                  <td className="px-4 py-3 text-right text-slate-300 font-mono text-xs">{c.quality.toFixed(1)}%</td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{c.lastIngestAt}</td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{c.hubs?.join(', ') ?? '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
