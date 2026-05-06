package com.abenix.sdk;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public record Approval(
    String id,
    @JsonProperty("agent_id") String agentId,
    @JsonProperty("agent_execution_id") String agentExecutionId,
    String title,
    Map<String, Object> payload,
    @JsonProperty("required_signoffs") int requiredSignoffs,
    List<Map<String, Object>> signoffs,
    String status,
    @JsonProperty("requested_by") String requestedBy,
    @JsonProperty("expires_at") String expiresAt,
    @JsonProperty("decided_at") String decidedAt,
    @JsonProperty("created_at") String createdAt,
    @JsonProperty("gate_kind") String gateKind,
    @JsonProperty("client_token") String clientToken
) {}
