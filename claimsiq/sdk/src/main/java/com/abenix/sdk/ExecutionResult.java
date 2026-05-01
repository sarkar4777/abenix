package com.abenix.sdk;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Terminal result from a synchronous {@link Abenix#execute(String, String)} call.
 * Mirrors the Python SDK's {@code ExecutionResult} dataclass.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record ExecutionResult(
    @JsonProperty("execution_id") String executionId,
    Object output,                                         // String | Map | List — parsed from envelope
    @JsonProperty("input_tokens") int inputTokens,
    @JsonProperty("output_tokens") int outputTokens,
    double cost,
    @JsonProperty("duration_ms") long durationMs,
    String model,
    @JsonProperty("tool_calls") List<Map<String, Object>> toolCalls,
    @JsonProperty("node_results") Map<String, Object> nodeResults,
    @JsonProperty("confidence_score") Double confidenceScore
) {}
