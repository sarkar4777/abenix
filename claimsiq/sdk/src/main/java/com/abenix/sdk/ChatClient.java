package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Persistent multi-turn chat — the platform's chat history primitive.
 * Mirrors the Python {@code ChatClient}: create / list / get / send /
 * rename / archive / delete.
 */
public final class ChatClient {

    private final HttpKit kit;

    ChatClient(HttpKit kit) { this.kit = kit; }

    public Map<String, Object> create(
        String agentSlug, String agentId, String appSlug, String title, ActingSubject actAs
    ) {
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "agent_slug", agentSlug,
            "agent_id", agentId,
            "app_slug", appSlug,
            "title", title
        );
        JsonNode data = kit.dataOrRoot(kit.postJson("/api/conversations", body, actAs));
        return asMap(data);
    }

    public List<Map<String, Object>> list(
        String appSlug, String agentSlug, boolean archived, int limit, int offset, ActingSubject actAs
    ) {
        int per = limit <= 0 ? 50 : limit;
        int page = Math.max(1, (offset / Math.max(1, per)) + 1);
        Map<String, Object> params = HttpKit.mapOfNonNull(
            "per_page", per,
            "page", page,
            "archived", archived ? "true" : "false",
            "app_slug", appSlug,
            "agent_slug", agentSlug
        );
        JsonNode root = kit.getJson("/api/conversations", params, actAs);
        JsonNode arr = root != null && root.isArray() ? root : kit.dataOrRoot(root);
        List<Map<String, Object>> out = new ArrayList<>();
        if (arr != null && arr.isArray()) {
            for (JsonNode row : arr) out.add(asMap(row));
        }
        return out;
    }

    public Map<String, Object> get(String threadId, ActingSubject actAs) {
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/conversations/" + threadId, null, actAs));
        return asMap(data);
    }

    public Map<String, Object> send(
        String threadId, String content, String context, String agentSlug,
        List<Map<String, Object>> attachments, ActingSubject actAs
    ) {
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "content", content,
            "context", context,
            "agent_slug", agentSlug,
            "attachments", attachments
        );
        JsonNode data = kit.dataOrRoot(kit.postJson("/api/conversations/" + threadId + "/turn", body, actAs));
        return asMap(data);
    }

    public Map<String, Object> rename(String threadId, String title, ActingSubject actAs) {
        JsonNode data = kit.dataOrRoot(kit.putJson(
            "/api/conversations/" + threadId,
            HttpKit.mapOfNonNull("title", title), actAs));
        return asMap(data);
    }

    public Map<String, Object> archive(String threadId, boolean archived, ActingSubject actAs) {
        JsonNode data = kit.dataOrRoot(kit.putJson(
            "/api/conversations/" + threadId,
            HttpKit.mapOfNonNull("is_archived", archived), actAs));
        return asMap(data);
    }

    public Map<String, Object> delete(String threadId, ActingSubject actAs) {
        JsonNode data = kit.dataOrRoot(kit.deleteJson("/api/conversations/" + threadId, actAs));
        return asMap(data);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) return Map.of();
        return HttpKit.JSON.convertValue(n, Map.class);
    }
}
