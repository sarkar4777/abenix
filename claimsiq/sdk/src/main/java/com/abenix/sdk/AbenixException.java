package com.abenix.sdk;

public class AbenixException extends RuntimeException {
    public AbenixException(String message) { super(message); }
    public AbenixException(String message, Throwable cause) { super(message, cause); }
}
