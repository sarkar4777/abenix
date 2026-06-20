'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Flame, Play, Loader2, AlertTriangle, ChevronDown, ChevronRight,
  FileText, Sparkles,
} from 'lucide-react';
import { FanChart, FanChartForecast } from '@/components/commodities/FanChart';
import { ScenarioList, Scenario } from '@/components/commodities/ScenarioCard';
import { ThesisPanel, Driver } from '@/components/commodities/ThesisPanel';
import { ProvenanceBanner, Provenance } from '@/components/commodities/ProvenanceBanner';
import { PageExplainer } from '@/components/PageExplainer';
import { getPageExplanation } from '@/lib/page_explanations';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
const EXEC_ID_KEY = 'contractiq_commodities_exec_id';
const EXEC_META_KEY = 'contractiq_commodities_exec_meta';
const LAST_RESULT_KEY_PREFIX = 'contractiq_commodities_last_result';

interface CachedResultMeta {
  commodity: string;
  hub: string;
  fair_value: number | null;
  market_quote?: number | null;
  unit?: string;
  saved_at: number; // epoch ms
  data_quality?: string;
}

function cachedResultKey(commodity: string, hub: string): string {
  return `${LAST_RESULT_KEY_PREFIX}_${commodity}_${hub}`;
}

function loadCachedResult(commodity: string, hub: string): CachedResultMeta | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(cachedResultKey(commodity, hub));
    if (!raw) return null;
    return JSON.parse(raw) as CachedResultMeta;
  } catch {
    return null;
  }
}

function saveCachedResult(meta: CachedResultMeta): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(cachedResultKey(meta.commodity, meta.hub), JSON.stringify(meta));
  } catch {}
}

function fmtAgo(ts: number): string {
  const dt = Date.now() - ts;
  if (dt < 60_000) return 'just now';
  if (dt < 3_600_000) return `${Math.floor(dt / 60_000)}m ago`;
  if (dt < 86_400_000) return `${Math.floor(dt / 3_600_000)}h ago`;
  return `${Math.floor(dt / 86_400_000)}d ago`;
}

const COMMODITIES: { slug: string; label: string; enabled: boolean }[] = [
  { slug: 'pipeline_gas', label: 'Pipeline Gas', enabled: true },
  { slug: 'lng',          label: 'LNG',          enabled: true },
  { slug: 'power',        label: 'Power',        enabled: true },
  { slug: 'carbon',       label: 'Carbon (EUA)', enabled: true },
  { slug: 'crude',        label: 'Crude',        enabled: true },
  { slug: 'refined',      label: 'Refined Products', enabled: true },
  { slug: 'coal',         label: 'Coal',         enabled: true },
];

// Slug → display label. Keep aligned with COMMODITIES for direct lookups.
const COMMODITY_LABELS: Record<string, string> = {
  pipeline_gas: 'Pipeline Gas',
  lng: 'LNG',
  power: 'Power',
  carbon: 'Carbon (EUA)',
  crude: 'Crude',
  refined: 'Refined Products',
  coal: 'Coal',
};

function displayCommodity(slug: string): string {
  return COMMODITY_LABELS[slug] || slug;
}

const HUBS_BY_COMMODITY: Record<string, string[]> = {
  pipeline_gas: ['TTF', 'NBP', 'PEG', 'THE', 'CEGH', 'PSV'],
  lng:    ['JKM', 'FOB_USGC', 'DES_NWE', 'TFDES'],
  power:  ['EPEX-DE', 'Nord Pool', 'PJM'],
  carbon: ['EUA', 'CCA', 'RGGI'],
  crude:  ['Brent', 'WTI', 'Dubai'],
  refined:['Gasoil', 'Jet', 'Gasoline'],
  coal:   ['API2', 'API4', 'Newcastle'],
};

const DEFAULT_HUB: Record<string, string> = {
  pipeline_gas: 'TTF',
  lng: 'JKM',
};

// Power is region-driven (one agent, five regions). The selector renders a
// region sub-picker after the commodity is set to 'power'; the run button
// posts { region, horizon_months } instead of { hub }.
const POWER_REGIONS = ['DE', 'FR', 'NORDICS', 'ERCOT', 'PJM'] as const;
type PowerRegion = (typeof POWER_REGIONS)[number];
const DEFAULT_POWER_REGION: PowerRegion = 'DE';
const DEFAULT_POWER_HORIZON_MONTHS = 12;

// Human-readable suffix on the H1 for each power region.
const POWER_REGION_SUFFIX: Record<PowerRegion, string> = {
  DE:      'DE Day-Ahead',
  FR:      'FR Day-Ahead',
  NORDICS: 'Nord Pool System',
  ERCOT:   'ERCOT North Hub',
  PJM:     'PJM Western Hub',
};

// Crude and coal are region/benchmark-driven (one agent, multiple benchmarks).
// Refined is product-driven. Same selector pattern as power.
const CRUDE_REGIONS = ['BRENT', 'WTI'] as const;
type CrudeRegion = (typeof CRUDE_REGIONS)[number];
const DEFAULT_CRUDE_REGION: CrudeRegion = 'BRENT';

const COAL_REGIONS = ['NEWCASTLE', 'API2', 'API4'] as const;
type CoalRegion = (typeof COAL_REGIONS)[number];
const DEFAULT_COAL_REGION: CoalRegion = 'NEWCASTLE';

const REFINED_PRODUCTS = ['RBOB', 'ULSD', 'JET'] as const;
type RefinedProduct = (typeof REFINED_PRODUCTS)[number];
const DEFAULT_REFINED_PRODUCT: RefinedProduct = 'RBOB';

const DEFAULT_FORECAST_HORIZON_MONTHS = 12;

// Asset-class slug used to filter /contracts by commodity. Matches the
// AssetClass enum stored on ContractIQContract.asset_class.
const ASSET_CLASS_FOR_COMMODITY: Record<string, string> = {
  pipeline_gas: 'natgas',
  lng: 'lng',
  power: 'power',
  carbon: 'carbon',
  crude: 'crude',
  refined: 'refined',
  coal: 'coal',
};

// Per-commodity glossary + reference-price tiles, ported from the retired hub
// pages. The 'spot' values are static SAMPLE anchors — not a live feed. They
// orient an analyst on relative magnitudes before the agent run produces the
// real fair-value. Tenor labels ('M+1', 'Cal+1', 'Dec-NN') are computed from
// current_time at render so they never read as historically rolled.
interface KpiCard {
  // Suffix appended to the name at render time, e.g. 'M+1' / 'Cal+1' / 'Dec-25'.
  // Resolves via tenorSuffix() so the rendered label tracks the calendar.
  tenorKind?: 'M+1' | 'Cal+1' | 'Dec-front';
  name: string;
  spot: number;
  unit: string;
  change: number;
}
interface GlossaryItem { term: string; def: string; }
interface CommodityModule { kpis: KpiCard[]; glossary: GlossaryItem[]; }

// Two-digit short year suffix for 'Dec-NN'. Front Dec contract rolls on the
// last business day of November; before then it's current-year Dec, after it's
// next-year Dec. Approximated with month >= 11 because we only need the label
// to read "current front contract" to a trader.
function frontDecYearTwoDigit(now: Date = new Date()): string {
  const month = now.getUTCMonth(); // 0=Jan
  const year = now.getUTCFullYear() + (month >= 11 ? 1 : 0);
  return String(year % 100).padStart(2, '0');
}

// Cal+1 = the following calendar year.
function nextCalYearTwoDigit(now: Date = new Date()): string {
  return String((now.getUTCFullYear() + 1) % 100).padStart(2, '0');
}

function tenorSuffix(kind: KpiCard['tenorKind']): string {
  switch (kind) {
    case 'M+1':       return 'M+1';
    case 'Cal+1':     return `Cal-${nextCalYearTwoDigit()}`;
    case 'Dec-front': return `Dec-${frontDecYearTwoDigit()}`;
    default:          return '';
  }
}

function kpiLabel(k: KpiCard): string {
  const suffix = tenorSuffix(k.tenorKind);
  return suffix ? `${k.name} ${suffix}` : k.name;
}

const COMMODITY_MODULES: Record<string, CommodityModule> = {
  pipeline_gas: {
    kpis: [
      { name: 'TTF',  tenorKind: 'M+1', spot: 34.82, unit: '€/MWh', change:  0.62 },
      { name: 'THE',  tenorKind: 'M+1', spot: 35.04, unit: '€/MWh', change:  0.41 },
      { name: 'CEGH', tenorKind: 'M+1', spot: 35.21, unit: '€/MWh', change:  0.18 },
      { name: 'PSV',  tenorKind: 'M+1', spot: 35.78, unit: '€/MWh', change:  0.71 },
    ],
    glossary: [
      { term: 'TTF / THE / CEGH / PSV', def: 'European gas pricing hubs. TTF (Netherlands) is the benchmark, THE (Germany merged), CEGH (Austria), PSV (Italy) trade as basis to TTF.' },
      { term: 'Storage cycling',        def: 'P&L from injecting gas during summer (cheap) and withdrawing in winter (expensive). The spread between front-month and winter prices drives the trade.' },
      { term: 'Linepack',               def: 'Gas pressurised inside a pipeline acting as short-term flexibility. When linepack is tight, system operators raise balancing prices to force adjustments.' },
    ],
  },
  lng: {
    kpis: [
      { name: 'JKM',      tenorKind: 'M+1', spot: 12.40, unit: '$/MMBtu', change:  0.30 },
      { name: 'FOB USGC', tenorKind: 'M+1', spot:  9.85, unit: '$/MMBtu', change: -0.12 },
      { name: 'DES NWE',  tenorKind: 'M+1', spot: 11.62, unit: '$/MMBtu', change:  0.18 },
      { name: 'TFDES',    tenorKind: 'M+1', spot: 11.95, unit: '$/MMBtu', change:  0.22 },
    ],
    glossary: [
      { term: 'JKM',       def: 'Japan-Korea Marker, the Asian LNG benchmark. Front-month price for a delivered cargo to a North-Asian regas terminal.' },
      { term: 'FOB / DES', def: 'Free On Board (loaded at the export terminal, buyer arranges shipping) vs Delivered Ex-Ship (seller delivers to the destination terminal). DES = FOB + freight + boil-off.' },
      { term: 'TFDES',     def: 'TTF-linked DES cargo to NWE, priced against the TTF gas hub instead of a fixed level. Common in long-term contracts.' },
    ],
  },
  power: {
    kpis: [
      { name: 'DE', tenorKind: 'Cal+1', spot:  95.6, unit: '€/MWh', change: -1.20 },
      { name: 'HU', tenorKind: 'Cal+1', spot: 113.0, unit: '€/MWh', change:  0.85 },
      { name: 'PL', tenorKind: 'Cal+1', spot:  90.4, unit: '€/MWh', change:  0.32 },
      { name: 'IT', tenorKind: 'Cal+1', spot: 108.2, unit: '€/MWh', change:  1.10 },
    ],
    glossary: [
      { term: 'Clean-spark spread',              def: 'The margin a gas-fired plant earns: power price minus (gas price × heat rate) minus (EUA price × emission rate). When clean-spark is positive, gas plants run profitably.' },
      { term: 'Day-ahead / intraday / balancing', def: 'Three power markets: day-ahead clears the next 24h at noon, intraday runs continuously up to delivery, balancing settles deviations in real-time.' },
      { term: 'BESS',                            def: 'Battery Energy Storage System. Charges when power is cheap, discharges when expensive, also earns from balancing-reserve auctions.' },
    ],
  },
  carbon: {
    kpis: [
      { name: 'EUA',             tenorKind: 'Dec-front', spot:  87.40, unit: '€/t',   change:  1.42 },
      { name: 'GoO Nordic Wind',                          spot:   3.84, unit: '€/MWh', change:  0.21 },
      { name: 'GoO Solar EU',                             spot:   2.91, unit: '€/MWh', change:  0.05 },
      { name: 'Biomethane',                               spot:  62.30, unit: '€/MWh', change: -0.18 },
    ],
    glossary: [
      { term: 'EUA',             def: 'European Union Allowance, one tonne of CO₂ permitted to be emitted under the EU ETS. Industrial + power emitters must surrender one EUA per tonne emitted.' },
      { term: 'GoO',             def: 'Guarantee of Origin, a certificate proving 1 MWh was generated from a specific renewable source. Sold separately from the underlying electricity.' },
      { term: 'Biomethane cert', def: 'Certificate proving 1 MWh of biomethane was injected into the gas grid. Allows fossil-gas buyers to claim renewable equivalence.' },
      { term: 'CBAM',            def: 'Carbon Border Adjustment Mechanism, EU import levy on carbon-intensive goods to prevent leakage. Phasing in from 2026.' },
    ],
  },
  crude: {
    kpis: [
      { name: 'Brent',     tenorKind: 'M+1', spot: 82.1, unit: '$/bbl', change: -0.45 },
      { name: 'WTI',       tenorKind: 'M+1', spot: 78.6, unit: '$/bbl', change: -0.32 },
      { name: 'Dubai',     tenorKind: 'M+1', spot: 81.4, unit: '$/bbl', change:  0.10 },
      { name: 'Brent-WTI',                    spot:  3.5, unit: '$/bbl', change: -0.13 },
    ],
    glossary: [
      { term: 'Brent / WTI / Dubai', def: 'Three crude oil benchmarks. Brent (North Sea, waterborne), WTI (US inland, Cushing OK), Dubai (Middle East sour). Refiners price feedstock against one of these.' },
      { term: 'Crack spread',        def: 'Refining margin: refined-product price minus crude cost. The 3-2-1 crack is 3 barrels crude into 2 gasoline + 1 distillate.' },
    ],
  },
  refined: {
    kpis: [
      { name: 'Gasoil ARA',          spot:  760,  unit: '$/t',   change:  1.20 },
      { name: 'Jet CIF NWE',         spot:  815,  unit: '$/t',   change:  0.85 },
      { name: 'Gasoline RBOB',       spot:    2.45, unit: '$/gal', change: -0.02 },
      { name: 'Gasoil-Brent crack',  spot:   22.4, unit: '$/bbl', change:  0.30 },
    ],
    glossary: [
      { term: 'Gasoil / Jet / Gasoline', def: 'Refined products. Gasoil = middle distillate (diesel + heating), jet = aviation kerosene, gasoline = motor spirit.' },
      { term: 'CIF / FOB',               def: 'CIF (Cost Insurance Freight) is delivered to the destination port, FOB is loaded at the source. CIF NWE = delivered into Amsterdam-Rotterdam-Antwerp.' },
    ],
  },
  coal: {
    kpis: [
      { name: 'API2 (ARA)',  spot: 110.5, unit: '$/t', change: -0.75 },
      { name: 'API4 (RB)',   spot:  98.3, unit: '$/t', change: -0.30 },
      { name: 'Newcastle',   spot: 134.0, unit: '$/t', change:  0.40 },
      { name: 'API2-Newc',   spot: -23.5, unit: '$/t', change: -0.20 },
    ],
    glossary: [
      { term: 'API2 / API4', def: 'API2 = thermal coal CIF ARA (Amsterdam-Rotterdam-Antwerp), API4 = thermal coal FOB Richards Bay South Africa. Both reference 6000 kcal/kg energy content.' },
      { term: 'Newcastle',   def: 'Newcastle FOB (Australia) is the Pacific-basin thermal coal benchmark. Premium to API2 reflects Pacific-Atlantic basin tightness.' },
    ],
  },
};

interface ContractRow {
  id: string;
  title?: string | null;
  counterparty_a?: string | null;
  counterparty_b?: string | null;
  status?: string | null;
  total_capacity_mw?: number | null;
}

// Raw agent point shape — we accept several aliases so a small drift in
// the YAML doesn't snap the renderer.
type RawCurvePoint = {
  tenor_month?: number;
  tenor?: string | number;
  price_eur_mwh?: number;
  price_usd_mwh?: number;
  price_per_mwh?: number;
  price_usd_mmbtu?: number;
  price?: number;
  mid?: number;
  value?: number;
  expected?: number;
};

interface AgentForecast {
  hub?: string;
  region?: string;
  commodity?: string;
  as_of?: string;
  tenor_months?: number;
  horizon_months?: number;
  unit?: string;
  anchor_currency?: string;
  anchor_source?: string;
  spot_anchor?: number;
  summary_markdown?: string;
  base_curve?: RawCurvePoint[];
  expected_curve?: RawCurvePoint[];
  p10_curve?: RawCurvePoint[];
  p90_curve?: RawCurvePoint[];
  // Some agents emit p10/p90 directly, mirror the FanChart props for compat.
  p10?: RawCurvePoint[];
  p90?: RawCurvePoint[];
  scenarios?: any[];
  drivers?: Driver[];
  summary?: string;
  narrative_markdown?: string;
  confidence?: number | string;
  data_quality?: string;
  provenance?: Provenance & { fetched_at?: string };
  // Stamped by the runtime canonical-anchor guardrail when it overrode the
  // agent's fabricated curve. Drives the amber "guardrail corrected"
  // pill on the provenance banner.
  meta?: { post_processed?: boolean; post_processor?: string };
}

interface ToolCallDetail {
  tool_name?: string;
  args?: any;
  content_snippet?: string;
}

interface AgentResponse {
  forecast?: AgentForecast | null;
  raw_output?: string | null;
  execution_id?: string;
  cost_usd?: number;
  duration_ms?: number;
  model?: string | null;
  tool_calls?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  meta?: { tool_calls?: ToolCallDetail[] } | null;
}

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('contractiq_token');
}

function tenorLabel(p: RawCurvePoint, idx: number): string {
  if (typeof p.tenor === 'string') return p.tenor;
  if (typeof p.tenor === 'number') return `M+${p.tenor}`;
  if (typeof p.tenor_month === 'number') return `M+${p.tenor_month}`;
  return `M+${idx + 1}`;
}

function pickPrice(p: RawCurvePoint): number | null {
  for (const k of ['price_eur_mwh', 'price_usd_mwh', 'price_per_mwh', 'price_usd_mmbtu', 'price', 'mid', 'value', 'expected'] as const) {
    const v = p?.[k as keyof RawCurvePoint] as number | undefined;
    if (typeof v === 'number' && isFinite(v)) return v;
  }
  return null;
}

function adaptForecast(f?: AgentForecast | null): FanChartForecast | null {
  if (!f) return null;
  const base = (f.base_curve || []).map((p, i) => ({
    tenor: tenorLabel(p, i),
    mid: pickPrice(p) ?? 0,
  }));
  const expected = (f.expected_curve || []).map((p, i) => ({
    tenor: tenorLabel(p, i),
    expected: pickPrice(p) ?? 0,
  }));
  const p10 = (f.p10_curve || f.p10 || []).map((p, i) => ({
    tenor: tenorLabel(p, i),
    value: pickPrice(p) ?? 0,
  }));
  const p90 = (f.p90_curve || f.p90 || []).map((p, i) => ({
    tenor: tenorLabel(p, i),
    value: pickPrice(p) ?? 0,
  }));
  if (!base.length && !expected.length && !p10.length && !p90.length) return null;
  return { base_curve: base, expected_curve: expected, p10, p90 };
}

function adaptScenarios(f?: AgentForecast | null): Scenario[] | undefined {
  if (!f || !f.scenarios) return undefined;
  return f.scenarios.map((s: any) => ({
    name: s.name || s.label || s.id || 'scenario',
    probability: typeof s.probability === 'number' ? s.probability : undefined,
    description: s.narrative || s.description,
    impact: s.impact_eur_mwh ?? s.impact ?? undefined,
    direction: s.direction,
  }));
}

// Scenarios should sum to ~1.0. If they don't, the agent output is malformed.
function probabilitySum(scenarios?: Scenario[]): number | null {
  if (!scenarios || !scenarios.length) return null;
  let total = 0;
  let counted = 0;
  for (const s of scenarios) {
    if (typeof s.probability === 'number' && isFinite(s.probability)) {
      total += s.probability;
      counted += 1;
    }
  }
  return counted ? total : null;
}

function flattenDrivers(f?: AgentForecast | null): Driver[] | undefined {
  if (!f) return undefined;
  // Prefer top-level drivers; fall back to flattening per-scenario drivers.
  if (f.drivers && f.drivers.length) return f.drivers;
  const acc: Driver[] = [];
  for (const s of f.scenarios || []) {
    for (const d of (s as any).drivers || []) {
      acc.push({
        category: d.category,
        headline: d.headline,
        source: d.source,
        url: d.url,
        date: d.date,
        impact: d.impact_eur_mwh ?? d.impact,
      });
    }
  }
  return acc.length ? acc : undefined;
}

// Anchor sources we treat as "real-fetched" when the agent only stamps an
// anchor_source string and not a mode. Keep this list narrow — every entry
// must be a documented public feed (Yahoo Finance proxy or EIA series id).
const DOCUMENTED_ANCHOR_SOURCES = ['yahoo_finance', 'eia_open_data', 'eia '];

function inferModeFromAnchor(anchor?: string): 'real_fetched' | undefined {
  if (!anchor) return undefined;
  const a = anchor.toLowerCase();
  return DOCUMENTED_ANCHOR_SOURCES.some(s => a.includes(s)) ? 'real_fetched' : undefined;
}

function provenanceFor(f?: AgentForecast | null): Provenance {
  if (f?.provenance) {
    const p = f.provenance;
    // Map agent-side fetched_at -> banner-side last_refresh so older yaml
    // contracts keep working without a banner change.
    const normalised: Provenance = {
      data_source: p.data_source,
      last_refresh: p.last_refresh || p.fetched_at,
      mode: p.mode,
      notes: p.notes,
    };
    // If the agent set data_quality but forgot mode, infer it.
    if (!normalised.mode && f.data_quality) {
      const dq = f.data_quality.toLowerCase();
      normalised.mode =
        dq === 'live' ? 'real_fetched' :
        dq === 'simulated' ? 'agent_simulated' :
        dq === 'degraded' ? 'agent_simulated' :
        normalised.mode;
    }
    // Final fallback — read anchor_source. Power's contract emits this even
    // when the agent forgets the explicit mode field.
    if (!normalised.mode) {
      const inferred = inferModeFromAnchor(f.anchor_source);
      if (inferred) normalised.mode = inferred;
    }
    return normalised;
  }
  // Default placeholder — keeps the banner honest before the first run.
  return {
    data_source: 'awaiting first run — no source yet',
    last_refresh: 'pending first run',
    mode: 'unknown',
    notes: 'no agent run yet',
  };
}

function confidenceNumber(c?: number | string | null): number | null {
  if (c == null) return null;
  if (typeof c === 'number') return c;
  const map: Record<string, number> = { low: 0.4, medium: 0.65, high: 0.85 };
  return map[c.toLowerCase()] ?? null;
}

export default function CommoditiesForwardPage() {
  const [commodity, setCommodity] = useState<string>('pipeline_gas');
  const [hub, setHub] = useState<string>(DEFAULT_HUB[commodity] || 'TTF');
  const [region, setRegion] = useState<PowerRegion>(DEFAULT_POWER_REGION);
  const [crudeRegion, setCrudeRegion] = useState<CrudeRegion>(DEFAULT_CRUDE_REGION);
  const [coalRegion, setCoalRegion] = useState<CoalRegion>(DEFAULT_COAL_REGION);
  const [refinedProduct, setRefinedProduct] = useState<RefinedProduct>(DEFAULT_REFINED_PRODUCT);
  const [running, setRunning] = useState(false);
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attachStatus, setAttachStatus] = useState<string | null>(null);
  const [showAudit, setShowAudit] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [cachedResult, setCachedResult] = useState<CachedResultMeta | null>(null);
  const [contracts, setContracts] = useState<ContractRow[]>([]);
  const [contractsLoading, setContractsLoading] = useState<boolean>(false);
  const abortRef = useRef<AbortController | null>(null);

  // Reload cached fair-value summary whenever the selector changes. For
  // power/crude/coal the second-level lever is a region/benchmark; for
  // refined it's a product code; everything else uses the hub label.
  const selectorKey =
    commodity === 'power' ? region :
    commodity === 'crude' ? crudeRegion :
    commodity === 'coal' ? coalRegion :
    commodity === 'refined' ? refinedProduct :
    hub;
  useEffect(() => {
    setCachedResult(loadCachedResult(commodity, selectorKey));
  }, [commodity, selectorKey]);

  // Pull contracts scoped to this commodity. We don't fail the page when
  // the API rejects — just leave the table empty with a "none yet" row.
  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    setContractsLoading(true);
    (async () => {
      try {
        const token = getToken();
        const r = await fetch(`${API_URL}/api/contractiq/contracts?limit=8`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: ctrl.signal,
        });
        const j = await r.json().catch(() => ({}));
        const rows: ContractRow[] = (j?.data || []) as ContractRow[];
        const ac = ASSET_CLASS_FOR_COMMODITY[commodity];
        // Filter client-side on title/asset_class match — the listing API
        // doesn't yet expose an asset_class query, but the seeded test
        // corpus tags titles consistently (gas_supply / ppa / lng / etc).
        const filtered = rows.filter(c => {
          const hay = `${c.title || ''}`.toLowerCase();
          if (ac && hay.includes(ac)) return true;
          if (commodity === 'pipeline_gas' && /gas|ttf|the|cegh|psv/i.test(hay)) return true;
          if (commodity === 'lng' && /lng|jkm/i.test(hay)) return true;
          if (commodity === 'power' && /power|ppa|wind|solar/i.test(hay)) return true;
          if (commodity === 'carbon' && /eua|carbon|cbam|goo/i.test(hay)) return true;
          if (commodity === 'crude' && /brent|wti|crude/i.test(hay)) return true;
          if (commodity === 'refined' && /gasoil|jet|gasoline|rbob|ulsd|diesel/i.test(hay)) return true;
          if (commodity === 'coal' && /coal|api2|api4|newcastle/i.test(hay)) return true;
          return false;
        });
        // Fall back to the un-filtered slice when nothing tags — still
        // informative for the analyst.
        const display = filtered.length ? filtered : rows.slice(0, 5);
        if (!cancelled) setContracts(display.slice(0, 6));
      } catch {
        if (!cancelled) setContracts([]);
      } finally {
        if (!cancelled) setContractsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [commodity]);

  // On mount, look for a pending execution in localStorage. Surface
  // a "still running, attaching..." banner so the user knows we didn't
  // forget the previous request after a refresh / nav.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const eid = localStorage.getItem(EXEC_ID_KEY);
      const metaRaw = localStorage.getItem(EXEC_META_KEY);
      if (eid && metaRaw) {
        setAttachStatus(`execution still running, attaching... ${eid.slice(0, 12)}`);
      }
    } catch {
      // ignore - localStorage is best-effort
    }
  }, []);

  // Honor ?commodity=<slug> so the retired hub pages can redirect into
  // the forward page without losing context. We accept disabled slugs
  // too — the selector renders them with a "Coming soon" pill and the
  // Run button stays disabled, but the analyst still sees the KPI strip
  // and glossary for the commodity they navigated to. For power, also
  // honour ?region=<DE|FR|NORDICS|ERCOT|PJM>; missing/invalid falls back
  // to DE.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const qs = new URLSearchParams(window.location.search);
      const target = qs.get('commodity');
      const targetRegion = (qs.get('region') || '').toUpperCase().trim();
      const targetProduct = (qs.get('product') || '').toUpperCase().trim();
      if (target) {
        const match = COMMODITIES.find(c => c.slug === target);
        if (match && target !== commodity) {
          setCommodity(target);
          setHub(DEFAULT_HUB[target] || (HUBS_BY_COMMODITY[target] || [''])[0]);
        }
        if (target === 'power') {
          const valid = (POWER_REGIONS as readonly string[]).includes(targetRegion);
          setRegion(valid ? (targetRegion as PowerRegion) : DEFAULT_POWER_REGION);
        }
        if (target === 'crude') {
          const valid = (CRUDE_REGIONS as readonly string[]).includes(targetRegion);
          setCrudeRegion(valid ? (targetRegion as CrudeRegion) : DEFAULT_CRUDE_REGION);
        }
        if (target === 'coal') {
          const valid = (COAL_REGIONS as readonly string[]).includes(targetRegion);
          setCoalRegion(valid ? (targetRegion as CoalRegion) : DEFAULT_COAL_REGION);
        }
        if (target === 'refined') {
          const valid = (REFINED_PRODUCTS as readonly string[]).includes(targetProduct);
          setRefinedProduct(valid ? (targetProduct as RefinedProduct) : DEFAULT_REFINED_PRODUCT);
        }
      }
    } catch {
      // ignore - URLSearchParams is best-effort
    }
  }, []);

  // Make sure we abort any in-flight fetch on unmount so an old reply
  // can't ratchet state on a stale component.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const enabledCommodity = COMMODITIES.find(c => c.slug === commodity)?.enabled;
  const hubs = HUBS_BY_COMMODITY[commodity] || [];

  function switchCommodity(slug: string) {
    const target = COMMODITIES.find(c => c.slug === slug);
    if (!target?.enabled) return;
    setCommodity(slug);
    setHub(DEFAULT_HUB[slug] || (HUBS_BY_COMMODITY[slug] || [''])[0]);
    if (slug === 'power') setRegion(DEFAULT_POWER_REGION);
    if (slug === 'crude') setCrudeRegion(DEFAULT_CRUDE_REGION);
    if (slug === 'coal') setCoalRegion(DEFAULT_COAL_REGION);
    if (slug === 'refined') setRefinedProduct(DEFAULT_REFINED_PRODUCT);
    setResponse(null);
    setError(null);
  }

  function switchRegion(next: PowerRegion) {
    if (next === region) return;
    setRegion(next);
    // Match the hub switch: drop any cached agent result so the analyst
    // never reads stale numbers under a fresh region label.
    setResponse(null);
    setError(null);
  }

  function switchCrudeRegion(next: CrudeRegion) {
    if (next === crudeRegion) return;
    setCrudeRegion(next);
    setResponse(null);
    setError(null);
  }

  function switchCoalRegion(next: CoalRegion) {
    if (next === coalRegion) return;
    setCoalRegion(next);
    setResponse(null);
    setError(null);
  }

  function switchRefinedProduct(next: RefinedProduct) {
    if (next === refinedProduct) return;
    setRefinedProduct(next);
    setResponse(null);
    setError(null);
  }

  async function run() {
    if (!enabledCommodity) return;
    // Cancel any in-flight request before kicking off a new one.
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    // Hard 6-minute ceiling — covers the 300s agent runtime timeout plus
    // network latency and browser overhead seen under Playwright.
    const timeoutId = setTimeout(() => ctrl.abort(), 360_000);

    setRunning(true);
    setError(null);
    setAttachStatus(null);
    try {
      const token = getToken();
      // Power/crude/coal post a region tag; refined posts a product code;
      // every other commodity stays on the { hub } contract. The agent
      // expects its native input shape so we route on slug here.
      let requestBody: Record<string, any>;
      if (commodity === 'power') {
        requestBody = { commodity: 'power', region, horizon_months: DEFAULT_POWER_HORIZON_MONTHS };
      } else if (commodity === 'crude') {
        requestBody = { commodity: 'crude', region: crudeRegion, horizon_months: DEFAULT_FORECAST_HORIZON_MONTHS };
      } else if (commodity === 'coal') {
        requestBody = { commodity: 'coal', region: coalRegion, horizon_months: DEFAULT_FORECAST_HORIZON_MONTHS };
      } else if (commodity === 'refined') {
        requestBody = { commodity: 'refined', product: refinedProduct, horizon_months: DEFAULT_FORECAST_HORIZON_MONTHS };
      } else {
        requestBody = { hub };
      }
      // Persist a marker so a refresh during the long fetch surfaces an
      // honest "attaching..." status instead of a silent blank page.
      try {
        localStorage.setItem(
          EXEC_META_KEY,
          JSON.stringify({ commodity, ...requestBody, started_at: Date.now() }),
        );
      } catch {}
      const r = await fetch(
        `${API_URL}/api/contractiq/commodities/${commodity}/forward/run`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(requestBody),
          signal: ctrl.signal,
        },
      );
      const j = await r.json();
      if (!r.ok) throw new Error(j?.error?.message || `HTTP ${r.status}`);
      const data = (j.data || j) as AgentResponse;
      setResponse(data);
      try {
        if (data?.execution_id) {
          localStorage.setItem(EXEC_ID_KEY, data.execution_id);
        }
      } catch {}
      // Cache the headline fair-value so a refresh shows last result instantly.
      try {
        const fc = data?.forecast;
        const firstExpected = fc?.expected_curve?.[0];
        const firstBase = fc?.base_curve?.[0];
        const fv = firstExpected ? pickPrice(firstExpected) : (firstBase ? pickPrice(firstBase) : null);
        // Cache keyed on the active sub-selector so DE/FR/JKM/TTF results
        // don't clobber each other when the analyst flips between them.
        const cacheUnit = fc?.unit
          || (fc?.anchor_currency ? `${fc.anchor_currency}/MWh` : undefined);
        const meta: CachedResultMeta = {
          commodity,
          hub: selectorKey,
          fair_value: fv,
          unit: cacheUnit,
          saved_at: Date.now(),
          data_quality: fc?.data_quality,
        };
        saveCachedResult(meta);
        setCachedResult(meta);
      } catch {}
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        setError('Run aborted (3 minute ceiling reached or user cancelled).');
      } else {
        setError(e?.message || 'Run failed');
      }
    } finally {
      clearTimeout(timeoutId);
      try {
        localStorage.removeItem(EXEC_META_KEY);
      } catch {}
      setRunning(false);
    }
  }

  const forecast = adaptForecast(response?.forecast);
  const scenarios = adaptScenarios(response?.forecast);
  const drivers = flattenDrivers(response?.forecast);
  const provenance = provenanceFor(response?.forecast);
  const dataQuality = response?.forecast?.data_quality;
  const probSum = probabilitySum(scenarios);
  const probMalformed = probSum != null && Math.abs(probSum - 1) > 0.02;
  // Surface raw_output when the agent didn't return a parseable forecast.
  // Today the user just saw blanks; this gives the analyst a diagnostic.
  const showRawDiag = !response?.forecast && (response?.raw_output || '').length > 0;

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500 via-amber-500 to-red-500 flex items-center justify-center shadow-lg">
            <Flame className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-white">
              Forward fair-value · {displayCommodity(commodity)}
              {commodity === 'power' && (
                <span className="text-white"> ({POWER_REGION_SUFFIX[region]})</span>
              )}
              {commodity === 'crude' && (
                <span className="text-white"> ({crudeRegion})</span>
              )}
              {commodity === 'coal' && (
                <span className="text-white"> ({coalRegion})</span>
              )}
              {commodity === 'refined' && (
                <span className="text-white"> ({refinedProduct})</span>
              )}
            </h1>
            <p className="text-slate-300 text-sm mt-1">
              Model-implied forward price vs current market quote — gap is the tradeable signal.
            </p>
            <p className="text-slate-500 text-[11px] mt-0.5">
              Wingman-style fan chart powered by the contractiq_{commodity}_fairvalue agent.
            </p>
          </div>
        </div>
        <PageExplainer
          routeKey={
            getPageExplanation(`commodities-forward-${commodity.replace(/_/g, '-')}`)
              ? `commodities-forward-${commodity.replace(/_/g, '-')}`
              : 'commodities-forward'
          }
        />

        <div data-testid="commodity-selector" className="flex flex-wrap gap-2 mt-4">
          {COMMODITIES.map(c => {
            const active = c.slug === commodity;
            return (
              <button
                key={c.slug}
                type="button"
                onClick={() => switchCommodity(c.slug)}
                disabled={!c.enabled}
                data-testid={`commodity-${c.slug}`}
                className={`px-3 py-1.5 text-xs rounded-md border transition-colors flex items-center gap-1.5
                  ${active ? 'border-orange-500/60 bg-orange-500/15 text-orange-200' : 'border-slate-800 bg-slate-900/40 text-slate-300'}
                  ${!c.enabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-slate-700'}`}
              >
                {c.label}
                {!c.enabled && (
                  <span className="text-[9px] uppercase tracking-wider bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">
                    Coming soon
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {commodity === 'power' ? (
          <div data-testid="region-selector" className="flex flex-wrap gap-2 mt-3">
            {POWER_REGIONS.map(r => {
              const active = r === region;
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => switchRegion(r)}
                  data-testid={`region-${r}`}
                  data-active={active ? 'true' : 'false'}
                  className={`px-2.5 py-1 text-[11px] rounded border font-mono uppercase tracking-wider transition-colors
                    ${active ? 'border-amber-500/50 bg-amber-500/10 text-amber-200' : 'border-slate-800 bg-slate-900/40 text-slate-400'}
                    hover:border-slate-700`}
                >
                  {r}
                </button>
              );
            })}
          </div>
        ) : commodity === 'crude' ? (
          <div data-testid="region-selector" className="flex flex-wrap gap-2 mt-3">
            {CRUDE_REGIONS.map(r => {
              const active = r === crudeRegion;
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => switchCrudeRegion(r)}
                  data-testid={`region-${r}`}
                  data-active={active ? 'true' : 'false'}
                  className={`px-2.5 py-1 text-[11px] rounded border font-mono uppercase tracking-wider transition-colors
                    ${active ? 'border-amber-500/50 bg-amber-500/10 text-amber-200' : 'border-slate-800 bg-slate-900/40 text-slate-400'}
                    hover:border-slate-700`}
                >
                  {r}
                </button>
              );
            })}
          </div>
        ) : commodity === 'coal' ? (
          <div data-testid="region-selector" className="flex flex-wrap gap-2 mt-3">
            {COAL_REGIONS.map(r => {
              const active = r === coalRegion;
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => switchCoalRegion(r)}
                  data-testid={`region-${r}`}
                  data-active={active ? 'true' : 'false'}
                  className={`px-2.5 py-1 text-[11px] rounded border font-mono uppercase tracking-wider transition-colors
                    ${active ? 'border-amber-500/50 bg-amber-500/10 text-amber-200' : 'border-slate-800 bg-slate-900/40 text-slate-400'}
                    hover:border-slate-700`}
                >
                  {r}
                </button>
              );
            })}
          </div>
        ) : commodity === 'refined' ? (
          <div data-testid="product-selector" className="flex flex-wrap gap-2 mt-3">
            {REFINED_PRODUCTS.map(p => {
              const active = p === refinedProduct;
              return (
                <button
                  key={p}
                  type="button"
                  onClick={() => switchRefinedProduct(p)}
                  data-testid={`product-${p}`}
                  data-active={active ? 'true' : 'false'}
                  className={`px-2.5 py-1 text-[11px] rounded border font-mono uppercase tracking-wider transition-colors
                    ${active ? 'border-amber-500/50 bg-amber-500/10 text-amber-200' : 'border-slate-800 bg-slate-900/40 text-slate-400'}
                    hover:border-slate-700`}
                >
                  {p}
                </button>
              );
            })}
          </div>
        ) : (
          <div data-testid="hub-selector" className="flex flex-wrap gap-2 mt-3">
            {hubs.map(h => {
              const active = h === hub;
              const disabled = !enabledCommodity;
              return (
                <button
                  key={h}
                  type="button"
                  onClick={() => !disabled && setHub(h)}
                  disabled={disabled}
                  data-testid={`hub-${h}`}
                  data-active={active ? 'true' : 'false'}
                  className={`px-2.5 py-1 text-[11px] rounded border font-mono uppercase tracking-wider transition-colors
                    ${active ? 'border-amber-500/50 bg-amber-500/10 text-amber-200' : 'border-slate-800 bg-slate-900/40 text-slate-400'}
                    ${disabled ? 'opacity-40 cursor-not-allowed' : 'hover:border-slate-700'}`}
                >
                  {h}
                </button>
              );
            })}
          </div>
        )}

        {cachedResult && cachedResult.fair_value != null && !response && (
          <div
            data-testid="cached-fair-value"
            className="mt-4 rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2 text-xs text-slate-300 flex items-center gap-3"
          >
            <span className="text-slate-500 uppercase tracking-wider text-[10px]">Last fair-value</span>
            <span className="font-mono text-emerald-300 text-sm">
              {cachedResult.fair_value.toFixed(2)}{cachedResult.unit ? ` ${cachedResult.unit}` : ''}
            </span>
            <span className="text-slate-500">·</span>
            <span className="text-slate-400">{selectorKey}</span>
            <span className="text-slate-500">·</span>
            <span className="text-slate-500">{fmtAgo(cachedResult.saved_at)}</span>
            {cachedResult.data_quality && (
              <span className="text-[10px] uppercase tracking-wider text-slate-500 ml-auto">{cachedResult.data_quality}</span>
            )}
          </div>
        )}

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={run}
            disabled={!enabledCommodity || running}
            data-testid="run-analysis"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-orange-500/20 border border-orange-500/40 text-orange-200 text-sm font-semibold hover:bg-orange-500/30 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            Run analysis
          </button>
          {response?.execution_id && (
            <span data-testid="execution-id" className="text-[11px] font-mono text-slate-500">
              exec: {response.execution_id.slice(0, 12)} · {response.duration_ms ?? 0}ms · ${response.cost_usd?.toFixed(4) ?? '0.0000'}
            </span>
          )}
          {error && (
            <span data-testid="run-error" className="text-xs text-rose-300">
              {error}
            </span>
          )}
          {attachStatus && !running && (
            <span data-testid="attach-status" className="text-xs text-amber-300">
              {attachStatus}
            </span>
          )}
        </div>
      </header>

      {COMMODITY_MODULES[commodity]?.kpis?.length ? (
        <section
          data-testid="commodity-kpis"
          aria-label="Sample reference prices — not a live feed"
          className="mb-6"
        >
          <div className="flex items-baseline justify-between mb-2">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">
              Sample reference prices — orientation only. Live fair-value lands in the fan chart after Run analysis.
            </p>
          </div>
          <div className="grid grid-cols-4 gap-3">
            {COMMODITY_MODULES[commodity].kpis.map(k => {
              const label = kpiLabel(k);
              return (
                <div
                  key={label}
                  data-testid={`kpi-card-${label.replace(/[^A-Za-z0-9]+/g, '_')}`}
                  className="relative rounded-xl border border-slate-800 p-4 bg-slate-900/40"
                >
                  <span
                    data-testid="kpi-sample-badge"
                    className="absolute top-2 right-2 text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700"
                    title="Static reference value, not a live quote"
                  >
                    Sample
                  </span>
                  <p className="text-[11px] text-slate-500 uppercase tracking-wider pr-12">{label}</p>
                  <p className="text-xl font-bold text-white mt-1 font-mono">
                    {k.spot.toFixed(2)}{' '}
                    <span className="text-[11px] text-slate-500 font-sans">{k.unit}</span>
                  </p>
                  <p className={`text-[11px] mt-0.5 font-mono ${k.change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {k.change >= 0 ? '+' : ''}{k.change.toFixed(2)}%
                  </p>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {probMalformed && (
        <div
          data-testid="prob-malformed-banner"
          className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 text-rose-200 text-xs px-3 py-2 flex items-center gap-2"
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          probabilities do not sum to 1 (got {probSum?.toFixed(3)}) — agent output may be malformed
        </div>
      )}

      <div className="grid grid-cols-12 gap-6 mb-6">
        <section className="col-span-8">
          <FanChart
            forecast={forecast}
            unit={
              response?.forecast?.unit
                || (response?.forecast?.anchor_currency
                  ? `${response.forecast.anchor_currency}/MWh`
                  : '—')
            }
            title={
              commodity === 'power'
                ? `${POWER_REGION_SUFFIX[region]} forward (Power)`
                : `${selectorKey} forward (${displayCommodity(commodity)})`
            }
            dataQuality={dataQuality}
          />
        </section>
        <aside className="col-span-4">
          <h2 className="text-sm font-semibold text-white mb-2">Scenarios</h2>
          <ScenarioList scenarios={scenarios} />
        </aside>
      </div>

      <div className="mb-6">
        <ThesisPanel
          summary={response?.forecast?.summary}
          narrativeMarkdown={response?.forecast?.narrative_markdown}
          drivers={drivers}
          confidence={confidenceNumber(response?.forecast?.confidence as any)}
        />
      </div>

      <div className="grid grid-cols-12 gap-6 mb-6">
        <section
          data-testid="active-contracts"
          className="col-span-7 rounded-xl border border-slate-800 bg-slate-900/40 p-6"
        >
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
              <FileText className="w-3.5 h-3.5 text-orange-300" /> Active contracts
            </h2>
            <a href="/contracts" className="text-[11px] text-slate-500 hover:text-white">
              All contracts →
            </a>
          </div>
          {contractsLoading ? (
            <p data-testid="active-contracts-loading" className="text-xs text-slate-500">
              loading contracts...
            </p>
          ) : contracts.length === 0 ? (
            <p data-testid="active-contracts-empty" className="text-xs text-slate-500">
              No contracts tagged to {displayCommodity(commodity)} yet.
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="text-left py-2">Contract</th>
                  <th className="text-left py-2">Counterparty</th>
                  <th className="text-left py-2">Capacity</th>
                  <th className="text-left py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {contracts.map(c => {
                  const cp = c.counterparty_b || c.counterparty_a || '—';
                  const cap = c.total_capacity_mw != null ? `${c.total_capacity_mw} MW` : '—';
                  return (
                    <tr
                      key={c.id}
                      data-testid={`contract-row-${c.id}`}
                      className="border-b border-slate-800/40 hover:bg-slate-800/20"
                    >
                      <td className="py-2.5 text-slate-200 font-mono">
                        <a className="hover:text-white" href={`/contracts/${c.id}`}>
                          {c.title || c.id.slice(0, 8)}
                        </a>
                      </td>
                      <td className="py-2.5 text-slate-300">{cp}</td>
                      <td className="py-2.5 text-slate-400 font-mono">{cap}</td>
                      <td className="py-2.5">
                        <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border border-orange-500/40 bg-orange-500/15 text-orange-200">
                          {c.status || 'unknown'}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>

        <section
          data-testid="commodity-glossary"
          className="col-span-5 rounded-xl border border-slate-800 bg-slate-900/40 p-6"
        >
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5 mb-3">
            <Sparkles className="w-3.5 h-3.5 text-orange-300" /> Glossary
          </h2>
          <dl className="space-y-3">
            {(COMMODITY_MODULES[commodity]?.glossary || []).map(g => (
              <div key={g.term}>
                <dt className="text-xs font-semibold text-white">{g.term}</dt>
                <dd className="text-[11px] text-slate-500 leading-relaxed mt-0.5">{g.def}</dd>
              </div>
            ))}
            {!(COMMODITY_MODULES[commodity]?.glossary?.length) && (
              <p className="text-[11px] text-slate-500">No glossary defined for this commodity yet.</p>
            )}
          </dl>
        </section>
      </div>

      {showRawDiag && (
        <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/5 text-amber-100 text-xs">
          <button
            type="button"
            data-testid="raw-output-toggle"
            onClick={() => setShowRaw(v => !v)}
            className="w-full flex items-center gap-2 px-3 py-2 font-semibold uppercase tracking-wider text-[10px]"
          >
            {showRaw ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            agent returned unparsed text — click to inspect
          </button>
          {showRaw && (
            <pre
              data-testid="raw-output"
              className="px-3 pb-3 max-h-72 overflow-auto whitespace-pre-wrap text-[11px] font-mono text-amber-200/80"
            >
              {response?.raw_output}
            </pre>
          )}
        </div>
      )}

      {response && (
        <div className="mb-4 rounded-md border border-slate-800 bg-slate-900/40 text-xs">
          <button
            type="button"
            data-testid="audit-toggle"
            onClick={() => setShowAudit(v => !v)}
            className="w-full flex items-center gap-2 px-3 py-2 font-semibold uppercase tracking-wider text-[10px] text-slate-400"
          >
            {showAudit ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            execution details
          </button>
          {showAudit && (
            <div
              data-testid="audit-drawer"
              className="px-3 pb-3 text-[11px] font-mono text-slate-300"
            >
              <div className="grid grid-cols-2 gap-2">
                <div>execution_id</div><div>{response.execution_id || '—'}</div>
                <div>model</div><div>{response.model || '—'}</div>
                <div>tool_calls</div><div>{response.tool_calls ?? '—'}</div>
                <div>duration_ms</div><div>{response.duration_ms ?? '—'}</div>
                <div>cost_usd</div><div>${response.cost_usd?.toFixed(6) ?? '0.000000'}</div>
                <div>input_tokens</div><div>{response.input_tokens ?? '—'}</div>
                <div>output_tokens</div><div>{response.output_tokens ?? '—'}</div>
                <div>data_quality</div><div>{dataQuality || '—'}</div>
              </div>
              {response.meta?.tool_calls && response.meta.tool_calls.length > 0 && (
                <div className="mt-3 border-t border-slate-800 pt-3">
                  <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
                    tool calls ({response.meta.tool_calls.length})
                  </div>
                  <ul data-testid="audit-tool-calls" className="space-y-2">
                    {response.meta.tool_calls.map((tc, i) => (
                      <li
                        key={i}
                        data-testid={`audit-tool-call-${i}`}
                        className="rounded border border-slate-800 bg-slate-950/40 px-2 py-1.5"
                      >
                        <div className="text-slate-200 text-[11px]">
                          {tc.tool_name || '(unnamed)'}
                        </div>
                        <div className="text-slate-500 text-[10px] mt-0.5">
                          args: {tc.args ? JSON.stringify(tc.args).slice(0, 200) : '{}'}
                        </div>
                        {tc.content_snippet && (
                          <div className="text-slate-400 text-[10px] mt-0.5 whitespace-pre-wrap">
                            {tc.content_snippet}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <ProvenanceBanner
        provenance={provenance}
        postProcessed={Boolean(response?.forecast?.meta?.post_processed)}
      />
    </div>
  );
}
