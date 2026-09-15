package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertArrayEquals;
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
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;
import java.util.function.Supplier;

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
    // Counts only "/answer-bundle" requests. server.getRequestCount() alone
    // is not enough for aSecondSessionInTheSameActivityInstanceFetchesAgain,
    // which also drives a real DocScanController recovery
    // (finalize-reading + review) through the same MockWebServer.
    private final AtomicInteger answerBundleRequests = new AtomicInteger();

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
        setField(activity, "connectionSettings", new ConnectionSettings(new File(filesDir, "test-connection.bin"),
                javax.crypto.KeyGenerator.getInstance("AES").generateKey()));
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
    public void delayedBackEventsKeepTheirOriginalConfirmationInterval() throws Exception {
        invokeOpenAnswers(bundleForSession(SESSION_ID), "q10", 0);
        invokeOnAction(GlassesInputAction.BACK, 1000);
        invokeOnAction(GlassesInputAction.BACK, 5000);
        assertNotNull("events four seconds apart cannot confirm exit", getField(activity, "reader"));
        invokeOnAction(GlassesInputAction.BACK, 5500);
        assertNull(getField(activity, "reader"));
    }

    @Test
    public void menuBackReturnsOneLevelAndFocusLossDisarmsExit() throws Exception {
        invokeOpenAnswers(bundleForSession(SESSION_ID), "q10", 0);
        AnswerReader reader = (AnswerReader) getField(activity, "reader");
        invokeOnAction(GlassesInputAction.SHORT_TAP);
        invokeOnAction(GlassesInputAction.SHORT_TAP);
        assertEquals(AnswerReader.Screen.QUESTIONS, reader.screen());
        invokeOnAction(GlassesInputAction.BACK);
        assertEquals(AnswerReader.Screen.GROUPS, reader.screen());
        assertFalse(backExit().isArmed());
        invokeOnAction(GlassesInputAction.BACK);
        assertEquals(AnswerReader.Screen.ANSWER, reader.screen());
        assertFalse(backExit().isArmed());
        invokeOnAction(GlassesInputAction.BACK);
        assertTrue(backExit().isArmed());
        activity.onWindowFocusChanged(false);
        activity.onWindowFocusChanged(true);
        assertFalse(backExit().isArmed());
        invokeOnAction(GlassesInputAction.BACK);
        assertNotNull(getField(activity, "reader"));
        assertTrue(backExit().isArmed());
    }

    @Test
    public void theBundleIsFetchedOnceAndClosingTheReaderDoesNotReopenOrRefetchIt()
            throws Exception {
        activity.onUpdate(RelayState.REVIEW, List.of("a", "b", "c"), "review-1");
        awaitTrue(() -> getField(activity, "reader") != null);
        assertEquals("one HTTP request for the bundle", 1, server.getRequestCount());

        invokeOnAction(GlassesInputAction.BACK);
        assertNotNull(getField(activity, "reader"));
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

    /**
     * I3: one failed request must not permanently forfeit the session's
     * answers. The likeliest failure at a venue is the hotspot not yet up
     * when REVIEW is first published; {@code nextReviewItem}/
     * {@code previousReviewItem} republish REVIEW on every page turn, so the
     * guard must roll back on failure to give the next publish a free retry
     * -- and a fetch that does succeed must not be retried again.
     */
    @Test
    public void aFailedFetchIsRetriedOnTheNextReviewPublishButNotAfterSucceeding()
            throws Exception {
        AtomicInteger bundleAttempts = new AtomicInteger();
        server.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) {
                String path = request.getPath();
                if (path != null && path.endsWith("/answer-bundle")) {
                    if (bundleAttempts.incrementAndGet() == 1) {
                        return new MockResponse().setResponseCode(500);
                    }
                    return json(bundleForSession(SESSION_ID).toJson());
                }
                return new MockResponse().setResponseCode(404).setBody("unexpected test request");
            }
        });

        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue(() -> bundleAttempts.get() >= 1);
        Thread.sleep(200);
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertNull("a failed fetch must not open the reader",
                getField(activity, "reader"));

        // A later REVIEW publish -- e.g. nextReviewItem/previousReviewItem
        // republishing it -- must retry, not be permanently skipped.
        activity.onUpdate(RelayState.REVIEW, List.of("b"), "review-2");
        awaitTrue(() -> getField(activity, "reader") != null);
        assertEquals("the failed attempt must be retried exactly once more",
                2, bundleAttempts.get());

        // A successful fetch must not be retried by a further REVIEW publish.
        activity.onUpdate(RelayState.REVIEW, List.of("c"), "review-3");
        Thread.sleep(200);
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertEquals("a successful fetch must not be retried again",
                2, bundleAttempts.get());
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

    /**
     * C2: the saved reader must resume with no route to the server at all --
     * the one condition the whole feature exists for. Offline, a restart's
     * first {@code onUpdate} is never {@code RelayState.REVIEW}: reaching
     * REVIEW needs {@code finalize-reading} then {@code review}, both HTTP,
     * and a failed {@code resumeNow} publishes {@code ERROR} instead (see
     * {@code DocScanController.java:668-694,730}). This drives exactly that
     * -- {@code onUpdate(ERROR, ...)}, never REVIEW -- against a server
     * that fails every request, and the reader must still open from disk.
     */
    @Test
    public void aSavedReaderResumesFromAnUnreachableServerWithoutEverReachingReview()
            throws Exception {
        AnswerStore preSeeded = new AnswerStore(filesDir);
        AnswerBundle bundle = bundleForSession(SESSION_ID);
        preSeeded.start(bundle);
        preSeeded.save(bundle, "q11", 3, false);

        server.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) {
                return new MockResponse().setResponseCode(500)
                        .setBody("server unreachable in this test");
            }
        });

        activity.onUpdate(RelayState.ERROR, List.of("offline"), "network unreachable");
        awaitTrue(() -> getField(activity, "reader") != null);

        assertEquals("resume must not touch the network", 0, server.getRequestCount());
        AnswerReader reader = (AnswerReader) getField(activity, "reader");
        assertEquals("q11", reader.current().questionId);
        assertEquals(3, reader.offset());
    }

    private static AnswerBundle bundleForSession(long sessionId) {
        return new AnswerBundle(Long.toString(sessionId), "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 2"),
                AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
    }

    /**
     * Item 2 test-coverage gap flagged in review: {@code SESSION_ID} is
     * written into SharedPreferences once in {@code setUp} and
     * {@code DocScanController} only reads {@code KEY_SESSION} in its own
     * constructor, so nothing in the rest of this file ever varies the
     * session id mid-test. Every other test here still passes if
     * {@code answersFetchedForSession} is reverted to a plain
     * {@code boolean answersFetched} -- this is the one that does not (see
     * the fix report for the captured failing/passing runs).
     *
     * <p>The only real production path that hands an Activity a second,
     * genuinely-assigned session id is a new {@code DocScanController}
     * recovering a persisted session -- the same
     * {@code configureAndResume -> resumeNow}'s {@code sessionId > 0} branch
     * that runs on a real process restart (temple-arm fold), and the same
     * seam {@code DocScanControllerLifecycleTest} already drives. This test
     * persists a second session id, builds a second real
     * {@code DocScanController} against it, swaps it into this Activity
     * instance the same way {@code setUp} wires the first one, and drives
     * that controller's real recovery (finalize-reading, then review) end to
     * end through the Activity's real {@code onUpdate} callback.
     *
     * <p><b>What this proves:</b> when the same Activity instance observes
     * REVIEW for two distinct, genuinely-assigned session ids, it fetches
     * the answer bundle for both -- not just the first, which is what a
     * plain one-shot boolean guard would do.
     *
     * <p><b>What this does not prove:</b> that a single
     * {@code DocScanController} instance can hand the same Activity a
     * second session id without an intervening restart (e.g. a
     * SHORT_TAP-driven new document within one continuous run). That would
     * need a full second capture/OCR/finalize cycle through one controller
     * -- {@code sessionId} is only ever reassigned via
     * {@code api.createExamSession(...)}'s real response, in the finalize
     * flow or in this same recovery branch -- which would mean standing up
     * the capture/OCR/finalize HTTP surface as well as review's, not
     * attempted here for cost. The guard's job is identical either way: react
     * to whatever {@code controller.sessionId()} currently reports. Driving
     * that comparison through a second controller is the closest seam that
     * still exercises the real production check
     * ({@code sessionId != answersFetchedForSession}), rather than reaching
     * past it by poking the field with reflection.
     */
    @Test
    public void aSecondSessionInTheSameActivityInstanceFetchesAgain() throws Exception {
        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue(() -> getField(activity, "reader") != null);
        assertEquals("first session fetches once", 1, answerBundleRequests.get());

        long secondSessionId = SESSION_ID + 1;
        activity.getSharedPreferences("docscan_relay", Context.MODE_PRIVATE)
                .edit().putLong("session_id", secondSessionId).apply();
        DocScanController controller2 = new DocScanController(activity, new Surface(), null,
                activity, new ClientIdentity("test-glasses", "answer-test/1", "fake-camera"));
        try {
            assertEquals("test precondition: the new controller must read the "
                    + "second session id from preferences, not the first",
                    secondSessionId, controller2.sessionId());

            setField(activity, "controller", controller2);
            controller2.configureAndResume(server.url("/").toString(), "test-key", 180);

            awaitTrue(() -> answerBundleRequests.get() >= 2);
            assertEquals("the second session must be fetched too, not silently "
                    + "skipped by a guard still keyed to the first session",
                    2, answerBundleRequests.get());
        } finally {
            controller2.close();
        }
    }

    /**
     * The fetch -> persist -> new Activity -> resume round trip, made cheap
     * by the {@code bundleForSession(SESSION_ID)} fixture fix: the saved
     * bundle's session id now actually matches the session a later resume
     * checks against, which it never did against the old {@code bundle()}
     * ("s1") fixture. Reuses the same {@code controller} and
     * {@code filesDir} from {@code setUp} for a second Activity instance --
     * the same {@code AnswerStore} on disk is what a real process restart
     * shares, not a second controller (that is
     * {@link #aSecondSessionInTheSameActivityInstanceFetchesAgain}'s job).
     */
    @Test
    public void fetchThenPersistThenANewActivityResumesWithoutRefetching() throws Exception {
        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue("first activity reader", () -> getField(activity, "reader") != null);
        AnswerReader reader = (AnswerReader) getField(activity, "reader");
        int guard = 0;
        while (!"q11".equals(reader.current().questionId) && guard++ < 50) {
            invokeOnAction(GlassesInputAction.SWIPE_FORWARD);
        }
        assertEquals("q11", reader.current().questionId);
        int movedOffset = reader.offset();
        assertEquals("one HTTP request for the first Activity's fetch",
                1, answerBundleRequests.get());
        // persistAnswerPosition(false) now writes off the main thread (I4):
        // wait for the last swipe's write to land before the "restart"
        // reads it back, instead of assuming it already has.
        awaitSavedState(filesDir, "q11", movedOffset);

        DocScanGlassActivity activity2 = Robolectric.buildActivity(DocScanGlassActivity.class).get();
        setField(activity2, "hud", new HudView(activity2));
        setField(activity2, "answerStore", new AnswerStore(filesDir));
        setField(activity2, "controller", controller);

        activity2.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue("resumed activity reader", () -> getField(activity2, "reader") != null);

        assertEquals("resuming from the saved state must not re-fetch",
                1, answerBundleRequests.get());
        AnswerReader resumed = (AnswerReader) getField(activity2, "reader");
        assertEquals("q11", resumed.current().questionId);
        assertEquals(movedOffset, resumed.offset());
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

        // persistAnswerPosition(false) now writes off the main thread (I4),
        // so the on-disk state catches up asynchronously -- wait for it
        // instead of assuming the last gesture's write already landed.
        AnswerStore.Saved saved = awaitSavedState(filesDir, "q11", reader.offset());
        assertFalse(saved.closed);
    }

    /**
     * I4: {@code persistAnswerPosition} queues both position writes and the
     * CLOSED write on the same single-threaded executor, so CLOSED -- and
     * only {@code closeAnswers} blocks on its own write -- can never be
     * overtaken by a position write a faster preceding gesture already
     * queued. Fires two moving gestures immediately followed by BACK, with
     * no wait in between, and reads the file synchronously right after:
     * a separate queue (or no queue at all) for CLOSED could let a still
     * in-flight position write land after it and silently reopen the
     * session on the next resume.
     */
    @Test
    public void closingRightAfterMovingPersistsClosedNotAStalePosition() throws Exception {
        activity.onUpdate(RelayState.REVIEW, List.of("a"), "review-1");
        awaitTrue(() -> getField(activity, "reader") != null);

        invokeOnAction(GlassesInputAction.SWIPE_FORWARD);
        invokeOnAction(GlassesInputAction.SWIPE_FORWARD);
        invokeOnAction(GlassesInputAction.BACK);
        assertNotNull(getField(activity, "reader"));
        invokeOnAction(GlassesInputAction.BACK);

        AnswerStore.Saved saved = new AnswerStore(filesDir).load();
        assertNotNull(saved);
        assertTrue("CLOSED must not be overtaken by an earlier-queued, now-stale "
                + "position write", saved.closed);
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
    public void backDuringCaptureBelongsToCaptureCompletionInsteadOfAppExit()
            throws Exception {
        // No onUpdate(REVIEW, ...): the reader never opens, matching the
        // ordinary capture/review flow this must leave unchanged.
        assertNull(getField(activity, "reader"));

        pressBack();

        assertFalse("capture completion must not also arm app exit",
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
     * C1: {@code openAnswers}'s placeholder viewport (width=1f, replaced by
     * {@code AnswerView.onSizeChanged} as soon as it is laid out) must not
     * crash on any answer text. The old placeholder measured a cluster's
     * UTF-16 {@code length()}: any surrogate pair or combining mark -- a
     * math italic variable, an emoji, an NFD-decomposed accent -- measures
     * &gt;= 2, always &gt; width=1f, and {@code AnswerLayout.paginate}
     * throws {@code IllegalArgumentException("viewport narrower than
     * glyph")} for a cluster it cannot start a line with. Uses U+1D465
     * (MATHEMATICAL ITALIC SMALL X, "𝑥") as the surrogate pair.
     */
    @Test
    public void openAnswersToleratesASurrogatePairInThePlaceholderViewport() throws Exception {
        AnswerBundle bundle = new AnswerBundle(Long.toString(SESSION_ID), "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 𝑥")));

        invokeOpenAnswers(bundle, "q10", 0);

        assertNotNull("the placeholder viewport must not crash the Activity",
                getField(activity, "reader"));
    }

    @Test
    public void secondListeningBackFinishesAudioWhileTheLastPhotoRemainsInReview()
            throws Exception {
        java.util.concurrent.CountDownLatch audioUpload = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch releaseUpload = new java.util.concurrent.CountDownLatch(1);
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                if (request.getPath() != null && request.getPath().endsWith("/audio-chunks")) {
                    audioUpload.countDown();
                    releaseUpload.await(5, TimeUnit.SECONDS);
                }
                return json("{}");
            }
        });

        controller.close();
        LocalReviewSurface surface = new LocalReviewSurface();
        controller = new DocScanController(activity, surface, null, activity,
                new ClientIdentity("test-glasses", "answer-test/1", "fake-camera"));
        controller.configure(server.url("/").toString(), "test-key", 180);
        controllerBarrier();
        setField(activity, "controller", controller);
        setField(activity, "listeningMode", true);

        File audioRoot = new File(filesDir, "rp08-stopped-audio");
        ListeningRecorder recording = stoppedRecording(audioRoot, 18, controller);
        setField(activity, "listening", recording);
        byte[] photo = new byte[]{11, 22, 33, 44};
        invokeStageCaptureReview(photo);
        File pendingOriginal = new File(filesDir, "pending-capture-v1.bin");
        byte[] savedPhoto = java.nio.file.Files.readAllBytes(pendingOriginal.toPath());

        try {
            invokeOnAction(GlassesInputAction.BACK, 1_000);
            controllerBarrier();
            assertTrue("the first BACK must end capture without leaving the last review",
                    (boolean) getField(controller, "finishCaptureRequested"));
            assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
            assertTrue(controller.hasPendingCaptureReview());
            assertArrayEquals(photo, surface.reviewJpeg);
            assertEquals("the first BACK must not finish the recording", 0, server.getRequestCount());

            invokeOnAction(GlassesInputAction.BACK, 2_000);
            assertTrue("the second BACK must start finishing the saved recording even while CAPTURE_REVIEW remains",
                    audioUpload.await(2, TimeUnit.SECONDS));
            Shadows.shadowOf(Looper.getMainLooper()).idle();
            assertFalse("audio finish must not turn off the last-photo review",
                    (boolean) getField(activity, "awaitingAnswers"));
            assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
            assertTrue(controller.hasPendingCaptureReview());
            assertArrayEquals(photo, surface.reviewJpeg);
            assertArrayEquals("the durable pending photo must remain byte-for-byte unchanged",
                    savedPhoto, java.nio.file.Files.readAllBytes(pendingOriginal.toPath()));
        } finally {
            releaseUpload.countDown();
            recording.close();
        }
    }

    @Test public void stoppedAudioCompletesWhenDocumentBindingArrivesWithoutStartingAnotherRecorder() throws Exception {
        java.util.concurrent.CountDownLatch complete = new java.util.concurrent.CountDownLatch(1);
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                if (request.getPath().endsWith("/audio-complete")) complete.countDown();
                return json("{}");
            }
        });
        controllerBarrier();
        setField(activity, "listeningMode", true);
        File root = new File(filesDir, "audio-before-binding");
        ListeningRecorder recording = stoppedRecording(root, 0, controller);
        setField(activity, "listening", recording);
        setField(activity, "listeningDirectory", root);
        byte[] original = java.nio.file.Files.readAllBytes(new File(root, "listening-0/0000.wav").toPath());
        try {
            Method finish = DocScanGlassActivity.class.getDeclaredMethod("finishAudio");
            finish.setAccessible(true); finish.invoke(activity);
            awaitTrue(() -> !(boolean) getField(activity, "finishingAudio"));
            assertEquals(0, server.getRequestCount());
            org.robolectric.shadows.ShadowApplication application = Shadows.shadowOf(org.robolectric.RuntimeEnvironment.getApplication());
            application.clearStartedServices();
            activity.onListeningReady(root, 18, false);
            Shadows.shadowOf(Looper.getMainLooper()).idle();
            android.content.Intent resumedService = application.getNextStartedService();
            assertNotNull("saved audio must have a foreground service during retry", resumedService);
            assertTrue(resumedService.getBooleanExtra(ListeningService.FINISHING, false));
            assertTrue(complete.await(3, TimeUnit.SECONDS));
            assertEquals("/v1/documents/18/audio-chunks", server.takeRequest().getPath());
            assertEquals("/v1/documents/18/audio-complete", server.takeRequest().getPath());
            assertTrue(recording == getField(activity, "listening"));
            assertNull(getField(recording, "microphone"));
            assertArrayEquals(original, java.nio.file.Files.readAllBytes(new File(root, "listening-0/0000.wav").toPath()));
        } finally { recording.close(); }
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
        invokeOnAction(action, android.os.SystemClock.elapsedRealtime());
    }

    private void invokeOnAction(GlassesInputAction action, long elapsedMillis) throws Exception {
        Method onAction = DocScanGlassActivity.class.getDeclaredMethod(
                "onAction", GlassesInputAction.class, long.class);
        onAction.setAccessible(true);
        onAction.invoke(activity, action, elapsedMillis);
    }

    private void controllerBarrier() throws Exception {
        ((ExecutorService) getField(controller, "serial")).submit(() -> { }).get(5, TimeUnit.SECONDS);
    }

    private void invokeStageCaptureReview(byte[] jpeg) throws Exception {
        for (Method method : DocScanController.class.getDeclaredMethods()) {
            if (method.getName().equals("stageCaptureReview") && method.getParameterCount() == 7) {
                method.setAccessible(true);
                method.invoke(controller, 0, jpeg, "実資料", 180, "", null, null);
                return;
            }
        }
        throw new AssertionError("stageCaptureReview overload not found");
    }

    private static ListeningRecorder stoppedRecording(
            File root, long documentId, DocScanController controller) throws Exception {
        File folder = new File(root, "listening-" + documentId);
        assertTrue(folder.mkdirs());
        java.nio.file.Files.write(new File(folder, "started-epoch-ms").toPath(),
                "1700000000000".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        File wav = new File(folder, "0000.wav");
        try (java.io.RandomAccessFile output = new java.io.RandomAccessFile(wav, "rw")) {
            output.write(ListeningRecorder.wavHeader(3200));
            output.write(new byte[3200]);
        }
        java.util.Properties manifest = new java.util.Properties();
        manifest.setProperty("phase", "stopped");
        manifest.setProperty("epoch", "1700000000000");
        manifest.setProperty("document", Long.toString(documentId));
        manifest.setProperty("chunks", "1");
        manifest.setProperty("samples", "1600");
        try (java.io.FileOutputStream output = new java.io.FileOutputStream(
                new File(folder, "recording.properties"))) {
            manifest.store(output, "stopped before network ACK");
        }
        ListeningRecorder recording = new ListeningRecorder(root, documentId, controller.api(), () -> { });
        assertTrue(recording.restore());
        assertFalse(recording.isInterrupted());
        return recording;
    }

    private static void awaitTrue(BooleanSupplier condition) throws InterruptedException {
        awaitTrue("condition", condition);
    }

    /**
     * `what` is not decoration: every wait in this file reports the same
     * "condition not met within timeout", so a failure names the helper's line
     * and nothing about which wait, or what the state actually was.
     */
    private static void awaitTrue(String what, BooleanSupplier condition)
            throws InterruptedException {
        awaitTrue(() -> what, condition);
    }

    /** The message is built on failure, so it can report the state it saw. */
    private static void awaitTrue(Supplier<String> what, BooleanSupplier condition)
            throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (System.nanoTime() < deadline) {
            Shadows.shadowOf(Looper.getMainLooper()).idle();
            if (condition.getAsBoolean()) {
                return;
            }
            Thread.sleep(10);
        }
        assertTrue(what.get() + " not met within 5s", condition.getAsBoolean());
    }

    /**
     * I4: {@code persistAnswerPosition(false)} now queues its write on a
     * background executor instead of writing inline, so a test that just
     * moved the reader cannot assume the on-disk state already matches --
     * it has to wait for it, the same way {@link #awaitTrue} waits for a
     * main-thread post.
     */
    /**
     * Wait for the write itself, not for a stretch of wall-clock time.
     *
     * persistAnswerPosition(false) queues the write on the Activity's
     * single-threaded answerPersistExecutor, so submitting an empty task and
     * waiting for THAT proves the earlier write has already run: a
     * single-threaded executor runs its queue in order. Polling the file for
     * five seconds instead made this a race against the CI runner's load, and
     * it lost there while passing on a developer machine.
     */
    private AnswerStore.Saved awaitSavedState(File dir, String questionId, int offset)
            throws Exception {
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        ExecutorService persist =
                (ExecutorService) getField(activity, "answerPersistExecutor");
        persist.submit(() -> { }).get(30, TimeUnit.SECONDS);
        AnswerStore.Saved saved = new AnswerStore(dir).load();
        assertNotNull("nothing was persisted at all", saved);
        assertEquals("persisted question", questionId, saved.questionId);
        assertEquals("persisted offset", offset, saved.offset);
        return saved;
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
                    answerBundleRequests.incrementAndGet();
                    // sessionId must match SESSION_ID, the same way the real
                    // server's answer-bundle response's session_id always
                    // matches the session it was requested for
                    // (app/main.py:2841 returns str(session_id)). A mismatch
                    // here (the old "s1" placeholder) made every fetch->
                    // persist->resume round trip untestable, since no saved
                    // bundle could ever match the session a later resume
                    // checks against.
                    return json(bundleForSession(SESSION_ID).toJson());
                }
                // Only exercised by aSecondSessionInTheSameActivityInstanceFetchesAgain,
                // which drives a second, real DocScanController through its
                // own recovery path (resumeNow) to reach REVIEW with a
                // second, genuinely-assigned session id.
                if (path != null && path.endsWith("/finalize-reading")) {
                    return json("{\"status\":\"ready\"}");
                }
                if (path != null && path.contains("/review?")) {
                    return json("{\"index\":0,\"problem_count\":1,\"glasses_view\":{"
                            + "\"lines\":[\"answer\"],\"view_page\":0,\"total_view_pages\":1}}");
                }
                return new MockResponse().setResponseCode(404).setBody("unexpected test request");
            }
        });
        result.start();
        return result;
    }

    private static MockResponse json(String body) {
        return new MockResponse().addHeader("Content-Type", "application/json").setBody(body);
    }

    private static class Surface implements CaptureSurface {
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

    private static final class LocalReviewSurface extends Surface {
        byte[] reviewJpeg;

        @Override public boolean supportsLocalCaptureReview() {
            return true;
        }

        @Override public long showCaptureReview(byte[] jpeg, int rotation, List<String> lines) {
            reviewJpeg = jpeg.clone();
            return super.showCaptureReview(jpeg, rotation, lines);
        }
    }
}
