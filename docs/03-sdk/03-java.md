# Java SDK

> JDK 21. Blocking calls on the JDK `HttpClient`, Jackson for JSON. It lives in [`claimsiq/sdk/`](../../claimsiq/sdk/) and covers execute, watch, approvals and the read-side clients. There are no decisions, sources or events clients in Java yet.

Install: it is not published to a Maven repository. It is a Gradle subproject of `claimsiq/` (group `com.abenix`, version `0.1.0`). Inside that build, depend on it the way the ClaimsIQ app does:

```kotlin
// build.gradle.kts
dependencies {
    implementation(project(":sdk"))
}
```

Elsewhere, build the jar with Gradle 8.x and put it on your classpath with its two runtime dependencies:

```bash
cd claimsiq && gradle :sdk:jar
# claimsiq/sdk/build/libs/sdk-0.1.0.jar
```

```kotlin
implementation(files("libs/sdk-0.1.0.jar"))
implementation("com.fasterxml.jackson.core:jackson-databind:2.17.2")
implementation("org.slf4j:slf4j-api:2.0.13")
```

---

## Quick start

```java
import com.abenix.sdk.Abenix;
import com.abenix.sdk.ExecutionResult;

Abenix client = Abenix.builder()
    .baseUrl(System.getenv("ABENIX_API_URL"))
    .apiKey(System.getenv("ABENIX_API_KEY"))
    .build();

ExecutionResult r = client.execute("wingman-market-brief", "Brief me on today's crude market");
System.out.println(r.status() + " " + r.output());
```

---

## Client construction

```java
Abenix client = Abenix.builder()
    .baseUrl("http://localhost:8000")         // default
    .apiKey(key)                              // required, whitespace stripped
    .timeout(Duration.ofSeconds(600))         // default, request timeout for execute and the sub-clients
    .actingSubject(subject)                   // optional default subject
    .build();
```

`Abenix` implements `AutoCloseable`, but `close()` does nothing today. Sub-clients hang off accessor methods: `approvals()`, `agents()`, `tools()`, `presets()`, `mlModels()`, `knowledge()`, `chat()`, `executions()`.

---

## Execute

```java
ExecutionResult execute(String slugOrId, String message)
ExecutionResult execute(String slugOrId, String message, Abenix.ExecuteOptions opts)
ExecutionResult submit(String slugOrId, String message, Abenix.ExecuteOptions opts)
ExecutionResult getExecution(String executionId)
JsonNode getExecutionRaw(String executionId)
JsonNode liveExecutions()
JsonNode platformLimits()
```

All calls block. There is no `CompletableFuture` variant of `execute`. Wrap it in your own executor if you need one.

`ExecuteOptions` is a record with `waitTimeoutSeconds`, `context`, `actingSubject` and `waitMode`. Build it from `ExecuteOptions.defaults()` (600 s wait, nothing else set) or `ExecuteOptions.withContext(map)`, then chain `actingAs(subject)`, `waitTimeout(seconds)` and `waitMode(mode)`. The server accepts a wait of 5 to 1800 seconds.

```java
import com.abenix.sdk.Abenix.ExecuteOptions;
import com.abenix.sdk.WaitMode;

ExecutionResult r = client.execute(
    "contract-execute-flow",
    "Execute the Acme renewal",
    ExecuteOptions.withContext(Map.of("counterparty_id", cpId, "amount_usd", 2_400_000))
        .waitMode(WaitMode.UNTIL_GATE)
        .waitTimeout(300));
```

| `WaitMode` | Behaviour |
|---|---|
| none set, or `COMPLETED` | Blocks until the run ends. |
| `SUBMITTED` | Returns at once with `executionId` and `status`. |
| `UNTIL_GATE` | Blocks, but returns early with `status` `"paused"` and `pausedAt` when a HITL gate opens. |

`submit` is the fire-and-forget form. It always sends `wait=false`, uses a 30 s request timeout and ignores `waitMode` and `waitTimeoutSeconds`.

`ExecutionResult` is a record: `executionId`, `output` (an `Object`, a string or parsed JSON), `inputTokens`, `outputTokens`, `cost`, `durationMs`, `model`, `toolCalls`, `nodeResults`, `confidenceScore`, `status`, `pausedAt`, plus `isPaused()`. `pausedAt` is an `ApprovalRef` record with `approvalId`, `title`, `payload`, `requiredSignoffs`, `expiresAt`, `gateKind`. A failed run does not throw, so check `status()`.

Unlike Python, Java does not poll. If the server returns an async response, `output` is null and you poll `getExecution(executionId)`.

---

## actAs

```java
import com.abenix.sdk.ActingSubject;

ActingSubject subject = ActingSubject.builder()
    .subjectType("contractiq")
    .subjectId(userId)
    .email(email)
    .displayName(displayName)
    .build();

ExecutionResult r = client.execute(
    "contractiq-clause-extractor",
    "Extract the clauses",
    ExecuteOptions.withContext(Map.of("document_id", docId)).actingAs(subject));
```

Also there: `ActingSubject.of(type, id)` and the constructors `new ActingSubject(type, id)` and `new ActingSubject(type, id, email, displayName, metadata)`. The subject goes out as the JSON `X-Abenix-Subject` header, same shape as Python.

A per-call subject on `ExecuteOptions` wins over the builder's `actingSubject`. The builder default is also sent by `submit`, `getExecution`, `watch`, `approve`, `reject` and every sub-client. `chat()` methods take an `ActingSubject` argument per call. There is no `withSubject`. Build a second client if you need a different default. The API key needs the `can_delegate` scope.

---

## Watching a run

```java
try (WatchStream stream = client.watch(executionId)) {
    for (DagSnapshot snap : stream) {
        log.info("{} {}/{}", snap.status(), snap.progress().completed(), snap.progress().total());
        if (snap.isTerminal()) break;
    }
}
```

`watch(executionId)` opens the `/api/executions/{id}/watch` SSE stream and yields `DagSnapshot` records (status, progress, nodes, edges, cost so far). `WatchStream` is `Iterable<DagSnapshot>` and `AutoCloseable`, and also has `onSnapshot(cb)`, `onError(cb)`, `latest()` and `terminal()`, a `CompletableFuture<DagSnapshot>` for the final snapshot. The connection opens on the first `onSnapshot`, `terminal()` or iteration.

There is no token-level streaming in Java.

---

## Approvals

```java
Approval a = client.approvals().waitFor(r.pausedAt().approvalId(), 3600);
if ("approved".equals(a.status())) {
    JsonNode row = client.getExecutionRaw(r.executionId());
}

client.approvals().approve(approvalId, "Looks right");
client.approvals().deny(approvalId, "Wrong counterparty");
client.approvals().signoff(approvalId, "approve", "Looks right", "signoff-123");
```

| Method | Signature |
|---|---|
| `list` | `(ApprovalsClient.ListOptions opts)`, build with `ListOptions.empty().status("pending").limit(50)` |
| `get` | `(approvalId)` |
| `create` | `(title, payload, requiredSignoffs, expiresSeconds, gateKind, clientToken)` |
| `signoff` | `(approvalId, decision, reason, clientToken)` |
| `approve` / `deny` | `(approvalId, reason)` |
| `waitFor` | `(approvalId, timeoutSeconds)`, long-polls `/wait` in chunks of up to 120 s |
| `configureWebhook` | `(url, secret)`, admin only |

They return the `Approval` record. There is no `returnForChanges` in Java, send `signoff(approvalId, "return", reason, null)` instead. `client.approve(executionId, gateId, comment)` and `client.reject(...)` are the old gate-id shape.

---

## Other clients

Each returns `Map<String, Object>` or `List<Map<String, Object>>`.

| Client | Methods |
|---|---|
| `agents()` | `list()`, `get(agentId)`, `findBySlug(slug)` (null when not found) |
| `executions()` | `live()`, `get(id)`, `replay(id)`, `tree(id)`, `pendingApprovals()` |
| `knowledge()` | `cognify(kbId, docIds, model, chunkSize, chunkOverlap)`, `graphStats(kbId)`, `search(kbId, query, mode, topK, graphDepth)`, `graph(kbId, limit)`, `cognifyJobs(kbId)` |
| `chat()` | `create(agentSlug, agentId, appSlug, title, actAs)`, `list(appSlug, agentSlug, archived, limit, offset, actAs)`, `get`, `send(threadId, content, context, agentSlug, attachments, actAs)`, `rename`, `archive`, `delete` |
| `tools()` | `list()`, `catalog()`, `execute(slug, arguments, config)` |
| `presets()` | `list()`, `list(toolSlug, uiGroup, assetClass)`, `get`, `upsert(body)`, `delete`, `run(slug, arguments, config)` |
| `mlModels()` | `list()` |

---

## Spring Boot integration

There is no starter. Declare the client as a bean.

```java
@Configuration
public class AbenixConfig {
    @Bean
    public Abenix abenix(@Value("${abenix.api-url}") String url,
                         @Value("${abenix.api-key}") String key) {
        return Abenix.builder().baseUrl(url).apiKey(key).build();
    }
}

@RestController
public class ScanController {
    private final Abenix abenix;

    public ScanController(Abenix abenix) { this.abenix = abenix; }

    @PostMapping("/api/scan")
    public ResponseEntity<?> scan(@RequestBody ScanRequest req, Principal principal) {
        var subject = ActingSubject.of("contractiq", principal.getName());
        var result = abenix.execute(
            "contractiq-clause-extractor",
            req.message(),
            ExecuteOptions.withContext(req.toMap())
                .actingAs(subject)
                .waitMode(WaitMode.SUBMITTED));
        return ResponseEntity.accepted().body(Map.of("execution_id", result.executionId()));
    }
}
```

---

## Errors

Every failure throws `AbenixException`, an unchecked `RuntimeException`. An HTTP error's message holds the call, the status and up to 400 characters of the response body (the approvals client includes the whole body). Transport errors keep the original as the cause. There are no `status` or `code` fields and no subclasses, so parse the message if you need the status. An unknown slug throws with `No agent matched slug: ...`. The SDK does not retry.

```java
try {
    client.execute("invoice-triage", "Route INV-1042");
} catch (AbenixException e) {
    log.error("abenix call failed: {}", e.getMessage(), e);
}
```

---

## OTel

The SDK has no OpenTelemetry code and sets no `traceparent` header. The OpenTelemetry Java agent instruments `java.net.http.HttpClient`, so running your service with it propagates the trace.

---

## See also

- [00-overview](00-overview.md) — actAs + wait modes
- [01-python](01-python.md), [02-typescript](02-typescript.md) — sibling SDKs
