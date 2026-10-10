package com.abenix.sdk;

public class AbenixException extends RuntimeException {
    private final int status;
    private final String code;

    public AbenixException(String message) { this(message, 0, null); }
    public AbenixException(String message, Throwable cause) {
        super(message, cause);
        this.status = 0;
        this.code = null;
    }
    public AbenixException(String message, int status, String code) {
        super(message);
        this.status = status;
        this.code = code;
    }

    /** HTTP status the platform answered with, 0 when the call never got an answer. */
    public int status() { return status; }

    /** The server's error_code, such as UNKNOWN_ACTION, when it sent one. */
    public String code() { return code; }
}
