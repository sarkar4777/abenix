'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, FileSearch,
  Gauge, Loader2, MapPin, Play, ShieldCheck, Sparkles, TrendingUp,
  Waves, Wind, Zap,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { findPipelineBySlug, runPipeline, type PipelineKey } from '../lib/pipelineRunner';
import KbBadge from '../components/KbBadge';
import PipelineDagViz from '../components/PipelineDagViz';
import { VALUEEDGE_DAG } from '../components/dags';
import ScenarioExplainer from '../components/ScenarioExplainer';
import { Database, Layers, ListChecks } from 'lucide-react';

// ── Types ────────────────────────────────────────────────────────────

interface SiteBrief {
  capacity_mw: number;
  location: string;
  water_depth_m: number;
  distance_to_shore_km: number;
  soil_type: 'sand' | 'clay' | 'rock' | 'mixed';
  wind_class: 'I' | 'II' | 'III' | 'S';
  grid_voltage_kv: number;
}

interface SiteTemplate extends SiteBrief {
  id: string;
  name: string;
  country: string;
  comment: string;
}

interface Scenario {
  id: string;
  name: string;
  thesis?: string;
  turbine_model?: string;
  turbine_rating_mw?: number;
  turbine_count?: number;
  rotor_diameter_m?: number;
  hub_height_m?: number;
  foundation_type?: string;
  array_voltage_kv?: number;
  export_topology?: string;
  offshore_substations?: number;
  layout_pattern?: string;
  spacing_x_d?: number;
  spacing_y_d?: number;
  estimated_capex_musd?: number;
  estimated_co2_kt?: number;
  estimated_irr_pct?: number;
  estimated_lcoe_usd_mwh?: number;
  key_risks?: string[];
  cost_drivers?: string[];
  standards_cited?: string[];
}

interface CostRecompute {
  id: string;
  name?: string;
  capacity_mw?: number;
  capex_musd?: number;
  co2_kt?: number;
  irr_pct?: number;
  lcoe_usd_mwh?: number;
}

interface VeOpportunity {
  id: string;
  title: string;
  category: string;
  applies_to_scenario_ids: string[];
  description: string;
  capex_delta_pct: number;
  co2_delta_pct: number;
  irr_delta_pct_points: number;
  risk_score: number;
  confidence: number;
  composite_score: number;
  evidence?: { scenario_field: string; from_value: string; to_value: string; rationale: string }[];
  standards_cited?: string[];
  decision_owner?: string;
}

interface ComplianceFinding {
  id: string;
  scenario_id: string;
  scenario_field?: string;
  severity: 'BLOCKER' | 'MAJOR' | 'MINOR' | 'ADVISORY';
  title: string;
  description: string;
  violated_clause: string;
  clause_excerpt?: string;
  remediation_hint?: string;
  rfi_required: boolean;
}

interface Rfi {
  rfi_number: string;
  linked_finding_id: string;
  scenario_id: string;
  addressed_to: string;
  subject: string;
  priority: 'BLOCKER' | 'MAJOR' | 'MINOR';
  clause_cited: string;
  context: string;
  questions: string[];
  evidence_requested: string[];
  due_date: string;
  response_format?: string;
}

interface PipelineReport {
  status?: string;
  scenarios?: Scenario[];
  cost_recompute?: CostRecompute[];
  ve_opportunities?: VeOpportunity[];
  ve_portfolio_summary?: {
    total_capex_savings_potential_pct?: number;
    total_co2_savings_potential_pct?: number;
    headline_opportunity_id?: string;
  };
  compliance_findings?: ComplianceFinding[];
  compliance_summary?: {
    blocker_count?: number;
    major_count?: number;
    minor_count?: number;
    advisory_count?: number;
    highest_risk_scenario?: string;
  };
  rfis?: Rfi[];
}

// ── Static templates ─────────────────────────────────────────────────

const SITE_TEMPLATES: SiteTemplate[] = [
  {
    id: 'dogger-bank',
    name: 'Dogger Bank — UK',
    country: 'UK',
    capacity_mw: 200,
    location: 'Dogger Bank, North Sea (UK EEZ)',
    water_depth_m: 28,
    distance_to_shore_km: 130,
    soil_type: 'sand',
    wind_class: 'I',
    grid_voltage_kv: 275,
    comment: 'Shallow sand, long export — HVDC territory.',
  },
  {
    id: 'german-north-sea',
    name: 'German North Sea — N-9.x',
    country: 'DE',
    capacity_mw: 120,
    location: 'German Bight, North Sea (DE EEZ)',
    water_depth_m: 42,
    distance_to_shore_km: 75,
    soil_type: 'mixed',
    wind_class: 'II',
    grid_voltage_kv: 220,
    comment: 'Transitional depth — jacket default.',
  },
  {
    id: 'us-east-coast',
    name: 'US East Coast — OCS-A 0512',
    country: 'US',
    capacity_mw: 150,
    location: 'New York Bight (BOEM)',
    water_depth_m: 33,
    distance_to_shore_km: 38,
    soil_type: 'clay',
    wind_class: 'II',
    grid_voltage_kv: 345,
    comment: 'Jones Act vessels — install logistics dominate.',
  },
];

const FOUNDATION_TONES: Record<string, string> = {
  monopile: 'from-cyan-500/15 to-cyan-600/5 border-cyan-500/30',
  jacket: 'from-purple-500/15 to-purple-600/5 border-purple-500/30',
  'floating-semisub': 'from-amber-500/15 to-amber-600/5 border-amber-500/30',
  'floating-spar': 'from-emerald-500/15 to-emerald-600/5 border-emerald-500/30',
};

const SEVERITY_TONE: Record<string, string> = {
  BLOCKER: 'bg-red-500/20 text-red-300 border-red-500/40',
  MAJOR: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  MINOR: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
  ADVISORY: 'bg-slate-700/60 text-slate-300 border-slate-600/40',
};

// ── Component ────────────────────────────────────────────────────────

export default function ValueEdgeTab() {
  const [pipelineId, setPipelineId] = useState<PipelineKey | null>(null);
  const [brief, setBrief] = useState<SiteBrief>({
    capacity_mw: SITE_TEMPLATES[0].capacity_mw,
    location: SITE_TEMPLATES[0].location,
    water_depth_m: SITE_TEMPLATES[0].water_depth_m,
    distance_to_shore_km: SITE_TEMPLATES[0].distance_to_shore_km,
    soil_type: SITE_TEMPLATES[0].soil_type,
    wind_class: SITE_TEMPLATES[0].wind_class,
    grid_voltage_kv: SITE_TEMPLATES[0].grid_voltage_kv,
  });
  const [activeTemplateId, setActiveTemplateId] = useState<string>(SITE_TEMPLATES[0].id);

  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<PipelineReport | null>(null);
  const [error, setError] = useState<string>('');
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const [expandedRfi, setExpandedRfi] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const id = await findPipelineBySlug('iot-valueedge-pipeline');
      setPipelineId(id);
    })();
  }, []);

  const applyTemplate = (t: SiteTemplate) => {
    setActiveTemplateId(t.id);
    setBrief({
      capacity_mw: t.capacity_mw,
      location: t.location,
      water_depth_m: t.water_depth_m,
      distance_to_shore_km: t.distance_to_shore_km,
      soil_type: t.soil_type,
      wind_class: t.wind_class,
      grid_voltage_kv: t.grid_voltage_kv,
    });
  };

  const generate = async () => {
    if (!pipelineId) {
      setError('iot-valueedge-pipeline not yet seeded on this cluster.');
      return;
    }
    setRunning(true); setError(''); setReport(null); setSelectedScenarioId(null);
    const result = await runPipeline(pipelineId, brief, {}, { waitSeconds: 240 });
    if (!result.ok) {
      setError(result.error ?? 'pipeline execution failed');
    } else {
      const out = (result.final_output ?? {}) as PipelineReport;
      setReport(out);
      if (out.scenarios && out.scenarios.length > 0) {
        setSelectedScenarioId(out.scenarios[0].id);
      }
    }
    setRunning(false);
  };

  const selectedScenario = useMemo(() => {
    if (!report || !selectedScenarioId) return null;
    return report.scenarios?.find((s) => s.id === selectedScenarioId) ?? null;
  }, [report, selectedScenarioId]);

  const veForSelected = useMemo(() => {
    if (!report || !selectedScenarioId) return [];
    return (report.ve_opportunities ?? []).filter((v) =>
      v.applies_to_scenario_ids?.includes(selectedScenarioId),
    );
  }, [report, selectedScenarioId]);

  const findingsForSelected = useMemo(() => {
    if (!report || !selectedScenarioId) return [];
    return (report.compliance_findings ?? []).filter((f) => f.scenario_id === selectedScenarioId);
  }, [report, selectedScenarioId]);

  const rfisForSelected = useMemo(() => {
    if (!report || !selectedScenarioId) return [];
    return (report.rfis ?? []).filter((r) => r.scenario_id === selectedScenarioId);
  }, [report, selectedScenarioId]);

  return (
    <div className="grid lg:grid-cols-[1fr_320px] gap-6">
    <div className="space-y-6 min-w-0">
      {/* ── Hero ───────────────────────────────────────────────── */}
      <div
        className="relative overflow-hidden rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-slate-900 via-slate-900 to-cyan-950/40 p-6"
        style={{
          backgroundImage:
            'linear-gradient(to bottom right, rgba(2,6,23,0.85), rgba(8,47,73,0.40)), url(/industrial-iot/valueedge/offshore-wind-aerial.jpg)',
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      >
        <div className="relative z-10 flex flex-col lg:flex-row lg:items-end lg:justify-between gap-6">
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-cyan-300/90 bg-cyan-500/10 border border-cyan-500/30 rounded px-2 py-0.5 mb-3">
              <Wind className="w-3 h-3" />
              ValueEdge — Engineering & EPC Copilot
            </div>
            <h2 className="text-3xl font-semibold text-white leading-tight">
              "I have a 200&nbsp;MW offshore wind site —
              <span className="text-cyan-300"> generate 3 designs.</span>"
            </h2>
            <p className="mt-3 text-sm text-slate-300 leading-relaxed">
              From one line of intent to three fully-specified design scenarios with
              CapEx, CO<sub>2</sub>, IRR, value-engineering opportunities, and
              compliance RFIs against IEC 61400-3, NEC 690, IEEE 1547 and your
              tenant EPC standards. Built on the same agent runtime that powers the
              rest of the platform.
            </p>
          </div>
          <div className="flex flex-col gap-2 min-w-[200px]">
            <KbBadge />
            <button
              disabled={running || !pipelineId}
              onClick={generate}
              title={
                !pipelineId
                  ? 'Pipeline iot-valueedge-pipeline not yet seeded.'
                  : 'Run the 4-agent design pipeline (~3-4 min)'
              }
              className="flex items-center justify-center gap-2 px-4 py-2.5 bg-cyan-500 text-slate-950 font-semibold rounded-lg hover:bg-cyan-400 disabled:bg-slate-700 disabled:text-slate-500 transition-colors"
            >
              {running ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  Generate Scenarios
                </>
              )}
            </button>
            {!pipelineId && (
              <p className="text-[10px] text-amber-300/80 text-right">
                Pipeline not seeded on this cluster.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* ── Site brief form ────────────────────────────────────── */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-white font-semibold flex items-center gap-2">
            <MapPin className="w-4 h-4 text-cyan-400" />
            Site Brief
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {SITE_TEMPLATES.map((t) => (
              <button
                key={t.id}
                onClick={() => applyTemplate(t)}
                className={`text-[11px] px-2.5 py-1 rounded-md border transition-colors ${
                  activeTemplateId === t.id
                    ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-200'
                    : 'bg-slate-800/40 border-slate-700 text-slate-300 hover:border-slate-600'
                }`}
              >
                {t.name}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <FormField label="Capacity (MW)">
            <input
              type="number"
              value={brief.capacity_mw}
              onChange={(e) => setBrief({ ...brief, capacity_mw: Number(e.target.value) })}
              className="bg-slate-950/70 border border-slate-700 text-slate-100 text-sm rounded-md px-2.5 py-1.5 w-full focus:border-cyan-500 focus:outline-none"
            />
          </FormField>
          <FormField label="Location">
            <input
              type="text"
              value={brief.location}
              onChange={(e) => setBrief({ ...brief, location: e.target.value })}
              className="bg-slate-950/70 border border-slate-700 text-slate-100 text-sm rounded-md px-2.5 py-1.5 w-full focus:border-cyan-500 focus:outline-none"
            />
          </FormField>
          <FormField label="Water depth (m)">
            <input
              type="number"
              value={brief.water_depth_m}
              onChange={(e) => setBrief({ ...brief, water_depth_m: Number(e.target.value) })}
              className="bg-slate-950/70 border border-slate-700 text-slate-100 text-sm rounded-md px-2.5 py-1.5 w-full focus:border-cyan-500 focus:outline-none"
            />
          </FormField>
          <FormField label="Distance to shore (km)">
            <input
              type="number"
              value={brief.distance_to_shore_km}
              onChange={(e) =>
                setBrief({ ...brief, distance_to_shore_km: Number(e.target.value) })
              }
              className="bg-slate-950/70 border border-slate-700 text-slate-100 text-sm rounded-md px-2.5 py-1.5 w-full focus:border-cyan-500 focus:outline-none"
            />
          </FormField>
          <FormField label="Soil type">
            <select
              value={brief.soil_type}
              onChange={(e) =>
                setBrief({ ...brief, soil_type: e.target.value as SiteBrief['soil_type'] })
              }
              className="bg-slate-950/70 border border-slate-700 text-slate-100 text-sm rounded-md px-2.5 py-1.5 w-full focus:border-cyan-500 focus:outline-none"
            >
              <option value="sand">sand</option>
              <option value="clay">clay</option>
              <option value="rock">rock</option>
              <option value="mixed">mixed</option>
            </select>
          </FormField>
          <FormField label="Wind class (IEC 61400-1)">
            <select
              value={brief.wind_class}
              onChange={(e) =>
                setBrief({ ...brief, wind_class: e.target.value as SiteBrief['wind_class'] })
              }
              className="bg-slate-950/70 border border-slate-700 text-slate-100 text-sm rounded-md px-2.5 py-1.5 w-full focus:border-cyan-500 focus:outline-none"
            >
              <option value="I">I</option>
              <option value="II">II</option>
              <option value="III">III</option>
              <option value="S">S (site-specific)</option>
            </select>
          </FormField>
          <FormField label="Grid voltage (kV)">
            <input
              type="number"
              value={brief.grid_voltage_kv}
              onChange={(e) =>
                setBrief({ ...brief, grid_voltage_kv: Number(e.target.value) })
              }
              className="bg-slate-950/70 border border-slate-700 text-slate-100 text-sm rounded-md px-2.5 py-1.5 w-full focus:border-cyan-500 focus:outline-none"
            />
          </FormField>
          <FormField label="">
            <div className="text-[10px] text-slate-500 leading-tight pt-1.5 italic">
              {SITE_TEMPLATES.find((t) => t.id === activeTemplateId)?.comment}
            </div>
          </FormField>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg p-3">
          <AlertTriangle className="w-4 h-4 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {running && !report && <RunningSkeleton />}

      {/* ── Scenario cards ─────────────────────────────────────── */}
      {report?.scenarios && report.scenarios.length > 0 && (
        <div>
          <div className="flex items-baseline justify-between mb-3">
            <h3 className="text-white font-semibold flex items-center gap-2">
              <Gauge className="w-4 h-4 text-cyan-400" />
              Generated Scenarios
            </h3>
            {report.ve_portfolio_summary?.headline_opportunity_id && (
              <p className="text-xs text-slate-400">
                Headline VE opportunity:{' '}
                <span className="text-cyan-300">
                  {report.ve_portfolio_summary.headline_opportunity_id}
                </span>
              </p>
            )}
          </div>
          <div className="grid md:grid-cols-3 gap-4">
            {report.scenarios.map((s) => {
              const cost = report.cost_recompute?.find((c) => c.id === s.id);
              const isSelected = selectedScenarioId === s.id;
              const tone = FOUNDATION_TONES[s.foundation_type ?? ''] ??
                'from-slate-800/60 to-slate-900/40 border-slate-700';
              return (
                <motion.button
                  key={s.id}
                  layout
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  onClick={() => setSelectedScenarioId(s.id)}
                  className={`text-left rounded-xl p-4 border bg-gradient-to-br transition-all ${tone} ${
                    isSelected ? 'ring-2 ring-cyan-400/60 shadow-lg shadow-cyan-500/10' : ''
                  }`}
                >
                  <div className="flex items-start justify-between mb-2">
                    <div>
                      <p className="text-[10px] uppercase tracking-wider text-slate-400">{s.id}</p>
                      <h4 className="text-white font-semibold text-sm leading-tight">{s.name}</h4>
                    </div>
                    <div className="shrink-0 text-[10px] uppercase tracking-wider text-cyan-300/80 px-1.5 py-0.5 bg-cyan-500/10 border border-cyan-500/30 rounded">
                      {s.foundation_type}
                    </div>
                  </div>
                  <p className="text-[11px] text-slate-300 italic mb-3 leading-snug min-h-[2.5em]">
                    {s.thesis}
                  </p>
                  <LayoutSketch scenario={s} />
                  <div className="grid grid-cols-2 gap-2 mt-3 text-[11px]">
                    <Metric
                      label="CapEx"
                      value={fmtUsd(cost?.capex_musd ?? s.estimated_capex_musd)}
                      unit="M"
                    />
                    <Metric
                      label="LCOE"
                      value={fmtNum(cost?.lcoe_usd_mwh ?? s.estimated_lcoe_usd_mwh, 0)}
                      unit="$/MWh"
                    />
                    <Metric
                      label="IRR"
                      value={fmtNum(cost?.irr_pct ?? s.estimated_irr_pct, 2)}
                      unit="%"
                    />
                    <Metric
                      label="CO₂ life-cycle"
                      value={fmtNum(cost?.co2_kt ?? s.estimated_co2_kt, 0)}
                      unit="kt"
                    />
                    <Metric
                      label="Turbines"
                      value={`${s.turbine_count ?? '—'} × ${s.turbine_rating_mw ?? '—'} MW`}
                    />
                    <Metric
                      label="Array"
                      value={`${s.array_voltage_kv ?? '—'} kV`}
                    />
                  </div>
                </motion.button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Drill-in panel ─────────────────────────────────────── */}
      <AnimatePresence mode="wait">
        {selectedScenario && (
          <motion.div
            key={selectedScenario.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.25 }}
            className="space-y-4"
          >
            <ScenarioHeader scenario={selectedScenario} />

            {/* Cost breakdown chart + risks */}
            <div className="grid lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                <h4 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
                  <Zap className="w-4 h-4 text-cyan-400" />
                  CapEx Breakdown — {selectedScenario.id}
                </h4>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={breakdownData(selectedScenario, report?.cost_recompute)}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="label" stroke="#64748b" fontSize={11} />
                      <YAxis stroke="#64748b" fontSize={11} />
                      <Tooltip
                        contentStyle={{
                          background: '#0f172a',
                          border: '1px solid #334155',
                          fontSize: 12,
                        }}
                        labelStyle={{ color: '#94a3b8' }}
                      />
                      <Bar dataKey="value" fill="#06b6d4" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                <h4 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
                  <Waves className="w-4 h-4 text-cyan-400" />
                  Key Risks & Drivers
                </h4>
                <div className="space-y-3 text-xs">
                  {selectedScenario.key_risks && selectedScenario.key_risks.length > 0 && (
                    <div>
                      <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">
                        Risks
                      </p>
                      <ul className="space-y-1 text-slate-300">
                        {selectedScenario.key_risks.map((r, i) => (
                          <li key={i} className="flex gap-1.5">
                            <span className="text-amber-400">•</span>
                            <span>{r}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {selectedScenario.cost_drivers &&
                    selectedScenario.cost_drivers.length > 0 && (
                      <div>
                        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">
                          Cost drivers
                        </p>
                        <ul className="space-y-1 text-slate-300">
                          {selectedScenario.cost_drivers.map((r, i) => (
                            <li key={i} className="flex gap-1.5">
                              <span className="text-cyan-400">•</span>
                              <span>{r}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                </div>
              </div>
            </div>

            {/* VE opportunities table */}
            {veForSelected.length > 0 && (
              <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                <h4 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-cyan-400" />
                  Value-Engineering Opportunities ({veForSelected.length})
                </h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-slate-500 border-b border-slate-800">
                        <th className="py-2 pr-3 font-medium">ID</th>
                        <th className="py-2 pr-3 font-medium">Title</th>
                        <th className="py-2 pr-3 font-medium">Cat</th>
                        <th className="py-2 pr-3 font-medium text-right">CapEx Δ</th>
                        <th className="py-2 pr-3 font-medium text-right">CO₂ Δ</th>
                        <th className="py-2 pr-3 font-medium text-right">IRR Δ</th>
                        <th className="py-2 pr-3 font-medium text-right">Risk</th>
                        <th className="py-2 pr-3 font-medium text-right">Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {veForSelected.map((v) => (
                        <tr key={v.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                          <td className="py-2 pr-3 font-mono text-slate-400">{v.id}</td>
                          <td className="py-2 pr-3 text-slate-200">
                            <div className="font-medium">{v.title}</div>
                            <div className="text-[10.5px] text-slate-500 italic">
                              {v.description}
                            </div>
                          </td>
                          <td className="py-2 pr-3 text-[10px] text-cyan-300">{v.category}</td>
                          <td
                            className={`py-2 pr-3 text-right font-mono ${
                              v.capex_delta_pct < 0 ? 'text-emerald-300' : 'text-rose-300'
                            }`}
                          >
                            {v.capex_delta_pct > 0 ? '+' : ''}
                            {fmtNum(v.capex_delta_pct, 1)}%
                          </td>
                          <td
                            className={`py-2 pr-3 text-right font-mono ${
                              v.co2_delta_pct < 0 ? 'text-emerald-300' : 'text-rose-300'
                            }`}
                          >
                            {v.co2_delta_pct > 0 ? '+' : ''}
                            {fmtNum(v.co2_delta_pct, 1)}%
                          </td>
                          <td
                            className={`py-2 pr-3 text-right font-mono ${
                              v.irr_delta_pct_points > 0 ? 'text-emerald-300' : 'text-rose-300'
                            }`}
                          >
                            {v.irr_delta_pct_points > 0 ? '+' : ''}
                            {fmtNum(v.irr_delta_pct_points, 2)}
                          </td>
                          <td className="py-2 pr-3 text-right">
                            <RiskPip score={v.risk_score} />
                          </td>
                          <td className="py-2 pr-3 text-right font-mono text-slate-300">
                            {fmtNum(v.composite_score, 2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Compliance findings */}
            {findingsForSelected.length > 0 && (
              <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                <h4 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-cyan-400" />
                  Compliance Findings ({findingsForSelected.length})
                </h4>
                <ul className="space-y-2">
                  {findingsForSelected.map((f) => (
                    <li
                      key={f.id}
                      className="border border-slate-800 rounded-lg p-3 bg-slate-950/40"
                    >
                      <div className="flex items-start gap-3">
                        <span
                          className={`text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-md border whitespace-nowrap ${
                            SEVERITY_TONE[f.severity] ?? SEVERITY_TONE.ADVISORY
                          }`}
                        >
                          {f.severity}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-slate-200 text-sm font-medium">{f.title}</p>
                          <p className="text-xs text-slate-400 mt-0.5">{f.description}</p>
                          <div className="flex flex-wrap items-center gap-2 mt-2 text-[11px]">
                            <span className="text-cyan-300 font-mono">{f.violated_clause}</span>
                            {f.scenario_field && (
                              <span className="text-slate-500">
                                field: <code>{f.scenario_field}</code>
                              </span>
                            )}
                            {f.rfi_required && (
                              <span className="inline-flex items-center gap-1 text-amber-300">
                                <FileSearch className="w-3 h-3" />
                                RFI required
                              </span>
                            )}
                          </div>
                          {f.remediation_hint && (
                            <p className="text-[11px] text-emerald-300/80 mt-1.5">
                              <CheckCircle2 className="w-3 h-3 inline mr-1" />
                              {f.remediation_hint}
                            </p>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Drafted RFIs (clickable) */}
            {rfisForSelected.length > 0 && (
              <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                <h4 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
                  <FileSearch className="w-4 h-4 text-cyan-400" />
                  Drafted RFIs ({rfisForSelected.length})
                </h4>
                <ul className="space-y-2">
                  {rfisForSelected.map((r) => {
                    const open = expandedRfi === r.rfi_number;
                    return (
                      <li key={r.rfi_number} className="border border-slate-800 rounded-lg">
                        <button
                          className="w-full flex items-center gap-3 p-3 text-left hover:bg-slate-800/40"
                          onClick={() =>
                            setExpandedRfi(open ? null : r.rfi_number)
                          }
                        >
                          <span className="text-xs font-mono text-cyan-300 w-32">
                            {r.rfi_number}
                          </span>
                          <span
                            className={`text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-md border ${
                              SEVERITY_TONE[r.priority] ?? SEVERITY_TONE.ADVISORY
                            }`}
                          >
                            {r.priority}
                          </span>
                          <span className="text-sm text-slate-200 flex-1 truncate">
                            {r.subject}
                          </span>
                          <span className="text-[10px] text-slate-500 whitespace-nowrap">
                            due {r.due_date}
                          </span>
                          {open ? (
                            <ChevronDown className="w-4 h-4 text-slate-500" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-slate-500" />
                          )}
                        </button>
                        <AnimatePresence>
                          {open && (
                            <motion.div
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: 'auto', opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              transition={{ duration: 0.18 }}
                              className="overflow-hidden"
                            >
                              <div className="px-4 pb-4 pt-0 text-xs space-y-3">
                                <div className="grid sm:grid-cols-2 gap-3 text-slate-400">
                                  <div>
                                    <p className="text-[10px] uppercase tracking-wider text-slate-500">
                                      Addressed to
                                    </p>
                                    <p>{r.addressed_to}</p>
                                  </div>
                                  <div>
                                    <p className="text-[10px] uppercase tracking-wider text-slate-500">
                                      Clause
                                    </p>
                                    <p className="font-mono text-cyan-300">{r.clause_cited}</p>
                                  </div>
                                </div>
                                <div>
                                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                                    Context
                                  </p>
                                  <p className="text-slate-300 leading-relaxed">{r.context}</p>
                                </div>
                                <div>
                                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                                    Questions
                                  </p>
                                  <ol className="list-decimal list-outside pl-5 space-y-1 text-slate-300">
                                    {r.questions.map((q, i) => (
                                      <li key={i}>{q}</li>
                                    ))}
                                  </ol>
                                </div>
                                <div>
                                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                                    Evidence requested
                                  </p>
                                  <ul className="list-disc list-outside pl-5 space-y-0.5 text-slate-300">
                                    {r.evidence_requested.map((q, i) => (
                                      <li key={i}>{q}</li>
                                    ))}
                                  </ul>
                                </div>
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <PipelineDagViz dag={VALUEEDGE_DAG} />
    </div>

    <ScenarioExplainer
      eyebrow="ValueEdge · UAT guide"
      title="From one site brief to three ranked designs"
      lede={(
        <>
          Pick a template (or punch your own numbers), hit <strong>Generate scenarios</strong>,
          drill into one card to see ranked value-engineering opportunities, code findings
          with cited clauses, and any compliance RFIs the engine wants raised. Every number
          on screen comes from the agent runtime — there is no client-side rule engine.
        </>
      )}
      callouts={[
        { label: 'Scenarios', value: '3 per run' },
        { label: 'Latency',   value: '90–180 s' },
        { label: 'KB',        value: 'rwe-valueedge-design-standards · 8 docs' },
        { label: 'Pipeline',  value: 'iot-valueedge-pipeline' },
      ]}
      sections={[
        {
          icon: ListChecks,
          tone: 'cyan',
          title: '1. Brief the engine',
          body: 'Use a site template (Dogger Bank, North Sea, US East Coast) or edit the form. Capacity, water depth, distance to shore, soil type, wind class, and grid voltage are the seven inputs that drive scenario configuration.',
        },
        {
          icon: Layers,
          tone: 'amber',
          title: '2. Compare 3 scenarios',
          body: (
            <>
              Each card shows CapEx, LCOE, IRR, CO<sub>2</sub>, layout sketch + a 5-pip risk meter.
              Numbers come from the deterministic <code>cost_recompute</code> node, not the LLM.
            </>
          ),
        },
        {
          icon: Database,
          tone: 'purple',
          title: '3. Drill into VE + RFIs',
          body: 'Click any scenario to surface its Pareto-ranked VE opportunities (CapEx vs CO₂ vs risk), compliance findings with clause citations, and pre-drafted RFIs ready to send to the EPC.',
        },
      ]}
      footer={(
        <p>
          Pipeline runs server-side via the SDK. The execution DAG below the page shows
          every node + how it routes — open it any time to inspect what the engine did.
        </p>
      )}
    />
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1">
        {label || ' '}
      </span>
      {children}
    </label>
  );
}

function Metric({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div>
      <p className="text-[9.5px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-slate-100 font-mono text-[12.5px] mt-0.5">
        {value}
        {unit && <span className="text-slate-500 text-[10px] ml-1">{unit}</span>}
      </p>
    </div>
  );
}

function RiskPip({ score }: { score: number }) {
  const pips = Array.from({ length: 5 }, (_, i) => i < score);
  const tone = score >= 4 ? 'bg-rose-400' : score >= 3 ? 'bg-amber-400' : 'bg-emerald-400';
  return (
    <span className="inline-flex gap-0.5">
      {pips.map((on, i) => (
        <span
          key={i}
          className={`w-1.5 h-3 rounded-sm ${on ? tone : 'bg-slate-700'}`}
        />
      ))}
    </span>
  );
}

function ScenarioHeader({ scenario }: { scenario: Scenario }) {
  return (
    <div className="bg-gradient-to-br from-slate-900 to-slate-900/50 border border-cyan-500/30 rounded-xl p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-cyan-300/80">
            Scenario {scenario.id}
          </p>
          <h3 className="text-xl text-white font-semibold leading-tight">{scenario.name}</h3>
          <p className="text-sm text-slate-300 mt-1">{scenario.thesis}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          {scenario.standards_cited?.slice(0, 4).map((s) => (
            <span
              key={s}
              className="px-2 py-0.5 rounded-md bg-slate-800/80 border border-slate-700 text-slate-300 font-mono"
            >
              {s}
            </span>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 mt-4 text-xs">
        <KV label="Turbine" value={scenario.turbine_model ?? '—'} />
        <KV label="Foundation" value={scenario.foundation_type ?? '—'} />
        <KV
          label="Layout"
          value={`${scenario.layout_pattern ?? '—'} ${
            scenario.spacing_x_d ? `(${scenario.spacing_x_d}D × ${scenario.spacing_y_d}D)` : ''
          }`}
        />
        <KV label="Array" value={`${scenario.array_voltage_kv ?? '—'} kV`} />
        <KV label="Export" value={scenario.export_topology ?? '—'} />
        <KV label="OSS" value={`${scenario.offshore_substations ?? '—'}`} />
      </div>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-slate-200 mt-0.5 truncate">{value}</p>
    </div>
  );
}

function LayoutSketch({ scenario }: { scenario: Scenario }) {
  // Tiny SVG of the array layout — driven by turbine_count + spacing.
  const n = Math.min(scenario.turbine_count ?? 12, 30);
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const w = 220;
  const h = 70;
  const cellW = w / (cols + 1);
  const cellH = h / (rows + 1);
  const dots: { x: number; y: number }[] = [];
  for (let i = 0; i < n; i++) {
    const r = Math.floor(i / cols);
    const c = i % cols;
    const offset = scenario.layout_pattern === 'staggered-grid' && r % 2 ? cellW / 2 : 0;
    dots.push({ x: cellW * (c + 1) + offset, y: cellH * (r + 1) });
  }
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-16 rounded-md bg-slate-950/60 border border-slate-800">
      {dots.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={2} fill="#06b6d4" />
      ))}
      <line x1={0} y1={h - 1} x2={w} y2={h - 1} stroke="#475569" strokeWidth={0.5} />
    </svg>
  );
}

function RunningSkeleton() {
  return (
    <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-6">
      <div className="flex items-center gap-3 text-sm text-slate-300">
        <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
        Configuring scenarios → recomputing costs → ranking VE → checking
        compliance → drafting RFIs. Typical end-to-end ~3-4 min.
      </div>
      <div className="grid md:grid-cols-3 gap-4 mt-4">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-48 rounded-xl bg-gradient-to-br from-slate-800/40 to-slate-900/40 border border-slate-800 animate-pulse"
          />
        ))}
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────

function fmtNum(v: number | undefined | null, digits = 1): string {
  if (v === undefined || v === null || Number.isNaN(v)) return '—';
  return v.toFixed(digits);
}

function fmtUsd(v: number | undefined | null): string {
  if (v === undefined || v === null || Number.isNaN(v)) return '—';
  return `$${v.toFixed(0)}`;
}

function breakdownData(
  scenario: Scenario,
  costs: CostRecompute[] | undefined,
): { label: string; value: number }[] {
  const cost = costs?.find((c) => c.id === scenario.id);
  const total = cost?.capex_musd ?? scenario.estimated_capex_musd ?? 0;
  if (!total) return [];
  // shares aligned with code-asset breakdown table
  const share =
    scenario.foundation_type?.startsWith('floating')
      ? { Turbines: 0.28, Foundation: 0.31, BoS: 0.18, Install: 0.15, Dev: 0.08 }
      : scenario.foundation_type === 'jacket'
      ? { Turbines: 0.32, Foundation: 0.24, BoS: 0.19, Install: 0.16, Dev: 0.09 }
      : { Turbines: 0.36, Foundation: 0.18, BoS: 0.20, Install: 0.16, Dev: 0.10 };
  return Object.entries(share).map(([label, pct]) => ({
    label,
    value: Math.round(total * pct),
  }));
}
