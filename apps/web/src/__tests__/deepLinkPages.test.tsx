import { render, screen, waitFor } from '@testing-library/react';

const state: { query: string; data: Record<string, unknown> } = { query: '', data: {} };
const replace = vi.fn();

vi.mock('next/navigation', () => ({
  usePathname: () => '/x',
  useRouter: () => ({ push: vi.fn(), replace, prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(state.query),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/hooks/useApi', () => ({
  useApi: (path: string | null) => ({
    data: path ? (Object.entries(state.data).find(([k]) => path.startsWith(k))?.[1] ?? null) : null,
    error: null,
    isLoading: false,
    meta: null,
    mutate: vi.fn(),
  }),
}));
vi.mock('@/lib/api-client', () => ({
  apiFetch: vi.fn(async (path: string) => ({ data: path.endsWith('/kb-1') ? { id: 'kb-1', name: 'Site manuals', documents: [] } : null, error: path.endsWith('/kb-1') ? null : 'not found' })),
  ApiError: class extends Error {},
  API_URL: '',
}));
vi.mock('@/components/observability/InvocationsTable', () => ({ default: () => null }));
vi.mock('@/components/share/ResourceShareDialog', () => ({ default: () => null }));
vi.mock('@/components/ui/ResponsiveModal', () => ({ default: () => null }));

import CodeRunnerPage from '@/app/(app)/code-runner/page';
import MLModelsPage from '@/app/(app)/ml-models/page';
import KnowledgePage from '@/app/(app)/knowledge/page';

const asset = (id: string, name: string) => ({
  id, name, description: null, source_type: 'zip', source_git_url: null, source_ref: null, file_size_bytes: 10,
  detected_language: 'python', detected_version: '3.12', detected_package_manager: null, detected_entrypoint: null,
  suggested_image: null, suggested_build_command: null, suggested_run_command: null, analysis_notes: [],
  input_schema: null, output_schema: null, status: 'ready', error: null, last_test_input: null, last_test_output: null,
  last_test_ok: null, last_test_at: null,
});
const model = (id: string, name: string, version: string, is_active: boolean) => ({
  id, name, version, framework: 'sklearn', description: null, status: 'ready', is_active, file_size_bytes: 10,
  original_filename: 'm.joblib', input_schema: null, output_schema: null, training_metrics: null, tags: null,
  deployments: [], created_at: '2026-10-01T00:00:00Z',
});

const scrolled = vi.fn();
beforeAll(() => {
  Element.prototype.scrollIntoView = scrolled;
});

beforeEach(() => {
  scrolled.mockClear();
  state.query = '';
  state.data = {};
  replace.mockClear();
  localStorage.clear();
});

describe('deep links', () => {
  it('/code-runner?asset= opens that asset', async () => {
    state.data = { '/api/code-assets': [asset('c1', 'alpha'), asset('c2', 'bravo')] };
    state.query = 'asset=c2';
    render(<CodeRunnerPage />);
    await waitFor(() => expect(screen.getByRole('heading', { name: /bravo/ })).toBeInTheDocument());
    expect(screen.queryByTestId('code-deeplink-missing')).toBeNull();
    await waitFor(() => expect(scrolled).toHaveBeenCalled());
  });

  it('/code-runner?asset= with an unknown id says so', async () => {
    state.data = { '/api/code-assets': [asset('c1', 'alpha')] };
    state.query = 'asset=nope';
    render(<CodeRunnerPage />);
    expect(await screen.findByTestId('code-deeplink-missing')).toHaveTextContent('nope');
  });

  it('/ml-models?model= opens that model, by id or by name', async () => {
    state.data = { '/api/ml-models': [model('m1', 'churn', '1.0.0', false), model('m2', 'churn', '1.1.0', true)] };
    state.query = 'model=m1';
    const { unmount } = render(<MLModelsPage />);
    expect(await screen.findByTestId('ml-detail')).toHaveTextContent('v1.0.0');
    unmount();
    state.query = 'model=churn';
    render(<MLModelsPage />);
    expect(await screen.findByTestId('ml-detail')).toHaveTextContent('v1.1.0');
  });

  it('/knowledge?id= opens that knowledge base', async () => {
    state.data = { '/api/knowledge-bases': [] };
    state.query = 'id=kb-1';
    render(<KnowledgePage />);
    expect(await screen.findByText('Site manuals')).toBeInTheDocument();
    expect(screen.queryByTestId('kb-deeplink-missing')).toBeNull();
  });

  it('/knowledge?id= that cannot be opened says so', async () => {
    state.data = { '/api/knowledge-bases': [] };
    state.query = 'id=kb-gone';
    render(<KnowledgePage />);
    expect(await screen.findByTestId('kb-deeplink-missing')).toHaveTextContent('kb-gone');
  });
});
