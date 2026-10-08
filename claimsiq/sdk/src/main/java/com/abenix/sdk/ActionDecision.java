package com.abenix.sdk;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

/**
 * What the autonomy gate said about an action an app proposed. Only
 * {@code decision == "run"} means go ahead. After a wait, use
 * {@link #arguments()} since a reviewer may have edited them.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record ActionDecision(
    @JsonProperty("action_id") String actionId,
    String decision,
    String status,
    @JsonProperty("approval_id") String approvalId,
    String message,
    Map<String, Object> arguments,
    boolean edited,
    @JsonProperty("decided_by_name") String decidedByName,
    @JsonProperty("decision_note") String decisionNote
) {
    public boolean shouldRun() { return "run".equals(decision); }
    public boolean isWaiting() { return "wait".equals(decision); }
}
