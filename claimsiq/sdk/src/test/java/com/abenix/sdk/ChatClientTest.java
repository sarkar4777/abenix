package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ChatClientTest {

    @Test
    void create_thread_returns_unwrapped_row() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/conversations", 200, "application/json",
                "{\"data\":{\"id\":\"th-1\",\"title\":\"Claim CLM-001\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> th = forge.chat().create(
                "adjudicate-claim", null, "claimsiq", "Claim CLM-001", null);
            assertEquals("th-1", th.get("id"));
            String body = s.recorded().get(0).body();
            assertTrue(body.contains("adjudicate-claim"));
            assertTrue(body.contains("claimsiq"));
        }
    }

    @Test
    void send_appends_turn_and_returns_pair() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/conversations/th-1/turn", 200, "application/json",
                "{\"data\":{\"user_message\":{\"id\":\"m-u\"},\"assistant_message\":{\"id\":\"m-a\",\"content\":\"hi\"}}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> out = forge.chat().send("th-1", "hello", null, null, null, null);
            Map<?, ?> assistant = (Map<?, ?>) out.get("assistant_message");
            assertEquals("hi", assistant.get("content"));
        }
    }

    @Test
    void delete_propagates_403() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/conversations/th-1", 403, "application/json",
                "{\"error\":\"forbidden\"}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            AbenixException ex = assertThrows(AbenixException.class, () ->
                forge.chat().delete("th-1", null));
            assertTrue(ex.getMessage().contains("HTTP 403"));
        }
    }
}
