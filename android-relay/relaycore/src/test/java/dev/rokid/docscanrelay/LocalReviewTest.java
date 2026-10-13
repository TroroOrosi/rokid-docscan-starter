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
    @Test public void earlyMixedAudioCompletionDoesNotEndCaptureAndSurvivesRestartUntilImagesAreSubmitted() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        List<String> requests = new java.util.concurrent.CopyOnWriteArrayList<>();
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) {
                    requests.add(request.getPath());
                    if ("/v1/documents".equals(request.getPath())) return new MockResponse().setBody("{\"document_id\":17}");
                    if ("/v1/exam-sessions".equals(request.getPath())) return new MockResponse().setBody("{\"session_id\":7}");
                    return new MockResponse().setBody("{\"status\":\"reviewing\"}");
                }
            });
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession saved = LocalCaptureSession.create(new File(context.getFilesDir(), "local-scans"), address, "mixed");
            saved.commit(new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "", 270, ""));
            for (int run = 0; run < 2; run++) {
                Surface surface = new Surface(); surface.holdForPage = true;
                DocScanController controller = new DocScanController(context, surface, null,
                        (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
                try {
                    controller.configureForLocalStart(address, "", 270); barrier(controller);
                    controller.resumeLocalSession(saved.id()); barrier(controller);
                    if (run == 0) {
                        controller.completeListening(); barrier(controller);
                        ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                        barrier(controller);
                        LocalCaptureSession restored = LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), saved.id());
                        assertTrue(restored.audioComplete());
                        assertEquals(LocalCaptureSession.Phase.CAPTURE, restored.phase());
                        assertTrue(controller.isAutoCaptureEnabled());
                        assertFalse(requests.stream().anyMatch(path -> path.contains("finalize-reading") || path.contains("document-audio")));
                    } else {
                        controller.finishReading(); barrier(controller);
                        ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                        barrier(controller);
                        assertEquals(1, java.util.Collections.frequency(requests, "/v1/exam-sessions/7/finalize-reading?solve=background"));
                        assertEquals(1, java.util.Collections.frequency(requests, "/v1/exam-sessions/7/document-audio"));
                    }
                } finally { controller.close(); }
            }
        }
    }

    @Test public void aMixedRecordingFailureKeepsPaperCaptureReviewAndStageOneUsableWithoutAttachingBrokenAudio() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface(); surface.holdForPage = true;
        List<String> requests = new java.util.concurrent.CopyOnWriteArrayList<>();
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) {
                    requests.add(request.getPath());
                    if ("/v1/documents".equals(request.getPath())) return new MockResponse().setBody("{\"document_id\":17}");
                    if ("/v1/exam-sessions".equals(request.getPath())) return new MockResponse().setBody("{\"session_id\":7}");
                    return new MockResponse().setBody("{\"status\":\"reviewing\"}");
                }
            });
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 270);
                controller.startLocalSession("mixed", accepted -> assertTrue(accepted));
                barrier(controller);
                controller.onListeningError(); barrier(controller);
                assertTrue("a recording failure cannot stop the independent paper capture", controller.isAutoCaptureEnabled());
                CaptureReviewStore.Pending photo = new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "", 270, "");
                call(controller, "stageCaptureReview", new Class<?>[]{CaptureReviewStore.Pending.class, OcrQuality.class}, photo, null);
                assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
                surface.visible = true;
                controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
                controller.onGlassesAction(GlassesInputAction.BACK, android.os.SystemClock.elapsedRealtime()); barrier(controller);
                long generation = (long)get(controller, "reviewGeneration");
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(3));
                call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, generation);
                barrier(controller);
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                barrier(controller);
                controller.completeListening(); barrier(controller);
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                assertTrue(requests.contains("/v1/exam-sessions/7/finalize-reading?solve=background"));
                assertFalse(requests.contains("/v1/exam-sessions/7/document-audio"));
                assertTrue(((LocalCaptureSession)get(controller, "localSession")).contains(photo));
                assertFalse(((LocalCaptureSession)get(controller, "localSession")).audioComplete());
            } finally { controller.close(); }
        }
    }

    @Test public void mixedImagesFinalizeBeforeAudioAndCompletedAudioAttachesOnce() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface();
        surface.holdForPage = true;
        List<String> requests = new java.util.concurrent.CopyOnWriteArrayList<>();
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) {
                    requests.add(request.getPath());
                    if ("/v1/documents".equals(request.getPath())) return new MockResponse().setBody("{\"document_id\":17}");
                    if ("/v1/exam-sessions".equals(request.getPath())) {
                        assertTrue(request.getBody().readUtf8().contains("\"exam_type\":\"mixed\""));
                        return new MockResponse().setBody("{\"session_id\":7}");
                    }
                    return new MockResponse().setBody("{\"status\":\"reviewing\"}");
                }
            });
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession saved = LocalCaptureSession.create(new File(context.getFilesDir(), "local-scans"), address, true);
            File file = new File(saved.directory(), "state.properties");
            java.util.Properties properties = new java.util.Properties();
            try (java.io.InputStream input = new java.io.FileInputStream(file)) { properties.load(input); }
            properties.setProperty("exam_type", "mixed");
            try (java.io.OutputStream output = new java.io.FileOutputStream(file)) { properties.store(output, "mixed test"); }
            saved = LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), saved.id());
            CaptureReviewStore.Pending photo = new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "", 270, "");
            saved.commit(photo);
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(address, "", 270);
                barrier(controller);
                controller.resumeLocalSession(saved.id());
                barrier(controller);
                assertTrue("mixed capture begins without waiting for microphone samples", controller.isAutoCaptureEnabled());
                controller.finishReading();
                barrier(controller);
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                barrier(controller);
                assertTrue(requests.contains("/v1/exam-sessions/7/finalize-reading?solve=background"));
                assertFalse(requests.contains("/v1/exam-sessions/7/document-audio"));
                assertEquals(7, controller.sessionId());
                controller.completeListening();
                barrier(controller);
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                barrier(controller);
                controller.completeListening();
                barrier(controller);
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                assertEquals(1, java.util.Collections.frequency(requests, "/v1/exam-sessions/7/document-audio"));
                assertEquals(1, java.util.Collections.frequency(requests, "/v1/exam-sessions/7/finalize-reading?solve=background"));
                assertTrue(LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), saved.id()).contains(photo));
            } finally { controller.close(); }
        }
    }

    @Test public void earlyCompletedMixedAudioRetriesAfterTransientFailureWithoutRepeatingReadingAnalysis() throws Exception {
        assertMixedAudioRetriesAfterTransientFailure(true);
    }

    @Test public void lateCompletedMixedAudioRetriesAfterTransientFailureWithoutRepeatingReadingAnalysis() throws Exception {
        assertMixedAudioRetriesAfterTransientFailure(false);
    }

    private void assertMixedAudioRetriesAfterTransientFailure(boolean early) throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        File root = new File(context.getFilesDir(), "local-scans");
        List<String> requests = new java.util.concurrent.CopyOnWriteArrayList<>();
        CountDownLatch retried = new CountDownLatch(1);
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new Dispatcher() {
                private int attachments;
                @Override public MockResponse dispatch(RecordedRequest request) {
                    requests.add(request.getPath());
                    if ("/v1/exam-sessions/7/document-audio".equals(request.getPath())) {
                        if (++attachments == 1) return new MockResponse().setResponseCode(503).setBody("{}");
                        retried.countDown();
                    }
                    return new MockResponse().setBody("{\"status\":\"reviewing\"}");
                }
            });
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession saved = LocalCaptureSession.create(root, address, "mixed");
            CaptureReviewStore.Pending photo = new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "", 270, "");
            saved.commit(photo);
            saved.acknowledge(saved.page(0));
            saved.bindDocument(17);
            saved.bindSession(7);
            saved.setPhase(early ? LocalCaptureSession.Phase.ANALYSIS : LocalCaptureSession.Phase.REVIEW);
            byte[] originalAudio = {4, 5, 6, 7};
            File audio = new File(saved.directory(), "original-audio-test.pcm");
            java.nio.file.Files.write(audio.toPath(), originalAudio);
            if (early) saved.completeAudio();
            Surface surface = new Surface(); surface.holdForPage = true;
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(address, "", 270); barrier(controller);
                controller.resumeLocalSession(saved.id()); barrier(controller);
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                barrier(controller);
                if (!early) {
                    controller.completeListening(); barrier(controller);
                    ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                    barrier(controller);
                }
                LocalCaptureSession retained = LocalCaptureSession.load(root, saved.id());
                assertTrue(retained.audioAttachPending());
                assertArrayEquals(originalAudio, java.nio.file.Files.readAllBytes(audio.toPath()));
                assertFalse("only the idempotent audio attach may be retried after a transient failure",
                        (boolean)get(controller, "localUploadBlocked"));
                assertEquals("reading stays available during an audio retry", RelayState.REVIEW, controller.getState());
                assertTrue("the existing five-second retry tick must resume the saved audio", retried.await(8, TimeUnit.SECONDS));
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                barrier(controller);
                retained = LocalCaptureSession.load(root, saved.id());
                assertFalse(retained.audioAttachPending());
                assertTrue(retained.contains(photo));
                assertArrayEquals(originalAudio, java.nio.file.Files.readAllBytes(audio.toPath()));
                controller.completeListening(); barrier(controller);
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                barrier(controller);
            } finally { controller.close(); }

            DocScanController restarted = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                restarted.configureForLocalStart(address, "", 270); barrier(restarted);
                restarted.resumeLocalSession(saved.id()); barrier(restarted);
                ((ExecutorService)get(restarted, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                barrier(restarted);
                assertEquals("one failed attach and one success; receipt persists across restart", 2,
                        java.util.Collections.frequency(requests, "/v1/exam-sessions/7/document-audio"));
                assertEquals("audio retry must never repeat stage one", early ? 1 : 0,
                        java.util.Collections.frequency(requests, "/v1/exam-sessions/7/finalize-reading?solve=background"));
                assertEquals(0, java.util.Collections.frequency(requests, "/v1/exam-sessions"));
            } finally { restarted.close(); }
        }
    }

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

    @Test public void assignedSessionIsPublishedBeforeFinalizationCanPutTheCpuToSleep() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        CountDownLatch finalizing = new CountDownLatch(1), release = new CountDownLatch(1);
        List<RelayState> updates = new java.util.concurrent.CopyOnWriteArrayList<>();
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                    if (request.getPath().equals("/v1/exam-sessions")) return new MockResponse().setBody("{\"session_id\":7}");
                    if (request.getPath().contains("finalize-reading")) {
                        finalizing.countDown(); release.await(3, TimeUnit.SECONDS);
                        return new MockResponse().setBody("{\"status\":\"solving\",\"review_total\":1}");
                    }
                    return new MockResponse().setBody("{}");
                }
            });
            LocalCaptureSession saved = LocalCaptureSession.create(new File(context.getFilesDir(), "local-scans"),
                    server.url("/").toString().replaceAll("/+$", ""), false);
            saved.bindDocument(17);
            saved.commit(new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "", 270, ""));
            saved.acknowledge(saved.nextUnsent());
            saved.setPhase(LocalCaptureSession.Phase.ANALYSIS);
            DocScanController controller = new DocScanController(context, new Surface(), null,
                    (state, lines, diagnostic) -> updates.add(state), new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 270);
                barrier(controller);
                set(controller, "localSession", saved);
                call(controller, "queueLocalUpload", new Class<?>[]{});
                assertTrue(finalizing.await(2, TimeUnit.SECONDS));
                barrier(controller);
                assertEquals("watch must know the server session before the long request returns", 7, controller.sessionId());
                assertTrue(updates.contains(RelayState.FINALIZING));
            } finally { release.countDown(); controller.close(); }
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
                android.os.PowerManager.WakeLock transferLock = org.robolectric.shadows.ShadowPowerManager.getLatestWakeLock();
                assertNotNull("a stored image's transfer needs a bounded CPU lease", transferLock);
                assertTrue(transferLock.isHeld());
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(121));
                assertFalse("transfer cannot retain CPU past two minutes", transferLock.isHeld());
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
                    assertFalse("successful transfer releases the CPU before answer analysis", org.robolectric.shadows.ShadowPowerManager.getLatestWakeLock().isHeld());
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

    @Test public void aDiagramOnlyPhotoIsReviewedWithoutCallingOcr() throws Exception {
        Surface surface = new Surface();
        DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        try {
            ((CaptureLease)get(controller, "captureLease")).begin(0);
            set(controller, "state", RelayState.CAPTURING);
            controller.onPhoto(new byte[]{1, 2, 3});
            barrier(controller);
            assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
            CaptureReviewStore.Pending photo = ((CaptureReviewStore)get(controller, "captureReview")).peek();
            assertArrayEquals(new byte[]{1, 2, 3}, photo.jpeg);
            assertEquals("", photo.ocrText);
            assertEquals(0, surface.photos);
        } finally { controller.close(); }
    }

    @Test public void previewFailureBeforeAnyPhotoStopsAutomaticCaptureAndKeepsOriginals() throws Exception {
        Surface surface = new Surface();
        surface.holdForPage = true;
        List<Boolean> running = new java.util.concurrent.CopyOnWriteArrayList<>();
        DocScanController.Listener updates = new DocScanController.Listener() {
            public void onUpdate(RelayState state, List<String> lines, String diagnostic) { }
            public void onAutoCaptureChanged(boolean active) { running.add(active); }
        };
        try (MockWebServer server = new MockWebServer()) {
            DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                    updates, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 270);
                controller.startLocalSession(false);
                barrier(controller);
                LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
                CaptureReviewStore.Pending original = new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "", 270, "");
                saved.commit(original);
                assertTrue(controller.isAutoCaptureEnabled());
                assertFalse(((CaptureLease)get(controller, "captureLease")).isUnresolved());
                assertEquals(RelayState.READY, controller.getState());
                controller.onPhotoError("preview unavailable", null);
                barrier(controller);
                assertEquals(RelayState.ERROR, controller.getState());
                assertFalse(controller.isAutoCaptureEnabled());
                assertTrue(surface.pauses > 0);
                assertEquals(Boolean.FALSE, running.get(running.size() - 1));
                surface.pageReady.run(); // a late preview callback cannot restart the failed camera
                barrier(controller);
                assertEquals(RelayState.ERROR, controller.getState());
                assertEquals(0, surface.photos);
                assertTrue(saved.contains(original));
            } finally { controller.close(); }
        }
    }

    @Test public void microphoneFailureStopsLivePreviewAndKeepsThePendingOriginal() throws Exception {
        Surface surface = new Surface();
        List<Boolean> running = new java.util.concurrent.CopyOnWriteArrayList<>();
        DocScanController.Listener updates = new DocScanController.Listener() {
            public void onUpdate(RelayState state, List<String> lines, String diagnostic) { }
            public void onAutoCaptureChanged(boolean active) { running.add(active); }
        };
        DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                updates, new ClientIdentity("test", "test", "test"));
        try {
            CaptureReviewStore.Pending original = new CaptureReviewStore.Pending(0, new byte[]{1, 2, 3}, "", 270, "");
            call(controller, "stageCaptureReview", new Class<?>[]{CaptureReviewStore.Pending.class, OcrQuality.class}, original, null);
            set(controller, "autoCaptureEnabled", true);
            controller.onListeningError();
            barrier(controller);
            assertEquals(RelayState.ERROR, controller.getState());
            assertFalse(controller.isAutoCaptureEnabled());
            assertTrue(surface.pauses > 0);
            assertEquals(Boolean.FALSE, running.get(running.size() - 1));
            assertArrayEquals(original.jpeg, ((CaptureReviewStore)get(controller, "captureReview")).peek().jpeg);
        } finally { controller.close(); }
    }

    @Test public void localShutterHudDoesNotCoverThePaperWithCoaching() throws Exception {
        Surface surface = new Surface();
        surface.holdForPage = true;
        List<List<String>> captureHud = new java.util.concurrent.CopyOnWriteArrayList<>();
        try (MockWebServer server = new MockWebServer()) {
            DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                    (state, lines, diagnostic) -> { if (state == RelayState.CAPTURING) captureHud.add(lines); },
                    new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 270);
                controller.startLocalSession(false);
                barrier(controller);
                set(controller, "state", RelayState.STABILIZING);
                call(controller, "requestPhotoAt", new Class<?>[]{int.class, boolean.class}, 0, false);
                assertEquals(1, surface.photos);
                assertEquals(List.of("撮影中", "", ""), captureHud.get(0));
            } finally { controller.close(); }
        }
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

    @Test public void unreadPhotoIsReviewedWithoutAnyTextSimilarityGate() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface();
        List<String> diagnostics = new java.util.concurrent.CopyOnWriteArrayList<>();
        byte[] sheet = {1, 2, 3};
        CountDownLatch release = new CountDownLatch(1);
        try (MockWebServer server = new MockWebServer()) {
            // The upload queued by the commit stays parked, so it cannot change state under the test.
            server.setDispatcher(new Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                    release.await(10, TimeUnit.SECONDS);
                    return new MockResponse().setResponseCode(503);
                }
            });
            server.start();
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> diagnostics.add(diagnostic), new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 0);
                controller.startLocalSession(false);
                barrier(controller);
                assertTrue((boolean) get(controller, "autoCaptureEnabled"));
                Class<?>[] shot = {CaptureReviewStore.Pending.class, OcrQuality.class};
                // A diagram-only image is kept for the model to read.

                call(controller, "stageCaptureReview", shot, new CaptureReviewStore.Pending(0, sheet, "", 0, ""), null);
                assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
                surface.visible = true;
                controller.onCustomViewAvailable(1, "capture-review");
                barrier(controller);
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(3));
                call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, (long) get(controller, "reviewGeneration"));
                barrier(controller);
                LocalCaptureSession saved = (LocalCaptureSession) get(controller, "localSession");
                assertEquals(1, saved.pageCount());

                // Not turned yet, and OCR fails outright on the same JPEG. With no text to compare,
                // it is reviewed again: a duplicate the model can ignore, never a skipped page.

                call(controller, "stageCaptureReview", shot, new CaptureReviewStore.Pending(1, sheet, "", 0, "OCR error"), null);
                assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
                assertTrue(((CaptureReviewStore) get(controller, "captureReview")).hasPending());

                assertFalse(diagnostics.stream().anyMatch(d -> d.contains("skipped as a duplicate")));
                assertEquals(0, surface.photos);
            } finally { release.countDown(); controller.close(); }
        }
    }

    /** 30s with no page registered rests the camera; the shutter tap restarts it. */
    @Test public void automaticReadingPausesWhenNothingHasBeenRegisteredForThirtySeconds() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface();
        List<String> diagnostics = new java.util.ArrayList<>();
        try (MockWebServer server = new MockWebServer()) {
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> diagnostics.add(diagnostic == null ? "" : diagnostic),
                    new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(server.url("/").toString(), "", 270);
                controller.startLocalSession(false);
                barrier(controller);

                int shotsBeforeTheStall = surface.photos;

                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(30));
                call(controller, "waitForNextPage", new Class<?>[]{});

                assertEquals(shotsBeforeTheStall, surface.photos);
                assertTrue("idle capture closes the preview rather than only changing the HUD", surface.pauses > 0);
                assertTrue(diagnostics.stream().anyMatch(
                        d -> d.contains("Automatic reading paused after 30000ms")));

                // A tap is the shutter and the resume.
                diagnostics.clear();
                call(controller, "manualCaptureNow", new Class<?>[]{});
                call(controller, "waitForNextPage", new Class<?>[]{});
                assertFalse(diagnostics.stream().anyMatch(d -> d.contains("paused")));
            } finally { controller.close(); }
        }
    }

    /** Manual mode never opens the camera on its own; a tap takes one photo. */
    @Test public void manualCaptureTakesNoPhotoUntilTheOperatorTaps() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface();
        List<String> diagnostics = new java.util.ArrayList<>();
        try (MockWebServer server = new MockWebServer()) {
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> diagnostics.add(diagnostic == null ? "" : diagnostic),
                    new ClientIdentity("test", "test", "test"));
            try {
                controller.setManualCapture(true);
                controller.configureForLocalStart(server.url("/").toString(), "", 270);
                controller.startLocalSession(false);
                barrier(controller);

                assertFalse("no automatic loop", controller.isAutoCaptureEnabled());
                assertEquals("no photo before a tap", 0, surface.photos);
                assertTrue(diagnostics.stream().anyMatch(d -> d.contains("Manual capture")));

                // The tap arms the page; the photo still waits for the visible guide.
                call(controller, "manualCaptureNow", new Class<?>[]{});
                barrier(controller);
                assertEquals(RelayState.AIMING, controller.getState());
                assertEquals(0, surface.photos);

                // The shutter then waits out SHUTTER_STABILIZATION_MILLIS, so this
                // stops at the state; the photo itself is covered by the tests above.
                set(controller, "captureGuideAcknowledged", true);
                call(controller, "triggerArmedCaptureNow", new Class<?>[]{});
                barrier(controller);
                assertEquals("the tap is the shutter", RelayState.STABILIZING, controller.getState());
                assertFalse("still no automatic loop", controller.isAutoCaptureEnabled());

                // The listening recorder's start request is refused the same way.
                controller.startAutoCapture();
                barrier(controller);
                assertFalse(controller.isAutoCaptureEnabled());
            } finally { controller.close(); }
        }
    }

    private static final class Surface implements CaptureSurface {
        boolean visible;
        int photos;
        int pauses;
        boolean holdForPage;
        Runnable pageReady;
        public void awaitNextPage(Runnable ready) { if (holdForPage) pageReady = ready; else ready.run(); }
        public void pausePreview() { pauses++; }
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
        ((ExecutorService) get(object, "serial")).submit(() -> {}).get(5, TimeUnit.SECONDS);
    }
}
