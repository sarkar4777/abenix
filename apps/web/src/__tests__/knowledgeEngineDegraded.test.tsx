import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'k' }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock('next/link', () => ({ default: ({ href, children }: any) => <a href={href}>{children}</a> }));
vi.mock('@/lib/api-client', () => ({ apiFetch: vi.fn(async () => ({ data: null })), API_URL: 'http://test' }));
vi.mock('@/lib/fetch-all-agents', () => ({ fetchAllAgents: vi.fn(async () => ({ agents: [] })) }));
vi.mock('@/components/layout/PageHeader', () => ({ default: ({ primaryAction, children }: any) => <div>{primaryAction}{children}</div> }));
vi.mock('@/components/ui/ResponsiveModal', () => ({ default: ({ open, children }: any) => (open ? <div>{children}</div> : null) }));
vi.mock('@/components/knowledge/EmbeddingModelPanel', () => ({ EmbeddingModelPanel: () => null }));
vi.mock('@/components/knowledge/ConnectorsPanel', () => ({ ConnectorsPanel: () => null }));

import KnowledgeEnginePage from '@/app/(app)/knowledge/[id]/engine/page';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function stubApi(search: object) {
  const fetchMock = vi.fn(async (url: string) => {
    const data = url.endsWith('/search')
      ? search
      : url.endsWith('/cognify-jobs') || url.endsWith('/agents')
        ? []
        : url.endsWith('/graph-stats')
          ? { entity_count: 0, relationship_count: 0, entities_by_type: {}, top_entities: [], neo4j_available: true, doc_count: 1 }
          : { id: 'k', name: 'Manuals', search_language: 'french', index_mode: 'shared', can_edit: true };
    return { ok: true, status: 200, json: async () => ({ data }) } as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  localStorage.setItem('access_token', 't');
}

describe('the search playground', () => {
  it('says when the search fell back to keywords', async () => {
    stubApi({ results: [], mode_used: 'keyword', degraded: 'Matched by keywords because the embedding provider is unavailable', vector_count: 0, graph_count: 0, entities_found: [], latency_ms: 3 });
    render(<KnowledgeEnginePage />);
    const input = await screen.findByTestId('kb-search-input');
    fireEvent.change(input, { target: { value: 'swing radius' } });
    fireEvent.click(screen.getByTestId('kb-search-button'));
    await waitFor(() => expect(screen.getByTestId('kb-search-degraded')).toHaveTextContent('embedding provider is unavailable'));
  });

  it('says nothing extra on a normal search', async () => {
    stubApi({ results: [], mode_used: 'hybrid', degraded: null, vector_count: 0, graph_count: 0, entities_found: [], latency_ms: 3 });
    render(<KnowledgeEnginePage />);
    fireEvent.change(await screen.findByTestId('kb-search-input'), { target: { value: 'q' } });
    fireEvent.click(screen.getByTestId('kb-search-button'));
    await waitFor(() => expect(screen.getByTestId('kb-search-empty')).toBeInTheDocument());
    expect(screen.queryByTestId('kb-search-degraded')).toBeNull();
  });

  it('opens the start dialog from Run Cognify and shows the search settings', async () => {
    stubApi({ results: [] });
    render(<KnowledgeEnginePage />);
    expect(await screen.findByTestId('kb-search-settings')).toBeInTheDocument();
    expect(screen.getByTestId('kb-language')).toHaveValue('french');
    expect(screen.queryByTestId('cognify-start')).toBeNull();
    fireEvent.click(screen.getByTestId('run-cognify'));
    expect(await screen.findByTestId('cognify-start')).toBeInTheDocument();
  });
});
