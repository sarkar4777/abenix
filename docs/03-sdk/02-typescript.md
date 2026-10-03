# TypeScript SDK

> A smaller surface than the Python SDK, idiomatic for TS/JS. One file, built on the global `fetch`.

Build it from the monorepo:
```bash
cd packages/sdk/js && npm install && npm run build
# then, from your app
npm install /path/to/agentforge/packages/sdk/js
```

The package is `@abenix/sdk`. It has no runtime dependencies. It needs a global `fetch` and `AbortSignal.timeout`, so Node 18+ or a modern browser.

---

## Quick start

```ts
import { Abenix } from "@abenix/sdk";

const client = new Abenix({
  apiKey: process.env.ABENIX_API_KEY!,
  baseUrl: process.env.ABENIX_API_URL,
});

const result = await client.execute("wingman-market-brief", "Brief me on today's crude market");
console.log(result.status, result.output);
```

---

## Client construction

```ts
interface AbenixConfig {
  apiKey: string;
  baseUrl?: string;          // default "http://localhost:8000"
  timeout?: number;          // ms, default 120000
  actAs?: ActingSubject;     // default subject for execute and stream
}
```

Every request sends `X-API-Key` and is aborted after `timeout`. `execute` also derives the server-side wait from it (`timeout / 1000 - 5` seconds, clamped to 5..1800). There is nothing to close.

Sub-clients: `executions`, `agents`, `knowledge`, `approvals`, `decisions`, `sources`, `events`. Top-level methods: `permissions`, `execute`, `stream`, `approve`, `reject`, `setActAs`.

---

## actAs

```ts
const subject = {
  subjectType: "wingman",
  subjectId: "trader-42",
  email: "alice@trading-desk.com",
  displayName: "Alice — Crude Desk",
};

const result = await client.execute(
  "wingman-mispricing-extractor",
  "Scan USGC-NWE",
  { actAs: subject },
);
```

Pass `actAs` per call, or set a default with the constructor or `client.setActAs(subject)`. A per-call subject wins. Fields are camelCase here and go out as the snake_case JSON object in `X-Abenix-Subject`. Only `execute` and `stream` send the header. The API key needs the `can_delegate` scope.

---

## Execute

```ts
async execute(agentSlugOrId: string, message: string, options?: ExecuteOptions): Promise<ExecutionResult>

interface ExecuteOptions {
  context?: Record<string, unknown>;   // input variables for agents and pipelines
  actAs?: ActingSubject;
  wait?: "completed" | "submitted" | "until_gate" | boolean;
  stream?: boolean;
  maxTokens?: number;
  temperature?: number;
}
```

`ExecutionResult` has `output` (string), `inputTokens`, `outputTokens`, `cost`, `durationMs`, `model`, `toolCalls`, `confidenceScore?`, `executionId?`, `status` and `pausedAt?`. `pausedAt` is an `ApprovalRef` with `approvalId`, `title`, `payload`, `requiredSignoffs`, `expiresAt`, `gateKind`.

| `wait` | Behaviour |
|---|---|
| omitted or `true` or `"completed"` | Blocks until the run ends. |
| `"submitted"` | Returns at once with `executionId` and `status`. `output` is empty. |
| `"until_gate"` | Blocks, but returns early with `status: "paused"` and `pausedAt` when a HITL gate opens. |
| `false` | Asks the server not to wait. |

Unlike Python, the TS client does not poll. If the server hands back an async response, `output` is empty and you poll `client.executions.get(executionId)` yourself. `maxTokens` and `temperature` are sent in the body but the execute endpoint ignores them. Use `stream()` rather than `stream: true` here.

---

## Streaming

```ts
for await (const event of client.stream("deep-research", "Analyze market trends for EVs")) {
  if (event.type === "token") process.stdout.write(event.text ?? "");
  else if (event.type === "tool_call") console.log(`\ntool ${event.name}`);
  else if (event.type === "done") console.log(`\ncost ${event.cost} in ${event.durationMs}ms`);
  else if (event.type === "error") console.log("\nfailed:", event.message);
}
```

`stream(agentSlugOrId, message, options?)` is an async generator of `StreamEvent`. `type` is one of `token`, `tool_call`, `tool_result`, `node_start`, `node_complete`, `done`, `error`. An HTTP error does not throw. It yields one `error` event and ends. There is no reconnect and no TS `watch` for runs started elsewhere.

For React there is no streaming hook. `@abenix/react` (`packages/sdk/react`) ships one component, `AgentChat`, an embeddable chat box. Its props are `apiKey`, `agentSlug`, `baseUrl`, `theme`, `height`, `placeholder`, `onMessage`, `onError`, `onCostUpdate` and `className`.

---

## HITL

```ts
const result = await client.execute(
  "contract-execute-flow",
  "Execute the Acme renewal",
  { wait: "until_gate", context: { counterparty_id: cpId, amount_usd: 2_400_000 } },
);

if (result.status === "paused" && result.pausedAt) {
  console.log("Pending:", result.pausedAt.approvalId, result.pausedAt.title);
  const approval = await client.approvals.waitFor(result.pausedAt.approvalId, { timeoutSeconds: 3600 });
  if (approval.status === "approved") {
    const row = await client.executions.get(result.executionId!);
    console.log(row.status, row.output_message);
  }
}
```

The run resumes on the server after sign-off, so `row.status` may still be `running`. Poll until it is terminal.

---

## Errors

`execute`, `approvals` and `knowledge` throw a plain `Error` carrying the server's message. `executions` and `agents` do not check the status at all and resolve to `undefined` (or `[]` for lists) on an error. `stream` yields an `error` event. The newer calls throw `AbenixError` or `AbenixDecisionError` with `status`, `code`, `details` and `message`, see [Errors from these clients](#errors-from-these-clients).

```ts
try {
  await client.execute("invoice-triage", "Route INV-1042");
} catch (e) {
  console.log((e as Error).message);   // server message, or "HTTP 500"
}
```

The SDK does not retry anything itself.

---

## Platform clients

These calls return the `data` field of the response and throw on any 4xx or 5xx. The examples assume:

```ts
import { Abenix, AbenixDecisionError, EventsClient } from "@abenix/sdk";

const client = new Abenix({ apiKey: "af_xxx", baseUrl: "http://localhost:8000" });
```

The TS client is behind Python here. Not in TS yet: `me()`, `agents.bySlug`, `agents.create`, `agents.update`, `decisions.tests`, `decisions.retire`, `events.redeliver`. Neither SDK wraps the server's decision `check` and `try` endpoints.

### Errors from these clients

```ts
class AbenixError extends Error {
  status: number;      // HTTP status
  code?: string;       // server error_code, e.g. "STALE_DRAFT"
  details?: unknown;
}
class AbenixDecisionError extends Error { /* same fields */ }
```

`AbenixDecisionError` does not extend `AbenixError`, so check for both if you need to. Decision calls throw `AbenixDecisionError`. `permissions()`, `sources` and `events` throw `AbenixError`. The older `execute`, `approvals` and `knowledge` methods still throw a plain `Error`.

```ts
try {
  await client.decisions.get("no-such-decision");
} catch (e) {
  if (e instanceof AbenixDecisionError) console.log(e.status, e.code, e.message);
  else throw e;
}
```

### `permissions()`

```ts
const perms = await client.permissions();
if (!perms.capabilities.includes("decisions.publish")) {
  console.log(`${perms.email} cannot publish decisions`);
}
```

### Decisions

See [08-howto/09-decisions](../08-howto/09-decisions.md).

```ts
const res = await client.decisions.evaluate(
  "credit-limit",
  { segment: "smb", annual_revenue: 1_200_000 },
  { asOf: "2026-10-01" },
);
if (res.outcome === "decided") console.log(res.result, res.applied_rules);
else if (res.outcome === "missing_facts") console.log("need", res.missing_facts);

const batch = await client.decisions.evaluateBatch("credit-limit", [
  { facts: { segment: "smb", annual_revenue: 900_000 } },
  { facts: { segment: "enterprise", annual_revenue: 40_000_000 } },
]);
console.log(batch.counts);
```

Drafts carry an `etag`. Pass it as `etag` to `saveDraft` or `importRules` and it goes out as `If-Match`. A stale save throws with `code === "STALE_DRAFT"`. Each save returns the new `etag`.

```ts
const key = "credit-limit";
const draft = await client.decisions.newDraft(key, { note: "Raise SMB cap" });
const n: number = draft.version;

let saved = await client.decisions.importRules(key, n, rules, { mode: "merge", etag: draft.etag });
saved = await client.decisions.saveDraft(key, n, {
  etag: saved.etag,
  validFrom: "2026-11-01",
  changeNote: "SMB cap to 250k",
});

console.log(await client.decisions.validate(key, n));
console.log(await client.decisions.diff(key, n - 1, n));
console.log(await client.decisions.publishPlan(key, n));
await client.decisions.propose(key, n, "SMB cap to 250k");
// await client.decisions.withdraw(key, n);

// after sign-off
await client.decisions.publish(key, n, { expectedCurrent: n - 1 });
await client.decisions.update(key, { riskTier: "medium", tags: ["credit"] });
```

| Method | Signature |
|---|---|
| `evaluate` | `(key, facts, opts?: { asOf, knownAt, version, trace, persist, idempotencyKey })` |
| `evaluateBatch` | `(key, items, opts?: { asOf, version })` |
| `newDraft` | `(key, opts?: { note, fromVersion })` |
| `saveDraft` | `(key, version, fields: { etag, authoring, content, validFrom, validTo, clearValidFrom, clearValidTo, changeNote, provenance })` |
| `importRules` | `(key, version, rules, opts?: { mode: "merge" \| "replace", etag })` |
| `validate` | `(key, version)` |
| `propose` | `(key, version, note = "")` |
| `withdraw` | `(key, version)` |
| `publishPlan` | `(key, version)` |
| `publish` | `(key, version, opts?: { expectedCurrent })` |
| `diff` | `(key, a, b)` |
| `update` | `(key, fields: { name, description, riskTier, tags, logMode })` |

Also there: `list`, `get`, `compare`, `proposeRules`, `export`, `referenceSets`.

### Sources

See [02-runtime/17-source-watch](../02-runtime/17-source-watch.md).

```ts
const src = await client.sources.create({
  name: "EU AI Act page",
  url: "https://example.org/ai-act",
  kind: "html",
  cadence_minutes: 1440,
  selector: "main",
  tags: ["ai-act"],
});
const { outcome } = await client.sources.checkNow(src.id);
const recent = await client.sources.changes(20);
const full = await client.sources.change(recent[0].id);
```

`create` takes one object with snake_case keys. Other methods: `list(q)`, `get`, `update(sourceId, fields)`, `delete`, `pause(sourceId, reason)`, `resume`, `sourceChanges(sourceId, limit)`, `snapshot(snapshotId, { full })`. The Python `snapshots`, `validate_url`, `preview` and `settings` have no TS version.

### Events

See [02-runtime/19-outbound-events](../02-runtime/19-outbound-events.md).

```ts
const catalog = await client.events.catalog();

const sub = await client.events.subscribe(["decision.published", "source.changed"], {
  url: "https://hooks.example.com/abenix",
  name: "rules feed",
});
const secret: string = sub.signing_secret; // returned once

const failed = await client.events.deliveries(sub.id, { limit: 20, status: "failed" });
```

`subscribe(events, opts?: { url, name, filter, targetType, target })` rejects on an empty list. `targetType` is `webhook`, `agent` or `pipeline`. There is no `redeliver` in TS, use the Python SDK or `POST /api/webhooks/deliveries/{id}/redeliver`.

`EventsClient.verifySignature(secret, body, signature)` is static and async. It computes `"sha256=" + HMAC-SHA256(secret, body)` with Web Crypto and compares it to the `X-Abenix-Signature` header in constant time. `body` must be the raw request text. It resolves `false` when the secret or header is missing.

```ts
// Express
app.post("/abenix", express.text({ type: "*/*" }), async (req, res) => {
  const ok = await EventsClient.verifySignature(SECRET, req.body, req.get("X-Abenix-Signature"));
  if (!ok) return res.sendStatus(401);
  const event = JSON.parse(req.body);
  console.log(req.get("X-Abenix-Event"), event.id);
  res.sendStatus(200);
});
```

### Approvals: return for changes

See [02-runtime/05-approvals-hitl](../02-runtime/05-approvals-hitl.md).

```ts
await client.approvals.returnForChanges(approvalId, "Cap should be 200k, not 250k", {
  clientToken: "ret-123",
});
```

Rejects when `reason` is blank. It calls `signoff(approvalId, "return", ...)` and resolves to the updated `Approval`.

---


## OTel propagation

The SDK has no OpenTelemetry code and sets no `traceparent` header. To join platform runs to your traces, instrument `fetch` yourself, for example with `@opentelemetry/instrumentation-undici` in Node or `@opentelemetry/instrumentation-fetch` in the browser.

---

## Dependencies

None at runtime. The whole SDK is [`packages/sdk/js/src/index.ts`](../../packages/sdk/js/src/index.ts), compiled with `tsc` to `dist/`.

---

## Browser notes

- Every request sends `X-API-Key`, and there is no JWT option. An API key in a browser bundle is visible to anyone, so keep SDK calls on a backend.
- CORS: the API allows the origins in `CORS_ORIGINS` (default `http://localhost:3000`, set from `corsOrigins` in the Helm values).

---

## See also

- [00-overview](00-overview.md) — design + actAs
- [01-python](01-python.md) — reference language
- [03-java](03-java.md) — Java SDK
