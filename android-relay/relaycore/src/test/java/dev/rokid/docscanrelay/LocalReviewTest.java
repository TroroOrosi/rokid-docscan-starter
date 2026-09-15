package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import android.content.Context;
import dev.rokid.docscanglass.input.GlassesInputAction;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.RecordedRequest;
import okhttp3.mockwebserver.Dispatcher;
import java.util.concurrent.CountDownLatch;
import java.io.File;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

/** Exercises the real controller: no unseen photo, no stale timer after a retake. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class LocalReviewTest {
    @Test public void upgradedLegacyWorkflowCannotLoseItsOriginalServer() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        android.content.SharedPreferences prefs = context.getSharedPreferences("docscan_relay", Context.MODE_PRIVATE);
        prefs.edit().putString("server", "http://original.test").putLong("document_id", 17).commit();
        DocScanController controller = new DocScanController(context, new Surface(), null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        try {
            controller.configureForLocalStart("http://new.test", "", 180);
            barrier(controller);
            assertEquals("http://original.test", prefs.getString("server", ""));
            assertEquals(17, controller.documentId());
            assertNull(controller.api());
            assertEquals(RelayState.ERROR, controller.getState());
        } finally { controller.close(); }
    }

    @Test public void olderInterruptedScanRemainsSelectableAfterStartingAnother() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        File root = new File(context.getFilesDir(), "local-scans");
        try (MockWebServer server = new MockWebServer()) {
            server.start();
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession old = LocalCaptureSession.create(root, address, false);
            CaptureReviewStore.Pending pending = new CaptureReviewStore.Pending(0, new byte[]{1, 2}, "前の資料", 180, "");
            new CaptureReviewPersistence(new File(old.directory(), "pending.bin")).save(pending);
            old.close();
            DocScanController controller = new DocScanController(context, new Surface(), null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(address, "", 180);
                controller.startLocalSession(false);
                barrier(controller);
                assertEquals(2, controller.savedCaptures().size());
            } finally { controller.close(); }
            DocScanController restarted = new DocScanController(context, new Surface(), null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                restarted.configureForLocalStart(address, "", 180);
                restarted.resumeLocalSession(old.id());
                barrier(restarted);
                assertEquals(RelayState.CAPTURE_REVIEW, restarted.getState());
                assertEquals(old.id(), ((LocalCaptureSession)get(restarted, "localSession")).id());
                assertArrayEquals(pending.jpeg, ((CaptureReviewStore)get(restarted, "captureReview")).peek().jpeg);
                assertEquals(2, restarted.savedCaptures().size());
                assertEquals(0, server.getRequestCount());
            } finally { restarted.close(); }
        }
    }

    @Test public void corruptLocalImageStopsWithoutRetryAndKeepsOriginal() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        CountDownLatch stopped = new CountDownLatch(1);
        try (MockWebServer server = new MockWebServer()) {
            server.start();
            LocalCaptureSession saved = LocalCaptureSession.create(new File(context.getFilesDir(), "local-scans"),
                    server.url("/").toString().replaceAll("/+$", ""), false);
            saved.bindDocument(17);
            saved.commit(new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "資料", 180, ""));
            File image = new File(saved.directory(), saved.page(0).fileName);
            java.nio.file.Files.write(image.toPath(), new byte[]{9});
            DocScanController controller = new DocScanController(context, new Surface(), null,
                    (state, lines, diagnostic) -> { if (state == RelayState.ERROR) stopped.countDown(); },
                    new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 180);
                barrier(controller);
                set(controller, "localSession", saved);
                call(controller, "queueLocalUpload", new Class<?>[]{});
                assertTrue("Storage damage must stop, not enter network retry", stopped.await(2, TimeUnit.SECONDS));
                barrier(controller);
                assertEquals(RelayState.ERROR, controller.getState());
                assertTrue(image.isFile());
                assertEquals(0, server.getRequestCount());
            } finally { controller.close(); }
        }
    }

    @Test public void committedPhotoDoesNotBlockNextGestureOnSlowHttpAndSurvivesRestart() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface();
        CountDownLatch uploading = new CountDownLatch(1);
        CountDownLatch response = new CountDownLatch(1);
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                    if (request.getPath().equals("/v1/documents")) return new MockResponse().setBody("{\"document_id\":17}");
                    if (request.getPath().equals("/v1/documents/17/pages")) {
                        uploading.countDown();
                        response.await(10, TimeUnit.SECONDS);
                        return new MockResponse().setBody("{\"replaced\":false}");
                    }
                    return new MockResponse().setResponseCode(404);
                }
            });
            server.start();
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 180);
                controller.startLocalSession(false);
                barrier(controller);
                assertEquals(RelayState.AIMING, controller.getState());
                assertEquals("No health or document creation before capture", 0, server.getRequestCount());
                set(controller, "autoShotsRemaining", 0);
                CaptureReviewStore.Pending photo = new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "実資料", 180, "");
                call(controller, "stageCaptureReview", new Class<?>[]{CaptureReviewStore.Pending.class, OcrQuality.class}, photo, null);
                assertEquals(0, server.getRequestCount());
                controller.confirmPendingCapture();
                barrier(controller);
                assertEquals("An unseen photo cannot be committed by a direct command", 0, server.getRequestCount());
                surface.visible = true;
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                // Keep the runnable check fast while preserving the timer's monotonic boundary.
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(3));
                call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, (long)get(controller, "reviewGeneration"));
                assertTrue(uploading.await(5, TimeUnit.SECONDS));
                controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
                barrier(controller); // Times out if the capture executor still performs HTTP.
                assertEquals(RelayState.AIMING, controller.getState());
                assertEquals(1, (int)get(controller, "nextPageIndex"));
                LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
                assertTrue(saved.contains(photo));
                controller.close();
                DocScanController restarted = new DocScanController(context, surface, null,
                        (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
                try {
                    assertTrue(restarted.hasLocalSession());
                    assertEquals(17, restarted.documentId());
                    assertEquals(1, (int)get(restarted, "nextPageIndex"));
                    assertFalse(((CaptureReviewStore)get(restarted, "captureReview")).hasPending());
                    LocalCaptureSession retained = LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), saved.id());
                    assertTrue(retained.contains(photo));
                    assertNotNull(retained.nextUnsent());
                    response.countDown();
                    restarted.configureForLocalStart(server.url("/").toString(), "", 180);
                    restarted.resumeLocalSession();
                    barrier(restarted);
                    ((ExecutorService)get(restarted, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                    barrier(restarted);
                    RecordedRequest create = server.takeRequest(5, TimeUnit.SECONDS);
                    RecordedRequest first = server.takeRequest(5, TimeUnit.SECONDS);
                    RecordedRequest retry = server.takeRequest(5, TimeUnit.SECONDS);
                    assertEquals("/v1/documents", create.getPath());
                    assertEquals("/v1/documents/17/pages", first.getPath());
                    assertEquals(first.getPath(), retry.getPath());
                    String firstBody = first.getBody().readUtf8();
                    String retryBody = retry.getBody().readUtf8();
                    // Multipart boundaries vary, but every field and the original image are identical.
                    assertEquals(firstBody.substring(firstBody.indexOf("\r\n")),
                            retryBody.substring(retryBody.indexOf("\r\n")).replace(
                                    retryBody.substring(0, retryBody.indexOf("\r\n")),
                                    firstBody.substring(0, firstBody.indexOf("\r\n"))));
                    assertNull(LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), saved.id()).nextUnsent());
                } finally { restarted.close(); }
            } finally { response.countDown(); controller.close(); }
        }
    }

    @Test public void microphoneFailureCannotBeClearedByLatePhotoOrOcr() throws Exception {
        Surface surface = new Surface();
        DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        try {
            CaptureLease lease = (CaptureLease)get(controller, "captureLease");
            lease.begin(0);
            set(controller, "state", RelayState.CAPTURING);
            controller.onListeningError();
            controller.onPhoto(new byte[]{1, 2, 3});
            barrier(controller);
            assertEquals(RelayState.ERROR, controller.getState());
            assertFalse(lease.isUnresolved());
            call(controller, "stageCaptureReview", new Class<?>[]{int.class, byte[].class,
                    String.class, int.class, String.class, PageFraming.class, OcrQuality.class},
                    0, new byte[]{1, 2, 3}, "late OCR", 0, "", PageFraming.UNKNOWN, null);
            assertEquals(RelayState.ERROR, controller.getState());
            assertFalse((boolean)get(controller, "autoCommitArmed"));
        } finally { controller.close(); }
    }

    @Test public void tapBetweenBurstShotsReviewsTheAlreadyCapturedFrame() throws Exception {
        Surface surface = new Surface();
        DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        try {
            set(controller, "state", RelayState.OCR);
            set(controller, "autoCaptureEnabled", true);
            set(controller, "autoShotsRemaining", 2);
            set(controller, "autoBest", new CaptureReviewStore.Pending(0, new byte[]{1, 2}, "wide image", 0, ""));
            controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
            barrier(controller);
            assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
            assertEquals(0, surface.photos);
            assertEquals(0, (int)get(controller, "autoShotsRemaining"));
        } finally { controller.close(); }
    }

    @Test public void localCameraFailureRemainsUnknownAndBlocksAnotherPhoto() throws Exception {
        Surface surface = new Surface();
        DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        try {
            CaptureLease lease = (CaptureLease)get(controller, "captureLease");
            lease.begin(0);
            controller.onPhotoError("camera timeout", null);
            barrier(controller);
            assertTrue(lease.isTimedOut());
            controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
            barrier(controller);
            assertEquals(0, surface.photos);
        } finally { controller.close(); }
    }

    @Test public void reviewNeedsVisibleAckAndRetakeRetiresItsCountdown() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface();
        try (MockWebServer server = new MockWebServer()) {
            server.start();
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                set(controller, "api", new DocScanApi(server.url("/").toString(), "",
                        new ClientIdentity("test", "test", "test")));
                set(controller, "linkReady", true);
                set(controller, "documentId", 17L);
                call(controller, "stageCaptureReview", new Class<?>[]{int.class, byte[].class,
                        String.class, int.class, String.class, PageFraming.class, OcrQuality.class},
                        0, new byte[]{1, 2, 3}, "wide material", 0, "", PageFraming.UNKNOWN, null);
                long review = (long) get(controller, "reviewGeneration");
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                assertFalse((boolean) get(controller, "autoCommitScheduled"));
                call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, review);
                barrier(controller);
                assertEquals(0, server.getRequestCount());

                surface.visible = true;
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                assertTrue((boolean) get(controller, "autoCommitScheduled"));
                controller.onGlassesAction(GlassesInputAction.SHORT_TAP);
                barrier(controller);
                assertEquals(RelayState.AIMING, controller.getState());
                call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, review);
                barrier(controller);
                assertEquals(0, server.getRequestCount());
                assertEquals(0, surface.photos); // retake also needs its own visible guide
            } finally { controller.close(); }
        }
    }

    private static final class Surface implements CaptureSurface {
        boolean visible;
        int photos;
        public boolean supportsLocalCaptureReview() { return true; }
        public boolean isCaptureReviewVisible(long generation) { return visible && generation == 1; }
        public PhotoStartResult takePhoto(int w, int h, int q) { photos++; return PhotoStartResult.STARTED; }
        public long showHud(List<String> lines) { return 2; }
        public long showCaptureAiming(int page, boolean retake, boolean stable) { return 3; }
        public long showCaptureReview(byte[] jpeg, int rotation, List<String> lines) { return 1; }
        public void fenceCustomViewEpoch(long generation, String reason) { }
    }
    private static Object get(Object object, String name) throws Exception {
        Field field = object.getClass().getDeclaredField(name); field.setAccessible(true);
        return field.get(object);
    }
    private static void set(Object object, String name, Object value) throws Exception {
        Field field = object.getClass().getDeclaredField(name); field.setAccessible(true); field.set(object, value);
    }
    private static void call(Object object, String name, Class<?>[] types, Object... args) throws Exception {
        Method method = object.getClass().getDeclaredMethod(name, types); method.setAccessible(true);
        ((ExecutorService) get(object, "serial")).submit(() -> {
            try { method.invoke(object, args); } catch (Exception error) { throw new RuntimeException(error); }
        }).get(5, TimeUnit.SECONDS);
    }
    private static void barrier(Object object) throws Exception {
        ((ExecutorService) get(object, "serial")).submit(() -> {}).get(5, TimeUnit.SECONDS);
    }
}
