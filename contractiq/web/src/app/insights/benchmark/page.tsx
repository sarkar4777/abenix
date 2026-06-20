'use client';


import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { PageExplainer } from '@/components/PageExplainer';
import {
  Scale, Loader2, Sparkles, ChevronLeft, AlertTriangle, CheckCircle2,
  X, ExternalLink, FileText, BookOpen, TrendingUp, TrendingDown, Shield,
  Target, Zap, Info, Copy, Users,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

type Contract = {
  id: string;
  title: string;
  contract_type: string;
  counterparty_a?: string | null;
  counterparty_b?: string | null;
  status: string;
};

type Clause = {
  id: string;
  clause_number?: string | null;
  clause_title: string;
  clause_text: string;
  clause_type: string;
  risk_level: string;
  risk_notes?: string | null;
};

type PeerComparison = {
  contract_title: string;
  stance_vs_target: string;
  one_line_difference: string;
};

type Recommendation = {
  title: string;
  rationale: string;
  priority: 'critical' | 'high' | 'medium' | 'low' | string;
};

type Benchmark = {
  id: string;
  clause_id: string;
  contract_id: string;
  clause_type?: string | null;
  jurisdiction?: string | null;
  stance?: string | null;
  deviation_score?: number | null;
  market_standard_summary?: string | null;
  peer_comparisons?: PeerComparison[] | null;
  recommendations?: Recommendation[] | null;
  suggested_language?: string | null;
  sources?: string[] | null;
  narrative?: string | null;
  status: string;
  cost_usd?: number | null;
  duration_ms?: number | null;
  error_message?: string | null;
  created_at: string;
};

// ── Helpers ────────────────────────────────────────────────────────────

const STANCE_META: Record<string, { color: string; label: string; icon: any; bar: string }> = {
  favourable: { color: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40', label: 'Favourable',  icon: TrendingUp,   bar: 'bg-emerald-500' },
  standard:   { color: 'bg-slate-500/15 text-slate-300 border-slate-500/40',       label: 'Standard',    icon: Shield,       bar: 'bg-slate-500' },
  adverse:    { color: 'bg-rose-500/15 text-rose-300 border-rose-500/40',          label: 'Adverse',     icon: TrendingDown, bar: 'bg-rose-500' },
  aggressive: { color: 'bg-orange-500/15 text-orange-300 border-orange-500/40',    label: 'Aggressive',  icon: Zap,          bar: 'bg-orange-500' },
  lenient:    { color: 'bg-teal-500/15 text-teal-300 border-teal-500/40',          label: 'Lenient',     icon: Info,         bar: 'bg-teal-500' },
};

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'bg-rose-500/10 text-rose-300 border-rose-500/40',
  high:     'bg-orange-500/10 text-orange-300 border-orange-500/40',
  medium:   'bg-amber-500/10 text-amber-300 border-amber-500/40',
  low:      'bg-slate-500/10 text-slate-300 border-slate-500/40',
};

const RISK_COLOR: Record<string, string> = {
  low: 'text-emerald-400',
  medium: 'text-amber-400',
  high: 'text-orange-400',
  critical: 'text-rose-400',
};

function formatClauseType(t?: string | null): string {
  if (!t) return 'Other';
  return t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// ── Page ───────────────────────────────────────────────────────────────

export default function BenchmarkPage() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [selectedContract, setSelectedContract] = useState<string>('');
  const [clauses, setClauses] = useState<Clause[]>([]);
  const [benchmarks, setBenchmarks] = useState<Record<string, Benchmark>>({}); // clause_id → latest benchmark
  const [loading, setLoading] = useState(true);
  const [loadingClauses, setLoadingClauses] = useState(false);
  const [runningFor, setRunningFor] = useState<string | null>(null);
  const [modalBenchmark, setModalBenchmark] = useState<Benchmark | null>(null);
  const [modalClause, setModalClause] = useState<Clause | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jurisdiction, setJurisdiction] = useState<string>('');

  const loadContracts = useCallback(async () => {
    const token = getToken();
    if (!token) { setLoading(false); return; }
    try {
      const [cRes, bRes] = await Promise.all([
        fetch(`${API_URL}/api/contractiq/contracts?limit=100`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/api/contractiq/insights/benchmarks`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      const cJ = await cRes.json();
      const bJ = await bRes.json();
      const analyzed = (cJ.data || []).filter((c: any) => c.status === 'analyzed');
      setContracts(analyzed);
      const map: Record<string, Benchmark> = {};
      for (const b of (bJ.data?.benchmarks || [])) {
        if (!map[b.clause_id]) map[b.clause_id] = b;
      }
      setBenchmarks(map);
      if (analyzed.length > 0 && !selectedContract) {
        setSelectedContract(analyzed[0].id);
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to load contracts');
    }
    setLoading(false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadClauses = useCallback(async (contractId: string) => {
    if (!contractId) return;
    setLoadingClauses(true);
    const token = getToken();
    try {
      const r = await fetch(`${API_URL}/api/contractiq/contracts/${contractId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const j = await r.json();
      setClauses(j.data?.clauses || []);
    } catch {
      setClauses([]);
    }
    setLoadingClauses(false);
  }, []);

  useEffect(() => { loadContracts(); }, [loadContracts]);
  useEffect(() => { if (selectedContract) loadClauses(selectedContract); }, [selectedContract, loadClauses]);

  const runBenchmark = async (clause: Clause) => {
    setError(null);
    setRunningFor(clause.id);
    const token = getToken();
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/benchmarks/run`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ clause_id: clause.id, jurisdiction: jurisdiction || undefined }),
      });
      const j = await r.json();
      if (j.error) {
        setError(j.error.message || 'Benchmark failed');
      } else if (j.data) {
        setBenchmarks(prev => ({ ...prev, [clause.id]: j.data }));
        setModalBenchmark(j.data);
        setModalClause(clause);
      }
    } catch (e: any) {
      setError(e?.message || 'Benchmark request failed');
    } finally {
      setRunningFor(null);
    }
  };

  const retryBenchmark = async (clause: Clause, benchmarkId: string) => {
    setError(null);
    setRunningFor(clause.id);
    const token = getToken();
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/benchmarks/${benchmarkId}/retry`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      });
      const j = await r.json();
      if (j.error) {
        setError(j.error.message || 'Retry failed');
      } else if (j.data) {
        setBenchmarks(prev => ({ ...prev, [clause.id]: j.data }));
        if (j.data.status === 'completed') {
          setModalBenchmark(j.data);
          setModalClause(clause);
        }
      }
    } catch (e: any) {
      setError(e?.message || 'Retry request failed');
    } finally {
      setRunningFor(null);
    }
  };

  const openDetails = (clause: Clause) => {
    const b = benchmarks[clause.id];
    if (!b) return;
    setModalClause(clause);
    setModalBenchmark(b);
  };

  // KPI metrics
  const kpis = useMemo(() => {
    const all = Object.values(benchmarks);
    const completed = all.filter(b => b.status === 'completed');
    const adverse = completed.filter(b => b.stance === 'adverse' || b.stance === 'aggressive').length;
    const favourable = completed.filter(b => b.stance === 'favourable' || b.stance === 'lenient').length;
    const critical = 0 + completed.reduce((n, b) => n + (b.recommendations?.filter(r => r.priority === 'critical').length || 0), 0);
    return {
      total: completed.length,
      adverse,
      favourable,
      critical_recs: critical,
    };
  }, [benchmarks]);

  // Group clauses by type
  const grouped = useMemo(() => {
    const g: Record<string, Clause[]> = {};
    for (const c of clauses) {
      const key = c.clause_type || 'other';
      (g[key] = g[key] || []).push(c);
    }
    return Object.entries(g).sort((a, b) => a[0].localeCompare(b[0]));
  }, [clauses]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-indigo-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6" data-testid="benchmark-page">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <a href="/insights" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-400 mb-2">
            <ChevronLeft className="w-3 h-3" /> Back to Insights Hub
          </a>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500/20 to-violet-500/20 border border-indigo-500/30 flex items-center justify-center">
              <Scale className="w-6 h-6 text-indigo-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-2xl font-bold text-white">Clause Benchmarking</h1>
              <p className="text-xs text-slate-400">
                Benchmark any clause against market standard + your own portfolio via
                <code className="text-indigo-300"> contractiq-clause-benchmarker</code> (Gemini 2.5 Pro)
              </p>
            </div>
          </div>
        </div>
        <PageExplainer routeKey="insights-benchmark" />

        {error && (
          <div className="bg-rose-500/10 border border-rose-500/30 rounded-lg px-4 py-2 text-xs text-rose-300 flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5" />
            {error}
          </div>
        )}

        {/* KPI strip */}
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Benchmarks Run',       value: kpis.total,          icon: Scale,         color: 'text-indigo-400' },
            { label: 'Adverse / Aggressive', value: kpis.adverse,        icon: TrendingDown,  color: kpis.adverse > 0 ? 'text-rose-400' : 'text-slate-400' },
            { label: 'Favourable / Lenient', value: kpis.favourable,     icon: TrendingUp,    color: 'text-emerald-400' },
            { label: 'Critical Recs',        value: kpis.critical_recs,  icon: AlertTriangle, color: kpis.critical_recs > 0 ? 'text-rose-400' : 'text-slate-400' },
          ].map(k => (
            <div key={k.label} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <k.icon className={`w-4 h-4 ${k.color}`} />
                <span className="text-[10px] uppercase tracking-wider text-slate-500">{k.label}</span>
              </div>
              <p className={`text-2xl font-bold ${k.color}`}>{k.value}</p>
            </div>
          ))}
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <FileText className="w-3.5 h-3.5 text-slate-500" />
            <select
              data-testid="contract-picker"
              value={selectedContract}
              onChange={e => setSelectedContract(e.target.value)}
              className="bg-slate-800/40 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-white outline-none min-w-[300px]"
            >
              {contracts.length === 0 && <option value="">No analyzed contracts yet</option>}
              {contracts.map(c => (
                <option key={c.id} value={c.id}>
                  {c.title} ({c.contract_type?.toUpperCase()})
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <Target className="w-3.5 h-3.5 text-slate-500" />
            <input
              value={jurisdiction}
              onChange={e => setJurisdiction(e.target.value)}
              placeholder="Jurisdiction (optional): UK, EU, US, Gulf..."
              className="bg-slate-800/40 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 outline-none w-56"
            />
          </div>
        </div>

        {/* Contracts: empty state */}
        {contracts.length === 0 && (
          <div className="bg-slate-800/20 border border-slate-700/40 rounded-2xl p-12 text-center">
            <Scale className="w-14 h-14 text-slate-700 mx-auto mb-3" />
            <p className="text-sm text-slate-400">Upload and analyze a contract first — then benchmark its clauses.</p>
            <a
              href="/upload"
              className="inline-flex mt-4 items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 text-white text-xs font-semibold"
            >
              Upload a Contract
            </a>
          </div>
        )}

        {/* Clauses loading */}
        {loadingClauses && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading clauses…
          </div>
        )}

        {/* Clauses by type */}
        {!loadingClauses && clauses.length > 0 && (
          <div className="space-y-4">
            {grouped.map(([type, list]) => (
              <div key={type} className="space-y-2">
                <div className="flex items-center gap-2">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
                    {formatClauseType(type)}
                  </h3>
                  <span className="text-[10px] text-slate-500">({list.length})</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {list.map(c => {
                    const b = benchmarks[c.id];
                    const stance = b?.stance && STANCE_META[b.stance];
                    return (
                      <div
                        key={c.id}
                        data-testid="clause-card"
                        className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-3 hover:border-indigo-500/50 transition"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              {c.clause_number && (
                                <span className="text-[10px] text-slate-500 font-mono">{c.clause_number}</span>
                              )}
                              <p className="text-xs font-semibold text-white truncate" title={c.clause_title}>{c.clause_title}</p>
                              <span className={`text-[10px] ${RISK_COLOR[c.risk_level?.toLowerCase()] || 'text-slate-500'}`}>
                                {c.risk_level} risk
                              </span>
                            </div>
                            <p className="text-[11px] text-slate-400 line-clamp-2 mt-1">{c.clause_text}</p>
                          </div>
                          {stance && (
                            <span className={`text-[10px] px-2 py-0.5 rounded-full border whitespace-nowrap flex items-center gap-1 ${stance.color}`}>
                              <stance.icon className="w-2.5 h-2.5" />
                              {stance.label}
                            </span>
                          )}
                        </div>

                        {b?.deviation_score != null && (
                          <div className="mt-2 flex items-center gap-2">
                            <span className="text-[10px] text-slate-500 w-20">Deviation</span>
                            <div className="flex-1 h-1 bg-slate-800 rounded relative">
                              <div className="absolute inset-y-0 w-px bg-slate-500 left-1/2" />
                              <div
                                className={`absolute inset-y-0 ${(b.deviation_score || 0) >= 0 ? 'bg-emerald-500' : 'bg-rose-500'}`}
                                style={{
                                  left: (b.deviation_score || 0) >= 0 ? '50%' : `${50 + (b.deviation_score || 0) * 50}%`,
                                  width: `${Math.abs((b.deviation_score || 0) * 50)}%`,
                                }}
                              />
                            </div>
                            <span className="text-[10px] text-slate-300 w-10 text-right tabular-nums">{(b.deviation_score || 0).toFixed(2)}</span>
                          </div>
                        )}

                        {b?.status === 'failed' && b.error_message && (
                          <div className="mt-2 text-[10px] text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded px-2 py-1 line-clamp-2" title={b.error_message}>
                            {b.error_message}
                          </div>
                        )}

                        <div className="flex items-center gap-2 mt-2">
                          <button
                            onClick={() => runBenchmark(c)}
                            disabled={runningFor === c.id}
                            data-testid="run-benchmark"
                            className="text-[11px] px-2 py-1 rounded-md bg-indigo-500/15 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/25 disabled:opacity-50 inline-flex items-center gap-1"
                          >
                            {runningFor === c.id ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              <Sparkles className="w-3 h-3" />
                            )}
                            {b ? 'Re-benchmark' : 'Benchmark'}
                          </button>
                          {b?.status === 'failed' && (
                            <button
                              onClick={() => retryBenchmark(c, b.id)}
                              disabled={runningFor === c.id}
                              data-testid="retry-benchmark"
                              className="text-[11px] px-2 py-1 rounded-md bg-amber-500/15 border border-amber-500/40 text-amber-300 hover:bg-amber-500/25 disabled:opacity-50 inline-flex items-center gap-1"
                            >
                              {runningFor === c.id ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <AlertTriangle className="w-3 h-3" />
                              )}
                              Retry
                            </button>
                          )}
                          {b && b.status !== 'failed' && (
                            <button
                              onClick={() => openDetails(c)}
                              data-testid="view-benchmark"
                              className="text-[11px] px-2 py-1 rounded-md bg-slate-800/40 border border-slate-700/50 text-slate-300 hover:bg-slate-800/60 inline-flex items-center gap-1"
                            >
                              <BookOpen className="w-3 h-3" /> View details
                            </button>
                          )}
                          {b?.recommendations && b.recommendations.length > 0 && (
                            <span className="text-[10px] text-slate-500">
                              {b.recommendations.length} rec{b.recommendations.length !== 1 ? 's' : ''}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        {modalBenchmark && modalClause && (
          <BenchmarkModal
            benchmark={modalBenchmark}
            clause={modalClause}
            onClose={() => { setModalBenchmark(null); setModalClause(null); }}
          />
        )}
      </div>
    </div>
  );
}

// ── Modal ──────────────────────────────────────────────────────────────

function BenchmarkModal({
  benchmark, clause, onClose,
}: {
  benchmark: Benchmark;
  clause: Clause;
  onClose: () => void;
}) {
  const stance = benchmark.stance ? STANCE_META[benchmark.stance] : null;
  const [copiedLanguage, setCopiedLanguage] = useState(false);

  const copyLanguage = async () => {
    if (!benchmark.suggested_language) return;
    try {
      await navigator.clipboard.writeText(benchmark.suggested_language);
      setCopiedLanguage(true);
      setTimeout(() => setCopiedLanguage(false), 1500);
    } catch {
      // ignore
    }
  };

  return (
    <div
      data-testid="benchmark-modal"
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={e => e.stopPropagation()}
        className="bg-[#0B0F19] border border-slate-700/60 rounded-2xl max-w-4xl w-full max-h-[90vh] flex flex-col shadow-2xl"
      >
        <header className="flex items-start justify-between p-5 border-b border-slate-700/50">
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1 flex items-center gap-2">
              <Scale className="w-3 h-3" /> Clause Benchmark
            </p>
            <h2 className="text-base font-semibold text-white truncate">
              {clause.clause_number && <span className="text-slate-500 mr-2 font-mono">{clause.clause_number}</span>}
              {clause.clause_title}
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              {formatClauseType(clause.clause_type)}
              {benchmark.jurisdiction && ` · ${benchmark.jurisdiction}`}
              {benchmark.duration_ms != null && ` · ${(benchmark.duration_ms / 1000).toFixed(1)}s`}
              {benchmark.cost_usd != null && ` · $${benchmark.cost_usd.toFixed(4)}`}
            </p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-slate-800/60 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {benchmark.status !== 'completed' && (
            <div className="bg-rose-500/10 border border-rose-500/30 rounded-lg p-3 text-xs text-rose-300">
              Status: {benchmark.status}. {benchmark.error_message}
            </div>
          )}

          {/* Stance + deviation score */}
          {stance && (
            <div className={`rounded-xl p-4 border ${stance.color}`}>
              <div className="flex items-center gap-3">
                <stance.icon className="w-5 h-5" />
                <div className="flex-1">
                  <p className="text-sm font-semibold">Stance: {stance.label}</p>
                  {benchmark.deviation_score != null && (
                    <p className="text-[11px] opacity-80">
                      Deviation score: <span className="font-mono">{benchmark.deviation_score.toFixed(2)}</span>
                      {' '}(−1 = maximally adverse to you, +1 = maximally favourable)
                    </p>
                  )}
                </div>
              </div>

              {benchmark.deviation_score != null && (
                <div className="mt-3 relative h-2 bg-slate-800 rounded-full overflow-visible">
                  <div className="absolute inset-y-0 left-1/2 w-px bg-slate-500" />
                  <div
                    className={`absolute inset-y-0 ${stance.bar} rounded-full`}
                    style={{
                      left: benchmark.deviation_score >= 0 ? '50%' : `${50 + benchmark.deviation_score * 50}%`,
                      width: `${Math.abs(benchmark.deviation_score * 50)}%`,
                    }}
                  />
                  <div
                    className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full border-2 border-white"
                    style={{
                      left: `calc(${50 + benchmark.deviation_score * 50}% - 6px)`,
                      background: benchmark.deviation_score >= 0 ? '#10b981' : '#f43f5e',
                    }}
                  />
                  <div className="absolute inset-x-0 -bottom-4 flex justify-between text-[9px] text-slate-500">
                    <span>adverse</span>
                    <span>standard</span>
                    <span>favourable</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Market standard summary */}
          {benchmark.market_standard_summary && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                <BookOpen className="w-3 h-3" /> Market Standard
              </p>
              <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-3">
                <p className="text-xs text-slate-300 leading-relaxed">{benchmark.market_standard_summary}</p>
              </div>
            </div>
          )}

          {/* Narrative */}
          {benchmark.narrative && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Analyst Narrative</p>
              <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-3">
                <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">{benchmark.narrative}</p>
              </div>
            </div>
          )}

          {/* Peer comparison table */}
          {benchmark.peer_comparisons && benchmark.peer_comparisons.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                <Users className="w-3 h-3" /> Peer comparison — your portfolio
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs border border-slate-700/50 rounded-lg overflow-hidden">
                  <thead>
                    <tr className="bg-slate-800/50 text-left text-[10px] uppercase text-slate-500">
                      <th className="py-2 px-3">Contract</th>
                      <th className="py-2 px-3">vs Target</th>
                      <th className="py-2 px-3">Key difference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {benchmark.peer_comparisons.map((p, i) => {
                      const sv = (p.stance_vs_target || '').toLowerCase();
                      const color = sv.includes('tight') || sv.includes('adverse') || sv.includes('strict')
                        ? 'text-rose-400'
                        : sv.includes('loose') || sv.includes('favourable') || sv.includes('soft')
                          ? 'text-emerald-400'
                          : 'text-slate-300';
                      return (
                        <tr key={i} className="border-t border-slate-700/40 hover:bg-slate-800/20">
                          <td className="py-2 px-3 text-white">{p.contract_title}</td>
                          <td className={`py-2 px-3 ${color}`}>{p.stance_vs_target}</td>
                          <td className="py-2 px-3 text-slate-400">{p.one_line_difference}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Recommendations */}
          {benchmark.recommendations && benchmark.recommendations.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3" /> Recommendations
              </p>
              <div className="space-y-2">
                {benchmark.recommendations.map((r, i) => (
                  <div key={i} className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-xs font-semibold text-white flex-1">{r.title}</p>
                      <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${PRIORITY_COLOR[r.priority?.toLowerCase()] || PRIORITY_COLOR.low}`}>
                        {r.priority || 'medium'}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed mt-1">{r.rationale}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Suggested language */}
          {benchmark.suggested_language && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-[10px] uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                  <FileText className="w-3 h-3" /> Suggested redline language
                </p>
                <button
                  onClick={copyLanguage}
                  className="text-[10px] px-2 py-0.5 rounded border border-slate-700/50 hover:border-indigo-500/50 text-slate-300 hover:text-white inline-flex items-center gap-1 transition"
                >
                  <Copy className="w-2.5 h-2.5" />
                  {copiedLanguage ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <div className="bg-indigo-500/5 border border-indigo-500/30 rounded-lg p-3">
                <pre className="text-xs text-slate-200 leading-relaxed whitespace-pre-wrap font-serif">{benchmark.suggested_language}</pre>
              </div>
            </div>
          )}

          {/* Sources */}
          {benchmark.sources && benchmark.sources.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Sources</p>
              <ul className="text-[11px] text-slate-400 space-y-1">
                {benchmark.sources.map((s, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <ExternalLink className="w-3 h-3 mt-0.5 flex-shrink-0" />
                    {s.startsWith('http') ? (
                      <a href={s} target="_blank" rel="noreferrer" className="text-indigo-300 hover:text-indigo-200 break-all">{s}</a>
                    ) : (
                      <span>{s}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Original clause text */}
          <details className="border-t border-slate-700/40 pt-4">
            <summary className="text-[10px] uppercase tracking-wider text-slate-500 cursor-pointer hover:text-white">
              Show original clause text
            </summary>
            <div className="mt-2 bg-slate-900/40 border border-slate-700/50 rounded-lg p-3">
              <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{clause.clause_text}</p>
            </div>
          </details>
        </div>
      </motion.div>
    </div>
  );
}
