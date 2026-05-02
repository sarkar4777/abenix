'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, Binary, Boxes, Brain, ChevronDown, ChevronRight,
  ClipboardList, CloudUpload, Cpu, Database, FlaskConical, Loader2, Play,
  Rocket, Square, Stethoscope, Timer, Waves,
} from 'lucide-react';
import ScenarioExplainer from '../components/ScenarioExplainer';
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis, Bar, BarChart,
} from 'recharts';
import {
  CodeAssetRow, PUMP_DSP, RUL_ESTIMATOR,
  findAssetByName, uploadAndDeploy, waitForSchemaProbe,
} from '../lib/deploy';
import { findPipelineBySlug, runPipeline, type PipelineKey } from '../lib/pipelineRunner';
import { vibrationWindow, VibrationWindow, parsePumpQueryParams } from '../lib/synthetic';
import KbBadge from '../components/KbBadge';

interface WindowResult {
  index: number;
  scenario: VibrationWindow['scenario'];
  rms?: number;
  peak?: number;
  crest?: number;
  kurtosis?: number;
  dominantFreqs?: { hz: number; amplitude: number }[];
  faultScores?: {
    bearing: number;
    imbalance: number;
    misalignment: number;
    cavitation: number;
  };
  severity?: string;
  rootCause?: string;
  rationale?: string;
  rulHours?: number | null;
  workOrder?: Record<string, unknown> | null;
  raw?: string;
  error?: string;
}

function severityTone(sev?: string): string {
  switch (sev) {
    case 'CRITICAL': return 'bg-red-500/20 text-red-300 border-red-500/40';
    case 'WARN':     return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
    case 'WATCH':    return 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
    case 'OK':       return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
    default:         return 'bg-slate-700/60 text-slate-300 border-slate-600/40';
  }
}

export default function PumpTab() {
  const [dspAsset, setDspAsset] = useState<CodeAssetRow | null>(null);
  const [rulAsset, setRulAsset] = useState<CodeAssetRow | null>(null);
  const [deployingDsp, setDeployingDsp] = useState(false);
  const [deployingRul, setDeployingRul] = useState(false);
  const [deployError, setDeployError] = useState<string>('');
  const [probeStatus, setProbeStatus] = useState<string>('');

  const [pipelineId, setPipelineId] = useState<PipelineKey | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [results, setResults] = useState<WindowResult[]>([]);
  const [currentLog, setCurrentLog] = useState<string[]>([]);
  const [expandedWindow, setExpandedWindow] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    (async () => {
      // Run in parallel — none of these depend on each other. Letting
      // the page render while they resolve keeps the UX snappy.
      const [id, existingDsp, existingRul] = await Promise.all([
        findPipelineBySlug('iot-pump-pipeline'),
        findAssetByName(PUMP_DSP.slug,      { spec: PUMP_DSP,      skipStale: true }),
        findAssetByName(RUL_ESTIMATOR.slug, { spec: RUL_ESTIMATOR, skipStale: true }),
      ]);
      setPipelineId(id);
      if (existingDsp && existingDsp.status === 'ready') setDspAsset(existingDsp);
      if (existingRul && existingRul.status === 'ready') setRulAsset(existingRul);
    })();
  }, []);

  const deployDsp = async () => {
    setDeployError(''); setDeployingDsp(true);
    try {
      const asset = await uploadAndDeploy(PUMP_DSP);
      setDspAsset(asset);
      if (!asset.output_schema) {
        setProbeStatus('Running smoke-test probe in k8s Job…');
        const ok = await waitForSchemaProbe(asset.id);
        setProbeStatus(ok ? 'Schema probe complete.' : 'Schema probe timed out (asset still usable).');
      }
    } catch (e) {
      setDeployError((e as Error).message);
    } finally {
      setDeployingDsp(false);
    }
  };

  const deployRul = async () => {
    setDeployError(''); setDeployingRul(true);
    try {
      const asset = await uploadAndDeploy(RUL_ESTIMATOR);
      setRulAsset(asset);
    } catch (e) {
      setDeployError((e as Error).message);
    } finally {
      setDeployingRul(false);
    }
  };

  const startStream = async () => {
    if (!pipelineId) {
      setDeployError('Pump pipeline not yet seeded on this cluster.');
      return;
    }
    if (!dspAsset) {
      setDeployError('Deploy the pump-dsp asset first.');
      return;
    }
    setStreaming(true); setResults([]); setCurrentLog([]); setExpandedWindow(null);
    abortRef.current = new AbortController();

    const overrides = parsePumpQueryParams();
    const total = 10; // 10 windows across ~5-10 min (LLM round-trip per window)
    for (let i = 1; i <= total; i++) {
      if (abortRef.current.signal.aborted) break;
      const win = vibrationWindow(i, total, overrides);
      setCurrentLog((p) => [...p.slice(-12), `Window ${i}/${total} (${win.scenario})  running…`]);

      const message = {
        samples: win.samples,
        sample_rate_hz: win.sample_rate_hz,
        sensor_id: win.sensor_id,
        shaft_rpm: win.shaft_rpm,
      };
      const ctx: Record<string, unknown> = {
        pump_dsp_asset_id: dspAsset.id,
        asset_context: { sensor_id: win.sensor_id, site: 'Plant 3', line: 'Cooling A' },
      };
      if (rulAsset) ctx.rul_asset_id = rulAsset.id;

      const wr: WindowResult = { index: i, scenario: win.scenario };
      const result = await runPipeline(pipelineId, message, ctx, {
        waitSeconds: 180,
        signal: abortRef.current.signal,
      });

      if (!result.ok) {
        wr.error = result.error ?? 'execution failed';
        setCurrentLog((p) => [...p.slice(-12), `  #${i} ERR: ${wr.error}`]);
      } else {
        const payload = result.final_output ?? {};
        const dsp = (payload.dsp as Record<string, unknown>) ?? {};
        const diag = (payload.diagnosis as Record<string, unknown>) ?? {};
        wr.rms = dsp.rms as number | undefined;
        wr.peak = dsp.peak as number | undefined;
        wr.crest = dsp.crest_factor as number | undefined;
        wr.kurtosis = dsp.kurtosis as number | undefined;
        wr.dominantFreqs = (dsp.dominant_freqs as { hz: number; amplitude: number }[]) ?? undefined;
        wr.faultScores = (dsp.fault_scores as WindowResult['faultScores']) ?? undefined;
        wr.severity = (diag.severity as string) ?? (payload.severity as string) ?? 'OK';
        wr.rootCause = diag.root_cause as string | undefined;
        wr.rationale = diag.rationale as string | undefined;
        wr.rulHours = (payload.rul_hours as number | null) ?? null;
        wr.workOrder = (payload.work_order as Record<string, unknown> | null) ?? null;
        setCurrentLog((p) => [
          ...p.slice(-12),
          `  #${i} ${wr.severity}${wr.rootCause ? ` / ${wr.rootCause}` : ''}  rms=${wr.rms?.toFixed(3) ?? '—'}`,
        ]);
      }

      setResults((prev) => [...prev, wr]);
      // Short pause so the dashboard animates between windows.
      await new Promise((r) => setTimeout(r, 400));
    }
    setStreaming(false);
  };

  const stopStream = () => { abortRef.current?.abort(); };

  const latest = results[results.length - 1];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-6">
      <div className="space-y-6 min-w-0">
      {/* ── Row 1: Deploy assets ─────────────────────────────────── */}
      {/* Stack vertically — the right rail leaves the main column too
          narrow for two side-by-side deploy cards once the UUID + image
          metadata lands. xl: restores the 2-column layout on wide screens. */}
      <div className="grid xl:grid-cols-2 gap-4">
        <DeployCard
          icon={CloudUpload}
          title="Step 1 · Deploy Go DSP Asset"
          subtitle="pump-dsp-correction · runs as a k8s Job on every window"
          asset={dspAsset}
          busy={deployingDsp}
          onDeploy={deployDsp}
          highlight
        />
        <DeployCard
          icon={CloudUpload}
          title="Step 2 · Deploy RUL Estimator"
          subtitle="rul-estimator · optional — smoothens cold-start estimates"
          asset={rulAsset}
          busy={deployingRul}
          onDeploy={deployRul}
        />
      </div>
      {probeStatus && (
        <div className="text-xs text-slate-400">{probeStatus}</div>
      )}
      <KbBadge />
      {deployError && (
        <div className="flex items-start gap-2 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg p-3">
          <AlertTriangle className="w-4 h-4 mt-0.5" />
          <span>{deployError}</span>
        </div>
      )}

      {/* ── Row 2: Run the pipeline ─────────────────────────────── */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-white font-semibold flex items-center gap-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              Step 3 · Stream vibration windows through the pipeline
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              10 windows over ~30s. Scripted fault trajectory:
              healthy → early bearing wear → acute imbalance.
              Each window runs validate → <span className="text-cyan-300">Go DSP (k8s Job)</span>
              → LLM diagnosis → RUL estimator → severity router → (CRITICAL/WARN: maintenance planner) → persist.
            </p>
          </div>
          {streaming ? (
            <button
              onClick={stopStream}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-red-500/10 border border-red-500/30 text-red-300 rounded-lg hover:bg-red-500/20">
              <Square className="w-3.5 h-3.5" /> Stop
            </button>
          ) : (
            <div className="flex flex-col items-end gap-1">
              <button
                disabled={!pipelineId || !dspAsset}
                onClick={startStream}
                title={
                  !dspAsset ? 'Deploy the Go DSP asset in Step 1 first.' :
                  !pipelineId ? 'Pipeline iot-pump-pipeline not yet seeded.' :
                  'Fire 10 scripted vibration windows'
                }
                className="whitespace-nowrap flex items-center gap-1.5 px-3 py-1.5 text-sm bg-cyan-500 text-slate-950 rounded-lg hover:bg-cyan-400 disabled:bg-slate-700 disabled:text-slate-500 font-medium">
                <Play className="w-3.5 h-3.5" /> Start Stream
              </button>
              {(!pipelineId || !dspAsset) && (
                <p className="text-[10px] text-slate-500">
                  {!dspAsset ? 'Deploy the Go DSP asset first.' :
                   !pipelineId ? 'Pipeline not seeded on this cluster.' : ''}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Live log */}
        {currentLog.length > 0 && (
          <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/70 p-3 font-mono text-[11px] text-slate-400 space-y-0.5 max-h-28 overflow-auto">
            {currentLog.slice(-8).map((l, i) => <div key={i}>{l}</div>)}
          </div>
        )}
      </div>

      {/* ── Row 3: Live charts ─────────────────────────────────── */}
      {results.length > 0 && (
        <div className="grid md:grid-cols-3 gap-4">
          <div className="md:col-span-2 bg-slate-900/50 border border-slate-800 rounded-xl p-5">
            <h4 className="text-white font-semibold text-sm mb-2">RMS + Peak over windows</h4>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={results}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="index" stroke="#64748b" />
                  <YAxis stroke="#64748b" />
                  <Tooltip
                    contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
                    labelStyle={{ color: '#94a3b8' }} />
                  <Line type="monotone" dataKey="rms" stroke="#06b6d4" strokeWidth={2} dot={false} name="RMS" />
                  <Line type="monotone" dataKey="peak" stroke="#a855f7" strokeWidth={2} dot={false} name="Peak" />
                  <ReferenceLine y={0.15} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: 'WARN', fill: '#f59e0b', fontSize: 10 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
            <h4 className="text-white font-semibold text-sm mb-2">Latest FFT peaks</h4>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={(latest?.dominantFreqs ?? []).map((d) => ({ hz: Math.round(d.hz), amp: d.amplitude }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="hz" stroke="#64748b" label={{ value: 'Hz', fill: '#64748b', fontSize: 10, position: 'insideBottomRight', offset: -2 }} />
                  <YAxis stroke="#64748b" />
                  <Tooltip
                    contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
                    labelStyle={{ color: '#94a3b8' }} />
                  <Bar dataKey="amp" fill="#06b6d4" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* ── Row 4: Per-window verdicts ─────────────────────────── */}
      {results.length > 0 && (
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
          <h4 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
            <Stethoscope className="w-4 h-4 text-cyan-400" />
            Per-window diagnosis
          </h4>
          <div className="space-y-2">
            {results.map((r) => (
              <div key={r.index} className="border border-slate-800 rounded-lg">
                <button
                  onClick={() => setExpandedWindow(expandedWindow === r.index ? null : r.index)}
                  className="w-full flex items-center gap-3 p-3 hover:bg-slate-800/40 transition-colors">
                  <span className="text-xs font-mono text-slate-500 w-14">#{String(r.index).padStart(2,'0')}</span>
                  <span className="text-xs text-slate-400 w-36">{r.scenario}</span>
                  <span className={`text-[11px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-md border ${severityTone(r.severity)}`}>
                    {r.severity ?? (r.error ? 'ERR' : '—')}
                  </span>
                  <span className="text-xs text-slate-400 w-32 truncate">{r.rootCause ?? ''}</span>
                  <span className="text-xs text-slate-500 flex-1 truncate italic">{r.rationale ?? r.error ?? ''}</span>
                  {r.rulHours != null && (
                    <span className="text-[11px] text-cyan-300 flex items-center gap-1">
                      <Timer className="w-3 h-3" /> RUL ~{Math.round(r.rulHours)}h
                    </span>
                  )}
                  {expandedWindow === r.index ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
                </button>
                {expandedWindow === r.index && (
                  <div className="px-4 pb-4 text-xs">
                    <div className="grid grid-cols-4 gap-3 text-slate-400 mb-3">
                      <Metric label="RMS" value={r.rms?.toFixed(3)} />
                      <Metric label="Peak" value={r.peak?.toFixed(3)} />
                      <Metric label="Crest" value={r.crest?.toFixed(2)} />
                      <Metric label="Kurtosis" value={r.kurtosis?.toFixed(2)} />
                    </div>
                    {r.faultScores && (
                      <div className="grid grid-cols-4 gap-3 mb-3">
                        <Metric label="Bearing"      value={r.faultScores.bearing.toFixed(2)} />
                        <Metric label="Imbalance"    value={r.faultScores.imbalance.toFixed(2)} />
                        <Metric label="Misalignment" value={r.faultScores.misalignment.toFixed(2)} />
                        <Metric label="Cavitation"   value={r.faultScores.cavitation.toFixed(2)} />
                      </div>
                    )}
                    {r.workOrder && (
                      <div className="mt-2 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
                        <p className="text-amber-300 text-xs flex items-center gap-1.5 font-semibold mb-1">
                          <ClipboardList className="w-3.5 h-3.5" /> Work Order Drafted
                        </p>
                        <pre className="text-[10.5px] text-slate-400 whitespace-pre-wrap">{JSON.stringify(r.workOrder, null, 2)}</pre>
                      </div>
                    )}
                    {r.raw && !r.workOrder && !r.rationale && (
                      <pre className="text-[10.5px] text-slate-500 whitespace-pre-wrap">{r.raw}</pre>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      </div>

      {/* ── Right: rich explainer ──────────────────────────────── */}
      <ScenarioExplainer
        eyebrow="Industrial IoT · Scenario A"
        title="Predictive Maintenance for Rotating Machinery"
        lede={
          <>
            Rotating equipment — centrifugal pumps, compressors,
            fans, motors — is the <b className="text-white">single
            biggest source of unplanned downtime</b> in process
            industries. Every 24 hours a fault progresses, a plant
            loses 1–3% of its output capacity. This scenario shows
            the platform catching a developing fault <i>before</i>
            the outage.
          </>
        }
        callouts={[
          { label: 'Sampling rate', value: '2 kHz' },
          { label: 'Shaft RPM',     value: '1800' },
          { label: 'Windows',       value: '10 over ~5 min' },
          { label: 'Latency target', value: '<300 ms/window' },
        ]}
        sections={[
          {
            icon: Waves,
            tone: 'cyan',
            title: 'The signal',
            body: (
              <>
                <p>
                  A tri-axial accelerometer mounted on the pump
                  housing streams raw vibration at 2 kHz.
                  Every 250 ms we send one <i>window</i> (500
                  samples) into the pipeline.
                </p>
                <p>
                  The scripted trajectory goes
                  <b className="text-white"> healthy → early
                  bearing wear → acute imbalance</b> so you can
                  watch the platform escalate its diagnosis
                  window-over-window.
                </p>
              </>
            ),
          },
          {
            icon: Binary,
            tone: 'purple',
            title: 'The Go DSP asset',
            body: (
              <>
                <p>
                  Deployed from the browser as a
                  <code className="px-1 text-cyan-300">code_asset</code> — runs
                  as a single-use
                  <b className="text-white"> k8s Job</b> per
                  invocation in the <code>abenix</code>
                  namespace, image{' '}
                  <code className="text-cyan-300">golang:1.22-alpine</code>.
                </p>
                <p>
                  Pipeline: detrend → median de-noise →
                  FFT (Cooley–Tukey radix-2) → RMS / peak /
                  crest / kurtosis → per-fault scoring →
                  ISO 10816-3 zone.
                </p>
              </>
            ),
          },
          {
            icon: Brain,
            tone: 'amber',
            title: 'LLM diagnosis',
            body: (
              <>
                <p>
                  An agent reads the DSP output and decides
                  severity + probable root cause. Rule-based
                  thresholds get fooled when multiple faults
                  overlap (bearing harmonics often sit right on
                  2× shaft), so the LLM reasons over the
                  <i> pattern</i>, not just the numbers.
                </p>
                <p>
                  It cross-references against the tenant's
                  knowledge base (ISO 10816 excerpts, failure
                  mode catalogues) via{' '}
                  <code className="text-cyan-300">knowledge_search</code>.
                </p>
              </>
            ),
          },
          {
            icon: Timer,
            tone: 'emerald',
            title: 'RUL + work-order planning',
            body: (
              <>
                <p>
                  A tiny exponential fit on recent health
                  indices gives remaining useful life in hours.
                  Optionally this can route to the uploaded
                  Python RUL estimator for richer fits on long
                  histories.
                </p>
                <p>
                  On <b className="text-white">CRITICAL</b> a
                  second agent drafts a structured work order
                  (parts, crew, window) that could be handed
                  directly to a CMMS.
                </p>
              </>
            ),
          },
          {
            icon: Boxes,
            tone: 'cyan',
            title: 'Pipeline shape',
            body: (
              <>
                <p className="font-mono text-[10.5px] text-slate-300">
                  validate → <span className="text-cyan-300">dsp (k8s)</span>{' '}
                  → <span className="text-amber-300">diagnose (LLM)</span> → rul →
                  severity_router →{' '}
                  <span className="text-amber-300">plan_maintenance</span>{' '}
                  → final_report
                </p>
                <p>
                  Deterministic number-crunching stays in Go;
                  pattern interpretation stays in the LLM.
                  Nothing that can be cheaply reduced to a
                  formula goes through tokens.
                </p>
              </>
            ),
          },
          {
            icon: Cpu,
            tone: 'purple',
            title: 'Why it matters',
            body: (
              <ul className="list-disc list-outside pl-4 space-y-1">
                <li>Bring-your-own code — no container push, no registry hassle.</li>
                <li>Same request path runs on minikube locally and AKS in prod.</li>
                <li>Every agent + tool call is recorded under <a href={`${(process.env.NEXT_PUBLIC_ABENIX_WEB_URL || 'http://localhost:3000').replace(/\/$/, '')}/executions`} target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline">/executions</a> for audit.</li>
                <li>Budgets, rate-limits, moderation gates apply to this flow like every other.</li>
              </ul>
            ),
          },
        ]}
        footer={
          <p className="text-xs text-slate-400 leading-relaxed">
            <FlaskConical className="w-3.5 h-3.5 inline mr-1.5 text-cyan-400" />
            Click <b className="text-white">Start Stream</b> to drive
            the pipeline through the scripted trajectory. Each window
            runs the full DAG — expect ~5 minutes end-to-end because
            real LLM round-trips are the long pole.
          </p>
        }
      />
    </div>
  );
}

function DeployCard({
  icon: Icon, title, subtitle, asset, busy, onDeploy, highlight,
}: {
  icon: typeof CloudUpload;
  title: string;
  subtitle: string;
  asset: CodeAssetRow | null;
  busy: boolean;
  onDeploy: () => void;
  highlight?: boolean;
}) {
  const deployed = asset?.status === 'ready';
  return (
    <div className={`rounded-xl p-5 border ${highlight ? 'bg-gradient-to-br from-cyan-500/5 to-purple-500/5 border-cyan-500/30' : 'bg-slate-900/50 border-slate-800'}`}>
      <div className="flex items-start gap-3">
        <Icon className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
        {/* min-w-0 lets this column shrink so long titles / UUIDs wrap
            instead of pushing the Deploy button on top of the text. */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2">
            <p className="text-white font-semibold text-sm leading-tight flex-1 min-w-0 break-words">
              {title}
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
          <p className="text-xs text-slate-400 mt-1.5">{subtitle}</p>
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

function Metric({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-600">{label}</p>
      <p className="text-sm font-mono text-slate-200 mt-0.5">{value ?? '—'}</p>
    </div>
  );
}
