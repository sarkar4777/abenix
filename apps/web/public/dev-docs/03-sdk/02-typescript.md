# TypeScript SDK

> A smaller surface than the Python SDK, idiomatic for TS/JS. One file, built on the global `fetch`.

Build it from the monorepo:
```bash
cd packages/sdk/js && npm install && npm run build
# then, from your app
npm install /path/to/agentforge/packages/sdk/js
```

The package is `@abenix/sdk`, an ES module (`"type": "module"`, `import { Abenix } from "@abenix/sdk"`). It has no runtime dependencies. It needs a global `fetch`, `FormData`, `Blob` and `AbortSignal.timeout`, so Node 18+ or a modern browser. `npm pack` in `packages/sdk/js` gives a tarball an app can install the same way.

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

Sub-clients: `executions`, `agents`, `knowledge`, `approvals`, `decisions`, `sources`, `events`, `actions`, `autonomy`, `improvements`, `lessons`, `feedback`. Top-level methods: `permissions`, `execute`, `stream`, `approve`, `reject`, `setActAs`.

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
  conversationId?: string;             // continue a chat thread
  waitTimeoutSeconds?: number;         // 5 to 1800, defaults to the client timeout less 5 s
  maxTokens?: number;                  // deprecated, ignored
  temperature?: number;                // deprecated, ignored
}
```

`ExecutionResult` has `output` (string), `inputTokens`, `outputTokens`, `cost`, `durationMs`, `model`, `toolCalls`, `confidenceScore?`, `executionId?`, `status` and `pausedAt?`. `pausedAt` is an `ApprovalRef` with `approvalId`, `title`, `payload`, `requiredSignoffs`, `expiresAt`, `gateKind`.

| `wait` | Behaviour |
|---|---|
| omitted or `true` or `"completed"` | Blocks until the run ends. |
| `"submitted"` | Returns at once with `executionId` and `status`. `output` is empty. |
| `"until_gate"` | Blocks, but returns early with `status: "paused"` and `pausedAt` when a HITL gate opens. |
| `false` | Asks the server not to wait. |

If the server hands back an async response with only an `execution_id`, the client reads the run until it ends, the same as Python, so `output` is filled in. `maxTokens` and `temperature` are not sent, the execute endpoint has no such fields. Set them on the agent's `model_config`. Use `stream()` rather than `stream: true` here.

An agent can be named by slug or id. A slug is looked up exactly through `/api/agents/by-slug/{slug}`, and only a real UUID skips the lookup.

Results carry `triggerKind`, `triggerId`, `triggerName` and `startedBy`. `client.executions.list({ triggerKind: ['schedule', 'webhook'] })` and `list({ triggerId })` filter past runs by what started them.

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

`stream(agentSlugOrId, message, options?)` is an async generator of `StreamEvent`. `type` is one of `token`, `tool_call`, `tool_result`, `node_start`, `node_complete`, `done`, `error`, or the name of any other event the server sends, such as `moderation` or `node_trace`. Only `error` means the run failed. `done` carries `executionId`, and every event has its raw payload in `data`. An HTTP error does not throw. It yields one `error` event and ends. Breaking out of the loop closes the connection. There is no reconnect and no TS `watch` for runs started elsewhere.

### React

`@abenix/react` (`packages/sdk/react`) is built on `@abenix/sdk` and ships two things.

`useAgentStream({ client | apiKey + baseUrl, agentSlug, actAs?, onCostUpdate?, onError? })` resolves the agent by slug and returns `{ messages, agentState, agentName, isStreaming, error, send, stop, reset }`. `agentState` is `loading`, `ready` or `missing`, the last when the slug is unknown or the key cannot see the agent. Each message has `role`, `content`, `toolCalls`, `isStreaming`, and on replies `executionId` and `error`.

```tsx
const chat = useAgentStream({ client, agentSlug: "deep-research" });
if (chat.agentState === "missing") return <p>{chat.error}</p>;
await chat.send("Summarise the EV market");
```

`AgentChat` (named and default export) is a ready chat box on top of the hook. Props: `apiKey` or `client`, `agentSlug`, `baseUrl`, `actAs`, `theme`, `height`, `placeholder`, `onMessage`, `onError`, `onCostUpdate` and `className`. It shows a connecting state, a clear message when the agent cannot be found, tool calls as they run, and a Stop button while a reply streams. `onMessage` fires once per finished message with its `executionId`.

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

`execute`, `approvals` and `knowledge` throw a plain `Error` carrying the server's message. `executions`, `agents` and the top-level `approve` and `reject` do not check the status at all. On an error the single-row calls resolve to `null` (the envelope's `data`) and the list calls to `[]`. `stream` yields an `error` event. The newer calls throw `AbenixError` or `AbenixDecisionError` with `status`, `code`, `details` and `message`, see [Errors from these clients](#errors-from-these-clients).

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

The TS client is behind Python here. Not in TS yet:

- `watch()` and `executions.watchRawSse`
- `agents.findBySlug` (use `bySlug`)
- `decisions.create`, `versions`, `version`, `retire`, `evaluations`, `referenceSet`, `putReferenceSet`
- `sources.snapshots`, `validateUrl`, `preview`, `settings`
- `events.test`, `events.redeliver`
- `knowledge.ensureSubjectCollection`
- the `chat`, `tools` and `presets` sub-clients, and `codeAssets.run`

Neither SDK wraps the server's decision `check` and `try` endpoints.

### Errors from these clients

```ts
class AbenixError extends Error {
  status: number;      // HTTP status
  code?: string;       // server error_code, e.g. "STALE_DRAFT"
  details?: unknown;
}
class AbenixDecisionError extends Error { /* same fields */ }
```

`AbenixDecisionError` does not extend `AbenixError`, so check for both if you need to. Decision calls throw `AbenixDecisionError`. `permissions()`, `sources`, `events`, `actions`, `autonomy`, `improvements`, `lessons`, `feedback`, `mlModels`, `codeAssets`, `killSwitches` and `apiKeys` throw `AbenixError`. The older `execute`, `approvals` and `knowledge` methods still throw a plain `Error`.

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
| `list` | `(q = "")` |
| `get` | `(key)` |
| `compare` | `(key, facts, targets)`, each target `{ label, version }` or `{ as_of, known_at }` |
| `proposeRules` | `(key, rules, note, mode = "merge")`, new draft, import and propose in one call |
| `export` | `(key, version?)` |
| `referenceSets` | `()` |
| `tests` | `(key)` |
| `addTest` | `(key, name, facts, opts?: { expected, expectedOutcome, asOf, match })`, `match` is `"exact"` (default) or `"subset"` |
| `updateTest` | `(key, testId, fields: { name, facts, expected, expectedOutcome, asOf, match })`, fields left out stay as they are |
| `deleteTest` | `(key, testId)` |

A golden test with `match: "subset"` passes when every key in `expected` is in the result with the same value. Extra result keys are ignored and nested objects are matched the same way.

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

### Actions

Earned autonomy for actions your app takes itself. Act only when the decision is `run`. See [08-howto/13-earned-autonomy](../08-howto/13-earned-autonomy.md#8-drive-it-from-a-standalone-app).

```ts
const d = await client.actions.propose('trade.execute', { symbol: 'TTF', lots: 5 }, {
  target: 'TTF-Q1',
  intent: 'Spread is two sigma under fair value',
  prediction: { metric: 'pnl_eur', value: 12000, low: 4000, high: 20000 },
});
let go = d.decision === 'run';
let args: Record<string, unknown> = { symbol: 'TTF', lots: 5 };
if (d.decision === 'wait') {
  const w = await client.actions.wait(d.action_id, { timeoutSeconds: 1800 });
  go = w.decision === 'run';
  args = w.arguments ?? args;   // a reviewer may have edited them
}
if (go) {
  await placeOrder(args);
  await client.actions.executed(d.action_id, true, { resultPreview: 'filled' });
  await client.actions.reportOutcome(d.action_id, 9800);
}
```

| Method | Calls |
|---|---|
| `propose(actionKey, args?, opts?: { agentId, target, intent, prediction })` | `POST /api/autonomy/actions/propose`, resolves `ProposeResult` `{ action_id, decision, approval_id, message }` |
| `wait(actionId, opts?: { timeoutSeconds })` | Long-polls `/api/autonomy/actions/{id}/wait` in chunks of up to 120 s, default 60 s total. Resolves `ActionWaitResult` with the final `arguments` |
| `executed(actionId, ok = true, opts?: { resultPreview })` | `POST /api/autonomy/actions/{id}/executed` |
| `reportOutcome(actionId, value, opts?: { note })` | `POST /api/autonomy/actions/{id}/outcome` with `source: 'api'`. Needs `actions.review` |
| `flagHarm(actionId, note)` | `POST /api/autonomy/actions/{id}/harm`. Rejects on a blank note. Needs `actions.review` |
| `get(actionId)` | `GET /api/autonomy/actions/{id}`. Needs `autonomy.view` |

`ActionDecision` is `'run' | 'wait' | 'watching' | 'blocked'`. Response fields stay snake_case as the API sends them.

### Autonomy

| Method | Calls |
|---|---|
| `overview()` | `GET /api/autonomy/overview` |
| `grant(grantId)` | `GET /api/autonomy/grants/{id}` |
| `grantActions(grantId, opts?: { status, limit, before })` | `GET /api/autonomy/grants/{id}/actions`, resolves `{ items, next_before }` |

All need `autonomy.view`.

### Feedback, lessons and improvements

| Method | Calls |
|---|---|
| `feedback.give(rating, opts?: { executionId, conversationId, messageId, agentId, correction })` | `POST /api/improvements/feedback`. `rating` is `1` or `-1` |
| `lessons.report(agentId, note, opts?: { expected, executionId, input, output })` | `POST /api/improvements/lessons` with `source: 'sdk'`. Rejects on a blank note |
| `improvements.list(opts?: { agentId, state, limit })` | `GET /api/improvements/proposals`, resolves `ProposalRow[]` |
| `improvements.get(proposalId)` | `GET /api/improvements/proposals/{id}` |

These throw `AbenixError` like the other platform clients.

### ML models

A name stands for the model's active version, a UUID for one exact version.

```ts
const model = await client.mlModels.upload("churn", "./churn.joblib", {
  featureNames: ["age", "income", "tenure"],
  description: "Churn risk, retrained weekly",
});
console.log(model.version, model.status);
console.log(await client.mlModels.predict("churn", { age: 35, income: 50000, tenure: 24 }));
const why = await client.mlModels.explain("churn", { age: 35, income: 50000, tenure: 24 });
console.log(why.method, why.contributions[0]);
await client.mlModels.delete("churn", { allVersions: true });
```

| Method | Calls |
|---|---|
| `list()` | `GET /api/ml-models` |
| `get(nameOrId)` | `GET /api/ml-models/{id}` |
| `upload(name, file, opts?: { filename, framework, version, description, inputSchema, featureNames, outputSchema, tags })` | `POST /api/ml-models` as multipart. `file` is a path (Node), a `Blob`, a `Uint8Array` or an `ArrayBuffer`. Bytes need `filename` or `framework`. A version is picked for you when left out |
| `predict(nameOrId, inputData)` | `POST /api/ml-models/{id}/predict` |
| `explain(nameOrId, inputData, baseline?)` | `POST /api/ml-models/{id}/explain`. Resolves an `MLExplanation` with `contributions`, `waterfall`, `method` and `baseline_source`. See [Explanations](../02-runtime/12-ml-models.md#explanations) |
| `delete(nameOrId, opts?: { allVersions })` | Resolves `{ deleted: string[] }` |

A file that does not load throws `AbenixError` 422 with `code === "MODEL_LOAD_FAILED"` and the stored error version in `details.model`. A taken version throws 409 `VERSION_EXISTS`. An unknown name throws 404 `NOT_FOUND`.

### Code assets

```ts
let asset = await client.codeAssets.create("scorer", "./scorer", { description: "Scores rows" });
if (asset.status !== "ready") throw new Error(asset.error ?? "analysis failed");
asset = await client.codeAssets.newVersion(asset.id, "./scorer");
```

| Method | Calls |
|---|---|
| `list()` | `GET /api/code-assets` |
| `get(nameOrId)` | `GET /api/code-assets/{id}` |
| `create(name, source?, opts?: { description, gitUrl, gitRef, filename })` | `POST /api/code-assets` as multipart. `source` is a zip or tar.gz path, a folder (Node, zipped for you without `.git`, virtualenvs, `node_modules` and caches) or the bytes of an archive. Or pass `gitUrl` and no source |
| `newVersion(nameOrId, source?, opts?: { gitUrl, gitRef, filename })` | `POST /api/code-assets/{id}/versions`. Throws `AbenixError` 422 when the new code does not analyse cleanly, the live version stays |

`create` resolves once analysis is done, also when it failed, so check `status` and `error`. Paths and folders need Node. In a browser pass a `Blob`.

### Kill switches

```ts
const sw = await client.killSwitches.set("agent", "groundwork-trainer", "Bad outputs after the 2.1 data load");
console.log(await client.killSwitches.list());
await client.killSwitches.clear(sw.id);
```

| Method | Calls |
|---|---|
| `list(opts?: { includeCleared })` | `GET /api/governance/kill-switches`, resolves the switches. Needs `risk.view` |
| `set(scope, target, reason)` | `POST /api/governance/kill-switches`. `scope` is `all`, `agent`, `pipeline`, `tool`, `model`, `trigger`, `decision`, `source` or `improvements`, `target` a name or id in it or `*`. `reason` needs at least 3 characters. Needs `killswitch.manage` |
| `clear(switchId)` | `POST /api/governance/kill-switches/{id}/clear` |

### API keys

| Method | Calls |
|---|---|
| `list()` | `GET /api/api-keys`, your active keys, every key in the tenant for an admin |
| `create(name, scopes?, opts?: { expiresAt, maxMonthlyTokens, maxMonthlyCost })` | `POST /api/api-keys`. `scopes` is `{ can_delegate: true }`, `{ allowed_actions: [...] }` or a list of actions, any other shape rejects before the call. `raw_key` is only in this response |
| `revoke(keyId)` | `DELETE /api/api-keys/{id}` |

---

## Other sub-clients

The older sub-clients. Errors behave as described under [Errors](#errors).

### `approvals`

Every call resolves to an `Approval` (camelCase: `id`, `agentId`, `agentExecutionId`, `title`, `payload`, `requiredSignoffs`, `signoffs`, `status`, `requestedBy`, `expiresAt`, `decidedAt`, `createdAt`, `gateKind`, `clientToken`) unless noted.

| Method | Notes |
|---|---|
| `list(opts?: { status, executionId, agentId, kind, limit })` | `GET /api/approvals`, `limit` defaults to 200 |
| `get(approvalId)` | `GET /api/approvals/{id}` |
| `create(title, payload, opts?: { requiredSignoffs, expiresSeconds, gateKind, agentId, agentExecutionId, clientToken })` | `POST /api/approvals`. Defaults are 1 signoff and 86400 s |
| `signoff(approvalId, decision, opts?: { reason, clientToken, editedArguments })` | `decision` is `"approve"`, `"deny"` or `"return"`. `editedArguments` only on an `action:*` approval with `approve` |
| `approve(approvalId, opts?)` / `deny(approvalId, opts?)` | `signoff` with that decision |
| `returnForChanges(approvalId, reason, opts?: { clientToken })` | see above |
| `waitFor(approvalId, opts?: { timeoutSeconds, pollSeconds })` | Long-polls `/wait` in chunks of up to 120 s, default 60 s total. A busy answer (429, 502, 503, 504) or a dropped connection is retried until the timeout |
| `subscribe()` | Async generator over `GET /api/notifications/stream?types=approval_pending,approval_resolved`, yields `{ event, data }` |
| `configureWebhook({ url, secret })` | `PUT /api/approvals/webhooks`, resolves `{ url, hasSecret }`. A missing field is sent as `null` |

### `executions`

`live()`, `get(executionId)`, `replay(executionId)`, `tree(executionId)` and `pendingApprovals()` wrap `GET /api/executions/live`, `/api/executions/{id}`, `/api/executions/{id}/replay`, `/api/executions/tree/{id}` and `/api/executions/approvals`. `replay` returns the stored trace, it does not run anything.

`list(opts?: { agentId, status, triggerKind, triggerId, search, limit, offset })` wraps `GET /api/executions`. `limit` defaults to 20 and `triggerKind` takes a string or an array.

### `agents`

`list()` (first page, 20 agents), `get(agentId)`, `bySlug(slug)` (null when there is none), `create(body)` and `update(agentId, body)`. `create` and `update` take the same fields as `POST /api/agents`, including `model_config`, and throw `AbenixError`.

`client.me()` resolves `{ user: { id, email, full_name, role, tenant_id } }`.

### `knowledge`

| Method | Notes |
|---|---|
| `bootstrapProject(slug, name, opts?: { description, collections })` | `POST /api/knowledge-projects/bootstrap`, idempotent. Resolves `{ project, collections, skipped_agents }` |
| `upload(kbId, file, filename, contentType?)` | `file` is a `Blob`, `Uint8Array` or string, sent as multipart. Resolves the document with `status: "processing"`. Throws `AbenixError` 400 for an empty or unsupported file |
| `documents(kbId)` | Documents with their `status`. Poll until yours is `ready` before you search |
| `cognify(kbId, opts?: { docIds, model, chunkSize, chunkOverlap })` | Resolves `{ jobId, status, documents, message }` |
| `graphStats(kbId)` | Resolves `{ entities, relationships, entityTypes }` |
| `search(kbId, query, opts?: { mode, topK, graphDepth })` | Defaults `hybrid`, 5, 2. Resolves `{ results, entitiesFound, modeUsed, vectorCount, graphCount, latencyMs }`, each result has `content`, `score`, `source` and `metadata`. Throws `AbenixError` |
| `graph(kbId, limit = 100)` | Subgraph for display |
| `cognifyJobs(kbId)` | Job history |

### Top-level `approve` and `reject`

`approve(executionId, gateId, comment?)` and `reject(...)` post to `/api/executions/{id}/approve?gate_id=`. They are the old gate shape. Prefer `approvals.approve`.

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
