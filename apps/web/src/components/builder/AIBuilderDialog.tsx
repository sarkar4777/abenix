// @ts-nocheck — Dynamic config fields from API use Record<string,unknown> casts
'use client';

import { useState, useRef } from 'react';
import { Loader2, Sparkles, X, Zap, GitBranch, ArrowRight, Check, AlertTriangle, FileText, Copy, Repeat } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface IterationEvent {
  event: string;
  iteration?: number;
  [key: string]: any;
}

interface DynamicTool {
  name: string;
  description: string;
  code: string;
  parameters: { name: string; type: string; required: boolean; description: string }[];
  generated: boolean;
}

interface GeneratedConfig {
  name: string;
  description: string;
  mode: 'agent' | 'pipeline';
  system_prompt: string;
  tools: string[];
  custom_tools?: { name: string; description: string; parameters: { name: string; type: string; required: boolean; description: string }[] }[];
  dynamic_tools?: DynamicTool[];
  input_variables: { name: string; type: string; description: string; required: boolean }[];
  example_prompts: string[];
  pipeline_config?: {
    nodes: { id: string; tool_name: string; arguments?: Record<string, unknown>; depends_on?: string[] }[];
    edges: { source: string; target: string }[];
  };
}

interface Props {
  open: boolean;
  onClose: () => void;
  onApply: (config: GeneratedConfig) => void;
}

export default function AIBuilderDialog({ open, onClose, onApply }: Props) {
  const [description, setDescription] = useState('');
  const [mode, setMode] = useState<'auto' | 'agent' | 'pipeline'>('auto');
  const [iterative, setIterative] = useState(false);
  const [maxIterations, setMaxIterations] = useState(8);
  const [generating, setGenerating] = useState(false);
  const [config, setConfig] = useState<GeneratedConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<IterationEvent[]>([]);
  const [finalOutcome, setFinalOutcome] = useState<'success' | 'blocked' | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  if (!open) return null;

  const generateIterative = async () => {
    setGenerating(true);
    setError(null);
    setConfig(null);
    setEvents([]);
    setFinalOutcome(null);
    const token = localStorage.getItem('access_token');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const resp = await fetch(`${API_URL}/api/ai/build-iterative`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ description, mode, max_iterations: maxIterations }),
        signal: controller.signal,
      });
      if (!resp.body) throw new Error('No response stream');
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let sepIdx;
        while ((sepIdx = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, sepIdx);
          buf = buf.slice(sepIdx + 2);
          if (!frame.trim()) continue;
          let evName = 'message';
          let data: any = {};
          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) evName = line.slice(6).trim();
            else if (line.startsWith('data:')) {
              try { data = JSON.parse(line.slice(5).trim()); } catch { /* ignore */ }
            }
          }
          const ev: IterationEvent = { event: evName, ...data };
          setEvents((prev) => [...prev, ev]);
          if (evName === 'final_success' && ev.config) {
            setConfig(ev.config);
            setFinalOutcome('success');
          } else if (evName === 'final_blocked') {
            if (ev.config) setConfig(ev.config);
            setFinalOutcome('blocked');
          }
        }
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') setError(err?.message || 'Stream error');
    } finally {
      setGenerating(false);
      abortRef.current = null;
    }
  };

  const generate = async () => {
    if (!description.trim() || description.length < 10) {
      setError('Please describe what you want to build (at least 10 characters)');
      return;
    }

    if (iterative) {
      await generateIterative();
      return;
    }

    setGenerating(true);
    setError(null);
    setConfig(null);
    setEvents([]);
    setFinalOutcome(null);

    const token = localStorage.getItem('access_token');
    try {
      const resp = await fetch(`${API_URL}/api/ai/build-agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ description, mode }),
      });
      const body = await resp.json();
      if (body.data && body.data.name) {
        setConfig(body.data as GeneratedConfig);
      } else {
        setError(body.error?.message || 'Failed to generate config');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">Build with AI</h2>
              <p className="text-[10px] text-slate-500">Describe what you want — AI generates the full config</p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          {/* Description input */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">What do you want to build?</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Example: I need a pipeline that takes customer support emails, classifies them by urgency (billing, technical, escalation), routes each to the right handler, drafts a response, and merges everything into a summary report."
              rows={4}
              className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-cyan-500 resize-none"
            />
            <p className="text-[9px] text-slate-600 mt-1">{description.length} characters — be specific about tools, data flow, and conditions</p>
          </div>

          {/* Mode selector */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-slate-400">Mode:</span>
            {(['auto', 'agent', 'pipeline'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                data-testid={`ai-builder-mode-${m}`}
                className={`px-3 py-1 text-xs rounded-lg border transition-colors ${
                  mode === m
                    ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                    : 'border-slate-700 text-slate-500 hover:text-slate-300'
                }`}
              >
                {m === 'auto' ? 'Auto-detect' : m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            ))}
            <label
              className={`ml-auto flex items-center gap-1.5 px-2 py-1 text-[11px] rounded-lg border cursor-pointer transition-colors ${
                iterative
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                  : 'border-slate-700 text-slate-500 hover:text-slate-300'
              }`}
              data-testid="iterative-toggle"
            >
              <input type="checkbox" className="hidden" checked={iterative} onChange={(e) => setIterative(e.target.checked)} />
              <Repeat className="w-3 h-3" /> Iterative (validate + judge)
            </label>
          </div>

          {/* Iteration budget — only shown when iterative is on. The
              backend caps at 20; each iteration = generate → tier1+tier2+tier3
              validate → judge → repair. Higher budget = deeper fixes, more cost. */}
          {iterative && (
            <div
              className="flex items-center gap-3 bg-slate-900/40 border border-slate-800/60 rounded-lg px-3 py-2"
              data-testid="iteration-budget"
            >
              <label className="text-[11px] text-slate-400 whitespace-nowrap">Max iterations</label>
              <input
                type="range" min={1} max={20} step={1}
                value={maxIterations}
                onChange={(e) => setMaxIterations(Number(e.target.value))}
                className="flex-1 accent-cyan-500"
              />
              <span className="text-[11px] font-mono text-cyan-300 w-10 text-right">{maxIterations}</span>
            </div>
          )}

          {/* Generate button */}
          <button
            onClick={generate}
            disabled={generating || description.length < 10}
            className="w-full py-2.5 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-2"
          >
            {generating ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Generating...</>
            ) : (
              <><Sparkles className="w-4 h-4" /> Generate Agent / Pipeline</>
            )}
          </button>

          {error && (
            <p className="text-xs text-red-400 bg-red-500/5 border border-red-500/20 rounded-lg px-3 py-2">{error}</p>
          )}

          {/* Iterative timeline */}
          {iterative && events.length > 0 && (
            <div className="border border-emerald-500/20 bg-emerald-500/[0.03] rounded-lg p-3 space-y-1.5" data-testid="iterative-timeline">
              <p className="text-[10px] text-emerald-300 font-medium">Iterative build progress</p>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {events.map((ev, i) => {
                  const label =
                    ev.event === 'iteration_start' ? `→ Iteration ${ev.iteration} start` :
                    ev.event === 'generated' ? `   generated: ${ev.name} (${ev.mode}, ${ev.node_count} nodes, ${ev.tool_count} tools)` :
                    ev.event === 'validating' ? `   validating...` :
                    ev.event === 'validation_result'
                      ? `   validation: tier1 ${ev.tier1?.errors?.length || 0}E / ${ev.tier1?.warnings?.length || 0}W, tier2 ${ev.tier2?.errors?.length || 0}E / ${ev.tier2?.warnings?.length || 0}W`
                      :
                    ev.event === 'judging' ? `   judging...` :
                    ev.event === 'judge_result' ? `   judge: ${ev.passed ? '✓ passed' : '✗ failed'} (score ${ev.score}/10) — ${ev.summary}` :
                    ev.event === 'critiquing' ? `   adversarial critic reviewing...` :
                    ev.event === 'critic_result'
                      ? `   critic: severity=${ev.severity || '?'} ${(ev.concerns || []).length} concerns — ${ev.verdict || ''}`
                      :
                    ev.event === 'auto_testing' ? `   auto-test: executing pipeline with sample input...` :
                    ev.event === 'auto_test_result'
                      ? `   auto-test: ${ev.ok ? '✓ passed' : '✗ failed'} ${ev.skipped ? `(${ev.skipped})` : ''} ${ev.error ? `— ${String(ev.error).slice(0,160)}` : ''}`
                      :
                    ev.event === 'iteration_end' ? `← Iteration ${ev.iteration} end` :
                    ev.event === 'final_success' ? `✓ FINAL SUCCESS (iter ${ev.iteration}, score ${ev.score})` :
                    ev.event === 'final_blocked' ? `⚠ BLOCKED (iter ${ev.iteration}): ${ev.reason}` :
                    `${ev.event}`;
                  const color =
                    ev.event === 'final_success' ? 'text-emerald-400' :
                    ev.event === 'final_blocked' ? 'text-amber-400' :
                    ev.event.startsWith('iteration') ? 'text-cyan-300' :
                    'text-slate-400';
                  return <p key={i} className={`text-[10px] font-mono ${color}`}>{label}</p>;
                })}
              </div>
              {finalOutcome === 'blocked' && (
                <p className="text-[10px] text-amber-300 mt-1">The iterative build surfaced a real blocker. You can still apply the last config and fix it manually.</p>
              )}
            </div>
          )}

          {/* Generated config preview */}
          {config && (
            <div className="space-y-3 border-t border-slate-700/50 pt-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <Check className="w-4 h-4 text-emerald-400" />
                  Generated: {config.name}
                </h3>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ${
                  config.mode === 'pipeline'
                    ? 'bg-teal-500/10 border-teal-500/20 text-teal-400'
                    : 'bg-cyan-500/10 border-cyan-500/20 text-cyan-400'
                }`}>
                  {config.mode === 'pipeline' ? 'Pipeline' : 'Agent'}
                </span>
              </div>

              <p className="text-xs text-slate-400">{config.description}</p>

              {/* Tools */}
              <div>
                <p className="text-[10px] text-slate-500 mb-1">Tools ({config.tools.length})</p>
                <div className="flex flex-wrap gap-1">
                  {config.tools.map((t) => {
                    const isCustom = config.dynamic_tools?.some((dt) => dt.name === t);
                    return (
                      <span key={t} className={`text-[9px] px-1.5 py-0.5 rounded ${isCustom ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-cyan-500/10 text-cyan-400'}`}>
                        {isCustom && '★ '}{t}
                      </span>
                    );
                  })}
                </div>
              </div>

              {/* Auto-repair status */}
              {(config as any).auto_repair?.attempted && (
                <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-3 space-y-1" data-testid="auto-repair-info">
                  <p className="text-[10px] text-cyan-400 font-medium">
                    ✓ Auto-Repair ran — fixed {(config as any).auto_repair.fixed_count ?? 0} validator error(s)
                    {typeof (config as any).auto_repair.residual_errors?.length === 'number' && (config as any).auto_repair.residual_errors.length > 0 && (
                      <span className="text-amber-400"> · {(config as any).auto_repair.residual_errors.length} still remain</span>
                    )}
                  </p>
                  {(config as any).auto_repair.original_errors?.slice(0, 3).map((e: any, i: number) => (
                    <p key={i} className="text-[9px] text-slate-400 font-mono">
                      fixed: {e.node_id || '(pipeline)'}/{e.field} — {e.message}
                    </p>
                  ))}
                </div>
              )}

              {/* Custom-generated tools */}
              {config.dynamic_tools && config.dynamic_tools.length > 0 && (
                <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg p-3 space-y-2">
                  <p className="text-[10px] text-amber-400 font-medium">
                    ★ {config.dynamic_tools.length} Custom Tool{config.dynamic_tools.length > 1 ? 's' : ''} Generated
                  </p>
                  {config.dynamic_tools.map((dt) => (
                    <div key={dt.name} className="space-y-1">
                      <p className="text-[10px] text-amber-300 font-mono">{dt.name}</p>
                      <p className="text-[9px] text-slate-400">{dt.description}</p>
                      {dt.parameters.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {dt.parameters.map((p) => (
                            <span key={p.name} className="text-[8px] px-1 py-0.5 bg-slate-800 text-slate-400 rounded font-mono">
                              {p.name}: {p.type}{p.required ? '*' : ''}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  <p className="text-[8px] text-slate-600">Auto-saved to Tool Library</p>
                </div>
              )}

              {/* Pipeline nodes */}
              {config.pipeline_config?.nodes && (
                <div>
                  <p className="text-[10px] text-slate-500 mb-1">Pipeline Nodes ({config.pipeline_config.nodes.length})</p>
                  <div className="flex flex-wrap items-center gap-1">
                    {config.pipeline_config.nodes.map((n, i) => (
                      <span key={n.id} className="flex items-center gap-1">
                        {i > 0 && <ArrowRight className="w-3 h-3 text-slate-600" />}
                        <span className="text-[9px] px-1.5 py-0.5 bg-emerald-500/10 text-emerald-400 rounded font-mono">{n.id}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Input variables */}
              {config.input_variables?.length > 0 && (
                <div>
                  <p className="text-[10px] text-slate-500 mb-1">Input Variables</p>
                  <div className="flex flex-wrap gap-1">
                    {config.input_variables.map((v) => (
                      <span key={v.name} className="text-[9px] px-1.5 py-0.5 bg-slate-700/50 text-slate-300 rounded">
                        {v.name}{v.required ? '*' : ''}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Example prompts */}
              {config.example_prompts?.length > 0 && (
                <div>
                  <p className="text-[10px] text-slate-500 mb-1">Example Prompts</p>
                  {config.example_prompts.slice(0, 2).map((p, i) => (
                    <p key={i} className="text-[10px] text-slate-400 truncate">{p}</p>
                  ))}
                </div>
              )}

              {/* Review score & validation */}
              {((config as Record<string, unknown>).review_score || (config as Record<string, unknown>).validation_issues) && (
                <div className="space-y-2">
                  {(config as Record<string, unknown>).review_score && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-slate-500">AI Review Score:</span>
                      <span className={`text-xs font-bold ${((config as Record<string, unknown>).review_score as number) >= 7 ? 'text-emerald-400' : ((config as Record<string, unknown>).review_score as number) >= 5 ? 'text-amber-400' : 'text-red-400'}`}>
                        {String((config as Record<string, unknown>).review_score)}/10
                      </span>
                    </div>
                  )}
                  {((config as Record<string, unknown>).validation_issues as string[])?.length > 0 && (
                    <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg p-2">
                      <p className="text-[9px] text-amber-400 font-medium flex items-center gap-1 mb-1"><AlertTriangle className="w-3 h-3" /> Issues</p>
                      {((config as Record<string, unknown>).validation_issues as string[]).map((issue, i) => (
                        <p key={i} className="text-[9px] text-amber-300">{issue}</p>
                      ))}
                    </div>
                  )}
                  {((config as Record<string, unknown>).suggestions as string[])?.length > 0 && (
                    <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-2">
                      <p className="text-[9px] text-cyan-400 font-medium mb-1">Suggestions</p>
                      {((config as Record<string, unknown>).suggestions as string[]).map((s, i) => (
                        <p key={i} className="text-[9px] text-cyan-300">{s}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* YAML/JSON preview toggle */}
              <details className="group">
                <summary className="flex items-center gap-1.5 text-[10px] text-slate-500 cursor-pointer hover:text-slate-300">
                  <FileText className="w-3 h-3" /> View raw config (JSON)
                </summary>
                <div className="mt-2 relative">
                  <button
                    onClick={() => navigator.clipboard.writeText(JSON.stringify(config, null, 2))}
                    className="absolute top-2 right-2 text-slate-500 hover:text-white"
                    title="Copy to clipboard"
                  ><Copy className="w-3 h-3" /></button>
                  <pre className="text-[9px] font-mono text-slate-400 bg-slate-900/80 rounded-lg p-3 max-h-48 overflow-auto">
                    {JSON.stringify(config, null, 2)}
                  </pre>
                </div>
              </details>

              {/* Apply buttons */}
              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => { onApply(config); onClose(); }}
                  className="flex-1 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:opacity-90 flex items-center justify-center gap-2"
                >
                  <Zap className="w-4 h-4" /> Apply to Canvas
                </button>
                <button
                  onClick={generate}
                  className="px-4 py-2 border border-slate-600 text-slate-300 text-sm rounded-lg hover:bg-slate-700/50"
                >
                  Regenerate
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
