'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Sparkles, Loader2, Send, History, ArrowRight, Activity, Brain, Newspaper, ExternalLink } from 'lucide-react';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip, { PipelineNode } from '../components/PipelineStrip';

const TERMINAL = new Set(['completed', 'succeeded', 'failed', 'error', 'cancelled']);

const KNOWN_SPECIALISTS: Record<string, { label: string; hint: string }> = {
  'wingman-arb-analyzer': { label: 'Arb analyzer', hint: '12mo forward net-arb' },
  'wingman-mispricing-extractor': { label: 'Mispricing Lens', hint: 'Bayesian fair-value + IsoForest' },
  'wingman-scenario-forecaster': { label: 'Forward Scenarios', hint: 'GaussianNB prior + LLM posterior' },
  'wingman-ops-monitor': { label: 'Ops Monitor', hint: 'AIS + weather + alerts' },
  'wingman-graph-query': { label: 'Knowledge Graph', hint: 'typed Atlas traversal' },
  'wingman-market-brief': { label: 'Market Brief', hint: 'morning macro indicators' },
  'wingman-broker-classifier': { label: 'Broker Classifier', hint: 'TF-IDF intent tag' },
  'wingman-broker-parser': { label: 'Broker Parser', hint: 'LLM structured offer' },
};

interface Driver { category?: string; headline?: string; source?: string; url?: string; impact_usd_mt?: number; }
interface PlanStep { agent: string; rationale?: string; input_summary?: string; }
interface DeskAnswer {
  intent?: string;
  plan?: PlanStep[];
  specialist_outputs?: Record<string, any>;
  headline?: string;
  brief?: string;
  drivers?: Driver[];
  recommended_action?: string;
  cited_trajectories?: string[];
  confidence?: string;
}

interface DeskResponse {
  execution_id: string;
  status: string;
  question?: string;
  answer?: DeskAnswer | null;
  error_message?: string | null;
  cost_usd?: number;
  duration_ms?: number;
}

interface Trajectory {
  id: string;
  intent: string;
  agents_invoked?: string[];
  headline?: string;
  brief?: string;
  recommended_action?: string;
  confidence?: string;
  created_at?: string;
  approval_id?: string | null;
  success_signal?: number | null;
}

const SAMPLE_QUESTIONS = [
  'Should I trade the USGC->NWE propane arb this week?',
  'Which corridor has the cheapest forward right now, and what is the conviction?',
  'Is the Aug-15 USGC->FE strategy still viable given current weather and counterparty credit?',
  'Summarise everything that moved propane spreads in the last 7 days.',
];

export default function DeskPage() {
  const [question, setQuestion] = useState('');
  const [running, setRunning] = useState(false);
  const [meta, setMeta] = useState<DeskResponse | null>(null);
  const [answer, setAnswer] = useState<DeskAnswer | null>(null);
  const [activeExecution, setActiveExecution] = useState<string | null>(null);
  const [history, setHistory] = useState<Trajectory[]>([]);
  const pollerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadHistory = () => {
    fetch('/api/wingman/desk/trajectories?limit=20')
      .then((r) => r.json())
      .then((j) => setHistory(j?.data || []))
      .catch(() => {});
  };

  useEffect(() => {
    loadHistory();
    const t = setInterval(loadHistory, 30_000);
    return () => clearInterval(t);
  }, []);

  const ask = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text || running) return;
    setQuestion(text);
    setRunning(true);
    setAnswer(null);
    setMeta(null);
    try {
      const r = await fetch('/api/wingman/desk/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      });
      const j = await r.json();
      const execId = j?.data?.execution_id;
      if (!execId) { setRunning(false); return; }
      setActiveExecution(execId);
      if (pollerRef.current) clearInterval(pollerRef.current);
      pollerRef.current = setInterval(async () => {
        try {
          const rr = await fetch(`/api/wingman/desk/result/${execId}`);
          const jj = await rr.json();
          const data: DeskResponse = jj?.data;
          if (!data) return;
          if (TERMINAL.has((data.status || '').toLowerCase())) {
            setMeta(data);
            setAnswer(data.answer || null);
            setRunning(false);
            if (pollerRef.current) clearInterval(pollerRef.current);
            pollerRef.current = null;
            loadHistory();
          }
        } catch { /* keep polling */ }
      }, 2500);
    } catch {
      setRunning(false);
    }
  };

  const replayTrajectory = (t: Trajectory) => {
    setAnswer({
      intent: t.intent,
      headline: t.headline,
      brief: t.brief,
      recommended_action: t.recommended_action,
      confidence: t.confidence,
      plan: (t.agents_invoked || []).map((a) => ({ agent: a })),
    });
    setQuestion(t.intent || '');
    setMeta(null);
    setActiveExecution(null);
  };

  const planNodes: PipelineNode[] = useMemo(() => {
    const planned = (answer?.plan || []).map((p) => ({
      id: p.agent,
      label: KNOWN_SPECIALISTS[p.agent]?.label || p.agent,
      kind: 'agent' as const,
      icon: 'sparkles' as const,
      hint: KNOWN_SPECIALISTS[p.agent]?.hint || p.rationale,
    }));
    return [
      { id: 'wingman-desk-copilot', label: 'Desk Copilot', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'planner + synthesiser' },
      { id: 'recall_trajectory', label: 'Past trajectories', icon: 'cpu' as const, hint: 'phase-2 memory lookup' },
      { id: 'invoke_agent', label: 'Fan-out', icon: 'tool' as const, hint: 'invoke_agent → each specialist' },
      ...planned,
    ];
  }, [answer?.plan]);

  return (
    <div className="p-6">
      <HeroBar
        eyebrow="DESK COPILOT"
        title="Ask the desk anything."
        subtitle="Type a real trader question. Desk Copilot plans which Wingman specialists to fire, fans them out in parallel, and stitches every answer into one brief — citations, drivers, conviction, recommended action. Trajectory memory means the second time you ask a similar question it is faster and cheaper."
        rightSlot={
          <div className="flex items-center gap-3 text-[10px]">
            <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-bold border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 rounded px-2 py-1">
              <Sparkles className="w-3 h-3" /> meta-agent
            </span>
            <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
              <span className="text-[9px] uppercase tracking-wider text-slate-500">trajectories</span>
              <span className="text-xs font-mono font-semibold text-white">{history.length}</span>
            </span>
          </div>
        }
      />

      <PipelineStrip
        title="Pipeline · 1 meta-agent · trajectory memory · dynamic fan-out"
        subtitle="Type a question — Desk Copilot recalls past similar runs, plans the specialists, and lights them up live."
        nodes={planNodes}
        executionId={activeExecution}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
        <section className="space-y-5">
          <div className="rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/5 to-cyan-500/[0.03] p-5">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') ask(); }}
              data-testid="desk-question"
              rows={3}
              placeholder="e.g. Should I trade the USGC->NWE propane arb this week?"
              className="w-full bg-slate-950/40 border border-slate-800 rounded-lg px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-emerald-500/40"
            />
            <div className="flex items-center justify-between mt-3">
              <div className="flex flex-wrap gap-2">
                {SAMPLE_QUESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => ask(s)}
                    disabled={running}
                    className="text-[10px] text-slate-400 hover:text-emerald-300 px-2 py-1 rounded border border-slate-800 hover:border-emerald-500/40 disabled:opacity-40"
                  >
                    {s.length > 60 ? `${s.slice(0, 57)}...` : s}
                  </button>
                ))}
              </div>
              <button
                onClick={() => ask()}
                disabled={running || !question.trim()}
                data-testid="desk-ask"
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 text-xs font-semibold"
              >
                {running ? (
                  <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Thinking...</>
                ) : (
                  <><Send className="w-3.5 h-3.5" /> Ask the desk <ArrowRight className="w-3 h-3" /></>
                )}
              </button>
            </div>
          </div>

          {meta?.status === 'failed' && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-[12px] text-rose-200">
              <div className="font-semibold mb-1 uppercase tracking-wider text-[10px]">Run failed</div>
              <div className="font-mono break-words leading-relaxed">{meta.error_message || 'No detail returned.'}</div>
            </div>
          )}

          {answer && (
            <>
              <BriefCard answer={answer} cost={meta?.cost_usd} durationMs={meta?.duration_ms} />
              {(answer.plan && answer.plan.length > 0) && <PlanList plan={answer.plan} outputs={answer.specialist_outputs} />}
              {(answer.drivers && answer.drivers.length > 0) && <DriversList drivers={answer.drivers} />}
              {answer.specialist_outputs && Object.keys(answer.specialist_outputs).length > 0 && (
                <SpecialistOutputs outputs={answer.specialist_outputs} />
              )}
            </>
          )}

          {!answer && !running && (
            <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center text-[12px] text-slate-500">
              <Sparkles className="w-5 h-5 inline-block text-emerald-400/60 mr-1" />
              Ask any trader-style question. Desk Copilot will plan, fan out, and answer with citations.
            </div>
          )}
        </section>

        <aside className="rounded-xl border border-slate-800 bg-slate-900/30 p-4 lg:sticky lg:top-4 self-start" data-testid="desk-history">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
            <History className="w-3.5 h-3.5" /> Past trajectories ({history.length})
          </div>
          {history.length === 0 ? (
            <div className="text-[11px] text-slate-600 italic">no runs yet — ask the first question above.</div>
          ) : (
            <div className="space-y-2 max-h-[60vh] overflow-y-auto -mr-2 pr-2">
              {history.map((t) => (
                <button
                  key={t.id}
                  onClick={() => replayTrajectory(t)}
                  data-testid={`desk-trajectory-${t.id}`}
                  className="w-full text-left rounded-lg border border-slate-800 bg-slate-950/40 hover:border-emerald-500/30 px-3 py-2.5"
                >
                  <div className="text-[11px] text-slate-200 leading-snug line-clamp-2">{t.intent}</div>
                  <div className="flex items-center gap-2 mt-1.5 text-[9px]">
                    {(t.agents_invoked || []).slice(0, 3).map((a) => (
                      <span key={a} className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono truncate max-w-[80px]" title={a}>{a.replace(/^wingman-/, '')}</span>
                    ))}
                    {(t.agents_invoked || []).length > 3 && (
                      <span className="text-slate-500">+{(t.agents_invoked || []).length - 3}</span>
                    )}
                  </div>
                  {t.recommended_action && (
                    <div className="text-[9px] mt-1 text-emerald-300 uppercase tracking-wider">{t.recommended_action}</div>
                  )}
                </button>
              ))}
            </div>
          )}
        </aside>
      </div>

      <DagDrawer executionId={activeExecution} onClose={() => setActiveExecution(null)} />
    </div>
  );
}

function BriefCard({ answer, cost, durationMs }: { answer: DeskAnswer; cost?: number; durationMs?: number }) {
  const tone = (() => {
    switch ((answer.recommended_action || '').toLowerCase()) {
      case 'execute': return { border: 'border-emerald-500/40', bg: 'bg-emerald-500/10', text: 'text-emerald-200' };
      case 'hedge': return { border: 'border-cyan-500/40', bg: 'bg-cyan-500/10', text: 'text-cyan-200' };
      case 'reject': case 'escalate': return { border: 'border-rose-500/40', bg: 'bg-rose-500/10', text: 'text-rose-200' };
      default: return { border: 'border-slate-700/40', bg: 'bg-slate-800/30', text: 'text-slate-200' };
    }
  })();
  return (
    <div className={`rounded-xl border ${tone.border} ${tone.bg} p-5`} data-testid="desk-brief">
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
          <Brain className="w-3.5 h-3.5" /> Brief
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          {answer.recommended_action && (
            <span className={`px-2 py-0.5 rounded uppercase tracking-wider font-semibold ${tone.text} border ${tone.border}`}>
              {answer.recommended_action}
            </span>
          )}
          {answer.confidence && (
            <span className="px-2 py-0.5 rounded bg-slate-800/60 text-slate-300 uppercase tracking-wider">conf {answer.confidence}</span>
          )}
          {cost != null && (
            <span className="font-mono text-slate-500">${cost.toFixed(4)}</span>
          )}
          {durationMs != null && (
            <span className="font-mono text-slate-500">{Math.round(durationMs / 1000)}s</span>
          )}
        </div>
      </div>
      {answer.headline && <div className="text-lg font-bold text-white mb-2">{answer.headline}</div>}
      {answer.brief && <p className="text-[13px] text-slate-200 leading-relaxed whitespace-pre-wrap">{answer.brief}</p>}
    </div>
  );
}

function PlanList({ plan, outputs }: { plan: PlanStep[]; outputs?: Record<string, any> }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-3">
        Plan · {plan.length} specialist{plan.length === 1 ? '' : 's'} invoked
      </div>
      <div className="space-y-2">
        {plan.map((step, i) => {
          const slug = step.agent;
          const meta = KNOWN_SPECIALISTS[slug];
          const out = outputs?.[slug];
          return (
            <div key={`${slug}-${i}`} className="flex items-start gap-3 text-[12px] py-2 border-b border-slate-800/50 last:border-b-0">
              <span className="text-emerald-400 font-mono text-[10px] w-5 shrink-0 mt-0.5">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-slate-200">{meta?.label || slug}</span>
                  <span className="text-[10px] font-mono text-slate-500">{slug}</span>
                  {out ? (
                    <span className="text-[9px] uppercase tracking-wider text-emerald-400">returned</span>
                  ) : (
                    <span className="text-[9px] uppercase tracking-wider text-slate-500">no output</span>
                  )}
                </div>
                {(step.rationale || step.input_summary) && (
                  <div className="text-[11px] text-slate-400 mt-1 leading-snug">
                    {step.rationale && <span>{step.rationale}</span>}
                    {step.input_summary && <span className="font-mono text-slate-500"> · {step.input_summary}</span>}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DriversList({ drivers }: { drivers: Driver[] }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
      <div className="flex items-center gap-2 mb-2 text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
        <Newspaper className="w-3.5 h-3.5" /> Cited drivers ({drivers.length})
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {drivers.map((d, i) => (
          <div key={i} className="px-3 py-2 rounded bg-slate-950/40 border border-slate-800 text-[11px]">
            <div className="flex items-center gap-1.5 mb-1">
              {d.category && (
                <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{d.category}</span>
              )}
              {d.impact_usd_mt != null && (
                <span className={`text-[10px] font-mono font-semibold ${d.impact_usd_mt >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                  {d.impact_usd_mt >= 0 ? '+' : ''}{d.impact_usd_mt.toFixed(2)} $/MT
                </span>
              )}
            </div>
            <div className="text-slate-200 leading-snug mb-1">{d.headline}</div>
            {(d.source || d.url) && (
              <div className="text-[9px] text-slate-500 flex items-center gap-2 flex-wrap">
                {d.source && <span>{d.source}</span>}
                {d.url && (
                  <a href={d.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-emerald-400 hover:underline">
                    open <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function SpecialistOutputs({ outputs }: { outputs: Record<string, any> }) {
  const keys = Object.keys(outputs);
  return (
    <details className="rounded-xl border border-slate-800 bg-slate-900/20 p-3">
      <summary className="text-[11px] uppercase tracking-wider text-slate-400 cursor-pointer">
        Specialist outputs ({keys.length}) — full envelopes
      </summary>
      <pre className="mt-2 text-[10px] text-slate-300 overflow-x-auto bg-slate-950/40 p-3 rounded max-h-[420px]">
        {JSON.stringify(outputs, null, 2)}
      </pre>
    </details>
  );
}
