'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import Link from 'next/link';
import {
  Diamond, ShieldCheck, AlertTriangle, Truck, Globe, Radar,
  Loader2, ArrowRight, Activity, Layers,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Overview {
  contracts_with_extraction: number;
  compliance_runs: number;
  dispute_scans: number;
  sourcing_audits: number;
  tracked_refiners: number;
  refiners_at_risk: number;
  total_expected_dispute_loss_usd: number;
  avg_compliance_score: number | null;
  avg_audit_readiness_score: number | null;
  material_mix: Record<string, number>;
  loco_mix: Record<string, number>;
}

const MODULE_CARDS = [
  { href: '/metals/extract',     icon: Diamond,       title: 'Metals Extraction',     desc: 'Purity, bar specs, loco, pricing reference, assay protocol, vaulting type — pulled from contract text.', accent: 'amber' },
  { href: '/metals/compliance',  icon: ShieldCheck,   title: 'Compliance Audit',      desc: 'LBMA Good Delivery, RGG, LPPM, OECD DDG, RJC, ISO 9001/14001, Swiss PMCA, HMRC, sanctions.', accent: 'emerald' },
  { href: '/metals/disputes',    icon: AlertTriangle, title: 'Dispute Risk Scorer',   desc: 'Assay + weight + brand + late-delivery + sanctioned-origin → expected $ exposure.', accent: 'red' },
  { href: '/metals/loco',        icon: Truck,         title: 'Loco + Delivery',       desc: 'Zurich / London / NY / Shanghai premium, insurance, customs, chain of integrity.', accent: 'cyan' },
  { href: '/metals/sourcing',    icon: Globe,         title: 'Responsible Sourcing',  desc: 'OECD 5-step + LBMA RGG + RJC CoC, country of origin, mine identity, audit readiness.', accent: 'violet' },
  { href: '/metals/refiners',    icon: Radar,         title: 'Refiner Watch',         desc: 'Counterparty Good Delivery list status, audit dates, OFAC SDN, alert on changes.', accent: 'orange' },
];

const ACCENT: Record<string, string> = {
  amber: 'from-amber-500/20 to-amber-600/10 border-amber-500/40 text-amber-300',
  emerald: 'from-emerald-500/20 to-emerald-600/10 border-emerald-500/40 text-emerald-300',
  red: 'from-red-500/20 to-red-600/10 border-red-500/40 text-red-300',
  cyan: 'from-cyan-500/20 to-cyan-600/10 border-cyan-500/40 text-cyan-300',
  violet: 'from-violet-500/20 to-violet-600/10 border-violet-500/40 text-violet-300',
  orange: 'from-orange-500/20 to-orange-600/10 border-orange-500/40 text-orange-300',
};

export default function MetalsOverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      const token = getToken();
      if (!token) { setLoading(false); return; }
      try {
        const res = await fetch(`${API_URL}/api/contractiq/metals/overview`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const j = await res.json();
        setData(j.data || null);
      } catch (e) {
        setData(null);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 rounded-xl bg-gradient-to-br from-amber-500/20 to-amber-700/10 border border-amber-500/40">
            <Diamond className="w-7 h-7 text-amber-300" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Precious Metals</h1>
            <p className="text-sm text-slate-400">Refiner-grade contract intelligence — extract, audit, watch, score.</p>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
              <KPI label="Contracts indexed"      value={data?.contracts_with_extraction ?? 0} />
              <KPI label="Compliance runs"        value={data?.compliance_runs ?? 0} />
              <KPI label="Dispute scans"          value={data?.dispute_scans ?? 0} />
              <KPI label="Sourcing audits"        value={data?.sourcing_audits ?? 0} />
              <KPI label="Tracked refiners"       value={data?.tracked_refiners ?? 0} />
              <KPI
                label="Refiners at risk"
                value={data?.refiners_at_risk ?? 0}
                accent={(data?.refiners_at_risk ?? 0) > 0 ? 'red' : 'neutral'}
              />
              <KPI
                label="Expected dispute loss"
                value={formatUsd(data?.total_expected_dispute_loss_usd ?? 0)}
                accent={(data?.total_expected_dispute_loss_usd ?? 0) > 0 ? 'amber' : 'neutral'}
              />
              <KPI
                label="Avg compliance"
                value={data?.avg_compliance_score != null ? data.avg_compliance_score.toFixed(2) : 'n/a'}
                accent={
                  data?.avg_compliance_score == null ? 'neutral'
                  : data.avg_compliance_score >= 0.85 ? 'emerald'
                  : data.avg_compliance_score >= 0.6 ? 'amber'
                  : 'red'
                }
              />
            </div>

            {data && (Object.keys(data.material_mix).length > 0 || Object.keys(data.loco_mix).length > 0) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-8">
                <MixBox title="Material mix" icon={Layers} mix={data.material_mix} />
                <MixBox title="Loco mix" icon={Truck} mix={data.loco_mix} />
              </div>
            )}

            <div className="text-xs uppercase tracking-wide text-slate-500 mb-3">Modules</div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {MODULE_CARDS.map((m) => (
                <Link key={m.href} href={m.href}>
                  <motion.div
                    whileHover={{ y: -2 }}
                    className={`p-4 rounded-xl bg-gradient-to-br ${ACCENT[m.accent]} border h-full cursor-pointer`}
                  >
                    <div className="flex items-start justify-between mb-3">
                      <m.icon className="w-5 h-5" />
                      <ArrowRight className="w-4 h-4 opacity-60" />
                    </div>
                    <div className="text-base font-semibold text-white mb-1">{m.title}</div>
                    <div className="text-xs text-slate-300/80 leading-relaxed">{m.desc}</div>
                  </motion.div>
                </Link>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function KPI({ label, value, accent = 'neutral' }: { label: string; value: any; accent?: string }) {
  const tone: Record<string, string> = {
    neutral: 'text-white',
    red: 'text-red-300',
    amber: 'text-amber-300',
    emerald: 'text-emerald-300',
  };
  return (
    <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/80">
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">{label}</div>
      <div className={`text-lg font-bold ${tone[accent]}`}>{value}</div>
    </div>
  );
}

function MixBox({ title, icon: Icon, mix }: { title: string; icon: any; mix: Record<string, number> }) {
  const total = Object.values(mix).reduce((a, b) => a + b, 0) || 1;
  const entries = Object.entries(mix).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return null;
  return (
    <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/80">
      <div className="flex items-center gap-2 mb-3 text-xs uppercase tracking-wide text-slate-500">
        <Icon className="w-4 h-4" /> {title}
      </div>
      <div className="space-y-1.5">
        {entries.map(([k, n]) => (
          <div key={k}>
            <div className="flex items-center justify-between text-xs mb-0.5">
              <span className="text-slate-300">{k.replace(/_/g, ' ')}</span>
              <span className="text-slate-500">{n}</span>
            </div>
            <div className="h-1.5 rounded-full bg-slate-800/80 overflow-hidden">
              <div className="h-full bg-gradient-to-r from-cyan-500 to-violet-500" style={{ width: `${(n / total) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatUsd(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}
