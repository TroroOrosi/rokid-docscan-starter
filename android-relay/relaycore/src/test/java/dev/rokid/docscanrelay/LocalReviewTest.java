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
    @Test public void tapStartedBeforeDeadlineRetakesSamePageAfterFirmwareClassification() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface();
        try (MockWebServer server = new MockWebServer()) {
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 270);
                controller.startLocalSession(false);
                barrier(controller);
                set(controller, "autoShotsRemaining", 0);
                // A real pending page, including local persistence and the visible ACK.
                CaptureReviewStore.Pending photo = new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "page", 270, "");
                call(controller, "stageCaptureReview", new Class<?>[]{CaptureReviewStore.Pending.class, OcrQuality.class}, photo, null);
                surface.visible = true;
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                long generation = (long)get(controller, "reviewGeneration");
                long start = android.os.SystemClock.elapsedRealtime();
                // Measured: NOTIFICATION at 2485ms, ENTER at 3003ms.
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMillis(2485));
                controller.onGlassesGestureStarted(start + 2485);
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMillis(518));
                call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, generation);
                barrier(controller);
                controller.onGlassesAction(GlassesInputAction.SHORT_TAP, start + 3003);
                barrier(controller);
                assertEquals("Retake must still target P1", 0, (int)get(controller, "armedPageIndex"));
                assertEquals("The tap must prevent the original commit", 0,
                        ((LocalCaptureSession)get(controller, "localSession")).pageCount());
                assertEquals(0, server.getRequestCount());

                // An early retake retires the old deadline before a fresh shutter gesture.
                call(controller, "stageCaptureReview", new Class<?>[]{CaptureReviewStore.Pending.class, OcrQuality.class}, photo, null);
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                start = android.os.SystemClock.elapsedRealtime();
                controller.onGlassesGestureStarted(start + 500);
                controller.onGlassesAction(GlassesInputAction.SHORT_TAP, start + 1000);
                barrier(controller);
                assertEquals(RelayState.AIMING, controller.getState());
                set(controller, "captureGuideAcknowledged", true);
                controller.onGlassesGestureStarted(start + 1200);
                controller.onGlassesAction(GlassesInputAction.SHORT_TAP, start + 1700);
                barrier(controller);
                assertEquals("Fresh shutter must not inherit the retired review", RelayState.STABILIZING, controller.getState());
                assertEquals(0, (int)get(controller, "armedPageIndex"));

                // An action queued before processing still wins when the timer is ahead of it.
                call(controller, "stageCaptureReview", new Class<?>[]{CaptureReviewStore.Pending.class, OcrQuality.class}, photo, null);
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                generation = (long)get(controller, "reviewGeneration");
                start = android.os.SystemClock.elapsedRealtime();
                controller.onGlassesGestureStarted(start + 2999);
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMillis(4500));
                CountDownLatch blocked = new CountDownLatch(1), release = new CountDownLatch(1);
                ((ExecutorService)get(controller, "serial")).execute(() -> {
                    blocked.countDown();
                    try { release.await(2, TimeUnit.SECONDS); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
                });
                assertTrue(blocked.await(1, TimeUnit.SECONDS));
                try {
                    Method timer = DocScanController.class.getDeclaredMethod("enqueueAutoCommit", long.class);
                    timer.setAccessible(true);
                    timer.invoke(controller, generation);
                    controller.onGlassesAction(GlassesInputAction.SHORT_TAP, start + 3500);
                } finally { release.countDown(); }
                barrier(controller);
                assertEquals(0, (int)get(controller, "armedPageIndex"));
                assertEquals(0, ((LocalCaptureSession)get(controller, "localSession")).pageCount());

                // A fresh tap that starts at the deadline cannot retake or become P2.
                call(controller, "stageCaptureReview", new Class<?>[]{CaptureReviewStore.Pending.class, OcrQuality.class}, photo, null);
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                start = android.os.SystemClock.elapsedRealtime();
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMillis(3000));
                controller.onGlassesGestureStarted(start + 3000);
                controller.onGlassesAction(GlassesInputAction.SHORT_TAP, start + 3500);
                barrier(controller);
                assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
                assertEquals(-1, (int)get(controller, "armedPageIndex"));

                // An incomplete gesture cannot hold the page forever.
                call(controller, "stageCaptureReview", new Class<?>[]{CaptureReviewStore.Pending.class, OcrQuality.class}, photo, null);
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                generation = (long)get(controller, "reviewGeneration");
                start = android.os.SystemClock.elapsedRealtime();
                controller.onGlassesGestureStarted(start + 2999);
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMillis(3970));
                assertEquals(false, invoke(controller, "reviewGestureBlocksCommit", new Class<?>[]{long.class}, generation));
            } finally { controller.close(); }
        }
    }

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

    @Test public void audioDirectoryUsesLocalIdentityAndRejectsAnotherOriginWithTheSameDocumentId() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        File root = new File(context.getFilesDir(), "local-scans");
        try (MockWebServer server = new MockWebServer()) {
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession old = LocalCaptureSession.create(root, "http://previous.invalid", true);
            LocalCaptureSession current = LocalCaptureSession.create(root, address, true);
            old.bindDocument(17); current.bindDocument(17);
            File original = new File(old.directory(), "original-audio");
            java.nio.file.Files.write(original.toPath(), new byte[]{1, 2, 3});
            DocScanController controller = new DocScanController(context, new Surface(), null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(address, "", 180);
                barrier(controller);
                set(controller, "localSession", old);
                org.junit.Assert.assertThrows(java.io.IOException.class, controller::localCaptureDirectory);
                set(controller, "localSession", current);
                assertEquals(current.directory(), controller.localCaptureDirectory());
                assertFalse(old.directory().equals(controller.localCaptureDirectory()));
                assertArrayEquals(new byte[]{1, 2, 3}, java.nio.file.Files.readAllBytes(original.toPath()));
                assertEquals(0, server.getRequestCount());
            } finally { controller.close(); }
        }
    }

    @Test public void listeningSelectionHandsOffLocalRecordingBeforeAnyHttpResponse() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        CountDownLatch selected = new CountDownLatch(1), response = new CountDownLatch(1);
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                    response.await(5, TimeUnit.SECONDS);
                    return new MockResponse().setBody(request.getPath().equals("/v1/listening-ready")
                            ? "{\"ready\":true}" : "{\"document_id\":17}");
                }
            });
            DocScanController controller = new DocScanController(context, new Surface(), null,
                    new DocScanController.Listener() {
                        public void onUpdate(RelayState state, List<String> lines, String diagnostic) { }
                        @Override public void onListeningReady(File directory, long documentId, boolean resume) {
                            if (documentId == 0 && !resume && directory.isDirectory()) selected.countDown();
                        }
                    }, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 180);
                controller.startLocalSession(true);
                assertTrue("Audio must be handed off locally before the server answers", selected.await(1, TimeUnit.SECONDS));
            } finally { response.countDown(); controller.close(); }
        }
    }

    @Test public void resumingPendingListeningPhotoAlsoRestoresItsAudioWithoutStartingANewRecording() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        File root = new File(context.getFilesDir(), "local-scans");
        CountDownLatch restored = new CountDownLatch(1);
        try (MockWebServer server = new MockWebServer()) {
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession saved = LocalCaptureSession.create(root, address, true);
            saved.bindDocument(17);
            CaptureReviewStore.Pending pending = new CaptureReviewStore.Pending(0, new byte[]{1, 2}, "前の資料", 180, "");
            new CaptureReviewPersistence(new File(saved.directory(), "pending.bin")).save(pending);
            DocScanController controller = new DocScanController(context, new Surface(), null,
                    new DocScanController.Listener() {
                        public void onUpdate(RelayState state, List<String> lines, String diagnostic) { }
                        @Override public void onListeningReady(File directory, long documentId, boolean resume) {
                            if (directory.equals(saved.directory()) && documentId == 17 && resume) restored.countDown();
                        }
                    }, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(address, "", 180);
                controller.resumeLocalSession(saved.id());
                assertTrue(restored.await(2, TimeUnit.SECONDS));
                barrier(controller);
                assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
                assertArrayEquals(pending.jpeg, ((CaptureReviewStore) get(controller, "captureReview")).peek().jpeg);
                assertEquals(0, server.getRequestCount());
            } finally { controller.close(); }
        }
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
        invoke(object, name, types, args);
    }
    private static Object invoke(Object object, String name, Class<?>[] types, Object... args) throws Exception {
        Method method = object.getClass().getDeclaredMethod(name, types); method.setAccessible(true);
        return ((ExecutorService) get(object, "serial")).submit(() -> {
            try { return method.invoke(object, args); } catch (Exception error) { throw new RuntimeException(error); }
        }).get(5, TimeUnit.SECONDS);
    }
    private static void barrier(Object object) throws Exception {
        ((ExecutorService) get(object, "serial")).submit(() -> {}).get(5, TimeUnit.SECONDS);
    }
}
