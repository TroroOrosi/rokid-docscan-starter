package dev.rokid.docscanrelay;

/**
 * Tracks the one-shot CXR-L photo request until its terminal callback arrives.
 *
 * <p>CXR-L exposes {@code takePhoto} and success/error callbacks, but no
 * documented cancellation API. A timeout therefore makes the camera state
 * unknown; it must not be treated as permission to start another capture.
 * The lease remains unresolved until a late callback arrives or the link is
 * disconnected.</p>
 */
final class CaptureLease {
    static final long NO_TOKEN = -1;

    static final class Completion {
        final int pageIndex;
        final boolean lateAfterTimeout;

        Completion(int pageIndex, boolean lateAfterTimeout) {
            this.pageIndex = pageIndex;
            this.lateAfterTimeout = lateAfterTimeout;
        }
    }

    private long generation;
    private long token = NO_TOKEN;
    private int pageIndex = -1;
    private boolean timedOut;

    synchronized long begin(int requestedPageIndex) {
        if (isUnresolved()) {
            return NO_TOKEN;
        }
        generation++;
        token = generation;
        pageIndex = requestedPageIndex;
        timedOut = false;
        return token;
    }

    synchronized boolean abortBeforeStart(long expectedToken) {
        if (token != expectedToken || !isUnresolved()) {
            return false;
        }
        clear();
        return true;
    }

    synchronized boolean markTimedOut(long expectedToken) {
        if (token != expectedToken || !isUnresolved() || timedOut) {
            return false;
        }
        timedOut = true;
        return true;
    }

    synchronized Completion complete() {
        if (!isUnresolved()) {
            return null;
        }
        Completion completion = new Completion(pageIndex, timedOut);
        clear();
        return completion;
    }

    synchronized boolean isUnresolved() {
        return token != NO_TOKEN;
    }

    synchronized boolean isTimedOut() {
        return isUnresolved() && timedOut;
    }

    synchronized void resetAfterDisconnect() {
        clear();
        generation++;
    }

    private void clear() {
        token = NO_TOKEN;
        pageIndex = -1;
        timedOut = false;
    }
}
