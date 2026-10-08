package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ActionsClientTest {

    @Test
    void propose_sends_key_arguments_and_prediction() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/autonomy/actions/propose", 201, "application/json",
                "{\"data\":{\"action_id\":\"a1\",\"decision\":\"wait\",\"approval_id\":\"p1\",\"message\":\"Waiting\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            ActionDecision d = forge.actions().propose(
                ActionsClient.ProposeRequest.of("sample_plant.set_setpoint")
                    .arguments(Map.of("setpoint_bar", 4.6))
                    .target("plant-1")
                    .intent("Pressure is low")
                    .prediction(Map.of("metric", "pressure_bar", "value", 4.5, "low", 4.4, "high", 4.6)));
            assertEquals("a1", d.actionId());
            assertEquals("p1", d.approvalId());
            assertTrue(d.isWaiting());
            assertFalse(d.shouldRun());
            String body = s.recorded().get(0).body();
            assertTrue(body.contains("\"action_key\":\"sample_plant.set_setpoint\""));
            assertTrue(body.contains("\"target\":\"plant-1\""));
            assertTrue(body.contains("pressure_bar"));
            assertFalse(body.contains("agent_id"));
        }
    }

    @Test
    void wait_returns_edited_arguments_and_reports_run_and_outcome() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/autonomy/actions/a1/wait", 200, "application/json",
                "{\"data\":{\"action_id\":\"a1\",\"decision\":\"run\",\"status\":\"edited\",\"edited\":true,"
                    + "\"arguments\":{\"setpoint_bar\":4.4},\"decided_by_name\":\"Ana\"}}");
            s.on("/api/autonomy/actions/a1/executed", 200, "application/json", "{\"data\":{\"status\":\"executed\"}}");
            s.on("/api/autonomy/actions/a1/outcome", 200, "application/json", "{\"data\":{\"outcome_status\":\"observed\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            ActionDecision d = forge.actions().waitFor("a1", 30);
            assertTrue(d.shouldRun());
            assertTrue(d.edited());
            assertEquals(4.4, d.arguments().get("setpoint_bar"));
            assertEquals("executed", forge.actions().executed("a1", true, "ok").get("status"));
            assertEquals("observed", forge.actions().reportOutcome("a1", 4.47, null).get("outcome_status"));
            assertTrue(s.recorded().get(2).body().contains("\"source\":\"api\""));
        }
    }

    @Test
    void harm_needs_a_note_and_errors_propagate() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/autonomy/actions/propose", 404, "application/json",
                "{\"error\":{\"message\":\"There is no action type called nope\",\"error_code\":\"UNKNOWN_ACTION\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            assertThrows(IllegalArgumentException.class, () -> forge.actions().flagHarm("a1", " "));
            AbenixException ex = assertThrows(AbenixException.class, () ->
                forge.actions().propose("nope", Map.of()));
            assertTrue(ex.getMessage().contains("HTTP 404"));
        }
    }

    @Test
    void autonomy_overview_and_grant_actions() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/autonomy/overview", 200, "application/json", "{\"data\":{\"counts\":{\"actions_7d\":3}}}");
            s.on("/api/autonomy/grants/g1/actions", 200, "application/json", "{\"data\":{\"items\":[],\"next_before\":null}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            assertTrue(forge.autonomy().overview().containsKey("counts"));
            assertTrue(forge.autonomy().grantActions("g1", "executed", 10, null).containsKey("items"));
        }
    }
}
