'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, Archive, ArrowRight, BarChart3, BookOpen, Bot, Brain,
  Camera, Check, ChevronRight, Code2, Compass, Cpu, Database,
  DollarSign, Eye, FileJson, FileText, Gauge, GitBranch, Globe,
  HelpCircle, Key, Layers, Library, Link2, Network, Plug, Radio, Route,
  ScanLine, Search, Settings, Shield, ShieldCheck, Sparkles, Store,
  Terminal, Upload, UserCircle2, Users, Wand2, Workflow, Wrench, Zap,
  Bell, FlaskConical, History, ListChecks, OctagonX, Radar, Scale, ShieldAlert, UserCog,
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
            <p>Abenix is the open-source platform for building AI agents that <em>think in graphs</em>. You drop in your domain knowledge as documents, ontologies, or live data, Abenix turns it into a typed graph, agents traverse the graph to answer questions, run pipelines, or act on schedules.</p>
            <p>Three things make Abenix different from every other agent platform:</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <FeatureCard icon={Network} accent="violet" title="Atlas — ontology + KB canvas" body="Documents and concepts share one canvas. Drop a PDF, type a sentence, draw a relationship. Agents query the graph, not raw vectors." />
              <FeatureCard icon={Brain} accent="cyan" title="Knowledge Engine" body="Graph-aware retrieval. Token cost drops 5–10× because agents read curated evidence, not noisy near-neighbours." />
              <FeatureCard icon={Workflow} accent="emerald" title="Pipelines + 100+ tools" body="Visual builder for multi-agent DAGs. Switch nodes, loops, sandboxed code, MCP integrations." />
            </div>
            <Hero src={SS('04-atlas-canvas.png')} alt="Atlas — thinking in graphs" caption="Atlas — drop documents, draw concepts, edges and instances live on one canvas" />
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
              'Read <strong>Decisions</strong> and <strong>Governance</strong> when an agent must follow business rules, needs sign-off or must be stoppable.',
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
        id: 'tools-reference',
        title: 'Tools reference — the tool catalog',
        icon: <Wrench className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p><strong className="text-white">Tools</strong> is the catalog of everything an agent can call. Each entry shows its name, what it does, and the arguments it takes. An agent only gets the tools named in its own config, so the catalog is the menu, not the grant.</p>
            <p><strong className="text-white">Rough shape of the catalog:</strong></p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Retrieval</strong> — knowledge_search, vector_search, graph_explorer, web_search.</li>
              <li><strong className="text-white">Data</strong> — database_query, csv_analyzer, spreadsheet_analyzer, tsdb_query, market_data.</li>
              <li><strong className="text-white">Compute</strong> — code_executor, sandboxed_job, code_asset, ml_model, financial_calculator.</li>
              <li><strong className="text-white">Documents</strong> — document_extractor, image_analyzer, speech_to_text, text_to_speech.</li>
              <li><strong className="text-white">Actions</strong> — http_client, email_sender, mqtt_publish, opcua_write, github, integration_hub.</li>
              <li><strong className="text-white">Control</strong> — agent_step, sub_pipeline, human_approval, defer_to_human, memory_store.</li>
            </ul>
            <p>Two things catch people out. A tool needing a credential the platform does not have reports &quot;tool not configured&quot; rather than failing the run. And <code className="text-amber-300">knowledge_search</code> is only registered when the agent has a knowledge base granted to it — without a grant the agent will tell you it has no way to look anything up.</p>
            <p>Add your own with <strong className="text-white">MCP</strong> for an external server, or <strong className="text-white">Code Runner</strong> to turn a repo into a callable tool.</p>
          </div>
        ),
      },
      {
        id: 'executions',
        title: 'Executions & the Flight Recorder',
        icon: <Activity className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p><strong className="text-white">Executions</strong> lists every run for your tenant, newest first, with status, duration, cost and token count. Click a row to open the Flight Recorder for that run.</p>
            <p>The <strong className="text-white">Flight Recorder</strong> is the execution detail page. It replays a run node by node: the input each node received, the output it produced, every tool call with its arguments and result, the model that actually served each call, and a waterfall of where the time went.</p>
            <p><strong className="text-white">Reading a failed run:</strong></p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>The <code className="text-amber-300">failure_code</code> badge on the row says what class of failure it was. <code className="text-amber-300">SANDBOX_TIMEOUT</code> means the run hit its budget — see Platform settings to raise it.</li>
              <li>A node whose output is <code className="text-amber-300">[not available]</code> did not run or produced nothing its downstream nodes could read. Look at the node above it, not the one that reports the gap.</li>
              <li>An amber <strong className="text-white">fallback</strong> dot means the requested model was not the one that served the call. Hover it for the reason.</li>
              <li>A node answering in prose where the pipeline expects JSON usually means a tool it needed was unavailable. The tool-call list shows what it actually had.</li>
            </ul>
            <p><strong className="text-white">Executions &rarr; Live</strong> streams the same view for runs in flight, so you can watch a long pipeline progress rather than waiting for it to land.</p>
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
              'Click an agent to see its full config, click <strong>Run</strong> to fire a one-shot, or <strong>Chat</strong> to open a thread.',
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
              <li><code>STALE_SWEEP</code> — owning pod crashed, sweeper marked the run failed</li>
              <li><code>MODERATION_BLOCKED</code> — moderation gate refused the input/output</li>
              <li><code>INFRA_CRASH</code> · <code>INFRA_AUTH_ERROR</code> · <code>LLM_AUTH_ERROR</code> (provider rejected the key, re-sync the subscription token or fix it under Tool Configuration) · <code>UNKNOWN_ERROR</code></li>
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
              'Use the AI Builder field — describe what you want in one sentence, a draft pops onto the canvas.',
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
        id: 'pipeline-inputs',
        title: 'Pipeline inputs',
        icon: <ListChecks className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>A pipeline can declare the values a caller must give it, such as a date, a postcode and a weight. Declared inputs become form fields in chat and in the SDK playground, and the steps read them by name. No step has to dig them out of a chat message.</p>
            <Steps items={[
              'Open <strong>Agent Builder</strong> and switch to <strong>Pipeline</strong> mode.',
              'With no step selected, the overview panel shows <strong>Input Parameters</strong>. Click <strong>Add</strong> once per value.',
              'Give each one a name, a type (Text, Number, Yes/No, URL, File, DB Conn or Dropdown), a description people will see, and tick <strong>required</strong> where the pipeline cannot run without it. A Dropdown takes its options, comma separated, in Default value.',
              'In any step argument or prompt, write <code>{{input.ship_date}}</code> to use the value. The panel lists the placeholder for each input so you can copy it.',
              'Save and publish. The inputs are stored on the pipeline, so every caller sees the same form.',
            ]} />
            <p>In chat, the fields sit above the message box and required ones must be filled before the run starts. From the SDK, pass them as the <code className="text-cyan-300">context</code> of the run. Agents in agent mode can declare inputs the same way on the Advanced tab.</p>
            <Callout tone="info">Names must be unique. The editor marks a second input with the same name before you save.</Callout>
          </div>
        ),
      },
      {
        id: 'decisions',
        title: 'Decisions: business rules',
        icon: <Scale className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>A decision takes facts, such as a shipment date, a postcode and a weight, and returns outcomes, such as a surcharge, from rules people can read. The same facts and the same version always give the same answer, with a trace of which rule applied and the values it looked at. Agents call decisions instead of guessing at thresholds in a prompt.</p>
            <p><strong className="text-white">Who can do what.</strong> Seeing decisions needs <code>decisions.view</code>, writing them <code>decisions.author</code>, making an approved version live <code>decisions.publish</code>. Users can view and evaluate, creators can also author, admins hold everything. An admin can hand out the rest under <a href="#permissions" className="text-violet-300 underline">Permissions</a>.</p>

            <h4 className="text-white font-semibold pt-3">Create one</h4>
            <Steps items={[
              'Open <strong>Build &rarr; Decisions</strong> and click <strong>New decision</strong>, or pick a card on the empty page.',
              'Choose how to start: <strong>Blank</strong>, <strong>Import JSON</strong> (one rule, a list, or an object with a rules list) or the <strong>Surcharge example</strong>.',
              'Give it a name. The key fills in from the name and is what agents and apps call it by. It takes lowercase letters, digits, dots, dashes and underscores.',
              'Say what it decides, pick a <strong>risk tier</strong> (Low, Medium, High, Critical), then <strong>Create and open</strong>. Higher tiers need more sign-off before a version goes live.',
            ]} />

            <h4 className="text-white font-semibold pt-3">Facts and outcomes</h4>
            <p>The <strong>Facts and outcomes</strong> tab lists what callers send in and what the decision returns. A fact has a path such as <code>shipment.postcode</code>, a label and a type: text, number, yes/no, date or list. Types are checked before any rule runs. A fact or outcome still used by a rule cannot be removed until the rule stops using it. You can also add facts on the fly from the rule builder by typing a new path.</p>

            <h4 className="text-white font-semibold pt-3">Rules view</h4>
            <p>The default view. Rules are listed on the left and edited one at a time on the right.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Conditions.</strong> Pick a fact, then a comparison that fits its type. Dates get before, after and between. Numbers get more than, at least and between. Text gets is one of, starts with and is in reference set. Group conditions as <em>all of</em>, <em>any of</em> or <em>none of</em>, and drag them to reorder or into groups. A rule with no conditions always applies, which makes a good default at the end.</li>
              <li><strong className="text-white">Then.</strong> Set each outcome to a fixed value, or switch it to a formula such as <code>shipment.parcelCount * 2.1</code>. Fact names complete as you type.</li>
              <li><strong className="text-white">Rule key, meaning and sources.</strong> The rule key shows in results as the rule that applied. Write what the rule means in plain words and add the citations it rests on, such as a tariff section.</li>
              <li><strong className="text-white">Facts it needs.</strong> If any is missing the answer is <em>missing facts</em>, never a guess.</li>
              <li><strong className="text-white">Dates per rule.</strong> Leave them empty to follow the version&apos;s dates, or set when this one rule applies. The end date is not included.</li>
              <li><strong className="text-white">On or off.</strong> A rule switched off is skipped without being deleted.</li>
              <li><strong className="text-white">Hit policy.</strong> <em>First match wins</em> checks rules top to bottom and stops at the first that matches. <em>Every match applies</em> returns a list with one entry per matching rule.</li>
            </ul>
            <p>A sentence under the rule reads it back in plain words, so a reviewer can check it without learning the builder. Problems show at the field as you type: an unknown fact, a value of the wrong type, a range the wrong way round, a formula that does not parse, or a rule hidden by one above it.</p>

            <h4 className="text-white font-semibold pt-3">Table view</h4>
            <p>One row per rule, one column per fact and outcome. Type conditions straight into cells: <code>&gt; 50</code>, <code>&gt;= 2026-01-01</code>, <code>a, b, c</code>, <code>in REMOTE_POSTCODES</code> or <code>between 1 and 5</code>. An empty cell means any value. <strong>Paste rows from Excel</strong>, with or without a header row, and export to CSV. Drag rows to reorder.</p>

            <h4 className="text-white font-semibold pt-3">Flow view</h4>
            <p>Shows the decision your rules compile to. For multi-step logic with switches, expressions, functions and chained tables, choose to edit the draft as a flow. From then on that draft is a flow, and the rule builder and table no longer apply to it. Start a new draft from a builder version to go back.</p>

            <h4 className="text-white font-semibold pt-3">Try it and golden tests</h4>
            <p>The <strong>Try it</strong> panel runs your unsaved changes as you edit. Enter the facts and the <em>date of the activity</em>, and it shows the outcome, which rule applied, the values it looked at and how long it took. The result is one of these:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Decided</strong>, a rule applied.</li>
              <li><strong className="text-white">No match</strong>, no rule applied, so this decision requires nothing.</li>
              <li><strong className="text-white">Missing facts</strong>, with the list of facts to give before it can decide.</li>
              <li><strong className="text-white">Facts with the wrong type</strong>, for example text where a number belongs.</li>
            </ul>
            <p>When the answer is right, name the case and click <strong>Keep as test</strong>. It becomes a golden test. The <strong>Golden tests</strong> tab lists them and runs them all against any version. Every new version must still give these answers, or the change has to be explained.</p>

            <h4 className="text-white font-semibold pt-3">Working together</h4>
            <p>Drafts save themselves. The header shows <em>All changes saved</em> and names anyone else editing the same draft. If someone saves first, their changes and yours are combined rule by rule. You are only asked to choose where you both changed the same rule.</p>
            <p><strong>Import</strong> takes typed JSON rules and either adds and updates by rule key or replaces everything. <strong>Export</strong> downloads the version as JSON, ready to import elsewhere.</p>
          </div>
        ),
      },
      {
        id: 'decision-versions',
        title: 'Decisions: check, propose, publish',
        icon: <GitBranch className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Every change is a numbered version. A version is a draft, then proposed, then approved, then published. Nothing is deleted. A correction is a new version.</p>
            <Steps items={[
              'Set the period the version applies to, under <strong>This version applies</strong>. Leave the end open unless the rules stop on a known date. Add a note under <strong>What changed and why</strong>.',
              'Click <strong>Check</strong>. It validates the rules, runs the golden tests and compares the answers with the version in force, over the golden tests and recent recorded evaluations. Every answer that would change is listed.',
              'Click <strong>Propose for sign-off</strong>. The button shows how many approvals the tier needs. Low and Medium need none by default, High needs one person who did not author it, Critical needs two. Until someone acts you can <strong>Withdraw</strong> it back to a draft.',
              'Approvers find it on <strong>Approvals</strong> as a <em>rule change</em>, with a link to the rules and what changes. They approve, deny, or return it for changes with a note you will see on the draft.',
              'Once approved, click <strong>Publish</strong>. The dialog says when it applies and which versions it ends. A version whose period would be split in two is refused, with the fix. Agents and apps use the new version within seconds.',
            ]} />
            <p><strong className="text-white">Versions and dates.</strong> The version picker shows each version and its state. Pick one and choose <strong>New draft from it</strong> to start the next change. The <strong>History</strong> tab draws a bar per version for the period it applies to, with the dates it was published and replaced, and compares any two versions rule by rule.</p>
            <p>Two dates matter when a decision is asked a question. The <em>date of the activity</em> picks the version that applies to it, so a shipment from last March gets last March&apos;s rules. The optional <em>known at</em> date answers as the rules were known on that day, so an answer given last year can be repeated exactly, even after a later correction.</p>
            <Callout tone="info">Changing a decision&apos;s risk tier applies to the next version you propose. Versions already waiting keep the sign-off rules they were proposed under. Publishing needs the <code>decisions.publish</code> capability as well as the approvals.</Callout>
          </div>
        ),
      },
      {
        id: 'reference-sets',
        title: 'Reference sets',
        icon: <Layers className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>A reference set is a named list that rules check against, such as remote postcode areas or covered product codes. Keeping the list outside the rules means it can change without rewriting them.</p>
            <Steps items={[
              'On <strong>Decisions</strong>, click <strong>Reference sets</strong>, then <strong>New</strong>.',
              'Give it a name and the key rules will use, for example <code>REMOTE_POSTCODES</code>.',
              'Paste the values, one per line. A column copied from a spreadsheet works. Duplicates and blank lines are dropped, and the button shows how many values are left.',
              'In a rule, pick <em>is in reference set</em> or <em>is not in reference set</em> and choose the set. In the table view, type <code>in REMOTE_POSTCODES</code>.',
            ]} />
            <p>Each change to a set saves a new version. A published decision keeps the values it was compiled with, so changing a set never changes a live answer by surprise. The next draft picks up the latest values and goes through Check and sign-off like any other change. A set that a decision still uses cannot be deleted. Editing sets needs <code>decisions.author</code>.</p>
          </div>
        ),
      },
      {
        id: 'decisions-in-agents',
        title: 'Using a decision in an agent or pipeline',
        icon: <Bot className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Only published versions are called. A decision with no published version cannot be evaluated yet.</p>
            <p><strong className="text-white">In an agent.</strong> In the builder palette, open <em>Decisions &amp; Rules</em> and add the tools the agent needs.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><code className="text-cyan-300">decision_list</code> lists published decisions with the facts each one needs.</li>
              <li><code className="text-cyan-300">decision_evaluate</code> evaluates facts and says which facts to gather when some are missing. Takes <code>as_of</code> for the activity date and <code>known_at</code> for the rules as known then.</li>
              <li><code className="text-cyan-300">decision_compare</code> runs the same facts under several dates or versions and shows what changes.</li>
              <li><code className="text-cyan-300">decision_explain</code> says why the result came out as it did, with the sources each rule cites.</li>
              <li><code className="text-cyan-300">decision_test</code> runs a decision&apos;s golden tests.</li>
              <li><code className="text-cyan-300">decision_propose</code> proposes rule changes for people to approve. Agents can never publish.</li>
            </ul>
            <p>Tell the agent in its prompt which decision to use and to quote the outcome as given. When facts are missing the tool says which, so the agent can ask the user instead of inventing a value.</p>
            <p><strong className="text-white">In a pipeline.</strong></p>
            <Steps items={[
              'Declare the values the pipeline needs as <a href="#pipeline-inputs" class="text-violet-300 underline">pipeline inputs</a>.',
              'Add a <code>decision_evaluate</code> step and label it, for example <code>decide</code>.',
              'Open its arguments. The <strong>decision</strong> field lists your decisions and shows the facts the chosen one needs. It warns when the decision has no published version.',
              'Fill <strong>facts</strong> as JSON using your inputs, for example <code>{"shipment": {"date": "{{input.ship_date}}", "postcode": "{{input.postcode}}"}}</code>. Set <strong>as_of</strong> to the activity date.',
              'Later steps read <code>{{decide.result}}</code> and <code>{{decide.applied_rules}}</code>.',
            ]} />
            <p><strong className="text-white">From an app.</strong> The SDKs call <code className="text-cyan-300">decisions.evaluate(key, facts, as_of=...)</code>. The developer docs cover batch evaluation and comparisons.</p>

            <h4 className="text-white font-semibold pt-3">See what a decision did in a run</h4>
            <p>Every decision an agent or pipeline makes is kept as an evaluation and linked to the run, unless the call asks not to keep it. Open the run from <strong>Executions</strong> and the decision call shows as a decision card instead of raw JSON.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>The outcome: <em>Decided</em>, <em>No rule applies</em>, <em>Missing facts</em> or <em>Facts with the wrong type</em>.</li>
              <li><strong>Outputs</strong>, the values the decision returned.</li>
              <li><strong>Rules that applied</strong>, each with the source it cites. When facts were missing or wrong, the card says which and why instead.</li>
              <li>The <strong>Version</strong> that ran, linked to that version, the activity date, the trace hash and the evaluation id.</li>
              <li><strong>Open in Try with these facts</strong> opens the decision with the same facts filled in, so you can see the result again or test a change against the exact case. <strong>All evaluations</strong> opens the decision&apos;s evaluation history.</li>
            </ul>
            <p>Pipeline steps that ran <code>decision_evaluate</code> show the same card.</p>

            <h4 className="text-white font-semibold pt-3">Evaluation history</h4>
            <p>Each decision has an <strong>Evaluations</strong> tab listing the evaluations that were kept: time, version, outcome, who called it and the trace hash. Filter by outcome or version. <strong>Called by</strong> names the agent or pipeline and links back to the run, or names the API user. Click a row to see the facts given, the result, the rules that applied with their sources and the full trace. The panel shows <em>trace hash matches</em> when re-running the stored version on the stored facts gives the same answer it gave then.</p>
            <Callout tone="warn">A kill switch on a decision refuses every evaluation of it until it is resumed. See <a href="#kill-switches" className="text-violet-300 underline">Kill switches</a>.</Callout>
          </div>
        ),
      },
      {
        id: 'source-watch',
        title: 'Source Watch',
        icon: <Radar className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Source Watch checks web pages, documents, tables and feeds on a schedule, keeps every version it sees, and records a change with a diff when the readable content changes. Agents can read the snapshots and cite them, and a change can start a pipeline or call your system through <a href="#events" className="text-violet-300 underline">Events</a>.</p>
            <p>Everyone in the tenant can see sources. Adding, editing, pausing and checking need <code>sources.manage</code>, which creators and admins hold.</p>

            <h4 className="text-white font-semibold pt-3">Add a source</h4>
            <Steps items={[
              'Open <strong>Build &rarr; Source Watch</strong> and click <strong>Watch a new source</strong>.',
              'Paste the address. It is checked as you type and the kind is suggested: HTML page, PDF, Excel, CSV, JSON or RSS.',
              'For a page, narrow the watch to the main content with a selector, so menus, banners and dates elsewhere do not count as changes.',
              'Name it, pick how often to check (at most every 5 minutes), and add a jurisdiction, tags and a risk tier if you like. The tier travels on every change event, so subscribers can route high tier changes for review.',
              'If the site needs a sign-in, pick a source credential. Add plain request headers, such as Accept-Language, where needed.',
              'Optionally add each new snapshot to a knowledge base, so answers cite the exact snapshot they came from.',
              'Click <strong>Test fetch</strong> to see exactly the text that will be watched, then save. The first check captures a baseline, usually within a minute.',
            ]} />

            <h4 className="text-white font-semibold pt-3">Changes and diffs</h4>
            <p>The list shows how many sources are watching, changed in the last 7 days, failing, and paused or stopped. Open a source for its snapshot timeline and recent changes. Each change has a one-line summary and a rough <em>high</em>, <em>medium</em> or <em>low</em> hint, a first sort by size and wording rather than a judgement. <strong>See the diff</strong> shows lines added and removed for text, or rows added, removed and changed for tables. <strong>View text</strong> opens any snapshot with search, and you can download the original bytes or copy their SHA-256.</p>

            <h4 className="text-white font-semibold pt-3">Check now, pause, resume</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Check now</strong> runs a check straight away and says what it found.</li>
              <li><strong className="text-white">Pause</strong> stops scheduled checks until someone resumes. Give a reason, others will see it. Snapshots and changes are kept.</li>
              <li><strong className="text-white">Resume</strong> starts checks again. The next one runs within a minute.</li>
              <li>A source that fails too many checks in a row pauses itself. Resume it when the site is reachable again.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Allowlist and limits</h4>
            <p><strong>Allowlist and limits</strong> on the Source Watch page lists the hosts sources may fetch from (empty means any public host), the failure count that pauses a source, and the fetch limits. Private and internal addresses are always refused. Changing the allowlist and the threshold needs <code>risk.manage</code>. Source credentials are set under <a href="#tool-configuration" className="text-violet-300 underline">Tool Configuration</a>, encrypted and never shown again.</p>
          </div>
        ),
      },
      {
        id: 'code-runner',
        title: 'Code Runner',
        icon: <Code2 className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Bring your own repository. Upload a zip or paste a git URL. Abenix analyzes the code, identifies entry points, and exposes runnable artefacts as <code className="text-cyan-300">code_asset</code> tools. Pipelines call them like any other tool. Supports <strong>Python, Node, Go, Rust, Ruby, Java</strong>.</p>
            <Hero src={SS('12-code-runner.png')} alt="Code Runner" />
            <Steps items={[
              '<strong>Upload</strong> a zip or paste a git URL.',
              'Abenix clones, analyzes, and lists discovered entry points (e.g. CLI commands, exported functions).',
              'Tag entry points as runnable tools with input/output schemas.',
              'Each invocation runs in a fresh Docker / Podman sandbox with strict resource quotas (default 512 MB / 30 s).',
              'Output streams back to the calling agent as a <code>tool</code> message.',
            ]} />
            <Callout tone="info">Sandboxes are isolation-first: no network unless explicitly allowed, no host filesystem mount, ephemeral overlay FS, and an OOM watchdog. See the <a href="#scaling-sandbox" className="text-violet-300 underline">sandbox scaling notes</a>.</Callout>

            <h4 className="text-white font-semibold pt-3">Source picker is exclusive — zip or git, not both</h4>
            <p>The upload form has two sides: pick a <code>.zip</code> on the left, or paste a git URL on the right. Filling either side grays + disables the other so the precedence question never comes up.</p>
            <Hero src={SS('31-code-runner-xor.png')} alt="Code Runner zip-vs-git XOR" caption="Type a git URL and the zip picker greys out — and vice versa." />

            <h4 className="text-white font-semibold pt-3">Schemas lint inline</h4>
            <p>The <em>I/O schemas</em> textareas validate JSON on blur. A malformed paste underlines the field red and shows the parser error next to it, instead of silently rejecting the save. The <strong>Save schemas + commands</strong> button only fires when both schemas parse cleanly.</p>

            <h4 className="text-white font-semibold pt-3">Use it from an agent in one click</h4>
            <p>Once status is <em>ready</em>, the <strong>Use in Agent</strong> button deep-links to the builder with the <code>code_asset</code> tool pre-added and <code>parameter_defaults.asset_id</code> pre-filled. Same flow as the ML model wire-in path. <strong>Share</strong> opens the generic dialog so a teammate can call the asset without owning the source.</p>
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

            <h4 className="text-white font-semibold pt-3">Wire it into an agent without leaving the page</h4>
            <p>Once a model is <em>ready</em>, the detail panel shows two new CTAs next to <strong>Activate</strong> / <strong>Delete</strong>:</p>
            <Hero src={SS('29-ml-use-in-agent.png')} alt="Use in Agent + Edit metadata + Share buttons" caption="Use in Agent · Edit metadata · Share — all live on the model detail panel." />
            <ul className="list-disc list-inside space-y-1">
              <li><strong>Use in Agent</strong> → deep-links to <code>/builder?tool=ml_model&model_name=&lt;name&gt;</code>. Lands in a fresh agent canvas with the <code>ml_model</code> tool already added and <code>parameter_defaults.model_name</code> pre-filled.</li>
              <li><strong>Edit metadata</strong> → inline panel for description + <code>input_schema</code> + <code>output_schema</code>. JSON is linted on blur, so a malformed paste shows the error next to the field instead of silently saving.</li>
              <li><strong>Share</strong> → opens the generic share dialog (see the <em>Sharing resources</em> note below) so a teammate can <code>view</code>, <code>use</code>, or <code>edit</code> the model without you handing them admin.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Schema editor on upload — no .meta.json required</h4>
            <p>The upload form has a collapsible <em>Schemas (optional, recommended)</em> section. Paste the feature list inline so the agent's <code>ml_model.get_model_info</code> call returns a real shape from day one. Skip it and the platform tries to infer from the model file, but explicit schemas are more reliable.</p>

            <h4 className="text-white font-semibold pt-3">Kubernetes deployment — replicas + resource preset</h4>
            <p>When the target is <strong>Kubernetes Pod</strong>, the panel exposes the two knobs that used to be opaque defaults:</p>
            <Hero src={SS('30-ml-k8s-deploy-config.png')} alt="k8s deploy config" caption="Replicas 1-10 and small/medium/large resource preset. Each preset maps to a fixed cpu/memory request + limit pair." />
            <ul className="list-disc list-inside space-y-1">
              <li><strong>Replicas</strong>: 1-10. Each replica is an independent pod fronted by a single ClusterIP service.</li>
              <li><strong>Resource preset</strong>: <code>small</code> (100m / 256Mi), <code>medium</code> (250m / 512Mi), <code>large</code> (500m / 1Gi). Limits scale 2-4× the request.</li>
            </ul>
            <p>Backend gates both inputs with structured error codes (<code>INVALID_REPLICAS</code>, <code>INVALID_RESOURCE_PRESET</code>) so the toast tells you exactly what went wrong on a bad value.</p>

            <h4 className="text-white font-semibold pt-4">Shipped model catalogue</h4>
            <p>Sixteen models ship with the platform. Each one is registered at first startup via <code>seed_ml_models.py</code> which scans <code>&lt;app&gt;/aimodels/</code> for matching <code>.pkl</code> + <code>.meta.json</code> pairs.</p>

            <h5 className="text-violet-300 font-semibold pt-3 pb-1">E&C-Copilot (4 models)</h5>
            <table className="w-full text-[12px] border border-slate-700/40 rounded-md overflow-hidden">
              <thead className="bg-slate-800/60 text-slate-400 text-[10.5px] uppercase">
                <tr>
                  <th className="text-left py-1.5 px-2">Slug</th>
                  <th className="text-left py-1.5 px-2">Algorithm</th>
                  <th className="text-left py-1.5 px-2">Inputs</th>
                  <th className="text-left py-1.5 px-2">Output</th>
                  <th className="text-left py-1.5 px-2">Holdout</th>
                  <th className="text-left py-1.5 px-2">Used by</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                <tr className="border-t border-slate-800/40">
                  <td className="py-1.5 px-2 font-mono">contractiq-clause-classifier</td>
                  <td className="py-1.5 px-2">TF-IDF + LogReg</td>
                  <td className="py-1.5 px-2 text-slate-400">clause text</td>
                  <td className="py-1.5 px-2 text-slate-400">1 of 30 ETRM classes</td>
                  <td className="py-1.5 px-2 text-emerald-300">100%</td>
                  <td className="py-1.5 px-2 text-slate-400">extractor</td>
                </tr>
                <tr className="border-t border-slate-800/40">
                  <td className="py-1.5 px-2 font-mono">contractiq-risk-tier-predictor</td>
                  <td className="py-1.5 px-2">Calibrated GBC</td>
                  <td className="py-1.5 px-2 text-slate-400">10 deal features</td>
                  <td className="py-1.5 px-2 text-slate-400">low / medium / high / critical</td>
                  <td className="py-1.5 px-2 text-emerald-300">92.83%</td>
                  <td className="py-1.5 px-2 text-slate-400">hedge_advisor</td>
                </tr>
                <tr className="border-t border-slate-800/40">
                  <td className="py-1.5 px-2 font-mono">contractiq-counterparty-default</td>
                  <td className="py-1.5 px-2">Logistic Regression</td>
                  <td className="py-1.5 px-2 text-slate-400">11 financial ratios + sector</td>
                  <td className="py-1.5 px-2 text-slate-400">P(default 12m)</td>
                  <td className="py-1.5 px-2 text-emerald-300">89.47%</td>
                  <td className="py-1.5 px-2 text-slate-400">hedge_advisor, credit_risk</td>
                </tr>
                <tr className="border-t border-slate-800/40">
                  <td className="py-1.5 px-2 font-mono">contractiq-price-anomaly</td>
                  <td className="py-1.5 px-2">IsolationForest</td>
                  <td className="py-1.5 px-2 text-slate-400">8 deal features</td>
                  <td className="py-1.5 px-2 text-slate-400">+1 inlier / -1 outlier</td>
                  <td className="py-1.5 px-2 text-emerald-300">100% recall</td>
                  <td className="py-1.5 px-2 text-slate-400">portfolio_valuator</td>
                </tr>
              </tbody>
            </table>

            <h5 className="text-cyan-300 font-semibold pt-3 pb-1">Wingman (5 models for LPG mispricing + freight forecast)</h5>
            <table className="w-full text-[12px] border border-slate-700/40 rounded-md overflow-hidden">
              <thead className="bg-slate-800/60 text-slate-400 text-[10.5px] uppercase">
                <tr>
                  <th className="text-left py-1.5 px-2">Slug</th>
                  <th className="text-left py-1.5 px-2">Algorithm</th>
                  <th className="text-left py-1.5 px-2">Purpose</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">wingman-mispricing-fairvalue</td><td className="py-1.5 px-2">BayesianRidge</td><td className="py-1.5 px-2 text-slate-400">arb fair-value on MEG-FE, USGC-NWE, MB-JPN corridors</td></tr>
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">wingman-mispricing-anomaly</td><td className="py-1.5 px-2">IsolationForest</td><td className="py-1.5 px-2 text-slate-400">corridor spread anomaly flag</td></tr>
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">wingman-scenario-prior</td><td className="py-1.5 px-2">GaussianNB</td><td className="py-1.5 px-2 text-slate-400">5-scenario Bayesian prior (base / bull-geo / bear-glut / bear-demand / tail)</td></tr>
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">wingman-broker-intent-classifier</td><td className="py-1.5 px-2">LR text classifier</td><td className="py-1.5 px-2 text-slate-400">broker message intent (RFQ / FIRM / FYI / SPEC)</td></tr>
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">wingman-freight-forecast</td><td className="py-1.5 px-2">sklearn regression</td><td className="py-1.5 px-2 text-slate-400">BLPG1/2/3 short-term forecast on top of Baltic Exchange</td></tr>
              </tbody>
            </table>

            <h5 className="text-amber-300 font-semibold pt-3 pb-1">Industrial-IoT + demo</h5>
            <table className="w-full text-[12px] border border-slate-700/40 rounded-md overflow-hidden">
              <thead className="bg-slate-800/60 text-slate-400 text-[10.5px] uppercase">
                <tr>
                  <th className="text-left py-1.5 px-2">Slug</th>
                  <th className="text-left py-1.5 px-2">Purpose</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">wind-turbine-failure-classifier</td><td className="py-1.5 px-2 text-slate-400">vibration + temperature features &rarr; 7-class failure type. Used in the Industrial-IoT pump pipeline.</td></tr>
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">iris-species-classifier</td><td className="py-1.5 px-2 text-slate-400">canonical sklearn demo</td></tr>
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">housing-price-predictor</td><td className="py-1.5 px-2 text-slate-400">California housing regression</td></tr>
                <tr className="border-t border-slate-800/40"><td className="py-1.5 px-2 font-mono">churn-predictor</td><td className="py-1.5 px-2 text-slate-400">SaaS churn binary classifier</td></tr>
              </tbody>
            </table>

            <h4 className="text-white font-semibold pt-3">How predictions flow through the tool gate</h4>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>The agent (or SDK) calls <code>ml_model.predict(model_name, input_data)</code>.</li>
              <li>The call hits the <code>/api/tools/ml_model/execute</code> endpoint, passing through the <a href="#scaling-three-layers" className="text-cyan-300 underline">tool gate</a>: cache check (<code>cache_ttl_seconds=30</code>, scope <code>per_tenant</code>), then <code>max_inflight_global=40 / max_inflight_per_tenant=10</code> semaphore, then a 60s timeout.</li>
              <li>MLModelTool loads the pickle from <code>/data/ml-models/&lt;tenant_id&gt;/&lt;file&gt;.pkl</code> (PVC, persistent across pod restarts).</li>
              <li>Pickle is cached in process memory after first load. Cold-call latency 3-4s (PVC read). Warm-call 45-335ms.</li>
              <li>Result + metadata land in <code>ml_model_invocations</code> + <code>tool_invocations</code> tables. Surfaced in <a href="/ml-models" className="text-cyan-300 underline">/ml-models</a> as a 24h stats card and in <a href="/admin/tool-scaling" className="text-cyan-300 underline">/admin/tool-scaling</a> with live counters.</li>
            </ol>

            <Callout tone="info">
              <strong>Adding your own model.</strong> Drop a <code>my-model.pkl</code> + <code>my-model.meta.json</code> into <code>aimodels/</code> at the repo root (or under any <code>&lt;app&gt;/aimodels/</code>). Restart the api pod or run <code>seed_ml_models.py</code>. The platform discovers the pair, copies the pickle to the per-tenant PVC, and creates the MLModel + Deployment rows automatically.
            </Callout>
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

            <h4 className="text-white font-semibold pt-3">Batch ingest — drop multiple files at once</h4>
            <p>The dropzone accepts any number of files in one gesture. They upload serially (so backend stays responsive) with a progress bar and a per-file failure list when something doesn&apos;t parse. The OS file picker also accepts multi-select via <code>&lt;input multiple&gt;</code>.</p>
            <Hero src={SS('32-kb-multi-upload.png')} alt="KB multi-file dropzone" caption="Drop a folder, click to multi-select, or paste a long list — same UI." />
            <p>Use <strong>Share</strong> in the KB header to grant a teammate <code>view</code> / <code>use</code> / <code>edit</code> on this knowledge base without exposing every other KB in the tenant. See the <em>Sharing resources</em> note below.</p>


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
              <li><strong>Tenant boundary</strong> — every <code>knowledge_collections</code> row carries a <code>tenant_id</code>. Routers hard-filter on the calling user&apos;s tenant, cross-tenant reads return 404.</li>
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
              <li>Strengthens edges that lead to good answers, weakens those that don&apos;t (the Knowledge Engine self-tunes).</li>
            </ol>
            <p>Agents using <code>knowledge_search</code> on a graph-enabled collection get hybrid retrieval: vector similarity AND multi-hop graph walks. This is the 5–10× token reduction story.</p>

            <h4 className="text-white font-semibold pt-3">v2.0 enterprise capabilities <Pill tone="cyan">new</Pill></h4>
            <p>Sixteen features landed in v2.0 to move the knowledge stack from demo-ready to Fortune-500-ready. Open <code>/settings/cognify</code> for the runtime knobs and <code>/settings/gdpr</code> for the cascade purge UI.</p>

            <h5 className="text-white font-medium pt-2 flex items-center gap-2"><Shield className="w-3.5 h-3.5 text-cyan-300" /> Document-level ACL</h5>
            <p>A collection grant lets someone read the whole collection. A document grant narrows one document inside it. A document with no grants is visible to everyone who can read the collection. The first grant restricts it to its grantees, which are users or agents, plus tenant admins, the collection creator and anyone holding WRITE or ADMIN on the collection. There are no team or role grants.</p>
            <p>Search drops restricted documents before ranking, so the top-K an agent sees comes only from what it may read, and the document list hides them too. Only people who can edit the collection can add or remove grants, with <code>POST /api/knowledge/{`{kb}`}/documents/{`{doc}`}/grants</code> and <code>DELETE .../grants/{`{grant_id}`}</code>.</p>

            <h5 className="text-white font-medium pt-2 flex items-center gap-2"><GitBranch className="w-3.5 h-3.5 text-cyan-300" /> Document versioning + replace</h5>
            <p>Upload an amendment with <code>POST /api/knowledge/{`{kb}`}/documents/{`{doc}`}/replace</code>. The old row is marked <code>is_current=false, superseded_by=&lt;new_id&gt;</code>. Search and Cognify follow automatically, with no agent or caller change:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Hybrid search</strong> filters <code>documents.is_current = true</code> before similarity scoring. The new version&apos;s chunks are the only candidates. Pass <code>?include_superseded=true</code> to surface history.</li>
                            <li><strong>Cognify</strong> incremental runs only fetch <code>is_current = true AND (cognified_at IS NULL OR updated_at &gt; cognified_at)</code>. The replaced document immediately appears in the next job&apos;s frontier. The superseded one is excluded.</li>
            </ul>

            <h5 className="text-white font-medium pt-2 flex items-center gap-2"><Settings className="w-3.5 h-3.5 text-cyan-300" /> Cognify config + conflict surface</h5>
            <p>Per-tenant row in <code>cognify_configs</code> (one row, surfaced at <code>/settings/cognify</code>):</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><code>auto_accept_threshold</code> (default <code>0.85</code>). Proposals below it are left out of the graph. The job report counts how many entities and relationships were held back.</li>
              <li><code>conflict_action</code>. Used when sources disagree on an entity&apos;s type. <code>flag</code> (default) keeps the stored or majority type and records a conflict for a person to pick, <code>higher_conf_wins</code> or <code>lower_conf_wins</code> pick by confidence, <code>split</code> keeps both linked as VARIANT_OF.</li>
              <li><code>max_parallel_docs</code> (default 8). Documents processed at once in a job.</li>
              <li><code>daily_budget_usd</code> (optional). Once the day&apos;s Cognify spend (UTC) reaches it, jobs stop taking documents and say how many they skipped.</li>
            </ul>
            <p>Flagged conflicts show on the settings page with <strong>Accept A</strong> and <strong>Accept B</strong>. Picking one writes that type to the graph. Three job modes ship: <code>incremental</code> (default, new and updated docs), <code>full</code> (every doc, use when the ontology changes), <code>selective</code> (explicit <code>document_ids</code>).</p>

            <h5 className="text-white font-medium pt-2 flex items-center gap-2"><Wand2 className="w-3.5 h-3.5 text-cyan-300" /> Embedding-model swap</h5>
            <p>Every collection stores its <code>embedding_model</code>, and ingest and search both use it. The allowed models are <code>text-embedding-3-small</code>, <code>text-embedding-3-large</code> (at 1536 dimensions), <code>text-embedding-ada-002</code> and <code>local-hashing-v1</code>, the built-in embedder that needs no provider.</p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Open the collection&apos;s engine page. The <strong>Embedding model</strong> panel shows the current model and any job in progress (<code>GET /api/knowledge/{`{kb}`}/reembed</code>).</li>
              <li>An admin picks a model and sees the chunk count, cost estimate and ETA (<code>POST .../reembed</code> with <code>dry_run</code>).</li>
              <li>Starting the swap queues the worker. It re-reads and re-chunks every document with the new model, then switches the collection in one step. If anything fails first, nothing changes.</li>
            </ol>

            <h5 className="text-white font-medium pt-2 flex items-center gap-2"><Search className="w-3.5 h-3.5 text-cyan-300" /> Reranking + deep-link citations</h5>
            <p>Hybrid search reranks its candidates before returning the top-K when a reranker is on:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Cohere <code>rerank-english-v3.0</code> when <code>COHERE_API_KEY</code> is set.</li>
              <li>The Claude Haiku scorer only with <code>RERANKER_PROVIDER=llm</code>, since it adds a model call to every search.</li>
              <li>Otherwise results keep their retrieval order.</li>
            </ul>
            <p>Every chunk hit carries <code>metadata.citation</code> with the document, page, chunk index and character offsets. Agents can cite <em>contract.pdf · page 42 · chunk 3</em> in their output.</p>

            <h5 className="text-white font-medium pt-2 flex items-center gap-2"><ScanLine className="w-3.5 h-3.5 text-cyan-300" /> Multi-modal extractors (OCR auto-fallback)</h5>
            <p>Each document records the <code>extraction_method</code> and <code>extraction_quality</code> it used, so you can see which ones needed OCR. Chunks keep their page numbers for citations.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>pdf</strong> → <code>text_pdf</code> first. Under 50 characters a page, it falls through to <code>vision_pdf</code> (PyMuPDF rasterisation read by Claude).</li>
              <li><strong>docx</strong> → unstructured, falling back to python-docx.</li>
              <li><strong>text</strong> (txt / md / csv / json) → plain.</li>
            </ul>
            <p>Vision OCR needs PyMuPDF and <code>ANTHROPIC_API_KEY</code> on the worker. Uploads are still limited to PDF, DOCX, TXT, CSV, MD and JSON.</p>

            <h5 className="text-white font-medium pt-2 flex items-center gap-2"><Layers className="w-3.5 h-3.5 text-cyan-300" /> Pagination + cleanup</h5>
            <p>Every list endpoint now accepts <code>?cursor=&lt;id&gt;&amp;limit=&lt;N&gt;</code> and returns <code>next_cursor</code> for stable forward iteration (replaced hardcoded <code>.limit(500)</code> on persona items, <code>.limit(20)</code> on cognify jobs, and the new conflicts endpoint). The API scheduler queues a Pinecone vacuum daily at 02:30 UTC. It deletes the namespaces of deleted collections, leftover vectors past a document&apos;s chunk count and persona vectors of deleted items. Vectors with no document row are kept.</p>

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

            <h4 className="text-white font-semibold pt-3 flex items-center gap-2"><ShieldCheck className="w-4 h-4 text-cyan-300" /> At-rest encryption <Pill tone="cyan">v2.0</Pill></h4>
            <p>The platform can encrypt secrets with AES-256-GCM at the application layer. Today that covers tool credentials, Slack and approval webhook URLs and MCP secrets. Persona items and agent memories have columns for it but are not encrypted yet. The cluster KEK lives in <code>ABENIX_DATA_KEY_KEK_BASE64</code>, sourced from a vault, never the database. The per-tenant key is derived as <code>HMAC-SHA256(KEK, tenant_id)</code>, so every pod agrees without storing per-tenant key rows.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>No KEK, no encryption.</strong> Without the env var values are stored as entered. Tool Configuration says in its header which mode you are in. Production deployments must set the KEK.</li>
              <li><strong>No rotation yet.</strong> Changing the KEK makes values written under the old one unreadable, so set it once.</li>
              <li><strong>Scope.</strong> Encryption protects DB-at-rest exfiltration scenarios (stolen snapshot, leaked backup). It does not encrypt vectors in Pinecone — use Pinecone&apos;s own encryption-at-rest for that surface.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3 flex items-center gap-2"><Shield className="w-4 h-4 text-cyan-300" /> GDPR cascade purge <Pill tone="cyan">v2.0</Pill></h4>
            <p>The right-to-be-forgotten request used to be a forensic exercise. <code>POST /api/gdpr/users/{`{user_id}`}/purge</code> now runs the five-store cascade in one call. The trigger UI sits at <code>/settings/gdpr</code>:</p>
            <table className="w-full text-xs my-2">
              <thead className="text-[10px] uppercase text-slate-500">
                <tr><th className="text-left py-1">Store</th><th className="text-left py-1">What is purged</th></tr>
              </thead>
              <tbody className="text-slate-300 align-top">
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono">postgres</td><td className="py-1">The person&apos;s persona items soft-deleted, agent memories soft-deleted only for agents the person created, API keys deactivated and the user row scrubbed to a placeholder. Every message in the person&apos;s conversations, theirs and the replies, is replaced with <code>[erased]</code>, with their blocks, attachments and tool calls cleared, their conversation titles and previews are erased and any share link revoked, and the runs they started lose their input, output, tool calls, node results and trace. Conversations and runs stay linked to the scrubbed user row, so spend history stays whole. Audit rows keep the hash chain: the salted PII digest stays, while the salt, user id, IP and user agent go, so a row can no longer be tied to the person. Rows already erased by an earlier attempt are not counted again</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono">pinecone</td><td className="py-1">The person&apos;s persona vectors, retried 3 times</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono">neo4j</td><td className="py-1">Cognify entities that name the person in any of the tenant&apos;s collections: the email on any entity, the full name (two or more words) on person entities. The matching graph rows in Postgres go too</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono">blob</td><td className="py-1">Code asset archives (every version) and ML model files the person uploaded, deleted on local disk and in object storage, everything under the person&apos;s own storage folder (<code>users/&lt;id&gt;/</code>), and their cloned voice at the voice provider, with the voice link on the user row cleared. Uploads still used by an agent or pipeline, shared, or deployed are kept and logged. The count is the files really deleted, plus one for a deleted voice</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono">trajectory</td><td className="py-1">Trajectory records written from the person&apos;s runs, matched by the run&apos;s execution id or a user id on the record, in the tenant&apos;s folder and the <code>shared</code> folder under <code>TRAJECTORY_DIR</code> (<code>/data/trajectories</code>) and <code>WINGMAN_TRAJECTORY_DIR</code> (<code>/data/wingman-trajectories</code>). The count is the records deleted</td></tr>
              </tbody>
            </table>
            <p>A purge can only target a user in your own tenant. Every per-store attempt writes a <code>gdpr_purge_log</code> row with its status and how many rows, vectors, files or records it really removed. <code>/settings/gdpr</code> shows that count in the <strong>Removed</strong> column, and <code>GET /api/gdpr/users/{`{user_id}`}/receipts</code> returns the same trail.</p>
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
            <Hero src={SS('06-atlas-extract.png')} alt="Atlas — extracted ontology proposal" caption="After dropping a document — entities and edges proposed for review at the bottom" />

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
              <li><strong>Validation</strong> — outputs validated against the ontology&apos;s cardinalities and types, bad outputs reject before they land.</li>
              <li><strong>Provenance</strong> — every agent answer cites the Atlas nodes it walked.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Agent tools — read the graph</h4>
            <p>Five tools ship in the catalogue. Attach any of them to an agent from the Builder palette under <em>Knowledge</em>:</p>
            <ul className="list-disc pl-5 space-y-1.5 text-[13px]">
              <li><code className="text-cyan-300">atlas_describe</code> — summarise the graph (counts by kind, top edge labels, most-connected concepts). Use first when the user asks "what do you know about X?".</li>
              <li><code className="text-cyan-300">atlas_query</code> — pattern-match nodes by <code>label_like</code> + <code>kind</code>. Returns structured rows, the typed alternative to vector search.</li>
              <li><code className="text-cyan-300">atlas_traverse</code> — 1-hop neighbourhood of a node. Use after locating a concept to walk to related concepts.</li>
              <li><code className="text-cyan-300">atlas_search_grounded</code> — find KB documents bound to nodes near a target term. Better than vector-only when the chunks must be tied to a typed concept.</li>
              <li><code className="text-cyan-300">atlas_as_of</code> <Pill tone="cyan">v2.0</Pill> — shows an atlas graph as it stood at a past moment, from the newest snapshot saved at or before that time, or the live graph when nothing changed since. Inputs are <code>graph_id</code>, <code>as_of</code>, <code>label_like</code>, <code>kind</code> and <code>limit</code>. Answers &quot;what did the ontology say on 2025-01-15?&quot;. With no snapshot that old it says so.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Bi-temporal Atlas <Pill tone="cyan">v2.0</Pill></h4>
            <p>Every Atlas node and edge carries four time and provenance columns:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><code>valid_from</code> — when the fact became true in the world</li>
              <li><code>valid_to</code> — when it stopped being true (<code>NULL</code> = still current)</li>
              <li><code>recorded_at</code> — when Cognify learned the fact</li>
              <li><code>source_anchors</code> — JSONB array of <code>{`{document_id, page, chunk_id, confidence}`}</code> per supporting citation, built up across multiple Cognify runs as evidence accumulates</li>
            </ul>
            <p><code>atlas_as_of</code> keeps live rows inside their <code>valid_from</code> and <code>valid_to</code>.</p>

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
              <strong className="text-white">Per-application:</strong> standalone apps using the actAs delegation pattern pass <code>X-Abenix-Subject</code> per request. The subject inherits the agent&apos;s allow-list, the data still flows under the agent's <code>tenant_id</code>, so cross-app reads stay impossible at the SQL layer.
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
            <p><strong className="text-white">Configurable model.</strong> The Surgeon's model is read from <strong>Admin → Settings → <code>pipeline_surgeon.model</code></strong>. Defaults to <code>claude-sonnet-4-5-20250929</code>. Switch it cluster-wide from the central model selection page so every LLM-using primitive shares one configuration surface.</p>
          </div>
        ),
      },
      {
        id: 'workflow-shell',
        title: 'Talk-to-workflow shell',
        icon: <Terminal className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>A typed verb grammar — over 30 verbs across five intents — that drives every aspect of a pipeline. The LLM is only used to translate natural language into a verb invocation (when you type prose), the parser, the dispatcher, and every mutating verb are deterministic.</p>
            <p>Open it from any pipeline agent's <code>/info</code> page via the <strong>Shell</strong> button next to <strong>Healing</strong>. Tab-completion comes from the live verb registry. Up/down recalls history. Mutating verbs draft a Healing patch you Apply or Reject — same ledger as the Surgeon, same one-click rollback.</p>
            <p><strong className="text-white">Five intents, ~30 verbs:</strong></p>
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase text-slate-500">
                <tr><th className="text-left py-1">Intent</th><th className="text-left py-1">Verbs</th><th className="text-left py-1">Purpose</th></tr>
              </thead>
              <tbody className="text-slate-300 align-top">
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono text-cyan-300">INSPECT</td><td className="py-1 font-mono text-[11px]">show, describe, diff, why, list</td><td className="py-1">Read the workflow object — DSL, runs, failures, costs, schedule, patches, history.</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono text-amber-300">MUTATE</td><td className="py-1 font-mono text-[11px]">add, remove, rename, set, swap-model, add-fallback, attach</td><td className="py-1">Compile to JSON-Patch ops. Always create a draft proposal — never live-edit.</td></tr>
                <tr className="border-t border-slate-800/60"><td className="py-1 font-mono text-emerald-300">EXECUTE</td><td className="py-1 font-mono text-[11px]">run, replay, simulate, branch, merge, rollback</td><td className="py-1">Drive runs. <code>simulate</code> is idempotent (dry-run). <code>branch</code> creates a sandbox version.</td></tr>
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
  // PRODUCTION TOOLS — v1.1.0 industrial primitives
  {
    id: 'prod-tools',
    label: 'Production tools (v1.1)',
    blurb: 'The 13 primitives that turn the IoT showcases into something an enterprise can run live.',
    topics: [
      {
        id: 'streaming-triggers',
        title: 'Streaming triggers — MQTT & Kafka',
        icon: <Radio className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Until v1.1 every agent ran in response to an HTTP call, a cron, or a webhook. Streaming triggers let an agent or pipeline subscribe directly to an MQTT topic or a Kafka consumer group, so a vibration packet, a temperature waypoint, or a SCADA alarm wakes the agent the instant it lands on the broker — no polling, no batch lag.</p>
            <p><strong className="text-white">What it solves.</strong> The Pump Vibration showcase used to call a synthetic generator on a 5-second timer. With the MQTT trigger an agent subscribed to <code className="text-cyan-300">vibration.raw</code> reacts to every packet a SCADA gateway publishes, exactly the way a plant historian would in production.</p>
            <p><strong className="text-white">When to use.</strong> High-rate machine telemetry, IoT fleet messages, alarm fan-outs, change-data-capture from a Debezium Kafka topic. <strong className="text-white">When not to use.</strong> Low-rate human-in-the-loop flows (a Slack mention or a calendar event) — those are still a webhook trigger.</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Open the agent or pipeline in the Builder.',
              'Click the <strong>Triggers</strong> tab on the right rail.',
              'Click <strong>+ Add trigger</strong> and pick <strong>MQTT subscribe</strong> or <strong>Kafka consume</strong>.',
              'Enter the broker URL (defaults to the in-cluster <code>mosquitto:1883</code>) and the topic — wildcards <code>+</code> and <code>#</code> work.',
              'Pick the <strong>QoS</strong> (0 fire-and-forget, 1 at-least-once, 2 exactly-once) and an optional message <strong>filter</strong>.',
              'Save. The trigger registers a long-lived consumer in the streaming-trigger pod and shows up on the agent&apos;s <strong>/triggers</strong> page.',
            ]} />
            <Callout tone="warn"><strong>Gotcha.</strong> A single agent can only consume one MQTT topic per trigger. For multi-topic routing put a fan-in pipeline in front and use a switch node. Kafka consumer groups are tenant-scoped — two tenants subscribing to the same external topic stay isolated automatically.</Callout>
          </div>
        ),
      },
      {
        id: 'bidirectional-tools',
        title: 'Bidirectional tools — OPC-UA write, MQTT publish, CMMS write',
        icon: <ArrowRight className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Read-only agents are demos. Production agents have to <em>act</em> — open a valve, raise a work order, push a setpoint back to the PLC. v1.1 ships three palette tools that write back to the systems of record: <code className="text-cyan-300">opcua_write</code> for OPC-UA tag writes, <code className="text-cyan-300">mqtt_publish</code> for command topics, and <code className="text-cyan-300">cmms_write</code> for SAP-style work-order creates via the connector framework.</p>
            <p><strong className="text-white">What it solves.</strong> The Alarm Desk showcase couldn&apos;t actually reset an alarm — it could only suggest one. With <code className="text-cyan-300">opcua_write</code> gated by an <code>approval_gate</code> the agent now drafts a remote-reset command, blocks for two human signoffs, and on approval pushes the setpoint to the device through the platform OPC-UA bridge.</p>
            <p><strong className="text-white">When to use.</strong> Anywhere an agent&apos;s output is meant to change the physical or business world: closing a CMMS work order, publishing a control message, raising a partial-loss claim. <strong className="text-white">When not to use.</strong> Inside the agent&apos;s reasoning loop. Always put the write at the end of the pipeline behind a clear human or programmatic gate.</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Drag <strong>OPC-UA write</strong>, <strong>MQTT publish</strong>, or <strong>CMMS write</strong> from the Builder palette onto the canvas.',
              'In the config panel, pick the target connector or broker URL.',
              'For OPC-UA: enter the node-id (e.g. <code>ns=2;s=Pump1.SetpointRPM</code>) and the value template.',
              'For MQTT publish: pick topic + retain flag + QoS.',
              'For CMMS write: pick the operation (<code>create_work_order</code>, <code>update_status</code>, <code>attach_photo</code>) — the dropdown auto-discovers from the connector preset.',
              'Connect the tool node to the upstream agent that produces the payload.',
            ]} />
            <Callout tone="warn"><strong>Gotcha.</strong> Every bidirectional tool emits an audit-log event with the calling agent&apos;s identity, the tenant, and the full payload — the regulated-environment flag automatically enforces a human approval gate before the write fires.</Callout>
          </div>
        ),
      },
      {
        id: 'connector-framework',
        title: 'Connector framework — CMMS, HRIS, telematics, weather, market data',
        icon: <Plug className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>An agent that has to call SAP, ServiceNow, Workday, Sensitech, BNEF, and ECMWF gets unmaintainable fast if every integration is a hand-rolled tool. The connector framework gives you one generic <code className="text-cyan-300">connector_call(connector_id, operation, payload)</code> tool plus a registry of presets — each connector has a kind (cmms / hris / telematics / standards / market-data / custom), a base URL, an auth profile, and an operation catalogue.</p>
            <p><strong className="text-white">What it solves.</strong> Field Guide needs CMMS for fleet + WO read, HRIS for the technician roster, weather for forecasts, and CMMS-write for closeout — all four are now the same tool with different connector IDs. Cold Chain swaps the telematics preset from Sensitech to Geotab without touching the agent prompt.</p>
            <p><strong className="text-white">When to use.</strong> Any third-party SaaS or enterprise system the agent has to read from or write to. <strong className="text-white">When not to use.</strong> Public web pages — that&apos;s still <code>web_search</code> + <code>web_scrape</code>. Internal databases — that&apos;s <code>postgres_query</code>.</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Open <strong>/admin/connectors</strong>.',
              'Click <strong>+ New connector</strong>, pick a kind, and either start from a preset (SAP / ServiceNow / Workday / Sensitech / Geotab / BNEF / ECMWF) or roll a custom one.',
              'Enter the base URL, pick the auth type (none / bearer / basic / oauth2-client-creds), and store the secret in the platform vault.',
              'Click <strong>Test</strong> — the connector pings its <code>/health</code> or first read operation.',
              'In the agent Builder, open the <strong>Knowledge</strong> tab → <strong>Connectors</strong> sub-tab and check the connectors this agent may use.',
              'Drop the <strong>Connector call</strong> tool from the palette. The operation dropdown is populated from the preset.',
            ]} />
            <Callout tone="info">Connectors are tenant-scoped, secrets are referenced by ID never inlined, and every <code>connector_call</code> is auditable from the execution detail page.</Callout>
          </div>
        ),
      },
      {
        id: 'sliding-window-state',
        title: 'Sliding-window state',
        icon: <Activity className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>An agent that has to spot a cascade — three correlated alarms in 90 seconds, five vibration spikes in five minutes, two failed logins in a row — needs short-term memory keyed by an asset, not by a chat thread. The <code className="text-cyan-300">windowed_state</code> tool gives every agent a Redis-backed sorted set per <code>(tenant, asset, name)</code> with append, query, count, and pattern-match operations.</p>
            <p><strong className="text-white">What it solves.</strong> Alarm Desk now detects <em>cascades</em> — alarm A followed by alarm B within a configurable window — instead of only firing on individual events. Pump Vibration uses <code>count(asset, &quot;high_severity&quot;, since=now-1h)</code> to suppress duplicate work orders.</p>
            <p><strong className="text-white">When to use.</strong> Anywhere temporal correlation matters — debouncing, cascade detection, last-N reasoning, simple counters. <strong className="text-white">When not to use.</strong> Long-term memory or auditable history — that&apos;s the time-series store. Cross-asset analytics — that&apos;s a real OLAP query.</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Drag <strong>Windowed state</strong> from the palette.',
              'Pick the operation: <code>append</code>, <code>query</code>, <code>count</code>, or <code>pattern_match</code>.',
              'Set the <strong>asset_id</strong> (template-resolved from upstream output, e.g. <code>{`{{trigger.payload.asset_id}}`}</code>) and the <strong>name</strong> (e.g. <code>vibration_spikes</code>).',
              'For <code>append</code>: pick the payload template. For <code>query</code>: enter the <code>since</code>/<code>until</code> window — relative (<code>now-15m</code>) or absolute timestamps.',
              'For <code>pattern_match</code>: define the sequence (e.g. <code>[&quot;A&quot;, &quot;B&quot;]</code> within 90s).',
            ]} />
            <Callout tone="warn"><strong>Gotcha.</strong> Window TTL defaults to 24 hours per key. Raise it for slow processes (a daily reconciliation) and lower it for hot loops (a per-second alarm stream) so Redis stays small.</Callout>
          </div>
        ),
      },
      {
        id: 'backend-approvals',
        title: 'Backend approvals',
        icon: <ShieldCheck className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Some agent actions must not fire without human signoff — a remote PLC reset, a refund above $1k, a contract execute. The approval workflow is enforced server-side: when an agent calls <code className="text-cyan-300">approval_gate</code> the execution blocks, a row lands in the <code>approvals</code> table, the right humans get a notification, and the agent only resumes once the configured number of signoffs land (or the request expires / is denied).</p>
            <p><strong className="text-white">What it solves.</strong> Alarm Desk&apos;s remote-reset flow now requires two operator signoffs before <code>opcua_write</code> fires. ResolveAI&apos;s refund flow blocks any amount over policy until a supervisor approves. The gate is enforced in the API layer so a malicious or buggy agent cannot bypass it.</p>
            <p><strong className="text-white">When to use.</strong> Any irreversible or expensive action. Anything a regulator might audit. <strong className="text-white">When not to use.</strong> Internal reasoning steps — humans should not be in the inner loop.</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Drop the <strong>Approval gate</strong> tool from the palette.',
              'Set the <strong>required signoffs</strong> count (1 for a single approver, 2+ for sensitive ops).',
              'Set <strong>expires_seconds</strong>, 30 minutes by default and at most 7 days. A request nobody approves in time ends as <code>expired</code>, and the agent should treat it like a denial.',
              'Optionally set a <strong>kind</strong>, such as <code>device.remote_reset</code>, so reviewers and SDK consumers can tell gates apart. Who may sign follows the tier policy, see <a href="#approvals" class="text-violet-300 underline">Approvals</a>.',
              'Wire the gate before the action tool. The downstream tool only runs on <code>status=approved</code>.',
              'Operators see pending requests on the <strong>/approvals</strong> page (sidebar item) and on Slack/email if those channels are configured.',
            ]} />
            <Callout tone="info">Every approval action is hashed into the audit log: who approved, when, and the full payload that was approved. The sidebar shows a live count of pending approvals for the current user. Returning, tier floors and escalation are covered under <a href="#approvals" className="text-violet-300 underline">Approvals</a>.</Callout>

            <h4 className="text-white font-semibold pt-3">Reading the payload — no JSON parsing required</h4>
            <p>The approval card&apos;s <em>Payload, signoff history</em> section now renders the request body as a readable key/value grid (nested objects and arrays are indented). A compliance reviewer can scan vendor, amount, risk tier, etc. at a glance instead of squinting at raw JSON. <strong>Show raw JSON</strong> keeps the full payload one click away for power users.</p>
            <Hero src={SS('33-approvals-payload.png')} alt="Approval payload key/value renderer" caption="Structured fields up top, 'Show raw JSON' toggle at the bottom." />

            <h4 className="text-white font-semibold pt-3">Live expiry countdown</h4>
            <p>The amber expiry chip on each pending row ticks live — once remaining time drops below a minute it switches to second-granularity so a reviewer can watch the gate close. If you don&apos;t signoff before zero the request transitions to <code>expired</code> and the calling agent unblocks with a denial.</p>
          </div>
        ),
      },
      {
        id: 'sharing-resources',
        title: 'Sharing resources with teammates',
        icon: <ShieldCheck className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Every shareable resource — <strong>agent</strong>, <strong>pipeline</strong>, <strong>ML model</strong>, <strong>code asset</strong>, <strong>knowledge base</strong> — uses the same dialog. Open it from the <strong>Share</strong> button on the resource detail page.</p>
            <Hero src={SS('34-resource-share-dialog.png')} alt="Resource share dialog" caption="One dialog, four resource kinds, three permission levels." />
            <ul className="list-disc list-inside space-y-1">
              <li><strong>View</strong> — recipient sees it in their list. Cannot run or change it.</li>
              <li><strong>Use</strong> — recipient can call / run the resource but not modify the definition.</li>
              <li><strong>Edit</strong> — full editor access. Can change config, schema, version.</li>
            </ul>
            <p>The recipient must already be a member of your tenant — invite them first via <em>Settings → Team</em>. Shares are notification-aware: the recipient gets an in-app notification (and email, if configured) so they know what just landed in their queue. Anyone in the share list can be revoked one-click. The revoke action is audit-logged with the actor and timestamp.</p>
            <Callout tone="info">All sharing routes through one polymorphic <code>resource_shares</code> table. The same RBAC predicate gates every endpoint, so you can&apos;t accidentally over-grant by going through one resource&apos;s UI vs another&apos;s.</Callout>
          </div>
        ),
      },
      {
        id: 'sdk-hitl',
        title: 'SDK — Human-in-the-loop',
        icon: <ShieldCheck className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The SDK turns approval gates into a first-class outcome of <code className="text-cyan-300">execute()</code>. You no longer have to scrape stream events or poll a queue to find out an agent paused — you ask for a wait mode and get an <code className="text-cyan-300">ApprovalRef</code> back. All three SDKs (Python, TypeScript, Java) ship the same surface.</p>

            <p><strong className="text-white">Wait modes.</strong> The third value is the new one.</p>
            <ul className="list-disc list-inside text-slate-300 ml-2 space-y-1 text-[12.5px]">
              <li><code className="text-cyan-300">wait="completed"</code> (default) — block until the agent finishes or fails.</li>
              <li><code className="text-cyan-300">wait="submitted"</code> — kick off and return an <code>execution_id</code>. You handle resumption from a worker or scheduler.</li>
              <li><code className="text-cyan-300">wait="until_gate"</code> — block, but if the agent hits an approval gate, return immediately with <code>status="paused"</code> and a populated <code>paused_at</code> field. This covers <code>approval_gate</code> and <code>human_approval</code> gates. For a <code>human_approval</code> gate the id starts with <code>hitl:</code> and <code>signoff</code> accepts it.</li>
            </ul>

            <p><strong className="text-white">The approvals client.</strong> Same shape in every language: <code>create</code>, <code>list</code>, <code>get</code>, <code>signoff</code> (or <code>approve</code>/<code>deny</code>), <code>wait_for</code>, <code>subscribe</code>, <code>configure_webhook</code>. <code>signoff</code> and <code>create</code> both take an optional <code>client_token</code> so retries collapse to a single decision instead of a 409. <code>wait_for</code> uses a server-side long poll under the hood — one round trip covers up to 120 seconds of real waiting.</p>

            <p><strong className="text-white"><code>create</code> — human-initiated approvals.</strong> Two ways an approval gate lands in the queue:</p>
            <ul className="list-disc list-inside text-slate-300 ml-2 space-y-1 text-[12.5px]">
              <li><strong>Agent-initiated</strong>: an agent calls the <code className="text-cyan-300">approval_gate</code> tool inside its execution. The execution pauses until a human decides. Use this when the agent is the one needing permission.</li>
              <li><strong>Human-initiated</strong> (new): your app code calls <code className="text-cyan-300">forge.approvals.create(...)</code> directly — typically on a user button click (e.g. &quot;Acknowledge to broker&quot;, &quot;Activate strategy&quot;, &quot;Approve PO&quot;). Use this when a UI action needs governance signoff before it proceeds.</li>
            </ul>
            <p>Wingman uses both. Broker Inbox &quot;Acknowledge&quot; and Strategy Lab &quot;Activate&quot; call <code>create()</code> to open a senior-trader signoff before the action fires. Pipeline-internal gates (e.g. before MQTT-publishing a remote command) use <code>approval_gate</code>. Both surface in the same <code>/approvals</code> queue and the same top-bar bell.</p>

            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`# Python — open a gate from a user button click
approval = await forge.approvals.create(
    title="Acknowledge to broker — 25kt USGC propane Aug-15",
    payload={"offer_id": "offer-abc", "broker": "Acme Energy"},
    required_signoffs=1,
    expires_seconds=7200,
    gate_kind="broker.acknowledge",
    client_token=f"ack-{offer_id}",   # idempotent retries
)
print(approval["id"])  # surfaces in /approvals; bell rings`}</pre>

            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`// TypeScript
const approval = await forge.approvals.create(
  'Activate strategy: lock-in USGC->FE Q1 above $30/MT',
  { intent: 'strategy_activate', rule_id: ruleId },
  { gateKind: 'strategy.activate', expiresSeconds: 86400 },
);`}</pre>

            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`// Java
Approval approval = forge.approvals().create(
    "Activate strategy: ...",
    Map.of("intent", "strategy_activate", "rule_id", ruleId),
    1, 86400, "strategy.activate", null
);`}</pre>


            <p className="pt-1"><strong className="text-white">Python.</strong></p>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`from abenix_sdk import Abenix

async with Abenix(api_key=KEY) as forge:
    result = await forge.execute("alarm-triage", payload, wait="until_gate")

    if result.status == "paused":
        ref = result.paused_at
        # Show ref.title / ref.payload to a human, take their decision...
        await forge.approvals.approve(ref.approval_id, reason="confirmed by ops")
        # ...and resume.
        approval = await forge.approvals.wait_for(ref.approval_id, timeout_seconds=300)
        print("resolved:", approval["status"])`}</pre>

            <p className="pt-1"><strong className="text-white">TypeScript.</strong></p>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`import { Abenix } from '@abenix/sdk';

const forge = new Abenix({ apiKey: KEY });
const result = await forge.execute('alarm-triage', payload, { wait: 'until_gate' });

if (result.status === 'paused' && result.pausedAt) {
  const ref = result.pausedAt;
  await forge.approvals.approve(ref.approvalId, { reason: 'confirmed by ops' });
  const approval = await forge.approvals.waitFor(ref.approvalId, { timeoutSeconds: 300 });
  console.log('resolved:', approval.status);
}`}</pre>

            <p className="pt-1"><strong className="text-white">Java.</strong></p>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`Abenix forge = Abenix.builder().apiKey(KEY).build();
ExecutionResult result = forge.execute(
    "alarm-triage", payload,
    Abenix.ExecuteOptions.defaults().waitMode(WaitMode.UNTIL_GATE)
);

if (result.isPaused()) {
    var ref = result.pausedAt();
    forge.approvals().approve(ref.approvalId(), "confirmed by ops");
    Approval approval = forge.approvals().waitFor(ref.approvalId(), 300);
    System.out.println("resolved: " + approval.status());
}`}</pre>

            <p><strong className="text-white">Discriminating gate types.</strong> Pass <code className="text-cyan-300">kind: "device.remote_reset"</code> when the agent calls <code>approval_gate</code>. The value flows into the <code>gate_kind</code> column and lets reviewer UIs (or your own SDK code) dispatch handlers per gate kind without parsing the payload.</p>

            <p><strong className="text-white">Webhooks.</strong> Tenant admins can register a webhook URL via <code className="text-cyan-300">forge.approvals.configure_webhook(url=..., secret=...)</code>. The platform fires <code>approval_pending</code> and <code>approval_resolved</code> events to that URL with an HMAC-SHA256 signature in <code>X-Abenix-Signature</code>. Replaces every bespoke poller wrapping a Slack or PagerDuty integration.</p>

            <Callout tone="info">The SDK Playground&apos;s <strong>HITL</strong> use case generates this exact pattern in any of the three languages with the agent slug already wired in. Pick an agent, hit Generate, copy/paste.</Callout>
          </div>
        ),
      },
      {
        id: 'time-series-store',
        title: 'Time-series store — tsdb_query',
        icon: <BarChart3 className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Pump readings, fridge temperatures, alarm rates, market ticks — all of that fits Postgres badly and pgvector worse. v1.1 ships TimescaleDB as a sidecar in the dev-local stack (port <code>5433</code>) and exposes a <code className="text-cyan-300">tsdb_query</code> tool with first-class hypertable support: ingest with <code>insert</code>, query with <code>select</code> + time-bucket aggregates, and pull a sample with <code>recent</code>.</p>
            <p><strong className="text-white">What it solves.</strong> Pump Vibration now writes every severity reading to TSDB, so a downstream agent can answer "what was the average severity for asset X last week?" without scanning every execution row. Cold Chain pivots waypoints to a daily mean. Design Studio caches BNEF cost coefficients with daily-bucket aggregates.</p>
            <p><strong className="text-white">When to use.</strong> Sensor data, KPIs, financial ticks, anything timestamped + numeric you want to aggregate over a window. <strong className="text-white">When not to use.</strong> Document content (that&apos;s a knowledge base). Mutable rows (that&apos;s Postgres).</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Drop the <strong>TSDB query</strong> tool onto the canvas.',
              'Pick the operation: <code>insert</code>, <code>select</code>, <code>recent</code>, or <code>aggregate</code>.',
              'Set the <strong>hypertable name</strong> — pre-seeded ones include <code>iot_pump_readings</code>, <code>iot_cold_chain_waypoints</code>, <code>iot_alarms</code>.',
              'For <code>aggregate</code>: pick the bucket (<code>1m</code>, <code>1h</code>, <code>1d</code>) and the aggregate function (<code>avg</code>, <code>p95</code>, <code>max</code>, <code>count</code>).',
              'Connect the tool, then either downstream of the trigger (insert) or upstream of the agent that needs the rollup.',
            ]} />
            <Callout tone="info">Production swap-out targets are documented under <strong>Scale &amp; operate</strong>: AWS Timestream, Azure Data Explorer, InfluxDB Cloud — each takes one connection-string change.</Callout>
          </div>
        ),
      },
      {
        id: 'idempotency-dlq',
        title: 'Idempotency keys & dead-letter queue',
        icon: <Shield className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>An at-least-once trigger is going to redeliver. A network blip is going to retry. v1.1 makes both safe with two new primitives: an <code className="text-cyan-300">Idempotency-Key</code> header on <code>/api/agents/{`{id}`}/execute</code> (same key inside 24h returns the original execution) and a dead-letter queue for executions the stale sweeper aborts as <code>STALE_SWEEP</code>.</p>
            <p><strong className="text-white">What it solves.</strong> A retry storm on a vibration packet no longer creates ten work orders for the same window. An execution killed by a pod restart shows up on the DLQ page with the full failure context and a one-click <strong>Replay</strong>, so it never just disappears.</p>
            <p><strong className="text-white">When to use.</strong> Idempotency: every external caller that can retry — webhooks, MQTT triggers, an SDK with auto-retry. DLQ: it&apos;s on by default. Nothing to wire.</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Caller passes <code>Idempotency-Key: {`{any-uuid}`}</code> on the execute call.',
              'Server stores key + execution ID in <code>execution_idempotency</code> (TTL 24h).',
              'Same key + same tenant inside the TTL returns the original <code>execution_id</code> and current status — no second run.',
              'For DLQ inspection: open <strong>/admin/dlq</strong>, sort by failure code, click <strong>Replay</strong> to re-enqueue the execution, click <strong>Discard</strong> to mark resolved.',
            ]} />
            <Callout tone="warn"><strong>Gotcha.</strong> The idempotency key is scoped per-tenant + per-agent — two tenants reusing the same UUID don&apos;t collide. Don&apos;t rely on idempotency to deduplicate semantically different inputs. Use a hash of the canonical payload as the key.</Callout>
          </div>
        ),
      },
      {
        id: 'subscribed-feeds',
        title: 'Subscribed feeds',
        icon: <Globe className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Some data is read so often, and changes so rarely, that calling the upstream API from every agent run is wasteful — weather forecasts, FX rates, electricity prices, BNEF cost benchmarks. The <code className="text-cyan-300">subscribed_feed</code> tool lets you register a feed once with a refresh interval, the platform polls in the background, and every agent reads from a TTL cache.</p>
            <p><strong className="text-white">What it solves.</strong> Field Guide&apos;s weather forecast went from "five Open-Meteo calls per work order" to "one cached read." Design Studio&apos;s BNEF cost coefficients refresh once a day at 06:00 UTC instead of on every scenario.</p>
            <p><strong className="text-white">When to use.</strong> Slow-changing reference data — currencies, weather, market indices, public dataset snapshots. <strong className="text-white">When not to use.</strong> User-specific or sensor data — those need fresh reads on every call.</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Drag <strong>Subscribed feed</strong> from the palette.',
              'Pick a registered feed (<strong>weather.open-meteo</strong>, <strong>fx.exchangerate-host</strong>, <strong>bnef.cost-coefficients</strong>) or click <strong>+ Register feed</strong>.',
              'Set the <strong>refresh interval</strong> (60s minimum, 24h default for daily series).',
              'Set the <strong>TTL</strong> for the cache (defaults to 2× refresh interval).',
              'Wire the tool wherever the agent needs the data — the read is a hash-map lookup, sub-millisecond.',
            ]} />
            <Callout tone="info">Subscribed feeds count against the platform&apos;s outbound API budget rather than per-agent cost lines, so a hot agent doesn&apos;t blow its tenant cap on weather lookups.</Callout>
          </div>
        ),
      },
      {
        id: 'audio-stt',
        title: 'Audio STT',
        icon: <Camera className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Field technicians dictate work-order closeouts. Customer-service agents listen to call recordings. Plant operators speak shift reports. The <code className="text-cyan-300">audio_stt</code> tool transcribes any uploaded audio (or an MQTT-published audio blob) using a Deepgram preset — language autodetect, speaker diarisation optional, punctuation always on.</p>
            <p><strong className="text-white">What it solves.</strong> Field Guide&apos;s voice-driven closeout (technician taps the mic, dictates "valve replaced, leak resolved, took 35 min") flows through STT into a structured WO. Alarm Desk&apos;s shift handover ingests the operator&apos;s verbal summary into the EOD report.</p>
            <p><strong className="text-white">When to use.</strong> Any audio you want to feed into a downstream LLM step. <strong className="text-white">When not to use.</strong> Real-time conversational voice — that&apos;s the LiveKit meeting bot path. STT is one-shot.</p>
            <p><strong className="text-white">How to wire.</strong></p>
            <Steps items={[
              'Drop the <strong>Audio STT</strong> tool onto the canvas.',
              'Pick the input source: file upload, URL, MQTT topic, or upstream <code>audio_url</code> field.',
              'Pick the language (auto-detect default) and toggle <strong>diarise speakers</strong> if the recording has two or more voices.',
              'The tool returns a <code>{`{text, words, language, confidence}`}</code> object that flows into the next agent.',
            ]} />
            <Callout tone="warn"><strong>Gotcha.</strong> Deepgram&apos;s API key is required (set <code>DEEPGRAM_API_KEY</code>). Without it the tool falls back to Gemini&apos;s audio path with a warning surfaced into the execution trace.</Callout>
          </div>
        ),
      },
      {
        id: 'edge-runtime',
        title: 'Edge runtimes + .agent bundles',
        icon: <Cpu className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>An offshore wind farm, a pharma cold-storage warehouse, a refinery — all of them have hours where the network is gone or the data is too sensitive to leave the site. The edge runtime takes any Abenix agent flagged <code>edge_compatible</code>, packages it into a signed <code>.agent</code> bundle, and runs it next to the equipment.</p>
            <p><strong className="text-white">Three runtime variants ship.</strong> Same <code>.agent</code> bundle, same MQTT delivery topic, same HTTP contract — pick the one that matches the plant hardware:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-cyan-300">Python</strong> (~80 MB, <code>agentforge/edge-runtime</code>) — default, easiest to extend with tool shims, runs on any box that already has python3.12+.</li>
              <li><strong className="text-orange-300">Rust</strong> (~25 MB, <code>agentforge/edge-runtime-rust</code>) — single static binary for rugged industrial PCs (Moxa UC-8580, Siemens RUGGEDCOM, Beckhoff CX, NVIDIA Jetson). No Python needed on the box.</li>
              <li><strong className="text-slate-300">C</strong> (~12 MB, <code>agentforge/edge-runtime-c</code>) — musl static, for ultra-constrained gateways (Allen-Bradley CompactLogix, Phoenix Contact PLCnext, OpenWRT, ARM Cortex-A7 with 256 MB RAM).</li>
            </ul>
            <p><strong className="text-white">Where to download.</strong> Open <code>/edge</code> in the sidebar — the top section shows all three variants with copy-to-clipboard <strong>Helm install</strong> and <strong>Docker pull</strong> commands. Or call <code>GET /api/edge/runtime/download</code> for the JSON manifest. Helm charts live at <code>infra/helm/edge-runtime/</code>, <code>infra/helm/edge-runtime-rust/</code>, <code>infra/helm/edge-runtime-c/</code>.</p>
            <p><strong className="text-white">How to create a gateway in AgentForge.</strong></p>
            <Steps items={[
              'Mint a registration token: <strong>API Keys → New key</strong>, scopes <code>agents:execute, edge:register</code>. Copy the <code>af_…</code> value — that\'s the gateway\'s <code>PLATFORM_TOKEN</code>.',
              'Helm-install the runtime variant on the plant gateway: <code>helm install abenix-edge ./infra/helm/edge-runtime --set platform.url=$URL --set platform.token=$AF_KEY --set gateway.id=$GW</code>. (Or <code>edge-runtime-rust</code> / <code>edge-runtime-c</code>.)',
              'The pod boots, calls <code>POST /api/edge/gateways/register</code> every 60 s with <code>Authorization: Bearer af_…</code>. The first call inserts the row in <code>edge_gateways</code>. The gateway shows up in the platform UI under <strong>/edge → Registered gateways</strong> within ~60 s.',
              'Mark an agent <strong>Edge eligible</strong> in the Builder → Settings → Advanced. Set <code>edge_constraints</code> (max payload, max runtime, allowed MQTT publish/subscribe topics).',
              'On the gateway card click <strong>Deploy agent</strong>. The platform compiles the <code>.agent</code> bundle (tar with <code>agent.yaml</code>, <code>system_prompt.md</code>, optional <code>tools/*.py</code>, <code>signature.sig</code>), signs it with RSA-PSS / SHA-256, and publishes to <code>edge.{`{gateway_id}`}.deploy</code> over MQTT (HTTP POST fallback). The runtime hot-reloads and the bundle digest appears on the card.',
            ]} />
            <p><strong className="text-white">How interactions work.</strong></p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Bundle delivery (default):</strong> MQTT topic <code>edge.{`{gateway_id}`}.deploy</code> at QoS 1. The runtime verifies the RSA-PSS signature, refuses tampered bundles, extracts to <code>/var/edge/agents/{`{slug}`}/</code>.</li>
              <li><strong>Bundle delivery (fallback):</strong> if MQTT publish fails, the platform <code>POST</code>s the tar bytes to <code>{`{endpoint_url}`}/agents/{`{slug}`}/bundle</code> on the gateway.</li>
              <li><strong>Sync execution:</strong> <code>POST {`{endpoint_url}`}/agents/{`{slug}`}/execute</code> with a JSON body — runtime returns <code>{`{slug, duration_ms, result}`}</code>.</li>
              <li><strong>Async execution:</strong> publish to <code>agents.{`{slug}`}.input</code> over MQTT — runtime invokes the agent and publishes the result on <code>agents.{`{slug}`}.output</code> (subject to <code>edge_constraints.mqtt_publish[]</code> ACL).</li>
              <li><strong>Tool budget:</strong> only <code>mqtt_publish, mqtt_subscribe, current_time, windowed_state, connector_call, code_executor</code> are allowed on edge. Bundle compiler refuses anything else. Runtime re-checks on load.</li>
            </ul>
            <p><strong className="text-white">When to use.</strong> Latency-sensitive sites (sub-100 ms), intermittent connectivity, data-residency regulations. <strong className="text-white">When NOT to use.</strong> Anything that needs platform-only tools (<code>knowledge_search</code>, <code>atlas_*</code>, MCP) or a &gt;2 GB model.</p>
            <Callout tone="info">Bundle format, signing math, manifest schema, and failure modes are documented in <code>infra/edge-runtime/AGENT_BUNDLE_FORMAT.md</code>. End-to-end smoke: <code>scripts/edge-smoke.sh</code>. Pick the variant that matches plant hardware — they all interop with the same bundle.</Callout>

            <h4 className="text-white font-semibold pt-3">Three secrets every gateway needs</h4>
            <table className="w-full text-[12px] border border-slate-700/40 rounded-md overflow-hidden">
              <thead className="bg-slate-800/60 text-slate-400 text-[10.5px] uppercase">
                <tr><th className="text-left py-1.5 px-2">Env</th><th className="text-left py-1.5 px-2">What it does</th><th className="text-left py-1.5 px-2">Get it from</th><th className="text-left py-1.5 px-2">If missing</th></tr>
              </thead>
              <tbody className="text-slate-300">
                <tr className="border-t border-slate-800/40">
                  <td className="px-2 py-1.5 font-mono text-cyan-300">PLATFORM_TOKEN</td>
                  <td className="px-2 py-1.5">af_* API key for /register + heartbeat</td>
                  <td className="px-2 py-1.5"><a href="/edge" className="text-cyan-300 underline">/edge</a> &rarr; <em>Mint edge token + pubkey</em></td>
                  <td className="px-2 py-1.5 text-amber-300">runtime logs 401, gateway shows offline</td>
                </tr>
                <tr className="border-t border-slate-800/40">
                  <td className="px-2 py-1.5 font-mono text-cyan-300">SIGNING_PUBKEY</td>
                  <td className="px-2 py-1.5">RSA-PSS-2048 pub key to verify bundles</td>
                  <td className="px-2 py-1.5">Same mint dialog returns it</td>
                  <td className="px-2 py-1.5 text-rose-300">Rust: accepts UNVERIFIED bundles. C: hard-rejects. Real security gap.</td>
                </tr>
                <tr className="border-t border-slate-800/40">
                  <td className="px-2 py-1.5 font-mono text-cyan-300">ANTHROPIC_API_KEY</td>
                  <td className="px-2 py-1.5">Cloud LLM. Or <code>LOCAL_LLM_URL</code> for air-gapped.</td>
                  <td className="px-2 py-1.5">helm <code>--set anthropic_api_key=$KEY</code></td>
                  <td className="px-2 py-1.5 text-slate-400">Execute returns <code>stub: true</code>. Tool-only agents still work.</td>
                </tr>
              </tbody>
            </table>
            <p className="text-[12px] text-slate-400">
              <strong>On a fresh Azure deploy</strong>, <code>scripts/deploy-azure.sh</code> mints both token and signing pubkey for every edge runtime variant (Python / Rust / C) automatically and passes them into the helm install. For a gateway you provision manually (a real plant box), open <code>/edge</code>, click <strong>Mint edge token + pubkey</strong>, copy both values into the gateway's helm chart or systemd env file. The token is shown ONCE — store it before closing the dialog.
            </p>
            <p className="text-[12px] text-slate-400">
              <strong>Local-LLM vs cloud-LLM at the edge.</strong> Set <code>LOCAL_LLM_URL=http://ollama:11434/v1</code> on the gateway and pin <code>model: ollama/qwen2.5:7b</code> in the agent YAML for air-gapped sites. The Rust runtime auto-detects the <code>ollama/</code> prefix and routes to local. The C runtime is tool-only — no LLM key needed for sensor-loop agents like the IoT pump classifier.
            </p>
          </div>
        ),
      },
      {
        id: 'iot-modernized-examples',
        title: 'Example workflows — modernized IoT use cases',
        icon: <Workflow className="w-4 h-4" />,
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Every Industrial-IoT showcase has a <strong>Live mode</strong> toggle in v1.1 that wires the tab&apos;s pipeline to the new primitives end-to-end. Use them as templates when you build your own.</p>
            <ul className="list-disc pl-5 space-y-2 text-[13px]">
              <li><strong>Pump Vibration → live mode.</strong> The simulator agent publishes packets to <code>vibration.raw</code>. An MQTT trigger wakes the pump pipeline. Severity readings are written to the <code>iot_pump_readings</code> hypertable. High-severity windows raise a CMMS work order via the connector framework.</li>
              <li><strong>Cold Chain → live mode.</strong> Telematics connector (Sensitech preset) feeds waypoints into <code>cold-chain.waypoints</code>. The excursion adjudicator uses <code>windowed_state</code> to detect repeated-breach patterns. The partial-loss claim drops into the broker portal via a custom connector.</li>
              <li><strong>Design Studio → live mode.</strong> The <code>bnef.cost-coefficients</code> subscribed feed refreshes daily. Scenarios re-rank automatically. RFI drafts post into Ariba via a connector preset.</li>
              <li><strong>Field Guide → live mode.</strong> CMMS preset for fleet + WO read. HRIS preset for the tech roster. <code>weather.open-meteo</code> subscribed feed for next-day conditions. Voice closeout flows through <code>audio_stt</code> → CMMS write.</li>
              <li><strong>Alarm Desk → live mode.</strong> MQTT trigger on <code>alarms.realtime</code>. <code>windowed_state</code> for cascade detection. Safe-reset writes via <code>opcua_write</code> behind an <code>approval_gate</code> requiring two operator signoffs. Shift report posts to a logbook connector.</li>
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
            <p>Pick an agent or pipeline, run it for real with your own inputs, then generate Python, TypeScript or Java code that makes the same call with the Abenix SDK. The generator loads the actual SDK source as context, so the code uses real methods.</p>
            <Hero src={SS('16-sdk-playground.png')} alt="SDK Playground" />
            <Steps items={[
              'Search for the agent or pipeline on the left and select it.',
              'Fill <strong>Live inputs</strong>. The panel reads the declared <a href="#pipeline-inputs" class="text-violet-300 underline">inputs</a> and shows a field for each, marked required or optional, plus a message box. Numbers, yes/no values and JSON are sent as their real types.',
              'Click <strong>Run live</strong>. The result panel shows the status, the output and the execution id. A run that reaches an approval gate stops waiting and shows <em>Paused on approval gate</em>, so you can sign it off on Approvals.',
              'Pick a language and a use case, add an optional note such as <em>add retry logic</em>, and click <strong>Generate Code</strong>. The code uses the message and inputs you filled in, passing inputs as the run context.',
              'Python can run straight from the page in a sandbox, with a one-hour API key minted for the run and switched off when it ends. TypeScript and Java are copy only.',
            ]} />
            <p><strong className="text-white">Use cases:</strong> one-shot, streaming, chat threads (create, send a turn, list, history, delegated with act_as), KB search, Cognify, per-user KB collections, batch, HITL and custom. The HITL snippet is end to end: it starts the run with <code className="text-cyan-300">wait=&quot;until_gate&quot;</code>, waits on the approval and prints the resolved status.</p>
            <p className="pt-2 border-t border-slate-800/40 text-slate-400 text-[12.5px]">
              <strong className="text-white">Three SDKs ship today.</strong> Python (<code className="text-cyan-300">packages/sdk/python</code>), TypeScript (<code className="text-cyan-300">packages/sdk/js</code>), and Java/JVM (<code className="text-cyan-300">claimsiq/sdk</code>). The Java SDK is stdlib-only on its public surface, JDK 21 <code>HttpClient</code> for HTTP and SSE, Jackson for JSON, SLF4J for logging, so Kotlin and Scala consumers need no glue. All three have clients for executions, agents, knowledge and approvals. Python and TypeScript also have clients for decisions, sources and events.
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
            <p>Fire N parallel executions against any agent or pipeline, watch p50/p99/p999 latency and per-tool timing. Use it before promoting an agent to production.</p>
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
              'Select the agent or pipeline, provide the input template.',
              'For cron: pick a timezone, set the schedule. For webhook: copy the URL + secret.',
              'Hit <strong>Save</strong>. Activations show up in <em>Executions</em> with a <code>trigger_id</code> tag.',
            ]} />
          </div>
        ),
      },
      {
        id: 'evals',
        title: 'Evaluation suites',
        icon: <FlaskConical className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>An evaluation suite is a set of real inputs for one agent or pipeline, each with checks its answer must pass. Run the suite after a prompt, model or tool change and you see what got better and what broke before anyone else does.</p>
            <p>Running suites needs <code>evals.run</code>, which every role holds. Creating and changing them needs <code>evals.manage</code>, which creators and admins hold.</p>

            <h4 className="text-white font-semibold pt-3">Create a suite</h4>
            <Steps items={[
              'Open <strong>Run &amp; test &rarr; Evaluations</strong> and click <strong>New suite</strong>.',
              'Pick the agent or pipeline, name the suite and say what it covers.',
              'Set the <strong>pass threshold</strong>, the weighted share of cases that must pass for a run to pass. The default is 90%.',
              'Tick <strong>Gate publishing on this suite</strong> if a new version should only publish after this suite passes. See the gate below.',
            ]} />

            <h4 className="text-white font-semibold pt-3">Cases and assertions</h4>
            <p>A case is one input with the checks its answer must pass. Add one on the <strong>Cases</strong> tab with a name, the input message, optional context JSON for the run&apos;s input variables, and tags. Faster still, open any past run under <strong>Executions</strong> and click <strong>Save as eval case</strong>. The run&apos;s input becomes the case and its output seeds suggested assertions you can tighten.</p>
            <p>Assertions you can add:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Field equals / field contains</strong>, a value at a JSON path such as <code>decision</code> or <code>items[0].sku</code>.</li>
              <li><strong className="text-white">Contains / does not contain</strong> a piece of text, and <strong className="text-white">regex</strong> match or no match.</li>
              <li><strong className="text-white">Schema valid</strong>, the output parses as JSON and fits a JSON schema.</li>
              <li><strong className="text-white">Required tools called</strong>, all or any of a list.</li>
              <li><strong className="text-white">Max cost</strong> and <strong className="text-white">max duration</strong>.</li>
              <li><strong className="text-white">Cited sources present</strong>, at least a number of citations.</li>
              <li><strong className="text-white">Model judged</strong>, a model scores the answer against your rubric.</li>
            </ul>
            <p>Before the first run, try the assertions on a sample answer, or on the answer of the run the case was captured from. A case with no assertions passes when the run finishes.</p>

            <h4 className="text-white font-semibold pt-3">Runs and comparing</h4>
            <p>Click <strong>Run now</strong>. Every case runs for real and is scored as it finishes. The run page filters by all, failed, passed and changed, and shows each assertion&apos;s result. The <strong>Runs</strong> tab charts the score over time. Tick two runs to compare them <strong>side by side</strong>, with regressions, improvements and cases still failing.</p>
            <p>The suite&apos;s settings also take a schedule (only when you run it, daily, weekdays, Mondays, every 6 hours or a custom cron, all in UTC), how many cases run at once, the judge model, and for agents whether to run again whenever the agent&apos;s model changes. <strong>Run on another model</strong> runs every case on a different model for that run only, to see whether a switch is safe. The agent keeps its own model.</p>

            <h4 className="text-white font-semibold pt-3">The publish gate</h4>
            <p>When the tier policy for an agent&apos;s tier requires passing evaluations, which High and Critical do by default, a new version publishes only once every gating suite has a passing run against that exact version. Runs on another model do not count. A suite shows <em>Agent changed since</em> when its last run is out of date. Turn the gate on or off per tier under <a href="#risk-tiers" className="text-violet-300 underline">Risk &amp; Controls</a>.</p>
          </div>
        ),
      },
    ],
  },
  // GOVERN
  {
    id: 'govern',
    label: 'Governance',
    blurb: 'Risk tiers, sign-off, stop buttons and who may do what.',
    topics: [
      {
        id: 'risk-tiers',
        title: 'Risk tiers and policies',
        icon: <ShieldAlert className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Every agent, pipeline, tool and decision carries a risk tier: Low, Medium, High or Critical. The tier decides how much sign-off a change needs and what happens when a run reaches for something riskier than itself.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Low</strong> reads data and drafts text a person reads anyway.</li>
              <li><strong className="text-white">Medium</strong> writes to internal systems or produces output other teams rely on.</li>
              <li><strong className="text-white">High</strong> affects customers, money, compliance positions or regulated records.</li>
              <li><strong className="text-white">Critical</strong> covers irreversible or legally binding actions, filings and payments.</li>
            </ul>
            <p><strong className="text-white">Setting a tier.</strong> For an agent or pipeline, pick it on the builder&apos;s General tab. The picker shows what that tier requires and flags what your agent is missing, such as an output schema or a model the tier does not allow. Tools come with a tier set by the platform, listed under <strong>Tool tiers</strong>. A decision gets its tier when you create it.</p>
            <p><strong className="text-white">When a run calls a riskier tool.</strong> A run starts at its agent&apos;s tier. If it calls a tool of a higher tier, the policy for that tier says what happens: <em>Allow</em> (the run goes on and is recorded at the higher tier), <em>Ask a person</em> (the run pauses on Approvals) or <em>Block</em> (the call is refused and the agent is told to raise its tier).</p>
            <h4 className="text-white font-semibold pt-3">Tier policies</h4>
            <p>Open <strong>Admin &rarr; Risk &amp; Controls</strong>. Seeing it needs <code>risk.view</code>, changing policies needs <code>risk.manage</code>. For each tier you set:</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>How many sign-offs a new version needs (0 to 10), whether the author may sign, and the capability signers need, such as <code>approvals.sign:legal</code>.</li>
              <li>What a lower-tier run does when it calls a tool at this tier.</li>
              <li>Whether an output schema is required before going live.</li>
              <li>Whether gating <a href="#evals" className="text-violet-300 underline">evaluation suites</a> must pass before an agent publishes.</li>
              <li>After how many hours an approval nobody has acted on is escalated to admins (0 to 720, 0 means never).</li>
              <li>Which models are allowed. Empty means any.</li>
            </ul>
            <p>Out of the box, Low and Medium need no sign-off. High needs one approver who is not the author, an output schema, passing evals and escalates after 24 hours. Critical needs two approvers and escalates after 4 hours. Saved changes reach new runs within five seconds. <strong>Use the defaults</strong> puts a tier back to the platform values.</p>
            <h4 className="text-white font-semibold pt-3">Audit integrity</h4>
            <p>The activity log is chained entry to entry with hashes, so a changed or removed entry shows. The <strong>Audit integrity</strong> tab verifies the whole chain and reports the first broken link, and exports it so an auditor can check it outside Abenix. Verifying needs <code>audit.verify</code>. Entries from the last minute show as waiting to be linked. People erased for privacy still verify, only who did it is removed.</p>
          </div>
        ),
      },
      {
        id: 'kill-switches',
        title: 'Kill switches',
        icon: <OctagonX className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>A kill switch stops something now, on every server, within five seconds. Nothing is deleted. Resume it when the problem is fixed.</p>
            <Steps items={[
              'Open <strong>Admin &rarr; Risk &amp; Controls &rarr; Kill switches</strong> and click <strong>Stop something</strong>.',
              'Pick what to stop: an agent, a pipeline, a tool, a model, a trigger, a decision, a watched source, or everything in the tenant.',
              'Search for the one to stop, or type a decision key or source.',
              'Give a reason of at least three characters. People who hit the stop see it.',
              'Confirm. The tab shows a count of active switches, and each one has a <strong>Resume</strong> button.',
            ]} />
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Agent.</strong> New runs are refused, running ones stop at their next tool call.</li>
              <li><strong className="text-white">Pipeline.</strong> Stops the pipeline and any agent it is running.</li>
              <li><strong className="text-white">Tool.</strong> Every call to it is refused, in every agent and pipeline.</li>
              <li><strong className="text-white">Model.</strong> Runs that would use it are refused before any tokens are spent.</li>
              <li><strong className="text-white">Trigger.</strong> Its schedule and webhook stop firing.</li>
              <li><strong className="text-white">Decision.</strong> Evaluations are refused.</li>
              <li><strong className="text-white">Watched source.</strong> Change detection pauses.</li>
              <li><strong className="text-white">Everything.</strong> Every agent, pipeline and tool call in the tenant. For incidents.</li>
            </ul>
            <Callout tone="warn">Setting and resuming need <code>killswitch.manage</code>, and both are written to the audit log. A run refused by a switch fails with <code>KILL_SWITCH</code>, which shows on Alerts.</Callout>
          </div>
        ),
      },
      {
        id: 'permissions',
        title: 'Permissions and capabilities',
        icon: <UserCog className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Roles (user, creator, admin) give everyone a baseline. Capabilities add specific abilities on top, so a compliance reviewer can sign rule changes without being made an admin. The sidebar only shows what you can use.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Users</strong> can view and evaluate decisions, view risk policies, run evaluations and replay runs.</li>
              <li><strong className="text-white">Creators</strong> can also author decisions, manage evaluation suites, watched sources and event subscriptions.</li>
              <li><strong className="text-white">Admins</strong> hold every capability.</li>
            </ul>
            <p>Other capabilities include <code>decisions.review</code>, <code>decisions.publish</code>, <code>approvals.sign</code>, <code>risk.manage</code>, <code>killswitch.manage</code>, <code>audit.view</code>, <code>audit.verify</code> and <code>permissions.manage</code>. <code>approvals.sign:legal</code> limits signing to gates that ask for the legal group, while plain <code>approvals.sign</code> covers every gate.</p>
            <h4 className="text-white font-semibold pt-3">Permission sets</h4>
            <Steps items={[
              'Open <strong>Admin &rarr; Permissions</strong>. It needs <code>permissions.manage</code>. The top of the page shows what each role already has.',
              'Click <strong>New permission set</strong>, name it (for example <em>Decision reviewers</em>) and say what it is for.',
              'Tick its capabilities. Filter the list by typing. For signing, choose any approval gate or limit it to named groups.',
              'Add people by name or email. They must already be in the tenant, so invite them under Team first.',
            ]} />
            <p>Grants apply within ten seconds. Removing a person or deleting a set takes the capabilities away again.</p>
          </div>
        ),
      },
      {
        id: 'approvals',
        title: 'Approvals',
        icon: <ShieldCheck className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p><strong>Workspace &rarr; Approvals</strong> is the one queue for everything that waits on a person. Each card has a badge for what kind of gate it is.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong className="text-white">Agent gate.</strong> A running agent paused itself with the <code>human_approval</code> tool, or called a tool above its own tier where the tier policy says ask a person.</li>
              <li><strong className="text-white">Rule change.</strong> A decision version was proposed. The card links to the rules and what changes.</li>
              <li>Other approvals, such as those from the <code>approval_gate</code> tool or from an app calling <code>approvals.create</code> before a sensitive action, show the kind they were raised with, such as <code>device.remote_reset</code>, or no badge.</li>
            </ul>
            <h4 className="text-white font-semibold pt-3">Deciding</h4>
            <Steps items={[
              'Open the card. The payload shows as readable fields, with <strong>Show raw JSON</strong> one click away. The signoff history shows who has acted.',
              'Type a reason. It is kept with your decision.',
              'Click <strong>Approve</strong> or <strong>Deny</strong>. With several sign-offs required, the card counts approvals until enough are in.',
              'Or click <strong>Return for changes</strong> to send it back to the requester without rejecting it. A return needs a reason that says what to change. A returned rule change becomes a draft again with your note on it. Agent gates cannot be returned, only approved or denied.',
            ]} />
            <h4 className="text-white font-semibold pt-3">Tier floor and escalation</h4>
            <p>An approval raised for tiered work takes the tier policy as it stood when it was raised. The policy sets the minimum number of approvers, whether the requester may sign, and the capability signers need. If you requested it yourself and the policy excludes authors, someone else has to approve. A later policy change does not move the goalposts for approvals already waiting.</p>
            <p>A rule change also needs the <code>decisions.review</code> capability to sign. Admins hold it by default. Anyone else gets it from a permission set under <strong>Admin &rarr; Permissions</strong>.</p>
            <p>If nobody acts within the tier&apos;s escalation time, 24 hours for High and 4 hours for Critical by default, every admin in the tenant gets a notification saying how long it has waited and how many sign-offs it has. Each approval escalates once.</p>
            <p>Every card shows a live countdown to expiry. An approval that expires counts as not approved, and the waiting agent is told so. The sidebar shows how many approvals wait on you.</p>
          </div>
        ),
      },
      {
        id: 'run-provenance',
        title: 'What a run used, and replay',
        icon: <History className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Every run records the agent revision, a hash of the system prompt and a snapshot of the exact configuration it ran with. Open a run under <strong>Executions</strong> and the <strong>What this run used</strong> panel shows them, and which settings have changed on the agent since.</p>
            <p><strong className="text-white">Replay</strong> runs an agent again with the same input and the recorded configuration, then shows whether the answer and the tools used came out the same. Model calls are billed again. Pipeline runs replay from a step, with the Replay button on that step. A run whose agent was deleted cannot be replayed. Replay needs <code>runs.replay</code>, which every role holds.</p>
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
        id: 'executions-list',
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
              <li>Use the <em>Re-run</em> button to open the agent with the same input filled in, handy for fix-then-verify cycles. The <em>Step replay</em> panel lists every node in the order it ran with its input, output and duration.</li>
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
            <p>Streams every active execution in real time. Open it in a side window during a load test or a stuck-agent investigation, you see every tool call as it happens.</p>
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
              <li><code className="text-rose-300">block</code> — refuse, execution fails with <code>MODERATION_BLOCKED</code>.</li>
              <li><code className="text-violet-300">redact</code> — mask matching spans, allow through.</li>
              <li><code className="text-amber-300">flag</code> — pass through, log + notify only.</li>
              <li><code className="text-emerald-300">allow</code> — default for un-triggered categories.</li>
            </ul>
            <p>Provider: OpenAI <code>omni-moderation-latest</code> (free for OpenAI customers, ~40–150ms). Falls open if the API key is missing, tenants who want strict fail-closed can set <code>fail_closed=true</code> on the policy.</p>
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
              <li>API publishes the work to NATS JetStream: stream <code>agents</code>, subject <code>agents.&lt;pool&gt;</code> (default, chat, heavy-reasoning, long-running).</li>
              <li>A runtime pod (matching the pool) consumes the message via <code>consumer.py</code>, loads the LLM + tools, runs the agent.</li>
              <li>Runtime publishes events back over Redis: <code>start</code>, <code>tool_call</code>, <code>tool_result</code>, <code>token</code>, <code>done</code> or <code>error</code>.</li>
              <li>API streams those events to the caller (or blocks if <code>wait=true</code>).</li>
            </ol>

            <h4 className="text-white font-semibold pt-2">Why remote is more robust</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>Crash recovery</strong>. If a runtime pod dies mid-agent, NATS redelivers the message and another pod reruns the agent from the start. Tool side effects from the first try can repeat. After 3 pickups the run fails with <code>STALE_SWEEP</code>.</li>
              <li><strong>Resource isolation</strong> — heavy-reasoning agents can&apos;t OOM the API.</li>
              <li><strong>Independent scaling</strong> — API runs at predictable CPU. Runtime pools KEDA-autoscale per pool to 0 between bursts.</li>
              <li><strong>Per-pool routing</strong> — chat agents on a small pool, heavy on the big pool, governed independently by per-pool KEDA triggers on JetStream consumer lag.</li>
            </ul>

            <h4 className="text-white font-semibold pt-2">Toggling</h4>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`# Production — default in this Helm chart
kubectl -n abenix set env deployment/abenix-api RUNTIME_MODE=remote

# Dev / single-pod — agent runs in the API process
kubectl -n abenix set env deployment/abenix-api RUNTIME_MODE=embedded`}</pre>

            <Callout tone="info">
              All Atlas tools work in both modes. In embedded mode the tools execute in-process, in remote mode they execute on the runtime pod. The tenant + per-agent <code>atlas_graphs</code> allow-list is enforced identically in both code paths.
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
              <li><strong>long-running</strong> — over-30s executions, bigger CPU/RAM, slower scale.</li>
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
            <p>Tune <code>listLength</code> down for lower latency at higher cost, tune up to save money at the cost of queue wait. The <code>/admin/scaling</code> page exposes these knobs to admins without a helm upgrade — see the <a href="#admin-scaling" className="text-violet-300 underline">Scaling Console</a> topic below.</p>
          </div>
        ),
      },
      {
        id: 'scaling-three-layers',
        title: 'Three scaling layers (agents · tools · pipelines)',
        icon: <Gauge className="w-4 h-4" />,
        badge: 'Architecture',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>The runtime pool above is only <em>one</em> of three concentric scaling layers. Each addresses a different way the platform can get swamped, and each has its own admin UI. All three pages, and the APIs behind them, are admin only. They <strong>compose</strong> — you don&apos;t need a separate "pipelines" runtime, because pipelines re-use agent + tool scaling underneath.</p>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 text-[12.5px]">
              <div className="rounded-lg border border-violet-700/40 bg-violet-900/15 p-3">
                <div className="text-violet-300 font-semibold mb-1">Layer 1 — Agents + pods</div>
                <div className="text-slate-400 mb-2"><a href="/admin/scaling" className="text-violet-300 underline">/admin/scaling</a></div>
                <p className="text-slate-300 mb-2">Per-agent <code>runtime_pool</code>, <code>min_replicas</code>, <code>max_replicas</code>, <code>concurrency_per_replica</code>, <code>rate_limit_qps</code>, <code>daily_budget_usd</code>. Once a tenant has spent <code>daily_budget_usd</code> on the agent in a UTC day, or the agent has spent its <code>daily_cost_limit</code> across everyone, new runs are refused with <code>BUDGET_EXCEEDED</code> until midnight UTC. 0 means no cap.</p>
                <p className="text-slate-300 mb-2">The daily caps are checked before any run starts on every path: the agent page, the API, triggers, pipelines and pipeline steps, meetings, OracleNet, governance replays, a2a and batch. A refusal is 429 <code>BUDGET_EXCEEDED</code> with today&apos;s spend (UTC) and who can raise the cap. A saved agent run as a pipeline step counts toward its own caps once the pipeline finishes, without counting twice in the organization totals.</p>
                <p className="text-slate-300 mb-2"><code>per_execution_cost_limit</code> caps one run. After each model call the run checks its spend, and once the limit is reached and the agent wants another step it stops with <code>BUDGET_EXCEEDED</code>. The answer so far and every step stay in the Flight Recorder, ending with a <code>budget_stop</code> step. A final answer that crosses the limit is kept. Pipelines apply the same limit across steps, and an API caller can only tighten it with <code>cost_limit</code>. A pipeline run&apos;s cost includes what failed and retried steps spent.</p>
                <p className="text-slate-400 text-[11.5px]">Stops the api pod from doing agent work itself. KEDA scales the pool deployments on NATS JetStream consumer lag.</p>
              </div>
              <div className="rounded-lg border border-cyan-700/40 bg-cyan-900/15 p-3">
                <div className="text-cyan-300 font-semibold mb-1">Layer 2 — Tools</div>
                <div className="text-slate-400 mb-2"><a href="/admin/tool-scaling" className="text-cyan-300 underline">/admin/tool-scaling</a></div>
                <p className="text-slate-300 mb-2">Per-tool gate: <strong>cache</strong> → <strong>breaker</strong> → <strong>qps</strong> (global + per-tenant) → <strong>daily budget</strong> → <strong>semaphore</strong>. Plus <code>pool=inline|runtime</code>.</p>
                <p className="text-slate-400 text-[11.5px]">Stops 50 callers from each calling Yahoo at once. <code>pool=runtime</code> pushes execution onto the agent-runtime fleet so api pods don&apos;t block.</p>
              </div>
              <div className="rounded-lg border border-emerald-700/40 bg-emerald-900/15 p-3">
                <div className="text-emerald-300 font-semibold mb-1">Layer 3 — Pipelines</div>
                <div className="text-slate-400 mb-2"><a href="/admin/pipeline-scaling" className="text-emerald-300 underline">/admin/pipeline-scaling</a></div>
                <p className="text-slate-300 mb-2">Pure composition. No new primitives. The pipeline pod lives in Layer 1. Agent nodes route to Layer 1. Tool nodes go through Layer 2. Control nodes run in-process.</p>
                <p className="text-slate-400 text-[11.5px]">Drill into any pipeline&apos;s DAG to see exactly which pool / cache / qps each node uses.</p>
              </div>
            </div>

            <h4 className="text-white font-semibold pt-3">The tool gate (Layer 2) — order of checks</h4>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li><strong>Cache lookup</strong> — SHA-256 of canonical args. Scope <code>global</code> for public data, <code>per_tenant</code> for private. TTL=0 disables.</li>
              <li><strong>Circuit breaker</strong> — opens after N failures in window. Goes half-open after the cooldown.</li>
              <li><strong>Rate limit</strong> — Redis token bucket. The <code>(global)</code> and <code>(per-tenant)</code> caps are applied in sequence.</li>
              <li><strong>Daily budget</strong> — per-tenant Redis counter, resets at UTC midnight.</li>
              <li><strong>Semaphore</strong> — Redis INCR with TTL longer than the tool timeout. Global + per-tenant inflight caps.</li>
            </ol>
            <p className="text-[12.5px] text-slate-400">Fails open on Redis errors so an outage doesn&apos;t take the platform down. Every <code>POST /api/tools/&#123;slug&#125;/execute</code>, every preset run, every agent-loop tool call goes through the same function.</p>

            <h4 className="text-white font-semibold pt-3">Pool dispatch — when <code>pool=&apos;runtime&apos;</code></h4>
            <p>The api pod doesn&apos;t execute the tool. It XADDs <code>tools:queue</code> with a per-job result channel, then SUBSCRIBEs and awaits the reply. Agent-runtime pods run <code>tool_stream_consumer.py</code> as a background task — KEDA capacity provisioned for agents is reused for tools without a separate deployment.</p>

            <h4 className="text-white font-semibold pt-3">Decision tree for an incident</h4>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li><strong>Open <a href="/admin/scaling" className="text-violet-300 underline">/admin/scaling</a>.</strong> Is the pool pinned at max replicas? Move the loud agent to a less-contested pool or raise its <code>max_replicas</code>.</li>
              <li><strong>Open <a href="/admin/tool-scaling" className="text-cyan-300 underline">/admin/tool-scaling</a>.</strong> Any tool with red breaker dot or many 24h calls? Raise its qps (if external can take it) or its cache TTL.</li>
              <li><strong>Open <a href="/admin/pipeline-scaling" className="text-emerald-300 underline">/admin/pipeline-scaling</a>.</strong> Expand the slow pipeline. The slow node is either an agent (go to step 1) or a tool (step 2). Control nodes don&apos;t scale separately.</li>
              <li>Only after all three show green: it&apos;s the external provider. Add a breaker and an alert.</li>
            </ol>

            <Callout tone="info">
              Full dev-doc reference: <a href="/docs?slug=02-runtime%2F08-queue-scaling" target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline">02-runtime/08-queue-scaling</a>.
            </Callout>
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
              <li><strong>Connection pooling</strong> via PgBouncer. The default pod-side pool is 20 per API replica, PgBouncer collapses N×20 client conns to a fixed primary-side limit.</li>
              <li><strong>pgvector → Pinecone</strong> when embeddings exceed ~5M rows. Per-collection toggle, no code change.</li>
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
            <p>Redis carries: rate-limit counters, KB ingestion job state, the WebSocket broker for real-time updates, the LLM cache, and the Celery queues for document, cognify and KB jobs. Agent runs never queue on Redis.</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Default deployment: a single Redis pod, persistence off — fine for ~50 RPS.</li>
              <li>Above 50 RPS, switch to <strong>Redis Cluster mode</strong> (the bundled bitnami chart supports it) and enable AOF persistence.</li>
              <li>Queued agent runs need <strong>NATS JetStream</strong>. See the NATS topic next.</li>
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
              <strong className="text-white">Queued agent runs run on NATS JetStream only.</strong> With <code>scaling.queueBackend: nats</code> the Helm chart deploys an <code>abenix-nats</code> StatefulSet, and KEDA scales each runtime pool on its JetStream consumer lag.
            </p>

            <h4 className="text-white font-semibold pt-3">Topology</h4>
            <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 overflow-x-auto">{`API publishes  ──▶  NATS JetStream stream "agents"
                          │ subjects: agents.<pool>
                          ▼
        ┌─────────────────┬──────────────────┬──────────────────────┐
        ▼                 ▼                  ▼                      ▼
  agents.default    agents.chat     agents.heavy-reasoning   agents.long-running
  (one durable consumer per pool, abenix-<pool>-consumer)`}</pre>

            <h4 className="text-white font-semibold pt-3">At-least-once delivery</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>The runtime acks a message only after the run ends. While it runs, the pod sends heartbeats to NATS and renews a lease on the run&apos;s execution row every few seconds.</li>
              <li>A duplicate for a run that already finished is dropped. A duplicate for a run another pod is still working on waits.</li>
              <li>If the pod dies, its lease runs out (25 seconds by default) and another pod reruns the agent from the start. Tool calls with side effects can happen twice in that case.</li>
              <li>After 3 pickups the run fails with <code>STALE_SWEEP</code> instead of looping. <code>CONSUMER_LEASE_SECONDS</code> and <code>CONSUMER_MAX_ATTEMPTS</code> change these.</li>
              <li>The trace context rides along in the message, so one trace covers the API, the queue, the runtime and any child agents when <code>OTEL_EXPORTER_OTLP_ENDPOINT</code> is set.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Settings</h4>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li>Backend selector: <code>QUEUE_BACKEND=nats</code>, set from <code>scaling.queueBackend</code>. The local and Azure values use it.</li>
              <li>Connection: <code>NATS_URL=nats://abenix-nats:4222</code>. Auth via <code>NATS_USER</code> and <code>NATS_PASSWORD</code>.</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">With Celery</h4>
            <p>
              <code>scaling.queueBackend: celery</code> cannot run agents remotely. The chart refuses <code>scaling.execRemote</code> or runtime pools with it, a runtime pool pod exits at startup with a clear error, and the API runs the agent inline when it cannot enqueue. Celery still runs document, cognify and KB jobs.
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
            <p>Each runtime pod ships Docker / Podman, sandboxes are spawned per-execution. Resource caps live on <code>SandboxImagePolicy</code>: default 512 MB / 30s / no network. Three things matter at scale:</p>
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
                <tr className="border-b border-slate-800/60"><td className="py-1.5"><strong>pgvector</strong></td><td>Up to ~5M chunks per collection. In-cluster, no extra cost.</td><td>Single primary, vacuum windows can pause ingestion.</td></tr>
                <tr><td className="py-1.5"><strong>Pinecone</strong></td><td>10M+ chunks, multi-tenant cost amortisation.</td><td>External dep + cost. ~50 ms network round-trip.</td></tr>
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
            <p>Set <code>STORAGE_BACKEND=s3</code> and the standard AWS env vars, the API + worker share the bucket through the <code>StorageService</code> abstraction. Multi-region: set the bucket region close to the cluster, large blobs are streamed, not buffered, so latency doesn&apos;t spike memory.</p>
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
              <li><strong>Budget</strong> — per-tenant monthly USD cap, on overage the gate returns <code>BUDGET_EXCEEDED</code>.</li>
              <li><strong>Sandbox concurrency</strong> — described above.</li>
            </ul>
            <p>Surface tenant fairness on the dashboard: the <code>abenix_active_executions{`{tenant_id}`}</code> gauge is per-tenant, Grafana&apos;s &quot;Top tenants&quot; panel highlights the loud neighbours.</p>
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
              <li>Deploy the full stack per region, route traffic via Cloudflare / Akamai based on lowest latency.</li>
              <li>Set <code>DATABASE_URL_RO</code> in non-write regions so list endpoints stay local.</li>
              <li>Object storage: prefer a single bucket with cross-region replication enabled.</li>
              <li>LLM provider keys: keep one set globally, provider rate-limits aggregate across regions.</li>
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
            <p>Pre-wired observability ships with <code>scripts/deploy.sh</code>. <strong>Prometheus</strong> scrapes <code>/api/metrics</code> on the API every 15s, <strong>Grafana</strong> renders the bundled &quot;Abenix Operations&quot; dashboard.</p>
            <Hero src={SS('09-grafana-dashboard.png')} alt="Grafana — Abenix Operations dashboard" caption="Operations Overview — LLM spend, tokens, execution outcomes, failure breakdown by code, stale sweeps" />
            <Callout tone="info">
              Grafana is intentionally <strong>not exposed on the public ingress</strong>. Reach it via port-forward:
              <pre className="text-xs bg-slate-950/60 border border-slate-800 rounded p-3 mt-2 overflow-x-auto">{`bash scripts/portforward-azure.sh start
# Forwards Grafana on http://localhost:3010 (admin / abenix-admin)
# Tempo raw API on http://localhost:3200, Prometheus on http://localhost:9090`}</pre>
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
              <li className="text-emerald-300">abenix_code_asset_invocations_total{`{code_asset_id,status}`} <span className="text-slate-500">(v1.4.0)</span></li>
              <li className="text-emerald-300">abenix_code_asset_duration_seconds (histogram)</li>
              <li className="text-emerald-300">abenix_ml_model_invocations_total{`{ml_model_id,operation,status}`} <span className="text-slate-500">(v1.4.0)</span></li>
              <li className="text-emerald-300">abenix_ml_model_duration_seconds (histogram)</li>
              <li className="text-emerald-300">abenix_ml_model_cost_usd_total{`{ml_model_id}`}</li>
              <li className="text-emerald-300">abenix_kb_query_invocations_total{`{kb_collection_id,status}`}</li>
              <li className="text-emerald-300">abenix_kb_query_duration_seconds (histogram)</li>
            </ul>

            <h4 className="text-white font-semibold pt-3">Resource invocation log (v1.4)</h4>
            <p>Every <code>code_asset</code> pod run, <code>ml_model</code> prediction, and <code>knowledge_search</code> query is now persisted as a first-class row in the new <code>code_asset_invocations</code>, <code>ml_model_invocations</code>, and <code>kb_query_invocations</code> tables. The Invocations panel on <a href="/code-runner" className="text-cyan-300 underline">/code-runner</a> and <a href="/ml-models" className="text-cyan-300 underline">/ml-models</a> reads from these tables: 24h stats card (totals, error rate, p95 duration, top calling agents, total ML cost) plus a scrollable list of recent runs. Click any row → expand to see input, output, stdout/stderr, predicted class, confidence, parent agent execution link.</p>
            <p><strong className="text-white">Live updates (v1.4.1):</strong> Once you open the Invocations tab, new runs stream into the panel via SSE — the "live" indicator turns on, and new rows prepend to the list automatically as agents fire elsewhere. Powered by Redis pub/sub channel <code>invocations:{`{kind}:{resource_id}`}</code> with a 15-second heartbeat to keep the connection alive.</p>
            <h4 className="text-white font-semibold pt-3">Backfill from existing executions (v1.4.2)</h4>
            <p>Historical agent runs from before the v1.4.0 deploy live in <code>executions.tool_calls</code> JSONB blobs but not in the new invocation tables. Run <code>scripts/backfill_resource_invocations.py</code> via <code>kubectl exec abenix-api ... python /app/scripts/backfill_resource_invocations.py</code> with optional <code>BACKFILL_DAYS</code> env var (default 30). Script is idempotent — re-runs skip rows already backfilled (marked <code>caller_source=&apos;backfill&apos;</code>).</p>
            <h4 className="text-white font-semibold pt-3">Pre-built Grafana dashboard (v1.4.3)</h4>
            <p>Dashboard JSON at <code>infra/observability/dashboards/resource-invocations.json</code> ships via the existing Grafana ConfigMap provisioning. Nine panels: invocation rate per resource, p95 latency, error rate stat, cumulative ML cost, 24h spend stat. Auto-loaded by Grafana at startup. Template variables let you filter by <code>code_asset_id</code> or <code>ml_model_id</code>.</p>
            <h4 className="text-white font-semibold pt-3">Distributed tracing (v1.5.0)</h4>
            <p><strong className="text-white">What it does:</strong> Every agent execution becomes a single timeline ("trace") you can open in Grafana to see <em>exactly</em> where the seconds went. An agent run that took 47s shows as a flame graph: HTTP request (200ms) → desk-copilot ReAct loop (43s) → tool.recall_trajectory (120ms) → tool.invoke_agent (3.2s) → child agent (2.9s) → tool.ml_model (180ms) → … The pattern that took 80% of the wall clock is the one you optimize.</p>
            <p><strong className="text-white">Implementation:</strong> <code>opentelemetry-sdk</code> in both <code>apps/api</code> + <code>apps/agent-runtime</code>. New <code>engine/tracing.py</code> init helper. Manual spans wrap <code>agent.execute</code> and <code>tool.{`{name}`}</code> at runtime. FastAPI + httpx auto-instrumentation captures every inbound and outbound HTTP call. Trace context propagates via W3C TraceContext headers (auto-handled) and via <code>traceparent</code> in NATS message envelopes for the queue-backed remote runs.</p>
            <p><strong className="text-white">Backend:</strong> Grafana Tempo, deployed as <code>abenix-tempo</code> in the cluster — single-replica, local storage, 7-day retention. Configured as a Grafana datasource so admins can search by trace_id, drill into spans, and view the service-map graph.</p>
            <p><strong className="text-white">PII redaction:</strong> a custom span processor strips any attribute named <code>llm.prompt</code>, <code>llm.completion</code>, <code>tool.args</code>, <code>tool.input</code>, <code>tool.output</code>, <code>agent.system_prompt</code> before export. The redacted value becomes <code>&lt;redacted len=N sha256=...&gt;</code> so you can still grep by content hash without leaking the raw text into Tempo.</p>
            <p><strong className="text-white">Sampling:</strong> 10% probabilistic baseline via <code>OTEL_TRACES_SAMPLER_ARG=0.1</code>. Parent-based sampler — once a trace is sampled at the entry point every span downstream is also sampled, so you never see partial flame graphs. Crank to 1.0 (100%) for debugging by setting the env var.</p>
            <p><strong className="text-white">Linking from executions:</strong> Each <code>executions</code> row now has a <code>trace_id</code> column (32-char hex). The execution detail page exposes a "View Trace" link that deep-links into Grafana → Tempo → that exact trace.</p>
            <p><strong className="text-white">End-user walkthrough:</strong></p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Trader at <code>/desk</code> asks a question → desk-copilot fans out → Anthropic Sonnet 4.5 thinks → invokes 3 specialists → stitches a brief. Total 47s.</li>
              <li>Trader (or admin) opens <code>/executions/{`{exec_id}`}</code>, sees the standard execution detail page. Bottom-right has a <strong>View Trace</strong> button (only renders when <code>trace_id</code> is present).</li>
              <li>Click → opens Grafana Explore in a new tab with the Tempo datasource pre-selected and the trace pre-loaded.</li>
              <li>Flame graph: 47s wall clock decomposes as 3.5s LLM call (Anthropic 200 OK), 2.8s sub-agent 1 (mispricing), 11.2s sub-agent 2 (forecaster — the long one), 0.4s sub-agent 3, 28s waiting on the final LLM stitch. Action: tune the forecaster's model_config.</li>
              <li>Click any span → side panel shows attributes (agent.id, tool.name, llm.model, llm.tokens.input). Prompts and outputs are <code>&lt;redacted&gt;</code> with a sha256 hash so the trace is shareable with the SRE team without leaking trader data.</li>
              <li>Service map (Grafana Tempo &quot;Service Graph&quot; tab): shows the call graph across abenix-api → agent-runtime → external Anthropic API → sandbox pod (when code_asset fires). Red edges flag latency outliers.</li>
            </ol>
            <Callout tone="info">
              Grafana Tempo runs as <code>abenix-tempo</code> in-cluster (single-replica, local emptyDir storage, 7-day retention). For multi-node clusters or higher durability, swap the storage block to <code>backend: s3</code> in the ConfigMap. Tempo is forwarded by <code>portforward-azure.sh</code> on <code>http://localhost:3200</code>. You can also reach traces through Grafana at <code>http://localhost:3010</code> → <strong>Explore → Tempo</strong>.
            </Callout>
            <h4 className="text-white font-semibold pt-3">Notification fan-out</h4>
            <ul className="list-disc pl-5 space-y-0.5 text-[12px]">
              <li><strong>WebSocket</strong> — always on, powers the bell.</li>
              <li><strong>Slack</strong> — set <code>ABENIX_SLACK_WEBHOOK_URL</code>. Per-user opt-in via Settings.</li>
              <li><strong>Email</strong> — set <code>SMTP_HOST / SMTP_USER / SMTP_PASS / SMTP_FROM</code>.</li>
            </ul>
            <h4 className="text-white font-semibold pt-3">Stale-execution sweeper</h4>
            <p>An APScheduler job runs every 5 minutes and marks any execution still <code>RUNNING</code> for &gt;<code>STALE_EXECUTION_MAX_MINUTES</code> (default 30) as <code>FAILED</code> with <code>failure_code=STALE_SWEEP</code>. A Postgres advisory lock ensures only one API replica runs the sweep per interval.</p>
          </div>
        ),
      },
      {
        id: 'archives',
        title: 'Archives — retention + cold-storage dumps',
        icon: <Archive className="w-4 h-4" />,
        badge: 'admin',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Recording tables (anything that&apos;s append-only — invocations, executions, messages, activity logs) get garbage-collected on a schedule so they don&apos;t balloon the live DB. Old rows are streamed to gzipped JSONL on a persistent volume, then deleted from the source table after a sha256 verification.</p>
            <p><strong className="text-white">Schedule:</strong> nightly at <code>02:00 UTC</code> via APScheduler inside <code>abenix-api</code> — same scheduler that handles cron triggers and the stale-execution sweeper.</p>
            <p><strong className="text-white">Default retention:</strong></p>
            <ul className="list-disc pl-5 space-y-0.5 text-[12px] font-mono">
              <li>code_asset_invocations — 30 days</li>
              <li>ml_model_invocations — 30 days</li>
              <li>kb_query_invocations — 30 days</li>
              <li>executions — 60 days</li>
              <li>messages — 60 days</li>
              <li>activity_logs — 90 days</li>
            </ul>
            <p>Admin-editable per-table at <a href="/admin/archives" className="text-cyan-300 underline">/admin/archives</a>. Toggle <code>enabled</code> off to pause archiving for a table. Bump <code>retention_days</code> upward to keep more history.</p>
            <p><strong className="text-white">Dump format:</strong> <code>/data/archives/{`{table}/{YYYY-MM}/{table}-{timestamp}-{batch}.jsonl.gz`}</code>. Each line is one row as JSON. Files survive pod restarts (hostPath volume). Sha256 of the dump is stored in <code>archive_runs.file_sha256</code> so you can verify offline copies haven&apos;t been tampered with.</p>
            <p><strong className="text-white">Manual trigger:</strong> on the admin page, click any table button to fire an archive right now. Useful before a long retention-policy change (archive what&apos;s about-to-expire first so it lands in a clean dump).</p>
            <p><strong className="text-white">Restore:</strong> v1 has no restore UI by design. Admin downloads the .jsonl.gz via the &quot;dump&quot; link, extracts on a workstation, and re-imports into a forensic database. The original rows have stable UUIDs so a careful <code>INSERT ... ON CONFLICT DO NOTHING</code> can re-hydrate the live table if needed. Restore-from-UI ships in v1.5.0.</p>
            <Callout tone="warn">
              The hostPath volume is single-node. For multi-node clusters or higher durability, mount a PVC (RWX storage class) at <code>/data/archives</code> instead. The archiver writes via <code>ARCHIVE_ROOT</code> env, default <code>/data/archives</code>.
            </Callout>
            <h4 className="text-white font-semibold pt-3">End-user walkthrough</h4>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Day 0: admin opens <code>/admin/archives</code>, sees the seeded default retention policies, leaves them alone.</li>
              <li>Day 30 at 02:00 UTC: scheduler fires the first archive job for <code>code_asset_invocations</code> — streams rows older than 30 days into <code>code_asset_invocations-2026-06-15T020000-{`{rand}`}.jsonl.gz</code> on the abenix-api pod&apos;s <code>/data/archives/</code>, verifies sha256, then deletes those rows in 1000-row batches.</li>
              <li>Compliance audit hits: open <code>/admin/archives</code>, find the run for May 2026, click <strong>dump</strong>, download the gzipped JSONL, grep with <code>zcat | jq</code>.</li>
              <li>If a row was hot-data that shouldn&apos;t have been archived, edit the retention policy upward (e.g. 30 → 90 days) so the same window stays live going forward.</li>
            </ol>
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
              <li><code>/admin/llm-settings</code> — which models are exposed to which agents. Disable expensive models tenant-wide, force a fallback to cheaper ones.</li>
              <li><code>/admin/tool-config</code> — every API key and setting a built-in tool needs, grouped by provider and generated from the tools themselves. Save a value and agents use it within 30 seconds, no redeploy. Rows show where the value comes from (saved here, environment, defaults file) and a Test button checks the key with the provider. A tool that is missing a required key tells the user so, and names this screen.</li>
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
            <p>Mint platform keys for SDK use. Scopes: <code>execute</code>, <code>read</code>, <code>write</code>, <code>can_delegate</code>. Bcrypt-hashed at rest, the plaintext is shown once at creation.</p>
            <Hero src={SS('27-api-keys.png')} alt="API keys" />
            <h4 className="text-white font-semibold pt-3">actAs delegation</h4>
            <p>For third-party apps holding a platform key: pass <code>X-Abenix-Subject: &lt;end-user-id&gt;</code> on every request. The runtime treats the request as if that subject were calling, and applies row-level RBAC accordingly.</p>
          </div>
        ),
      },
      {
        id: 'events',
        title: 'Events and subscriptions',
        icon: <Bell className="w-4 h-4" />,
        badge: 'new',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p>Events let the platform tell your systems what happened, or start an agent or pipeline when it does. Each event is recorded together with the change that caused it, so none are lost, and failed deliveries retry on their own.</p>
            <p>Events you can subscribe to: a run completed or failed, an approval requested or resolved, a decision proposed, published or retired, a kill switch set or cleared, a watched source changed, and an evaluation run completed.</p>
            <h4 className="text-white font-semibold pt-3">Create a subscription</h4>
            <Steps items={[
              'Open <strong>Admin &rarr; Events</strong> and click <strong>New subscription</strong>. Creating and changing subscriptions needs <code>events.manage</code>, which creators and admins hold.',
              'Name it, for example <em>Reassess products when a rule is published</em>, and tick the events. Ticking a whole group takes every event in it, including ones added later.',
              'Optionally add conditions under <strong>Only when the event says</strong>, such as <code>decision_key</code> is <code>freight.remote.surcharge</code>. Several values can be given with commas.',
              'Pick the target. <strong>Call a URL</strong> posts the event to your endpoint. <strong>Run an agent</strong> or <strong>Run a pipeline</strong> starts it as you, with a message that can use event fields such as <code>{{data.decision_key}}</code>. The whole event is also in the run&apos;s context.',
              'Create it. For a URL target the signing secret is shown once. Copy it now.',
            ]} />
            <h4 className="text-white font-semibold pt-3">Signing</h4>
            <p>Every call to a URL carries <code>X-Abenix-Signature</code>, an HMAC-SHA256 of the body with your signing secret. Check it on your side before trusting the call. <code>X-Abenix-Event</code> names the event and <code>X-Abenix-Delivery</code> is its id, which you can use to ignore repeats.</p>
            <h4 className="text-white font-semibold pt-3">Deliveries</h4>
            <p>Each subscription card has <strong>Send test</strong>, which sends a sample event that appears in the delivery log within seconds. The log lists each delivery with its status. For agent and pipeline targets it links to the run it started. Failed calls retry with growing gaps for about eight hours. <strong>Redeliver</strong> sends any delivery again. The pause button stops a subscription without deleting it.</p>
            <Callout tone="info">A typical use: subscribe a pipeline to <code>source.changed</code> with a condition on the source&apos;s tags, so every change to a tariff page gets a first read and a summary for review.</Callout>
          </div>
        ),
      },
      {
        id: 'tool-configuration',
        title: 'Tool configuration',
        icon: <Wrench className="w-4 h-4" />,
        badge: 'admin',
        body: (
          <div className="space-y-3 text-[13.5px] text-slate-300 leading-relaxed">
            <p><strong>Admin &rarr; Tool Configuration</strong> lists every key and setting a built-in tool needs, one card per provider and one row per key. It needs the admin role. New tools appear here on their own, with no UI work.</p>
            <p>Each row says whether the value is set and where it comes from: saved for this tenant, saved for the platform, from the environment, from <code>tool_defaults.yaml</code>, the tool&apos;s own default, or not set. A row marked <strong>required</strong> belongs to a tool that cannot run without it.</p>
            <Steps items={[
              'Pick the scope at the top. <strong>This tenant</strong> is the default and shows what your agents run with. <strong>Platform</strong> is the fallback for every tenant that has not saved its own value.',
              'Search by key, provider or tool.',
              'Paste the value and click <strong>Save</strong>. Agents pick it up within about 30 seconds, no redeploy.',
              'Where offered, <strong>Test</strong> sends one request to the provider with the value and reports the answer.',
              '<strong>Clear tenant value</strong> or <strong>Clear platform value</strong> removes what was saved so the next source applies again.',
            ]} />
            <p>Secrets are masked after saving and encrypted with the cluster key when one is set. The page header says which. A tool missing a required key tells the agent, in one sentence, which key to ask an admin for. The Tools Catalogue and the builder palette show a badge per tool: needs key, optional key or key set.</p>
            <Callout tone="info">Not here: MCP tools keep credentials on their connection under MCP Servers, and code assets keep their own secrets in Code Runner. Source Watch sign-in credentials are set here, under Source Watch.</Callout>
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
              There is <strong>no global super-admin endpoint</strong> that lists or creates tenants. The seeded <code>admin@abenix.dev</code> account is admin of the seeded tenant only — it can&apos;t see any other tenant&apos;s data. To run N organisations on one Abenix instance, have one person from each organisation register, they each get their own tenant + admin.
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
                  <td>Real users, they accept via emailed link, set their own password.</td>
                </tr>
                <tr>
                  <td className="py-2"><strong>Dev create</strong></td>
                  <td><code>POST /api/team/dev-create-member</code></td>
                  <td>E2E tests / immediate provisioning, admin sets the password.</td>
                </tr>
              </tbody>
            </table>
            <Callout tone="info">
              Both paths require <code>role=admin</code> and hard-scope the new user to the caller&apos;s tenant — <strong>no cross-tenant invites are possible</strong>. The backend enforces the scope on the route, not just the UI.
            </Callout>

            <h4 className="text-white font-semibold pt-3">3 · Roles</h4>
            <p>Three roles, hot-applied (next request reads the new role from <code>/api/me/permissions</code>):</p>
            <ul className="list-disc pl-5 space-y-1 text-[13px]">
              <li><strong>admin</strong> — full control inside the tenant. Can invite, change roles, set quotas, configure tenant settings, see all members&apos; activity, hit every <code>/admin/*</code> page.</li>
              <li><strong>creator</strong> — same as user, plus can publish agents/pipelines to the marketplace and earn from subscriptions.</li>
              <li><strong>user</strong> — default. Builds and runs their own agents, cannot manage team / quotas / tenant settings.</li>
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
            <p>The 3 roles drive coarse access, <strong>feature flags</strong> drive fine-grained access. The flag table is <code>ROLE_FEATURES</code> in <code>apps/api/app/core/permissions.py</code>. Every user gets <code>view_dashboard</code>, <code>create_agents</code>, <code>use_builder</code>, <code>create_pipelines</code>, <code>use_chat</code>, <code>use_kb</code>, <code>use_persona</code>, <code>use_ml_models</code>, <code>use_code_runner</code>, <code>use_meetings</code>, <code>use_triggers</code>, <code>view_executions</code>, <code>view_analytics</code>, <code>view_alerts</code>, <code>use_marketplace</code>, <code>use_sdk_playground</code>, <code>use_load_playground</code>, <code>manage_api_keys</code> and <code>manage_mcp</code>. Creators add <code>manage_ontology</code> and <code>publish_to_marketplace</code>. Admins add <code>review_queue</code>, <code>manage_team</code>, <code>manage_settings</code> and <code>see_other_users_resources</code>. Each sidebar item declares the <code>feature</code> that shows it (Meetings is <code>use_meetings</code>, Review Queue is <code>review_queue</code>, Model Selection / Tool Configuration / LLM Pricing / Connectors / Integrations are <code>manage_settings</code>, Team is <code>manage_team</code>). <code>see_other_users_resources</code> is read by the API list scopes, <code>publish_to_marketplace</code> by the publish check and <code>manage_ontology</code> by the schema editor routes. The frontend renders the sidebar from <code>/api/me/permissions</code>, which resolves:</p>
            <ol className="list-decimal pl-5 space-y-1 text-[13px]">
              <li>Default flags from the user&apos;s role.</li>
              <li>Tenant overrides applied on top (admin can disable a feature for everyone, e.g. turn off Marketplace for an enterprise deployment).</li>
              <li>The merged map is returned and consumed.</li>
            </ol>
            <Callout tone="warn">
              The sidebar is a UX hint, <strong>not</strong> the security boundary. Every route on the API independently re-checks role + feature flag. Hiding a sidebar item without disabling the feature flag does not actually deny access.
            </Callout>

            <h4 className="text-white font-semibold pt-3">6 · Per-resource sharing</h4>
            <p>The <code>ResourceShare</code> table grants a specific user <code>READ</code> or <code>EDIT</code> on a specific agent / pipeline / KB / atlas — without changing their role. Click <strong>Share</strong> on any agent / KB / atlas detail page, pick teammates + scope. Used for cross-team handoffs without elevating roles.</p>
            <p className="text-[12px]">A <code>creator</code> shared into <code>EDIT</code> on a single agent gets to edit only that one agent — nothing else changes about their permissions. Revoking a share is instant, the next API call from that user will fail.</p>

            <h4 className="text-white font-semibold pt-3">7 · Multiplexing many end-users through one tenant — actAs</h4>
            <p>When a SaaS app holds a platform API key and serves many end-users (a typical &quot;build on top of Abenix&quot; scenario), the app passes <code>X-Abenix-Subject: &lt;end-user-id&gt;</code> on every request. The API treats the request as if that subject were calling — applies row-level RBAC, attributes audit-log events to that subject, scopes resource lookups to subject-bound collections.</p>
            <p className="text-[12px]">Critical property: <strong>the actAs subject can&apos;t escape the agent&apos;s tenant</strong>. Rows still belong to the agent&apos;s <code>tenant_id</code>. Cross-app reads remain impossible at the SQL layer. The subject is a sub-identity inside the tenant, not a different tenant.</p>
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
              'They open <code>/settings/team</code> and invite teammates by email, choose <code>admin</code> / <code>creator</code> / <code>user</code> per invite.',
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
            <p>Settings has a tab per area: Profile, API Keys, Billing (when monetization is on), Team, Integrations, Notifications, Observability, Security, Data &amp; DLP, Privacy &amp; GDPR, Events, Token Quotas and Sandbox. The Events tab is the same page as <a href="#events" className="text-violet-300 underline">Events</a> and shows only to people with <code>events.manage</code>. Without it the page says an admin can grant it under <strong>Admin &rarr; Permissions</strong>.</p>
            <p>When your session expires you land back on the sign-in form with a notice. After you sign in you return to the page you were on. Notifications (toasts) show on every page, the sign-in page included.</p>
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
