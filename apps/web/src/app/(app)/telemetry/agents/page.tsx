'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import useSWR from 'swr';
import { Bot, CheckCircle2, ExternalLink, Loader2, Plus, RefreshCw, Send, ShieldCheck, Wrench, Zap } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { fetchDefaultModel } from '@/lib/models';
import { AGENT_TEMPLATES, buildFromTemplate, templateHref, type AgentTemplate, type TemplateAsset } from '@/lib/telemetry/agentTemplates';
import type { Target, TargetSignal } from '@/lib/telemetry/commandPolicy';

const PURPOSE = 'Start an agent that reads your streams, reasons about them and, when you allow it, acts on your assets through governed commands.';

interface Targets { assets: Target[]; total: number; can_command: boolean; tiers: Record<string, string> }
interface Created { id: string; name: string; template: AgentTemplate }

function fetcher(url: string) {
  return apiFetch<unknown>(url, { silent: true });
}

function TemplateCard({ t, picked, asset, signals, canCreate, createWhy, canCommand, busy, onCreate }: {
  t: AgentTemplate; picked: boolean; asset?: TemplateAsset; signals: string[]; canCreate: boolean; createWhy?: string; canCommand: boolean; busy: boolean; onCreate: (t: AgentTemplate) => void;
}) {
  return (
    <li className={`flex min-w-0 flex-col rounded-xl border p-4 [overflow-wrap:anywhere] ${picked ? 'border-cyan-500/70 bg-cyan-500/5' : 'border-slate-700/60 bg-slate-900/40'}`} data-testid={`agent-template-${t.id}`}>
      <div className="flex items-start gap-2">
        <Bot className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-white">{t.name}</h2>
          <p className="mt-1 text-sm text-slate-300">{t.blurb}</p>
          <p className="mt-1 text-xs text-slate-500">{t.when}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {t.tools.map((tool) => (
          <span key={tool} className="inline-flex items-center gap-1 rounded-full border border-slate-700 px-2 py-0.5 font-mono text-[11px] text-slate-300"><Wrench className="h-3 w-3" aria-hidden />{tool}</span>
        ))}
      </div>
      {t.commands ? (
        <p className="mt-3 flex items-start gap-1.5 text-xs text-amber-100">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" aria-hidden />
          <span>
            Can send commands, and a person approves every one at first.{' '}
            {asset ? <>It may command {asset.name || asset.key}{signals.length ? `, signals ${signals.join(', ')}` : ', you pick the signals in the builder'}.</> : 'You pick the assets and signals in the builder.'}
            {!canCommand && ' You do not have Send machine commands, so runs you start will be refused until an admin adds you to Machine operators.'}
          </span>
        </p>
      ) : (
        <p className="mt-3 text-xs text-slate-400">Only reads. It never changes anything.</p>
      )}
      <p className="mt-2 text-[11px] text-slate-500">Answers with <code className="break-all text-slate-400">{t.output}</code>, so later rule steps can use it.</p>
      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        <button type="button" onClick={() => onCreate(t)} disabled={!canCreate || busy} title={!canCreate ? createWhy : `Create ${t.name}${asset ? ` for ${asset.name || asset.key}` : ''}`}
          className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-cyan-500 px-3 text-sm font-medium text-white hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50" data-testid={`agent-template-create-${t.id}`}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Create agent
        </button>
        <Link href={templateHref(t.id, asset)} className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border border-slate-700 px-3 text-sm text-slate-200 hover:bg-slate-800" data-testid={`agent-template-open-${t.id}`}>
          Open in the builder first
        </Link>
      </div>
    </li>
  );
}

function AgentsPage() {
  usePageTitle('Agents for your assets');
  const params = useSearchParams();
  const { perms, loading: permsLoading } = useMyPermissions();
  const caps = perms?.capabilities;
  const canView = holds(caps, 'telemetry.view');
  const canCreate = perms ? perms.features?.create_agents !== false : false;
  const targets = useSWR(canView ? '/api/telemetry/loop/command-targets' : null, fetcher, { revalidateOnFocus: false });
  const t = (targets.data?.data ?? null) as Targets | null;
  const loadErr = targets.data?.error || (targets.error ? 'The assets could not load.' : null);
  const [assetKey, setAssetKey] = useState(params.get('asset') || '');
  const [signals, setSignals] = useState<string[]>(() => (params.get('signal') ? [params.get('signal') as string] : []));
  const [writable, setWritable] = useState<TargetSignal[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const [createErr, setCreateErr] = useState<string | null>(null);
  const picked = params.get('template');

  const asset: TemplateAsset | undefined = useMemo(() => {
    if (!assetKey) return undefined;
    const row = t?.assets.find((a) => `${a.group}/${a.node}` === assetKey.split('/').slice(0, 2).join('/'));
    return { key: assetKey.split('/').filter(Boolean).slice(0, 2).join('/'), name: row?.name || params.get('asset_name') || undefined };
  }, [assetKey, t, params]);

  useEffect(() => {
    setWritable(null);
    if (!asset) return;
    const [g, n] = asset.key.split('/');
    void apiFetch<TargetSignal[]>(`/api/telemetry/loop/command-targets/signals?group=${encodeURIComponent(g)}&node=${encodeURIComponent(n)}`, { silent: true })
      .then((res) => setWritable(res.data || []));
  }, [asset]);

  async function create(tpl: AgentTemplate) {
    setBusy(tpl.id);
    setCreateErr(null);
    const b = buildFromTemplate(tpl, asset, tpl.commands ? signals : []);
    const model = await fetchDefaultModel().catch(() => null);
    const res = await apiFetch<{ id: string; name: string }>('/api/agents', {
      method: 'POST',
      silent: true,
      throwOnError: false,
      body: JSON.stringify({
        name: b.name,
        description: b.description,
        system_prompt: b.system_prompt,
        category: 'other',
        model_config: {
          ...(model ? { model } : {}),
          temperature: 0.2,
          max_tokens: 4096,
          max_iterations: 12,
          tools: b.tools,
          tool_config: b.tool_config,
          example_prompts: b.example_prompts,
          input_variables: [],
        },
      }),
    });
    setBusy(null);
    if (!res.data?.id) {
      setCreateErr(res.errorDetail?.error_code === 'NETWORK_ERROR'
        ? 'Abenix could not be reached, so the agent was not created. Check your connection and press Create agent again.'
        : res.error || 'The agent could not be created. Try again.');
      return;
    }
    setCreated({ id: res.data.id, name: res.data.name || b.name, template: tpl });
  }

  if (permsLoading && !perms) return <div className="mx-auto max-w-6xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>;
  if (perms && !canView) {
    return (
      <NoAccess testId="telemetry-agents-no-access" title="Agents for your assets" purpose={PURPOSE} icon={Bot}
        need={{ capability: 'telemetry.view', label: 'View machine telemetry' }} role={perms.role}
        instead={{ text: 'You can still build any agent by hand.', href: '/builder', label: 'Open the builder' }} />
    );
  }
  const writableNames = Array.from(new Set((writable || []).filter((s) => s.writable).map((s) => s.signal))).sort();

  return (
    <div className="mx-auto max-w-6xl space-y-4" data-testid="telemetry-agents-page">
      <PageHeader
        title="Agents for your assets"
        purpose={PURPOSE}
        icon={Bot}
        storageKey="telemetry-agents"
        back={{ href: '/telemetry', label: 'Telemetry' }}
        primaryAction={{
          label: 'Create a health watcher',
          icon: Plus,
          onClick: () => void create(AGENT_TEMPLATES[0]),
          disabled: !canCreate || !!busy,
          busy: busy === AGENT_TEMPLATES[0].id,
          title: canCreate ? `Create a Machine health watcher${asset ? ` for ${asset.name || asset.key}` : ''}` : 'Your role cannot create agents. Ask an admin.',
          testId: 'telemetry-agents-primary',
        }}
        secondaryAction={{ label: 'Signal rules', icon: Zap, href: '/telemetry/rules', testId: 'telemetry-agents-rules' }}
        steps={[
          { title: 'Pick the asset', body: 'Optional. The agent is told about it and, if it can send commands, may only command it.' },
          { title: 'Create from a template', body: 'One click makes the agent with the right tools and a prompt. Commands start with a person approving each one.' },
          { title: 'Tune it', body: 'In the builder, click device_command to pick the signals it may set, how approval works and its rate.' },
          { title: 'Run it from a rule', body: 'A signal rule runs it the moment a reading crosses a line, and passes it the asset, the signal and the recent trend.' },
        ]}
        howItWorks={
          <p className="text-xs text-slate-400">
            Agents read streams with asset_search, device_state and signal_history, and act with device_command. Each command goes through the same checks as one sent by hand, is kept in the audit log with the run and the reason, and reaches your app as the telemetry.command_sent event.
          </p>
        }
      />

      {perms && !canCreate && (
        <ViewOnlyBanner testId="telemetry-agents-view-only">You can see the templates. Your role cannot create agents, ask an admin.</ViewOnlyBanner>
      )}

      <section className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4" data-testid="telemetry-agents-asset">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="min-w-0">
            <label htmlFor="tpl-asset" className="mb-1 block text-xs font-medium text-slate-300">Asset to watch</label>
            {loadErr ? (
              <div className="flex items-center justify-between gap-2 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-xs text-rose-100" role="alert">
                <span>{loadErr}</span>
                <button type="button" onClick={() => void targets.mutate()} className="inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-rose-500/10"><RefreshCw className="h-3 w-3" /> Try again</button>
              </div>
            ) : (
              <select id="tpl-asset" value={asset?.key || ''} onChange={(e) => { setAssetKey(e.target.value); setSignals([]); }} disabled={!t}
                className="min-h-[40px] w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-60" data-testid="telemetry-agents-asset-select">
                <option value="">{t ? 'Any asset, named when it runs' : 'Loading assets'}</option>
                {asset && t && !t.assets.some((a) => `${a.group}/${a.node}` === asset.key) && <option value={asset.key}>{asset.name || asset.key}</option>}
                {(t?.assets || []).map((a) => <option key={a.key} value={`${a.group}/${a.node}`}>{a.name} ({a.group}/{a.node}){a.online === false ? ', offline' : ''}</option>)}
              </select>
            )}
            <p className="mt-1 text-xs text-slate-500">
              {t && t.assets.length === 0 ? <>No assets are streaming yet. <Link href="/telemetry" className="text-cyan-300 hover:underline">Connect a source</Link> first, or create an agent that names its asset when it runs.</> : 'Leave it on any asset for an agent that works on whatever a rule hands it.'}
            </p>
          </div>
          <div className="min-w-0">
            <p className="mb-1 block text-xs font-medium text-slate-300">Signals a commanding agent may set</p>
            {!asset ? (
              <p className="text-xs text-slate-500">Pick an asset to choose from what it reports.</p>
            ) : writable === null ? (
              <p className="flex items-center gap-1.5 text-xs text-slate-400"><Loader2 className="h-3 w-3 animate-spin" /> Reading what it reports</p>
            ) : writableNames.length === 0 ? (
              <p className="text-xs text-slate-400">It has no writable signals now. You can type them in the builder later.</p>
            ) : (
              <div className="flex max-h-32 flex-wrap gap-1.5 overflow-auto" data-testid="telemetry-agents-signals">
                {writableNames.slice(0, 60).map((s) => {
                  const on = signals.includes(s);
                  return (
                    <button key={s} type="button" aria-pressed={on} onClick={() => setSignals(on ? signals.filter((x) => x !== s) : [...signals, s])}
                      className={`rounded-full border px-2 py-0.5 font-mono text-[11px] ${on ? 'border-cyan-500/70 bg-cyan-500/15 text-cyan-100' : 'border-slate-700 text-slate-300 hover:border-slate-500'}`}>
                      {s}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </section>

      {createErr && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-100" role="alert" data-testid="telemetry-agents-error">{createErr}</div>
      )}

      {created && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4" role="status" data-testid="telemetry-agents-created" data-agent-id={created.id}>
          <p className="flex items-center gap-2 text-sm font-semibold text-emerald-100"><CheckCircle2 className="h-4 w-4" /> {created.name} is ready</p>
          <p className="mt-1 text-sm text-slate-300">
            {created.template.commands ? 'Next, check what it may command, then run it from a rule.' : 'Next, run it from a rule, or ask it something in the builder.'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link href={`/builder?agent=${created.id}`} className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-cyan-500 px-3 text-sm font-medium text-white hover:bg-cyan-400" data-testid="telemetry-agents-open-builder">
              <Wrench className="h-4 w-4" /> {created.template.commands ? 'Check its command policy' : 'Open in the builder'}
            </Link>
            <Link href={`/telemetry/rules/new?run_agent=${created.id}${asset ? `&group=${encodeURIComponent(asset.key.split('/')[0])}&node=${encodeURIComponent(asset.key.split('/')[1] || '')}` : ''}`}
              className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border border-slate-600 px-3 text-sm text-slate-200 hover:bg-slate-800" data-testid="telemetry-agents-new-rule">
              <Zap className="h-4 w-4" /> Run it from a new rule
            </Link>
            <Link href={`/agents/${created.id}/info`} className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border border-slate-700 px-3 text-sm text-slate-300 hover:bg-slate-800">
              <ExternalLink className="h-4 w-4" /> Agent page
            </Link>
          </div>
        </div>
      )}

      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" data-testid="telemetry-agents-templates">
        {AGENT_TEMPLATES.map((tpl) => (
          <TemplateCard key={tpl.id} t={tpl} picked={picked === tpl.id} asset={asset} signals={signals} canCreate={canCreate}
            createWhy="Your role cannot create agents. Ask an admin." canCommand={!!t?.can_command} busy={busy === tpl.id} onCreate={(x) => void create(x)} />
        ))}
      </ul>
      <p className="flex items-center gap-1.5 text-xs text-slate-500"><Send className="h-3.5 w-3.5" aria-hidden /> Results reach your own app through forge.events.stream and forge.telemetry.firings in the SDK. <Link href="/docs?doc=08-howto%2F19-close-the-loop" className="text-cyan-300 hover:underline">How to close the loop</Link></p>
    </div>
  );
}

export default function TelemetryAgentsRoute() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-6xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>}>
      <AgentsPage />
    </Suspense>
  );
}
