'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ShieldCheck, ShieldAlert, ShieldX, TrendingUp, TrendingDown,
  RefreshCw, Loader2, ChevronDown, ChevronUp, AlertTriangle,
  Building2, BarChart3, Target, Clock, Zap, DollarSign,
  ArrowRight, CheckCircle2, XCircle, Activity, FileCheck2,
} from 'lucide-react';
import TrafficLightDashboard from './components/TrafficLightDashboard';
import ComplianceAlertsTicker from './components/ComplianceAlertsTicker';
import DataSourcePanel from '../components/DataSourcePanel';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('contractiq_token') || ''; }
function getUser() { try { return JSON.parse(localStorage.getItem('contractiq_user') || '{}'); } catch { return null; } }

const RISK_COLORS: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  Low: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', icon: 'text-emerald-400' },
  Medium: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', icon: 'text-amber-400' },
  High: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', icon: 'text-orange-400' },
  Critical: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', icon: 'text-red-400' },
};

const Z_ZONE_COLORS: Record<string, string> = {
  'Safe Zone': 'text-emerald-400',
  'Grey Zone': 'text-amber-400',
  'Distress Zone': 'text-red-400',
};

interface CreditAssessment {
  id: string;
  counterparty_name: string;
  ticker?: string;
  sector?: string;
  credit_rating?: string;
  credit_score?: number;
  altman_z_score?: number;
  z_score_zone?: string;
  probability_of_default_pct?: number;
  risk_level?: string;
  key_ratios?: Record<string, number>;
  financial_highlights?: string[];
  risk_factors?: string[];
  mitigating_factors?: string[];
  credit_mitigation_recommendations?: string[];
  monitoring_triggers?: string[];
  narrative?: string;
  status: string;
  error_message?: string;
  cost_usd?: number;
  assessed_at?: string;
}

interface PortfolioSummary {
  counterparties: string[];
  assessments: CreditAssessment[];
  total_counterparties: number;
  assessed_count: number;
  unassessed: string[];
}

interface SeededCounterparty {
  id: string;
  legal_name: string;
  credit_score_1_100: number | null;
  risk_tier: 'green' | 'amber' | 'red' | 'unknown';
  credit_utilisation_pct: number | null;
}

function RiskIcon({ level }: { level?: string }) {
  const Icon = level === 'Critical' || level === 'High' ? ShieldX : level === 'Medium' ? ShieldAlert : ShieldCheck;
  const color = RISK_COLORS[level || 'Low']?.icon || 'text-slate-400';
  return <Icon className={`w-5 h-5 ${color}`} />;
}

function ScoreGauge({ score, label }: { score: number; label: string }) {
  const pct = Math.min(100, Math.max(0, score));
  const color = pct >= 70 ? '#10b981' : pct >= 40 ? '#f59e0b' : '#ef4444';
  const circumference = 2 * Math.PI * 38;
  const strokeDashoffset = circumference - (pct / 100) * circumference;

  return (
    <div className="flex flex-col items-center">
      <svg width="90" height="90" className="-rotate-90">
        <circle cx="45" cy="45" r="38" stroke="#1e293b" strokeWidth="6" fill="none" />
        <circle cx="45" cy="45" r="38" stroke={color} strokeWidth="6" fill="none"
          strokeDasharray={circumference} strokeDashoffset={strokeDashoffset}
          strokeLinecap="round" className="transition-all duration-1000" />
      </svg>
      <div className="absolute mt-5 flex flex-col items-center">
        <span className="text-2xl font-bold text-white">{score}</span>
        <span className="text-[9px] text-slate-500 uppercase">{label}</span>
      </div>
    </div>
  );
}

function RatioBar({ label, value, max, unit }: { label: string; value?: number; max: number; unit?: string }) {
  if (value == null) return null;
  const pct = Math.min(100, (Math.abs(value) / max) * 100);
  const color = value > max * 0.7 ? 'bg-red-500' : value > max * 0.4 ? 'bg-amber-500' : 'bg-emerald-500';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="text-white font-medium">{value.toFixed(2)}{unit || 'x'}</span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all duration-700`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function CreditRiskPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [assessments, setAssessments] = useState<CreditAssessment[]>([]);
  const [seededCps, setSeededCps] = useState<SeededCounterparty[]>([]);
  const [loading, setLoading] = useState(true);
  const [assessing, setAssessing] = useState<string | null>(null);
  const [assessingAll, setAssessingAll] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchData = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const [portfolioRes, assessmentsRes, cpsRes] = await Promise.all([
        fetch(`${API_URL}/api/contractiq/insights/credit-risk/portfolio`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_URL}/api/contractiq/insights/credit-risk`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_URL}/api/contractiq/counterparties`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);
      const pData = await portfolioRes.json();
      const aData = await assessmentsRes.json();
      const cData = await cpsRes.json();
      if (pData.data) setPortfolio(pData.data);
      if (aData.data) setAssessments(aData.data);
      if (cData?.data?.items) setSeededCps(cData.data.items);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    const u = getUser();
    if (!u?.email) { router.replace('/'); return; }
    setUser(u);
    fetchData();
  }, [router, fetchData]);

  // Auto-refresh every 60 minutes
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 60 * 60 * 1000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchData]);

  const assessCounterparty = async (name: string) => {
    setAssessing(name);
    try {
      const res = await fetch(`${API_URL}/api/contractiq/insights/credit-risk/assess`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ counterparty_name: name }),
      });
      const data = await res.json();
      if (data.data) {
        setAssessments(prev => [data.data, ...prev.filter(a => a.id !== data.data.id)]);
      }
    } catch { /* silent */ }
    setAssessing(null);
    fetchData();
  };

  const assessAll = async () => {
    setAssessingAll(true);
    try {
      const res = await fetch(`${API_URL}/api/contractiq/insights/credit-risk/assess-all`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
        body: '{}',
      });
      await res.json();
    } catch { /* silent */ }
    setAssessingAll(false);
    fetchData();
  };

  const logout = () => { localStorage.removeItem('contractiq_token'); localStorage.removeItem('contractiq_refresh_token'); localStorage.removeItem('contractiq_user'); router.replace('/'); };

  if (!user || loading) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><Loader2 className="w-8 h-8 text-emerald-400 animate-spin" /></div>;

  const completedAssessments = assessments.filter(a => a.status === 'completed');

  // KPIs are sourced off the seeded counterparty table so the strip stays
  // consistent with the heat map below. Agentic assessments augment it when
  // present, but never gate the headline numbers.
  const cpCount = seededCps.length;
  const assessedCp = seededCps.filter(c => (c.credit_score_1_100 ?? 0) > 0);
  const scoredCount = Math.max(completedAssessments.length, assessedCp.length);
  const avgScore = assessedCp.length > 0
    ? Math.round(assessedCp.reduce((s, c) => s + (c.credit_score_1_100 || 0), 0) / assessedCp.length)
    : (completedAssessments.length > 0
        ? Math.round(completedAssessments.reduce((s, a) => s + (a.credit_score || 0), 0) / completedAssessments.length)
        : 0);
  const highRiskCount = seededCps.filter(c => c.risk_tier === 'red').length
    + completedAssessments.filter(a => a.risk_level === 'High' || a.risk_level === 'Critical').length;
  // No PD column on the seeded counterparty row — derive a heuristic from the
  // 1-100 score (100 - score scaled to a 0-10% band). Agentic assessments
  // override this when they exist because they carry a modelled PD.
  const avgPD = completedAssessments.length > 0
    ? completedAssessments.reduce((s, a) => s + (a.probability_of_default_pct || 0), 0) / completedAssessments.length
    : (assessedCp.length > 0
        ? assessedCp.reduce((s, c) => s + Math.max(0, (100 - (c.credit_score_1_100 || 0)) / 10), 0) / assessedCp.length
        : 0);

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <ShieldCheck className="w-7 h-7 text-emerald-400" />
              Counterparty Credit Risk
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Real-time credit assessment of your contract counterparties
              {autoRefresh && <span className="text-emerald-500/50 ml-2">Auto-refresh ON</span>}
            </p>
          </div>
          <div className="flex gap-2">
            <a
              href="/credit-risk/kyc"
              className="px-3 py-1.5 rounded-lg text-xs flex items-center gap-1.5 bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/20 transition-colors"
            >
              <FileCheck2 className="w-3 h-3" />
              KYC Standard Checks
            </a>
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`px-3 py-1.5 rounded-lg text-xs flex items-center gap-1.5 transition-colors ${autoRefresh ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' : 'bg-slate-800/50 text-slate-400 border border-slate-700'}`}
            >
              <Clock className="w-3 h-3" />
              {autoRefresh ? 'Auto-Refresh' : 'Manual'}
            </button>
            <button
              onClick={assessAll}
              disabled={assessingAll || !portfolio?.unassessed?.length}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-sm font-semibold flex items-center gap-2 hover:shadow-lg hover:shadow-emerald-500/20 disabled:opacity-50 transition-all"
            >
              {assessingAll ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
              {assessingAll ? 'Assessing All...' : 'Assess All Counterparties'}
            </button>
          </div>
        </div>
        <PageExplainer routeKey="credit-risk-counterparty" />

        {/* KYC surface callout */}
        <a
          href="/credit-risk/kyc"
          className="block bg-gradient-to-r from-cyan-500/10 to-emerald-500/10 border border-cyan-500/30 rounded-xl p-4 hover:border-cyan-500/50 transition-colors"
        >
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/20 flex items-center justify-center shrink-0">
              <FileCheck2 className="w-5 h-5 text-cyan-400" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold text-cyan-100">KYC Standard Check Reports</p>
              <p className="text-xs text-slate-400 mt-0.5">
                Full KYC report with sanctions, PEP, UBO, adverse media, enforcement and country-risk screening — all agent-driven, all traceable to primary sources.
              </p>
            </div>
            <ArrowRight className="w-5 h-5 text-cyan-400" />
          </div>
        </a>

        {/* 1. KPI Strip — top */}
        <div className="grid grid-cols-5 gap-4" data-testid="credit-risk-kpis">
          {[
            { label: 'Counterparties', value: cpCount || portfolio?.total_counterparties || 0, icon: Building2, color: 'text-cyan-400', testid: 'kpi-counterparties' },
            { label: 'Assessed', value: scoredCount, icon: CheckCircle2, color: 'text-emerald-400', testid: 'kpi-assessed' },
            { label: 'Avg Credit Score', value: avgScore, icon: BarChart3, color: avgScore >= 60 ? 'text-emerald-400' : avgScore >= 40 ? 'text-amber-400' : 'text-red-400', testid: 'kpi-avg-score' },
            { label: 'High Risk', value: highRiskCount, icon: AlertTriangle, color: highRiskCount > 0 ? 'text-red-400' : 'text-emerald-400', testid: 'kpi-high-risk' },
            { label: 'Avg PD', value: `${avgPD.toFixed(1)}%`, icon: Activity, color: avgPD > 5 ? 'text-red-400' : avgPD > 2 ? 'text-amber-400' : 'text-emerald-400', testid: 'kpi-avg-pd' },
          ].map((kpi) => (
            <div key={kpi.label} data-testid={kpi.testid} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <kpi.icon className={`w-4 h-4 ${kpi.color}`} />
                <span className="text-xs text-slate-400">{kpi.label}</span>
              </div>
              <p className={`text-2xl font-bold ${kpi.color}`}>{kpi.value}</p>
            </div>
          ))}
        </div>

        {/* 2. Compliance warnings — severity-sorted ticker */}
        <ComplianceAlertsTicker />

        {/* 3. Counterparty heat map — drill-down */}
        <TrafficLightDashboard />

        {/* Unassessed Counterparties */}
        {portfolio?.unassessed && portfolio.unassessed.length > 0 && (
          <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <span className="text-sm font-medium text-amber-300">
                {portfolio.unassessed.length} counterpart{portfolio.unassessed.length > 1 ? 'ies' : 'y'} not yet assessed
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {portfolio.unassessed.map((name) => (
                <button
                  key={name}
                  onClick={() => assessCounterparty(name)}
                  disabled={assessing === name}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700 text-xs text-slate-300 hover:border-emerald-500/50 hover:text-white transition-all disabled:opacity-50"
                >
                  {assessing === name ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowRight className="w-3 h-3" />}
                  {name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Assessment Cards */}
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
            Credit Assessments ({completedAssessments.length})
          </h2>

          <AnimatePresence>
            {completedAssessments.map((a) => {
              const colors = RISK_COLORS[a.risk_level || 'Low'] || RISK_COLORS.Low;
              const isExpanded = expandedId === a.id;
              const ratios = a.key_ratios || {};

              return (
                <motion.div
                  key={a.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`border ${colors.border} rounded-xl overflow-hidden`}
                >
                  {/* Header */}
                  <button
                    onClick={() => setExpandedId(isExpanded ? null : a.id)}
                    className="w-full flex items-center gap-4 p-4 hover:bg-slate-800/20 transition-colors text-left"
                  >
                    <RiskIcon level={a.risk_level} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-white">{a.counterparty_name}</span>
                        {a.ticker && <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-cyan-400 font-mono">{a.ticker}</span>}
                        {a.sector && <span className="text-[10px] text-slate-500">{a.sector}</span>}
                      </div>
                      <div className="flex items-center gap-4 mt-1 text-xs text-slate-400">
                        {a.credit_rating && <span>Rating: <strong className="text-white">{a.credit_rating}</strong></span>}
                        {a.altman_z_score != null && (
                          <span>Z-Score: <strong className={Z_ZONE_COLORS[a.z_score_zone || ''] || 'text-white'}>{a.altman_z_score.toFixed(2)}</strong></span>
                        )}
                        {a.probability_of_default_pct != null && (
                          <span>PD: <strong className={a.probability_of_default_pct > 5 ? 'text-red-400' : 'text-white'}>{a.probability_of_default_pct.toFixed(1)}%</strong></span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={`text-xs px-2 py-1 rounded-full ${colors.bg} ${colors.text} font-medium`}>
                        {a.risk_level}
                      </span>
                      {a.credit_score != null && (
                        <div className="relative w-12 h-12">
                          <ScoreGauge score={a.credit_score} label="Score" />
                        </div>
                      )}
                      {isExpanded ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
                    </div>
                  </button>

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="border-t border-slate-800/50 p-5 space-y-5 bg-slate-900/30"
                    >
                      {/* Narrative */}
                      {a.narrative && (
                        <div>
                          <h4 className="text-xs font-semibold text-slate-400 uppercase mb-2">Credit Analysis</h4>
                          <p className="text-sm text-slate-300 leading-relaxed">{a.narrative}</p>
                        </div>
                      )}

                      {/* Key Ratios */}
                      <div className="grid grid-cols-2 gap-6">
                        <div>
                          <h4 className="text-xs font-semibold text-slate-400 uppercase mb-3">Financial Ratios</h4>
                          <div className="space-y-3">
                            <RatioBar label="Debt / Equity" value={ratios.debt_to_equity} max={3} />
                            <RatioBar label="Current Ratio" value={ratios.current_ratio} max={3} />
                            <RatioBar label="Interest Coverage" value={ratios.interest_coverage} max={10} />
                            <RatioBar label="Net Debt / EBITDA" value={ratios.net_debt_to_ebitda} max={6} />
                            <RatioBar label="Return on Equity" value={ratios.return_on_equity} max={30} unit="%" />
                          </div>
                        </div>
                        <div>
                          <h4 className="text-xs font-semibold text-slate-400 uppercase mb-3">Financial Highlights</h4>
                          <div className="space-y-1.5">
                            {(a.financial_highlights || []).map((h, i) => (
                              <div key={i} className="flex items-start gap-2 text-xs">
                                <DollarSign className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" />
                                <span className="text-slate-300">{h}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Risk & Mitigating Factors */}
                      <div className="grid grid-cols-2 gap-6">
                        <div>
                          <h4 className="text-xs font-semibold text-red-400 uppercase mb-2">Risk Factors</h4>
                          <div className="space-y-1.5">
                            {(a.risk_factors || []).map((r, i) => (
                              <div key={i} className="flex items-start gap-2 text-xs">
                                <XCircle className="w-3 h-3 text-red-400 mt-0.5 shrink-0" />
                                <span className="text-slate-300">{r}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div>
                          <h4 className="text-xs font-semibold text-emerald-400 uppercase mb-2">Mitigating Factors</h4>
                          <div className="space-y-1.5">
                            {(a.mitigating_factors || []).map((m, i) => (
                              <div key={i} className="flex items-start gap-2 text-xs">
                                <CheckCircle2 className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" />
                                <span className="text-slate-300">{m}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Credit Mitigation Recommendations */}
                      {a.credit_mitigation_recommendations && a.credit_mitigation_recommendations.length > 0 && (
                        <div>
                          <h4 className="text-xs font-semibold text-cyan-400 uppercase mb-2">Credit Mitigation Recommendations</h4>
                          <div className="bg-slate-800/30 rounded-lg p-3 space-y-2">
                            {a.credit_mitigation_recommendations.map((r, i) => (
                              <div key={i} className="flex items-start gap-2 text-xs">
                                <Target className="w-3 h-3 text-cyan-400 mt-0.5 shrink-0" />
                                <span className="text-slate-300">{r}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Monitoring Triggers */}
                      {a.monitoring_triggers && a.monitoring_triggers.length > 0 && (
                        <div>
                          <h4 className="text-xs font-semibold text-amber-400 uppercase mb-2">Monitoring Triggers</h4>
                          <div className="flex flex-wrap gap-2">
                            {a.monitoring_triggers.map((t, i) => (
                              <span key={i} className="text-[10px] px-2.5 py-1 rounded-full bg-amber-500/5 border border-amber-500/20 text-amber-300">
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Meta */}
                      <div className="flex items-center gap-4 text-[10px] text-slate-500 pt-2 border-t border-slate-800/30">
                        {a.assessed_at && <span>Assessed: {new Date(a.assessed_at).toLocaleString()}</span>}
                        {a.cost_usd != null && <span>Cost: ${a.cost_usd.toFixed(4)}</span>}
                        <button onClick={() => assessCounterparty(a.counterparty_name)} className="text-emerald-500 hover:text-emerald-400 flex items-center gap-1">
                          <RefreshCw className="w-3 h-3" /> Refresh
                        </button>
                      </div>
                    </motion.div>
                  )}
                </motion.div>
              );
            })}
          </AnimatePresence>

          {completedAssessments.length === 0 && !assessingAll && (
            <div className="text-center py-16">
              <ShieldCheck className="w-12 h-12 text-slate-700 mx-auto mb-4" />
              <p className="text-slate-500">No credit assessments yet</p>
              <p className="text-xs text-slate-600 mt-1">Click &quot;Assess All Counterparties&quot; to analyze your portfolio</p>
            </div>
          )}
        </div>

        {/* Data sources — collapsed disclosure at the bottom */}
        <DataSourcePanel
          title="Where data comes from in production"
          description="Counterparty risk + KYC + permits + alerts blend deterministic seed rows with Abenix-agent-driven feeds. Live sources are public registers and free APIs wired through Abenix tools. Premium bureaus and rating agencies are listed for transparency but are not active in this tenant — they require a paid contract."
          groups={[
            {
              category: 'Live in this tenant',
              description: 'Public registers and free APIs wired through Abenix tools',
              sources: [
                { name: 'OFAC SDN List', role: 'US Treasury — daily refresh, primary sanctions list', status: 'live', url: 'https://sanctionslist.ofac.treas.gov' },
                { name: 'EU Consolidated Sanctions', role: 'European Council restrictive measures', status: 'live', url: 'https://data.europa.eu/euodp/en/data/dataset/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions' },
                { name: 'UN Consolidated List', role: 'UN Security Council resolutions', status: 'live', url: 'https://www.un.org/securitycouncil/content/un-sc-consolidated-list' },
                { name: 'HMT (UK) Consolidated List', role: 'UK OFSI sanctions register', status: 'live' },
                { name: 'OpenSanctions', role: 'Aggregator across 100+ lists, used for breadth', status: 'live', url: 'https://www.opensanctions.org' },
                { name: 'FERC eLibrary', role: 'Market-Based Rate authorities + filings', status: 'live', url: 'https://elibrary.ferc.gov' },
                { name: 'EPA ECHO', role: 'Enforcement and compliance history', status: 'live', url: 'https://echo.epa.gov' },
                { name: 'PHMSA Operator Search', role: 'US pipeline operator permit and incident data', status: 'live' },
                { name: 'Companies House', role: 'UK beneficial-ownership and filings', status: 'live', url: 'https://find-and-update.company-information.service.gov.uk' },
                { name: 'Bundesanzeiger', role: 'German company filings and ownership', status: 'live', url: 'https://www.bundesanzeiger.de' },
                { name: 'SEC EDGAR', role: 'US issuer filings — 10-K, 10-Q, 8-K, ownership', status: 'live', url: 'https://www.sec.gov/edgar' },
              ],
            },
            {
              category: 'Unavailable in this tenant — premium contract required',
              description: 'Listed for transparency. Contact procurement to negotiate a subscription.',
              sources: [
                { name: 'S&P Global Ratings', role: 'Long-term issuer ratings via Rating Xpress API', status: 'unavailable', tooltip: 'Requires a paid contract — contact procurement to negotiate.' },
                { name: "Moody's Investors Service", role: "Issuer ratings and outlooks via Moody's API", status: 'unavailable', tooltip: 'Requires a paid contract — contact procurement to negotiate.' },
                { name: 'Fitch Connect', role: 'Fitch sovereign and corporate ratings', status: 'unavailable', tooltip: 'Requires a paid contract — contact procurement to negotiate.' },
                { name: 'World-Check (Refinitiv)', role: 'Premium PEP and adverse-media screening', status: 'unavailable', tooltip: 'Requires a paid contract — contact procurement to negotiate.' },
                { name: 'LexisNexis Risk Solutions', role: 'Identity and PEP fallback', status: 'unavailable', tooltip: 'Requires a paid contract — contact procurement to negotiate.' },
                { name: 'Dun & Bradstreet', role: 'Private-company D-U-N-S and paydex', status: 'unavailable', tooltip: 'Requires a paid contract — contact procurement to negotiate.' },
                { name: 'Creditsafe', role: 'EU SME bureau coverage', status: 'unavailable', tooltip: 'Requires a paid contract — contact procurement to negotiate.' },
                { name: 'GDELT + Reuters Connect', role: 'Adverse-media event stream', status: 'unavailable', tooltip: 'Requires a paid contract — contact procurement to negotiate.' },
              ],
            },
          ]}
        />
      </div>
    </div>
  );
}
