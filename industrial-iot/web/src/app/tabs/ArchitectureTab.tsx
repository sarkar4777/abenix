'use client';

import { Box, Cpu, Database, GitBranch, HardDrive, Server, Wind, Wrench, ShieldAlert, Activity, Thermometer, BookOpen } from 'lucide-react';

// Abenix's main UI lives on a different origin in cluster (e.g.
// http://20.72.73.141.nip.io). Falling back to localhost:3000 keeps dev
// links working. Build with NEXT_PUBLIC_ABENIX_WEB_URL set.
const ABENIX_WEB =
  (process.env.NEXT_PUBLIC_ABENIX_WEB_URL || 'http://localhost:3000').replace(/\/$/, '');

export default function ArchitectureTab() {
  return (
    <div className="space-y-6">
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-white mb-2">Industrial-IoT — Help &amp; UAT Guide</h2>
        <p className="text-sm text-slate-400">
          Five end-to-end industrial scenarios all riding the same production chassis — the only
          difference is which sandboxed code gets uploaded, which pipeline gets called, and what
          the LLM is reasoning about. This page walks the operator through every tab + how to
          run a UAT pass against each.
        </p>
      </div>

      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-3">
          <BookOpen className="w-4 h-4 text-cyan-400" />
          <h3 className="text-white font-semibold text-sm">Scenario tour</h3>
        </div>
        <div className="grid md:grid-cols-2 gap-3">
          <ScenarioCard
            icon={Activity}
            name="Pump Vibration"
            tagline="Predictive maintenance on rotating machinery"
            steps={[
              'Click "Deploy DSP" — uploads the Go FFT analyser to a k8s sandbox.',
              'Click "Deploy RUL" — uploads the Python remaining-useful-life regressor.',
              'Click "Stream 10 windows" — synthetic vibration data fans through the pipeline.',
              'Inspect each window\'s severity (OK / WATCH / WARN / CRITICAL) + root cause.',
            ]}
            pipeline="iot-pump-pipeline"
          />
          <ScenarioCard
            icon={Thermometer}
            name="Cold Chain"
            tagline="Reefer-container FSMA excursion monitoring"
            steps={[
              'Click "Deploy excursion corrector" — Python time-series patcher.',
              'Click "Stream 20 waypoints" — synthetic SFO→LAX run with 2 excursions.',
              'Watch the adjudicator agent classify partial-loss vs total-loss.',
              'Final output is a draft FSMA claim with regulator-ready narrative.',
            ]}
            pipeline="iot-coldchain-pipeline"
          />
          <ScenarioCard
            icon={Wind}
            name="Design Studio"
            tagline="Engineering & EPC copilot — site brief → 3 ranked designs"
            steps={[
              'Pick a site template (Dogger Bank / North Sea / US East Coast) or fill the form.',
              'Click "Generate scenarios" — pipeline ranks 3 designs against IEC 61400-3, NEC 690, IEEE 1547.',
              'Drill into a card to see VE opportunities (CapEx vs CO₂ vs risk) + compliance findings.',
              'Open any blocker finding to see its pre-drafted RFI ready for the EPC.',
            ]}
            pipeline="iot-valueedge-pipeline"
          />
          <ScenarioCard
            icon={Wrench}
            name="Field Guide"
            tagline="Wind-farm maintenance copilot + scheduler"
            steps={[
              'Pick a turbine (TURB-01 through TURB-12) or scan the QR mock.',
              'Type or dictate the issue ("blade leading-edge erosion") — hit "Get Repair Procedure".',
              'Read the cited OEM manual sections, similar past WOs + safety gate.',
              'Use the "Voice close-out" panel to convert the WO into structured fields, then re-optimise the schedule.',
            ]}
            pipeline="iot-fieldedge-pipeline"
          />
          <ScenarioCard
            icon={ShieldAlert}
            name="Alarm Desk"
            tagline="Operations control-room alarm triage"
            steps={[
              'Watch alarms stream into the queue (synthetic 30-alarm replay).',
              'Click any alarm to triage — see severity override, root-cause hypothesis, ROI estimate.',
              'When a cascade fires, the banner suppresses correlated alarms while preserving safety codes.',
              'Approve a safe remote reset via the two-step modal, or Generate the EOD shift report.',
            ]}
            pipeline="iot-bedrocc-pipeline"
          />
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <Stage
          icon={Box}
          step="1"
          title="Browser"
          body={
            <>
              The user clicks <b>Deploy</b> — the browser fetches a bundled
              zip from <code className="text-cyan-300">/industrial-iot/&lt;slug&gt;.zip</code>,
              POSTs it multipart to <code className="text-cyan-300">/api/code-assets</code>.
            </>
          }
        />
        <Stage
          icon={Server}
          step="2"
          title="API"
          body={
            <>
              Analyzer detects Go/Python, picks an image (<code>golang:1.22-alpine</code>,
              <code>python:3.12-slim</code>), infers <code>input_schema</code> from the
              declared <code>abenix.yaml</code>, then kicks off a background
              smoke-test probe that runs the program with the bundled example
              — producing the final <code>output_schema</code> without author
              intervention.
            </>
          }
        />
        <Stage
          icon={Cpu}
          step="3"
          title="Sandbox (k8s Job)"
          body={
            <>
              Each pipeline run calls the <code>code_asset</code> tool, which
              spawns a one-shot k8s Job with the asset zip delivered via
              stdin — no image push, no credentials, no network. Locally this
              runs on <b>minikube</b>; on AKS the same path runs on the
              <b>abenix</b> namespace.
            </>
          }
        />
        <Stage
          icon={GitBranch}
          step="4"
          title="Pipeline"
          body={
            <>
              Seeded pipelines (<code>iot-pump-pipeline</code>,
              <code>iot-coldchain-pipeline</code>) chain deterministic Go/Python
              steps with LLM reasoning steps. Severity routing decides when to
              invoke maintenance planning or claim drafting.
            </>
          }
        />
        <Stage
          icon={HardDrive}
          step="5"
          title="LLM"
          body={
            <>
              Claude Sonnet (primary) + Gemini 2.0 Flash (fallback). Schema
              injection hides internal ids from the LLM and inlines the asset's
              real input_schema, so prompts stay faithful to the uploaded code.
            </>
          }
        />
        <Stage
          icon={Database}
          step="6"
          title="Persistence"
          body={
            <>
              Pipeline writes rows to <code>af_pump_readings</code> +
              <code>af_work_orders</code> or <code>af_coldchain_events</code>
              via the <code>database_writer</code> tool. All executions are
              visible under <a href={`${ABENIX_WEB}/executions`} target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline">/executions</a>.
            </>
          }
        />
      </div>

      <div className="bg-orange-950/20 border border-orange-900/40 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-3">
          <Cpu className="w-4 h-4 text-orange-300" />
          <h3 className="text-white font-semibold text-sm">Edge runtimes — on the floor, not in the cloud</h3>
        </div>
        <p className="text-sm text-slate-400 mb-3">
          Agents flagged <code className="text-orange-200">edge_compatible:&nbsp;true</code> compile to a signed{' '}
          <code className="text-orange-200">.agent</code> bundle (RSA-PSS over a deterministic tar) and ship to a runtime
          pod sitting next to the equipment. Three variants — same bundle, same MQTT delivery topic,
          same HTTP contract — pick the one that matches plant hardware:
        </p>
        <div className="grid md:grid-cols-3 gap-3 mb-4">
          <div className="rounded-lg border border-cyan-800/40 bg-cyan-950/20 p-3">
            <div className="text-cyan-300 text-xs font-semibold mb-1">Python · 80 MB</div>
            <div className="text-slate-400 text-[12.5px]">x86_64 / arm64. Default — best LLM SDK ergonomics, easiest to extend.</div>
          </div>
          <div className="rounded-lg border border-orange-800/40 bg-orange-950/20 p-3">
            <div className="text-orange-300 text-xs font-semibold mb-1">Rust · 25 MB</div>
            <div className="text-slate-400 text-[12.5px]">x86_64 / arm64 / armv7. Rugged industrial PCs — Moxa UC-8580, Siemens RUGGEDCOM, Beckhoff CX, NVIDIA Jetson.</div>
          </div>
          <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
            <div className="text-slate-300 text-xs font-semibold mb-1">C · 12 MB</div>
            <div className="text-slate-400 text-[12.5px]">armv7 / arm64 / x86_64. Phoenix Contact PLCnext, Allen-Bradley CompactLogix, OpenWRT routers.</div>
          </div>
        </div>
        <p className="text-sm text-slate-400 mb-2">
          <b className="text-white">How a gateway gets created:</b> mint an <code>af_…</code> API key (scopes <code>edge:register, agents:execute</code>),
          then{' '}
          <code className="text-cyan-300">helm install abenix-edge ./infra/helm/edge-runtime --set platform.token=$AF</code>{' '}
          (or <code>edge-runtime-rust</code> / <code>edge-runtime-c</code>). The pod registers with the platform
          every 60 s and shows up in <a href={`${ABENIX_WEB}/edge`} target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline">/edge</a>.
        </p>
        <p className="text-sm text-slate-400 mb-2">
          <b className="text-white">How interactions work:</b> bundle delivery via MQTT topic{' '}
          <code className="text-orange-200">edge.{'{gateway_id}'}.deploy</code> (HTTP POST fallback);
          sync execute via <code>POST {'{gateway_url}'}/agents/{'{slug}'}/execute</code>; async via MQTT topic{' '}
          <code className="text-orange-200">agents.{'{slug}'}.input</code>. Tool budget on edge:{' '}
          <code>mqtt_publish, mqtt_subscribe, current_time, windowed_state, connector_call, code_executor</code>.
        </p>
        <p className="text-sm text-slate-400">
          <b className="text-white">Wired into Pump Vibration:</b> the <code className="text-orange-200">iot-pump-edge-classifier</code>{' '}
          agent (Haiku-4-5 + <code>code_executor</code> + <code>mqtt_publish</code>) ships to a Rust gateway,
          runs FFT + RMS through the embedded Python interpreter, and returns a severity verdict in single-digit
          milliseconds. See the <b>Run on the edge</b> section in the Pump Vibration tab for the live demo.
        </p>
      </div>

      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
        <h3 className="text-white font-semibold text-sm mb-3">What's novel here?</h3>
        <ul className="text-sm text-slate-400 space-y-2 list-disc list-inside">
          <li>
            <b className="text-white">Bring-your-own-code, in production.</b> The Go DSP isn't a
            stub — it does the FFT, windows, fault-specific scoring, and
            ISO 10816 zone mapping. The Python RUL estimator does exponential
            degradation fitting with a linear fallback. Both compile and run
            inside sandboxed k8s Jobs the user can inspect under
            <a href={`${ABENIX_WEB}/code-runner`} target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline ml-1">Code Runner</a>.
          </li>
          <li>
            <b className="text-white">Two fundamentally different industrial problems, one platform.</b>
            Predictive-maintenance on rotating machinery and FSMA cold-chain
            monitoring share zero domain logic but share 100% of the orchestration
            substrate — agents, tools, sandboxing, knowledge search, pipelines,
            observability.
          </li>
          <li>
            <b className="text-white">LLM doing LLM-appropriate work.</b> Deterministic
            number-crunching stays in Go; pattern interpretation
            (bearing vs. imbalance signatures, FSMA liability attribution) is
            where the model earns its cost.
          </li>
        </ul>
      </div>
    </div>
  );
}

function ScenarioCard({
  icon: Icon, name, tagline, steps, pipeline,
}: {
  icon: typeof Box;
  name: string;
  tagline: string;
  steps: string[];
  pipeline: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 text-cyan-400" />
        <h4 className="text-white font-semibold text-sm">{name}</h4>
      </div>
      <p className="text-xs text-slate-400 mb-3">{tagline}</p>
      <ol className="text-[12px] text-slate-300 space-y-1 list-decimal list-outside pl-5">
        {steps.map((s, i) => <li key={i}>{s}</li>)}
      </ol>
      <p className="text-[10px] text-slate-500 mt-3 font-mono">pipeline: {pipeline}</p>
    </div>
  );
}

function Stage({
  icon: Icon, step, title, body,
}: {
  icon: typeof Box;
  step: string;
  title: string;
  body: React.ReactNode;
}) {
  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded-full">
          Stage {step}
        </span>
        <Icon className="w-4 h-4 text-cyan-400 ml-auto" />
      </div>
      <h4 className="text-white font-semibold text-sm mb-2">{title}</h4>
      <p className="text-xs text-slate-400 leading-relaxed">{body}</p>
    </div>
  );
}
