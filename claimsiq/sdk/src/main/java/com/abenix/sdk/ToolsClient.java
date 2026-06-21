package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Tool catalogue + direct execution surface. Mirrors the Python
 * {@code ToolsClient}: {@code list()} / {@code catalog()} enumerate the
 * registered tools and {@code execute(slug, args, config)} runs a tool
 * directly, bypassing the agent loop.
 */
public final class ToolsClient {

    private final HttpKit kit;

    ToolsClient(HttpKit kit) { this.kit = kit; }

    public List<Map<String, Object>> list() {
        JsonNode root = kit.getJson("/api/tools", null);
        JsonNode arr = root != null && root.isArray() ? root
            : (root != null && root.has("data") ? root.get("data") : null);
        if (arr == null || !arr.isArray()) {
            // Fallback to {tools: [...]} shape.
            arr = root != null && root.has("tools") ? root.get("tools") : null;
        }
        List<Map<String, Object>> out = new ArrayList<>();
        if (arr != null && arr.isArray()) {
            for (JsonNode row : arr) out.add(asMap(row));
        }
        return out;
    }

    /** Alias for {@link #list()} — matches the Python helper. */
    public List<Map<String, Object>> catalog() { return list(); }

    public Map<String, Object> execute(String slug, Map<String, Object> arguments, Map<String, Object> config) {
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "arguments", arguments == null ? Map.of() : arguments,
            "config", config == null ? Map.of() : config
        );
        JsonNode data = kit.dataOrRoot(kit.postJson("/api/tools/" + slug + "/execute", body, null));
        return asMap(data);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) return Map.of();
        return HttpKit.JSON.convertValue(n, Map.class);
    }
}
