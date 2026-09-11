package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import android.os.Looper;
import android.view.KeyEvent;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;

import java.io.File;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;

import dev.rokid.docscanglass.input.BackExitPolicy;
import dev.rokid.docscanglass.input.GlassesInputAction;
import dev.rokid.docscanrelay.CaptureSurface;
import dev.rokid.docscanrelay.ClientIdentity;
import dev.rokid.docscanrelay.DocScanController;
import dev.rokid.docscanrelay.RelayState;
import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
import dev.rokid.docscanrelay.study.AnswerReader;
import dev.rokid.docscanrelay.study.AnswerStore;

import okhttp3.mockwebserver.Dispatcher;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

/**
 * Task 5 review findings: the once-only fetch guard and the resume-before-fetch
 * wiring. {@code DocScanGlassActivity} implements {@code DocScanController.Listener}
 * itself, so {@code onUpdate} is driven directly, the same pattern
 * {@code DocScanGlassActivityIntentTest} already uses for this Activity.
 */
// sdk 28, not :glassdoc's usual 32: AnswerStoreTest (:relaycore) already
// pins 28 for the same reason -- API 32's android-all AtomicFile writes its
// replacement through a ".new" rename-over-existing-file step, which fails
// silently (logged, not thrown) on a Windows host filesystem. 28 is still
// >= this module's own minSdk 28, so nothing about the Activity under test
// is left unexercised.
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28, manifest = Config.NONE)
public class DocScanGlassActivityAnswerReadingTest {
    private static final long SESSION_ID = 7;

    private DocScanGlassActivity activity;
    private MockWebServer server;
    private DocScanController controller;
    // Captured once: Robolectric's Context.getFilesDir() is not guaranteed to
    // return the same File across separate calls (AnswerSurfaceTest avoids
    // this the same way, by capturing its directory into a local once).
    private File filesDir;

    private AnswerBundle bundle() {
        return new AnswerBundle("s1", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 2"),
                AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
    }

    @Before
    public void setUp() throws Exception {
        activity = Robolectric.buildActivity(DocScanGlassActivity.class).get();
        filesDir = activity.getFilesDir();
        setField(activity, "hud", new HudView(activity));
        setField(activity, "answerStore", new AnswerStore(filesDir));
        // configureAndResume's health check is not exercised here; onCreate
        // was not called (matching DocScanGlassActivityIntentTest's own
        // pattern), so nothing else has touched "docscan_relay" yet.
        activity.getSharedPreferences("docscan_relay", Context.MODE_PRIVATE)
                .edit().clear().putLong("session_id", SESSION_ID).apply();
        server = newServer();
        controller = new DocScanController(activity, new Surface(), null, activity,
                new ClientIdentity("test-glasses", "answer-test/1", "fake-camera"));
        controller.configure(server.url("/").toString(), "test-key", 180);
        setField(activity, "controller", controller);
    }

    @After
    public void tearDown() throws Exception {
        if (controller != null) {
            controller.close();
        }
        if (server != null) {
            server.shutdown();
        }
    }

    @Test
    public void theBundleIsFetchedOnceAndClosingTheReaderDoesNotReopenOrRefetchIt()
            throws Exception {
        activity.onUpdate(RelayState.REVIEW, List.of("a", "b", "c"), "review-1");
        awaitTrue(() -> getField(activity, "reader") != null);
        assertEquals("one HTTP request for the bundle", 1, server.getRequestCount());

        invokeOnAction(GlassesInputAction.BACK);
        assertNull("closing must release screen ownership", getField(activity, "reader"));
        AnswerStore.Saved closed = new AnswerStore(filesDir).load();
        assertNotNull(closed);
        assertTrue("closeAnswers must persist CLOSED", closed.closed);

        // A REVIEW publish after the operator left the reader (e.g. the
        // controller's own nextReviewItem/previousReviewItem republishing
        // REVIEW) must not re-fetch or hand the screen back to the reader.
        activity.onUpdate(RelayState.REVIEW, List.of("d", "e", "f"), "review-2");
        Thread.sleep(200);
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertEquals("no second request after close", 1, server.getRequestCount());
        assertNull("the reader must not reopen on its own", getField(activity, "reader"));
    }

    @Test
    public void aSavedReaderIsResumedInsteadOfFetched() throws Exception {
        AnswerStore preSeeded = new AnswerStore(filesDir);
        // sessionId must match the controller's session (SESSION_ID): a saved
        // bundle from a different session must not be resumed, see
        // aSavedReaderFromADifferentSessionIsNotResumedAndIsFetchedInstead.
        AnswerBundle bundle = bundleForSession(SESSION_ID);
        preSeeded.start(bundle);
        // Offset 3 of "y = 3" (length 5): AnswerReader#restore clamps to the
        // current question's own answer length, so a larger offset here would
        // silently pass even if resume's offset were ignored entirely.
        preSeeded.save(bundle, "q11", 3, false);

        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue(() -> getField(activity, "reader") != null);

        assertEquals("resume must not touch the network", 0, server.getRequestCount());
        AnswerReader reader = (AnswerReader) getField(activity, "reader");
        assertEquals("q11", reader.current().questionId);
        assertEquals(3, reader.offset());
    }

    /**
     * New Breakage #1 from the Task 5 fix-round review: {@code AnswerStore}'s
     * {@code save} rejects a mismatched {@code sessionId} as stale, but an
     * earlier version of the resume path did not apply the same check, so a
     * bundle saved for one session was resumed for any later one and no
     * fetch ever ran again. This pins the fix: a saved bundle for a
     * different session must be ignored and a fresh fetch must run instead.
     */
    @Test
    public void aSavedReaderFromADifferentSessionIsNotResumedAndIsFetchedInstead()
            throws Exception {
        AnswerStore preSeeded = new AnswerStore(filesDir);
        AnswerBundle staleBundle = bundle(); // sessionId "s1" != SESSION_ID (7)
        preSeeded.start(staleBundle);
        preSeeded.save(staleBundle, "q11", 3, false);

        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue(() -> getField(activity, "reader") != null);

        assertEquals("a session mismatch must fall through to a fresh fetch",
                1, server.getRequestCount());
        AnswerReader reader = (AnswerReader) getField(activity, "reader");
        assertEquals("the freshly fetched bundle must be shown, not the stale saved state",
                "q10", reader.current().questionId);
        assertEquals(0, reader.offset());
    }

    /**
     * New Breakage #3: {@code AnswerStore.resume()} is documented as the only
     * thing allowed to clear CLOSED, and only for a user-requested resume.
     * The automatic path on REVIEW is not that, so it must read with
     * {@code load()} and leave a same-session CLOSED save alone -- neither
     * reopening the old reader nor fetching a fresh one that would silently
     * undo the close.
     */
    @Test
    public void aClosedSavedReaderIsNotAutomaticallyReopenedOrRefetched() throws Exception {
        AnswerStore preSeeded = new AnswerStore(filesDir);
        AnswerBundle bundle = bundleForSession(SESSION_ID);
        preSeeded.start(bundle);
        preSeeded.save(bundle, "q11", 3, true);

        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        Thread.sleep(200);
        Shadows.shadowOf(Looper.getMainLooper()).idle();

        assertNull("a CLOSED reader must not be reopened automatically",
                getField(activity, "reader"));
        assertEquals("a CLOSED reader for the current session must not trigger a fetch either",
                0, server.getRequestCount());
    }

    private static AnswerBundle bundleForSession(long sessionId) {
        return new AnswerBundle(Long.toString(sessionId), "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 2"),
                AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
    }

    @Test
    public void eachMovingGesturePersistsTheReaderPosition() throws Exception {
        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue(() -> getField(activity, "reader") != null);
        AnswerReader reader = (AnswerReader) getField(activity, "reader");
        assertEquals("q10", reader.current().questionId);

        int guard = 0;
        while (!"q11".equals(reader.current().questionId) && guard++ < 50) {
            invokeOnAction(GlassesInputAction.SWIPE_FORWARD);
        }
        assertEquals("swiping forward enough must cross into the second question",
                "q11", reader.current().questionId);

        AnswerStore.Saved saved = new AnswerStore(filesDir).load();
        assertNotNull(saved);
        assertFalse(saved.closed);
        assertEquals("the saved question must follow the reader, not stay at fetch time",
                "q11", saved.questionId);
        assertEquals(reader.offset(), saved.offset);
    }

    /**
     * Finding 3: leaving the reader must not also arm the two-stage exit.
     * Drives the real {@code onKeyDown}/{@code onKeyUp} pair -- the code path
     * {@code normalize} actually guards -- rather than calling {@code onAction}
     * directly, so the fix under test (the key-consumption decision) is the
     * thing exercised, not bypassed.
     *
     * <p>This cannot also exercise the one-finger-double-tap correlation that
     * really closes the reader on hardware ({@code KEYCODE_NOTIFICATION}
     * twice then {@code KEYCODE_BACK}, decided inside
     * {@code GlassesInputNormalizer}): under Robolectric 4.14.1,
     * {@code KeyEvent.keyCodeToString} always returns the numeric keyCode as
     * a string (confirmed by inspecting {@code shadows-framework-4.14.1.jar}
     * -- it shadows only {@code nativeKeyCodeFromString}, the reverse
     * direction), so {@code GlassKeyEvents.isKnown(name)} is false for every
     * key driven this way and the normalizer never recognizes a gesture.
     * That would need a real device, or a Robolectric shadow for
     * {@code KeyEvent.nativeKeyCodeToString}, to drive. The reader-closing
     * behavior itself is covered separately, at the {@code onAction} level,
     * by {@link #theBundleIsFetchedOnceAndClosingTheReaderDoesNotReopenOrRefetchIt}.
     * This test instead drives {@code onUpdate(REVIEW, ...)} through the real
     * fetch to put the reader in place (the same seam as the other tests in
     * this file), then drives only the key-consumption decision.
     */
    @Test
    public void backPressWhileTheReaderOwnsTheScreenDoesNotArmTheExitConfirmation()
            throws Exception {
        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue(() -> getField(activity, "reader") != null);

        pressBack();

        assertFalse("leaving the reader must not also arm the exit confirmation",
                backExit().isArmed());
    }

    /**
     * The other half of Finding 3's fix: when the reader does not own the
     * screen, the ordinary two-stage exit must arm exactly as before. A test
     * that only covered the reader case would still pass if BACK were made to
     * never reach the exit policy at all.
     */
    @Test
    public void backPressWhileTheReaderDoesNotOwnTheScreenStillArmsTheExitConfirmation()
            throws Exception {
        // No onUpdate(REVIEW, ...): the reader never opens, matching the
        // ordinary capture/review flow this must leave unchanged.
        assertNull(getField(activity, "reader"));

        pressBack();

        assertTrue("the ordinary two-stage exit must still arm on the first BACK",
                backExit().isArmed());
    }

    /**
     * Minor 2: a fetch or resume that completes after the two-stage exit
     * already finished the Activity must not touch its screen.
     */
    @Test
    public void openAnswersDoesNothingOnceTheActivityIsFinishing() throws Exception {
        activity.finish();
        assertTrue("test precondition: finish() must mark the Activity finishing",
                activity.isFinishing());

        invokeOpenAnswers(bundle(), "q10", 0);

        assertNull("a late fetch must not open the reader on a finishing Activity",
                getField(activity, "reader"));
        assertNull("a late fetch must not touch the screen of a finishing Activity",
                getField(activity, "answers"));
    }

    /**
     * A real BACK key press: {@code onKeyDown} then {@code onKeyUp}, both
     * through the Activity's real overrides, so {@code normalize}'s own
     * consumption decision -- not a stand-in for it -- controls whether
     * {@code super.onKeyUp} (and, through it, the framework's tracking-based
     * {@code onBackPressed} dispatch, unmodified by this change) ever runs.
     * The UP event carries {@code FLAG_TRACKING} because Robolectric does not
     * run the native input pipeline that would set it on a real device after
     * Activity's own default {@code onKeyDown} calls
     * {@code event.startTracking()} on the DOWN; this reproduces what a real
     * BACK release delivers to {@code onKeyUp}.
     */
    private void pressBack() {
        activity.onKeyDown(KeyEvent.KEYCODE_BACK,
                new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_BACK));
        activity.onKeyUp(KeyEvent.KEYCODE_BACK,
                new KeyEvent(0L, 0L, KeyEvent.ACTION_UP, KeyEvent.KEYCODE_BACK,
                        0, 0, 0, 0, KeyEvent.FLAG_TRACKING));
    }

    private BackExitPolicy backExit() {
        return (BackExitPolicy) getField(activity, "backExit");
    }

    private void invokeOpenAnswers(AnswerBundle bundle, String questionId, int offset)
            throws Exception {
        Method openAnswers = DocScanGlassActivity.class.getDeclaredMethod(
                "openAnswers", AnswerBundle.class, String.class, int.class);
        openAnswers.setAccessible(true);
        openAnswers.invoke(activity, bundle, questionId, offset);
    }

    private void invokeOnAction(GlassesInputAction action) throws Exception {
        Method onAction = DocScanGlassActivity.class.getDeclaredMethod(
                "onAction", GlassesInputAction.class);
        onAction.setAccessible(true);
        onAction.invoke(activity, action);
    }

    private static void awaitTrue(BooleanSupplier condition) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (System.nanoTime() < deadline) {
            Shadows.shadowOf(Looper.getMainLooper()).idle();
            if (condition.getAsBoolean()) {
                return;
            }
            Thread.sleep(10);
        }
        assertTrue("condition not met within timeout", condition.getAsBoolean());
    }

    private static Object getField(Object target, String name) {
        try {
            Field field = target.getClass().getDeclaredField(name);
            field.setAccessible(true);
            return field.get(target);
        } catch (ReflectiveOperationException error) {
            throw new AssertionError(error);
        }
    }

    private static void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

    private MockWebServer newServer() throws Exception {
        MockWebServer result = new MockWebServer();
        result.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) {
                String path = request.getPath();
                if (path != null && path.endsWith("/answer-bundle")) {
                    return new MockResponse().setBody(bundle().toJson());
                }
                return new MockResponse().setResponseCode(404).setBody("unexpected test request");
            }
        });
        result.start();
        return result;
    }

    private static final class Surface implements CaptureSurface {
        private long generation;

        @Override
        public PhotoStartResult takePhoto(int width, int height, int quality) {
            throw new AssertionError("Answer reading must never request a photo");
        }

        @Override
        public long showHud(List<String> lines) {
            return ++generation;
        }

        @Override
        public long showCaptureAiming(int pageNumber, boolean retake, boolean stabilizing) {
            return ++generation;
        }

        @Override
        public long showCaptureReview(byte[] jpeg, int rotation, List<String> lines) {
            return ++generation;
        }

        @Override
        public void fenceCustomViewEpoch(long viewGeneration, String reason) {
        }
    }
}
