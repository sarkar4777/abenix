import { describe, expect, it } from 'vitest';
import { readableInput } from '@/lib/readable-input';

describe('readableInput', () => {
  it('shows the words of a pipeline input envelope', () => {
    expect(readableInput('{"message": "Which plant is exposed?"}')).toBe('Which plant is exposed?');
  });

  it('keeps the words of a preview cut short', () => {
    expect(readableInput('{"message": "Score these suppliers: {\\"suppliers\\":[{\\"name')).toBe('Score these suppliers: {"suppliers":[{"name');
  });

  it('names extra fields instead of dumping them', () => {
    expect(readableInput('{"message": "Go", "context": {"a": 1, "b": 2}, "dry_run": true}')).toBe('Go · context: 2 fields · dry run: true');
  });

  it('leaves plain text and other JSON alone', () => {
    expect(readableInput('Convert 30 C to kelvin')).toBe('Convert 30 C to kelvin');
    expect(readableInput('[1, 2]')).toBe('[1, 2]');
    expect(readableInput('{}')).toBe('{}');
    expect(readableInput(null)).toBe('');
  });
});
