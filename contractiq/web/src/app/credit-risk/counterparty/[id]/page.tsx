'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  Building2, ShieldCheck, ShieldAlert, ShieldX, FileText, Award,
  TrendingUp, Calendar, AlertTriangle, CheckCircle2, ArrowLeft, ScrollText,
  RefreshCw, ExternalLink,
} from 'lucide-react';
import { PageExplainer } from '@/components/PageExplainer';

interface Cp {
  id: string; legal_name: string; ticker: string | null; sector: string | null;
  country: string | null; credit_rating: string | null; credit_rating_agency: string | null;
  credit_score_1_100: number | null; risk_tier: 'green' | 'amber' | 'red' | 'unknown';
  credit_limit_usd: number | null; credit_utilisation_pct: number | null;
  last_kyc_at: string | null;
}

interface StmtRow { label: string; [year: string]: any; }
interface RatioRow {
  fiscal_year: number;
  current_ratio: number | null; quick_ratio: number | null;
  debt_to_equity: number | null; interest_coverage: number | null;
  net_margin_pct: number | null; return_on_assets_pct: number | null;
  return_on_equity_pct: number | null; altman_z: number | null;
}
interface FinancialsResp {
  counterparty: Cp;
  years: number[];
  currency: string;
  statement_rows: StmtRow[];
  ratios: RatioRow[];
  source: string | null;
}

interface Permit {
  id: string; license_type: string; issuer: string;
  identifier: string | null; status: string;
  valid_from: string | null; valid_to: string | null;
  days_to_expiry: number | null; notes: string | null;
}

interface ProvenanceRow {
  id: string;
  target_table: string;
  target_row_id: string;
  target_field: string | null;
  source_tool: string;
  source_url: string | null;
  source_identifier: string | null;
  fetched_at: string | null;
  fetched_by_agent: string | null;
  execution_id: string | null;
}

function fmtUsdM(v: any) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}T`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1000).toFixed(1)}B`;
  return `$${n.toFixed(0)}M`;
}

const LINE_LABELS: Record<string, string> = {
  revenue: 'Revenue',
  ebitda: 'EBITDA',
  net_income: 'Net income',
  total_assets: 'Total assets',
  current_assets: 'Current assets',
  cash_and_equivalents: 'Cash & equivalents',
  total_liabilities: 'Total liabilities',
  current_liabilities: 'Current liabilities',
  long_term_debt: 'Long-term debt',
  total_equity: 'Total equity',
  interest_expense: 'Interest expense',
  operating_cash_flow: 'Operating cash flow',
  free_cash_flow: 'Free cash flow',
};

const TIER_STYLE: Record<string, { ring: string; text: string; bg: string; Icon: any; label: string }> = {
  green:   { ring: 'border-emerald-500/40', text: 'text-emerald-300', bg: 'bg-emerald-500/10', Icon: ShieldCheck, label: 'LOW RISK' },
  amber:   { ring: 'border-amber-500/40',   text: 'text-amber-300',   bg: 'bg-amber-500/10',   Icon: ShieldAlert, label: 'MEDIUM RISK' },
  red:     { ring: 'border-rose-500/40',    text: 'text-rose-300',    bg: 'bg-rose-500/10',    Icon: ShieldX,     label: 'HIGH RISK' },
  unknown: { ring: 'border-slate-700',      text: 'text-slate-300',   bg: 'bg-slate-800/30',   Icon: AlertTriangle, label: 'UNRATED' },
};

const PERMIT_STATUS_STYLE: Record<string, string> = {
  active:  'border-emerald-500/30 bg-emerald-500/5 text-emerald-200',
  expired: 'border-rose-500/30 bg-rose-500/5 text-rose-200',
  pending: 'border-amber-500/30 bg-amber-500/5 text-amber-200',
  revoked: 'border-rose-500/30 bg-rose-500/5 text-rose-200',
};

export default function CounterpartyDetailPage() {
  const params = useParams<{ id: string }>();
  const [tab, setTab] = useState<'financials' | 'ratios' | 'permits'>('financials');
  const [data, setData] = useState<FinancialsResp | null>(null);
  const [permits, setPermits] = useState<Permit[] | null>(null);
  const [provenance, setProvenance] = useState<ProvenanceRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);

  const load = async () => {
    try {
      const token = localStorage.getItem('contractiq_token') || '';
      const [f, p, pv] = await Promise.all([
        fetch(`/api/contractiq/counterparties/${params.id}/financials`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`/api/contractiq/counterparties/${params.id}/permits`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`/api/contractiq/counterparties/${params.id}/provenance`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (!f.ok) { setErr(`financials ${f.status}`); return; }
      const fj = await f.json();
      const pj = p.ok ? await p.json() : { data: { items: [] } };
      const pvj = pv.ok ? await pv.json() : { data: { items: [] } };
      setData(fj.data);
      setPermits(pj.data?.items ?? []);
      setProvenance(pvj.data?.items ?? []);
    } catch (e: any) { setErr(String(e)); }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => { if (!cancelled) await load(); })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  const triggerRefresh = async () => {
    setRefreshing(true);
    setRefreshMsg(null);
    try {
      const token = localStorage.getItem('contractiq_token') || '';
      const r = await fetch(`/api/contractiq/counterparties/${params.id}/refresh`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        setRefreshMsg(`Refresh failed: ${j?.detail ?? r.status}`);
      } else {
        const s = j?.data?.summary ?? {};
        setRefreshMsg(`Refreshed via Abenix · ${s.statements ?? 0} statements · ${s.permits ?? 0} permits · ${s.ratings ?? 0} ratings · ${s.provenance ?? 0} provenance rows`);
        await load();
      }
    } catch (e: any) {
      setRefreshMsg(`Refresh error: ${String(e)}`);
    } finally {
      setRefreshing(false);
    }
  };

  const provIndex = useMemo(() => {
    const out: Record<string, ProvenanceRow[]> = {};
    for (const p of provenance) {
      const key = `${p.target_table}:${p.target_field || ''}`;
      (out[key] ??= []).push(p);
    }
    return out;
  }, [provenance]);

  const latestFinancialsProv = useMemo(() => {
    return provenance.find(p => p.target_table === 'contractiq_financial_statements') ?? null;
  }, [provenance]);
  const latestPermitsProv = useMemo(() => {
    return provenance.find(p => p.target_table === 'contractiq_regulatory_permits') ?? null;
  }, [provenance]);
  const latestRatingProv = useMemo(() => {
    return provenance.find(p => p.target_field === 'credit_rating') ?? null;
  }, [provenance]);

  const cp = data?.counterparty;
  const tier = cp ? TIER_STYLE[cp.risk_tier] || TIER_STYLE.unknown : TIER_STYLE.unknown;
  const Ic = tier.Icon;

  const sortedRatios = useMemo(() => (data?.ratios ?? []).slice().sort((a, b) => a.fiscal_year - b.fiscal_year), [data]);

  if (err) return <main className="p-8 text-rose-300 text-sm">Failed to load: {err}</main>;
  if (!data || !cp) return <main className="p-8 text-slate-500 text-sm">Loading counterparty…</main>;

  return (
    <main className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto" data-testid="counterparty-detail">
      <Link href="/credit-risk" className="text-xs text-slate-500 hover:text-white inline-flex items-center gap-1 mb-4">
        <ArrowLeft className="w-3.5 h-3.5" /> Counterparty heat map
      </Link>

      <header className={`rounded-xl border ${tier.ring} ${tier.bg} p-6 mb-6`}>
        <div className="flex items-start gap-4">
          <div className={`w-12 h-12 rounded-xl ${tier.bg} border ${tier.ring} flex items-center justify-center`}>
            <Ic className={`w-6 h-6 ${tier.text}`} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-3 mb-1 flex-wrap">
              <h1 className="text-2xl font-bold text-white truncate">{cp.legal_name}</h1>
              {cp.ticker && <span className="text-xs text-cyan-300 font-mono bg-slate-900 border border-slate-800 px-2 py-0.5 rounded">{cp.ticker}</span>}
              {cp.credit_rating && (
                <span className="text-xs text-slate-200 font-mono bg-slate-900 border border-slate-700 px-2 py-0.5 rounded">
                  {cp.credit_rating}
                  {cp.credit_rating_agency && <span className="text-slate-500"> · {cp.credit_rating_agency}</span>}
                </span>
              )}
              <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${tier.ring} ${tier.text}`}>{tier.label}</span>
              <button
                onClick={triggerRefresh}
                disabled={refreshing}
                data-testid="refresh-from-sources"
                className="ml-auto text-[11px] px-3 py-1.5 rounded border border-emerald-500/40 text-emerald-200 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-40 inline-flex items-center gap-1.5"
              >
                <RefreshCw className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
                {refreshing ? 'Refreshing via Abenix…' : 'Refresh from sources'}
              </button>
              <Link
                href={`/credit-risk/kyc?counterparty=${encodeURIComponent(cp.legal_name)}`}
                data-testid="run-kyc"
                className="text-[11px] px-2.5 py-1 rounded border border-cyan-500/40 text-cyan-200 bg-cyan-500/10 hover:bg-cyan-500/20"
              >
                Run KYC via Abenix agent →
              </Link>
            </div>
            <p className="text-sm text-slate-400">{cp.sector ?? '—'}{cp.country ? ` · ${cp.country}` : ''}</p>
            {refreshMsg && (
              <p className={`text-[11px] mt-2 ${refreshMsg.startsWith('Refresh failed') || refreshMsg.startsWith('Refresh error') ? 'text-rose-300' : 'text-emerald-300'}`}>
                {refreshMsg}
              </p>
            )}
            <div className="mt-4">
              <PageExplainer routeKey="credit-risk-counterparty-detail" />
            </div>
            <p className="text-[10px] text-slate-500 mt-1 italic">Refresh fans out the ciq-counterparty-refresher orchestrator (Abenix) → financial extractor (EDGAR / Companies House / Bundesanzeiger), permit checker (FERC / EPA / PHMSA), rating fetcher (S&amp;P / Moody&apos;s / Fitch). Every write lands in Postgres with a provenance row.</p>
            <div className="grid grid-cols-4 gap-4 mt-4">
              <Stat label="Credit score" value={`${cp.credit_score_1_100 ?? '—'} / 100`} tone={tier.text} />
              <Stat label="Limit" value={cp.credit_limit_usd ? `$${(cp.credit_limit_usd / 1_000_000).toFixed(0)}M` : '—'} />
              <Stat label="Utilisation" value={cp.credit_utilisation_pct != null ? `${cp.credit_utilisation_pct.toFixed(0)}%` : '—'} tone={(cp.credit_utilisation_pct ?? 0) > 80 ? 'text-rose-300' : (cp.credit_utilisation_pct ?? 0) > 60 ? 'text-amber-300' : ''} />
              <Stat label="Last KYC" value={cp.last_kyc_at ? new Date(cp.last_kyc_at).toLocaleDateString() : '—'} />
            </div>
          </div>
        </div>
      </header>

      <div className="flex gap-2 mb-4 border-b border-slate-800 pb-2">
        <TabBtn active={tab === 'financials'} onClick={() => setTab('financials')} Icon={FileText} label="Financials (5-yr)" testId="tab-financials" />
        <TabBtn active={tab === 'ratios'}     onClick={() => setTab('ratios')}     Icon={TrendingUp} label="Ratios + Altman Z" testId="tab-ratios" />
        <TabBtn active={tab === 'permits'}    onClick={() => setTab('permits')}    Icon={Award} label={`Permits (${permits?.length ?? 0})`} testId="tab-permits" />
      </div>

      {tab === 'financials' && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden" data-testid="financials-table">
          <div className="px-4 py-3 border-b border-slate-800 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-white">Unified financial data — USD millions</h2>
            {latestFinancialsProv ? (
              <a href={latestFinancialsProv.source_url ?? '#'} target="_blank" rel="noopener noreferrer"
                 className="text-[10px] text-cyan-300 hover:text-cyan-200 inline-flex items-center gap-1">
                {latestFinancialsProv.source_identifier ?? latestFinancialsProv.source_tool}
                {latestFinancialsProv.source_url && <ExternalLink className="w-2.5 h-2.5" />}
              </a>
            ) : (
              <span className="text-[10px] text-slate-500">{data.source ?? 'Seed data · click Refresh to pull from sources'}</span>
            )}
          </div>
          <table className="w-full text-xs">
            <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium">Line item</th>
                {data.years.map(y => <th key={y} className="text-right px-4 py-2.5 font-medium">FY{y}</th>)}
              </tr>
            </thead>
            <tbody>
              {data.statement_rows.map(row => (
                <tr key={row.label} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-4 py-2 text-slate-300">{LINE_LABELS[row.label] ?? row.label}</td>
                  {data.years.map(y => (
                    <td key={y} className="px-4 py-2 text-right text-slate-200 font-mono">{fmtUsdM(row[String(y)])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'ratios' && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden" data-testid="ratios-table">
          <div className="px-4 py-3 border-b border-slate-800">
            <h2 className="text-sm font-semibold text-white">Derived ratios — deterministic from line items</h2>
            <p className="text-[11px] text-slate-500 mt-0.5">Computed in-DB at seed time; never LLM-guessed.</p>
          </div>
          <table className="w-full text-xs">
            <thead className="bg-slate-900/80 text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium">Ratio</th>
                {sortedRatios.map(r => <th key={r.fiscal_year} className="text-right px-4 py-2.5 font-medium">FY{r.fiscal_year}</th>)}
              </tr>
            </thead>
            <tbody>
              {[
                { key: 'current_ratio', label: 'Current ratio', fmt: (v: any) => v?.toFixed(2) ?? '—' },
                { key: 'quick_ratio', label: 'Quick ratio', fmt: (v: any) => v?.toFixed(2) ?? '—' },
                { key: 'debt_to_equity', label: 'Debt / equity', fmt: (v: any) => v?.toFixed(2) ?? '—' },
                { key: 'interest_coverage', label: 'Interest coverage', fmt: (v: any) => v?.toFixed(1) ?? '—' },
                { key: 'net_margin_pct', label: 'Net margin', fmt: (v: any) => v != null ? `${v.toFixed(1)}%` : '—' },
                { key: 'return_on_assets_pct', label: 'Return on assets', fmt: (v: any) => v != null ? `${v.toFixed(1)}%` : '—' },
                { key: 'return_on_equity_pct', label: 'Return on equity', fmt: (v: any) => v != null ? `${v.toFixed(1)}%` : '—' },
                { key: 'altman_z', label: "Altman Z (distress)", fmt: (v: any) => v != null ? v.toFixed(2) : '—' },
              ].map(r => (
                <tr key={r.key} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-4 py-2 text-slate-300">{r.label}</td>
                  {sortedRatios.map(row => (
                    <td key={row.fiscal_year} className="px-4 py-2 text-right text-slate-200 font-mono">{r.fmt((row as any)[r.key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'permits' && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden" data-testid="permits-panel">
          <div className="px-4 py-3 border-b border-slate-800">
            <h2 className="text-sm font-semibold text-white">Regulatory permits + licenses</h2>
            <p className="text-[11px] text-slate-500 mt-0.5">FERC, RTOs, EPA, BOEM, PHMSA, CFTC/NFA. Expiry → compliance alert.</p>
          </div>
          {(!permits || permits.length === 0) ? (
            <p className="px-4 py-6 text-xs text-slate-500 italic">No permits on file.</p>
          ) : (
            <ul className="divide-y divide-slate-800">
              {permits.map(p => {
                const sStyle = PERMIT_STATUS_STYLE[p.status] || PERMIT_STATUS_STYLE.active;
                const dte = p.days_to_expiry;
                const expiryTone =
                  dte === null ? 'text-slate-400' :
                  dte < 0 ? 'text-rose-300' :
                  dte < 30 ? 'text-rose-300' :
                  dte < 90 ? 'text-amber-300' :
                  'text-slate-300';
                return (
                  <li key={p.id} className="px-4 py-3 flex items-start gap-4 hover:bg-slate-800/30" data-testid={`permit-${p.status}`}>
                    <ScrollText className={`w-4 h-4 mt-0.5 shrink-0 ${expiryTone}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline gap-2">
                        <p className="text-sm font-semibold text-white">{p.license_type.replace(/_/g, ' ')}</p>
                        <span className="text-[10px] text-slate-500 font-mono">{p.issuer}</span>
                        {p.identifier && <span className="text-[10px] text-slate-500 font-mono">· {p.identifier}</span>}
                      </div>
                      {p.notes && <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">{p.notes}</p>}
                      <p className="text-[11px] text-slate-500 mt-1 flex items-center gap-1.5">
                        <Calendar className="w-3 h-3" />
                        {p.valid_from ? `from ${new Date(p.valid_from).toLocaleDateString()} ` : ''}
                        {p.valid_to ? `to ${new Date(p.valid_to).toLocaleDateString()}` : ''}
                        {dte !== null && (
                          <span className={`ml-2 ${expiryTone}`}>
                            ({dte < 0 ? `EXPIRED ${-dte}d ago` : `${dte}d to expiry`})
                          </span>
                        )}
                      </p>
                    </div>
                    <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${sStyle}`}>{p.status}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}
    </main>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`text-base font-bold mt-1 ${tone || 'text-white'}`}>{value}</p>
    </div>
  );
}

function TabBtn({ active, onClick, Icon, label, testId }: { active: boolean; onClick: () => void; Icon: any; label: string; testId: string }) {
  return (
    <button
      onClick={onClick}
      data-testid={testId}
      className={`px-3 py-2 rounded-md text-xs flex items-center gap-1.5 transition-colors ${
        active
          ? 'bg-emerald-500/15 text-emerald-200 border border-emerald-500/40'
          : 'text-slate-400 hover:text-white border border-transparent hover:bg-slate-800/40'
      }`}
    >
      <Icon className="w-3.5 h-3.5" /> {label}
    </button>
  );
}
