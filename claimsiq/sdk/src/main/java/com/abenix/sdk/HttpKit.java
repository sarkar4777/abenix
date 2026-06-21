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
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Shared HTTP plumbing for every typed sub-client. Centralises the
 * X-API-Key + X-Abenix-Subject header injection so each new client
 * doesn't re-implement the same six lines.
 */
final class HttpKit {

    static final ObjectMapper JSON = new ObjectMapper();

    private final String baseUrl;
    private final String apiKey;
    private final HttpClient http;
    private final ActingSubject defaultSubject;
    private final Duration timeout;

    HttpKit(String baseUrl, String apiKey, HttpClient http, ActingSubject defaultSubject, Duration timeout) {
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
        this.http = http;
        this.defaultSubject = defaultSubject;
        this.timeout = timeout;
    }

    String baseUrl() { return baseUrl; }
    HttpClient http() { return http; }
    Duration timeout() { return timeout; }

    HttpRequest.Builder authed(HttpRequest.Builder b, ActingSubject subject) {
        b.header("X-API-Key", apiKey).timeout(timeout);
        ActingSubject s = subject != null ? subject : defaultSubject;
        if (s != null) s.toHeader().forEach(b::header);
        return b;
    }

    JsonNode getJson(String path, ActingSubject subject) {
        return getJson(path, Map.of(), subject);
    }

    JsonNode getJson(String path, Map<String, Object> params, ActingSubject subject) {
        String qs = encodeParams(params);
        URI uri = URI.create(baseUrl + path + (qs.isEmpty() ? "" : (path.contains("?") ? "&" : "?") + qs));
        HttpRequest req = authed(HttpRequest.newBuilder(uri).GET(), subject).build();
        return send(req);
    }

    JsonNode postJson(String path, Object body, ActingSubject subject) {
        String json = encode(body == null ? Map.of() : body);
        HttpRequest req = authed(HttpRequest.newBuilder(URI.create(baseUrl + path))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json)), subject).build();
        return send(req);
    }

    JsonNode putJson(String path, Object body, ActingSubject subject) {
        String json = encode(body == null ? Map.of() : body);
        HttpRequest req = authed(HttpRequest.newBuilder(URI.create(baseUrl + path))
            .header("Content-Type", "application/json")
            .PUT(HttpRequest.BodyPublishers.ofString(json)), subject).build();
        return send(req);
    }

    JsonNode deleteJson(String path, ActingSubject subject) {
        HttpRequest req = authed(HttpRequest.newBuilder(URI.create(baseUrl + path)).DELETE(), subject).build();
        return send(req);
    }

    /** Returns the {@code data} sub-tree if the envelope has one, otherwise the root. */
    JsonNode dataOrRoot(JsonNode root) {
        return root != null && root.has("data") ? root.get("data") : root;
    }

    private JsonNode send(HttpRequest req) {
        try {
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw new AbenixException(req.method() + " " + req.uri().getPath()
                    + " HTTP " + resp.statusCode() + " — " + truncate(resp.body(), 400));
            }
            return JSON.readTree(resp.body() == null || resp.body().isBlank() ? "{}" : resp.body());
        } catch (IOException | InterruptedException e) {
            throw new AbenixException(req.method() + " " + req.uri().getPath() + " failed: " + e.getMessage(), e);
        }
    }

    static String encode(Object o) {
        try { return JSON.writeValueAsString(o); }
        catch (IOException e) { throw new AbenixException("JSON encode failed: " + e.getMessage(), e); }
    }

    static String encodeParams(Map<String, Object> params) {
        if (params == null || params.isEmpty()) return "";
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, Object> e : params.entrySet()) {
            if (e.getValue() == null) continue;
            if (sb.length() > 0) sb.append('&');
            sb.append(URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8))
              .append('=')
              .append(URLEncoder.encode(String.valueOf(e.getValue()), StandardCharsets.UTF_8));
        }
        return sb.toString();
    }

    static Map<String, Object> mapOfNonNull(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            Object v = kv[i + 1];
            if (v != null) m.put((String) kv[i], v);
        }
        return m;
    }

    private static String truncate(String s, int n) {
        if (s == null) return "";
        return s.length() <= n ? s : s.substring(0, n) + "…";
    }
}
