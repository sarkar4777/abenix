package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ExecutionsAndMlClientTest {

    @Test
    void executions_live_returns_list() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/executions/live", 200, "application/json",
                "{\"data\":[{\"execution_id\":\"e-1\",\"agent_name\":\"Adjudicate\"}]}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            List<Map<String, Object>> rows = forge.executions().live();
            assertEquals(1, rows.size());
            assertEquals("e-1", rows.get(0).get("execution_id"));
        }
    }

    @Test
    void executions_tree_proxies_to_correct_path() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/executions/tree/e-1", 200, "application/json",
                "{\"data\":{\"root\":{\"id\":\"e-1\",\"children\":[]}}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> tree = forge.executions().tree("e-1");
            assertTrue(tree.containsKey("root"));
        }
    }

    @Test
    void executions_replay_propagates_404() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/executions/missing/replay", 404, "application/json",
                "{\"error\":\"not found\"}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            AbenixException ex = assertThrows(AbenixException.class, () ->
                forge.executions().replay("missing"));
            assertTrue(ex.getMessage().contains("HTTP 404"));
        }
    }

    @Test
    void ml_models_list_returns_rows() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/ml-models", 200, "application/json",
                "{\"data\":[{\"id\":\"m-1\",\"name\":\"Severity\"}]}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            List<Map<String, Object>> rows = forge.mlModels().list();
            assertEquals("Severity", rows.get(0).get("name"));
        }
    }
}
