'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, useInView } from 'framer-motion';
import { Boxes, ShieldCheck, Cpu, Workflow } from 'lucide-react';
import AuthCard from './AuthCard';

const features = [
  {
    icon: Workflow,
    label: 'AI-Powered Builder',
    desc: 'Describe it, the platform builds it',
  },
  {
    icon: Cpu,
    label: 'Bring-Your-Own Code',
    desc: 'Upload a repo, get a tool',
  },
  {
    icon: Boxes,
    label: '100+ Built-in Tools',
    desc: 'Plus MCP + sandboxed jobs',
  },
  {
    icon: ShieldCheck,
    label: 'Moderation + DLP + RBAC',
    desc: 'Policy-gated execution path',
  },
];

const stats: Array<{ value: number; prefix?: string; suffix: string; label: string }> = [
  { value: 79, suffix: '', label: 'Pre-Built Agents' },
  { value: 100, suffix: '+', label: 'Built-in Tools' },
  { value: 49, suffix: '', label: 'Test Suites' },
];

function CountUp({
  value,
  prefix,
  suffix,
}: {
  value: number;
  prefix?: string;
  suffix?: string;
}) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });

  useEffect(() => {
    if (!inView) return;
    let start = 0;
    const duration = 1500;
    const step = value / (duration / 16);
    const timer = setInterval(() => {
      start += step;
      if (start >= value) {
        setCount(value);
        clearInterval(timer);
      } else {
        setCount(Math.floor(start));
      }
    }, 16);
    return () => clearInterval(timer);
  }, [inView, value]);

  return (
    <span ref={ref} className="text-2xl font-bold text-white">
      {prefix}
      <span className="text-cyan-400">{count.toLocaleString()}</span>
      {suffix}
    </span>
  );
}

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.1 } },
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

export default function HeroSection() {
  return (
    <section
      id="hero"
      className="relative z-10 min-h-screen flex items-center pt-20 pb-16"
    >
      <div className="max-w-7xl mx-auto px-6 w-full">
        <div className="flex flex-col lg:flex-row items-center gap-12 lg:gap-16">
          <motion.div
            variants={container}
            initial="hidden"
            animate="show"
            className="flex-1 lg:max-w-[55%]"
          >
            <motion.div variants={item} className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-sm font-medium">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                AI Agent Orchestration Engine
              </span>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-violet-500/10 border border-violet-500/30 text-violet-200 text-xs font-semibold">
                <ShieldCheck className="w-3 h-3" />
                Enterprise-ready · multi-tenant · MIT-licensed
              </span>
            </motion.div>

            <motion.h1
              variants={item}
              className="text-5xl md:text-6xl font-bold text-white mt-8 leading-tight"
            >
              Build, Deploy &
            </motion.h1>
            <motion.h1
              variants={item}
              className="text-5xl md:text-6xl font-bold gradient-text-hero leading-tight"
            >
              Orchestrate AI Agents
            </motion.h1>

            <motion.p
              variants={item}
              className="text-lg text-slate-400 max-w-xl mt-6 leading-relaxed"
            >
              One open-source platform for agents, pipelines, and ontologies.
              Describe what you need in plain English and the builder assembles
              the agent for you — or drag-and-drop your own from 100+ built-in
              tools, uploaded code, trained ML models, and sandboxed jobs.
              Atlas turns your documents into a typed graph that agents
              traverse like citations. Policy-gated execution with moderation,
              DLP, RBAC, and full observability from day one.
            </motion.p>

            <motion.div
              variants={item}
              className="grid grid-cols-2 gap-3 mt-10"
            >
              {features.map((f) => (
                <div
                  key={f.label}
                  className="bg-slate-800/30 border border-slate-700/50 rounded-xl px-4 py-3 flex items-start gap-3 hover:border-cyan-500/20 transition-colors"
                >
                  <div className="w-9 h-9 rounded-lg bg-cyan-500/10 flex items-center justify-center shrink-0 mt-0.5">
                    <f.icon className="w-[18px] h-[18px] text-cyan-400" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-white">{f.label}</p>
                    <p className="text-xs text-slate-500 mt-0.5">{f.desc}</p>
                  </div>
                </div>
              ))}
            </motion.div>

            <motion.div
              variants={item}
              className="flex items-center gap-8 mt-8"
            >
              {stats.map((s, i) => (
                <div key={s.label} className="flex items-center gap-8">
                  {i > 0 && (
                    <div className="w-px h-10 bg-slate-700/50" />
                  )}
                  <div>
                    <CountUp
                      value={s.value}
                      prefix={s.prefix}
                      suffix={s.suffix}
                    />
                    <p className="text-xs text-slate-500 mt-1">{s.label}</p>
                  </div>
                </div>
              ))}
            </motion.div>
          </motion.div>

          <div className="flex-1 flex justify-center lg:justify-end w-full lg:max-w-[45%]">
            <AuthCard />
          </div>
        </div>
      </div>
    </section>
  );
}
