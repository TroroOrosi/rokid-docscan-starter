package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;

import java.lang.reflect.Field;
import java.io.File;
import java.io.IOException;
import javax.crypto.KeyGenerator;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import dev.rokid.docscanrelay.CaptureLinkEvent;
import dev.rokid.docscanrelay.CaptureSurface;
import dev.rokid.docscanrelay.ClientIdentity;
import dev.rokid.docscanrelay.DocScanController;
import dev.rokid.docscanrelay.RelayState;
import dev.rokid.docscanglass.input.GlassesInputAction;
import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
import dev.rokid.docscanrelay.study.AnswerStore;
import okhttp3.mockwebserver.Dispatcher;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

/** Intent delivery with the real Activity, HUD and serial controller. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class DocScanGlassActivityIntentTest {
    private DocScanGlassActivity activity;
    private HudView hud;
    private DocScanController controller;
    private SharedPreferences workflow;
    private MockWebServer server;
    private final Updates updates = new Updates();

    @Test public void inspectionContextUsesOnlyThePersistedCurrentWearGeneration() throws Exception {
        setField(activity, "deviceId", "test-glasses");
        setField(activity, "powerGeneration", 12L);
        activity.getPreferences(Context.MODE_PRIVATE).edit().putLong("power_generation", 12)
                .putString("power_phase", "capturing").commit();
        var current = activity.captureInspectionContext();
        assertNotNull(current); assertEquals("test-glasses", current.deviceId); assertEquals(12, current.generation);
        activity.getPreferences(Context.MODE_PRIVATE).edit().putLong("power_generation", 13).commit();
        assertNull("a newer wear run fences the old Activity", activity.captureInspectionContext());
        setField(activity, "powerGeneration", 13L);
        assertEquals(13, activity.captureInspectionContext().generation);
        activity.getPreferences(Context.MODE_PRIVATE).edit().putString("power_phase", "writing_done").commit();
        assertNull(activity.captureInspectionContext());
        activity.getPreferences(Context.MODE_PRIVATE).edit().putString("power_phase", "closed").commit();
        assertNull(activity.captureInspectionContext());
    }

    @Test public void terminalOrUnavailableInspectionContextDoesNotCreateANewGeneration() throws Exception {
        setField(activity, "deviceId", "test-glasses"); setField(activity, "powerGeneration", 12L);
        activity.getPreferences(Context.MODE_PRIVATE).edit().putLong("power_generation", 12)
                .putString("power_phase", "capturing").commit();
        setField(activity, "sessionClosed", true); assertNull(activity.captureInspectionContext());
        setField(activity, "sessionClosed", false); setField(activity, "writingDone", true);
        assertNull(activity.captureInspectionContext());
        setField(activity, "writingDone", false); setField(activity, "deviceId", "invalid device");
        assertNull(activity.captureInspectionContext());
        assertEquals(12, activity.getPreferences(Context.MODE_PRIVATE).getLong("power_generation", -1));
    }

    @Before
    public void setUp() throws Exception {
        // buildActivity attaches a real Context before onCreate. Inject the two
        // collaborators needed by onNewIntent so camera2/ML Kit are not started.
        activity = Robolectric.buildActivity(DocScanGlassActivity.class).get();
        hud = new HudView(activity);
        setField(activity, "hud", hud);
        updates.settings = new ConnectionSettings(new File(activity.getFilesDir(), "intent-connection.bin"),
                KeyGenerator.getInstance("AES").generateKey());
        setField(activity, "connectionSettings", updates.settings);
        activity.getPreferences(Context.MODE_PRIVATE).edit().clear().commit();
        workflow = activity.getSharedPreferences("docscan_relay", Context.MODE_PRIVATE);
        workflow.edit().clear().commit();
        server = newServer();
        controller = new DocScanController(activity, new Surface(), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        setField(activity, "controller", controller);
        controller.configure(server.url("/").toString(), "original-test-key", 180);
        controller.onCaptureLinkStateChanged(true, CaptureLinkEvent.GLASSES_STATUS_CHANGED);
        updates.awaitState(RelayState.READY);
        updates.clear();
    }

    @After
    public void tearDown() throws Exception {
        if (controller != null) {
            controller.close();
        }
        if (server != null) {
            server.shutdown();
        }
        ((java.util.concurrent.ExecutorService)org.robolectric.util.ReflectionHelpers.getField(activity, "stateExecutor")).shutdownNow();
        ((android.os.Handler)org.robolectric.util.ReflectionHelpers.getField(activity, "main")).removeCallbacksAndMessages(null);
        // onCreate was not called, so no camera/Activity lifecycle cleanup is owed.
    }

    @Test
    public void guideOnlyIntentChangesHudAndPersistenceWhileCaptureRemainsArmed() throws Exception {
        controller.captureNextPage();
        updates.awaitState(RelayState.AIMING);
        updates.clear();
        Intent intent = new Intent().putExtra("guide", 0.72f).putExtra("spread", true);

        activity.onNewIntent(intent);
        awaitControllerBarrier();

        assertSame(intent, activity.getIntent());
        assertEquals(0.72, guideFraction(), 0.00001);
        assertEquals(0.72f, activity.getPreferences(Context.MODE_PRIVATE).getFloat("guide", -1), 0.00001f);
        assertTrue(activity.getPreferences(Context.MODE_PRIVATE).getBoolean("spread", false));
        Field spread = HudView.class.getDeclaredField("spreadGuide");
        spread.setAccessible(true);
        assertTrue(spread.getBoolean(hud));
        assertEquals(RelayState.AIMING, controller.getState());
        assertEquals("Guide-only Intent must not submit configuration work", 1, updates.size());
        assertEquals(0, server.getRequestCount());
    }

    /** The wearer cannot see the lowest part of the panel: every screen is laid out above a saved margin. */
    @Test
    public void bottomMarginIntentRaisesEveryScreenAndPersistsWhileCaptureRemainsArmed() throws Exception {
        controller.captureNextPage();
        updates.awaitState(RelayState.AIMING);
        android.view.View content = activity.findViewById(android.R.id.content);

        activity.onNewIntent(new Intent().putExtra("bottom_margin", 125));
        awaitControllerBarrier();

        assertEquals(125, content.getPaddingBottom());
        assertEquals(125, activity.getPreferences(Context.MODE_PRIVATE).getInt("bottom_margin", -1));
        assertEquals("the strip below the screens must stay dark", android.graphics.Color.BLACK,
                ((android.graphics.drawable.ColorDrawable) content.getBackground()).getColor());
        assertEquals(RelayState.AIMING, controller.getState());

        activity.onNewIntent(new Intent());
        activity.onNewIntent(new Intent().putExtra("bottom_margin", "40"));
        assertEquals("an Intent without an integer margin keeps the saved one", 125, content.getPaddingBottom());

        activity.onNewIntent(new Intent().putExtra("bottom_margin", 9999));
        assertEquals(DocScanGlassActivity.MAX_MARGIN, content.getPaddingBottom());
        activity.onNewIntent(new Intent().putExtra("bottom_margin", -5));
        assertEquals(0, content.getPaddingBottom());
        assertEquals(0, activity.getPreferences(Context.MODE_PRIVATE).getInt("bottom_margin", -1));
        assertEquals(0, server.getRequestCount());
    }

    /** Answers start at the top of the panel: the wearer who finds that too high lowers them with a top margin. */
    @Test
    public void topMarginIntentLowersEveryScreenIndependentlyOfTheBottomMargin() throws Exception {
        android.view.View content = activity.findViewById(android.R.id.content);

        activity.onNewIntent(new Intent().putExtra("bottom_margin", 125).putExtra("top_margin", 80));
        assertEquals(80, content.getPaddingTop());
        assertEquals(125, content.getPaddingBottom());
        assertEquals(80, activity.getPreferences(Context.MODE_PRIVATE).getInt("top_margin", -1));

        activity.onNewIntent(new Intent().putExtra("bottom_margin", 100));
        assertEquals("one margin alone keeps the other", 80, content.getPaddingTop());
        assertEquals(100, content.getPaddingBottom());

        activity.onNewIntent(new Intent().putExtra("top_margin", 9999).putExtra("bottom_margin", 9999));
        assertEquals(DocScanGlassActivity.MAX_MARGIN, content.getPaddingTop());
        assertEquals(DocScanGlassActivity.MAX_MARGIN, content.getPaddingBottom());
        assertTrue("both at their limit still leave a screen", 640 - 2 * DocScanGlassActivity.MAX_MARGIN >= 160);
    }

    /** The wearer does not see the lowest part of the panel: before any margin is saved, every screen stands above it. */
    @Test public void the_bottom_margin_defaults_to_125() {
        android.view.View content = activity.findViewById(android.R.id.content);
        activity.onNewIntent(new Intent().putExtra("top_margin", 10));
        assertEquals(125, content.getPaddingBottom());
        activity.onNewIntent(new Intent().putExtra("bottom_margin", 0));
        assertEquals("a saved value is kept, zero too", 0, content.getPaddingBottom());
        activity.onNewIntent(new Intent().putExtra("top_margin", 20));
        assertEquals(0, content.getPaddingBottom());
    }

    @Test public void the_capture_option_is_saved_and_clips_are_for_ordinary_written_reading_only() {
        SharedPreferences saved = activity.getPreferences(Context.MODE_PRIVATE);
        assertEquals("stills until the desk checks have passed", "still", DocScanGlassActivity.captureOption(saved));
        activity.onNewIntent(new Intent().putExtra("capture", "clip"));
        assertEquals("clip", DocScanGlassActivity.captureOption(saved));
        activity.onNewIntent(new Intent().putExtra("guide", 0.6f));
        assertEquals("an Intent without the option keeps it", "clip", DocScanGlassActivity.captureOption(saved));
        assertTrue(DocScanGlassActivity.clipRoute("clip", true, false, false));
        assertFalse("mixed English keeps the still camera", DocScanGlassActivity.clipRoute("clip", true, true, true));
        assertFalse("listening keeps the still camera", DocScanGlassActivity.clipRoute("clip", true, false, true));
        assertFalse("so does every evaluation launch", DocScanGlassActivity.clipRoute("clip", false, false, false));
        assertFalse(DocScanGlassActivity.clipRoute("still", true, false, false));
        activity.onNewIntent(new Intent().putExtra("capture", "anything else"));
        assertEquals("still", DocScanGlassActivity.captureOption(saved));

        activity.onNewIntent(new Intent().putExtra("far_share", 0.3f));
        assertEquals(0.3f, saved.getFloat("far_share", -1), 0.0001f);
        activity.onNewIntent(new Intent().putExtra("far_share", 7f));
        assertEquals("a share is at most the whole window", 1f, saved.getFloat("far_share", -1), 0.0001f);
        assertEquals("until a gain is saved a clip never takes the long exposure", 0L, DocScanGlassActivity.longExposure(saved, 60_000_000L));
        activity.onNewIntent(new Intent().putExtra("long_above", 300));
        assertEquals("the gain, in hundredths, above which a clip takes the long exposure", 300, saved.getInt("long_above", -1));
        activity.onNewIntent(new Intent().putExtra("long_above", 5));
        assertEquals("never under 1.0", 100, saved.getInt("long_above", -1));
        assertEquals("a saved gain turns the long exposure on", 60_000_000L, DocScanGlassActivity.longExposure(saved, 60_000_000L));
        activity.onNewIntent(new Intent().putExtra("long_above", 0));
        assertFalse("0 turns it off again", saved.contains("long_above"));
        assertEquals(0L, DocScanGlassActivity.longExposure(saved, 60_000_000L));
    }

    /** The kind of session is chosen on the chooser, after the cameras were built: the camera is chosen when it starts. */
    @Test public void an_ordinary_written_session_records_clips_and_any_other_keeps_the_still_camera() throws Exception {
        android.os.HandlerThread thread = new android.os.HandlerThread("test-camera");
        thread.start();
        try {
            GlassCamera still = new GlassCamera(activity, new android.os.Handler(thread.getLooper()), new GlassCamera.Callback() {
                @Override public void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis) { }
                @Override public void onCaptureFailed(String reason) { }
            });
            GlassesCaptureSurface glasses = new GlassesCaptureSurface(activity, still, hud,
                    new android.os.Handler(android.os.Looper.getMainLooper()), activity);
            setField(activity, "cameraThread", thread); setField(activity, "stillCamera", still);
            setField(activity, "camera", still); setField(activity, "surface", glasses);
            setField(activity, "ordinaryCamera", true);
            java.lang.reflect.Method choose = DocScanGlassActivity.class.getDeclaredMethod("chooseCamera");
            choose.setAccessible(true);

            choose.invoke(activity);
            assertSame("stills unless clips were asked for", still, org.robolectric.util.ReflectionHelpers.getField(activity, "camera"));
            assertNull(org.robolectric.util.ReflectionHelpers.getField(controller, "clipInbox"));

            activity.onNewIntent(new Intent().putExtra("capture", "clip"));
            choose.invoke(activity);
            assertTrue(org.robolectric.util.ReflectionHelpers.getField(activity, "camera") instanceof ClipCamera);
            assertFalse("the surface answers for the camera in use", glasses.supportsFuturePages());
            assertNotNull("the controller looks for each page's clip", org.robolectric.util.ReflectionHelpers.getField(controller, "clipInbox"));

            setField(activity, "mixedMode", true); setField(activity, "listeningMode", true);
            choose.invoke(activity);
            assertSame("mixed English keeps the still camera", still, org.robolectric.util.ReflectionHelpers.getField(activity, "camera"));
            assertTrue(glasses.supportsFuturePages());
            assertNull(org.robolectric.util.ReflectionHelpers.getField(controller, "clipInbox"));

            setField(activity, "mixedMode", false); setField(activity, "listeningMode", false);
            setField(activity, "ordinaryCamera", false);
            choose.invoke(activity);
            assertSame("an evaluation launch keeps it too", still, org.robolectric.util.ReflectionHelpers.getField(activity, "camera"));
        } finally {
            thread.quitSafely();
        }
    }

    /**
     * The "paper too far" mark's rule does not measure distance: worn on 2026-11-16 it stood for 38 of 67 s while the
     * distance was fine (register 2-24). Off until a share is saved for a trial; the clip bar needs no option.
     */
    @Test public void the_far_mark_is_off_until_a_share_is_saved_and_the_clip_cameras_marks_go_to_the_display() throws Exception {
        android.os.HandlerThread thread = new android.os.HandlerThread("test-camera");
        thread.start();
        try {
            GlassCamera still = new GlassCamera(activity, new android.os.Handler(thread.getLooper()), new GlassCamera.Callback() {
                @Override public void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis) { }
                @Override public void onCaptureFailed(String reason) { }
            });
            GlassesCaptureSurface glasses = new GlassesCaptureSurface(activity, still, hud,
                    new android.os.Handler(android.os.Looper.getMainLooper()), activity);
            setField(activity, "cameraThread", thread); setField(activity, "stillCamera", still);
            setField(activity, "camera", still); setField(activity, "surface", glasses);
            setField(activity, "ordinaryCamera", true);
            java.lang.reflect.Method choose = DocScanGlassActivity.class.getDeclaredMethod("chooseCamera");
            choose.setAccessible(true);

            choose.invoke(activity);
            assertNull("the still route has no clip camera: nothing reports to the bar",
                    org.robolectric.util.ReflectionHelpers.getField(activity, "clipCamera"));

            activity.onNewIntent(new Intent().putExtra("capture", "clip"));
            choose.invoke(activity);
            ClipCamera clip = org.robolectric.util.ReflectionHelpers.getField(activity, "camera");
            ClipCamera.Options options = org.robolectric.util.ReflectionHelpers.getField(clip, "options");
            assertEquals("no far mark unless asked for", 0f, options.farShare, 0f);
            assertSame("what the clip camera reports is shown by the surface", glasses,
                    org.robolectric.util.ReflectionHelpers.getField(clip, "marks"));

            activity.onNewIntent(new Intent().putExtra("far_share", 0.3f));
            setField(activity, "clipCamera", null); // built once a run: the next run's
            choose.invoke(activity);
            clip = org.robolectric.util.ReflectionHelpers.getField(activity, "camera");
            options = org.robolectric.util.ReflectionHelpers.getField(clip, "options");
            assertEquals("--ef far_share turns it on for a trial", 0.3f, options.farShare, 0.0001f);
        } finally {
            thread.quitSafely();
        }
    }

    @Test public void ordinaryNewIntentRevokesComparisonTransferWithoutCarryingAnySavedFlag() throws Exception {
        CaptureVideoTransfer transfer=new CaptureVideoTransfer(activity.getFilesDir(),() -> null,null);
        setField(activity,"videoTransfer",transfer); setField(activity,"comparisonTransferEnabled",true);
        activity.getPreferences(Context.MODE_PRIVATE).edit().putBoolean("video_transfer_evaluation",true).commit();
        try {
            activity.onNewIntent(new Intent().putExtra("guide",0.61f));
            assertFalse((Boolean)org.robolectric.util.ReflectionHelpers.getField(activity,"comparisonTransferEnabled"));
            assertNull(org.robolectric.util.ReflectionHelpers.getField(activity,"videoTransfer"));
            assertTrue((Boolean)org.robolectric.util.ReflectionHelpers.getField(transfer,"closed"));
            assertFalse(DocScanGlassActivity.videoTransferEvaluation(new Intent()));
        } finally { transfer.close(); }
    }

    @Test
    public void intentWithoutGuidePreservesExistingCalibration() throws Exception {
        activity.onNewIntent(new Intent().putExtra("guide", 0.61f));
        Intent intent = new Intent();

        activity.onNewIntent(intent);
        awaitControllerBarrier();

        assertSame(intent, activity.getIntent());
        assertEquals(0.61, guideFraction(), 0.00001);
        assertEquals(0.61f, activity.getPreferences(Context.MODE_PRIVATE).getFloat("guide", -1), 0.00001f);
        assertEquals(0, server.getRequestCount());
    }

    @Test
    public void newServerAndKeyReachNewHttpDestinationAndKeepGuide() throws Exception {
        activity.onNewIntent(new Intent().putExtra("guide", 0.66f));
        try (MockWebServer replacement = newServer()) {
            Intent intent = new Intent()
                    .putExtra("server", replacement.url("/").toString())
                    .putExtra("key", "replacement-test-key");

            activity.onNewIntent(intent);
            updates.awaitState(RelayState.READY);

            assertSame(intent, activity.getIntent());
            RecordedRequest health = takeRequest(replacement);
            assertEquals("/health", health.getPath());
            assertEquals("Bearer replacement-test-key", health.getHeader("Authorization"));
            assertEquals(replacement.url("/").toString().replaceAll("/+$", ""),
                    workflow.getString("server", ""));
            assertEquals(0.66, guideFraction(), 0.00001);
            assertEquals(0, server.getRequestCount());
        }
    }

    @Test
    public void keyOnlyIntentUpdatesAuthenticationAtExistingServer() throws Exception {
        Intent intent = new Intent().putExtra("key", "updated-test-key");

        activity.onNewIntent(intent);
        updates.awaitState(RelayState.READY);

        assertSame(intent, activity.getIntent());
        RecordedRequest health = takeRequest(server);
        assertEquals("/health", health.getPath());
        assertEquals("Bearer updated-test-key", health.getHeader("Authorization"));
        assertEquals(server.url("/").toString().replaceAll("/+$", ""),
                workflow.getString("server", ""));
        assertFalse(intent.hasExtra("key"));
    }

    @Test
    public void restartUsesSavedCredentialButNewDestinationNeverReceivesIt() throws Exception {
        controller.close();
        controller = new DocScanController(activity, new Surface(), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        setField(activity, "controller", controller);
        java.lang.reflect.Method apply = DocScanGlassActivity.class.getDeclaredMethod("applyIntent", Intent.class, boolean.class);
        apply.setAccessible(true);
        apply.invoke(activity, new Intent(), true);
        assertEquals("Bearer original-test-key", takeRequest(server).getHeader("Authorization"));
        updates.awaitState(RelayState.READY);
        try (MockWebServer replacement = newServer()) {
            activity.onNewIntent(new Intent().putExtra("server", replacement.url("/").toString()));
            assertNull(takeRequest(replacement).getHeader("Authorization"));
        }
    }

    @Test
    public void rejectedDestinationCannotReplaceSavedConfiguration() throws Exception {
        controller.captureNextPage();
        updates.awaitState(RelayState.AIMING);
        String previous = updates.settings.load().server;
        activity.onNewIntent(new Intent().putExtra("server", "http://replacement.test").putExtra("key", "replacement"));
        awaitControllerBarrier();
        assertEquals(previous, updates.settings.load().server);
        assertEquals("original-test-key", updates.settings.load().key);
        assertEquals(0, server.getRequestCount());
    }

    @Test
    public void startupWaitsForSelectionAndNormalModeStartsWithoutHttp() throws Exception {
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        setField(activity, "controller", controller);
        setField(activity, "choosingSession", true);
        Shadows.shadowOf(activity.getApplication()).grantPermissions(android.Manifest.permission.CAMERA);
        java.lang.reflect.Method apply = DocScanGlassActivity.class.getDeclaredMethod("applyIntent", Intent.class, boolean.class);
        apply.setAccessible(true);
        apply.invoke(activity, new Intent(), true);
        awaitSerial();
        assertEquals(RelayState.DISCONNECTED, controller.getState());
        assertEquals(0, server.getRequestCount());
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, 1000L);
        assertEquals(0, server.getRequestCount());
        action.invoke(activity, GlassesInputAction.SWIPE_BACK, 1200L);
        // Operator, 2026-11-12: a tap turns the display off on every screen; the double tap starts.
        action.invoke(activity, GlassesInputAction.SHORT_TAP, 1300L);
        awaitSerial();
        assertFalse("a tap on the choices starts nothing", controller.hasLocalSession());
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, 1350L); // brings the display back, moves nothing
        action.invoke(activity, GlassesInputAction.BACK, 1400L);
        awaitSerial();
        assertEquals(RelayState.AIMING, controller.getState());
        assertTrue(controller.hasLocalSession());
        assertFalse(controller.isListeningMode());
        assertEquals(0, server.getRequestCount());
        assertTrue(controller.closeLocalSession());
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        assertTrue(controller.hasSavedWorkflow());
        assertEquals("Restart never starts a capture automatically", RelayState.DISCONNECTED, controller.getState());
    }

    private void awaitSerial() throws Exception {
        Field serial = DocScanController.class.getDeclaredField("serial");
        serial.setAccessible(true);
        ((java.util.concurrent.ExecutorService) serial.get(controller)).submit(() -> {}).get(5, TimeUnit.SECONDS);
        ((java.util.concurrent.ExecutorService) serial.get(controller)).submit(() -> {}).get(5, TimeUnit.SECONDS);
    }

    @Test public void ordinaryLaunchNeverInheritsThePreviousManualOverride() throws Exception {
        activity.getPreferences(Context.MODE_PRIVATE).edit().putBoolean("manual", true).commit();
        java.lang.reflect.Method apply = DocScanGlassActivity.class.getDeclaredMethod("applyIntent", Intent.class, boolean.class);
        apply.setAccessible(true);
        apply.invoke(activity, new Intent(), true);
        assertFalse(controller.isManualCapture());
        assertFalse(activity.getPreferences(Context.MODE_PRIVATE).contains("manual"));
        apply.invoke(activity, new Intent().putExtra("manual", true), true);
        assertTrue(controller.isManualCapture());
        apply.invoke(activity, new Intent(), true);
        assertFalse(controller.isManualCapture());
    }

    @Test @Config(sdk = 28, manifest = Config.NONE)
    public void closingPreviousAnswersDoesNotCloseAnUnselectedCapture() throws Exception {
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        controller.configureForLocalStart(server.url("/").toString(), "", 180);
        controller.startLocalSession(false);
        awaitSerial();
        File record = new File(activity.getFilesDir(), "local-scans/"
                + controller.savedCaptures().get(0).id + "/state.properties");
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        setField(activity, "controller", controller);
        AnswerStore answers = new AnswerStore(activity.getFilesDir());
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1,
                List.of(AnswerItem.ready("g1", "第1問", "q1", "問1", "2")));
        answers.start(bundle);
        answers.save(bundle, "q1", 0, true);
        setField(activity, "answerStore", answers);
        setField(activity, "startupAnswers", answers.load());
        setField(activity, "choosingSession", true);
        setField(activity, "startupSelection", 4);
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        action.invoke(activity, GlassesInputAction.BACK, 1000L);
        ((java.util.concurrent.ExecutorService) org.robolectric.util.ReflectionHelpers.getField(activity, "answerPersistExecutor"))
                .submit(() -> {}).get(5, TimeUnit.SECONDS);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        layoutAnswersAndWaitForReceipt();
        assertFalse("previous answers must reopen before completion gestures", answers.load().closed);
        action.invoke(activity, GlassesInputAction.BACK, 2000L);
        action.invoke(activity, GlassesInputAction.BACK, 2500L);
        java.util.Properties state = new java.util.Properties();
        try (java.io.InputStream stream = new java.io.FileInputStream(record)) { state.load(stream); }
        assertEquals("CAPTURE", state.getProperty("phase"));
        assertTrue(answers.load().closed);
        assertEquals(0, server.getRequestCount());
    }

    @Test public void rejectedResumeKeepsChooserAndDoesNotCloseTheCurrentRecord() throws Exception {
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test", "test", "test"));
        controller.configureForLocalStart("http://old-server.test", "", 180);
        controller.startLocalSession(false);
        awaitSerial();
        String oldId = controller.savedCaptures().get(0).id;
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test", "test", "test"));
        controller.configureForLocalStart(server.url("/").toString(), "", 180);
        controller.startLocalSession(false);
        awaitSerial();
        String currentId = controller.savedCaptures().stream().filter(saved -> !saved.id.equals(oldId)).findFirst().get().id;
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test", "test", "test"));
        controller.configureForLocalStart(server.url("/").toString(), "", 180);
        awaitSerial();
        setField(activity, "controller", controller);
        setField(activity, "choosingSession", true);
        setField(activity, "startupCaptures", controller.savedCaptures().stream()
                .filter(saved -> saved.id.equals(oldId)).collect(java.util.stream.Collectors.toList()));
        Shadows.shadowOf(activity.getApplication()).grantPermissions(android.Manifest.permission.CAMERA);
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        action.invoke(activity, GlassesInputAction.BACK, 1000L);
        awaitSerial();
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        Field choosing = DocScanGlassActivity.class.getDeclaredField("choosingSession");
        choosing.setAccessible(true);
        assertTrue(choosing.getBoolean(activity));
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, 2000L); // the notice gives way to the list
        setField(activity, "startupSelection", 1); // "back to the list" follows the one saved capture
        action.invoke(activity, GlassesInputAction.BACK, 2500L);
        setField(activity, "startupSelection", 0);
        action.invoke(activity, GlassesInputAction.SWIPE_BACK, 2800L); // the last choice ends the app
        action.invoke(activity, GlassesInputAction.BACK, 3000L);
        java.util.Properties saved = new java.util.Properties();
        try (java.io.InputStream stream = new java.io.FileInputStream(new File(activity.getFilesDir(),
                "local-scans/" + currentId + "/state.properties"))) { saved.load(stream); }
        assertEquals("CAPTURE", saved.getProperty("phase"));
        assertEquals(0, server.getRequestCount());
    }

    private void awaitControllerBarrier() throws Exception {
        // This queues after any Intent configuration, then publishes a diagnostic.
        controller.restoreGlassesViewAfterMenuExit();
        updates.awaitDiagnostic("Restored DocScan glasses view after system-menu exit");
    }

    @Test public void playbackMutePreservesMicrophoneAndDisablesTouchSounds() throws Exception {
        android.media.AudioManager audio = (android.media.AudioManager)activity.getSystemService(Context.AUDIO_SERVICE);
        java.lang.reflect.Method mute = DocScanGlassActivity.class.getDeclaredMethod("muteOutput");
        mute.setAccessible(true);
        for (boolean microphoneMuted : new boolean[]{false, true}) {
            audio.setMicrophoneMute(microphoneMuted);
            audio.setStreamVolume(android.media.AudioManager.STREAM_MUSIC, 2, 0);
            audio.setStreamVolume(android.media.AudioManager.STREAM_SYSTEM, 2, 0);
            mute.invoke(activity);
            assertEquals(0, audio.getStreamVolume(android.media.AudioManager.STREAM_MUSIC));
            assertEquals(0, audio.getStreamVolume(android.media.AudioManager.STREAM_SYSTEM));
            assertEquals(microphoneMuted, audio.isMicrophoneMute());
        }
        assertEquals(0, android.provider.Settings.System.getInt(activity.getContentResolver(),
                android.provider.Settings.System.SOUND_EFFECTS_ENABLED, -1));
    }

    @Test public void newRunInvalidatesThePreviousNotificationGeneration() throws Exception {
        java.lang.reflect.Method begin = DocScanGlassActivity.class.getDeclaredMethod("beginPowerGeneration");
        begin.setAccessible(true);
        java.lang.reflect.Method accept = DocScanGlassActivity.class.getDeclaredMethod("acceptsWake", Intent.class);
        accept.setAccessible(true);
        begin.invoke(activity);
        long generation = activity.getPreferences(Context.MODE_PRIVATE).getLong("power_generation", -1);
        assertEquals("the resident service must read the same counter as the Activity", generation,
                PowerState.forContext(activity).load().generation);
        setField(activity, "powerSession", 7L);
        setField(activity, "powerPhase", "analyzing");
        Intent wake = new Intent().putExtra("wake_session_id", 7).putExtra("wake_generation", generation);
        assertTrue((boolean)accept.invoke(activity, wake));
        begin.invoke(activity);
        assertEquals(generation + 1, activity.getPreferences(Context.MODE_PRIVATE).getLong("power_generation", -1));
        assertFalse((boolean)accept.invoke(activity, wake));
    }

    @Test public void aConfirmedWearEntryDiscardsAllPreviousAnswerWakeAndCredentialExtras() throws Exception {
        PowerState store = PowerState.forContext(activity);
        long generation = store.begin(0).generation;
        store.publish(generation, 0, "chooser", "wake");
        PowerState.Snapshot entry = store.wear(true, -1);
        activity.setIntent(new Intent().putExtra("wake_session_id", 7).putExtra("answer_revision", 1L));
        activity.onNewIntent(new Intent().putExtra("chooser", true).putExtra("wear_origin", true)
                .putExtra("wear_generation", entry.generation).putExtra("wake_session_id", 7)
                .putExtra("wake_generation", generation).putExtra("answer_revision", 2L).putExtra("key", "test-key"));
        assertTrue(activity.getIntent().getBooleanExtra("chooser", false));
        assertFalse(activity.getIntent().hasExtra("wake_session_id"));
        assertFalse(activity.getIntent().hasExtra("wake_generation"));
        assertFalse(activity.getIntent().hasExtra("answer_revision"));
        assertFalse(activity.getIntent().hasExtra("key"));
    }

    @Test public void aStaleWearRequestCannotReplaceTheCurrentIntentOrGeneration() throws Exception {
        PowerState store = PowerState.forContext(activity);
        long generation = store.begin(0).generation;
        Intent current = new Intent().putExtra("retained", "current");
        activity.setIntent(current);
        activity.onNewIntent(new Intent().putExtra("chooser", true).putExtra("wear_origin", true)
                .putExtra("wear_generation", generation - 1));
        assertSame(current, activity.getIntent());
        assertEquals(generation, store.load().generation);
    }

    @Test public void aServiceWearGenerationRejectsAnOldAnswerWakeBeforeTheFreshChooserIntentArrives() throws Exception {
        java.lang.reflect.Method begin = DocScanGlassActivity.class.getDeclaredMethod("beginPowerGeneration");
        begin.setAccessible(true); begin.invoke(activity);
        PowerState store = PowerState.forContext(activity);
        long generation = store.load().generation;
        store.publish(generation, 7, "analyzing", "sleep");
        setField(activity, "powerSession", 7L);
        setField(activity, "powerPhase", "analyzing");
        java.lang.reflect.Method accept = DocScanGlassActivity.class.getDeclaredMethod("acceptsWake", Intent.class);
        accept.setAccessible(true);
        Intent old = new Intent().putExtra("wake_session_id", 7).putExtra("wake_generation", generation);
        assertTrue((boolean)accept.invoke(activity, old));
        store.wear(false, -1);
        assertFalse("the shared generation changes before the Activity receives the chooser intent",
                (boolean)accept.invoke(activity, old));
    }

    @Test public void resumingAfterASupersededWearGenerationCannotHoldOrWakeTheOldDisplay() throws Exception {
        java.lang.reflect.Method begin = DocScanGlassActivity.class.getDeclaredMethod("beginPowerGeneration");
        begin.setAccessible(true); begin.invoke(activity);
        PowerState store = PowerState.forContext(activity);
        long generation = store.load().generation;
        store.publish(generation, 7, "analyzing", "wake");
        setField(activity, "powerSession", 7L);
        setField(activity, "powerPhase", "analyzing");
        setField(activity, "awaitingAnswers", true);
        setField(activity, "idleAsleep", false);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        activity.onResume();
        assertTrue("the current generation still holds its display before idle sleep",
                (activity.getWindow().getAttributes().flags & keepOn) != 0);
        long wearGeneration = store.wear(false, -1).generation;
        activity.getWindow().clearFlags(keepOn);
        activity.setTurnScreenOn(false);
        activity.onNewIntent(new Intent().putExtra("wake_session_id", 7)
                .putExtra("wake_generation", generation).putExtra("answer_revision", 1L));
        assertFalse(Shadows.shadowOf(activity).getTurnScreenOn());
        activity.onResume();
        assertEquals("onResume cannot restore the service-superseded display hold", 0,
                activity.getWindow().getAttributes().flags & keepOn);
        assertFalse(Shadows.shadowOf(activity).getTurnScreenOn());
        assertEquals("a stale resume must not allocate a generation", wearGeneration, store.load().generation);
        assertEquals(0, server.getRequestCount());
    }

    @Test public void startupDistinguishesMixedEnglishFromLegacyListening() throws Exception {
        java.lang.reflect.Method options = DocScanGlassActivity.class.getDeclaredMethod("startupOptions");
        options.setAccessible(true);
        @SuppressWarnings("unchecked") List<String> modes = (List<String>)options.invoke(activity);
        assertEquals(List.of("通常の読取", "合同英語（読解＋音声）", "リスニング"), modes.subList(0, 3));
    }

    @Test public void resumingKeepsActiveViewsAwakeButNeverKeepsWaitingOrCompletedSessionsAwake() throws Exception {
        android.provider.Settings.System.putInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, 0);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        activity.onResume();
        assertTrue("an active chooser, capture or reader must hold its display",
                (activity.getWindow().getAttributes().flags & keepOn) != 0);
        setField(activity, "awaitingAnswers", true);
        setField(activity, "idleAsleep", true);
        activity.onResume();
        assertTrue("a display the system turned back on is shown again, not left dark behind a stale flag",
                (activity.getWindow().getAttributes().flags & keepOn) != 0);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(5_000));
        assertEquals("and a waiting session lets it go again after five seconds without input", 0,
                activity.getWindow().getAttributes().flags & keepOn);
        setField(activity, "awaitingAnswers", false);
        setField(activity, "idleAsleep", false);
        setField(activity, "writingDone", true);
        activity.getWindow().addFlags(keepOn);
        activity.onResume();
        assertEquals(0, activity.getWindow().getAttributes().flags & keepOn);
        setField(activity, "writingDone", false);
        setField(activity, "sessionClosed", true);
        activity.getWindow().addFlags(keepOn);
        activity.onResume();
        assertEquals(0, activity.getWindow().getAttributes().flags & keepOn);
        assertEquals(0, android.provider.Settings.System.getInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, -1));
    }

    /**
     * Glasses, 2026-11-13, events written to the touchpad's own input device: a touch on a sleeping display is
     * consumed by the wake and never reaches the app; the Activity is only restarted and resumed. The app kept
     * believing the display was off, so the next tap was spent as "turn it back on": the display-off worked once.
     */
    @Test public void aSystemWakeWithoutAGestureIsNoticedAndTheNextTapTurnsTheDisplayOffEveryTime() throws Exception {
        setField(activity, "choosingSession", true);
        activity.onResume();
        java.lang.reflect.Method choices = DocScanGlassActivity.class.getDeclaredMethod("showStartupChoices");
        choices.setAccessible(true);
        choices.invoke(activity);
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        Field asleep = DocScanGlassActivity.class.getDeclaredField("idleAsleep");
        asleep.setAccessible(true);
        Field hudField = DocScanGlassActivity.class.getDeclaredField("hud");
        hudField.setAccessible(true);
        HudView hud = (HudView)hudField.get(activity);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        for (int cycle = 1; cycle <= 3; cycle++) {
            action.invoke(activity, GlassesInputAction.SHORT_TAP, cycle * 10_000L);
            assertTrue("tap " + cycle + " turns the display off", asleep.getBoolean(activity));
            assertTrue("and nothing is drawn", hud.isBlank());
            assertEquals(0, activity.getWindow().getAttributes().flags & keepOn);
            activity.onResume(); // the system woke the display; no gesture arrives
            assertFalse("wake " + cycle + " is noticed without a gesture", asleep.getBoolean(activity));
            assertFalse("and the screen is back", hud.isBlank());
            assertTrue((activity.getWindow().getAttributes().flags & keepOn) != 0);
        }
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(10_000));
        assertTrue("ten seconds without input on the chooser", asleep.getBoolean(activity));
        assertTrue("off as the wearer sees it, whether or not the system's sleep follows", hud.isBlank());
        activity.onResume();
        action.invoke(activity, GlassesInputAction.SHORT_TAP, 50_000L);
        assertTrue("the tap after an unseen wake turns it off", asleep.getBoolean(activity));
    }

    /**
     * Route check on the glasses, 2026-11-13: after the writing was ended the display is off, and the touch that wakes
     * a sleeping display never reaches the app, so "two double taps within three seconds" took three. The wake itself
     * counts as the first.
     */
    @Test public void afterTheWritingIsDoneTheWakingTouchCountsAsTheFirstOfTheTwoThatLeave() throws Exception {
        setField(activity, "writingDone", true);
        Field closed = DocScanGlassActivity.class.getDeclaredField("sessionClosed");
        closed.setAccessible(true);
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        activity.onResume(); // the display was woken by a touch the app never sees
        activity.onWindowFocusChanged(true); // on the glasses the focus returns after the resume and used to disarm it
        assertFalse(closed.getBoolean(activity));
        action.invoke(activity, GlassesInputAction.BACK, android.os.SystemClock.elapsedRealtime() + 800);
        assertTrue("one delivered double tap after the wake leaves", closed.getBoolean(activity));
    }

    /** Waiting for the answers: a tap turns the display off as on every screen, and the gesture that brings it back does nothing else. */
    @Test public void whileWaitingForAnswersATapTurnsTheDisplayOffAndTheWakingGestureDoesNothingElse() throws Exception {
        setField(activity, "awaitingAnswers", true);
        activity.onResume();
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        Field asleep = DocScanGlassActivity.class.getDeclaredField("idleAsleep");
        asleep.setAccessible(true);
        RelayState before = controller.getState();
        action.invoke(activity, GlassesInputAction.SHORT_TAP, 1_000L);
        assertTrue("a tap turns the display off while waiting", asleep.getBoolean(activity));
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, 2_000L);
        assertFalse("any gesture brings it back", asleep.getBoolean(activity));
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, 3_000L);
        assertEquals("a swipe while waiting never reaches the capture controller", before, controller.getState());
        assertFalse(controller.hasLocalSession());
    }

    /**
     * Worn, 2026-11-16 (register 1-16): a tap while a page was being taken only booked the pause. The display stayed
     * on for up to 13 s, the wearer tapped again, and those taps were read as the double tap that ends the capture.
     */
    @Test public void aTapDuringCaptureClearsTheDisplayInItsOwnTurnAndADoubleTapBehindItOnlyBringsItBack() throws Exception {
        startLocalCapture();
        assertEquals("a page is about to be taken", RelayState.AIMING, controller.getState());
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);

        action.invoke(activity, GlassesInputAction.SHORT_TAP, 1_000L);
        assertTrue("nothing is drawn from the turn of the tap on", hud.isBlank());
        awaitSerial();
        activity.onUpdate(controller.getState(), List.of("", "", ""), "the controller reports during the pause");
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        assertTrue("what the controller reports meanwhile does not bring the display back", hud.isBlank());
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, 1_500L);
        assertTrue("nor does a swipe", hud.isBlank());

        action.invoke(activity, GlassesInputAction.BACK, 2_000L);
        assertFalse("a double tap behind the cleared display brings it back", hud.isBlank());
        awaitSerial();
        assertFalse("and is not the end of the capture",
                (Boolean) org.robolectric.util.ReflectionHelpers.getField(controller, "finishCaptureRequested"));
        assertFalse(controller.isCapturePaused());

        action.invoke(activity, GlassesInputAction.BACK, 4_000L);
        awaitSerial();
        assertTrue("with the capture in view a double tap ends it as before",
                (Boolean) org.robolectric.util.ReflectionHelpers.getField(controller, "finishCaptureRequested"));
    }

    @Test public void aFailureBehindAClearedDisplayIsShown() throws Exception {
        startLocalCapture();
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        action.invoke(activity, GlassesInputAction.SHORT_TAP, 1_000L);
        awaitSerial();
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, 1_200L); // ignored; the waiting screen's idle clock is running
        assertTrue(hud.isBlank());

        controller.onPhotoError("camera lost", null);
        awaitSerial();
        activity.onUpdate(RelayState.ERROR, List.of("エラー", "", ""), "the controller ended the pause itself");
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        assertFalse("the display follows the controller out of the pause", hud.isBlank());
    }

    /** An ordinary written session of the real controller on a surface that reviews on the glasses; a page is in view. */
    private void startLocalCapture() throws Exception {
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        setField(activity, "controller", controller);
        controller.configureForLocalStart(server.url("/").toString(), "", 180);
        controller.startLocalSession(false);
        awaitSerial();
    }

    /**
     * Real use, 2026-11-13: the chooser appeared when the glasses were put on and was gone five seconds later, before
     * its six lines could be read and one chosen; the next double tap then only brought the display back. The first
     * screen stayed for thirty seconds from then. Worn on 2026-11-17 the operator set it to ten. Waiting screens
     * keep their five.
     */
    @Test public void theChooserStaysLongEnoughToBeReadAndChosenFrom() throws Exception {
        android.provider.Settings.System.putInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, 0);
        setField(activity, "choosingSession", true);
        activity.onResume();
        java.lang.reflect.Method choices = DocScanGlassActivity.class.getDeclaredMethod("showStartupChoices");
        choices.setAccessible(true);
        choices.invoke(activity);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(5_000));
        assertTrue("five seconds is not enough to read six lines and choose", (activity.getWindow().getAttributes().flags & keepOn) != 0);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(4_999));
        assertTrue((activity.getWindow().getAttributes().flags & keepOn) != 0);
        activity.onUpdate(RelayState.READY, List.of("network update"), "background status");
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(1));
        assertEquals("background updates must not extend chooser inactivity", 0,
                activity.getWindow().getAttributes().flags & keepOn);
        assertEquals(0, android.provider.Settings.System.getInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, -1));
    }

    @Test public void aNewWearGenerationInvalidatesAnAlreadyQueuedIdleTimer() throws Exception {
        android.provider.Settings.System.putInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, 0);
        setField(activity, "choosingSession", true);
        java.lang.reflect.Method choices = DocScanGlassActivity.class.getDeclaredMethod("showStartupChoices");
        choices.setAccessible(true);
        choices.invoke(activity);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(4_999));
        PowerState store = PowerState.forContext(activity);
        long nextGeneration = store.wear(false, -1).generation;

        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(1));

        assertTrue("the old Activity's idle timer cannot release the new wear entry's display",
                (activity.getWindow().getAttributes().flags
                        & android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) != 0);
        assertEquals(nextGeneration, store.load().generation);
        assertEquals("wake", store.load().display);
        assertEquals(0, android.provider.Settings.System.getInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, -1));
    }

    @Test public void aQueuedOldCaptureCallbackCannotReacquireTheNewWearGenerationsDisplay() throws Exception {
        activity.onAutoCaptureChanged(true);
        PowerState.forContext(activity).wear(false, -1);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        activity.getWindow().clearFlags(keepOn);

        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();

        assertEquals("a callback from the superseded Activity cannot hold the display", 0,
                activity.getWindow().getAttributes().flags & keepOn);
    }

    @Test public void onlyAnAcceptedWearEntryExplicitlyWakesAnAsleepChooser() throws Exception {
        android.os.PowerManager power = activity.getSystemService(android.os.PowerManager.class);
        Shadows.shadowOf(power).setIsInteractive(false);
        org.robolectric.shadows.ShadowPowerManager.clearWakeLocks();
        PowerState.Snapshot entry = PowerState.forContext(activity).wear(false, -1);
        Intent wear = new Intent().putExtra("chooser", true).putExtra("wear_origin", true)
                .putExtra("wear_generation", entry.generation);

        activity.onNewIntent(wear);

        android.os.PowerManager.WakeLock wake = org.robolectric.shadows.ShadowPowerManager.getLatestWakeLock();
        assertNotNull("KEEP_SCREEN_ON alone cannot light a noninteractive display on confirmed wear", wake);
        assertEquals("docscan:answer-display", Shadows.shadowOf(wake).getTag());
        assertFalse("the bounded wake request never leaves a CPU/display lock held", wake.isHeld());
    }

    @Test public void staleWearAndOrdinaryChooserRefreshCannotWakeTheDisplay() throws Exception {
        android.os.PowerManager power = activity.getSystemService(android.os.PowerManager.class);
        Shadows.shadowOf(power).setIsInteractive(false);
        org.robolectric.shadows.ShadowPowerManager.clearWakeLocks();
        PowerState.Snapshot entry = PowerState.forContext(activity).wear(false, -1);
        activity.onNewIntent(new Intent().putExtra("chooser", true).putExtra("wear_origin", true)
                .putExtra("wear_generation", entry.generation - 1));
        setField(activity, "powerGeneration", entry.generation);
        java.lang.reflect.Method choices = DocScanGlassActivity.class.getDeclaredMethod("showStartupChoices");
        choices.setAccessible(true);
        choices.invoke(activity);
        assertNull(org.robolectric.shadows.ShadowPowerManager.getLatestWakeLock());
    }

    @Test public void captureReviewAndWrittenAnswersKeepTheirDisplayBeyondFiveSeconds() throws Exception {
        android.provider.Settings.System.putInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, 0);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        java.lang.reflect.Method idle = DocScanGlassActivity.class.getDeclaredMethod("enterIdleDisplay", String.class, long.class);
        idle.setAccessible(true);
        for (RelayState state : List.of(RelayState.AIMING, RelayState.STABILIZING,
                RelayState.CAPTURING, RelayState.CAPTURE_REVIEW)) {
            idle.invoke(activity, "waiting", 0L);
            setField(controller, "state", state);
            activity.onUpdate(state, List.of("capture"), "test capture state");
            Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(6));
            assertTrue(state.name(), (activity.getWindow().getAttributes().flags & keepOn) != 0);
        }
        setField(controller, "state", RelayState.READY);
        AnswerStore store = new AnswerStore(activity.getFilesDir());
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1,
                List.of(AnswerItem.ready("g1", "読解", "q1", "問1", "保存済み答案")));
        store.start(bundle);
        setField(activity, "answerStore", store);
        java.lang.reflect.Method open = DocScanGlassActivity.class.getDeclaredMethod("openAnswers", AnswerBundle.class, String.class, int.class);
        open.setAccessible(true);
        open.invoke(activity, bundle, "q1", 0);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(30));
        assertTrue((activity.getWindow().getAttributes().flags & keepOn) != 0);
        assertEquals("reading", PowerState.forContext(activity).load().phase);
        assertEquals(0, android.provider.Settings.System.getInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, -1));
        assertEquals(0, server.getRequestCount());
    }

    private void openReaderWith(AnswerItem item) throws Exception {
        android.provider.Settings.System.putInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, 0);
        AnswerStore store = new AnswerStore(activity.getFilesDir());
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1, List.of(item));
        store.start(bundle);
        setField(activity, "answerStore", store);
        java.lang.reflect.Method open = DocScanGlassActivity.class.getDeclaredMethod("openAnswers", AnswerBundle.class, String.class, int.class);
        open.setAccessible(true);
        open.invoke(activity, bundle, "q1", 0);
    }

    /**
     * Worn, 2026-11-17: every answer of a booklet came back as "cannot be read" (nine items, no answer text) and
     * the reader went dark five seconds after each touch. Reasons alone did not count as something to read.
     */
    @Test public void answersThatAreOnlyReasonsHoldTheDisplayLikeAnyAnswer() throws Exception {
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        openReaderWith(new AnswerItem("g1", "全体", "q1", "問一", "", AnswerItem.Status.NEEDS_INPUT, "不鮮明で判読できません"));
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(30));
        assertTrue("the reason an item has no answer is read like an answer", (activity.getWindow().getAttributes().flags & keepOn) != 0);
        assertEquals("reading", PowerState.forContext(activity).load().phase);
    }

    @Test public void answersStillBeingMadeDoNotHoldTheDisplay() throws Exception {
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        openReaderWith(new AnswerItem("g1", "全体", "q1", "問一", "", AnswerItem.Status.PENDING, "未解答"));
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(6));
        assertEquals("nothing final to read yet: a waiting screen", 0, activity.getWindow().getAttributes().flags & keepOn);
        assertEquals("waiting", PowerState.forContext(activity).load().phase);
    }

    @Test public void aChooserSwipeRestartsTheIdleClockAndAStoppedCameraCanSleep() throws Exception {
        setField(activity, "choosingSession", true);
        activity.onResume();
        java.lang.reflect.Method choices = DocScanGlassActivity.class.getDeclaredMethod("showStartupChoices");
        choices.setAccessible(true);
        choices.invoke(activity);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(9));
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, android.os.SystemClock.elapsedRealtime());
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(9));
        assertTrue((activity.getWindow().getAttributes().flags & keepOn) != 0);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(1));
        assertEquals(0, activity.getWindow().getAttributes().flags & keepOn);

        setField(activity, "choosingSession", false);
        activity.onAutoCaptureChanged(true);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(10));
        assertTrue("the camera's active preview must stay visible", (activity.getWindow().getAttributes().flags & keepOn) != 0);
        activity.onAutoCaptureChanged(false);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(5));
        assertEquals("the camera's idle pause is an ordinary waiting screen", 0,
                activity.getWindow().getAttributes().flags & keepOn);
    }

    // --- the chooser's line on the answer routes ---------------------------------------------------------------

    private static final String ROUTES_PASSED = "{\"name\":\"codex-cli\",\"ok\":true,\"code\":\"ok\",\"real\":true,\"seconds\":5.1,"
            + "\"usage\":{\"used_percent\":3.0,\"window_minutes\":10080,\"resets_at\":1795429113}},"
            + "{\"name\":\"chatgpt-work\",\"ok\":true,\"code\":\"ok\",\"real\":false,\"seconds\":0.2},"
            + "{\"name\":\"chatgpt-web\",\"ok\":true,\"code\":\"ok\",\"real\":false,\"seconds\":0.3}";
    private static final String CODEX_FAILED = "{\"name\":\"codex-cli\",\"ok\":false,\"code\":\"rate_limited\",\"real\":true,\"seconds\":4.0},"
            + "{\"name\":\"chatgpt-work\",\"ok\":true,\"code\":\"ok\",\"real\":false,\"seconds\":0.2},"
            + "{\"name\":\"chatgpt-web\",\"ok\":true,\"code\":\"ok\",\"real\":false,\"seconds\":0.3}";

    /** A check of the routes as the server keeps it, made this many seconds ago by the clock the app reads. */
    private static String routesChecked(long secondsAgo, String routes) {
        return "{\"checked_at\":" + (System.currentTimeMillis() / 1000 - secondsAgo) + ",\"ok\":true,\"routes\":[" + routes + "]}";
    }

    /** What the server keeps in its settings and what a check made now finds; {@code held} keeps every reply back. */
    private void serveRoutes(String kept, String checkedNow, java.util.concurrent.CountDownLatch held) {
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                if (held != null) held.await(10, TimeUnit.SECONDS);
                if ("GET".equals(request.getMethod()) && "/v1/settings".equals(request.getPath())) {
                    return new MockResponse().setBody("{\"hud\":{\"max_lines\":3},\"route_check\":" + kept + "}");
                }
                if ("POST".equals(request.getMethod()) && "/v1/route-check".equals(request.getPath())) {
                    return new MockResponse().setBody(checkedNow);
                }
                return new MockResponse().setResponseCode(404).setBody("unexpected test request");
            }
        });
    }

    /** The chooser as onCreate shows it, run until the controller has handed over the client it was configured with. */
    private void showChooser() throws Exception {
        setField(activity, "choosingSession", true);
        activity.onResume();
        java.lang.reflect.Method choices = DocScanGlassActivity.class.getDeclaredMethod("showStartupChoices");
        choices.setAccessible(true);
        choices.invoke(activity);
        settleChooser();
    }

    private void settleChooser() throws Exception {
        awaitSerial();
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
    }

    private void gesture(GlassesInputAction action, long at) throws Exception {
        java.lang.reflect.Method onAction = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        onAction.setAccessible(true);
        onAction.invoke(activity, action, at);
    }

    /** The routes' line as the HUD holds it: null when what is shown is not the chooser's list. */
    private String routesLine() {
        return org.robolectric.util.ReflectionHelpers.getField(hud, "route");
    }

    /** Lets the reply that is on its way arrive and be handled on the main thread, without moving the clock. */
    private void awaitRoutesReply() throws Exception {
        for (int attempt = 0; attempt < 1000
                && (boolean) org.robolectric.util.ReflectionHelpers.getField(activity, "routeInFlight"); attempt++) {
            Thread.sleep(10);
            Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        }
        assertFalse("the reply was handled", (boolean) org.robolectric.util.ReflectionHelpers.getField(activity, "routeInFlight"));
    }

    @Test public void theChooserShowsTheRoutesFromOneReadingOfAFreshResult() throws Exception {
        java.util.concurrent.CountDownLatch held = new java.util.concurrent.CountDownLatch(1);
        serveRoutes(routesChecked(60, ROUTES_PASSED), "{}", held);

        showChooser();

        assertEquals("while the reply is on its way", "経路 …", routesLine());
        held.countDown();
        awaitRoutesReply();
        assertEquals("経路 ○ 使用3%", routesLine());
        RecordedRequest read = takeRequest(server);
        assertEquals("GET", read.getMethod());
        assertEquals("/v1/settings", read.getPath());
        assertEquals("Bearer original-test-key", read.getHeader("Authorization"));
        gesture(GlassesInputAction.SWIPE_FORWARD, 1_000L); // the marker moves and the list is drawn again: the same showing
        settleChooser();
        assertEquals("the line stays with the list", "経路 ○ 使用3%", routesLine());
        assertEquals("a fresh result is read once and nothing is checked", 1, server.getRequestCount());
    }

    @Test public void aResultOverThirtyMinutesOldMakesExactlyOneCheckNow() throws Exception {
        serveRoutes(routesChecked(31 * 60, ROUTES_PASSED), routesChecked(0, CODEX_FAILED), null);

        showChooser();
        awaitRoutesReply();

        assertEquals("what the check made now found", "経路 △ (Codex×)", routesLine());
        assertEquals("/v1/settings", takeRequest(server).getPath());
        RecordedRequest check = takeRequest(server);
        assertEquals("POST", check.getMethod());
        assertEquals("/v1/route-check", check.getPath());
        assertEquals("Bearer original-test-key", check.getHeader("Authorization"));
        gesture(GlassesInputAction.SWIPE_FORWARD, 1_000L);
        gesture(GlassesInputAction.SWIPE_BACK, 2_000L);
        settleChooser();
        assertEquals("one reading and one check for this showing, however the list is redrawn", 2, server.getRequestCount());
    }

    @Test public void aServerThatKeepsNoResultMakesExactlyOneCheckNow() throws Exception {
        serveRoutes("null", routesChecked(0, ROUTES_PASSED), null);

        showChooser();
        awaitRoutesReply();

        assertEquals("経路 ○ 使用3%", routesLine());
        assertEquals("GET", takeRequest(server).getMethod());
        assertEquals("POST", takeRequest(server).getMethod());
        assertEquals(2, server.getRequestCount());
    }

    @Test public void aServerThatCannotBeReachedIsSaidInTheFixedWords() throws Exception {
        server.shutdown();

        showChooser();
        awaitRoutesReply();

        assertEquals("経路 ? サーバーに届きません", routesLine());
    }

    @Test public void eachShowingOfTheChooserAsksOnceAndNeverWhileAReplyIsOnItsWay() throws Exception {
        java.util.concurrent.CountDownLatch held = new java.util.concurrent.CountDownLatch(1);
        serveRoutes(routesChecked(60, ROUTES_PASSED), "{}", held);
        showChooser();
        takeRequest(server);                               // the reading has reached the server and is held back there
        gesture(GlassesInputAction.SHORT_TAP, 1_000L);     // the display is cleared: this showing is over
        gesture(GlassesInputAction.SWIPE_FORWARD, 2_000L); // and brought back while the first reply is still on its way
        settleChooser();
        assertFalse(hud.isBlank());
        assertEquals("the returning list says a reply is still awaited", "経路 …", routesLine());

        held.countDown();
        awaitRoutesReply();
        assertEquals("経路 ○ 使用3%", routesLine());
        gesture(GlassesInputAction.SWIPE_FORWARD, 3_000L);
        settleChooser();
        assertEquals("no second question while one was on its way, nor for a redrawn list", 1, server.getRequestCount());

        gesture(GlassesInputAction.SHORT_TAP, 4_000L);
        gesture(GlassesInputAction.SWIPE_FORWARD, 5_000L); // the next showing
        settleChooser();
        awaitRoutesReply();
        assertEquals("the chooser shown again reads the result again, once", 2, server.getRequestCount());
        assertEquals("経路 ○ 使用3%", routesLine());
    }

    /** A touch on the sleeping display never reaches the app: it is only resumed, and that is a showing too. */
    @Test public void aChooserTheSystemWokeWithoutAGestureAsksAgain() throws Exception {
        serveRoutes(routesChecked(60, ROUTES_PASSED), "{}", null);
        showChooser();
        awaitRoutesReply();
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(10));
        assertTrue("ten seconds without input", hud.isBlank());
        serveRoutes(routesChecked(60, CODEX_FAILED), "{}", null);

        activity.onResume();
        settleChooser();
        awaitRoutesReply();

        assertFalse(hud.isBlank());
        assertEquals("what the server keeps now, not what was shown before the sleep", "経路 △ (Codex×)", routesLine());
        assertEquals(2, server.getRequestCount());
    }

    @Test public void aReplyAfterTheChooserWasLeftForACaptureChangesNothing() throws Exception {
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        setField(activity, "controller", controller);
        controller.configureForLocalStart(server.url("/").toString(), "", 180);
        Shadows.shadowOf(activity.getApplication()).grantPermissions(android.Manifest.permission.CAMERA);
        java.util.concurrent.CountDownLatch held = new java.util.concurrent.CountDownLatch(1);
        serveRoutes(routesChecked(60, ROUTES_PASSED), "{}", held);
        showChooser();
        assertEquals("経路 …", routesLine());

        gesture(GlassesInputAction.BACK, 1_000L); // the double tap starts the ordinary reading
        settleChooser();
        assertFalse((boolean) org.robolectric.util.ReflectionHelpers.getField(activity, "choosingSession"));
        assertEquals("a page is about to be taken", RelayState.AIMING, controller.getState());
        int flags = activity.getWindow().getAttributes().flags;
        PowerState.Snapshot power = PowerState.forContext(activity).load();
        held.countDown();
        awaitRoutesReply();

        // This test's capture surface draws nothing, so the HUD still holds the chooser's list and would take a line.
        assertEquals("the late reply is dropped", "経路 …", routesLine());
        assertEquals(RelayState.AIMING, controller.getState());
        assertEquals(flags, activity.getWindow().getAttributes().flags);
        assertEquals(power.sequence, PowerState.forContext(activity).load().sequence);
        assertEquals("capturing", PowerState.forContext(activity).load().phase);
        assertEquals("and nothing more was asked of the server", 1, server.getRequestCount());
    }

    @Test public void aReplyBehindAClearedDisplayLeavesItCleared() throws Exception {
        java.util.concurrent.CountDownLatch held = new java.util.concurrent.CountDownLatch(1);
        serveRoutes(routesChecked(60, ROUTES_PASSED), "{}", held);
        showChooser();
        takeRequest(server); // the reading is on its way when the wearer clears the display
        gesture(GlassesInputAction.SHORT_TAP, 1_000L);
        assertTrue("the tap clears the display", hud.isBlank());
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        assertEquals(0, activity.getWindow().getAttributes().flags & keepOn);
        long sequence = PowerState.forContext(activity).load().sequence;

        held.countDown();
        awaitRoutesReply();

        assertTrue("nothing is drawn when the reply arrives", hud.isBlank());
        assertTrue((boolean) org.robolectric.util.ReflectionHelpers.getField(activity, "idleAsleep"));
        assertEquals("the display is not held on again", 0, activity.getWindow().getAttributes().flags & keepOn);
        assertEquals("sleep", PowerState.forContext(activity).load().display);
        assertEquals("and the phone is asked for nothing new", sequence, PowerState.forContext(activity).load().sequence);
    }

    @Test public void aReplyDoesNotRestartTheChoosersTenSeconds() throws Exception {
        java.util.concurrent.CountDownLatch held = new java.util.concurrent.CountDownLatch(1);
        serveRoutes(routesChecked(60, ROUTES_PASSED), "{}", held);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        showChooser();
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(9_999));
        assertTrue((activity.getWindow().getAttributes().flags & keepOn) != 0);

        held.countDown();
        awaitRoutesReply();
        assertEquals("the reply came in the last millisecond and is shown", "経路 ○ 使用3%", routesLine());

        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(1));
        assertEquals("a reply is not input: the ten seconds end when they would have", 0,
                activity.getWindow().getAttributes().flags & keepOn);
        assertTrue(hud.isBlank());
    }

    @Test public void withoutASavedServerNothingIsAskedAndNoLineIsShown() throws Exception {
        controller.close();
        controller = new DocScanController(activity, new Surface(true), null, updates,
                new ClientIdentity("test-glasses", "intent-test/1", "fake-camera"));
        setField(activity, "controller", controller);
        assertNull("no connection was configured", controller.api());

        showChooser();
        Thread.sleep(200);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();

        assertEquals("the chooser is the list alone", "", routesLine());
        assertEquals(0, server.getRequestCount());
        assertFalse((boolean) org.robolectric.util.ReflectionHelpers.getField(activity, "routeInFlight"));
    }

    @Test public void staleWakeCannotCreateAChooserAfterTheProcessWasStopped() throws Exception {
        activity.getPreferences(Context.MODE_PRIVATE).edit().putLong("power_generation", 3)
                .putLong("power_session", 7).putString("power_phase", "writing_done").commit();
        org.robolectric.android.controller.ActivityController<DocScanGlassActivity> stopped =
                Robolectric.buildActivity(DocScanGlassActivity.class,
                        new Intent().putExtra("wake_session_id", 7).putExtra("wake_generation", 3L)).create();
        try {
            assertTrue("a stale answer wake ends before any capture or chooser UI is created", stopped.get().isFinishing());
            assertNull(org.robolectric.util.ReflectionHelpers.getField(stopped.get(), "camera"));
            assertNull(org.robolectric.util.ReflectionHelpers.getField(stopped.get(), "hud"));
            stopped.start().resume();
            assertFalse(Shadows.shadowOf(stopped.get()).getTurnScreenOn());
            assertEquals(0, stopped.get().getWindow().getAttributes().flags
                    & android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            assertEquals(3, activity.getPreferences(Context.MODE_PRIVATE).getLong("power_generation", -1));
        } finally { stopped.destroy(); }
    }

    @Test @Config(sdk = 28, manifest = Config.NONE)
    public void mixedInterimDoneKeepsTheSessionAndRecordingOpenForTheFinalRevision() throws Exception {
        AnswerStore store = new AnswerStore(activity.getFilesDir());
        org.json.JSONObject json = new org.json.JSONObject(new AnswerBundle("7", "a".repeat(64), 1,
                List.of(AnswerItem.ready("g1", "読解", "q1", "問1", "A"),
                        new AnswerItem("g2", "音声", "q2", "問2", "", AnswerItem.Status.PENDING, "原音待ち"))).toJson())
                .put("analysis_stage", "awaiting_audio").put("available_stage", "reading");
        AnswerBundle bundle = AnswerBundle.fromJson(json.toString());
        store.start(bundle);
        setField(activity, "answerStore", store);
        ListeningRecorder recorder = new ListeningRecorder(activity.getFilesDir(), 7, controller.api(), () -> {});
        setField(activity, "listening", recorder);
        java.lang.reflect.Method open = DocScanGlassActivity.class.getDeclaredMethod("openAnswers", AnswerBundle.class, String.class, int.class);
        open.setAccessible(true);
        open.invoke(activity, bundle, "q1", 0);
        layoutAnswersAndWaitForReceipt();
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        try {
            action.invoke(activity, GlassesInputAction.BACK, 1000L);
            assertFalse("reading completion cannot close a mixed session awaiting audio", store.load().closed);
            assertFalse(org.robolectric.util.ReflectionHelpers.getField(activity, "writingDone"));
            assertSame(recorder, org.robolectric.util.ReflectionHelpers.getField(activity, "listening"));
            assertFalse(org.robolectric.util.ReflectionHelpers.getField(recorder, "closed"));
            assertNull(org.robolectric.util.ReflectionHelpers.getField(activity, "reader"));
            assertEquals("waiting", org.robolectric.util.ReflectionHelpers.getField(activity, "powerPhase"));
            assertEquals("intermediate waiting keeps only the revision actually received", 1,
                    activity.getPreferences(Context.MODE_PRIVATE).getLong("power_ack_revision", -1));
        } finally { recorder.close(); }
    }

    @Test @Config(sdk = 28, manifest = Config.NONE)
    public void aFinalRevisionNotificationFetchesBeyondTheSavedReadingBundle() throws Exception {
        AnswerStore store = new AnswerStore(activity.getFilesDir());
        AnswerBundle old = new AnswerBundle("7", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q1", "問1", "前の答え"),
                new AnswerItem("g1", "第1問", "q2", "問2", "", AnswerItem.Status.PENDING, "原音待ち")));
        AnswerBundle next = old.withAnswer(AnswerItem.ready("g1", "第1問", "q2", "問2", "音声の答え"));
        store.start(old);
        store.save(old, "q2", 0, false);
        setField(activity, "answerStore", store);
        setField(activity, "powerPhase", "reading");
        setField(activity, "powerSession", 7L);
        setField(activity, "powerGeneration", 3L);
        PowerState.forContext(activity).begin(2);
        setField(activity, "answersFetchedForSession", 7L);
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                return new MockResponse().setBody(next.toJson());
            }
        });
        activity.onNewIntent(new Intent().putExtra("wake_session_id", 7)
                .putExtra("wake_generation", 3L).putExtra("answer_revision", 2L));
        RecordedRequest request = server.takeRequest(2, TimeUnit.SECONDS);
        assertNotNull("a saved stage1 must not block fetching a newer final revision", request);
        assertEquals("/v1/exam-sessions/7/answer-bundle", request.getPath());
        for (int attempt = 0; attempt < 100 && store.load().bundle.revision < 2; attempt++) Thread.sleep(10);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        assertEquals(2, store.load().bundle.revision);
        assertEquals("q2", store.load().questionId);
        assertEquals("音声の答え", store.load().bundle.items.get(1).answer);
    }

    @Test @Config(sdk = 28, manifest = Config.NONE)
    public void repeatedRevisionDuringFetchDoesNotStartASecondGetAndOnlyDisplayedSavedAnswersAreAcknowledged() throws Exception {
        AnswerStore store = new AnswerStore(activity.getFilesDir());
        setField(activity, "answerStore", store);
        java.lang.reflect.Method begin = DocScanGlassActivity.class.getDeclaredMethod("beginPowerGeneration");
        begin.setAccessible(true);
        begin.invoke(activity);
        long generation = PowerState.forContext(activity).load().generation;
        PowerState.forContext(activity).publish(generation, 7, "analyzing", "sleep");
        setField(activity, "powerSession", 7L);
        setField(activity, "powerPhase", "analyzing");
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1,
                List.of(AnswerItem.ready("g1", "読解", "q1", "問1", "A")));
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                assertTrue(release.await(5, TimeUnit.SECONDS));
                return new MockResponse().setBody(bundle.toJson());
            }
        });
        Intent notification = new Intent().putExtra("wake_session_id", 7)
                .putExtra("wake_generation", generation).putExtra("answer_revision", 1L);
        try {
            activity.onNewIntent(notification);
            assertNotNull(server.takeRequest(2, TimeUnit.SECONDS));
            activity.onNewIntent(notification);
            assertNull("a repeated notification while the GET is in flight must not issue a second GET",
                    server.takeRequest(100, TimeUnit.MILLISECONDS));
            assertEquals(-1, activity.getPreferences(Context.MODE_PRIVATE).getLong("power_ack_revision", -1));
        } finally { release.countDown(); }
        for (int attempt = 0; attempt < 100 && store.load() == null; attempt++) Thread.sleep(10);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        layoutAnswersAndWaitForReceipt();
        assertEquals("only a saved and visible bundle may acknowledge receipt", 1,
                activity.getPreferences(Context.MODE_PRIVATE).getLong("power_ack_revision", -1));
        long sequence = PowerState.forContext(activity).load().sequence;
        activity.onNewIntent(notification);
        assertEquals(1, server.getRequestCount());
        assertEquals("an already-read notification only retries its state ACK; no display update",
                sequence, PowerState.forContext(activity).load().sequence);
    }

    @Test @Config(sdk = 28, manifest = Config.NONE)
    public void anAlreadyReadNotificationRetriesALostReceiptWithoutFetchingOrLightingAgain() throws Exception {
        AnswerStore store = new AnswerStore(activity.getFilesDir());
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1,
                List.of(AnswerItem.ready("g1", "読解", "q1", "問1", "A")));
        store.start(bundle);
        setField(activity, "answerStore", store);
        java.lang.reflect.Method begin = DocScanGlassActivity.class.getDeclaredMethod("beginPowerGeneration");
        begin.setAccessible(true); begin.invoke(activity);
        java.lang.reflect.Method open = DocScanGlassActivity.class.getDeclaredMethod("openAnswers", AnswerBundle.class, String.class, int.class);
        open.setAccessible(true); open.invoke(activity, bundle, "q1", 0);
        layoutAnswersAndWaitForReceipt();
        long generation = PowerState.forContext(activity).load().generation;
        long sequence = PowerState.forContext(activity).load().sequence;
        server.setDispatcher(new Dispatcher() {
            int calls;
            @Override public MockResponse dispatch(RecordedRequest request) {
                assertEquals("/v1/glasses/state", request.getPath());
                return new MockResponse().setResponseCode(++calls == 1 ? 500 : 200).setBody("{}");
            }
        });
        setField(activity, "deviceId", "test-android-id");
        activity.setTurnScreenOn(false);
        Intent notification = new Intent().putExtra("wake_session_id", 7)
                .putExtra("wake_generation", generation).putExtra("answer_revision", 1L);
        activity.onNewIntent(notification);
        RecordedRequest first = server.takeRequest(2, TimeUnit.SECONDS);
        assertNotNull(first);
        ((java.util.concurrent.ExecutorService)org.robolectric.util.ReflectionHelpers.getField(activity, "stateExecutor"))
                .submit(() -> {}).get(2, TimeUnit.SECONDS);
        activity.onNewIntent(notification);
        RecordedRequest retry = server.takeRequest(2, TimeUnit.SECONDS);
        assertNotNull(retry);
        org.json.JSONObject receipt = new org.json.JSONObject(retry.getBody().readUtf8());
        assertEquals("Bearer original-test-key", retry.getHeader("Authorization"));
        assertEquals(1, receipt.getLong("ack_answer_revision"));
        assertEquals(generation, receipt.getLong("generation"));
        assertEquals(sequence, receipt.getLong("sequence"));
        assertEquals(2, server.getRequestCount());
        assertFalse(Shadows.shadowOf(activity).getTurnScreenOn());
        assertEquals(sequence, PowerState.forContext(activity).load().sequence);
    }

    private void layoutAnswersAndWaitForReceipt() throws Exception {
        AnswerView view = org.robolectric.util.ReflectionHelpers.getField(activity, "answers");
        assertNotNull(view);
        view.layout(0, 0, 480, 640);
        ((java.util.concurrent.ExecutorService) org.robolectric.util.ReflectionHelpers.getField(activity, "answerPersistExecutor"))
                .submit(() -> {}).get(5, TimeUnit.SECONDS);
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
    }

    @Test @Config(sdk = 28, manifest = Config.NONE)
    public void aWearGenerationAlsoCancelsAnOldAnswerGetAlreadyInFlight() throws Exception {
        AnswerStore store = new AnswerStore(activity.getFilesDir());
        setField(activity, "answerStore", store);
        java.lang.reflect.Method begin = DocScanGlassActivity.class.getDeclaredMethod("beginPowerGeneration");
        begin.setAccessible(true); begin.invoke(activity);
        PowerState power = PowerState.forContext(activity);
        long generation = power.load().generation;
        power.publish(generation, 7, "analyzing", "sleep");
        setField(activity, "powerSession", 7L); setField(activity, "powerPhase", "analyzing");
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1,
                List.of(AnswerItem.ready("g1", "読解", "q1", "問1", "A")));
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                return new MockResponse().setBody(bundle.toJson()).setBodyDelay(250, TimeUnit.MILLISECONDS);
            }
        });
        activity.onNewIntent(new Intent().putExtra("wake_session_id", 7)
                .putExtra("wake_generation", generation).putExtra("answer_revision", 1L));
        assertNotNull(server.takeRequest(2, TimeUnit.SECONDS));
        power.wear(false, -1);
        activity.setTurnScreenOn(false);
        for (int attempt = 0; attempt < 200; attempt++) {
            Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
            if ((long)org.robolectric.util.ReflectionHelpers.getField(activity, "answersFetchSession") < 0) break;
            Thread.sleep(10);
        }
        assertNull("an old generation may neither persist nor display a late answer", store.load());
        assertNull(org.robolectric.util.ReflectionHelpers.getField(activity, "reader"));
        assertFalse(Shadows.shadowOf(activity).getTurnScreenOn());
    }

    @Test @Config(sdk = 28, manifest = Config.NONE)
    public void anAllFailedMixedReplyShowsTheReasonAndStillSleepsAtFiveSeconds() throws Exception {
        AnswerStore store = new AnswerStore(activity.getFilesDir());
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1,
                List.of(new AnswerItem("g1", "読解", "q1", "問1", "", AnswerItem.Status.FAILED, "送信結果を確認できません")),
                "reading", "reading");
        store.start(bundle);
        setField(activity, "answerStore", store);
        java.lang.reflect.Method open = DocScanGlassActivity.class.getDeclaredMethod("openAnswers", AnswerBundle.class, String.class, int.class);
        open.setAccessible(true);
        open.invoke(activity, bundle, "q1", 0);
        assertNotNull(org.robolectric.util.ReflectionHelpers.getField(activity, "reader"));
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(5));
        assertEquals(0, activity.getWindow().getAttributes().flags & android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            assertEquals("waiting", org.robolectric.util.ReflectionHelpers.getField(activity, "powerPhase"));
        assertFalse(store.load().closed);
        assertEquals("送信結果を確認できません", store.load().bundle.items.get(0).issue);
    }

    @Test public void mixedReviewSwipeStopsAudioWithoutRetakingOrMovingTheStill() throws Exception {
        setField(activity, "mixedMode", true);
        setField(activity, "listeningDirectory", activity.getFilesDir());
        setField(controller, "state", RelayState.CAPTURE_REVIEW);
        ListeningRecorder recorder = new ListeningRecorder(activity.getFilesDir(), 0, controller.api(), () -> {});
        setField(recorder, "running", true);
        setField(activity, "listening", recorder);
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        try {
            action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, 1_000L);
            assertFalse((boolean)org.robolectric.util.ReflectionHelpers.getField(recorder, "running"));
            assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
            assertTrue((boolean)org.robolectric.util.ReflectionHelpers.getField(activity, "audioStopRequested"));
        } finally { recorder.close(); }
    }

    private double guideFraction() throws Exception {
        Field field = HudView.class.getDeclaredField("guideFraction");
        field.setAccessible(true);
        return field.getDouble(hud);
    }

    private static void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

    private static RecordedRequest takeRequest(MockWebServer target) throws Exception {
        RecordedRequest request = target.takeRequest(5, TimeUnit.SECONDS);
        assertNotNull("Expected HTTP request", request);
        return request;
    }

    private static MockWebServer newServer() throws Exception {
        MockWebServer result = new MockWebServer();
        result.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) {
                String path = request.getPath();
                if ("/health".equals(path)) {
                    return new MockResponse().setBody("{\"status\":\"ok\"}");
                }
                if ("/v1/settings".equals(path)) {
                    return new MockResponse().setBody("{\"hud\":{\"max_lines\":3}}");
                }
                return new MockResponse().setResponseCode(404).setBody("unexpected test request");
            }
        });
        result.start();
        return result;
    }

    private static final class Surface implements CaptureSurface {
        private long generation;
        private final boolean local;
        Surface() { this(false); }
        Surface(boolean local) { this.local = local; }
        @Override public boolean supportsLocalCaptureReview() { return local; }

        @Override
        public PhotoStartResult takePhoto(int width, int height, int quality) {
            throw new AssertionError("Intent update must never request a photo");
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

    private static final class Updates implements DocScanController.Listener {
        private ConnectionSettings settings;
        private final List<RelayState> states = new ArrayList<>();
        private final List<String> diagnostics = new ArrayList<>();

        @Override public void persistConfiguration(String server, String key) throws IOException {
            settings.save(server, key);
        }

        @Override
        public synchronized void onUpdate(RelayState state, List<String> lines, String diagnostic) {
            states.add(state);
            diagnostics.add(diagnostic);
            notifyAll();
        }

        synchronized void clear() {
            states.clear();
            diagnostics.clear();
        }

        synchronized int size() {
            return states.size();
        }

        synchronized void awaitState(RelayState expected) throws InterruptedException {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
            while (!states.contains(expected) && System.nanoTime() < deadline) {
                TimeUnit.NANOSECONDS.timedWait(this, Math.max(1, deadline - System.nanoTime()));
            }
            assertTrue("Expected " + expected + "; got " + states + "; " + diagnostics,
                    states.contains(expected));
        }

        synchronized void awaitDiagnostic(String expected) throws InterruptedException {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
            while (!diagnostics.contains(expected) && System.nanoTime() < deadline) {
                TimeUnit.NANOSECONDS.timedWait(this, Math.max(1, deadline - System.nanoTime()));
            }
            assertTrue("Expected " + expected + "; got " + diagnostics, diagnostics.contains(expected));
        }
    }
}
