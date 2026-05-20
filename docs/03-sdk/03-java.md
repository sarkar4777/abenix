# Java SDK

> JDK 17+. Blocking and `CompletableFuture` surfaces, Spring Boot 3 integration.

Install (Maven):
```xml
<dependency>
  <groupId>com.abenix</groupId>
  <artifactId>abenix-sdk</artifactId>
  <version>1.5.5</version>
</dependency>
```

Gradle:
```groovy
implementation 'com.abenix:abenix-sdk:1.5.5'
```

---

## Quick start

```java
import com.abenix.sdk.Abenix;
import com.abenix.sdk.ExecutionResult;

Abenix client = Abenix.builder()
    .apiUrl(System.getenv("ABENIX_API_URL"))
    .apiKey(System.getenv("ABENIX_API_KEY"))
    .build();

ExecutionResult r = client.execute("wingman-market-brief", Map.of(), Wait.COMPLETE);
System.out.println(r.output());
```

---

## Sync vs async

```java
// Blocking (default)
ExecutionResult r = client.execute("slug", input, Wait.COMPLETE);

// Async
CompletableFuture<ExecutionResult> fut = client.executeAsync("slug", input, Wait.COMPLETE);
fut.thenAccept(r -> System.out.println(r.output()));
```

The async surface uses Java 17's `HttpClient` with virtual threads (JDK 21+) when available. No third-party HTTP dependency.

---

## actAs

```java
ActingSubject subject = ActingSubject.of("example_app", userId, email, displayName);

ExecutionResult r = client.withSubject(subject)
    .execute("example_app-clause-extractor", Map.of("document_id", docId), Wait.COMPLETE);
```

`withSubject` returns a wrapper. the original `client` is unaffected.

---

## Streaming

```java
client.executeStream("agent-slug", input).forEach(event -> {
    switch (event.type()) {
        case TOOL_END -> log.info("tool {} ms={}", event.toolSlug(), event.latencyMs());
        case COMPLETED -> log.info("done: {}", event.output());
    }
});
```

The stream is a `Stream<ExecEvent>` backed by a non-blocking consumer.

---

## Spring Boot integration

```java
@Configuration
public class AbenixConfig {
    @Bean
    public Abenix abenix(@Value("${abenix.api-url}") String url,
                         @Value("${abenix.api-key}") String key) {
        return Abenix.builder().apiUrl(url).apiKey(key).build();
    }
}

@RestController
public class ScanController {
    private final Abenix abenix;
    
    @PostMapping("/api/scan")
    public ResponseEntity<?> scan(@RequestBody ScanRequest req, Principal principal) {
        var subject = ActingSubject.of("example_app", principal.getName(), null, null);
        var result = abenix.withSubject(subject)
            .executeAsync("example_app-…", req.toMap(), Wait.SUBMITTED)
            .get();
        return ResponseEntity.accepted().body(Map.of("execution_id", result.executionId()));
    }
}
```

---

## Errors

```java
try {
    client.execute(...);
} catch (AbenixRateLimited e) {
    Thread.sleep(e.retryAfterMs());
    // retry
} catch (AbenixError e) {
    log.error("error_code={} details={}", e.errorCode(), e.details());
}
```

---

## OTel

If `opentelemetry-api` is on the classpath and a current `Span` exists, the SDK propagates `traceparent`. Otherwise no header.

The SDK ships an optional `abenix-sdk-otel` artifact that auto-wires the propagator and adds attributes to the SDK's internal span.

---

## See also

- [00-overview](00-overview.md) — actAs + wait modes
- [01-python](01-python.md), [02-typescript](02-typescript.md) — sibling SDKs
