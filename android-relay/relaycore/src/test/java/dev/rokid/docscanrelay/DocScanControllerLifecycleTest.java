package dev.rokid.docscanrelay;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import android.content.SharedPreferences;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import dev.rokid.docscanglass.input.GlassesInputAction;
import okhttp3.mockwebserver.Dispatcher;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

/** Exercises the actual serial controller, durable preferences and HTTP client. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class DocScanControllerLifecycleTest {
    private Context context;
    private SharedPreferences preferences;
    private MockWebServer server;
    private DocScanController controller;
    private final Updates updates = new Updates();
    private final Surface surface = new Surface();

    @Before
    public void setUp() throws Exception {
        context = RuntimeEnvironment.getApplication();
        preferences = context.getSharedPreferences("docscan_relay", Context.MODE_PRIVATE);
        preferences.edit().clear().commit();
        server = newServer();
    }

    @After
    public void tearDown() throws Exception {
        surface.releaseAiming.countDown();
        if (controller != null) {
            controller.close();
        }
        server.shutdown();
    }

    @Test
    public void startupRestoresSavedReadingWithoutAnIntermediateReadyOrError() throws Exception {
        saveReading();
        createController();

        controller.configureAndResume(server.url("/").toString(), "", 0);

        updates.awaitState(RelayState.READING);
        assertEquals("/v1/documents/17/scan-status", takeRequest(server).getPath());
        assertEquals(3, preferences.getInt("next_page", -1));
        assertFalse(updates.states.contains(RelayState.READY));
        assertFalse(updates.states.contains(RelayState.ERROR));
    }

    @Test
    public void launcherWithoutExtrasRestoresSavedServerAndReading() throws Exception {
        saveReading();
        createController();

        controller.configureAndResume(null, null, 0);

        updates.awaitState(RelayState.READING);
        assertEquals("/v1/documents/17/scan-status", takeRequest(server).getPath());
        controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
        updates.awaitState(RelayState.AIMING);
    }

    @Test
    public void launcherWithoutExtrasRestoresSavedAnswerReview() throws Exception {
        saveReading();
        preferences.edit().putLong("session_id", 23).commit();
        createController();

        controller.configureAndResume(null, null, 0);

        updates.awaitState(RelayState.REVIEW);
        assertEquals("/v1/exam-sessions/23/finalize-reading", takeRequest(server).getPath());
        assertEquals("/v1/exam-sessions/23/review?index=0&view_page=0",
                takeRequest(server).getPath());
        assertFalse(updates.states.contains(RelayState.READY));
        assertFalse(updates.states.contains(RelayState.ERROR));
    }

    @Test
    public void liveConfigurationAppliesNewServerAndKeyAndClearsOldWorkflow() throws Exception {
        saveReading();
        createController();
        controller.configureAndResume(null, "first-test-key", 0);
        updates.awaitState(RelayState.READING);
        assertEquals("Bearer first-test-key", takeRequest(server).getHeader("Authorization"));

        try (MockWebServer replacement = newServer()) {
            controller.configureAndResume(replacement.url("/").toString(), "next-test-key", 90);

            updates.awaitState(RelayState.READY);
            assertEquals(0, preferences.getLong("document_id", 0));
            assertEquals(replacement.url("/").toString().replaceAll("/+$", ""),
                    preferences.getString("server", ""));
            RecordedRequest health = takeRequest(replacement);
            assertEquals("/health", health.getPath());
            assertEquals("Bearer next-test-key", health.getHeader("Authorization"));
        }
    }

    @Test
    public void omittedLiveKeyKeepsExistingKeyForSameServer() throws Exception {
        saveReading();
        createController();
        controller.configureAndResume(null, "existing-test-key", 0);
        updates.awaitState(RelayState.READING);
        takeRequest(server);
        updates.clear();

        controller.configureAndResume(null, null, 90);

        updates.awaitState(RelayState.READING);
        assertEquals("Bearer existing-test-key", takeRequest(server).getHeader("Authorization"));
    }

    @Test
    public void queuedSecondTapUsesAimingStateWhenItsTurnArrives() throws Exception {
        startReady();
        surface.blockAiming = true;

        controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
        assertTrue("First tap did not enter aiming view", surface.enteredAiming.await(5, TimeUnit.SECONDS));
        assertEquals(RelayState.READY, controller.getState());
        controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
        surface.releaseAiming.countDown();

        updates.awaitState(RelayState.STABILIZING);
        assertEquals(1, surface.aimingViews.get());
        assertEquals(1, surface.stabilizingViews.get());
    }

    @Test
    public void terminalPhotoFailureReleasesLeaseAndAllowsShortTapRetry() throws Exception {
        startCapture(CaptureSurface.PhotoStartResult.STARTED);

        controller.onPhotoError("camera disconnected", null);
        updates.awaitDiagnostic("短押しで再撮影できます");
        updates.clear();
        controller.onGlassesAction(GlassesInputAction.SHORT_TAP);

        updates.awaitState(RelayState.AIMING);
        assertEquals(1, surface.photos.get());
    }

    @Test
    public void unresolvedPhotoFailureBlocksTapUntilTerminalCallback() throws Exception {
        // UNKNOWN marks the same timed-out lease as the no-callback watchdog,
        // without making this regression test wait the 30-second device timeout.
        startCapture(CaptureSurface.PhotoStartResult.UNKNOWN);
        updates.awaitState(RelayState.ERROR);
        int aimingViews = surface.aimingViews.get();
        updates.clear();

        controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
        controller.resume();
        updates.awaitDiagnostic("Resume rejected");

        assertEquals(RelayState.ERROR, controller.getState());
        assertEquals(aimingViews, surface.aimingViews.get());
        assertEquals(1, surface.photos.get());
        controller.onPhotoError("late terminal callback", null);
        updates.awaitDiagnostic("短押しで再撮影できます");
        updates.clear();
        controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
        updates.awaitState(RelayState.AIMING);
    }

    @Test
    public void configurationWhileAimingIsRejectedWithoutChangingStateOrServer() throws Exception {
        startReady();
        controller.captureNextPage();
        updates.awaitState(RelayState.AIMING);
        updates.clear();
        String previousServer = preferences.getString("server", "");

        try (MockWebServer replacement = newServer()) {
            controller.configureAndResume(replacement.url("/").toString(), "new-test-key", 90);
            updates.awaitConfigurationRejection();

            assertEquals(RelayState.AIMING, controller.getState());
            assertEquals(previousServer, preferences.getString("server", ""));
            assertTrue("Rejected configuration must not redraw the workflow", updates.states.isEmpty());
            assertEquals(0, replacement.getRequestCount());
        }
    }

    @Test
    public void pendingPhotoCannotBeRedirectedByNewServerConfiguration() throws Exception {
        saveReading();
        File pendingFile = new File(context.getFilesDir(), "pending-capture-v1.bin");
        CaptureReviewPersistence persistence = new CaptureReviewPersistence(pendingFile);
        byte[] jpeg = {1, 3, 5, 7};
        persistence.save(new CaptureReviewStore.Pending(1, jpeg, "saved page", 180, ""));
        createController();
        controller.configureAndResume(null, null, 180);
        updates.awaitState(RelayState.CAPTURE_REVIEW);
        updates.clear();
        String previousServer = preferences.getString("server", "");

        try (MockWebServer replacement = newServer()) {
            controller.configureAndResume(replacement.url("/").toString(), "new-test-key", 90);
            updates.awaitConfigurationRejection();

            assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
            assertEquals(previousServer, preferences.getString("server", ""));
            assertTrue(controller.hasPendingCaptureReview());
            CaptureReviewStore.Pending retained = persistence.loadOrNull();
            assertNotNull(retained);
            assertArrayEquals(jpeg, retained.jpeg);
            assertEquals(180, retained.rotationDegrees);
            assertTrue("Rejected configuration must leave the displayed photo intact", updates.states.isEmpty());
            assertEquals(0, replacement.getRequestCount());
            assertEquals(0, server.getRequestCount());
        }
    }

    private void startCapture(CaptureSurface.PhotoStartResult result) throws Exception {
        saveReading();
        createController();
        controller.configure(server.url("/").toString(), "", 0);
        controller.onCaptureLinkStateChanged(true, CaptureLinkEvent.GLASSES_STATUS_CHANGED);
        updates.awaitState(RelayState.READING);
        surface.photoResult = result;
        surface.acknowledgeGuides = true;
        updates.clear();
        controller.captureNextPage();
        updates.awaitState(RelayState.AIMING);
        controller.triggerArmedCapture();
        assertTrue("Camera was not requested", surface.photoRequested.await(6, TimeUnit.SECONDS));
    }

    private void startReady() throws Exception {
        createController();
        controller.configure(server.url("/").toString(), "", 0);
        controller.onCaptureLinkStateChanged(true, CaptureLinkEvent.GLASSES_STATUS_CHANGED);
        updates.awaitState(RelayState.READY);
        updates.clear();
    }

    private void saveReading() {
        preferences.edit().putString("server", server.url("/").toString().replaceAll("/+$", ""))
                .putLong("document_id", 17).putInt("next_page", 1).commit();
    }

    private void createController() {
        controller = new DocScanController(context, surface, null, updates,
                new ClientIdentity("test-glasses", "lifecycle-test/1", "fake-camera"));
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
                    return json("{\"status\":\"ok\"}");
                }
                if ("/v1/settings".equals(path)) {
                    return json("{\"hud\":{\"max_lines\":3}}");
                }
                if ("/v1/documents/17/scan-status".equals(path)) {
                    return json("{\"status\":\"reading\",\"page_indexes\":[0,1,2]}");
                }
                if ("/v1/exam-sessions/23/finalize-reading".equals(path)) {
                    return json("{\"status\":\"ready\"}");
                }
                if (path != null && path.startsWith("/v1/exam-sessions/23/review?")) {
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

    private final class Surface implements CaptureSurface {
        final AtomicInteger aimingViews = new AtomicInteger();
        final AtomicInteger stabilizingViews = new AtomicInteger();
        final AtomicInteger photos = new AtomicInteger();
        final CountDownLatch enteredAiming = new CountDownLatch(1);
        final CountDownLatch releaseAiming = new CountDownLatch(1);
        final CountDownLatch photoRequested = new CountDownLatch(1);
        volatile boolean blockAiming;
        volatile boolean acknowledgeGuides;
        volatile PhotoStartResult photoResult = PhotoStartResult.STARTED;
        private long generation;

        @Override
        public PhotoStartResult takePhoto(int width, int height, int quality) {
            photos.incrementAndGet();
            photoRequested.countDown();
            return photoResult;
        }

        @Override
        public long showHud(List<String> lines) {
            return ++generation;
        }

        @Override
        public long showCaptureAiming(int pageNumber, boolean retake, boolean stabilizing) {
            if (stabilizing) {
                stabilizingViews.incrementAndGet();
            } else {
                aimingViews.incrementAndGet();
            }
            if (blockAiming && !stabilizing) {
                enteredAiming.countDown();
                try {
                    if (!releaseAiming.await(5, TimeUnit.SECONDS)) {
                        return NO_VIEW_GENERATION;
                    }
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    return NO_VIEW_GENERATION;
                }
            }
            long next = ++generation;
            if (acknowledgeGuides) {
                controller.onCustomViewAvailable(next, "capture_aiming");
            }
            return next;
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
        final List<RelayState> states = new ArrayList<>();
        final List<String> diagnostics = new ArrayList<>();
        private final List<String> configurationRejections = new ArrayList<>();

        @Override
        public synchronized void onUpdate(RelayState state, List<String> lines, String diagnostic) {
            states.add(state);
            diagnostics.add(diagnostic);
            notifyAll();
        }

        @Override
        public synchronized void onConfigurationRejected(String message) {
            configurationRejections.add(message);
            notifyAll();
        }

        synchronized void clear() {
            states.clear();
            diagnostics.clear();
            configurationRejections.clear();
        }

        synchronized void awaitConfigurationRejection() throws InterruptedException {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
            while (configurationRejections.isEmpty() && System.nanoTime() < deadline) {
                TimeUnit.NANOSECONDS.timedWait(this, Math.max(1, deadline - System.nanoTime()));
            }
            assertFalse("Expected configuration rejection; states=" + states + "; " + diagnostics,
                    configurationRejections.isEmpty());
        }

        synchronized void awaitState(RelayState expected) throws InterruptedException {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
            while (!states.contains(expected) && System.nanoTime() < deadline) {
                TimeUnit.NANOSECONDS.timedWait(this, Math.max(1, deadline - System.nanoTime()));
            }
            assertTrue("Expected " + expected + "; states=" + states + "; diagnostics=" + diagnostics,
                    states.contains(expected));
        }

        synchronized void awaitDiagnostic(String text) throws InterruptedException {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
            while (!containsDiagnostic(text) && System.nanoTime() < deadline) {
                TimeUnit.NANOSECONDS.timedWait(this, Math.max(1, deadline - System.nanoTime()));
            }
            assertTrue("Expected diagnostic " + text + "; got " + diagnostics, containsDiagnostic(text));
        }

        private boolean containsDiagnostic(String text) {
            return diagnostics.stream().anyMatch(value -> value != null && value.contains(text));
        }
    }
}
