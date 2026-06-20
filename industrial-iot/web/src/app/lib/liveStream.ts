// Helper around the standalone API's SSE bridges.
// Each tab-specific endpoint forwards from MQTT into a Server-Sent
// Events channel so the browser doesn't speak MQTT directly.

export interface LiveSubscription {
  close: () => void;
}

// onEvent receives parsed JSON payloads (one per MQTT message). The
// returned handle's `close()` aborts the EventSource.
export function subscribeLive<T = unknown>(
  topic: string,
  onEvent: (msg: T) => void,
  onError?: (err: Event) => void,
): LiveSubscription {
  const url = `/api/industrial-iot/live/sse?topic=${encodeURIComponent(topic)}`;
  let es: EventSource | null = null;
  try {
    es = new EventSource(url);
    es.onmessage = (ev) => {
      try {
        const parsed = JSON.parse(ev.data) as T;
        onEvent(parsed);
      } catch {
        // ignore malformed frames — the bridge guarantees JSON, but
        // a partial flush during reconnect can still slip through.
      }
    };
    if (onError) es.onerror = onError;
  } catch (e) {
    if (onError) onError(e as Event);
  }
  return {
    close: () => { try { es?.close(); } catch { /* noop */ } },
  };
}

// Toggle the simulator / listener trigger on the standalone API.
// Returns a structured result so the UI can distinguish a real
// subscription from a demo-mode fallback (when the trigger registry
// isn't wired on the platform yet).
export interface TriggerResult {
  ok: boolean;       // forward succeeded end-to-end
  demo: boolean;     // upstream returned 404 — caller should show "demo" badge
  status?: number;   // upstream HTTP status when known
  reason?: string;
}

export async function toggleLiveTrigger(
  agentSlug: string,
  enabled: boolean,
): Promise<TriggerResult> {
  try {
    const r = await fetch('/api/industrial-iot/live/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_slug: agentSlug, enabled }),
    });
    let body: { ok?: boolean; status?: number; reason?: string } = {};
    try { body = await r.json(); } catch { /* non-JSON — leave empty */ }
    const status = body.status ?? r.status;
    const demo = status === 404;
    return {
      ok: Boolean(body.ok ?? r.ok),
      demo,
      status,
      reason: body.reason,
    };
  } catch {
    return { ok: false, demo: false };
  }
}
