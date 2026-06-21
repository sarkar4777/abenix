package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class KnowledgeClientTest {

    @Test
    void cognify_posts_chunk_params() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/knowledge-engines/kb-1/cognify", 200, "application/json",
                "{\"data\":{\"job_id\":\"job-7\",\"status\":\"queued\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> out = forge.knowledge()
                .cognify("kb-1", List.of("doc-1"), null, 800, 100);
            assertEquals("job-7", out.get("job_id"));
            String body = s.recorded().get(0).body();
            assertTrue(body.contains("\"chunk_size\":800"));
            assertTrue(body.contains("\"chunk_overlap\":100"));
            assertTrue(body.contains("doc-1"));
        }
    }

    @Test
    void search_returns_unwrapped_data() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/knowledge-engines/kb-1/search", 200, "application/json",
                "{\"data\":{\"hits\":[{\"score\":0.91}]}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> r = forge.knowledge().search("kb-1", "policy 23", "hybrid", 5, 2);
            assertTrue(r.containsKey("hits"));
        }
    }

    @Test
    void graphStats_propagates_500() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/knowledge-engines/kb-1/graph-stats", 500, "application/json",
                "{\"error\":\"neo4j down\"}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            AbenixException ex = assertThrows(AbenixException.class, () ->
                forge.knowledge().graphStats("kb-1"));
            assertTrue(ex.getMessage().contains("HTTP 500"));
        }
    }
}
