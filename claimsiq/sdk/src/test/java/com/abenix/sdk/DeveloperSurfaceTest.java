package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DeveloperSurfaceTest {

    @Test
    void executions_list_sends_every_filter() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/executions", 200, "application/json",
                "{\"data\":[{\"id\":\"e-1\",\"trigger_kind\":\"api\"}]}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            List<Map<String, Object>> rows = forge.executions().list(
                ExecutionsClient.ListOptions.empty()
                    .agentId("a-1").status("failed").triggerKind("schedule", "webhook")
                    .triggerId("t-9").search("invoice").limit(5).offset(10));
            assertEquals("e-1", rows.get(0).get("id"));
            String q = java.net.URLDecoder.decode(s.recorded().get(0).query(), StandardCharsets.UTF_8);
            for (String want : List.of("agent_id=a-1", "status=failed", "trigger_kind=schedule,webhook",
                    "trigger_id=t-9", "search=invoice", "limit=5", "offset=10")) {
                assertTrue(q.contains(want), q + " lacks " + want);
            }
        }
    }

    @Test
    void executions_list_defaults_leave_filters_out() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/executions", 200, "application/json", "{\"data\":[]}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            assertTrue(forge.executions().list().isEmpty());
            assertEquals("limit=20&offset=0", s.recorded().get(0).query());
        }
    }

    @Test
    void by_slug_is_null_on_404_and_errors_carry_status_and_code() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/agents/by-slug/nope", 404, "application/json",
                "{\"data\":null,\"error\":{\"message\":\"Agent not found\",\"error_code\":\"NOT_FOUND\"}}");
            s.on("/api/autonomy/actions/propose", 404, "application/json",
                "{\"data\":null,\"error\":{\"message\":\"There is no action type called x\",\"error_code\":\"UNKNOWN_ACTION\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            assertNull(forge.agents().bySlug("nope"));
            AbenixException e = assertThrows(AbenixException.class,
                () -> forge.actions().propose("x", Map.of()));
            assertEquals(404, e.status());
            assertEquals("UNKNOWN_ACTION", e.code());
            assertTrue(e.getMessage().contains("There is no action type called x"));
        }
    }

    @Test
    void knowledge_upload_sends_one_multipart_file() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/knowledge-bases/kb-1/upload", 201, "application/json",
                "{\"data\":{\"id\":\"d-1\",\"status\":\"processing\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Map<String, Object> doc = forge.knowledge().upload(
                "kb-1", "hello".getBytes(StandardCharsets.UTF_8), "notes.txt", "text/plain");
            assertEquals("d-1", doc.get("id"));
            MockServer.Recorded r = s.recorded().get(0);
            assertTrue(r.headers().get("Content-type").startsWith("multipart/form-data; boundary="));
            assertTrue(r.body().contains("filename=\"notes.txt\""));
            assertTrue(r.body().contains("hello"));
            assertThrows(IllegalArgumentException.class,
                () -> forge.knowledge().upload("kb-1", new byte[0], " ", null));
        }
    }

    @Test
    void me_and_permissions_unwrap_the_envelope() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/me", 200, "application/json", "{\"data\":{\"user\":{\"email\":\"a@b.c\"}}}");
            s.on("/api/me/permissions", 200, "application/json",
                "{\"data\":{\"role\":\"admin\",\"capabilities\":[\"approvals.sign\"]}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            assertEquals("a@b.c", ((Map<?, ?>) forge.me().get("user")).get("email"));
            assertEquals("admin", forge.permissions().get("role"));
        }
    }

    @Test
    void approve_with_edited_arguments() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/approvals/ap-1/signoff", 200, "application/json",
                "{\"data\":{\"id\":\"ap-1\",\"status\":\"approved\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            Approval a = forge.approvals().approve("ap-1", "ok", Map.of("setpoint_bar", 4.4));
            assertEquals("approved", a.status());
            assertTrue(s.recorded().get(0).body().contains("\"edited_arguments\":{\"setpoint_bar\":4.4}"));
        }
    }

    @Test
    void watch_reads_offset_times_and_stops_at_end() throws Exception {
        String snap = "{\"execution_id\":\"e-1\",\"status\":\"completed\","
            + "\"started_at\":\"2026-10-09T08:18:50.770073+00:00\",\"completed_at\":\"2026-10-09T08:18:53+00:00\","
            + "\"nodes\":[{\"id\":\"agent\",\"status\":\"completed\",\"started_at\":\"2026-10-09T08:18:50+00:00\"}]}";
        try (MockServer s = new MockServer()) {
            s.on("/api/executions/e-1/watch", 200, "text/event-stream",
                "event: snapshot\ndata: " + snap + "\n\nevent: end\ndata: {}\n\n");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            try (WatchStream w = forge.watch("e-1")) {
                DagSnapshot last = w.terminal().get(10, java.util.concurrent.TimeUnit.SECONDS);
                assertEquals("completed", last.status());
                assertEquals(java.time.Instant.parse("2026-10-09T08:18:53Z"), last.completedAt());
            }
        }
    }
}
