package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Read-side helpers for the executions surface. Wraps the
 * {@code /api/executions/*} endpoints the Python SDK exposes as
 * {@code ExecutionsClient}.
 */
public final class ExecutionsClient {

    private final HttpKit kit;

    ExecutionsClient(HttpKit kit) { this.kit = kit; }

    public List<Map<String, Object>> live() {
        JsonNode root = kit.getJson("/api/executions/live", null);
        JsonNode arr = root != null && root.isArray() ? root : kit.dataOrRoot(root);
        List<Map<String, Object>> out = new ArrayList<>();
        if (arr != null && arr.isArray()) {
            for (JsonNode row : arr) out.add(asMap(row));
        }
        return out;
    }

    public Map<String, Object> get(String executionId) {
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/executions/" + executionId, null));
        return asMap(data);
    }

    public Map<String, Object> replay(String executionId) {
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/executions/" + executionId + "/replay", null));
        return asMap(data);
    }

    public Map<String, Object> tree(String executionId) {
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/executions/tree/" + executionId, null));
        return asMap(data);
    }

    public List<Map<String, Object>> pendingApprovals() {
        JsonNode root = kit.getJson("/api/executions/approvals", null);
        JsonNode arr = root != null && root.isArray() ? root : kit.dataOrRoot(root);
        List<Map<String, Object>> out = new ArrayList<>();
        if (arr != null && arr.isArray()) {
            for (JsonNode row : arr) out.add(asMap(row));
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) return Map.of();
        return HttpKit.JSON.convertValue(n, Map.class);
    }
}
