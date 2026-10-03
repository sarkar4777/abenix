import { describe, it, expect } from 'vitest';
import { deserializeConfig, serializeConfig, validatePipeline } from '@/components/builder/pipeline/pipelineUtils';

const config: any = {
  nodes: [
    { id: 'feed', tool_name: 'current_time', label: 'Feed', arguments: {}, depends_on: [] },
    { id: 'planner', type: 'agent', agent_slug: 'grid-dispatch-planner', label: 'Planner', input: 'Plan {{feed.result}}', depends_on: ['feed'] },
  ],
  edges: [],
};

describe('agent nodes in the pipeline builder', () => {
  it('loads a type: agent node as an agent step with its input', () => {
    const { steps } = deserializeConfig(config) as any;
    const planner = steps.find((s: any) => s.id === 'planner');
    expect(planner.toolName).toBe('agent_step');
    expect(planner.agentSlug).toBe('grid-dispatch-planner');
    expect(planner.arguments.input_message).toBe('Plan {{feed.result}}');
  });

  it('round trips without losing the agent or its input', () => {
    const { steps, edges } = deserializeConfig(config) as any;
    const out: any = serializeConfig(steps, edges || [], { x: 0, y: 0, zoom: 1 });
    const planner = out.nodes.find((n: any) => n.id === 'planner');
    expect(planner.tool_name).toBe('agent_step');
    expect(planner.agent_slug).toBe('grid-dispatch-planner');
    expect(planner.type).toBe('agent');
    expect(planner.arguments.input_message).toBe('Plan {{feed.result}}');
  });

  it('does not report the agent step as an error', () => {
    const { steps } = deserializeConfig(config) as any;
    const result: any = validatePipeline(steps, []);
    expect((result.errors || []).filter((e: any) => e.node_id === 'planner')).toEqual([]);
  });
});
