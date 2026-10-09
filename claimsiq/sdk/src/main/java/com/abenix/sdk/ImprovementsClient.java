package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Fixes proposed from an agent's lessons, their proof, approval and watch. */
public final class ImprovementsClient {

    private final HttpKit kit;

    ImprovementsClient(HttpKit kit) { this.kit = kit; }

    /** Proposals you may see, newest first. agentId and state may be null. */
    public List<Map<String, Object>> list(String agentId, String state, int limit) {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("limit", limit > 0 ? limit : 50);
        if (agentId != null) q.put("agent_id", agentId);
        if (state != null) q.put("state", state);
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/improvements/proposals", q, null));
        List<Map<String, Object>> out = new ArrayList<>();
        JsonNode items = data == null ? null : data.get("items");
        if (items != null && items.isArray()) {
            for (JsonNode n : items) out.add(asMap(n));
        }
        return out;
    }

    public List<Map<String, Object>> list() { return list(null, null, 50); }

    /** One proposal with its diff, proof, progress and watch result. */
    public Map<String, Object> get(String proposalId) {
        return asMap(kit.dataOrRoot(kit.getJson("/api/improvements/proposals/" + proposalId, null)));
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) return Map.of();
        return HttpKit.JSON.convertValue(n, Map.class);
    }
}
