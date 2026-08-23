package dev.rokid.docscanrelay;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.fail;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;

import org.junit.Test;

public class CaptureReviewTransactionTest {
    @Test
    public void failedReplacementKeepsOldPhotoInMemoryAndOnDisk() throws Exception {
        File directory = Files.createTempDirectory("docscan-transaction").toFile();
        CaptureReviewPersistence persistence =
                new CaptureReviewPersistence(new File(directory, "capture.bin"));
        CaptureReviewStore store = new CaptureReviewStore();
        CaptureReviewStore.Pending oldPhoto =
                store.stage(0, new byte[]{1, 2}, "old", 90, "");
        persistence.save(oldPhoto);
        CaptureReviewStore.Pending replacement =
                new CaptureReviewStore.Pending(0, new byte[]{8, 9}, "new", 90, "");

        try {
            CaptureReviewTransaction.replace(
                    store,
                    replacement,
                    ignored -> {
                        throw new IOException("injected write failure");
                    });
            fail("replacement should fail");
        } catch (IOException expected) {
            // Expected.
        }

        assertSame(oldPhoto, store.peek());
        assertArrayEquals(
                oldPhoto.jpeg,
                persistence.loadOrNull().jpeg);
    }

    @Test
    public void successfulReplacementPublishesOnlyTheDurableCandidate() throws Exception {
        File directory = Files.createTempDirectory("docscan-transaction").toFile();
        CaptureReviewPersistence persistence =
                new CaptureReviewPersistence(new File(directory, "capture.bin"));
        CaptureReviewStore store = new CaptureReviewStore();
        CaptureReviewStore.Pending candidate =
                new CaptureReviewStore.Pending(1, new byte[]{5, 6}, "new", 180, "");

        CaptureReviewStore.Pending committed = CaptureReviewTransaction.replace(
                store,
                candidate,
                persistence::save);

        assertSame(candidate, committed);
        assertSame(candidate, store.peek());
        assertArrayEquals(candidate.jpeg, persistence.loadOrNull().jpeg);
    }
}
