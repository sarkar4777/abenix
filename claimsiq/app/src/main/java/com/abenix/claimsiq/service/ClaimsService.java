package com.abenix.claimsiq.service;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.domain.ClaimRepository;
import com.abenix.sdk.ActingSubject;
import com.abenix.sdk.Abenix;
import com.abenix.sdk.ExecutionResult;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

@Service
public class ClaimsService {

    private static final Logger log = LoggerFactory.getLogger(ClaimsService.class);
    private static final ObjectMapper JSON = new ObjectMapper();

    private final ClaimRepository repo;
    private final Abenix forge;
    private final String pipelineSlug;
    private final int waitTimeoutSeconds;
    private final String subjectType;

    public ClaimsService(
        ClaimRepository repo,
        @Value("${claimsiq.abenix.base-url}") String baseUrl,
        @Value("${claimsiq.abenix.api-key:}") String apiKey,
        @Value("${claimsiq.abenix.subject-type:claimsiq}") String subjectType,
        @Value("${claimsiq.pipeline.slug:claimsiq-adjudicate}") String pipelineSlug,
        @Value("${claimsiq.pipeline.wait-timeout-seconds:240}") int waitTimeoutSeconds
    ) {
        this.repo = repo;
        this.pipelineSlug = pipelineSlug;
        this.waitTimeoutSeconds = waitTimeoutSeconds;
        this.subjectType = subjectType;
        if (apiKey == null || apiKey.isBlank()) {
            log.warn("CLAIMSIQ_ABENIX_API_KEY not set — pipeline calls will 401 until it is.");
        }
        // Headroom past the platform's own ceiling (3600s). The per-run wait is
        // resolved from the platform setting; this only stops the HTTP read
        // timeout firing before the server has had its say.
        this.forge = Abenix.builder()
            .baseUrl(baseUrl)
            .apiKey(apiKey == null ? "" : apiKey)
            .timeout(Duration.ofSeconds(MAX_PLATFORM_BUDGET_SECONDS + 120))
            .build();
    }

    private static final int MAX_PLATFORM_BUDGET_SECONDS = 3600;
    private static final long LIMITS_TTL_MS = 60_000;

    private volatile int cachedWaitSeconds = 0;
    private volatile long cachedWaitAtMs = 0;

    /**
     * How long to wait on a run, taken from the platform's own budget so one
     * admin setting governs both sides. ClaimsIQ used to carry an independent
     * 240s, which meant a slow adjudication returned 504 to the app while the
     * pipeline went on and finished. Falls back to the configured property
     * whenever the platform cannot be asked.
     */
    private int resolveWaitSeconds() {
        long now = System.currentTimeMillis();
        if (cachedWaitSeconds > 0 && now - cachedWaitAtMs < LIMITS_TTL_MS) {
            return cachedWaitSeconds;
        }
        int resolved = waitTimeoutSeconds;
        try {
            JsonNode limits = forge.platformLimits();
            int budget = limits.path("pipeline_timeout_seconds").asInt(0);
            if (budget > 0) {
                // Sit just past the server's deadline so it times the run out
                // and reports which nodes ran over, rather than the client
                // giving up first and losing the result.
                resolved = Math.min(budget + 30, MAX_PLATFORM_BUDGET_SECONDS + 60);
            }
        } catch (Throwable t) {
            log.debug("platformLimits unavailable, using configured wait: {}", t.getMessage());
        }
        cachedWaitSeconds = resolved;
        cachedWaitAtMs = now;
        return resolved;
    }

    public Abenix forge() { return forge; }

    public List<Claim> listRecent() {
        return repo.findTop200ByOrderByCreatedAtDesc();
    }

    public Optional<Claim> find(UUID id) {
        return repo.findById(id);
    }

    public List<Claim> listRoutedToHuman() {
        return repo.findByStatusOrderByCreatedAtDesc("routed_to_human");
    }

    public Optional<Claim> review(UUID claimId, String reviewer, String decision, String notes) {
        Optional<Claim> opt = repo.findById(claimId);
        if (opt.isEmpty()) return opt;
        Claim c = opt.get();
        String mapped = switch (decision == null ? "" : decision) {
            case "approve"  -> "approved";
            case "partial"  -> "partial";
            case "deny"     -> "denied";
            default         -> null;
        };
        if (mapped == null) {
            throw new IllegalArgumentException("decision must be one of: approve | partial | deny");
        }
        c.setStatus(mapped);
        c.setReviewedBy(reviewer == null || reviewer.isBlank() ? "adjuster" : reviewer);
        c.setReviewerDecision(decision);
        c.setReviewerNotes(notes);
        c.setReviewedAt(Instant.now());
        c.setUpdatedAt(Instant.now());
        return Optional.of(repo.save(c));
    }

    public Claim ingest(FnolRequest req) {
        Instant now = Instant.now();
        Claim c = new Claim();
        c.setClaimantName(req.claimantName());
        c.setPolicyNumber(req.policyNumber());
        c.setChannel(req.channel() == null ? "web" : req.channel());
        c.setDescription(req.description());
        c.setPhotoUrls(req.photoUrls());
        c.setStatus("ingested");
        c.setCreatedAt(now);
        c.setUpdatedAt(now);
        c = repo.save(c);

        // Fire the pipeline on a background thread. The REST layer
        // returns the claim row with status=ingested immediately; the
        // UI subscribes to /api/claimsiq/claims/{id}/watch which
        // proxies to Abenix's /api/executions/{id}/watch.
        final UUID claimId = c.getId();
        final String desc = c.getDescription() == null ? "" : c.getDescription();
        final String photos = c.getPhotoUrls() == null ? "" : c.getPhotoUrls();
        CompletableFuture.runAsync(() -> runPipeline(claimId, desc, photos, req.claimantName(), req.policyNumber()));
        return c;
    }

    private void runPipeline(UUID claimId, String message, String photoUrls, String claimantName, String policyNumber) {
        Claim c = repo.findById(claimId).orElse(null);
        if (c == null) return;
        try {
            c.setStatus("running");
            c.setUpdatedAt(Instant.now());
            repo.save(c);

            Map<String, Object> ctx = new LinkedHashMap<>();
            ctx.put("claim_id", claimId.toString());
            ctx.put("claimant_id", claimantName);
            ctx.put("policy_number", policyNumber);
            ctx.put("channel", c.getChannel());
            ctx.put("photo_urls", photoUrls);
            ctx.put("message", message);

            Abenix.ExecuteOptions opts = Abenix.ExecuteOptions
                .withContext(ctx)
                .waitTimeout(resolveWaitSeconds())
                .actingAs(new ActingSubject(subjectType, claimId.toString()));

            ExecutionResult result = forge.execute(pipelineSlug, message, opts);
            if (result.executionId() != null) {
                Claim refreshed = repo.findById(claimId).orElse(c);
                refreshed.setExecutionId(result.executionId());
                refreshed.setUpdatedAt(Instant.now());
                repo.save(refreshed);
                c = refreshed;
            }

            // The platform answers 200 with status=failed so the caller still gets
            // an execution id to inspect. Treating that as success left the claim
            // on "running" for ever, because mapDecisionToStatus(null) is
            // "running" and a failed run has no decision.
            if ("failed".equals(result.status()) || "cancelled".equals(result.status())) {
                c.setCostUsd(result.cost());
                c.setDurationMs(result.durationMs());
                c.setStatus("failed");
                c.setErrorMessage(firstNodeError(result));
                c.setUpdatedAt(Instant.now());
                repo.save(c);
                log.warn("Adjudication {} for claim {}: {}",
                    result.status(), claimId, c.getErrorMessage());
                return;
            }

            JsonNode output = JSON.valueToTree(result.output());
            c.setCostUsd(result.cost());
            c.setDurationMs(result.durationMs());
            c.setDecision(textOrNull(output, "decision"));
            c.setApprovedAmountUsd(doubleOrNull(output, "approved_amount_usd"));
            c.setFraudRiskTier(textOrNull(output, "fraud_risk_tier"));
            c.setFraudScore(doubleOrNull(output, "fraud_score"));
            c.setDamageSeverity(textOrNull(output, "damage_severity"));
            c.setDeflectionScore(doubleOrNull(output, "deflection_score"));
            c.setDraftLetter(textOrNull(output, "draft_letter"));
            c.setAdjusterNotes(textOrNull(output, "adjuster_notes"));
            if (output.has("citations")) c.setCitationsJson(output.get("citations").toString());
            if (output.has("claim_type")) c.setClaimType(output.get("claim_type").asText(null));
            c.setPipelineOutputJson(output.toString());
            c.setStatus(mapDecisionToStatus(c.getDecision()));
            c.setErrorMessage(degradedReason(output));
            c.setUpdatedAt(Instant.now());
            repo.save(c);
            if (c.getErrorMessage() != null) {
                log.warn("Claim {} completed degraded: {}", claimId, c.getErrorMessage());
            }
        } catch (Throwable t) {
            log.warn("Pipeline failed for claim {}: {}", claimId, t.getMessage());
            // Re-read first. discoverExecutionId writes the id straight to the
            // row on its own thread, and saving this stale copy wiped it — so a
            // run the client gave up on left nothing to go and look at.
            Claim latest = repo.findById(claimId).orElse(c);
            latest.setStatus("failed");
            latest.setErrorMessage(t.getMessage());
            latest.setUpdatedAt(Instant.now());
            try { repo.save(latest); } catch (Throwable ignored) {}
        }
    }

    /**
     * Poll /api/executions/live every 500ms looking for the just-started
     * pipeline run associated with this claim, and write its id onto
     * the claim row so the watch SSE endpoint can subscribe. Cancelled
     * by the caller once the synchronous execute() returns.
     */
    private void discoverExecutionId(UUID claimId) {
        String targetName = "ClaimsIQ — Adjudicate Claim";
        for (int i = 0; i < 60; i++) {
            if (Thread.currentThread().isInterrupted()) return;
            try {
                JsonNode live = forge.liveExecutions();
                String bestId = null;
                String bestUpdated = "";
                if (live.isArray()) {
                    for (JsonNode exec : live) {
                        if (!targetName.equals(exec.path("agent_name").asText(""))) continue;
                        String updated = exec.path("updated_at").asText("");
                        if (updated.compareTo(bestUpdated) > 0) {
                            bestUpdated = updated;
                            bestId = exec.path("execution_id").asText(null);
                        }
                    }
                }
                if (bestId != null && !bestId.isBlank()) {
                    Claim c = repo.findById(claimId).orElse(null);
                    if (c != null && c.getExecutionId() == null) {
                        c.setExecutionId(bestId);
                        c.setUpdatedAt(Instant.now());
                        repo.save(c);
                        log.info("Discovered executionId {} for claim {}", bestId, claimId);
                    }
                    return;
                }
            } catch (Throwable t) {
                log.debug("liveExecutions poll error: {}", t.getMessage());
            }
            try { Thread.sleep(1000); }
            catch (InterruptedException e) { Thread.currentThread().interrupt(); return; }
        }
    }

    /** First node error from a failed run, so the claim carries a usable reason. */
    private static String firstNodeError(ExecutionResult result) {
        Map<String, Object> nodes = result.nodeResults();
        if (nodes != null) {
            for (Map.Entry<String, Object> e : nodes.entrySet()) {
                if (!(e.getValue() instanceof Map<?, ?> node)) continue;
                Object err = node.get("error");
                if (err != null && !err.toString().isBlank()) {
                    return (e.getKey() + ": " + err).substring(0,
                        Math.min(1000, (e.getKey() + ": " + err).length()));
                }
            }
        }
        return "Adjudication pipeline reported status=" + result.status()
            + " with no node error recorded.";
    }

    /**
     * A run that finished but produced no decision we recognise goes to an
     * adjuster, not back to "running". Leaving it in-flight meant a claim whose
     * pipeline had already completed sat on the queue for ever with no way for
     * anyone to notice.
     */
    private static String mapDecisionToStatus(String decision) {
        if (decision == null) return "routed_to_human";
        return switch (decision) {
            case "approve"          -> "approved";
            case "partial"          -> "partial";
            case "deny"             -> "denied";
            case "route_to_human"   -> "routed_to_human";
            default                 -> "routed_to_human";
        };
    }

    /** Engine placeholder for a template that resolved to nothing. */
    private static final String UNRESOLVED = "[not available]";

    private static boolean isUnresolved(String v) {
        return v == null || v.isBlank() || UNRESOLVED.equals(v.trim());
    }

    /**
     * Names the report fields the pipeline could not fill, so a claim that
     * completed with a half-empty report says why instead of looking clean.
     */
    private static String degradedReason(JsonNode output) {
        List<String> missing = new ArrayList<>();
        for (String f : new String[] {
            "decision", "approved_amount_usd", "draft_letter", "adjuster_notes",
            "net_settlement_usd", "citations",
        }) {
            JsonNode n = output.get(f);
            if (n == null || n.isNull()) { missing.add(f); continue; }
            // asText() is null on arrays and objects, so a populated citations
            // list read as missing until this checked the container first.
            if (n.isContainerNode()) {
                if (n.isEmpty()) missing.add(f);
            } else if (isUnresolved(n.asText(null))) {
                missing.add(f);
            }
        }
        if (missing.isEmpty()) return null;
        return "Adjudication completed but produced no value for: "
            + String.join(", ", missing)
            + ". An upstream node returned prose instead of its JSON contract.";
    }

    // "[not available]" is the engine's placeholder for a template that never
    // resolved, not a value. Storing it verbatim put that text in front of the
    // adjuster and made a missing decision look like a real one.
    private static String textOrNull(JsonNode n, String f) {
        if (n == null || !n.has(f) || n.get(f).isNull()) return null;
        String v = n.get(f).asText(null);
        return isUnresolved(v) ? null : v;
    }

    private static Double doubleOrNull(JsonNode n, String f) {
        if (n == null || !n.has(f) || n.get(f).isNull()) return null;
        JsonNode v = n.get(f);
        if (v.isNumber()) return v.asDouble();
        if (isUnresolved(v.asText(null))) return null;
        try { return Double.parseDouble(v.asText()); } catch (Exception e) { return null; }
    }

    public record FnolRequest(
        String claimantName,
        String policyNumber,
        String channel,
        String description,
        String photoUrls
    ) {}
}
