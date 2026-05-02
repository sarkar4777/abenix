'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Gauge, Play, Loader2, ChevronDown, CheckCircle2, Clock } from 'lucide-react';
import { fetchWithToast, toastSuccess } from '@/stores/toastStore';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return localStorage.getItem('st_token') || ''; }

export default function SimulationsPage() {
  const [presets, setPresets] = useState<any>({});
  const [history, setHistory] = useState<any[]>([]);
  const [selected, setSelected] = useState('visa_policy');
  const [params, setParams] = useState<any>({});
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    (async () => {
      const headers = { Authorization: `Bearer ${getToken()}` };
      const [presetsJson, histJson] = await Promise.all([
        fetchWithToast(`${API_URL}/api/st/simulations/presets`, { headers }, 'Failed to load simulation presets'),
        fetchWithToast(`${API_URL}/api/st/simulations`, { headers }, 'Failed to load simulation history'),
      ]);
      if (presetsJson.data) setPresets(presetsJson.data);
      if (histJson.data) setHistory(histJson.data);
    })();
  }, []);

  useEffect(() => {
    const preset = presets[selected];
    if (preset?.parameters) {
      const defaults: any = {};
      Object.entries(preset.parameters).forEach(([k, v]: [string, any]) => {
        defaults[k] = v.default;
      });
      setParams(defaults);
    }
  }, [selected, presets]);

  async function runSimulation() {
    setRunning(true);
    setResult(null);
    const headers = { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' };
    const json = await fetchWithToast(
      `${API_URL}/api/st/simulations/run`,
      { method: 'POST', headers, body: JSON.stringify({ type: selected, parameters: params }) },
      'Simulation failed',
    );
    if (json.data) {
      setResult(json.data);
      toastSuccess('Simulation complete');
    }
    const histJson = await fetchWithToast(
      `${API_URL}/api/st/simulations`,
      { headers: { Authorization: `Bearer ${getToken()}` } },
      'Failed to refresh simulation history',
    );
    if (histJson.data) setHistory(histJson.data);
    setRunning(false);
  }

  const preset = presets[selected] || {};

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Simulations</h1>
        <p className="text-sm text-green-300/40 mt-1">What-if scenarios via Abenix st-simulator agent (scenario_planner + weather_simulator + financial_calculator)</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.5fr] gap-6">
        {/* Left: Simulation type picker + params */}
        <div>
          {/* Type cards */}
          <div className="space-y-3 mb-6">
            {Object.entries(presets).map(([key, p]: [string, any]) => (
              <button key={key} onClick={() => { setSelected(key); setResult(null); }}
                className={`w-full text-left rounded-xl border p-4 transition-all ${selected === key ? 'border-green-500 bg-green-900/30' : 'border-green-800/40 bg-[#0A2818]/50 hover:border-green-600/50'}`}>
                <h3 className="text-sm font-semibold text-white">{p.title}</h3>
                <p className="text-xs text-green-300/30 mt-1">{p.description}</p>
              </button>
            ))}
          </div>

          {/* Parameters */}
          {preset.parameters && (
            <div className="rounded-xl border border-green-800/40 bg-[#0A2818]/50 p-5">
              <h3 className="text-sm font-semibold text-green-200 mb-4">Parameters</h3>
              <div className="space-y-3">
                {Object.entries(preset.parameters).map(([key, spec]: [string, any]) => (
                  <div key={key}>
                    <label className="text-xs text-green-300/40 block mb-1">{spec.label}</label>
                    {spec.options ? (
                      <select value={params[key] || spec.default}
                        onChange={e => setParams({ ...params, [key]: e.target.value })}
                        className="w-full bg-green-900/30 border border-green-700/40 rounded-lg px-3 py-2 text-white text-sm focus:border-green-500 focus:outline-none">
                        {spec.options.map((o: string) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : spec.type === 'number' ? (
                      <input type="number" value={params[key] ?? spec.default}
                        min={spec.min} max={spec.max}
                        onChange={e => setParams({ ...params, [key]: Number(e.target.value) })}
                        className="w-full bg-green-900/30 border border-green-700/40 rounded-lg px-3 py-2 text-white text-sm focus:border-green-500 focus:outline-none" />
                    ) : (
                      <input type="text" value={params[key] || spec.default}
                        onChange={e => setParams({ ...params, [key]: e.target.value })}
                        className="w-full bg-green-900/30 border border-green-700/40 rounded-lg px-3 py-2 text-white text-sm focus:border-green-500 focus:outline-none" />
                    )}
                  </div>
                ))}
              </div>
              <button onClick={runSimulation} disabled={running}
                className="w-full mt-4 px-4 py-3 rounded-lg bg-gradient-to-r from-green-600 to-green-700 text-white text-sm font-semibold hover:shadow-lg hover:shadow-green-600/25 transition-all flex items-center justify-center gap-2 disabled:opacity-50">
                {running ? <><Loader2 className="w-4 h-4 animate-spin" /> Running simulation via Abenix...</> : <><Play className="w-4 h-4" /> Run Simulation</>}
              </button>
            </div>
          )}
        </div>

        {/* Right: Results */}
        <div>
          {result ? (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl border border-green-600/40 bg-[#0A2818]/70 p-6">
              <div className="flex items-center gap-2 mb-4">
                <CheckCircle2 className="w-5 h-5 text-green-400" />
                <h2 className="text-lg font-bold text-white">{result.results?.title || result.title || 'Simulation Results'}</h2>
              </div>

              {/* Summary */}
              {(result.results?.summary || result.results?.text) && (
                <p className="text-sm text-green-200/60 mb-4 leading-relaxed">{result.results.summary || result.results.text}</p>
              )}

              {/* Key Metrics */}
              {result.results?.key_metrics && (
                <div className="grid grid-cols-2 gap-3 mb-4">
                  {Object.entries(result.results.key_metrics).map(([k, v]: [string, any]) => (
                    <div key={k} className="rounded-xl bg-green-900/30 border border-green-800/30 p-3">
                      <div className="text-xs text-green-400/40">{k.replace(/_/g, ' ')}</div>
                      <div className="text-lg font-bold text-green-300">{typeof v === 'number' ? v.toLocaleString() : v}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Scenarios */}
              {result.results?.scenarios?.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-semibold text-green-200 mb-2">Scenarios</h3>
                  <div className="space-y-2">
                    {result.results.scenarios.map((s: any, i: number) => (
                      <div key={i} className="rounded-lg bg-green-900/20 border border-green-800/20 p-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-white font-medium">{s.label}</span>
                          <span className="text-sm text-green-400 font-mono">{typeof s.value === 'number' ? s.value.toLocaleString() : s.value}</span>
                        </div>
                        {s.description && <p className="text-xs text-green-300/30 mt-1">{s.description}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recommendations */}
              {result.results?.recommendations?.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-semibold text-green-200 mb-2">Recommendations</h3>
                  <ul className="space-y-1">
                    {result.results.recommendations.map((r: string, i: number) => (
                      <li key={i} className="text-xs text-green-200/50 flex items-start gap-2">
                        <span className="text-green-500 mt-0.5">*</span> {r}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Methodology */}
              {result.results?.methodology && (
                <div className="pt-3 border-t border-green-800/30">
                  <p className="text-[10px] text-green-400/20">{result.results.methodology}</p>
                </div>
              )}

              {/* Agent cost */}
              {result.agent_cost !== undefined && (
                <div className="mt-2 text-[10px] text-green-400/20">
                  Agent cost: ${result.agent_cost?.toFixed(4)} | Tokens: {result.agent_tokens?.toLocaleString()}
                </div>
              )}
            </motion.div>
          ) : (
            <div className="rounded-2xl border border-green-800/40 bg-[#0A2818]/30 p-12 text-center">
              <Gauge className="w-10 h-10 text-green-600/30 mx-auto mb-4" />
              <p className="text-green-300/30">Select a simulation type and run it</p>
              <p className="text-xs text-green-400/20 mt-2">The st-simulator agent will use scenario_planner, weather_simulator, and financial_calculator tools</p>
            </div>
          )}

          {/* History */}
          {history.length > 0 && (
            <div className="mt-6">
              <h3 className="text-sm font-semibold text-green-200 mb-3">Previous Simulations</h3>
              <div className="space-y-2">
                {history.slice(0, 5).map((s: any) => (
                  <div key={s.id} className="rounded-lg border border-green-800/30 bg-[#0A2818]/30 p-3 flex items-center gap-3">
                    <Clock className="w-3.5 h-3.5 text-green-500/30" />
                    <div className="flex-1">
                      <p className="text-xs text-white">{s.title}</p>
                      <p className="text-[10px] text-green-400/20">{s.type} &middot; {new Date(s.created_at).toLocaleDateString()}</p>
                    </div>
                    <button onClick={() => setResult(s)} className="text-xs text-green-400 hover:text-green-300">View</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
