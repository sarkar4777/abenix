package com.abenix.sdk;

import java.util.Map;

/** Thumbs up or down on an answer, with an optional correction. */
public final class FeedbackClient {

    private final HttpKit kit;

    FeedbackClient(HttpKit kit) { this.kit = kit; }

    /** rating is 1 or -1. A thumbs down with a correction becomes a lesson with that as the right answer. */
    public Map<String, Object> give(int rating, String executionId, String agentId, String correction) {
        if (rating != 1 && rating != -1) throw new IllegalArgumentException("rating is 1 or -1.");
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "rating", rating, "execution_id", executionId, "agent_id", agentId, "correction", correction);
        return ImprovementsClient.asMap(kit.dataOrRoot(kit.postJson("/api/improvements/feedback", body, null)));
    }

    /** Feedback on a chat message instead of a run. */
    public Map<String, Object> giveOnMessage(int rating, String conversationId, String messageId, String correction) {
        if (rating != 1 && rating != -1) throw new IllegalArgumentException("rating is 1 or -1.");
        Map<String, Object> body = HttpKit.mapOfNonNull(
            "rating", rating, "conversation_id", conversationId, "message_id", messageId, "correction", correction);
        return ImprovementsClient.asMap(kit.dataOrRoot(kit.postJson("/api/improvements/feedback", body, null)));
    }
}
