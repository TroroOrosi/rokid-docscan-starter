package dev.rokid.docscanrelay;

import java.util.ArrayDeque;

/**
 * Distinguishes asynchronous CustomView close callbacks caused by this app
 * from a close initiated on the glasses.
 */
final class CustomViewCloseTracker {
    private static final class Expectation {
        final long viewGeneration;
        final long deadlineMillis;

        Expectation(long viewGeneration, long deadlineMillis) {
            this.viewGeneration = viewGeneration;
            this.deadlineMillis = deadlineMillis;
        }
    }

    private final long expectationTtlMillis;
    private final ArrayDeque<Expectation> programmaticCloses = new ArrayDeque<>();
    private final ArrayDeque<Long> orphanedCloseDeadlines = new ArrayDeque<>();
    private long lastUserClosedGeneration = -1;

    CustomViewCloseTracker(long expectationTtlMillis) {
        if (expectationTtlMillis <= 0) {
            throw new IllegalArgumentException("close expectation TTL must be positive");
        }
        this.expectationTtlMillis = expectationTtlMillis;
    }

    synchronized void expectProgrammaticClose(long nowMillis, long viewGeneration) {
        pruneExpired(nowMillis);
        programmaticCloses.addLast(
                new Expectation(viewGeneration, nowMillis + expectationTtlMillis));
    }

    /**
     * @return true when no current app-initiated close explains the callback.
     */
    synchronized boolean onClosed(
            long nowMillis,
            long currentGeneration,
            boolean remoteStillOpen,
            boolean localViewWasOpen
    ) {
        pruneExpired(nowMillis);

        // The callback cannot represent the currently displayed view while
        // the service still reports that view open. It is a delayed close
        // from a replacement (or a duplicate of one).
        if (remoteStillOpen) {
            if (!programmaticCloses.isEmpty()) {
                programmaticCloses.removeFirst();
            } else if (!orphanedCloseDeadlines.isEmpty()) {
                orphanedCloseDeadlines.removeFirst();
            }
            return false;
        }

        // A new view may be tapped before an old app-initiated close callback
        // arrives. The locally open current generation is authoritative: emit
        // one user action for it and quarantine every older expected callback.
        if (localViewWasOpen) {
            if (lastUserClosedGeneration == currentGeneration) {
                return false;
            }
            lastUserClosedGeneration = currentGeneration;
            while (!programmaticCloses.isEmpty()) {
                orphanedCloseDeadlines.addLast(
                        programmaticCloses.removeFirst().deadlineMillis);
            }
            return true;
        }

        if (!programmaticCloses.isEmpty()) {
            programmaticCloses.removeFirst();
            return false;
        }
        if (!orphanedCloseDeadlines.isEmpty()) {
            orphanedCloseDeadlines.removeFirst();
            return false;
        }
        return false;
    }

    synchronized void cancelLatestExpectation() {
        if (!programmaticCloses.isEmpty()) {
            programmaticCloses.removeLast();
        }
    }

    synchronized void reset() {
        programmaticCloses.clear();
        orphanedCloseDeadlines.clear();
        lastUserClosedGeneration = -1;
    }

    private void pruneExpired(long nowMillis) {
        while (!programmaticCloses.isEmpty()
                && programmaticCloses.peekFirst().deadlineMillis < nowMillis) {
            programmaticCloses.removeFirst();
        }
        while (!orphanedCloseDeadlines.isEmpty()
                && orphanedCloseDeadlines.peekFirst() < nowMillis) {
            orphanedCloseDeadlines.removeFirst();
        }
    }
}
