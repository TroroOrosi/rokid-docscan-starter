package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

import android.content.Context;
import android.graphics.ImageFormat;
import android.hardware.camera2.*;
import android.media.ImageReader;
import android.os.Handler;
import android.os.Looper;
import android.util.Size;
import android.view.Surface;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.Implementation;
import org.robolectric.annotation.Implements;
import org.robolectric.shadow.api.Shadow;
import org.robolectric.shadows.*;
import org.robolectric.util.ReflectionHelpers;

/** Drives captureOnce through Camera2 callbacks. No physical exposure is simulated. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE,
        shadows = {GlassCameraExposureTest.DeviceShadow.class, GlassCameraExposureTest.SessionShadow.class})
public class GlassCameraExposureTest {
    private GlassCamera camera;
    private final List<String> failures = new ArrayList<>();

    @Before public void setup() {
        DeviceShadow.outputs = null;
        DeviceShadow.session = null;
        DeviceShadow.templates.clear();
        CameraManager manager = (CameraManager) RuntimeEnvironment.getApplication()
                .getSystemService(Context.CAMERA_SERVICE);
        CameraCharacteristics characteristics = ShadowCameraCharacteristics.newCameraCharacteristics();
        ShadowCameraCharacteristics values = Shadow.extract(characteristics);
        values.set(CameraCharacteristics.LENS_FACING, CameraCharacteristics.LENS_FACING_BACK);
        values.set(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP,
                StreamConfigurationMapBuilder.newBuilder()
                        // StreamConfigurationMapBuilder takes the internal BLOB format for JPEG.
                        .addOutputSize(0x21, new Size(4032, 3024))
                        .addOutputSize(ImageFormat.YUV_420_888, new Size(1920, 1080))
                        .addOutputSize(ImageFormat.YUV_420_888, new Size(640, 360))
                        .addOutputSize(ImageFormat.YUV_420_888, new Size(320, 240))
                        .addOutputSize(ImageFormat.YUV_420_888, new Size(640, 480)).build());
        shadowOf(manager).addCamera("0", characteristics);
        camera = new GlassCamera(RuntimeEnvironment.getApplication(), new Handler(Looper.getMainLooper()),
                new GlassCamera.Callback() {
                    @Override public void onCaptured(byte[] jpeg, int w, int h, long elapsed) {
                        fail("metadata must not deliver a JPEG");
                    }
                    @Override public void onCaptureFailed(String reason) { failures.add(reason); }
                });
    }

    private SessionShadow start() {
        camera.captureOnce();
        shadowOf(Looper.getMainLooper()).idle();
        assertTrue(failures.toString(), failures.isEmpty());
        SessionShadow session = Shadow.extract(DeviceShadow.session);
        assertNotNull("a configured session must meter before requesting its JPEG", session.repeating);
        return session;
    }

    private void result(SessionShadow session, Integer ae) {
        TotalCaptureResult result = ShadowTotalCaptureResult.newTotalCaptureResult();
        ShadowCaptureResult values = Shadow.extract(result);
        values.set(CaptureResult.CONTROL_AE_STATE, ae);
        session.repeating.onCaptureCompleted(DeviceShadow.session, null, result);
    }

    @Test public void onlyConvergenceRequestsOneStillAndPreservesJpegDimensions() {
        SessionShadow session = start();
        assertEquals(2, DeviceShadow.outputs.size());
        ImageReader jpeg = ReflectionHelpers.getField(camera, "reader");
        ImageReader metering = ReflectionHelpers.getField(camera, "meteringReader");
        assertEquals(4032, jpeg.getWidth());
        assertEquals(3024, jpeg.getHeight());
        assertEquals(640, metering.getWidth());
        assertEquals(480, metering.getHeight());
        assertEquals(2, metering.getMaxImages());
        assertEquals(List.of(metering.getSurface()), targets(session.preview));
        result(session, null);
        result(session, CaptureResult.CONTROL_AE_STATE_INACTIVE);
        result(session, CaptureResult.CONTROL_AE_STATE_SEARCHING);
        result(session, CaptureResult.CONTROL_AE_STATE_LOCKED);
        result(session, CaptureResult.CONTROL_AE_STATE_FLASH_REQUIRED);
        assertEquals(0, session.stills);
        result(session, CaptureResult.CONTROL_AE_STATE_CONVERGED);
        result(session, CaptureResult.CONTROL_AE_STATE_CONVERGED);
        assertEquals(1, session.stills);
        assertEquals(1, session.stops);
        assertEquals(List.of(jpeg.getSurface()), targets(session.still));
        assertEquals(List.of(CameraDevice.TEMPLATE_PREVIEW, CameraDevice.TEMPLATE_STILL_CAPTURE),
                DeviceShadow.templates);
        // Stopping the repeating stream can echo abort; that must not abort the JPEG.
        session.repeating.onCaptureSequenceAborted(DeviceShadow.session, 1);
        assertTrue(failures.isEmpty());
        camera.close();
        shadowOf(Looper.getMainLooper()).idle();
    }

    @Test public void unknownExposureUsesOriginalDeadlineAndNeverRestarts() {
        SessionShadow session = start();
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(14));
        result(session, null);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
        assertEquals(List.of("CAMERA TIMEOUT"), failures);
        assertEquals(0, session.stills);
        assertNull(ReflectionHelpers.getField(camera, "meteringReader"));
        assertNull(ReflectionHelpers.getField(camera, "reader"));
        result(session, CaptureResult.CONTROL_AE_STATE_CONVERGED);
        camera.captureOnce();
        shadowOf(Looper.getMainLooper()).idle();
        assertEquals(0, session.stills);
        assertEquals(1, failures.size());
    }

    @Test public void closeRejectsLateConvergenceAndReleasesBothReaders() {
        SessionShadow session = start();
        camera.close();
        shadowOf(Looper.getMainLooper()).idle();
        result(session, CaptureResult.CONTROL_AE_STATE_CONVERGED);
        assertEquals(0, session.stills);
        assertTrue(failures.isEmpty());
        assertNull(ReflectionHelpers.getField(camera, "meteringReader"));
        assertNull(ReflectionHelpers.getField(camera, "reader"));
    }

    @Test public void convergenceDoesNotRenewTheDeadlineOrPermitAnotherRequest() {
        SessionShadow session = start();
        camera.captureOnce();
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(14));
        result(session, CaptureResult.CONTROL_AE_STATE_CONVERGED);
        assertEquals(1, session.stills);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
        assertEquals(List.of("CAMERA TIMEOUT"), failures);
        assertEquals(2, DeviceShadow.templates.size());
        assertNull(ReflectionHelpers.getField(camera, "meteringReader"));
    }

    @Test public void meteringFailureClosesTheSessionWithoutShooting() {
        SessionShadow session = start();
        session.repeating.onCaptureBufferLost(DeviceShadow.session, null, null, 1L);
        result(session, CaptureResult.CONTROL_AE_STATE_CONVERGED);
        assertEquals(List.of("metering buffer lost"), failures);
        assertEquals(0, session.stills);
        assertNull(ReflectionHelpers.getField(camera, "meteringReader"));
        assertNull(ReflectionHelpers.getField(camera, "reader"));
    }

    @Test public void previousGenerationCannotShootOrFailCurrentMetering() {
        SessionShadow session = start();
        // Simulate a newer generation; the callback retained by the HAL is stale.
        ReflectionHelpers.setField(camera, "generation", 2L);
        result(session, CaptureResult.CONTROL_AE_STATE_CONVERGED);
        session.repeating.onCaptureSequenceAborted(DeviceShadow.session, 1);
        assertEquals(0, session.stills);
        assertTrue(failures.isEmpty());
        camera.close();
        shadowOf(Looper.getMainLooper()).idle();
    }

    @Test public void unsupportedMeteringSizeFailsBeforeOpeningWithoutImmediateStillFallback() {
        CameraManager manager = (CameraManager) RuntimeEnvironment.getApplication()
                .getSystemService(Context.CAMERA_SERVICE);
        CameraCharacteristics unsupported = ShadowCameraCharacteristics.newCameraCharacteristics();
        ShadowCameraCharacteristics values = Shadow.extract(unsupported);
        values.set(CameraCharacteristics.LENS_FACING, CameraCharacteristics.LENS_FACING_BACK);
        values.set(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP,
                StreamConfigurationMapBuilder.newBuilder()
                        .addOutputSize(0x21, new Size(4032, 3024))
                        .addOutputSize(ImageFormat.YUV_420_888, new Size(1920, 1080)).build());
        shadowOf(manager).removeCamera("0");
        shadowOf(manager).addCamera("0", unsupported);
        camera.captureOnce();
        shadowOf(Looper.getMainLooper()).idle();
        assertEquals(List.of("no bounded metering size"), failures);
        assertTrue(DeviceShadow.templates.isEmpty());
        assertNull(DeviceShadow.session);
    }

    private static List<Surface> targets(CaptureRequest request) {
        Collection<Surface> targets = ReflectionHelpers.callInstanceMethod(request, "getTargets");
        return new ArrayList<>(targets);
    }

    @Implements(className = "android.hardware.camera2.impl.CameraDeviceImpl", isInAndroidSdk = false)
    public static class DeviceShadow extends ShadowCameraDeviceImpl {
        static List<Surface> outputs;
        static CameraCaptureSession session;
        static final List<Integer> templates = new ArrayList<>();
        @Implementation protected CaptureRequest.Builder createCaptureRequest(int template) {
            templates.add(template);
            return super.createCaptureRequest(template);
        }
        @Implementation protected void createCaptureSession(List<Surface> surfaces,
                CameraCaptureSession.StateCallback callback, Handler handler) {
            outputs = surfaces;
            session = (CameraCaptureSession) Shadow.newInstanceOf(
                    "android.hardware.camera2.impl.CameraCaptureSessionImpl");
            handler.post(() -> callback.onConfigured(session));
        }
    }

    @Implements(className = "android.hardware.camera2.impl.CameraCaptureSessionImpl", isInAndroidSdk = false)
    public static class SessionShadow extends ShadowCameraCaptureSessionImpl {
        CameraCaptureSession.CaptureCallback repeating;
        CaptureRequest preview;
        CaptureRequest still;
        int stills;
        int stops;
        @Implementation protected int setRepeatingRequest(CaptureRequest request,
                CameraCaptureSession.CaptureCallback callback, Handler handler) {
            preview = request;
            repeating = callback;
            return 1;
        }
        @Implementation protected int capture(CaptureRequest request,
                CameraCaptureSession.CaptureCallback callback, Handler handler) {
            still = request;
            stills++;
            return 2;
        }
        @Implementation protected void stopRepeating() { stops++; }
        @Implementation protected void close() { }
    }
}
