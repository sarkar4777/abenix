package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Read-side agent registry. Mirrors the Python {@code AgentsClient}. */
public final class AgentsClient {

    private final HttpKit kit;

    AgentsClient(HttpKit kit) { this.kit = kit; }

    public List<Map<String, Object>> list() {
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/agents", null));
        return asListOfMap(data);
    }

    public Map<String, Object> get(String agentId) {
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/agents/" + agentId, null));
        return asMap(data);
    }

    /** Returns null when no agent with that slug exists. */
    public Map<String, Object> findBySlug(String slug) {
        JsonNode root = kit.getJson("/api/agents",
            HttpKit.mapOfNonNull("search", slug, "limit", 10), null);
        JsonNode arr = kit.dataOrRoot(root);
        if (arr != null && arr.isArray()) {
            for (JsonNode a : arr) {
                if (slug.equals(a.path("slug").asText(null))) {
                    return asMap(a);
                }
            }
        }
        return null;
    }

    /** Exact lookup by slug, null when there is no such agent. */
    public Map<String, Object> bySlug(String slug) {
        try {
            return asMap(kit.dataOrRoot(kit.getJson(
                "/api/agents/by-slug/" + java.net.URLEncoder.encode(slug, java.nio.charset.StandardCharsets.UTF_8), null)));
        } catch (AbenixException e) {
            if (e.status() == 404) return null;
            throw e;
        }
    }

    /** Create an agent or pipeline. Takes the same fields as POST /api/agents, including model_config. */
    public Map<String, Object> create(Map<String, Object> body) {
        return asMap(kit.dataOrRoot(kit.postJson("/api/agents", body, null)));
    }

    private static List<Map<String, Object>> asListOfMap(JsonNode n) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (n != null && n.isArray()) {
            for (JsonNode row : n) out.add(asMap(row));
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) return Map.of();
        return HttpKit.JSON.convertValue(n, Map.class);
    }
}
