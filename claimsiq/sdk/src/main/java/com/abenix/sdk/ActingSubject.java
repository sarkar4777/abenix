package com.abenix.sdk;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Identity of the end-user on whose behalf a service-account call is
 * being made. Maps to the X-Abenix-Subject header that the Abenix API
 * uses for per-grant authorization — so ClaimsIQ's service key can be
 * auditable down to the specific adjuster.
 *
 * <p>Wire shape MUST match the Python SDK's {@code ActingSubject.to_header()}:
 * a single {@code X-Abenix-Subject} header carrying a JSON object with
 * {@code subject_type}, {@code subject_id}, and the optional
 * {@code email}, {@code display_name}, {@code metadata} fields. The
 * server (apps/api/app/core/acting_subject.py) parses that JSON; the
 * older flat {@code X-Abenix-Subject-Type / -Id} headers are ignored.
 */
public final class ActingSubject {

    private static final ObjectMapper JSON = new ObjectMapper();

    private final String subjectType;
    private final String subjectId;
    private final String email;
    private final String displayName;
    private final Map<String, Object> metadata;

    public ActingSubject(String subjectType, String subjectId) {
        this(subjectType, subjectId, null, null, null);
    }

    public ActingSubject(
        String subjectType,
        String subjectId,
        String email,
        String displayName,
        Map<String, Object> metadata
    ) {
        this.subjectType = subjectType;
        this.subjectId = subjectId;
        this.email = email;
        this.displayName = displayName;
        this.metadata = metadata;
    }

    public static ActingSubject of(String subjectType, String subjectId) {
        return new ActingSubject(subjectType, subjectId);
    }

    public static Builder builder() { return new Builder(); }

    public String subjectType() { return subjectType; }
    public String subjectId() { return subjectId; }
    public String email() { return email; }
    public String displayName() { return displayName; }
    public Map<String, Object> metadata() { return metadata; }

    /**
     * Returns the single-header map {@code { "X-Abenix-Subject": "<json>" }}
     * the Abenix API expects. Older code that called this used to emit two
     * flat headers — the server ignored those, so service-account calls
     * landed without an acting subject. Fixed here to mirror the Python
     * SDK 1:1.
     */
    public Map<String, String> toHeader() {
        Map<String, String> out = new HashMap<>();
        out.put("X-Abenix-Subject", toJson());
        return out;
    }

    /** Raw JSON payload of the X-Abenix-Subject header — useful for debug logs. */
    public String toJson() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("subject_type", subjectType);
        m.put("subject_id", subjectId);
        if (email != null) m.put("email", email);
        if (displayName != null) m.put("display_name", displayName);
        if (metadata != null && !metadata.isEmpty()) m.put("metadata", metadata);
        try {
            return JSON.writeValueAsString(m);
        } catch (IOException e) {
            throw new AbenixException("ActingSubject JSON encode failed: " + e.getMessage(), e);
        }
    }

    public static final class Builder {
        private String subjectType;
        private String subjectId;
        private String email;
        private String displayName;
        private Map<String, Object> metadata;

        public Builder subjectType(String v) { this.subjectType = v; return this; }
        public Builder subjectId(String v) { this.subjectId = v; return this; }
        public Builder email(String v) { this.email = v; return this; }
        public Builder displayName(String v) { this.displayName = v; return this; }
        public Builder metadata(Map<String, Object> v) { this.metadata = v; return this; }

        public ActingSubject build() {
            return new ActingSubject(subjectType, subjectId, email, displayName, metadata);
        }
    }
}
