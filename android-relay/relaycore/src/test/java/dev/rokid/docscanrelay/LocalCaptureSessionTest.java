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

    @Test public void fullJpegAndTextBudgetsFitTheRecordButOversizedRecordsRemainRejected() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        byte[] jpeg = new byte[20 * 1024 * 1024];
        jpeg[0] = 12;
        jpeg[jpeg.length - 1] = 34;
        CaptureReviewStore.Pending pending = new CaptureReviewStore.Pending(0, jpeg,
                "t".repeat(4 * 1024 * 1024), 270, "e".repeat(64 * 1024));
        session.commit(pending);
        LocalCaptureSession restored = LocalCaptureSession.load(folder.getRoot(), session.id());
        LocalCaptureSession.Page page = restored.nextUnsent();
        assertTrue(restored.contains(pending));
        CaptureReviewStore.Pending read = restored.read(page);
        assertArrayEquals(jpeg, read.jpeg);
        assertEquals(pending.ocrText, read.ocrText);
        assertEquals(pending.ocrFailure, read.ocrFailure);
        File file = new File(restored.directory(), page.fileName);
        assertTrue(file.length() <= CaptureReviewPersistence.MAX_RECORD_BYTES);
        try (java.io.RandomAccessFile oversized = new java.io.RandomAccessFile(file, "rw")) {
            oversized.setLength((long) CaptureReviewPersistence.MAX_RECORD_BYTES + 1);
        }
        assertThrows(IOException.class, () -> restored.read(page));
        assertEquals((long) CaptureReviewPersistence.MAX_RECORD_BYTES + 1, file.length());
    }

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

    /** A photo that leaves the review without becoming a page: kept in the reading's folder, offered for review no more. */
    @Test public void aPhotoSetAsideFromTheReviewKeepsItsOriginalAndIsNoLongerPending() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        session.commit(nativePhoto(session, 0, 1));
        CaptureReviewStore.Pending unmatched = nativePhoto(session, 1, 9);
        File pending = new File(session.directory(), "pending.bin");
        new CaptureReviewPersistence(pending).save(unmatched);

        session.setAsidePending();
        session.setAsidePending(); // nothing under review: nothing to do

        assertFalse(pending.exists());
        File[] kept = session.directory().listFiles((directory, name) -> name.startsWith("unresolved-"));
        assertEquals(1, kept.length);
        assertTrue("the original and what was known of it are whole", new CaptureReviewPersistence(kept[0]).matches(unmatched));
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        assertEquals("it did not become a page", 1, restarted.pageCount());
    }

    private static CaptureReviewStore.Pending nativePhoto(LocalCaptureSession session, int index, int value) {
        byte[] jpeg = {(byte)value, 2, 3};
        CaptureProvenance source = CaptureProvenance.nativeStill(jpeg, 4032, 3024,
                (long)value, (long)value, (long)value, 10_000_000L, 100, 0, 2)
                .bind(session.id(), index, 270);
        return new CaptureReviewStore.Pending(index, jpeg, "", 270, "", PageFraming.UNKNOWN, value, source);
    }

    @Test public void aClipFollowsItsPageAndIsSentOnlyAfterThePage() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        ClipInbox inbox = new ClipInbox(folder.newFolder("inbox"));
        String capture = clip(inbox, 7);
        session.commit(photo(0, 1));
        session.attachClip(0, capture, inbox);
        assertFalse("the clip has left the inbox", inbox.has(capture));
        assertNull("a clip is not sent before its page", session.nextUnsentClip());
        session.acknowledge(session.nextUnsent());
        LocalCaptureSession restarted = LocalCaptureSession.load(folder.getRoot(), session.id());
        LocalCaptureSession.Clip clip = restarted.nextUnsentClip();
        assertNotNull(clip);
        assertEquals(0, clip.index);
        assertEquals(capture, clip.captureId);
        assertEquals("v-0-" + clip.sha256 + ".mp4", clip.file.getName());
        assertArrayEquals(new byte[]{0, 0, 0, 24, 'f', 't', 'y', 'p', 7}, Files.readAllBytes(clip.file.toPath()));
        assertTrue(clip.record.isFile());
        restarted.acknowledgeClip(clip);
        assertNull(restarted.nextUnsentClip());
        assertFalse("a clip the server holds is not kept", clip.file.exists());
        assertFalse(clip.record.exists());
        assertNull(LocalCaptureSession.load(folder.getRoot(), session.id()).nextUnsentClip());
    }

    @Test public void aRetakeReplacesTheClipAndAStillRetakeRemovesIt() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        ClipInbox inbox = new ClipInbox(folder.newFolder("inbox"));
        session.commit(photo(0, 1));
        session.attachClip(0, clip(inbox, 1), inbox);
        session.acknowledge(session.nextUnsent());
        LocalCaptureSession.Clip first = session.nextUnsentClip();
        assertNotNull(first);

        session.commit(photo(0, 2));
        String second = clip(inbox, 2);
        session.attachClip(0, second, inbox);
        assertFalse("the first clip belongs to a photo that was replaced", first.file.exists());
        assertNull("the new clip waits for the new page", session.nextUnsentClip());
        session.acknowledgeClip(first); // A late acknowledgement cannot cover the replacement.
        session.acknowledge(session.nextUnsent());
        LocalCaptureSession.Clip replacement = session.nextUnsentClip();
        assertNotNull(replacement);
        assertEquals(second, replacement.captureId);

        session.commit(photo(0, 3));
        session.attachClip(0, java.util.UUID.randomUUID().toString(), inbox); // a still: no clip of this capture
        session.acknowledge(session.nextUnsent());
        assertNull(session.nextUnsentClip());
        assertFalse(replacement.file.exists());
    }

    @Test public void aClipWithoutItsPageIsRefused() throws Exception {
        LocalCaptureSession session = LocalCaptureSession.create(folder.getRoot(), "http://phone:8000", false);
        ClipInbox inbox = new ClipInbox(folder.newFolder("inbox"));
        String capture = clip(inbox, 1);
        assertThrows(IOException.class, () -> session.attachClip(0, capture, inbox));
        assertTrue("a refused clip stays where it was", inbox.has(capture));
    }

    private static String clip(ClipInbox inbox, int value) throws Exception {
        String id = java.util.UUID.randomUUID().toString();
        Files.write(inbox.reserve(id).toPath(), new byte[]{0, 0, 0, 24, 'f', 't', 'y', 'p', (byte) value});
        inbox.offer(id, ("{\"schema\":1,\"n\":" + value + "}").getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return id;
    }

    /**
     * The operator, 2026-11-17 (gist): old history and pictures burden the glasses; delete or move them. Every reading
     * since the app was installed had kept its folder (the real app held 1.4 GB): nothing removed a finished one.
     * Finished means the server holds every page and the answers were shown, and no screen leads back to it.
     */
    /**
     * The operator's trial of 2026-11-17 (register 3-1, known and left open until then). A booklet was closed during
     * the wait for its answers and taken up again while its pages were still on their way; closed a second time
     * after the server had taken it, it was listed nowhere: a reading counted as finished from the moment the server
     * had the booklet. The answers arrived on the phone and were never seen; the booklet was photographed again.
     */
    @Test public void aReadingWhoseAnswersHaveNotArrivedCanBeTakenUpAgain() throws Exception {
        File root = folder.getRoot();
        LocalCaptureSession sent = LocalCaptureSession.create(root, "http://phone:8000", false);
        sent.commit(photo(0, 7));
        sent.setPhase(LocalCaptureSession.Phase.ANALYSIS);
        sent.setPhase(LocalCaptureSession.Phase.REVIEW); // the server has taken the booklet
        assertTrue(sent.answersPending());
        assertTrue("closed during the wait, it is still a reading to go back to", sent.unfinished());
        sent.close();
        assertTrue(LocalCaptureSession.load(root, sent.id()).unfinished());
        assertEquals(0, LocalCaptureSession.retirePast(root, "", System.currentTimeMillis()));

        LocalCaptureSession again = LocalCaptureSession.load(root, sent.id());
        again.resume();
        again.answersArrived();
        assertFalse("its answers are on the glasses now", LocalCaptureSession.load(root, sent.id()).unfinished());
        assertEquals(1, LocalCaptureSession.retirePast(root, "", System.currentTimeMillis()));
    }

    @Test public void finishedReadingsAreClearedAwayAndEverythingElseStays() throws Exception {
        File root = folder.getRoot();
        LocalCaptureSession finished = LocalCaptureSession.create(root, "http://phone:8000", false);
        finished.commit(photo(0, 7));
        finished.setPhase(LocalCaptureSession.Phase.REVIEW);
        finished.answersArrived();
        LocalCaptureSession leftAfterReading = LocalCaptureSession.create(root, "http://phone:8000", false);
        leftAfterReading.setPhase(LocalCaptureSession.Phase.REVIEW);
        leftAfterReading.answersArrived();
        leftAfterReading.close();
        LocalCaptureSession capturing = LocalCaptureSession.create(root, "http://phone:8000", false);
        capturing.commit(photo(0, 8));
        LocalCaptureSession waiting = LocalCaptureSession.create(root, "http://phone:8000", false);
        waiting.setPhase(LocalCaptureSession.Phase.ANALYSIS);
        LocalCaptureSession current = LocalCaptureSession.create(root, "http://phone:8000", false);
        current.setPhase(LocalCaptureSession.Phase.REVIEW);
        File broken = new File(root, "11111111-2222-3333-4444-555555555555");
        assertTrue(broken.mkdir());
        Files.write(new File(broken, "state.properties").toPath(), new byte[]{1, 2, 3});
        File other = new File(root, "not-a-reading");
        assertTrue(other.mkdir());

        assertEquals(2, LocalCaptureSession.retirePast(root, current.id(), System.currentTimeMillis()));
        assertFalse("retired at once: the list of readings no longer sees it", finished.directory().exists());
        assertFalse(leftAfterReading.directory().exists());
        LocalCaptureSession.sweepRetired(root);

        String[] left = root.list();
        java.util.Arrays.sort(left);
        String[] expected = {capturing.id(), waiting.id(), current.id(), broken.getName(), other.getName()};
        java.util.Arrays.sort(expected);
        assertArrayEquals("unfinished readings, the one in hand, what cannot be judged and what is not a reading stay",
                expected, left);
        assertTrue(new File(capturing.directory(), "state.properties").isFile());
        assertEquals(0, LocalCaptureSession.retirePast(root, current.id(), System.currentTimeMillis()));
    }

    /**
     * A reading that was left unfinished keeps its pages and its unsent clips (up to 190 MB each) so that it can be
     * taken up again, and no screen discards one. After a day nobody takes it up: the test it was for is over.
     */
    @Test public void aReadingLeftUnfinishedForOverADayIsClearedAwayToo() throws Exception {
        File root = folder.getRoot();
        long now = System.currentTimeMillis(), hour = 3_600_000L;
        LocalCaptureSession stale = LocalCaptureSession.create(root, "http://phone:8000", false);
        stale.commit(photo(0, 5));
        LocalCaptureSession recent = LocalCaptureSession.create(root, "http://phone:8000", false);
        recent.commit(photo(0, 6));
        LocalCaptureSession inHand = LocalCaptureSession.create(root, "http://phone:8000", false);
        assertTrue(new File(stale.directory(), "state.properties").setLastModified(now - 25 * hour));
        assertTrue(new File(recent.directory(), "state.properties").setLastModified(now - 23 * hour));
        assertTrue(new File(inHand.directory(), "state.properties").setLastModified(now - 99 * hour));

        assertEquals(1, LocalCaptureSession.retirePast(root, inHand.id(), now));
        assertFalse(stale.directory().exists());
        assertTrue("within a day it can still be taken up again", recent.directory().exists());
        assertTrue("the reading in hand stays whatever its age", inHand.directory().exists());
        assertEquals("a clock that was set back removes nothing", 0, LocalCaptureSession.retirePast(root, inHand.id(), now - 400 * hour));
    }

    /**
     * Glasses, 2026-11-17, glassdoc 0.44.10: the real app died as it started ("Comparison method violates its general
     * contract"). The chooser sorted every folder by its time while the sweep was removing the retired ones, whose
     * time changes as they empty. The check package had passed: its store had been cleared and held nothing to sweep.
     * The list holds readings only, and each folder's time is read once before the sort.
     */
    @Test public void theListOfReadingsLeavesOutWhatIsBeingSweptAndReadsEachTimeOnce() throws Exception {
        File root = folder.getRoot();
        long now = System.currentTimeMillis();
        String[] ids = new String[40];
        for (int i = 0; i < ids.length; i++) {
            LocalCaptureSession reading = LocalCaptureSession.create(root, "http://phone:8000", false);
            ids[i] = reading.id();
            assertTrue(reading.directory().setLastModified(now - i * 60_000L));
        }
        for (int i = 0; i < 40; i++) assertTrue(new File(root, "done-" + java.util.UUID.randomUUID()).mkdir());
        assertTrue(new File(root, "not-a-reading").mkdir());

        java.util.concurrent.atomic.AtomicBoolean stop = new java.util.concurrent.atomic.AtomicBoolean();
        Thread touching = new Thread(() -> { // what a sweep, or a capture writing its record, does to the times meanwhile
            java.util.Random random = new java.util.Random(3);
            File[] all = root.listFiles();
            while (!stop.get()) all[random.nextInt(all.length)].setLastModified(now - random.nextInt(1_000_000));
        });
        touching.start();
        try {
            for (int round = 0; round < 300; round++) {
                File[] listed = LocalCaptureSession.folders(root);
                assertEquals(40, listed.length);
                for (File one : listed) assertFalse(one.getName().startsWith("done-"));
            }
        } finally {
            stop.set(true);
            touching.join();
        }
        for (int i = 0; i < ids.length; i++) assertTrue(new File(root, ids[i]).setLastModified(now - i * 60_000L));
        File[] listed = LocalCaptureSession.folders(root);
        for (int i = 0; i < ids.length; i++) assertEquals("newest first", ids[i], listed[i].getName());
        assertEquals(0, LocalCaptureSession.folders(new File(root, "absent")).length);
    }

    @Test public void whatAnEarlierSweepLeftBehindIsRemovedByTheNext() throws Exception {
        File root = folder.getRoot();
        LocalCaptureSession finished = LocalCaptureSession.create(root, "http://phone:8000", false);
        finished.commit(photo(0, 9));
        finished.setPhase(LocalCaptureSession.Phase.REVIEW);
        finished.answersArrived();
        assertEquals(1, LocalCaptureSession.retirePast(root, "", System.currentTimeMillis()));
        assertEquals("retired, not yet swept: the process ended here", 1, root.list().length);
        LocalCaptureSession.sweepRetired(root);
        assertEquals(0, root.list().length);
        LocalCaptureSession.sweepRetired(new File(root, "absent")); // a root that does not exist is nothing to sweep
    }

    private static CaptureReviewStore.Pending photo(int index, int value) {
        return new CaptureReviewStore.Pending(index, new byte[]{(byte)value, 2, 3}, "実資料", 180, "",
                PageFraming.UNKNOWN, 1000 + value);
    }
}
