import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
const push = vi.fn();
const search = vi.hoisted(() => ({ q: '' }));
vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'ag-1' }),
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(search.q),
}));
vi.mock('@/hooks/usePageTitle', () => ({ usePageTitle: () => {} }));
const perms = vi.hoisted(() => ({ caps: ['improvements.view'] as string[] }));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => ({ perms: { capabilities: perms.caps }, loading: false }) };
});
const api = vi.hoisted(() => ({ agent: vi.fn(), overview: vi.fn(), sample: vi.fn(), cluster: vi.fn() }));
vi.mock('@/lib/improvements', async (orig) => {
  const actual = await orig<typeof import('@/lib/improvements')>();
  return { ...actual, improvementsApi: { ...actual.improvementsApi, ...api } };
});

import AgentImprovementsPage from '@/app/(app)/agents/[id]/improvements/page';
import ImprovementsPage from '@/app/(app)/improvements/page';
import type { AgentImprovements, Overview } from '@/lib/improvements';

const lesson = {
  id: 'l1', source: 'correction', source_label: 'Correction', polarity: 'negative' as const,
  input_text: 'What is copper today?', output_text: 'Last month it was 8,100', expected: 'Use today', note: null,
  failure_code: null, tool_name: null, execution_id: 'ex-1', by_user_name: 'Ana', created_at: new Date().toISOString(),
};

const agentData: AgentImprovements = {
  agent: { id: 'ag-1', name: 'Pricer' },
  can_manage: true,
  clusters: [{
    id: 'c1', agent: { id: 'ag-1', name: 'Pricer' }, title: "Uses last month's price", summary: '2 correction',
    count: 2, negative_count: 2, severity: 'medium', trend: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2], state: 'open',
    last_lesson_at: null, examples: [lesson, { ...lesson, id: 'l2' }], proposal: null,
  }],
  suggested_cases: [],
  proposals: [],
  releases: [],
  counts: { good_examples: 3, closed_clusters: 0, waiting_to_group: 0 },
};

const overview: Overview = {
  counts: { open_lessons: 2, open_clusters: 1, proposals_waiting: 0, releases_watching: 0, rolled_back_30d: 0 },
  agents: [{ agent: { id: 'ag-1', name: 'Pricer' }, open_clusters: 1, open_lessons: 2, worst_severity: 'medium', trend: [0, 2], last_lesson_at: null }],
  total_agents: 1,
};

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  push.mockReset();
  perms.caps = ['improvements.view'];
  search.q = '';
});

describe('agent Improvements tab', () => {
  it('shows groups with examples, the cases empty state and the proposal sections', async () => {
    api.agent.mockResolvedValue({ data: agentData, error: null });
    render(<AgentImprovementsPage />);
    await waitFor(() => expect(screen.getByTestId('agent-improvements')).toBeInTheDocument());
    expect(screen.getByTestId('improvement-cluster-title')).toHaveTextContent("Uses last month's price");
    expect(screen.getAllByTestId('improvement-lesson')).toHaveLength(2);
    expect(screen.getByTestId('improvement-cases-empty')).toBeInTheDocument();
    expect(screen.getByTestId('improvements-section-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('agent-improvements-no-releases')).toBeInTheDocument();
    expect(screen.getByTestId('agent-improvements-counts')).toHaveTextContent('3 answers people liked');
  });

  it('says who can see lessons when access is refused', async () => {
    api.agent.mockResolvedValue({ data: null, error: 'no', status: 403 });
    render(<AgentImprovementsPage />);
    await waitFor(() => expect(screen.getByTestId('agent-improvements-error')).toHaveTextContent("Only the agent's owner"));
  });

  it('loads again when See the proof points at a fix made after the last load', async () => {
    const made = {
      id: 'p-new', agent: { id: 'ag-1', name: 'Pricer' }, cluster: { id: 'c1', title: "Uses last month's price" },
      change_kind: 'prompt_edit', change_label: 'Edit the instructions', diff: {}, rationale: 'Use the live price.', risk: 'low',
      state: 'awaiting_approval', state_label: 'Waiting for approval', progress: {}, proof: {}, approval_id: 'a1',
      released_revision_id: null, watch_until: null, watch_result: null, created_at: new Date().toISOString(),
    };
    search.q = 'proposal=p-new';
    Element.prototype.scrollIntoView = vi.fn();
    api.agent
      .mockResolvedValueOnce({ data: agentData, error: null })
      .mockResolvedValue({ data: { ...agentData, proposals: [made] }, error: null });
    render(<AgentImprovementsPage />);
    await waitFor(() => expect(document.querySelector('[data-testid="proposal-item"][data-proposal-id="p-new"]')).not.toBeNull());
    expect(api.agent).toHaveBeenCalledTimes(2);
  });

  it('points to chat when there is nothing yet', async () => {
    api.agent.mockResolvedValue({ data: { ...agentData, clusters: [] }, error: null });
    render(<AgentImprovementsPage />);
    await waitFor(() => expect(screen.getByTestId('agent-improvements-no-clusters')).toHaveTextContent('thumbs down'));
  });
});

describe('Improvements page', () => {
  it('lists agents worst first with real counts', async () => {
    api.overview.mockResolvedValue({ data: overview, error: null });
    render(<ImprovementsPage />);
    await waitFor(() => expect(screen.getByTestId('improvements-count-lessons')).toHaveTextContent('2'));
    expect(screen.getByTestId('improvements-agent-row')).toHaveAttribute('href', '/agents/ag-1/improvements');
  });

  it('offers the sample when empty and explains when it is not there yet', async () => {
    api.overview.mockResolvedValue({ data: { ...overview, counts: { ...overview.counts, open_lessons: 0 }, agents: [], total_agents: 0 }, error: null });
    api.sample.mockResolvedValue({ data: null, error: 'Not Found', status: 404 });
    render(<ImprovementsPage />);
    await waitFor(() => expect(screen.getByTestId('improvements-empty')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('improvements-sample'));
    await waitFor(() => expect(screen.getByTestId('improvements-sample-message')).toHaveTextContent('arrives with the next update'));
    expect(push).not.toHaveBeenCalled();
  });

  it('opens the sample agent when it installs', async () => {
    api.overview.mockResolvedValue({ data: { ...overview, counts: { ...overview.counts, open_lessons: 0 }, agents: [], total_agents: 0 }, error: null });
    api.sample.mockResolvedValue({ data: { agent: { id: 'sample-1' } }, error: null });
    render(<ImprovementsPage />);
    await waitFor(() => screen.getByTestId('improvements-sample'));
    fireEvent.click(screen.getByTestId('improvements-sample'));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/agents/sample-1/improvements'));
  });

  it('keeps the sample one click away once lessons exist', async () => {
    api.overview.mockResolvedValue({ data: overview, error: null });
    api.sample.mockResolvedValue({ data: { agent_id: 'sample-2' }, error: null });
    render(<ImprovementsPage />);
    await waitFor(() => screen.getByTestId('improvements-agent-row'));
    expect(screen.queryByTestId('improvements-empty')).toBeNull();
    fireEvent.click(screen.getByTestId('improvements-sample'));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/agents/sample-2/improvements'));
  });

  it('explains the missing permission', () => {
    perms.caps = [];
    render(<ImprovementsPage />);
    expect(screen.getByTestId('improvements-no-access')).toHaveTextContent('improvements.view');
  });
});
