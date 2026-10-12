export interface AlertLike {
  name: string;
  state: string;
  summary?: string | null;
  description?: string | null;
  labels?: Record<string, string>;
}

export interface AlertFilter {
  q?: string;
  alertname?: string;
  status?: '' | 'firing' | 'muted';
  rule?: string;
}

// free text, plus key=value words that must match a label
export function filterAlerts<A extends AlertLike>(alerts: A[], f: AlertFilter): A[] {
  const words = (f.q || '').trim().split(/\s+/).filter(Boolean);
  const pairs = words.filter((w) => /^[^=]+=.+$/.test(w)).map((w) => {
    const i = w.indexOf('=');
    return [w.slice(0, i).toLowerCase(), w.slice(i + 1).toLowerCase()] as const;
  });
  const text = words.filter((w) => !/^[^=]+=.+$/.test(w)).map((w) => w.toLowerCase());
  return alerts.filter((a) => {
    const labels = a.labels || {};
    if (f.alertname && a.name !== f.alertname) return false;
    if (f.status === 'firing' && a.state !== 'firing') return false;
    if (f.status === 'muted' && a.state !== 'silenced' && a.state !== 'inhibited') return false;
    if (f.rule && labels.rule_id !== f.rule && labels.rule !== f.rule) return false;
    for (const [k, v] of pairs) {
      const hit = Object.entries(labels).find(([lk]) => lk.toLowerCase() === k);
      if (!hit || !String(hit[1]).toLowerCase().includes(v)) return false;
    }
    if (text.length) {
      const hay = `${a.name} ${a.summary ?? ''} ${a.description ?? ''} ${Object.values(labels).join(' ')}`.toLowerCase();
      if (!text.every((t) => hay.includes(t))) return false;
    }
    return true;
  });
}

export function alertNames(alerts: AlertLike[]): Array<{ name: string; count: number }> {
  const m = new Map<string, number>();
  for (const a of alerts) m.set(a.name, (m.get(a.name) ?? 0) + 1);
  return Array.from(m.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

// Alertmanager keeps pushing endsAt forward on a firing alert, so it is no promise of when it clears
export function resolvesText(state: string, endsAt: string | null | undefined, now = Date.now()): string | null {
  if (!endsAt || state === 'firing' || state === 'silenced' || state === 'inhibited') return null;
  const t = new Date(endsAt).getTime();
  if (Number.isNaN(t) || t > now) return null;
  const m = Math.floor((now - t) / 60000);
  return m < 1 ? 'resolved just now' : m < 60 ? `resolved ${m}m ago` : m < 1440 ? `resolved ${Math.floor(m / 60)}h ago` : `resolved ${Math.floor(m / 1440)}d ago`;
}

export function firingStepLink(link: string, ruleId: string | null | undefined, alertname?: unknown): string {
  if (!link.startsWith('/alerts') || !ruleId) return link;
  const [path, qs = ''] = link.split('?');
  const p = new URLSearchParams(qs);
  if (!p.has('rule')) p.set('rule', ruleId);
  if (typeof alertname === 'string' && alertname && !p.has('alertname')) p.set('alertname', alertname);
  return `${path}?${p.toString()}`;
}
