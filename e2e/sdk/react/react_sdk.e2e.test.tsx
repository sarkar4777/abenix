// React SDK against the live API: renders AgentChat and useAgentStream in
// jsdom with the real fetch, no mocks. scripts/sdk-e2e.sh runs it.
import { readFileSync, existsSync } from 'node:fs';
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, renderHook, act } from '@testing-library/react';
import { Abenix } from '@abenix/sdk';
import { AgentChat, useAgentStream } from '@abenix/react';

const BASE = process.env.ABENIX_URL || 'http://localhost:8000';
const KEY_FILE = process.env.SDK_KEY_FILE || `${__dirname}/../.sdk-key`;
const SLUG = process.env.SDK_E2E_AGENT || 'sdk-e2e-assistant';
const key = (process.env.ABENIX_API_KEY || (existsSync(KEY_FILE) ? readFileSync(KEY_FILE, 'utf8') : '')).trim();

beforeAll(async () => {
  expect(key, 'no API key, run e2e/sdk/mint_key.spec.ts first').toMatch(/^af_/);
  const forge = new Abenix({ apiKey: key, baseUrl: BASE });
  if (!(await forge.agents.bySlug(SLUG))) {
    await forge.agents.create({
      name: 'SDK e2e assistant',
      slug: SLUG,
      description: 'Answers short questions. Used by the SDK end to end suites.',
      system_prompt: 'You answer in one short sentence. No preamble.',
      model_config: { model: 'claude-haiku-4-5-20251001', temperature: 0, max_tokens: 200, tools: [] },
    });
  }
});

afterEach(() => cleanup());

describe('AgentChat', () => {
  it('resolves the agent, streams a reply and reports the run', async () => {
    const seen: Array<{ role: string; content: string; executionId?: string }> = [];
    const costs: number[] = [];
    const errors: string[] = [];
    render(
      <AgentChat
        apiKey={key}
        baseUrl={BASE}
        agentSlug={SLUG}
        onMessage={(m) => seen.push(m)}
        onCostUpdate={(c) => costs.push(c.outputTokens)}
        onError={(e) => errors.push(e)}
      />,
    );
    expect(screen.getByText('Connecting to the agent...')).toBeTruthy();
    const box = screen.getByLabelText('Message') as HTMLInputElement;
    await waitFor(() => expect(box.disabled).toBe(false), { timeout: 30_000 });
    expect(screen.getByText(/Ask SDK e2e assistant something to start/)).toBeTruthy();

    fireEvent.change(box, { target: { value: 'What colour is a clear daytime sky? One word.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy();

    await waitFor(
      () => {
        const replies = document.querySelectorAll('[data-role="assistant"][data-streaming="false"]');
        expect(replies.length).toBe(1);
      },
      { timeout: 180_000 },
    );
    const reply = document.querySelector('[data-role="assistant"]')!.textContent || '';
    expect(reply.toLowerCase()).toContain('blue');
    expect(errors).toEqual([]);
    expect(costs.length).toBe(1);
    const assistant = seen.find((m) => m.role === 'assistant');
    expect(assistant?.executionId).toBeTruthy();

    const run = await new Abenix({ apiKey: key, baseUrl: BASE }).executions.get(assistant!.executionId!);
    expect(['completed', 'running']).toContain(run.status);
  });

  it('says so when the slug does not exist', async () => {
    render(<AgentChat apiKey={key} baseUrl={BASE} agentSlug="no-such-agent-sdk-e2e" />);
    const alert = await screen.findByRole('alert', {}, { timeout: 30_000 });
    expect(alert.textContent).toContain('no-such-agent-sdk-e2e');
    expect((screen.getByLabelText('Message') as HTMLInputElement).disabled).toBe(true);
  });

  it('shows the platform error for a bad key', async () => {
    render(<AgentChat apiKey="af_not_a_real_key" baseUrl={BASE} agentSlug={SLUG} />);
    const alert = await screen.findByRole('alert', {}, { timeout: 30_000 });
    expect(alert.textContent?.length).toBeGreaterThan(0);
  });
});

describe('useAgentStream', () => {
  it('drives a conversation with a shared client', async () => {
    const client = new Abenix({ apiKey: key, baseUrl: BASE });
    const { result } = renderHook(() => useAgentStream({ client, agentSlug: SLUG }));
    await waitFor(() => expect(result.current.agentState).toBe('ready'), { timeout: 30_000 });
    await act(async () => {
      await result.current.send('What is 12 times 12? Digits only.');
    });
    const [user, reply] = result.current.messages;
    expect(user.role).toBe('user');
    expect(reply.content).toContain('144');
    expect(reply.isStreaming).toBe(false);
    expect(reply.executionId).toBeTruthy();
    expect(result.current.error).toBeNull();
    act(() => result.current.reset());
    expect(result.current.messages).toEqual([]);
  });
});
