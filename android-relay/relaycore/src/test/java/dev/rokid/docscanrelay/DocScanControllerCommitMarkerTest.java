package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class DocScanControllerCommitMarkerTest {
    @Test
    public void restoredMarkerMatchesOnlyTheCommittedPageAndJpeg() {
        CaptureReviewStore.Pending committed = pending(3, new byte[]{1, 2, 3});
        DocScanController.FallbackCommitMarker created =
                DocScanController.FallbackCommitMarker.fromPendingOrNull(committed);

        assertNotNull(created);
        DocScanController.FallbackCommitMarker restored =
                DocScanController.FallbackCommitMarker.restoreOrNull(
                        created.pageIndex,
                        created.jpegSha256.toUpperCase());

        assertNotNull(restored);
        assertTrue(restored.matches(committed));
        assertFalse(restored.matches(pending(4, committed.jpeg)));
        assertFalse(restored.matches(pending(3, new byte[]{1, 2, 4})));
    }

    @Test
    public void malformedPreferenceMarkerIsRejected() {
        assertNull(DocScanController.FallbackCommitMarker.restoreOrNull(-1, repeat('0', 64)));
        assertNull(DocScanController.FallbackCommitMarker.restoreOrNull(0, "abc"));
        assertNull(DocScanController.FallbackCommitMarker.restoreOrNull(0, repeat('z', 64)));
    }

    @Test
    public void emptyPendingCaptureCannotCreateMarker() {
        assertNull(DocScanController.FallbackCommitMarker.fromPendingOrNull(
                pending(0, new byte[0])));
    }

    @Test
    public void cleanupFailureKeepsFallbackMarkerForTheNextRestart() {
        boolean[] fallbackDeleteCalled = {false};

        boolean cleared = DocScanController.clearFallbackOnlyAfterRecovery(
                false,
                true,
                () -> {
                    fallbackDeleteCalled[0] = true;
                    return true;
                });

        assertFalse(cleared);
        assertFalse(fallbackDeleteCalled[0]);
    }

    @Test
    public void successfulCleanupMayDeleteTheFallbackMarker() {
        boolean[] fallbackDeleteCalled = {false};

        boolean cleared = DocScanController.clearFallbackOnlyAfterRecovery(
                true,
                true,
                () -> {
                    fallbackDeleteCalled[0] = true;
                    return true;
                });

        assertTrue(cleared);
        assertTrue(fallbackDeleteCalled[0]);
    }

    private static CaptureReviewStore.Pending pending(int pageIndex, byte[] jpeg) {
        return new CaptureReviewStore.Pending(pageIndex, jpeg, "", 0, "");
    }

    private static String repeat(char value, int count) {
        StringBuilder result = new StringBuilder(count);
        for (int i = 0; i < count; i++) {
            result.append(value);
        }
        return result.toString();
    }
}
