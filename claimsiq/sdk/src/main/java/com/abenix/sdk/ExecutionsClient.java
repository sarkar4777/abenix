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

    /** Past runs, newest first, each with trigger_kind, trigger_id, trigger_name and started_by. */
    public List<Map<String, Object>> list(ListOptions opts) {
        ListOptions o = opts == null ? ListOptions.empty() : opts;
        Map<String, Object> params = HttpKit.mapOfNonNull(
            "agent_id", o.agentId,
            "status", o.status,
            "trigger_kind", o.triggerKind == null || o.triggerKind.isEmpty() ? null : String.join(",", o.triggerKind),
            "trigger_id", o.triggerId,
            "search", o.search == null || o.search.isBlank() ? null : o.search,
            "limit", o.limit,
            "offset", o.offset
        );
        JsonNode arr = kit.dataOrRoot(kit.getJson("/api/executions", params, null));
        List<Map<String, Object>> out = new ArrayList<>();
        if (arr != null && arr.isArray()) {
            for (JsonNode row : arr) out.add(asMap(row));
        }
        return out;
    }

    public List<Map<String, Object>> list() { return list(ListOptions.empty()); }

    /** Filters for {@link #list(ListOptions)}. */
    public static final class ListOptions {
        public String agentId;
        public String status;
        public List<String> triggerKind;
        public String triggerId;
        public String search;
        public int limit = 20;
        public int offset = 0;

        public static ListOptions empty() { return new ListOptions(); }
        public ListOptions agentId(String v) { this.agentId = v; return this; }
        public ListOptions status(String v) { this.status = v; return this; }
        /** schedule, webhook, manual, event, source_watch, chat, api ... one or more */
        public ListOptions triggerKind(String... v) { this.triggerKind = List.of(v); return this; }
        public ListOptions triggerId(String v) { this.triggerId = v; return this; }
        public ListOptions search(String v) { this.search = v; return this; }
        public ListOptions limit(int v) { this.limit = v; return this; }
        public ListOptions offset(int v) { this.offset = v; return this; }
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
