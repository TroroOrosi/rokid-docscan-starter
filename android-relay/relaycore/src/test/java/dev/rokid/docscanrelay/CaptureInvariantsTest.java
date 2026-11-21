package dev.rokid.docscanrelay;

import static org.junit.Assert.fail;

import android.content.Context;
import android.os.SystemClock;
import dev.rokid.docscanglass.input.GlassesInputAction;
import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Random;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowSystemClock;

/**
 * Looks for sequences of gestures, camera answers and passing time that leave a local capture in a dead end.
 *
 * <p>Every other test of the capture scripts one hand-picked sequence. Here a seeded driver picks, step by step, among
 * what can happen next to the real controller in ORDINARY WRITTEN READING, and after every step the invariants are
 * checked from the controller's own fields ({@code Capture.broken}). After each sequence the wearer ends the capture
 * (the closing script, {@code Capture.end}) and I5 is checked. A failure names its seed and its whole step list, and a
 * shortened list that still fails; {@link #assertHolds} replays a list.</p>
 *
 * <ul>
 * <li>I1 automatic capture is live: in READY or READING, not paused, with no end asked for and the camera known, a
 * page is waited for at the camera or a photo is in flight.</li>
 * <li>I2 at most one camera request is in flight.</li>
 * <li>I3 nothing is saved while paused: a step that began or ended behind a cleared display saved no page.</li>
 * <li>I4 page indexes are contiguous from 0 and the count never decreases.</li>
 * <li>I5 the end is live: after the closing script the capture has ended (its phase has left CAPTURE) or failed. With
 * no page saved an end is not taken and the capture goes on: then no end stays requested.</li>
 * <li>I6 a review that is shown has its countdown: in CAPTURE_REVIEW, not paused, with a page that needs no
 * recapture, the review is armed and its still is the view the display was given last.</li>
 * </ul>
 *
 * <p>The steps of a list: PAGE (the camera sees a new page lying still), ACK (the newest view is on the display),
 * NOACK (it is not, and 3 s pass), HIDE (it is hidden; ACK shows it again), WAIT:n (n ms pass), PHOTO, UNRESOLVED,
 * NOTSTARTED and CAMERAFAIL (the camera's answer to a request), NOSTILL (the next still cannot be decoded for the
 * display), DOCUMENT (the phone has made the document), TAP, DOUBLETAP, SWIPE and BACKSWIPE (the wearer), A+B (a burst:
 * the controller's thread is held meanwhile), RETAKE:a,b (after an end: the phone names the pages, by index, that are
 * not whole; they are taken again in place and the booklet then goes out by itself; drawn once a sequence), CLOSE (the
 * closing script, which always runs last).</p>
 *
 * <p>What stands in for the glasses, each after its source in {@code android-relay/glassdoc}:</p>
 * <ul>
 * <li>Gestures as {@code DocScanGlassActivity.onAction} maps them: a tap toggles the pause; a double tap behind a
 * cleared display only brings it back, otherwise it is BACK; a forward swipe is SHORT_TAP unless paused; a back swipe
 * reaches the controller and does nothing there. With the controller in ERROR, or waiting for answers (FINALIZING), no
 * gesture is passed on. The call is the Activity's own two-argument one, with the clock's time.</li>
 * <li>The display as {@code GlassesCaptureSurface.show}: one counter for every view, and only the newest view can be
 * reported shown, hidden (window focus lost) and shown again. A still is visible from its report to its hiding. A still
 * that cannot be decoded is not shown at all ({@code showCaptureReview} returns NO_VIEW_GENERATION).</li>
 * <li>The camera as {@code GlassCamera}: one waiting page callback, replaced by the next {@code awaitNextPage}, dropped
 * by {@code pausePreview}, spent when it fires, and never fired while a photo is being taken. A photo asked for is
 * answered once: by the photo, by a photo whose capture metadata could not be matched, by "not started" (the head did
 * not hold still), or by a failure.</li>
 * <li>The controller's one thread being busy: a burst (A+B) is several of these while that thread is held.</li>
 * </ul>
 *
 * <p>Out of scope: the upload chain ({@code localNetworkBusy} keeps it from running, so a capture that has ended stays
 * at FINALIZING), clips, mixed English and listening, a reading taken up again, pages watched during a review
 * ({@code supportsFuturePages} is false, as on the glasses), and a store that fails to save (such a run is repeated).</p>
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class CaptureInvariantsTest {
    private static final int SEEDS = 300;

    /**
     * How far the drawn sequences got. From 2026-11-18 to 11-19 every sequence ended at its first saved page (the way
     * the upload was held back stopped the controller there), and "3000 sequences find nothing" was written twice.
     */
    private static int reachedTwoPages, reachedRetake;

    @Test public void randomGesturesCameraAnswersAndPassingTimeKeepTheCaptureInvariants() throws Exception {
        reachedTwoPages = reachedRetake = 0;
        for (long seed = 1; seed <= SEEDS; seed++) {
            Finding found = explore(null, seed);
            if (found != null) {
                fail("seed " + seed + " violates " + found.broken + "\nsteps: " + found.steps
                        + "\nshortened: " + shorten(found));
            }
        }
        String reach = SEEDS + " sequences: " + reachedTwoPages + " saved two pages or more, " + reachedRetake
                + " were asked by the phone for pages again";
        System.out.println("capture invariants reach: " + reach);
        org.junit.Assert.assertTrue("the sequences end early: " + reach, reachedTwoPages * 5 >= SEEDS && reachedRetake * 20 >= SEEDS);
    }

    // ---- pages the phone asks for again before the booklet goes out (2026-11-19) ------------------------------------

    private static final String[] ONE_PAGE = {"PAGE", "ACK", "ACK", "WAIT:1500", "PHOTO", "ACK", "WAIT:3100"};

    private static void take(Capture capture, int pages) throws Exception {
        for (int page = 0; page < pages; page++) for (String step : ONE_PAGE) assertStep(capture, step);
    }

    private static void assertStep(Capture capture, String step) throws Exception {
        String broken = capture.step(step);
        if (broken != null) fail(broken + "\nsteps: " + capture.done);
    }

    /** Which photo (counted from 1 in the order the camera delivered them) each saved page holds. */
    private static List<Integer> photosOf(Capture capture) throws Exception {
        List<Integer> held = new ArrayList<>();
        for (int index = 0; index < capture.session.pageCount(); index++) {
            held.add((int) capture.session.read(capture.session.page(index)).jpeg[1]);
        }
        return held;
    }

    /**
     * The operator, 2026-11-19: a page that has to be taken again has to be found before GPT asks for it, and the
     * number shown at each capture is to be the number of the page being taken again. The phone names the pages that
     * are not whole when the wearer has ended the capture; they are taken again in place, each under its own number,
     * and when the last one is saved the booklet goes out without another double tap.
     */
    @Test public void pagesThePhoneAsksForAreTakenAgainUnderTheirOwnNumbersAndThenTheBookletGoesOut() throws Exception {
        try (Capture capture = new Capture()) {
            take(capture, 3);
            assertStep(capture, "DOUBLETAP");
            org.junit.Assert.assertEquals(capture.told + " " + capture.controller.getState() + " pages=" + capture.session.pageCount(),
                    LocalCaptureSession.Phase.ANALYSIS, capture.session.phase());
            assertStep(capture, "RETAKE:0,2");
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.CAPTURE, capture.session.phase());
            org.junit.Assert.assertEquals(List.of(1, 3), capture.asked);
            org.junit.Assert.assertTrue("a page is waited for again", capture.glasses.pageReady != null);
            for (String step : new String[]{"PAGE", "ACK"}) assertStep(capture, step);
            org.junit.Assert.assertEquals("the first page asked for, by its own number", 1, capture.glasses.aimingPage);
            org.junit.Assert.assertTrue("shown as a page taken again", capture.glasses.aimingRetake);
            for (String step : new String[]{"ACK", "WAIT:1500", "PHOTO", "ACK", "WAIT:3100"}) assertStep(capture, step);
            org.junit.Assert.assertEquals("in place: the fourth photo is page 1", List.of(4, 2, 3), photosOf(capture));
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.CAPTURE, capture.session.phase());
            for (String step : new String[]{"PAGE", "ACK"}) assertStep(capture, step);
            org.junit.Assert.assertEquals(3, capture.glasses.aimingPage);
            for (String step : new String[]{"ACK", "WAIT:1500", "PHOTO", "ACK", "WAIT:3100"}) assertStep(capture, step);
            org.junit.Assert.assertEquals(List.of(4, 2, 5), photosOf(capture));
            org.junit.Assert.assertEquals("the last page asked for is in: the booklet goes out by itself",
                    LocalCaptureSession.Phase.ANALYSIS, capture.session.phase());
        }
    }

    /** The wearer does not have to take them: a double tap sends the booklet as it is. */
    @Test public void aDoubleTapWhilePagesAreAskedForSendsTheBookletAsItIs() throws Exception {
        try (Capture capture = new Capture()) {
            take(capture, 2);
            assertStep(capture, "DOUBLETAP");
            assertStep(capture, "RETAKE:1");
            assertStep(capture, "DOUBLETAP");
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.ANALYSIS, capture.session.phase());
            org.junit.Assert.assertEquals(List.of(1, 2), photosOf(capture));
            // And a page taken after that end was asked for is an ordinary next page, were the capture taken up again.
            org.junit.Assert.assertTrue(((java.util.Collection<?>) get(capture.controller, "retakeQueue")).isEmpty());
        }
    }

    /**
     * Nobody may be looking when the phone asks: it asks once the clips are gathered, 83 s after the end on
     * 2026-11-20, with the display long dark and the wearer waiting for answers. Until 2026-11-21 the booklet then
     * waited for a page or a double tap without end, and no answer could come.
     */
    @Test public void pagesAskedForThatNobodyTakesInAMinuteDoNotHoldTheBookletBack() throws Exception {
        try (Capture capture = new Capture()) {
            take(capture, 2);
            assertStep(capture, "DOUBLETAP");
            assertStep(capture, "RETAKE:1");
            assertStep(capture, "WAIT:59000");
            org.junit.Assert.assertEquals("a minute is given", LocalCaptureSession.Phase.CAPTURE, capture.session.phase());
            assertStep(capture, "WAIT:2000");
            org.junit.Assert.assertEquals("then the booklet goes out as it is", LocalCaptureSession.Phase.ANALYSIS, capture.session.phase());
            org.junit.Assert.assertEquals(List.of(1, 2), photosOf(capture));
            org.junit.Assert.assertTrue(((java.util.Collection<?>) get(capture.controller, "retakeQueue")).isEmpty());
        }
    }

    @Test public void aWearerWhoIsTakingThePagesIsNotCutOffByThatMinute() throws Exception {
        try (Capture capture = new Capture()) {
            take(capture, 2);
            assertStep(capture, "DOUBLETAP");
            assertStep(capture, "RETAKE:0,1");
            assertStep(capture, "WAIT:50000");
            for (String step : new String[]{"PAGE", "ACK", "ACK", "WAIT:1500"}) assertStep(capture, step);
            assertStep(capture, "WAIT:15000"); // the page is being taken when the minute is up
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.CAPTURE, capture.session.phase());
            for (String step : new String[]{"PHOTO", "ACK", "WAIT:3100"}) assertStep(capture, step);
            org.junit.Assert.assertEquals("the first page asked for is in", List.of(3, 2), photosOf(capture));
            assertStep(capture, "WAIT:59000");
            org.junit.Assert.assertEquals("and the next one has a minute of its own", LocalCaptureSession.Phase.CAPTURE, capture.session.phase());
            assertStep(capture, "SWIPE"); // any gesture: the wearer is there
            assertStep(capture, "WAIT:2000");
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.CAPTURE, capture.session.phase());
        }
    }

    /** A page asked for that the reading does not hold is not waited for, and with none left the booklet goes out. */
    @Test public void aPageTheReadingDoesNotHoldIsNotAskedFor() throws Exception {
        try (Capture capture = new Capture()) {
            take(capture, 1);
            assertStep(capture, "DOUBLETAP");
            assertStep(capture, "RETAKE:5");
            org.junit.Assert.assertEquals(List.of(), capture.asked);
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.ANALYSIS, capture.session.phase());
        }
    }

    // ---- pages taken again after the answers were read: the last net (2026-11-19) -----------------------------------

    /** The reading as it stands while its answers are read: sent, answered, nothing waited for. */
    private static void answered(Capture capture) throws Exception {
        assertStep(capture, "DOUBLETAP");
        capture.session.bindDocument(17L);
        capture.session.bindSession(23L);
        capture.session.setPhase(LocalCaptureSession.Phase.REVIEW);
        capture.session.answersArrived();
        set(capture.controller, "state", RelayState.REVIEW);
    }

    /**
     * The operator, 2026-11-19: where the answers end with pages to take again, a double tap takes them. A second
     * double tap before any page is taken leaves the retake: nothing is sent or read again, the reading is as it
     * was, and the display is told, which ends the writing.
     */
    @Test public void aRetakeBegunFromTheAnswersIsLeftByADoubleTapBeforeAnyPageAndNothingIsSent() throws Exception {
        try (Capture capture = new Capture()) {
            take(capture, 2);
            answered(capture);
            org.junit.Assert.assertTrue(capture.controller.canRetakeAnswered(List.of(1)));
            org.junit.Assert.assertFalse("a page the reading does not hold", capture.controller.canRetakeAnswered(List.of(9)));
            capture.controller.retakeAnswered(List.of(1));
            barrier(capture.controller);
            org.junit.Assert.assertEquals(List.of(2), capture.asked);
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.CAPTURE, capture.session.phase());
            org.junit.Assert.assertTrue("the phone is told before the first page goes", capture.session.retakeReopen());
            org.junit.Assert.assertTrue(capture.glasses.pageReady != null);
            assertStep(capture, "DOUBLETAP");
            org.junit.Assert.assertTrue("the display is told: that double tap ends the writing", capture.left);
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.REVIEW, capture.session.phase());
            org.junit.Assert.assertEquals(RelayState.REVIEW, capture.controller.getState());
            org.junit.Assert.assertFalse(capture.session.retakeReopen());
            org.junit.Assert.assertFalse("nothing is waited for: the answers are on the glasses", capture.session.answersPending());
            org.junit.Assert.assertNull("the camera stops", capture.glasses.pageReady);
            org.junit.Assert.assertEquals(List.of(1, 2), photosOf(capture));
        }
    }

    /** With the page taken, the booklet goes out again by itself, and the phone is still to be told first. */
    @Test public void aPageTakenAgainFromTheAnswersGoesOutWithTheBooklet() throws Exception {
        try (Capture capture = new Capture()) {
            take(capture, 2);
            answered(capture);
            capture.controller.retakeAnswered(List.of(1));
            barrier(capture.controller);
            for (String step : ONE_PAGE) assertStep(capture, step);
            org.junit.Assert.assertEquals(List.of(1, 3), photosOf(capture));
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.ANALYSIS, capture.session.phase());
            org.junit.Assert.assertTrue(capture.session.retakeReopen());
            org.junit.Assert.assertFalse(capture.left);
        }
    }

    /** A double tap while the page is being taken is the end of the capture, not a retake left: the page is kept. */
    @Test public void aDoubleTapWhileThePageIsBeingTakenAgainSendsItWithTheBooklet() throws Exception {
        try (Capture capture = new Capture()) {
            take(capture, 2);
            answered(capture);
            capture.controller.retakeAnswered(List.of(0));
            barrier(capture.controller);
            for (String step : new String[]{"PAGE", "ACK", "ACK", "WAIT:1500"}) assertStep(capture, step);
            org.junit.Assert.assertTrue("the camera has been asked", capture.glasses.requestOpen);
            for (String step : new String[]{"DOUBLETAP", "PHOTO", "ACK", "WAIT:3100"}) assertStep(capture, step);
            org.junit.Assert.assertFalse(capture.left);
            org.junit.Assert.assertEquals(List.of(3, 2), photosOf(capture));
            org.junit.Assert.assertEquals(LocalCaptureSession.Phase.ANALYSIS, capture.session.phase());
        }
    }

    // ---- sequences the random test found on 2026-11-18, each since fixed in the controller ----------------------
    // Each test's text says what the fault was. The first four were found within 300 seeds, the last two with
    // 3000 (one of them made by the first fix of the first). With all six fixed, 3000 seeds find nothing.

    /**
     * Found by the random test. The wearer clears the display during a review; the review's three seconds run out
     * behind the cleared display while the controller's thread is busy; the wearer taps to come back before that
     * thread gets to the countdown. The tap takes the pause off on the caller's thread
     * (toggleCapturePause), so the countdown from before the pause finds no pause and saves the page (enqueueAutoCommit,
     * confirmPendingCaptureNow), and only then is the return worked off (resumeCaptureNow), which would have shown
     * the page afresh for its own three seconds. The page is saved without the review a return gives it every other
     * time ({@code LocalReviewTest.aTapDuringTheReviewClearsItAndThePageIsReviewedAfreshOnReturn}: "the countdown
     * from before the tap is dead"). Nothing stops: the capture goes on with the next page.
     */
    @Test public void aReviewCutShortByAPauseIsNotSavedByItsOldCountdownAsTheWearerReturns() throws Exception {
        assertHolds("PAGE", "ACK", "ACK", "WAIT:1500", "PHOTO", "ACK", "TAP", "WAIT:3000+TAP");
    }

    /**
     * Found by the random test. The glasses cannot decode a photo for the display
     * ({@code GlassesCaptureSurface.showCaptureReview} returns NO_VIEW_GENERATION: out of memory in decodePreview, or
     * a JPEG that does not decode). publishCaptureReview takes that answer as a view (publishCaptureAiming does not)
     * and enters CAPTURE_REVIEW armed for a still that is never reported shown: its three seconds never start, the
     * page is never saved, no further page is looked for, and what the display shows is what it showed before. A
     * double tap does not end the capture either (finishLocalCaptureWhenCameraIdle waits for the countdown: I5).
     * Only a tap and the tap back, or a forward swipe, show a still again.
     */
    @Test public void aStillThatCannotBeShownDoesNotLeaveAReviewNobodySees() throws Exception {
        assertHolds("PAGE", "ACK", "ACK", "WAIT:1500", "NOSTILL", "PHOTO");
    }

    /**
     * Found by the random test. The camera delivers a photo it could not match to its
     * capture result ({@code onPhoto(.., false)}; GlassCamera's associationResolved). The page is kept for an explicit
     * recapture: never saved by time (publishCaptureReview, confirmPendingCaptureNow) and marked as a capture gap
     * (handlePhoto). A double tap then shows the same review again and returns (finishLocalCaptureWhenCameraIdle),
     * every time: the capture neither ends nor goes on until a forward swipe retakes the page, and the pages saved
     * before it are not sent for answers.
     */
    @Test public void aDoubleTapEndsACaptureWhoseLastPhotoNeedsARecapture() throws Exception {
        assertHolds("PAGE", "ACK", "ACK", "WAIT:1500", "PHOTO", "ACK", "WAIT:3000",
                "PAGE", "ACK", "ACK", "WAIT:1500", "UNRESOLVED", CLOSE);
    }

    /**
     * Found by the random test. A photo that needs a recapture marks a capture gap (handlePhoto). The wearer retakes
     * it by a forward swipe and then retakes the retake: retakePendingCaptureNow sets reacquiringCaptureGap only when
     * the photo under review is itself a failed one, so the second retake turns it off, the save does not take the
     * gap away (commitLocalPhoto) and ends in publishCaptureGap: "Observed scene was not captured", although every
     * page is saved. No further page is looked for, an end already asked for is dropped, and each later double tap
     * lands in the same place (finishReadingNow): the state worn on 2026-11-17, reached without watching during a
     * review. A forward swipe gets out of it, at the price of one more photo of a page that is already saved.
     */
    @Test public void retakingTheRetakeOfAPhotoThatNeededARecaptureDoesNotStopTheCapture() throws Exception {
        assertHolds("PAGE", "ACK", "ACK", "WAIT:1500", "UNRESOLVED", "SWIPE", "ACK", "ACK", "WAIT:1500", "PHOTO",
                "SWIPE", "ACK", "ACK", "WAIT:1500", "PHOTO", "ACK", "WAIT:3000");
    }

    /**
     * Found by the random test with the four faults above fixed (seed 71). A photo that needs a recapture is the
     * only thing taken; the wearer ends the capture. The end drops that page (it can only be retaken), nothing is
     * saved, so the capture goes on, and the mark the photo left (a scene seen and not taken) stood: no page was
     * looked for and every later end was refused at that mark.
     */
    @Test public void anEndOverARetakeOnlyPageWithNothingSavedLeavesTheCaptureLooking() throws Exception {
        assertHolds("PAGE", "WAIT:800+ACK", "ACK", "NOACK", "UNRESOLVED", CLOSE);
    }

    /**
     * Found by the random test (seed 2018 of 3000), and made by the first fix of the first fault above: a pause
     * retired the review's countdown and left the review armed. An end that overtook the return from the pause
     * (double taps and a tap while the controller's thread was held) then waited for that countdown for good.
     */
    @Test public void anEndThatOvertakesTheReturnFromAPauseStillEndsTheCapture() throws Exception {
        assertHolds("PAGE", "ACK", "ACK", "WAIT:683", "WAIT:881", "PHOTO", "ACK+ACK", "TAP",
                "DOUBLETAP+DOUBLETAP+TAP", CLOSE);
    }

    // ---- one sequence -------------------------------------------------------------------------------------------

    private record Finding(String broken, List<String> steps) { }

    /**
     * Runs a drawn sequence (script null, from the seed) or a given one, then the closing script. Null when every
     * invariant held. A run in which the store failed to save is not judged but repeated: a failed save is a path of
     * its own in the controller (and Windows refuses a file now and then under this many small writes).
     */
    private static Finding explore(List<String> script, long seed) throws Exception {
        for (int attempt = 0; ; attempt++) {
            try (Capture capture = new Capture()) {
                Random random = new Random(seed);
                Finding found = null;
                int length = script != null ? script.size() : 40 + random.nextInt(41);
                for (int index = 0; index < length && found == null; index++) {
                    String step = script != null ? script.get(index) : capture.draw(random, seed);
                    if (step.equals(CLOSE)) break;
                    String broken = capture.step(step);
                    if (broken != null) found = new Finding(broken, capture.done);
                }
                int saved = capture.session.pageCount();
                if (found == null) {
                    String broken = capture.end();
                    capture.done.add(CLOSE);
                    if (broken != null) found = new Finding(broken, capture.done);
                }
                if (!capture.storeFailed || attempt == 2) {
                    if (script == null) {
                        if (saved >= 2) reachedTwoPages++;
                        if (capture.done.stream().anyMatch(step -> step.startsWith("RETAKE:"))) reachedRetake++;
                    }
                    return found;
                }
            }
        }
    }

    /**
     * Drops the steps the same invariant does not need: runs of four, of two (a tap and the tap that undoes it) and
     * single steps, until nothing more can go. Quadratic in the sequence; run only for a failure.
     */
    private static List<String> shorten(Finding found) throws Exception {
        String invariant = found.broken.substring(0, 2);
        List<String> kept = new ArrayList<>(found.steps);
        for (boolean shorter = true; shorter; ) {
            shorter = false;
            for (int run : new int[]{4, 2, 1}) {
                for (int index = kept.size() - run; index >= 0 && !shorter; index--) {
                    List<String> tried = new ArrayList<>(kept);
                    tried.subList(index, index + run).clear();
                    Finding again = explore(tried, 0);
                    // Strictly shorter: a list whose CLOSE was dropped comes back with its CLOSE, the same list.
                    if (again != null && again.broken.startsWith(invariant) && again.steps.size() < kept.size()) {
                        kept = again.steps;
                        shorter = true;
                    }
                }
            }
        }
        return kept;
    }

    /** Replays a sequence with every guard off; for the tests that hold a known violation. */
    private static void assertHolds(String... steps) throws Exception {
        Finding found = explore(Arrays.asList(steps), 0);
        if (found != null) fail(found.broken + "\nsteps: " + found.steps);
    }

    private static final String CLOSE = "CLOSE";

    /** One local capture of ordinary written reading: the real controller, the stand-in glasses, one clock. */
    private static final class Capture implements AutoCloseable {
        final Glasses glasses = new Glasses();
        final Clock clock = new Clock();
        final DocScanController controller;
        final LocalCaptureSession session;
        final List<String> done = new ArrayList<>();
        volatile String told = "";
        volatile boolean storeFailed;
        /** The page numbers the wearer was last told to take again (Listener.onRetakeRequested). */
        volatile List<Integer> asked = List.of();
        /** The retake begun from the answers was left untouched (Listener.onRetakeLeft). */
        volatile boolean left;
        boolean retaken;
        int photos;

        Capture() throws Exception {
            Context context = RuntimeEnvironment.getApplication();
            // Each sequence starts from nothing, so that a seed gives the same sequence alone and in the loop.
            context.getSharedPreferences("docscan_relay", Context.MODE_PRIVATE).edit().clear().commit();
            delete(new File(context.getFilesDir(), "local-scans"));
            controller = new DocScanController(context, glasses, null, new DocScanController.Listener() {
                @Override public void onUpdate(RelayState state, List<String> lines, String diagnostic) {
                    told = diagnostic;
                    // Every way the controller says that something could not be written.
                    if (diagnostic.contains("save failed") || diagnostic.contains("could not be saved")
                            || diagnostic.contains("保存できません") || diagnostic.contains("開始できません")) storeFailed = true;
                }
                @Override public void onRetakeRequested(List<Integer> pageNumbers) { asked = pageNumbers; }
                @Override public void onRetakeLeft() { left = true; }
            }, new ClientIdentity("test", "test", "test"));
            ((ExecutorService) get(controller, "watchdog")).shutdownNow();
            set(controller, "watchdog", clock);
            controller.configureForLocalStart("http://phone:8000", "", 270);
            controller.startLocalSession(false);
            barrier(controller);
            // The upload chain is out of scope: pages stay saved on the glasses and nothing is sent. Held as "a pass is
            // under way", which only keeps another from starting. Until 2026-11-19 this set localUploadBlocked, "the
            // sending has stopped": from 2026-11-18 the controller says that again after every saved page
            // (commitLocalPhoto) and stops in ERROR, so every sequence here ended at its first saved page and the
            // 3000 sequences that "found nothing" had looked at little behind it.
            set(controller, "localNetworkBusy", true);
            session = (LocalCaptureSession) get(controller, "localSession");
            if (session == null) throw new IOException("the capture did not start: " + told);
        }

        /**
         * What can happen next, weighted so that the camera and the display mostly answer and a gesture comes about
         * once in fifteen steps: a sequence then saves pages, and the gestures land in every state on the way.
         * Seeds 0 mod 3 leave the end to the closing script (long captures); seeds 2 mod 3 are a restless head (a
         * page is seen as soon as one is waited for, and time passes in short pieces).
         */
        String draw(Random random, long seed) throws Exception {
            boolean restless = seed % 3 == 2, paused = controller.isCapturePaused();
            CaptureReviewStore.Pending pending = ((CaptureReviewStore) get(controller, "captureReview")).peek();
            boolean reviewing = pending != null;
            List<String> options = new ArrayList<>();
            offer(options, "WAIT:" + (100 + random.nextInt(restless ? 901 : 3901)), 6);
            if (glasses.pageReady != null && !glasses.requestOpen) offer(options, "PAGE", restless ? 14 : 6);
            if (glasses.generation > 0 && !glasses.shown) { offer(options, "ACK", 12); offer(options, "NOACK", 1); }
            if (glasses.shown && random.nextBoolean()) offer(options, "HIDE", 1);
            if (glasses.requestOpen) {
                offer(options, "PHOTO", 12);
                offer(options, "NOTSTARTED", 2);
                if (random.nextInt(4) == 0) offer(options, "UNRESOLVED", 1);
                if (random.nextInt(20) == 0) offer(options, "CAMERAFAIL", 1);
                if (random.nextInt(10) == 0) offer(options, "NOSTILL", 1);
            }
            if (controller.documentId() == 0) offer(options, "DOCUMENT", 1);
            // The phone's answer to the check that follows an end: once a reading, as on the glasses.
            if (!retaken && controller.getState() == RelayState.FINALIZING && session.pageCount() > 0
                    && session.phase() == LocalCaptureSession.Phase.ANALYSIS) {
                int first = random.nextInt(session.pageCount());
                offer(options, "RETAKE:" + first + (first + 1 < session.pageCount() && random.nextBoolean()
                        ? "," + (first + 1) : ""), 8);
            }
            if (gesturesArePassedOn()) {
                // A wearer who cleared the display brings it back.
                if (paused || random.nextBoolean()) offer(options, "TAP", paused ? 5 : 1);
                if (!paused && random.nextBoolean()) offer(options, "SWIPE", reviewing ? 2 : 1);
                if (!paused && random.nextInt(8) == 0) offer(options, "BACKSWIPE", 1);
                // Behind a cleared display a double tap only brings it back; in view it ends the capture, and what
                // follows an end is of little use here, so it comes seldom.
                if (seed % 3 != 0 && (paused || random.nextInt(3) == 0)) offer(options, "DOUBLETAP", paused ? 2 : 1);
            }
            String step = options.get(random.nextInt(options.size()));
            // One step in eight is a burst: two or three of the things that can happen now, while the controller's
            // thread is held. Each is decided on what was true before the burst, and they are worked off in order.
            if (random.nextInt(8) == 0) {
                for (int more = 1 + random.nextInt(2); more > 0; more--) {
                    step += "+" + options.get(random.nextInt(options.size()));
                }
            }
            return step;
        }

        private static void offer(List<String> options, String step, int weight) {
            for (int count = 0; count < weight; count++) options.add(step);
        }

        /** DocScanGlassActivity.onAction: a failure and the wait for answers keep every gesture from the controller. */
        private boolean gesturesArePassedOn() {
            RelayState state = controller.getState();
            return state != RelayState.ERROR && state != RelayState.FINALIZING && state != RelayState.REVIEW;
        }

        /** Applies one step (a step that cannot happen now does nothing) and returns the invariant it broke, or null. */
        String step(String step) throws Exception {
            done.add(step);
            boolean pausedBefore = controller.isCapturePaused();
            int pagesBefore = session.pageCount();
            apply(step);
            return broken(pausedBefore, pagesBefore);
        }

        /**
         * A+B: a burst. The controller's one thread is held while A and B happen (writing a page out has held it for
         * seconds, hardware-measurements M-30; a tap then "counts from the turn it is made in"), so what the caller
         * reads for B (the pause flag, the state, the review's window) is what was true before A was worked off.
         */
        private void apply(String step) throws Exception {
            if (!step.contains("+")) { act(step, false); barrier(controller); return; }
            CountDownLatch release = new CountDownLatch(1);
            ((ExecutorService) get(controller, "serial")).execute(() -> {
                try { release.await(5, TimeUnit.SECONDS); } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); }
            });
            try { for (String part : step.split("\\+")) act(part, true); }
            finally { release.countDown(); }
            barrier(controller);
        }

        private void act(String step, boolean held) throws Exception {
            long now = SystemClock.elapsedRealtime();
            boolean paused = controller.isCapturePaused();
            boolean review = "capture-review".equals(glasses.purpose);
            switch (step.startsWith("WAIT:") ? "WAIT" : step.startsWith("RETAKE:") ? "RETAKE" : step) {
                case "RETAKE": { // the phone names pages (indexes here) that are not whole: queueLocalUpload's check
                    List<Integer> indexes = new ArrayList<>();
                    for (String index : step.substring(7).split(",")) indexes.add(Integer.parseInt(index));
                    retaken = true;
                    controller.retakePages(indexes);
                    break;
                }
                case "PAGE": // the camera sees a new page lying still
                    if (glasses.pageReady != null && !glasses.requestOpen) {
                        Runnable ready = glasses.pageReady;
                        glasses.pageReady = null;
                        ready.run();
                    }
                    break;
                case "ACK": // the newest view is on the display
                    if (glasses.generation > 0 && !glasses.shown) {
                        glasses.shown = true;
                        if (review) glasses.visibleReview = glasses.generation;
                        controller.onCustomViewAvailable(glasses.generation, glasses.purpose);
                    }
                    break;
                case "HIDE": // the window loses focus; ACK shows the same view again
                    if (glasses.shown) {
                        glasses.shown = false;
                        if (review) {
                            glasses.visibleReview = CaptureSurface.NO_VIEW_GENERATION;
                            controller.onCaptureReviewHidden(glasses.generation);
                        }
                    }
                    break;
                case "NOACK": // the view is not reported and three seconds pass
                    clock.advanceBy(controller, 3000, held);
                    break;
                case "WAIT":
                    clock.advanceBy(controller, Long.parseLong(step.substring(5)), held);
                    break;
                case "PHOTO":
                case "UNRESOLVED": // GlassCamera could not match the still to its capture result: kept for a recapture
                    if (glasses.requestOpen) {
                        glasses.requestOpen = false;
                        photos++;
                        byte[] jpeg = {1, (byte) photos, (byte) (photos >> 8)}; // a stand-in, never decoded
                        long stamp = 100L * photos;
                        controller.onPhoto(jpeg, CaptureProvenance.nativeStill(jpeg, 4032, 3024, stamp, stamp, stamp,
                                10_000_000L, 100, 0, 2), step.equals("PHOTO"));
                    }
                    break;
                case "NOTSTARTED":
                    if (glasses.requestOpen) { glasses.requestOpen = false; controller.onPhotoNotStarted(); }
                    break;
                case "CAMERAFAIL":
                    if (glasses.requestOpen) { glasses.requestOpen = false; controller.onPhotoError("camera failed", null); }
                    break;
                case "NOSTILL": // the next still cannot be decoded for the display (GlassesCaptureSurface.decodePreview)
                    glasses.nextStillFails = true;
                    break;
                case "DOCUMENT":
                    // The one thing of the upload chain the capture can tell: once the phone has made the document,
                    // the controller waits in READING where it waited in READY (queueLocalUpload's last task).
                    set(controller, "documentId", 17L);
                    break;
                case "TAP":
                    if (gesturesArePassedOn()) controller.toggleCapturePause();
                    break;
                case "DOUBLETAP":
                    if (!gesturesArePassedOn()) break;
                    if (paused) controller.toggleCapturePause();
                    else controller.onGlassesAction(GlassesInputAction.BACK, now);
                    break;
                case "SWIPE":
                    if (gesturesArePassedOn() && !paused) controller.onGlassesAction(GlassesInputAction.SHORT_TAP, now);
                    break;
                case "BACKSWIPE":
                    if (gesturesArePassedOn() && !paused) controller.onGlassesAction(GlassesInputAction.SWIPE_BACK, now);
                    break;
                default:
                    throw new IllegalArgumentException(step);
            }
        }

        /** I1-I4 and I6, read from the controller's fields after a step. */
        private String broken(boolean pausedBefore, int pagesBefore) throws Exception {
            RelayState state = controller.getState();
            boolean paused = controller.isCapturePaused();
            boolean ending = (boolean) get(controller, "finishCaptureRequested");
            boolean cameraUnknown = (boolean) get(controller, "localCameraUnknown");
            boolean requestPending = ((CaptureLease) get(controller, "captureLease")).isUnresolved();
            CaptureReviewStore.Pending pending = ((CaptureReviewStore) get(controller, "captureReview")).peek();
            String at = " [state=" + state + " paused=" + paused + " ending=" + ending + " pages=" + session.pageCount()
                    + " view=" + glasses.purpose + "#" + glasses.generation + (glasses.shown ? " shown" : " waiting")
                    + " told=\"" + told + "\"]";

            // I1: automatic capture is live. A capture that waits for a page has a page callback at the camera.
            if ((state == RelayState.READY || state == RelayState.READING) && !paused && !ending && !cameraUnknown
                    && glasses.pageReady == null && !requestPending) {
                return "I1 automatic capture is live: no page is waited for and nothing is pending" + at;
            }
            // I2: at most one camera request in flight.
            if (glasses.overlapping) return "I2 at most one camera request in flight: takePhoto over an open request" + at;
            // I3: nothing is saved while paused. A step that began or ended behind a cleared display saved no page.
            int pages = session.pageCount();
            if ((pausedBefore || paused) && pages > pagesBefore) return "I3 nothing is saved while paused" + at;
            // I4: page indexes are contiguous from 0 and the count never decreases.
            if (pages < pagesBefore) return "I4 the page count decreased from " + pagesBefore + at;
            for (int index = 0; index < pages; index++) {
                try {
                    if (session.page(index).index != index) return "I4 page " + index + " is out of place" + at;
                } catch (IOException missing) { return "I4 page " + index + " of " + pages + " is missing" + at; }
            }
            // I6: a review that is shown has its countdown. The still must also be the newest view the display was
            // given, or it can never be reported shown and its three seconds never start. Left out, by reading:
            //  - a page that needs a recapture (its capture metadata is unresolved) is never saved by time;
            //  - the review put back after a failed save (commitLocalPhoto, stageCaptureReview) is unarmed, so that a
            //    store that cannot save is not asked again every three seconds: a run with a failed save is not
            //    judged at all (explore repeats it).
            if (state == RelayState.CAPTURE_REVIEW && !paused && !storeFailed
                    && !(pending != null && pending.needsSceneRecapture())) {
                if (pending == null) return "I6 a review that is shown has its countdown: no photo is under review" + at;
                if (!(boolean) get(controller, "autoCommitArmed")) {
                    return "I6 a review that is shown has its countdown: autoCommitArmed is false" + at;
                }
                long view = (long) get(controller, "reviewViewGeneration");
                if (view == CaptureSurface.NO_VIEW_GENERATION) {
                    // The picture could not be drawn: its three seconds run without it and the page is then saved
                    // (publishCaptureReview), so that the capture does not stand at a review nobody sees.
                    if ((long) get(controller, "reviewDeadlineMillis") == 0) {
                        return "I6 a review that is shown has its countdown: the picture could not be drawn and no"
                                + " countdown runs" + at;
                    }
                } else if (!"capture-review".equals(glasses.purpose) || glasses.generation != view) {
                    return "I6 a review that is shown has its countdown: the still (view " + view
                            + ") is not what the display was given last, so it is never reported shown" + at;
                }
            }
            return null;
        }

        /**
         * The closing script: the wearer comes back from a pause and ends the capture, up to three times, and each
         * time the camera delivers what it was asked for, the display shows its newest view and 3.1 s pass.
         * Then I5: the end is live.
         */
        String end() throws Exception {
            String broken;
            if (controller.isCapturePaused() && (broken = closing("TAP")) != null) return broken;
            for (int round = 0; round < 3; round++) {
                for (String step : new String[]{"DOUBLETAP", "PHOTO", "ACK", "WAIT:3100"}) {
                    if ((broken = closing(step)) != null) return broken;
                }
            }
            RelayState state = controller.getState();
            boolean ending = (boolean) get(controller, "finishCaptureRequested");
            // With no page saved an END is not taken and the capture goes on
            // (LocalReviewTest.aDoubleTapBeforeAnyPageIsSavedLeavesTheCaptureRunning): then no end stays requested,
            // and I1, checked after the last step above, says that the capture which goes on is live.
            if (session.phase() != LocalCaptureSession.Phase.CAPTURE || state == RelayState.ERROR
                    || (session.pageCount() == 0 && !ending)) return null;
            return "I5 the end is live: after the closing script the capture has neither ended nor failed [state=" + state
                    + " paused=" + controller.isCapturePaused() + " ending=" + ending
                    + " pages=" + session.pageCount() + " told=\"" + told + "\"]";
        }

        private String closing(String step) throws Exception {
            String broken = step(step);
            done.remove(done.size() - 1); // the closing script is written as CLOSE
            return broken == null ? null : broken + " (in the closing script, at " + step + ")";
        }

        @Override public void close() { controller.close(); }
    }

    /** The glasses' display and camera, reduced to what the controller can tell of them. */
    private static final class Glasses implements CaptureSurface {
        // GlassCamera: one waiting page callback.
        volatile Runnable pageReady;
        // A takePhoto the test has not answered yet, and whether another one came on top of it (I2).
        volatile boolean requestOpen, overlapping;
        // GlassesCaptureSurface.show: one counter for every view; only the newest can be reported shown.
        volatile long generation, visibleReview = NO_VIEW_GENERATION;
        volatile String purpose = "";
        volatile boolean shown, nextStillFails;
        // What the number above the small window last said (showCaptureAiming).
        volatile int aimingPage;
        volatile boolean aimingRetake;

        @Override public boolean supportsLocalCaptureReview() { return true; }
        @Override public boolean isCaptureReviewVisible(long view) { return view == visibleReview && view != NO_VIEW_GENERATION; }
        @Override public void awaitNextPage(Runnable ready) { pageReady = ready; }
        @Override public void pausePreview() { pageReady = null; }
        @Override public PhotoStartResult takePhoto(int width, int height, int quality) {
            if (requestOpen) overlapping = true;
            requestOpen = true;
            return PhotoStartResult.STARTED;
        }
        @Override public long showHud(List<String> lines) { return show("hud"); }
        @Override public long showCaptureAiming(int page, boolean retake, boolean stabilizing) {
            aimingPage = page;
            aimingRetake = retake;
            return show(stabilizing ? "capture-stabilizing" : "capture-aiming");
        }
        @Override public long showCaptureReview(byte[] jpeg, int rotation, List<String> lines) {
            // As the real surface: nothing is drawn and no view is counted for a still that cannot be decoded.
            if (nextStillFails) { nextStillFails = false; return NO_VIEW_GENERATION; }
            return show("capture-review");
        }
        @Override public void fenceCustomViewEpoch(long view, String reason) { }

        private long show(String view) {
            purpose = view;
            shown = false;
            visibleReview = NO_VIEW_GENERATION;
            return ++generation;
        }
    }

    /**
     * Runs the controller's delayed callbacks against the clock its deadlines are read from, in the order of their
     * deadlines and each at its own time (LocalReviewTest's ClockedWatchdog runs them in the order they were asked for).
     */
    private static final class Clock extends ScheduledThreadPoolExecutor {
        private record Timer(long deadline, ScheduledFuture<?> task) { }
        private final List<Timer> timers = new ArrayList<>();

        Clock() { super(1); }

        @Override public synchronized ScheduledFuture<?> schedule(Runnable task, long delay, TimeUnit unit) {
            ScheduledFuture<?> held = super.schedule(task, 1, TimeUnit.DAYS);
            timers.add(new Timer(SystemClock.elapsedRealtime() + unit.toMillis(delay), held));
            return held;
        }

        /** Held: the controller's thread is busy, so what falls due is only queued behind it. */
        void advanceBy(DocScanController controller, long millis, boolean held) throws Exception {
            long end = SystemClock.elapsedRealtime() + millis;
            for (;;) {
                Timer next = null;
                synchronized (this) {
                    for (Timer timer : timers) {
                        if (timer.deadline <= end && (next == null || timer.deadline < next.deadline)) next = timer;
                    }
                    timers.remove(next);
                }
                if (next == null) break;
                moveTo(next.deadline);
                ((Runnable) next.task).run();
                if (!held) barrier(controller);
            }
            moveTo(end);
        }

        private static void moveTo(long time) {
            long ahead = time - SystemClock.elapsedRealtime();
            if (ahead > 0) ShadowSystemClock.advanceBy(Duration.ofMillis(ahead));
        }
    }

    // ---- helpers, as in LocalReviewTest ---------------------------------------------------------------------------

    private static Object get(Object object, String name) throws Exception {
        Field field = object.getClass().getDeclaredField(name); field.setAccessible(true);
        return field.get(object);
    }
    private static void set(Object object, String name, Object value) throws Exception {
        Field field = object.getClass().getDeclaredField(name); field.setAccessible(true); field.set(object, value);
    }
    private static void barrier(Object object) throws Exception {
        ((ExecutorService) get(object, "serial")).submit(() -> {}).get(5, TimeUnit.SECONDS);
        ((ExecutorService) get(object, "serial")).submit(() -> {}).get(5, TimeUnit.SECONDS);
    }
    private static void delete(File file) {
        File[] inside = file.listFiles();
        if (inside != null) for (File entry : inside) delete(entry);
        file.delete();
    }
}
