package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Knowledge Engine client — Cognify trigger, graph queries, hybrid
 * search. Mirrors the Python {@code KnowledgeClient}.
 */
public final class KnowledgeClient {

    private final HttpKit kit;

    KnowledgeClient(HttpKit kit) { this.kit = kit; }

    public Map<String, Object> cognify(
        String kbId,
        List<String> docIds,
        String model,
        int chunkSize,
        int chunkOverlap
    ) {
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "doc_ids", docIds,
            "model", model == null ? "claude-sonnet-4-5-20250929" : model,
            "chunk_size", chunkSize <= 0 ? 1000 : chunkSize,
            "chunk_overlap", chunkOverlap <= 0 ? 200 : chunkOverlap
        );
        JsonNode data = kit.dataOrRoot(kit.postJson("/api/knowledge-engines/" + kbId + "/cognify", body, null));
        return asMap(data);
    }

    public Map<String, Object> graphStats(String kbId) {
        JsonNode data = kit.dataOrRoot(kit.getJson("/api/knowledge-engines/" + kbId + "/graph-stats", null));
        return asMap(data);
    }

    public Map<String, Object> search(String kbId, String query, String mode, int topK, int graphDepth) {
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "query", query,
            "mode", mode == null ? "hybrid" : mode,
            "top_k", topK <= 0 ? 5 : topK,
            "graph_depth", graphDepth <= 0 ? 2 : graphDepth
        );
        JsonNode data = kit.dataOrRoot(kit.postJson("/api/knowledge-engines/" + kbId + "/search", body, null));
        return asMap(data);
    }

    public Map<String, Object> graph(String kbId, int limit) {
        JsonNode data = kit.dataOrRoot(kit.getJson(
            "/api/knowledge-engines/" + kbId + "/graph",
            HttpKit.mapOfNonNull("limit", limit <= 0 ? 100 : limit), null));
        return asMap(data);
    }

    public List<Map<String, Object>> cognifyJobs(String kbId) {
        JsonNode root = kit.getJson("/api/knowledge-engines/" + kbId + "/cognify-jobs", null);
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
