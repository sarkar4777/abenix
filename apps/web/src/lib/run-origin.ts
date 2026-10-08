// What started a run, as the executions list, run page and triggers page show it.

export interface RunOrigin {
  trigger_id?: string | null;
  trigger_kind?: string | null;
  trigger_name?: string | null;
  parent_execution_id?: string | null;
}

export const ORIGIN_LABELS: Record<string, string> = {
  schedule: 'Schedule',
  webhook: 'Webhook',
  manual: 'Run by hand',
  event: 'Event subscription',
  source_watch: 'Source watch',
  chat: 'Chat',
  api: 'API',
  playground: 'SDK playground',
  pipeline: 'Pipeline',
  agent: 'Another agent',
  autonomy_sample: 'Autonomy sample',
  eval: 'Evaluation',
  replay: 'Replay',
  a2a: 'Agent to agent',
  batch: 'Batch',
  meeting: 'Meeting',
  builder: 'Builder test',
};

// the filter on /executions, most common first
export const ORIGIN_FILTERS: Array<{ value: string; label: string }> = [
  { value: 'schedule,webhook,manual', label: 'Any trigger' },
  { value: 'schedule', label: 'Schedule' },
  { value: 'webhook', label: 'Webhook' },
  { value: 'manual', label: 'Run by hand' },
  { value: 'chat', label: 'Chat' },
  { value: 'api', label: 'API' },
  { value: 'event', label: 'Event subscription' },
  { value: 'source_watch', label: 'Source watch' },
  { value: 'pipeline,agent', label: 'Another run' },
  { value: 'replay', label: 'Replay' },
  { value: 'eval', label: 'Evaluation' },
  { value: 'autonomy_sample', label: 'Autonomy sample' },
  { value: 'playground,builder', label: 'Playground or builder' },
  { value: 'unknown', label: 'Not recorded' },
];

export function originLabel(kind: string | null | undefined): string {
  if (!kind) return 'Not recorded';
  if (ORIGIN_LABELS[kind]) return ORIGIN_LABELS[kind];
  const words = kind.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// "Nightly report (schedule)", "Chat", "Not recorded"
export function startedByText(o: RunOrigin): string {
  const kind = o.trigger_kind || null;
  const name = (o.trigger_name || '').trim();
  if (!kind && !name) return 'Not recorded';
  if (!name) return originLabel(kind);
  if (kind === 'manual' && o.trigger_id) return `${name} (run now)`;
  const kindWords = originLabel(kind).toLowerCase();
  // "Pinned replay" already says what it is
  if (name.toLowerCase().includes(kindWords)) return name;
  return `${name} (${kindWords})`;
}

// where "Started by" links to, null when there is nothing to open
export function originHref(o: RunOrigin): string | null {
  if (o.trigger_id) return `/triggers?focus=${o.trigger_id}`;
  switch (o.trigger_kind) {
    case 'pipeline':
    case 'agent':
    case 'replay':
      return o.parent_execution_id ? `/executions/${o.parent_execution_id}` : null;
    case 'event':
      return '/settings/webhooks';
    case 'source_watch':
      return '/sources';
    case 'eval':
      return '/evals';
    case 'autonomy_sample':
      return '/autonomy';
    default:
      return null;
  }
}

// a deleted trigger keeps its name on the run but has nothing left to open
export function originNote(o: RunOrigin): string | null {
  if (!o.trigger_kind) return 'This run is older than the Started by record.';
  const fromTrigger = ['schedule', 'webhook'].includes(o.trigger_kind) || (o.trigger_kind === 'manual' && !!o.trigger_name);
  if (fromTrigger && !o.trigger_id) return 'The trigger has since been deleted.';
  return null;
}

// rows still on screen from the previous filter, trimmed to what the new one asks for
export function matchesFilters(
  e: RunOrigin & { status?: string; input_message?: string },
  f: { status: string; search: string; origin: string; triggerId: string },
): boolean {
  if (f.status && e.status?.toLowerCase() !== f.status) return false;
  if (f.search && !(e.input_message || '').toLowerCase().includes(f.search.toLowerCase())) return false;
  if (f.triggerId && e.trigger_id !== f.triggerId) return false;
  if (f.origin) {
    const kinds = f.origin.split(',');
    const kind = e.trigger_kind || 'unknown';
    if (!kinds.includes(kind)) return false;
  }
  return true;
}
