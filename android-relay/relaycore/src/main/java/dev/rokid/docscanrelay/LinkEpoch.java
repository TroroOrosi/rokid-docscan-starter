package dev.rokid.docscanrelay;

/**
 * Issues monotonically increasing epochs for service bindings and callback sets.
 *
 * <p>Callbacks are inactive while registration is incomplete. Starting a new
 * epoch or invalidating the current one makes callbacks already queued by an
 * older Binder registration harmless.</p>
 */
final class LinkEpoch {
    private static final long NO_EPOCH = -1;

    private long generation;
    private long current = NO_EPOCH;
    private boolean active;

    synchronized long begin() {
        generation++;
        current = generation;
        active = false;
        return current;
    }

    synchronized boolean activate(long expectedEpoch) {
        if (current != expectedEpoch) {
            return false;
        }
        active = true;
        return true;
    }

    synchronized boolean isCurrent(long expectedEpoch) {
        return current == expectedEpoch;
    }

    synchronized boolean isActive(long expectedEpoch) {
        return current == expectedEpoch && active;
    }

    synchronized boolean runIfActive(long expectedEpoch, Runnable action) {
        if (!isActive(expectedEpoch)) {
            return false;
        }
        action.run();
        return true;
    }

    synchronized boolean invalidate(long expectedEpoch) {
        if (current != expectedEpoch) {
            return false;
        }
        invalidateCurrent();
        return true;
    }

    synchronized void invalidateCurrent() {
        current = NO_EPOCH;
        active = false;
        generation++;
    }
}
