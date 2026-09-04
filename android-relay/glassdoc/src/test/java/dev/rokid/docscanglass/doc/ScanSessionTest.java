package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * The scan state machine. Its job is to stop the mistakes hardware made
 * expensive on 2026-09-04: two taps creating two documents, a gesture storm
 * opening the camera twice, a page number consumed by a page the server never
 * accepted, and a page uploaded before the operator saw what was photographed.
 */
public final class ScanSessionTest {

    @Test
    public void startsWithNoDocumentAndRefusesToCapture() {
        ScanSession session = new ScanSession();

        assertEquals(ScanSession.State.NO_DOCUMENT, session.state());
        assertFalse("capture before a document exists would have no page to join",
                session.beginCapture());
    }

    @Test
    public void refusesASecondDocumentRequestWhileTheFirstIsStillInFlight() {
        ScanSession session = new ScanSession();

        assertTrue(session.beginOpenDocument());
        assertEquals(ScanSession.State.OPENING, session.state());

        // Measured 2026-09-04: two taps 1.95 s apart both reached the server,
        // which created documents 3 and 4. The old guard refused the second
        // *response*, by which time the request had gone and document 4 was
        // orphaned. The guard has to sit on the request.
        assertFalse(session.beginOpenDocument());
    }

    @Test
    public void cannotCaptureWhileTheDocumentRequestIsStillInFlight() {
        ScanSession session = new ScanSession();
        session.beginOpenDocument();

        assertFalse(session.beginCapture());
    }

    @Test
    public void allowsAnotherDocumentRequestAfterTheFirstOneFails() {
        ScanSession session = new ScanSession();
        session.beginOpenDocument();

        session.onFailed("ConnectException");

        assertTrue(session.beginOpenDocument());
    }

    @Test
    public void opensADocumentAndThenAcceptsACapture() {
        ScanSession session = openedSession();

        assertEquals(ScanSession.State.READY, session.state());
        assertEquals(41, session.documentId());
        assertEquals(0, session.nextPageIndex());
        assertTrue(session.beginCapture());
        assertEquals(ScanSession.State.CAPTURING, session.state());
    }

    @Test
    public void refusesASecondCaptureWhileOneIsStillRunning() {
        ScanSession session = openedSession();
        assertTrue(session.beginCapture());

        // A capture measured at 785-1380 ms. A stray tap inside that window
        // must not open the camera a second time.
        assertFalse(session.beginCapture());
    }

    @Test
    public void showsTheOperatorTheImageBeforeAnythingIsSent() {
        ScanSession session = openedSession();
        session.beginCapture();

        session.onImageCaptured();

        assertEquals("nothing may be uploaded that the operator was not shown",
                ScanSession.State.REVIEW, session.state());
    }

    @Test
    public void aTapDuringReviewConfirmsThePageAndStartsRecognition() {
        ScanSession session = reviewingSession();

        assertTrue(session.confirmPage());

        assertEquals(ScanSession.State.RECOGNIZING, session.state());
    }

    @Test
    public void aRetakeDuringReviewGoesStraightBackToCapturingWithoutSpendingThePage() {
        ScanSession session = reviewingSession();

        assertTrue(session.beginCapture());

        assertEquals(ScanSession.State.CAPTURING, session.state());
        assertEquals(0, session.nextPageIndex());
    }

    @Test
    public void confirmOutsideReviewIsRefusedSoAStrayTapCannotSendTwice() {
        ScanSession session = reviewingSession();
        session.confirmPage();

        assertFalse(session.confirmPage());
        assertEquals(ScanSession.State.RECOGNIZING, session.state());
    }

    @Test
    public void advancesThePageIndexOnlyWhenTheServerAcceptsThePage() {
        ScanSession session = reviewingSession();
        session.confirmPage();
        session.onTextRecognized();

        assertEquals(ScanSession.State.UPLOADING, session.state());
        assertEquals("still the page being uploaded", 0, session.nextPageIndex());

        session.onPageAccepted();

        assertEquals(ScanSession.State.ACKED, session.state());
        assertEquals(1, session.nextPageIndex());
    }

    @Test
    public void keepsThePageIndexWhenTheUploadFailsSoTheRetryResendsTheSamePage() {
        ScanSession session = reviewingSession();
        session.confirmPage();
        session.onTextRecognized();

        session.onFailed("no route to host");

        assertEquals(ScanSession.State.FAILED, session.state());
        assertEquals("a failed page must not consume a page number",
                0, session.nextPageIndex());
        assertEquals("no route to host", session.lastError());
    }

    @Test
    public void allowsTheNextCaptureAfterAnAcknowledgementAndAfterAFailure() {
        ScanSession session = reviewingSession();
        session.confirmPage();
        session.onTextRecognized();
        session.onPageAccepted();
        assertTrue("the operator photographs the next page", session.beginCapture());

        session.onFailed("timeout");
        assertTrue("a failure must not strand the operator", session.beginCapture());
    }

    @Test
    public void clearsTheErrorOnceTheNextCaptureStarts() {
        ScanSession session = openedSession();
        session.beginCapture();
        session.onFailed("camera error 3");
        assertEquals("camera error 3", session.lastError());

        session.beginCapture();

        assertEquals("", session.lastError());
    }

    @Test
    public void resetReturnsToTheNoDocumentStateWithAFreshPageCount() {
        ScanSession session = reviewingSession();
        session.confirmPage();
        session.onTextRecognized();
        session.onPageAccepted();

        session.reset();

        assertEquals(ScanSession.State.NO_DOCUMENT, session.state());
        assertEquals(0, session.nextPageIndex());
        assertEquals(-1, session.documentId());
    }

    private static ScanSession openedSession() {
        ScanSession session = new ScanSession();
        session.beginOpenDocument();
        session.openDocument(41);
        return session;
    }

    private static ScanSession reviewingSession() {
        ScanSession session = openedSession();
        session.beginCapture();
        session.onImageCaptured();
        return session;
    }
}
