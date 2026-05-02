package com.abenix.claimsiq.api;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.service.ClaimsService;
import com.abenix.sdk.DagSnapshot;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

@RestController
@RequestMapping("/api/claimsiq/claims")
public class WatchController {

    private static final Logger log = LoggerFactory.getLogger(WatchController.class);
    // findAndRegisterModules() picks up jackson-datatype-jsr310 so the
    // DagSnapshot's Instant fields serialise into SSE events.
    private static final ObjectMapper JSON = new ObjectMapper().findAndRegisterModules();

    // Long server-side timeout matches our pipeline cap. The browser
    // can still close early at any moment; SseEmitter cleans up on
    // disconnect.
    private static final long SSE_TIMEOUT_MS = 6 * 60 * 1000L;

    // Daemon scheduler for keep-alive comments — without these, NAT
    // proxies can recycle the connection mid-pipeline.
    private static final ScheduledExecutorService HEARTBEAT =
        Executors.newScheduledThreadPool(2, r -> {
            Thread t = new Thread(r, "claimsiq-sse-heartbeat");
            t.setDaemon(true);
            return t;
        });

    private final ClaimsService service;

    public WatchController(ClaimsService service) { this.service = service; }

    @GetMapping(value = "/{id}/watch", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter watch(@PathVariable UUID id) {
        log.info("watch SSE opened for claim {}", id);
        Optional<Claim> claimOpt = service.find(id);
        if (claimOpt.isEmpty()) {
            // Spring picks up a 404 from a thrown ResponseStatusException;
            // returning ResponseEntity<SseEmitter> here was suppressing
            // the streaming negotiation, leaving the request hung.
            throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.NOT_FOUND, "Claim not found");
        }

        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);

        // Heartbeat keeps the connection warm. Cancelled in onCompletion
        // / onTimeout / onError so the JVM doesn't leak schedules.
        ScheduledFuture<?> heartbeat = HEARTBEAT.scheduleAtFixedRate(() -> {
            try { emitter.send(SseEmitter.event().comment("keep-alive")); }
            catch (Throwable ignore) { /* emitter probably closed */ }
        }, 20, 20, TimeUnit.SECONDS);

        emitter.onCompletion(() -> heartbeat.cancel(false));
        emitter.onTimeout(() -> { heartbeat.cancel(false); emitter.complete(); });
        emitter.onError(t -> { heartbeat.cancel(false); emitter.complete(); });

        sendSnapshot(emitter, synthesiseQueued(claimOpt.get()));

        Thread worker = new Thread(() -> {
            try {
                String executionId = waitForExecutionId(id);
                if (executionId == null) {
                    sendEnd(emitter);
                    emitter.complete();
                    return;
                }
                long start = System.currentTimeMillis();
                long deadline = start + (5L * 60_000L);   // hard 5-min cap
                String previousJson = null;
                while (System.currentTimeMillis() < deadline) {
                    com.fasterxml.jackson.databind.JsonNode raw;
                    try {
                        raw = service.forge().getExecutionRaw(executionId);
                    } catch (Throwable t) {
                        log.debug("getExecution polled error: {}", t.getMessage());
                        Thread.sleep(2000);
                        continue;
                    }
                    DagSnapshot snap = snapshotFromExecution(executionId, raw);
                    String j;
                    try { j = JSON.writeValueAsString(snap); }
                    catch (Throwable t) { j = String.valueOf(System.currentTimeMillis()); }
                    // Only emit when the snapshot actually changed —
                    // saves bandwidth and avoids unnecessary repaints.
                    if (!j.equals(previousJson)) {
                        sendSnapshot(emitter, snap);
                        previousJson = j;
                    }
                    if (snap.isTerminal()) break;
                    Thread.sleep(2000);
                }
                sendEnd(emitter);
                emitter.complete();
            } catch (Throwable t) {
                log.warn("watch handler died for claim {}: {}", id, t.getMessage());
                try { emitter.completeWithError(t); } catch (Throwable ignore) {}
            }
        }, "claimsiq-watch-" + id);
        worker.setDaemon(true);
        worker.start();

        return emitter;
    }

    // ─── helpers ───────────────────────────────────────────────────

    /**
     * Find the executionId for this claim. First tries the claim row
     * (set by ClaimsService.discoverExecutionId or the synchronous
     * execute return). Falls back to scanning /api/executions/live for
     * a ClaimsIQ pipeline that started after the claim's createdAt.
     */
    private String waitForExecutionId(UUID id) throws InterruptedException {
        Claim c0 = service.find(id).orElse(null);
        java.time.Instant claimCreated = c0 == null ? java.time.Instant.now() : c0.getCreatedAt();
        for (int i = 0; i < 60; i++) {
            Claim c = service.find(id).orElse(null);
            if (c == null) return null;
            if (c.getExecutionId() != null) return c.getExecutionId();
            // Fallback: directly query live executions every 2s.
            if (i % 4 == 0) {
                try {
                    com.fasterxml.jackson.databind.JsonNode live = service.forge().liveExecutions();
                    if (live.isArray()) {
                        for (com.fasterxml.jackson.databind.JsonNode exec : live) {
                            if (!"ClaimsIQ — Adjudicate Claim".equals(exec.path("agent_name").asText(""))) continue;
                            String startedAt = exec.path("started_at").asText("");
                            if (startedAt.isEmpty()) startedAt = exec.path("updated_at").asText("");
                            try {
                                java.time.Instant started = java.time.Instant.parse(startedAt);
                                // Must have started AFTER the claim was created (within 60s window).
                                if (started.isBefore(claimCreated)) continue;
                                if (started.isAfter(claimCreated.plusSeconds(60))) continue;
                            } catch (Throwable ignore) { /* malformed timestamp */ }
                            String execId = exec.path("execution_id").asText(null);
                            if (execId != null && !execId.isBlank()) return execId;
                        }
                    }
                } catch (Throwable t) {
                    log.debug("liveExecutions probe error: {}", t.getMessage());
                }
            }
            Thread.sleep(500);
        }
        return null;
    }

    private void sendSnapshot(SseEmitter emitter, DagSnapshot snap) {
        try {
            emitter.send(SseEmitter.event()
                .name("snapshot")
                .data(JSON.writeValueAsString(snap), MediaType.APPLICATION_JSON));
        } catch (Throwable t) {
            log.debug("SSE send failed (client probably disconnected): {}", t.getMessage());
        }
    }

    private void sendEnd(SseEmitter emitter) {
        try {
            emitter.send(SseEmitter.event().name("end").data("{}"));
        } catch (Throwable ignore) { /* terminal */ }
    }

    private void sendError(SseEmitter emitter, String msg) {
        try {
            emitter.send(SseEmitter.event().name("error")
                .data("{\"error\":\"" + escape(msg) + "\"}"));
        } catch (Throwable ignore) {}
    }

    /**
     * Build a DagSnapshot from the platform's `/api/executions/{id}`
     * JSON. We don't get a pre-shaped DagSnapshot from that endpoint,
     * so we extract status, cost, tokens, and pivot node_results into
     * the DagSnapshot.Node list shape the UI already understands.
     */
    private DagSnapshot snapshotFromExecution(String executionId, com.fasterxml.jackson.databind.JsonNode exec) {
        if (exec == null || exec.isNull()) {
            return synthesiseQueued(null);
        }
        String status = optText(exec, "status", "running").toLowerCase();
        Double cost = optDouble(exec, "cost");
        int tokensIn = optInt(exec, "input_tokens");
        int tokensOut = optInt(exec, "output_tokens");
        java.time.Instant started = optInstant(exec, "started_at");
        java.time.Instant completed = optInstant(exec, "completed_at");

        // Pivot node_results map into a list of DagSnapshot.Node
        java.util.List<DagSnapshot.Node> nodes = new java.util.ArrayList<>();
        com.fasterxml.jackson.databind.JsonNode nr = exec.path("node_results");
        if (nr.isObject()) {
            nr.fields().forEachRemaining(e -> {
                String nodeId = e.getKey();
                com.fasterxml.jackson.databind.JsonNode v = e.getValue();
                if (!v.isObject()) return;
                String nStatus = optText(v, "status", "pending");
                Integer dur = v.has("duration_ms") && !v.get("duration_ms").isNull()
                    ? v.get("duration_ms").asInt() : null;
                Object output = v.has("output") ? toPlain(v.get("output")) : null;
                String error = v.has("error") && !v.get("error").isNull() ? v.get("error").asText() : null;
                nodes.add(new DagSnapshot.Node(
                    nodeId, nodeId, null, null, nStatus,
                    optInstant(v, "started_at"), optInstant(v, "completed_at"),
                    dur, null, output, optDouble(v, "cost"), null, null, null, error
                ));
            });
        }
        // If we got nothing yet but the pipeline is running, scaffold
        // the 6 user-visible agent nodes so the user sees the structure.
        if (nodes.isEmpty()) {
            String[][] skeleton = {
                {"fnol",          "FNOL Intake",     "claimsiq-fnol-intake"},
                {"policy_match",  "Policy Matcher",  "claimsiq-policy-matcher"},
                {"damage_assess", "Damage Assessor", "claimsiq-damage-assessor"},
                {"fraud_screen",  "Fraud Screener",  "claimsiq-fraud-screener"},
                {"valuate",       "Valuator",        "claimsiq-valuator"},
                {"decide",        "Claim Decider",   "claimsiq-claim-decider"},
            };
            for (String[] row : skeleton) {
                nodes.add(new DagSnapshot.Node(row[0], row[1], null, row[2], "pending",
                    null, null, null, null, null, null, null, null, null, null));
            }
        }
        int total = nodes.size();
        int done = (int) nodes.stream().filter(n -> "completed".equals(n.status())).count();

        return new DagSnapshot(
            executionId, null, "ClaimsIQ — Adjudicate Claim", "pipeline",
            status,
            started, completed, null,
            new DagSnapshot.Progress(done, total),
            cost == null ? 0.0 : cost,
            new DagSnapshot.Tokens(tokensIn, tokensOut),
            nodes,
            java.util.List.of()
        );
    }

    private static String optText(com.fasterxml.jackson.databind.JsonNode n, String f, String dflt) {
        return n != null && n.has(f) && !n.get(f).isNull() ? n.get(f).asText(dflt) : dflt;
    }
    private static Double optDouble(com.fasterxml.jackson.databind.JsonNode n, String f) {
        return n != null && n.has(f) && !n.get(f).isNull() ? n.get(f).asDouble() : null;
    }
    private static int optInt(com.fasterxml.jackson.databind.JsonNode n, String f) {
        return n != null && n.has(f) && !n.get(f).isNull() ? n.get(f).asInt() : 0;
    }
    private static java.time.Instant optInstant(com.fasterxml.jackson.databind.JsonNode n, String f) {
        if (n == null || !n.has(f) || n.get(f).isNull()) return null;
        try { return java.time.Instant.parse(n.get(f).asText()); }
        catch (Throwable t) { return null; }
    }
    private static Object toPlain(com.fasterxml.jackson.databind.JsonNode n) {
        try { return JSON.treeToValue(n, Object.class); }
        catch (Throwable t) { return n.toString(); }
    }

    private DagSnapshot synthesiseQueued(Claim c) {
        // 6 user-visible agent nodes — same shape + labels as the
        // client-side LiveDagView skeleton so the first SSE snapshot
        // doesn't reflow the DAG.
        String[][] skeleton = {
            {"fnol",          "FNOL Intake",     "claimsiq-fnol-intake"},
            {"policy_match",  "Policy Matcher",  "claimsiq-policy-matcher"},
            {"damage_assess", "Damage Assessor", "claimsiq-damage-assessor"},
            {"fraud_screen",  "Fraud Screener",  "claimsiq-fraud-screener"},
            {"valuate",       "Valuator",        "claimsiq-valuator"},
            {"decide",        "Claim Decider",   "claimsiq-claim-decider"},
        };
        java.util.List<DagSnapshot.Node> placeholderNodes = new java.util.ArrayList<>();
        for (String[] row : skeleton) {
            placeholderNodes.add(new DagSnapshot.Node(
                row[0], row[1], null, row[2], "pending",
                null, null, null, null, null, null, null, null, null, null));
        }
        Instant started = (c == null || c.getCreatedAt() == null) ? Instant.now() : c.getCreatedAt();
        return new DagSnapshot(
            null, null, "ClaimsIQ — Adjudicate Claim", "pipeline",
            "queued",
            started,
            null, null,
            new DagSnapshot.Progress(0, placeholderNodes.size()),
            0.0,
            new DagSnapshot.Tokens(0, 0),
            placeholderNodes,
            java.util.List.of()
        );
    }

    private static String escape(String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ");
    }
}
