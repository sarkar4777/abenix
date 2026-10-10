package com.abenix.sdk;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Test-only HTTP server. Routes are matched by exact path; the handler
 * returns the configured status + body, and every received request is
 * recorded so tests can assert on method, path, headers, and body.
 */
final class MockServer implements AutoCloseable {

    private final HttpServer server;
    private final int port;
    private final Map<String, Route> routes = new HashMap<>();
    private final ConcurrentLinkedQueue<Recorded> log = new ConcurrentLinkedQueue<>();

    MockServer() throws IOException {
        this.server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        this.port = server.getAddress().getPort();
        server.createContext("/", new Dispatcher());
        server.setExecutor(null);
        server.start();
    }

    String baseUrl() { return "http://127.0.0.1:" + port; }

    /** Register a fixed-status, fixed-body response for the given path. */
    MockServer on(String path, int status, String contentType, String body) {
        routes.put(path, new Route(status, contentType, body));
        return this;
    }

    /** Register a dynamic handler that can inspect the recorded request. */
    MockServer onDynamic(String path, HttpHandler h) {
        server.createContext(path, h);
        return this;
    }

    List<Recorded> recorded() { return new ArrayList<>(log); }

    @Override
    public void close() { server.stop(0); }

    private final class Dispatcher implements HttpHandler {
        @Override
        public void handle(HttpExchange ex) throws IOException {
            String fullPath = ex.getRequestURI().getRawPath();
            String matched = null;
            // longest-prefix match so /a/b registered routes catch /a/b
            // even if /a was also registered.
            for (String r : routes.keySet()) {
                if (r.equals(fullPath) || (r.endsWith("/*") && fullPath.startsWith(r.substring(0, r.length() - 1)))) {
                    if (matched == null || r.length() > matched.length()) matched = r;
                }
            }
            byte[] body = readBody(ex);
            Map<String, String> headers = new HashMap<>();
            ex.getRequestHeaders().forEach((k, v) -> headers.put(k, String.join(",", v)));
            log.add(new Recorded(ex.getRequestMethod(), fullPath, headers, new String(body, StandardCharsets.UTF_8),
                ex.getRequestURI().getRawQuery()));

            Route r = matched == null ? null : routes.get(matched);
            if (r == null) {
                String msg = "{\"error\":\"no route for " + fullPath + "\"}";
                byte[] b = msg.getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "application/json");
                ex.sendResponseHeaders(404, b.length);
                ex.getResponseBody().write(b);
                ex.getResponseBody().close();
                return;
            }
            byte[] b = r.body.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", r.contentType);
            ex.sendResponseHeaders(r.status, b.length);
            ex.getResponseBody().write(b);
            ex.getResponseBody().close();
        }
    }

    private static byte[] readBody(HttpExchange ex) throws IOException {
        return ex.getRequestBody().readAllBytes();
    }

    record Route(int status, String contentType, String body) {}
    record Recorded(String method, String path, Map<String, String> headers, String body, String query) {}
}
