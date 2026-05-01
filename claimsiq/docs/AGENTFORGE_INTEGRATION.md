# Calling Abenix from ClaimsIQ (JVM/Kotlin)

ClaimsIQ doesn't share the Python SDK — instead it talks to Abenix via plain HTTP. The same primitives the Python SDK exposes (`execute`, `chat.send`, `knowledge.search`) are documented here as raw REST so the Kotlin client stays simple.

## Auth

All requests go to the Abenix API base URL (in-cluster: `http://abenix-api:8000`).

- `X-API-Key: <CLAIMSIQ_ABENIX_API_KEY>` — platform key with `can_delegate` scope
- `X-Abenix-Subject: {"subject_type":"claimsiq","subject_id":"<claims-user-id>","email":"…","display_name":"…"}` — JSON-encoded; tells Abenix which ClaimsIQ end-user is acting

The subject header scopes:
- chat thread visibility (one ClaimsIQ user can't see another's threads)
- agent tool data filters (row-level security)
- audit + cost attribution

## One-shot agent dispatch (no thread)

```kotlin
val client = HttpClient(CIO) { install(ContentNegotiation) { json() } }

val res: ExecutionResult = client.post("$base/api/agent-execution/execute") {
    header("X-API-Key", apiKey)
    header("X-Abenix-Subject", subjectJson)
    contentType(ContentType.Application.Json)
    setBody(mapOf(
        "agent_slug" to "cq-claim-decider",
        "message" to claimSummaryJson,
        "wait_timeout_seconds" to 180
    ))
}.body()
```

## Persistent multi-turn chat (use the platform thread primitive)

Same primitive the example app uses. Threads are scoped per `(app_slug, subject)`.

```kotlin
// 1) Create or reuse a thread
val threads = client.get("$base/api/conversations") {
    header("X-API-Key", apiKey); header("X-Abenix-Subject", subjectJson)
    parameter("app_slug", "claimsiq"); parameter("agent_slug", "cq-claims-chat"); parameter("per_page", 1)
}.body<ListResponse>()

val threadId = threads.data.firstOrNull()?.id ?: client.post("$base/api/conversations") {
    header("X-API-Key", apiKey); header("X-Abenix-Subject", subjectJson)
    contentType(ContentType.Application.Json)
    setBody(mapOf("app_slug" to "claimsiq", "agent_slug" to "cq-claims-chat"))
}.body<ThreadResponse>().data.id

// 2) Send a turn — the platform repacks history + persists both sides
val turn = client.post("$base/api/conversations/$threadId/turn") {
    header("X-API-Key", apiKey); header("X-Abenix-Subject", subjectJson)
    contentType(ContentType.Application.Json)
    setBody(mapOf(
        "content" to userQuestion,
        "context" to currentClaimSnapshot   // optional, fresh per turn
    ))
}.body<TurnResponse>()

println(turn.data.assistantMessage.content)
```

## Endpoints reference

| Verb | Path | Purpose |
|------|------|---------|
| POST | `/api/agent-execution/execute` | One-shot agent run |
| POST | `/api/conversations` | Create chat thread |
| GET  | `/api/conversations?app_slug=claimsiq&agent_slug=…` | List my threads |
| GET  | `/api/conversations/{id}` | Get thread + messages |
| POST | `/api/conversations/{id}/turn` | Append user msg + run agent + persist response |
| PUT  | `/api/conversations/{id}` | Rename / archive |
| DELETE | `/api/conversations/{id}` | Delete thread |
| POST | `/api/knowledge-engines/{kbId}/search` | KB hybrid search |

## Environment

Set in ClaimsIQ pod env:

```
ABENIX_API_URL=http://abenix-api:8000
CLAIMSIQ_ABENIX_API_KEY=<from k8s secret>
```

The platform key must be created in the Abenix admin console with the `can_delegate` flag, otherwise `X-Abenix-Subject` is rejected.
