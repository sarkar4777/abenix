export interface Labelled { group: string; node: string; name?: string | null; display_name?: string | null }

const nameOf = (a: Labelled) => (a.display_name || a.name || '').trim();

// asset names that appear in more than one group, by the name people see
export function repeatedNames(list: Labelled[]): Set<string> {
  const groups = new Map<string, Set<string>>();
  for (const a of list) {
    const n = (nameOf(a) || a.node).toLowerCase();
    if (!groups.has(n)) groups.set(n, new Set());
    groups.get(n)!.add(a.group);
  }
  return new Set(Array.from(groups.entries()).filter(([, g]) => g.size > 1).map(([n]) => n));
}

// group/asset whenever the name alone could mean two things
export function assetLabel(a: Labelled, repeated?: Set<string> | boolean): string {
  const name = nameOf(a);
  const shown = name || a.node;
  const twice = typeof repeated === 'boolean' ? repeated : !!repeated?.has(shown.toLowerCase());
  const path = twice ? `${a.group}/${a.node}` : a.node;
  if (!name || name === a.node) return twice ? path : a.node;
  return `${name} (${path})`;
}

// a template agent's name says which group its asset is in
export function agentAssetLabel(key: string, name?: string | null): string {
  const [group = '', node = ''] = key.split('/');
  const n = (name || '').trim();
  return n && n !== node ? `${n} (${group}/${node})` : `${group}/${node}`;
}
