'use client';

import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle, Binary, Brain, CloudUpload, FileText, FlaskConical,
  Gavel, Globe2, Loader2, Package, Play, Rocket, ScrollText, ShieldAlert,
  Snowflake, Square, Thermometer, Truck,
} from 'lucide-react';
import ScenarioExplainer from '../components/ScenarioExplainer';
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceArea,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  CodeAssetRow, COLDCHAIN_CORRECTOR,
  findAssetByName, uploadAndDeploy, waitForSchemaProbe,
} from '../lib/deploy';
import { findPipelineBySlug, runPipeline, type PipelineKey } from '../lib/pipelineRunner';
import { coldChainShipment } from '../lib/synthetic';

interface Adjudication {
  severity?: string;
  spoilage_risk_pct?: number;
  liability?: string;
  notification_tier?: string;
  evidence?: string[];
  rationale?: string;
  recommended_action?: string;
}

interface ClaimDraft {
  claim_id?: string;
  amount_usd?: number;
  policy_clause_cited?: string;
  excursion_summary?: Record<string, unknown>;
  customer_letter_markdown?: string;
  evidence?: string[];
}

interface MonitorResult {
  smoothed?: { timestamp: string; temp_c: number }[];
  excursions?: { start: string; end: string; duration_min: number; peak_temp_c: number; direction: string }[];
  door_events?: { start: string; end: string; duration_min: number }[];
  summary?: Record<string, number | boolean>;
}

function sevTone(sev?: string): string {
  switch (sev) {
    case 'HIGH':    return 'bg-red-500/20 text-red-300 border-red-500/40';
    case 'MEDIUM':  return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
    case 'LOW':     return 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
    case 'OK':      return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
    default:        return 'bg-slate-700/60 text-slate-300 border-slate-600/40';
  }
}

export default function ColdChainTab() {
  const [asset, setAsset] = useState<CodeAssetRow | null>(null);
  const [deploying, setDeploying] = useState(false);
  const [probeStatus, setProbeStatus] = useState<string>('');
  const [deployError, setDeployError] = useState<string>('');

  const [pipelineId, setPipelineId] = useState<PipelineKey | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [rawReadings, setRawReadings] = useState<{ i: number; temp: number; door: boolean }[]>([]);
  const [monitor, setMonitor] = useState<MonitorResult | null>(null);
  const [adjudication, setAdjudication] = useState<Adjudication | null>(null);
  const [claim, setClaim] = useState<ClaimDraft | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    (async () => {
      const [id, existing] = await Promise.all([
        findPipelineBySlug('iot-coldchain-pipeline'),
        findAssetByName(COLDCHAIN_CORRECTOR.slug, {
          spec: COLDCHAIN_CORRECTOR, skipStale: true,
        }),
      ]);
      setPipelineId(id);
      if (existing && existing.status === 'ready') setAsset(existing);
    })();
  }, []);

  const deploy = async () => {
    setDeployError(''); setDeploying(true);
    try {
      const a = await uploadAndDeploy(COLDCHAIN_CORRECTOR);
      setAsset(a);
      if (!a.output_schema) {
        setProbeStatus('Running smoke-test probe in k8s Job…');
        const ok = await waitForSchemaProbe(a.id);
        setProbeStatus(ok ? 'Schema probe complete.' : 'Schema probe timed out (asset still usable).');
      }
    } catch (e) {
      setDeployError((e as Error).message);
    } finally {
      setDeploying(false);
    }
  };

  const startShipment = async () => {
    if (!pipelineId) { setDeployError('Cold-chain pipeline not seeded yet.'); return; }
    if (!asset) { setDeployError('Deploy the cold-chain-corrector asset first.'); return; }
    setStreaming(true); setRawReadings([]); setMonitor(null); setAdjudication(null); setClaim(null);
    setLog([]);
    abortRef.current = new AbortController();

    const shipment = coldChainShipment();

    // Animate the raw reading stream up front so the user can watch
    // the excursion spike unfold, BEFORE we show what the pipeline
    // makes of it.
    for (let i = 0; i < shipment.readings.length; i++) {
      if (abortRef.current.signal.aborted) break;
      const r = shipment.readings[i];
      setRawReadings((prev) => [...prev, { i, temp: r.temp_c, door: r.door_open }]);
      setLog((p) => [...p.slice(-9), `${r.timestamp}  ${r.temp_c.toFixed(1)}°C  ${r.door_open ? '[DOOR OPEN]' : ''}  ${r.label}`]);
      await new Promise((res) => setTimeout(res, 180));
    }

    // Now fire the pipeline against the full window.
    setLog((p) => [...p, 'Sending full window to pipeline…']);
    const result = await runPipeline(
      pipelineId, shipment,
      { coldchain_asset_id: asset.id },
      { waitSeconds: 180, signal: abortRef.current.signal },
    );
    if (!result.ok) {
      setLog((p) => [...p, `ERR: ${result.error ?? 'unknown error'}`]);
    } else {
      const payload = result.final_output ?? {};
      if (payload.monitor) setMonitor(payload.monitor as MonitorResult);
      if (payload.adjudication) setAdjudication(payload.adjudication as Adjudication);
      if (payload.claim) setClaim(payload.claim as ClaimDraft);
      setLog((p) => [
        ...p,
        `done — status=${result.status}  excursions=${((payload.monitor as MonitorResult)?.excursions ?? []).length}`,
      ]);
    }
    setStreaming(false);
  };

  const stop = () => abortRef.current?.abort();

  const chartData = rawReadings.map((r) => {
    const sm = monitor?.smoothed?.[r.i];
    return {
      i: r.i,
      raw: r.temp,
      smoothed: sm?.temp_c,
    };
  });

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-6">
      <div className="space-y-6 min-w-0">
      <DeployRow asset={asset} busy={deploying} onDeploy={deploy} />
      {probeStatus && <div className="text-xs text-slate-400">{probeStatus}</div>}
      {deployError && (
        <div className="flex items-start gap-2 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg p-3">
          <AlertTriangle className="w-4 h-4 mt-0.5" />
          <span>{deployError}</span>
        </div>
      )}

      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-white font-semibold flex items-center gap-2">
              <Thermometer className="w-4 h-4 text-cyan-400" />
              Step 2 · Simulate reefer shipment (SFO → LAX, 20 waypoints)
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Scripted scenario: reefer unit stumbles between waypoints 8–12
              (temp peaks ~13°C), door opens at waypoint 15 for an
              intermediate scan. Product spec: insulin, 2–8°C, 10-min
              excursion tolerance.
            </p>
          </div>
          {streaming ? (
            <button onClick={stop} className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-red-500/10 border border-red-500/30 text-red-300 rounded-lg hover:bg-red-500/20">
              <Square className="w-3.5 h-3.5" /> Stop
            </button>
          ) : (
            <div className="flex flex-col items-end gap-1">
              <button
                disabled={!pipelineId || !asset}
                onClick={startShipment}
                title={
                  !asset ? 'Deploy the Go corrector in Step 1 first.' :
                  !pipelineId ? 'Pipeline iot-coldchain-pipeline not yet seeded.' :
                  'Run a scripted SFO→LAX shipment'
                }
                className="whitespace-nowrap flex items-center gap-1.5 px-3 py-1.5 text-sm bg-cyan-500 text-slate-950 rounded-lg hover:bg-cyan-400 disabled:bg-slate-700 disabled:text-slate-500 font-medium">
                <Play className="w-3.5 h-3.5" /> Start Shipment
              </button>
              {(!pipelineId || !asset) && (
                <p className="text-[10px] text-slate-500">
                  {!asset ? 'Deploy the Go corrector first.' :
                   !pipelineId ? 'Pipeline not seeded on this cluster.' : ''}
                </p>
              )}
            </div>
          )}
        </div>
        {log.length > 0 && (
          <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/70 p-3 font-mono text-[11px] text-slate-400 space-y-0.5 max-h-32 overflow-auto">
            {log.slice(-10).map((l, i) => <div key={i}>{l}</div>)}
          </div>
        )}
      </div>

      {rawReadings.length > 0 && (
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
          <h4 className="text-white font-semibold text-sm mb-2">Temperature — raw vs Kalman-smoothed</h4>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="i" stroke="#64748b" label={{ value: 'waypoint', fill: '#64748b', fontSize: 10, position: 'insideBottom', offset: -2 }} />
                <YAxis stroke="#64748b" domain={['dataMin - 1', 'dataMax + 1']} unit="°C" />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }} labelStyle={{ color: '#94a3b8' }} />
                {/* Spec band */}
                <ReferenceArea y1={2} y2={8} fill="#059669" fillOpacity={0.08} />
                <ReferenceLine y={8} stroke="#f59e0b" strokeDasharray="4 4" />
                <ReferenceLine y={2} stroke="#f59e0b" strokeDasharray="4 4" />
                <Line type="monotone" dataKey="raw"      stroke="#64748b" strokeWidth={1}   dot={false} name="Raw" />
                <Line type="monotone" dataKey="smoothed" stroke="#06b6d4" strokeWidth={2.5} dot={false} name="Smoothed" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {monitor?.excursions && monitor.excursions.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2 text-xs">
              {monitor.excursions.map((e, idx) => (
                <span key={idx} className="px-2 py-1 rounded-md bg-amber-500/10 border border-amber-500/30 text-amber-300">
                  Excursion #{idx + 1}: {e.duration_min}min peak {e.peak_temp_c}°C ({e.direction})
                </span>
              ))}
            </div>
          )}
          {monitor?.door_events && monitor.door_events.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              {monitor.door_events.map((d, idx) => (
                <span key={idx} className="px-2 py-1 rounded-md bg-slate-700/40 border border-slate-600/40 text-slate-300">
                  Door event: {d.duration_min}min
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {adjudication && (
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <ShieldAlert className="w-4 h-4 text-cyan-400" />
            <h4 className="text-white font-semibold text-sm">LLM Adjudication</h4>
            <span className={`text-[11px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-md border ${sevTone(adjudication.severity)}`}>
              {adjudication.severity ?? '—'}
            </span>
            {typeof adjudication.spoilage_risk_pct === 'number' && (
              <span className="text-[11px] text-slate-400">
                spoilage risk <b className="text-slate-200">{adjudication.spoilage_risk_pct}%</b>
              </span>
            )}
            {adjudication.liability && (
              <span className="text-[11px] text-slate-400">
                liability <b className="text-slate-200">{adjudication.liability}</b>
              </span>
            )}
          </div>
          {adjudication.rationale && (
            <p className="text-sm text-slate-300 mb-3 italic">{adjudication.rationale}</p>
          )}
          {adjudication.evidence && adjudication.evidence.length > 0 && (
            <ul className="text-xs text-slate-400 space-y-1 list-disc list-inside">
              {adjudication.evidence.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
          {adjudication.recommended_action && (
            <p className="mt-3 text-xs text-cyan-300">
              Recommended action: <b>{adjudication.recommended_action}</b>
            </p>
          )}
        </div>
      )}

      {claim && (
        <div className="bg-gradient-to-br from-amber-500/5 to-red-500/5 border border-amber-500/30 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <FileText className="w-4 h-4 text-amber-300" />
            <h4 className="text-white font-semibold text-sm">Draft Insurance Claim</h4>
            {claim.claim_id && <span className="text-[11px] font-mono text-amber-200">#{claim.claim_id}</span>}
            {typeof claim.amount_usd === 'number' && (
              <span className="ml-auto text-sm font-mono text-amber-200">
                ${claim.amount_usd.toLocaleString()}
              </span>
            )}
          </div>
          {claim.policy_clause_cited && (
            <p className="text-xs text-slate-400 mb-2">
              Policy clause: <span className="text-slate-200">{claim.policy_clause_cited}</span>
            </p>
          )}
          {claim.evidence && (
            <ul className="text-xs text-slate-400 space-y-1 list-disc list-inside mb-3">
              {claim.evidence.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
          {claim.customer_letter_markdown && (
            <div className="mt-3 p-3 rounded-lg bg-slate-950/60 border border-slate-800">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Customer letter (drafted)</p>
              <pre className="text-xs text-slate-200 whitespace-pre-wrap font-sans">{claim.customer_letter_markdown}</pre>
            </div>
          )}
        </div>
      )}
      </div>

      {/* ── Right: rich explainer ──────────────────────────────── */}
      <ScenarioExplainer
        eyebrow="Industrial IoT · Scenario B"
        title="FSMA-Compliant Cold-Chain Monitoring"
        lede={
          <>
            Pharma, vaccines, fresh food — once the chain breaks,
            the product's shelf life has to be re-evaluated or
            it's waste. Pharma alone loses{' '}
            <b className="text-white">~$35B/year</b> to
            temperature excursions. This scenario plays back one
            reefer container from pickup to delivery and lets
            the platform decide whether the load still meets spec.
          </>
        }
        callouts={[
          { label: 'Route',         value: 'SFO → LAX' },
          { label: 'Waypoints',     value: '20 over 100 min' },
          { label: 'Product',       value: 'Insulin 2–8°C' },
          { label: 'Tolerance',     value: '10 min out of spec' },
        ]}
        sections={[
          {
            icon: Truck,
            tone: 'cyan',
            title: 'The shipment',
            body: (
              <>
                <p>
                  A simulated reefer truck carries 500 vials of
                  insulin ($120 each) from San Francisco to Los
                  Angeles. The scripted trajectory includes
                  <b className="text-white"> one reefer-unit
                  stumble</b> (waypoints 8–12, temperature
                  peaks ~13 °C) and a
                  <b className="text-white"> mid-route door scan</b>
                  (waypoint 15).
                </p>
                <p>
                  Each waypoint is one ISO-8601 reading with
                  temperature, door state, and GPS.
                </p>
              </>
            ),
          },
          {
            icon: Binary,
            tone: 'purple',
            title: 'The Go corrector',
            body: (
              <>
                <p>
                  Deployed from the browser as a{' '}
                  <code className="text-cyan-300">code_asset</code>.
                  Runs as a single-use
                  <b className="text-white"> k8s Job</b>, image{' '}
                  <code className="text-cyan-300">golang:1.22-alpine</code>.
                </p>
                <p>
                  Pipeline: <b>1-D Kalman filter</b> on the noisy
                  temperature series (no lag), FSMA-style
                  excursion detection (peaks outside spec for
                  longer than tolerance), door-open edge
                  detection, GPS-based dwell-stop inference
                  using haversine distance.
                </p>
              </>
            ),
          },
          {
            icon: Gavel,
            tone: 'amber',
            title: 'LLM adjudication',
            body: (
              <>
                <p>
                  One agent decides{' '}
                  <b className="text-white">spoilage risk %</b>,{' '}
                  <b className="text-white">liability</b>{' '}
                  (carrier / shipper / consignee), and the
                  notification tier against FSMA / GDP rules.
                </p>
                <p>
                  Rule tables alone can't pick out the nuance
                  (door-dwell vs. reefer failure vs. dock heat) —
                  the LLM reasons over the excursion shape and
                  the GPS context together.
                </p>
              </>
            ),
          },
          {
            icon: ScrollText,
            tone: 'emerald',
            title: 'Claim + customer letter',
            body: (
              <>
                <p>
                  On MEDIUM / HIGH severity a second agent drafts
                  a structured insurance claim:{' '}
                  <code className="text-cyan-300">amount = units × unit_value × risk%</code>,
                  plus an evidence bullet list and a customer-facing
                  letter short enough to actually be sent.
                </p>
                <p>
                  Policy clauses come from the tenant KB via{' '}
                  <code className="text-cyan-300">knowledge_search</code>;
                  with no KB, the draft falls back to "standard terms"
                  instead of fabricating a citation.
                </p>
              </>
            ),
          },
          {
            icon: Snowflake,
            tone: 'cyan',
            title: 'Pipeline shape',
            body: (
              <>
                <p className="font-mono text-[10.5px] text-slate-300">
                  validate →{' '}
                  <span className="text-cyan-300">monitor (k8s)</span>{' '}
                  → <span className="text-amber-300">adjudicate (LLM)</span>{' '}
                  → route →{' '}
                  <span className="text-amber-300">draft_claim</span>{' '}
                  → final_report
                </p>
                <p>
                  Same chassis as the pump scenario — the only
                  thing scenario-specific is the Go program and
                  the agent's prompt. One platform, two very
                  different industrial problems, zero orchestration
                  duplication.
                </p>
              </>
            ),
          },
          {
            icon: Globe2,
            tone: 'purple',
            title: 'Real-world parallels',
            body: (
              <ul className="list-disc list-outside pl-4 space-y-1">
                <li>
                  Sensitech, Tive, Controlant sell
                  purpose-built reefer loggers — this shows how
                  a generic platform substitutes for one vendor.
                </li>
                <li>
                  The liability-attribution step is normally done
                  by a human QA specialist hours after delivery.
                  Here it's bounded and drafted within seconds.
                </li>
                <li>
                  Works unchanged for vaccine, plasma, fresh
                  produce, seafood — just change the
                  <code className="text-cyan-300">product_spec</code>.
                </li>
              </ul>
            ),
          },
        ]}
        footer={
          <p className="text-xs text-slate-400 leading-relaxed">
            <FlaskConical className="w-3.5 h-3.5 inline mr-1.5 text-cyan-400" />
            Click <b className="text-white">Start Shipment</b>. Waypoints
            animate for ~4s while the temperature spike unfolds, then
            the full window is handed to the pipeline for Kalman
            smoothing + LLM adjudication.
          </p>
        }
      />
    </div>
  );
}

function DeployRow({
  asset, busy, onDeploy,
}: {
  asset: CodeAssetRow | null;
  busy: boolean;
  onDeploy: () => void;
}) {
  const deployed = asset?.status === 'ready';
  return (
    <div className="rounded-xl p-5 border bg-gradient-to-br from-cyan-500/5 to-purple-500/5 border-cyan-500/30">
      <div className="flex items-start gap-3">
        <CloudUpload className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2">
            <p className="text-white font-semibold text-sm leading-tight flex-1 min-w-0 break-words">
              Step 1 · Deploy Go Cold-Chain Corrector
            </p>
            <button
              disabled={busy || deployed}
              onClick={onDeploy}
              className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/30 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap">
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> :
               deployed ? <Rocket className="w-3.5 h-3.5" /> :
               <CloudUpload className="w-3.5 h-3.5" />}
              {busy ? 'Deploying…' : deployed ? 'Deployed' : 'Deploy'}
            </button>
          </div>
          <p className="text-xs text-slate-400 mt-1.5">
            cold-chain-corrector · Kalman smoothing + FSMA excursion
            detection, runs as a k8s Job
          </p>
          {deployed && (
            <div className="mt-2.5 space-y-0.5 font-mono text-[10.5px] text-emerald-300/90">
              <p className="truncate">
                <span className="text-slate-500">id:&nbsp;&nbsp;&nbsp;&nbsp;</span>
                {asset!.id}
              </p>
              <p className="truncate">
                <span className="text-slate-500">image:&nbsp;</span>
                {asset!.suggested_image}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
