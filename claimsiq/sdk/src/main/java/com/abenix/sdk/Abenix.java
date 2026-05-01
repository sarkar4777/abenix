package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

public final class Abenix implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(Abenix.class);
    private static final ObjectMapper JSON = new ObjectMapper();

    private final String baseUrl;
    private final String apiKey;
    private final Duration timeout;
    private final HttpClient http;
    private final ActingSubject defaultActingSubject;

    private Abenix(Builder b) {
        this.baseUrl = stripTrailingSlash(Objects.requireNonNull(b.baseUrl, "baseUrl"));
        this.apiKey = Objects.requireNonNull(b.apiKey, "apiKey");
        this.timeout = b.timeout;
        this.defaultActingSubject = b.actingSubject;
        this.http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .version(HttpClient.Version.HTTP_1_1)      // SSE is happier on 1.1
            .build();
    }

    public static Builder builder() { return new Builder(); }

    // ─────────────────────────── Public verbs ───────────────────────────

    public ExecutionResult execute(String slugOrId, String message) {
        return execute(slugOrId, message, ExecuteOptions.defaults());
    }

    public ExecutionResult submit(String slugOrId, String message, ExecuteOptions opts) {
        String agentId = resolveAgentId(slugOrId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("message", message);
        body.put("stream", false);
        body.put("wait", false);
        if (opts.context() != null) body.put("context", opts.context());
        String json = toJson(body);
        HttpRequest req = authHeaders(HttpRequest.newBuilder()
            .uri(URI.create(baseUrl + "/api/agents/" + agentId + "/execute"))
            .timeout(Duration.ofSeconds(30))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json)), opts.actingSubject())
            .build();
        HttpResponse<String> resp;
        try {
            resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        } catch (IOException | InterruptedException e) {
            throw new AbenixException("submit(" + slugOrId + ") failed: " + e.getMessage(), e);
        }
        if (resp.statusCode() >= 400) {
            throw new AbenixException("submit(" + slugOrId + ") HTTP " + resp.statusCode()
                + " — " + truncate(resp.body(), 400));
        }
        JsonNode root = parse(resp.body());
        JsonNode data = root.has("data") ? root.get("data") : root;
        try {
            return JSON.treeToValue(data, ExecutionResult.class);
        } catch (IOException e) {
            throw new AbenixException("Bad submit response shape: " + e.getMessage(), e);
        }
    }

    public ExecutionResult getExecution(String executionId) {
        JsonNode data = getExecutionRaw(executionId);
        try {
            return JSON.treeToValue(data, ExecutionResult.class);
        } catch (IOException e) {
            throw new AbenixException("Bad getExecution response shape: " + e.getMessage(), e);
        }
    }

    /**
     * List currently-running executions for the caller's tenant. Used
     * by ClaimsIQ to discover the executionId of a pipeline that was
     * just kicked off via the synchronous {@link #execute} (which
     * doesn't surface the id until it returns).
     */
    public JsonNode liveExecutions() {
        HttpRequest req = authHeaders(HttpRequest.newBuilder()
            .uri(URI.create(baseUrl + "/api/executions/live"))
            .timeout(Duration.ofSeconds(15))
            .GET(), defaultActingSubject)
            .build();
        try {
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw new AbenixException("liveExecutions HTTP " + resp.statusCode());
            }
            JsonNode root = parse(resp.body());
            return root.has("data") ? root.get("data") : root;
        } catch (IOException | InterruptedException e) {
            throw new AbenixException("liveExecutions failed: " + e.getMessage(), e);
        }
    }

    /**
     * Raw JSON for the execution row. Returns the {@code data} payload
     * — includes status, node_results, error_message etc. — so callers
     * can build whatever shape they need (the polling DAG view in
     * ClaimsIQ uses this to construct a DagSnapshot every tick).
     */
    public JsonNode getExecutionRaw(String executionId) {
        HttpRequest req = authHeaders(HttpRequest.newBuilder()
            .uri(URI.create(baseUrl + "/api/executions/" + Objects.requireNonNull(executionId)))
            .timeout(Duration.ofSeconds(30))
            .GET(), defaultActingSubject)
            .build();
        try {
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw new AbenixException("getExecution HTTP " + resp.statusCode());
            }
            JsonNode root = parse(resp.body());
            return root.has("data") ? root.get("data") : root;
        } catch (IOException | InterruptedException e) {
            throw new AbenixException("getExecution failed: " + e.getMessage(), e);
        }
    }

    public ExecutionResult execute(String slugOrId, String message, ExecuteOptions opts) {
        String agentId = resolveAgentId(slugOrId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("message", message);
        body.put("stream", false);
        body.put("wait", true);
        body.put("wait_timeout_seconds", opts.waitTimeoutSeconds());
        if (opts.context() != null) body.put("context", opts.context());
        String json = toJson(body);
        HttpRequest req = authHeaders(HttpRequest.newBuilder()
            .uri(URI.create(baseUrl + "/api/agents/" + agentId + "/execute"))
            .timeout(timeout)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json)), opts.actingSubject())
            .build();
        HttpResponse<String> resp;
        try {
            resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        } catch (IOException | InterruptedException e) {
            throw new AbenixException("execute(" + slugOrId + ") failed: " + e.getMessage(), e);
        }
        if (resp.statusCode() >= 400) {
            throw new AbenixException("execute(" + slugOrId + ") HTTP " + resp.statusCode()
                + " — " + truncate(resp.body(), 400));
        }
        JsonNode root = parse(resp.body());
        JsonNode data = root.has("data") ? root.get("data") : root;
        try {
            return JSON.treeToValue(data, ExecutionResult.class);
        } catch (IOException e) {
            throw new AbenixException("Bad execute response shape: " + e.getMessage(), e);
        }
    }

    public WatchStream watch(String executionId) {
        String url = baseUrl + "/api/executions/" + Objects.requireNonNull(executionId) + "/watch";
        Map<String, String> headers = new HashMap<>();
        headers.put("X-API-Key", apiKey);
        headers.put("Accept", "text/event-stream");
        headers.put("Cache-Control", "no-cache");
        if (defaultActingSubject != null) headers.putAll(defaultActingSubject.toHeader());
        return new SseWatchStream(http, URI.create(url), headers, JSON);
    }

    // ──────────────────────────── Internals ────────────────────────────

    private String resolveAgentId(String slugOrId) {
        // A well-formed UUID skips the lookup — same rule the Python
        // SDK uses. Anything else is resolved via /api/agents?search=
        if (slugOrId != null && slugOrId.length() == 36 && slugOrId.chars().filter(c -> c == '-').count() == 4) {
            return slugOrId;
        }
        try {
            // Fast path — search endpoint matches on name/description/slug
            // (depending on the Abenix version). One round-trip for the
            // common case.
            String fast = fetchAgentsPage("search=" + urlEncode(slugOrId) + "&limit=5");
            String hit = findSlugMatch(fast, slugOrId);
            if (hit != null) return hit;

            // Fallback — paginate the full catalog. Keeps the SDK working
            // against older API versions whose search field only matches
            // name/description. Mirrors the Python SDK's behavior.
            int offset = 0;
            while (true) {
                String page = fetchAgentsPage("limit=100&offset=" + offset);
                JsonNode list = parse(page).path("data");
                for (JsonNode a : list) {
                    if (slugOrId.equals(a.path("slug").asText()) || slugOrId.equals(a.path("id").asText())) {
                        return a.path("id").asText();
                    }
                }
                if (!list.isArray() || list.size() < 100) break;
                offset += 100;
            }
            throw new AbenixException("No agent matched slug: " + slugOrId);
        } catch (IOException | InterruptedException e) {
            throw new AbenixException("Agent lookup failed: " + e.getMessage(), e);
        }
    }

    private String fetchAgentsPage(String query) throws IOException, InterruptedException {
        HttpRequest req = authHeaders(HttpRequest.newBuilder()
            .uri(URI.create(baseUrl + "/api/agents?" + query))
            .timeout(timeout)
            .GET(), defaultActingSubject)
            .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() >= 400) {
            throw new AbenixException("Agent lookup failed: HTTP " + resp.statusCode());
        }
        return resp.body();
    }

    private String findSlugMatch(String json, String slugOrId) {
        JsonNode list = parse(json).path("data");
        for (JsonNode a : list) {
            if (slugOrId.equals(a.path("slug").asText()) || slugOrId.equals(a.path("id").asText())) {
                return a.path("id").asText();
            }
        }
        return null;
    }

    private HttpRequest.Builder authHeaders(HttpRequest.Builder b, ActingSubject subject) {
        b.header("X-API-Key", apiKey);
        ActingSubject subj = subject != null ? subject : defaultActingSubject;
        if (subj != null) subj.toHeader().forEach(b::header);
        return b;
    }

    private static String toJson(Object o) {
        try { return JSON.writeValueAsString(o); }
        catch (IOException e) { throw new AbenixException("JSON encode failed: " + e.getMessage(), e); }
    }

    private static JsonNode parse(String s) {
        try { return JSON.readTree(s); }
        catch (IOException e) { throw new AbenixException("JSON parse failed: " + e.getMessage(), e); }
    }

    private static String urlEncode(String s) {
        return java.net.URLEncoder.encode(s, java.nio.charset.StandardCharsets.UTF_8);
    }

    private static String stripTrailingSlash(String s) {
        return s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
    }

    private static String truncate(String s, int n) {
        if (s == null) return "";
        return s.length() <= n ? s : s.substring(0, n) + "…";
    }

    @Override
    public void close() {
        // HttpClient has no explicit close in JDK 21; the daemon threads
        // shut down when the JVM exits. We keep the AutoCloseable for
        // future-proofing and for idiomatic try-with-resources.
    }

    public static final class Builder {
        private String baseUrl = "http://localhost:8000";
        private String apiKey;
        private Duration timeout = Duration.ofSeconds(600);
        private ActingSubject actingSubject;

        public Builder baseUrl(String v) { this.baseUrl = v; return this; }
        public Builder apiKey(String v) { this.apiKey = v; return this; }
        public Builder timeout(Duration v) { this.timeout = v; return this; }
        public Builder actingSubject(ActingSubject v) { this.actingSubject = v; return this; }

        public Abenix build() { return new Abenix(this); }
    }

    public record ExecuteOptions(
        int waitTimeoutSeconds,
        Map<String, Object> context,
        ActingSubject actingSubject
    ) {
        public static ExecuteOptions defaults() {
            return new ExecuteOptions(600, null, null);
        }

        public static ExecuteOptions withContext(Map<String, Object> ctx) {
            return new ExecuteOptions(600, ctx, null);
        }

        public ExecuteOptions actingAs(ActingSubject subj) {
            return new ExecuteOptions(waitTimeoutSeconds, context, subj);
        }

        public ExecuteOptions waitTimeout(int seconds) {
            return new ExecuteOptions(seconds, context, actingSubject);
        }
    }
}
