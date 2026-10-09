package com.abenix.sdk;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ImprovementsClientTest {

    @Test
    void list_get_report_and_give() throws IOException {
        try (MockServer s = new MockServer()) {
            s.on("/api/improvements/proposals", 200, "application/json",
                "{\"data\":{\"items\":[{\"id\":\"p1\",\"state\":\"kept\"}]}}");
            s.on("/api/improvements/proposals/p1", 200, "application/json",
                "{\"data\":{\"id\":\"p1\",\"state\":\"kept\"}}");
            s.on("/api/improvements/lessons", 201, "application/json", "{\"data\":{\"id\":\"l1\"}}");
            s.on("/api/improvements/feedback", 201, "application/json", "{\"data\":{\"id\":\"f1\",\"lesson_id\":\"l2\"}}");
            Abenix forge = Abenix.builder().baseUrl(s.baseUrl()).apiKey("k").build();
            List<Map<String, Object>> items = forge.improvements().list("a1", "kept", 5);
            assertEquals(1, items.size());
            assertEquals("p1", items.get(0).get("id"));
            assertEquals("kept", forge.improvements().get("p1").get("state"));
            assertEquals("l1", forge.lessons().report("a1", "Used Fahrenheit", "273.15 K", null).get("id"));
            assertEquals("l2", forge.feedback().give(-1, "e1", null, "273.15 K").get("lesson_id"));
            String lessonBody = s.recorded().get(2).body();
            assertTrue(lessonBody.contains("\"expected\":\"273.15 K\""));
            assertTrue(!lessonBody.contains("execution_id"));
            assertTrue(s.recorded().get(3).body().contains("\"rating\":-1"));
        }
    }

    @Test
    void bad_input_is_refused_before_any_call() {
        Abenix forge = Abenix.builder().baseUrl("http://localhost:1").apiKey("k").build();
        assertThrows(IllegalArgumentException.class, () -> forge.feedback().give(0, null, null, null));
        assertThrows(IllegalArgumentException.class, () -> forge.lessons().report("a1", " "));
    }
}
