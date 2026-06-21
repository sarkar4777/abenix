package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AgentsClientTest {

    private static final String CATALOG_JSON =
        "{\"data\":[" +
        "  {\"id\":\"a-1\",\"slug\":\"adjudicate-claim\",\"name\":\"Adjudicate\"}," +
        "  {\"id\":\"a-2\",\"slug\":\"triage\",\"name\":\"Triage\"}" +
        "]}";

    @Test
    void list_returns_two_agents_and_sends_api_key() throws Exception {
        try (MockServer s = new MockServer()) {
            s.on("/api/agents", 200, "application/json", CATALOG_JSON);
            Abenix forge = Abenix.builder()
                .baseUrl(s.baseUrl())
                .apiKey("secret-key")
                .timeout(Duration.ofSeconds(10))
                .build();
            List<Map<String, Object>> rows = forge.agents().list();
            assertEquals(2, rows.size());
            assertEquals("a-1", rows.get(0).get("id"));
            // Auth header was applied.
            assertEquals("secret-key", s.recorded().get(0).headers().getOrDefault("X-api-key", ""));
        }
    }

    @Test
    void findBySlug_filters_to_exact_match() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/agents", 200, "application/json", CATALOG_JSON);
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> hit = forge.agents().findBySlug("triage");
            assertNotNull(hit);
            assertEquals("a-2", hit.get("id"));
            assertNull(forge.agents().findBySlug("does-not-exist"));
        }
    }

    @Test
    void list_propagates_http_500_as_AbenixException() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/agents", 500, "application/json", "{\"error\":\"boom\"}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            AbenixException ex = assertThrows(AbenixException.class, () -> forge.agents().list());
            assertTrue(ex.getMessage().contains("HTTP 500"));
        }
    }
}
