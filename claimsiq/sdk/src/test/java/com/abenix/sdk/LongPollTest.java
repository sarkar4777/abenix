package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class LongPollTest {

    private static MockServer busyThen(MockServer s, String path, String body, AtomicInteger calls) {
        return s.onDynamic(path, ex -> {
            boolean first = calls.getAndIncrement() == 0;
            byte[] out = (first ? "{\"error\":{\"message\":\"The service is busy, retry shortly.\",\"code\":503}}" : body)
                .getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            ex.sendResponseHeaders(first ? 503 : 200, out.length);
            ex.getResponseBody().write(out);
            ex.close();
        });
    }

    @Test
    void approval_wait_rides_out_a_busy_server() throws IOException {
        try (MockServer s = new MockServer()) {
            AtomicInteger calls = new AtomicInteger();
            busyThen(s, "/api/approvals/p1/wait", "{\"data\":{\"id\":\"p1\",\"status\":\"approved\"}}", calls);
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Approval a = forge.approvals().waitFor("p1", 600);
            assertEquals("approved", a.status());
            assertEquals(2, calls.get());
        }
    }

    @Test
    void action_wait_rides_out_a_busy_server() throws IOException {
        try (MockServer s = new MockServer()) {
            AtomicInteger calls = new AtomicInteger();
            busyThen(s, "/api/autonomy/actions/a1/wait", "{\"data\":{\"action_id\":\"a1\",\"decision\":\"run\"}}", calls);
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            assertTrue(forge.actions().waitFor("a1", 600).shouldRun());
            assertEquals(2, calls.get());
        }
    }

    @Test
    void a_real_refusal_still_throws() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/approvals/nope/wait", 404, "application/json", "{\"error\":{\"message\":\"Approval not found\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            AbenixException e = assertThrows(AbenixException.class, () -> forge.approvals().waitFor("nope", 5));
            assertEquals(404, e.status());
        }
    }
}
