export interface SchemaParam {
  name: string;
  type: string;
  required: boolean;
  description: string;
  defaultValue?: unknown;
  hasDefault: boolean;
  enumValues?: unknown[];
}

type Json = Record<string, unknown>;

function asObj(v: unknown): Json | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : null;
}

export function typeLabel(prop: Json): string {
  const t = prop.type;
  if (Array.isArray(t)) return t.filter((x) => x !== 'null').join(' or ') || 'any';
  if (t === 'array') {
    const items = asObj(prop.items);
    const inner = items ? typeLabel(items) : '';
    return inner && inner !== 'any' ? `array of ${inner}` : 'array';
  }
  if (typeof t === 'string') return t;
  if (Array.isArray(prop.enum)) return 'enum';
  const alts = (prop.anyOf || prop.oneOf) as unknown;
  if (Array.isArray(alts)) {
    return alts.map((a) => (asObj(a) ? typeLabel(a as Json) : 'any')).filter((x) => x !== 'null').join(' or ') || 'any';
  }
  return 'any';
}

export function schemaParams(schema: unknown): SchemaParam[] {
  const s = asObj(schema);
  const props = asObj(s?.properties);
  if (!props) return [];
  const required = new Set(Array.isArray(s?.required) ? (s!.required as string[]) : []);
  const out = Object.entries(props).map(([name, raw]) => {
    const p = asObj(raw) || {};
    return {
      name,
      type: typeLabel(p),
      required: required.has(name),
      description: typeof p.description === 'string' ? p.description : '',
      hasDefault: 'default' in p,
      defaultValue: p.default,
      enumValues: Array.isArray(p.enum) ? (p.enum as unknown[]) : undefined,
    };
  });
  // required first, schema order otherwise
  return out.sort((a, b) => Number(b.required) - Number(a.required));
}

function exampleValue(name: string, prop: Json): unknown {
  if ('default' in prop) return prop.default;
  if (Array.isArray(prop.examples) && prop.examples.length) return prop.examples[0];
  if (Array.isArray(prop.enum) && prop.enum.length) return prop.enum[0];
  const t = Array.isArray(prop.type) ? prop.type.find((x) => x !== 'null') : prop.type;
  switch (t) {
    case 'integer':
    case 'number':
      return typeof prop.minimum === 'number' ? prop.minimum : 1;
    case 'boolean':
      return false;
    case 'array': {
      const items = asObj(prop.items);
      return items ? [exampleValue(name.replace(/s$/, ''), items)] : [];
    }
    case 'object': {
      const inner = asObj(prop.properties);
      if (!inner) return {};
      return buildExampleArgs(prop);
    }
    default:
      return `<${name}>`;
  }
}

// required params plus optional ones that carry a default; falls back to the first param
export function buildExampleArgs(schema: unknown): Record<string, unknown> {
  const s = asObj(schema);
  const props = asObj(s?.properties);
  if (!props) return {};
  const required = new Set(Array.isArray(s?.required) ? (s!.required as string[]) : []);
  const out: Record<string, unknown> = {};
  for (const [name, raw] of Object.entries(props)) {
    const p = asObj(raw) || {};
    if (required.has(name) || 'default' in p) out[name] = exampleValue(name, p);
  }
  if (!Object.keys(out).length) {
    const [first] = Object.entries(props);
    if (first) out[first[0]] = exampleValue(first[0], asObj(first[1]) || {});
  }
  return out;
}

export const API_DESCRIPTION_CAP = 400;

// the list API cuts descriptions at 400 chars, so end a cut one on a word with an ellipsis
export function tidyDescription(text: string | undefined, cap = API_DESCRIPTION_CAP): string {
  const t = (text || '').trim();
  if (t.length < cap || /[.!?]$/.test(t)) return t;
  const space = t.lastIndexOf(' ');
  const cut = (space > cap * 0.6 ? t.slice(0, space) : t).replace(/[\s,;:(–-]+$/, '');
  return `${cut}…`;
}

// prefer the longer of the API text and the generated docs, they come from the same tool class
export function fullDescription(apiText: string | undefined, docText: string | undefined): string {
  const a = (apiText || '').trim();
  const d = (docText || '').trim();
  if (d.length > a.length && (!a || d.startsWith(a.slice(0, 40)))) return d;
  return tidyDescription(a);
}
