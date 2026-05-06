package com.abenix.sdk;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public record ApprovalRef(
    @JsonProperty("approval_id") String approvalId,
    String title,
    Map<String, Object> payload,
    @JsonProperty("required_signoffs") int requiredSignoffs,
    @JsonProperty("expires_at") String expiresAt,
    @JsonProperty("gate_kind") String gateKind
) {}
