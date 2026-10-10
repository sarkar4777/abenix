import { describe, it, expect } from 'vitest';
import { deserializeConfig, serializeConfig, toolDisplayName } from '@/components/builder/pipeline/pipelineUtils';

const config: any = {
  nodes: [
    { id: 'mode', tool_name: 'decision_evaluate', arguments: { decision: 'gw.simplex.switch' }, depends_on: [] },
    { id: 'result', type: 'structured', depends_on: ['mode'], output: { mode: '{{mode.result}}', note: 'fixed' } },
  ],
  edges: [],
};

describe('structured nodes in the pipeline builder', () => {
  it('loads type: structured as the built-in output step with its output map', () => {
    const { steps } = deserializeConfig(config) as any;
    const result = steps.find((s: any) => s.id === 'result');
    expect(result.toolName).toBe('__structured__');
    expect(result.arguments).toEqual({ mode: '{{mode.result}}', note: 'fixed' });
  });

  it('saves it in the form the engine runs', () => {
    const { steps, edges } = deserializeConfig(config) as any;
    const out: any = serializeConfig(steps, edges || [], { x: 0, y: 0, zoom: 1 });
    const result = out.nodes.find((n: any) => n.id === 'result');
    expect(result.tool_name).toBe('__structured__');
    expect(result.arguments.mode).toBe('{{mode.result}}');
  });

  it('names built-in steps in words on the canvas', () => {
    expect(toolDisplayName('__structured__')).toBe('assemble output');
    expect(toolDisplayName('agent_step')).toBe('agent');
    expect(toolDisplayName('decision_evaluate')).toBe('decision_evaluate');
  });
});
