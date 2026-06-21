package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Read-side access to the platform's ML model registry. */
public final class MLModelsClient {

    private final HttpKit kit;

    MLModelsClient(HttpKit kit) { this.kit = kit; }

    public List<Map<String, Object>> list() {
        JsonNode root = kit.getJson("/api/ml-models", null);
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
