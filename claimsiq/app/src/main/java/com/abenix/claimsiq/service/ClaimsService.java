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
        this.forge = Abenix.builder()
            .baseUrl(baseUrl)
            .apiKey(apiKey == null ? "" : apiKey)
            .timeout(Duration.ofSeconds(waitTimeoutSeconds + 30))
            .build();
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
                .waitTimeout(waitTimeoutSeconds)
                .actingAs(new ActingSubject(subjectType, claimId.toString()));

            ExecutionResult result = forge.execute(pipelineSlug, message, opts);
            if (result.executionId() != null) {
                Claim refreshed = repo.findById(claimId).orElse(c);
                refreshed.setExecutionId(result.executionId());
                refreshed.setUpdatedAt(Instant.now());
                repo.save(refreshed);
                c = refreshed;
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
            c.setUpdatedAt(Instant.now());
            repo.save(c);
        } catch (Throwable t) {
            log.warn("Pipeline failed for claim {}: {}", claimId, t.getMessage());
            c.setStatus("failed");
            c.setErrorMessage(t.getMessage());
            c.setUpdatedAt(Instant.now());
            try { repo.save(c); } catch (Throwable ignored) {}
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

    private static String mapDecisionToStatus(String decision) {
        if (decision == null) return "running";
        return switch (decision) {
            case "approve"          -> "approved";
            case "partial"          -> "partial";
            case "deny"             -> "denied";
            case "route_to_human"   -> "routed_to_human";
            default                 -> "running";
        };
    }

    private static String textOrNull(JsonNode n, String f) {
        return n != null && n.has(f) && !n.get(f).isNull() ? n.get(f).asText(null) : null;
    }

    private static Double doubleOrNull(JsonNode n, String f) {
        if (n == null || !n.has(f) || n.get(f).isNull()) return null;
        JsonNode v = n.get(f);
        if (v.isNumber()) return v.asDouble();
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
