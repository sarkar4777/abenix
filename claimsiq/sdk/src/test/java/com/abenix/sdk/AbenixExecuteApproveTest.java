package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Sanity-check the two execution-level HITL helpers added for Python
 * parity: {@code approve(executionId, gateId, comment)} and
 * {@code reject(executionId, gateId, comment)}. Both POST to
 * {@code /api/executions/{id}/approve?gate_id=...} with a decision
 * field in the body — the API differentiates by that decision value.
 */
class AbenixExecuteApproveTest {

    private static final String EXEC_RESPONSE =
        "{\"data\":{\"execution_id\":\"e-1\",\"status\":\"completed\",\"output\":\"ok\"," +
        "\"input_tokens\":1,\"output_tokens\":2,\"cost\":0.01,\"duration_ms\":10,\"model\":\"haiku\"}}";

    @Test
    void execute_returns_terminal_ExecutionResult() throws IOException {
        try (MockServer s = new MockServer()) {
            // Resolver hits /api/agents?search=…&limit=5 before /execute.
            s.on("/api/agents", 200, "application/json",
                "{\"data\":[{\"id\":\"a-1\",\"slug\":\"my-agent\"}]}");
            s.on("/api/agents/a-1/execute", 200, "application/json", EXEC_RESPONSE);
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            ExecutionResult r = forge.execute("my-agent", "hello");
            assertEquals("e-1", r.executionId());
            assertEquals("completed", r.status());
        }
    }

    @Test
    void approve_posts_decision_approved_with_gate_id_in_query() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/executions/e-1/approve", 200, "application/json", "{\"ok\":true}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            forge.approve("e-1", "gate-1", "looks good");
            List<MockServer.Recorded> log = s.recorded();
            assertEquals(1, log.size());
            assertEquals("POST", log.get(0).method());
            assertTrue(log.get(0).path().startsWith("/api/executions/e-1/approve"),
                "approve POSTs to the /approve endpoint");
            assertTrue(log.get(0).body().contains("\"decision\":\"approved\""));
            assertTrue(log.get(0).body().contains("looks good"));
        }
    }

    @Test
    void reject_posts_decision_rejected() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/executions/e-1/approve", 200, "application/json", "{\"ok\":true}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            forge.reject("e-1", "gate-1", "nope");
            assertTrue(s.recorded().get(0).body().contains("\"decision\":\"rejected\""));
        }
    }

    @Test
    void approve_propagates_5xx_as_AbenixException() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/executions/e-1/approve", 500, "application/json", "{\"error\":\"boom\"}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            AbenixException ex = assertThrows(AbenixException.class, () ->
                forge.approve("e-1", "gate-1", ""));
            assertTrue(ex.getMessage().contains("HTTP 500"));
        }
    }

    @Test
    void execute_carries_ActingSubject_json_header() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/agents", 200, "application/json",
                "{\"data\":[{\"id\":\"a-1\",\"slug\":\"my-agent\"}]}");
            s.on("/api/agents/a-1/execute", 200, "application/json", EXEC_RESPONSE);
            Abenix forge = Abenix.builder()
                .baseUrl(s.baseUrl())
                .apiKey("k")
                .actingSubject(ActingSubject.builder()
                    .subjectType("claimsiq").subjectId("u-1").email("a@b.com").build())
                .build();
            forge.execute("my-agent", "hello");
            // The mock lower-cases header keys.
            String hdr = null;
            for (MockServer.Recorded r : s.recorded()) {
                String v = r.headers().get("X-abenix-subject");
                if (v != null) { hdr = v; break; }
            }
            assertNotNull(hdr, "X-Abenix-Subject header sent");
            assertTrue(hdr.contains("\"subject_type\":\"claimsiq\""));
            assertTrue(hdr.contains("\"email\":\"a@b.com\""));
        }
    }
}
