package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.LinkedHashMap;
import java.util.Map;

/** Read the autonomy ladder: levels, track records and the actions behind them. */
public final class AutonomyClient {

    private final HttpKit kit;

    AutonomyClient(HttpKit kit) { this.kit = kit; }

    /** Counts, every grant, what is ready to promote, recent demotions and unmanaged actions. */
    public Map<String, Object> overview() {
        return asMap(kit.dataOrRoot(kit.getJson("/api/autonomy/overview", null)));
    }

    /** One grant with its next-step checklist, level history and chart points. */
    public Map<String, Object> grant(String grantId) {
        return asMap(kit.dataOrRoot(kit.getJson("/api/autonomy/grants/" + grantId, null)));
    }

    /** A page of the grant's actions, newest first. Pass next_before as before for the next page. */
    public Map<String, Object> grantActions(String grantId, String status, int limit, String before) {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("limit", limit > 0 ? limit : 50);
        if (status != null) q.put("status", status);
        if (before != null) q.put("before", before);
        return asMap(kit.dataOrRoot(kit.getJson("/api/autonomy/grants/" + grantId + "/actions", q, null)));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) return Map.of();
        return HttpKit.JSON.convertValue(n, Map.class);
    }
}
