'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Car, CircuitBoard, Factory, Loader2, Plus, RefreshCw, Send, Wifi } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { usePageTitle } from '@/hooks/usePageTitle';
import { holds, useMyPermissions } from '@/lib/capabilities';
import AddGatewayWizard, { type WizardStart } from '@/components/edge/AddGatewayWizard';
import AgentsPanel, { DeployModal } from '@/components/edge/AgentsPanel';
import GatewayCard from '@/components/edge/GatewayCard';
import GatewayDetail from '@/components/edge/GatewayDetail';
import { edgeCall, type Catalog, type Gateway } from '@/components/edge/model';

const PURPOSE = 'Collect from vehicle buses, PLCs, meters, GPS and site brokers with a small gateway on your own box, and run agents next to the machines. Readings wait on the box when the link drops.';

function EdgePage() {
  usePageTitle('Edge');
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { perms, loading: permsLoading } = useMyPermissions();
  const canManage = holds(perms?.capabilities, 'telemetry.manage');

  const [gateways, setGateways] = useState<Gateway[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [deployTo, setDeployTo] = useState<Gateway | null>(null);
  const [deployed, setDeployed] = useState<{ gw: Gateway; agentId: string } | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const wizardOpen = params.get('add') === 'gateway';
  const detailId = params.get('gateway');
  const [editStart, setEditStart] = useState<WizardStart | null>(null);
  const start: WizardStart = useMemo(() => editStart || { collector: params.get('collector') }, [editStart, params]);

  const setParams = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(Array.from(params.entries()));
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    router.replace(`${pathname}${qs ? `?${qs}` : ''}`, { scroll: false });
  }, [params, pathname, router]);

  const load = useCallback(async () => {
    const r = await edgeCall<{ gateways: Gateway[] }>('/api/edge/gateways');
    if (r.error) setLoadErr(r.error);
    else { setLoadErr(null); setGateways(r.data?.gateways || []); }
  }, []);

  useEffect(() => {
    load();
    edgeCall<Catalog>('/api/edge/collectors/catalog').then((r) => r.data && setCatalog(r.data));
    const h = setInterval(load, 10_000);
    return () => clearInterval(h);
  }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const openWizard = (collector?: string) => {
    setEditStart(null);
    setParams({ add: 'gateway', collector: collector || null, gateway: null });
  };
  const closeWizard = () => {
    setEditStart(null);
    setParams({ add: null, collector: null, role: null });
    load();
  };

  const collecting = (gateways || []).filter((g) => (g.roles || []).includes('collect'));
  const agentsOnly = (gateways || []).filter((g) => !(g.roles || []).includes('collect'));
  const online = (gateways || []).filter((g) => g.status === 'online').length;

  return (
    <div className="p-4 sm:p-6" data-testid="edge-page">
      <div className="mx-auto max-w-6xl space-y-6">
        <PageHeader
          title="Edge"
          purpose={PURPOSE}
          icon={CircuitBoard}
          storageKey="edge"
          docSlug="08-howto/18-connect-your-organisation"
          primaryAction={canManage ? { label: 'Add an edge gateway', icon: Plus, onClick: () => openWizard(), testId: 'edge-add' } : undefined}
          extraActions={
            <button type="button" onClick={refresh} className="flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs text-slate-300 hover:bg-slate-700/60" data-testid="edge-refresh">
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
            </button>
          }
          howToggleTestId="how-it-works-toggle"
          steps={[
            { title: 'Say what it collects', body: 'A CAN bus, Modbus, OPC UA, a GPS, a site MQTT broker or a log file. Each form has examples and checks as you type.' },
            { title: 'Run the install command', body: 'Docker, Compose, Kubernetes or a Linux box with systemd, amd64 or arm64. It carries a one-time token.' },
            { title: 'Watch it start', body: 'The gateway enrols, gets its own key and its source in Telemetry, then reports health every few seconds.' },
            { title: 'Use the data', body: 'Readings land in Telemetry under the group and asset you picked, ready for rules, agents and twins.' },
          ]}
          howItWorks={
            <p className="text-xs text-slate-400">
              Abenix Edge keeps every reading on the box&apos;s disk until Abenix has it, oldest first, for 72 hours by default. Changes you make here reach the gateway on its next heartbeat. Revoke stops it at once. Devices that can send MQTT, HTTP, Kafka or OPC UA to Abenix themselves do not need a gateway, see <Link href="/telemetry?guide=1" className="text-cyan-300 underline">Telemetry, Get started</Link>.
            </p>
          }
        />

        {!permsLoading && !canManage && (
          <ViewOnlyBanner testId="edge-view-only">
            You can see the gateways and their health. Adding, changing, revoking or removing a gateway, and sending agents to one, needs Manage telemetry brokers. An admin can give you that under Admin, Permissions.
          </ViewOnlyBanner>
        )}

        {deployed && (
          <NextSteps
            title={`Agent sent to ${deployed.gw.name}. What next?`}
            testId="edge-next-steps"
            onDismiss={() => setDeployed(null)}
            steps={[
              { id: 'agent', label: 'Open the agent', hint: 'See its settings and recent runs.', icon: CircuitBoard, href: `/agents/${deployed.agentId}` },
              { id: 'another', label: 'Deploy another agent', hint: 'Send one more agent to the same gateway.', icon: Send, onClick: () => { setDeployTo(deployed.gw); setDeployed(null); } },
            ]}
          />
        )}

        <section aria-labelledby="edge-gateways-title" className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 id="edge-gateways-title" className="flex items-center gap-2 text-lg font-semibold text-white">
                <Wifi className="h-4 w-4 text-cyan-400" /> Gateways{gateways ? ` (${gateways.length})` : ''}
              </h2>
              {gateways && gateways.length > 0 && <p className="text-xs text-slate-400">{online} online. Details shows each collector, the buffer and the link.</p>}
            </div>
          </div>

          {loadErr && (
            <div role="alert" data-testid="edge-error" className="flex flex-wrap items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
              Could not load the gateways. {loadErr}
              <button type="button" onClick={refresh} className="underline">Try again</button>
            </div>
          )}

          {!gateways && !loadErr && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2" aria-busy="true" aria-label="Loading gateways">
              {[0, 1].map((i) => <div key={i} className="h-40 animate-pulse rounded-lg border border-slate-800 bg-slate-800/30" />)}
              <span className="sr-only">Loading gateways</span>
            </div>
          )}

          {gateways && gateways.length === 0 && (
            <div className="rounded-lg border border-dashed border-slate-700 bg-slate-800/20 p-6" data-testid="edge-empty">
              <p className="text-sm font-medium text-white">No edge gateways yet.</p>
              <p className="mt-1 max-w-2xl text-sm text-slate-400">
                Add one when something cannot reach Abenix on its own: engine data on a truck&apos;s CAN bus, a meter on RS-485, PLCs on a closed site network, or a GPS. The guide asks what it collects, makes the install command and waits with you for the first data.
              </p>
              {canManage ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  <button type="button" onClick={() => openWizard()} className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500" data-testid="edge-empty-add">
                    <Plus className="h-4 w-4" /> Add an edge gateway
                  </button>
                  <button type="button" onClick={() => openWizard('can')} className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800" data-testid="edge-empty-vehicle">
                    <Car className="h-4 w-4" /> From a vehicle bus
                  </button>
                  <button type="button" onClick={() => openWizard('modbus')} className="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800" data-testid="edge-empty-plc">
                    <Factory className="h-4 w-4" /> From a meter or PLC
                  </button>
                </div>
              ) : (
                <p className="mt-3 text-xs text-slate-400">Someone who can manage telemetry sources adds gateways. They show up here with their health.</p>
              )}
            </div>
          )}

          {collecting.length > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2" data-testid="edge-gateways">
              {collecting.map((g) => (
                <GatewayCard key={g.id} g={g} canManage={canManage} onOpen={() => setParams({ gateway: g.id })} onDeploy={() => setDeployTo(g)} />
              ))}
            </div>
          )}
          {agentsOnly.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-slate-200">Running agents only</h3>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {agentsOnly.map((g) => (
                  <GatewayCard key={g.id} g={g} canManage={canManage} onOpen={() => setParams({ gateway: g.id })} onDeploy={() => setDeployTo(g)} />
                ))}
              </div>
            </div>
          )}
        </section>

        <AgentsPanel canManage={canManage} />
      </div>

      {wizardOpen && canManage && (
        <AddGatewayWizard open catalog={catalog} start={start} onClose={closeWizard} onChanged={load} />
      )}
      {wizardOpen && !canManage && !permsLoading && (
        <div className="fixed bottom-4 left-4 right-4 z-40 mx-auto max-w-lg rounded-lg border border-slate-600 bg-slate-900 p-4 text-sm text-slate-200 shadow-xl" role="status">
          Adding a gateway needs Manage telemetry brokers. An admin can give you that under Admin, Permissions.
          <button type="button" onClick={closeWizard} className="ml-2 text-cyan-300 underline">Close</button>
        </div>
      )}
      {wizardOpen && !catalog && canManage && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50" aria-label="Loading"><Loader2 className="h-6 w-6 animate-spin text-cyan-300" /></div>
      )}
      {detailId && (
        <GatewayDetail
          id={detailId}
          canManage={canManage}
          onClose={() => setParams({ gateway: null })}
          onChanged={load}
          onEdit={(g) => { setEditStart({ gateway: g, step: 1 }); setParams({ gateway: null, add: 'gateway' }); }}
        />
      )}
      {deployTo && (
        <DeployModal gateway={deployTo} onClose={() => setDeployTo(null)} onDeployed={(agentId) => { setDeployed({ gw: deployTo, agentId }); setDeployTo(null); load(); }} />
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<div className="flex min-h-[60vh] items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-cyan-400" /></div>}>
      <EdgePage />
    </Suspense>
  );
}
