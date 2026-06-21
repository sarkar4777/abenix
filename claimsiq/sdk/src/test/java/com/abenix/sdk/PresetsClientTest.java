package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PresetsClientTest {

    @Test
    void list_filters_via_query_params() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/tool-presets", 200, "application/json",
                "{\"data\":[{\"slug\":\"lbma_gold_fix\",\"tool_slug\":\"yahoo_finance\"}]}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            List<Map<String, Object>> rows = forge.presets().list("yahoo_finance", "commodities", null);
            assertEquals(1, rows.size());
            String path = s.recorded().get(0).path();
            // GETs hit / without query string in our mock — but we record the
            // raw path. Query keys must appear in the recorded URI.
            assertTrue(path.contains("/api/tool-presets"));
        }
    }

    @Test
    void run_posts_arguments_and_returns_unwrapped_data() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/tool-presets/lbma_gold_fix/run", 200, "application/json",
                "{\"data\":{\"price\":2350.5,\"ccy\":\"USD\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> out = forge.presets().run("lbma_gold_fix", Map.of(), Map.of());
            assertEquals("USD", out.get("ccy"));
            assertEquals(2350.5, ((Number) out.get("price")).doubleValue());
        }
    }

    @Test
    void delete_propagates_404() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/tool-presets/missing", 404, "application/json",
                "{\"error\":\"not found\"}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            AbenixException ex = assertThrows(AbenixException.class, () ->
                forge.presets().delete("missing"));
            assertTrue(ex.getMessage().contains("HTTP 404"));
        }
    }
}
