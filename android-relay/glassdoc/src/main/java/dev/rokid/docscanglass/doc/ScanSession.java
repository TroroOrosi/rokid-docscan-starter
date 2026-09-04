package dev.rokid.docscanglass.doc;

/**
 * One document being photographed from the glasses.
 *
 * <p>Pure Java, so the rules that decide whether a page number is consumed can
 * be tested without a camera, a server, or a device.
 *
 * <p>Four hardware measurements shape it.
 *
 * <ul>
 *   <li>Two taps 1.95 s apart on 2026-09-04 created documents 3 <em>and</em> 4,
 *       because the old guard refused the second response rather than the
 *       second request. {@link #beginOpenDocument()} now holds the request.</li>
 *   <li>A still takes 785-1380 ms, long enough for a second tap to arrive
 *       mid-capture, so {@link #beginCapture()} refuses while one runs.</li>
 *   <li>The operator cannot see through the camera, so a capture stops at
 *       {@link State#REVIEW} until it is confirmed. Nothing is uploaded that
 *       the operator was not shown.</li>
 *   <li>A page the server never accepted must not consume a page number:
 *       {@code (document_id, page_index)} is the server's replacement key, so
 *       advancing on failure would file the retry as the following page.</li>
 * </ul>
 */
public final class ScanSession {

    /**
     * {@code OPENING} is a document creation in flight; {@code REVIEW} is a
     * captured image waiting for the operator to accept or retake it.
     */
    public enum State {
        NO_DOCUMENT, OPENING, READY, CAPTURING, REVIEW, RECOGNIZING, UPLOADING, ACKED, FAILED
    }

    private static final long NO_DOCUMENT_ID = -1;

    private State state = State.NO_DOCUMENT;
    private long documentId = NO_DOCUMENT_ID;
    private int nextPageIndex;
    private String lastError = "";

    public synchronized State state() {
        return state;
    }

    public synchronized long documentId() {
        return documentId;
    }

    /** Zero-based index the next accepted page will take. */
    public synchronized int nextPageIndex() {
        return nextPageIndex;
    }

    public synchronized String lastError() {
        return lastError;
    }

    /**
     * Claims the right to ask the server for a document.
     *
     * @return false when a request is already in flight or a document is
     *     already open. Callers use this to drop the extra tap.
     */
    public synchronized boolean beginOpenDocument() {
        if (state != State.NO_DOCUMENT && state != State.FAILED) {
            return false;
        }
        lastError = "";
        state = State.OPENING;
        return true;
    }

    /** Binds the document the server created for the request in flight. */
    public synchronized boolean openDocument(long id) {
        if (state != State.OPENING) {
            return false;
        }
        documentId = id;
        nextPageIndex = 0;
        lastError = "";
        state = State.READY;
        return true;
    }

    /**
     * @return false while a capture or a document request is in flight, or
     *     before a document exists. From {@link State#REVIEW} this is a
     *     retake, which deliberately costs no page number.
     */
    public synchronized boolean beginCapture() {
        if (state != State.READY && state != State.ACKED
                && state != State.FAILED && state != State.REVIEW) {
            return false;
        }
        if (state == State.FAILED && documentId == NO_DOCUMENT_ID) {
            return false;
        }
        lastError = "";
        state = State.CAPTURING;
        return true;
    }

    /** The image exists but has not been shown to anyone yet. */
    public synchronized void onImageCaptured() {
        if (state == State.CAPTURING) {
            state = State.REVIEW;
        }
    }

    /**
     * The operator accepted what the review showed.
     *
     * @return false outside {@link State#REVIEW}, so a stray tap cannot send
     *     the same page twice.
     */
    public synchronized boolean confirmPage() {
        if (state != State.REVIEW) {
            return false;
        }
        state = State.RECOGNIZING;
        return true;
    }

    public synchronized void onTextRecognized() {
        if (state == State.RECOGNIZING) {
            state = State.UPLOADING;
        }
    }

    /** The only transition that consumes a page number. */
    public synchronized void onPageAccepted() {
        if (state != State.UPLOADING) {
            return;
        }
        nextPageIndex++;
        lastError = "";
        state = State.ACKED;
    }

    public synchronized void onFailed(String reason) {
        lastError = reason == null ? "" : reason;
        state = State.FAILED;
    }

    /** Drops the document binding and the page count. */
    public synchronized void reset() {
        state = State.NO_DOCUMENT;
        documentId = NO_DOCUMENT_ID;
        nextPageIndex = 0;
        lastError = "";
    }
}
