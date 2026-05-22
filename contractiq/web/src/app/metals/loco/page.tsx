'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Truck, ChevronLeft, Loader2, Play, Shield, FileCheck2 } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Contract { id: string; title: string; counterparty: string }
interface Loco {
  id: string;
  contract_id: string;
  loco: string;
  reference_price_usd_per_oz: number;
  loco_premium_pct: number;
  loco_premium_usd_per_oz: number;
  comparison: any;
  insurance: any;
  customs_tariff: any;
  chain_of_integrity: any;
  repatriation: any;
  vault_handover: any;
  alerts: string[];
  recommendations: string[];
}

export default function LocoPage() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [rows, setRows] = useState<Loco[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    const [cRes, rRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/contracts`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/metals/loco`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setContracts((await cRes.json()).data || []);
    setRows((await rRes.json()).data || []);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const run = async (id: string) => {
    setRunning(id);
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/metals/contracts/${id}/loco-analyze`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      await load();
    } finally { setRunning(null); }
  };

  const byContract = new Map<string, Loco>();
  rows.forEach((r) => { if (!byContract.has(r.contract_id)) byContract.set(r.contract_id, r); });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-7xl mx-auto p-6 lg:p-10">
        <Link href="/metals" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 mb-4">
          <ChevronLeft className="w-3.5 h-3.5" /> Back to metals
        </Link>
        <div className="flex items-center gap-3 mb-6">
          <Truck className="w-7 h-7 text-cyan-300" />
          <div>
            <h1 className="text-2xl font-bold text-white">Loco + Delivery</h1>
            <p className="text-sm text-slate-400">Zurich / London / NY / Shanghai · premium vs benchmark · insurance · customs · chain of integrity.</p>
          </div>
        </div>

        {loading ? <Loader2 className="w-6 h-6 animate-spin text-slate-500 mx-auto block mt-20" /> : (
          <div className="space-y-3">
            {contracts.map((c) => {
              const r = byContract.get(c.id);
              const isOpen = open === c.id;
              return (
                <div key={c.id} className="rounded-xl bg-slate-900/60 border border-slate-800/80">
                  <div className="p-4 flex items-center justify-between">
                    <div className="flex-1">
                      <div className="text-sm font-semibold text-white">{c.title}</div>
                      <div className="text-xs text-slate-500 mt-0.5">{c.counterparty}</div>
                    </div>
                    {r && (
                      <div className="flex items-center gap-4 mr-3">
                        <div className="px-2 py-1 rounded-md text-[10px] uppercase bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">loco {r.loco}</div>
                        <div className="text-right">
                          <div className="text-[9px] uppercase text-slate-500">Premium</div>
                          <div className="text-sm font-bold text-cyan-200">{r.loco_premium_pct?.toFixed(2)}% · ${r.loco_premium_usd_per_oz?.toFixed(2)}/oz</div>
                        </div>
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      <button onClick={() => run(c.id)} disabled={running === c.id}
                        className="px-3 py-1.5 text-xs rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-50 flex items-center gap-1.5">
                        {running === c.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                        {r ? 'Re-analyze' : 'Analyze'}
                      </button>
                      {r && (
                        <button onClick={() => setOpen(isOpen ? null : c.id)} className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700">
                          {isOpen ? 'Hide' : 'Detail'}
                        </button>
                      )}
                    </div>
                  </div>
                  {isOpen && r && (
                    <div className="px-4 pb-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                      <Section title="Insurance" icon={Shield} data={r.insurance} />
                      <Section title="Customs & tariff" icon={FileCheck2} data={r.customs_tariff} />
                      <Section title="Chain of integrity" icon={FileCheck2} data={r.chain_of_integrity} />
                      <Section title="Repatriation" icon={Truck} data={r.repatriation} />
                      <Section title="Vault handover" icon={FileCheck2} data={r.vault_handover} />
                      {r.comparison && (
                        <Section title="vs other loco" icon={Truck} data={r.comparison} />
                      )}
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

function Section({ title, icon: Icon, data }: { title: string; icon: any; data: any }) {
  if (!data) return null;
  const entries = Object.entries(data);
  return (
    <div className="p-3 rounded-md bg-slate-800/40 border border-slate-800">
      <div className="flex items-center gap-1.5 mb-2 text-[10px] uppercase tracking-wide text-slate-500">
        <Icon className="w-3.5 h-3.5" /> {title}
      </div>
      <div className="space-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-start justify-between text-xs">
            <span className="text-slate-400">{k.replace(/_/g, ' ')}</span>
            <span className="text-slate-200 text-right ml-2 max-w-[60%] truncate" title={String(v)}>
              {typeof v === 'object' ? JSON.stringify(v) : String(v)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
