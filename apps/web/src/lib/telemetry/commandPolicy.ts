// device_command's policy, kept in tool_config.device_command.parameter_defaults.policy

export type ApprovalMode = 'always' | 'tier' | 'never';
export type Tier = 'low' | 'medium' | 'high' | 'critical';

export interface CommandPolicy {
  assets: string[];
  signals: string[];
  approval: ApprovalMode;
  tier: Tier;
  rate_per_minute: number;
  confirm_timeout_ms: number;
}

export interface Target {
  key: string;
  group: string;
  node: string;
  device: string;
  name: string;
  type?: string | null;
  tags?: string[];
  online?: boolean | null;
  parts?: string[];
}

export interface TargetSignal {
  signal: string;
  part: string;
  value: unknown;
  type: string | null;
  writable: boolean;
}

export const TIERS: Tier[] = ['low', 'medium', 'high', 'critical'];

export const APPROVAL_MODES: Array<{ value: ApprovalMode; label: string; help: string }> = [
  { value: 'always', label: 'Always ask a person', help: 'Every command waits on Approvals until someone approves it. Start here.' },
  { value: 'tier', label: 'By risk tier', help: 'Your workspace rule for the tier you pick decides: run, ask first or block.' },
  { value: 'never', label: 'Never ask', help: 'Commands go out at once. Use it for safe, reversible signals only.' },
];

export function blankPolicy(): CommandPolicy {
  return { assets: [], signals: [], approval: 'always', tier: 'high', rate_per_minute: 6, confirm_timeout_ms: 3000 };
}

function list(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((x) => String(x ?? '').trim()).filter(Boolean);
  if (typeof v === 'string') return v.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
  return [];
}

export function readPolicy(raw: unknown): CommandPolicy {
  const b = blankPolicy();
  if (!raw || typeof raw !== 'object') return b;
  const r = raw as Record<string, unknown>;
  const mode = String(r.approval || '') as ApprovalMode;
  const tier = String(r.tier || '') as Tier;
  const num = (v: unknown, d: number) => (v === undefined || v === null || v === '' || Number.isNaN(Number(v)) ? d : Number(v));
  return {
    assets: list(r.assets),
    signals: list(r.signals),
    approval: (['always', 'tier', 'never'] as const).includes(mode) ? mode : b.approval,
    tier: TIERS.includes(tier) ? tier : b.tier,
    rate_per_minute: num(r.rate_per_minute, b.rate_per_minute),
    confirm_timeout_ms: num(r.confirm_timeout_ms, b.confirm_timeout_ms),
  };
}

/** Why a typed asset or signal pattern cannot be used, or null. Same rule as the API. */
export function patternProblem(s: string): string | null {
  const v = s.trim();
  if (!v) return null;
  if (v.length > 300) return 'Keep it under 300 characters.';
  if (/[\s#+]/.test(v)) return 'Patterns have no spaces, # or +.';
  if (!v.includes(':') && v.split('/').filter(Boolean).length > 3) return 'An asset key has at most three parts: group/asset/part.';
  return null;
}

export function policyProblems(p: CommandPolicy): Record<string, string> {
  const out: Record<string, string> = {};
  if (!p.assets.length) out.assets = 'Pick at least one asset. Until then every command is refused.';
  if (!p.signals.length) out.signals = 'Pick at least one signal. Until then every command is refused.';
  if (!Number.isInteger(p.rate_per_minute) || p.rate_per_minute < 1 || p.rate_per_minute > 600) out.rate_per_minute = 'From 1 to 600.';
  if (!Number.isInteger(p.confirm_timeout_ms) || p.confirm_timeout_ms < 0 || p.confirm_timeout_ms > 10000) out.confirm_timeout_ms = 'From 0 to 10000.';
  return out;
}

function words(items: string[]): string {
  if (!items.length) return 'nothing';
  if (items.length <= 4) return items.join(', ');
  return `${items.slice(0, 4).join(', ')} and ${items.length - 4} more`;
}

export function policySentence(p: CommandPolicy): string {
  if (!p.assets.length || !p.signals.length) {
    return 'No command policy yet, so device_command refuses every command. Pick assets and signals above.';
  }
  const ask = p.approval === 'always'
    ? 'A person approves every command first.'
    : p.approval === 'tier'
      ? `The workspace rule for ${p.tier} risk decides whether a person approves.`
      : 'Commands go out without asking.';
  return `May set ${words(p.signals)} on ${words(p.assets)}. ${ask} At most ${p.rate_per_minute} a minute.`;
}

/** Whether a key matches a pattern, the way the API checks it. */
export function assetMatches(pattern: string, key: string, tags: string[] = [], type?: string | null): boolean {
  const p = pattern.trim();
  const low = p.toLowerCase();
  if (low.startsWith('tag:')) return tags.map((t) => t.toLowerCase()).includes(low.slice(4).trim());
  if (low.startsWith('type:')) return (type || '') === low.slice(5).trim();
  let segs = p.replace(/^\/+|\/+$/g, '').split('/');
  if (segs.length === 1) segs = [segs[0], '*', '*'];
  else if (segs.length === 2) segs = [segs[0], segs[1], '*'];
  else if (segs.length > 3) return false;
  const parts = key.split('/');
  while (parts.length < 3) parts.push('');
  const glob = (s: string) => new RegExp(`^${s.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')}$`);
  return segs.every((s, i) => glob(s).test(parts[i] || ''));
}
