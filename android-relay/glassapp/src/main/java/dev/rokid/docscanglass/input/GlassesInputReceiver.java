package dev.rokid.docscanglass.input;

import java.util.Objects;
import java.util.function.Consumer;

/** Exact-once lifecycle guard and content-free adapter for platform broadcasts. */
public final class GlassesInputReceiver {

    @FunctionalInterface
    public interface PlatformOperation {
        void run();
    }

    private final Consumer<InputSignal> listener;
    private boolean registered;

    public GlassesInputReceiver(Consumer<InputSignal> listener) {
        this.listener = Objects.requireNonNull(listener, "listener");
    }

    public synchronized boolean register(PlatformOperation operation) {
        Objects.requireNonNull(operation, "operation");
        if (registered) {
            return false;
        }
        operation.run();
        registered = true;
        return true;
    }

    public synchronized boolean unregister(PlatformOperation operation) {
        Objects.requireNonNull(operation, "operation");
        if (!registered) {
            return false;
        }
        operation.run();
        registered = false;
        return true;
    }

    public synchronized boolean registered() {
        return registered;
    }

    public void accept(long elapsedMillis, String action) {
        InputSignal signal;
        synchronized (this) {
            if (!registered || action == null) {
                return;
            }
            signal = InputSignal.broadcast(
                    elapsedMillis, action, OfficialKeyBroadcasts.isOfficial(action));
        }
        listener.accept(signal);
    }
}
