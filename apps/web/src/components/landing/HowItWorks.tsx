'use client';

import { useRef } from 'react';
import { motion, useInView } from 'framer-motion';
import { ArrowRight, LayoutDashboard, Plug, Rocket } from 'lucide-react';

const steps = [
  {
    number: '01',
    title: 'Design',
    description:
      'Describe your agent in plain English or open the drag-and-drop builder. Pick a model, wire in tools, and preview the generated pipeline before saving.',
    icon: LayoutDashboard,
  },
  {
    number: '02',
    title: 'Connect',
    description:
      'Upload a code repo or ML model, attach MCP servers, link knowledge bases, and configure per-tool parameter defaults. Schemas, examples, and build caches are inferred for you.',
    icon: Plug,
  },
  {
    number: '03',
    title: 'Deploy',
    description:
      'One-click publish to a private tenant or share with your team. Autoscaling runtime pools, moderation / DLP gates, Prometheus + Grafana, and per-agent cost budgets ship on by default.',
    icon: Rocket,
  },
];

export default function HowItWorks() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-100px' });

  return (
    <section id="how-it-works" className="relative z-10 py-24">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5 }}
            className="text-3xl md:text-4xl font-bold gradient-text inline-block"
          >
            How It Works
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="text-slate-400 mt-4 max-w-2xl mx-auto"
          >
            Three steps from idea to production-ready AI agent.
          </motion.p>
        </div>

        <motion.div
          ref={ref}
          initial="hidden"
          animate={inView ? 'show' : 'hidden'}
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.15 } } }}
          className="flex flex-col md:flex-row items-center md:items-start gap-6 md:gap-0"
        >
          {steps.map((step, i) => (
            <div key={step.number} className="flex items-center flex-1 w-full">
              <motion.div
                variants={{
                  hidden: { opacity: 0, y: 30 },
                  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
                }}
                className="flex-1 flex flex-col items-center text-center"
              >
                <div className="relative mb-6">
                  <div className="w-20 h-20 rounded-full bg-gradient-to-br from-cyan-500/20 to-purple-600/20 border-2 border-cyan-500/30 flex items-center justify-center">
                    <step.icon className="w-8 h-8 text-cyan-400" />
                  </div>
                  <span className="absolute -top-2 -right-2 w-8 h-8 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center text-xs font-bold text-white">
                    {step.number}
                  </span>
                </div>
                <h3 className="text-xl font-bold text-white mb-2">
                  {step.title}
                </h3>
                <p className="text-sm text-slate-400 max-w-xs leading-relaxed">
                  {step.description}
                </p>
              </motion.div>

              {i < steps.length - 1 && (
                <div className="hidden md:flex items-center px-4 pt-10">
                  <div className="w-12 h-px bg-gradient-to-r from-cyan-500/50 to-purple-500/50" />
                  <ArrowRight className="w-5 h-5 text-slate-600 -ml-1" />
                </div>
              )}
            </div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
