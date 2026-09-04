package dev.rokid.docscanglass.doc;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Optional;

/**
 * Pages photographed but not yet accepted by the server.
 *
 * <p>Measured 2026-09-04: with Wi-Fi off the glasses hold no IPv4 address and
 * no route, and an HTTP call fails with {@code ConnectException} in under
 * 40 ms — yet the camera still returns a full 4032x3024 still in about 800 ms.
 * Capture therefore outlives connectivity and the pages have to wait here.
 *
 * <p>Two rules the tests pin down. Order is never changed, because the server
 * keys page replacement on {@code (document_id, page_index)} and a rotated
 * queue would file one page as another. And the queue is bounded and refuses
 * rather than evicting: silently dropping the oldest page would finalize a
 * document that is missing a page nobody was told about.
 */
public final class UploadQueue {

    /**
     * Stills measured at 5.7-6.1 MB each, against a 256 MB heap on a device
     * that reports {@code ro.config.low_ram=true}. Twenty is about 120 MB of
     * backlog, which is a long offline stretch and still short of the heap.
     */
    public static final int MAX_PENDING = 20;

    private final Deque<PendingPage> pending = new ArrayDeque<>();
    private long bufferedBytes;

    /**
     * @return false when the page carries no image, or when the buffer is
     *     full. A false here is the operator's cue to restore connectivity,
     *     not something to swallow.
     */
    public synchronized boolean enqueue(PendingPage page) {
        if (page == null || page.jpeg().length == 0) {
            return false;
        }
        if (pending.size() >= MAX_PENDING) {
            return false;
        }
        pending.addLast(page);
        bufferedBytes += page.jpeg().length;
        return true;
    }

    /** The page to send next. Never reordered. */
    public synchronized Optional<PendingPage> head() {
        return Optional.ofNullable(pending.peekFirst());
    }

    public synchronized void markUploaded() {
        PendingPage done = pending.pollFirst();
        if (done != null) {
            bufferedBytes -= done.jpeg().length;
        }
    }

    /** Leaves the page at the head and counts the attempt. */
    public synchronized void markFailed() {
        PendingPage head = pending.peekFirst();
        if (head != null) {
            head.recordAttempt();
        }
    }

    public synchronized int size() {
        return pending.size();
    }

    public synchronized long bufferedBytes() {
        return bufferedBytes;
    }
}
