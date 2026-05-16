package com.abenix.claimsiq.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;
import java.util.UUID;

/**
 * Persisted claim record. Row is created immediately on FNOL ingest
 * (even before the pipeline runs) so a pipeline failure always
 * leaves an auditable trail — same "commit case first, fire
 * pipeline second" pattern ResolveAI uses.
 */
@Entity
@Table(name = "claimsiq_claims")
public class Claim {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(columnDefinition = "uuid")
    private UUID id;

    @Column(name = "claimant_name", length = 200)
    private String claimantName;

    @Column(name = "policy_number", length = 60)
    private String policyNumber;

    @Column(name = "channel", length = 40)
    private String channel;

    @Column(name = "claim_type", length = 40)
    private String claimType;

    @Column(name = "loss_date", length = 40)
    private String lossDate;

    @Column(name = "description", columnDefinition = "TEXT")
    private String description;

    @Column(name = "photo_urls", columnDefinition = "TEXT")
    private String photoUrls;             // comma-separated

    @Column(name = "status", length = 40)
    private String status;                // ingested | running | approved | partial | denied | routed_to_human | failed

    @Column(name = "decision", length = 40)
    private String decision;

    @Column(name = "approved_amount_usd")
    private Double approvedAmountUsd;

    @Column(name = "fraud_risk_tier", length = 20)
    private String fraudRiskTier;

    @Column(name = "fraud_score")
    private Double fraudScore;

    @Column(name = "damage_severity", length = 20)
    private String damageSeverity;

    @Column(name = "deflection_score")
    private Double deflectionScore;

    @Column(name = "execution_id", length = 60)
    private String executionId;

    @Column(name = "draft_letter", columnDefinition = "TEXT")
    private String draftLetter;

    @Column(name = "adjuster_notes", columnDefinition = "TEXT")
    private String adjusterNotes;

    @Column(name = "citations_json", columnDefinition = "TEXT")
    private String citationsJson;

    @Column(name = "pipeline_output_json", columnDefinition = "TEXT")
    private String pipelineOutputJson;

    @Column(name = "error_message", length = 2000)
    private String errorMessage;

    @Column(name = "cost_usd")
    private Double costUsd;

    @Column(name = "duration_ms")
    private Long durationMs;

    // ── HITL ── populated when an adjuster reviews a routed_to_human
    //           claim. Final decision overrides the AI's recommendation.
    @Column(name = "reviewed_by", length = 200)
    private String reviewedBy;
    @Column(name = "reviewer_decision", length = 20)
    private String reviewerDecision;       // approve | partial | deny
    @Column(name = "reviewer_notes", columnDefinition = "TEXT")
    private String reviewerNotes;
    @Column(name = "reviewed_at")
    private Instant reviewedAt;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    // ─── Getters / setters ─────────────────────────────────────────────

    public UUID getId() { return id; }
    public void setId(UUID id) { this.id = id; }
    public String getClaimantName() { return claimantName; }
    public void setClaimantName(String v) { claimantName = v; }
    public String getPolicyNumber() { return policyNumber; }
    public void setPolicyNumber(String v) { policyNumber = v; }
    public String getChannel() { return channel; }
    public void setChannel(String v) { channel = v; }
    public String getClaimType() { return claimType; }
    public void setClaimType(String v) { claimType = v; }
    public String getLossDate() { return lossDate; }
    public void setLossDate(String v) { lossDate = v; }
    public String getDescription() { return description; }
    public void setDescription(String v) { description = v; }
    public String getPhotoUrls() { return photoUrls; }
    public void setPhotoUrls(String v) { photoUrls = v; }
    public String getStatus() { return status; }
    public void setStatus(String v) { status = v; }
    public String getDecision() { return decision; }
    public void setDecision(String v) { decision = v; }
    public Double getApprovedAmountUsd() { return approvedAmountUsd; }
    public void setApprovedAmountUsd(Double v) { approvedAmountUsd = v; }
    public String getFraudRiskTier() { return fraudRiskTier; }
    public void setFraudRiskTier(String v) { fraudRiskTier = v; }
    public Double getFraudScore() { return fraudScore; }
    public void setFraudScore(Double v) { fraudScore = v; }
    public String getDamageSeverity() { return damageSeverity; }
    public void setDamageSeverity(String v) { damageSeverity = v; }
    public Double getDeflectionScore() { return deflectionScore; }
    public void setDeflectionScore(Double v) { deflectionScore = v; }
    public String getExecutionId() { return executionId; }
    public void setExecutionId(String v) { executionId = v; }
    public String getDraftLetter() { return draftLetter; }
    public void setDraftLetter(String v) { draftLetter = v; }
    public String getAdjusterNotes() { return adjusterNotes; }
    public void setAdjusterNotes(String v) { adjusterNotes = v; }
    public String getCitationsJson() { return citationsJson; }
    public void setCitationsJson(String v) { citationsJson = v; }
    public String getPipelineOutputJson() { return pipelineOutputJson; }
    public void setPipelineOutputJson(String v) { pipelineOutputJson = v; }
    public String getErrorMessage() { return errorMessage; }
    public void setErrorMessage(String v) { errorMessage = v; }
    public Double getCostUsd() { return costUsd; }
    public void setCostUsd(Double v) { costUsd = v; }
    public Long getDurationMs() { return durationMs; }
    public void setDurationMs(Long v) { durationMs = v; }
    public String getReviewedBy() { return reviewedBy; }
    public void setReviewedBy(String v) { reviewedBy = v; }
    public String getReviewerDecision() { return reviewerDecision; }
    public void setReviewerDecision(String v) { reviewerDecision = v; }
    public String getReviewerNotes() { return reviewerNotes; }
    public void setReviewerNotes(String v) { reviewerNotes = v; }
    public Instant getReviewedAt() { return reviewedAt; }
    public void setReviewedAt(Instant v) { reviewedAt = v; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant v) { createdAt = v; }
    public Instant getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Instant v) { updatedAt = v; }
}
