'use client';

/**
 * Clause Library — every clause across the user's portfolio in one
 * searchable, filterable surface. Includes a gap-analysis heatmap that
 * shows which contracts are MISSING which standard clause types so risk
 * officers can spot exposure at a glance.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  BookOpen, Search, Filter, AlertTriangle, ShieldCheck, Layers,
  ChevronRight, Loader2, ExternalLink, FileText, Grid, Upload,
} from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

type Clause = {
  id: string;
  contract_id: string;
  contract_title: string;
  contract_type: string | null;
  clause_number: string | null;
  clause_title: string;
  clause_text: string;
  clause_type: string;
  risk_level: string;
  risk_notes: string | null;
  created_at: string | null;
};

type LibraryPayload = {
  items: Clause[];
  total: number;
  by_type: Record<string, number>;
  by_risk: Record<string, number>;
};

type GapRow = {
  contract_id: string;
  contract_title: string;
  contract_type: string | null;
  present: Record<string, number>;
  missing: string[];
  coverage_pct: number;
};

type RollupRow = {
  clause_type: string;
  present_in: number;
  missing_in: number;
  coverage_pct: number;
};

type GapsPayload = {
  standard_types: string[];
  rows: GapRow[];
  rollup: RollupRow[];
  total_contracts: number;
};

const RISK_STYLE: Record<string, string> = {
  low: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  medium: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  high: 'bg-orange-500/10 text-orange-300 border-orange-500/30',
  critical: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
};

const TYPE_LABEL = (k: string) => k.replace(/_/g, ' ');

export default function ClauseLibraryPage() {
  const [tab, setTab] = useState<'library' | 'gaps'>('library');
  const [data, setData] = useState<LibraryPayload | null>(null);
  const [gaps, setGaps] = useState<GapsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterRisk, setFilterRisk] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    if (filterType) params.set('clause_type', filterType);
    if (filterRisk) params.set('risk_level', filterRisk);
    params.set('limit', '200');
    const [libRes, gapsRes] = await Promise.all([
      apiFetch<{ data: LibraryPayload }>(`${API_URL}/api/contractiq/clauses?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
      apiFetch<{ data: GapsPayload }>(`${API_URL}/api/contractiq/clauses/gaps`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    ]);
    if (libRes.ok) setData(libRes.data?.data || null);
    if (gapsRes.ok) setGaps(gapsRes.data?.data || null);
    setLoading(false);
  }, [search, filterType, filterRisk]);

  useEffect(() => { load(); }, [load]);

  const totals = useMemo(() => {
    if (!data) return { total: 0, types: 0, highRisk: 0 };
    const highRisk = (data.by_risk.high || 0) + (data.by_risk.critical || 0);
    return { total: data.total, types: Object.keys(data.by_type).length, highRisk };
  }, [data]);

  const toggle = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center">
              <BookOpen className="w-5 h-5 text-emerald-400" />
            </div>
            Clause Library
          </h1>
          <p className="text-sm text-slate-400 mt-2 max-w-3xl">
            Every clause the extractor has surfaced across your contracts, in one place. Search by
            keyword, filter by type or risk, or switch to the <strong className="text-white">Gaps</strong> tab to
            see which contracts are missing standard clause types.
          </p>
        </div>

        <PageExplainer routeKey="clauses" />

        {/* KPI strip */}
        <div className="grid grid-cols-4 gap-3">
          <KPI label="Total clauses" value={totals.total} icon={BookOpen} color="text-emerald-400" />
          <KPI label="Clause types" value={totals.types} icon={Layers} color="text-cyan-400" />
          <KPI label="High / critical risk" value={totals.highRisk} icon={AlertTriangle} color="text-rose-400" />
          <KPI label="Contracts" value={gaps?.total_contracts || 0} icon={FileText} color="text-violet-400" />
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 border-b border-slate-800/60">
          {[
            { id: 'library' as const, label: 'Library', icon: BookOpen },
            { id: 'gaps' as const, label: 'Gaps', icon: Grid },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-2 text-sm inline-flex items-center gap-2 border-b-2 ${
                tab === t.id
                  ? 'text-emerald-300 border-emerald-400'
                  : 'text-slate-400 border-transparent hover:text-white'
              }`}
            >
              <t.icon className="w-4 h-4" /> {t.label}
            </button>
          ))}
        </div>

        {tab === 'library' && (
          <>
            {/* Filters */}
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2 bg-slate-800/30 border border-slate-700/50 rounded-lg px-3 py-2 flex-1 min-w-[260px] max-w-md">
                <Search className="w-3.5 h-3.5 text-slate-500" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search clause title, text, or number…"
                  className="flex-1 bg-transparent outline-none text-xs text-white placeholder-slate-500"
                />
              </div>
              <div className="flex items-center gap-2 bg-slate-800/30 border border-slate-700/50 rounded-lg px-3 py-2">
                <Filter className="w-3.5 h-3.5 text-slate-500" />
                <select value={filterType} onChange={e => setFilterType(e.target.value)} className="bg-transparent outline-none text-xs text-white">
                  <option value="">All types</option>
                  {data && Object.entries(data.by_type).sort().map(([k, n]) => (
                    <option key={k} value={k}>{TYPE_LABEL(k)} ({n})</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2 bg-slate-800/30 border border-slate-700/50 rounded-lg px-3 py-2">
                <ShieldCheck className="w-3.5 h-3.5 text-slate-500" />
                <select value={filterRisk} onChange={e => setFilterRisk(e.target.value)} className="bg-transparent outline-none text-xs text-white">
                  <option value="">All risk</option>
                  {['low', 'medium', 'high', 'critical'].map(r => (
                    <option key={r} value={r}>{r}{data?.by_risk[r] != null ? ` (${data.by_risk[r]})` : ''}</option>
                  ))}
                </select>
              </div>
              {(search || filterType || filterRisk) && (
                <button
                  onClick={() => { setSearch(''); setFilterType(''); setFilterRisk(''); }}
                  className="text-[11px] text-slate-400 hover:text-white"
                >Clear filters</button>
              )}
            </div>

            {loading && (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 text-emerald-400 animate-spin" />
              </div>
            )}

            {!loading && data && data.items.length === 0 && data.total === 0 && (
              <div className="bg-slate-800/20 border border-slate-700/40 rounded-2xl p-12 text-center">
                <Upload className="w-14 h-14 text-slate-700 mx-auto mb-3" />
                <p className="text-base font-semibold text-white mb-1">No clauses yet</p>
                <p className="text-sm text-slate-400 mb-5">Upload a contract to populate the clause library.</p>
                <Link href="/upload" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-400 transition-colors">
                  <Upload className="w-4 h-4" /> Upload your first contract
                </Link>
              </div>
            )}

            {!loading && data && data.items.length === 0 && data.total > 0 && (
              <div className="bg-slate-800/20 border border-slate-700/40 rounded-2xl p-12 text-center">
                <BookOpen className="w-14 h-14 text-slate-700 mx-auto mb-3" />
                <p className="text-sm text-slate-400">No clauses match your filters.</p>
              </div>
            )}

            {!loading && data && data.items.length > 0 && (
              <div className="space-y-2">
                {data.items.map(c => {
                  const isOpen = expanded.has(c.id);
                  return (
                    <div key={c.id} className="border border-slate-700/50 rounded-xl bg-slate-900/40 overflow-hidden">
                      <button
                        onClick={() => toggle(c.id)}
                        className="w-full flex items-start gap-3 px-4 py-3 hover:bg-slate-800/30 text-left"
                      >
                        <ChevronRight className={`w-3.5 h-3.5 text-slate-500 mt-1 flex-shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] uppercase tracking-wider text-slate-500">
                              {c.clause_number ? `Clause ${c.clause_number}` : 'Clause'} · {TYPE_LABEL(c.clause_type)}
                            </span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${RISK_STYLE[c.risk_level?.toLowerCase()] || 'bg-slate-500/10 text-slate-400 border-slate-500/30'}`}>
                              {c.risk_level} risk
                            </span>
                          </div>
                          <p className="text-sm font-semibold text-white mt-0.5 truncate">{c.clause_title}</p>
                          <p className="text-[11px] text-slate-500 truncate mt-0.5">
                            From <span className="text-slate-300">{c.contract_title}</span>
                            {c.contract_type && <span> · {c.contract_type}</span>}
                          </p>
                        </div>
                        <Link
                          href={`/contracts/${c.contract_id}`}
                          onClick={e => e.stopPropagation()}
                          className="text-[11px] text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1 mt-1"
                        >
                          contract <ExternalLink className="w-2.5 h-2.5" />
                        </Link>
                      </button>
                      {isOpen && (
                        <div className="px-4 pb-4 pl-10 border-t border-slate-800/60 bg-slate-950/40">
                          <p className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed mt-3">{c.clause_text}</p>
                          {c.risk_notes && (
                            <div className="mt-3 pt-3 border-t border-slate-800/60 flex items-start gap-2">
                              <AlertTriangle className="w-3 h-3 text-amber-400 mt-0.5 flex-shrink-0" />
                              <p className="text-[11px] text-amber-200/80 leading-relaxed">{c.risk_notes}</p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
                <p className="text-[11px] text-slate-500 text-center pt-2">
                  Showing {data.items.length} of {data.total} clause{data.total !== 1 ? 's' : ''}.
                </p>
              </div>
            )}
          </>
        )}

        {tab === 'gaps' && (
          <>
            {loading && (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 text-emerald-400 animate-spin" />
              </div>
            )}

            {!loading && gaps && gaps.standard_types.length === 0 && (
              <div className="bg-slate-800/20 border border-slate-700/40 rounded-2xl p-12 text-center">
                <Upload className="w-14 h-14 text-slate-700 mx-auto mb-3" />
                <p className="text-base font-semibold text-white mb-1">No contracts to analyze yet</p>
                <p className="text-sm text-slate-400 mb-5">Upload at least one contract to run the gap analysis.</p>
                <Link href="/upload" className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-400 transition-colors">
                  <Upload className="w-4 h-4" /> Upload your first contract
                </Link>
              </div>
            )}

            {!loading && gaps && gaps.standard_types.length > 0 && (
              <>
                {/* Per-type roll-up */}
                <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
                    <ShieldCheck className="w-4 h-4 text-cyan-400" /> Coverage by clause type
                  </h3>
                  <p className="text-[11px] text-slate-500 mb-3">
                    Across {gaps.total_contracts} contract{gaps.total_contracts !== 1 ? 's' : ''}. Lower coverage = bigger gap.
                  </p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {gaps.rollup.map(r => {
                      const ratio = r.coverage_pct / 100;
                      const barColor = r.coverage_pct >= 80 ? '#10b981' : r.coverage_pct >= 50 ? '#f59e0b' : '#f43f5e';
                      return (
                        <div key={r.clause_type} className="border border-slate-700/40 bg-slate-900/40 rounded-lg p-3">
                          <div className="flex items-center justify-between mb-1">
                            <p className="text-xs font-semibold text-white truncate">{TYPE_LABEL(r.clause_type)}</p>
                            <span className="text-[11px] text-slate-400">{r.coverage_pct}%</span>
                          </div>
                          <div className="h-1.5 bg-slate-800 rounded overflow-hidden">
                            <div className="h-full" style={{ width: `${ratio * 100}%`, background: barColor }} />
                          </div>
                          <p className="text-[10px] text-slate-500 mt-1">
                            {r.present_in}/{gaps.total_contracts} present · {r.missing_in} missing
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </section>

                {/* Per-contract gap heatmap */}
                <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
                    <Grid className="w-4 h-4 text-cyan-400" /> Per-contract gap heatmap
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="text-xs w-full">
                      <thead className="text-slate-500">
                        <tr>
                          <th className="text-left font-medium px-2 py-1.5 sticky left-0 bg-slate-800/50 backdrop-blur">Contract</th>
                          <th className="text-right font-medium px-2 py-1.5">Coverage</th>
                          {gaps.standard_types.map(t => (
                            <th key={t} className="px-1 py-1.5 text-[10px] font-medium" style={{ minWidth: 60 }}>
                              <div className="rotate-[-45deg] origin-bottom-left whitespace-nowrap">{TYPE_LABEL(t)}</div>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {gaps.rows.map(row => (
                          <tr key={row.contract_id} className="border-t border-slate-800/60 hover:bg-slate-800/20">
                            <td className="px-2 py-1.5 sticky left-0 bg-slate-900/40 backdrop-blur">
                              <Link href={`/contracts/${row.contract_id}`} className="text-cyan-400 hover:text-cyan-300 truncate max-w-[260px] inline-block">
                                {row.contract_title}
                              </Link>
                            </td>
                            <td className="px-2 py-1.5 text-right text-slate-300">{row.coverage_pct}%</td>
                            {gaps.standard_types.map(t => {
                              const count = row.present[t] || 0;
                              const present = count > 0;
                              return (
                                <td key={t} className="px-1 py-1.5 text-center">
                                  <div
                                    className={`mx-auto w-5 h-5 rounded ${
                                      present
                                        ? 'bg-emerald-500/30 border border-emerald-500/50'
                                        : 'bg-rose-500/15 border border-rose-500/40'
                                    }`}
                                    title={`${TYPE_LABEL(t)}: ${present ? `${count} clause${count !== 1 ? 's' : ''}` : 'MISSING'}`}
                                  >
                                    {present && <span className="text-[9px] text-emerald-200 leading-5 block">{count}</span>}
                                  </div>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="flex items-center gap-4 mt-3 text-[11px] text-slate-500">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="w-3 h-3 rounded bg-emerald-500/30 border border-emerald-500/50" /> present
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="w-3 h-3 rounded bg-rose-500/15 border border-rose-500/40" /> missing
                    </span>
                  </div>
                </section>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function KPI({ label, value, icon: Icon, color }: { label: string; value: number; icon: any; color: string }) {
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-1">
        <Icon className={`w-4 h-4 ${color}`} />
        <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
      </div>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  );
}
