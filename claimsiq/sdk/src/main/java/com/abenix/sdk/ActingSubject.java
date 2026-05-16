package com.abenix.sdk;

import java.util.HashMap;
import java.util.Map;

/**
 * Identity of the end-user on whose behalf a service-account call is
 * being made. Maps to the X-Abenix-Subject header that the
 * Abenix API uses for per-grant authorization — so ClaimsIQ's
 * service key can be auditable down to the specific adjuster.
 */
public record ActingSubject(String subjectType, String subjectId) {

    public static ActingSubject of(String subjectType, String subjectId) {
        return new ActingSubject(subjectType, subjectId);
    }

    public Map<String, String> toHeader() {
        Map<String, String> m = new HashMap<>();
        m.put("X-Abenix-Subject-Type", subjectType);
        m.put("X-Abenix-Subject-Id", subjectId);
        return m;
    }
}
