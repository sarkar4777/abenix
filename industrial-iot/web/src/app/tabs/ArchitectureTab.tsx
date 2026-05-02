'use client';

import { Box, Cpu, Database, GitBranch, HardDrive, Server } from 'lucide-react';

// Abenix's main UI lives on a different origin in cluster (e.g.
// http://20.72.73.141.nip.io). Falling back to localhost:3000 keeps dev
// links working. Build with NEXT_PUBLIC_ABENIX_WEB_URL set.
const ABENIX_WEB =
  (process.env.NEXT_PUBLIC_ABENIX_WEB_URL || 'http://localhost:3000').replace(/\/$/, '');

export default function ArchitectureTab() {
  return (
    <div className="space-y-6">
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-white mb-2">How the Industrial IoT showcase fits together</h2>
        <p className="text-sm text-slate-400">
          Both scenarios ride the exact same production chassis — the only
          difference is which Go program gets uploaded, which pipeline gets
          called, and what the downstream LLM is reasoning about. Nothing in
          the request path is scenario-specific.
        </p>
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
