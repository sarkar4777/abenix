package com.abenix.sdk;

import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;

public interface WatchStream extends AutoCloseable, Iterable<DagSnapshot> {

    WatchStream onSnapshot(Consumer<DagSnapshot> cb);

    WatchStream onError(Consumer<Throwable> cb);

    DagSnapshot latest();

    /**
     * Future that completes with the terminal snapshot (status
     * {@code completed} or {@code failed}) — or completes
     * exceptionally on a transport error.
     */
    CompletableFuture<DagSnapshot> terminal();

    @Override
    void close();
}
