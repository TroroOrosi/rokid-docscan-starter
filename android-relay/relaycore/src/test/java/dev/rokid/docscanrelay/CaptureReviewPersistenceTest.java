package dev.rokid.docscanrelay;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;

import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Files;

import org.junit.Test;

public class CaptureReviewPersistenceTest {
    @Test
    public void theProducerKindIsPartOfTheSameOriginalsIdentity() throws Exception {
        File directory = Files.createTempDirectory("docscan-producer-identity").toFile();
        File nativeFile = new File(directory, "native.bin");
        File zslFile = new File(directory, "zsl.bin");
        writeFixture(nativeFile, 5, "native_still", 100L, 100L);
        writeFixture(zslFile, 5, "zsl_reprocess", 100L, 100L);
        CaptureReviewPersistence nativeDisk = new CaptureReviewPersistence(nativeFile);
        CaptureReviewStore.Pending zsl = new CaptureReviewPersistence(zslFile).readPending();
        assertFalse(nativeDisk.readPending().provenance.equals(zsl.provenance));
        assertFalse(nativeDisk.matches(zsl));
    }

    @Test
    public void v5RetainsTheSelectedProducerAndItsMatchingExposureAcrossRestart() throws Exception {
        File file = new File(Files.createTempDirectory("docscan-v5").toFile(), "capture.bin");
        writeFixture(file, 5, "zsl_reprocess", 100L, 100L);
        CaptureReviewPersistence disk = new CaptureReviewPersistence(file);
        CaptureReviewStore.Pending restored = disk.readPending();
        assertEquals("zsl_reprocess", restored.provenance.sourceKind);
        assertEquals(Long.valueOf(100), restored.provenance.imageTimestampNanos);
        assertEquals(Long.valueOf(100), restored.provenance.resultTimestampNanos);
        disk.save(restored);
        assertEquals(restored.provenance, disk.readPending().provenance);
        assertEquals("zsl_reprocess", disk.readPending().provenance.sourceKind);
        assertArrayEquals(new byte[]{1, 2, 3}, disk.readPending().jpeg);
    }

    @Test
    public void oldV1ThroughV4OriginalsRemainReadableWithTheirOriginalIdentity() throws Exception {
        File file = new File(Files.createTempDirectory("docscan-legacy").toFile(), "capture.bin");
        CaptureReviewPersistence disk = new CaptureReviewPersistence(file);
        for (int version = 1; version <= 4; version++) {
            writeFixture(file, version, "native_still", null, null);
            CaptureReviewStore.Pending restored = disk.readPending();
            assertArrayEquals(new byte[]{1, 2, 3}, restored.jpeg);
            assertEquals(0, restored.pageIndex);
            assertEquals(270, restored.rotationDegrees);
            assertEquals(version >= 3 ? 1234 : 0, restored.capturedAtMillis);
            if (version < 4) assertNull(restored.provenance);
            else {
                assertEquals("native_still", restored.provenance.sourceKind);
                assertNull(restored.provenance.imageTimestampNanos);
                assertNull(restored.provenance.resultTimestampNanos);
                assertEquals("11111111-1111-4111-8111-111111111111", restored.provenance.captureId);
            }
        }
    }

    @Test
    public void v5RejectsUnknownProducerAndZslWithMissingOrDifferentExposure() throws Exception {
        File file = new File(Files.createTempDirectory("docscan-v5-reject").toFile(), "capture.bin");
        CaptureReviewPersistence disk = new CaptureReviewPersistence(file);
        writeFixture(file, 5, "video_frame", 100L, 100L);
        assertThrows(IOException.class, disk::readPending);
        for (Long[] timestamps : new Long[][]{{null, null}, {100L, null}, {null, 100L},
                {0L, 0L}, {-1L, -1L}, {100L, 101L}}) {
            writeFixture(file, 5, "zsl_reprocess", timestamps[0], timestamps[1]);
            assertThrows(IOException.class, disk::readPending);
        }
        writeFixture(file, 5, "native_still", null, null);
        assertNull(disk.readPending().provenance.resultTimestampNanos);
    }

    private static void writeFixture(File file, int version, String kind, Long imageTs, Long resultTs)
            throws Exception {
        try (DataOutputStream data = new DataOutputStream(new FileOutputStream(file))) {
            data.writeInt(0x44534350);
            data.writeInt(version);
            data.writeInt(0);
            data.writeInt(270);
            writeBytes(data, new byte[0]);
            writeBytes(data, new byte[0]);
            if (version >= 2) writeBytes(data, PageFraming.UNKNOWN.toToken().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            writeBytes(data, new byte[]{1, 2, 3});
            if (version >= 3) data.writeLong(1234);
            if (version >= 4) {
                if (version >= 5) data.writeUTF(kind);
                data.writeUTF("11111111-1111-4111-8111-111111111111");
                data.writeUTF("039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81");
                data.writeInt(4032);
                data.writeInt(3024);
                writeLong(data, imageTs);
                writeLong(data, resultTs);
                for (int index = 0; index < 5; index++) writeLong(data, null);
                data.writeUTF("");
                data.writeInt(-1);
                data.writeInt(-1);
            }
        }
    }

    private static void writeBytes(DataOutputStream data, byte[] bytes) throws Exception {
        data.writeInt(bytes.length);
        data.write(bytes);
    }

    private static void writeLong(DataOutputStream data, Long value) throws Exception {
        data.writeBoolean(value != null);
        if (value != null) data.writeLong(value);
    }

    @Test
    public void atomicallyRestoresAndReplacesThePendingPhoto() throws Exception {
        File directory = Files.createTempDirectory("docscan-pending").toFile();
        File file = new File(directory, "capture.bin");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(file);

        persistence.save(new CaptureReviewStore.Pending(
                2, new byte[]{1, 2, 3}, "本文", 90, "", PageFraming.UNKNOWN, 1720000000123L));
        CaptureReviewStore.Pending first = persistence.loadOrNull();
        assertEquals(2, first.pageIndex);
        assertEquals(1720000000123L, first.capturedAtMillis);
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
