'use client';

import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Brain,
  Zap,
  MessageSquare,
  Workflow,
  Shuffle,
  GitBranch,
  Repeat,
  BarChart3,
  Play,
  ArrowRight,
} from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';

// Props

interface BuilderHelpDialogProps {
  open: boolean;
  onClose: () => void;
}

// SVG Illustrations

function AgentIllustration() {
  return (
    <svg
      viewBox="0 0 160 120"
      fill="none"
      className="w-full h-auto"
      aria-hidden="true"
    >
      {/* Central brain node */}
      <circle cx="80" cy="60" r="22" fill="#06B6D4" fillOpacity={0.15} stroke="#06B6D4" strokeWidth={1.5} />
      <Brain
        // inline lucide path
        x={68}
        y={48}
        width={24}
        height={24}
        className="text-cyan-400"
      />
      {/* We can't use lucide JSX inside SVG, so draw a simple brain shape */}
      <path
        d="M74 55 C72 50, 78 47, 80 50 C82 47, 88 50, 86 55 C89 57, 89 63, 86 65 C88 68, 84 72, 80 70 C76 72, 72 68, 74 65 C71 63, 71 57, 74 55Z"
        fill="#06B6D4"
        fillOpacity={0.4}
        stroke="#06B6D4"
        strokeWidth={1}
      />
      {/* Radiating connections — dashed lines to tool circles */}
      <line x1="80" y1="38" x2="80" y2="18" stroke="#06B6D4" strokeWidth={1} strokeDasharray="3 2" strokeOpacity={0.5} />
      <line x1="98" y1="48" x2="130" y2="28" stroke="#06B6D4" strokeWidth={1} strokeDasharray="3 2" strokeOpacity={0.5} />
      <line x1="98" y1="72" x2="130" y2="92" stroke="#06B6D4" strokeWidth={1} strokeDasharray="3 2" strokeOpacity={0.5} />
      <line x1="62" y1="48" x2="30" y2="28" stroke="#06B6D4" strokeWidth={1} strokeDasharray="3 2" strokeOpacity={0.5} />
      <line x1="62" y1="72" x2="30" y2="92" stroke="#06B6D4" strokeWidth={1} strokeDasharray="3 2" strokeOpacity={0.5} />
      {/* Tool circles */}
      <circle cx="80" cy="14" r="8" fill="#0F172A" stroke="#06B6D4" strokeWidth={1} strokeOpacity={0.6} />
      <text x="80" y="18" textAnchor="middle" fill="#06B6D4" fontSize="8" fontFamily="monospace">?</text>
      <circle cx="134" cy="24" r="8" fill="#0F172A" stroke="#06B6D4" strokeWidth={1} strokeOpacity={0.6} />
      <text x="134" y="28" textAnchor="middle" fill="#06B6D4" fontSize="8" fontFamily="monospace">T</text>
      <circle cx="134" cy="96" r="8" fill="#0F172A" stroke="#06B6D4" strokeWidth={1} strokeOpacity={0.6} />
      <text x="134" y="100" textAnchor="middle" fill="#06B6D4" fontSize="8" fontFamily="monospace">T</text>
      <circle cx="26" cy="24" r="8" fill="#0F172A" stroke="#06B6D4" strokeWidth={1} strokeOpacity={0.6} />
      <text x="26" y="28" textAnchor="middle" fill="#06B6D4" fontSize="8" fontFamily="monospace">T</text>
      <circle cx="26" cy="96" r="8" fill="#0F172A" stroke="#06B6D4" strokeWidth={1} strokeOpacity={0.6} />
      <text x="26" y="100" textAnchor="middle" fill="#06B6D4" fontSize="8" fontFamily="monospace">T</text>
      {/* "AI decides" label */}
      <text x="80" y="112" textAnchor="middle" fill="#94A3B8" fontSize="7" fontFamily="sans-serif">AI decides which tools to use</text>
    </svg>
  );
}

function PipelineIllustration() {
  return (
    <svg
      viewBox="0 0 160 120"
      fill="none"
      className="w-full h-auto"
      aria-hidden="true"
    >
      {/* Step A (top-left) */}
      <rect x="8" y="20" width="36" height="22" rx="4" fill="#10B981" fillOpacity={0.15} stroke="#10B981" strokeWidth={1.2} />
      <text x="26" y="34" textAnchor="middle" fill="#10B981" fontSize="8" fontWeight="bold" fontFamily="sans-serif">A</text>
      {/* Step B (bottom-left) */}
      <rect x="8" y="78" width="36" height="22" rx="4" fill="#10B981" fillOpacity={0.15} stroke="#10B981" strokeWidth={1.2} />
      <text x="26" y="92" textAnchor="middle" fill="#10B981" fontSize="8" fontWeight="bold" fontFamily="sans-serif">B</text>
      {/* Step C (center) — fan-in */}
      <rect x="62" y="44" width="36" height="28" rx="4" fill="#10B981" fillOpacity={0.2} stroke="#10B981" strokeWidth={1.5} />
      <text x="80" y="62" textAnchor="middle" fill="#10B981" fontSize="9" fontWeight="bold" fontFamily="sans-serif">C</text>
      {/* Step D (right) */}
      <rect x="116" y="48" width="36" height="22" rx="4" fill="#10B981" fillOpacity={0.15} stroke="#10B981" strokeWidth={1.2} />
      <text x="134" y="62" textAnchor="middle" fill="#10B981" fontSize="8" fontWeight="bold" fontFamily="sans-serif">D</text>
      {/* Edges A→C */}
      <path d="M44 31 L62 52" stroke="#10B981" strokeWidth={1.5} markerEnd="url(#arrowGreen)" />
      {/* Edges B→C */}
      <path d="M44 89 L62 64" stroke="#10B981" strokeWidth={1.5} markerEnd="url(#arrowGreen)" />
      {/* Edge C→D */}
      <path d="M98 58 L116 58" stroke="#10B981" strokeWidth={1.5} markerEnd="url(#arrowGreen)" />
      {/* Parallel indicator */}
      <text x="6" y="62" fill="#10B981" fontSize="7" fontFamily="sans-serif" fillOpacity={0.6}>parallel</text>
      <path d="M4 50 L4 72" stroke="#10B981" strokeWidth={0.8} strokeDasharray="2 2" strokeOpacity={0.4} />
      {/* Arrow marker */}
      <defs>
        <marker id="arrowGreen" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6" fill="none" stroke="#10B981" strokeWidth={1} />
        </marker>
      </defs>
      {/* Label */}
      <text x="80" y="112" textAnchor="middle" fill="#94A3B8" fontSize="7" fontFamily="sans-serif">You design the execution flow</text>
    </svg>
  );
}

// Feature list items

const AGENT_FEATURES = [
  { icon: MessageSquare, text: 'Conversational \u2014 chat back and forth' },
  { icon: Brain, text: 'AI decides which tools to use and when' },
  { icon: Shuffle, text: 'Dynamic flow \u2014 varies per conversation' },
  { icon: Repeat, text: 'Great for open-ended, exploratory tasks' },
];

const PIPELINE_FEATURES = [
  { icon: Workflow, text: 'Visual DAG \u2014 drag, connect, run' },
  { icon: GitBranch, text: 'You design exact steps and data flow' },
  { icon: Zap, text: 'Parallel execution of independent steps' },
  { icon: BarChart3, text: 'Repeatable, auditable, deterministic' },
];

// Component

export default function BuilderHelpDialog({
  open,
  onClose,
}: BuilderHelpDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  // Trap Escape key
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  return (
    <ResponsiveModal open={open} onClose={onClose} title="Agent vs Pipeline" maxWidth="max-w-2xl">
      <div className="space-y-6">
        {/* Two-card comparison */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Agent card */}
          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                <Brain className="w-4 h-4 text-cyan-400" />
              </div>
              <h3 className="text-sm font-semibold text-cyan-400">
                Agent
              </h3>
            </div>

            <div className="bg-slate-900/60 rounded-lg p-2">
              <AgentIllustration />
            </div>

            <ul className="space-y-2">
              {AGENT_FEATURES.map(({ icon: Icon, text }) => (
                <li
                  key={text}
                  className="flex items-start gap-2 text-xs text-slate-300"
                >
                  <Icon className="w-3.5 h-3.5 text-cyan-400/70 mt-0.5 shrink-0" />
                  <span>{text}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Pipeline card */}
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                <Zap className="w-4 h-4 text-emerald-400" />
              </div>
              <h3 className="text-sm font-semibold text-emerald-400">
                Pipeline
              </h3>
            </div>

            <div className="bg-slate-900/60 rounded-lg p-2">
              <PipelineIllustration />
            </div>

            <ul className="space-y-2">
              {PIPELINE_FEATURES.map(({ icon: Icon, text }) => (
                <li
                  key={text}
                  className="flex items-start gap-2 text-xs text-slate-300"
                >
                  <Icon className="w-3.5 h-3.5 text-emerald-400/70 mt-0.5 shrink-0" />
                  <span>{text}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* When to use */}
        <div className="space-y-3">
          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            When to use which?
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="rounded-lg bg-cyan-500/5 border border-cyan-500/10 px-3 py-2.5">
              <p className="text-[11px] font-medium text-cyan-400 mb-1">
                Use Agent when...
              </p>
              <ul className="text-[11px] text-slate-400 space-y-0.5">
                <li>- You want a conversational assistant</li>
                <li>- Tasks are open-ended or exploratory</li>
                <li>- The AI should decide the approach</li>
                <li>- Users interact via chat</li>
              </ul>
            </div>
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/10 px-3 py-2.5">
              <p className="text-[11px] font-medium text-emerald-400 mb-1">
                Use Pipeline when...
              </p>
              <ul className="text-[11px] text-slate-400 space-y-0.5">
                <li>- You have a repeatable workflow</li>
                <li>- Steps and data flow are known ahead</li>
                <li>- You need parallel execution</li>
                <li>- Results must be auditable</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Example */}
        <div className="rounded-lg bg-slate-800/50 border border-slate-700/50 p-4 space-y-3">
          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Same task, two approaches
          </h4>
          <p className="text-xs text-slate-300 italic">
            &ldquo;Compare the writing quality of Claude vs GPT-4o&rdquo;
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <p className="text-[10px] font-semibold text-cyan-400">
                Agent approach
              </p>
              <div className="flex items-center gap-1 text-[10px] text-slate-500 flex-wrap">
                <span className="px-1.5 py-0.5 bg-slate-800 rounded text-cyan-400/70">Chat</span>
                <ArrowRight className="w-3 h-3" />
                <span className="px-1.5 py-0.5 bg-slate-800 rounded text-cyan-400/70">AI reasons</span>
                <ArrowRight className="w-3 h-3" />
                <span className="px-1.5 py-0.5 bg-slate-800 rounded text-cyan-400/70">Tools</span>
                <ArrowRight className="w-3 h-3" />
                <span className="px-1.5 py-0.5 bg-slate-800 rounded text-cyan-400/70">Reply</span>
              </div>
              <p className="text-[10px] text-slate-500">
                AI decides steps dynamically each turn
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-[10px] font-semibold text-emerald-400">
                Pipeline approach
              </p>
              <div className="flex items-center gap-1 text-[10px] text-slate-500 flex-wrap">
                <span className="px-1.5 py-0.5 bg-slate-800 rounded text-emerald-400/70">LLM A</span>
                <span className="text-slate-600">&amp;</span>
                <span className="px-1.5 py-0.5 bg-slate-800 rounded text-emerald-400/70">LLM B</span>
                <ArrowRight className="w-3 h-3" />
                <span className="px-1.5 py-0.5 bg-slate-800 rounded text-emerald-400/70">Merge</span>
                <ArrowRight className="w-3 h-3" />
                <span className="px-1.5 py-0.5 bg-slate-800 rounded text-emerald-400/70">Report</span>
              </div>
              <p className="text-[10px] text-slate-500">
                Fixed steps, parallel execution, same flow every time
              </p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end pt-2">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </ResponsiveModal>
  );
}
