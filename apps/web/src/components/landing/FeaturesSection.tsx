'use client';

import { useRef } from 'react';
import { motion, useInView } from 'framer-motion';
import {
  BarChart3,
  Brain,
  Code2,
  Database,
  LayoutDashboard,
  Package,
  Plug,
  Radio,
  Sparkles,
  Shield,
  Users,
  Zap,
} from 'lucide-react';

const features = [
  {
    icon: Sparkles,
    title: 'AI-Powered Builder',
    description:
      'Describe what you need in plain English. The builder generates complete agents or pipelines with tools, parameters, and configurations — ready to execute in seconds.',
    highlight: true,
  },
  {
    icon: Code2,
    title: 'Bring-Your-Own-Code Tools',
    description:
      'Upload a zip or point at a git repo — Python, Node, Go, Rust, Ruby, Java, Perl. The analyzer detects the language, runs it in a sandbox, and exposes it to every agent as a first-class tool with schema discovery and a build cache.',
    highlight: true,
  },
  {
    icon: Package,
    title: 'Deploy ML Models as Tools',
    description:
      'Upload scikit-learn, XGBoost, or ONNX models. The platform introspects the feature set, wraps inference in a sandboxed job, and exposes the model to agents through the same tool registry your Python code uses.',
    highlight: true,
  },
  {
    icon: Shield,
    title: 'Moderation + DLP + RBAC',
    description:
      'Pre-LLM and post-LLM moderation gates on every execution. DLP scans input for PII in detect / mask / block modes. Per-user resource isolation via polymorphic ResourceShare. Every agent inherits the tenant\'s policy.',
  },
  {
    icon: LayoutDashboard,
    title: 'Visual Pipeline Builder',
    description:
      'Drag-and-drop canvas with 100+ built-in tools, switch routing, merge nodes, error branches, per-node timeouts, while loops, and for-each parallel iteration.',
  },
  {
    icon: Brain,
    title: 'Multi-Model + Multi-Agent',
    description:
      'Route across Claude, GPT, Gemini. Chain agents as pipeline steps. LLM-powered dynamic routing with confidence-gated branching. Per-agent runtime pools with KEDA queue-depth autoscaling.',
  },
  {
    icon: Plug,
    title: 'MCP + 100+ Built-in Tools',
    description:
      'Financial, risk, KYC/AML, market data, weather, patents, Twilio, Plotly charts, browser automation, PII redactor, memory, moderation, and more. Plus full MCP protocol for unlimited extensibility.',
  },
  {
    icon: Database,
    title: 'Knowledge Engine — Projects, Ontology, Hybrid Search',
    description:
      'Organise collections into projects, control access per agent and per user, author a domain ontology that constrains entity extraction, and explore correlations across collections. Hybrid retrieval over Pinecone or pgvector plus Neo4j graph traversal. Bootstrap endpoint for standalone-app integrations.',
  },
  {
    icon: Users,
    title: 'Meeting Primitives',
    description:
      'Eight tools for live-meeting agents: join, listen, speak, post-chat, leave, plus persona RAG, defer-to-human, and scope gating. Sub-3s response latency. Meetings become an agent execution surface, not a separate product.',
  },
  {
    icon: Radio,
    title: 'Live Debug & Flight Recorder',
    description:
      'Real-time SSE streaming with per-node status. Full execution traces, waterfall visualization, replay from any node. Prometheus /metrics on every pod, Grafana dashboards, and /alerts page grouped by failure_code.',
  },
  {
    icon: Zap,
    title: 'Wave-2 Scale: NATS + KEDA + Multi-Pool',
    description:
      'Per-agent runtime pools with KEDA queue-depth scaling. NATS JetStream transport, Redis execution bus, stale-sweeper with advisory locks. Validated at 500+ concurrent workflows without regression.',
  },
  {
    icon: BarChart3,
    title: 'Enterprise: Drift, Cost, HITL',
    description:
      'Statistical drift detection, per-execution cost budgets, human-in-the-loop approval gates, moderation queue, Slack / email / webhook alerts, and circuit breakers with adaptive retry.',
  },
];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};

const item = {
  hidden: { opacity: 0, y: 30 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

export default function FeaturesSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-100px' });

  return (
    <section id="features" className="relative z-10 py-24">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5 }}
            className="text-3xl md:text-4xl font-bold gradient-text inline-block"
          >
            Platform Capabilities
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="text-slate-400 mt-4 max-w-2xl mx-auto"
          >
            Everything you need to ship production-grade AI agents — builder,
            runtime, tools, knowledge, observability, and governance — in one
            platform.
          </motion.p>
        </div>

        <motion.div
          ref={ref}
          variants={container}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
          className="grid md:grid-cols-2 lg:grid-cols-3 gap-5"
        >
          {features.map((f) => {
            const isHighlight = (f as { highlight?: boolean }).highlight;
            return (
            <motion.div
              key={f.title}
              variants={item}
              className={`rounded-2xl p-6 transition-all group ${
                isHighlight
                  ? 'bg-gradient-to-br from-cyan-500/5 to-purple-500/5 border border-cyan-500/30 hover:border-cyan-400/50 shadow-lg shadow-cyan-500/5'
                  : 'bg-slate-800/30 border border-slate-700/50 hover:border-cyan-500/30 hover:shadow-lg hover:shadow-cyan-500/10'
              }`}
            >
              {isHighlight && (
                <span className="inline-block text-[8px] font-bold uppercase tracking-wider text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded-full mb-3">
                  Unique to Abenix
                </span>
              )}
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 transition-colors ${
                isHighlight ? 'bg-cyan-500/20 group-hover:bg-cyan-500/30' : 'bg-cyan-500/10 group-hover:bg-cyan-500/20'
              }`}>
                <f.icon className="w-6 h-6 text-cyan-400" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-2">
                {f.title}
              </h3>
              <p className="text-sm text-slate-400 leading-relaxed">
                {f.description}
              </p>
            </motion.div>
          );})}
        </motion.div>
      </div>
    </section>
  );
}
