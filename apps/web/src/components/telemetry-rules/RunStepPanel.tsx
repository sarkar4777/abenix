'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Bot, ChevronDown, ChevronRight, ExternalLink, FlaskConical, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import type { Action, Condition, Options, Scope } from './lib';
import { Field, cls } from './ui';

interface PreviewDoc {
  source: 'firing' | 'latest' | 'none';
  message: string | null;
  context: { telemetry: Record<string, unknown> } | null;
  note: string;
}

interface Run { status: string; output_message?: string | null; error_message?: string | null; duration_ms?: number | null }

const POLL_MS = 2000;
const POLL_FOR_MS = 10 * 60 * 1000;

function pretty(text: string | null | undefined): string {
  if (!text) return '';
  const t = text.trim();
  const fenced = t.match(/```(?:json)?\s*([\s\S]*?)```/);
  for (const c of [t, fenced?.[1]]) {
    if (!c) continue;
    try { return JSON.stringify(JSON.parse(c.trim()), null, 2); } catch { /* not JSON */ }
  }
  return t;
}

function Summary({ ctx }: { ctx: Record<string, unknown> }) {
  const h = ctx.history as { minutes?: number; summary?: Record<string, number> | null } | null | undefined;
  const rows: Array<[string, unknown]> = [
    ['Asset', `${ctx.asset ?? ''} (${ctx.group}/${ctx.node}${ctx.device ? `/${ctx.device}` : ''})`],
    ['Signal', ctx.signal ? `${ctx.signal} = ${JSON.stringify(ctx.value)}` : 'none'],
    ['Why', ctx.detail],
  ];
  if (h?.summary) rows.push([`Last ${h.minutes} min`, `first ${h.summary.first}, last ${h.summary.last}, min ${h.summary.min}, max ${h.summary.max}`]);
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="text-slate-200 [overflow-wrap:anywhere]">{String(v ?? '')}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function RunStepPanel({ a, i, set, errors, options, scope, condition, ruleId, ruleName, disabled }: {
  a: Action; i: number; set: (p: Partial<Action>) => void; errors: Record<string, string>; options: Options | null;
  scope: Scope; condition?: Condition; ruleId?: string; ruleName?: string; disabled?: boolean;
}) {
  const e = (k: string) => errors[`actions.${i}.${k}`];
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewDoc | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testErr, setTestErr] = useState<string | null>(null);
  const [execId, setExecId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const body = () => JSON.stringify({ rule_id: ruleId || null, agent_id: a.agent_id || null, message: a.message || '', scope, condition, name: ruleName || '' });
  const assetQuery = scope.kind === 'asset' && scope.group && scope.node ? `?asset=${encodeURIComponent(`${scope.group}/${scope.node}`)}` : '';
  const agents = options?.agents || [];

  async function loadPreview() {
    setPreviewErr(null);
    setPreview(null);
    const res = await apiFetch<PreviewDoc>('/api/telemetry/loop/run-preview', { method: 'POST', body: body(), silent: true, throwOnError: false });
    if (res.data) setPreview(res.data);
    else setPreviewErr(res.error || 'Could not build the preview.');
  }

  useEffect(() => {
    if (open) void loadPreview();
  }, [open, ruleId, a.message, scope.kind, scope.group, scope.node, scope.device, condition?.signal]);

  async function test() {
    setTesting(true);
    setTestErr(null);
    setRun(null);
    setExecId(null);
    const res = await apiFetch<{ execution_id: string }>('/api/telemetry/loop/run-test', { method: 'POST', body: body(), silent: true, throwOnError: false });
    if (!res.data?.execution_id) {
      setTesting(false);
      setTestErr(res.error || 'The test could not start.');
      return;
    }
    const id = res.data.execution_id;
    setExecId(id);
    const until = Date.now() + POLL_FOR_MS;
    while (alive.current && Date.now() < until) {
      const r = await apiFetch<Run>(`/api/executions/${id}`, { silent: true });
      if (r.data) {
        setRun(r.data);
        if (r.data.status !== 'running') break;
      }
      await new Promise((ok) => setTimeout(ok, POLL_MS));
    }
    if (alive.current) setTesting(false);
  }

  const testWhy = disabled ? 'View only' : !a.agent_id ? 'Pick the agent or pipeline first' : undefined;

  return (
    <div className="space-y-3" data-testid={`action-${i}-run-panel`}>
      {options && agents.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-700 px-3 py-2 text-xs text-slate-300" data-testid={`action-${i}-no-agents`}>
          No agents yet. <Link href={`/telemetry/agents${assetQuery}`} className="text-cyan-300 hover:underline">Create one from a template</Link>, like a Machine health watcher, then pick it here.
        </p>
      ) : (
        <p className="text-xs text-slate-500">
          Need one that reads streams? <Link href={`/telemetry/agents${assetQuery}`} className="text-cyan-300 hover:underline" data-testid={`action-${i}-agent-templates`}>Start one from a template</Link>.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex min-h-[40px] items-start gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200">
          <input type="checkbox" className="mt-1 accent-cyan-500" checked={a.wait !== false} disabled={disabled} onChange={(ev) => set({ wait: ev.target.checked })} data-testid={`action-${i}-wait`} />
          <span>
            Wait for its answer
            <span className="block text-xs text-slate-500">Later steps can use it as {`{steps.${i + 1}.output}`}, or one field like {`{steps.${i + 1}.output.severity}`}.</span>
          </span>
        </label>
        {a.wait !== false && (
          <Field label="Wait at most (seconds)" htmlFor={`a${i}-wait`} error={e('wait_s')} help="Default 600. A person approving a command counts toward it.">
            <input id={`a${i}-wait`} type="number" min={5} max={3600} value={a.wait_s ?? ''} placeholder="600" disabled={disabled}
              onChange={(ev) => set({ wait_s: ev.target.value })} className={cls(e('wait_s'))} data-testid={`action-${i}-wait-s`} />
          </Field>
        )}
      </div>

      <div className="rounded-lg border border-slate-700/70">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex min-h-[40px] w-full items-center gap-2 px-3 text-left text-sm text-slate-200 hover:bg-slate-800/50" data-testid={`action-${i}-receives`}>
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />} What it will receive
        </button>
        {open && (
          <div className="space-y-2 border-t border-slate-700/70 p-3" data-testid={`action-${i}-receives-body`}>
            {!preview && !previewErr && <p className="flex items-center gap-1.5 text-xs text-slate-400"><Loader2 className="h-3 w-3 animate-spin" /> Reading the last firing</p>}
            {previewErr && <p className="text-xs text-rose-300" role="alert">{previewErr} <button type="button" className="text-cyan-300 hover:underline" onClick={() => void loadPreview()}>Try again</button></p>}
            {preview && (
              preview.source === 'none' ? (
                <p className="text-xs text-slate-400">{preview.note}</p>
              ) : (
                <>
                  <p className="text-[11px] text-slate-500">{preview.note}</p>
                  {preview.context?.telemetry && <Summary ctx={preview.context.telemetry} />}
                  <p className="text-[11px] text-slate-500">The message</p>
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-950/70 p-2 text-xs text-slate-200" data-testid={`action-${i}-receives-message`}>{preview.message}</pre>
                  <p className="text-[11px] text-slate-500">The full firing is in its context under telemetry, with the earlier steps&apos; answers under steps.</p>
                </>
              )
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => void test()} disabled={!!testWhy || testing} title={testWhy || 'Run it once now with the last firing. Commands it proposes are checked, never sent.'}
          className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-slate-600 px-3 text-xs text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50" data-testid={`action-${i}-test`}>
          {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />} Test with the last firing
        </button>
        <span className="text-xs text-slate-500">{testWhy ? testWhy : 'Runs it once now. Commands it proposes are checked, never sent.'}</span>
      </div>
      {testErr && <p className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-2 text-xs text-rose-200" role="alert" data-testid={`action-${i}-test-error`}>{testErr}</p>}
      {execId && (
        <div className="space-y-1.5 rounded-lg border border-slate-700/70 bg-slate-950/40 p-3" data-testid={`action-${i}-test-result`} data-status={run?.status || 'running'}>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Bot className="h-3.5 w-3.5 text-cyan-300" />
            <span className="text-slate-200">
              {!run || run.status === 'running' ? 'Running' : run.status === 'completed' ? `Answered${run.duration_ms ? ` in ${(run.duration_ms / 1000).toFixed(1)} s` : ''}` : `It ${run.status}`}
            </span>
            {(!run || run.status === 'running') && <Loader2 className="h-3 w-3 animate-spin text-slate-400" />}
            <Link href={`/executions/${execId}`} className="ml-auto inline-flex items-center gap-1 text-cyan-300 hover:underline">Open the run <ExternalLink className="h-3 w-3" /></Link>
          </div>
          {run?.status === 'completed' && <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-950/70 p-2 text-xs text-slate-200" data-testid={`action-${i}-test-output`}>{pretty(run.output_message)}</pre>}
          {run && run.status !== 'completed' && run.status !== 'running' && <p className="text-xs text-rose-200">{run.error_message || 'No reason was given. Open the run to see each step.'}</p>}
        </div>
      )}
    </div>
  );
}
