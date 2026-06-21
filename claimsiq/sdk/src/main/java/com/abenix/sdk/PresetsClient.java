package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Per-tenant labelled (tool, default_args) bundles. Mirrors the Python
 * {@code PresetsClient}: list / get / upsert / delete / run.
 */
public final class PresetsClient {

    private final HttpKit kit;

    PresetsClient(HttpKit kit) { this.kit = kit; }

    public List<Map<String, Object>> list(String toolSlug, String uiGroup, String assetClass) {
        Map<String, Object> params = HttpKit.mapOfNonNull(
            "tool_slug", toolSlug,
            "ui_group", uiGroup,
            "asset_class", assetClass
        );
        JsonNode root = kit.getJson("/api/tool-presets", params, null);
        JsonNode arr = root != null && root.isArray() ? root : kit.dataOrRoot(root);
        List<Map<String, Object>> out = new ArrayList<>();
        if (arr != null && arr.isArray()) {
            for (JsonNode row : arr) out.add(asMap(row));
        }
        return out;
    }

    public List<Map<String, Object>> list() { return list(null, null, null); }

    public Map<String, Object> get(String slug) {
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/tool-presets/" + slug, null));
        return asMap(data);
    }

    public Map<String, Object> upsert(Map<String, Object> body) {
        JsonNode data = kit.dataOrRoot(kit.postJson("/api/tool-presets", body, null));
        return asMap(data);
    }

    public Map<String, Object> delete(String slug) {
        JsonNode data = kit.dataOrRoot(kit.deleteJson("/api/tool-presets/" + slug, null));
        return asMap(data);
    }

    public Map<String, Object> run(String slug, Map<String, Object> arguments, Map<String, Object> config) {
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "arguments", arguments == null ? Map.of() : arguments,
            "config", config == null ? Map.of() : config
        );
        JsonNode data = kit.dataOrRoot(kit.postJson("/api/tool-presets/" + slug + "/run", body, null));
        return asMap(data);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) return Map.of();
        return HttpKit.JSON.convertValue(n, Map.class);
    }
}
