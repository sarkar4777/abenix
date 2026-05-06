package com.abenix.sdk;

/** HITL-aware wait modes for {@link Abenix#execute}. */
public enum WaitMode {
    /** Block until the agent reaches a terminal state. Default behaviour. */
    COMPLETED("completed"),
    /** Kick off the execution and return immediately with executionId. */
    SUBMITTED("submitted"),
    /** Block, but if a HITL approval gate opens, return early with pausedAt. */
    UNTIL_GATE("until_gate");

    private final String wire;

    WaitMode(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }
}
