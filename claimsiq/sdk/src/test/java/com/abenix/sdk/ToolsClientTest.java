package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ToolsClientTest {

    @Test
    void list_unwraps_data_envelope() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/tools", 200, "application/json",
                "{\"data\":[{\"slug\":\"yahoo_finance\"},{\"slug\":\"sql_runner\"}]}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            List<Map<String, Object>> tools = forge.tools().list();
            assertEquals(2, tools.size());
            assertEquals("yahoo_finance", tools.get(0).get("slug"));
            // catalog() is the alias used by some app code; must return same.
            assertEquals(2, forge.tools().catalog().size());
        }
    }

    @Test
    void execute_posts_arguments_and_config_and_returns_data() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/tools/sql_runner/execute", 200, "application/json",
                "{\"data\":{\"rows\":[{\"col\":1}],\"rowcount\":1}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> out = forge.tools().execute("sql_runner",
                Map.of("query", "SELECT 1"), Map.of("readonly", true));
            assertEquals(1, out.get("rowcount"));
            // Verify the wire body had both arguments + config.
            String reqBody = s.recorded().get(0).body();
            assertTrue(reqBody.contains("SELECT 1"));
            assertTrue(reqBody.contains("readonly"));
        }
    }

    @Test
    void execute_propagates_4xx() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/tools/bad/execute", 400, "application/json",
                "{\"error\":\"bad slug\"}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            AbenixException ex = assertThrows(AbenixException.class, () ->
                forge.tools().execute("bad", Map.of(), Map.of()));
            assertTrue(ex.getMessage().contains("HTTP 400"));
        }
    }
}
