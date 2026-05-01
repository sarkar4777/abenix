export interface ParsedCurl {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
  params: Record<string, string>;
  bearer_token: string;
  warnings: string[];
}

const EMPTY: ParsedCurl = {
  url: '',
  method: 'GET',
  headers: {},
  body: null,
  params: {},
  bearer_token: '',
  warnings: [],
};

/**
 * Split a shell-quoted command into argv-style tokens. Honours single
 * and double quotes and backslash continuation across newlines.
 */
function tokenize(input: string): string[] {
  const out: string[] = [];
  let buf = '';
  let i = 0;
  const s = input.replace(/\\\r?\n/g, ' ');
  while (i < s.length) {
    const c = s[i];
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r') {
      if (buf.length > 0) { out.push(buf); buf = ''; }
      i++; continue;
    }
    if (c === "'" || c === '"') {
      const quote = c; i++;
      while (i < s.length && s[i] !== quote) {
        if (s[i] === '\\' && quote === '"' && i + 1 < s.length) {
          buf += s[i + 1]; i += 2; continue;
        }
        buf += s[i++];
      }
      i++; continue;
    }
    if (c === '\\' && i + 1 < s.length) {
      buf += s[i + 1]; i += 2; continue;
    }
    buf += s[i++];
  }
  if (buf.length > 0) out.push(buf);
  return out;
}

function tryParseJson(s: string): unknown {
  try { return JSON.parse(s); } catch { return s; }
}

function splitUrlAndQuery(url: string): { url: string; params: Record<string, string> } {
  const qIdx = url.indexOf('?');
  if (qIdx < 0) return { url, params: {} };
  const base = url.slice(0, qIdx);
  const qs = url.slice(qIdx + 1);
  const params: Record<string, string> = {};
  for (const pair of qs.split('&')) {
    if (!pair) continue;
    const [k, ...rest] = pair.split('=');
    if (!k) continue;
    try {
      params[decodeURIComponent(k)] = decodeURIComponent(rest.join('='));
    } catch {
      params[k] = rest.join('=');
    }
  }
  return { url: base, params };
}

export function parseCurl(input: string): ParsedCurl {
  const trimmed = (input || '').trim();
  if (!trimmed) return { ...EMPTY };

  const tokens = tokenize(trimmed);
  if (tokens.length === 0) return { ...EMPTY };

  // Drop a leading "curl" if present.
  let i = 0;
  if (tokens[i].toLowerCase() === 'curl') i++;

  const out: ParsedCurl = {
    url: '',
    method: '',
    headers: {},
    body: null,
    params: {},
    bearer_token: '',
    warnings: [],
  };
  let hasJsonBody = false;

  while (i < tokens.length) {
    const tok = tokens[i];
    if (tok === '-X' || tok === '--request') {
      out.method = (tokens[++i] || 'GET').toUpperCase();
    } else if (tok === '-H' || tok === '--header') {
      const raw = tokens[++i] || '';
      const colon = raw.indexOf(':');
      if (colon < 0) { out.warnings.push(`malformed header: ${raw}`); continue; }
      const k = raw.slice(0, colon).trim();
      const v = raw.slice(colon + 1).trim();
      if (!k) continue;
      const m = /^bearer\s+(.+)$/i.exec(v);
      if (k.toLowerCase() === 'authorization' && m) {
        out.bearer_token = m[1];
      } else if (k.toLowerCase() === 'content-type' && /json/i.test(v)) {
        out.headers[k] = v;
        hasJsonBody = true;
      } else {
        out.headers[k] = v;
      }
    } else if (tok === '-d' || tok === '--data' || tok === '--data-raw' ||
               tok === '--data-binary' || tok === '--data-ascii') {
      const raw = tokens[++i] || '';
      out.body = hasJsonBody ? tryParseJson(raw) : raw;
      if (!out.method) out.method = 'POST';
    } else if (tok === '--json') {
      const raw = tokens[++i] || '';
      out.body = tryParseJson(raw);
      if (!out.method) out.method = 'POST';
      out.headers['Content-Type'] = 'application/json';
    } else if (tok === '-u' || tok === '--user') {
      out.warnings.push('--user / -u (basic auth) not yet supported');
      i++;
    } else if (tok === '-G' || tok === '--get') {
      out.method = 'GET';
    } else if (tok === '--url') {
      const raw = tokens[++i] || '';
      const split = splitUrlAndQuery(raw);
      out.url = split.url;
      Object.assign(out.params, split.params);
    } else if (tok.startsWith('--data-urlencode')) {
      // form-style — not the JSON body the tool expects; skip with warning.
      out.warnings.push('--data-urlencode dropped (use a body object instead)');
      i++;
    } else if (tok.startsWith('-')) {
      // Unknown flag — consume one extra arg only if it doesn't look like a flag itself.
      if (i + 1 < tokens.length && !tokens[i + 1].startsWith('-')) i++;
      out.warnings.push(`ignored flag: ${tok}`);
    } else {
      // Bare positional — treat as URL if we don't have one yet.
      if (!out.url) {
        const split = splitUrlAndQuery(tok);
        out.url = split.url;
        Object.assign(out.params, split.params);
      } else {
        out.warnings.push(`extra positional ignored: ${tok}`);
      }
    }
    i++;
  }

  if (!out.method) out.method = out.body == null ? 'GET' : 'POST';
  if (!out.url) out.warnings.push('no URL detected');
  return out;
}
