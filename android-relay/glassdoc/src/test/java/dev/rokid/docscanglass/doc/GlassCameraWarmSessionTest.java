package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;
import static android.hardware.camera2.CameraMetadata.*;

import android.graphics.Bitmap;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorManager;
import android.hardware.camera2.*;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.hardware.camera2.params.MeteringRectangle;
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
import dev.rokid.docscanrelay.CaptureSurface;
import dev.rokid.docscanrelay.CaptureProvenance;
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
import org.robolectric.shadows.ShadowSensor;
import org.robolectric.shadows.ShadowSensorManager;
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
    private final List<GlassCamera.Captured> originals = new ArrayList<>();
    private int delivered;
    private int displayed;
    private PaperGeometry.Box displayedPaper;
    private int displayedCenter;
    private Long exposureNanos = 10_000_000L;

    @Before public void setup() {
        ManagerShadow.devices.clear(); ReaderShadow.readers.clear();
        ManagerShadow.refuseSession = false; CharacteristicsShadow.fixedFocus = false;
        CharacteristicsShadow.aeRegions = 0; // AGENT_APPROVED=1: explicit comparison test setup.
        CharacteristicsShadow.strictPublicApi = false;
        CharacteristicsShadow.afMode = CONTROL_AF_MODE_CONTINUOUS_PICTURE;
        createCamera();
    }
    private void createCamera() {
        createCamera(false);
    }
    private void createCamera(boolean paperEvaluation) {
        camera = new GlassCamera(RuntimeEnvironment.getApplication(), new Handler(Looper.getMainLooper()),
                new GlassCamera.Callback() {
                    @Override public void onCaptured(GlassCamera.Captured captured) {
                        originals.add(captured); GlassCamera.Callback.super.onCaptured(captured);
                    }
                    @Override public void onCaptured(byte[] bytes, int w, int h, long elapsed) {
                        assertEquals(4032, w); assertEquals(3024, h); delivered++;
                    }
                    @Override public void onCaptureFailed(String reason) { failures.add(reason); }
                    @Override public void onPreview(Bitmap frame) { displayed++; frame.recycle(); }
                    @Override public void onPreview(Bitmap frame, PaperGeometry.Box paper) {
                        displayedPaper = paper; displayedCenter = android.graphics.Color.green(
                                frame.getPixel(frame.getWidth() / 2, frame.getHeight() / 2));
                        onPreview(frame);
                    }
                }, GlassCamera.Mode.NATIVE_STILL, null, null,
                CaptureVideoRecording.Options.defaults("test", 0, 270), null, paperEvaluation);
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
        frame(currentReader(ImageFormat.YUV_420_888), value, turning, SystemClock.elapsedRealtimeNanos());
    }
    private void frame(ReaderShadow reader, int value, boolean turning, long sensorTimestamp) {
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
        image.format = ImageFormat.YUV_420_888; image.width = 32; image.height = 24;
        image.rowStride = 32; image.pixelStride = 1;
        byte[] pixels = new byte[32 * 24]; java.util.Arrays.fill(pixels, (byte) value);
        if (turning) java.util.Arrays.fill(pixels, 0, pixels.length / 3, (byte) 70);
        image.timestamp = sensorTimestamp;
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
        values.set(CaptureResult.SENSOR_EXPOSURE_TIME, exposureNanos);
        assertEquals(Integer.valueOf(af), result.get(CaptureResult.CONTROL_AF_STATE));
        assertEquals(Integer.valueOf(ae), result.get(CaptureResult.CONTROL_AE_STATE));
        return result;
    }
    private void readyFrame() { idle(100); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); }

    private void selectionOriginal() {
        SensorManager manager = (SensorManager)RuntimeEnvironment.getApplication().getSystemService(android.content.Context.SENSOR_SERVICE);
        ShadowSensorManager sensors = shadowOf(manager);
        sensors.addSensor(ShadowSensor.newInstance(Sensor.TYPE_GYROSCOPE));
        createCamera(); camera.nativeSelection(true); camera.captureOnce(); idle(100);
        motionFrames(sensors, 0f, 12);
        assertEquals(1, firstDevice().session.captures);
        selectionJpeg(new byte[]{1, 2, 3});
    }

    private void selectionJpeg(byte[] bytes) {
        idle(1); // Distinct real sensor timestamps, including an immediately issued optional still.
        long timestamp = SystemClock.elapsedRealtimeNanos();
        var session = firstDevice().session;
        session.captureCallback.onCaptureCompleted(session, session.captured,
                metadata(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, timestamp));
        var jpeg = currentReader(ImageFormat.JPEG);
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
        image.timestamp = timestamp; image.buffer = ByteBuffer.wrap(bytes); jpeg.image = image;
        jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
    }

    private static final class Alternative implements CaptureSurface.NativeAlternative {
        int starting, skipped, delivered;
        boolean matched;
        byte[] bytes;
        CaptureProvenance source;
        @Override public boolean onStarting() { starting++; return true; }
        @Override public void onSkipped() { skipped++; }
        @Override public void onOriginal(byte[] jpeg, CaptureProvenance provenance, boolean sameScene) {
            delivered++; bytes = jpeg; source = provenance; matched = sameScene;
        }
    }

    @Test public void nativeSelectionIsAnExplicitNativeOnlyNonpersistentGate() {
        assertFalse(DocScanGlassActivity.nativeSelection(new android.content.Intent()));
        assertTrue(DocScanGlassActivity.nativeSelection(new android.content.Intent().putExtra("native_selection", true)));
        assertEquals(GlassCamera.Mode.NATIVE_STILL, DocScanGlassActivity.evaluationMode(new android.content.Intent()
                .putExtra("native_selection", true)));
        assertEquals(GlassCamera.Mode.NATIVE_STILL, DocScanGlassActivity.evaluationMode(new android.content.Intent()
                .putExtra("paper_geometry_evaluation", true)));
        for (String other : new String[]{"zsl_evaluation", "video_evaluation", "video_transfer_evaluation",
                "paper_geometry_evaluation", "wrong_type"}) {
            android.content.Intent intent = new android.content.Intent().putExtra("native_selection", true);
            if (other.equals("wrong_type")) intent.putExtra("native_selection", "true"); else intent.putExtra(other, true);
            assertThrows(IllegalArgumentException.class, () -> DocScanGlassActivity.evaluationMode(intent));
        }
        assertNull(camera.nativeSelectionScene(CaptureProvenance.nativeStill(new byte[]{1}, 4032, 3024, 1L, 1L, 1L,
                10_000_000L, 100, 0, 2)));
    }

    @Test public void optionalNativeOriginalUsesOneReadyShotAndTheEndBarrierWaitsForItsBytes() {
        selectionOriginal();
        CaptureSurface.NativeScene scene = camera.nativeSelectionScene(originals.get(0).provenance);
        assertNotNull(scene); assertTrue(camera.isNativeSelectionSceneCurrent(scene));
        Alternative b = new Alternative(); camera.requestNativeAlternative(scene, b); idle(0);
        assertEquals(1, b.starting); assertEquals(2, firstDevice().session.captures);
        assertEquals(1, delivered); // first review did not wait for B
        AtomicInteger idle = new AtomicInteger(); camera.stopFuturePages(idle::incrementAndGet); idle(0);
        assertEquals(0, idle.get());
        selectionJpeg(new byte[]{4, 5, 6});
        assertEquals(1, b.delivered); assertTrue(b.matched);
        assertArrayEquals(new byte[]{4, 5, 6}, b.bytes);
        assertEquals(CaptureProvenance.nativeStill(b.bytes, 4032, 3024, 1L, 1L, 1L,
                10_000_000L, 100, 0, 2).jpegSha256, b.source.jpegSha256);
        assertEquals(1, delivered); assertEquals(1, idle.get());
        Alternative third = new Alternative(); camera.requestNativeAlternative(scene, third); idle(0);
        assertEquals(0, third.starting); assertEquals(1, third.skipped);
        assertFalse(((PageChange)ReflectionHelpers.getField(camera, "pageChange")).ready(SystemClock.elapsedRealtime()));
        assertTrue(failures.isEmpty());
    }

    @Test public void aTurnAndReturnDuringTheOptionalShotRetainsBytesButNeverReusesTheOldScene() {
        selectionOriginal();
        CaptureSurface.NativeScene scene = camera.nativeSelectionScene(originals.get(0).provenance);
        Alternative b = new Alternative(); camera.requestNativeAlternative(scene, b); idle(0);
        idle(30); frame(180, true); idle(30); frame(180); idle(400);
        assertFalse(camera.isNativeSelectionSceneCurrent(scene));
        selectionJpeg(new byte[]{4, 5, 6});
        assertEquals(1, b.delivered); assertFalse(b.matched);
        assertEquals(1, delivered);
        assertTrue(((PageChange)ReflectionHelpers.getField(camera, "pageChange")).ready(SystemClock.elapsedRealtime()));
        assertTrue(failures.isEmpty());
    }

    @Test public void missingFreshGyroOrANextPageNeverStartsAnOptionalPreparationWait() {
        selectionOriginal();
        CaptureSurface.NativeScene scene = camera.nativeSelectionScene(originals.get(0).provenance);
        idle(CameraReadiness.FRESH_MILLIS + 1);
        Alternative stale = new Alternative(); camera.requestNativeAlternative(scene, stale); idle(0);
        assertEquals(0, stale.starting); assertEquals(1, stale.skipped);
        assertEquals(1, firstDevice().session.captures);
        camera.observeFuturePages(1, new CaptureSurface.FuturePageListener() {
            @Override public boolean onCaptureStarting() { return true; }
            @Override public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sameScene) { }
            @Override public void onPageMissed() { fail("available next-page capacity must be retained"); }
        }); idle(0);
        frame(180, true); idle(30); frame(180);
        SensorManager manager = (SensorManager)RuntimeEnvironment.getApplication().getSystemService(android.content.Context.SENSOR_SERVICE);
        motionFrames(shadowOf(manager), 0f, 10);
        Alternative late = new Alternative(); camera.requestNativeAlternative(scene, late); idle(0);
        assertEquals(0, late.starting); assertEquals(1, late.skipped);
        assertNotNull(ReflectionHelpers.getField(camera, "activeFuturePage"));
        assertTrue(failures.isEmpty());
    }

    private void paperFrame() {
        paperFrame(20); // AGENT_APPROVED=1: same paper, independently changing surrounding scene.
    }
    private void paperFrame(int background) {
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
        image.format = ImageFormat.YUV_420_888; image.width = 32; image.height = 24;
        image.rowStride = 32; image.pixelStride = 1;
        byte[] pixels = new byte[32 * 24]; java.util.Arrays.fill(pixels, (byte)background);
        for (int y = 6; y < 18; y++) java.util.Arrays.fill(pixels, y * 32 + 8, y * 32 + 24, (byte)220);
        image.timestamp = SystemClock.elapsedRealtimeNanos(); image.buffer = ByteBuffer.wrap(pixels);
        var reader = currentReader(ImageFormat.YUV_420_888); reader.image = image;
        reader.listener.onImageAvailable(reader.reader);
    }

    private void paperResult(CaptureRequest request, MeteringRectangle[] regions) {
        paperResult(request, regions, null);
    }
    private void paperResult(CaptureRequest request, MeteringRectangle[] regions, Float zoom) {
        paperResult(request, regions, zoom, SystemClock.elapsedRealtimeNanos()); // AGENT_APPROVED=1
    }
    private void paperResult(CaptureRequest request, MeteringRectangle[] regions, Float zoom, long timestamp) {
        TotalCaptureResult result = metadata(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED,
                timestamp);
        ShadowCaptureResult values = Shadow.extract(result);
        values.set(CaptureResult.SCALER_CROP_REGION, new Rect(0, 0, 4032, 3024));
        values.set(CaptureResult.CONTROL_AE_REGIONS, regions);
        if (zoom != null) values.set(CaptureResult.CONTROL_ZOOM_RATIO, zoom);
        var session = currentDevice().session;
        session.previewCallback.onCaptureCompleted(session, request, result);
    }

    @Test public void paperAeComparisonWaitsForTheSameRevisionAndActualReturnedRegion() {
        CharacteristicsShadow.fixedFocus = true; CharacteristicsShadow.aeRegions = 1; createCamera(true);
        camera.captureOnce(); idle(100);
        var session = firstDevice().session;
        CaptureRequest initial = session.repeating;
        MeteringRectangle[] whole = {new MeteringRectangle(0, 0, 4032, 3024, 0)};
        paperResult(initial, whole); paperFrame(); idle(100);
        paperResult(session.repeating, whole); paperFrame();
        CaptureRequest proposed = session.repeating;
        MeteringRectangle[] region = proposed.get(CaptureRequest.CONTROL_AE_REGIONS);
        assertArrayEquals(new MeteringRectangle[]{new MeteringRectangle(882, 630, 2268, 1764, 1000)}, region);
        assertNotSame(initial, proposed); assertEquals(0, session.captures);
        idle(400); paperResult(initial, whole); paperFrame(); idle(50);
        assertEquals("late full-frame metadata cannot authorize the new paper region", 0, session.captures);
        paperResult(proposed, whole); paperFrame(); idle(50);
        assertEquals("an unreturned AE region cannot authorize a shutter", 0, session.captures);
        idle(700);
        paperResult(proposed, region, null, SystemClock.elapsedRealtimeNanos() - 700_000_000L); paperFrame(); idle(50);
        assertEquals("the right region with stale sensor timing is insufficient", 0, session.captures);
        paperResult(proposed, region); paperFrame(); idle(50);
        assertEquals(1, session.captures);
        RequestShadow still = Shadow.extract(session.captured);
        assertEquals(CONTROL_AF_MODE_OFF, still.values.get(CaptureRequest.CONTROL_AF_MODE.getName()));
        assertArrayEquals(region, session.captured.get(CaptureRequest.CONTROL_AE_REGIONS));
        assertNull(session.captured.get(CaptureRequest.SCALER_CROP_REGION));
        assertNull(session.captured.get(CaptureRequest.CONTROL_ZOOM_RATIO));
        assertEquals(0, still.values.get(CaptureRequest.JPEG_ORIENTATION.getName()));
    }

    @Test public void paperProposalWithoutAeCapabilityKeepsFullFrameNativeReadiness() {
        CharacteristicsShadow.fixedFocus = true; createCamera(true);
        camera.captureOnce(); idle(100); result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); paperFrame();
        idle(400); result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); paperFrame(); idle(50);
        assertEquals(1, firstDevice().session.captures);
        assertNull(firstDevice().session.captured.get(CaptureRequest.CONTROL_AE_REGIONS));
        assertNull(firstDevice().session.captured.getTag());
    }

    @Test @Config(sdk = {28, 30, 31})
    public void paperAeComparisonUsesOnlyTransformKeysAvailableOnThatAndroidApi() {
        CharacteristicsShadow.strictPublicApi = true; // Android-all also contains hidden keys; enforce the public HAL boundary.
        CharacteristicsShadow.fixedFocus = true; CharacteristicsShadow.aeRegions = 1; createCamera(true); // AGENT_APPROVED=1
        camera.captureOnce(); idle(100);
        for (int n = 0; n < 8; n++) {
            idle(100); CaptureRequest request = firstDevice().session.repeating;
            paperResult(request, request.get(CaptureRequest.CONTROL_AE_REGIONS)); paperFrame();
        }
        assertEquals(1, firstDevice().session.captures); assertTrue(failures.isEmpty());
    }

    @Test public void paperGeometryComparisonIsExplicitAndCannotCombineOtherProducers() {
        assertFalse(DocScanGlassActivity.paperGeometryEvaluation(new android.content.Intent())); // AGENT_APPROVED=1
        assertTrue(DocScanGlassActivity.paperGeometryEvaluation(new android.content.Intent().putExtra("paper_geometry_evaluation", true)));
        for (String other : new String[]{"zsl_evaluation", "video_evaluation"}) {
            try {
                DocScanGlassActivity.evaluationMode(new android.content.Intent()
                        .putExtra("paper_geometry_evaluation", true).putExtra(other, true));
                fail("independent comparison producers cannot be combined implicitly");
            } catch (IllegalArgumentException expected) { }
        }
        try {
            DocScanGlassActivity.paperGeometryEvaluation(new android.content.Intent().putExtra("paper_geometry_evaluation", "true"));
            fail("comparison must require a boolean opt-in");
        } catch (IllegalArgumentException expected) { }
    }

    @Test public void paperProposalAndWholePreviewHonorTheSamePaddedPlaneOrigin() {
        createCamera(true); camera.preview(); // AGENT_APPROVED=1: actual Y-plane/display seam, no camera hardware.
        for (int n = 0; n < 2; n++) {
            idle(100);
            DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
            image.format = ImageFormat.YUV_420_888; image.width = 32; image.height = 24;
            image.rowStride = 71; image.pixelStride = 2;
            byte[] pixels = new byte[7 + 24 * 71]; java.util.Arrays.fill(pixels, (byte)4);
            for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++)
                pixels[7 + y * 71 + x * 2] = (byte)(x >= 8 && x < 24 && y >= 6 && y < 18 ? 220 : 20);
            image.timestamp = SystemClock.elapsedRealtimeNanos(); image.buffer = ByteBuffer.wrap(pixels); image.buffer.position(7);
            var reader = currentReader(ImageFormat.YUV_420_888); reader.image = image; reader.listener.onImageAvailable(reader.reader);
        }
        assertArrayEquals(new int[]{7, 5, 25, 19}, displayedPaper.edges());
        assertEquals("the guide and the visible paper use the same plane origin", 220, displayedCenter);
        assertTrue(failures.isEmpty());
    }

    @Test public void paperComparisonKeepsFullFrameAToBToATurnsDuringReviewAndAllOriginalBytes() {
        CharacteristicsShadow.fixedFocus = true; CharacteristicsShadow.aeRegions = 1; createCamera(true);
        camera.captureOnce(); idle(100);
        for (int n = 0; n < 8; n++) {
            idle(100); var request = firstDevice().session.repeating;
            paperResult(request, request.get(CaptureRequest.CONTROL_AE_REGIONS)); paperFrame();
        }
        assertEquals(1, firstDevice().session.captures);
        byte[] first = {1, 2, 3}; deliverOriginal(first, SystemClock.elapsedRealtimeNanos());
        assertArrayEquals(first, originals.get(0).jpeg);
        List<byte[]> future = new ArrayList<>();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance p, boolean matched) {
                assertTrue(matched); future.add(jpeg);
            }
            public void onPageMissed() { fail("these two stable scenes fit the existing two slots"); }
        }); idle(0);
        // Only the surround changes; the same apparent paper rectangle cannot suppress a turn.
        for (int background : new int[]{100, 20}) {
            int before = firstDevice().session.captures;
            for (int n = 0; n < 8; n++) {
                idle(100); var request = firstDevice().session.repeating;
                paperResult(request, request.get(CaptureRequest.CONTROL_AE_REGIONS)); paperFrame(background);
            }
            assertEquals(before + 1, firstDevice().session.captures);
            deliverOriginal(new byte[]{(byte)background, 4, 5}, SystemClock.elapsedRealtimeNanos());
        }
        assertEquals(2, future.size()); assertArrayEquals(new byte[]{100, 4, 5}, future.get(0));
        assertArrayEquals(new byte[]{20, 4, 5}, future.get(1));
        camera.stopFuturePages(() -> {}); idle(0); idle(600);
        assertEquals(3, firstDevice().session.captures); assertTrue(failures.isEmpty());
    }

    @Test public void anUnknownTransformReturnsToFreshFullFrameAeWithoutChangingZoomOrCropping() {
        CharacteristicsShadow.fixedFocus = true; CharacteristicsShadow.aeRegions = 1; createCamera(true);
        camera.preview(); idle(100);
        for (int n = 0; n < 3; n++) {
            idle(100); var request = firstDevice().session.repeating;
            paperResult(request, request.get(CaptureRequest.CONTROL_AE_REGIONS)); paperFrame();
        }
        var session = firstDevice().session;
        CaptureRequest region = session.repeating;
        paperResult(region, region.get(CaptureRequest.CONTROL_AE_REGIONS), 2f); idle(100); paperFrame();
        CaptureRequest fallback = session.repeating;
        assertNotSame(region, fallback);
        assertEquals(0, fallback.get(CaptureRequest.CONTROL_AE_REGIONS)[0].getMeteringWeight());
        camera.captureOnce(); idle(0); idle(100);
        paperResult(fallback, fallback.get(CaptureRequest.CONTROL_AE_REGIONS), 2f); paperFrame(); idle(50);
        assertEquals(1, session.captures);
        assertNull(session.captured.get(CaptureRequest.CONTROL_ZOOM_RATIO));
        assertNull(session.captured.get(CaptureRequest.SCALER_CROP_REGION));
    }

    @Test public void twoStableFutureScenesUseNativeOriginalsWithoutReplacingTheVisibleReview() {
        warmOriginal();
        List<byte[]> candidates = new ArrayList<>();
        List<CaptureProvenance> sources = new ArrayList<>();
        AtomicInteger gaps = new AtomicInteger();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) {
                assertTrue(sceneMatched); candidates.add(jpeg); sources.add(source);
            }
            public void onPageMissed() { gaps.incrementAndGet(); }
        }); idle(0);
        stableTurn();
        assertEquals(2, firstDevice().session.captures);
        byte[] second = {4, 5, 6}; long secondAt = SystemClock.elapsedRealtimeNanos();
        deliverOriginal(second, secondAt);
        // The coarse image returns to A, but a positive turn separates this future scene.
        stableTurn();
        assertEquals(3, firstDevice().session.captures);
        byte[] third = {7, 8, 9}; long thirdAt = SystemClock.elapsedRealtimeNanos();
        deliverOriginal(third, thirdAt);
        assertEquals(1, delivered);
        assertEquals(2, candidates.size()); assertArrayEquals(second, candidates.get(0));
        assertArrayEquals(third, candidates.get(1));
        assertEquals(Long.valueOf(secondAt), sources.get(0).imageTimestampNanos);
        assertEquals(Long.valueOf(thirdAt), sources.get(1).imageTimestampNanos);
        assertNotEquals(sources.get(0).captureId, sources.get(1).captureId);
        assertNotEquals(sources.get(0).jpegSha256, sources.get(1).jpegSha256);
        for (int i = 0; i < 10; i++) readyFrame();
        assertEquals("an unchanged page cannot consume another native request", 3, firstDevice().session.captures);
        stableTurn();
        assertEquals(1, gaps.get()); assertEquals(3, firstDevice().session.captures);
        stableTurn(); assertEquals(1, gaps.get());
        assertTrue(failures.isEmpty()); assertEquals(1, ManagerShadow.devices.size());
    }

    @Test public void anOldZslSourceIsPreservedAsUnresolvedInsteadOfBecomingTheNextScene() {
        long firstAt = warmOriginal();
        List<byte[]> retained = new ArrayList<>();
        List<Boolean> matched = new ArrayList<>();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) {
                retained.add(jpeg); matched.add(sceneMatched);
                assertEquals(Long.valueOf(firstAt + 1), source.imageTimestampNanos);
            }
            public void onPageMissed() { fail("the original must be delivered with its uncertainty"); }
        }); idle(0); stableTurn();
        deliverOriginal(new byte[]{9, 9, 9}, firstAt + 1);
        assertEquals(List.of(false), matched); assertArrayEquals(new byte[]{9, 9, 9}, retained.get(0));
        stableTurn(); idle(15000);
        assertEquals("one unresolved scene must not trigger an unbounded retry", 2, firstDevice().session.captures);
        assertEquals(1, delivered);
    }

    @Test public void stoppingFutureCaptureWaitsForTheInFlightOriginalAndDoesNotStartAnother() {
        warmOriginal();
        List<String> order = new ArrayList<>();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) { order.add("original"); }
            public void onPageMissed() { fail("end is not an overflow"); }
        }); idle(0); stableTurn();
        camera.stopFuturePages(() -> order.add("idle")); idle(0);
        assertTrue(order.isEmpty());
        deliverOriginal(new byte[]{4, 4, 4}, SystemClock.elapsedRealtimeNanos());
        assertEquals(List.of("original", "idle"), order);
        stableTurn(); assertEquals(2, firstDevice().session.captures); assertEquals(1, delivered);
    }

    @Test public void aStableSceneThatLeavesDuringAnotherNativeRequestCannotBeCollapsedIntoTheLatestScene() {
        warmOriginal();
        AtomicInteger gaps = new AtomicInteger();
        List<Boolean> matched = new ArrayList<>();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) { matched.add(sceneMatched); }
            public void onPageMissed() { gaps.incrementAndGet(); }
        }); idle(0); stableTurn();
        long bTimestamp = SystemClock.elapsedRealtimeNanos();
        stableTurn(); // C was stable while the only native request still belonged to B.
        idle(30); frame(180, true); // C leaves before it could be photographed.
        assertEquals(1, gaps.get());
        deliverOriginal(new byte[]{4, 5, 6}, bTimestamp);
        assertEquals(List.of(true), matched);
        idle(30); frame(180); idle(400); readyFrame(); idle(50);
        assertEquals("the lost intermediate scene cannot silently become D", 2, firstDevice().session.captures);
    }

    @Test public void aFutureNativeFailureIsUnknownAndUnblocksStopOnlyAfterFailureWithoutAnotherStill() {
        warmOriginal(); AtomicInteger stopped = new AtomicInteger();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) { fail("failed JPEG cannot be delivered"); }
            public void onPageMissed() { fail("native failure is not overflow"); }
        }); idle(0); stableTurn();
        camera.stopFuturePages(stopped::incrementAndGet); idle(0);
        assertEquals(0, stopped.get());
        var session = firstDevice().session;
        session.previewCallback.onCaptureFailed(session, session.repeating, null);
        assertEquals(1, stopped.get()); assertEquals(1, failures.size());
        assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
        camera.captureOnce(); camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) { fail(); }
            public void onPageMissed() { fail(); }
        }); idle(15000);
        assertEquals(2, session.captures); assertEquals(1, delivered);
    }

    @Test public void aFailedDurableReservationPreventsTheFutureNativeRequest() {
        warmOriginal();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public boolean onCaptureStarting() { return false; }
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) { fail("reservation was rejected"); }
            public void onPageMissed() { fail("storage failure is not a missed scene"); }
        }); idle(0); stableTurn();
        assertEquals("native still cannot precede its durable reservation", 1, firstDevice().session.captures);
        assertEquals(1, failures.size()); assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
    }

    @Test public void aDurableReservationCannotAuthorizeMeteringThatExpiredDuringTheWrite() {
        warmOriginal();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public boolean onCaptureStarting() {
                org.robolectric.shadows.ShadowSystemClock.advanceBy(Duration.ofMillis(600)); return true;
            }
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) { fail("stale AF/AE"); }
            public void onPageMissed() { fail(); }
        }); idle(0); stableTurn();
        assertEquals("the durable write cannot extend the native AF/AE freshness window", 1, firstDevice().session.captures);
        assertEquals(1, failures.size()); assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
    }

    private long warmOriginal() {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        long timestamp = SystemClock.elapsedRealtimeNanos();
        deliverOriginal(new byte[]{1, 2, 3}, timestamp);
        assertEquals(1, delivered); return timestamp;
    }

    private void stableTurn() {
        idle(30); frame(180, true); idle(30); frame(180);
        idle(400); readyFrame(); idle(50);
    }

    private void deliverOriginal(byte[] bytes, long timestamp) {
        var jpeg = currentReader(ImageFormat.JPEG);
        var session = currentDevice().session;
        session.captureCallback.onCaptureCompleted(session, session.captured,
                metadata(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, timestamp));
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
        image.timestamp = timestamp; image.buffer = ByteBuffer.wrap(bytes);
        jpeg.image = image; jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
    }

    @Test public void missingOrInvalidExposureCannotAuthorizeAStillAfterMeteringConverges() {
        camera.captureOnce(); idle(100); frame(180); idle(500);
        for (Long value : new Long[]{null, 0L, -1L}) {
            exposureNanos = value;
            result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
            assertEquals(0, firstDevice().session.captures);
        }
        exposureNanos = 25_000_000L;
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, firstDevice().session.captures); assertTrue(failures.isEmpty());
    }

    @Test public void longExposureWaitsForSlowerHeadMotionOnTheRealPreparationPath() {
        SensorManager manager = (SensorManager)RuntimeEnvironment.getApplication()
                .getSystemService(android.content.Context.SENSOR_SERVICE);
        ShadowSensorManager sensors = shadowOf(manager);
        sensors.addSensor(ShadowSensor.newInstance(Sensor.TYPE_GYROSCOPE));
        createCamera();
        exposureNanos = 25_000_000L;
        camera.captureOnce(); idle(0);
        motionFrames(sensors, 0.1f, 14);
        assertEquals("25ms must not reuse the 10ms angular-speed allowance", 0, firstDevice().session.captures);
        motionFrames(sensors, 0.02f, 8);
        assertEquals(1, firstDevice().session.captures); assertTrue(failures.isEmpty());
    }

    @Test public void invalidMetadataCannotMakeAnOldExposureResultFreshAgain() {
        camera.captureOnce(); idle(100); frame(180); idle(400);
        long acceptedAt = SystemClock.elapsedRealtimeNanos();
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, acceptedAt); frame(180);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, 0);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, acceptedAt); idle(50);
        assertEquals(0, firstDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, firstDevice().session.captures); assertTrue(failures.isEmpty());
    }

    @Test public void aPriorPreviewGenerationCannotSupplyTheNextShotsExposure() {
        camera.preview(); idle(100);
        var old = currentDevice().session;
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        camera.pausePreview(); idle(0); camera.captureOnce(); idle(100); frame(180); idle(400);
        old.previewCallback.onCaptureCompleted(old, old.repeating,
                metadata(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        frame(180); idle(50);
        assertEquals(0, currentDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, currentDevice().session.captures); assertTrue(failures.isEmpty());
    }

    @Test public void staleExposureCannotBeRefreshedByNewImagesOrDuplicateResults() {
        camera.captureOnce(); idle(100);
        long acceptedAt = SystemClock.elapsedRealtimeNanos();
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, acceptedAt); frame(180);
        // Keep moving until the initial metadata expires; do not permit an earlier valid shot.
        idle(250); frame(180, true); idle(100); frame(180); idle(400);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, acceptedAt); frame(180); idle(50);
        assertEquals(0, firstDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, firstDevice().session.captures); assertTrue(failures.isEmpty());
    }

    private void motionFrames(ShadowSensorManager sensors, float speed, int readings) {
        for (int i = 0; i < readings; i++) {
            SensorEvent event = ShadowSensorManager.createSensorEvent(3);
            event.values[0] = speed;
            sensors.sendSensorEventToListeners(event);
            idle(50); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        }
    }

    @Test public void aShortTurnBetweenHudUpdatesStillReleasesTheSimilarNextPage() {
        camera.preview(); idle(100);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange"); pages.consumed();
        AtomicInteger ready = new AtomicInteger(); camera.awaitNextPage(ready::incrementAndGet); idle(0);
        assertEquals(1, displayed);

        // Both the turn and the next, visually similar page arrive inside one HUD interval.
        idle(30); frame(180, true); idle(30); frame(180);
        assertEquals(1, displayed); assertEquals(0, ready.get());
        idle(399); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(0, ready.get()); assertEquals(2, displayed);
        idle(1); frame(180);
        assertEquals(1, ready.get()); assertEquals(2, displayed);
        idle(100); frame(180); assertEquals(1, ready.get());
        assertTrue(failures.isEmpty());
    }

    @Test public void motionBetweenHudUpdatesRestartsTheNativeCaptureStillnessWait() {
        camera.preview(); idle(100);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        idle(400); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        idle(30); frame(180, true); idle(30); frame(180);
        assertEquals(2, displayed);

        camera.captureOnce(); idle(350);
        assertEquals(0, firstDevice().session.captures);
        idle(50);
        assertEquals(1, firstDevice().session.captures);
        assertEquals(2, displayed); assertTrue(failures.isEmpty());
    }

    @Test public void invalidDuplicateAndReversedFramesCannotBecomeNewPageObservations() {
        camera.preview(); idle(100); frame(180);
        ReaderShadow preview = currentReader(ImageFormat.YUV_420_888);
        long acceptedAt = SystemClock.elapsedRealtimeNanos();
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange"); pages.consumed();
        AtomicInteger ready = new AtomicInteger(); camera.awaitNextPage(ready::incrementAndGet); idle(0);
        idle(100); frame(preview, 180, true, 0);
        idle(100); frame(preview, 180, true, acceptedAt - 1);
        idle(100); frame(preview, 180, true, acceptedAt);
        assertEquals(1, displayed);
        idle(400); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(0, ready.get()); assertEquals(2, displayed);

        idle(30); frame(180, true); idle(30); frame(180); idle(400);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(1, ready.get()); assertTrue(failures.isEmpty());
    }

    @Test public void aLateFrameFromAClosedPreviewCannotAffectTheReopenedSession() {
        camera.preview(); idle(100); frame(180);
        ReaderShadow old = currentReader(ImageFormat.YUV_420_888);
        camera.pausePreview(); idle(0); camera.preview(); idle(100); frame(180);
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange"); pages.consumed();
        int before = displayed;
        idle(100); frame(old, 180, true, SystemClock.elapsedRealtimeNanos());
        assertEquals(before, displayed);
        AtomicInteger ready = new AtomicInteger(); camera.awaitNextPage(ready::incrementAndGet); idle(400);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(0, ready.get()); assertTrue(failures.isEmpty());
    }

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
        finishAutoFocusThenOneJpeg(mode, ready, 0);
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
        // The next page must run a new AF cycle even when the native session stays open.
        camera.captureOnce(); idle(100); frame(180); idle(400); frame(180);
        var first = currentDevice().session;
        assertEquals(1, first.captures);
        var oldFocusCallback = first.captureCallback;
        var oldFocusRequest = first.captured;
        first.captureCallback.onCaptureCompleted(first, first.captured,
                metadata(CONTROL_AF_STATE_ACTIVE_SCAN, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        idle(100); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(2, first.captures);
        ReaderShadow jpeg = currentReader(ImageFormat.JPEG);
        jpeg.image = new DocScanTestImage(new ArrayList<>()); jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
        assertEquals(1, delivered); assertEquals(1, ManagerShadow.devices.size());

        // The turn happens during review, before awaitNextPage is registered.
        idle(100); frame(180); idle(100); frame(180, true); idle(100); frame(180);
        AtomicInteger ready = new AtomicInteger();
        camera.awaitNextPage(() -> { ready.incrementAndGet(); camera.captureOnce(); }); idle(0);
        assertEquals(2, currentDevice().session.captures);
        idle(400); result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(3, first.captures);
        idle(100);
        oldFocusCallback.onCaptureCompleted(first, oldFocusRequest,
                metadata(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        frame(180); idle(50);
        assertEquals("the previous page's AF callback cannot acknowledge the new START", 0, ready.get());
        oldFocusCallback.onCaptureFailed(first, oldFocusRequest, null);
        assertTrue("the previous page's AF failure cannot cancel the new page", failures.isEmpty());
        finishAutoFocusThenOneJpeg(mode, ready, 2);
        assertEquals(1, ManagerShadow.devices.size()); assertTrue(failures.isEmpty());
    }

    private void finishAutoFocusThenOneJpeg(int mode, AtomicInteger ready, int precedingCaptures) {
        var session = currentDevice().session;
        assertEquals("one AF START before pageReady", precedingCaptures + 1, session.captures);
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
        assertEquals(0, ready.get()); assertEquals(precedingCaptures + 1, session.captures);
        idle(100);
        triggerCallback.onCaptureCompleted(session, triggerRequest,
                metadata(CONTROL_AF_STATE_ACTIVE_SCAN, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        idle(100); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED, oldLockedAt); frame(180);
        assertEquals(0, ready.get()); assertEquals(precedingCaptures + 1, session.captures);
        idle(100); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_SEARCHING); frame(180);
        assertEquals(0, ready.get()); assertEquals(precedingCaptures + 1, session.captures);
        idle(100); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, ready.get()); assertEquals(precedingCaptures + 2, session.captures);
        assertEquals(CameraDevice.TEMPLATE_STILL_CAPTURE, ((RequestShadow)Shadow.extract(session.captured)).template);
        assertEquals(1, currentDevice().configurations);
    }

    @Test public void warmedPreviewFocusAndLargestJpegUseOneDeviceAndOneSession() {
        camera.preview(); idle(100); readyFrame();
        DocScanTestCamera device = firstDevice();
        camera.captureOnce(); camera.captureOnce(); idle(400); readyFrame(); idle(50);
        assertEquals(1, ManagerShadow.devices.size()); assertEquals(1, device.configurations);
        assertEquals(2, device.outputs.size()); assertEquals(1, device.session.captures);
        assertFalse(device.closed); assertFalse(device.session.repeatingStopped);
        RequestShadow request = Shadow.extract(device.session.captured);
        assertEquals(CameraDevice.TEMPLATE_STILL_CAPTURE, request.template);
        assertEquals(0, request.values.get(CaptureRequest.JPEG_ORIENTATION.getName()));
        assertEquals(CONTROL_AF_MODE_CONTINUOUS_PICTURE, request.values.get(CaptureRequest.CONTROL_AF_MODE.getName()));
        assertEquals(List.of(originalReader(ImageFormat.JPEG).surface), request.targets);
        ReaderShadow jpeg = originalReader(ImageFormat.JPEG);
        jpeg.image = new DocScanTestImage(new ArrayList<>());
        jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
        assertEquals(1, delivered); assertFalse(device.closed); assertFalse(jpeg.closed);
        assertFalse(originalReader(ImageFormat.YUV_420_888).closed);
        camera.pausePreview(); idle(0);
        assertTrue(device.closed); assertTrue(device.session.closed); assertTrue(jpeg.closed);
        assertTrue(originalReader(ImageFormat.YUV_420_888).closed);
        assertEquals(1, ManagerShadow.devices.size());
        assertTrue(failures.isEmpty());
    }

    @Test public void aTurnDuringTheJpegWaitRemainsAvailableAfterTheVisibleReview() {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        var device = firstDevice();
        int before = displayed;
        idle(100); frame(180, true); idle(30); frame(180);
        assertTrue("received frames must still be observed while JPEG is pending", displayed > before);
        assertFalse(device.session.repeatingStopped);
        ReaderShadow jpeg = originalReader(ImageFormat.JPEG);
        jpeg.image = new DocScanTestImage(new ArrayList<>());
        jpeg.listener.onImageAvailable(jpeg.reader); idle(3000);
        AtomicInteger ready = new AtomicInteger(); camera.awaitNextPage(ready::incrementAndGet); idle(0);
        assertEquals(0, ready.get());
        readyFrame(); assertEquals(1, ready.get());
        assertEquals(1, delivered); assertEquals(1, device.session.captures);
        assertEquals(1, ManagerShadow.devices.size()); assertEquals(1, device.configurations);
        assertFalse(jpeg.closed); assertFalse(originalReader(ImageFormat.YUV_420_888).closed);
        assertTrue(failures.isEmpty());
    }

    @Test public void theRetainedJpegReaderDrainsOldBuffersWithoutRebindingTheNextOriginal() {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        var session = firstDevice().session;
        var oldCallback = session.captureCallback; var oldRequest = session.captured;
        ReaderShadow jpeg = originalReader(ImageFormat.JPEG);
        jpeg.image = new DocScanTestImage(new ArrayList<>());
        jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
        assertEquals(1, delivered); assertFalse(jpeg.closed);

        List<String> inactiveEvents = new ArrayList<>();
        DocScanTestImage inactive = new DocScanTestImage(inactiveEvents); inactive.memoryFailure = true;
        jpeg.image = inactive; jpeg.listener.onImageAvailable(jpeg.reader);
        assertEquals(List.of("image.close"), inactiveEvents); assertTrue(failures.isEmpty());
        camera.captureOnce(); camera.captureOnce(); idle(0); readyFrame(); idle(50);
        assertEquals(2, session.captures);
        oldCallback.onCaptureSequenceAborted(session, 1);
        oldCallback.onCaptureCompleted(session, oldRequest,
                metadata(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, 20L));
        List<String> staleEvents = new ArrayList<>();
        DocScanTestImage stale = new DocScanTestImage(staleEvents); stale.memoryFailure = true;
        jpeg.image = stale; jpeg.listener.onImageAvailable(jpeg.reader);
        assertEquals(List.of("image.close"), staleEvents); assertEquals(1, delivered);

        // Native ZSL may predate the latest YUV frame; compare JPEGs, not wall/preview time.
        DocScanTestImage fresh = new DocScanTestImage(new ArrayList<>());
        fresh.timestamp = 20L; fresh.buffer = ByteBuffer.wrap(new byte[]{4, 5, 6});
        jpeg.image = fresh; jpeg.listener.onImageAvailable(jpeg.reader); idle(15000);
        assertEquals(2, delivered); assertEquals(1, ManagerShadow.devices.size());
        assertArrayEquals(new byte[]{4, 5, 6}, originals.get(1).jpeg);
        assertEquals(Long.valueOf(20), originals.get(1).provenance.imageTimestampNanos);
        assertNull("the previous request's result cannot become this JPEG's metadata",
                originals.get(1).provenance.resultTimestampNanos);
        assertNotEquals(originals.get(0).provenance.captureId, originals.get(1).provenance.captureId);
        assertNotEquals(originals.get(0).provenance.jpegSha256, originals.get(1).provenance.jpegSha256);
        assertTrue(failures.isEmpty());
    }

    @Test public void aRetainedPreviewFailureSettlesAnInFlightStillOnlyOnce() {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        var device = firstDevice();
        var jpeg = originalReader(ImageFormat.JPEG);
        device.session.previewCallback.onCaptureFailed(device.session, device.session.repeating, null);
        assertEquals(List.of("camera metering failed"), failures);
        jpeg.image = new DocScanTestImage(new ArrayList<>()); jpeg.listener.onImageAvailable(jpeg.reader);
        camera.captureOnce(); idle(15000);
        assertEquals(1, failures.size()); assertEquals(0, delivered);
        assertEquals(1, device.session.captures); assertEquals(1, ManagerShadow.devices.size());
        assertTrue(device.closed); assertTrue(jpeg.closed);
        assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
    }

    @Test public void anInactiveJpegAcquireFailureClosesTheRetainedCameraOnlyOnce() {
        inactiveJpegFailureClosesRetainedCamera(false);
    }

    @Test public void anInactiveJpegCloseMemoryFailureClosesTheRetainedCameraOnlyOnce() {
        inactiveJpegFailureClosesRetainedCamera(true);
    }

    private void inactiveJpegFailureClosesRetainedCamera(boolean closeFailure) {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        var device = firstDevice();
        var jpeg = originalReader(ImageFormat.JPEG);
        var yuv = originalReader(ImageFormat.YUV_420_888);
        jpeg.image = new DocScanTestImage(new ArrayList<>());
        jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
        assertEquals(1, delivered); assertFalse(device.closed);

        if (closeFailure) {
            // This HAL buffer's close delegates to the event sink; fail at that boundary.
            jpeg.image = new DocScanTestImage(new ArrayList<String>() {
                @Override public boolean add(String event) {
                    throw new OutOfMemoryError("synthetic native Image.close failure");
                }
            });
        } else {
            jpeg.acquireFailure = new IllegalStateException("synthetic native acquire failure");
        }
        jpeg.listener.onImageAvailable(jpeg.reader);
        assertEquals(List.of(closeFailure ? "image OutOfMemoryError" : "image IllegalStateException"), failures);
        assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
        assertTrue(device.closed); assertTrue(device.session.closed); assertTrue(jpeg.closed); assertTrue(yuv.closed);
        assertNull(ReflectionHelpers.getField(camera, "reader"));
        assertNull(ReflectionHelpers.getField(camera, "previewReader"));

        jpeg.listener.onImageAvailable(jpeg.reader);
        device.session.previewCallback.onCaptureFailed(device.session, device.session.repeating, null);
        camera.captureOnce(); camera.preview(); camera.awaitNextPage(() -> fail("UNKNOWN cannot become ready"));
        idle(15000);
        assertEquals(1, failures.size()); assertEquals(1, delivered);
        assertEquals(1, ManagerShadow.devices.size()); assertEquals(1, device.session.captures);
    }

    @Test public void pausingAnInFlightStillClosesTheRetainedSessionAfterTheImage() {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        var device = firstDevice();
        camera.pausePreview(); idle(0); assertFalse(device.closed);
        var jpeg = originalReader(ImageFormat.JPEG);
        jpeg.image = new DocScanTestImage(new ArrayList<>()); jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
        assertEquals(1, delivered); assertTrue(device.closed); assertTrue(device.session.closed);
        assertTrue(jpeg.closed); assertTrue(originalReader(ImageFormat.YUV_420_888).closed);
        assertEquals(1, ManagerShadow.devices.size()); assertTrue(failures.isEmpty());
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
        static int aeRegions;
        static boolean strictPublicApi;
        @Implementation protected <T> T get(CameraCharacteristics.Key<T> key) {
            if (strictPublicApi && ((android.os.Build.VERSION.SDK_INT < 30
                    && key.getName().equals("android.control.zoomRatioRange"))
                    || (android.os.Build.VERSION.SDK_INT < 31
                    && key.getName().equals("android.scaler.availableRotateAndCropModes"))))
                throw new AssertionError("transform key unavailable at this public API level");
            Object value = key.equals(CameraCharacteristics.LENS_FACING) ? LENS_FACING_BACK
                    : key.equals(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ? Shadow.newInstanceOf(StreamConfigurationMap.class)
                    : key.equals(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES) ? new int[]{CONTROL_AF_MODE_OFF, afMode}
                    : key.equals(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES) ? new int[]{CONTROL_AE_MODE_ON}
                    : key.equals(CameraCharacteristics.CONTROL_MAX_REGIONS_AE) ? aeRegions
                    : key.equals(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE) ? new Rect(0, 0, 4032, 3024)
                    : key.equals(CameraCharacteristics.SENSOR_INFO_PRE_CORRECTION_ACTIVE_ARRAY_SIZE) ? new Rect(0, 0, 4032, 3024)
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
        ImageReader reader; int format; Image image; boolean closed; RuntimeException acquireFailure;
        Surface surface = Shadow.newInstanceOf(Surface.class); ImageReader.OnImageAvailableListener listener;
        @Implementation protected static ImageReader newInstance(int width, int height, int format, int maxImages) {
            ImageReader reader = Shadow.newInstanceOf(ImageReader.class);
            ReaderShadow shadow = Shadow.extract(reader); shadow.reader = reader; shadow.format = format; readers.add(shadow); return reader;
        }
        @Implementation protected Surface getSurface() { return surface; }
        @Implementation protected void setOnImageAvailableListener(ImageReader.OnImageAvailableListener l, Handler h) { listener = l; }
        @Implementation protected Image acquireLatestImage() { return image; }
        @Implementation protected Image acquireNextImage() {
            if (acquireFailure != null) throw acquireFailure;
            return image;
        }
        @Implementation protected void close() { closed = true; }
    }
    @Implements(CaptureRequest.Builder.class) public static class BuilderShadow {
        int template; final Map<String,Object> values = new HashMap<>(); final List<Surface> targets = new ArrayList<>();
        Object tag;
        @Implementation protected void setTag(Object value) { tag = value; }
        @Implementation protected <T> void set(CaptureRequest.Key<T> key, T value) { values.put(key.getName(), value); }
        @Implementation protected void addTarget(Surface target) { targets.add(target); }
        @Implementation protected CaptureRequest build() {
            CaptureRequest request = Shadow.newInstanceOf(CaptureRequest.class);
            RequestShadow shadow = Shadow.extract(request); shadow.template = template;
            shadow.values.putAll(values); shadow.targets.addAll(targets); shadow.tag = tag; return request;
        }
    }
    @Implements(CaptureRequest.class) public static class RequestShadow {
        int template; final Map<String,Object> values = new HashMap<>(); final List<Surface> targets = new ArrayList<>();
        Object tag;
        @Implementation protected Object getTag() { return tag; }
        @Implementation protected <T> T get(CaptureRequest.Key<T> key) {
            @SuppressWarnings("unchecked") T value = (T)values.get(key.getName()); return value;
        }
    }
}
