import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api-client', () => ({ apiFetch, API_URL: 'http://test' }));
vi.mock('@/components/ui/ResponsiveModal', () => ({
  default: ({ open, children }: { open: boolean; children: React.ReactNode }) => (open ? <div>{children}</div> : null),
}));

import { CognifyStartDialog } from '@/components/knowledge/CognifyStartDialog';
import { KnowledgeSearchSettings } from '@/components/knowledge/KnowledgeSearchSettings';
import { cognifyBody, cognifyProblem } from '@/lib/knowledge-settings';
import { followRun } from '../../../../wingman/web/src/app/ops/follow-run';

const ESTIMATE = {
  documents: 3,
  chunks: 240,
  chunks_total: 1200,
  model: 'claude-haiku-4-5',
  estimated_usd: 0.42,
  max_cost_usd: 5,
  note: 'Chunks already in the ledger are skipped.',
};

afterEach(() => {
  cleanup();
  apiFetch.mockReset();
});

function bodies() {
  return apiFetch.mock.calls.map((c) => JSON.parse(c[1].body));
}

describe('CognifyStartDialog', () => {
  beforeEach(() => {
    apiFetch.mockImplementation(async (_url: string, init: { body: string }) =>
      JSON.parse(init.body).dry_run ? { data: ESTIMATE } : { data: { job_id: 'j' } },
    );
  });

  it('shows the cost from a dry run and asks again when the selection changes', async () => {
    render(<CognifyStartDialog kbId="k" open onClose={vi.fn()} onStarted={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('cognify-estimate')).toHaveTextContent('About $0.42'));
    expect(screen.getByTestId('cognify-estimate')).toHaveTextContent('240 of 1,200 chunks in 3 documents');
    expect(bodies()[0]).toEqual({ selection: 'all', dry_run: true });

    fireEvent.change(screen.getByTestId('cognify-selection'), { target: { value: 'sample' } });
    fireEvent.change(screen.getByTestId('cognify-percent'), { target: { value: '25' } });
    await waitFor(() => expect(bodies().at(-1)).toEqual({ selection: 'sample', sample_rate: 0.25, dry_run: true }));
  });

  it('starts with the chosen budget and selection, without dry run', async () => {
    const onClose = vi.fn();
    const onStarted = vi.fn();
    render(<CognifyStartDialog kbId="k" open onClose={onClose} onStarted={onStarted} />);
    fireEvent.change(screen.getByTestId('cognify-selection'), { target: { value: 'salient' } });
    fireEvent.change(screen.getByTestId('cognify-job-budget'), { target: { value: '2.5' } });
    fireEvent.change(screen.getByTestId('cognify-max-per-doc'), { target: { value: '50' } });
    fireEvent.click(screen.getByTestId('cognify-start'));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(apiFetch.mock.calls.at(-1)?.[0]).toBe('/api/knowledge-engines/k/cognify');
    expect(bodies().at(-1)).toEqual({ selection: 'salient', sample_rate: 0.2, max_cost_usd: 2.5, max_chunks_per_doc: 50 });
    expect(onClose).toHaveBeenCalled();
  });

  it('warns when the estimate is over the budget', async () => {
    render(<CognifyStartDialog kbId="k" open onClose={vi.fn()} onStarted={vi.fn()} />);
    fireEvent.change(screen.getByTestId('cognify-job-budget'), { target: { value: '0.10' } });
    await waitFor(() => expect(screen.getByTestId('cognify-over-budget')).toHaveTextContent('stops at $0.10'));
  });

  it('keeps the dialog open and shows why a start was refused', async () => {
    apiFetch.mockImplementation(async (_url: string, init: { body: string }) =>
      JSON.parse(init.body).dry_run ? { data: ESTIMATE } : { data: null, error: 'Cognify is already running on this collection.' },
    );
    const onClose = vi.fn();
    render(<CognifyStartDialog kbId="k" open onClose={onClose} onStarted={vi.fn()} />);
    fireEvent.click(screen.getByTestId('cognify-start'));
    await waitFor(() => expect(screen.getByTestId('cognify-error')).toHaveTextContent('already running'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('refuses bad values before asking the server', () => {
    const good = { budget: '', selection: 'all' as const, percent: '20', maxPerDoc: '' };
    expect(cognifyProblem(good)).toBeNull();
    expect(cognifyProblem({ ...good, budget: '-1' })).toMatch(/budget/);
    expect(cognifyProblem({ ...good, selection: 'sample', percent: '0' })).toMatch(/share/);
    expect(cognifyProblem({ ...good, maxPerDoc: '1.5' })).toMatch(/whole number/);
    expect(cognifyBody(good)).toEqual({ selection: 'all' });
  });
});

describe('KnowledgeSearchSettings', () => {
  it('saves the language and offers to build a deferred index', async () => {
    apiFetch.mockResolvedValue({ data: {} });
    const onChanged = vi.fn();
    render(<KnowledgeSearchSettings kbId="k" language="simple" indexMode="deferred" canEdit onChanged={onChanged} />);
    fireEvent.change(screen.getByTestId('kb-language'), { target: { value: 'german' } });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(apiFetch.mock.calls[0][0]).toBe('/api/knowledge-bases/k');
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ search_language: 'german' });
    fireEvent.click(screen.getByTestId('kb-index-build'));
    await waitFor(() => expect(apiFetch.mock.calls[1][0]).toBe('/api/knowledge-bases/k/index/build'));
  });

  it('shows the reason the server refuses to defer', async () => {
    apiFetch.mockResolvedValue({ data: null, error: 'The index can only be deferred while a collection is empty.' });
    render(<KnowledgeSearchSettings kbId="k" language="simple" indexMode="shared" canEdit onChanged={vi.fn()} />);
    fireEvent.click(screen.getByTestId('kb-index-defer'));
    await waitFor(() => expect(screen.getByTestId('kb-search-settings-error')).toHaveTextContent('while a collection is empty'));
  });

  it('is read only for someone who can not edit', () => {
    render(<KnowledgeSearchSettings kbId="k" language="english" indexMode="deferred" canEdit={false} onChanged={vi.fn()} />);
    expect(screen.getByTestId('kb-language')).toBeDisabled();
    expect(screen.queryByTestId('kb-index-build')).toBeNull();
  });
});

describe('followRun for Wingman Ops', () => {
  const sleep = async () => {};
  const answer = (data: object, ok = true, status = 200) => ({ ok, status, json: async () => ({ data }) }) as Response;

  it('keeps polling while the run is live and returns its snapshot', async () => {
    const get = vi.fn()
      .mockResolvedValueOnce(answer({ status: 'running' }))
      .mockResolvedValueOnce(answer({ status: 'completed', snapshot: { narrative: 'calm' } }));
    expect(await followRun('r', { get, sleep })).toEqual({ snapshot: { narrative: 'calm' } });
    expect(get).toHaveBeenCalledTimes(2);
    expect(get).toHaveBeenLastCalledWith('/api/wingman/ops/result/r');
  });

  it('turns a failed run into its reason', async () => {
    const get = vi.fn().mockResolvedValue(answer({ status: 'failed', error_message: 'AIS feed refused' }));
    expect(await followRun('r', { get, sleep })).toEqual({ error: 'AIS feed refused' });
  });

  it('reports when the result can not be read at all', async () => {
    const get = vi.fn().mockResolvedValue(answer({}, false, 502));
    const out = await followRun('r', { get, sleep, maxMisses: 2 });
    expect(out.error).toContain('HTTP 502');
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('gives up with a message when the run outlasts the wait', async () => {
    const get = vi.fn().mockResolvedValue(answer({ status: 'running' }));
    const out = await followRun('r', { get, sleep, intervalMs: 1, maxWaitMs: 3 });
    expect(out.error).toContain('still running');
  });
});
