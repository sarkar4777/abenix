// Small helpers the sidebar pages share, kept here so they can be tested.

export const MODERATION_SOURCE_LABEL: Record<string, string> = {
  api_vet: 'Test on this page',
  pre_llm: 'Input, before the model',
  post_llm: 'Model answer',
  tool_output: 'Tool output',
  on_tool_output: 'Tool output',
  moderation_vet: 'moderation_vet tool',
};

// "custom:0" is the first custom pattern of the policy, say which one
export function moderationCategoryLabel(cat: string, patterns?: string[]): string {
  const m = /^custom:(\d+)$/.exec(cat);
  if (!m) return cat;
  const i = Number(m[1]);
  const pat = patterns?.[i];
  return pat ? `custom pattern ${i + 1} (${pat})` : `custom pattern ${i + 1}`;
}

// five space separated fields, the shape the scheduler takes
export function looksLikeCron(expr: string): boolean {
  return /^\S+(\s+\S+){4}$/.test(expr.trim());
}

// the API sends {message, code}, older routes a bare string
export function apiErrorText(e: unknown, fallback: string): string {
  if (typeof e === 'string') return e;
  if (e && typeof e === 'object' && typeof (e as { message?: unknown }).message === 'string') {
    return (e as { message: string }).message;
  }
  return fallback;
}

// text typed into a chip box but not yet added still counts
export function withPending(items: string[], pending: string): string[] {
  const v = pending.trim();
  return v && !items.includes(v) ? [...items, v] : items;
}
