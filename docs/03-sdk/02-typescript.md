# TypeScript SDK

> Same surface as the Python SDK, idiomatic for TS/JS. Works in browsers (via `fetch`), in Node ≥18 (built-in `fetch`), and in edge runtimes (Cloudflare Workers, Vercel Edge).

Install:
```bash
npm install @abenix/sdk
# or in this monorepo:
cd packages/sdk/typescript && npm link
```

---

## Quick start

```ts
import { Abenix } from "@abenix/sdk";

const client = new Abenix({
  apiUrl: process.env.ABENIX_API_URL!,
  apiKey: process.env.ABENIX_API_KEY!,
});

const result = await client.execute("wingman-market-brief", {}, { wait: "complete" });
console.log(result.output);
```

---

## Client construction

```ts
interface AbenixOptions {
  apiUrl: string;
  apiKey?: string;
  token?: string;
  fetch?: typeof fetch;       // override; useful for testing or polyfills
  timeoutMs?: number;         // default 30000
  retries?: number;           // default 3 on 5xx + 429
  signal?: AbortSignal;       // honoured on every call
}
```

There's no `async`-context to close — the SDK is stateless beyond the per-call `fetch`. No `await client.close()` needed.

---

## actAs

```ts
const subject = {
  subject_type: "wingman" as const,
  subject_id: "trader-42",
  email: "alice@trading-desk.com",
  display_name: "Alice — Crude Desk",
};

const result = await client
  .withSubject(subject)
  .execute("wingman-mispricing-extractor", { corridor: { id: "USGC-NWE" } });
```

`withSubject` returns a new client wrapper that adds `X-Abenix-Subject` to each call.

---

## Streaming

```ts
for await (const event of client.executeStream("agent-slug", input)) {
  if (event.type === "tool.end") {
    console.log(`tool ${event.toolSlug} latency=${event.latencyMs}ms`);
  } else if (event.type === "completed") {
    console.log(event.output);
  }
}
```

Built on the Streams API (`ReadableStream<TextEvent>`). Works in browsers + Node.

For React, there's a `useAbenixStream` hook in `@abenix/sdk-react`:

```tsx
import { useAbenixStream } from "@abenix/sdk-react";

function LiveScan({ corridorId }: { corridorId: string }) {
  const { events, terminal, error } = useAbenixStream(
    "wingman-mispricing-extractor",
    { corridor: { id: corridorId } },
  );

  return (
    <>
      {events.map(e => <EventRow key={e.id} event={e} />)}
      {terminal && <Result output={terminal.output} />}
      {error && <Error err={error} />}
    </>
  );
}
```

The hook handles reconnection, last-event-id, and cleanup.

---

## HITL

Same wait modes as Python:

```ts
const result = await client.execute(
  "contract-execute-flow",
  { counterparty_id, amount_usd },
  { wait: "approval_or_complete" },
);

if (result.status === "waiting_approval") {
  console.log("Pending:", result.approvalRef!.id);
  // ... later
  const final = await client.executions.wait(result.executionId, "terminal");
  console.log(final.output);
}
```

---

## Errors

```ts
import { AbenixError } from "@abenix/sdk";

try {
  await client.execute(...);
} catch (e) {
  if (e instanceof AbenixError) {
    console.log(e.errorCode);   // stable string
    console.log(e.message);     // human
    console.log(e.status);      // HTTP status
    console.log(e.details);     // record
  } else throw e;
}
```

Subclasses for common codes: `AbenixRateLimited`, `AbenixValidationError`, etc.

---

## OTel propagation

If `@opentelemetry/api` is loaded and a `Span` is active, the SDK propagates W3C `traceparent`. Otherwise no header is set.

The SDK does **not** auto-instrument your service. Use `@opentelemetry/instrumentation-fetch` / `@opentelemetry/sdk-node` separately.

---

## Bundle size

The minified + gzipped bundle is **~6 KB** when tree-shaken. The SDK has no runtime dependencies beyond the standard Web Streams + Fetch APIs.

---

## Browser-specific notes

- The browser SDK will auto-refresh JWTs using a stored refresh token if a `localStorage` adapter is wired. See `@abenix/sdk-browser`.
- CORS: the platform's API enables CORS with credentials. Your app must serve from a domain in `ALLOWED_ORIGINS` (env on abenix-api).
- The browser SDK does **not** ship `apiKey` support — use JWT auth in browsers. API keys belong on backends.

---

## See also

- [00-overview](00-overview.md) — design + actAs
- [01-python](01-python.md) — reference language
- [03-java](03-java.md) — Java SDK
