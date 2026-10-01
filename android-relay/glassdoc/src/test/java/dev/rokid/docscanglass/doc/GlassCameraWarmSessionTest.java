package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;
import static android.hardware.camera2.CameraMetadata.*;

import android.graphics.ImageFormat;
import android.hardware.camera2.*;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.DocScanTestImage;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Size;
import android.view.Surface;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.Implementation;
import org.robolectric.annotation.Implements;
import org.robolectric.shadow.api.Shadow;
import org.robolectric.shadows.ShadowCaptureResult;
import org.robolectric.shadows.ShadowTotalCaptureResult;
import org.robolectric.util.ReflectionHelpers;

/** Runs the real preview -> metering -> JPEG path against a fake HAL, never a camera. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE, shadows = {GlassCameraWarmSessionTest.ManagerShadow.class,
        GlassCameraWarmSessionTest.CharacteristicsShadow.class, GlassCameraWarmSessionTest.MapShadow.class,
        GlassCameraWarmSessionTest.ReaderShadow.class, GlassCameraWarmSessionTest.BuilderShadow.class,
        GlassCameraWarmSessionTest.RequestShadow.class})
public class GlassCameraWarmSessionTest {
    private GlassCamera camera;
    private final List<String> failures = new ArrayList<>();
    private int delivered;

    @Before public void setup() {
        ManagerShadow.devices.clear(); ReaderShadow.readers.clear();
        ManagerShadow.refuseSession = false; CharacteristicsShadow.fixedFocus = false;
        CharacteristicsShadow.afMode = CONTROL_AF_MODE_CONTINUOUS_PICTURE;
        camera = new GlassCamera(RuntimeEnvironment.getApplication(), new Handler(Looper.getMainLooper()),
                new GlassCamera.Callback() {
                    @Override public void onCaptured(byte[] bytes, int w, int h, long elapsed) {
                        assertEquals(4032, w); assertEquals(3024, h); delivered++;
                    }
                    @Override public void onCaptureFailed(String reason) { failures.add(reason); }
                });
    }
    private void idle(long millis) { shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(millis)); }
    private DocScanTestCamera firstDevice() { return ManagerShadow.devices.get(0); }
    private DocScanTestCamera currentDevice() { return ManagerShadow.devices.get(ManagerShadow.devices.size() - 1); }
    private ReaderShadow originalReader(int format) {
        return ReaderShadow.readers.stream().filter(r -> r.format == format).findFirst().orElseThrow();
    }
    private ReaderShadow currentReader(int format) {
        return ReaderShadow.readers.stream().filter(r -> r.format == format && !r.closed).findFirst().orElseThrow();
    }
    private void frame(int value) { frame(value, false); }
    private void frame(int value, boolean turning) {
        ReaderShadow reader = currentReader(ImageFormat.YUV_420_888);
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
        image.format = ImageFormat.YUV_420_888; image.width = 32; image.height = 24;
        image.rowStride = 32; image.pixelStride = 1;
        byte[] pixels = new byte[32 * 24]; java.util.Arrays.fill(pixels, (byte) value);
        if (turning) java.util.Arrays.fill(pixels, 0, pixels.length / 3, (byte) 70);
        image.timestamp = SystemClock.elapsedRealtimeNanos();
        image.buffer = ByteBuffer.wrap(pixels); reader.image = image;
        reader.listener.onImageAvailable(reader.reader);
    }
    private void result(int af, int ae) { result(af, ae, SystemClock.elapsedRealtimeNanos()); }
    private void result(int af, int ae, long sensorTimestamp) {
        var session = currentDevice().session;
        session.previewCallback.onCaptureCompleted(session, session.repeating, metadata(af, ae, sensorTimestamp));
    }
    private TotalCaptureResult metadata(int af, int ae, long sensorTimestamp) {
        TotalCaptureResult result = ShadowTotalCaptureResult.newTotalCaptureResult();
        ShadowCaptureResult values = Shadow.extract(result);
        values.set(CaptureResult.CONTROL_AF_STATE, af); values.set(CaptureResult.CONTROL_AE_STATE, ae);
        values.set(CaptureResult.SENSOR_TIMESTAMP, sensorTimestamp);
        assertEquals(Integer.valueOf(af), result.get(CaptureResult.CONTROL_AF_STATE));
        assertEquals(Integer.valueOf(ae), result.get(CaptureResult.CONTROL_AE_STATE));
        return result;
    }
    private void readyFrame() { idle(100); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); }

    @Test public void autoOnlyHardwareStartsFocusBeforeTheFirstAutomaticPageCallback() {
        firstAutomaticPage(CONTROL_AF_MODE_AUTO);
    }

    @Test public void macroOnlyHardwareStartsFocusBeforeTheFirstAutomaticPageCallback() {
        firstAutomaticPage(CONTROL_AF_MODE_MACRO);
    }

    private void firstAutomaticPage(int mode) {
        CharacteristicsShadow.afMode = mode;
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(() -> { ready.incrementAndGet(); camera.captureOnce(); });
        idle(100); result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(0, currentDevice().session.captures);
        idle(400); result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); frame(180);
        finishAutoFocusThenOneJpeg(mode, ready);
        assertEquals(1, ManagerShadow.devices.size()); assertTrue(failures.isEmpty());
    }

    @Test public void autoOnlyHardwareStartsFreshFocusAfterAReviewPageTurn() {
        nextAutomaticPage(CONTROL_AF_MODE_AUTO);
    }

    @Test public void macroOnlyHardwareStartsFreshFocusAfterAReviewPageTurn() {
        nextAutomaticPage(CONTROL_AF_MODE_MACRO);
    }

    private void nextAutomaticPage(int mode) {
        CharacteristicsShadow.afMode = mode;
        // A manual first shot reaches the review/new-preview seam even before C1 is fixed.
        camera.captureOnce(); idle(100); frame(180); idle(400); frame(180);
        var first = currentDevice().session;
        assertEquals(1, first.captures);
        first.captureCallback.onCaptureCompleted(first, first.captured,
                metadata(CONTROL_AF_STATE_ACTIVE_SCAN, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        idle(100); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(2, first.captures);
        ReaderShadow jpeg = currentReader(ImageFormat.JPEG);
        jpeg.image = new DocScanTestImage(new ArrayList<>()); jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
        assertEquals(1, delivered); assertEquals(2, ManagerShadow.devices.size());

        // The turn happens during review, before awaitNextPage is registered.
        idle(100); frame(180); idle(100); frame(180, true); idle(100); frame(180);
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(() -> { ready.incrementAndGet(); camera.captureOnce(); }); idle(0);
        assertEquals(0, currentDevice().session.captures);
        idle(400); result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); frame(180);
        finishAutoFocusThenOneJpeg(mode, ready);
        assertEquals(2, ManagerShadow.devices.size()); assertTrue(failures.isEmpty());
    }

    private void finishAutoFocusThenOneJpeg(int mode, AtomicInteger ready) {
        var session = currentDevice().session;
        assertEquals("one AF START before pageReady", 1, session.captures);
        RequestShadow trigger = Shadow.extract(session.captured);
        assertEquals(CameraDevice.TEMPLATE_PREVIEW, trigger.template);
        assertEquals(mode, trigger.values.get(CaptureRequest.CONTROL_AF_MODE.getName()));
        assertEquals(CONTROL_AF_TRIGGER_START, trigger.values.get(CaptureRequest.CONTROL_AF_TRIGGER.getName()));
        var triggerRequest = session.captured;
        var triggerCallback = session.captureCallback;
        assertEquals(0, ready.get());

        // A pre-trigger locked result, even delivered now, cannot acknowledge this START.
        idle(100);
        long oldLockedAt = SystemClock.elapsedRealtimeNanos();
        result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED, oldLockedAt); frame(180);
        assertEquals(0, ready.get()); assertEquals(1, session.captures);
        idle(100);
        triggerCallback.onCaptureCompleted(session, triggerRequest,
                metadata(CONTROL_AF_STATE_ACTIVE_SCAN, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        idle(100); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED, oldLockedAt); frame(180);
        assertEquals(0, ready.get()); assertEquals(1, session.captures);
        idle(100); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_SEARCHING); frame(180);
        assertEquals(0, ready.get()); assertEquals(1, session.captures);
        idle(100); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, ready.get()); assertEquals(2, session.captures);
        assertEquals(CameraDevice.TEMPLATE_STILL_CAPTURE, ((RequestShadow)Shadow.extract(session.captured)).template);
        assertEquals(1, currentDevice().configurations);
    }

    @Test public void warmedPreviewFocusAndLargestJpegUseOneDeviceAndOneSession() {
        camera.preview(); idle(100); readyFrame();
        DocScanTestCamera device = firstDevice();
        camera.captureOnce(); camera.captureOnce(); idle(400); readyFrame(); idle(50);
        assertEquals(1, ManagerShadow.devices.size()); assertEquals(1, device.configurations);
        assertEquals(2, device.outputs.size()); assertEquals(1, device.session.captures);
        assertFalse(device.closed); assertTrue(device.session.repeatingStopped);
        RequestShadow request = Shadow.extract(device.session.captured);
        assertEquals(CameraDevice.TEMPLATE_STILL_CAPTURE, request.template);
        assertEquals(0, request.values.get(CaptureRequest.JPEG_ORIENTATION.getName()));
        assertEquals(CONTROL_AF_MODE_CONTINUOUS_PICTURE, request.values.get(CaptureRequest.CONTROL_AF_MODE.getName()));
        assertEquals(List.of(originalReader(ImageFormat.JPEG).surface), request.targets);
        ReaderShadow jpeg = originalReader(ImageFormat.JPEG);
        jpeg.image = new DocScanTestImage(new ArrayList<>());
        jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
        assertEquals(1, delivered); assertTrue(device.closed); assertTrue(jpeg.closed);
        assertTrue(originalReader(ImageFormat.YUV_420_888).closed);
        assertTrue(failures.isEmpty());
    }

    @Test public void aColdManualShotAlsoWaitsForFreshStablePreviewAndMetering() {
        CharacteristicsShadow.fixedFocus = true;
        camera.captureOnce(); idle(100); frame(180); idle(500);
        assertEquals(0, firstDevice().session.captures);
        result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, firstDevice().session.captures); assertEquals(1, ManagerShadow.devices.size());
        assertEquals(CONTROL_AF_MODE_OFF, ((RequestShadow)Shadow.extract(firstDevice().session.captured))
                .values.get(CaptureRequest.CONTROL_AF_MODE.getName()));
    }

    @Test public void waitingForFocusKeepsTheObservedPageTurnLatched() {
        camera.preview(); idle(100); readyFrame();
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange"); pages.consumed();
        AtomicInteger ready = new AtomicInteger(); camera.awaitNextPage(ready::incrementAndGet); idle(0);
        idle(100); result(CONTROL_AF_STATE_PASSIVE_SCAN, CONTROL_AE_STATE_CONVERGED); frame(180, true);
        idle(100); frame(180); idle(400);
        result(CONTROL_AF_STATE_PASSIVE_SCAN, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(0, ready.get());
        readyFrame(); assertEquals(1, ready.get()); readyFrame(); assertEquals(1, ready.get());
        assertEquals(0, firstDevice().session.captures);
    }

    @Test public void missingReadinessTimesOutWithoutShootingAndLateResultsCannotRetry() {
        camera.captureOnce(); idle(100); frame(180); idle(9900);
        assertEquals(List.of("camera not still or AF/AE not ready"), failures);
        assertEquals(0, firstDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED);
        camera.captureOnce(); idle(1000);
        assertEquals(1, ManagerShadow.devices.size()); assertEquals(0, delivered);
        assertTrue(firstDevice().closed); assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
    }

    @Test public void aRefusedTwoOutputSessionStopsWithoutAColdJpegFallback() {
        ManagerShadow.refuseSession = true;
        camera.captureOnce(); idle(10000);
        assertEquals(1, failures.size()); assertEquals(1, ManagerShadow.devices.size());
        assertEquals(0, firstDevice().session.captures); assertTrue(firstDevice().closed);
        assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
    }

    @Test public void aLateOldSensorResultCannotBecomeFreshMeteringForTheCurrentFrame() {
        camera.captureOnce(); idle(100); frame(180); idle(1100);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, 10L);
        frame(180); idle(50);
        assertEquals(0, firstDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); idle(100); frame(180); idle(50);
        assertEquals(1, firstDevice().session.captures);
    }

    @Test public void aMissingJpegCannotBeFollowedByAnotherPhotoOrARecoveryFromLateMetadata() {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        DocScanTestCamera device = firstDevice();
        assertEquals(1, device.session.captures);
        var lateCallback = device.session.captureCallback;
        var request = device.session.captured;
        idle(15000); assertEquals(List.of("CAMERA TIMEOUT"), failures);
        lateCallback.onCaptureCompleted(device.session, request, null);
        camera.captureOnce(); idle(1000);
        assertEquals(1, device.session.captures); assertEquals(1, ManagerShadow.devices.size());
        assertEquals(0, delivered); assertTrue(device.closed);
        assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
    }

    @Implements(CameraManager.class) public static class ManagerShadow {
        static final List<DocScanTestCamera> devices = new ArrayList<>();
        static boolean refuseSession;
        @Implementation protected String[] getCameraIdList() { return new String[]{"0"}; }
        @Implementation protected CameraCharacteristics getCameraCharacteristics(String id) { return Shadow.newInstanceOf(CameraCharacteristics.class); }
        @Implementation protected void openCamera(String id, CameraDevice.StateCallback callback, Handler h) {
            DocScanTestCamera device = new DocScanTestCamera(template -> {
                CaptureRequest.Builder b = Shadow.newInstanceOf(CaptureRequest.Builder.class);
                ((BuilderShadow)Shadow.extract(b)).template = template; return b;
            });
            device.handler = h; device.state = callback; device.refuseSession = refuseSession;
            devices.add(device); h.post(() -> callback.onOpened(device));
        }
    }
    @Implements(CameraCharacteristics.class) public static class CharacteristicsShadow {
        static boolean fixedFocus;
        static int afMode;
        @Implementation protected <T> T get(CameraCharacteristics.Key<T> key) {
            Object value = key.equals(CameraCharacteristics.LENS_FACING) ? LENS_FACING_BACK
                    : key.equals(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ? Shadow.newInstanceOf(StreamConfigurationMap.class)
                    : key.equals(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES) ? new int[]{CONTROL_AF_MODE_OFF, afMode}
                    : key.equals(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES) ? new int[]{CONTROL_AE_MODE_ON}
                    : key.equals(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE) ? fixedFocus ? 0f : 8f : null;
            @SuppressWarnings("unchecked") T typed = (T)value; return typed;
        }
    }
    @Implements(StreamConfigurationMap.class) public static class MapShadow {
        @Implementation protected Size[] getOutputSizes(int format) {
            return new Size[]{format == ImageFormat.JPEG ? new Size(4032, 3024) : new Size(320, 240)};
        }
    }
    @Implements(ImageReader.class) public static class ReaderShadow {
        static final List<ReaderShadow> readers = new ArrayList<>();
        ImageReader reader; int format; Image image; boolean closed;
        Surface surface = Shadow.newInstanceOf(Surface.class); ImageReader.OnImageAvailableListener listener;
        @Implementation protected static ImageReader newInstance(int width, int height, int format, int maxImages) {
            ImageReader reader = Shadow.newInstanceOf(ImageReader.class);
            ReaderShadow shadow = Shadow.extract(reader); shadow.reader = reader; shadow.format = format; readers.add(shadow); return reader;
        }
        @Implementation protected Surface getSurface() { return surface; }
        @Implementation protected void setOnImageAvailableListener(ImageReader.OnImageAvailableListener l, Handler h) { listener = l; }
        @Implementation protected Image acquireLatestImage() { return image; }
        @Implementation protected Image acquireNextImage() { return image; }
        @Implementation protected void close() { closed = true; }
    }
    @Implements(CaptureRequest.Builder.class) public static class BuilderShadow {
        int template; final Map<String,Object> values = new HashMap<>(); final List<Surface> targets = new ArrayList<>();
        @Implementation protected <T> void set(CaptureRequest.Key<T> key, T value) { values.put(key.getName(), value); }
        @Implementation protected void addTarget(Surface target) { targets.add(target); }
        @Implementation protected CaptureRequest build() {
            CaptureRequest request = Shadow.newInstanceOf(CaptureRequest.class);
            RequestShadow shadow = Shadow.extract(request); shadow.template = template;
            shadow.values.putAll(values); shadow.targets.addAll(targets); return request;
        }
    }
    @Implements(CaptureRequest.class) public static class RequestShadow {
        int template; final Map<String,Object> values = new HashMap<>(); final List<Surface> targets = new ArrayList<>();
    }
}
