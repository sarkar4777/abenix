package com.abenix.sdk;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.List;
import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public record DagSnapshot(
    @JsonProperty("execution_id") String executionId,
    @JsonProperty("agent_id") String agentId,
    @JsonProperty("agent_name") String agentName,
    String mode,                              // "pipeline" | "agent"
    String status,                            // queued | running | completed | failed
    @JsonProperty("started_at") Instant startedAt,
    @JsonProperty("completed_at") Instant completedAt,
    @JsonProperty("current_node_id") String currentNodeId,
    Progress progress,
    @JsonProperty("cost_so_far") Double costSoFar,
    Tokens tokens,
    List<Node> nodes,
    List<Edge> edges
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Progress(int completed, int total) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Tokens(@JsonProperty("in") int in, @JsonProperty("out") int out) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Node(
        String id,
        String label,
        @JsonProperty("tool_name") String toolName,
        @JsonProperty("agent_slug") String agentSlug,
        String status,                        // pending | running | completed | skipped | failed
        @JsonProperty("started_at") Instant startedAt,
        @JsonProperty("completed_at") Instant completedAt,
        @JsonProperty("duration_ms") Integer durationMs,
        Map<String, Object> input,
        Object output,                        // parsed JSON (Map / List / String / primitive)
        Double cost,
        @JsonProperty("tokens_in") Integer tokensIn,
        @JsonProperty("tokens_out") Integer tokensOut,
        @JsonProperty("tool_calls") List<ToolCall> toolCalls,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ToolCall(
        String name,
        Map<String, Object> arguments,
        Object result,
        @JsonProperty("duration_ms") Integer durationMs,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Edge(
        String from,
        String to,
        String field
    ) {}

    public boolean isTerminal() {
        return "completed".equals(status) || "failed".equals(status);
    }
}
