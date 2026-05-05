'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle, Calendar, ClipboardCheck, Loader2, Mic, QrCode,
  Send, ShieldAlert, Sparkles, Wind, Wrench, Zap,
} from 'lucide-react';
import ScenarioExplainer from '../components/ScenarioExplainer';
import PipelineDagViz from '../components/PipelineDagViz';
import { FIELDEDGE_DAG } from '../components/dags';
import KbBadge from '../components/KbBadge';
import { findPipelineBySlug, runPipeline, type PipelineKey } from '../lib/pipelineRunner';

// ── Types matching the backend agent JSON shapes ─────────────────────
interface Turbine {
  id: string;
  model: string;
  install_date: string;
  last_service_date: string;
  status: 'running' | 'warning' | 'offline';
  active_alarms?: string[];
  hub_height_m: number;
  rotor_diameter_m: number;
  rated_kw: number;
  lat: number;
  lon: number;
}
interface Fleet { site: string; operator: string; turbines: Turbine[]; }

interface WO {
  wo_id: string;
  turbine_id: string;
  model: string;
  opened: string;
  closed: string | null;
  issue: string;
  parts: string[];
  hours: number | null;
  technician: string | null;
  outcome: string;
  service_summary?: string;
}
interface WorkOrders { work_orders: WO[]; }

interface Technician {
  id: string;
  name: string;
  skills: string[];
  shift: string;
  hours_per_day: number;
}
interface Technicians { technicians: Technician[]; }

interface ManualCitation { section: string; excerpt: string; }
interface SimilarWO {
  wo_id: string; turbine_id: string; issue: string;
  parts?: string[]; hours?: number; outcome?: string;
  match_quality?: string;
}
interface ProcedureStep {
  step: number; action: string;
  tool_required?: string | null; warning?: string | null;
}
interface PartRequired { part_number: string; description: string; qty: number; }

interface TroubleshootResult {
  safety_gate?: string;
  confidence?: number;
  diagnosis_summary?: string;
  manual_citations?: ManualCitation[];
  similar_past_wos?: SimilarWO[];
  procedure?: ProcedureStep[];
  parts_required?: PartRequired[];
  estimated_hours?: number;
  rationale?: string;
  escalate_to_engineering?: boolean;
  part_lookup_required?: boolean;
}

interface CloseoutResult {
  status?: string;
  labour_hours?: number;
  parts_consumed?: { part_number: string; description: string; qty: number }[];
  root_cause?: string | null;
  actions_taken?: string[];
  follow_up_actions?: { action: string; due_date?: string; priority?: string }[];
  service_summary_for_customer?: string;
  confidence?: number;
  raw_transcript?: string;
}

interface ScheduleAssignment {
  wo_id: string;
  turbine_id: string;
  technician_id: string;
  technician_name?: string;
  day: string;
  duration_hours: number;
  priority?: string;
}
interface ScheduleResult {
  solver_used?: string;
  infeasible?: boolean;
  assignments?: ScheduleAssignment[];
  unassigned?: { wo_id: string; reason: string }[];
  weekly_grid?: Record<string, Record<string, ScheduleAssignment | null>>;
  delta?: { wo_id: string; from?: unknown; to?: unknown }[];
  summary?: string;
  risks?: string[];
}

function tone(quality?: string): string {
  switch (quality) {
    case 'exact': return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40';
    case 'close': return 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40';
    case 'loose': return 'bg-slate-700/40 text-slate-300 border-slate-600/40';
    default:      return 'bg-slate-700/40 text-slate-300 border-slate-600/40';
  }
}

function gateTone(gate?: string): string {
  switch (gate) {
    case 'PROCEED_WITH_LOTO':  return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
    case 'STAND_DOWN_WEATHER': return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
    case 'EVACUATE_AND_LOTO':  return 'bg-red-500/20 text-red-300 border-red-500/40';
    default:                   return 'bg-slate-700/40 text-slate-300 border-slate-600/40';
  }
}

// Default seed weather — used if the user doesn't override.
const DEFAULT_WEATHER = {
  wind_mps: 7, gusts_mps: 10, temp_c: 14, precip: 'none',
};

// 7-day forecast scaffold — first day clear, mid-week wind picks up.
// Lets the schedule optimizer demonstrate weather gating.
const DEFAULT_FORECAST = (() => {
  const start = new Date();
  start.setUTCHours(0, 0, 0, 0);
  return Array.from({ length: 7 }).map((_, i) => {
    const d = new Date(start.getTime() + i * 86400000);
    const day = d.toISOString().slice(0, 10);
    const wind = i === 2 || i === 3 ? 13.5 : 7 + (i * 0.5);
    const climb_safe = wind <= 12;
    const precip = i === 3 ? 'rain' : 'none';
    return { day, wind_mps: wind, precip, climb_safe };
  });
})();

export default function FieldEdgeTab() {
  // ── Bootstrap data ────────────────────────────────────────────────
  const [fleet, setFleet] = useState<Turbine[]>([]);
  const [wos, setWos] = useState<WO[]>([]);
  const [techs, setTechs] = useState<Technician[]>([]);
  const [pipelineId, setPipelineId] = useState<PipelineKey | null>(null);

  // ── Inputs ────────────────────────────────────────────────────────
  const [selectedTurbineId, setSelectedTurbineId] = useState<string>('TURB-07');
  const [query, setQuery] = useState<string>(
    'Blade leading-edge erosion outer 6m LP side. Drone scan flagged it last week.'
  );
  const [closeoutText, setCloseoutText] = useState<string>(
    'Finished the LE erosion job, used three rolls of LE tape and one epoxy kit, took about 7 hours, found a small crack at 4.5m from tip on LP side, filled with epoxy, tape applied on top. Recommend re-inspect in 6 months. M Patel.'
  );

  // ── Async state ───────────────────────────────────────────────────
  const [streaming, setStreaming] = useState(false);
  const [troubleshoot, setTroubleshoot] = useState<TroubleshootResult | null>(null);
  const [streamLog, setStreamLog] = useState<string[]>([]);
  const [error, setError] = useState<string>('');
  const [photoDataUrl, setPhotoDataUrl] = useState<string | null>(null);
  const [photoName, setPhotoName] = useState<string>('');

  const [submittingCloseout, setSubmittingCloseout] = useState(false);
  const [closeout, setCloseout] = useState<CloseoutResult | null>(null);
  const [closeoutError, setCloseoutError] = useState<string>('');

  const [optimising, setOptimising] = useState(false);
  const [schedule, setSchedule] = useState<ScheduleResult | null>(null);
  const [scheduleError, setScheduleError] = useState<string>('');

  const [recording, setRecording] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  // ── Initial bootstrap — fetch fleet / WO / techs / pipeline id in parallel ──
  useEffect(() => {
    (async () => {
      const [pid, fleetRes, woRes, techRes] = await Promise.all([
        findPipelineBySlug('iot-fieldedge-pipeline'),
        fetch('/industrial-iot/fieldedge/fleet.json').then((r) => r.json()).catch(() => null),
        fetch('/industrial-iot/fieldedge/historical-wos.json').then((r) => r.json()).catch(() => null),
        fetch('/industrial-iot/fieldedge/technicians.json').then((r) => r.json()).catch(() => null),
      ]);
      setPipelineId(pid);
      if (fleetRes) setFleet((fleetRes as Fleet).turbines || []);
      if (woRes) setWos((woRes as WorkOrders).work_orders || []);
      if (techRes) setTechs((techRes as Technicians).technicians || []);
    })();
  }, []);

  const selectedTurbine = useMemo(
    () => fleet.find((t) => t.id === selectedTurbineId) || null,
    [fleet, selectedTurbineId],
  );

  // ── Submit the symptom ────────────────────────────────────────────
  const submitSymptom = async () => {
    setError('');
    if (!pipelineId) {
      setError('Field Guide pipeline is not seeded on this cluster yet.');
      return;
    }
    if (!selectedTurbine) {
      setError('Pick a turbine first.');
      return;
    }
    if (!query.trim()) {
      setError('Describe the issue — even one sentence helps.');
      return;
    }

    setStreaming(true);
    setTroubleshoot(null);
    setStreamLog([
      `[${new Date().toISOString().slice(11, 19)}] Submitting symptom for ${selectedTurbine.id} (${selectedTurbine.model})`,
      '  -> Searching fleet history (30 historical WOs)...',
    ]);
    abortRef.current = new AbortController();

    // Bundle the relevant fleet history so the pipeline doesn't have to
    // round-trip to a DB on the standalone — small enough to inline.
    const fleet_history = wos.map((w) => ({
      wo_id: w.wo_id,
      turbine_id: w.turbine_id,
      model: w.model,
      issue: w.issue,
      parts: w.parts,
      hours: w.hours,
      outcome: w.outcome,
    }));

    const payload: Record<string, unknown> = {
      turbine_id: selectedTurbine.id,
      model: selectedTurbine.model,
      symptom: query.trim(),
      site: 'Brevard Mesa Wind Farm',
      weather: DEFAULT_WEATHER,
      fleet_history,
    };
    // Optional photo — only attach if the technician picked one. The
    // troubleshoot agent runs on Claude Sonnet which can read base64
    // image data URLs, so we forward the data URL verbatim.
    if (photoDataUrl) {
      payload.photo_data_url = photoDataUrl;
      payload.photo_filename = photoName;
    }

    const result = await runPipeline(pipelineId, payload, {}, {
      waitSeconds: 240,
      signal: abortRef.current.signal,
    });

    if (!result.ok) {
      setError(result.error || 'pipeline failed');
      setStreamLog((p) => [...p, `  ERR: ${result.error}`]);
    } else {
      const final = (result.final_output || {}) as Record<string, unknown>;
      const tr = (final.troubleshoot || {}) as TroubleshootResult;
      setTroubleshoot(tr);
      setStreamLog((p) => [
        ...p,
        '  -> Fleet search returned matches, grounding in OEM manuals...',
        `  Done. Safety gate: ${tr.safety_gate ?? 'unknown'}, confidence: ${tr.confidence ?? '—'}`,
      ]);
    }
    setStreaming(false);
  };

  const stopStream = () => {
    abortRef.current?.abort();
    setStreaming(false);
  };

  // ── Closeout (calls the closeout_documenter agent via /api/agents proxy) ──
  const submitCloseout = async () => {
    setCloseoutError('');
    if (!closeoutText.trim()) {
      setCloseoutError('Dictate or type the close-out before submitting.');
      return;
    }
    setSubmittingCloseout(true);
    try {
      const body = {
        message: JSON.stringify({
          wo_id: `WO-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-NEW`,
          turbine_id: selectedTurbineId,
          opened_at: new Date(Date.now() - 7 * 3600 * 1000).toISOString(),
          transcript: closeoutText.trim(),
          technician_id: 'T-01',
        }),
      };
      const r = await fetch('/api/agents/iot-fieldedge-closeout-documenter/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      const out = parseAgentOutput(json);
      setCloseout(out as CloseoutResult);
    } catch (e) {
      setCloseoutError((e as Error).message);
    } finally {
      setSubmittingCloseout(false);
    }
  };

  // ── Schedule optimiser ────────────────────────────────────────────
  const reoptimiseSchedule = async () => {
    setScheduleError('');
    setOptimising(true);
    try {
      const openWos = wos
        .filter((w) => w.outcome === 'open' || w.outcome === 'ongoing')
        .map((w, i) => ({
          wo_id: w.wo_id,
          turbine_id: w.turbine_id,
          skill_required: skillFromIssue(w.issue),
          estimated_hours: 6,
          priority: i === 0 ? 'P1' : 'P2',
          weather_sensitive: skillFromIssue(w.issue) === 'blade-repair',
        }));
      // Pad with a couple of synthetic open WOs so the grid has more to chew on.
      const synthOpen = [
        { wo_id: 'WO-PLAN-001', turbine_id: 'TURB-07', skill_required: 'blade-repair',
          estimated_hours: 7, priority: 'P2', weather_sensitive: true },
        { wo_id: 'WO-PLAN-002', turbine_id: 'TURB-09', skill_required: 'gearbox',
          estimated_hours: 6, priority: 'P2', weather_sensitive: false },
        { wo_id: 'WO-PLAN-003', turbine_id: 'TURB-12', skill_required: 'generator',
          estimated_hours: 9, priority: 'P1', weather_sensitive: false },
      ];
      const body = {
        message: JSON.stringify({
          technicians: techs,
          work_orders: [...openWos, ...synthOpen],
          weather_forecast: DEFAULT_FORECAST,
          previous_schedule: schedule || null,
        }),
      };
      const r = await fetch('/api/agents/iot-fieldedge-schedule-optimizer/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      const out = parseAgentOutput(json);
      setSchedule(out as ScheduleResult);
    } catch (e) {
      setScheduleError((e as Error).message);
    } finally {
      setOptimising(false);
    }
  };

  // ── UI ────────────────────────────────────────────────────────────
  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-6">
      <div className="space-y-6 min-w-0">

        {/* Mobile-first symptom card — capped to max-w-md so it visually feels
            like a tablet pane even when the desktop layout is wide. */}
        <div className="max-w-md mx-auto w-full">
          <motion.div
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            className="bg-gradient-to-br from-slate-900/80 to-slate-950/80 border border-slate-800 rounded-2xl p-5 shadow-xl shadow-slate-950/50"
          >
            <div className="flex items-center gap-2 mb-4">
              <Wind className="w-5 h-5 text-cyan-400" />
              <h3 className="text-white font-semibold">Field Guide — Tower Tablet</h3>
            </div>

            {/* Turbine picker + Scan QR */}
            <div className="space-y-2.5">
              <label className="text-[10px] uppercase tracking-wider text-slate-500">Turbine</label>
              <div className="flex gap-2">
                <select
                  value={selectedTurbineId}
                  onChange={(e) => setSelectedTurbineId(e.target.value)}
                  className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-3 text-sm text-white focus:outline-none focus:border-cyan-500"
                >
                  {fleet.length === 0 && <option>Loading fleet…</option>}
                  {fleet.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.id} · {t.model.split(' ')[0]} · {t.status}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => {
                    // Mock QR scan: cycle through warning turbines
                    const flagged = fleet.filter((t) => t.status !== 'running');
                    if (flagged.length === 0) return;
                    const next = flagged[Math.floor(Math.random() * flagged.length)];
                    setSelectedTurbineId(next.id);
                  }}
                  title="Mock QR scan — cycles to a turbine with active alarms"
                  className="px-3 py-3 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg"
                >
                  <QrCode className="w-4 h-4 text-cyan-400" />
                </button>
              </div>

              {selectedTurbine && (
                <div className="text-[11px] text-slate-400 leading-relaxed pt-1">
                  <span className="text-slate-300">{selectedTurbine.model}</span>
                  {' · '}installed {selectedTurbine.install_date}
                  {' · '}last service {selectedTurbine.last_service_date}
                  {selectedTurbine.active_alarms && selectedTurbine.active_alarms.length > 0 && (
                    <div className="mt-1.5 flex items-start gap-1.5 text-amber-300">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                      <span>{selectedTurbine.active_alarms.join('; ')}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Voice/text query */}
              <label className="text-[10px] uppercase tracking-wider text-slate-500 pt-2 block">
                Describe the issue
              </label>
              <div className="relative">
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  rows={3}
                  placeholder="e.g. blade leading-edge erosion outer 6m LP, what now?"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 pr-12 text-sm text-white focus:outline-none focus:border-cyan-500 resize-none"
                />
                <button
                  type="button"
                  onClick={() => {
                    // Visual-only "voice" — just toggles a state for affordance.
                    setRecording((r) => !r);
                    if (!recording) {
                      // Simulate a 1.4s "listening" then stop.
                      setTimeout(() => setRecording(false), 1400);
                    }
                  }}
                  title="Voice dictation (mock)"
                  className={`absolute right-2 bottom-2 p-2 rounded-lg ${
                    recording
                      ? 'bg-red-500/30 text-red-300 animate-pulse'
                      : 'bg-slate-800 hover:bg-slate-700 text-cyan-400'
                  }`}
                >
                  <Mic className="w-4 h-4" />
                </button>
              </div>

              {/* Optional photo — sent to the troubleshoot agent as a
                  base64 data URL for multimodal reasoning. Common case:
                  the technician snaps the blade-erosion or the gearbox
                  oil-film and lets the agent reason over what it sees. */}
              <div className="pt-2">
                <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1">
                  Attach a photo of the damage (optional)
                </label>
                <div className="flex items-center gap-2">
                  <label
                    htmlFor="fieldedge-photo"
                    className="flex-1 cursor-pointer rounded-lg border border-dashed border-slate-700 hover:border-cyan-500/60 bg-slate-950 px-3 py-2 text-xs text-slate-400 transition-colors"
                  >
                    {photoDataUrl
                      ? `📎 ${photoName} attached — click to replace`
                      : 'Tap to choose / drag-drop a JPG/PNG (≤4 MB)'}
                  </label>
                  {photoDataUrl && (
                    <button
                      type="button"
                      onClick={() => { setPhotoDataUrl(null); setPhotoName(''); }}
                      className="px-2 py-1 text-[10px] text-slate-400 hover:text-rose-300 border border-slate-700 rounded"
                    >
                      Remove
                    </button>
                  )}
                </div>
                <input
                  id="fieldedge-photo"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    if (f.size > 4 * 1024 * 1024) {
                      setError('Photo must be ≤4 MB.');
                      return;
                    }
                    const reader = new FileReader();
                    reader.onload = () => {
                      setPhotoDataUrl(typeof reader.result === 'string' ? reader.result : null);
                      setPhotoName(f.name);
                    };
                    reader.readAsDataURL(f);
                  }}
                />
                {photoDataUrl && (
                  <div className="mt-2 rounded-lg border border-slate-800 overflow-hidden bg-slate-950 max-w-xs">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={photoDataUrl} alt={photoName} className="w-full max-h-44 object-contain" />
                  </div>
                )}
              </div>

              <button
                onClick={streaming ? stopStream : submitSymptom}
                disabled={!pipelineId && !streaming}
                className={`w-full flex items-center justify-center gap-2 py-3 rounded-lg font-medium text-sm transition-colors ${
                  streaming
                    ? 'bg-red-500/20 border border-red-500/40 text-red-300'
                    : 'bg-cyan-500 text-slate-950 hover:bg-cyan-400 disabled:bg-slate-700 disabled:text-slate-500'
                }`}
              >
                {streaming ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Cancel</>
                ) : (
                  <><Send className="w-4 h-4" /> Get Repair Procedure</>
                )}
              </button>
              {!pipelineId && (
                <p className="text-[10px] text-slate-500 text-center">
                  iot-fieldedge-pipeline not yet seeded.
                </p>
              )}
              {error && (
                <div className="flex items-start gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg p-2.5">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}
            </div>
          </motion.div>
        </div>

        <KbBadge />

        {/* Streaming log */}
        {streamLog.length > 0 && (
          <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 font-mono text-[11px] text-slate-400 space-y-0.5 max-h-32 overflow-auto">
            {streamLog.slice(-8).map((l, i) => <div key={i}>{l}</div>)}
          </div>
        )}

        {/* ── Troubleshoot result ─────────────────────────────────────── */}
        <AnimatePresence>
          {troubleshoot && (
            <motion.div
              key="troubleshoot"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              className="space-y-4"
            >
              {/* Safety + summary header */}
              <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                <div className="flex items-start gap-3 flex-wrap">
                  <ShieldAlert className="w-5 h-5 text-cyan-400 shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h4 className="text-white font-semibold text-sm">Repair procedure</h4>
                      <span className={`text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-md border ${gateTone(troubleshoot.safety_gate)}`}>
                        {troubleshoot.safety_gate ?? '—'}
                      </span>
                      {typeof troubleshoot.confidence === 'number' && (
                        <span className="text-[11px] text-slate-400">
                          conf <b className="text-slate-200">{(troubleshoot.confidence * 100).toFixed(0)}%</b>
                        </span>
                      )}
                      {typeof troubleshoot.estimated_hours === 'number' && (
                        <span className="text-[11px] text-slate-400">
                          est <b className="text-slate-200">{troubleshoot.estimated_hours}h</b>
                        </span>
                      )}
                    </div>
                    {troubleshoot.diagnosis_summary && (
                      <p className="text-sm text-slate-300 mt-2">{troubleshoot.diagnosis_summary}</p>
                    )}
                    {troubleshoot.rationale && (
                      <p className="text-xs text-slate-400 italic mt-2">{troubleshoot.rationale}</p>
                    )}
                    {troubleshoot.escalate_to_engineering && (
                      <div className="mt-3 flex items-start gap-2 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-lg p-2.5">
                        <AlertTriangle className="w-3.5 h-3.5 mt-0.5" />
                        <span>Confidence below threshold — escalation to engineering recommended.</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Manual citations + similar WOs */}
              <div className="grid md:grid-cols-2 gap-4">
                <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
                    Cited manual sections
                  </p>
                  {(troubleshoot.manual_citations ?? []).length > 0 ? (
                    <ul className="space-y-2">
                      {(troubleshoot.manual_citations ?? []).map((m, i) => (
                        <li key={i} className="text-xs">
                          <p className="text-cyan-300 font-mono">{m.section}</p>
                          {m.excerpt && <p className="text-slate-400 italic mt-0.5">"{m.excerpt}"</p>}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500 italic">No KB hits — answer based on fleet history only.</p>
                  )}
                </div>
                <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
                    Similar past work orders
                  </p>
                  {(troubleshoot.similar_past_wos ?? []).length > 0 ? (
                    <ul className="space-y-2">
                      {(troubleshoot.similar_past_wos ?? []).map((w, i) => (
                        <li key={i} className="text-xs flex items-start gap-2">
                          <span className={`shrink-0 px-1.5 py-0.5 text-[9px] rounded border ${tone(w.match_quality)}`}>
                            {w.match_quality ?? 'match'}
                          </span>
                          <span className="text-slate-300">
                            <span className="font-mono text-cyan-300">{w.wo_id}</span>
                            {' '}({w.turbine_id}) — {w.issue}
                            {typeof w.hours === 'number' && (
                              <span className="text-slate-500"> · {w.hours}h</span>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500 italic">No matching past WOs across the fleet.</p>
                  )}
                </div>
              </div>

              {/* Procedure steps */}
              {(troubleshoot.procedure ?? []).length > 0 && (
                <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                  <div className="flex items-center gap-2 mb-3">
                    <Wrench className="w-4 h-4 text-cyan-400" />
                    <p className="text-white font-semibold text-sm">Procedure</p>
                  </div>
                  <ol className="space-y-2">
                    {(troubleshoot.procedure ?? []).map((s) => (
                      <li key={s.step} className="flex gap-3 text-sm">
                        <span className="shrink-0 w-7 h-7 rounded-full bg-cyan-500/15 text-cyan-300 text-xs font-mono flex items-center justify-center">
                          {s.step}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-slate-200">{s.action}</p>
                          {s.tool_required && (
                            <p className="text-[11px] text-slate-500 mt-0.5">
                              tool: <span className="text-slate-300">{s.tool_required}</span>
                            </p>
                          )}
                          {s.warning && (
                            <p className="text-[11px] text-amber-300 mt-0.5 flex items-start gap-1">
                              <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" /> {s.warning}
                            </p>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {/* Parts */}
              {(troubleshoot.parts_required ?? []).length > 0 && (
                <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
                    Parts required
                  </p>
                  <table className="w-full text-xs">
                    <thead className="text-slate-500">
                      <tr><th className="text-left font-normal">Part #</th><th className="text-left font-normal">Description</th><th className="text-right font-normal">Qty</th></tr>
                    </thead>
                    <tbody>
                      {(troubleshoot.parts_required ?? []).map((p, i) => (
                        <tr key={i} className="border-t border-slate-800">
                          <td className="py-1.5 font-mono text-cyan-300">{p.part_number}</td>
                          <td className="py-1.5 text-slate-300">{p.description}</td>
                          <td className="py-1.5 text-right text-slate-200">{p.qty}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {troubleshoot.part_lookup_required && (
                    <p className="text-[11px] text-amber-300 mt-2">Some parts need engineer-side lookup.</p>
                  )}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Closeout panel ───────────────────────────────────────────── */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <ClipboardCheck className="w-4 h-4 text-cyan-400" />
            <h4 className="text-white font-semibold text-sm">Voice close-out</h4>
            <span className="text-[10px] text-slate-500">
              free-text → structured WO record
            </span>
          </div>
          <textarea
            value={closeoutText}
            onChange={(e) => setCloseoutText(e.target.value)}
            rows={4}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-cyan-500 resize-none font-sans"
          />
          <div className="flex items-center gap-2 mt-3">
            <button
              onClick={submitCloseout}
              disabled={submittingCloseout}
              className="flex items-center gap-2 px-4 py-2 text-sm rounded-lg bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/30 disabled:opacity-50"
            >
              {submittingCloseout ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {submittingCloseout ? 'Documenting…' : 'Document Close-out'}
            </button>
            {closeoutError && (
              <span className="text-xs text-red-300">{closeoutError}</span>
            )}
          </div>

          {closeout && (
            <div className="mt-4 grid md:grid-cols-2 gap-3 text-xs">
              <KV label="Status" value={closeout.status ?? '—'} />
              <KV label="Labour hours" value={String(closeout.labour_hours ?? '—')} />
              <KV label="Root cause" value={closeout.root_cause ?? '—'} />
              <KV label="Confidence" value={typeof closeout.confidence === 'number' ? `${(closeout.confidence * 100).toFixed(0)}%` : '—'} />
              {(closeout.parts_consumed ?? []).length > 0 && (
                <div className="md:col-span-2">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Parts consumed</p>
                  <ul className="space-y-1">
                    {(closeout.parts_consumed ?? []).map((p, i) => (
                      <li key={i}>
                        <span className="font-mono text-cyan-300">{p.part_number}</span>
                        {' · '}{p.description}{' · '}<b className="text-slate-200">×{p.qty}</b>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {(closeout.actions_taken ?? []).length > 0 && (
                <div className="md:col-span-2">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Actions taken</p>
                  <ul className="list-disc list-inside text-slate-300 space-y-0.5">
                    {(closeout.actions_taken ?? []).map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </div>
              )}
              {(closeout.follow_up_actions ?? []).length > 0 && (
                <div className="md:col-span-2">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Follow-up</p>
                  <ul className="space-y-0.5">
                    {(closeout.follow_up_actions ?? []).map((a, i) => (
                      <li key={i} className="text-slate-300">
                        {a.action} {a.due_date && <span className="text-slate-500">({a.due_date}, {a.priority})</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {closeout.service_summary_for_customer && (
                <div className="md:col-span-2 mt-1 p-3 rounded-lg bg-slate-950/60 border border-slate-800">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">
                    Customer-facing summary
                  </p>
                  <p className="text-slate-200 italic">{closeout.service_summary_for_customer}</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Schedule grid ────────────────────────────────────────────── */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4 text-cyan-400" />
              <h4 className="text-white font-semibold text-sm">Crew schedule — next 7 days</h4>
              {schedule?.solver_used && (
                <span className="text-[10px] text-slate-500">solver: {schedule.solver_used}</span>
              )}
            </div>
            <button
              onClick={reoptimiseSchedule}
              disabled={optimising || techs.length === 0}
              className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/30 disabled:opacity-50"
            >
              {optimising ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
              {optimising ? 'Solving…' : 'Re-optimise schedule'}
            </button>
          </div>
          {scheduleError && (
            <p className="text-xs text-red-300 mb-2">{scheduleError}</p>
          )}
          {schedule ? (
            <ScheduleGrid schedule={schedule} techs={techs} forecast={DEFAULT_FORECAST} />
          ) : (
            <p className="text-xs text-slate-500 italic">
              Click "Re-optimise schedule" to assign open WOs across the crew. Solver picks
              technician + day based on skills, weather windows, and parts availability.
            </p>
          )}
          {schedule?.summary && (
            <p className="mt-3 text-xs text-slate-400 italic">{schedule.summary}</p>
          )}
          {(schedule?.risks ?? []).length > 0 && (
            <div className="mt-2 text-xs text-amber-300 space-y-0.5">
              {(schedule!.risks ?? []).map((r, i) => (
                <div key={i} className="flex items-start gap-1.5"><AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />{r}</div>
              ))}
            </div>
          )}
        </div>

        <PipelineDagViz dag={FIELDEDGE_DAG} />
      </div>

      {/* ── Right rail ─────────────────────────────────────────────── */}
      <ScenarioExplainer
        eyebrow="Industrial IoT · Scenario C"
        title="Field Guide — On-the-Nacelle Maintenance Copilot"
        lede={
          <>
            A wind-farm technician is 90 m up a tower, harnessed
            against gusts, holding a 5-inch ruggedised tablet. They
            see <b className="text-white">leading-edge erosion on
            the LP side outer 6 m</b>. They could call the engineering
            office. Or they could ask Field Guide — and get the manual
            section, the parts list, and the past-WO precedent in
            seconds.
          </>
        }
        callouts={[
          { label: 'Fleet',         value: '12 turbines' },
          { label: 'WO history',    value: '30 past records' },
          { label: 'Crew',          value: '6 technicians' },
          { label: 'Latency target',value: '<5 s end-to-end' },
        ]}
        sections={[
          {
            icon: Wind,
            tone: 'cyan',
            title: 'The technician',
            body: (
              <>
                <p>
                  Two trades on a tower, one tablet, one weather
                  window. The OEM service manual is 800 pages.
                  The fleet's WO database has 30,000 rows. They
                  need <b className="text-white">the right paragraph
                  and the right precedent</b>, not a search engine.
                </p>
                <p>
                  Voice-or-text symptom in. Procedure out — with
                  cited section, parts, hours estimate, and the
                  "this is what TURB-04 did three months ago" anchor.
                </p>
              </>
            ),
          },
          {
            icon: ShieldAlert,
            tone: 'amber',
            title: 'Safety gates first',
            body: (
              <>
                <p>
                  Every answer runs through a hard safety check
                  <i> before</i> the procedure is written. Wind &gt;
                  12 m/s? Gusts &gt; 16? Lightning within 25 km?
                  → <code className="text-amber-300">STAND_DOWN_WEATHER</code>.
                  Smoke or arcing? →{' '}
                  <code className="text-amber-300">EVACUATE_AND_LOTO</code>.
                  Otherwise → <code className="text-emerald-300">PROCEED_WITH_LOTO</code>.
                </p>
                <p>
                  The agent never quietly downgrades a dangerous
                  procedure to "with caution". Bad-weather work just
                  doesn't get a procedure.
                </p>
              </>
            ),
          },
          {
            icon: Wrench,
            tone: 'purple',
            title: 'Grounded answers',
            body: (
              <>
                <p>
                  The pipeline has two stages: a fleet-history
                  searcher that ranks past WOs by model match,
                  failure-mode keyword overlap, and outcome; then a
                  troubleshoot agent that pulls Vestas /
                  Siemens-Gamesa-style manual sections from the
                  KB and writes a step-by-step procedure citing
                  them.
                </p>
                <p>
                  No KB hit? The agent says so, lowers confidence,
                  and offers the fleet-history precedent only —
                  it does <i>not</i> fabricate a manual citation.
                </p>
              </>
            ),
          },
          {
            icon: Calendar,
            tone: 'emerald',
            title: 'Schedule + close-out',
            body: (
              <>
                <p>
                  The schedule optimiser wraps a Python OR-tools
                  CP-SAT solver (with greedy fallback when the
                  package is missing). Constraints: technician
                  skills, daily hours, weather windows, parts
                  availability. Objective: P1 first, spread across
                  the crew, minimise the unassigned set.
                </p>
                <p>
                  Close-out is a separate agent — free-text in,
                  parts/hours/root-cause/follow-up out, plus a
                  customer-facing service summary in plain English.
                </p>
              </>
            ),
          },
          {
            icon: Sparkles,
            tone: 'cyan',
            title: 'Why it matters',
            body: (
              <ul className="list-disc list-outside pl-4 space-y-1">
                <li>Unplanned blade outages cost ~1 % AEP per turbine per week.</li>
                <li>Average WO close-out adds 30+ min of post-tower paperwork. Voice → JSON kills that.</li>
                <li>Schedule re-optimise runs sub-second on the cluster — no Excel tug-of-war.</li>
                <li>Every step is audited under <code className="text-cyan-300">/executions</code>.</li>
              </ul>
            ),
          },
        ]}
        agentTrace={[
          {
            agent_slug: 'iot-fieldedge-pipeline',
            source: 'agent',
            when: 'click "Get Repair Procedure"',
            inputs: 'turbine_id (TURB-01..12), model + install_date pulled from fleet.json, plus the free-text or dictated issue',
            outputs: 'JSON with cited procedure steps, parts list, similar past WOs, safety gate flag',
          },
          {
            agent_slug: 'iot-fieldedge-fleet-history-searcher',
            source: 'agent',
            when: 'pipeline branch — runs in parallel with troubleshoot',
            inputs: 'turbine model + issue text + the historical-wos.json corpus indexed in rwe-fieldedge-oem-manuals',
            outputs: 'top-3 similar past WOs with date, technician, parts, hours, outcome',
          },
          {
            agent_slug: 'iot-fieldedge-troubleshoot-assistant',
            source: 'agent',
            when: 'pipeline branch — KB-grounded, multimodal',
            inputs: 'issue text + (optional) base64 photo data URL the technician attaches + fleet-history results + the rwe-fieldedge-oem-manuals KB (V120 / SG-3.4 manual excerpts). Claude Sonnet reads the image directly when present.',
            outputs: 'procedure with cited manual sections (e.g. "V120-2.0 §5.4.7"), torque values, safety preconditions, and (when a photo was given) what the agent observed in the image',
          },
          {
            agent_slug: 'iot-fieldedge-schedule-optimizer',
            source: 'agent',
            when: 'click "Re-optimise schedule"',
            inputs: 'work_orders[] + technicians[] + 7-day weather forecast + the OR-tools or-tools_scheduler code asset',
            outputs: 'technician × day assignment matrix with priority scoring, weather-windowing, parts-availability gates',
          },
          {
            agent_slug: 'iot-fieldedge-closeout-documenter',
            source: 'agent',
            when: 'click "Convert to WO"',
            inputs: 'free-form close-out narrative the technician dictates / types',
            outputs: 'structured WO record (parts used, hours, root cause, follow-up flag) ready for the CMMS',
          },
        ]}
        simulationNote={(
          <>
            <p className="mb-2">
              <strong>In production —</strong> turbines + WO history come from the
              CMMS (SAP&nbsp;PM, IBM&nbsp;Maximo, Infor&nbsp;EAM) via REST every page
              load; technician roster + skills matrix live in the HRIS / certifications
              system (Workday + safety-cert DB); the 7-day weather forecast comes from
              the MET Office API or DTN; parts inventory checks the warehouse system
              (SAP&nbsp;MM / Oracle WMS) for on-hand counts before the optimiser
              schedules a job. Closed WOs write back to the CMMS via the same REST
              integration. Photos go through ServiceNow / IBM Maximo Mobile, base64'd
              into the agent payload.
            </p>
            <p>
              <strong>In the demo —</strong> the 12-turbine fleet, 30 historical WOs,
              and 6-technician roster are static JSON files at
              <code className="text-cyan-300 mx-1">scaffolding/fieldedge/data/</code>{' '}
              fetched once on page mount via
              <code className="text-cyan-300 mx-1">/industrial-iot/fieldedge/*.json</code>.
              No CMMS, no scheduled poll. <strong>Get Repair Procedure</strong> and
              <strong> Re-optimise schedule</strong> each fire one synchronous pipeline
              call. Photo upload uses the browser <code>FileReader</code> to convert
              the file to a base64 data URL client-side — never written to disk.
              The repair procedure, parts list, safety gate, schedule, and (when a
              photo is attached) the multimodal observations are all generated by the
              agents above.
            </p>
          </>
        )}
        footer={
          <p className="text-xs text-slate-400 leading-relaxed">
            <Sparkles className="w-3.5 h-3.5 inline mr-1.5 text-cyan-400" />
            Pick a turbine, type or dictate the issue, hit{' '}
            <b className="text-white">Get Repair Procedure</b>. The
            pipeline takes ~30 s end-to-end (LLM round-trip is the
            long pole).
          </p>
        }
      />
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────────────────

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-slate-200 mt-0.5">{value}</p>
    </div>
  );
}

// Heuristic skill mapping from a free-text issue. Good enough for the demo's
// auto-populated WO list — agents can override this on the real data path.
function skillFromIssue(issue: string): string {
  const lower = issue.toLowerCase();
  if (lower.includes('blade') || lower.includes('erosion') || lower.includes('le ')) return 'blade-repair';
  if (lower.includes('gearbox') || lower.includes('oil')) return 'gearbox';
  if (lower.includes('generator') || lower.includes('winding')) return 'generator';
  if (lower.includes('yaw') || lower.includes('pitch') || lower.includes('encoder')) return 'electrical';
  if (lower.includes('lightning')) return 'lightning-cert';
  return 'climbing-cert';
}

// Pull the structured JSON the agent printed out of the wrapper response.
// The /api/agents/{slug}/execute proxy returns {data:{response: ...}} or
// {data:{output: ...}} depending on whether the agent ran as oob or
// wrapped — handle both.
function parseAgentOutput(json: unknown): unknown {
  const j = json as Record<string, unknown>;
  const data = (j.data ?? j) as Record<string, unknown>;
  let raw = data.response ?? data.output ?? data.final_output ?? data;
  if (typeof raw === 'string') {
    // Strip ``` fences if present.
    const trimmed = raw.trim().replace(/^```(?:json)?\s*|```$/g, '').trim();
    try { raw = JSON.parse(trimmed); } catch { /* leave as string */ }
  }
  return raw;
}

// ── ScheduleGrid ────────────────────────────────────────────────────

function ScheduleGrid({
  schedule, techs, forecast,
}: {
  schedule: ScheduleResult;
  techs: Technician[];
  forecast: { day: string; wind_mps: number; precip: string; climb_safe: boolean }[];
}) {
  const days = forecast.map((f) => f.day);
  // Build the cell index: tech -> day -> assignment (or null).
  const byCell = new Map<string, ScheduleAssignment | null>();
  (schedule.assignments ?? []).forEach((a) => {
    byCell.set(`${a.technician_id}|${a.day}`, a);
  });

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] border-collapse">
        <thead>
          <tr>
            <th className="text-left text-slate-500 font-normal pb-2 pr-2">Tech</th>
            {days.map((d, i) => {
              const f = forecast[i];
              return (
                <th key={d} className="text-left text-slate-500 font-normal pb-2 px-1.5 min-w-[80px]">
                  <div>{d.slice(5)}</div>
                  <div className={`text-[9px] ${f.climb_safe ? 'text-emerald-400' : 'text-amber-300'}`}>
                    {f.wind_mps.toFixed(1)} m/s · {f.precip}
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {techs.map((t) => (
            <tr key={t.id} className="border-t border-slate-800/60">
              <td className="py-1.5 pr-2 text-slate-300 align-top">
                <p className="font-mono">{t.id}</p>
                <p className="text-[9px] text-slate-500 truncate max-w-[110px]">{t.name}</p>
              </td>
              {days.map((d) => {
                const a = byCell.get(`${t.id}|${d}`) || null;
                return (
                  <td key={d} className="px-1 py-1 align-top">
                    {a ? (
                      <div className={`rounded-md p-1.5 border ${prioTone(a.priority)}`}>
                        <p className="font-mono text-[10px] truncate">{a.wo_id}</p>
                        <p className="text-[9px] text-slate-300 truncate">{a.turbine_id}</p>
                        <p className="text-[9px] text-slate-500">{a.duration_hours}h</p>
                      </div>
                    ) : (
                      <div className="h-full min-h-[42px] rounded-md bg-slate-950/40 border border-slate-800/30" />
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {(schedule.unassigned ?? []).length > 0 && (
        <div className="mt-3 text-xs text-amber-300">
          Unassigned: {(schedule.unassigned ?? []).map((u) => `${u.wo_id} (${u.reason})`).join(', ')}
        </div>
      )}
    </div>
  );
}

function prioTone(p?: string): string {
  switch (p) {
    case 'P1': return 'bg-red-500/15 border-red-500/30 text-red-200';
    case 'P2': return 'bg-amber-500/10 border-amber-500/30 text-amber-200';
    case 'P3': return 'bg-cyan-500/10 border-cyan-500/30 text-cyan-200';
    default:   return 'bg-slate-700/30 border-slate-600/30 text-slate-300';
  }
}
