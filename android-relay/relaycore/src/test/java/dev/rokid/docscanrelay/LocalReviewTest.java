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
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

/** Exercises the real controller: no unseen photo, no stale timer after a retake. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class LocalReviewTest {
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
