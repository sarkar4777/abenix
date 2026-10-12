'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import useSWR from 'swr';
import { BellRing, Boxes, ChevronRight, FlaskConical, ListChecks, Loader2, Plus, RadioTower, RefreshCw, Search, Trash2, Zap } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { toastError, toastSuccess } from '@/stores/toastStore';
import FiringHistory from '@/components/telemetry-rules/FiringHistory';
import { TEMPLATES, ago, type Rule } from '@/components/telemetry-rules/lib';
import { Badge, severityTone } from '@/components/telemetry-rules/ui';
import RulesMode, { type ModeDoc } from '@/components/telemetry-rules/RulesMode';

const PURPOSE = 'Watch live signals and act the moment something happens: raise an alert, tell people, run an agent, check a decision table or send a command.';
const WHO_CAN = 'An admin, or anyone with Manage telemetry, can create and change rules.';

function fetcher(url: string) {
  return apiFetch<unknown>(url, { silent: true });
}

function useNow(ms: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const h = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(h);
  }, [ms]);
  return now;
}

interface Health { evaluators: Record<string, { lag_p99_ms?: number | null; observe_us_p99?: number | null; rules?: number; fired?: number }>; ingest_latency: Record<string, { p99?: number }>; mode?: ModeDoc }

function RuleCard({ r, canManage, now, onToggle, onTest, onDelete, busy }: {
  r: Rule; canManage: boolean; now: number; onToggle: (r: Rule) => void; onTest: (r: Rule) => void; onDelete: (r: Rule) => void; busy: boolean;
}) {
  const edit = canManage && r.can_edit;
  return (
    <li className="min-w-0 rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 [overflow-wrap:anywhere]" data-testid="rule-card" data-rule-id={r.id} data-enabled={r.enabled}>
      <div className="flex flex-wrap items-start gap-2">
        <Link href={`/telemetry/rules/${r.id}`} className="min-w-0 flex-1 text-sm font-semibold text-white hover:text-cyan-200" data-testid="rule-open">
          <span className="break-words">{r.name}</span>
        </Link>
        <Badge tone={severityTone(r.severity)}>{r.severity}</Badge>
        {r.firing_now > 0 && <Badge tone="rose" testId="rule-firing-now">Firing on {r.firing_now}</Badge>}
        {edit ? (
          <label className="inline-flex min-h-[32px] cursor-pointer items-center gap-2 rounded-full border border-slate-700 px-2.5 text-xs text-slate-200" title={r.enabled ? 'Turn the rule off' : 'Turn the rule on'}>
            <input type="checkbox" className="accent-cyan-500" checked={r.enabled} disabled={busy} onChange={() => onToggle(r)} data-testid="rule-toggle" aria-label={r.enabled ? `Turn ${r.name} off` : `Turn ${r.name} on`} />
            {r.enabled ? 'On' : 'Off'}
          </label>
        ) : (
          <Badge tone={r.enabled ? 'emerald' : 'slate'}>{r.enabled ? 'On' : 'Off'}</Badge>
        )}
      </div>
      <p className="mt-1.5 text-sm text-slate-300" data-testid="rule-summary">{r.summary}</p>
      {r.description && <p className="mt-1 text-xs text-slate-500">{r.description}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
        <span>{r.fire_count ? `Fired ${r.fire_count.toLocaleString('en-US')} ${r.fire_count === 1 ? 'time' : 'times'}` : 'Has not fired yet'}</span>
        {r.last_fired_at && <span>last {ago(r.last_fired_at, now)}</span>}
      </div>
      {r.last_firing && (
        <p className="mt-1 truncate text-xs text-slate-500" title={r.last_firing.detail}>Last: {r.last_firing.detail}</p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Link href={`/telemetry/rules/${r.id}`} className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-slate-700 px-3 text-xs text-slate-200 hover:bg-slate-800">
          {edit ? 'Open and edit' : 'Open'} <ChevronRight className="h-3.5 w-3.5" />
        </Link>
        {edit && (
          <>
            <button type="button" onClick={() => onTest(r)} disabled={busy || !r.actions.length} title={r.actions.length ? 'Run the steps once now with the latest reading, commands are skipped' : 'The rule has no steps to test'} className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-slate-700 px-3 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50" data-testid="rule-card-test">
              <FlaskConical className="h-3.5 w-3.5" /> Test
            </button>
            <button type="button" onClick={() => onDelete(r)} disabled={busy} className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-rose-500/40 px-3 text-xs text-rose-200 hover:bg-rose-500/10 disabled:opacity-50" data-testid="rule-card-delete">
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </button>
          </>
        )}
      </div>
    </li>
  );
}

function RulesPage() {
  usePageTitle('Signal rules');
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { perms, loading: permsLoading } = useMyPermissions();
  const caps = perms?.capabilities;
  const canView = holds(caps, 'telemetry.view');
  const canManage = holds(caps, 'telemetry.manage');
  const now = useNow(10_000);
  const tab = params.get('tab') === 'history' ? 'history' : 'rules';
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<Rule | null>(null);

  // links from alerts and notifications name the rule
  const ruleParam = params.get('rule');
  useEffect(() => {
    if (ruleParam) router.replace(`/telemetry/rules/${encodeURIComponent(ruleParam)}`);
  }, [ruleParam, router]);

  const setTab = useCallback((t: string) => {
    const next = new URLSearchParams(Array.from(params.entries()));
    if (t === 'rules') next.delete('tab'); else next.set('tab', t);
    const qs = next.toString();
    router.replace(`${pathname}${qs ? `?${qs}` : ''}`, { scroll: false });
  }, [params, pathname, router]);

  const res = useSWR(canView ? '/api/telemetry/rules' : null, fetcher, { refreshInterval: 10_000, revalidateOnFocus: false, keepPreviousData: true });
  const rules = Array.isArray(res.data?.data) ? (res.data!.data as Rule[]) : null;
  const health = useSWR(canView && rules && rules.length ? '/api/telemetry/rules/health' : null, fetcher, { refreshInterval: 15_000, revalidateOnFocus: false });
  const h = (health.data?.data ?? null) as Health | null;
  const evalLag = h ? Math.max(0, ...Object.values(h.evaluators || {}).map((e) => e.lag_p99_ms ?? 0)) : null;
  const ingestP99 = h ? Math.max(0, ...Object.values(h.ingest_latency || {}).map((e) => e.p99 ?? 0)) : null;
  const error = res.data?.error || (res.error ? 'The rules could not load.' : null);
  const list = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return (rules || []).filter((r) => !ql || r.name.toLowerCase().includes(ql) || r.summary.toLowerCase().includes(ql));
  }, [rules, q]);
  const firingNow = (rules || []).reduce((n, r) => n + (r.firing_now || 0), 0);

  async function toggle(r: Rule) {
    setBusy(true);
    const out = await apiFetch<Rule>(`/api/telemetry/rules/${r.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !r.enabled }), silent: true });
    setBusy(false);
    if (out.error) { toastError(out.error); return; }
    toastSuccess(r.enabled ? `${r.name} is off. It stops watching within a couple of seconds.` : `${r.name} is on and watching the stream.`);
    void res.mutate();
  }
  async function test(r: Rule) {
    setBusy(true);
    const out = await apiFetch(`/api/telemetry/rules/${r.id}/test`, { method: 'POST', silent: true });
    setBusy(false);
    if (out.error) { toastError(out.error); return; }
    toastSuccess('Test sent. Its steps run now, commands are skipped. See Firing history.');
  }
  async function del() {
    if (!deleting) return;
    setBusy(true);
    const out = await apiFetch(`/api/telemetry/rules/${deleting.id}`, { method: 'DELETE', silent: true });
    setBusy(false);
    if (out.error) { toastError(out.error); return; }
    toastSuccess(`${deleting.name} deleted.`);
    setDeleting(null);
    void res.mutate();
  }

  if (permsLoading && !perms) return <div className="mx-auto max-w-6xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>;
  if (perms && !canView) {
    return (
      <NoAccess
        testId="rules-no-access"
        title="Signal rules"
        purpose={PURPOSE}
        icon={Zap}
        need={{ capability: 'telemetry.view', label: 'View machine telemetry' }}
        role={perms.role}
        instead={{ text: 'Alerts lists anything that went wrong, including what rules raised.', href: '/alerts', label: 'Open Alerts' }}
      />
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4" data-testid="rules-page">
      <PageHeader
        title="Signal rules"
        purpose={PURPOSE}
        icon={Zap}
        storageKey="telemetry-rules"
        back={{ href: '/telemetry', label: 'Telemetry' }}
        primaryAction={canManage ? { label: 'New rule', icon: Plus, href: '/telemetry/rules/new', testId: 'rules-new' } : undefined}
        secondaryAction={{ label: 'Assets', icon: Boxes, href: '/telemetry/assets', testId: 'rules-assets' }}
        steps={[
          { title: 'Pick what to watch', body: 'One asset, or every asset of a type or with a tag. Names, types and tags come from the Assets page.' },
          { title: 'Say when', body: 'A limit, a range, a fast change, silence, a value, a zone or a count. Pick signals from what is streaming now.' },
          { title: 'See it on history', body: 'Before saving, the rule is replayed over the last hour so you see how often it would have fired.' },
          { title: 'Say what happens', body: 'Raise an alert, tell people, run an agent or pipeline, check a decision table, or send a command with the rule as the reason.' },
        ]}
        howItWorks={
          <p className="text-xs text-slate-400">
            Rules run as data streams in, not on a timer, inside the telemetry ingest or in a separate rules pool for busy installs. Each firing also goes out as the telemetry.rule_fired event, so webhooks and event subscriptions can follow it. Rules that run agents are listed on the Triggers page too.
          </p>
        }
      />

      {perms && !canManage && (
        <ViewOnlyBanner testId="rules-view-only">You can see the rules and what they did. {WHO_CAN}</ViewOnlyBanner>
      )}

      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800" role="tablist" aria-label="Rules or their history">
        {[
          { id: 'rules', label: `Rules${rules ? ` (${rules.length})` : ''}`, icon: ListChecks },
          { id: 'history', label: firingNow ? `Firing history (${firingNow} now)` : 'Firing history', icon: BellRing },
        ].map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={`-mb-px inline-flex min-h-[40px] items-center gap-1.5 border-b-2 px-3 text-sm ${tab === t.id ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
            data-testid={`rules-tab-${t.id}`}>
            <t.icon className="h-4 w-4" /> {t.label}
          </button>
        ))}
        {rules && rules.length > 0 && evalLag !== null && (
          <span className="ml-auto pb-1 text-[11px] text-slate-500" data-testid="rules-health" title="How long from a reading arriving to the rule deciding, and the ingest's own time to store it">
            Checked live: decides in {evalLag ? `${evalLag.toFixed(1)} ms` : 'under a millisecond'} (p99), ingest {ingestP99 ? `${ingestP99.toFixed(1)} ms` : 'idle'}
          </span>
        )}
      </div>

      {tab === 'rules' && rules && rules.length > 0 && h?.mode && (
        <RulesMode mode={h.mode} isAdmin={!!perms?.is_admin || perms?.role === 'admin'} onChanged={() => void health.mutate()} />
      )}

      {tab === 'history' ? (
        <FiringHistory showRule now={now} emptyHint={rules && rules.length === 0 ? 'No firings yet, because there are no rules yet.' : undefined} />
      ) : error && !rules ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-100" role="alert" data-testid="rules-error">
          <p>{error}</p>
          <button type="button" onClick={() => void res.mutate()} className="mt-2 inline-flex min-h-[36px] items-center gap-1.5 rounded-md border border-slate-600 px-3 text-xs text-slate-200 hover:bg-slate-800"><RefreshCw className="h-3.5 w-3.5" /> Try again</button>
        </div>
      ) : !rules ? (
        <div className="space-y-3" data-testid="rules-loading">{[0, 1, 2].map((i) => <div key={i} className="h-28 animate-pulse rounded-xl bg-slate-800/40" />)}</div>
      ) : rules.length === 0 ? (
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 sm:p-8" data-testid="rules-empty">
          <div className="text-center">
            <Zap className="mx-auto h-8 w-8 text-cyan-400" />
            <h2 className="mt-3 text-base font-semibold text-white">No rules yet</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm text-slate-300">
              A rule watches live signals and acts the moment something happens. {canManage ? 'Start from one of these, or build your own.' : WHO_CAN}
            </p>
          </div>
          {canManage ? (
            <div className="mx-auto mt-5 grid max-w-3xl gap-2 sm:grid-cols-2">
              {TEMPLATES.map((t) => (
                <Link key={t.id} href={`/telemetry/rules/new?template=${t.id}`} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 hover:border-cyan-500/60" data-testid={`rules-template-${t.id}`}>
                  <span className="block text-sm font-medium text-white">{t.label}</span>
                  <span className="mt-0.5 block text-xs text-slate-400">{t.help}</span>
                </Link>
              ))}
              <Link href="/telemetry/rules/new" className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-medium text-white hover:bg-cyan-400 sm:col-span-2" data-testid="rules-empty-new">
                <Plus className="h-4 w-4" /> Build a rule from scratch
              </Link>
            </div>
          ) : (
            <div className="mt-4 flex justify-center">
              <Link href="/telemetry" className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-slate-600 px-4 text-sm text-slate-200 hover:bg-slate-800"><RadioTower className="h-4 w-4" /> See the live telemetry</Link>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {rules.length > 5 && (
            <label className="relative block max-w-sm">
              <span className="sr-only">Search rules</span>
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search rules" className="min-h-[40px] w-full rounded-lg border border-slate-700 bg-slate-900 py-2 pl-8 pr-3 text-sm text-white placeholder:text-slate-500" data-testid="rules-search" />
            </label>
          )}
          {list.length === 0 ? (
            <p className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center text-sm text-slate-300">No rule matches. <button type="button" className="text-cyan-300 hover:underline" onClick={() => setQ('')}>Clear the search</button></p>
          ) : (
            <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2" data-testid="rules-list">
              {list.map((r) => <RuleCard key={r.id} r={r} canManage={canManage} now={now} onToggle={toggle} onTest={test} onDelete={setDeleting} busy={busy} />)}
            </ul>
          )}
        </div>
      )}

      <ConfirmModal
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={() => void del()}
        title={`Delete ${deleting?.name ?? 'this rule'}?`}
        description="It stops watching at once and its firing history is removed. Alerts it raised clear by themselves."
        confirmLabel="Delete rule"
        loading={busy}
        confirmTestId="rules-confirm-delete"
      />
      {busy && <span className="sr-only" aria-live="polite"><Loader2 /> Working</span>}
    </div>
  );
}

export default function RulesRoute() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-6xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>}>
      <RulesPage />
    </Suspense>
  );
}
