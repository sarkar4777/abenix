package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Wire-shape parity with the Python SDK. The Abenix API only knows the
 * single {@code X-Abenix-Subject} JSON header — the older flat
 * {@code X-Abenix-Subject-Type/-Id} pair was silently ignored, so this
 * test guards against that regression.
 */
class ActingSubjectTest {

    private static final ObjectMapper JSON = new ObjectMapper();

    @Test
    void toHeader_emits_single_json_header() throws Exception {
        ActingSubject s = ActingSubject.of("contractiq", "user-42");
        Map<String, String> headers = s.toHeader();
        assertEquals(1, headers.size(), "exactly one header");
        assertTrue(headers.containsKey("X-Abenix-Subject"));
        JsonNode tree = JSON.readTree(headers.get("X-Abenix-Subject"));
        assertEquals("contractiq", tree.get("subject_type").asText());
        assertEquals("user-42", tree.get("subject_id").asText());
        assertFalse(tree.has("email"));
        assertFalse(tree.has("display_name"));
    }

    @Test
    void builder_includes_optional_fields() throws Exception {
        ActingSubject s = ActingSubject.builder()
            .subjectType("claimsiq")
            .subjectId("claim-001")
            .email("adjuster@abenix.dev")
            .displayName("Jane Adjuster")
            .metadata(Map.of("region", "us-east"))
            .build();
        JsonNode tree = JSON.readTree(s.toHeader().get("X-Abenix-Subject"));
        assertEquals("adjuster@abenix.dev", tree.get("email").asText());
        assertEquals("Jane Adjuster", tree.get("display_name").asText());
        assertEquals("us-east", tree.get("metadata").get("region").asText());
    }

    @Test
    void of_factory_matches_full_ctor() {
        ActingSubject a = ActingSubject.of("x", "y");
        ActingSubject b = new ActingSubject("x", "y");
        assertEquals(a.toJson(), b.toJson());
        assertNull(a.email());
        assertNotNull(a.subjectType());
    }
}
