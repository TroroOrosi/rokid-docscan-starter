package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import java.io.File;
import java.io.IOException;
import java.util.UUID;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class CaptureProvenanceTest {
    @Rule public TemporaryFolder folder = new TemporaryFolder();

    @Test public void pendingRestartRetainsExactNativeOriginalAndItsObservedMetadata() throws Exception {
        byte[] jpeg = {1, 2, 3};
        CaptureProvenance source = nativeSource(jpeg).bind(UUID.randomUUID().toString(), 0, 270);
        CaptureReviewPersistence disk = new CaptureReviewPersistence(new File(folder.getRoot(), "pending.bin"));
        CaptureReviewStore.Pending pending = pending(jpeg, source);
        disk.save(pending);
        CaptureReviewStore.Pending restarted = disk.readPending();
        assertArrayEquals(jpeg, restarted.jpeg);
        assertEquals(source, restarted.provenance);
        assertTrue(disk.matches(pending));
    }

    @Test public void mismatchedOrMissingSensorResultsRemainExplicitlyUnknown() {
        for (Long resultTimestamp : new Long[]{null, 0L, 11L}) {
            CaptureProvenance source = CaptureProvenance.nativeStill(new byte[]{1}, 4032, 3024,
                    10L, resultTimestamp, 5L, 25_000_000L, 400, 0, 2);
            assertEquals(Long.valueOf(10), source.imageTimestampNanos);
            assertNull(source.resultTimestampNanos);
            assertNull(source.frameNumber);
            assertNull(source.exposureNanos);
            assertNull(source.sensitivityIso);
            assertNull(source.afState);
            assertNull(source.aeState);
        }
        CaptureProvenance unknown = CaptureProvenance.nativeStill(new byte[]{1}, 4032, 3024,
                null, 10L, 5L, 25_000_000L, 400, 0, 2);
        assertNull(unknown.imageTimestampNanos);
        assertNull(unknown.resultTimestampNanos);
    }

    @Test public void zslRetainsItsSourceExposureAndRejectsMissingOrMismatchedResults() throws Exception {
        byte[] jpeg = {1, 2, 3};
        CaptureProvenance source = CaptureProvenance.zslReprocess(jpeg, 4032, 3024,
                Long.MAX_VALUE, Long.MAX_VALUE, 5L, 25_000_000L, 400, 0, 2)
                .bind(UUID.randomUUID().toString(), 0, 270);
        CaptureReviewPersistence disk = new CaptureReviewPersistence(new File(folder.getRoot(), "zsl.bin"));
        disk.save(pending(jpeg, source));
        assertEquals("zsl_reprocess", source.sourceKind);
        assertEquals(Long.valueOf(Long.MAX_VALUE), source.imageTimestampNanos);
        assertEquals(source.imageTimestampNanos, source.resultTimestampNanos);
        assertEquals(source, disk.readPending().provenance);
        assertTrue(disk.matches(pending(jpeg, source)));
        try (java.io.DataInputStream data = new java.io.DataInputStream(new java.io.FileInputStream(
                new File(folder.getRoot(), "zsl.bin")))) {
            data.readInt();
            assertEquals(5, data.readInt());
        }
        for (Long[] timestamps : new Long[][]{{null, null}, {10L, null}, {null, 10L},
                {0L, 0L}, {-1L, -1L}, {10L, 11L}}) {
            assertThrows(IllegalArgumentException.class, () -> CaptureProvenance.zslReprocess(
                    jpeg, 4032, 3024, timestamps[0], timestamps[1], null, null, null, null, null));
        }
        CaptureProvenance unknownResultFields = CaptureProvenance.zslReprocess(jpeg, 4032, 3024,
                10L, 10L, null, null, null, null, null);
        assertNull(unknownResultFields.frameNumber);
        assertNull(unknownResultFields.exposureNanos);
        assertNull(unknownResultFields.sensitivityIso);
        assertNull(unknownResultFields.afState);
        assertNull(unknownResultFields.aeState);
    }

    @Test public void unknownMetadataSurvivesRestartAndLegacyCapturesKeepTheirFormat() throws Exception {
        byte[] jpeg = {1, 2, 3};
        CaptureReviewPersistence disk = new CaptureReviewPersistence(new File(folder.getRoot(), "pending.bin"));
        CaptureProvenance source = CaptureProvenance.nativeStill(jpeg, 4032, 3024,
                10L, null, null, null, null, null, null);
        disk.save(pending(jpeg, source));
        assertEquals(source, disk.readPending().provenance);
        assertNull(disk.readPending().provenance.resultTimestampNanos);
        disk.save(pending(jpeg, null));
        try (java.io.DataInputStream data = new java.io.DataInputStream(new java.io.FileInputStream(
                new File(folder.getRoot(), "pending.bin")))) {
            data.readInt();
            assertEquals("the frozen relay still writes its existing record version", 3, data.readInt());
        }
        assertNull(disk.readPending().provenance);
    }

    @Test public void aDifferentOriginalCannotBorrowTheSavedIdentity() throws Exception {
        byte[] jpeg = {1, 2, 3};
        CaptureProvenance first = nativeSource(jpeg).bind(UUID.randomUUID().toString(), 0, 270);
        CaptureReviewPersistence disk = new CaptureReviewPersistence(new File(folder.getRoot(), "pending.bin"));
        disk.save(pending(jpeg, first));
        assertThrows(IOException.class, () -> disk.save(pending(new byte[]{9, 8, 7}, first)));
        assertEquals(first, disk.readPending().provenance);
        assertArrayEquals(jpeg, disk.readPending().jpeg);
        assertThrows(IllegalArgumentException.class, () -> first.bind(UUID.randomUUID().toString(), 0, 270));
        assertThrows(IllegalArgumentException.class, () -> first.bind(first.localSessionId, 0, 90));
        assertNotEquals(first.captureId, nativeSource(jpeg).captureId);
    }

    @Test public void localRestartRetakeAndLateAcknowledgementRetainEachExactAssociation() throws Exception {
        assertLocalRestartRetakeAndLateAcknowledgement(false);
        assertLocalRestartRetakeAndLateAcknowledgement(true);
    }

    private void assertLocalRestartRetakeAndLateAcknowledgement(boolean reprocessed) throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        byte[] firstJpeg = {1, 2, 3}, nextJpeg = {4, 5, 6};
        CaptureProvenance first = source(firstJpeg, reprocessed).bind(session.id(), 0, 270);
        session.commit(pending(firstJpeg, first));
        LocalCaptureSession.Page old = session.nextUnsent();
        CaptureProvenance next = source(nextJpeg, reprocessed).bind(session.id(), 0, 270);
        session.commit(pending(nextJpeg, next));
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        restarted.acknowledge(old);
        assertNotNull(restarted.nextUnsent());
        assertEquals(first, restarted.read(old).provenance);
        assertEquals(next, restarted.read(restarted.nextUnsent()).provenance);
        assertNotEquals(old.fileName, restarted.nextUnsent().fileName);
        LocalCaptureSession other = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        assertThrows(IOException.class, () -> other.commit(pending(nextJpeg, next)));
        assertEquals(0, other.pageCount());
    }

    private static CaptureProvenance nativeSource(byte[] jpeg) {
        return CaptureProvenance.nativeStill(jpeg, 4032, 3024, 10L, 10L, 5L, 25_000_000L, 400, 0, 2);
    }
    private static CaptureProvenance source(byte[] jpeg, boolean reprocessed) {
        return reprocessed ? CaptureProvenance.zslReprocess(
                jpeg, 4032, 3024, 10L, 10L, 5L, 25_000_000L, 400, 0, 2) : nativeSource(jpeg);
    }
    private static CaptureReviewStore.Pending pending(byte[] jpeg, CaptureProvenance source) {
        return new CaptureReviewStore.Pending(0, jpeg, "", 270, "", PageFraming.UNKNOWN, 1000L, source);
    }
}
