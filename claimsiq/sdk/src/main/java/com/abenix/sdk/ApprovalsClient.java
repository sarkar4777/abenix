package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Client for the HITL approvals surface — list, get, sign off, and wait on
 * pending approval rows. Uses the same X-API-Key + ActingSubject auth as the
 * parent {@link Abenix} client.
 */
public final class ApprovalsClient {

    private static final ObjectMapper JSON = new ObjectMapper();

    private final String baseUrl;
    private final String apiKey;
    private final HttpClient http;
    private final ActingSubject defaultActingSubject;
    private final Duration timeout;

    ApprovalsClient(
        String baseUrl,
        String apiKey,
        HttpClient http,
        ActingSubject defaultActingSubject,
        Duration timeout
    ) {
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
        this.http = http;
        this.defaultActingSubject = defaultActingSubject;
        this.timeout = timeout;
    }

    public List<Approval> list(ListOptions opts) {
        StringBuilder qs = new StringBuilder();
        if (opts != null) {
            if (opts.status != null) append(qs, "status", opts.status);
            if (opts.executionId != null) append(qs, "execution_id", opts.executionId);
            if (opts.agentId != null) append(qs, "agent_id", opts.agentId);
            if (opts.kind != null) append(qs, "kind", opts.kind);
            if (opts.limit > 0) append(qs, "limit", String.valueOf(opts.limit));
        }
        URI uri = URI.create(baseUrl + "/api/approvals" + (qs.length() > 0 ? "?" + qs : ""));
        JsonNode data = sendForData(HttpRequest.newBuilder(uri).GET());
        if (!data.isArray()) return List.of();
        List<Approval> out = new ArrayList<>(data.size());
        for (JsonNode row : data) out.add(treeToValue(row, Approval.class));
        return out;
    }

    public Approval get(String approvalId) {
        URI uri = URI.create(baseUrl + "/api/approvals/" + approvalId);
        return treeToValue(sendForData(HttpRequest.newBuilder(uri).GET()), Approval.class);
    }

    /** Create an approval row directly from app code (e.g. a UI button click). */
    public Approval create(
        String title,
        Map<String, Object> payload,
        int requiredSignoffs,
        int expiresSeconds,
        String gateKind,
        String clientToken
    ) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("title", title);
        body.put("payload", payload == null ? Map.of() : payload);
        body.put("required_signoffs", requiredSignoffs > 0 ? requiredSignoffs : 1);
        body.put("expires_seconds", expiresSeconds > 0 ? expiresSeconds : 86400);
        if (gateKind != null) body.put("gate_kind", gateKind);
        if (clientToken != null) body.put("client_token", clientToken);
        URI uri = URI.create(baseUrl + "/api/approvals");
        return treeToValue(
            sendForData(HttpRequest.newBuilder(uri)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(toJson(body)))),
            Approval.class
        );
    }

    public Approval signoff(String approvalId, String decision, String reason, String clientToken) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("decision", decision);
        body.put("reason", reason == null ? "" : reason);
        if (clientToken != null) body.put("client_token", clientToken);
        URI uri = URI.create(baseUrl + "/api/approvals/" + approvalId + "/signoff");
        return treeToValue(
            sendForData(HttpRequest.newBuilder(uri)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(toJson(body)))),
            Approval.class
        );
    }

    public Approval approve(String approvalId, String reason) {
        return signoff(approvalId, "approve", reason, null);
    }

    public Approval deny(String approvalId, String reason) {
        return signoff(approvalId, "deny", reason, null);
    }

    /**
     * Block until the approval leaves pending status or the timeout fires.
     * Uses the server's /wait long-poll under the hood.
     */
    public Approval waitFor(String approvalId, int timeoutSeconds) {
        int deadline = Math.max(1, timeoutSeconds);
        int elapsed = 0;
        Approval last = null;
        while (elapsed < deadline) {
            int chunk = Math.min(120, deadline - elapsed);
            URI uri = URI.create(baseUrl + "/api/approvals/" + approvalId + "/wait?timeout_seconds=" + chunk);
            last = treeToValue(sendForData(HttpRequest.newBuilder(uri).GET()), Approval.class);
            if (last != null && last.status() != null && !"pending".equals(last.status())) {
                return last;
            }
            elapsed += chunk;
        }
        return last;
    }

    /** Set or clear the tenant-level approval webhook URL. Admin/owner only. */
    public Map<String, Object> configureWebhook(String url, String secret) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("url", url);
        body.put("secret", secret);
        URI uri = URI.create(baseUrl + "/api/approvals/webhooks");
        JsonNode data = sendForData(HttpRequest.newBuilder(uri)
            .header("Content-Type", "application/json")
            .PUT(HttpRequest.BodyPublishers.ofString(toJson(body))));
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> as = JSON.convertValue(data, Map.class);
            return as;
        } catch (Exception e) {
            return Map.of();
        }
    }

    public static final class ListOptions {
        public String status;
        public String executionId;
        public String agentId;
        public String kind;
        public int limit = 200;

        public static ListOptions empty() { return new ListOptions(); }
        public ListOptions status(String s) { this.status = s; return this; }
        public ListOptions executionId(String s) { this.executionId = s; return this; }
        public ListOptions agentId(String s) { this.agentId = s; return this; }
        public ListOptions kind(String s) { this.kind = s; return this; }
        public ListOptions limit(int n) { this.limit = n; return this; }
    }

    private void append(StringBuilder qs, String k, String v) {
        if (qs.length() > 0) qs.append("&");
        qs.append(URLEncoder.encode(k, StandardCharsets.UTF_8))
          .append("=")
          .append(URLEncoder.encode(v, StandardCharsets.UTF_8));
    }

    private JsonNode sendForData(HttpRequest.Builder rb) {
        rb.header("X-API-Key", apiKey).timeout(timeout);
        if (defaultActingSubject != null) defaultActingSubject.toHeader().forEach(rb::header);
        try {
            HttpResponse<String> resp = http.send(rb.build(), HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw new AbenixException("approvals HTTP " + resp.statusCode() + " — " + resp.body());
            }
            JsonNode root = JSON.readTree(resp.body());
            return root.has("data") ? root.get("data") : root;
        } catch (IOException | InterruptedException e) {
            throw new AbenixException("approvals call failed: " + e.getMessage(), e);
        }
    }

    private static <T> T treeToValue(JsonNode node, Class<T> klass) {
        try {
            return JSON.treeToValue(node, klass);
        } catch (IOException e) {
            throw new AbenixException("Bad approval response shape: " + e.getMessage(), e);
        }
    }

    private static String toJson(Object o) {
        try { return JSON.writeValueAsString(o); }
        catch (IOException e) { throw new AbenixException("JSON encode failed: " + e.getMessage(), e); }
    }
}
