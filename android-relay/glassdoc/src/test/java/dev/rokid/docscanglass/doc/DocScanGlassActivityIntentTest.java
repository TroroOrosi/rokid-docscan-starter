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
        action.invoke(activity, GlassesInputAction.SHORT_TAP, 1400L);
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
        action.invoke(activity, GlassesInputAction.SHORT_TAP, 1000L);
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
        action.invoke(activity, GlassesInputAction.SHORT_TAP, 1000L);
        awaitSerial();
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();
        Field choosing = DocScanGlassActivity.class.getDeclaredField("choosingSession");
        choosing.setAccessible(true);
        assertTrue(choosing.getBoolean(activity));
        action.invoke(activity, GlassesInputAction.BACK, 2000L); // back to root
        action.invoke(activity, GlassesInputAction.BACK, 2500L);
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
        assertEquals(0, activity.getWindow().getAttributes().flags & keepOn);
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

    @Test public void chooserIdleSleepsAtFiveSecondsWithoutChangingTheSystemTimeout() throws Exception {
        android.provider.Settings.System.putInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, 0);
        setField(activity, "choosingSession", true);
        activity.onResume();
        java.lang.reflect.Method choices = DocScanGlassActivity.class.getDeclaredMethod("showStartupChoices");
        choices.setAccessible(true);
        choices.invoke(activity);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(4_999));
        assertTrue((activity.getWindow().getAttributes().flags & keepOn) != 0);
        activity.onUpdate(RelayState.READY, List.of("network update"), "background status");
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(1));
        assertEquals("background updates must not extend chooser inactivity", 0,
                activity.getWindow().getAttributes().flags & keepOn);
        assertEquals(0, android.provider.Settings.System.getInt(activity.getContentResolver(),
                android.provider.Settings.System.SCREEN_OFF_TIMEOUT, -1));
    }

    @Test public void aChooserSwipeRestartsTheIdleClockAndAStoppedCameraCanSleep() throws Exception {
        setField(activity, "choosingSession", true);
        activity.onResume();
        java.lang.reflect.Method choices = DocScanGlassActivity.class.getDeclaredMethod("showStartupChoices");
        choices.setAccessible(true);
        choices.invoke(activity);
        int keepOn = android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(4));
        java.lang.reflect.Method action = DocScanGlassActivity.class.getDeclaredMethod("onAction", GlassesInputAction.class, long.class);
        action.setAccessible(true);
        action.invoke(activity, GlassesInputAction.SWIPE_FORWARD, android.os.SystemClock.elapsedRealtime());
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofSeconds(4));
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
