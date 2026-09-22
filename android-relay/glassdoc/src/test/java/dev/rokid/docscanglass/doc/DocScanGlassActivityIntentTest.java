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
        setField(activity, "startupSelection", 3);
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
