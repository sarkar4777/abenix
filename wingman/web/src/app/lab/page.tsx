'use client';

import { useState } from 'react';
import {
  Anchor, Ship, Gauge, Database, TrendingUp, MapPin, Wrench,
  Calculator, ArrowRight, Sparkles, ChevronDown,
} from 'lucide-react';
import HeroBar from '../components/HeroBar';
import ExplainerPanel from '../components/ExplainerPanel';
import type { ExplainerSpec } from '../components/ExplainerPanel';

const LAB_EXPLAINER: ExplainerSpec = {
  pageKey: 'lab',
  what:
    'The Market & Freight Lab is the interactive surface for every market-and-freight ' +
    'platform tool Wingman uses. Click any card to see what the tool returns, what ' +
    'inputs it takes, and how the Mispricing Lens consumes it.',
  how:
    'Each card is a thin client over a generic Abenix platform tool. The same tool — same ' +
    'inputs, same outputs — is callable from any agent or pipeline you build in the ' +
    'Builder. The data shown is the curated registry the tool ships with; live ' +
    'values (Yahoo, Baltic-subscription, Worldscale daily quotes) come in when the ' +
    'tool fires inside an agent run.',
  tools: [
    'vessel_specs', 'freight_baltic_blpg', 'freight_worldscale',
    'port_constraints', 'refined_products_forwards', 'options_data',
  ],
  models: [
    { name: 'wingman-mispricing-fairvalue', role: 'consumes Baltic + Worldscale + vessel_specs as the freight-quality features in the 15-feature vector' },
  ],
  inputs: [
    'Vessel class · product · UN/LOCODE port · WS route · BLPG route · futures symbol',
  ],
  outputs: [
    'Spec card, density value, m^3 ↔ MT conversion, freight $/MT, port compatibility verdict, futures curve, options IV + skew',
  ],
};

// ── Curated demo data (mirrors what the tools return) ──────────────────

const VESSELS = [
  { cls: 'VLGC',     family: 'LPG', cbm: 84_000,  mt: 44_000, speed: 16.0, burn: 38, loa: 230, beam: 36.6, draught: 11.7, air: 32 },
  { cls: 'MGC',      family: 'LPG', cbm: 38_000,  mt: 19_500, speed: 15.5, burn: 26, loa: 182, beam: 28.4, draught: 10.6, air: 28 },
  { cls: 'LGC',      family: 'LPG', cbm: 60_000,  mt: 31_000, speed: 16.0, burn: 32, loa: 210, beam: 32.0, draught: 11.2, air: 30 },
  { cls: 'SGC',      family: 'LPG', cbm: 12_000,  mt: 6_200,  speed: 14.5, burn: 14, loa: 130, beam: 21.5, draught: 7.8,  air: 20 },
  { cls: 'VLCC',     family: 'CPP', cbm: 330_000, mt: 0,      speed: 15.5, burn: 72, loa: 333, beam: 60.0, draught: 22.5, air: 47 },
  { cls: 'Suezmax',  family: 'CPP', cbm: 175_000, mt: 0,      speed: 14.5, burn: 55, loa: 274, beam: 48.0, draught: 16.5, air: 39 },
  { cls: 'Aframax',  family: 'CPP', cbm: 130_000, mt: 0,      speed: 14.5, burn: 45, loa: 245, beam: 42.0, draught: 14.5, air: 36 },
  { cls: 'LR2',      family: 'CPP', cbm: 130_000, mt: 0,      speed: 14.5, burn: 41, loa: 245, beam: 42.0, draught: 14.0, air: 35 },
  { cls: 'LR1',      family: 'CPP', cbm: 75_000,  mt: 0,      speed: 14.5, burn: 32, loa: 228, beam: 32.2, draught: 12.5, air: 32 },
  { cls: 'MR2',      family: 'CPP', cbm: 55_000,  mt: 0,      speed: 14.0, burn: 26, loa: 183, beam: 32.2, draught: 11.0, air: 30 },
  { cls: 'MR1',      family: 'CPP', cbm: 40_000,  mt: 0,      speed: 14.0, burn: 22, loa: 175, beam: 27.5, draught: 10.4, air: 28 },
  { cls: 'Handysize',family: 'CPP', cbm: 32_000,  mt: 0,      speed: 13.5, burn: 18, loa: 150, beam: 23.5, draught: 9.5,  air: 25 },
];

const DENSITIES = [
  { product: 'propane',     kg_l: 0.508, bbl_per_mt: 12.40, note: 'C3H8 liquid; storage temp ~-42 °C' },
  { product: 'butane',      kg_l: 0.580, bbl_per_mt: 10.84, note: 'n-C4H10 liquid' },
  { product: 'ammonia',     kg_l: 0.682, bbl_per_mt: 9.16,  note: 'NH3 liquid' },
  { product: 'ethane',      kg_l: 0.546, bbl_per_mt: null,  note: 'C2H6 cryogenic' },
  { product: 'lpg_mix',     kg_l: 0.540, bbl_per_mt: 11.65, note: '60/40 propane/butane export blend' },
  { product: 'naphtha',     kg_l: 0.720, bbl_per_mt: 8.90,  note: 'Light naphtha' },
  { product: 'gasoline',    kg_l: 0.740, bbl_per_mt: 8.50,  note: 'RBOB-grade motor gasoline' },
  { product: 'jet',         kg_l: 0.810, bbl_per_mt: 7.90,  note: 'Jet A-1 / kerosene' },
  { product: 'ulsd',        kg_l: 0.840, bbl_per_mt: 7.46,  note: 'Ultra-low-sulphur diesel' },
  { product: 'gasoil',      kg_l: 0.860, bbl_per_mt: 7.45,  note: 'Heating oil / gasoil' },
  { product: 'fuel_oil',    kg_l: 0.950, bbl_per_mt: 6.35,  note: 'VLSFO / HFO 380cSt' },
  { product: 'crude_wti',   kg_l: 0.825, bbl_per_mt: 7.45,  note: 'WTI ~39.6 API' },
  { product: 'crude_brent', kg_l: 0.835, bbl_per_mt: 7.45,  note: 'Brent blend ~38 API' },
  { product: 'methanol',    kg_l: 0.792, bbl_per_mt: null,  note: 'CH3OH' },
];

const BLPG_ROUTES = [
  { code: 'BLPG1', label: 'Ras Tanura → Chiba (MEG → Japan)',      mid: 71.50, low: 64.00, high: 79.00, vessel: 'VLGC 44kt propane' },
  { code: 'BLPG2', label: 'Houston → Flushing (USGC → NWE)',       mid: 49.20, low: 43.50, high: 56.00, vessel: 'VLGC 44kt propane' },
  { code: 'BLPG3', label: 'Houston → Chiba via Panama (USGC → FE)', mid: 132.0, low: 118.0, high: 148.0, vessel: 'VLGC 44kt propane' },
];

const WS_ROUTES = [
  { code: 'TC1',  label: 'MEG → Japan naphtha LR2',  cargo_mt: 75_000, flat: 17.45, product: 'naphtha' },
  { code: 'TC2',  label: 'Cont → USAC gasoline MR2', cargo_mt: 37_000, flat: 18.65, product: 'gasoline' },
  { code: 'TC5',  label: 'MEG → Japan naphtha LR1',  cargo_mt: 55_000, flat: 18.00, product: 'naphtha' },
  { code: 'TC6',  label: 'Algeria → France MR2',     cargo_mt: 30_000, flat:  8.40, product: 'gasoline' },
  { code: 'TC7',  label: 'SG → Sydney MR2',          cargo_mt: 30_000, flat: 22.15, product: 'gasoline' },
  { code: 'TC14', label: 'USAC → Cont gasoline MR2', cargo_mt: 38_000, flat: 17.10, product: 'gasoline' },
  { code: 'TC17', label: 'MEG → East Africa diesel MR2', cargo_mt: 35_000, flat: 25.40, product: 'diesel' },
];

const PORTS = [
  { code: 'USHOU', name: 'Houston',           loa: 305, beam: 50, draught: 13.7, air: 41,  dwt: 165_000, products: 'lpg / naphtha / gasoline / diesel / jet' },
  { code: 'USCRP', name: 'Corpus Christi',    loa: 366, beam: 60, draught: 16.0, air: 60,  dwt: 320_000, products: 'crude / clean products' },
  { code: 'USLOO', name: 'LOOP',              loa: 360, beam: 70, draught: 28.0, air: 999, dwt: 320_000, products: 'crude (VLCC)' },
  { code: 'USNYC', name: 'NY Harbor',         loa: 245, beam: 42, draught: 15.2, air: 65,  dwt: 120_000, products: 'gasoline / diesel / jet / lpg' },
  { code: 'NLRTM', name: 'Rotterdam',         loa: 400, beam: 70, draught: 20.5, air: 65,  dwt: 300_000, products: 'all liquid bulk' },
  { code: 'BEANR', name: 'Antwerp',           loa: 295, beam: 47, draught: 14.5, air: 70,  dwt: 165_000, products: 'lpg / naphtha / clean products' },
  { code: 'SGSIN', name: 'Singapore',         loa: 400, beam: 70, draught: 21.0, air: 999, dwt: 320_000, products: 'all liquid bulk + bunker' },
  { code: 'JPYOK', name: 'Yokohama',          loa: 333, beam: 60, draught: 18.0, air: 56,  dwt: 280_000, products: 'lpg / clean products' },
  { code: 'JPCHB', name: 'Chiba',             loa: 270, beam: 50, draught: 15.0, air: 999, dwt: 180_000, products: 'lpg / ethane / naphtha (BLPG1+3 discharge)' },
  { code: 'SARUH', name: 'Ras Tanura',        loa: 360, beam: 65, draught: 23.0, air: 999, dwt: 320_000, products: 'crude / lpg / clean products' },
  { code: 'AEFJR', name: 'Fujairah',          loa: 333, beam: 60, draught: 17.0, air: 999, dwt: 280_000, products: 'gasoline / diesel / jet / fuel oil' },
  { code: 'PAONP', name: 'Panama Canal (Neopanamax)', loa: 366, beam: 49, draught: 15.2, air: 57.9, dwt: 130_000, products: 'transit only' },
  { code: 'EGSUE', name: 'Suez Canal',        loa: 400, beam: 77.5, draught: 20.1, air: 68, dwt: 350_000, products: 'transit only' },
];

const FUTURES = [
  { product: 'gasoline',   symbol: 'RB=F', front: 2.27, unit: '$/gal', bbl: 95.34, source: 'NYMEX RBOB' },
  { product: 'heating_oil',symbol: 'HO=F', front: 2.39, unit: '$/gal', bbl: 100.38, source: 'NYMEX ULSD' },
  { product: 'wti',        symbol: 'CL=F', front: 76.18, unit: '$/bbl', bbl: 76.18, source: 'NYMEX WTI' },
  { product: 'brent',      symbol: 'BZ=F', front: 81.05, unit: '$/bbl', bbl: 81.05, source: 'ICE Brent' },
  { product: 'natural_gas',symbol: 'NG=F', front: 2.84,  unit: '$/MMBtu', bbl: null,  source: 'NYMEX HH' },
  { product: 'propane',    symbol: 'PG=F', front: 0.96,  unit: '$/gal', bbl: 40.32, source: 'NYMEX Mont Belvieu' },
];

const OPTIONS_SAMPLE = [
  { symbol: 'CL=F', atm_iv: 0.345, rr_25d: +0.06, put_call_oi: 0.85, regime: 'skewed_up',  note: 'Upside-skewed: option market pays more for crash hedges; supply-fear premium.' },
  { symbol: 'NG=F', atm_iv: 0.420, rr_25d: -0.01, put_call_oi: 1.12, regime: 'nervous',    note: 'Elevated IV with symmetric skew — large moves expected either direction.' },
  { symbol: '^VIX',atm_iv: 0.180, rr_25d: -0.02, put_call_oi: 0.74, regime: 'calm',       note: 'Macro vol sleepy; standard market backdrop.' },
];

// ── Page ────────────────────────────────────────────────────────────────

export default function LabPage() {
  const [vesselSel, setVesselSel] = useState<string>('VLGC');
  const [densityProduct, setDensityProduct] = useState<string>('propane');
  const [convertCbm, setConvertCbm] = useState<string>('84000');
  const [wsRoute, setWsRoute] = useState<string>('TC2');
  const [wsPoints, setWsPoints] = useState<string>('180');
  const [portCheckLocode, setPortCheckLocode] = useState<string>('PAONP');
  const [portCheckVessel, setPortCheckVessel] = useState<string>('VLGC');

  const vessel = VESSELS.find((v) => v.cls === vesselSel)!;
  const density = DENSITIES.find((d) => d.product === densityProduct)!;
  const cbmNum = Number(convertCbm) || 0;
  const mtFromCbm = cbmNum * 0.98 * density.kg_l;

  const ws = WS_ROUTES.find((r) => r.code === wsRoute)!;
  const wsPtsNum = Number(wsPoints) || 100;
  const wsFreight = (wsPtsNum / 100) * ws.flat;
  const wsVoyage = wsFreight * ws.cargo_mt;

  const portRow = PORTS.find((p) => p.code === portCheckLocode)!;
  const vRow = VESSELS.find((v) => v.cls === portCheckVessel)!;
  const portChecks = portRow && vRow
    ? {
        loa:     vRow.loa     <= portRow.loa,
        beam:    vRow.beam    <= portRow.beam,
        draught: vRow.draught <= portRow.draught,
        air:     vRow.air     <= portRow.air,
        dwt:     true,
      }
    : null;
  const portOverall = portChecks
    ? Object.values(portChecks).every(Boolean)
      ? portRow.products === 'transit only' ? 'transit_only' : 'compatible'
      : 'incompatible'
    : 'unknown';

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <HeroBar
        eyebrow="MARKET & FREIGHT LAB"
        title="The signals behind every trade idea, hands-on."
        subtitle="Drive every market, freight, vessel and port input the desk relies on. Pick a route — see the Baltic mid. Pick a vessel + port — see the berth compatibility. Pick a product + volume — see the density-corrected MT. Same data the agents see."
        rightSlot={
          <div className="flex flex-col items-end gap-1 text-[10px]">
            <span className="text-slate-500 uppercase tracking-wider">platform tools</span>
            <span className="text-slate-300 font-mono">vessel · freight · port · options</span>
          </div>
        }
      />

      <ExplainerPanel spec={LAB_EXPLAINER} />

      {/* Tool cards — 2-col grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mt-4">

        {/* 1) VESSEL SPECS */}
        <Card
          icon={<Ship className="w-4 h-4 text-cyan-300" />}
          tool="vessel_specs"
          title="Vessel-class registry"
          subtitle="VLGC/MGC/LGC/SGC for LPG, VLCC/Suezmax/Aframax/LR2/LR1/MR2/MR1/Handysize for CPP. 12 classes × 9 attributes."
        >
          <label className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 block">Vessel class</label>
          <select
            value={vesselSel}
            onChange={(e) => setVesselSel(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white w-full mb-3"
          >
            {VESSELS.map((v) => <option key={v.cls} value={v.cls}>{v.cls} ({v.family})</option>)}
          </select>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
            <Spec label="Capacity"        value={`${vessel.cbm.toLocaleString()} m³`} />
            <Spec label="Cargo (propane)" value={vessel.mt > 0 ? `${vessel.mt.toLocaleString()} MT` : 'CPP route'} />
            <Spec label="Speed"           value={`${vessel.speed} kt`} />
            <Spec label="VLSFO burn"      value={`${vessel.burn} MT/d`} />
            <Spec label="LOA / beam"      value={`${vessel.loa} m / ${vessel.beam} m`} />
            <Spec label="Draught loaded"  value={`${vessel.draught} m`} />
            <Spec label="Air draught"     value={`${vessel.air} m`} />
            <Spec label="AIS ship-type"   value={vessel.family === 'LPG' ? '84' : '80'} />
          </div>
        </Card>

        {/* 2) DENSITY + CONVERSION */}
        <Card
          icon={<Gauge className="w-4 h-4 text-emerald-300" />}
          tool="vessel_specs · density / convert"
          title="Product density + m³↔MT converter"
          subtitle="14 products at 15 °C reference. Powers the freight-math arithmetic the desk gets wrong most often."
        >
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 block">Product</label>
              <select
                value={densityProduct}
                onChange={(e) => setDensityProduct(e.target.value)}
                className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white w-full"
              >
                {DENSITIES.map((d) => <option key={d.product} value={d.product}>{d.product}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 block">Volume (m³)</label>
              <input
                type="number"
                value={convertCbm}
                onChange={(e) => setConvertCbm(e.target.value)}
                className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white w-full font-mono"
              />
            </div>
          </div>
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/[0.04] p-3 text-[12px]">
            <div className="flex items-baseline justify-between">
              <span className="text-slate-300">Density</span>
              <span className="font-mono text-emerald-300">{density.kg_l} kg/L (= MT/m³)</span>
            </div>
            <div className="flex items-baseline justify-between mt-1">
              <span className="text-slate-300">{cbmNum.toLocaleString()} m³ × 0.98 usable × {density.kg_l}</span>
              <span className="font-mono text-emerald-300 font-bold">{mtFromCbm.toFixed(0)} MT</span>
            </div>
            {density.bbl_per_mt && (
              <div className="flex items-baseline justify-between mt-1">
                <span className="text-slate-300">$/MT × {density.bbl_per_mt} → $/bbl conversion</span>
                <span className="font-mono text-emerald-300">1 MT = {density.bbl_per_mt} bbl</span>
              </div>
            )}
            <div className="text-[10px] text-slate-400 mt-2 leading-relaxed">{density.note}</div>
          </div>
        </Card>

        {/* 3) BALTIC BLPG */}
        <Card
          icon={<Anchor className="w-4 h-4 text-cyan-300" />}
          tool="freight_baltic_blpg"
          title="Baltic BLPG indices ($/MT propane VLGC)"
          subtitle="Three benchmark routes. Curated Q1-2026 OPEC-MOMR levels; live override via BALTIC_API_KEY env."
        >
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 pr-2">Route</th>
                <th className="text-left py-2 pr-2">Corridor</th>
                <th className="text-right py-2 pr-2">Low</th>
                <th className="text-right py-2 pr-2">Mid</th>
                <th className="text-right py-2">High</th>
              </tr>
            </thead>
            <tbody>
              {BLPG_ROUTES.map((r) => (
                <tr key={r.code} className="border-b border-slate-800/60">
                  <td className="py-2 pr-2 font-mono text-cyan-300">{r.code}</td>
                  <td className="py-2 pr-2 text-slate-300">{r.label}</td>
                  <td className="py-2 pr-2 text-right text-slate-400">${r.low.toFixed(2)}</td>
                  <td className="py-2 pr-2 text-right font-bold text-white">${r.mid.toFixed(2)}</td>
                  <td className="py-2 text-right text-slate-400">${r.high.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[10px] text-slate-500 mt-3">
            Used by Mispricing Lens as feature <span className="font-mono text-emerald-300">freight_baltic_z</span> on every LPG corridor scan.
          </div>
        </Card>

        {/* 4) WORLDSCALE */}
        <Card
          icon={<Anchor className="w-4 h-4 text-amber-300" />}
          tool="freight_worldscale"
          title="Worldscale freight (CPP tankers)"
          subtitle="2025 flat-rate schedule × broker-quoted WS points. Pick a route, dial in WS points, see the $/MT."
        >
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 block">TC route</label>
              <select
                value={wsRoute}
                onChange={(e) => setWsRoute(e.target.value)}
                className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white w-full"
              >
                {WS_ROUTES.map((r) => <option key={r.code} value={r.code}>{r.code} — {r.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 block">WS points (broker)</label>
              <input
                type="number"
                value={wsPoints}
                onChange={(e) => setWsPoints(e.target.value)}
                className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white w-full font-mono"
              />
            </div>
          </div>
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.04] p-3 text-[12px] space-y-1">
            <div className="flex justify-between"><span className="text-slate-300">Flat rate (WS100 2025)</span><span className="font-mono text-amber-200">${ws.flat.toFixed(2)}/MT</span></div>
            <div className="flex justify-between"><span className="text-slate-300">Standard cargo</span><span className="font-mono text-amber-200">{ws.cargo_mt.toLocaleString()} MT {ws.product}</span></div>
            <div className="flex justify-between border-t border-amber-500/20 pt-1.5"><span className="text-white font-semibold">Freight @ WS{wsPtsNum}</span><span className="font-mono text-amber-300 font-bold text-base">${wsFreight.toFixed(2)}/MT</span></div>
            <div className="flex justify-between"><span className="text-slate-300">Total voyage</span><span className="font-mono text-amber-200">${wsVoyage.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span></div>
          </div>
        </Card>

        {/* 5) PORT CONSTRAINTS */}
        <Card
          icon={<MapPin className="w-4 h-4 text-rose-300" />}
          tool="port_constraints"
          title="Port × vessel compatibility check"
          subtitle="~25 UN/LOCODE ports + Suez/Panama transit constraints. Returns compatible / borderline / incompatible / transit_only."
        >
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 block">Port (UN/LOCODE)</label>
              <select
                value={portCheckLocode}
                onChange={(e) => setPortCheckLocode(e.target.value)}
                className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white w-full"
              >
                {PORTS.map((p) => <option key={p.code} value={p.code}>{p.code} — {p.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 block">Vessel class</label>
              <select
                value={portCheckVessel}
                onChange={(e) => setPortCheckVessel(e.target.value)}
                className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-white w-full"
              >
                {VESSELS.map((v) => <option key={v.cls} value={v.cls}>{v.cls} ({v.family})</option>)}
              </select>
            </div>
          </div>
          <div className={`rounded-lg border p-3 text-[12px] ${
            portOverall === 'compatible'   ? 'border-emerald-500/40 bg-emerald-500/[0.05]' :
            portOverall === 'transit_only' ? 'border-amber-500/40 bg-amber-500/[0.05]' :
                                              'border-rose-500/40 bg-rose-500/[0.05]'
          }`}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-slate-300 text-[10px] uppercase tracking-wider">Verdict</span>
              <span className={`font-bold text-xs uppercase ${
                portOverall === 'compatible'   ? 'text-emerald-300' :
                portOverall === 'transit_only' ? 'text-amber-300' :
                                                 'text-rose-300'
              }`}>{portOverall}</span>
            </div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-[9px] text-slate-500 uppercase tracking-wider">
                  <th className="text-left py-1">Constraint</th>
                  <th className="text-right py-1">{vRow.cls}</th>
                  <th className="text-right py-1">{portRow.name}</th>
                  <th className="text-right py-1 w-10">OK?</th>
                </tr>
              </thead>
              <tbody>
                <CheckRow name="LOA"          v={`${vRow.loa} m`}     l={`${portRow.loa} m`}     ok={portChecks!.loa} />
                <CheckRow name="Beam"         v={`${vRow.beam} m`}    l={`${portRow.beam} m`}    ok={portChecks!.beam} />
                <CheckRow name="Draught"      v={`${vRow.draught} m`} l={`${portRow.draught} m`} ok={portChecks!.draught} />
                <CheckRow name="Air draught"  v={`${vRow.air} m`}     l={`${portRow.air} m`}     ok={portChecks!.air} />
              </tbody>
            </table>
            <div className="text-[10px] text-slate-400 mt-2 leading-relaxed border-t border-slate-800/60 pt-2">
              <span className="text-slate-300 font-semibold">{portRow.name}:</span> handles <span className="font-mono text-slate-300">{portRow.products}</span>.
            </div>
          </div>
        </Card>

        {/* 6) REFINED PRODUCTS FORWARDS */}
        <Card
          icon={<TrendingUp className="w-4 h-4 text-violet-300" />}
          tool="refined_products_forwards"
          title="Refined-products forwards (Yahoo)"
          subtitle="NYMEX/ICE continuous front-month + 3-2-1 crack spreads. Curve values shown are indicative — live every agent run."
        >
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
                <th className="text-left py-2">Product</th>
                <th className="text-left py-2">Symbol</th>
                <th className="text-right py-2">Front</th>
                <th className="text-right py-2">$/bbl-equiv</th>
              </tr>
            </thead>
            <tbody>
              {FUTURES.map((f) => (
                <tr key={f.symbol} className="border-b border-slate-800/60">
                  <td className="py-2 text-slate-300 capitalize">{f.product.replace(/_/g, ' ')}</td>
                  <td className="py-2 font-mono text-violet-300">{f.symbol}</td>
                  <td className="py-2 text-right font-mono text-white">{f.front.toFixed(2)} {f.unit}</td>
                  <td className="py-2 text-right font-mono text-slate-400">{f.bbl ? `$${f.bbl.toFixed(2)}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 rounded-lg border border-violet-500/30 bg-violet-500/[0.04] p-3 text-[12px]">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">3-2-1 Gulf Coast crack (indicative)</div>
            <div className="font-mono text-violet-200">((2 × ${FUTURES[0].bbl?.toFixed(2)} + ${FUTURES[1].bbl?.toFixed(2)}) − 3 × ${FUTURES[2].front.toFixed(2)}) ÷ 3 = <span className="font-bold text-white">${(((2 * (FUTURES[0].bbl || 0)) + (FUTURES[1].bbl || 0) - (3 * FUTURES[2].front)) / 3).toFixed(2)}/bbl</span></div>
          </div>
        </Card>

        {/* 7) OPTIONS DATA */}
        <Card
          icon={<TrendingUp className="w-4 h-4 text-fuchsia-300" />}
          tool="options_data"
          title="Options market signals (IV + skew + regime)"
          subtitle="ATM implied vol, 25-delta risk reversal (call IV − put IV), put/call OI ratio, four-bucket regime label."
        >
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
                <th className="text-left py-2 pr-2">Symbol</th>
                <th className="text-right py-2 pr-2">ATM IV</th>
                <th className="text-right py-2 pr-2">25-Δ RR</th>
                <th className="text-right py-2 pr-2">P/C OI</th>
                <th className="text-left py-2">Regime</th>
              </tr>
            </thead>
            <tbody>
              {OPTIONS_SAMPLE.map((o) => (
                <tr key={o.symbol} className="border-b border-slate-800/60">
                  <td className="py-2 pr-2 font-mono text-fuchsia-300">{o.symbol}</td>
                  <td className="py-2 pr-2 text-right font-mono text-white">{(o.atm_iv * 100).toFixed(1)}%</td>
                  <td className={`py-2 pr-2 text-right font-mono ${o.rr_25d >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{o.rr_25d >= 0 ? '+' : ''}{o.rr_25d.toFixed(3)}</td>
                  <td className="py-2 pr-2 text-right font-mono text-slate-300">{o.put_call_oi.toFixed(2)}</td>
                  <td className="py-2"><RegimeBadge label={o.regime} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 text-[11px] text-slate-400 space-y-1.5">
            {OPTIONS_SAMPLE.map((o) => (
              <div key={o.symbol}><span className="font-mono text-slate-300">{o.symbol}:</span> {o.note}</div>
            ))}
          </div>
        </Card>

        {/* 8) HOW MISPRICING LENS USES THEM */}
        <Card
          icon={<Sparkles className="w-4 h-4 text-emerald-300" />}
          tool="wingman-mispricing-fairvalue"
          title="How the Mispricing Lens consumes these"
          subtitle="Three of these tools feed the Bayesian fair-value model directly as features. The other four enrich the agent's narrative + trade-card math."
        >
          <ul className="text-[12px] text-slate-300 space-y-2 leading-relaxed">
            <li><span className="font-mono text-emerald-300">feature [12] freight_baltic_z</span> — z-score of <span className="font-mono">freight_baltic_blpg</span> route mid vs trailing.</li>
            <li><span className="font-mono text-emerald-300">feature [13] freight_ws_per_mt_z</span> — z-score of <span className="font-mono">freight_worldscale</span> density-corrected $/MT.</li>
            <li><span className="font-mono text-emerald-300">feature [14] route_vessel_size_norm</span> — from <span className="font-mono">vessel_specs</span> typical cargo MT ÷ 50,000.</li>
            <li><span className="font-mono text-fuchsia-300">features [8-11]</span> — from <span className="font-mono">options_data</span> (Brent IV + 25-Δ RR + HH IV + crude P/C OI).</li>
            <li><span className="text-slate-400">Other tools</span> — <span className="font-mono">port_constraints</span> flags impossible cargoes before the trade card is drafted; <span className="font-mono">refined_products_forwards</span> + 3-2-1 crack contextualise the spread in the LLM thesis.</li>
          </ul>
          <div className="mt-3 text-[11px] text-emerald-300 flex items-center gap-1">
            Holdout R² 0.665 · RMSE $7.49/MT · posterior std ~$8.5/MT. <ArrowRight className="w-3 h-3" />
          </div>
        </Card>
      </div>
    </div>
  );
}

function Card({ icon, tool, title, subtitle, children }: { icon: React.ReactNode; tool: string; title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="flex items-start justify-between mb-3 gap-3">
        <div className="flex items-center gap-2">
          {icon}
          <div>
            <div className="text-sm font-bold text-white leading-snug">{title}</div>
            <div className="text-[10px] font-mono text-slate-500 mt-0.5">{tool}</div>
          </div>
        </div>
      </div>
      <p className="text-[11px] text-slate-400 leading-relaxed mb-4">{subtitle}</p>
      {children}
    </section>
  );
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-slate-800/40 pb-1">
      <span className="text-slate-400 text-[11px]">{label}</span>
      <span className="font-mono text-slate-200">{value}</span>
    </div>
  );
}

function CheckRow({ name, v, l, ok }: { name: string; v: string; l: string; ok: boolean }) {
  return (
    <tr className="border-t border-slate-800/40">
      <td className="py-1 text-slate-400">{name}</td>
      <td className="py-1 text-right font-mono text-slate-200">{v}</td>
      <td className="py-1 text-right font-mono text-slate-200">{l}</td>
      <td className={`py-1 text-right ${ok ? 'text-emerald-400' : 'text-rose-400'} font-bold`}>{ok ? '✓' : '✗'}</td>
    </tr>
  );
}

function RegimeBadge({ label }: { label: string }) {
  const tones: Record<string, string> = {
    calm:        'border-emerald-500/40 text-emerald-300 bg-emerald-500/10',
    nervous:     'border-amber-500/40 text-amber-300 bg-amber-500/10',
    skewed_up:   'border-cyan-500/40 text-cyan-300 bg-cyan-500/10',
    skewed_down: 'border-rose-500/40 text-rose-300 bg-rose-500/10',
  };
  const tone = tones[label] || 'border-slate-600 text-slate-300';
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-semibold border ${tone}`}>
      {label.replace(/_/g, ' ')}
    </span>
  );
}
