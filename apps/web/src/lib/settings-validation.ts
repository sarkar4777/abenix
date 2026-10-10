// a retention field may hold half-typed text, it is checked rather than clamped
export function retentionProblem(raw: string, min: number): string | null {
  if (!/^\d+$/.test(raw.trim())) return 'Type a whole number of days';
  if (parseInt(raw, 10) < min) return `Use ${min} days or more`;
  return null;
}

// blank means no limit, otherwise a non-negative number
export function quotaProblem(raw: string, whole: boolean): string | null {
  const v = raw.trim();
  if (!v) return null;
  const n = Number(v);
  if (!Number.isFinite(n)) return 'Type a number, or leave it blank';
  if (n < 0) return 'Cannot be negative';
  if (whole && !Number.isInteger(n)) return 'Use a whole number';
  return null;
}
