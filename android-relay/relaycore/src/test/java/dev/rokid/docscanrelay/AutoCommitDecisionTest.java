package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * Registration is reachable from the glasses only as the outcome of doing
 * nothing, so the rules that retire a running countdown carry the whole
 * safety margin.
 */
public class AutoCommitDecisionTest {
    @Test
    public void aFramingPassCommitsSoonerThanAnythingUnverified() {
        long pass = DocScanController.autoCommitDelayMillis(
                pendingWith(framing(200, 150, 1700, 200)));
        long clipped = DocScanController.autoCommitDelayMillis(
                pendingWith(framing(200, 150, 1919, 200)));
        long noText = DocScanController.autoCommitDelayMillis(
                pendingWith(PageFraming.builder(1920, 1080).build()));
        long unknown = DocScanController.autoCommitDelayMillis(
                pendingWith(PageFraming.UNKNOWN));

        assertTrue(pass < clipped);
        assertEquals(clipped, noText);
        assertEquals(clipped, unknown);
    }

    @Test
    public void anArmedLocalReviewCanCommitOnlyWhileItsGenerationStillOwnsTheScreen() {
        assertTrue(DocScanController.shouldAutoCommit(
                RelayState.CAPTURE_REVIEW, 7, 7, true));
    }

    @Test
    public void aTapThatLeftReviewRetiresTheCountdown() {
        // The tap routes to a retake, which publishes AIMING.
        assertFalse(DocScanController.shouldAutoCommit(
                RelayState.AIMING, 7, 7, true));
        assertFalse(DocScanController.shouldAutoCommit(
                RelayState.STABILIZING, 7, 7, true));
        assertFalse(DocScanController.shouldAutoCommit(
                RelayState.READING, 7, 7, true));
    }

    @Test
    public void aNewerReviewRetiresAnOlderCountdown() {
        assertFalse(DocScanController.shouldAutoCommit(
                RelayState.CAPTURE_REVIEW, 7, 8, true));
    }

    @Test
    public void anUnarmedReviewNeverRegistersOnItsOwn() {
        // Re-publishes after a failed upload are deliberately unarmed, so a
        // failing server is never retried on a loop.
        assertFalse(DocScanController.shouldAutoCommit(
                RelayState.CAPTURE_REVIEW, 7, 7, false));
    }

    @Test
    public void aManualRegistrationInFlightRetiresTheCountdown() {
        assertFalse(DocScanController.shouldAutoCommit(
                RelayState.UPLOADING, 7, 7, true));
    }

    private static PageFraming framing(int left, int top, int right, int bottom) {
        return PageFraming.builder(1920, 1080)
                .addLineBounds(left, top, right, bottom)
                .build();
    }

    private static CaptureReviewStore.Pending pendingWith(PageFraming framing) {
        return new CaptureReviewStore.Pending(
                0, new byte[]{1, 2, 3}, "text", 90, "", framing);
    }
}
