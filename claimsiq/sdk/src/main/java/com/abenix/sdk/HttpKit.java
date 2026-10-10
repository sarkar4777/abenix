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
        return getJson(path, params, subject, timeout);
    }

    JsonNode getJson(String path, Map<String, Object> params, ActingSubject subject, Duration requestTimeout) {
        String qs = encodeParams(params);
        URI uri = URI.create(baseUrl + path + (qs.isEmpty() ? "" : (path.contains("?") ? "&" : "?") + qs));
        HttpRequest req = authed(HttpRequest.newBuilder(uri).GET(), subject).timeout(requestTimeout).build();
        return send(req);
    }

    /**
     * Repeats a server long-poll until {@code done} or the timeout. The call gets the seconds for this
     * round. A busy answer (429, 502, 503, 504) or a dropped connection is retried, anything else throws.
     */
    static <T> T longPoll(int timeoutSeconds, java.util.function.IntFunction<T> call, java.util.function.Predicate<T> done) {
        long deadline = System.nanoTime() + Math.max(1, timeoutSeconds) * 1_000_000_000L;
        T last = null;
        while (true) {
            long leftMs = (deadline - System.nanoTime()) / 1_000_000L;
            if (leftMs <= 0) return last;
            int chunk = (int) Math.max(1, Math.min(120, leftMs / 1000));
            try {
                last = call.apply(chunk);
                if (last != null && done.test(last)) return last;
            } catch (AbenixException e) {
                if (!retryable(e)) throw e;
                pause(Math.min(2000, leftMs));
            }
        }
    }

    private static boolean retryable(AbenixException e) {
        int s = e.status();
        if (s == 429 || s == 502 || s == 503 || s == 504) return true;
        Throwable c = e.getCause();
        return s == 0 && c instanceof IOException && !(c instanceof com.fasterxml.jackson.core.JsonProcessingException);
    }

    private static void pause(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            throw new AbenixException("wait interrupted", ie);
        }
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

    /** A multipart/form-data upload of one file under the field name {@code file}. */
    JsonNode postFile(String path, String filename, byte[] content, String contentType, ActingSubject subject) {
        String boundary = "abenix-" + java.util.UUID.randomUUID();
        String safe = filename.replace("\"", "");
        byte[] head = ("--" + boundary + "\r\n"
            + "Content-Disposition: form-data; name=\"file\"; filename=\"" + safe + "\"\r\n"
            + "Content-Type: " + (contentType == null ? "application/octet-stream" : contentType) + "\r\n\r\n")
            .getBytes(StandardCharsets.UTF_8);
        byte[] tail = ("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8);
        byte[] body = new byte[head.length + content.length + tail.length];
        System.arraycopy(head, 0, body, 0, head.length);
        System.arraycopy(content, 0, body, head.length, content.length);
        System.arraycopy(tail, 0, body, head.length + content.length, tail.length);
        HttpRequest req = authed(HttpRequest.newBuilder(URI.create(baseUrl + path))
            .header("Content-Type", "multipart/form-data; boundary=" + boundary)
            .POST(HttpRequest.BodyPublishers.ofByteArray(body)), subject).build();
        return send(req);
    }

    private JsonNode send(HttpRequest req) {
        try {
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() >= 400) {
                throw error(req.method() + " " + req.uri().getPath(), resp.statusCode(), resp.body());
            }
            return JSON.readTree(resp.body() == null || resp.body().isBlank() ? "{}" : resp.body());
        } catch (IOException | InterruptedException e) {
            throw new AbenixException(req.method() + " " + req.uri().getPath() + " failed: " + e.getMessage(), e);
        }
    }

    /** The platform's error envelope as an exception carrying status and error_code. */
    static AbenixException error(String what, int status, String body) {
        String code = null;
        String message = null;
        try {
            JsonNode root = JSON.readTree(body == null || body.isBlank() ? "{}" : body);
            JsonNode err = root.has("error") ? root.get("error") : root.get("detail");
            if (err != null && err.isObject()) {
                code = err.hasNonNull("error_code") ? err.get("error_code").asText() : null;
                message = err.hasNonNull("message") ? err.get("message").asText() : null;
            } else if (err != null && err.isTextual()) {
                message = err.asText();
            }
        } catch (IOException ignored) {
            // not JSON, keep the raw body in the message
        }
        String detail = message != null ? message : truncate(body, 400);
        return new AbenixException(what + " HTTP " + status + " — " + detail, status, code);
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
