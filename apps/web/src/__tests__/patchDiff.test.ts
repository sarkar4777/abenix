import { describePatch, readPointer } from '@/lib/patchDiff';

const before = {
  pipeline_config: {
    nodes: [
      { id: 'multiply', tool_name: 'calculator', arguments: { expression: '6 x 7' } },
      { id: 'announce', tool_name: 'llm_call', depends_on: ['multiply'] },
    ],
  },
};

describe('describePatch', () => {
  it('names the step and shows old and new value', () => {
    const out = describePatch(
      [{ op: 'replace', path: '/pipeline_config/nodes/0/arguments/expression', value: '6 * 7' }],
      before,
    );
    expect(out).toEqual([{ op: 'replace', where: 'multiply · arguments.expression', before: '"6 x 7"', after: '"6 * 7"' }]);
  });

  it('marks a field that was not set', () => {
    const [c] = describePatch([{ op: 'add', path: '/pipeline_config/nodes/1/on_error', value: 'continue' }], before);
    expect(c.where).toBe('announce · on_error');
    expect(c.before).toBe('(not set)');
  });

  it('treats a whole node as a new step', () => {
    const [c] = describePatch([{ op: 'add', path: '/pipeline_config/nodes/1', value: { id: 'check', tool_name: 'json_transformer' } }], before);
    expect(c.where).toBe('new step check');
    expect(c.before).toBe('(none)');
  });

  it('skips test ops and bad input', () => {
    expect(describePatch([{ op: 'test', path: '/pipeline_config/nodes/0/id', value: 'multiply' }], before)).toEqual([]);
    expect(describePatch(null, before)).toEqual([]);
  });

  it('reads escaped pointer keys', () => {
    expect(readPointer({ 'a/b': { '~c': 1 } }, '/a~1b/~0c')).toBe(1);
  });
});
