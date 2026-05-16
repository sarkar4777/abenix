package com.abenix.sdk;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

final class SseWatchStream implements WatchStream {

    private static final Logger log = LoggerFactory.getLogger(SseWatchStream.class);
    private static final DagSnapshot POISON = new DagSnapshot(null, null, null, null, null, null, null, null, null, null, null, null, null);

    private final HttpClient http;
    private final URI uri;
    private final Map<String, String> headers;
    private final ObjectMapper json;
    private final LinkedBlockingQueue<DagSnapshot> queue = new LinkedBlockingQueue<>(256);
    private final List<Consumer<DagSnapshot>> listeners = new CopyOnWriteArrayList<>();
    private final List<Consumer<Throwable>> errorListeners = new CopyOnWriteArrayList<>();
    private final AtomicBoolean started = new AtomicBoolean(false);
    private final AtomicBoolean closed = new AtomicBoolean(false);
    private final CompletableFuture<DagSnapshot> terminalFuture = new CompletableFuture<>();
    private volatile DagSnapshot latest;
    private Thread reader;

    SseWatchStream(HttpClient http, URI uri, Map<String, String> headers, ObjectMapper json) {
        this.http = http;
        this.uri = uri;
        this.headers = headers;
        this.json = json;
    }

    @Override
    public WatchStream onSnapshot(Consumer<DagSnapshot> cb) {
        listeners.add(cb);
        startIfNeeded();
        return this;
    }

    @Override
    public WatchStream onError(Consumer<Throwable> cb) {
        errorListeners.add(cb);
        return this;
    }

    @Override
    public DagSnapshot latest() { return latest; }

    @Override
    public CompletableFuture<DagSnapshot> terminal() {
        startIfNeeded();
        return terminalFuture;
    }

    @Override
    public Iterator<DagSnapshot> iterator() {
        startIfNeeded();
        return new Iterator<>() {
            DagSnapshot next;

            @Override
            public boolean hasNext() {
                if (next != null && next != POISON) return true;
                try {
                    next = queue.poll(30, TimeUnit.MINUTES);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return false;
                }
                return next != null && next != POISON;
            }

            @Override
            public DagSnapshot next() {
                DagSnapshot r = next;
                next = null;
                return r;
            }
        };
    }

    @Override
    public void close() {
        if (closed.compareAndSet(false, true)) {
            queue.offer(POISON);
            if (reader != null) reader.interrupt();
            if (!terminalFuture.isDone()) {
                terminalFuture.complete(latest);  // may be null if we never saw a snapshot
            }
        }
    }

    private void startIfNeeded() {
        if (!started.compareAndSet(false, true)) return;
        reader = Executors.defaultThreadFactory().newThread(this::runLoop);
        reader.setName("abenix-watch-" + uri.getRawPath());
        reader.setDaemon(true);
        reader.start();
    }

    private void runLoop() {
        int attempts = 0;
        while (!closed.get() && attempts < 2) {
            attempts++;
            try {
                HttpRequest.Builder b = HttpRequest.newBuilder(uri).timeout(Duration.ofMinutes(30)).GET();
                headers.forEach(b::header);
                HttpResponse<java.io.InputStream> resp = http.send(b.build(), HttpResponse.BodyHandlers.ofInputStream());
                if (resp.statusCode() >= 400) {
                    fireError(new AbenixException("watch stream HTTP " + resp.statusCode()));
                    return;
                }
                consumeSse(resp);
                return;   // terminal event closed the stream cleanly
            } catch (java.io.IOException | InterruptedException e) {
                if (closed.get()) return;
                if (attempts >= 2) { fireError(e); return; }
                try { Thread.sleep(500); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); return; }
                log.warn("watch stream blipped, reconnecting: {}", e.getMessage());
            }
        }
    }

    private void consumeSse(HttpResponse<java.io.InputStream> resp) throws java.io.IOException {
        try (BufferedReader r = new BufferedReader(new InputStreamReader(resp.body(), StandardCharsets.UTF_8))) {
            StringBuilder dataBuf = new StringBuilder();
            String eventType = null;
            String line;
            while ((line = r.readLine()) != null) {
                if (closed.get()) return;
                if (line.isEmpty()) {
                    if (dataBuf.length() > 0) {
                        dispatch(eventType, dataBuf.toString());
                        dataBuf.setLength(0);
                        eventType = null;
                    }
                    continue;
                }
                if (line.startsWith(":")) continue;    // comment
                if (line.startsWith("event:")) {
                    eventType = line.substring(6).trim();
                } else if (line.startsWith("data:")) {
                    if (dataBuf.length() > 0) dataBuf.append('\n');
                    dataBuf.append(line.substring(5).trim());
                }
            }
            // Stream ended without an explicit terminal event — treat as clean close.
            close();
        }
    }

    private void dispatch(String event, String data) {
        try {
            DagSnapshot snap = json.readValue(data, DagSnapshot.class);
            latest = snap;
            queue.offer(snap);
            for (Consumer<DagSnapshot> c : listeners) {
                try { c.accept(snap); }
                catch (Throwable t) { log.warn("snapshot listener threw: {}", t.getMessage()); }
            }
            if (snap.isTerminal()) {
                terminalFuture.complete(snap);
                close();
            }
        } catch (java.io.IOException e) {
            log.warn("bad SSE payload ({}): {}", event, e.getMessage());
        }
    }

    private void fireError(Throwable t) {
        if (!terminalFuture.isDone()) terminalFuture.completeExceptionally(t);
        for (Consumer<Throwable> c : errorListeners) {
            try { c.accept(t); } catch (Throwable ignored) {}
        }
        close();
    }
}
