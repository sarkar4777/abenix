'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  FileCheck2, ChevronRight, Play, Loader2, AlertTriangle, Building2,
  DollarSign, Briefcase, Info, FileText, Search, Flag, CheckCircle2,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }

// Small curated list. Users can type ANY two-letter ISO code manually too via the input.
const COUNTRIES: { code: string; name: string }[] = [
  { code: 'US', name: 'United States' }, { code: 'GB', name: 'United Kingdom' },
  { code: 'DE', name: 'Germany' }, { code: 'FR', name: 'France' }, { code: 'IT', name: 'Italy' },
  { code: 'ES', name: 'Spain' }, { code: 'NL', name: 'Netherlands' }, { code: 'BE', name: 'Belgium' },
  { code: 'PL', name: 'Poland' }, { code: 'CZ', name: 'Czechia' }, { code: 'AT', name: 'Austria' },
  { code: 'CH', name: 'Switzerland' }, { code: 'SE', name: 'Sweden' }, { code: 'NO', name: 'Norway' },
  { code: 'DK', name: 'Denmark' }, { code: 'FI', name: 'Finland' }, { code: 'IE', name: 'Ireland' },
  { code: 'PT', name: 'Portugal' }, { code: 'GR', name: 'Greece' }, { code: 'HU', name: 'Hungary' },
  { code: 'RO', name: 'Romania' }, { code: 'BG', name: 'Bulgaria' }, { code: 'SK', name: 'Slovakia' },
  { code: 'HR', name: 'Croatia' }, { code: 'SI', name: 'Slovenia' }, { code: 'EE', name: 'Estonia' },
  { code: 'LV', name: 'Latvia' }, { code: 'LT', name: 'Lithuania' }, { code: 'MT', name: 'Malta' },
  { code: 'CY', name: 'Cyprus' }, { code: 'LU', name: 'Luxembourg' },
  { code: 'TR', name: 'Turkey' }, { code: 'RU', name: 'Russia' }, { code: 'UA', name: 'Ukraine' },
  { code: 'CN', name: 'China' }, { code: 'HK', name: 'Hong Kong' }, { code: 'JP', name: 'Japan' },
  { code: 'KR', name: 'South Korea' }, { code: 'SG', name: 'Singapore' }, { code: 'IN', name: 'India' },
  { code: 'AE', name: 'United Arab Emirates' }, { code: 'SA', name: 'Saudi Arabia' }, { code: 'IL', name: 'Israel' },
  { code: 'ZA', name: 'South Africa' }, { code: 'BR', name: 'Brazil' }, { code: 'MX', name: 'Mexico' },
  { code: 'AR', name: 'Argentina' }, { code: 'CA', name: 'Canada' }, { code: 'AU', name: 'Australia' },
  { code: 'NZ', name: 'New Zealand' }, { code: 'IR', name: 'Iran' }, { code: 'KP', name: 'North Korea' },
];

const INDUSTRIES = [
  { key: 'energy_trading', label: 'Energy Trading' },
  { key: 'oil_gas', label: 'Oil & Gas' },
  { key: 'utility_regulated', label: 'Regulated Utility' },
  { key: 'wood_furniture_paper', label: 'Wood, Furniture & Paper' },
  { key: 'manufacturing', label: 'Manufacturing' },
  { key: 'mining_extractives', label: 'Mining / Extractives' },
  { key: 'shipping_maritime', label: 'Shipping / Maritime' },
  { key: 'construction', label: 'Construction' },
  { key: 'real_estate', label: 'Real Estate' },
  { key: 'banking_regulated', label: 'Regulated Banking' },
  { key: 'insurance_regulated', label: 'Regulated Insurance' },
  { key: 'technology_saas', label: 'Technology / SaaS' },
  { key: 'telecoms', label: 'Telecoms' },
  { key: 'crypto_vasp', label: 'Crypto / Virtual Asset Service Provider' },
  { key: 'gambling_casinos', label: 'Gambling / Casinos' },
  { key: 'arms_defence', label: 'Arms & Defence' },
  { key: 'money_service_business', label: 'Money Service Business' },
  { key: 'professional_services', label: 'Professional Services' },
  { key: 'wholesale_distribution', label: 'Wholesale / Distribution' },
  { key: 'agriculture', label: 'Agriculture / Agri-commodities' },
  { key: 'cash_intensive_retail', label: 'Cash-Intensive Retail' },
  { key: 'precious_metals_stones', label: 'Precious Metals / Stones' },
  { key: 'public_sector', label: 'Public Sector' },
  { key: 'healthcare_regulated', label: 'Regulated Healthcare' },
  { key: 'education', label: 'Education' },
  { key: 'other', label: 'Other' },
];

interface ContractRow {
  id: string;
  title?: string;
  counterparty_a?: string;
  counterparty_b?: string;
  contract_value?: number;
  currency?: string;
  total_capacity_mw?: number;
  extraction_summary?: any;
}

interface ExtractedCounterparty {
  name: string;
  contract_ids: string[];
  contract_count: number;
  notional_usd_estimate?: number;
  primary_business?: string;
  country_iso2?: string;
}

export default function NewKycCheckPage() {
  const router = useRouter();

  // Form state — NO hardcoded defaults. Everything starts empty / null.
  const [form, setForm] = useState({
    counterparty_name: '',
    country_iso2: '',
    industry_segment: '',
    annual_notional_usd: '' as string | number,
    activity_trigger: 'Pre-Check', // only enum pick, not a fact
    type_of_business_relationship: 'Noncore',
    profit_centre: '',
    primary_business: '',
    description: '',
  });
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Counterparty discovery from existing contracts.
  const [contracts, setContracts] = useState<ContractRow[]>([]);
  const [contractsLoading, setContractsLoading] = useState(true);
  const [pickerSearch, setPickerSearch] = useState('');
  const [pickerMode, setPickerMode] = useState<'existing' | 'new'>('existing');

  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }));

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetch(`${API_URL}/api/contractiq/contracts?limit=200`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(j => setContracts(j.data || []))
      .catch(() => {})
      .finally(() => setContractsLoading(false));
  }, []);

  // Deduplicate counterparties across all contracts, with aggregate notional + metadata
  const extractedCounterparties: ExtractedCounterparty[] = useMemo(() => {
    const bag = new Map<string, ExtractedCounterparty>();
    for (const c of contracts) {
      for (const name of [c.counterparty_a, c.counterparty_b]) {
        if (!name || !name.trim()) continue;
        const key = name.trim();
        const existing = bag.get(key) || {
          name: key,
          contract_ids: [],
          contract_count: 0,
          notional_usd_estimate: 0,
          primary_business: undefined,
          country_iso2: undefined,
        };
        existing.contract_ids.push(c.id);
        existing.contract_count += 1;
        if (c.contract_value) {
          existing.notional_usd_estimate = (existing.notional_usd_estimate || 0) + Number(c.contract_value);
        }
        const s = c.extraction_summary || {};
        if (!existing.primary_business && s.contract_type_detected) existing.primary_business = s.contract_type_detected;
        bag.set(key, existing);
      }
    }
    return Array.from(bag.values()).sort((a, b) => b.contract_count - a.contract_count);
  }, [contracts]);

  const filteredCounterparties = useMemo(() => {
    if (!pickerSearch.trim()) return extractedCounterparties;
    const q = pickerSearch.toLowerCase();
    return extractedCounterparties.filter(c =>
      c.name.toLowerCase().includes(q)
      || (c.primary_business || '').toLowerCase().includes(q)
    );
  }, [pickerSearch, extractedCounterparties]);

  const selectCounterparty = (cp: ExtractedCounterparty) => {
    setForm(f => ({
      ...f,
      counterparty_name: cp.name,
      primary_business: cp.primary_business || f.primary_business,
      country_iso2: cp.country_iso2 || f.country_iso2,
      annual_notional_usd: cp.notional_usd_estimate && cp.notional_usd_estimate > 0 ? cp.notional_usd_estimate : f.annual_notional_usd,
    }));
    setPickerMode('new'); // close picker, show the form
  };

  const canSubmit = form.counterparty_name.trim().length > 1
    && /^[A-Z]{2}$/.test(form.country_iso2.trim().toUpperCase())
    && !!form.industry_segment
    && Number(form.annual_notional_usd) > 0;

  const run = async () => {
    if (!canSubmit) {
      setError('Please fill counterparty name, country (2-letter ISO), industry, and notional.');
      return;
    }
    setError(null);
    setRunning(true);
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/run`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          country_iso2: form.country_iso2.toUpperCase(),
          annual_notional_usd: Number(form.annual_notional_usd),
        }),
      });
      const j = await r.json();
      if (j.error) {
        setError(j.error.message || j.error);
        setRunning(false);
        return;
      }
      if (j.data?.id) {
        router.push(`/credit-risk/kyc/${j.data.id}`);
        return;
      }
    } catch (e: any) {
      setError(e.message || 'Request failed');
    }
    setRunning(false);
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <a href="/credit-risk" className="hover:text-slate-300">Counterparty Risk</a>
            <ChevronRight className="w-3 h-3" />
            <a href="/credit-risk/kyc" className="hover:text-slate-300">KYC Checks</a>
            <ChevronRight className="w-3 h-3" />
            <span>New</span>
          </div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3 mt-1">
            <FileCheck2 className="w-7 h-7 text-cyan-400" />
            New KYC Standard Check
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            The agent screens sanctions (OFAC/EU/UN/UK/CA), PEPs (OpenSanctions/Wikidata),
            adverse media (GDELT/Google News/Tavily), UBOs (GLEIF/OpenCorporates/UK PSC),
            country risk (TI&nbsp;CPI/FATF/EU), and enforcement (SEC/DOJ/FCA) — scored against the
            SEE-BV standard taxonomy.
          </p>
        </div>

        {/* Picker: existing counterparties vs. new */}
        <div className="flex gap-2 border-b border-slate-800">
          <button
            onClick={() => setPickerMode('existing')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
              pickerMode === 'existing'
                ? 'text-white border-emerald-400'
                : 'text-slate-400 border-transparent hover:text-white'
            }`}
            data-testid="kyc-tab-existing"
          >
            From My Contracts ({extractedCounterparties.length})
          </button>
          <button
            onClick={() => setPickerMode('new')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
              pickerMode === 'new'
                ? 'text-white border-emerald-400'
                : 'text-slate-400 border-transparent hover:text-white'
            }`}
            data-testid="kyc-tab-new"
          >
            New Counterparty
          </button>
        </div>

        {/* Existing counterparty picker */}
        {pickerMode === 'existing' && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl">
              <div className="p-4 border-b border-slate-800 flex items-center gap-3">
                <Search className="w-4 h-4 text-slate-500" />
                <input
                  value={pickerSearch}
                  onChange={e => setPickerSearch(e.target.value)}
                  placeholder="Search your contract counterparties…"
                  className="flex-1 bg-transparent border-0 outline-none text-sm text-white placeholder-slate-500"
                  data-testid="kyc-picker-search"
                />
                {extractedCounterparties.length > 0 && (
                  <span className="text-[10px] text-slate-500">
                    {filteredCounterparties.length} / {extractedCounterparties.length}
                  </span>
                )}
              </div>

              {contractsLoading ? (
                <div className="p-8 flex items-center justify-center">
                  <Loader2 className="w-5 h-5 text-emerald-400 animate-spin" />
                </div>
              ) : extractedCounterparties.length === 0 ? (
                <div className="p-8 text-center">
                  <FileText className="w-10 h-10 text-slate-700 mx-auto mb-3" />
                  <p className="text-sm text-slate-400 mb-1">No contracts uploaded yet</p>
                  <p className="text-xs text-slate-600 mb-4">Upload contracts to auto-populate counterparties here, or add one manually.</p>
                  <div className="flex justify-center gap-2">
                    <a href="/upload" className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:bg-slate-700">
                      Upload Contract
                    </a>
                    <button
                      onClick={() => setPickerMode('new')}
                      className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-emerald-600 text-white text-xs font-medium"
                    >
                      Add Manually
                    </button>
                  </div>
                </div>
              ) : (
                <div className="divide-y divide-slate-800/60 max-h-[420px] overflow-y-auto">
                  {filteredCounterparties.map((cp) => (
                    <button
                      key={cp.name}
                      onClick={() => selectCounterparty(cp)}
                      data-testid={`kyc-picker-${cp.name.slice(0, 20)}`}
                      className="w-full flex items-center gap-4 p-4 hover:bg-slate-700/20 transition text-left"
                    >
                      <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center text-sm font-semibold text-emerald-300 shrink-0">
                        {cp.name.charAt(0).toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-white truncate">{cp.name}</p>
                        <div className="flex items-center gap-3 text-[11px] text-slate-500 mt-0.5">
                          <span>{cp.contract_count} contract{cp.contract_count > 1 ? 's' : ''}</span>
                          {cp.notional_usd_estimate && cp.notional_usd_estimate > 0 && (
                            <span>· ~${(cp.notional_usd_estimate / 1e6).toFixed(1)}M aggregate</span>
                          )}
                          {cp.primary_business && <span>· {cp.primary_business}</span>}
                        </div>
                      </div>
                      <CheckCircle2 className="w-4 h-4 text-slate-700 shrink-0" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}

        {/* Form */}
        {pickerMode === 'new' && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
            <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 space-y-4">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <Building2 className="w-4 h-4 text-cyan-400" /> Counterparty Identity
              </h2>
              <div className="grid grid-cols-2 gap-4">
                <label className="col-span-2 block text-xs text-slate-400">
                  Legal Name <span className="text-red-400">*</span>
                  <input
                    value={form.counterparty_name}
                    onChange={e => set('counterparty_name', e.target.value)}
                    placeholder="Full legal name of the counterparty"
                    data-testid="kyc-name"
                    autoFocus
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                  />
                </label>
                <label className="block text-xs text-slate-400">
                  Country of Domicile (ISO-2) <span className="text-red-400">*</span>
                  <select
                    value={form.country_iso2}
                    onChange={e => set('country_iso2', e.target.value)}
                    data-testid="kyc-country"
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                  >
                    <option value="">— Select —</option>
                    {COUNTRIES.map(c => (
                      <option key={c.code} value={c.code}>{c.code} — {c.name}</option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs text-slate-400">
                  Primary Business <span className="text-slate-600">(optional)</span>
                  <input
                    value={form.primary_business}
                    onChange={e => set('primary_business', e.target.value)}
                    placeholder="e.g. Wood, Furniture & Paper Manufacturing"
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                  />
                </label>
                <label className="col-span-2 block text-xs text-slate-400">
                  Short Description of Business Relationship <span className="text-slate-600">(optional)</span>
                  <input
                    value={form.description}
                    onChange={e => set('description', e.target.value)}
                    placeholder="e.g. Gas supply / Capacity agreement"
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                  />
                </label>
              </div>
            </section>

            <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 space-y-4">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <DollarSign className="w-4 h-4 text-emerald-400" /> Risk Indicators
              </h2>
              <div className="grid grid-cols-2 gap-4">
                <label className="block text-xs text-slate-400">
                  Industry Segment (Indicator III) <span className="text-red-400">*</span>
                  <select
                    value={form.industry_segment}
                    onChange={e => set('industry_segment', e.target.value)}
                    data-testid="kyc-industry"
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                  >
                    <option value="">— Select —</option>
                    {INDUSTRIES.map(i => (
                      <option key={i.key} value={i.key}>{i.label}</option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs text-slate-400">
                  Annual Contracted Volume / Notional (USD) <span className="text-red-400">*</span>
                  <input
                    type="number"
                    min={1}
                    value={form.annual_notional_usd}
                    onChange={e => set('annual_notional_usd', e.target.value)}
                    placeholder="e.g. 25000000"
                    data-testid="kyc-notional"
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                  />
                </label>
              </div>
              <p className="text-[10px] text-slate-500 flex items-start gap-2">
                <Info className="w-3 h-3 mt-0.5 text-cyan-500/70 shrink-0" />
                Indicator I (Country CPI rank) is fetched live from Transparency International via OurWorldInData.
                Volume bands align with common banking templates ($0.5M / $5M / $50M / $250M / $1B cut-offs).
              </p>
            </section>

            <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 space-y-4">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <Briefcase className="w-4 h-4 text-amber-400" /> Administrative <span className="text-[10px] text-slate-500 font-normal">(optional)</span>
              </h2>
              <div className="grid grid-cols-3 gap-4">
                <label className="block text-xs text-slate-400">
                  Activity Trigger
                  <select
                    value={form.activity_trigger}
                    onChange={e => set('activity_trigger', e.target.value)}
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                  >
                    <option>Pre-Check</option>
                    <option>Periodic Check</option>
                    <option>Ad-hoc Check</option>
                  </select>
                </label>
                <label className="block text-xs text-slate-400">
                  Business Relationship
                  <select
                    value={form.type_of_business_relationship}
                    onChange={e => set('type_of_business_relationship', e.target.value)}
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                  >
                    <option>Core</option>
                    <option>Noncore</option>
                  </select>
                </label>
                <label className="block text-xs text-slate-400">
                  Profit Centre / Booking Entity
                  <input
                    value={form.profit_centre}
                    onChange={e => set('profit_centre', e.target.value)}
                    placeholder="e.g. trading desk / BU name"
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                  />
                </label>
              </div>
            </section>

            {error && (
              <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/20 rounded-lg p-3">
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> {error}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <a
                href="/credit-risk/kyc"
                className="px-4 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-slate-300 text-sm hover:bg-slate-700"
              >
                Cancel
              </a>
              <button
                onClick={run}
                disabled={running || !canSubmit}
                data-testid="kyc-run"
                className="px-5 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white font-semibold text-sm flex items-center gap-2 hover:shadow-lg hover:shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {running
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> Running checks (60–120s)…</>
                  : <><Play className="w-4 h-4" /> Run KYC Standard Check</>
                }
              </button>
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
}
