'use client';

import { useMemo, useState } from 'react';
import { BrainCircuit, MessageSquare, PenLine, ShieldCheck, Sparkles } from 'lucide-react';

interface ShapDriver { feature: string; value: number; pretty: string; }

const FORECASTS = [
  { id: 'f-001', subject: 'TTF M+1', point: 34.82, p10: 33.10, p90: 36.51, model: 'price_fairvalue_gas_hubs', confidence: 0.91 },
  { id: 'f-002', subject: 'Residential 14d ahead', point: 318.4, p10: 296, p90: 341, model: 'offtake_residential', confidence: 0.86 },
  { id: 'f-003', subject: 'Storage cycling Q1', point: 11.2, p10: 8.7, p90: 13.5, model: 'offtake_storage_cycling', confidence: 0.78 },
  { id: 'f-004', subject: 'DE-Power Cal+1', point: 95.6, p10: 88.3, p90: 102.9, model: 'price_fairvalue_power_hubs', confidence: 0.83 },
];

const DRIVERS_BY_FORECAST: Record<string, ShapDriver[]> = {
  'f-001': [
    { feature: 'storage_inj_pct',       value:  0.42, pretty: '+0.42 €/MWh — storage net injection 92%' },
    { feature: 'hdd_7d_forecast',       value:  0.31, pretty: '+0.31 €/MWh — HDD 14% above norm' },
    { feature: 'eua_spot',              value:  0.18, pretty: '+0.18 €/MWh — EUA at €87/t' },
    { feature: 'ttf_the_basis',         value: -0.14, pretty: '-0.14 €/MWh — basis tightening' },
    { feature: 'lng_send_out_dwt',      value: -0.09, pretty: '-0.09 €/MWh — slot calendar full' },
  ],
  'f-002': [
    { feature: 'hdd_7d_forecast',       value:  12.4, pretty: '+12.4 GWh — HDD 14% above norm' },
    { feature: 'weekend_indicator',     value:  -8.1, pretty: '-8.1 GWh — weekend in 4d' },
    { feature: 'customer_mix_shift',    value:   4.6, pretty: '+4.6 GWh — Mega acquisition lift' },
    { feature: 'price_elasticity_hat',  value:  -3.2, pretty: '-3.2 GWh — retail tariff +2.1%' },
    { feature: 'retention_churn_drag',  value:  -2.8, pretty: '-2.8 GWh — churn cohort exit' },
  ],
  'f-003': [
    { feature: 'front_winter_spread',   value:  4.6, pretty: '+4.6 €/MWh — spread €7.4 wider than 5y avg' },
    { feature: 'days_to_withdrawal',    value:  2.1, pretty: '+2.1 €/MWh — 31 days to switch' },
    { feature: 'inj_capacity_left',     value:  1.7, pretty: '+1.7 €/MWh — 18% capacity left' },
    { feature: 'linepack_constraint',   value: -1.4, pretty: '-1.4 €/MWh — DE linepack tight' },
    { feature: 'ttf_the_basis',         value:  0.6, pretty: '+0.6 €/MWh — favours HU storage cycling' },
  ],
  'f-004': [
    { feature: 'clean_spark_spread',    value:  3.8, pretty: '+3.8 €/MWh — clean-spark €18 stronger' },
    { feature: 'wind_de_7d_forecast',   value: -2.9, pretty: '-2.9 €/MWh — wind 18% above norm' },
    { feature: 'industrial_pmi',        value:  2.1, pretty: '+2.1 €/MWh — PMI 52.4' },
    { feature: 'fr_de_basis',           value:  1.6, pretty: '+1.6 €/MWh — FR-DE basis +€3.20' },
    { feature: 'co2_eua',               value:  1.4, pretty: '+1.4 €/MWh — EUA at €87/t' },
  ],
};

const ANNOTATIONS_BY_FORECAST: Record<string, { author: string; ts: string; note: string }[]> = {
  'f-001': [
    { author: 'A. Bauer',   ts: '2 h ago', note: 'EUA breakout above €85 driving structural lift; expect to fade if EUA flattens.' },
    { author: 'M. Horváth', ts: '38 m ago', note: 'Storage 92% but bookings for Q1 already de-risked; demand side is the swing factor here.' },
  ],
  'f-002': [],
  'f-003': [
    { author: 'A. Bauer', ts: '1 h ago', note: 'Spread €7.4 above 5y — extrinsic value is real but liquidity at the back end is thin.' },
  ],
  'f-004': [],
};

export default function WorkbenchPage() {
  const [activeId, setActiveId] = useState(FORECASTS[0].id);
  const [override, setOverride] = useState<string>('');
  const [reason, setReason] = useState<string>('');
  const [overrideSubmitted, setOverrideSubmitted] = useState(false);
  const [annotationDraft, setAnnotationDraft] = useState('');

  const active = useMemo(() => FORECASTS.find(f => f.id === activeId)!, [activeId]);
  const drivers = DRIVERS_BY_FORECAST[active.id];
  const annotations = ANNOTATIONS_BY_FORECAST[active.id];

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <BrainCircuit className="w-7 h-7 text-emerald-400" />
          <h1 className="text-3xl font-bold text-white">Analyst Workbench</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          SHAP / LIME explainability, sensitivity sliders, pinned annotations, and analyst overrides that route through
          the Approvals HITL gate.
        </p>
      </header>

      <div className="grid grid-cols-12 gap-6">
        <aside className="col-span-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-3">Recent forecasts</p>
          <ul className="space-y-1">
            {FORECASTS.map(f => (
              <li key={f.id}>
                <button
                  onClick={() => { setActiveId(f.id); setOverride(''); setReason(''); setOverrideSubmitted(false); }}
                  className={`w-full text-left p-2.5 rounded-md border text-xs ${
                    activeId === f.id
                      ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-100'
                      : 'bg-slate-950/40 border-slate-800 hover:bg-slate-800/40 text-slate-300'
                  }`}
                >
                  <p className="font-semibold">{f.subject}</p>
                  <p className="text-[10px] text-slate-500 mt-1 font-mono">{f.point.toFixed(2)} · conf {(f.confidence * 100).toFixed(0)}%</p>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="col-span-9 space-y-6">
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
            <div className="flex items-baseline justify-between mb-2">
              <h2 className="text-lg font-semibold text-white">{active.subject}</h2>
              <span className="text-[10px] uppercase tracking-wider text-slate-500 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded">{active.model}</span>
            </div>
            <p className="text-xs text-slate-500 mb-4">
              Point estimate <span className="font-mono text-emerald-300 text-sm">{active.point.toFixed(2)}</span> ·
              P10 <span className="font-mono text-slate-400">{active.p10.toFixed(1)}</span> ·
              P90 <span className="font-mono text-slate-400">{active.p90.toFixed(1)}</span> ·
              confidence <span className="font-mono text-cyan-300">{(active.confidence * 100).toFixed(0)}%</span>
            </p>

            <h3 className="text-xs font-semibold text-white mb-3 flex items-center gap-1.5"><Sparkles className="w-3 h-3 text-amber-400" /> SHAP driver waterfall</h3>
            <div className="space-y-3">
              {drivers.map(d => {
                const pos = d.value >= 0;
                const w = Math.min(80, Math.abs(d.value) * 6);
                return (
                  <div key={d.feature}>
                    <div className="flex items-baseline justify-between mb-1">
                      <span className="text-xs text-slate-300">{d.pretty}</span>
                      <span className={`text-xs font-mono ${pos ? 'text-emerald-400' : 'text-rose-400'}`}>{pos ? '+' : ''}{d.value.toFixed(2)}</span>
                    </div>
                    <div className="h-1.5 bg-slate-800 rounded overflow-hidden">
                      <div className={`h-full ${pos ? 'bg-emerald-500/70' : 'bg-rose-500/70'}`} style={{ width: `${w}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-6">
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
              <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5"><MessageSquare className="w-3.5 h-3.5 text-cyan-400" /> Pinned annotations</h3>
              {annotations.length === 0 ? (
                <p className="text-xs text-slate-500 italic mb-3">No annotations yet on this forecast.</p>
              ) : (
                <ul className="space-y-2.5 mb-3">
                  {annotations.map((a, i) => (
                    <li key={i} className="text-xs">
                      <p className="text-slate-200">{a.note}</p>
                      <p className="text-[10px] text-slate-500 mt-1">{a.author} · {a.ts}</p>
                    </li>
                  ))}
                </ul>
              )}
              <textarea
                value={annotationDraft}
                onChange={e => setAnnotationDraft(e.target.value)}
                placeholder="Add an annotation..."
                rows={2}
                className="w-full bg-slate-950/60 border border-slate-800 rounded-md p-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/40"
              />
              <button
                onClick={() => { if (annotationDraft.trim()) { alert('Annotation pinned to forecast ' + active.id); setAnnotationDraft(''); } }}
                disabled={!annotationDraft.trim()}
                className="mt-2 w-full px-3 py-1.5 text-xs bg-cyan-600/20 text-cyan-200 border border-cyan-500/30 rounded-md hover:bg-cyan-600/30 disabled:opacity-40"
              >
                Pin annotation
              </button>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
              <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-1.5"><PenLine className="w-3.5 h-3.5 text-amber-400" /> Override the model</h3>
              {overrideSubmitted ? (
                <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs">
                  <p className="text-emerald-200 font-semibold flex items-center gap-1.5"><ShieldCheck className="w-3.5 h-3.5" /> Override routed to Approvals</p>
                  <p className="text-slate-400 mt-1.5">Reviewer: head of {active.subject.split(' ')[0]} desk. Decision will appear in your inbox.</p>
                </div>
              ) : (
                <>
                  <p className="text-xs text-slate-500 mb-3">An override creates a HITL approval task — never silently replaces the model.</p>
                  <label className="block">
                    <span className="text-[11px] text-slate-500 uppercase tracking-wider">Your value</span>
                    <input
                      type="number"
                      step="0.01"
                      value={override}
                      onChange={e => setOverride(e.target.value)}
                      placeholder={active.point.toFixed(2)}
                      className="mt-1 w-full bg-slate-950/60 border border-slate-800 rounded-md p-2 text-xs text-white font-mono focus:outline-none focus:border-amber-500/40"
                    />
                  </label>
                  <label className="block mt-3">
                    <span className="text-[11px] text-slate-500 uppercase tracking-wider">Rationale</span>
                    <textarea
                      value={reason}
                      onChange={e => setReason(e.target.value)}
                      rows={2}
                      placeholder="What did the model miss?"
                      className="mt-1 w-full bg-slate-950/60 border border-slate-800 rounded-md p-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-amber-500/40"
                    />
                  </label>
                  <button
                    onClick={() => { if (override && reason.trim()) setOverrideSubmitted(true); }}
                    disabled={!override || !reason.trim()}
                    className="mt-3 w-full px-3 py-1.5 text-xs bg-amber-600/20 text-amber-200 border border-amber-500/30 rounded-md hover:bg-amber-600/30 disabled:opacity-40"
                  >
                    Submit override → Approvals
                  </button>
                </>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
