// @ts-nocheck — Tier 2/3 payload shapes are dynamic
'use client';

import { useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, ShieldCheck, Sparkles, X, XCircle } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Props {
  open: boolean;
  onClose: () => void;
  agentId: string | null;
  agentName?: string;
  /**
   * Snapshot of the in-memory draft (not yet saved). When provided, the
   * dialog validates the draft via /api/pipelines/validate-smart instead of
   * the saved-agent endpoint. This lets users validate BEFORE clicking Save.
   */
  getDraft?: () => {
    nodes: unknown[];
    tools: string[];
    context_keys: string[];
    purpose: string;
  } | null;
}

interface SmartResult {
  agent?: { errors: any[]; warnings: any[] };
  tier1?: { valid: boolean; errors: any[]; warnings: any[] } | null;
  tier2?: { errors: any[]; warnings: any[]; cost_estimate_usd: number; node_cost_breakdown: Record<string, number>; unused_nodes: string[] } | null;
  tier3?: {
    coherence_score: number;
    missing_steps: string[];
    suspect_nodes: { node_id: string; reason: string }[];
    suggestions: string[];
    summary: string;
    model?: string;
    cost_usd?: number;
    error?: string | null;
  } | null;
  overall: { valid: boolean; severity: 'ok' | 'warn' | 'error'; score: number };
}

function SeverityPill({ severity, score }: { severity: string; score: number }) {
  const styles: Record<string, string> = {
    ok: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    warn: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    error: 'bg-red-500/10 text-red-400 border-red-500/30',
  };
  return (
    <span className={`px-2 py-0.5 rounded border text-[10px] font-medium ${styles[severity] || styles.warn}`}>
      {severity.toUpperCase()} · score {score}/10
    </span>
  );
}

function ErrorList({ items, label }: { items: any[]; label: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="space-y-1">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label} ({items.length})</p>
      <ul className="space-y-1">
        {items.map((e, i) => (
          <li key={i} className="text-[11px] text-slate-300 bg-slate-900/40 rounded px-2 py-1.5 border border-slate-700/40">
            {e.node_id && <span className="font-mono text-cyan-400 mr-1">{e.node_id}</span>}
            {e.field && <span className="font-mono text-purple-400 mr-1">/{e.field}</span>}
            <span className="text-slate-200">{e.message}</span>
            {e.suggestion && <p className="text-[10px] text-slate-500 mt-0.5">→ {e.suggestion}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function AIValidateDialog({ open, onClose, agentId, agentName, getDraft }: Props) {
  const [loading, setLoading] = useState(false);
  const [deep, setDeep] = useState(false);
  const [result, setResult] = useState<SmartResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const runValidation = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const token = localStorage.getItem('access_token');
      let resp: Response;
      if (agentId) {
        resp = await fetch(`${API_URL}/api/agents/${agentId}/validate-smart`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ deep }),
        });
      } else {
        const draft = getDraft?.();
        if (!draft || draft.nodes.length === 0) {
          setError('Nothing to validate yet. Add at least one step to the pipeline or switch to an existing agent.');
          setLoading(false);
          return;
        }
        resp = await fetch(`${API_URL}/api/pipelines/validate-smart`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            nodes: draft.nodes,
            tools: draft.tools,
            context_keys: draft.context_keys,
            purpose: draft.purpose,
            deep,
          }),
        });
      }
      const body = await resp.json();
      if (body.data) {
        setResult(body.data as SmartResult);
      } else {
        setError(body.error?.message || 'Validation failed');
      }
    } catch (e: any) {
      setError(e?.message || 'Network error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-cyan-600 flex items-center justify-center">
              <ShieldCheck className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">
                AI Validate {agentName ? `· ${agentName}` : ''}
                {!agentId && <span className="ml-2 text-[10px] font-normal text-amber-400">(draft — not saved)</span>}
              </h2>
              <p className="text-[10px] text-slate-500">Structural + semantic + (optional) LLM critic</p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
              <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} className="rounded border-slate-600" />
              Deep critique (LLM, ~$0.03, ~15s)
            </label>
            <button
              onClick={runValidation}
              disabled={loading}
              className="ml-auto px-4 py-2 bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-xs font-medium rounded-lg hover:opacity-90 disabled:opacity-40 flex items-center gap-2"
            >
              {loading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Validating...</> : <><Sparkles className="w-3.5 h-3.5" /> Run AI Validate</>}
            </button>
          </div>

          {error && <p className="text-xs text-red-400 bg-red-500/5 border border-red-500/20 rounded-lg px-3 py-2">{error}</p>}

          {result && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                {result.overall.severity === 'ok' ? (
                  <CheckCircle2 className="w-6 h-6 text-emerald-400" />
                ) : result.overall.severity === 'warn' ? (
                  <AlertTriangle className="w-6 h-6 text-amber-400" />
                ) : (
                  <XCircle className="w-6 h-6 text-red-400" />
                )}
                <SeverityPill severity={result.overall.severity} score={result.overall.score} />
                {result.tier2?.cost_estimate_usd != null && (
                  <span className="ml-auto text-[10px] text-slate-500">
                    Est. cost/run: ${result.tier2.cost_estimate_usd.toFixed(3)}
                  </span>
                )}
              </div>

              <div className="rounded-lg border border-slate-700/50 p-3 space-y-2" data-testid="validate-tier1">
                <p className="text-xs font-semibold text-cyan-300">Tier 1 — Structural</p>
                {result.tier1 == null && <p className="text-[11px] text-slate-500">Not a pipeline (skipped).</p>}
                {result.tier1 && result.tier1.valid && result.tier1.errors.length === 0 && result.tier1.warnings.length === 0 && (
                  <p className="text-[11px] text-emerald-400">✓ No structural issues</p>
                )}
                {result.tier1 && <ErrorList items={result.tier1.errors || []} label="Errors" />}
                {result.tier1 && <ErrorList items={result.tier1.warnings || []} label="Warnings" />}
              </div>

              <div className="rounded-lg border border-slate-700/50 p-3 space-y-2" data-testid="validate-tier2">
                <p className="text-xs font-semibold text-purple-300">Tier 2 — Semantic</p>
                {result.tier2 == null && <p className="text-[11px] text-slate-500">Not a pipeline (skipped).</p>}
                {result.tier2 && (result.tier2.errors?.length || 0) === 0 && (result.tier2.warnings?.length || 0) === 0 && (
                  <p className="text-[11px] text-emerald-400">✓ No semantic issues</p>
                )}
                {result.tier2 && <ErrorList items={result.tier2.errors || []} label="Errors" />}
                {result.tier2 && <ErrorList items={result.tier2.warnings || []} label="Warnings" />}
                {result.tier2 && result.tier2.unused_nodes?.length > 0 && (
                  <p className="text-[10px] text-amber-400">Unused nodes: {result.tier2.unused_nodes.join(', ')}</p>
                )}
              </div>

              {result.agent && (result.agent.errors?.length > 0 || result.agent.warnings?.length > 0) && (
                <div className="rounded-lg border border-slate-700/50 p-3 space-y-2">
                  <p className="text-xs font-semibold text-slate-300">Agent-level</p>
                  <ErrorList items={result.agent.errors} label="Errors" />
                  <ErrorList items={result.agent.warnings} label="Warnings" />
                </div>
              )}

              {result.tier3 && (
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 space-y-2" data-testid="validate-tier3">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
                    <p className="text-xs font-semibold text-emerald-300">Tier 3 — LLM Critic</p>
                    <span className="ml-auto text-[10px] text-slate-500">
                      {result.tier3.model} · ${result.tier3.cost_usd?.toFixed(4)}
                    </span>
                  </div>
                  {result.tier3.error ? (
                    <p className="text-[11px] text-red-400">{result.tier3.error}</p>
                  ) : (
                    <>
                      <p className="text-[11px] text-slate-200 italic">{result.tier3.summary}</p>
                      <p className="text-[10px] text-slate-400">Coherence score: <span className="font-bold text-white">{result.tier3.coherence_score}/10</span></p>
                      {result.tier3.missing_steps.length > 0 && (
                        <div>
                          <p className="text-[10px] text-amber-400 mb-0.5">Missing steps</p>
                          <ul className="text-[11px] text-slate-300 space-y-0.5 ml-2 list-disc list-inside">
                            {result.tier3.missing_steps.map((s, i) => <li key={i}>{s}</li>)}
                          </ul>
                        </div>
                      )}
                      {result.tier3.suspect_nodes.length > 0 && (
                        <div>
                          <p className="text-[10px] text-amber-400 mb-0.5">Suspect nodes</p>
                          <ul className="space-y-1">
                            {result.tier3.suspect_nodes.map((n, i) => (
                              <li key={i} className="text-[11px] text-slate-300">
                                <span className="font-mono text-cyan-400">{n.node_id}</span>: {n.reason}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {result.tier3.suggestions.length > 0 && (
                        <div>
                          <p className="text-[10px] text-cyan-400 mb-0.5">Suggestions</p>
                          <ul className="text-[11px] text-slate-300 space-y-0.5 ml-2 list-disc list-inside">
                            {result.tier3.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                          </ul>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
