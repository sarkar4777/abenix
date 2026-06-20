'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Diamond, ChevronLeft, Loader2, Play, FileText } from 'lucide-react';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Contract {
  id: string;
  title: string;
  counterparty: string;
  status: string;
  contract_value_usd: number | null;
}

interface Extraction {
  id: string;
  contract_id: string;
  material: string;
  material_form: string;
  fineness_min: number;
  bar_weight_oz: number;
  good_delivery_standard: string;
  accepted_refiners: string[];
  loco: string;
  pricing_reference: string;
  settlement_currency: string;
  assay_method: string;
  assay_tolerance_pct: number;
  umpire_clause_present: boolean;
  vaulting_type: string;
  insurance_min_coverage_pct: number;
  payable_percent_au: number;
  payable_percent_ag: number;
  treatment_charge_per_tonne_usd: number;
  refining_charge_per_oz_usd: number;
  russian_origin_excluded: boolean;
  ofac_clause_present: boolean;
  confidence: number;
  created_at: string;
}

export default function MetalsExtractPage() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [extractions, setExtractions] = useState<Extraction[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const [cRes, eRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/contracts`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/metals/extractions`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setContracts((await cRes.json()).data || []);
    setExtractions((await eRes.json()).data || []);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const run = async (contractId: string) => {
    setRunning(contractId);
    setToast(null);
    const token = getToken();
    try {
      const res = await fetch(`${API_URL}/api/contractiq/metals/contracts/${contractId}/extract`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const j = await res.json();
      if (j.data) setToast('Extraction complete');
      else setToast(j.error?.message || 'Extraction failed');
      await load();
    } catch (e: any) {
      setToast(e.message || 'Extraction failed');
    } finally {
      setRunning(null);
    }
  };

  const byContract = new Map<string, Extraction>();
  extractions.forEach((e) => { if (!byContract.has(e.contract_id)) byContract.set(e.contract_id, e); });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <Link href="/metals" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 mb-4">
          <ChevronLeft className="w-3.5 h-3.5" /> Back to metals
        </Link>

        <div className="flex items-center gap-3 mb-6">
          <Diamond className="w-7 h-7 text-amber-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Metals Extraction</h1>
            <p className="text-sm text-slate-400">Second-pass extraction of metals-specific fields per contract.</p>
          </div>
        </div>
        <div className="mb-4"><PageExplainer routeKey="metals-extract" /></div>

        {toast && (
          <div className="mb-4 p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-sm text-cyan-200">{toast}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-slate-500" /></div>
        ) : (
          <div className="space-y-3">
            {contracts.length === 0 && (
              <div className="text-center py-16 text-sm text-slate-500">
                No contracts yet. <Link href="/upload" className="text-cyan-400 hover:underline">Upload one</Link> first, then come back to extract metals fields.
              </div>
            )}
            {contracts.map((c) => {
              const e = byContract.get(c.id);
              return (
                <div key={c.id} className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <Link href={`/contracts/${c.id}`} className="text-sm font-semibold text-white hover:underline">
                        {c.title}
                      </Link>
                      <div className="text-xs text-slate-500 mt-0.5">{c.counterparty}</div>
                    </div>
                    <button
                      onClick={() => run(c.id)}
                      disabled={running === c.id}
                      className="px-3 py-1.5 text-xs rounded-lg bg-amber-500/20 border border-amber-500/40 text-amber-200 hover:bg-amber-500/30 disabled:opacity-50 flex items-center gap-1.5"
                    >
                      {running === c.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                      {e ? 'Re-extract' : 'Extract'}
                    </button>
                  </div>
                  {e ? (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                      <Field label="Material" value={`${e.material} / ${e.material_form}`} />
                      <Field label="Fineness" value={e.fineness_min != null ? e.fineness_min.toFixed(4) : 'n/a'} />
                      <Field label="Bar weight" value={e.bar_weight_oz ? `${e.bar_weight_oz} oz` : 'n/a'} />
                      <Field label="GD standard" value={e.good_delivery_standard || 'n/a'} />
                      <Field label="Loco" value={e.loco || 'n/a'} />
                      <Field label="Pricing ref" value={e.pricing_reference || 'n/a'} />
                      <Field label="Settlement" value={e.settlement_currency || 'n/a'} />
                      <Field label="Assay" value={`${e.assay_method || 'n/a'} ±${e.assay_tolerance_pct ?? '?'}%`} />
                      <Field label="Vaulting" value={e.vaulting_type || 'n/a'} />
                      <Field label="Insurance" value={e.insurance_min_coverage_pct ? `${e.insurance_min_coverage_pct}%` : 'n/a'} />
                      <Field label="Umpire clause" value={e.umpire_clause_present ? 'yes' : 'no'} />
                      <Field label="Russian-origin excluded" value={e.russian_origin_excluded ? 'yes' : 'no'} />
                      <Field label="OFAC clause" value={e.ofac_clause_present ? 'yes' : 'no'} />
                      <Field label="Refiners accepted" value={e.accepted_refiners?.length ? e.accepted_refiners.length.toString() : '0'} />
                      {(e.treatment_charge_per_tonne_usd ?? 0) > 0 && (
                        <Field label="TC / RC" value={`$${e.treatment_charge_per_tonne_usd}/t · $${e.refining_charge_per_oz_usd}/oz`} />
                      )}
                      <Field label="Confidence" value={e.confidence != null ? e.confidence.toFixed(2) : 'n/a'} />
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500 flex items-center gap-1.5">
                      <FileText className="w-3.5 h-3.5" /> No metals extraction yet
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-2 rounded-md bg-slate-800/40 border border-slate-800">
      <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-xs text-slate-200 font-medium truncate" title={value}>{value}</div>
    </div>
  );
}
