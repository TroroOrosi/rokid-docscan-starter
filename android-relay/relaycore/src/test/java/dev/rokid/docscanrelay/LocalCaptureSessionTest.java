package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class LocalCaptureSessionTest {
    @Rule public TemporaryFolder folder = new TemporaryFolder();

    @Test public void localCommitRestartReplacementAndAcknowledgementKeepEachRevision() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        assertEquals(0, session.documentId());
        CaptureReviewStore.Pending first = photo(0, 1);
        session.commit(first);
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertEquals(1, restarted.pageCount());
        assertTrue(restarted.contains(first));
        LocalCaptureSession.Page old = restarted.nextUnsent();
        assertArrayEquals(first.jpeg, restarted.read(old).jpeg);
        restarted.bindDocument(17);
        LocalCaptureSession bound = restarted;
        assertThrows(IOException.class, () -> bound.bindDocument(18));
        restarted.commit(photo(0, 2));
        restarted.acknowledge(old); // A late ACK cannot acknowledge the replacement.
        LocalCaptureSession.Page replacement = restarted.nextUnsent();
        assertNotNull(replacement);
        assertArrayEquals(first.jpeg, restarted.read(old).jpeg);
        assertEquals(2, restarted.read(replacement).jpeg[0]);
        restarted.acknowledge(replacement);
        restarted.setPhase(LocalCaptureSession.Phase.ANALYSIS);
        restarted.close();
        restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertEquals(17, restarted.documentId());
        assertNull(restarted.nextUnsent());
        assertEquals(LocalCaptureSession.Phase.CLOSED, restarted.phase());
        restarted.resume();
        assertEquals(LocalCaptureSession.Phase.ANALYSIS, restarted.phase());
    }

    @Test public void failedManifestWriteAndDamagedPageNeverEraseAcceptedPhotos() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", true);
        session.commit(photo(0, 1));
        LocalCaptureSession.Page original = session.nextUnsent();
        File temporary = new File(session.directory(), "state.properties.tmp");
        assertTrue(temporary.mkdir()); // Simulate a write failure after the new image was saved.
        assertThrows(IOException.class, () -> session.commit(photo(0, 2)));
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertArrayEquals(new byte[]{1, 2, 3}, restarted.read(original).jpeg);
        assertTrue(restarted.contains(photo(0, 1)));
        assertTrue(restarted.listening());
        File image = new File(session.directory(), original.fileName);
        byte[] damaged = Files.readAllBytes(image.toPath());
        damaged[damaged.length - 1] ^= 1;
        Files.write(image.toPath(), damaged);
        assertThrows(IOException.class, () -> restarted.read(original));
        assertArrayEquals(damaged, Files.readAllBytes(image.toPath()));
        assertThrows(IOException.class, () -> LocalCaptureSession.load(folder.getRoot(), "../outside"));
    }

    @Test public void futureOriginalsSurviveRestartWithoutBecomingUploadableBeforeReview() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        CaptureReviewStore.Pending first = nativePhoto(session, 0, 11);
        CaptureReviewStore.Pending second = nativePhoto(session, 1, 22);
        CaptureReviewStore.Pending third = nativePhoto(session, 2, 33);
        new CaptureReviewPersistence(new File(session.directory(), "pending.bin")).save(first);
        session.retainCandidate(second);
        session.retainCandidate(third);
        session = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertEquals(2, session.candidateCount());
        assertEquals(0, session.pageCount());
        assertNull("unseen originals cannot enter the upload cursor", session.nextUnsent());
        assertThrows(IOException.class, session::promoteCandidate);
        session.commit(first);
        CaptureReviewStore.Pending promoted = session.promoteCandidate();
        assertArrayEquals(second.jpeg, promoted.jpeg);
        assertEquals(second.provenance, promoted.provenance);
        assertEquals(Long.valueOf(22), promoted.provenance.imageTimestampNanos);
        LocalCaptureSession restored = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertEquals(1, restored.candidateCount());
        assertEquals(second.provenance, new CaptureReviewPersistence(
                new File(restored.directory(), "pending.bin")).readPending().provenance);
        restored.commit(promoted);
        assertEquals(third.provenance, restored.promoteCandidate().provenance);
        assertEquals(2, restored.pageCount());
    }

    @Test public void failedPromotionKeepsBothReferencesAndAnOverflowKeepsEveryOriginal() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        CaptureReviewStore.Pending first = nativePhoto(session, 0, 11);
        CaptureReviewStore.Pending second = nativePhoto(session, 1, 22);
        CaptureReviewStore.Pending third = nativePhoto(session, 2, 33);
        new CaptureReviewPersistence(new File(session.directory(), "pending.bin")).save(first);
        session.retainCandidate(second); session.retainCandidate(third); session.commit(first);
        File temporary = new File(session.directory(), "state.properties.tmp");
        assertTrue(temporary.mkdir());
        assertThrows(IOException.class, session::promoteCandidate);
        assertEquals(2, session.candidateCount());
        assertTrue(temporary.delete());
        session = LocalCaptureSession.load(folder.getRoot(), session.id());
        session.reconcileCandidates();
        assertEquals("a persisted review is never promoted twice after a crash", 1, session.candidateCount());
        session.retainCandidate(nativePhoto(session, 3, 44));
        LocalCaptureSession full = session;
        assertThrows(IOException.class, () -> full.retainCandidate(nativePhoto(full, 4, 55)));
        assertTrue(full.captureGap());
        assertEquals(2, full.candidateCount());
        assertEquals(4, java.util.Objects.requireNonNull(full.directory().listFiles(
                file -> file.getName().startsWith("c-") && file.getName().endsWith(".bin"))).length);
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), full.id());
        assertTrue(restarted.captureGap());
        assertEquals(2, restarted.candidateCount());
    }

    @Test public void anIssuedOriginalWhoseManifestWriteWasInterruptedStaysUnresolvedOnRestart() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        File stateFile = new File(session.directory(), "state.properties");
        java.util.Properties state = new java.util.Properties();
        try (var input = new java.io.FileInputStream(stateFile)) { state.load(input); }
        state.setProperty("candidate.issued", "true");
        try (var output = new java.io.FileOutputStream(stateFile)) { state.store(output, "interrupted native attempt"); }
        LocalCaptureSession issued = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertTrue(new File(issued.directory(), "state.properties.tmp").mkdir());
        assertThrows(IOException.class, () -> issued.retainCandidate(nativePhoto(issued, 0, 11)));
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), issued.id());
        assertTrue("a failed manifest must not erase the knowledge of an issued still", restarted.captureGap());
        assertNull(restarted.nextUnsent()); assertEquals(0, restarted.candidateCount());
        assertEquals(1, java.util.Objects.requireNonNull(restarted.directory().listFiles(
                file -> file.getName().startsWith("c-") && file.getName().endsWith(".bin"))).length);
    }

    @Test public void observedPreparationAndFailedGapWritesStayUnresolvedUntilExplicitRecapture() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        session.beginCandidateObservation();
        assertTrue(LocalCaptureSession.load(folder.getRoot(), session.id()).captureGap());
        session.beginCandidate();
        session.retainCandidate(nativePhoto(session, 0, 11));
        assertFalse("the live observer still has intact scene coverage", session.captureGap());
        assertTrue("saving a native original does not end observation", LocalCaptureSession.load(folder.getRoot(), session.id()).captureGap());
        File blocker = new File(session.directory(), "state.properties.tmp");
        assertTrue(blocker.mkdir());
        assertThrows(IOException.class, session::markCaptureGap);
        assertTrue("a failed write must also fence in-process completion", session.captureGap());
        assertTrue(blocker.delete());
        session.finishCandidateObservation();
        assertTrue("stopping alone cannot resolve a missed scene", LocalCaptureSession.load(folder.getRoot(), session.id()).captureGap());
        session.resolveCaptureGap();
        assertFalse("explicit recapture clears the unresolved observation atomically", LocalCaptureSession.load(folder.getRoot(), session.id()).captureGap());
    }

    @Test public void resolvingObservationRequiresDurableIdleAndEveryIssuedOriginal() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        assertFalse("legacy records without observation markers retain their meaning",
                LocalCaptureSession.load(folder.getRoot(), session.id()).captureGap());
        session.beginCandidateObservation();
        File blocker = new File(session.directory(), "state.properties.tmp");
        assertTrue(blocker.mkdir());
        assertThrows(IOException.class, session::finishCandidateObservation);
        assertTrue(LocalCaptureSession.load(folder.getRoot(), session.id()).captureGap());
        assertTrue(blocker.delete());
        session.finishCandidateObservation();
        assertFalse(LocalCaptureSession.load(folder.getRoot(), session.id()).captureGap());
        session.beginCandidateObservation(); session.beginCandidate();
        assertThrows(IOException.class, session::finishCandidateObservation);
        assertTrue(LocalCaptureSession.load(folder.getRoot(), session.id()).captureGap());
    }

    private static CaptureReviewStore.Pending nativePhoto(LocalCaptureSession session, int index, int value) {
        byte[] jpeg = {(byte)value, 2, 3};
        CaptureProvenance source = CaptureProvenance.nativeStill(jpeg, 4032, 3024,
                (long)value, (long)value, (long)value, 10_000_000L, 100, 0, 2)
                .bind(session.id(), index, 270);
        return new CaptureReviewStore.Pending(index, jpeg, "", 270, "", PageFraming.UNKNOWN, value, source);
    }

    private static CaptureReviewStore.Pending photo(int index, int value) {
        return new CaptureReviewStore.Pending(index, new byte[]{(byte)value, 2, 3}, "実資料", 180, "",
                PageFraming.UNKNOWN, 1000 + value);
    }
}
