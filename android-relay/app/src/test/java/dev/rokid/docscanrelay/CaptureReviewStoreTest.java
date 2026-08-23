package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CaptureReviewStoreTest {
    @Test
    public void stagedPhotoKeepsTheOriginalPageAndBytesUntilConfirmed() {
        CaptureReviewStore store = new CaptureReviewStore();
        byte[] jpeg = new byte[]{1, 2, 3};

        CaptureReviewStore.Pending pending =
                store.stage(4, jpeg, "本文", 90, "");

        assertTrue(store.hasPending());
        assertEquals(4, pending.pageIndex);
        assertSame(jpeg, pending.jpeg);
        assertEquals(2, pending.ocrCharacters());
        assertFalse(pending.hasOcrFailure());
    }

    @Test
    public void failedOrEmptyOcrStillRequiresReviewOfTheSamePage() {
        CaptureReviewStore store = new CaptureReviewStore();

        CaptureReviewStore.Pending empty =
                store.stage(2, new byte[]{7}, "", 90, "");
        assertEquals(2, store.peek().pageIndex);
        assertEquals(0, empty.ocrCharacters());

        CaptureReviewStore.Pending failed =
                store.stage(2, new byte[]{8}, "", 90, "model failed");
        assertSame(failed, store.peek());
        assertTrue(failed.hasOcrFailure());
    }

    @Test
    public void onlyTheCurrentlyDisplayedPhotoCanBeCleared() {
        CaptureReviewStore store = new CaptureReviewStore();
        CaptureReviewStore.Pending first =
                store.stage(0, new byte[]{1}, "first", 0, "");
        CaptureReviewStore.Pending replacement =
                store.stage(0, new byte[]{2}, "second", 0, "");

        assertFalse(store.clear(first));
        assertSame(replacement, store.peek());
        assertTrue(store.clear(replacement));
        assertFalse(store.hasPending());
    }

    @Test
    public void uploadAuthorityExistsOnlyAfterExplicitConfirmation() {
        CaptureReviewStore store = new CaptureReviewStore();
        CaptureReviewStore.Pending pending =
                store.stage(1, new byte[]{4, 5}, "本文", 90, "");

        assertTrue(store.hasPending());
        CaptureReviewStore.Confirmation confirmation = store.confirm();
        assertSame(pending, confirmation.pending());
        assertTrue(store.clear(confirmation));
        assertFalse(store.hasPending());
    }
}
