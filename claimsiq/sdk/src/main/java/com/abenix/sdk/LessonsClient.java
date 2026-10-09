package com.abenix.sdk;

import java.util.Map;

/** Tell an agent what it got wrong. Lessons feed proposals, they never change an agent on their own. */
public final class LessonsClient {

    private final HttpKit kit;

    LessonsClient(HttpKit kit) { this.kit = kit; }

    /** Say why a run was wrong. expected and executionId may be null. */
    public Map<String, Object> report(String agentId, String note, String expected, String executionId) {
        if (note == null || note.isBlank()) throw new IllegalArgumentException("Say what was wrong.");
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "agent_id", agentId, "note", note, "source", "sdk", "expected", expected, "execution_id", executionId);
        return ImprovementsClient.asMap(kit.dataOrRoot(kit.postJson("/api/improvements/lessons", body, null)));
    }

    public Map<String, Object> report(String agentId, String note) { return report(agentId, note, null, null); }
}
