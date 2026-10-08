import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  filterWorkloads, fmtAge, fmtBytes, fmtCores, groupSummary, groupWorkloads, hiddenAccess, isProblem,
  metricText, scalingText, sparkPoints, splitLogLine, usageTone, type Overview, type Workload,
} from '@/lib/cluster';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api-client', () => ({ apiFetch, API_URL: 'http://test' }));
// the page sits behind the admin gate
vi.mock('@/lib/capabilities', async (orig) => ({
  ...(await orig<typeof import('@/lib/capabilities')>()),
  useMyPermissions: () => ({ perms: { role: 'admin', is_admin: true, features: {}, capabilities: ['*'] }, loading: false }),
}));

import ClusterPage from '@/app/(app)/admin/cluster/page';
import PodDrawer from '@/components/cluster/PodDrawer';

function wl(over: Partial<Workload> = {}): Workload {
  return {
    kind: 'Deployment',
    name: 'abenix-api',
    display: 'api',
    group: 'Core',
    critical: true,
    desired: 1,
    ready: 1,
    updated: 1,
    available: 1,
    status: 'healthy',
    status_text: 'All 1 running and ready.',
    images: [{ container: 'api', image: 'reg/abenix/api:50dc0306', tag: '50dc0306' }],
    image_tag: '50dc0306',
    age_seconds: 3600,
    restarts: 0,
    last_restart: null,
    pods: [{ name: 'abenix-api-7d9f-x1', phase: 'Running', status: 'Running', ready: true, containers_ready: 1, containers_total: 1, restarts: 0, age_seconds: 600 }],
    cpu_used_cores: null,
    mem_used_bytes: null,
    scaling: null,
    history: [],
    ...over,
  };
}

function overview(over: Partial<Overview> = {}): Overview {
  return {
    namespace: 'abenix',
    release: 'abenix',
    source: 'in-cluster',
    rbac_value: 'clusterView.rbac.enabled',
    rbac_setting: 'true',
    generated_at: new Date().toISOString(),
    ttl_seconds: 10,
    cache_age_seconds: 0,
    nodes: [{
      name: 'minikube', ready: true, unschedulable: false, roles: ['control-plane'], cpu_cores: 6, cpu_allocatable_cores: 6,
      mem_bytes: 24 * 1024 ** 3, mem_allocatable_bytes: 24 * 1024 ** 3, pods_capacity: 110, pods_here: 35,
      cpu_requested_cores: 3, mem_requested_bytes: 8 * 1024 ** 3, cpu_used_cores: 0.3, mem_used_bytes: 7 * 1024 ** 3,
      cpu_pct: 5, mem_pct: 30, pressure: [], conditions: [{ type: 'Ready', status: 'True' }], taints: [], kubelet_version: 'v1.35.1', age_seconds: 86400,
    }],
    workloads: [
      wl(),
      wl({ name: 'abenix-web', display: 'web', status: 'down', ready: 0, status_text: 'No pods ready (0 of 1).' }),
      wl({ name: 'abenix-nats', display: 'nats', group: 'Data', kind: 'StatefulSet' }),
      wl({ name: 'coderun-x', display: 'coderun-x', group: 'Runtime pools', critical: false, desired: 0, ready: 0, status: 'idle', pods: [] }),
    ],
    events: [{ type: 'Warning', reason: 'BackOff', message: 'Back-off restarting failed container', kind: 'Pod', object: 'abenix-web-1-a', workload: 'abenix-web', count: 3, at: new Date().toISOString(), age_seconds: 60 }],
    pvcs: [],
    access: [
      { key: 'nodes', label: 'Nodes', why: 'node count', scope: 'cluster', ok: true, optional: false },
      { key: 'node_metrics', label: 'Node usage', why: 'live use', scope: 'cluster', ok: true, optional: true },
    ],
    totals: { nodes: 1, nodes_ready: 1, cpu_cores: 6, mem_bytes: 24 * 1024 ** 3, cpu_used_cores: 0.3, mem_used_bytes: 7 * 1024 ** 3, pods: 4, pod_phases: { Running: 4 }, services: 4, services_healthy: 3, warnings_recent: 3 },
    verdict: { state: 'critical', label: 'Service down', reasons: [{ level: 'critical', text: 'web is down. No pods ready (0 of 1).', target: 'abenix-web', kind: 'workload' }] },
    ...over,
  };
}

function route(ov: Overview | null, err: string | null = null) {
  apiFetch.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/admin/cluster/overview')) return { data: ov, error: err };
    if (url.startsWith('/api/admin/cluster/database')) return { data: { bytes: 1024 ** 2, top_tables: [] }, error: null };
    if (url.endsWith('/logs?container=main&lines=200&previous=false')) return { data: { pod: 'p', container: 'main', previous: false, lines: ['2026-10-08T10:00:00.123Z hello world', 'second line'], truncated: false }, error: null };
    if (url.startsWith('/api/admin/cluster/pods/')) {
      return {
        data: {
          name: 'abenix-api-7d9f-x1', phase: 'Running', status: 'Running', ready: true, containers_ready: 1, containers_total: 1, restarts: 0,
          owner: 'abenix-api', node: 'minikube', conditions: [],
          containers: [{ name: 'main', init: false, image: 'reg/api:1', tag: '1', ready: true, restarts: 0, state: 'running', last_termination: null, requests: {}, limits: {} }],
          events: [{ type: 'Normal', reason: 'Pulled', message: 'Image pulled', count: 1, at: new Date().toISOString(), age_seconds: 30 }],
        },
        error: null,
      };
    }
    return { data: null, error: 'unexpected' };
  });
}

beforeEach(() => {
  apiFetch.mockReset();
  localStorage.clear();
});

describe('cluster helpers', () => {
  it('formats sizes, cores and ages plainly', () => {
    expect(fmtBytes(0)).toBe('0 B');
    expect(fmtBytes(1536)).toBe('1.5 KB');
    expect(fmtBytes(24 * 1024 ** 3)).toBe('24.0 GB');
    expect(fmtCores(0.25)).toBe('250m');
    expect(fmtCores(6)).toBe('6');
    expect(fmtCores(3.8)).toBe('3.80');
    expect(fmtAge(45)).toBe('45s');
    expect(fmtAge(3 * 3600 + 120)).toBe('3h 2m');
    expect(fmtAge(11 * 86400)).toBe('11d');
    expect(usageTone(95)).toBe('bad');
    expect(usageTone(80)).toBe('warn');
    expect(usageTone(null)).toBe('none');
  });

  it('filters by group, status and search across pods and images', () => {
    const ws = overview().workloads;
    expect(filterWorkloads(ws, '', 'Data', 'all').map((w) => w.name)).toEqual(['abenix-nats']);
    expect(filterWorkloads(ws, '', 'all', 'problems').map((w) => w.name)).toEqual(['abenix-web']);
    expect(filterWorkloads(ws, '', 'all', 'idle').map((w) => w.name)).toEqual(['coderun-x']);
    expect(filterWorkloads(ws, '7d9f', 'all', 'all').map((w) => w.name)).toContain('abenix-api');
    expect(filterWorkloads(ws, '50dc03', 'Core', 'all').length).toBe(2);
    expect(isProblem(wl({ status: 'progressing', pods: [{ ...wl().pods[0], waiting: { reason: 'CrashLoopBackOff' } }] }))).toBe(true);
  });

  it('groups in a fixed order and summarises each group', () => {
    const g = groupWorkloads(overview().workloads);
    expect(g.map((x) => x.group)).toEqual(['Core', 'Runtime pools', 'Data']);
    expect(groupSummary(g[0].items)).toEqual({ text: '2 services, 1 down', tone: 'bad' });
    expect(groupSummary(g[2].items).tone).toBe('ok');
  });

  it('describes scaling and metrics', () => {
    expect(scalingText(null)).toBe('Fixed size');
    const s = { kind: 'keda' as const, name: 'x', min: 1, max: 8, current: 2, desired: 2, metrics: [], active: true, paused: false, triggers: [] };
    expect(scalingText(s)).toBe('KEDA 1–8');
    expect(scalingText({ ...s, paused: true })).toBe('KEDA 1–8, paused');
    expect(metricText({ name: 's0', label: 'Queue backlog (agents)', current: '12', current_value: 12, target: '3' })).toBe('Queue backlog (agents): 12 / 3');
    expect(metricText({ name: 'cpu', label: 'CPU use', current: null, current_value: null, target: '70%' })).toBe('CPU use, target 70%');
  });

  it('builds sparkline points only with enough history', () => {
    expect(sparkPoints([], 100, 20).ready).toBe('');
    const p = sparkPoints([{ t: 1, ready: 1, desired: 2 }, { t: 2, ready: 2, desired: 2 }], 100, 20);
    expect(p.max).toBe(2);
    expect(p.ready.split(' ')).toHaveLength(2);
  });

  it('separates blocking access gaps from optional add-ons', () => {
    const { blocking, optional } = hiddenAccess([
      { key: 'nodes', label: 'Nodes', why: '', scope: 'cluster', ok: false, optional: false, state: 'forbidden' },
      { key: 'node_metrics', label: 'm', why: '', scope: 'cluster', ok: false, optional: true, state: 'not_installed' },
      { key: 'pods', label: 'Pods', why: '', scope: 'namespace', ok: true, optional: false },
    ]);
    expect(blocking.map((a) => a.key)).toEqual(['nodes']);
    expect(optional.map((a) => a.key)).toEqual(['node_metrics']);
  });

  it('splits the kubernetes timestamp off a log line', () => {
    expect(splitLogLine('2026-10-08T10:00:00.123456Z hello')).toEqual({ time: '10:00:00', text: 'hello' });
    expect(splitLogLine('plain')).toEqual({ time: '', text: 'plain' });
  });
});

describe('cluster page', () => {
  it('shows the verdict, real node numbers and grouped services', async () => {
    route(overview());
    render(<ClusterPage />);
    expect(screen.getByTestId('cluster-loading')).toBeInTheDocument();
    await screen.findByTestId('cluster-verdict');
    expect(screen.getByTestId('cluster-verdict')).toHaveAttribute('data-state', 'critical');
    expect(screen.getByTestId('cluster-node-count')).toHaveTextContent('1');
    expect(screen.getByTestId('cluster-core-count')).toHaveTextContent('6 cores');
    const rows = screen.getAllByTestId('service-row');
    expect(rows.map((r) => r.getAttribute('data-service'))).toEqual(['abenix-api', 'abenix-web', 'coderun-x', 'abenix-nats']);
    expect(screen.getAllByTestId('service-group').map((g) => g.getAttribute('data-group'))).toEqual(['Core', 'Runtime pools', 'Data']);
    expect(screen.getAllByTestId('warning-item')).toHaveLength(1);
    expect(screen.getByTestId('cluster-link-scaling')).toHaveAttribute('href', '/admin/scaling');
    expect(screen.getByTestId('cluster-link-live')).toHaveAttribute('href', '/executions/live');
    expect(screen.getByTestId('cluster-link-grafana-disabled')).toHaveAttribute('title', expect.stringMatching(/not configured/));
  });

  it('filters and recovers from an empty filter', async () => {
    route(overview({ grafana_url: 'http://localhost:3030' }));
    render(<ClusterPage />);
    await screen.findByTestId('cluster-verdict');
    expect(screen.getByTestId('cluster-link-grafana')).toHaveAttribute('href', 'http://localhost:3030/d/abenix-overview');
    fireEvent.change(screen.getByTestId('cluster-search'), { target: { value: 'nothing-like-this' } });
    expect(screen.getByTestId('cluster-services-nomatch')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Clear filters'));
    expect(screen.getAllByTestId('service-row')).toHaveLength(4);
    fireEvent.click(screen.getByTestId('cluster-status-problems'));
    expect(screen.getAllByTestId('service-row').map((r) => r.getAttribute('data-service'))).toEqual(['abenix-web']);
  });

  it('pauses auto refresh and remembers it', async () => {
    route(overview());
    render(<ClusterPage />);
    await screen.findByTestId('cluster-verdict');
    fireEvent.click(screen.getByTestId('cluster-pause'));
    expect(screen.getByTestId('cluster-pause')).toHaveAttribute('aria-pressed', 'true');
    expect(localStorage.getItem('cluster-view-paused')).toBe('1');
    expect(screen.getByTestId('cluster-updated')).toHaveTextContent(/paused/);
  });

  it('explains what is hidden and which helm value fixes it', async () => {
    route(overview({
      access: [{ key: 'nodes', label: 'Nodes', why: 'node count, cores', scope: 'cluster', ok: false, optional: false, state: 'forbidden', fix: 'Set clusterView.rbac.enabled=true and run helm upgrade.' }],
      nodes: [],
    }));
    render(<ClusterPage />);
    await screen.findByTestId('cluster-access-panel');
    expect(screen.getByTestId('cluster-access-panel')).toHaveTextContent('clusterView.rbac.enabled=true');
    expect(screen.getByTestId('cluster-nodes-hidden')).toBeInTheDocument();
    expect(screen.queryByTestId('cluster-node-count')).toBeNull();
  });

  it('explains running outside kubernetes', async () => {
    route(overview({ source: 'outside', nodes: [], workloads: [], outside_reason: 'no kubeconfig' }));
    render(<ClusterPage />);
    expect(await screen.findByTestId('cluster-outside')).toHaveTextContent(/not running in Kubernetes/);
    expect(screen.queryByTestId('cluster-verdict')).toBeNull();
  });

  it('shows an error with a retry when the first load fails', async () => {
    route(null, 'admin-only');
    render(<ClusterPage />);
    expect(await screen.findByTestId('cluster-error')).toHaveTextContent('admin-only');
  });
});

describe('pod drawer', () => {
  it('shows containers, events and the log tail', async () => {
    route(overview());
    render(<PodDrawer pod="abenix-api-7d9f-x1" onClose={() => {}} />);
    await screen.findByTestId('pod-events');
    expect(screen.getAllByTestId('pod-event')).toHaveLength(1);
    await waitFor(() => expect(screen.getByTestId('pod-logs')).toHaveTextContent('hello world'));
    expect(screen.getByTestId('pod-logs')).toHaveAttribute('data-lines', '2');
    expect(screen.getByTestId('pod-logs-previous')).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Filter log lines'), { target: { value: 'second' } });
    expect(screen.getByTestId('pod-logs')).not.toHaveTextContent('hello world');
  });

  it('renders nothing when closed', () => {
    const { container } = render(<PodDrawer pod={null} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});
