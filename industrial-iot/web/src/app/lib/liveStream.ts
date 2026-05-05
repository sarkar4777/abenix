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
// Returns true on success.
export async function toggleLiveTrigger(
  agentSlug: string,
  enabled: boolean,
): Promise<boolean> {
  try {
    const r = await fetch('/api/industrial-iot/live/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_slug: agentSlug, enabled }),
    });
    return r.ok;
  } catch {
    return false;
  }
}
