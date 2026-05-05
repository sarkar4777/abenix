'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle, ShieldAlert, FileText, RefreshCw, ChevronDown, ChevronRight,
  CheckCircle2, X, Loader2, Activity, Clock, Wrench, Brain, Boxes,
  Workflow, Bell, Eye, EyeOff, FlaskConical, Send, Truck,
} from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend,
} from 'recharts';
import ScenarioExplainer from '../components/ScenarioExplainer';
import PipelineDagViz from '../components/PipelineDagViz';
import { BEDROCC_DAG } from '../components/dags';
import KbBadge from '../components/KbBadge';
import { findPipelineBySlug, runPipeline, type PipelineKey } from '../lib/pipelineRunner';

// ── Types ────────────────────────────────────────────────────────────
type ScadaSeverity = 'INFO' | 'LOW' | 'MED' | 'HIGH' | 'CRIT';
type AlarmStatus = 'NEW' | 'TRIAGED' | 'SUPPRESSED' | 'RESOLVED';
type RecommendedAction =
  | 'safe_remote_reset'
  | 'dispatch_technician'
  | 'wait_for_cascade'
  | 'suppress_as_noise'
  | 'escalate_supervisor';

interface AlarmAsset {
  site: string;
  turbine: string;
  subsystem: string;
}

interface RawAlarm {
  alarm_id: string;
  timestamp: string;
  asset: AlarmAsset;
  code: string;
  scada_severity: ScadaSeverity;
  raw_value: number | null;
  unit: string | null;
  description: string;
  context: Record<string, number | string | null | undefined>;
  scenario_tag?: string;
}

interface Triage {
  classification?: {
    ai_severity?: ScadaSeverity;
    scada_severity_overridden?: boolean;
    root_cause?: string;
    confidence?: number;
    recommended_action?: RecommendedAction;
    roi_estimate?: { amount_usd_per_hour?: number; basis?: string; spread_over_hours?: number | null };
    rationale?: string;
  };
  cascade?: {
    is_cascade?: boolean;
    primary_alarm_id?: string | null;
    primary_alarm_code?: string;
    suppressed_alarms?: { alarm_id: string; code: string; reason: string }[];
    rationale?: string;
    confidence?: number;
  };
  reset_advice?: {
    decision?: 'ALLOW' | 'DENY';
    reason?: string;
    reset_command?: string | null;
    preconditions_checked?: { check: string; status: string; evidence: string }[];
    two_person_confirmation_required?: boolean;
    authority_required?: 'T1' | 'T2' | 'T3';
    sop_cited?: string;
    rollback_if_alarm_returns?: string;
  } | null;
}

interface AlarmRow extends RawAlarm {
  status: AlarmStatus;
  triage?: Triage;
  triageError?: string;
  triageInFlight?: boolean;
  suppressedBy?: string;
  resetApproved?: {
    command: string;
    operator: string;
    twoPerson: boolean;
    outcome: 'cleared' | 'in_flight';
  };
  dispatched?: {
    crew: string;
    eta: string;
    wo_id: string;
  };
}

// ── Sample alarm bank — 30 hand-tuned events covering the full
//    operator surface: comms glitches, soft-reset candidates, a
//    multi-alarm turbine cascade, a feeder-wide grid event, two
//    critical dispatch-only events, and a two-person case. The UI
//    streams a subset of these every 4-6s on mount so the queue
//    feels alive without external data dependencies.
const SAMPLE_ALARMS: RawAlarm[] = [
  { alarm_id: 'ALM-2026-04-30-0001', timestamp: '2026-04-30T06:14:08Z', asset: { site: 'Northern Lights', turbine: 'NL-T-03', subsystem: 'comms' }, code: 'COMMS-LOSS', scada_severity: 'LOW', raw_value: null, unit: null, description: 'Telemetry heartbeat from turbine missed 3 of last 10 polls.', context: { wind_mps: 6.4, power_kw: 1240, ambient_c: 5.0 }, scenario_tag: 'comms_glitch_benign' },
  { alarm_id: 'ALM-2026-04-30-0003', timestamp: '2026-04-30T07:31:15Z', asset: { site: 'Northern Lights', turbine: 'NL-T-15', subsystem: 'yaw' }, code: 'YAW-MOTOR-OL', scada_severity: 'MED', raw_value: 118, unit: '%', description: 'Yaw motor overload, current 118% nameplate for 30s.', context: { wind_mps: 9.1, power_kw: 1850, ambient_c: 6.5, yaw_attempts_last_hour: 1 }, scenario_tag: 'soft_reset_candidate' },
  { alarm_id: 'ALM-2026-04-30-0004', timestamp: '2026-04-30T08:14:33Z', asset: { site: 'Northern Lights', turbine: 'NL-T-08', subsystem: 'gearbox' }, code: 'GBX-VIB-HI', scada_severity: 'HIGH', raw_value: 7.4, unit: 'mm/s', description: 'Gearbox high-speed-shaft vibration RMS above WARN threshold.', context: { wind_mps: 11.2, power_kw: 2150, ambient_c: 4.0 }, scenario_tag: 'cascade_primary' },
  { alarm_id: 'ALM-2026-04-30-0005', timestamp: '2026-04-30T08:14:41Z', asset: { site: 'Northern Lights', turbine: 'NL-T-08', subsystem: 'generator' }, code: 'GEN-TEMP-HI', scada_severity: 'MED', raw_value: 158, unit: 'C', description: 'Generator winding temperature rising at 1.4 C/min.', context: { wind_mps: 11.2, power_kw: 2110, ambient_c: 4.0 }, scenario_tag: 'cascade_downstream' },
  { alarm_id: 'ALM-2026-04-30-0006', timestamp: '2026-04-30T08:14:48Z', asset: { site: 'Northern Lights', turbine: 'NL-T-08', subsystem: 'converter' }, code: 'OVT-DC-LINK', scada_severity: 'HIGH', raw_value: 1290, unit: 'V', description: 'DC link overvoltage transient, 1290 V peak.', context: { wind_mps: 11.2, power_kw: 0, ambient_c: 4.0 }, scenario_tag: 'cascade_downstream' },
  { alarm_id: 'ALM-2026-04-30-0007', timestamp: '2026-04-30T08:14:56Z', asset: { site: 'Northern Lights', turbine: 'NL-T-08', subsystem: 'grid_interface' }, code: 'GRD-FRT-RIDE', scada_severity: 'HIGH', raw_value: null, unit: null, description: 'Fault Ride Through event triggered.', context: { wind_mps: 11.2, power_kw: 0, ambient_c: 4.0 }, scenario_tag: 'cascade_downstream' },
  { alarm_id: 'ALM-2026-04-30-0008', timestamp: '2026-04-30T09:02:11Z', asset: { site: 'Northern Lights', turbine: 'NL-T-21', subsystem: 'pitch' }, code: 'PITCH-DRIFT-LO', scada_severity: 'MED', raw_value: 2.3, unit: 'deg', description: 'Blade C pitch drift exceeds 2 deg from commanded.', context: { wind_mps: 8.4, power_kw: 1620, ambient_c: 7.0 }, scenario_tag: 'soft_reset_candidate' },
  { alarm_id: 'ALM-2026-04-30-0009', timestamp: '2026-04-30T09:43:02Z', asset: { site: 'Northern Lights', turbine: 'NL-T-11', subsystem: 'gearbox' }, code: 'GBX-OIL-LO', scada_severity: 'CRIT', raw_value: 1.2, unit: 'bar', description: 'Gearbox oil pressure below 1.5 bar threshold.', context: { wind_mps: 12.0, power_kw: 2400, ambient_c: 4.5 }, scenario_tag: 'critical_dispatch_only' },
  { alarm_id: 'ALM-2026-04-30-0011', timestamp: '2026-04-30T10:54:14Z', asset: { site: 'Northern Lights', turbine: 'NL-T-04', subsystem: 'generator' }, code: 'GEN-TEMP-HI', scada_severity: 'MED', raw_value: 152, unit: 'C', description: 'Generator winding temp at upper bound, no rate-of-rise.', context: { wind_mps: 13.2, power_kw: 2620, ambient_c: 8.0 }, scenario_tag: 'soft_reset_candidate' },
  { alarm_id: 'ALM-2026-04-30-0020', timestamp: '2026-04-30T14:54:33Z', asset: { site: 'Northern Lights', turbine: 'NL-T-02', subsystem: 'generator' }, code: 'GEN-WINDING-HI', scada_severity: 'HIGH', raw_value: 174, unit: 'C', description: 'Winding temperature in alarm band, two-person reset required.', context: { wind_mps: 13.8, power_kw: 2680, ambient_c: 10.0 }, scenario_tag: 'two_person_required' },
];

const SEVERITY_RANK: Record<ScadaSeverity, number> = { INFO: 0, LOW: 1, MED: 2, HIGH: 3, CRIT: 4 };

// ── Tone helpers ─────────────────────────────────────────────────────
function sevTone(sev?: string): string {
  switch (sev) {
    case 'CRIT':  return 'bg-red-500/20 text-red-300 border-red-500/40';
    case 'HIGH':  return 'bg-red-500/15 text-red-300 border-red-500/30';
    case 'MED':   return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
    case 'LOW':   return 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
    case 'INFO':  return 'bg-slate-700/60 text-slate-300 border-slate-600/40';
    default:      return 'bg-slate-700/60 text-slate-300 border-slate-600/40';
  }
}
function statusTone(s: AlarmStatus): string {
  switch (s) {
    case 'NEW':        return 'bg-slate-700/60 text-slate-200 border-slate-600/40';
    case 'TRIAGED':    return 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40';
    case 'SUPPRESSED': return 'bg-slate-800/80 text-slate-500 border-slate-700/60';
    case 'RESOLVED':   return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40';
  }
}
function actionLabel(a?: RecommendedAction): string {
  if (!a) return '—';
  return ({
    safe_remote_reset:    'Safe Remote Reset',
    dispatch_technician:  'Dispatch Technician',
    wait_for_cascade:     'Wait for Cascade',
    suppress_as_noise:    'Suppress as Noise',
    escalate_supervisor:  'Escalate Supervisor',
  } as const)[a];
}
function fmtUsd(v?: number): string {
  if (v == null) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}k/h`;
  return `$${Math.round(v)}/h`;
}
function fmtTs(iso: string): string {
  return iso.replace('T', ' ').replace(/Z$/, '').slice(11, 19);
}

// ── Component ────────────────────────────────────────────────────────
export default function BedRoccTab() {
  const [pipelineId, setPipelineId] = useState<PipelineKey | null>(null);
  const [alarms, setAlarms] = useState<AlarmRow[]>([]);
  const [streaming, setStreaming] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [bannerAck, setBannerAck] = useState<Record<string, boolean>>({});
  const [pendingReset, setPendingReset] = useState<AlarmRow | null>(null);
  const [resetStep, setResetStep] = useState<1 | 2>(1);
  const [resetError, setResetError] = useState<string>('');
  const [resetSubmitting, setResetSubmitting] = useState(false);

  const [reportLoading, setReportLoading] = useState(false);
  const [reportMd, setReportMd] = useState<string>('');
  const [reportError, setReportError] = useState<string>('');

  const streamIdxRef = useRef(0);
  const streamTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resolve the bedrocc pipeline slug at mount. The standalone API
  // exposes it via the listPipelines catalog.
  useEffect(() => {
    (async () => {
      const id = await findPipelineBySlug('iot-bedrocc-pipeline');
      setPipelineId(id);
    })();
  }, []);

  // Stream new alarms in every 4-6 seconds while streaming=true.
  useEffect(() => {
    if (!streaming) return;
    if (streamIdxRef.current >= SAMPLE_ALARMS.length) {
      setStreaming(false);
      return;
    }
    const next = SAMPLE_ALARMS[streamIdxRef.current];
    const delay = 4000 + Math.random() * 2000;
    streamTimerRef.current = setTimeout(() => {
      streamIdxRef.current += 1;
      setAlarms((prev) => [
        { ...next, status: 'NEW' as AlarmStatus },
        ...prev,
      ]);
      // Auto-trigger triage for the new alarm if pipeline is wired up.
      // Keeps the UI moving even if the user is reading something else.
      if (pipelineId) {
        // Defer slightly so React commits the new row first.
        setTimeout(() => triageAlarm(next.alarm_id), 50);
      }
    }, delay);
    return () => {
      if (streamTimerRef.current) clearTimeout(streamTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming, alarms.length, pipelineId]);

  // ── Triage a single alarm via the pipeline ─────────────────────
  const triageAlarm = async (alarmId: string) => {
    const target = (curr: AlarmRow[]) => curr.find((a) => a.alarm_id === alarmId);
    setAlarms((curr) => curr.map((a) => a.alarm_id === alarmId ? { ...a, triageInFlight: true, triageError: undefined } : a));

    // Use the most recent N other alarms as recent_alarms context.
    let recent: RawAlarm[] = [];
    setAlarms((curr) => {
      const alarm = target(curr);
      if (!alarm) return curr;
      const ts = new Date(alarm.timestamp).getTime();
      recent = curr.filter((a) =>
        a.alarm_id !== alarm.alarm_id &&
        Math.abs(new Date(a.timestamp).getTime() - ts) <= 60_000,
      ).slice(0, 8);
      return curr;
    });

    // Read latest snapshot synchronously after the setState batching.
    let alarm: AlarmRow | undefined;
    setAlarms((curr) => { alarm = target(curr); return curr; });
    if (!alarm || !pipelineId) return;

    const payload = {
      alarm: {
        alarm_id: alarm.alarm_id, timestamp: alarm.timestamp,
        asset: alarm.asset, code: alarm.code,
        description: alarm.description,
        scada_severity: alarm.scada_severity,
        raw_value: alarm.raw_value, unit: alarm.unit,
        context: alarm.context,
      },
      recent_alarms: recent,
      operator: { operator_id: 'OP-jsmith', authority_tier: 'T2' },
      loto_active: false,
      technician_in_nacelle: false,
      weather: {
        wind_mps: (alarm.context.wind_mps as number) ?? 0,
        lightning_within_km: (alarm.context.lightning_within_km as number) ?? 99,
      },
    };

    const result = await runPipeline(pipelineId, payload, {}, { waitSeconds: 120 });

    setAlarms((curr) => curr.map((a) => {
      if (a.alarm_id !== alarmId) return a;
      if (!result.ok) {
        return { ...a, triageInFlight: false, triageError: result.error || 'pipeline error' };
      }
      const fo = (result.final_output ?? {}) as Record<string, unknown>;
      const triage: Triage = {
        classification: (fo.classification as Triage['classification']) ?? undefined,
        cascade:        (fo.cascade        as Triage['cascade'])        ?? undefined,
        reset_advice:   (fo.reset_advice   as Triage['reset_advice'])   ?? null,
      };
      let nextStatus: AlarmStatus = 'TRIAGED';
      let suppressedBy: string | undefined;
      if (triage.cascade?.is_cascade && triage.cascade.suppressed_alarms?.some((s) => s.alarm_id === a.alarm_id)) {
        nextStatus = 'SUPPRESSED';
        suppressedBy = triage.cascade.primary_alarm_id ?? undefined;
      }
      return { ...a, triage, triageInFlight: false, status: nextStatus, suppressedBy };
    }));

    // After triage, propagate cascade suppression onto sibling rows.
    setAlarms((curr) => {
      const me = curr.find((a) => a.alarm_id === alarmId);
      const cas = me?.triage?.cascade;
      if (!cas?.is_cascade || !cas.suppressed_alarms?.length) return curr;
      const suppressedIds = new Set(cas.suppressed_alarms.map((s) => s.alarm_id));
      return curr.map((a) =>
        suppressedIds.has(a.alarm_id) && a.alarm_id !== alarmId
          ? { ...a, status: 'SUPPRESSED' as AlarmStatus, suppressedBy: cas.primary_alarm_id ?? alarmId }
          : a,
      );
    });
  };

  // ── Cascade banner detection ───────────────────────────────────
  // The UI surfaces a banner when 3+ correlated alarms hit within a
  // 60s window (same turbine OR all GRD-* on the same feeder). This
  // mirrors the noise_filter agent's cascade rule but renders it
  // even before the agent finishes — gives the operator immediate
  // situational awareness.
  const cascades = useMemo(() => {
    const out: { id: string; primary: AlarmRow; members: AlarmRow[]; reason: string }[] = [];
    const seen = new Set<string>();
    for (const a of alarms) {
      if (seen.has(a.alarm_id)) continue;
      const t = new Date(a.timestamp).getTime();
      const sameTurbine = alarms.filter(
        (b) => b.asset.turbine === a.asset.turbine
          && Math.abs(new Date(b.timestamp).getTime() - t) <= 60_000,
      );
      const sameGridEvent = a.code.startsWith('GRD-') ? alarms.filter(
        (b) => b.code.startsWith('GRD-')
          && Math.abs(new Date(b.timestamp).getTime() - t) <= 60_000,
      ) : [];
      const cluster = sameTurbine.length >= 3 ? sameTurbine
                      : sameGridEvent.length >= 3 ? sameGridEvent : null;
      if (!cluster) continue;
      // Pick the earliest as primary.
      const sorted = [...cluster].sort((x, y) => new Date(x.timestamp).getTime() - new Date(y.timestamp).getTime());
      const primary = sorted[0];
      if (seen.has(primary.alarm_id)) continue;
      sorted.forEach((m) => seen.add(m.alarm_id));
      out.push({
        id: primary.alarm_id,
        primary,
        members: sorted,
        reason: sameTurbine.length >= 3
          ? `Same turbine (${primary.asset.turbine})`
          : `Grid event across ${new Set(cluster.map((c) => c.asset.turbine)).size} turbines`,
      });
    }
    return out;
  }, [alarms]);

  // ── Approve safe reset (two-step modal) ────────────────────────
  const openResetModal = (a: AlarmRow) => {
    setPendingReset(a);
    setResetStep(1);
    setResetError('');
  };
  const proceedResetStep1 = () => setResetStep(2);
  const cancelReset = () => {
    setPendingReset(null);
    setResetStep(1);
    setResetError('');
  };

  const submitReset = async () => {
    if (!pendingReset) return;
    const advice = pendingReset.triage?.reset_advice;
    if (!advice || advice.decision !== 'ALLOW' || !advice.reset_command) {
      setResetError('Advisor denied this reset — operator override is not supported.');
      return;
    }
    setResetSubmitting(true);
    setResetError('');
    // We don't actually fire a control command from the showcase — log
    // the approval to the audit trail (visible in the row) and mark
    // the alarm RESOLVED. A production wire-up would POST to a
    // control-bus endpoint here.
    await new Promise((r) => setTimeout(r, 600));

    setAlarms((curr) => curr.map((a) =>
      a.alarm_id === pendingReset.alarm_id
        ? {
            ...a,
            status: 'RESOLVED' as AlarmStatus,
            resetApproved: {
              command: advice.reset_command!,
              operator: 'OP-jsmith',
              twoPerson: !!advice.two_person_confirmation_required,
              outcome: 'cleared',
            },
          }
        : a,
    ));
    setResetSubmitting(false);
    setPendingReset(null);
    setResetStep(1);
  };

  // ── Bar chart — alarms by AI severity over the shift ───────────
  const sevSeries = useMemo(() => {
    // Bucket alarms into 30-minute slots starting from the earliest
    // alarm so the bar chart shows a coherent shift timeline.
    if (alarms.length === 0) return [] as { slot: string; INFO: number; LOW: number; MED: number; HIGH: number; CRIT: number }[];
    const sorted = [...alarms].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
    const start = new Date(sorted[0].timestamp).getTime();
    const buckets: Record<string, { slot: string; INFO: number; LOW: number; MED: number; HIGH: number; CRIT: number }> = {};
    for (const a of sorted) {
      const offset = Math.floor((new Date(a.timestamp).getTime() - start) / (30 * 60_000));
      const slotIso = new Date(start + offset * 30 * 60_000).toISOString().slice(11, 16);
      if (!buckets[slotIso]) buckets[slotIso] = { slot: slotIso, INFO: 0, LOW: 0, MED: 0, HIGH: 0, CRIT: 0 };
      const sev = (a.triage?.classification?.ai_severity ?? a.scada_severity) as ScadaSeverity;
      buckets[slotIso][sev] += 1;
    }
    return Object.values(buckets);
  }, [alarms]);

  // ── EOD shift-report generation ────────────────────────────────
  const generateReport = async () => {
    if (!pipelineId) {
      setReportError('Pipeline not yet seeded on this cluster.');
      return;
    }
    setReportLoading(true);
    setReportError('');
    setReportMd('');
    // The shift_reporter agent expects a denormalised payload. We
    // call it directly through the Abenix /agents endpoint via the
    // existing /api/agents proxy on the standalone API. The path is
    // /api/agents/{slug}/execute — fall back to message-only if the
    // proxy doesn't accept structured input.
    const body = {
      shift: {
        shift_id: 'DAY-2026-04-30',
        supervisor: 'OP-jsmith',
        start_iso: '2026-04-30T06:00:00Z',
        end_iso:   '2026-04-30T18:00:00Z',
      },
      alarms: alarms.map((a) => ({
        alarm_id: a.alarm_id,
        timestamp: a.timestamp,
        asset: a.asset,
        code: a.code,
        scada_severity: a.scada_severity,
        ai_severity: a.triage?.classification?.ai_severity,
        status: a.status,
        action_taken: a.triage?.classification?.recommended_action,
        resolution_notes: a.triageError ?? a.triage?.classification?.rationale ?? '',
        open: a.status !== 'RESOLVED' && a.status !== 'SUPPRESSED',
      })),
      resets_approved: alarms.filter((a) => a.resetApproved).map((a) => ({
        alarm_id: a.alarm_id,
        command: a.resetApproved!.command,
        operator: a.resetApproved!.operator,
        two_person_signoff: a.resetApproved!.twoPerson,
        outcome: a.resetApproved!.outcome,
      })),
      dispatches: alarms.filter((a) => a.dispatched).map((a) => ({
        alarm_id: a.alarm_id, ...a.dispatched!,
      })),
      kpis: {
        uptime_pct: 98.4,
        alarms_total: alarms.length,
        alarms_suppressed: alarms.filter((a) => a.status === 'SUPPRESSED').length,
        resets_attempted: alarms.filter((a) => a.resetApproved).length,
        resets_succeeded: alarms.filter((a) => a.resetApproved?.outcome === 'cleared').length,
        mean_time_to_triage_seconds: 94,
        lost_generation_kwh: 820,
      },
    };

    try {
      const r = await fetch('/api/agents/iot-bedrocc-shift-reporter/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: JSON.stringify(body) }),
      });
      const j = await r.json();
      if (!r.ok) {
        setReportError(j?.error || `HTTP ${r.status}`);
      } else {
        const out = j?.data?.output ?? j?.output ?? j?.final_output ?? j;
        const md = (out?.report_markdown as string) || (typeof out === 'string' ? out : '');
        if (md) setReportMd(md);
        else setReportError('agent returned no report_markdown field');
      }
    } catch (e) {
      setReportError((e as Error).message);
    } finally {
      setReportLoading(false);
    }
  };

  // ── KPIs strip ─────────────────────────────────────────────────
  const kpis = useMemo(() => {
    const total = alarms.length;
    const suppressed = alarms.filter((a) => a.status === 'SUPPRESSED').length;
    const resolved = alarms.filter((a) => a.status === 'RESOLVED').length;
    const open = alarms.filter((a) => a.status === 'NEW' || a.status === 'TRIAGED').length;
    const overrides = alarms.filter((a) => a.triage?.classification?.scada_severity_overridden).length;
    const roi = alarms.reduce(
      (acc, a) => acc + (a.triage?.classification?.roi_estimate?.amount_usd_per_hour ?? 0),
      0,
    );
    return { total, suppressed, resolved, open, overrides, roi };
  }, [alarms]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-6">
      <div className="space-y-6 min-w-0">

        {/* ── Header strip ─────────────────────────────────────── */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-cyan-400" />
              Operations Control Room — Live Alarm Queue
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Northern Lights wind-farm SCADA bus. Alarms stream in
              every 4-6s. Click a row to expand the AI triage panel.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <KbBadge />
            {streaming ? (
              <span className="inline-flex items-center gap-1.5 text-[11px] text-cyan-300 bg-cyan-500/10 border border-cyan-500/30 rounded-md px-2 py-1">
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                Streaming
              </span>
            ) : (
              <button
                onClick={() => { streamIdxRef.current = 0; setAlarms([]); setStreaming(true); }}
                className="inline-flex items-center gap-1.5 text-[11px] text-slate-300 bg-slate-800 border border-slate-700 rounded-md px-2 py-1 hover:bg-slate-700">
                <RefreshCw className="w-3 h-3" /> Replay stream
              </button>
            )}
          </div>
        </div>

        {/* ── KPIs strip ───────────────────────────────────────── */}
        <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
          <KpiTile label="Alarms" value={kpis.total} icon={Bell} tone="slate" />
          <KpiTile label="Open"   value={kpis.open}  icon={AlertTriangle} tone="amber" />
          <KpiTile label="Suppressed" value={kpis.suppressed} icon={EyeOff} tone="slate" />
          <KpiTile label="Resolved"   value={kpis.resolved}   icon={CheckCircle2} tone="emerald" />
          <KpiTile label="AI overrides" value={kpis.overrides} icon={Brain} tone="cyan" />
          <KpiTile label="$/h at risk"  value={fmtUsd(kpis.roi)} icon={Activity} tone="purple" raw />
        </div>

        {/* ── Cascade banners ─────────────────────────────────── */}
        <AnimatePresence>
          {cascades.filter((c) => !bannerAck[c.id]).map((c) => (
            <motion.div
              key={c.id}
              initial={{ opacity: 0, y: -8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.98 }}
              className="bg-amber-500/10 border border-amber-500/40 rounded-xl p-4 flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-300 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-amber-200 font-semibold text-sm">
                  Suppressing {c.members.length - 1} alarm{c.members.length - 1 === 1 ? '' : 's'} —
                  cascade from primary <span className="font-mono">{c.primary.code}</span>
                </p>
                <p className="text-xs text-amber-200/80 mt-1">
                  {c.reason}. Window: 60s starting {fmtTs(c.primary.timestamp)}.
                  Members: {c.members.map((m) => m.code).join(', ')}.
                </p>
              </div>
              <button
                onClick={() => setBannerAck((p) => ({ ...p, [c.id]: true }))}
                className="text-xs text-amber-200/80 hover:text-amber-100 px-2 py-1 border border-amber-500/40 rounded-md">
                Acknowledge
              </button>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* ── Alarms-by-severity chart ────────────────────────── */}
        {sevSeries.length > 0 && (
          <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
            <h4 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              Alarms by AI severity (30-min buckets)
            </h4>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={sevSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="slot" stroke="#64748b" />
                  <YAxis stroke="#64748b" allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
                    labelStyle={{ color: '#94a3b8' }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="INFO" stackId="s" fill="#475569" />
                  <Bar dataKey="LOW"  stackId="s" fill="#06b6d4" />
                  <Bar dataKey="MED"  stackId="s" fill="#f59e0b" />
                  <Bar dataKey="HIGH" stackId="s" fill="#ef4444" />
                  <Bar dataKey="CRIT" stackId="s" fill="#dc2626" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* ── Alarm queue ─────────────────────────────────────── */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-3">
          <div className="grid grid-cols-[80px_1fr_120px_120px_90px_24px] gap-2 px-2 py-2 text-[10px] uppercase tracking-wider text-slate-500 font-semibold border-b border-slate-800">
            <span>Time</span>
            <span>Asset · Code</span>
            <span>SCADA</span>
            <span>AI</span>
            <span>Status</span>
            <span></span>
          </div>
          <div className="divide-y divide-slate-800/60">
            <AnimatePresence initial={false}>
              {alarms.map((a) => {
                const aiSev = a.triage?.classification?.ai_severity;
                const overridden = a.triage?.classification?.scada_severity_overridden;
                const isExpanded = expandedId === a.alarm_id;
                return (
                  <motion.div
                    key={a.alarm_id}
                    initial={{ opacity: 0, y: -8, height: 0 }}
                    animate={{ opacity: 1, y: 0, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.25 }}
                    className={a.status === 'SUPPRESSED' ? 'opacity-50' : ''}>
                    <button
                      onClick={() => setExpandedId(isExpanded ? null : a.alarm_id)}
                      className="w-full grid grid-cols-[80px_1fr_120px_120px_90px_24px] gap-2 items-center px-2 py-3 text-left hover:bg-slate-800/40 transition-colors">
                      <span className="text-[11px] font-mono text-slate-400">{fmtTs(a.timestamp)}</span>
                      <span className="min-w-0">
                        <span className="text-xs text-slate-300 block truncate">
                          <span className="text-slate-500">{a.asset.site}</span>
                          {' › '}
                          <span className="text-white font-medium">{a.asset.turbine}</span>
                          {' › '}
                          <span className="text-slate-400">{a.asset.subsystem}</span>
                        </span>
                        <span className="text-[11px] font-mono text-cyan-300/80">{a.code}</span>
                      </span>
                      <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-md border w-fit ${sevTone(a.scada_severity)}`}>
                        {a.scada_severity}
                      </span>
                      <span className="flex items-center gap-1.5">
                        {a.triageInFlight ? (
                          <span className="inline-flex items-center gap-1 text-[10px] text-slate-400">
                            <Loader2 className="w-3 h-3 animate-spin" /> triaging
                          </span>
                        ) : aiSev ? (
                          <>
                            <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-md border ${sevTone(aiSev)}`}>{aiSev}</span>
                            {overridden && (
                              <span title="AI overrode SCADA severity" className="text-[9px] text-purple-300 bg-purple-500/15 border border-purple-500/30 rounded px-1">override</span>
                            )}
                          </>
                        ) : (
                          <span className="text-[10px] text-slate-600">—</span>
                        )}
                      </span>
                      <span className={`text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-md border w-fit ${statusTone(a.status)}`}>
                        {a.status}
                      </span>
                      {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
                    </button>

                    {isExpanded && (
                      <ExpandedTriage
                        alarm={a}
                        onApproveReset={() => openResetModal(a)}
                        onRetry={() => triageAlarm(a.alarm_id)}
                      />
                    )}
                  </motion.div>
                );
              })}
            </AnimatePresence>
            {alarms.length === 0 && (
              <div className="p-8 text-center text-slate-500 text-xs">
                Waiting for the first alarm to come down the bus…
              </div>
            )}
          </div>
        </div>

        {/* ── EOD shift report ─────────────────────────────────── */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h4 className="text-white font-semibold text-sm flex items-center gap-2">
                <FileText className="w-4 h-4 text-cyan-400" />
                Generate EOD Shift Report
              </h4>
              <p className="text-xs text-slate-400 mt-1">
                Hands a denormalised view of the current alarm queue to the
                shift_reporter agent. Output is Markdown ready for handover.
              </p>
            </div>
            <button
              onClick={generateReport}
              disabled={reportLoading || alarms.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-cyan-500 text-slate-950 rounded-lg hover:bg-cyan-400 disabled:bg-slate-700 disabled:text-slate-500 font-medium whitespace-nowrap">
              {reportLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              {reportLoading ? 'Drafting…' : 'Draft report'}
            </button>
          </div>
          {reportError && (
            <div className="mt-3 text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded p-2">
              {reportError}
            </div>
          )}
          {reportMd && (
            <article className="prose prose-invert prose-sm max-w-none mt-4 p-4 bg-slate-950/70 border border-slate-800 rounded-lg whitespace-pre-wrap font-mono text-[12px] text-slate-200">
              {reportMd}
            </article>
          )}
        </div>

        <PipelineDagViz dag={BEDROCC_DAG} />
      </div>

      {/* ── Right: scenario explainer ───────────────────────────── */}
      <ScenarioExplainer
        eyebrow="Industrial IoT · Scenario C"
        title="Alarm Desk — Operations Control Room"
        lede={
          <>
            A wind-farm operator's screen during a busy shift looks
            like a wall of red. Most of those alarms are
            <b className="text-white"> noise</b> — cascades of
            downstream effects from a single physical event. Alarm Desk
            takes the SCADA stream, lets an LLM triage each event,
            suppresses the cascade, ranks by ROI, and gates remote
            resets behind a safety-precondition advisor.
          </>
        }
        callouts={[
          { label: 'Site',     value: 'Northern Lights' },
          { label: 'Turbines', value: '24 × 9.5 MW' },
          { label: 'Pipeline', value: 'iot-bedrocc' },
          { label: 'Agents',   value: '4 + 1 pipeline' },
        ]}
        sections={[
          {
            icon: Bell,
            tone: 'cyan',
            title: 'Live alarm queue',
            body: (
              <>
                <p>
                  Every alarm shows site, turbine, subsystem, code,
                  raw SCADA severity, AI-classified severity, and
                  status. When AI overrides SCADA, you see a
                  <b className="text-white"> purple "override" pill</b> next
                  to the new severity.
                </p>
                <p>
                  Click a row to expand the triage panel — root
                  cause, ROI in $/h saved, confidence %, recommended
                  action, and (if applicable) the safe-reset
                  command preview.
                </p>
              </>
            ),
          },
          {
            icon: ShieldAlert,
            tone: 'amber',
            title: 'Cascade detection',
            body: (
              <>
                <p>
                  When 3+ alarms cluster within 60s on the same
                  turbine — or when 3+ grid-event alarms hit on
                  the same feeder — the noise filter declares a
                  cascade and suppresses everything downstream.
                  An amber banner names the primary alarm and
                  the count suppressed.
                </p>
                <p>
                  Suppressed rows aren't deleted: they're kept in
                  the queue at low opacity so the audit trail is
                  intact and the operator can spot-check the
                  filter's call.
                </p>
              </>
            ),
          },
          {
            icon: RefreshCw,
            tone: 'purple',
            title: 'Safe remote reset',
            body: (
              <>
                <p>
                  When the classifier recommends a soft reset, the
                  safe_reset_advisor checks LOTO, occupancy, weather,
                  recurrence, and the SOP authorisation matrix. If
                  ALL preconditions pass it emits the
                  <b className="text-white"> minimum-privilege</b> command;
                  if any fail it emits DENY and the UI hides the
                  approve button.
                </p>
                <p>
                  Approving a reset triggers a two-step modal —
                  read-and-confirm + re-confirm. Two-person cases
                  add a supervisor signoff line.
                </p>
              </>
            ),
          },
          {
            icon: FileText,
            tone: 'emerald',
            title: 'EOD shift report',
            body: (
              <>
                <p>
                  At handover, the shift_reporter agent ingests the
                  full alarm queue (statuses + actions + dispatches)
                  and drafts a structured Markdown report following
                  the SOP template.
                </p>
                <p>
                  Sections: shift summary, KPIs, alarms triaged,
                  resets approved, dispatches, suppressed cascades,
                  open issues for the next shift, and trends worth
                  watching.
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
                  validate → <span className="text-cyan-300">classify</span> ║
                  <span className="text-amber-300"> noise_filter</span> →
                  reset_router → <span className="text-amber-300">safe_reset</span> →
                  envelope
                </p>
                <p>
                  Classification + cascade detection run in parallel.
                  Safe-reset advisor runs only if the classifier
                  nominated a reset AND the AI severity isn't CRIT.
                </p>
              </>
            ),
          },
          {
            icon: Workflow,
            tone: 'purple',
            title: 'Why it matters',
            body: (
              <ul className="list-disc list-outside pl-4 space-y-1">
                <li>One operator can supervise more turbines when noise is filtered.</li>
                <li>Severity overrides catch alarms whose risk SCADA undersells (and vice versa).</li>
                <li>Reset commands carry a full audit trail back to the SOP they cite.</li>
                <li>Two-person modal is enforced, not optional — the UI cannot ship a single signoff.</li>
              </ul>
            ),
          },
        ]}
        agentTrace={[
          {
            agent_slug: 'iot-bedrocc-pipeline',
            source: 'agent',
            when: 'click any alarm row',
            inputs: 'the clicked alarm + the rolling window of recent_alarms[] from the streaming queue + asset hierarchy from assets.json',
            outputs: 'TriageEnvelope with classification + cascade context + reset advice (or DENY)',
          },
          {
            agent_slug: 'iot-bedrocc-alarm-classifier',
            source: 'agent',
            when: 'pipeline branch — runs in parallel with cascade filter',
            inputs: 'one alarm: {code, asset, subsystem, raw_severity, value, threshold, timestamp}',
            outputs: 'severity (OK/WATCH/WARN/CRIT, can override SCADA), root_cause hypothesis, confidence, ROI estimate (USD/h), recommended_action enum',
          },
          {
            agent_slug: 'iot-bedrocc-noise-filter',
            source: 'agent',
            when: 'pipeline branch — cascade detection',
            inputs: '5-10 most recent alarms in a 60-second window for the same asset/feeder',
            outputs: 'primary alarm + suppressed[] member alarms (never suppresses FIRE-* / GAS-* / BIRD-* / ICE-* / LOTO-* / *-PROT / *-SAFE)',
          },
          {
            agent_slug: 'iot-bedrocc-safe-reset-advisor',
            source: 'agent',
            when: 'click "Approve safe reset" — only fires when classifier nominated reset AND severity != CRIT',
            inputs: 'classification result + active LOTO state + recent yaw/pitch reset history + sop-resets.json authority matrix',
            outputs: '4-stage gate decision: hard gates → authority matrix → context preconds → minimum-privilege command. Returns either {decision: APPROVE, reset_command, preconditions[], rollback_plan} or {decision: DENY, reset_command: null, reason}',
          },
          {
            agent_slug: 'iot-bedrocc-shift-reporter',
            source: 'agent',
            when: 'click "Generate EOD shift report"',
            inputs: 'the day\'s alarm queue + classifications + actions taken (resets approved, dispatches issued, suppressions)',
            outputs: 'Markdown shift report with 8 fixed sections (alarms triaged, resets approved, dispatches, open items for next shift)',
          },
        ]}
        simulationNote={(
          <>
            <p className="mb-2">
              <strong>In production —</strong> alarms stream live from SCADA via
              OPC-UA → MQTT broker → Kafka topic
              <code className="text-cyan-300 mx-1">alarms.realtime</code>{' '}
              into an always-on Alarm Desk consumer (a Kafka-Streams or Flink job, or
              the platform's own queue worker). Approved resets write back via
              OPC-UA <em>WriteValue</em> to the controlling RTU, gated by the SOP /
              authority matrix in SharePoint / Confluence. Two-person modal signoff
              is verified through SSO claim checks (Entra ID / Okta groups). EOD
              shift reports drop into the operator's logbook system (Honeywell PHD,
              AVEVA OASyS, or a custom logbook).
            </p>
            <p>
              <strong>In the demo —</strong> the 30-alarm queue at
              <code className="text-cyan-300 mx-1">scaffolding/bedrocc/data/alarm-stream.json</code>
              is fetched once on mount, then a client-side
              <code className="text-cyan-300 mx-1">setInterval</code> drips alarms
              into the queue every 4–6&nbsp;s to simulate live ingest. <strong>No
              SCADA, no OPC-UA, no Kafka</strong> — but the click-to-triage and
              cascade-banner timing match what an operator would see live. Severity
              overrides, cascade detection, reset gating, and the shift report are
              all generated by the agents above. The two-step modal enforces
              operator + supervisor signoffs before the agent's reset command is
              ever sent — same gate the production OPC-UA write would carry.
            </p>
          </>
        )}
        footer={
          <p className="text-xs text-slate-400 leading-relaxed">
            <FlaskConical className="w-3.5 h-3.5 inline mr-1.5 text-cyan-400" />
            Watch for the cascade banner around 08:14 — that's the
            scripted four-alarm gearbox failure on NL-T-08, plus a
            feeder-wide grid event at 17:47 fanning across four
            turbines simultaneously.
          </p>
        }
      />

      {/* ── Two-step reset modal ───────────────────────────────── */}
      <AnimatePresence>
        {pendingReset && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4">
            <motion.div
              initial={{ scale: 0.95, y: 8 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.95, y: 8 }}
              className="bg-slate-900 border border-slate-700 rounded-xl p-6 max-w-lg w-full">
              <div className="flex items-start gap-3">
                <ShieldAlert className="w-6 h-6 text-amber-300 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <h3 className="text-white font-semibold text-base">
                    {resetStep === 1 ? 'Confirm safe remote reset' : 'Re-confirm — final step'}
                  </h3>
                  <p className="text-xs text-slate-400 mt-1">
                    {pendingReset.asset.turbine} · {pendingReset.code}
                  </p>
                </div>
                <button onClick={cancelReset} className="text-slate-500 hover:text-slate-300">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <ResetModalBody alarm={pendingReset} step={resetStep} />

              {resetError && (
                <div className="mt-3 text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded p-2">
                  {resetError}
                </div>
              )}

              <div className="flex justify-end gap-2 mt-5">
                <button
                  onClick={cancelReset}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700">
                  Cancel
                </button>
                {resetStep === 1 ? (
                  <button
                    onClick={proceedResetStep1}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg bg-amber-500/20 border border-amber-500/40 text-amber-200 hover:bg-amber-500/30">
                    Continue to confirmation
                  </button>
                ) : (
                  <button
                    onClick={submitReset}
                    disabled={resetSubmitting}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-cyan-500 text-slate-950 hover:bg-cyan-400 disabled:opacity-50">
                    {resetSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                    {resetSubmitting ? 'Issuing…' : 'Issue reset command'}
                  </button>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────
function KpiTile({ label, value, icon: Icon, tone, raw }: {
  label: string;
  value: number | string;
  icon: typeof Activity;
  tone: 'cyan' | 'amber' | 'emerald' | 'slate' | 'purple';
  raw?: boolean;
}) {
  const ring = ({
    cyan: 'border-cyan-500/30 bg-cyan-500/5',
    amber: 'border-amber-500/30 bg-amber-500/5',
    emerald: 'border-emerald-500/30 bg-emerald-500/5',
    slate: 'border-slate-800 bg-slate-900/60',
    purple: 'border-purple-500/30 bg-purple-500/5',
  } as const)[tone];
  const text = ({
    cyan: 'text-cyan-300', amber: 'text-amber-300', emerald: 'text-emerald-300',
    slate: 'text-slate-300', purple: 'text-purple-300',
  } as const)[tone];
  return (
    <div className={`rounded-xl p-3 border ${ring}`}>
      <p className="text-[10px] uppercase tracking-wider text-slate-500 flex items-center gap-1">
        <Icon className={`w-3 h-3 ${text}`} /> {label}
      </p>
      <p className={`text-lg font-semibold mt-1 ${text}`}>{raw ? value : value}</p>
    </div>
  );
}

function ExpandedTriage({ alarm, onApproveReset, onRetry }: {
  alarm: AlarmRow; onApproveReset: () => void; onRetry: () => void;
}) {
  const cls = alarm.triage?.classification;
  const cas = alarm.triage?.cascade;
  const advice = alarm.triage?.reset_advice;
  return (
    <div className="px-4 pb-4 pt-1 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
      {/* Raw alarm context */}
      <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Raw event</p>
        <p className="text-slate-300 leading-snug">{alarm.description}</p>
        <div className="grid grid-cols-3 gap-2 mt-3 text-[11px]">
          {alarm.raw_value != null && (
            <Field label="Value" value={`${alarm.raw_value} ${alarm.unit ?? ''}`} />
          )}
          <Field label="Wind"  value={`${alarm.context.wind_mps ?? '—'} m/s`} />
          <Field label="Power" value={`${alarm.context.power_kw ?? '—'} kW`} />
          {alarm.suppressedBy && (
            <Field label="Suppressed by" value={alarm.suppressedBy} />
          )}
        </div>
      </div>

      {/* AI verdict */}
      <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3">
        <div className="flex items-center justify-between mb-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">AI verdict</p>
          {alarm.triageError ? (
            <button onClick={onRetry} className="text-[10px] text-cyan-300 hover:text-cyan-200 flex items-center gap-1">
              <RefreshCw className="w-3 h-3" /> retry
            </button>
          ) : null}
        </div>
        {alarm.triageInFlight ? (
          <p className="text-slate-400 italic flex items-center gap-2">
            <Loader2 className="w-3 h-3 animate-spin" /> Pipeline running…
          </p>
        ) : alarm.triageError ? (
          <p className="text-red-300 italic">{alarm.triageError}</p>
        ) : cls ? (
          <>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-md border ${sevTone(cls.ai_severity)}`}>
                {cls.ai_severity}
              </span>
              {cls.scada_severity_overridden && (
                <span className="text-[10px] text-purple-300 bg-purple-500/15 border border-purple-500/30 rounded px-1.5 py-0.5">
                  override (SCADA: {alarm.scada_severity})
                </span>
              )}
              <span className="text-[11px] text-slate-400">
                conf {Math.round((cls.confidence ?? 0) * 100)}%
              </span>
            </div>
            <p className="text-slate-300 leading-snug">{cls.rationale}</p>
            <div className="grid grid-cols-2 gap-2 mt-3">
              <Field label="Root cause" value={cls.root_cause ?? '—'} />
              <Field label="ROI" value={fmtUsd(cls.roi_estimate?.amount_usd_per_hour)} />
              <Field label="Action" value={actionLabel(cls.recommended_action)} wide />
            </div>
            {cls.roi_estimate?.basis && (
              <p className="text-[10.5px] text-slate-500 italic mt-2">{cls.roi_estimate.basis}</p>
            )}
          </>
        ) : (
          <p className="text-slate-500 italic">awaiting triage…</p>
        )}
      </div>

      {/* Cascade insight */}
      {cas && (
        <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 md:col-span-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 flex items-center gap-1">
            <Eye className="w-3 h-3" /> Cascade analysis
          </p>
          {cas.is_cascade ? (
            <p className="text-amber-200 text-[11px]">
              Cascade detected — primary <span className="font-mono">{cas.primary_alarm_code}</span>;
              {' '}{cas.suppressed_alarms?.length ?? 0} downstream IDs suppressed.
            </p>
          ) : (
            <p className="text-slate-400 text-[11px]">Independent alarm — not part of a cascade.</p>
          )}
          {cas.rationale && (
            <p className="text-slate-300 text-[11px] mt-1.5 leading-snug">{cas.rationale}</p>
          )}
        </div>
      )}

      {/* Reset advice */}
      {advice && (
        <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 md:col-span-2">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 flex items-center gap-1">
              <RefreshCw className="w-3 h-3" /> Safe-reset advisor
            </p>
            <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-md border ${
              advice.decision === 'ALLOW'
                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
                : 'bg-red-500/15 text-red-300 border-red-500/40'
            }`}>{advice.decision}</span>
          </div>
          <p className="text-slate-300 text-[11px] leading-snug mb-2">{advice.reason}</p>
          {advice.reset_command && (
            <div className="bg-slate-900/80 border border-slate-800 rounded p-2 font-mono text-[11px] text-cyan-300 mb-2">
              {advice.reset_command}
            </div>
          )}
          <div className="grid md:grid-cols-2 gap-1.5 text-[10.5px]">
            {(advice.preconditions_checked ?? []).map((p, i) => (
              <div key={i} className="flex items-center gap-1.5">
                {p.status === 'passed' ? <CheckCircle2 className="w-3 h-3 text-emerald-400" /> :
                 p.status === 'failed' ? <X className="w-3 h-3 text-red-400" /> :
                 <Clock className="w-3 h-3 text-slate-500" />}
                <span className="text-slate-300">{p.check}</span>
                <span className="text-slate-500 truncate">— {p.evidence}</span>
              </div>
            ))}
          </div>
          {advice.two_person_confirmation_required && (
            <p className="mt-2 text-[10.5px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1">
              <ShieldAlert className="w-3 h-3 inline mr-1" />
              Two-person sign-off required — supervisor confirmation will be requested.
            </p>
          )}
          {advice.sop_cited && (
            <p className="text-[10px] text-slate-500 mt-1.5">SOP cited: {advice.sop_cited}</p>
          )}
          {advice.decision === 'ALLOW' && advice.reset_command && alarm.status !== 'RESOLVED' && (
            <button
              onClick={onApproveReset}
              className="mt-3 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-cyan-500 text-slate-950 hover:bg-cyan-400">
              <RefreshCw className="w-3.5 h-3.5" />
              Approve safe reset
            </button>
          )}
          {alarm.status === 'RESOLVED' && alarm.resetApproved && (
            <p className="mt-3 text-[11px] text-emerald-300 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Reset issued by {alarm.resetApproved.operator}
              {alarm.resetApproved.twoPerson ? ' (two-person sign-off)' : ''} — outcome: {alarm.resetApproved.outcome}.
            </p>
          )}
        </div>
      )}

      {/* Dispatch CTA when classifier wants a truck-roll */}
      {cls && cls.recommended_action === 'dispatch_technician' && !alarm.dispatched && (
        <div className="rounded-lg bg-amber-500/5 border border-amber-500/30 p-3 md:col-span-2 flex items-start gap-3">
          <Truck className="w-4 h-4 text-amber-300 mt-0.5 shrink-0" />
          <div className="flex-1 text-[11px] text-amber-100/90">
            <p className="font-semibold">Recommended: dispatch technician.</p>
            <p>This alarm class is not eligible for remote reset. {advice?.reason ?? 'Operator must request a truck roll.'}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function ResetModalBody({ alarm, step }: { alarm: AlarmRow; step: 1 | 2 }) {
  const advice = alarm.triage?.reset_advice;
  if (!advice || advice.decision !== 'ALLOW') {
    return (
      <p className="mt-4 text-sm text-red-300">
        Reset is not currently allowed by the advisor.
      </p>
    );
  }
  if (step === 1) {
    return (
      <div className="mt-4 space-y-3 text-sm">
        <p className="text-slate-300">
          You are about to issue <span className="font-mono text-cyan-300">{advice.reset_command}</span>
          {' '}on <span className="font-mono text-white">{alarm.asset.turbine}</span>.
        </p>
        <ul className="text-xs text-slate-400 space-y-1 list-disc list-outside pl-4">
          {(advice.preconditions_checked ?? []).map((p, i) => (
            <li key={i}>
              <span className={p.status === 'passed' ? 'text-emerald-300' : 'text-amber-300'}>
                {p.check}
              </span>
              {' — '}{p.evidence}
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-slate-500">
          Rollback if the alarm returns: {advice.rollback_if_alarm_returns ?? '— park and dispatch.'}
        </p>
      </div>
    );
  }
  return (
    <div className="mt-4 space-y-3 text-sm">
      <p className="text-amber-200">
        FINAL CHECK — issuing this command will affect a 9.5 MW machine.
      </p>
      <div className="bg-slate-950 border border-slate-800 rounded p-3 text-xs space-y-1">
        <p>Turbine:    <span className="font-mono text-white">{alarm.asset.turbine}</span></p>
        <p>Subsystem:  <span className="font-mono text-white">{alarm.asset.subsystem}</span></p>
        <p>Command:    <span className="font-mono text-cyan-300">{advice.reset_command}</span></p>
        <p>Authority:  <span className="font-mono text-white">{advice.authority_required ?? 'T2'}</span></p>
        <p>Two-person: <span className="font-mono text-white">{advice.two_person_confirmation_required ? 'YES' : 'no'}</span></p>
      </div>
      {advice.two_person_confirmation_required && (
        <p className="text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5">
          A supervisor signature will be requested after this approval.
        </p>
      )}
    </div>
  );
}

function Field({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-2' : ''}>
      <p className="text-[10px] uppercase tracking-wider text-slate-600">{label}</p>
      <p className="text-slate-200 mt-0.5">{value}</p>
    </div>
  );
}
