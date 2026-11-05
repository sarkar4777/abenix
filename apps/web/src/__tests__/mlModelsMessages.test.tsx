import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const state: { capabilities: string[]; models: unknown[] } = { capabilities: ['ml_models.upload_pickle'], models: [] };
const posted: { fail?: unknown } = {};

vi.mock('next/navigation', () => ({
  usePathname: () => '/ml-models',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams('model=m1'),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/hooks/useApi', () => ({
  useApi: (path: string | null) => ({ data: path === '/api/ml-models' ? state.models : null, error: null, isLoading: false, meta: null, mutate: vi.fn() }),
}));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => ({ perms: { capabilities: state.capabilities }, loading: false }) };
});
vi.mock('@/lib/api-client', async (orig) => {
  const actual = await orig<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    apiFetch: vi.fn(async () => {
      if (posted.fail) throw posted.fail;
      return { data: null, error: null };
    }),
  };
});
vi.mock('@/components/observability/InvocationsTable', () => ({ default: () => null }));
vi.mock('@/components/share/ResourceShareDialog', () => ({ default: () => null }));
vi.mock('@/stores/toastStore', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

import MLModelsPage from '@/app/(app)/ml-models/page';
import { ApiError } from '@/lib/api-client';

const model = (deployments: unknown[]) => ({
  id: 'm1', name: 'churn', version: '1.0.0', framework: 'sklearn', description: null, status: 'ready', status_message: null, is_active: true,
  file_size_bytes: 10, original_filename: 'churn.pkl', input_schema: null, output_schema: null, training_metrics: null, tags: [], deployments, created_at: '2026-01-01T00:00:00Z',
});

beforeEach(() => {
  posted.fail = undefined;
  state.capabilities = ['ml_models.upload_pickle'];
  state.models = [model([])];
  Element.prototype.scrollIntoView = vi.fn();
});

describe('ML Models messages', () => {
  it('shows why a Kubernetes deployment failed', async () => {
    state.models = [model([{ id: 'd1', deployment_type: 'k8s', status: 'failed', endpoint_url: null, config: { error: 'Pod cannot start. ImagePullBackOff. Back-off pulling image' } }])];
    render(<MLModelsPage />);
    expect(await screen.findByTestId('ml-deployment-error')).toHaveTextContent('Pod cannot start. ImagePullBackOff.');
  });

  it('says plainly when a failed deployment came back with no reason', async () => {
    state.models = [model([{ id: 'd1', deployment_type: 'k8s', status: 'failed', endpoint_url: null }])];
    render(<MLModelsPage />);
    expect(await screen.findByTestId('ml-deployment-error')).toHaveTextContent('the server gave no reason');
  });

  it('warns before a pickle upload the person may not make', async () => {
    state.capabilities = ['agents.view'];
    const { container } = render(<MLModelsPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['x'], 'churn.pkl')] } });
    expect(await screen.findByText(/Upload pickle models permission/)).toBeInTheDocument();
    expect(screen.getByTestId('ml-upload-submit')).toBeDisabled();
  });

  it('allows an ONNX upload without that permission', async () => {
    state.capabilities = ['agents.view'];
    const { container } = render(<MLModelsPage />);
    fireEvent.change(container.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [new File(['x'], 'churn.onnx')] } });
    await waitFor(() => expect(screen.getByTestId('ml-upload-submit')).toBeEnabled());
    expect(screen.queryByText(/Upload pickle models permission/)).toBeNull();
  });

  it('shows the 403 words from the API on upload', async () => {
    const words = 'This needs Upload pickle models. Or export the model to ONNX and upload the .onnx file, which anyone can do.';
    posted.fail = new ApiError({ message: words, code: 403, error_code: 'MISSING_PERMISSION' });
    const { container } = render(<MLModelsPage />);
    fireEvent.change(container.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [new File(['x'], 'churn.pkl')] } });
    await waitFor(() => expect(screen.getByTestId('ml-upload-submit')).toBeEnabled());
    fireEvent.click(screen.getByTestId('ml-upload-submit'));
    expect(await screen.findByText(words)).toBeInTheDocument();
  });

  it('names the ONNX need when Explain is refused', async () => {
    posted.fail = new ApiError({ message: 'Explain is only available for ONNX models on this tenant.', code: 422, error_code: 'EXPLAIN_NEEDS_ONNX' });
    render(<MLModelsPage />);
    fireEvent.click(await screen.findByTestId('ml-explain'));
    expect(await screen.findByTestId('ml-explain-needs-onnx')).toHaveTextContent('Explain needs an ONNX model');
    expect(screen.getByText(/Explain is only available for ONNX models/)).toBeInTheDocument();
  });
});
