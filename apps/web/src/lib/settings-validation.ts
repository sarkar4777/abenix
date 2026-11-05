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

export type DlpMode = 'detect' | 'mask' | 'block';

export const DLP_MODES: { value: DlpMode; label: string; help: string }[] = [
  { value: 'detect', label: 'Detect', help: 'Personal data is logged. Messages and answers go through unchanged.' },
  { value: 'mask', label: 'Mask', help: 'Personal data is replaced with a label such as [EMAIL_MASKED] before the model sees it. Answers are masked the same way.' },
  { value: 'block', label: 'Block', help: 'A message with personal data is refused with a plain reason. An answer with personal data is withheld and replaced with a plain message.' },
];

export const RETENTION_FIELDS = [
  { key: 'execution_retention_days', label: 'Run history', min: 7 },
  { key: 'message_retention_days', label: 'Messages', min: 30 },
  { key: 'audit_log_retention_days', label: 'Audit logs', min: 365 },
] as const;

export type RetentionKey = (typeof RETENTION_FIELDS)[number]['key'];

// the scanner runs Python regex and quietly skips a bad one, so catch it before saving
export function dlpPatternProblem(name: string, regex: string, otherNames: string[] = []): string | null {
  const n = name.trim();
  if (!n) return 'Give this pattern a name';
  if (!/^[A-Za-z0-9_ ]+$/.test(n)) return 'Use letters, numbers and spaces in the name';
  if (otherNames.some((o) => o.trim().toLowerCase() === n.toLowerCase())) return 'Another pattern has this name';
  if (!regex.trim()) return 'Type a regular expression';
  const jsForm = regex.replace(/^\(\?[aiLmsux]+\)/, '').replace(/\(\?P</g, '(?<').replace(/\(\?P=(\w+)\)/g, '\\k<$1>');
  try {
    new RegExp(jsForm);
  } catch {
    return 'This is not a valid regular expression';
  }
  return null;
}
