package com.abenix.sdk;

import com.fasterxml.jackson.databind.JsonNode;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Earned autonomy for actions an app takes itself. Propose before acting,
 * wait when a person has to approve, then report that it ran and what
 * actually happened so the track record moves.
 */
public final class ActionsClient {

    private final HttpKit kit;

    ActionsClient(HttpKit kit) { this.kit = kit; }

    /** Ask before acting. The prediction is a map of metric, value, low and high. */
    public ActionDecision propose(ProposeRequest req) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("action_key", req.actionKey);
        body.put("arguments", req.arguments == null ? Map.of() : req.arguments);
        if (req.agentId != null) body.put("agent_id", req.agentId);
        if (req.target != null) body.put("target", req.target);
        if (req.intent != null) body.put("intent", req.intent);
        if (req.prediction != null) body.put("prediction", req.prediction);
        return decision(kit.dataOrRoot(kit.postJson("/api/autonomy/actions/propose", body, null)));
    }

    public ActionDecision propose(String actionKey, Map<String, Object> arguments) {
        return propose(ProposeRequest.of(actionKey).arguments(arguments));
    }

    /** Block until a person decides or the timeout fires, in long-poll rounds of up to 120 s. A busy server is retried. */
    public ActionDecision waitFor(String actionId, int timeoutSeconds) {
        return HttpKit.longPoll(timeoutSeconds, chunk -> decision(kit.dataOrRoot(kit.getJson(
            "/api/autonomy/actions/" + actionId + "/wait", Map.of("timeout_s", chunk), null,
            java.time.Duration.ofSeconds(chunk + 30L)))), d -> !d.isWaiting());
    }

    /** Say the action ran, or failed. Starts the outcome clock when the action type has a probe. */
    public Map<String, Object> executed(String actionId, boolean ok, String resultPreview) {
        Map<String, Object> body = HttpKit.mapOfNonNull("ok", ok, "result_preview", resultPreview);
        return asMap(kit.dataOrRoot(kit.postJson("/api/autonomy/actions/" + actionId + "/executed", body, null)));
    }

    /** What actually happened. A number is scored against the band, text must match a categorical prediction. */
    public Map<String, Object> reportOutcome(String actionId, Object value, String note) {
        Map<String, Object> body = HttpKit.mapOfNonNull("value", value, "source", "api", "note", note);
        return asMap(kit.dataOrRoot(kit.postJson("/api/autonomy/actions/" + actionId + "/outcome", body, null)));
    }

    /** Flag that the action did harm. Drops the agent to Asks first at once. */
    public Map<String, Object> flagHarm(String actionId, String note) {
        if (note == null || note.isBlank()) throw new IllegalArgumentException("Say what went wrong.");
        return asMap(kit.dataOrRoot(kit.postJson("/api/autonomy/actions/" + actionId + "/harm", Map.of("note", note), null)));
    }

    /** One action with its card, outcome and score. */
    public Map<String, Object> get(String actionId) {
        return asMap(kit.dataOrRoot(kit.getJson("/api/autonomy/actions/" + actionId, null)));
    }

    public static final class ProposeRequest {
        public String actionKey;
        public Map<String, Object> arguments;
        public String agentId;
        public String target;
        public String intent;
        public Map<String, Object> prediction;

        public static ProposeRequest of(String actionKey) {
            ProposeRequest r = new ProposeRequest();
            r.actionKey = actionKey;
            return r;
        }
        public ProposeRequest arguments(Map<String, Object> v) { this.arguments = v; return this; }
        public ProposeRequest agentId(String v) { this.agentId = v; return this; }
        public ProposeRequest target(String v) { this.target = v; return this; }
        public ProposeRequest intent(String v) { this.intent = v; return this; }
        public ProposeRequest prediction(Map<String, Object> v) { this.prediction = v; return this; }
    }

    private static ActionDecision decision(JsonNode n) {
        if (n == null || n.isNull()) return null;
        try {
            return HttpKit.JSON.treeToValue(n, ActionDecision.class);
        } catch (IOException e) {
            throw new AbenixException("Bad action response shape: " + e.getMessage(), e);
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(JsonNode n) {
        if (n == null || n.isNull()) return Map.of();
        return HttpKit.JSON.convertValue(n, Map.class);
    }
}
