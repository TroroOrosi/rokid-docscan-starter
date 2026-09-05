package dev.rokid.docscanrelay;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;

import java.io.File;
import java.nio.file.Files;

import org.junit.Test;

public class CaptureReviewPersistenceTest {
    @Test
    public void atomicallyRestoresAndReplacesThePendingPhoto() throws Exception {
        File directory = Files.createTempDirectory("docscan-pending").toFile();
        File file = new File(directory, "capture.bin");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(file);

        persistence.save(new CaptureReviewStore.Pending(
                2, new byte[]{1, 2, 3}, "本文", 90, ""));
        CaptureReviewStore.Pending first = persistence.loadOrNull();
        assertEquals(2, first.pageIndex);
        assertEquals("本文", first.ocrText);
        assertEquals(90, first.rotationDegrees);
        assertArrayEquals(new byte[]{1, 2, 3}, first.jpeg);

        persistence.save(new CaptureReviewStore.Pending(
                2, new byte[]{9, 8}, "", 180, "OCR error"));
        CaptureReviewStore.Pending replacement = persistence.loadOrNull();
        assertEquals(180, replacement.rotationDegrees);
        assertEquals("OCR error", replacement.ocrFailure);
        assertArrayEquals(new byte[]{9, 8}, replacement.jpeg);

        persistence.clear();
        assertNull(persistence.loadOrNull());
        assertFalse(file.exists());
    }

    @Test
    public void corruptStateIsDeletedAndNeverRecovered() throws Exception {
        File directory = Files.createTempDirectory("docscan-corrupt").toFile();
        File file = new File(directory, "capture.bin");
        Files.write(file.toPath(), new byte[]{1, 2, 3});
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(file);

        assertNull(persistence.loadOrNull());
        assertFalse(file.exists());
    }

    @Test
    public void matchingCommitMarkerSuppressesARegisteredPendingPhotoAfterRestart()
            throws Exception {
        File directory = Files.createTempDirectory("docscan-committed").toFile();
        File file = new File(directory, "capture.bin");
        File marker = new File(directory, "capture.bin.committed");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(file);
        CaptureReviewStore.Pending pending = new CaptureReviewStore.Pending(
                3, new byte[]{4, 5, 6}, "登録済み", 90, "");

        persistence.save(pending);
        persistence.markCommitted(pending);

        CaptureReviewPersistence restarted = new CaptureReviewPersistence(file);
        assertNull(restarted.loadOrNull());
        assertEquals(3, restarted.consumeRecoveredCommittedPageIndex());
        assertEquals(-1, restarted.consumeRecoveredCommittedPageIndex());
        assertFalse(file.exists());
        assertFalse(marker.exists());
    }

    @Test
    public void mismatchedCommitMarkerIsRemovedWithoutRemovingPendingPhoto()
            throws Exception {
        File directory = Files.createTempDirectory("docscan-mismatch").toFile();
        File file = new File(directory, "capture.bin");
        File marker = new File(directory, "capture.bin.committed");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(file);
        CaptureReviewStore.Pending committed = new CaptureReviewStore.Pending(
                1, new byte[]{1, 1, 1}, "old", 0, "");
        CaptureReviewStore.Pending replacement = new CaptureReviewStore.Pending(
                1, new byte[]{2, 2, 2}, "new", 0, "");

        persistence.save(committed);
        persistence.markCommitted(committed);
        persistence.save(replacement);

        CaptureReviewStore.Pending restored = persistence.loadOrNull();
        assertEquals(1, restored.pageIndex);
        assertArrayEquals(replacement.jpeg, restored.jpeg);
        assertFalse(marker.exists());
        assertEquals("new", restored.ocrText);
    }

    @Test
    public void pageIndexMustAlsoMatchTheCommitMarker() throws Exception {
        File directory = Files.createTempDirectory("docscan-page-mismatch").toFile();
        File file = new File(directory, "capture.bin");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(file);
        byte[] sameJpeg = new byte[]{7, 8, 9};
        CaptureReviewStore.Pending committed = new CaptureReviewStore.Pending(
                0, sameJpeg, "old page", 0, "");
        CaptureReviewStore.Pending anotherPage = new CaptureReviewStore.Pending(
                1, sameJpeg, "new page", 0, "");

        persistence.save(committed);
        persistence.markCommitted(committed);
        persistence.save(anotherPage);

        CaptureReviewStore.Pending restored = persistence.loadOrNull();
        assertEquals(1, restored.pageIndex);
        assertArrayEquals(sameJpeg, restored.jpeg);
    }

    @Test
    public void corruptCommitMarkerIsRemovedWithoutRemovingPendingPhoto()
            throws Exception {
        File directory = Files.createTempDirectory("docscan-marker-corrupt").toFile();
        File file = new File(directory, "capture.bin");
        File marker = new File(directory, "capture.bin.committed");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(file);
        CaptureReviewStore.Pending pending = new CaptureReviewStore.Pending(
                4, new byte[]{3, 2, 1}, "pending", 270, "");
        persistence.save(pending);
        Files.write(marker.toPath(), new byte[]{1, 2, 3});

        CaptureReviewStore.Pending restored = persistence.loadOrNull();
        assertEquals(4, restored.pageIndex);
        assertArrayEquals(pending.jpeg, restored.jpeg);
        assertFalse(marker.exists());
    }

    @Test
    public void clearAndClearAfterCommitRemovePendingAndMarkerFiles() throws Exception {
        File directory = Files.createTempDirectory("docscan-clear-marker").toFile();
        File file = new File(directory, "capture.bin");
        File marker = new File(directory, "capture.bin.committed");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(file);
        CaptureReviewStore.Pending pending = new CaptureReviewStore.Pending(
                5, new byte[]{8, 8}, "pending", 180, "");

        persistence.save(pending);
        persistence.markCommitted(pending);
        persistence.clearAfterCommit();
        assertFalse(file.exists());
        assertFalse(marker.exists());

        persistence.save(pending);
        persistence.markCommitted(pending);
        persistence.clear();
        assertFalse(file.exists());
        assertFalse(marker.exists());
    }
}
