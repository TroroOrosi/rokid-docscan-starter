package dev.rokid.docscanrelay;

import java.util.ArrayDeque;

/**
 * Correlates generation-less CustomView callbacks to requests in FIFO order.
 *
 * <p>The SDK callback has no request id. Treating only the most recently
 * requested generation as usable after its own FIFO open acknowledgement is
 * conservative: reversed or missing callbacks may delay/abort input, but can
 * never turn an old close into a shutter action.</p>
 */
final class CustomViewOpenTracker {
    static final long NONE = -1;

    private final ArrayDeque<Long> pendingOpenGenerations = new ArrayDeque<>();
    private long generation;
    private long acknowledgedGeneration = NONE;
    private boolean epochFaulted;

    synchronized long requestOpen() {
        if (epochFaulted) {
            throw new IllegalStateException(
                    "CustomView callback epoch is fenced until service rebind");
        }
        generation++;
        acknowledgedGeneration = NONE;
        pendingOpenGenerations.addLast(generation);
        return generation;
    }

    synchronized void rejectOpen(long rejectedGeneration) {
        pendingOpenGenerations.removeLastOccurrence(rejectedGeneration);
        if (generation == rejectedGeneration) {
            acknowledgedGeneration = NONE;
        }
        epochFaulted = true;
    }

    /**
     * @return the generation assigned to this callback, or {@link #NONE}.
     */
    synchronized long onOpened() {
        if (epochFaulted || pendingOpenGenerations.isEmpty()) {
            return NONE;
        }
        long openedGeneration = pendingOpenGenerations.removeFirst();
        if (openedGeneration == generation) {
            acknowledgedGeneration = openedGeneration;
        }
        return openedGeneration;
    }

    /**
     * Assigns an error to the oldest unacknowledged request. With no pending
     * request, an error applies to the currently acknowledged view.
     */
    synchronized long onError() {
        long failedGeneration;
        if (!pendingOpenGenerations.isEmpty()) {
            failedGeneration = pendingOpenGenerations.removeFirst();
        } else {
            failedGeneration = acknowledgedGeneration;
        }
        if (failedGeneration == generation) {
            acknowledgedGeneration = NONE;
        }
        epochFaulted = true;
        return failedGeneration;
    }

    synchronized boolean isCurrentAcknowledged() {
        return acknowledgedGeneration == generation && generation > 0;
    }

    synchronized boolean isCurrentAcknowledged(long candidateGeneration) {
        return candidateGeneration == generation
                && acknowledgedGeneration == candidateGeneration;
    }

    synchronized long currentGeneration() {
        return generation;
    }

    synchronized void onCurrentClosed() {
        acknowledgedGeneration = NONE;
    }

    synchronized void fault() {
        pendingOpenGenerations.clear();
        acknowledgedGeneration = NONE;
        epochFaulted = true;
    }

    synchronized boolean isFaulted() {
        return epochFaulted;
    }

    /** Starts a genuinely new callback epoch after service rebind. */
    synchronized void reset() {
        pendingOpenGenerations.clear();
        acknowledgedGeneration = NONE;
        epochFaulted = false;
    }
}
