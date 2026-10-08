// Turns a Pipeline Surgeon JSON-Patch into lines a person can read.

export interface PatchOp {
  op: string;
  path: string;
  value?: unknown;
}

export interface PatchChange {
  op: string;
  where: string;
  before: string;
  after: string;
}

export function readPointer(doc: unknown, pointer: string): unknown {
  let cur: unknown = doc;
  for (const raw of pointer.split('/').slice(1)) {
    const key = raw.replace(/~1/g, '/').replace(/~0/g, '~');
    if (cur == null || typeof cur !== 'object') return undefined;
    cur = (cur as Record<string, unknown>)[key];
  }
  return cur;
}

export function shortJson(v: unknown, max = 160): string {
  if (v === undefined) return '(not set)';
  const t = JSON.stringify(v) ?? String(v);
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

const NODE_PATH = /^\/pipeline_config\/nodes\/(\d+|-)(\/.*)?$/;

export function describePatch(jsonPatch: unknown, dslBefore: unknown): PatchChange[] {
  const ops = Array.isArray(jsonPatch) ? (jsonPatch as PatchOp[]) : [];
  return ops
    .filter((o) => o && (o.op === 'replace' || o.op === 'add'))
    .map((o) => {
      const m = NODE_PATH.exec(o.path || '');
      const sub = m?.[2];
      if (!m || !sub) {
        // a whole step added or replaced
        const id = (o.value as { id?: string } | undefined)?.id;
        return { op: o.op, where: id ? `new step ${id}` : 'new step', before: '(none)', after: shortJson(o.value) };
      }
      const node = readPointer(dslBefore, `/pipeline_config/nodes/${m[1]}`) as { id?: string } | undefined;
      return {
        op: o.op,
        where: `${node?.id || `step ${m[1]}`} · ${sub.slice(1).split('/').join('.')}`,
        before: shortJson(readPointer(dslBefore, o.path)),
        after: shortJson(o.value),
      };
    });
}
