const TEXT_KEYS = ['message', 'input', 'query', 'prompt', 'question', 'text'];
const ENVELOPE = /^\{\s*"(message|input|query|prompt|question|text)"\s*:\s*"/;

function brief(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return `${v.length} item${v.length === 1 ? '' : 's'}`;
  const n = Object.keys(v as object).length;
  return `${n} field${n === 1 ? '' : 's'}`;
}

// pipeline runs store their input as {"message": "..."}, show people the words instead
export function readableInput(raw: string | null | undefined): string {
  const s = (raw || '').trim();
  if (!s.startsWith('{')) return raw || '';
  try {
    const obj = JSON.parse(s);
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
      const key = TEXT_KEYS.find((k) => typeof obj[k] === 'string' && obj[k].trim());
      const rest = Object.keys(obj).filter((k) => k !== key && obj[k] !== null && obj[k] !== '');
      if (key && !rest.length) return obj[key];
      const parts = rest.map((k) => `${k.replace(/_/g, ' ')}: ${brief(obj[k])}`);
      return [key ? obj[key] : '', ...parts].filter(Boolean).join(' · ') || s;
    }
  } catch {
    // a preview cut short is not valid JSON, keep the words after the key
    const m = s.match(ENVELOPE);
    if (m) {
      return s
        .slice(m[0].length)
        .replace(/"\s*}?\s*$/, '')
        .replace(/\\n/g, ' ')
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, '\\');
    }
  }
  return raw || '';
}
