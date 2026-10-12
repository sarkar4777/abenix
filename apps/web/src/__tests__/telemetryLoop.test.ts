import { describe, expect, it } from 'vitest';
import { assetMatches, patternProblem, policyProblems, policySentence, readPolicy } from '@/lib/telemetry/commandPolicy';
import { AGENT_TEMPLATES, buildFromTemplate, templateById, templateHref } from '@/lib/telemetry/agentTemplates';
import { answeringSteps, stepRefProblem, type Action } from '@/components/telemetry-rules/lib';
import { confirmApproveText, needsApproveConfirm } from '@/lib/approvalText';

describe('device_command policy', () => {
  it('reads a stored policy with safe defaults', () => {
    const p = readPolicy(undefined);
    expect(p.approval).toBe('always');
    expect(policyProblems(p).assets).toMatch(/Pick at least one asset/);
    expect(policySentence(p)).toMatch(/refuses every command/);
    const q = readPolicy({ assets: 'g/ex1\ntag:haul', signals: ['Mode/Set'], approval: 'tier', tier: 'critical', rate_per_minute: '3' });
    expect(q.assets).toEqual(['g/ex1', 'tag:haul']);
    expect(q.tier).toBe('critical');
    expect(q.rate_per_minute).toBe(3);
    expect(policyProblems(q)).toEqual({});
    expect(policySentence(q)).toBe('May set Mode/Set on g/ex1, tag:haul. The workspace rule for critical risk decides whether a person approves. At most 3 a minute.');
  });

  it('flags bad patterns and limits in plain words', () => {
    expect(patternProblem('a b')).toMatch(/no spaces/);
    expect(patternProblem('a/b/c/d')).toMatch(/at most three parts/);
    expect(patternProblem('tag:north pit')).toMatch(/no spaces/);
    expect(patternProblem('groundwork/ipc-*')).toBeNull();
    expect(policyProblems({ ...readPolicy({ assets: ['a/b'], signals: ['s'] }), rate_per_minute: 0 }).rate_per_minute).toBe('From 1 to 600.');
  });

  it('matches keys the way the API does', () => {
    expect(assetMatches('groundwork/ipc-ex1', 'groundwork/ipc-ex1/safety')).toBe(true);
    expect(assetMatches('groundwork/ipc-ex1/engine', 'groundwork/ipc-ex1/safety')).toBe(false);
    expect(assetMatches('groundwork/ipc-*', 'groundwork/ipc-dz1/')).toBe(true);
    expect(assetMatches('tag:Haul', 'g/ht1/', ['haul'])).toBe(true);
    expect(assetMatches('type:vehicle', 'g/van/', [], 'vehicle')).toBe(true);
  });
});

describe('agent templates', () => {
  it('has the four templates with the loop tools', () => {
    expect(AGENT_TEMPLATES.map((t) => t.name)).toEqual(['Machine health watcher', 'Fleet dispatcher', 'Anomaly triage', 'Shift reporter']);
    for (const t of AGENT_TEMPLATES) {
      expect(t.tools).toContain('asset_search');
      expect(t.prompt()).toMatch(/JSON object/);
      expect(t.tools.includes('device_command')).toBe(t.commands);
    }
  });

  it('builds a command agent with approval on and the asset in its policy', () => {
    const t = templateById('machine-health-watcher')!;
    const b = buildFromTemplate(t, { key: 'testbed/meter-1/plc', name: 'Meter 1' }, ['Setpoint']);
    expect(b.name).toBe('Machine health watcher for Meter 1');
    const pol = b.tool_config.device_command.parameter_defaults.policy as Record<string, unknown>;
    expect(pol).toMatchObject({ assets: ['testbed/meter-1'], signals: ['Setpoint'], approval: 'always' });
    expect(b.system_prompt).toContain('Meter 1 (key testbed/meter-1/plc)');
    expect(buildFromTemplate(templateById('anomaly-triage')!).tool_config).toEqual({});
    expect(templateHref('fleet-dispatcher', { key: 'g/ht1', name: 'HT1' })).toBe('/builder?template=fleet-dispatcher&asset=g%2Fht1&asset_name=HT1');
  });
});

describe('rule step chaining', () => {
  const steps: Action[] = [
    { kind: 'run', agent_id: 'a' },
    { kind: 'decision', key: 'k', facts: { sev: '{steps.1.output.severity}' } },
    { kind: 'command', signal: 'Mode/Set', value: '{steps.3.output}' },
  ];
  it('lists the earlier steps that answer', () => {
    expect(answeringSteps(steps, 0)).toEqual([]);
    expect(answeringSteps(steps, 2)).toEqual([{ n: 1, kind: 'run' }, { n: 2, kind: 'decision' }]);
  });
  it('refuses a reference to this step or a later one', () => {
    expect(stepRefProblem(steps[1], 1)).toBeNull();
    expect(stepRefProblem(steps[2], 2)).toMatch(/must name an earlier step/);
    expect(stepRefProblem({ kind: 'notify', message: 'x {{steps.1.output}}' }, 0)).toMatch(/this is the first/);
  });
});

describe('command approvals', () => {
  it('ask once more before sending', () => {
    const row = {
      id: 'a1',
      gate_kind: 'telemetry.command',
      payload: { command: { signal: 'Setpoint', value: 42, node: 'meter-1', device: 'plc' }, asset: { name: 'Meter 1' }, agent: { name: 'Watcher' }, reason: 'Load is low' },
    };
    expect(needsApproveConfirm(row)).toBe(true);
    const c = confirmApproveText(row);
    expect(c.title).toBe('Send Setpoint = 42 to Meter 1?');
    expect(c.body).toContain('Watcher asked because: Load is low.');
  });
});
