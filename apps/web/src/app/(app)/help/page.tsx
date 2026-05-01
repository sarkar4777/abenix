'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowRight, BarChart3, BookOpen, Bot, Brain,
  Camera, Check, ChevronRight, Code2, Compass, Cpu, Database,
  DollarSign, Eye, FileJson, FileText, Gauge, GitBranch, Globe,
  HelpCircle, Key, Layers, Library, Link2, Network, Plug, Radio, Route,
  ScanLine, Search, Settings, Shield, ShieldCheck, Sparkles, Store,
  Terminal, Upload, UserCircle2, Users, Wand2, Workflow, Wrench, Zap,
} from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────────

interface Topic {
  id: string;
  title: string;
  icon?: React.ReactNode;
  badge?: string;
  body: React.ReactNode;
}
interface Category {
  id: string;
  label: string;
  blurb?: string;
  topics: Topic[];
}

// ─── Reusable building blocks ────────────────────────────────────────

function Hero({ src, alt, caption }: { src: string; alt: string; caption?: string }) {
  return (
    <figure className="rounded-xl overflow-hidden border border-slate-700/60 bg-slate-950/40 my-3 shadow-lg">
      <img src={src} alt={alt} className="w-full block" />
      {caption && (
        <figcaption className="px-3 py-2 text-[11px] text-slate-500 italic border-t border-slate-800/60">{caption}</figcaption>
      )}
    </figure>
  );
}
function Pill({ tone = 'violet', children }: { tone?: 'violet' | 'cyan' | 'emerald' | 'amber' | 'rose' | 'slate'; children: React.ReactNode }) {
  const m: Record<string, string> = {
    violet: 'bg-violet-500/15 text-violet-200 border-violet-500/40',
    cyan: 'bg-cyan-500/15 text-cyan-200 border-cyan-500/40',
    emerald: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/40',
    amber: 'bg-amber-500/15 text-amber-200 border-amber-500/40',
    rose: 'bg-rose-500/15 text-rose-200 border-rose-500/40',
    slate: 'bg-slate-700/40 text-slate-300 border-slate-600/50',
  };
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded border ${m[tone]}`}>{children}</span>;
}
function Steps({ items }: { items: string[] }) {
  return (
    <ol className="space-y-2 mt-3">
      {items.map((s, i) => (
        <li key={i} className="flex items-start gap-3">
          <span className="shrink-0 w-6 h-6 rounded-full bg-gradient-to-br from-violet-500/30 to-cyan-500/30 border border-violet-500/40 text-violet-200 text-[11px] font-bold inline-flex items-center justify-center">{i + 1}</span>
          <span className="text-sm text-slate-300 leading-relaxed flex-1" dangerouslySetInnerHTML={{ __html: s }} />
        </li>
      ))}
    </ol>
  );
}
function Callout({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'success'; children: React.ReactNode }) {
  const m: Record<string, string> = {
    info: 'border-violet-500/40 bg-violet-500/5 text-violet-100',
    warn: 'border-amber-500/40 bg-amber-500/5 text-amber-100',
    success: 'border-emerald-500/40 bg-emerald-500/5 text-emerald-100',
  };
  return <div className={`rounded-lg border ${m[tone]} p-3 my-3 text-[13px] leading-relaxed`}>{children}</div>;
}
function FeatureCard({
  title, body, href, icon: Icon, accent = 'violet',
}: { title: string; body: string; href?: string; icon: any; accent?: 'violet' | 'cyan' | 'emerald' | 'amber' }) {
  const tone: Record<string, string> = {
    violet: 'border-violet-500/30 hover:border-violet-500/50',
    cyan: 'border-cyan-500/30 hover:border-cyan-500/50',
    emerald: 'border-emerald-500/30 hover:border-emerald-500/50',
    amber: 'border-amber-500/30 hover:border-amber-500/50',
  };
  return (
    <div className={`rounded-xl border ${tone[accent]} bg-slate-900/40 p-3 transition-colors`}>
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-4 h-4 text-violet-300" />
        <p className="text-sm font-semibold text-white">{title}</p>
      </div>
      <p className="text-[12px] text-slate-400 leading-relaxed">{body}</p>
    </div>
  );
}

const SS = (n: string) => `/docs-screenshots/${n}`;

// ─── Categories + topics ─────────────────────────────────────────────

const categories: Category[] = [
  // GETTING STARTED
  {
    id: 'getting-started',
    label: 'Getting started',
    blurb: 'Read these first. Five minutes to a full mental model.',
    topics: [
      {
        id: 'welcome',
        title: 'Welcome',
        icon: <BookOpen className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Abenix is the open-source platform for building AI agents that <em>think in graphs</em>. You drop in your domain knowledge as documents, ontologies, or live data; Abenix turns it into a typed graph; agents traverse the graph to answer questions, run pipelines, or act on schedules.</p>
            <p>Three things make Abenix different from every other agent platform:</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <FeatureCard icon={Network} accent="violet" title="Atlas — ontology + KB canvas" body="Documents and concepts share one canvas. Drop a PDF, type a sentence, draw a relationship. Agents query the graph, not raw vectors." />
              <FeatureCard icon={Brain} accent="cyan" title="Knowledge Engine" body="Graph-aware retrieval. Token cost drops 5–10× because agents read curated evidence, not noisy near-neighbours." />
              <FeatureCard icon={Workflow} accent="emerald" title="Pipelines + 100+ tools" body="Visual builder for multi-agent DAGs. Switch nodes, loops, sandboxed code, MCP integrations." />
            </div>
            <Hero src={SS('01-dashboard.png')} alt="Abenix dashboard" caption="Dashboard — live agents, executions, cost, observability" />
          </div>
        ),
      },
      {
        id: 'tour',
        title: 'A 60-second tour',
        icon: <Sparkles className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>This entire page is structured as a left sidebar (categories) and a content pane (this column). Pick any topic to jump.</p>
            <p>If you&apos;re new, the recommended path:</p>
            <Steps items={[
              'Read the <strong>Knowledge Bases</strong> section so you understand how documents become a typed graph.',
              'Read <strong>Atlas</strong> — the unique differentiator.',
              'Read <strong>Agent Builder</strong> + <strong>Pipelines</strong>.',
              'Read <strong>Triggers</strong> + <strong>Executions</strong> to put the agent into production.',
              'Read the <strong>Scaling Out</strong> mega-section before you put it in front of customers.',
            ]} />
          </div>
        ),
      },
      {
        id: 'first-run',
        title: 'First run, locally',
        icon: <Terminal className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>If you&apos;re reading this in a deployed instance, the platform is already up. To run it yourself:</p>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`git clone https://github.com/sarkar4777/abenix.git
cd abenix
bash scripts/dev-local.sh`}</pre>
            <p>Boots Postgres, Redis, the API, the web app, and an agent runtime locally. Sign in with the seeded admin (<code className="text-cyan-300">admin@abenix.dev / Admin123456</code>).</p>
            <p>For Kubernetes-shape on your laptop:</p>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`bash scripts/deploy.sh local           # minikube + helm
bash scripts/deploy-azure.sh all       # AKS + ACR + helm`}</pre>
          </div>
        ),
      },
    ],
  },
  // CORE FEATURES — pinned
  {
    id: 'pinned',
    label: 'Pinned',
    blurb: 'The pages your operators live in.',
    topics: [
      {
        id: 'dashboard',
        title: 'Dashboard',
        icon: <Layers className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The Dashboard is the operator&apos;s home. Total agents, active right now, today&apos;s executions, today&apos;s failures, cost trend, and the recent-executions feed.</p>
            <Hero src={SS('01-dashboard.png')} alt="Dashboard" />
            <p><strong className="text-white">Common tasks:</strong></p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Pin an agent to the home for quick re-run.</li>
              <li>Click a failure to jump straight to the execution detail.</li>
              <li>Use the cost chart to spot a runaway agent (cost spike on the last hour with no matching execution count = an agent stuck in a retry loop).</li>
            </ul>
          </div>
        ),
      },
      {
        id: 'my-agents',
        title: 'My Agents',
        icon: <Bot className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Every agent owned by you or shared with you. Filter by category, tag, or status. Click one to open its detail page (system prompt, tools, KBs, executions, sharing).</p>
            <Hero src={SS('10-my-agents.png')} alt="My Agents" />
            <Steps items={[
              'Click <strong>+ New agent</strong> to open the Agent Builder.',
              'Use the <strong>filter chips</strong> to narrow by category — onboarding, finance, compliance, ops, custom.',
              'Click an agent to see its full config; click <strong>Run</strong> to fire a one-shot, or <strong>Chat</strong> to open a thread.',
              'Use <strong>Share</strong> to grant access to teammates with read or edit scope.',
            ]} />
          </div>
        ),
      },
      {
        id: 'ai-chat',
        title: 'AI Chat',
        icon: <Sparkles className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The general-purpose chat surface. Pick an agent, attach files, tools, and KBs, then converse. The chat sidebar is namespaced per app (your standalone apps each have their own threads).</p>
            <Hero src={SS('11-ai-chat.png')} alt="AI Chat" />
            <Hero src={SS('detail-tool-call.png')} alt="Tool call expansion" caption="Expand any tool call to see its arguments and result" />
            <p><strong className="text-white">Power moves:</strong></p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Press <kbd className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[11px] font-mono">↑</kbd> to recall the last user message and edit it.</li>
              <li>Drop any file in any modality (PDF, image, audio, video, DOCX, text) into the input — the agent receives it through the multimodal pipeline.</li>
              <li>Click any tool call card to expand its arguments + result inline.</li>
              <li>Use <code className="text-cyan-300">/agent slug</code> in the input to switch agents mid-thread.</li>
            </ul>
          </div>
        ),
      },
      {
        id: 'alerts',
        title: 'Alerts',
        icon: <AlertTriangle className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Failures, grouped by stable <code className="text-cyan-300">failure_code</code>, with one-line remediation hints and direct links to affected agents. The page does what the dashboard alone can&apos;t — it tells you the <em>pattern</em>, not just the count.</p>
            <Hero src={SS('08-alerts-page.png')} alt="Alerts page" />
            <p><strong className="text-white">Failure code reference:</strong></p>
            <ul className="list-disc pl-5 space-y-1 text-[12px]">
              <li><code>LLM_RATE_LIMIT</code> · <code>LLM_PROVIDER_ERROR</code> · <code>LLM_INVALID_RESPONSE</code> — model layer</li>
              <li><code>SANDBOX_TIMEOUT</code> · <code>SANDBOX_NONZERO_EXIT</code> · <code>SANDBOX_OOM</code> · <code>SANDBOX_IMAGE_BLOCKED</code> — sandbox</li>
              <li><code>TOOL_NOT_FOUND</code> · <code>TOOL_ERROR</code> — tool layer</li>
              <li><code>BUDGET_EXCEEDED</code> · <code>RATE_LIMITED</code> — quota</li>
              <li><code>STALE_SWEEP</code> — owning pod crashed; sweeper marked the run failed</li>
              <li><code>MODERATION_BLOCKED</code> — moderation gate refused the input/output</li>
              <li><code>INFRA_CRASH</code> · <code>INFRA_AUTH_ERROR</code> · <code>UNKNOWN_ERROR</code></li>
            </ul>
          </div>
        ),
      },
    ],
  },
  // BUILD
  {
    id: 'build',
    label: 'Build',
    blurb: 'Where you create agents, pipelines, knowledge, and ontologies.',
    topics: [
      {
        id: 'agent-builder',
        title: 'Agent Builder',
        icon: <Wand2 className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Visual canvas for designing single agents and multi-agent pipelines. Drag tools from the catalogue, drop knowledge collections, wire up switch nodes for branching and loop nodes for iteration.</p>
            <Hero src={SS('02-agent-builder.png')} alt="Agent Builder canvas" />
            <Steps items={[
              'Click <strong>+ New agent</strong> or <strong>+ New pipeline</strong>.',
              'Use the AI Builder field — describe what you want in one sentence; a draft pops onto the canvas.',
              'Drag <strong>tools</strong> from the right rail onto the canvas. Drop them on the agent node to attach.',
              'Drop a <strong>knowledge collection</strong> for graph-aware retrieval inside the agent.',
              'For pipelines: use <strong>switch</strong> nodes to branch on output, <strong>loop</strong> nodes to iterate, <strong>code asset</strong> nodes to invoke sandboxed code.',
              'Click <strong>Test run</strong> with sample input. The right rail streams the trace.',
              'Click <strong>Publish</strong> to make the agent runnable from anywhere (chat, SDK, triggers).',
            ]} />
          </div>
        ),
      },
      {
        id: 'code-runner',
        title: 'Code Runner',
        icon: <Code2 className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Bring your own repository. Upload a zip or paste a git URL; Abenix analyzes the code, identifies entry points, and exposes runnable artefacts as <code className="text-cyan-300">code_asset</code> tools. Pipelines call them like any other tool. Supports <strong>Python, Node, Go, Rust, Ruby, Java</strong>.</p>
            <Hero src={SS('12-code-runner.png')} alt="Code Runner" />
            <Steps items={[
              '<strong>Upload</strong> a zip or paste a git URL.',
              'Abenix clones, analyzes, and lists discovered entry points (e.g. CLI commands, exported functions).',
              'Tag entry points as runnable tools with input/output schemas.',
              'Each invocation runs in a fresh Docker / Podman sandbox with strict resource quotas (default 512 MB / 30 s).',
              'Output streams back to the calling agent as a <code>tool</code> message.',
            ]} />
            <Callout tone="info">Sandboxes are isolation-first: no network unless explicitly allowed, no host filesystem mount, ephemeral overlay FS, and an OOM watchdog. See the <a href="#scaling-sandbox" className="text-violet-300 underline">sandbox scaling notes</a>.</Callout>
          </div>
        ),
      },
      {
        id: 'ml-models',
        title: 'ML Models',
        icon: <Brain className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Register classical ML models (sklearn, XGBoost, ONNX) and serve them as agent tools. Useful for credit scoring, fraud detection, demand forecasts — anywhere the answer doesn&apos;t need an LLM.</p>
            <Hero src={SS('13-ml-models.png')} alt="ML Models" />
            <Steps items={[
              'Upload a serialised model (<code>.pkl</code>, <code>.onnx</code>, <code>.joblib</code>).',
              'Define an input/output schema. Abenix validates every call against it.',
              'Click <strong>Deploy</strong>. The model spins up as its own pod (the <code>ml-model-&lt;id&gt;</code> Deployment) so a heavy model doesn&apos;t starve agents.',
              'The model is now callable as <code>ml_predict_&lt;slug&gt;</code> from any agent.',
            ]} />
          </div>
        ),
      },
      {
        id: 'knowledge-bases',
        title: 'Knowledge Bases',
        icon: <Database className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Knowledge Bases (called <em>collections</em> in v2 terminology) store your documents and the entity / relationship graph extracted from them. This is the substrate every other feature is built on.</p>
            <Hero src={SS('07-knowledge-bases.png')} alt="Knowledge Bases" />

            <h4 className="text-white font-semibold pt-3">The hierarchy</h4>
            <p>A tenant has many <strong>projects</strong>. A project has many <strong>collections</strong>. A collection has many <strong>documents</strong>. Documents are chunked, embedded, and (optionally) Cognified into a typed entity / relationship graph.</p>

            <figure className="rounded-xl overflow-hidden border border-slate-700/60 bg-slate-950/40 p-4 my-3">
              <svg viewBox="0 0 700 360" className="w-full h-auto">
                <defs>
                  <marker id="hp-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
                  </marker>
                </defs>
                <text x="350" y="22" textAnchor="middle" fill="#94a3b8" fontSize="10">DATA HIERARCHY</text>
                <rect x="40" y="50" width="620" height="60" rx="10" fill="#0f172a" stroke="#7c3aed" />
                <text x="350" y="78" textAnchor="middle" fill="#e9d5ff" fontSize="14" fontWeight="bold">Tenant — your organisation</text>
                <text x="350" y="98" textAnchor="middle" fill="#94a3b8" fontSize="11">complete data isolation from every other tenant on the platform</text>

                <rect x="60" y="135" width="290" height="80" rx="10" fill="#0f172a" stroke="#06b6d4" />
                <text x="205" y="162" textAnchor="middle" fill="#a5f3fc" fontSize="13" fontWeight="bold">Project A — “Trading Compliance”</text>
                <text x="205" y="180" textAnchor="middle" fill="#94a3b8" fontSize="11">team_a, team_b · 5 members</text>
                <text x="205" y="198" textAnchor="middle" fill="#64748b" fontSize="11">visibility scope, retention policy</text>

                <rect x="370" y="135" width="290" height="80" rx="10" fill="#0f172a" stroke="#06b6d4" />
                <text x="515" y="162" textAnchor="middle" fill="#a5f3fc" fontSize="13" fontWeight="bold">Project B — “Customer Onboarding”</text>
                <text x="515" y="180" textAnchor="middle" fill="#94a3b8" fontSize="11">team_c · 3 members</text>
                <text x="515" y="198" textAnchor="middle" fill="#64748b" fontSize="11">visibility scope, retention policy</text>

                <rect x="80" y="240" width="120" height="50" rx="6" fill="#0f172a" stroke="#10b981" />
                <text x="140" y="263" textAnchor="middle" fill="#bbf7d0" fontSize="11">Collection A1</text>
                <text x="140" y="278" textAnchor="middle" fill="#64748b" fontSize="9">12 docs</text>

                <rect x="210" y="240" width="120" height="50" rx="6" fill="#0f172a" stroke="#10b981" />
                <text x="270" y="263" textAnchor="middle" fill="#bbf7d0" fontSize="11">Collection A2</text>
                <text x="270" y="278" textAnchor="middle" fill="#64748b" fontSize="9">200 docs</text>

                <rect x="390" y="240" width="120" height="50" rx="6" fill="#0f172a" stroke="#10b981" />
                <text x="450" y="263" textAnchor="middle" fill="#bbf7d0" fontSize="11">Collection B1</text>
                <text x="450" y="278" textAnchor="middle" fill="#64748b" fontSize="9">35 docs</text>

                <rect x="520" y="240" width="120" height="50" rx="6" fill="#0f172a" stroke="#10b981" />
                <text x="580" y="263" textAnchor="middle" fill="#bbf7d0" fontSize="11">Collection B2</text>
                <text x="580" y="278" textAnchor="middle" fill="#64748b" fontSize="9">7 docs</text>

                <line x1="205" y1="215" x2="140" y2="240" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp-arr)" />
                <line x1="205" y1="215" x2="270" y2="240" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp-arr)" />
                <line x1="515" y1="215" x2="450" y2="240" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp-arr)" />
                <line x1="515" y1="215" x2="580" y2="240" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp-arr)" />
                <line x1="205" y1="110" x2="205" y2="135" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp-arr)" />
                <line x1="515" y1="110" x2="515" y2="135" stroke="#475569" strokeWidth="1.5" markerEnd="url(#hp-arr)" />

                <text x="350" y="330" textAnchor="middle" fill="#64748b" fontSize="11">Reads cross-check: tenant_id at the row, project membership for visibility, ResourceShare grants for cross-team access.</text>
              </svg>
            </figure>

            <h4 className="text-white font-semibold pt-3">How isolation works under the hood</h4>
            <p>Three checks run on every read of a knowledge collection:</p>
            <ol className="list-decimal pl-5 space-y-1.5 text-[13px]">
              <li><strong>Tenant boundary</strong> — every <code>knowledge_collections</code> row carries a <code>tenant_id</code>. Routers hard-filter on the calling user&apos;s tenant; cross-tenant reads return 404.</li>
              <li><strong>Project visibility</strong> — collections live inside a project. Default visibility is <code>PROJECT</code>: only project members can see them. <code>PRIVATE</code> restricts to the creator. <code>TENANT</code> opens it to anyone in the tenant.</li>
              <li><strong>Per-resource sharing</strong> — <code>ResourceShare</code> grants override visibility for a specific user with explicit <code>READ</code> or <code>EDIT</code> scope. Used for cross-team handoffs without changing the collection&apos;s default.</li>
            </ol>

            <Callout tone="success">
              <strong>Why two projects can&apos;t leak into each other:</strong> when an agent calls the <code>knowledge_search</code> tool, the tool is bound to a specific collection ID at agent-config time. The runtime adds <code>tenant_id = :user.tenant</code> AND <code>kb_id = :bound</code> to every vector query. The vector backend (pgvector or Pinecone) then enforces those filters at the index level — there&apos;s no SQL-LIKE shortcut around it. The same agent shared into Project B can only read Project A&apos;s collections if explicit ResourceShare grants are in place.
            </Callout>

            <h4 className="text-white font-semibold pt-3">Cognify — the entity graph</h4>
            <p>For collections with <code>graph_enabled=true</code>, every uploaded document goes through a Cognify pipeline that:</p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Extracts entities (people, companies, concepts, dates, amounts) and relationships (CAUSED_BY, OWNS, MENTIONS, …).</li>
              <li>Stores them as nodes + edges in a typed graph alongside the chunks.</li>
              <li>Strengthens edges that lead to good answers; weakens those that don&apos;t (the Knowledge Engine self-tunes).</li>
            </ol>
            <p>Agents using <code>knowledge_search</code> on a graph-enabled collection get hybrid retrieval: vector similarity AND multi-hop graph walks. This is the 5–10× token reduction story.</p>

            <h4 className="text-white font-semibold pt-3">Common tasks</h4>
            <Steps items={[
              'Click <strong>+ New collection</strong> inside a project.',
              'Pick a vector backend — <strong>pgvector</strong> (default, in-cluster) or <strong>Pinecone</strong> (managed, scales further).',
              'Upload documents — PDF, DOCX, TXT, MD, CSV, JSON.',
              'Toggle <strong>Cognify</strong> on if you want the typed graph.',
              'Wait for status <code>READY</code>, then attach the collection to any agent.',
            ]} />
          </div>
        ),
      },
      {
        id: 'persona-kb',
        title: 'Persona KB',
        icon: <UserCircle2 className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>A private knowledge collection that follows <em>you</em>. Notes, files, meeting context. Lives in a dedicated namespace <code className="text-cyan-300">persona:&lt;tenant_id&gt;</code> so generic <code>knowledge_search</code> can&apos;t touch it.</p>
            <Hero src={SS('14-persona-kb.png')} alt="Persona KB" />
            <p><strong className="text-white">Three defenses prevent persona leakage:</strong></p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Generic <code>knowledge_search</code> applies a Pinecone filter that excludes any chunk with a <code>persona_scope</code> field.</li>
              <li><code>persona_rag</code> (the only tool that reads persona) requires the scope to be pre-authorised on the meeting (or be the implicit <code>self</code>).</li>
              <li>A defense-in-depth in-memory re-filter, in case the vector backend silently ignores the filter argument.</li>
            </ol>
            <p>Persona is also where you upload a voice sample for opt-in voice cloning (used by meeting bots — see the Meeting Primitives topic).</p>
          </div>
        ),
      },
      {
        id: 'portfolio-schemas',
        title: 'Portfolio Schemas',
        icon: <FileJson className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Define <em>domain-specific</em> schemas at runtime — no code change, no redeploy. The <code className="text-cyan-300">SchemaPortfolioTool</code> reads them and exposes a tool named <code>portfolio_&lt;domain&gt;</code> automatically.</p>
            <Hero src={SS('15-portfolio-schemas.png')} alt="Portfolio Schemas" />
            <p>A schema describes:</p>
            <ul className="list-disc pl-5 space-y-1 text-[12px]">
              <li><strong>Main table</strong> — name, columns with types/labels/formats, RBAC scope column, search columns, summary aggregations.</li>
              <li><strong>Related tables</strong> — foreign keys, searchable columns, KV stores for extracted data.</li>
              <li><strong>Domain context</strong> — record nouns, display labels.</li>
            </ul>
            <p>Three starters ship: <strong>Energy Contracts</strong>, <strong>Real Estate</strong>, <strong>M&amp;A Documents</strong>. Schemas are tenant-scoped and stored in Postgres.</p>
          </div>
        ),
      },
      {
        id: 'bpm-analyzer',
        title: 'BPM Analyzer',
        icon: <Workflow className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Drop any process artefact — BPMN PDF, flowchart screenshot, whiteboard photo, audio walkthrough, screencast. Get a multi-page agentification report. The <strong>Build Agents</strong> wizard generates synthetic test data, creates draft agents, and smoke-tests them in front of you.</p>
            <Hero src={SS('03-bpm-analyzer.png')} alt="BPM Analyzer" />
            <Steps items={[
              'Click <strong>Upload process artifact</strong> (or drop a file directly on the canvas).',
              'Pick the model. Audio + video auto-route to Gemini regardless of selection.',
              'Wait for the analysis. The right side renders the report — markdown tables, headings, callouts.',
              'Ask follow-up questions in the chat input — the model still sees the original artefact.',
              'Click <strong>Build Agents</strong> to open the wizard. Each suggested agent goes through synthesise → create → smoke-test in real time.',
              'Click <strong>Download PDF</strong> to export the full analysis as a beautifully formatted PDF.',
            ]} />
          </div>
        ),
      },
      {
        id: 'atlas',
        title: 'Atlas — ontology + KB canvas',
        icon: <Network className="w-4 h-4" />,
        badge: 'flagship',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p><strong className="text-white">Atlas</strong> is the unified ontology + knowledge-base canvas. Documents are nodes. Concepts are nodes. Edges are first-class. Agents read the graph, not raw chunks.</p>
            <Hero src={SS('05-atlas-empty-state.png')} alt="Atlas onboarding" caption="A brand-new atlas — pick any of four ways to begin" />

            <h4 className="text-white font-semibold pt-3">Five ways to fill an atlas</h4>
            <ul className="list-disc pl-5 space-y-2 text-[13px]">
              <li><strong>Drop a document</strong> — drag any PDF / image / audio / video / DOCX / text onto the canvas. Atlas extracts entities + relationships and shows them as a reviewable proposal at the bottom.</li>
              <li><strong>Type a sentence</strong> — the bar at the bottom converts natural language into structured ops. <em>“Counterparty has many Trades. Each Trade settles via exactly one SSI.”</em> → 3 add_node ops, 2 add_edge ops, cardinalities inferred.</li>
              <li><strong>Import a starter</strong> — five curated kits ship in the box: <strong>FIBO Core</strong>, <strong>FIX Protocol</strong>, <strong>EMIR Reporting</strong>, <strong>ISDA Master Agreement</strong>, <strong>ETRM EOD</strong>.</li>
              <li><strong>Bind a knowledge collection</strong> — when bound, <em>Project KB</em> pulls every existing document onto the canvas as a <code>document</code>-kind node. Drop new files on the canvas and they round-trip into the KB.</li>
              <li><strong>Draw it manually</strong> — add concepts and instances by hand. Drag from the right edge of one node to the left edge of another to create a relationship.</li>
            </ul>
            <Hero src={SS('04-atlas-canvas.png')} alt="Atlas with FIBO Core imported" caption="After importing the FIBO Core starter — concepts, edges, cardinalities" />

            <h4 className="text-white font-semibold pt-3">Inspector — five lenses</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Schema</strong> — kind, source, confidence, tags.</li>
              <li><strong>Relations</strong> — incoming + outgoing edges with cardinalities.</li>
              <li><strong>Properties</strong> — typed attributes pulled from the source document or set manually.</li>
              <li><strong>Instances</strong> — when the node is bound to a KB collection, the live document rows.</li>
              <li><strong>Lineage</strong> — created/updated timestamps, source (user / extractor / starter), originating document.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Layout, snapshots, visual query</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Three layout modes</strong> — Semantic (random projection of OpenAI embeddings), Circle, Grid.</li>
              <li><strong>Time slider</strong> — every save snapshots the entire graph as JSONB. One-click restore (auto-snapshots current state first).</li>
              <li><strong>Visual query</strong> — draw a pattern (label-like + kind), Run, click any match to fly the camera to it.</li>
              <li><strong>Ghost cursor</strong> — top-right card with deterministic suggestions: missing inverses, possible duplicates, orphans, missing cardinalities.</li>
              <li><strong>Export</strong> — JSON-LD round-trippable into Protégé, Stardog, TerminusDB.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Why this matters for agents</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Schema-grounded extraction</strong> — agents extract <em>into</em> the typed graph, not into a free-form bag of strings.</li>
              <li><strong>Better-than-vector retrieval</strong> — agents walk the graph, then pull only the chunks bound to those nodes. Token cost drops 5–10×.</li>
              <li><strong>Cross-agent disambiguation</strong> — “Trade” means the same thing across every agent reading this domain.</li>
              <li><strong>Multi-hop reasoning</strong> — the visual-query endpoint exposed as a tool lets agents draw patterns instead of stitching SQL.</li>
              <li><strong>Validation</strong> — outputs validated against the ontology&apos;s cardinalities and types; bad outputs reject before they land.</li>
              <li><strong>Provenance</strong> — every agent answer cites the Atlas nodes it walked.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Agent tools — read the graph</h4>
            <p>Four tools ship in the catalogue. Attach them to any agent in the Builder:</p>
            <ul className="list-disc pl-5 space-y-1.5 text-[13px]">
              <li><code className="text-cyan-300">atlas_describe</code> — summarise the graph (counts by kind, top edge labels, most-connected concepts). Use first when the user asks "what do you know about X?".</li>
              <li><code className="text-cyan-300">atlas_query</code> — pattern-match nodes by <code>label_like</code> + <code>kind</code>. Returns structured rows; the typed alternative to vector search.</li>
              <li><code className="text-cyan-300">atlas_traverse</code> — 1-hop neighbourhood of a node. Use after locating a concept to walk to related concepts.</li>
              <li><code className="text-cyan-300">atlas_search_grounded</code> — find KB documents bound to nodes near a target term. Better than vector-only when the chunks must be tied to a typed concept.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Per-agent + per-application segregation</h4>
            <p>Atlas graphs are tenant-scoped by default — every other tenant sees nothing. Inside a tenant, you can pin an agent to specific graphs:</p>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`# In the agent's model_config (Builder → Settings → Advanced JSON):
{
  "model": "claude-sonnet-4-5-20250929",
  "tools": ["atlas_describe", "atlas_query"],
  "atlas_graphs": [
    "11111111-1111-1111-1111-111111111111",   # the FIBO ontology
    "22222222-2222-2222-2222-222222222222"    # the firm-specific overlay
  ]
}`}</pre>
            <p className="text-[12px]">
              When the allow-list is non-empty, the tool can <em>only</em> see those graph IDs — even if other graphs exist in the same tenant. This lets you ship agents that read FIBO + your house ontology while a sibling agent sees a different domain (HL7 / FHIR for healthcare, FIX for trading) without leakage. Empty list = the agent sees every graph in its tenant (the default tenant boundary).
            </p>
            <p className="text-[12px]">
              <strong className="text-white">Per-application:</strong> standalone apps using the actAs delegation pattern pass <code>X-Abenix-Subject</code> per request. The subject inherits the agent&apos;s allow-list; the data still flows under the agent's <code>tenant_id</code>, so cross-app reads stay impossible at the SQL layer.
            </p>
          </div>
        ),
      },
    ],
  },
  // PIPELINE OPERATIONS — self-healing + workflow shell + per-agent scaling
  {
    id: 'pipeops',
    label: 'Pipeline operations',
    blurb: 'Three flagship features for keeping pipelines healthy: self-healing, the talk-to-workflow shell, and per-agent pod scaling.',
    topics: [
      {
        id: 'self-healing',
        title: 'Self-healing pipelines',
        icon: <Sparkles className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>When a pipeline node fails, Abenix captures a structured failure-diff (error class, observed-vs-expected output shape, the inputs the node received, last-N successful runs of the same node). The <strong className="text-white">Pipeline Surgeon</strong> agent reads that diff plus the live DSL and proposes a JSON-Patch (RFC 6902) fix.</p>
            <p><strong className="text-white">How to use it.</strong> On any pipeline agent's <code>/info</code> page, click the cyan <strong>Healing</strong> button. The page lists pending proposals, applied patches (with one-click rollback), recent failures, and the audit history. Click <strong>Diagnose latest failure</strong> to invoke the Surgeon. Each proposal shows the title, rationale, risk level, confidence score, and the JSON-Patch ops side-by-side with the resulting DSL.</p>
            <p><strong className="text-white">What the Surgeon writes.</strong> Minimal patches — typically one or two ops:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Add a fallback default for a missing field on a node's input mapping.</li>
              <li>Set <code>on_error: continue</code> on a non-critical step so the pipeline doesn't abort on a single transient failure.</li>
              <li>Insert a defensive coerce / validate node before the failing one.</li>
              <li>Swap the LLM model on an agent_step node (last-resort, marked <em>medium</em> risk).</li>
            </ul>
            <p><strong className="text-white">Apply and rollback.</strong> Patches never apply automatically. Apply records the user, the timestamp, and stores <code>dsl_before</code> in the proposal row so rollback is one click. Rollback writes <code>dsl_before</code> back to the live agent and marks the proposal <em>rolled_back</em> for audit.</p>
            <p><strong className="text-white">Configurable model.</strong> The Surgeon's model is read from <strong>Admin → Settings → <code>pipeline_surgeon.model</code></strong>. Defaults to <code>claude-sonnet-4-5-20250929</code>; switch it cluster-wide from the central model selection page so every LLM-using primitive shares one configuration surface.</p>
          </div>
        ),
      },
      {
        id: 'workflow-shell',
        title: 'Talk-to-workflow shell',
        icon: <Terminal className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>A typed verb grammar — over 30 verbs across five intents — that drives every aspect of a pipeline. The LLM is only used to translate natural language into a verb invocation (when you type prose); the parser, the dispatcher, and every mutating verb are deterministic.</p>
            <p>Open it from any pipeline agent's <code>/info</code> page via the <strong>Shell</strong> button next to <strong>Healing</strong>. Tab-completion comes from the live verb registry. Up/down recalls history. Mutating verbs draft a Healing patch you Apply or Reject — same ledger as the Surgeon, same one-click rollback.</p>
            <p><strong className="text-white">Five intents, ~30 verbs:</strong></p>
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase text-slate-500">
                <tr><th className="text-left py-1">Intent</th><th className="text-left py-1">Verbs</th><th className="text-left py-1">Purpose</th></tr>
              </thead>
              <tbody className="text-slate-300 align-top">
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono text-cyan-300">INSPECT</td><td className="py-1 font-mono text-[11px]">show, describe, diff, why, list</td><td className="py-1">Read the workflow object — DSL, runs, failures, costs, schedule, patches, history.</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono text-amber-300">MUTATE</td><td className="py-1 font-mono text-[11px]">add, remove, rename, set, swap-model, add-fallback, attach</td><td className="py-1">Compile to JSON-Patch ops. Always create a draft proposal — never live-edit.</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono text-emerald-300">EXECUTE</td><td className="py-1 font-mono text-[11px]">run, replay, simulate, branch, merge, rollback</td><td className="py-1">Drive runs. <code>simulate</code> is idempotent (dry-run); <code>branch</code> creates a sandbox version.</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono text-purple-300">GOVERN</td><td className="py-1 font-mono text-[11px]">watch, budget, pin, unpin, approve, reject</td><td className="py-1">Alert thresholds, budgets, model pins, patch decisions.</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono text-pink-300">LEARN</td><td className="py-1 font-mono text-[11px]">suggest, diagnose, explain, help</td><td className="py-1">Ask the shell for ideas, run the Surgeon, explain costs/latency/routing.</td></tr>
              </tbody>
            </table>
            <p><strong className="text-white">Real one-liners:</strong></p>
            <pre className="bg-slate-950/60 border border-slate-800 rounded-md p-3 overflow-x-auto text-[11px] font-mono text-slate-300">
{`> show failures
> diff last last-2
> swap-model extractor gemini-2.5-pro       # → draft patch, awaits approval
> add-fallback extractor counterparty UNKNOWN
> watch cost alert if > 5/run
> simulate fixture:weekend-batch
> approve p9d1`}
            </pre>
            <p><strong className="text-white">Configurable model.</strong> Natural-language translation goes through <strong>Admin → Settings → <code>workflow_shell.model</code></strong> (lower-latency models work best here).</p>
          </div>
        ),
      },
      {
        id: 'per-agent-scaling',
        title: 'Per-agent pod scaling',
        icon: <Cpu className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Most agents run beautifully on a shared pool. But for the long tail — a noisy extractor, a finetuned model with a 4 GB checkpoint, an agent with strict tenant-isolation needs — Abenix lets you opt that single agent into its own pod with one click.</p>
            <p><strong className="text-white">How to flip it on.</strong> Visit <strong>Admin → Scaling</strong>. The agents table now has a <strong>Mode</strong> column with a pill button: <em>Shared</em> (slate) or <em>Dedicated</em> (cyan). Click to toggle. Hover for the trade-off tooltip.</p>
            <p><strong className="text-white">What changes when you flip.</strong></p>
            <ul className="list-disc pl-6 space-y-1">
              <li><code>agents.dedicated_mode</code> goes <code>false → true</code>.</li>
              <li>The runtime reads <code>effective_pool</code> as <code>dedicated-&lt;agent-id&gt;</code> instead of the shared <code>runtime_pool</code>.</li>
              <li>Helm provisions a per-agent Deployment + KEDA ScaledObject keyed off the per-agent NATS subject (<code>abenix.runtime.dedicated-&lt;agent-id&gt;</code>).</li>
              <li>The runtime_pool field is left intact — you can flip back without losing your original pool selection.</li>
            </ul>
            <p><strong className="text-white">See the cost before you flip.</strong> The endpoint <code>GET /api/admin/scaling/agents/{'{'}id{'}'}/cost-projection</code> returns three scenarios — <em>shared</em>, <em>dedicated</em>, <em>peak</em> (worst case at <code>max_replicas</code>) — computed from the trailing-24h execution rate × per-run avg cost × replica count plus an explicit <code>$0.012/h</code> per-pod baseline. Tune the baseline in <code>app/routers/admin_scaling.py</code> if your cluster billing differs.</p>
            <p><strong className="text-white">When to flip it on:</strong></p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Noisy-neighbour isolation — a runaway extraction agent must not slow chat down.</li>
              <li>Per-agent resource limits — memory, GPU, custom node-pool affinity.</li>
              <li>Distinct image dependencies — proprietary SDKs, region-specific binaries.</li>
              <li>Cleaner reasoning — kubectl top per-agent.</li>
            </ul>
            <p><strong className="text-white">When NOT to flip it on:</strong></p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Stateless LLM-API callers — 200 in one pod scale identically to 200 in 200 pods at much higher control-plane overhead.</li>
              <li>Sub-2-second agents — the shared <code>chat</code> pool is already kept warm for them.</li>
            </ul>
          </div>
        ),
      },
    ],
  },
  // RUN & TEST
  {
    id: 'run',
    label: 'Run & test',
    blurb: 'Drive your agents from the SDK, simulate load, schedule them.',
    topics: [
      {
        id: 'sdk-playground',
        title: 'SDK Playground',
        icon: <Code2 className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Generates production-ready Python or TypeScript code that uses the Abenix SDK to call any agent, pipeline, or knowledge base. The generator loads the actual SDK source as authoritative context, so the code uses real methods — no hallucination.</p>
            <Hero src={SS('16-sdk-playground.png')} alt="SDK Playground" />
            <p><strong className="text-white">Use cases supported:</strong> one-shot, streaming, KB search, Cognify, batch, HITL.</p>
            <p><strong className="text-white">Run it in-browser:</strong> Python code can be executed in a sandbox with an ephemeral 1-hour API key minted automatically. TypeScript is copy-only in v1.</p>
            <p className="pt-2 border-t border-slate-800/40 text-slate-400 text-[12.5px]">
              <strong className="text-white">Three SDKs ship today.</strong> Python (<code className="text-cyan-300">packages/sdk/python</code>), TypeScript (<code className="text-cyan-300">packages/sdk/js</code>), and Java/JVM (<code className="text-cyan-300">claimsiq/sdk</code>). The Java SDK is stdlib-only on its public surface — JDK 21 <code>HttpClient</code> for HTTP+SSE, Jackson for JSON, SLF4J for logging — so Kotlin and Scala consumers get zero glue. Public types: <code className="text-cyan-300">Abenix</code> (entry point), <code className="text-cyan-300">ActingSubject</code>, <code className="text-cyan-300">ExecutionResult</code>, <code className="text-cyan-300">WatchStream</code> + <code className="text-cyan-300">SseWatchStream</code> for live DAG updates over SSE, <code className="text-cyan-300">DagSnapshot</code>, <code className="text-cyan-300">AbenixException</code>. ClaimsIQ's <code>ClaimsService</code> calls <code>forge.execute(...)</code> for every adjudication and the Live DAG view subscribes to <code>forge.watch(...)</code>.
            </p>
          </div>
        ),
      },
      {
        id: 'load-playground',
        title: 'Load Playground',
        icon: <Gauge className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Fire N parallel executions against any agent or pipeline; watch p50/p99/p999 latency and per-tool timing. Use it before promoting an agent to production.</p>
            <Hero src={SS('17-load-playground.png')} alt="Load Playground" />
          </div>
        ),
      },
      {
        id: 'triggers',
        title: 'Triggers',
        icon: <Zap className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Run any agent or pipeline on a schedule (cron) or on incoming webhooks. Triggers go through the same execution path as manual runs, so observability and quotas apply identically.</p>
            <Hero src={SS('detail-trigger-config.png')} alt="Triggers" />
            <Steps items={[
              'Click <strong>+ New trigger</strong>.',
              'Pick <strong>cron</strong> or <strong>webhook</strong>.',
              'Select the agent or pipeline; provide the input template.',
              'For cron: pick a timezone, set the schedule. For webhook: copy the URL + secret.',
              'Hit <strong>Save</strong>. Activations show up in <em>Executions</em> with a <code>trigger_id</code> tag.',
            ]} />
          </div>
        ),
      },
    ],
  },
  // MONITOR
  {
    id: 'monitor',
    label: 'Monitor',
    blurb: 'See what&apos;s happening in production. Spot patterns, not noise.',
    topics: [
      {
        id: 'executions',
        title: 'Executions',
        icon: <Activity className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Every run, with status, duration, model, cost, tokens, tool-call list, and the full trace. Click any execution for the per-step breakdown.</p>
            <Hero src={SS('18-executions.png')} alt="Executions" />
            <Hero src={SS('detail-pipeline-trace.png')} alt="Pipeline trace" caption="Pipeline detail — per-step durations, inputs, outputs" />
            <p><strong className="text-white">Pro tips:</strong></p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>The filter pill row supports <code>status</code>, <code>agent</code>, <code>trigger</code>, <code>failure_code</code>, and free-text in the input/output.</li>
              <li>Use the <em>Replay</em> button to re-run an execution with the same input — handy for fix-then-verify cycles.</li>
              <li>Use the <em>Export NDJSON</em> button to pull the trace into a notebook for ad-hoc analysis.</li>
            </ul>
          </div>
        ),
      },
      {
        id: 'live-debug',
        title: 'Live Debug',
        icon: <Radio className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Streams every active execution in real time. Open it in a side window during a load test or a stuck-agent investigation; you see every tool call as it happens.</p>
          </div>
        ),
      },
      {
        id: 'analytics',
        title: 'Analytics',
        icon: <BarChart3 className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Trends over time: executions per day, cost per day, top agents, top tools, p99 latency. The data is the same Prometheus that drives Grafana, projected for the operator who doesn&apos;t want to leave the app.</p>
            <Hero src={SS('19-analytics.png')} alt="Analytics" />
          </div>
        ),
      },
      {
        id: 'moderation',
        title: 'Moderation',
        icon: <ShieldCheck className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Tenant-scoped moderation gate. Runs <strong>pre-LLM</strong> on user input and <strong>post-LLM</strong> on model output for every agent execution. Non-bypassable — the agent itself cannot disable it.</p>
            <Hero src={SS('20-moderation.png')} alt="Moderation" />
            <p><strong className="text-white">Actions:</strong></p>
            <ul className="list-disc pl-5 space-y-0.5 text-[12px]">
              <li><code className="text-rose-300">block</code> — refuse; execution fails with <code>MODERATION_BLOCKED</code>.</li>
              <li><code className="text-violet-300">redact</code> — mask matching spans, allow through.</li>
              <li><code className="text-amber-300">flag</code> — pass through, log + notify only.</li>
              <li><code className="text-emerald-300">allow</code> — default for un-triggered categories.</li>
            </ul>
            <p>Provider: OpenAI <code>omni-moderation-latest</code> (free for OpenAI customers, ~40–150ms). Falls open if the API key is missing; tenants who want strict fail-closed can set <code>fail_closed=true</code> on the policy.</p>
            <p>The Observability section&apos;s observability stack also gives you the <code>/alerts</code> page, which surfaces moderation blocks alongside other failure codes — see <a href="#alerts" className="text-violet-300 underline">Alerts</a>.</p>
          </div>
        ),
      },
    ],
  },
  // SCALE & OPERATE — the big one
  {
    id: 'scale',
    label: 'Scale & operate',
    blurb: 'Everything you need to run Abenix at production scale.',
    topics: [
      {
        id: 'scaling-overview',
        title: 'Scaling overview',
        icon: <Gauge className="w-4 h-4" />,
        badge: 'Read first',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Abenix is three independently-scalable tiers backed by a shared Postgres. Every tier scales differently and is wired up in the bundled Helm chart.</p>

            <figure className="rounded-xl overflow-hidden border border-slate-700/60 bg-slate-950/40 p-4">
              <svg viewBox="0 0 880 460" className="w-full h-auto">
                <defs>
                  <marker id="sc-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
                  </marker>
                </defs>

                {/* Web tier */}
                <rect x="40" y="40" width="240" height="100" rx="10" fill="#0f172a" stroke="#06b6d4" />
                <text x="160" y="68" textAnchor="middle" fill="#a5f3fc" fontSize="14" fontWeight="bold">Web tier</text>
                <text x="160" y="90" textAnchor="middle" fill="#94a3b8" fontSize="11">Stateless · scale by replicas</text>
                <text x="160" y="108" textAnchor="middle" fill="#94a3b8" fontSize="11">CDN + ingress in front</text>
                <text x="160" y="126" textAnchor="middle" fill="#64748b" fontSize="10">3 replicas → 30 by HPA</text>

                {/* API tier */}
                <rect x="320" y="40" width="240" height="100" rx="10" fill="#0f172a" stroke="#a855f7" />
                <text x="440" y="68" textAnchor="middle" fill="#ddd6fe" fontSize="14" fontWeight="bold">API tier</text>
                <text x="440" y="90" textAnchor="middle" fill="#94a3b8" fontSize="11">Stateless · HPA by CPU + RPS</text>
                <text x="440" y="108" textAnchor="middle" fill="#94a3b8" fontSize="11">Connection pool 20 per pod</text>
                <text x="440" y="126" textAnchor="middle" fill="#64748b" fontSize="10">3 replicas → 50 typical</text>

                {/* Runtime tier */}
                <rect x="600" y="40" width="240" height="100" rx="10" fill="#0f172a" stroke="#10b981" />
                <text x="720" y="68" textAnchor="middle" fill="#bbf7d0" fontSize="14" fontWeight="bold">Runtime tier</text>
                <text x="720" y="90" textAnchor="middle" fill="#94a3b8" fontSize="11">Per-agent pools · KEDA</text>
                <text x="720" y="108" textAnchor="middle" fill="#94a3b8" fontSize="11">Queue-depth scaling</text>
                <text x="720" y="126" textAnchor="middle" fill="#64748b" fontSize="10">Scale to zero between bursts</text>

                {/* Pools row */}
                <text x="720" y="170" textAnchor="middle" fill="#94a3b8" fontSize="10">Pools</text>
                <rect x="600" y="180" width="55" height="36" rx="4" fill="#0f172a" stroke="#475569" />
                <text x="627" y="203" textAnchor="middle" fill="#bbf7d0" fontSize="10">chat</text>
                <rect x="660" y="180" width="55" height="36" rx="4" fill="#0f172a" stroke="#475569" />
                <text x="687" y="203" textAnchor="middle" fill="#bbf7d0" fontSize="10">default</text>
                <rect x="720" y="180" width="55" height="36" rx="4" fill="#0f172a" stroke="#475569" />
                <text x="747" y="200" textAnchor="middle" fill="#bbf7d0" fontSize="9">long-</text>
                <text x="747" y="211" textAnchor="middle" fill="#bbf7d0" fontSize="9">running</text>
                <rect x="780" y="180" width="55" height="36" rx="4" fill="#0f172a" stroke="#475569" />
                <text x="807" y="200" textAnchor="middle" fill="#bbf7d0" fontSize="9">heavy-</text>
                <text x="807" y="211" textAnchor="middle" fill="#bbf7d0" fontSize="9">reason</text>

                {/* Data tier */}
                <rect x="40" y="240" width="800" height="100" rx="10" fill="#0f172a" stroke="#3b82f6" />
                <text x="440" y="268" textAnchor="middle" fill="#dbeafe" fontSize="14" fontWeight="bold">Data tier</text>

                <rect x="60" y="284" width="180" height="40" rx="6" fill="#1e293b" stroke="#475569" />
                <text x="150" y="308" textAnchor="middle" fill="#dbeafe" fontSize="11">Postgres 16 + pgvector</text>

                <rect x="260" y="284" width="180" height="40" rx="6" fill="#1e293b" stroke="#475569" />
                <text x="350" y="308" textAnchor="middle" fill="#dbeafe" fontSize="11">Redis · queues · cache</text>

                <rect x="460" y="284" width="180" height="40" rx="6" fill="#1e293b" stroke="#475569" />
                <text x="550" y="308" textAnchor="middle" fill="#dbeafe" fontSize="11">Object storage S3</text>

                <rect x="660" y="284" width="160" height="40" rx="6" fill="#1e293b" stroke="#475569" />
                <text x="740" y="308" textAnchor="middle" fill="#dbeafe" fontSize="11">Pinecone (optional)</text>

                {/* Observability */}
                <rect x="40" y="365" width="800" height="60" rx="10" fill="#0f172a" stroke="#f59e0b" />
                <text x="440" y="390" textAnchor="middle" fill="#fde68a" fontSize="13" fontWeight="bold">Observability</text>
                <text x="440" y="410" textAnchor="middle" fill="#94a3b8" fontSize="11">Prometheus 15-day · Grafana · /alerts · Slack · email</text>

                {/* Connectors */}
                <line x1="280" y1="90" x2="320" y2="90" stroke="#475569" strokeWidth="1.5" markerEnd="url(#sc-arr)" />
                <line x1="560" y1="90" x2="600" y2="90" stroke="#475569" strokeWidth="1.5" markerEnd="url(#sc-arr)" />
                <line x1="160" y1="140" x2="160" y2="240" stroke="#475569" strokeWidth="1.5" markerEnd="url(#sc-arr)" />
                <line x1="440" y1="140" x2="440" y2="240" stroke="#475569" strokeWidth="1.5" markerEnd="url(#sc-arr)" />
                <line x1="720" y1="216" x2="720" y2="240" stroke="#475569" strokeWidth="1.5" markerEnd="url(#sc-arr)" />
              </svg>
            </figure>

            <h4 className="text-white font-semibold pt-3">Default sizing</h4>
            <table className="w-full text-[12px] my-2">
              <thead className="text-slate-400 border-b border-slate-700">
                <tr><th className="text-left py-1.5">Tier</th><th className="text-left py-1.5">CPU req</th><th className="text-left py-1.5">Mem req</th><th className="text-left py-1.5">Replicas (default)</th><th className="text-left py-1.5">Replicas (1k tenants)</th></tr>
              </thead>
              <tbody className="text-slate-300">
                <tr className="border-b border-slate-800/60"><td className="py-1.5">Web</td><td>200 m</td><td>256 Mi</td><td>3</td><td>10–30</td></tr>
                <tr className="border-b border-slate-800/60"><td className="py-1.5">API</td><td>500 m</td><td>1 Gi</td><td>3</td><td>20–50</td></tr>
                <tr className="border-b border-slate-800/60"><td className="py-1.5">Runtime · chat</td><td>500 m</td><td>1.5 Gi</td><td>2 → 0/burst</td><td>20–100</td></tr>
                <tr className="border-b border-slate-800/60"><td className="py-1.5">Runtime · default</td><td>500 m</td><td>1.5 Gi</td><td>2 → 0/burst</td><td>50–200</td></tr>
                <tr className="border-b border-slate-800/60"><td className="py-1.5">Runtime · long-running</td><td>1</td><td>4 Gi</td><td>1</td><td>5–20</td></tr>
                <tr><td className="py-1.5">Runtime · heavy-reasoning</td><td>2</td><td>8 Gi</td><td>1</td><td>2–10</td></tr>
              </tbody>
            </table>
          </div>
        ),
      },
      {
        id: 'scaling-runtime-mode',
        title: 'RUNTIME_MODE — embedded vs remote',
        icon: <Route className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>
              The <code className="text-cyan-300">RUNTIME_MODE</code> env var on the API decides where agent code actually executes. Two modes ship:
            </p>

            <table className="w-full text-[12px] my-2">
              <thead className="text-slate-400 border-b border-slate-700">
                <tr>
                  <th className="text-left py-2">Mode</th>
                  <th className="text-left py-2">Where the agent runs</th>
                  <th className="text-left py-2">Best for</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                <tr className="border-b border-slate-800/60">
                  <td className="py-2"><code>embedded</code></td>
                  <td>Inside the API process</td>
                  <td>Laptop dev, low-volume self-hosted</td>
                </tr>
                <tr>
                  <td className="py-2"><code>remote</code> <span className="text-emerald-300 text-[10px] uppercase ml-1">production</span></td>
                  <td>Runtime pods (NATS-routed)</td>
                  <td>Production · all multi-tenant traffic</td>
                </tr>
              </tbody>
            </table>

            <h4 className="text-white font-semibold pt-2">embedded mode — what it does</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>The API receives <code>POST /api/agents/{`{id}`}/execute</code>.</li>
              <li>The same API process loads the LLM client + tools and runs the loop in-thread.</li>
              <li>SSE events stream straight back to the client.</li>
              <li>Heavy reasoning agents share the API&apos;s memory + CPU — an OOM in one agent crashes the whole API replica.</li>
            </ul>

            <h4 className="text-white font-semibold pt-2">remote mode — what it does</h4>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>API loads the agent config + tools and builds an <code>ExecutionConfig</code>.</li>
              <li>API publishes the work to NATS: subject <code>agent-runs.&lt;pool&gt;.&gt;</code> (chat / default / long-running / heavy-reasoning).</li>
              <li>A runtime pod (matching the pool) consumes the message via <code>consumer.py</code>, loads the LLM + tools, runs the agent.</li>
              <li>Runtime publishes back through the NATS execution-bus: <code>start</code>, <code>tool_call</code>, <code>tool_result</code>, <code>token</code>, <code>done</code> / <code>error</code>.</li>
              <li>API streams those events to the caller (or blocks if <code>wait=true</code>).</li>
            </ol>

            <h4 className="text-white font-semibold pt-2">Why remote is more robust</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Crash recovery</strong> — runtime pod dies mid-agent → NATS redelivers the message → another pod retries. No work loss.</li>
              <li><strong>Resource isolation</strong> — heavy-reasoning agents can&apos;t OOM the API.</li>
              <li><strong>Independent scaling</strong> — API runs at predictable CPU; runtime pools KEDA-autoscale per pool to 0 between bursts.</li>
              <li><strong>Per-pool routing</strong> — chat agents on a small pool, heavy on the big pool, governed independently by per-pool KEDA <code>listLength</code>.</li>
            </ul>

            <h4 className="text-white font-semibold pt-2">Toggling</h4>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`# Production — default in this Helm chart
kubectl -n abenix set env deployment/abenix-api RUNTIME_MODE=remote

# Dev / single-pod — agent runs in the API process
kubectl -n abenix set env deployment/abenix-api RUNTIME_MODE=embedded`}</pre>

            <Callout tone="info">
              All Atlas tools work in both modes. In embedded mode the tools execute in-process; in remote mode they execute on the runtime pod. The tenant + per-agent <code>atlas_graphs</code> allow-list is enforced identically in both code paths.
            </Callout>
          </div>
        ),
      },
      {
        id: 'scaling-runtime',
        title: 'Runtime pools + KEDA',
        icon: <Cpu className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The runtime tier is split into pools, one per agent profile. Each pool has its own Deployment, its own Redis queue, and its own KEDA <code>ScaledObject</code> watching that queue&apos;s depth.</p>
            <p>Pools by purpose:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>chat</strong> — short-lived (under 30s), low memory, autoscales aggressively.</li>
              <li><strong>default</strong> — bulk workhorse for typical agents.</li>
              <li><strong>long-running</strong> — over-30s executions; bigger CPU/RAM, slower scale.</li>
              <li><strong>heavy-reasoning</strong> — 8GB RAM, large-context models, tightest concurrency cap.</li>
            </ul>
            <p>Why split? A long-running research agent shouldn&apos;t starve a chat session. Different concurrency, different SLOs, different LLM rate-limit budgets per pool.</p>

            <h4 className="text-white font-semibold pt-3">KEDA queue-depth scaling</h4>
            <p>Each pool autoscales by Redis list length. Conceptually: if 200 messages sit in <code>chat-queue</code> and the per-pod target is 10, KEDA grows the pool to 20 pods.</p>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`# infra/helm/abenix/templates/keda-chat.yaml (simplified)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: abenix-runtime-chat
spec:
  scaleTargetRef:
    name: abenix-agent-runtime-chat
  minReplicaCount: 0          # scale to zero on idle
  maxReplicaCount: 100
  pollingInterval: 10
  cooldownPeriod: 60
  triggers:
  - type: redis
    metadata:
      address: redis:6379
      listName: chat-queue
      listLength: "10"        # target items per pod`}</pre>
            <p>Tune <code>listLength</code> down for lower latency at higher cost; tune up to save money at the cost of queue wait. The <code>/admin/scaling</code> page exposes these knobs to admins without a helm upgrade.</p>
            <Hero src={SS('23-admin-scaling.png')} alt="Admin scaling console" />
          </div>
        ),
      },
      {
        id: 'scaling-postgres',
        title: 'Postgres scaling',
        icon: <Database className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Postgres is the source of truth for everything that needs to be transactional: tenants, users, agents, conversations, executions, atlas graphs, KB metadata, and (when <code>vector_backend=pgvector</code>) the embeddings themselves.</p>
            <p><strong className="text-white">Vertical first, horizontal later.</strong> A managed Postgres at 8 vCPU / 32 GB will comfortably hold ~1k tenants and 10M executions. Beyond that:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Read replicas</strong> for the <em>list</em> endpoints (executions, dashboards, analytics). The API supports a <code>DATABASE_URL_RO</code> env var that read-routes those queries.</li>
              <li><strong>Partitioning</strong> on <code>executions</code> and <code>messages</code> by <code>created_at</code> (monthly). A migration helper lives in <code>packages/db/scripts/partition_executions.py</code>.</li>
              <li><strong>Connection pooling</strong> via PgBouncer. The default pod-side pool is 20 per API replica; PgBouncer collapses N×20 client conns to a fixed primary-side limit.</li>
              <li><strong>pgvector → Pinecone</strong> when embeddings exceed ~5M rows. Per-collection toggle; no code change.</li>
              <li><strong>Aggressive vacuum</strong> on the <code>executions</code> table — it&apos;s the high-churn one.</li>
            </ul>
            <Callout tone="warn">Running embeddings on the same Postgres as the OLTP workload is fine until it&apos;s not. Watch <code>p99(http_request_duration)</code> — if it doubles when a Cognify job runs, move embeddings to Pinecone or a dedicated pgvector.</Callout>
          </div>
        ),
      },
      {
        id: 'scaling-redis',
        title: 'Redis + queues',
        icon: <Layers className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Redis carries: rate-limit counters, KB ingestion job state, the WebSocket broker for real-time updates, the LLM cache, and (when <code>QUEUE_BACKEND=celery</code>) the agent queues themselves.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Default deployment: a single Redis pod, persistence off — fine for ~50 RPS.</li>
              <li>Above 50 RPS, switch to <strong>Redis Cluster mode</strong> (the bundled bitnami chart supports it) and enable AOF persistence.</li>
              <li>Production agent queues run on <strong>NATS JetStream</strong> by default in this Helm chart — see the dedicated NATS topic next.</li>
            </ul>
          </div>
        ),
      },
      {
        id: 'scaling-nats',
        title: 'NATS JetStream — durable agent queues',
        icon: <Zap className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>
              <strong className="text-white">NATS JetStream is the production queue backend</strong> for agent execution. The Helm chart deploys an <code>abenix-nats</code> StatefulSet alongside the API + runtime; KEDA scales the runtime pools by NATS stream depth.
            </p>

            <h4 className="text-white font-semibold pt-3">Why NATS over Redis lists</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>At-least-once delivery</strong> — runtime pod crashes mid-execution → message redelivered. Redis lists can lose un-acked work.</li>
              <li><strong>Replay</strong> — re-stream a window of executions to a debug consumer without re-running them.</li>
              <li><strong>Per-pool subjects</strong> — <code>chat.&gt;</code>, <code>default.&gt;</code>, <code>long-running.&gt;</code>, <code>heavy-reasoning.&gt;</code>; each pool has its own consumer with its own ack-wait + max-deliver settings.</li>
              <li><strong>Built-in observability</strong> — NATS server publishes its own <code>abenix_nats_*</code> metrics that Grafana panels render alongside the runtime pool gauges.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Topology</h4>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`API publishes  ──▶  NATS JetStream stream "agent-runs"
                          │ subjects: chat.>, default.>, long-running.>, heavy-reasoning.>
                          │ retention: workqueue · max_age: 24h · replicas: 3
                          ▼
                  ┌───────┴────────┐
        ┌─────────┴─────────┬──────┴─────────┬─────────────────┐
        ▼                   ▼                ▼                 ▼
  runtime-chat      runtime-default   runtime-long-running  runtime-heavy-reasoning
  (KEDA → 0..100)   (KEDA → 0..200)   (KEDA → 1..20)        (KEDA → 1..10)`}</pre>

            <h4 className="text-white font-semibold pt-3">Toggle + tuning</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Backend selector: <code>QUEUE_BACKEND=nats</code> on the API + runtime pods (Helm default in this chart).</li>
              <li>Connection string: <code>NATS_URL=nats://abenix-nats:4222</code>; auth via <code>NATS_USER</code> + <code>NATS_PASSWORD</code>.</li>
              <li>Stream replicas: bump to 3 for HA: <code>nats stream edit agent-runs --replicas 3</code>.</li>
              <li>Per-subject max-deliver: cap retries before dead-lettering: <code>--max-deliver=4</code>.</li>
              <li>Acknowledge mode: explicit (the runtime acks only after the agent finishes, so a crashing pod re-queues automatically).</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Falling back to Celery + Redis</h4>
            <p>
              Set <code>QUEUE_BACKEND=celery</code> if you want a simpler stack. The runtime detects a missing <code>nats-py</code> client and silently degrades to Celery without redeploy. Useful for laptop dev runs; not recommended above 50 RPS or in any deploy where ack-loss matters.
            </p>
          </div>
        ),
      },
      {
        id: 'scaling-sandbox',
        title: 'Sandbox scaling',
        icon: <Terminal className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Each runtime pod ships Docker / Podman; sandboxes are spawned per-execution. Resource caps live on <code>SandboxImagePolicy</code>: default 512 MB / 30s / no network. Three things matter at scale:</p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li><strong>Image pre-warming</strong> — pull the standard images (python, node, go, …) into the runtime nodes via a DaemonSet. Cold pulls add 8–15s of latency on the first execution per pod.</li>
              <li><strong>Per-tenant quotas</strong> — set <code>tenant.sandbox_concurrency_max</code> so a runaway agent in one tenant can&apos;t exhaust a runtime pod.</li>
              <li><strong>OOM watchdog</strong> — the runtime kills sandboxes that exceed their memory cap and surfaces <code>SANDBOX_OOM</code> on the failed execution. Don&apos;t silence those — they&apos;re a real signal.</li>
            </ol>
          </div>
        ),
      },
      {
        id: 'scaling-vector',
        title: 'Vector backends — pgvector vs Pinecone',
        icon: <Brain className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Each collection picks its own vector backend. Mix freely:</p>
            <table className="w-full text-[12px] my-2">
              <thead className="text-slate-400 border-b border-slate-700">
                <tr><th className="text-left py-1.5">Backend</th><th className="text-left py-1.5">Best for</th><th className="text-left py-1.5">Limits</th></tr>
              </thead>
              <tbody className="text-slate-300">
                <tr className="border-b border-slate-800/60"><td className="py-1.5"><strong>pgvector</strong></td><td>Up to ~5M chunks per collection. In-cluster, no extra cost.</td><td>Single primary; vacuum windows can pause ingestion.</td></tr>
                <tr><td className="py-1.5"><strong>Pinecone</strong></td><td>10M+ chunks; multi-tenant cost amortisation.</td><td>External dep + cost; ~50 ms network round-trip.</td></tr>
              </tbody>
            </table>
            <p>Switch by setting <code>collection.vector_backend</code>. Existing chunks aren&apos;t migrated automatically — re-Cognify the collection.</p>
          </div>
        ),
      },
      {
        id: 'scaling-storage',
        title: 'Object storage',
        icon: <FileText className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>KB documents, code-asset zips, exported PDFs, and BPM-analyzer attachments live on object storage. Default: a PVC inside the cluster (good for dev). Production: S3 / Azure Blob / GCS.</p>
            <p>Set <code>STORAGE_BACKEND=s3</code> and the standard AWS env vars; the API + worker share the bucket through the <code>StorageService</code> abstraction. Multi-region: set the bucket region close to the cluster; large blobs are streamed, not buffered, so latency doesn&apos;t spike memory.</p>
          </div>
        ),
      },
      {
        id: 'scaling-tenants',
        title: 'Tenant fairness + quotas',
        icon: <Users className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Multi-tenant fairness is enforced at three places:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Rate limiter middleware</strong> — per-tenant token bucket on the API, configurable via <code>tenant.rate_limit_per_minute</code>.</li>
              <li><strong>Budget</strong> — per-tenant monthly USD cap; on overage the gate returns <code>BUDGET_EXCEEDED</code>.</li>
              <li><strong>Sandbox concurrency</strong> — described above.</li>
            </ul>
            <p>Surface tenant fairness on the dashboard: the <code>abenix_active_executions{`{tenant_id}`}</code> gauge is per-tenant; Grafana&apos;s &quot;Top tenants&quot; panel highlights the loud neighbours.</p>
          </div>
        ),
      },
      {
        id: 'scaling-multiregion',
        title: 'Multi-region',
        icon: <Globe className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The default Helm chart deploys to one region. For a global footprint:</p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Pick a write region. Postgres + Redis live there. Read replicas in other regions.</li>
              <li>Deploy the full stack per region; route traffic via Cloudflare / Akamai based on lowest latency.</li>
              <li>Set <code>DATABASE_URL_RO</code> in non-write regions so list endpoints stay local.</li>
              <li>Object storage: prefer a single bucket with cross-region replication enabled.</li>
              <li>LLM provider keys: keep one set globally; provider rate-limits aggregate across regions.</li>
            </ol>
            <Callout tone="warn">Cross-region writes are eventually consistent. The Atlas time-slider is an exception — it serialises through the write region. If you need strict regional isolation, deploy independent clusters and federate via the SDK.</Callout>
          </div>
        ),
      },
      {
        id: 'admin-scaling',
        title: 'Scaling Console',
        icon: <Gauge className="w-4 h-4" />,
        badge: 'admin',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The <code className="text-cyan-300">/admin/scaling</code> page lets admins tune scaling without a helm upgrade. Per-pool min/max replicas, KEDA <code>listLength</code>, sandbox concurrency caps — change values, click Apply, the API reconciles them via the kube API.</p>
            <Hero src={SS('23-admin-scaling.png')} alt="Scaling console" />
          </div>
        ),
      },
      {
        id: 'observability',
        title: 'Observability — Prometheus + Grafana',
        icon: <BarChart3 className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Pre-wired observability ships with <code>scripts/deploy.sh</code>. <strong>Prometheus</strong> scrapes <code>/api/metrics</code> on the API every 15s; <strong>Grafana</strong> renders the bundled &quot;Abenix Operations&quot; dashboard.</p>
            <Hero src={SS('09-grafana-dashboard.png')} alt="Grafana — Abenix Operations dashboard" caption="Operations Overview — LLM spend, tokens, execution outcomes, failure breakdown by code, stale sweeps" />
            <Callout tone="info">
              Grafana is intentionally <strong>not exposed on the public ingress</strong>. Reach it via port-forward:
              <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 mt-2 overflow-x-auto">{`kubectl -n abenix port-forward svc/abenix-grafana 3030:3000
# Then browse http://localhost:3030 (admin / abenix-admin)`}</pre>
            </Callout>
            <p><strong className="text-white">Metrics emitted:</strong></p>
            <ul className="list-disc pl-5 space-y-0.5 text-[12px] font-mono">
              <li>abenix_execution_outcomes_total{`{outcome,failure_code,agent_type}`}</li>
              <li>abenix_llm_tokens_provider_total{`{provider,model,direction}`}</li>
              <li>abenix_llm_cost_usd_provider_total{`{provider,model}`}</li>
              <li>abenix_llm_call_duration_provider_seconds (histogram)</li>
              <li>abenix_sandbox_runs_total{`{backend,image_family,outcome}`}</li>
              <li>abenix_sandbox_run_duration_seconds (histogram)</li>
              <li>abenix_active_executions{`{tenant_id}`}</li>
              <li>abenix_stale_sweeps_total{`{reason}`}</li>
              <li>abenix_notifications_sent_total{`{channel,severity}`}</li>
              <li>abenix_tool_calls_total{`{tool_name,outcome}`}</li>
              <li>abenix_http_requests_total + abenix_http_request_duration_seconds</li>
            </ul>
            <h4 className="text-white font-semibold pt-3">Notification fan-out</h4>
            <ul className="list-disc pl-5 space-y-0.5 text-[12px]">
              <li><strong>WebSocket</strong> — always on; powers the bell.</li>
              <li><strong>Slack</strong> — set <code>ABENIX_SLACK_WEBHOOK_URL</code>. Per-user opt-in via Settings.</li>
              <li><strong>Email</strong> — set <code>SMTP_HOST / SMTP_USER / SMTP_PASS / SMTP_FROM</code>.</li>
            </ul>
            <h4 className="text-white font-semibold pt-3">Stale-execution sweeper</h4>
            <p>An APScheduler job runs every 5 minutes and marks any execution still <code>RUNNING</code> for &gt;<code>STALE_EXECUTION_MAX_MINUTES</code> (default 30) as <code>FAILED</code> with <code>failure_code=STALE_SWEEP</code>. A Postgres advisory lock ensures only one API replica runs the sweep per interval.</p>
          </div>
        ),
      },
      {
        id: 'admin-llm-pricing',
        title: 'LLM pricing & routing',
        icon: <DollarSign className="w-4 h-4" />,
        badge: 'admin',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Cost is an operations problem at scale. The two admin pages tackle it:</p>
            <Hero src={SS('25-admin-llm-pricing.png')} alt="LLM pricing" />
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><code>/admin/llm-pricing</code> — provider × model price overrides. The router multiplies these by <code>tokens_in × cost_in + tokens_out × cost_out</code> and writes per-execution cost.</li>
              <li><code>/admin/llm-settings</code> — which models are exposed to which agents. Disable expensive models tenant-wide; force a fallback to cheaper ones.</li>
            </ul>
            <Hero src={SS('24-admin-llm-settings.png')} alt="Model selection" />
          </div>
        ),
      },
    ],
  },
  // MARKETPLACE / CREATOR
  {
    id: 'monetize',
    label: 'Marketplace',
    blurb: 'Publish, discover, and monetise agents.',
    topics: [
      {
        id: 'marketplace',
        title: 'Marketplace',
        icon: <Store className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Browse agents and pipelines published by other creators. Install one into your tenant with a click — it copies the spec, attaches your KBs, and is ready to run.</p>
            <Hero src={SS('21-marketplace.png')} alt="Marketplace" />
          </div>
        ),
      },
      {
        id: 'creator-hub',
        title: 'Creator Hub',
        icon: <DollarSign className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Publish your own agents. Set price (free / per-call / monthly), pick a license, define usage limits. Earnings show up in the Creator Hub dashboard.</p>
            <Hero src={SS('22-creator-hub.png')} alt="Creator Hub" />
          </div>
        ),
      },
    ],
  },
  // WORKSPACE
  {
    id: 'workspace',
    label: 'Workspace',
    blurb: 'Settings, integrations, and access control.',
    topics: [
      {
        id: 'mcp',
        title: 'MCP Servers',
        icon: <Plug className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The Model Context Protocol lets you wire in external servers (filesystem, browser, database, custom) so their tools become available to every agent. Register the URL — Abenix introspects the manifest and surfaces the tools.</p>
            <Hero src={SS('detail-mcp-config.png')} alt="MCP servers" />
          </div>
        ),
      },
      {
        id: 'api-keys',
        title: 'API Keys',
        icon: <Key className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Mint platform keys for SDK use. Scopes: <code>execute</code>, <code>read</code>, <code>write</code>, <code>can_delegate</code>. Bcrypt-hashed at rest; the plaintext is shown once at creation.</p>
            <Hero src={SS('27-api-keys.png')} alt="API keys" />
            <h4 className="text-white font-semibold pt-3">actAs delegation</h4>
            <p>For third-party apps holding a platform key: pass <code>X-Abenix-Subject: &lt;end-user-id&gt;</code> on every request. The runtime treats the request as if that subject were calling, and applies row-level RBAC accordingly.</p>
          </div>
        ),
      },
      {
        id: 'tenants-users-permissions',
        title: 'Tenants, users, and permissions',
        icon: <ShieldCheck className="w-4 h-4" />,
        badge: 'Read first',
        body: (
          <div className="space-y-4 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Abenix is multi-tenant by design. The model is intentionally small enough to fit on one page, and every endpoint enforces it server-side regardless of what the UI shows.</p>

            {/* Hierarchy diagram */}
            <figure className="rounded-xl overflow-hidden border border-slate-700/60 bg-slate-950/40 p-4 my-3">
              <svg viewBox="0 0 760 360" className="w-full h-auto">
                <defs>
                  <marker id="tup-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
                  </marker>
                </defs>
                <text x="380" y="22" textAnchor="middle" fill="#94a3b8" fontSize="10">ACCESS-CONTROL HIERARCHY</text>

                <rect x="40" y="50" width="680" height="50" rx="8" fill="#0f172a" stroke="#7c3aed" />
                <text x="380" y="72" textAnchor="middle" fill="#e9d5ff" fontSize="13" fontWeight="bold">Tenant</text>
                <text x="380" y="90" textAnchor="middle" fill="#94a3b8" fontSize="11">your organisation · complete isolation from every other tenant on the platform</text>

                <rect x="80" y="125" width="280" height="60" rx="8" fill="#0f172a" stroke="#06b6d4" />
                <text x="220" y="148" textAnchor="middle" fill="#a5f3fc" fontSize="12" fontWeight="bold">Users</text>
                <text x="220" y="166" textAnchor="middle" fill="#94a3b8" fontSize="10">role ∈ admin · creator · user</text>
                <text x="220" y="180" textAnchor="middle" fill="#64748b" fontSize="10">+ per-user quotas · profile</text>

                <rect x="400" y="125" width="280" height="60" rx="8" fill="#0f172a" stroke="#10b981" />
                <text x="540" y="148" textAnchor="middle" fill="#bbf7d0" fontSize="12" fontWeight="bold">Tenant settings</text>
                <text x="540" y="166" textAnchor="middle" fill="#94a3b8" fontSize="10">feature flags · retention</text>
                <text x="540" y="180" textAnchor="middle" fill="#64748b" fontSize="10">moderation policy · DLP</text>

                <rect x="80" y="210" width="280" height="50" rx="8" fill="#0f172a" stroke="#f59e0b" />
                <text x="220" y="232" textAnchor="middle" fill="#fde68a" fontSize="12" fontWeight="bold">Resolved permissions</text>
                <text x="220" y="248" textAnchor="middle" fill="#94a3b8" fontSize="10">/api/me/permissions per request</text>

                <rect x="400" y="210" width="280" height="50" rx="8" fill="#0f172a" stroke="#a855f7" />
                <text x="540" y="232" textAnchor="middle" fill="#ddd6fe" fontSize="12" fontWeight="bold">ResourceShare grants</text>
                <text x="540" y="248" textAnchor="middle" fill="#94a3b8" fontSize="10">per-resource cross-team handoff</text>

                <rect x="220" y="290" width="320" height="50" rx="8" fill="#0f172a" stroke="#3b82f6" />
                <text x="380" y="312" textAnchor="middle" fill="#dbeafe" fontSize="12" fontWeight="bold">actAs delegation (X-Abenix-Subject)</text>
                <text x="380" y="328" textAnchor="middle" fill="#94a3b8" fontSize="10">multiplex N end-users through one platform key</text>

                <line x1="380" y1="100" x2="220" y2="125" stroke="#475569" strokeWidth="1.5" markerEnd="url(#tup-arr)" />
                <line x1="380" y1="100" x2="540" y2="125" stroke="#475569" strokeWidth="1.5" markerEnd="url(#tup-arr)" />
                <line x1="220" y1="185" x2="220" y2="210" stroke="#475569" strokeWidth="1.5" markerEnd="url(#tup-arr)" />
                <line x1="540" y1="185" x2="540" y2="210" stroke="#475569" strokeWidth="1.5" markerEnd="url(#tup-arr)" />
                <line x1="540" y1="185" x2="222" y2="212" stroke="#475569" strokeWidth="1" strokeDasharray="3 3" />
                <line x1="220" y1="260" x2="380" y2="290" stroke="#475569" strokeWidth="1.5" markerEnd="url(#tup-arr)" />
                <line x1="540" y1="260" x2="380" y2="290" stroke="#475569" strokeWidth="1.5" markerEnd="url(#tup-arr)" />
              </svg>
            </figure>

            <h4 className="text-white font-semibold pt-3">1 · Where tenants come from</h4>
            <p>Every tenant is created <strong>automatically on signup</strong>. The first time anyone registers via the auth screen, the API:</p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Inserts a fresh row into <code>tenants</code>.</li>
              <li>Inserts the registering user with <code>role=admin</code> and <code>tenant_id</code> = that new row.</li>
              <li>Mints a JWT scoped to that tenant.</li>
            </ol>
            <p className="text-[12px] text-slate-400">
              There is <strong>no global super-admin endpoint</strong> that lists or creates tenants. The seeded <code>admin@abenix.dev</code> account is admin of the seeded tenant only — it can&apos;t see any other tenant&apos;s data. To run N organisations on one Abenix instance, have one person from each organisation register; they each get their own tenant + admin.
            </p>

            <h4 className="text-white font-semibold pt-3">2 · Adding users to a tenant</h4>
            <p>Open <code>/settings/team</code> as the tenant admin. Two paths:</p>
            <table className="w-full text-[12px] my-2">
              <thead className="text-slate-400 border-b border-slate-700">
                <tr><th className="text-left py-2">Path</th><th className="text-left py-2">API</th><th className="text-left py-2">When to use</th></tr>
              </thead>
              <tbody className="text-slate-300">
                <tr className="border-b border-slate-800/60">
                  <td className="py-2"><strong>Invite by email</strong></td>
                  <td><code>POST /api/team/invite</code></td>
                  <td>Real users; they accept via emailed link, set their own password.</td>
                </tr>
                <tr>
                  <td className="py-2"><strong>Dev create</strong></td>
                  <td><code>POST /api/team/dev-create-member</code></td>
                  <td>E2E tests / immediate provisioning; admin sets the password.</td>
                </tr>
              </tbody>
            </table>
            <Hero src={SS('26-team.png')} alt="Team management page" />
            <Callout tone="info">
              Both paths require <code>role=admin</code> and hard-scope the new user to the caller&apos;s tenant — <strong>no cross-tenant invites are possible</strong>. The backend enforces the scope on the route, not just the UI.
            </Callout>

            <h4 className="text-white font-semibold pt-3">3 · Roles</h4>
            <p>Three roles, hot-applied (next request reads the new role from <code>/api/me/permissions</code>):</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>admin</strong> — full control inside the tenant. Can invite, change roles, set quotas, configure tenant settings, see all members&apos; activity, hit every <code>/admin/*</code> page.</li>
              <li><strong>creator</strong> — same as user, plus can publish agents/pipelines to the marketplace and earn from subscriptions.</li>
              <li><strong>user</strong> — default. Builds and runs their own agents; cannot manage team / quotas / tenant settings.</li>
            </ul>
            <p className="text-[12px]">Change a member&apos;s role: <code>PUT /api/team/members/{`{id}`}/role</code> with body <code>{`{"role": "admin" | "creator" | "user"}`}</code>.</p>

            <h4 className="text-white font-semibold pt-3">4 · Per-user quotas</h4>
            <p>Each member gets independent caps so a runaway agent in one user&apos;s account can&apos;t drain the tenant&apos;s budget:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Monthly USD spend cap.</li>
              <li>Executions per day.</li>
              <li>Tokens (input + output) per day.</li>
            </ul>
            <p className="text-[12px]">Set via <code>PUT /api/team/members/{`{id}`}/quota</code>. Overage returns <code>BUDGET_EXCEEDED</code> on the next execution.</p>

            <h4 className="text-white font-semibold pt-3">5 · Per-feature flags</h4>
            <p>The 3 roles drive coarse access; <strong>feature flags</strong> drive fine-grained access. Every sidebar item declares a <code>feature</code> string (<code>view_dashboard</code>, <code>use_kb</code>, <code>use_atlas</code>, <code>manage_team</code>, <code>use_marketplace</code>, …). The frontend renders the sidebar from <code>/api/me/permissions</code>, which resolves:</p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Default flags from the user&apos;s role.</li>
              <li>Tenant overrides applied on top (admin can disable a feature for everyone, e.g. turn off Marketplace for an enterprise deployment).</li>
              <li>The merged map is returned and consumed.</li>
            </ol>
            <Callout tone="warn">
              The sidebar is a UX hint, <strong>not</strong> the security boundary. Every route on the API independently re-checks role + feature flag. Hiding a sidebar item without disabling the feature flag does not actually deny access.
            </Callout>

            <h4 className="text-white font-semibold pt-3">6 · Per-resource sharing</h4>
            <p>The <code>ResourceShare</code> table grants a specific user <code>READ</code> or <code>EDIT</code> on a specific agent / pipeline / KB / atlas — without changing their role. Click <strong>Share</strong> on any agent / KB / atlas detail page; pick teammates + scope. Used for cross-team handoffs without elevating roles.</p>
            <p className="text-[12px]">A <code>creator</code> shared into <code>EDIT</code> on a single agent gets to edit only that one agent — nothing else changes about their permissions. Revoking a share is instant; the next API call from that user will fail.</p>

            <h4 className="text-white font-semibold pt-3">7 · Multiplexing many end-users through one tenant — actAs</h4>
            <p>When a SaaS app holds a platform API key and serves many end-users (a typical &quot;build on top of Abenix&quot; scenario), the app passes <code>X-Abenix-Subject: &lt;end-user-id&gt;</code> on every request. The API treats the request as if that subject were calling — applies row-level RBAC, attributes audit-log events to that subject, scopes resource lookups to subject-bound collections.</p>
            <p className="text-[12px]">Critical property: <strong>the actAs subject can&apos;t escape the agent&apos;s tenant</strong>. Rows still belong to the agent&apos;s <code>tenant_id</code>; cross-app reads remain impossible at the SQL layer. The subject is a sub-identity inside the tenant, not a different tenant.</p>
            <p className="text-[12px]">API key needs the <code>can_delegate</code> scope. Mint via <code>/settings/api-keys</code>.</p>

            <h4 className="text-white font-semibold pt-3">8 · Tenant isolation under the hood</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Every readable row carries a <code>tenant_id</code> indexed for fast filter.</li>
              <li><code>TenantMiddleware</code> resolves the caller&apos;s tenant once per request from the JWT or API key.</li>
              <li>Routers add <code>WHERE tenant_id = :user.tenant_id</code> at the top of every query — no exceptions.</li>
              <li>Cross-tenant reads return <code>404</code> (never <code>403</code>) so probing can&apos;t enumerate other tenants.</li>
              <li>The vector backends (pgvector / Pinecone) enforce the same <code>tenant_id</code> filter at the index level so even a maliciously-shared agent can&apos;t walk to a different tenant&apos;s embeddings.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">9 · The end-to-end &quot;I want N organisations&quot; flow</h4>
            <Steps items={[
              'Each organisation has one person sign up at <code>/</code>. That mints their tenant + makes them admin.',
              'They open <code>/settings/team</code> and invite teammates by email; choose <code>admin</code> / <code>creator</code> / <code>user</code> per invite.',
              'Teammates click the email link, set a password, are dropped into the same tenant with the assigned role.',
              'Admin sets per-user quotas in <code>Settings → Team → ⋮ → Quotas</code>.',
              'Resource-level sharing happens organically — every Share button on an agent / KB / atlas page goes through ResourceShare.',
              'For SaaS apps fronting many end-users: mint a platform API key with <code>can_delegate</code>, pass <code>X-Abenix-Subject</code> per request.',
            ]} />

            <h4 className="text-white font-semibold pt-3">10 · What&apos;s not in the platform today</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>No global <em>super-admin</em> cockpit listing/creating/hopping into all tenants.</li>
              <li>No SSO / SAML / OIDC / SCIM (auth is JWT + email/password today).</li>
              <li>No &quot;my organisations&quot; picker (one user = one tenant).</li>
              <li>No custom roles beyond the three (you can simulate them with feature-flag overrides + ResourceShare).</li>
            </ul>
            <p className="text-[12px] italic text-slate-400">All four are tracked as roadmap items. PRs welcome.</p>
          </div>
        ),
      },
      {
        id: 'team',
        title: 'Team — managing this tenant',
        icon: <Users className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The <strong>Team</strong> page at <code>/settings/team</code> is where the tenant admin manages members, roles, quotas, and pending invites. See the <a href="#tenants-users-permissions" className="text-violet-300 underline">Tenants, users, and permissions</a> topic above for the full model.</p>
            <Hero src={SS('26-team.png')} alt="Team management" />
          </div>
        ),
      },
      {
        id: 'settings',
        title: 'Settings',
        icon: <Settings className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Per-user preferences: theme, default model, notification opt-ins (Slack / email severity), shortcut keys.</p>
            <Hero src={SS('28-settings.png')} alt="Settings" />
          </div>
        ),
      },
    ],
  },
];

// ─── Page shell ──────────────────────────────────────────────────────

export default function HelpPage() {
  const [active, setActive] = useState<string>('welcome');
  const sectionsRef = useRef<Map<string, HTMLElement>>(new Map());

  // IntersectionObserver to highlight the current section in the sidebar.
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter(e => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: '-25% 0px -60% 0px', threshold: [0, 0.25, 0.5] },
    );
    sectionsRef.current.forEach(el => obs.observe(el));
    return () => obs.disconnect();
  }, []);

  const scrollTo = (id: string) => {
    sectionsRef.current.get(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="min-h-screen bg-[#0B0F19]">
      {/* Top header */}
      <header className="sticky top-0 z-30 backdrop-blur-md bg-[#0B0F19]/80 border-b border-slate-800/60 px-6 py-3 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500/30 to-cyan-500/30 border border-violet-500/40 flex items-center justify-center">
          <BookOpen className="w-4 h-4 text-violet-300" />
        </div>
        <div>
          <h1 className="text-base font-bold text-white">User guide</h1>
          <p className="text-[10px] text-slate-500 uppercase tracking-wider">Abenix — every feature, every page, every scaling lever</p>
        </div>
      </header>

      <div className="flex max-w-[1600px] mx-auto">
        {/* Sticky sidebar TOC */}
        <aside className="w-64 shrink-0 border-r border-slate-800/60 sticky top-[57px] h-[calc(100vh-57px)] overflow-y-auto p-4">
          <nav className="space-y-5">
            {categories.map(cat => (
              <div key={cat.id}>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">{cat.label}</p>
                <ul className="space-y-0.5">
                  {cat.topics.map(t => (
                    <li key={t.id}>
                      <button
                        onClick={() => scrollTo(t.id)}
                        className={`w-full text-left px-2 py-1 rounded text-[12px] flex items-center gap-1.5 transition-colors ${
                          active === t.id
                            ? 'bg-violet-500/15 text-violet-200 border border-violet-500/30'
                            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
                        }`}
                      >
                        <ChevronRight className={`w-3 h-3 shrink-0 ${active === t.id ? 'text-violet-300' : 'text-slate-600'}`} />
                        <span className="flex-1 truncate">{t.title}</span>
                        {t.badge && <Pill tone={t.badge === 'admin' ? 'amber' : t.badge === 'flagship' ? 'violet' : 'cyan'}>{t.badge}</Pill>}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-w-0 px-8 py-8 max-w-4xl">
          {categories.map((cat) => (
            <div key={cat.id} className="mb-12">
              <header className="mb-6 pb-3 border-b border-slate-800/60">
                <p className="text-[10px] uppercase tracking-wider text-violet-300 font-bold">{cat.label}</p>
                {cat.blurb && <p className="text-[12px] text-slate-500 mt-1">{cat.blurb}</p>}
              </header>
              <div className="space-y-12">
                {cat.topics.map(t => (
                  <section
                    key={t.id}
                    id={t.id}
                    ref={(el) => { if (el) sectionsRef.current.set(t.id, el); }}
                    className="scroll-mt-24"
                  >
                    <div className="flex items-center gap-3 mb-3">
                      {t.icon && <span className="text-violet-300">{t.icon}</span>}
                      <h2 className="text-xl font-bold text-white">{t.title}</h2>
                      {t.badge && <Pill tone={t.badge === 'admin' ? 'amber' : t.badge === 'flagship' ? 'violet' : 'cyan'}>{t.badge}</Pill>}
                    </div>
                    {t.body}
                  </section>
                ))}
              </div>
            </div>
          ))}

          <footer className="mt-12 mb-20 pt-6 border-t border-slate-800/60 text-[12px] text-slate-500">
            <p>Found a gap or an out-of-date section? Open a PR — see <code className="text-cyan-300">CONTRIBUTING.md</code> in the repo.</p>
          </footer>
        </main>
      </div>
    </div>
  );
}
