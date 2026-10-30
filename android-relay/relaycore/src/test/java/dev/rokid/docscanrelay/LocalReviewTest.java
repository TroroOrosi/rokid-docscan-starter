package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import android.content.Context;
import dev.rokid.docscanglass.input.GlassesInputAction;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.RecordedRequest;
import okhttp3.mockwebserver.Dispatcher;
import java.util.concurrent.CountDownLatch;
import java.io.File;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

/** Exercises the real controller: no unseen photo, no stale timer after a retake. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class LocalReviewTest {
    @Test public void nativeInspectionOriginBindsTheIssuedRunAndTheActualLateDocumentId() throws Exception {
        Surface surface = new Surface(); surface.holdForPage = true;
        var run = new java.util.concurrent.atomic.AtomicReference<>(new CaptureInspectionOrigin.Context("glasses:one", 42));
        try (MockWebServer server = inspectionServer()) {
            DocScanController controller = inspectionController(server, surface, run);
            try {
                byte[] jpeg = {1, 2, 3}; CaptureProvenance source = nativeSource(jpeg, 100);
                issueInspectionPhoto(controller, 0, false); controller.onPhoto(jpeg, source); barrier(controller);
                LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
                assertEquals("server document is not guessed at capture", 0, saved.documentId());
                commitVisible(controller, surface);
                List<RecordedRequest> pages = uploadInspectionPages(controller, server);
                assertEquals(1, pages.size());
                JSONObject origin = new JSONObject(new String(uploadPart(pages.get(0), "inspection_origin"), StandardCharsets.UTF_8));
                assertEquals(6, origin.length()); assertEquals(17, origin.getLong("document_id"));
                assertEquals("glasses:one", origin.getString("device_id")); assertEquals(42, origin.getLong("generation"));
                assertEquals(saved.id(), origin.getString("local_session_id"));
                assertEquals(source.captureId, origin.getString("capture_id"));
                assertArrayEquals(jpeg, uploadPart(pages.get(0), "image")); assertNull(saved.nextUnsent());
            } finally { controller.close(); }
        }
    }

    @Test public void changingTheDeviceOrGenerationCannotRelabelAnIssuedOriginal() throws Exception {
        for (boolean changeBeforeCallback : new boolean[]{true, false}) {
            Surface surface = new Surface(); surface.holdForPage = true;
            var run = new java.util.concurrent.atomic.AtomicReference<>(new CaptureInspectionOrigin.Context("glasses:one", 42));
            try (MockWebServer server = inspectionServer()) {
                DocScanController controller = inspectionController(server, surface, run);
                try {
                    byte[] jpeg = {1, 2, 3}; issueInspectionPhoto(controller, 0, false);
                    if (changeBeforeCallback) run.set(new CaptureInspectionOrigin.Context("glasses:two", 42));
                    controller.onPhoto(jpeg, nativeSource(jpeg, 100)); barrier(controller);
                    if (!changeBeforeCallback) run.set(new CaptureInspectionOrigin.Context("glasses:one", 43));
                    commitVisible(controller, surface);
                    List<RecordedRequest> pages = uploadInspectionPages(controller, server);
                    assertEquals(1, pages.size());
                    assertFalse(pages.get(0).getBody().clone().readUtf8().contains("name=\"inspection_origin\""));
                    assertArrayEquals(jpeg, uploadPart(pages.get(0), "image"));
                    assertNull(((LocalCaptureSession)get(controller, "localSession")).nextUnsent());
                } finally { controller.close(); }
            }
        }
    }

    @Test public void retakeInspectionUsesOnlyTheNewCaptureAndItsOwnPreRequestRun() throws Exception {
        Surface surface = new Surface(); surface.holdForPage = true;
        var run = new java.util.concurrent.atomic.AtomicReference<>(new CaptureInspectionOrigin.Context("glasses", 1));
        try (MockWebServer server = inspectionServer()) {
            DocScanController controller = inspectionController(server, surface, run);
            try {
                byte[] first = {1, 2, 3}, second = {4, 5, 6};
                CaptureProvenance discarded = nativeSource(first, 100), kept = nativeSource(second, 200);
                issueInspectionPhoto(controller, 0, false); controller.onPhoto(first, discarded); barrier(controller);
                run.set(new CaptureInspectionOrigin.Context("glasses", 2));
                issueInspectionPhoto(controller, 0, true); controller.onPhoto(second, kept); barrier(controller);
                commitVisible(controller, surface);
                List<RecordedRequest> pages = uploadInspectionPages(controller, server);
                assertEquals(1, pages.size());
                JSONObject origin = new JSONObject(new String(uploadPart(pages.get(0), "inspection_origin"), StandardCharsets.UTF_8));
                assertEquals(kept.captureId, origin.getString("capture_id"));
                assertNotEquals(discarded.captureId, origin.getString("capture_id")); assertEquals(2, origin.getLong("generation"));
                assertArrayEquals(second, uploadPart(pages.get(0), "image"));
            } finally { controller.close(); }
        }
    }

    @Test public void futureInspectionRequiresItsOwnNativeStartAndStillCurrentRun() throws Exception {
        for (boolean changeAfterStart : new boolean[]{false, true}) {
            Surface surface = new Surface(); surface.holdForPage = true; surface.futureEnabled = true;
            var run = new java.util.concurrent.atomic.AtomicReference<>(new CaptureInspectionOrigin.Context("glasses", 1));
            try (MockWebServer server = inspectionServer()) {
                DocScanController controller = inspectionController(server, surface, run);
                try {
                    byte[] first = {1, 2, 3}, second = {4, 5, 6};
                    issueInspectionPhoto(controller, 0, false); controller.onPhoto(first, nativeSource(first, 100)); barrier(controller);
                    surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
                    assertNotNull(surface.future); assertTrue(surface.future.onCaptureStarting());
                    if (changeAfterStart) run.set(new CaptureInspectionOrigin.Context("glasses", 2));
                    CaptureProvenance kept = nativeSource(second, 200);
                    surface.future.onCandidate(second, kept, true); barrier(controller);
                    commitVisible(controller, surface); commitVisible(controller, surface);
                    List<RecordedRequest> pages = uploadInspectionPages(controller, server);
                    assertEquals(2, pages.size());
                    assertArrayEquals(second, uploadPart(pages.get(1), "image"));
                    String body = pages.get(1).getBody().clone().readUtf8();
                    if (changeAfterStart) assertFalse(body.contains("name=\"inspection_origin\""));
                    else {
                        JSONObject origin = new JSONObject(new String(uploadPart(pages.get(1), "inspection_origin"), StandardCharsets.UTF_8));
                        assertEquals(kept.captureId, origin.getString("capture_id")); assertEquals(1, origin.getLong("generation"));
                    }
                } finally { controller.close(); }
            }
        }
    }

    @Test public void timedOutNativeCallbackCannotPublishAnInspectionOrUpload() throws Exception {
        Surface surface = new Surface(); surface.holdForPage = true;
        var run = new java.util.concurrent.atomic.AtomicReference<>(new CaptureInspectionOrigin.Context("glasses", 1));
        try (MockWebServer server = inspectionServer()) {
            DocScanController controller = inspectionController(server, surface, run);
            try {
                issueInspectionPhoto(controller, 0, false);
                call(controller, "enqueueCaptureTimeout", new Class<?>[]{long.class}, 1L); barrier(controller);
                controller.onPhoto(new byte[]{1, 2, 3}, nativeSource(new byte[]{1, 2, 3}, 100)); barrier(controller);
                assertEquals(RelayState.ERROR, controller.getState());
                assertNull(((CaptureReviewStore)get(controller, "captureReview")).peek());
                assertNull(((LocalCaptureSession)get(controller, "localSession")).nextUnsent());
                assertEquals(0, server.getRequestCount());
            } finally { controller.close(); }
        }
    }

    @Test public void aFutureOriginalWithoutItsOwnNativeStartCannotBorrowTheReviewOrigin() throws Exception {
        Surface surface = new Surface(); surface.holdForPage = true; surface.futureEnabled = true;
        var run = new java.util.concurrent.atomic.AtomicReference<>(new CaptureInspectionOrigin.Context("glasses", 1));
        try (MockWebServer server = inspectionServer()) {
            DocScanController controller = inspectionController(server, surface, run);
            try {
                byte[] first = {1, 2, 3}, second = {4, 5, 6};
                issueInspectionPhoto(controller, 0, false); controller.onPhoto(first, nativeSource(first, 100)); barrier(controller);
                surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
                surface.future.onCandidate(second, nativeSource(second, 200), true); barrier(controller);
                commitVisible(controller, surface); commitVisible(controller, surface);
                List<RecordedRequest> pages = uploadInspectionPages(controller, server);
                assertEquals(2, pages.size());
                assertTrue(pages.get(0).getBody().clone().readUtf8().contains("name=\"inspection_origin\""));
                assertFalse(pages.get(1).getBody().clone().readUtf8().contains("name=\"inspection_origin\""));
                assertArrayEquals(second, uploadPart(pages.get(1), "image"));
            } finally { controller.close(); }
        }
    }

    @Test public void anUnavailableOptionalContextCannotFailOrdinaryNativeUpload() throws Exception {
        Surface surface = new Surface(); surface.holdForPage = true;
        var run = new java.util.concurrent.atomic.AtomicReference<>(new CaptureInspectionOrigin.Context("glasses", 1));
        try (MockWebServer server = inspectionServer()) {
            DocScanController controller = inspectionController(server, surface, run);
            try {
                controller.setCaptureInspectionContextProvider(() -> { throw new IllegalStateException("context unavailable"); });
                byte[] jpeg = {1, 2, 3}; issueInspectionPhoto(controller, 0, false);
                controller.onPhoto(jpeg, nativeSource(jpeg, 100)); barrier(controller); commitVisible(controller, surface);
                List<RecordedRequest> pages = uploadInspectionPages(controller, server);
                assertEquals(1, pages.size());
                assertFalse(pages.get(0).getBody().clone().readUtf8().contains("name=\"inspection_origin\""));
                assertArrayEquals(jpeg, uploadPart(pages.get(0), "image"));
                assertNull(((LocalCaptureSession)get(controller, "localSession")).nextUnsent());
            } finally { controller.close(); }
        }
    }

    private static MockWebServer inspectionServer() throws Exception {
        MockWebServer server = new MockWebServer();
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) {
                try {
                    if ("/v1/documents".equals(request.getPath())) return new MockResponse().setBody("{\"document_id\":17}");
                    if ("/v1/documents/17/pages".equals(request.getPath())) {
                        JSONObject metadata = new JSONObject(new String(uploadPart(request, "capture_provenance"), StandardCharsets.UTF_8));
                        return new MockResponse().setBody(new JSONObject().put("document_id", 17)
                                .put("page_index", metadata.getInt("page_index")).put("capture_provenance", metadata)
                                .put("canonical_image_sha256", "c".repeat(64)).toString());
                    }
                    return new MockResponse().setResponseCode(404);
                } catch (Exception error) { return new MockResponse().setResponseCode(500); }
            }
        });
        server.start(); return server;
    }

    private static DocScanController inspectionController(MockWebServer server, Surface surface,
            java.util.concurrent.atomic.AtomicReference<CaptureInspectionOrigin.Context> run) throws Exception {
        DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        controller.setCaptureInspectionContextProvider(run::get);
        controller.configureForLocalStart(server.url("/").toString(), "", 270);
        controller.startLocalSession(false); barrier(controller);
        set(controller, "localNetworkBusy", true); return controller;
    }

    private static void issueInspectionPhoto(DocScanController controller, int page, boolean retake) throws Exception {
        set(controller, "state", RelayState.STABILIZING);
        call(controller, "requestPhotoAt", new Class<?>[]{int.class, boolean.class}, page, retake); barrier(controller);
        assertEquals(RelayState.CAPTURING, controller.getState());
    }

    private static List<RecordedRequest> uploadInspectionPages(DocScanController controller, MockWebServer server) throws Exception {
        set(controller, "localNetworkBusy", false); call(controller, "queueLocalUpload", new Class<?>[]{}); waitForUpload(controller);
        List<RecordedRequest> pages = new java.util.ArrayList<>();
        RecordedRequest request;
        while ((request = server.takeRequest(50, TimeUnit.MILLISECONDS)) != null)
            if ("/v1/documents/17/pages".equals(request.getPath())) pages.add(request);
        return pages;
    }

    @Test public void mismatchedZslJpegIsPreservedUnresolvedAndCannotUploadAfterRestart() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface(); surface.holdForPage = true;
        DocScanController controller = localWithOriginal(context, surface);
        byte[] jpeg = {7, 8, 9}; String sessionId;
        try {
            sessionId = ((LocalCaptureSession)get(controller, "localSession")).id();
            ((CaptureLease)get(controller, "captureLease")).begin(0);
            set(controller, "state", RelayState.CAPTURING);
            controller.onPhoto(jpeg, null, false); barrier(controller);
            CaptureReviewStore.Pending held = ((CaptureReviewStore)get(controller, "captureReview")).peek();
            assertArrayEquals(jpeg, held.jpeg); assertNull(held.provenance); assertTrue(held.needsSceneRecapture());
            commitVisible(controller, surface);
            controller.onGlassesAction(GlassesInputAction.BACK); barrier(controller);
            controller.confirmPendingCapture(); barrier(controller);
            LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
            assertEquals(0, saved.pageCount()); assertNull(saved.nextUnsent()); assertTrue(saved.captureGap());
        } finally { controller.close(); }
        Surface restoredSurface = new Surface(); restoredSurface.holdForPage = true;
        DocScanController restored = new DocScanController(context, restoredSurface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        try {
            restored.configureForLocalStart("http://phone:8000", "", 270); barrier(restored);
            set(restored, "localNetworkBusy", true);
            restored.showPendingCaptureReview(); barrier(restored);
            CaptureReviewStore.Pending held = ((CaptureReviewStore)get(restored, "captureReview")).peek();
            assertArrayEquals(jpeg, held.jpeg); assertTrue(held.needsSceneRecapture()); assertNull(held.provenance);
            commitVisible(restored, restoredSurface); restored.confirmPendingCapture(); barrier(restored);
            LocalCaptureSession saved = (LocalCaptureSession)get(restored, "localSession");
            assertEquals(sessionId, saved.id()); assertEquals(0, saved.pageCount()); assertNull(saved.nextUnsent());
        } finally { restored.close(); }
    }

    @Test public void reviewKeepsTwoUnseenOriginalsAndEachGetsItsOwnVisibleThreeSecondsAfterRestart() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(context, surface);
        String id = ((LocalCaptureSession)get(controller, "localSession")).id();
        byte[] second = {4, 5, 6}, third = {7, 8, 9};
        CaptureProvenance b = nativeSource(second, 200), c = nativeSource(third, 300);
        try {
            surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
            assertNotNull("review ACK starts native future observation", surface.future);
            assertTrue(surface.future.onCaptureStarting());
            surface.future.onCandidate(second, b, true); barrier(controller);
            assertTrue(surface.future.onCaptureStarting());
            surface.future.onCandidate(third, c, true); barrier(controller);
            LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
            assertEquals(2, saved.candidateCount()); assertEquals(0, saved.pageCount());
            assertArrayEquals(new byte[]{1, 2, 3}, ((CaptureReviewStore)get(controller, "captureReview")).peek().jpeg);
            assertNull(saved.nextUnsent());
            // A newly loaded session cannot assume the still-running observer stopped without a missed scene.
            assertTrue(LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), id).captureGap());
            commitVisible(controller, surface);
            assertEquals(1, saved.pageCount());
            assertArrayEquals(second, ((CaptureReviewStore)get(controller, "captureReview")).peek().jpeg);
            assertEquals(1, saved.candidateCount());
        } finally { controller.close(); }
        Surface restoredSurface = new Surface(); restoredSurface.futureEnabled = true; restoredSurface.holdForPage = true;
        DocScanController restored = new DocScanController(context, restoredSurface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        try {
            restored.configureForLocalStart("http://phone:8000", "", 270); barrier(restored);
            set(restored, "localNetworkBusy", true);
            restored.showPendingCaptureReview(); barrier(restored);
            LocalCaptureSession saved = (LocalCaptureSession)get(restored, "localSession");
            assertEquals(id, saved.id());
            CaptureReviewStore.Pending pending = ((CaptureReviewStore)get(restored, "captureReview")).peek();
            assertEquals(b.captureId, pending.provenance.captureId);
            assertEquals(b.jpegSha256, pending.provenance.jpegSha256);
            assertEquals(b.imageTimestampNanos, pending.provenance.imageTimestampNanos);
            restored.confirmPendingCapture(); barrier(restored);
            assertEquals(1, saved.pageCount());
            commitVisible(restored, restoredSurface);
            assertEquals(2, saved.pageCount());
            assertEquals(c.captureId, ((CaptureReviewStore)get(restored, "captureReview")).peek().provenance.captureId);
            assertEquals("C is still unregistered", 2, saved.pageCount());
            commitVisible(restored, restoredSurface); assertEquals(3, saved.pageCount());
            assertArrayEquals(third, saved.read(saved.page(2)).jpeg);
        } finally { restored.close(); }
    }

    @Test public void overflowAndOldSceneCannotSilentlyFinishOrReplaceTheTwoPreservedCandidates() throws Exception {
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(RuntimeEnvironment.getApplication(), surface);
        try {
            surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
            assertTrue(surface.future.onCaptureStarting());
            surface.future.onCandidate(new byte[]{4, 5, 6}, nativeSource(new byte[]{4, 5, 6}, 200), true);
            barrier(controller);
            assertTrue(surface.future.onCaptureStarting());
            surface.future.onCandidate(new byte[]{7, 8, 9}, nativeSource(new byte[]{7, 8, 9}, 300), true);
            barrier(controller); surface.future.onPageMissed(); barrier(controller);
            LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
            assertTrue(saved.captureGap()); assertEquals(2, saved.candidateCount());
            controller.onGlassesAction(GlassesInputAction.BACK); barrier(controller);
            commitVisible(controller, surface); commitVisible(controller, surface); commitVisible(controller, surface);
            assertEquals(3, saved.pageCount());
            assertEquals(LocalCaptureSession.Phase.CAPTURE, saved.phase());
            assertEquals(RelayState.READING, controller.getState());
            assertTrue(saved.captureGap());
            controller.finishReading(); barrier(controller);
            assertEquals(LocalCaptureSession.Phase.CAPTURE, saved.phase());
            assertEquals(0, surface.photos);
        } finally { controller.close(); }
    }

    @Test public void aRetakeWaitsForTheNativeCandidateAndFailureFencesLateDeliveryWithoutErasingIt() throws Exception {
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(RuntimeEnvironment.getApplication(), surface);
        try {
            surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
            CaptureSurface.FuturePageListener future = surface.future;
            assertTrue(future.onCaptureStarting());
            surface.deferFutureStop = true;
            controller.onGlassesAction(GlassesInputAction.SHORT_TAP); barrier(controller);
            assertEquals("retake cannot overlap an already-issued future still", RelayState.CAPTURE_REVIEW, controller.getState());
            future.onCandidate(new byte[]{4, 5, 6}, nativeSource(new byte[]{4, 5, 6}, 200), true);
            barrier(controller); surface.futureStopped.run(); barrier(controller);
            assertEquals(RelayState.AIMING, controller.getState());
            LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
            assertEquals(1, saved.candidateCount()); assertEquals(0, saved.pageCount());
            controller.onPhotoError("native failure", null); barrier(controller);
            future.onCandidate(new byte[]{7, 8, 9}, nativeSource(new byte[]{7, 8, 9}, 300), true);
            barrier(controller);
            assertEquals(RelayState.ERROR, controller.getState()); assertEquals(2, saved.candidateCount());
            assertTrue(controller.isCaptureReconnectRequired());
            controller.onGlassesAction(GlassesInputAction.SHORT_TAP); barrier(controller);
            assertEquals(0, surface.photos); assertEquals(0, saved.pageCount());
        } finally { controller.close(); }
    }

    @Test public void anUnresolvedSceneOriginalIsVisibleButNeitherItsAckNorEndMayRegisterIt() throws Exception {
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(RuntimeEnvironment.getApplication(), surface);
        try {
            surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
            assertTrue(surface.future.onCaptureStarting());
            surface.future.onCandidate(new byte[]{4, 5, 6}, nativeSource(new byte[]{4, 5, 6}, 101), false);
            barrier(controller); commitVisible(controller, surface);
            LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
            assertEquals(1, saved.pageCount()); assertTrue(saved.captureGap());
            CaptureReviewStore.Pending held = ((CaptureReviewStore)get(controller, "captureReview")).peek();
            assertArrayEquals(new byte[]{4, 5, 6}, held.jpeg);
            controller.onGlassesAction(GlassesInputAction.BACK); barrier(controller);
            commitVisible(controller, surface); controller.confirmPendingCapture(); barrier(controller);
            assertEquals("finish cannot turn an unverified scene association into acceptance", 1, saved.pageCount());
            assertSame(held, ((CaptureReviewStore)get(controller, "captureReview")).peek());
            assertEquals(LocalCaptureSession.Phase.CAPTURE, saved.phase());
        } finally { controller.close(); }
    }

    @Test public void manualTapAfterCommitWaitsForIssuedFutureThenReviewsItsOriginal() throws Exception {
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(RuntimeEnvironment.getApplication(), surface);
        try {
            surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
            CaptureSurface.FuturePageListener future = surface.future;
            assertTrue(future.onCaptureStarting());
            surface.deferFutureStop = true;
            commitVisible(controller, surface);
            assertEquals(RelayState.READING, controller.getState());
            controller.captureNextPage(); barrier(controller);
            assertEquals("public capture cannot overlap the issued future still", RelayState.READING, controller.getState());
            controller.onGlassesAction(GlassesInputAction.SHORT_TAP); barrier(controller);
            assertEquals(RelayState.READING, controller.getState());
            assertNotNull(surface.futureStopped);
            Runnable stopped = surface.futureStopped;
            controller.onGlassesAction(GlassesInputAction.SHORT_TAP); barrier(controller);
            assertSame("repeated tap does not replace the first stop barrier", stopped, surface.futureStopped);
            byte[] second = {4, 5, 6};
            CaptureProvenance source = nativeSource(second, 200);
            future.onCandidate(second, source, true); barrier(controller);
            stopped.run(); barrier(controller);
            assertEquals(RelayState.CAPTURE_REVIEW, controller.getState());
            CaptureReviewStore.Pending pending = ((CaptureReviewStore)get(controller, "captureReview")).peek();
            assertEquals(source.captureId, pending.provenance.captureId);
            assertArrayEquals(second, pending.jpeg);
            assertEquals(1, pending.pageIndex);
            assertEquals(0, surface.photos);
            assertFalse(((CaptureLease)get(controller, "captureLease")).isUnresolved());
            commitVisible(controller, surface);
            assertEquals(2, ((LocalCaptureSession)get(controller, "localSession")).pageCount());
        } finally { controller.close(); }
    }

    @Test public void manualTapWhileFutureObserverIsIdleStillArmsOneVisibleShot() throws Exception {
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(RuntimeEnvironment.getApplication(), surface);
        try {
            commitVisible(controller, surface);
            assertTrue((boolean)get(controller, "futureWatching"));
            controller.onGlassesAction(GlassesInputAction.SHORT_TAP); barrier(controller);
            assertEquals(RelayState.AIMING, controller.getState());
            assertFalse((boolean)get(controller, "futureWatching"));
            assertFalse((boolean)get(controller, "futureStopping"));
            assertEquals(0, surface.photos); // The new guide must become visible first.
        } finally { controller.close(); }
    }

    private static CaptureProvenance nativeSource(byte[] jpeg, long timestamp) {
        return CaptureProvenance.nativeStill(jpeg, 4032, 3024, timestamp, timestamp, timestamp,
                10_000_000L, 100, 0, 2);
    }

    private static DocScanController localWithOriginal(Context context, Surface surface) throws Exception {
        DocScanController controller = new DocScanController(context, surface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        controller.configureForLocalStart("http://phone:8000", "", 270);
        controller.startLocalSession(false); barrier(controller);
        set(controller, "localNetworkBusy", true);
        ((CaptureLease)get(controller, "captureLease")).begin(0);
        set(controller, "state", RelayState.CAPTURING);
        controller.onPhoto(new byte[]{1, 2, 3}, nativeSource(new byte[]{1, 2, 3}, 100)); barrier(controller);
        return controller;
    }

    private static void commitVisible(DocScanController controller, Surface surface) throws Exception {
        surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
        org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(3));
        call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, (long)get(controller, "reviewGeneration"));
        barrier(controller);
    }

    @Test public void nativePhotoIdentitySurvivesRetakeVisibleReviewCommitAndRestart() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface();
        surface.holdForPage = true;
        DocScanController controller = new DocScanController(context, surface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        try {
            controller.configureForLocalStart("http://phone:8000", "", 270);
            controller.startLocalSession(false);
            barrier(controller);
            set(controller, "localNetworkBusy", true); // Test local persistence without a transfer.
            LocalCaptureSession session = (LocalCaptureSession)get(controller, "localSession");
            CaptureLease lease = (CaptureLease)get(controller, "captureLease");
            byte[] jpeg = {1, 2, 3}, retake = {4, 5, 6};
            CaptureProvenance first = CaptureProvenance.nativeStill(jpeg, 4032, 3024,
                    10L, 10L, 5L, 25_000_000L, 400, 0, 2);
            lease.begin(0);
            set(controller, "state", RelayState.CAPTURING);
            controller.onPhoto(jpeg, first);
            barrier(controller);
            CaptureReviewStore store = (CaptureReviewStore)get(controller, "captureReview");
            CaptureProvenance associatedFirst = store.peek().provenance;
            assertEquals(session.id(), associatedFirst.localSessionId);
            assertEquals(first.captureId, associatedFirst.captureId);
            assertEquals(0, associatedFirst.pageIndex);
            assertEquals(270, associatedFirst.rotationDegrees);
            long firstReview = (long)get(controller, "reviewGeneration");

            CaptureProvenance second = CaptureProvenance.nativeStill(retake, 4032, 3024,
                    20L, null, null, null, null, null, null);
            lease.begin(0);
            set(controller, "state", RelayState.CAPTURING);
            controller.onPhoto(retake, second);
            barrier(controller);
            CaptureReviewStore.Pending selected = store.peek();
            assertEquals(second.captureId, selected.provenance.captureId);
            assertNull(selected.provenance.exposureNanos);
            controller.onPhoto(jpeg, first); // Duplicate after completion has no capture lease.
            barrier(controller);
            assertSame(selected, store.peek());
            call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, firstReview);
            assertEquals(0, session.pageCount());
            assertEquals(selected.provenance, new CaptureReviewPersistence(
                    new File(session.directory(), "pending.bin")).readPending().provenance);

            surface.visible = true;
            controller.onCustomViewAvailable(1, "capture-review");
            barrier(controller);
            controller.confirmPendingCapture();
            barrier(controller);
            assertEquals("the existing visible 3s review still applies", 0, session.pageCount());
            org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(3));
            call(controller, "enqueueAutoCommit", new Class<?>[]{long.class}, (long)get(controller, "reviewGeneration"));
            barrier(controller);
            LocalCaptureSession restarted = LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), session.id());
            assertEquals(1, restarted.pageCount());
            CaptureReviewStore.Pending restored = restarted.read(restarted.nextUnsent());
            assertArrayEquals(retake, restored.jpeg);
            assertEquals(selected.provenance, restored.provenance);
            assertNotEquals(associatedFirst.captureId, restored.provenance.captureId);
        } finally { controller.close(); }
    }

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
                restarted.setCaptureInspectionContextProvider(() -> new CaptureInspectionOrigin.Context("new-run", 999));
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

    @Test public void comparisonBindingReadsOnlyTheCurrentDurableLocalIdentityWithoutCreatingServerIds() throws Exception {
        Context context=RuntimeEnvironment.getApplication();
        File root=new File(context.getFilesDir(),"local-scans");
        try (MockWebServer server=new MockWebServer()) {
            String address=server.url("/").toString().replaceAll("/+$","");
            LocalCaptureSession saved=LocalCaptureSession.create(root,address,false);
            DocScanController controller=new DocScanController(context,new Surface(),null,
                    (state,lines,diagnostic) -> {},new ClientIdentity("test","test","test"));
            try {
                controller.configureForLocalStart(address,"",270); barrier(controller);
                set(controller,"localSession",saved);
                var first=controller.localCaptureBinding(); assertNotNull(first);
                assertEquals(saved.id(),first.localId); assertEquals(0,first.documentId); assertEquals(0,first.sessionId);
                saved.bindDocument(9); saved.bindSession(7);
                var bound=controller.localCaptureBinding(); assertEquals(first.localId,bound.localId);
                assertEquals(9,bound.documentId); assertEquals(7,bound.sessionId); assertSame(controller.api(),bound.api);
                assertEquals(0,first.documentId); // immutable snapshot, no invented first binding
                set(controller,"localSession",LocalCaptureSession.create(root,"http://other.invalid",false));
                assertNull(controller.localCaptureBinding());
                set(controller,"localSession",saved); saved.close();
                assertNull(controller.localCaptureBinding()); assertEquals(0,server.getRequestCount());
            } finally { controller.close(); }
            assertNull(controller.localCaptureBinding());
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

    @Test public void automaticReadingStillCapturesAPageAfterThirtySecondsWithoutAChange() throws Exception {
        Surface surface = new Surface();
        surface.holdForPage = true;
        DocScanController controller = waitingLocalController(surface);
        ClockedWatchdog clock = installClockedWatchdog(controller);
        try {
            controller.startLocalSession(false); barrier(controller);
            assertNotNull(surface.pageReady);
            int pausesBeforeWaiting = surface.pauses;
            clock.advanceBy(controller, 31_000);
            assertEquals("waiting for a page must keep observation active", pausesBeforeWaiting, surface.pauses);
            assertTrue(controller.isAutoCaptureEnabled());
            assertEquals(0, surface.photos);

            captureObservedPage(controller, surface, clock);
            assertEquals(RelayState.CAPTURING, controller.getState());
            assertEquals("a page change takes one photo without a resume tap", 1, surface.photos);
        } finally { controller.close(); }
    }

    @Test public void finishedCaptureDoesNotResumeOnALatePageAfterThirtySeconds() throws Exception {
        Surface surface = new Surface();
        surface.holdForPage = true;
        DocScanController controller = waitingLocalController(surface);
        ClockedWatchdog clock = installClockedWatchdog(controller);
        try {
            controller.startLocalSession(false); barrier(controller);
            Runnable latePage = surface.pageReady;
            controller.onGlassesAction(GlassesInputAction.BACK); barrier(controller);
            assertTrue((boolean)get(controller, "finishCaptureRequested"));
            assertFalse(controller.isAutoCaptureEnabled());
            int pausesAfterFinishing = surface.pauses;
            clock.advanceBy(controller, 31_000);
            latePage.run(); barrier(controller);
            assertEquals(0, surface.photos);
            assertEquals(pausesAfterFinishing, surface.pauses);
            assertTrue((boolean)get(controller, "finishCaptureRequested"));
        } finally { controller.close(); }
    }

    @Test public void stoppedOrClosedCaptureDoesNotResumeOnALatePageAfterThirtySeconds() throws Exception {
        Surface surface = new Surface();
        surface.holdForPage = true;
        DocScanController controller = waitingLocalController(surface);
        ClockedWatchdog clock = installClockedWatchdog(controller);
        try {
            controller.startLocalSession(false); barrier(controller);
            Runnable latePage = surface.pageReady;
            controller.stopAutoCapture(); barrier(controller);
            clock.advanceBy(controller, 31_000);
            latePage.run(); barrier(controller);
            assertFalse(controller.isAutoCaptureEnabled());
            assertEquals(RelayState.READY, controller.getState());
            assertEquals(0, surface.photos);
            controller.close();
            latePage.run();
            assertEquals(0, surface.photos);
        } finally { controller.close(); }
    }

    @Test public void unknownCaptureDoesNotShootAgainAfterThirtySecondsAndALatePage() throws Exception {
        Surface surface = new Surface();
        surface.holdForPage = true;
        surface.photoStart = CaptureSurface.PhotoStartResult.UNKNOWN;
        DocScanController controller = waitingLocalController(surface);
        ClockedWatchdog clock = installClockedWatchdog(controller);
        try {
            controller.startLocalSession(false); barrier(controller);
            Runnable latePage = surface.pageReady;
            captureObservedPage(controller, surface, clock);
            assertEquals(1, surface.photos);
            assertEquals(RelayState.ERROR, controller.getState());
            assertTrue(controller.isCaptureReconnectRequired());
            clock.advanceBy(controller, 31_000);
            latePage.run(); barrier(controller);
            assertEquals(1, surface.photos);
            assertFalse(controller.isAutoCaptureEnabled());
            assertTrue(controller.isCaptureReconnectRequired());
        } finally { controller.close(); }
    }

    @Test public void missingPhotoStillTimesOutAndDoesNotRestartOnALatePage() throws Exception {
        Surface surface = new Surface();
        surface.holdForPage = true;
        DocScanController controller = waitingLocalController(surface);
        ClockedWatchdog clock = installClockedWatchdog(controller);
        try {
            controller.startLocalSession(false); barrier(controller);
            Runnable latePage = surface.pageReady;
            captureObservedPage(controller, surface, clock);
            assertEquals(RelayState.CAPTURING, controller.getState());
            clock.advanceBy(controller, 31_000);
            assertEquals(RelayState.ERROR, controller.getState());
            assertTrue(controller.isCaptureReconnectRequired());
            latePage.run(); barrier(controller);
            assertEquals(1, surface.photos);
            assertFalse(controller.isAutoCaptureEnabled());
        } finally { controller.close(); }
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

    @Test public void failedGapWriteCannotEraseAnObservedMissingSceneOnRestart() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(context, surface);
        LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
        File blocker = new File(saved.directory(), "state.properties.tmp");
        try {
            surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
            assertTrue(surface.future.onCaptureStarting());
            surface.future.onCandidate(new byte[]{4, 5, 6}, nativeSource(new byte[]{4, 5, 6}, 200), true);
            barrier(controller);
            assertTrue(surface.future.onCaptureStarting());
            surface.future.onCandidate(new byte[]{7, 8, 9}, nativeSource(new byte[]{7, 8, 9}, 300), true);
            barrier(controller);
            assertFalse(saved.captureGap()); assertEquals(2, saved.candidateCount());
            assertTrue(blocker.mkdir());
            surface.future.onPageMissed(); barrier(controller);
            assertTrue(controller.isCaptureReconnectRequired());
            controller.finishReading(); barrier(controller);
            assertEquals(LocalCaptureSession.Phase.CAPTURE, saved.phase());
        } finally {
            controller.close();
            assertEquals(0, java.util.Objects.requireNonNull(blocker.list()).length);
            java.nio.file.Files.delete(blocker.toPath());
        }
        LocalCaptureSession restored = LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), saved.id());
        assertTrue("gap-write failure must not erase a missed scene", restored.captureGap());
        assertEquals(2, restored.candidateCount()); assertNull(restored.nextUnsent());
    }

    @Test public void futurePreparationUnknownBeforeNativeIssueRemainsUnresolvedOnRestart() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(context, surface);
        LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
        try {
            surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
            assertNotNull(surface.future);
            // The observer may already be preparing B; no native onCaptureStarting has occurred.
            controller.onPhotoError("future scene changed during preparation", null); barrier(controller);
            assertTrue(controller.isCaptureReconnectRequired());
            controller.finishReading(); barrier(controller);
            assertEquals(LocalCaptureSession.Phase.CAPTURE, saved.phase());
            assertEquals(0, saved.candidateCount()); assertEquals(0, surface.photos);
        } finally { controller.close(); }
        LocalCaptureSession restored = LocalCaptureSession.load(new File(context.getFilesDir(), "local-scans"), saved.id());
        assertTrue("preparation failure is unresolved even before a native request was issued", restored.captureGap());
        assertNull(restored.nextUnsent());
    }

    @Test public void futureObservationIsResolvedOnlyAfterItsSuccessfulIdleBarrier() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        Surface surface = new Surface(); surface.futureEnabled = true; surface.holdForPage = true;
        DocScanController controller = localWithOriginal(context, surface);
        LocalCaptureSession saved = (LocalCaptureSession)get(controller, "localSession");
        File root = new File(context.getFilesDir(), "local-scans");
        try {
            surface.visible = true; controller.onCustomViewAvailable(1, "capture-review"); barrier(controller);
            surface.deferFutureStop = true;
            call(controller, "stopFutureObservation", new Class<?>[]{Runnable.class}, (Runnable)() -> {});
            barrier(controller);
            assertTrue("an unacknowledged stop is still unresolved", LocalCaptureSession.load(root, saved.id()).captureGap());
            assertNotNull(surface.futureStopped); surface.futureStopped.run(); barrier(controller);
            assertFalse("a normal idle stop needs no recapture", LocalCaptureSession.load(root, saved.id()).captureGap());
        } finally { controller.close(); }
        assertFalse("a later close cannot restore a resolved observation", LocalCaptureSession.load(root, saved.id()).captureGap());
    }

    @Test public void aNativeUploadWithoutItsReceiptRemainsUnsentAfterRestart() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        File root = new File(context.getFilesDir(), "local-scans");
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody("{\"document_id\":17,\"page_index\":0}"));
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession saved = LocalCaptureSession.create(root, address, false);
            saved.bindDocument(17);
            byte[] jpeg = {1, 2, 3};
            CaptureProvenance source = nativeSource(jpeg, 100).bind(saved.id(), 0, 270);
            saved.commit(new CaptureReviewStore.Pending(0, jpeg, "", 270, "", PageFraming.UNKNOWN, 1000L, source));
            Surface surface = new Surface(); surface.holdForPage = true;
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(address, "", 270); barrier(controller);
                controller.resumeLocalSession(saved.id()); barrier(controller);
                ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
                barrier(controller);
                LocalCaptureSession restored = LocalCaptureSession.load(root, saved.id());
                assertNotNull("HTTP success without the native receipt must not acknowledge the original", restored.nextUnsent());
                assertEquals(source, restored.read(restored.nextUnsent()).provenance);
                assertArrayEquals(jpeg, restored.read(restored.nextUnsent()).jpeg);
                assertEquals(RelayState.ERROR, controller.getState());
                assertEquals(1, server.getRequestCount());
            } finally { controller.close(); }
        }
    }

    @Test public void nativeUploadResumesWithTheSameOriginalAndCaptureIdentity() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        File root = new File(context.getFilesDir(), "local-scans");
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody("{}"));
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession saved = LocalCaptureSession.create(root, address, false);
            saved.bindDocument(17);
            byte[] jpeg = {1, 2, 3};
            CaptureProvenance source = CaptureProvenance.nativeStill(jpeg, 4032, 3024,
                    100L, null, null, null, null, null, null).bind(saved.id(), 0, 270);
            saved.commit(new CaptureReviewStore.Pending(0, jpeg, "", 270, "", PageFraming.UNKNOWN, 1000L, source));
            Surface surface = new Surface(); surface.holdForPage = true;
            DocScanController first = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            RecordedRequest attempted;
            try {
                first.configureForLocalStart(address, "", 270); barrier(first);
                first.resumeLocalSession(saved.id()); waitForUpload(first);
                assertNotNull(LocalCaptureSession.load(root, saved.id()).nextUnsent());
                attempted = server.takeRequest(5, TimeUnit.SECONDS);
                assertNotNull(attempted);
            } finally { first.close(); }
            JSONObject metadata = new JSONObject(new String(uploadPart(attempted, "capture_provenance"), StandardCharsets.UTF_8));
            assertEquals(source.captureId, metadata.getString("capture_id"));
            assertEquals(source.jpegSha256, metadata.getString("jpeg_sha256"));
            assertEquals(saved.id(), metadata.getString("local_session_id"));
            assertSame(JSONObject.NULL, metadata.get("result_timestamp_ns"));
            server.enqueue(new MockResponse().setBody(new JSONObject().put("document_id", 17).put("page_index", 0)
                    .put("capture_provenance", metadata).put("canonical_image_sha256", "c".repeat(64)).toString()));
            DocScanController restarted = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                restarted.configureForLocalStart(address, "", 270); barrier(restarted);
                restarted.resumeLocalSession(saved.id()); waitForUpload(restarted);
                assertNull(LocalCaptureSession.load(root, saved.id()).nextUnsent());
                RecordedRequest retry = server.takeRequest(5, TimeUnit.SECONDS);
                assertNotNull(retry);
                assertArrayEquals(uploadPart(attempted, "capture_provenance"), uploadPart(retry, "capture_provenance"));
                assertArrayEquals(jpeg, uploadPart(retry, "image"));
                assertFalse("restored original must not borrow the current display generation",
                        retry.getBody().clone().readUtf8().contains("name=\"inspection_origin\""));
                assertEquals(2, server.getRequestCount());
            } finally { restarted.close(); }
        }
    }

    @Test public void anOldHttpReceiptCannotAcknowledgeANewerNativeRevisionOfTheSamePixels() throws Exception {
        Context context = RuntimeEnvironment.getApplication();
        File root = new File(context.getFilesDir(), "local-scans");
        CountDownLatch uploading = new CountDownLatch(1), release = new CountDownLatch(1);
        java.util.concurrent.atomic.AtomicReference<String> oldReceipt = new java.util.concurrent.atomic.AtomicReference<>();
        try (MockWebServer server = new MockWebServer()) {
            server.setDispatcher(new Dispatcher() {
                @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                    uploading.countDown(); release.await(5, TimeUnit.SECONDS);
                    return new MockResponse().setBody(oldReceipt.get());
                }
            });
            String address = server.url("/").toString().replaceAll("/+$", "");
            LocalCaptureSession saved = LocalCaptureSession.create(root, address, false);
            saved.bindDocument(17);
            byte[] jpeg = {1, 2, 3};
            CaptureProvenance firstSource = nativeSource(jpeg, 100).bind(saved.id(), 0, 270);
            saved.commit(new CaptureReviewStore.Pending(0, jpeg, "", 270, "", PageFraming.UNKNOWN, 1000L, firstSource));
            LocalCaptureSession.Page firstRevision = saved.nextUnsent();
            Surface surface = new Surface(); surface.holdForPage = true;
            DocScanController controller = new DocScanController(context, surface, null,
                    (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
            try {
                controller.configureForLocalStart(address, "", 270); barrier(controller);
                controller.resumeLocalSession(saved.id()); barrier(controller);
                assertTrue(uploading.await(5, TimeUnit.SECONDS));
                RecordedRequest firstRequest = server.takeRequest(5, TimeUnit.SECONDS);
                JSONObject firstMetadata = new JSONObject(new String(uploadPart(firstRequest, "capture_provenance"), StandardCharsets.UTF_8));
                oldReceipt.set(new JSONObject().put("document_id", 17).put("page_index", 0)
                        .put("capture_provenance", firstMetadata).put("canonical_image_sha256", "c".repeat(64)).toString());
                LocalCaptureSession active = (LocalCaptureSession)get(controller, "localSession");
                CaptureProvenance retake = nativeSource(jpeg, 200).bind(saved.id(), 0, 270);
                active.commit(new CaptureReviewStore.Pending(0, jpeg, "", 270, "", PageFraming.UNKNOWN, 2000L, retake));
                assertNotEquals(firstRevision.fileName, active.nextUnsent().fileName);
                release.countDown(); waitForUpload(controller);
                LocalCaptureSession restored = LocalCaptureSession.load(root, saved.id());
                assertNotNull("the old receipt must leave the newer revision unacknowledged", restored.nextUnsent());
                assertEquals(retake, restored.read(restored.nextUnsent()).provenance);
                assertEquals(firstSource, restored.read(firstRevision).provenance);
                RecordedRequest secondRequest = server.takeRequest(5, TimeUnit.SECONDS);
                JSONObject secondMetadata = new JSONObject(new String(uploadPart(secondRequest, "capture_provenance"), StandardCharsets.UTF_8));
                assertEquals(retake.captureId, secondMetadata.getString("capture_id"));
                assertNotEquals(firstMetadata.getString("capture_id"), secondMetadata.getString("capture_id"));
                assertArrayEquals(jpeg, uploadPart(secondRequest, "image"));
                assertEquals(RelayState.ERROR, controller.getState());
                assertEquals(2, server.getRequestCount());
            } finally { release.countDown(); controller.close(); }
        }
    }

    private static void waitForUpload(DocScanController controller) throws Exception {
        barrier(controller);
        ((ExecutorService)get(controller, "localNetwork")).submit(() -> {}).get(5, TimeUnit.SECONDS);
        barrier(controller);
    }

    private static byte[] uploadPart(RecordedRequest request, String name) {
        assertNotNull(request);
        String boundary = request.getHeader("Content-Type").split("boundary=", 2)[1];
        String body = request.getBody().clone().readString(StandardCharsets.ISO_8859_1);
        int header = body.indexOf("Content-Disposition: form-data; name=\"" + name + "\"");
        assertTrue("multipart field missing: " + name, header >= 0);
        int start = body.indexOf("\r\n\r\n", header) + 4;
        int end = body.indexOf("\r\n--" + boundary, start);
        assertTrue(end >= start);
        return body.substring(start, end).getBytes(StandardCharsets.ISO_8859_1);
    }

    private static final class Surface implements CaptureSurface {
        boolean futureEnabled;
        boolean deferFutureStop;
        FuturePageListener future;
        Runnable futureStopped;
        public boolean supportsFuturePages() { return futureEnabled; }
        public void observeFuturePages(int capacity, FuturePageListener listener) { future = listener; }
        public void stopFuturePages(Runnable idle) { if (deferFutureStop) futureStopped = idle; else idle.run(); }
        boolean visible;
        int photos;
        int pauses;
        boolean holdForPage;
        Runnable pageReady;
        PhotoStartResult photoStart = PhotoStartResult.STARTED;
        public void awaitNextPage(Runnable ready) { if (holdForPage) pageReady = ready; else ready.run(); }
        public void pausePreview() { pauses++; }
        public boolean supportsLocalCaptureReview() { return true; }
        public boolean isCaptureReviewVisible(long generation) { return visible && generation == 1; }
        public PhotoStartResult takePhoto(int w, int h, int q) { photos++; return photoStart; }
        public long showHud(List<String> lines) { return 2; }
        public long showCaptureAiming(int page, boolean retake, boolean stable) { return 3; }
        public long showCaptureReview(byte[] jpeg, int rotation, List<String> lines) { return 1; }
        public void fenceCustomViewEpoch(long generation, String reason) { }
    }

    private static DocScanController waitingLocalController(Surface surface) throws Exception {
        DocScanController controller = new DocScanController(RuntimeEnvironment.getApplication(), surface, null,
                (state, lines, diagnostic) -> {}, new ClientIdentity("test", "test", "test"));
        controller.configureForLocalStart("http://phone:8000", "", 270); barrier(controller);
        return controller;
    }

    private static void captureObservedPage(DocScanController controller, Surface surface, ClockedWatchdog clock) throws Exception {
        surface.pageReady.run(); barrier(controller);
        assertEquals(RelayState.AIMING, controller.getState());
        controller.onCustomViewAvailable(3, "capture-aiming"); barrier(controller);
        assertEquals(RelayState.STABILIZING, controller.getState());
        controller.onCustomViewAvailable(3, "capture-stabilizing"); barrier(controller);
        clock.advanceBy(controller, 1500);
    }

    private static ClockedWatchdog installClockedWatchdog(DocScanController controller) throws Exception {
        ((ExecutorService)get(controller, "watchdog")).shutdownNow();
        ClockedWatchdog clock = new ClockedWatchdog();
        set(controller, "watchdog", clock);
        return clock;
    }

    /** Runs the real controller's delayed callbacks against the same clock as its deadlines. */
    private static final class ClockedWatchdog extends ScheduledThreadPoolExecutor {
        private final java.util.Map<ScheduledFuture<?>, Long> deadlines = new java.util.LinkedHashMap<>();
        ClockedWatchdog() { super(1); }
        @Override public synchronized ScheduledFuture<?> schedule(Runnable task, long delay, TimeUnit unit) {
            ScheduledFuture<?> future = super.schedule(task, 1, TimeUnit.DAYS);
            deadlines.put(future, android.os.SystemClock.elapsedRealtime() + unit.toMillis(delay));
            return future;
        }
        void advanceBy(DocScanController controller, long millis) throws Exception {
            org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMillis(millis));
            java.util.List<Runnable> ready = new java.util.ArrayList<>();
            synchronized (this) {
                deadlines.entrySet().removeIf(entry -> {
                    if (entry.getValue() > android.os.SystemClock.elapsedRealtime()) return false;
                    ready.add((Runnable)entry.getKey());
                    return true;
                });
            }
            for (Runnable task : ready) task.run();
            barrier(controller);
        }
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
