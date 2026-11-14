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
import android.util.Range;
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
    private long previewCostMillis;
    private PaperGeometry.Box displayedPaper;
    private int displayedCenter;
    private Long exposureNanos = 10_000_000L;

    @Before public void setup() {
        ManagerShadow.devices.clear(); ReaderShadow.readers.clear();
        ManagerShadow.refuseSession = false; CharacteristicsShadow.fixedFocus = false;
        CharacteristicsShadow.aeRegions = 0; // AGENT_APPROVED=1: explicit comparison test setup.
        CharacteristicsShadow.strictPublicApi = false;
        CharacteristicsShadow.manualSensor = false;
        CharacteristicsShadow.maxAnalog = null; CharacteristicsShadow.fpsRanges = false;
        failures.clear(); originals.clear(); delivered = 0;
        MapShadow.previewSize = new Size(320, 240);
        MapShadow.fullSizeYuv = false; ManagerShadow.refuseOutputs = 0; previewBoost = 150;
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
                    @Override public void onPreview(Bitmap frame) {
                        displayed++; frame.recycle();
                        if (previewCostMillis > 0) org.robolectric.shadows.ShadowSystemClock.advanceBy(Duration.ofMillis(previewCostMillis));
                    }
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


    private byte[] fineGlyphPage(boolean alternate) {
        byte[] pixels = new byte[320 * 240]; java.util.Arrays.fill(pixels, (byte)235);
        String[] glyph = alternate
                ? new String[]{"00100", "01100", "00100", "00100", "00100", "00100", "01110"}
                : new String[]{"01110", "11011", "11011", "11011", "11011", "11011", "01110"};
        for (int cy = 0; cy < 23; cy++) for (int cx = 0; cx < 31; cx++)
            for (int y = 0; y < 7; y++) for (int x = 0; x < 5; x++)
                if (glyph[y].charAt(x) == '1') pixels[(cy * 10 + y + 1) * 320 + cx * 10 + x + 1] = 30;
        return pixels;
    }
    private void fineFrame(byte[] luma) {
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
        image.format = ImageFormat.YUV_420_888;
        image.width = luma.length == 640 * 480 ? 640 : 320; image.height = luma.length / image.width;
        image.rowStride = image.width * 2 + 7; image.pixelStride = 2;
        byte[] storage = new byte[7 + image.rowStride * image.height]; java.util.Arrays.fill(storage, (byte)9);
        for (int y = 0; y < image.height; y++) for (int x = 0; x < image.width; x++)
            storage[7 + y * image.rowStride + x * 2] = luma[y * image.width + x];
        image.buffer = ByteBuffer.wrap(storage); image.buffer.position(7);
        image.timestamp = SystemClock.elapsedRealtimeNanos();
        ReaderShadow reader = currentReader(ImageFormat.YUV_420_888);
        reader.image = image; reader.listener.onImageAvailable(reader.reader);
    }
    private void fineReadyFrame(byte[] luma) {
        idle(100); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); fineFrame(luma);
    }
    private void fineClock(java.util.function.LongSupplier clock) {
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange");
        // Functional camera fixtures control work time; separate tests exercise the real deadline.
        ReflectionHelpers.setField(pages, "fine", new LumaPageEvidence(clock));
    }
    private void fineNextPage(byte[] first, byte[] second) {
        camera.captureOnce(); idle(0); fineClock(() -> 0L);
        for (int i = 0; i < 8; i++) fineReadyFrame(first);
        assertEquals("one original before a turn", 1, firstDevice().session.captures);
        selectionJpeg(new byte[]{1, 2, 3});
        AtomicInteger next = new AtomicInteger(); camera.awaitNextPage(next::incrementAndGet); idle(0);
        for (int i = 0; i < 8; i++) fineReadyFrame(second);
        assertEquals("changed native-area content must reach the real next-page callback", 1, next.get());
        assertTrue(failures.isEmpty()); camera.close(); idle(0);
    }
    @Test public void fineGlyphChangesBetweenTheCoarsePointsReachTheNextPageCallback() {
        fineNextPage(fineGlyphPage(false), fineGlyphPage(true));
    }
    @Test public void aLocalizedSixthOfThePageReachesTheNextPageCallback() {
        byte[] first = new byte[320 * 240]; java.util.Arrays.fill(first, (byte)220);
        byte[] second = first.clone(); java.util.Arrays.fill(second, 80 * 320, 120 * 320, (byte)160);
        fineNextPage(first, second);
    }

    @Test public void fineOnlyMotionRestartsTheRealShutterWaitEvenWhenThePageIdentityMatches() {
        byte[] page = fineGlyphPage(false);
        camera.captureOnce(); idle(0); fineClock(() -> 0L);
        for (int i = 0; i < 8; i++) fineReadyFrame(page);
        selectionJpeg(new byte[]{1, 2, 3});
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange"); long scene = pages.sequence();
        byte[] shifted = page.clone();
        for (int y = 0; y < 240; y++) for (int x = 0; x < 320; x++)
            shifted[y * 320 + x] = page[Math.min(239, y + 1) * 320 + Math.min(319, x + 1)];
        fineReadyFrame(shifted); assertEquals(scene, pages.sequence());
        camera.captureOnce(); idle(350);
        assertEquals("registered page motion still needs its own quiet interval", 1, firstDevice().session.captures);
        fineReadyFrame(shifted); idle(0); assertEquals(2, firstDevice().session.captures);
        assertTrue(failures.isEmpty()); camera.close(); idle(0);
    }
    @Test public void fineOnlyABATurnsKeepTwoFutureOriginalsWithoutReplacingTheVisibleOriginal() {
        fineFutureABA(fineGlyphPage(false), fineGlyphPage(true));
    }
    private void fineFutureABA(byte[] a, byte[] b) {
        camera.captureOnce(); idle(0); fineClock(() -> 0L);
        for (int i = 0; i < 8; i++) fineReadyFrame(a);
        selectionJpeg(new byte[]{1, 2, 3});
        List<byte[]> originals = new ArrayList<>(); AtomicInteger gaps = new AtomicInteger();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean matched) {
                assertTrue(matched); assertNotNull(source); originals.add(jpeg);
            }
            public void onPageMissed() { gaps.incrementAndGet(); }
        }); idle(0);
        for (int i = 0; i < 8; i++) fineReadyFrame(b);
        assertEquals(2, firstDevice().session.captures); selectionJpeg(new byte[]{4, 5, 6});
        for (int i = 0; i < 8; i++) fineReadyFrame(a);
        assertEquals(3, firstDevice().session.captures); selectionJpeg(new byte[]{7, 8, 9});
        assertEquals(0, gaps.get());
        for (int i = 0; i < 8; i++) fineReadyFrame(b);
        assertEquals(3, firstDevice().session.captures); assertEquals(1, gaps.get());
        assertEquals(1, delivered); assertEquals(2, originals.size());
        assertArrayEquals(new byte[]{4, 5, 6}, originals.get(0));
        assertArrayEquals(new byte[]{7, 8, 9}, originals.get(1));
        assertTrue(failures.isEmpty()); camera.close(); idle(0);
    }

    private byte[] fineGlyph640(boolean alternate) {
        byte[] small = fineGlyphPage(alternate), large = new byte[640 * 480];
        for (int y = 0; y < 480; y++) for (int x = 0; x < 640; x++) large[y * 640 + x] = small[(y / 2) * 320 + x / 2];
        return large;
    }
    @Test public void fine640GlyphsUseTheHalChosenPreviewWithoutChangingItsRequestedDimensions() {
        MapShadow.previewSize = new Size(640, 480);
        fineNextPage(fineGlyph640(false), fineGlyph640(true));
        ReaderShadow preview = originalReader(ImageFormat.YUV_420_888);
        assertEquals(640, preview.width); assertEquals(480, preview.height);
    }
    @Test public void fine640ABATurnsKeepTwoFutureOriginalsAtTheExistingCapacity() {
        MapShadow.previewSize = new Size(640, 480); fineFutureABA(fineGlyph640(false), fineGlyph640(true));
    }
    @Test public void fine640LocalizedSixthStillReachesTheNextPageCallback() {
        MapShadow.previewSize = new Size(640, 480);
        byte[] first = new byte[640 * 480]; java.util.Arrays.fill(first, (byte)220);
        byte[] second = first.clone(); java.util.Arrays.fill(second, 160 * 640, 240 * 640, (byte)160);
        fineNextPage(first, second);
    }

    @Test public void twoIncompleteComparisonsRetainTheOriginalAndStillWaitFourHundredMillisAfterPositive() {
        MapShadow.previewSize = new Size(640, 480);
        camera.captureOnce(); idle(0);
        final class WorkClock implements java.util.function.LongSupplier {
            boolean expired; int reads;
            @Override public long getAsLong() {
                return expired && reads++ > 0 ? LumaPageEvidence.MAX_COMPARE_NANOS : 0L;
            }
        }
        WorkClock clock = new WorkClock(); fineClock(clock);
        byte[] a = fineGlyph640(false), b = fineGlyph640(true), original = new byte[]{1, 2, 3};
        for (int i = 0; i < 8; i++) fineReadyFrame(a);
        assertEquals(1, firstDevice().session.captures); selectionJpeg(original);
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange");
        LumaPageEvidence fine = ReflectionHelpers.getField(pages, "fine"); long initial = pages.sequence();
        AtomicInteger next = new AtomicInteger(); camera.awaitNextPage(next::incrementAndGet); idle(0);
        clock.expired = true; int unknown = 0;
        for (int i = 0; i < 4; i++) {
            clock.reads = 0; fineReadyFrame(b);
            if (fine.status().equals("time_budget")) unknown++;
            assertEquals(initial, pages.sequence()); assertEquals(0, next.get());
            assertEquals(1, firstDevice().session.captures); assertEquals(1, originals.size());
            assertArrayEquals(original, originals.get(0).jpeg);
        }
        assertEquals("exactly two eligible searches exhausted their work budget", 2, unknown);
        clock.expired = false;
        fineReadyFrame(b); assertEquals(initial, pages.sequence()); // The intervening frame remains throttled.
        fineReadyFrame(b); assertEquals("different", fine.status()); assertEquals(6561, fine.evaluatedOffsets());
        assertEquals(initial + 1, pages.sequence()); assertEquals(0, next.get());
        long positiveAt = SystemClock.elapsedRealtime();
        idle(399); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); fineFrame(b);
        assertEquals(positiveAt + 399, SystemClock.elapsedRealtime());
        assertFalse(pages.ready(SystemClock.elapsedRealtime())); assertEquals(0, next.get());
        idle(1); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); fineFrame(b);
        assertTrue(pages.ready(SystemClock.elapsedRealtime())); assertEquals(1, next.get());
        assertEquals(1, firstDevice().session.captures); assertEquals(1, delivered);
        assertArrayEquals(original, originals.get(0).jpeg); assertTrue(failures.isEmpty());
        camera.close(); idle(0);
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
        // The preview that returned after the still has settled: its frames count as page evidence again.
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED);
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

    private void prepareManualStill() {
        CharacteristicsShadow.fixedFocus = true;
        CharacteristicsShadow.manualSensor = true;
        camera.captureOnce(); idle(100);
        for (int i = 0; i < 8; i++) {
            TotalCaptureResult result = manualResult(SystemClock.elapsedRealtimeNanos(), 10_000_000L, 800, CONTROL_AE_MODE_ON);
            var session = currentDevice().session;
            session.previewCallback.onCaptureCompleted(session, session.repeating, result);
            frame(180); idle(100);
        }
        assertEquals(1, firstDevice().session.captures);
    }

    private TotalCaptureResult manualResult(long timestamp, long exposure, int iso) {
        return manualResult(timestamp, exposure, iso, CONTROL_AE_MODE_OFF);
    }

    private int previewBoost = 150;

    private TotalCaptureResult manualResult(long timestamp, long exposure, int iso, int aeMode) {
        TotalCaptureResult result = ShadowTotalCaptureResult.newTotalCaptureResult();
        ShadowCaptureResult values = Shadow.extract(result);
        values.set(CaptureResult.CONTROL_AF_STATE, CONTROL_AF_STATE_INACTIVE);
        values.set(CaptureResult.CONTROL_AE_STATE, CONTROL_AE_STATE_CONVERGED);
        values.set(CaptureResult.SENSOR_TIMESTAMP, timestamp);
        values.set(CaptureResult.SENSOR_EXPOSURE_TIME, exposure);
        values.set(CaptureResult.SENSOR_SENSITIVITY, iso);
        values.set(CaptureResult.SENSOR_FRAME_DURATION, 33_333_333L);
        values.set(CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST, previewBoost);
        values.set(CaptureResult.CONTROL_AE_MODE, aeMode);
        values.set(CaptureResult.CONTROL_AWB_LOCK, true);
        return result;
    }

    private List<String> manualJpeg(long timestamp) {
        var reader = currentReader(ImageFormat.JPEG);
        List<String> events = new ArrayList<>();
        DocScanTestImage image = new DocScanTestImage(events);
        image.timestamp = timestamp; image.buffer = ByteBuffer.wrap(new byte[]{1, 2, 3});
        reader.image = image; reader.listener.onImageAvailable(reader.reader); idle(0);
        return events;
    }

    private void manualCompleted(TotalCaptureResult result) {
        var session = firstDevice().session;
        session.captureCallback.onCaptureCompleted(session, session.captured, result); idle(0);
    }

    @Test public void manualStillCopiesTheFreshExposureAndGainWithoutChangingTheRepeatingRequest() {
        prepareManualStill();
        var session = firstDevice().session;
        assertEquals(Integer.valueOf(CONTROL_AE_MODE_OFF), session.captured.get(CaptureRequest.CONTROL_AE_MODE));
        assertEquals(Long.valueOf(10_000_000), session.captured.get(CaptureRequest.SENSOR_EXPOSURE_TIME));
        assertEquals(Integer.valueOf(800), session.captured.get(CaptureRequest.SENSOR_SENSITIVITY));
        assertEquals(Long.valueOf(33_333_333), session.captured.get(CaptureRequest.SENSOR_FRAME_DURATION));
        assertEquals(Integer.valueOf(150), session.captured.get(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
        assertEquals(Boolean.TRUE, session.captured.get(CaptureRequest.CONTROL_AWB_LOCK));
        assertEquals(Integer.valueOf(CONTROL_AE_MODE_ON), session.repeating.get(CaptureRequest.CONTROL_AE_MODE));
        assertNull(session.repeating.get(CaptureRequest.SENSOR_EXPOSURE_TIME));
    }

    private TotalCaptureResult flickerResult(long exposure, int iso, Integer flicker) {
        TotalCaptureResult result = manualResult(SystemClock.elapsedRealtimeNanos(), exposure, iso, CONTROL_AE_MODE_ON);
        if (flicker != null) ((ShadowCaptureResult)Shadow.extract(result)).set(CaptureResult.STATISTICS_SCENE_FLICKER, flicker);
        return result;
    }

    private void prepareFlickerStill(long previewExposure, int iso, Integer flicker) {
        CharacteristicsShadow.fixedFocus = true;
        CharacteristicsShadow.manualSensor = true;
        camera.captureOnce(); idle(100);
        for (int i = 0; i < 8; i++) {
            var session = currentDevice().session;
            session.previewCallback.onCaptureCompleted(session, session.repeating, flickerResult(previewExposure, iso, flicker));
            frame(180); idle(100);
        }
        assertEquals(1, firstDevice().session.captures);
    }

    /**
     * Glasses, 2026-11-13: a still asked for manually at a shorter exposure and more gain than the preview's auto
     * exposure was running had three times the noise of an auto-exposed one at the same values, and one flicker
     * period with the gain raised by hand was colour noise beside the glasses' own camera. The still copies what
     * the preview measured, whatever the flicker (the 2026-11-10 one-period rule is withdrawn).
     */
    @Test public void theStillCopiesWhatThePreviewsAutoExposureMeasuredWhateverTheFlicker() {
        prepareFlickerStill(25_000_000L, 100, STATISTICS_SCENE_FLICKER_60HZ);
        var session = firstDevice().session;
        assertEquals(Integer.valueOf(CONTROL_AE_MODE_OFF), session.captured.get(CaptureRequest.CONTROL_AE_MODE));
        assertEquals(Long.valueOf(25_000_000), session.captured.get(CaptureRequest.SENSOR_EXPOSURE_TIME));
        assertEquals(Integer.valueOf(100), session.captured.get(CaptureRequest.SENSOR_SENSITIVITY));
        assertEquals(Integer.valueOf(150), session.captured.get(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
        assertNull("a low gain leaves the template's edge enhancement", session.captured.get(CaptureRequest.EDGE_MODE));
        long timestamp = SystemClock.elapsedRealtimeNanos();
        manualCompleted(manualResult(timestamp, 25_000_000L, 100)); manualJpeg(timestamp);
        assertEquals(1, delivered); assertTrue(originals.get(0).associationResolved);
        setup(); CharacteristicsShadow.maxAnalog = 800; previewBoost = 766;
        prepareFlickerStill(30_000_000L, 800, STATISTICS_SCENE_FLICKER_50HZ);
        assertEquals("a dim scene is not shortened by hand", Long.valueOf(30_000_000),
                firstDevice().session.captured.get(CaptureRequest.SENSOR_EXPOSURE_TIME));
        assertEquals(Integer.valueOf(800), firstDevice().session.captured.get(CaptureRequest.SENSOR_SENSITIVITY));
        assertEquals(Integer.valueOf(766), firstDevice().session.captured.get(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST));
        assertEquals("at this gain edge enhancement makes specks of the noise", Integer.valueOf(CaptureRequest.EDGE_MODE_OFF),
                firstDevice().session.captured.get(CaptureRequest.EDGE_MODE));
    }

    /** The measured scenes: a lit room (25 ms at 235) and the dim desk (60 ms at 3064, 30 ms at 6128, 10 ms spent near 10000). */
    @Test public void theExposurePaceFollowsTheLightAndLeavingNeedsMoreThanEntering() {
        int plain = GlassCamera.ExposurePace.DEFAULT, mid = GlassCamera.ExposurePace.MID, fast = GlassCamera.ExposurePace.FAST;
        long sixty = 8_333_333L, fifty = 10_000_000L;
        assertEquals(fast, GlassCamera.ExposurePace.next(plain, true, true, 25_000_000L, 235, sixty));
        assertEquals(fast, GlassCamera.ExposurePace.next(fast, true, true, 8_333_333L, 705, sixty));
        assertEquals(mid, GlassCamera.ExposurePace.next(plain, true, true, 60_000_000L, 3064, fifty));
        assertEquals(mid, GlassCamera.ExposurePace.next(mid, true, true, 30_000_000L, 6128, fifty));
        assertEquals("the gain is spent at one period", mid, GlassCamera.ExposurePace.next(fast, true, true, 10_000_000L, 10_000, fifty));
        // A worn head never held the template's 50-60 ms (limit 0.02 rad/s, 2026-11-12). Smear cannot be undone and
        // noise can be averaged out, so a darker scene keeps 30 ms and pays in gain or brightness.
        assertEquals("darker still: 30 ms stays", mid, GlassCamera.ExposurePace.next(mid, true, true, 30_000_000L, 9_000, fifty));
        assertEquals("the desk of 2026-11-14: 60 ms at 3320", mid, GlassCamera.ExposurePace.next(plain, true, true, 60_000_000L, 3_320, fifty));
        assertEquals(mid, GlassCamera.ExposurePace.next(plain, true, true, 60_000_000L, 12_000, fifty));
        assertEquals("a camera with only the fast range", plain, GlassCamera.ExposurePace.next(fast, false, true, 10_000_000L, 10_000, fifty));
        assertEquals("a camera without the ranges keeps the template's", plain,
                GlassCamera.ExposurePace.next(plain, false, false, 25_000_000L, 235, sixty));
        assertTrue(GlassCamera.ExposurePace.measuredUnder(fast, new Range<>(60, 60)));
        assertFalse("a result from the range asked before", GlassCamera.ExposurePace.measuredUnder(fast, new Range<>(14, 30)));
        assertTrue(GlassCamera.ExposurePace.measuredUnder(plain, new Range<>(30, 30)));
    }

    @Test public void aLitPreviewAsksItsAutoExposureForTheFastRangeAndTheStillCopiesAResultMeasuredUnderIt() {
        CharacteristicsShadow.fixedFocus = true; CharacteristicsShadow.manualSensor = true; CharacteristicsShadow.fpsRanges = true;
        createCamera(); camera.captureOnce(); idle(100);
        var session = currentDevice().session;
        assertNull("the template's own range to begin with", session.repeating.get(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE));
        session.previewCallback.onCaptureCompleted(session, session.repeating, flickerResult(25_000_000L, 235, STATISTICS_SCENE_FLICKER_60HZ));
        assertEquals(new Range<>(60, 60), currentDevice().session.repeating.get(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE));
        assertEquals("no still from the exposure measured before", 0, firstDevice().session.captures);
        for (int i = 0; i < 8; i++) {
            var now = currentDevice().session;
            TotalCaptureResult result = flickerResult(8_333_333L, 705, STATISTICS_SCENE_FLICKER_60HZ);
            ((ShadowCaptureResult)Shadow.extract(result)).set(CaptureResult.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(60, 60));
            now.previewCallback.onCaptureCompleted(now, now.repeating, result);
            frame(180); idle(100);
        }
        assertEquals(1, firstDevice().session.captures);
        assertEquals(Long.valueOf(8_333_333), firstDevice().session.captured.get(CaptureRequest.SENSOR_EXPOSURE_TIME));
        assertEquals(Integer.valueOf(705), firstDevice().session.captured.get(CaptureRequest.SENSOR_SENSITIVITY));
        assertTrue(failures.isEmpty());
    }

    private void quiet(ShadowSensorManager sensors) {
        SensorEvent event = ShadowSensorManager.createSensorEvent(3);
        event.timestamp = SystemClock.elapsedRealtimeNanos(); event.values[0] = 0f;
        sensors.sendSensorEventToListeners(event);
        idle(50);
        var session = currentDevice().session;
        session.previewCallback.onCaptureCompleted(session, session.repeating,
                flickerResult(8_333_333L, 200, STATISTICS_SCENE_FLICKER_60HZ));
        frame(180);
    }

    /** The fake HAL answers the request in flight: its result, then its JPEG. */
    private void bracketStill(int marker, long exposure, int iso) {
        idle(1);
        long timestamp = SystemClock.elapsedRealtimeNanos();
        manualCompleted(manualResult(timestamp, exposure, iso));
        var reader = currentReader(ImageFormat.JPEG);
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>());
        image.timestamp = timestamp; image.buffer = ByteBuffer.wrap(new byte[]{(byte)marker, 2, 3});
        reader.image = image; reader.listener.onImageAvailable(reader.reader); idle(0);
    }

    private ShadowSensorManager bracketCamera(boolean explicit) {
        SensorManager manager = (SensorManager)RuntimeEnvironment.getApplication()
                .getSystemService(android.content.Context.SENSOR_SERVICE);
        ShadowSensorManager sensors = shadowOf(manager);
        sensors.addSensor(ShadowSensor.newInstance(Sensor.TYPE_GYROSCOPE));
        CharacteristicsShadow.fixedFocus = true; CharacteristicsShadow.manualSensor = true;
        createCamera(); camera.settingsBracket(explicit); camera.captureOnce(); idle(0);
        for (int i = 0; i < 14 && firstDevice().session.captures == 0; i++) quiet(sensors);
        assertEquals(1, firstDevice().session.captures);
        bracketStill(1, 8_333_333L, 200);
        assertEquals(1, delivered);
        return sensors;
    }

    private static java.io.File bracketDirectory() {
        java.io.File[] runs = new java.io.File(RuntimeEnvironment.getApplication().getFilesDir(), "settings-bracket").listFiles();
        return runs == null || runs.length != 1 ? null : runs[0];
    }

    private static List<org.json.JSONObject> bracketJournal() throws Exception {
        List<org.json.JSONObject> lines = new ArrayList<>();
        for (String line : java.nio.file.Files.readAllLines(new java.io.File(bracketDirectory(), "journal.jsonl").toPath()))
            lines.add(new org.json.JSONObject(line));
        return lines;
    }

    @Test public void theSettingsBracketIsAnExplicitNativeOnlyNonpersistentGate() {
        assertFalse(DocScanGlassActivity.settingsBracket(new android.content.Intent()));
        assertTrue(DocScanGlassActivity.settingsBracket(new android.content.Intent().putExtra("settings_bracket", true)));
        assertEquals(GlassCamera.Mode.NATIVE_STILL, DocScanGlassActivity.evaluationMode(new android.content.Intent()
                .putExtra("settings_bracket", true)));
        for (String other : new String[]{"zsl_evaluation", "video_evaluation", "paper_geometry_evaluation",
                "native_selection", "wrong_type"}) {
            android.content.Intent intent = new android.content.Intent().putExtra("settings_bracket", true);
            if (other.equals("wrong_type")) intent.putExtra("settings_bracket", "true"); else intent.putExtra(other, true);
            assertThrows(other, IllegalArgumentException.class, () -> DocScanGlassActivity.evaluationMode(intent));
        }
        assertFalse(camera.settingsBracket());
        camera.nativeSelection(true);
        assertThrows(IllegalArgumentException.class, () -> camera.settingsBracket(true));
    }

    /** Plan step 5: the wearer looks at one sheet once; the app changes one setting per still by itself. */
    @Test public void theSettingsBracketRetakesTheSameSceneWithOneSettingChangedAndNeverAsAPage() throws Exception {
        ShadowSensorManager sensors = bracketCamera(true);
        var session = firstDevice().session;
        Object[][] expected = {
                {"ev+1", 8_333_333L, 400, null, null, null}, {"ev+2", 8_333_333L, 800, null, null, null},
                {"two-periods", 16_666_666L, 100, null, null, null},
                {"nr-off-edge-off", 8_333_333L, 200, NOISE_REDUCTION_MODE_OFF, EDGE_MODE_OFF, null},
                {"nr-hq-edge-hq", 8_333_333L, 200, NOISE_REDUCTION_MODE_HIGH_QUALITY, EDGE_MODE_HIGH_QUALITY, null},
                {"jpeg-90", 8_333_333L, 200, null, null, (byte)90}};
        for (int i = 0; i < expected.length; i++) {
            for (int n = 0; n < 20 && session.captures == i + 1; n++) quiet(sensors);
            String name = (String)expected[i][0];
            assertEquals(name + " must be requested", i + 2, session.captures);
            assertEquals(name, Integer.valueOf(CONTROL_AE_MODE_OFF), session.captured.get(CaptureRequest.CONTROL_AE_MODE));
            assertEquals(name, expected[i][1], session.captured.get(CaptureRequest.SENSOR_EXPOSURE_TIME));
            assertEquals(name, expected[i][2], session.captured.get(CaptureRequest.SENSOR_SENSITIVITY));
            assertEquals(name, expected[i][3], session.captured.get(CaptureRequest.NOISE_REDUCTION_MODE));
            assertEquals(name, expected[i][4], session.captured.get(CaptureRequest.EDGE_MODE));
            assertEquals(name, expected[i][5], session.captured.get(CaptureRequest.JPEG_QUALITY));
            quiet(sensors); quiet(sensors);
            assertEquals("one still in flight", i + 2, session.captures);
            bracketStill(10 + i, (Long)expected[i][1], (Integer)expected[i][2]);
            assertEquals("a bracket still is never handed to the session", 1, delivered);
            assertArrayEquals("saved before the next request", new byte[]{(byte)(10 + i), 2, 3}, java.nio.file.Files.readAllBytes(
                    new java.io.File(bracketDirectory(), String.format("set1-%02d-%s.jpg", i + 1, name)).toPath()));
        }
        for (int n = 0; n < 20; n++) quiet(sensors);
        assertEquals("the set ends after its last variant", 7, session.captures);
        List<org.json.JSONObject> journal = bracketJournal();
        assertEquals(8, journal.size());
        assertEquals("base", journal.get(0).getString("kind"));
        assertEquals(originals.get(0).provenance.jpegSha256, journal.get(0).getString("sha256"));
        assertEquals(8_333_333L, journal.get(0).getJSONObject("requested").getLong("exposure_ns"));
        for (int i = 0; i < expected.length; i++) {
            org.json.JSONObject line = journal.get(i + 1);
            assertEquals("variant", line.getString("kind")); assertEquals(expected[i][0], line.getString("name"));
            assertFalse(line.getBoolean("auto_upload_allowed")); assertTrue(line.getBoolean("metadata_matched"));
            assertEquals(((Long)expected[i][1]).longValue(), line.getJSONObject("requested").getLong("exposure_ns"));
            assertEquals(((Integer)expected[i][2]).intValue(), line.getJSONObject("actual").getInt("iso"));
        }
        assertEquals("end", journal.get(7).getString("kind")); assertEquals("complete", journal.get(7).getString("reason"));
        assertTrue(failures.isEmpty());
    }

    @Test public void aPageTurnEndsTheBracketAndTheStillInFlightIsKept() throws Exception {
        ShadowSensorManager sensors = bracketCamera(true);
        var session = firstDevice().session;
        for (int n = 0; n < 20 && session.captures == 1; n++) quiet(sensors);
        assertEquals(2, session.captures);
        idle(30); frame(180, true); idle(30); frame(180); idle(400);
        bracketStill(10, 8_333_333L, 400);
        for (int n = 0; n < 20; n++) quiet(sensors);
        assertEquals("no still of another page may enter this set", 2, session.captures);
        List<org.json.JSONObject> journal = bracketJournal();
        assertEquals("variant", journal.get(1).getString("kind"));
        assertFalse(journal.get(1).getBoolean("same_scene"));
        assertEquals("scene_changed", journal.get(journal.size() - 1).getString("reason"));
        assertEquals(1, delivered); assertTrue(failures.isEmpty());
    }

    @Test public void aBracketStillTheCameraDidNotTakeAsAskedIsRecordedAsSuchAndTheSetGoesOn() throws Exception {
        ShadowSensorManager sensors = bracketCamera(true);
        var session = firstDevice().session;
        for (int n = 0; n < 20 && session.captures == 1; n++) quiet(sensors);
        bracketStill(10, 16_666_666L, 400); // twice the requested exposure
        for (int n = 0; n < 20 && session.captures == 2; n++) quiet(sensors);
        assertEquals("the completed comparison still is not an unknown capture", 3, session.captures);
        assertFalse(bracketJournal().get(1).getBoolean("metadata_matched"));
        assertEquals(16_666_666L, bracketJournal().get(1).getJSONObject("actual").getLong("exposure_ns"));
        assertTrue(failures.isEmpty());
    }

    @Test public void withoutTheExplicitLaunchNoExtraStillFollowsAPage() {
        ShadowSensorManager sensors = bracketCamera(false);
        for (int n = 0; n < 20; n++) quiet(sensors);
        assertEquals(1, firstDevice().session.captures);
        assertNull(bracketDirectory());
        assertTrue(failures.isEmpty());
    }

    @Test public void manualJpegWaitsForItsResultWithTheNativeImageAlreadyClosed() {
        prepareManualStill();
        long timestamp = SystemClock.elapsedRealtimeNanos();
        List<String> events = manualJpeg(timestamp);
        assertEquals(List.of("image.close"), events); assertEquals(0, delivered);
        manualCompleted(manualResult(timestamp, 9_999_000L, 799));
        assertEquals(1, delivered); assertTrue(originals.get(0).associationResolved);
        assertEquals(Long.valueOf(9_999_000L), originals.get(0).provenance.exposureNanos);
        idle(15_000); assertEquals(1, delivered); assertTrue(failures.isEmpty());
    }

    @Test public void manualResultCanArriveBeforeItsJpeg() {
        prepareManualStill();
        long timestamp = SystemClock.elapsedRealtimeNanos();
        manualCompleted(manualResult(timestamp, 10_000_000L, 800));
        assertEquals(0, delivered); manualJpeg(timestamp);
        assertEquals(1, delivered); assertTrue(originals.get(0).associationResolved);
    }

    @Test public void manualJpegWithoutMetadataIsRetainedUnresolvedAtTheOriginalDeadline() {
        prepareManualStill();
        long timestamp = SystemClock.elapsedRealtimeNanos();
        manualJpeg(timestamp); assertEquals(0, delivered);
        idle(15_000);
        assertEquals(1, delivered); assertFalse(originals.get(0).associationResolved);
        assertArrayEquals(new byte[]{1, 2, 3}, originals.get(0).jpeg);
        manualCompleted(manualResult(timestamp, 10_000_000L, 800));
        assertEquals(1, delivered); assertFalse(originals.get(0).associationResolved);
    }

    @Test public void aLongerActualExposureIsRetainedWithoutOrdinaryAcceptance() {
        prepareManualStill();
        long timestamp = SystemClock.elapsedRealtimeNanos();
        manualCompleted(manualResult(timestamp, 66_666_666L, 800)); manualJpeg(timestamp);
        assertEquals(1, delivered); assertFalse(originals.get(0).associationResolved);
        assertEquals(Long.valueOf(66_666_666L), originals.get(0).provenance.exposureNanos);
    }

    @Test public void mismatchedManualMetadataCannotAuthorizeOrDescribeTheJpeg() {
        prepareManualStill();
        long timestamp = SystemClock.elapsedRealtimeNanos();
        manualJpeg(timestamp); manualCompleted(manualResult(timestamp + 1, 10_000_000L, 800));
        assertEquals(1, delivered); assertFalse(originals.get(0).associationResolved);
        assertNull(originals.get(0).provenance.resultTimestampNanos);
    }

    @Test public void laterPreviewExposureCannotRelaxTheIssuedManualStillsBudget() {
        prepareManualStill();
        long timestamp = SystemClock.elapsedRealtimeNanos();
        var session = firstDevice().session;
        session.previewCallback.onCaptureCompleted(session, session.repeating,
                manualResult(timestamp, 20_000_000L, 800, CONTROL_AE_MODE_ON));
        idle(1);
        long capturedAt = SystemClock.elapsedRealtimeNanos();
        manualCompleted(manualResult(capturedAt, 15_000_000L, 800)); manualJpeg(capturedAt);
        assertEquals(1, delivered); assertFalse(originals.get(0).associationResolved);
    }

    @Test public void autoExposureInAResultCannotAcknowledgeAManualRequest() {
        prepareManualStill();
        long timestamp = SystemClock.elapsedRealtimeNanos();
        manualCompleted(manualResult(timestamp, 10_000_000L, 800, CONTROL_AE_MODE_ON)); manualJpeg(timestamp);
        assertEquals(1, delivered); assertFalse(originals.get(0).associationResolved);
    }

    @Test public void endingTheCameraPreservesAJpegAlreadyAwaitingItsMetadata() {
        prepareManualStill();
        long timestamp = SystemClock.elapsedRealtimeNanos();
        manualJpeg(timestamp); camera.close(); idle(0);
        assertEquals(1, delivered); assertFalse(originals.get(0).associationResolved);
        assertArrayEquals(new byte[]{1, 2, 3}, originals.get(0).jpeg);
        manualCompleted(manualResult(timestamp, 10_000_000L, 800)); assertEquals(1, delivered);
    }

    @Test public void delayedRealtimePreviewAndResultsCannotAuthorizeAManualStill() {
        CharacteristicsShadow.fixedFocus = true; CharacteristicsShadow.manualSensor = true;
        camera.captureOnce(); idle(100);
        for (int i = 0; i < 8; i++) {
            long oldTimestamp = SystemClock.elapsedRealtimeNanos();
            idle(CameraReadiness.FRESH_MILLIS + 1);
            var session = firstDevice().session;
            session.previewCallback.onCaptureCompleted(session, session.repeating,
                    manualResult(oldTimestamp, 10_000_000L, 800, CONTROL_AE_MODE_ON));
            frame(currentReader(ImageFormat.YUV_420_888), 180, false, oldTimestamp);
            idle(50); assertEquals(0, session.captures);
        }
        for (int i = 0; i < 8; i++) {
            var session = firstDevice().session;
            session.previewCallback.onCaptureCompleted(session, session.repeating,
                    manualResult(SystemClock.elapsedRealtimeNanos(), 10_000_000L, 800, CONTROL_AE_MODE_ON));
            frame(180); idle(100);
        }
        assertEquals(1, firstDevice().session.captures);
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
            event.timestamp = SystemClock.elapsedRealtimeNanos();
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
        assertEquals("motion settled, but the previous page's metering is insufficient", 0, firstDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); idle(50);
        assertEquals(1, firstDevice().session.captures);
        assertEquals(2, displayed); assertTrue(failures.isEmpty());
    }

    @Test public void aNewSceneCannotBorrowThePreviousPagesStillFreshMetering() {
        camera.preview(); idle(100);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        idle(400); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        idle(30); frame(180, true); idle(30); frame(180);
        camera.captureOnce(); idle(400);
        // The old result is only 460 ms old, but describes the page before the turn.
        assertEquals("freshness alone cannot authorize a different scene", 0, firstDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_SEARCHING); frame(180); idle(50);
        assertEquals("the new scene must actually converge", 0, firstDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, firstDevice().session.captures);
        assertTrue(failures.isEmpty());
    }

    @Test public void automaticNextPageWaitsForItsOwnMeteringOnFixedFocusHardware() {
        CharacteristicsShadow.fixedFocus = true;
        camera.preview(); idle(100);
        result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); frame(180);
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange"); pages.consumed();
        AtomicInteger ready = new AtomicInteger(); camera.awaitNextPage(ready::incrementAndGet); idle(0);
        idle(30); frame(180, true); idle(30); frame(180); idle(400); frame(180);
        assertEquals("a fixed lens still requires this page's exposure", 0, ready.get());
        idle(1); result(CONTROL_AF_STATE_INACTIVE, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(1, ready.get()); assertTrue(failures.isEmpty());
    }

    /**
     * Glasses, 2026-11-11: frames handled back to back kept metering results and gyro readings waiting on the
     * same thread until they were stale, and no still was taken in 143 s.
     */
    @Test public void aSlowFrameLeavesTheThreadFreeForAsLongAsItTookAndDoesNotMoveThePlane() {
        camera.preview(); idle(100);
        previewCostMillis = 170;
        frame(180);
        ReaderShadow preview = currentReader(ImageFormat.YUV_420_888);
        assertEquals(1, displayed);
        assertEquals("the copy must leave the camera's plane where it was", 0, ((DocScanTestImage) preview.image).buffer.position());

        idle(100); frame(180);
        assertEquals("100 ms after a 170 ms frame the thread still belongs to the queued results", 1, displayed);
        idle(70); frame(180);
        assertEquals(2, displayed);
        assertTrue(failures.isEmpty());
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

    @Test public void aQueuedClosedReaderFailureCannotStopTheCurrentPreview() {
        camera.preview(); idle(100); frame(180);
        ReaderShadow old = currentReader(ImageFormat.YUV_420_888);
        camera.pausePreview(); idle(0); camera.preview(); idle(100);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        DocScanTestCamera reopened = currentDevice();
        assertTrue(old.closed);
        old.acquireFailure = new IllegalStateException("closed native reader");
        old.listener.onImageAvailable(old.reader);
        assertTrue("a stale reader must be rejected before native acquisition", failures.isEmpty());
        assertFalse(reopened.closed);
        camera.captureOnce(); idle(400);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, reopened.session.captures); assertTrue(failures.isEmpty());
    }

    @Test public void aReopenedSamePageNeedsMeteringFromItsFirstObservedFrameOrLater() {
        camera.preview(); idle(100); frame(180);
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange"); pages.consumed();
        long scene = pages.sequence();
        camera.pausePreview(); idle(0); camera.preview(); idle(100);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED);
        idle(50); frame(180); // the first observation of this stream follows its early metering result
        assertEquals("a stream restart alone is not another page", scene, pages.sequence());
        camera.captureOnce(); idle(400);
        assertEquals("the previous stream's scene floor cannot admit pre-observation metering", 0, currentDevice().session.captures);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(1, currentDevice().session.captures); assertTrue(failures.isEmpty());
    }

    @Test public void currentPreviewAcquisitionFailureStillBlocksAnotherCapture() {
        camera.preview(); idle(100);
        ReaderShadow current = currentReader(ImageFormat.YUV_420_888);
        current.acquireFailure = new IllegalStateException("current native reader failure");
        current.listener.onImageAvailable(current.reader);
        assertEquals(List.of("preview unavailable"), failures);
        camera.captureOnce(); idle(100);
        assertEquals(1, ManagerShadow.devices.size());
        assertTrue(current.closed); assertTrue(currentDevice().closed);
        assertEquals(0, currentDevice().session.captures);
    }

    @Test public void autoOnlyHardwareStartsFocusBeforeTheFirstAutomaticPageCallback() {
        firstAutomaticPage(CONTROL_AF_MODE_AUTO);
    }

    @Test public void macroOnlyHardwareStartsFocusBeforeTheFirstAutomaticPageCallback() {
        firstAutomaticPage(CONTROL_AF_MODE_MACRO);
    }

    @Test public void aTurnDuringAutoFocusPreparationCannotKeepThePreviousPagesLock() {
        turnDuringFocusPreparation(CONTROL_AF_MODE_AUTO);
    }

    @Test public void aTurnDuringMacroFocusPreparationCannotKeepThePreviousPagesLock() {
        turnDuringFocusPreparation(CONTROL_AF_MODE_MACRO);
    }

    private void turnDuringFocusPreparation(int mode) {
        CharacteristicsShadow.afMode = mode;
        camera.captureOnce(); idle(100); frame(180); idle(400); frame(180);
        var session = currentDevice().session;
        assertEquals(1, session.captures);
        var oldCallback = session.captureCallback;
        var oldRequest = session.captured;
        oldCallback.onCaptureCompleted(session, oldRequest,
                metadata(CONTROL_AF_STATE_ACTIVE_SCAN, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        idle(30); frame(180, true); idle(30); frame(180); idle(400);
        result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals("the new page needs its own AF START, not the old page's locked lens", 2, session.captures);
        assertEquals(CameraDevice.TEMPLATE_PREVIEW, ((RequestShadow)Shadow.extract(session.captured)).template);
        var newCallback = session.captureCallback;
        var newRequest = session.captured;
        idle(1);
        oldCallback.onCaptureCompleted(session, oldRequest,
                metadata(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        oldCallback.onCaptureFailed(session, oldRequest, null);
        idle(50);
        assertEquals("the prior scene's completion cannot acknowledge the new AF cycle", 2, session.captures);
        assertTrue(failures.isEmpty());
        newCallback.onCaptureCompleted(session, newRequest,
                metadata(CONTROL_AF_STATE_ACTIVE_SCAN, CONTROL_AE_STATE_CONVERGED, SystemClock.elapsedRealtimeNanos()));
        idle(1); result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals(3, session.captures);
        assertEquals(CameraDevice.TEMPLATE_STILL_CAPTURE, ((RequestShadow)Shadow.extract(session.captured)).template);
        idle(30); frame(180, true); idle(30); frame(180); idle(400);
        result(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED); frame(180); idle(50);
        assertEquals("a turn cannot start another focus or JPEG request while the original is in flight", 3, session.captures);
        assertTrue(failures.isEmpty());
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
        assertEquals("the still has a session of its own", List.of(currentReader(ImageFormat.JPEG).surface), currentDevice().outputs);
    }

    /**
     * On the glasses the frame handler asked the image for its width and height once per pixel: about 150,000
     * native calls and 145-285 ms a frame (2026-11-12), 0.5 ms here, so three frames a second were handled.
     */
    /**
     * After a still the preview starts its exposure over. Its unsettled frames were read as page turns and the
     * same unmoving page was taken five times in 15 s on the glasses (2026-11-12).
     */
    @Test public void framesOfTheReturningPreviewAreNotPageEvidenceUntilItsExposureHasSettled() {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        ReaderShadow jpeg = originalReader(ImageFormat.JPEG);
        jpeg.image = new DocScanTestImage(new ArrayList<>());
        jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
        assertEquals(1, delivered);
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange");
        long scene = pages.sequence();
        idle(CameraReadiness.FRESH_MILLIS + 1); // no fresh result yet: the exposure is still moving
        frame(40); idle(30); frame(90); idle(30);
        assertEquals("unsettled frames are not a page turn", scene, pages.sequence());
        readyFrame();
        assertEquals("the same page, settled, is not a turn either", scene, pages.sequence());
        idle(100); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180, true);
        assertEquals("a real turn after that is seen", scene + 1, pages.sequence());
        assertTrue(failures.isEmpty());
    }

    private ReaderShadow readerOfWidth(int width) {
        return ReaderShadow.readers.stream().filter(r -> r.width == width && !r.closed).findFirst().orElseThrow();
    }

    /**
     * Glasses, 2026-11-12: full-size YUV arrives beside the running preview in 0.65-0.74 s, where the JPEG
     * output needs a session of its own and leaves about 3 s without preview after every still.
     */
    @Test public void aFullSizeYuvStillSharesThePreviewSessionAndIsEncodedAfterItsImageIsClosed() {
        MapShadow.fullSizeYuv = true;
        ReflectionHelpers.setField(camera, "stillWorker", (java.util.concurrent.Executor) Runnable::run);
        List<String> events = new ArrayList<>();
        int[] asked = new int[4];
        camera.stillEncoder = (nv21, width, height, quality) -> {
            assertTrue("the camera's image is returned before the slow work", events.contains("image.close"));
            asked[0] = width; asked[1] = height; asked[2] = quality; asked[3] = nv21.length;
            assertEquals(11, nv21[0]); assertEquals(12, nv21[4032 * 3024 - 1]);
            assertEquals("V first", 22, nv21[4032 * 3024]); assertEquals("then U", 33, nv21[4032 * 3024 + 1]);
            assertEquals("the last U byte comes from the U plane", 44, nv21[nv21.length - 1]);
            return new byte[]{7, 7, 7};
        };
        camera.preview(); idle(100);
        ReaderShadow preview = readerOfWidth(320), still = readerOfWidth(4032);
        assertEquals(ImageFormat.YUV_420_888, still.format);
        DocScanTestCamera device = firstDevice();
        assertEquals("one session for the preview and the still", List.of(List.of(preview.surface, still.surface)), device.configured);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED);
        frame(preview, 180, false, SystemClock.elapsedRealtimeNanos());
        camera.captureOnce(); idle(400);
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED);
        frame(preview, 180, false, SystemClock.elapsedRealtimeNanos()); idle(50);
        assertEquals(1, device.session.captures);
        RequestShadow request = Shadow.extract(device.session.captured);
        assertEquals(CameraDevice.TEMPLATE_STILL_CAPTURE, request.template);
        assertEquals(List.of(still.surface), request.targets);
        assertEquals("no second session", 1, device.configurations);

        DocScanTestImage image = new DocScanTestImage(events);
        image.format = ImageFormat.YUV_420_888; image.rowStride = 4032; image.pixelStride = 1;
        byte[] luma = new byte[4032 * 3024]; luma[0] = 11; luma[luma.length - 1] = 12;
        byte[] vu = new byte[4032 * 1512 - 1]; vu[0] = 22; vu[1] = 33;
        byte[] uv = new byte[4032 * 1512 - 1]; uv[uv.length - 1] = 44;
        image.buffer = ByteBuffer.wrap(luma); image.chromaV = ByteBuffer.wrap(vu); image.chromaU = ByteBuffer.wrap(uv);
        image.timestamp = SystemClock.elapsedRealtimeNanos();
        still.image = image;
        int shown = displayed;
        still.listener.onImageAvailable(still.reader); idle(0);
        assertArrayEquals(new int[]{4032, 3024, GlassCamera.STILL_JPEG_QUALITY, 4032 * 3024 * 3 / 2}, asked);
        assertEquals(1, delivered);
        assertArrayEquals(new byte[]{7, 7, 7}, originals.get(0).jpeg);
        assertEquals("native_still", originals.get(0).provenance.sourceKind);
        assertEquals("the preview was never replaced", 1, device.configurations);
        assertFalse(device.closed);
        idle(100); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED);
        frame(preview, 180, false, SystemClock.elapsedRealtimeNanos());
        assertTrue("frames keep being observed right after the still", displayed > shown);
        assertTrue(failures.isEmpty());
    }

    @Test public void aCameraThatRefusesThePreviewWithFullSizeYuvFallsBackToTheJpegOnItsOwnSession() {
        MapShadow.fullSizeYuv = true;
        ManagerShadow.refuseOutputs = 2;
        camera.preview(); idle(200);
        assertEquals("the camera is opened again for the fallback", 2, ManagerShadow.devices.size());
        assertTrue(firstDevice().closed);
        ReaderShadow jpeg = currentReader(ImageFormat.JPEG);
        assertEquals(List.of(List.of(readerOfWidth(320).surface)), currentDevice().configured);
        assertEquals(4032, jpeg.width);
        assertTrue(failures.isEmpty());
    }

    /**
     * Glasses, 2026-11-12: 0.55-0.9 s after a still's request two preview frames rose from a mean of 70 to 155
     * and fell back, reported as converged. Counted as page turns they took one unmoving page three times.
     */
    @Test public void framesBrightenedByTheStillInFlightAreNotPageEvidenceButAnOrdinaryTurnStillIs() {
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        assertEquals(1, firstDevice().session.captures);
        PageChange pages = ReflectionHelpers.getField(camera, "pageChange");
        long scene = pages.sequence();
        int shown = displayed;
        idle(100); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(250);
        assertEquals("the leaked exposure is not a page turn", scene, pages.sequence());
        assertEquals("and is not shown", shown, displayed);
        idle(100); result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); frame(180);
        assertEquals(scene, pages.sequence());
        idle(100); frame(180, true);
        assertEquals("a page turned while the still is in flight is still seen", scene + 1, pages.sequence());
        assertTrue(failures.isEmpty());
    }

    @Test public void aPreviewFrameAsksTheImageForItsSizeOnce() {
        camera.preview(); idle(100);
        frame(180);
        DocScanTestImage image = (DocScanTestImage) currentReader(ImageFormat.YUV_420_888).image;
        assertTrue("size and plane queries in one frame: " + image.nativeCalls, image.nativeCalls <= 3);
        assertTrue(failures.isEmpty());
    }

    /**
     * Glasses firmware 1.29.013 (2026-11-12): a session holding the JPEG output beside the preview never
     * returns the still. The preview and each still therefore have sessions of their own on one open camera.
     */
    @Test public void warmedPreviewAndLargestJpegUseOneDeviceAndTheStillItsOwnSession() {
        camera.preview(); idle(100); readyFrame();
        DocScanTestCamera device = firstDevice();
        List<Surface> preview = List.of(originalReader(ImageFormat.YUV_420_888).surface);
        List<Surface> still = List.of(originalReader(ImageFormat.JPEG).surface);
        assertEquals(List.of(preview), device.configured);
        camera.captureOnce(); camera.captureOnce(); idle(400); readyFrame(); idle(50);
        assertEquals(1, ManagerShadow.devices.size()); assertEquals(List.of(preview, still), device.configured);
        assertEquals(1, device.session.captures);
        assertFalse(device.closed); assertFalse(device.session.repeatingStopped);
        // Preview frames flushed by the change of session are not a camera failure.
        android.hardware.camera2.CaptureFailure flushed = Shadow.newInstanceOf(android.hardware.camera2.CaptureFailure.class);
        org.robolectric.util.ReflectionHelpers.setField(flushed, "mReason", android.hardware.camera2.CaptureFailure.REASON_FLUSHED);
        device.session.previewCallback.onCaptureFailed(device.session, device.session.repeating, flushed);
        assertTrue(failures.isEmpty());
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
        assertEquals("the preview returns after the still", List.of(preview, still, preview), device.configured);
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
        assertEquals(1, ManagerShadow.devices.size()); assertEquals(3, device.configurations);
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

    /** Glasses, 2026-11-11/12: the HAL drops a frame or two about a second after every stream start. */
    @Test public void aDroppedPreviewFrameBeforeAnyStillIsNotTheEndOfTheSession() {
        camera.preview(); idle(100); frame(180);
        var device = firstDevice();
        device.session.previewCallback.onCaptureFailed(device.session, device.session.repeating, null);
        assertTrue(failures.isEmpty());
        assertFalse((Boolean)ReflectionHelpers.getField(camera, "unknown"));
        assertFalse(device.closed);

        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        assertEquals("the same stream still leads to a still", 1, device.session.captures);
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

    @Test public void missingReadinessExpiresWithoutShootingAndTheCameraStaysUsable() {
        camera.captureOnce(); idle(100); frame(180); idle(9900);
        assertEquals(List.of("camera not still or AF/AE not ready"), failures);
        assertEquals(0, firstDevice().session.captures);
        // A late result alone cannot fire the expired preparation.
        result(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED); idle(1000);
        assertEquals(0, firstDevice().session.captures); assertEquals(0, delivered);
        // No request reached the camera, so it is not unknown: the session continues.
        assertFalse(firstDevice().closed); assertFalse((Boolean)ReflectionHelpers.getField(camera, "unknown"));
        camera.captureOnce(); idle(100); readyFrame(); idle(400); readyFrame(); idle(50);
        assertEquals(1, firstDevice().session.captures); assertEquals(1, ManagerShadow.devices.size());
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
        static int refuseOutputs;
        @Implementation protected String[] getCameraIdList() { return new String[]{"0"}; }
        @Implementation protected CameraCharacteristics getCameraCharacteristics(String id) { return Shadow.newInstanceOf(CameraCharacteristics.class); }
        @Implementation protected void openCamera(String id, CameraDevice.StateCallback callback, Handler h) {
            DocScanTestCamera device = new DocScanTestCamera(template -> {
                CaptureRequest.Builder b = Shadow.newInstanceOf(CaptureRequest.Builder.class);
                ((BuilderShadow)Shadow.extract(b)).template = template; return b;
            });
            device.handler = h; device.state = callback; device.refuseSession = refuseSession;
            device.refuseOutputs = refuseOutputs;
            devices.add(device); h.post(() -> callback.onOpened(device));
        }
    }
    @Implements(CameraCharacteristics.class) public static class CharacteristicsShadow {
        static boolean fixedFocus;
        static int afMode;
        static int aeRegions;
        static boolean strictPublicApi;
        static boolean manualSensor;
        static Integer maxAnalog;
        static boolean fpsRanges;
        @Implementation protected <T> T get(CameraCharacteristics.Key<T> key) {
            if (strictPublicApi && ((android.os.Build.VERSION.SDK_INT < 30
                    && key.getName().equals("android.control.zoomRatioRange"))
                    || (android.os.Build.VERSION.SDK_INT < 31
                    && key.getName().equals("android.scaler.availableRotateAndCropModes"))))
                throw new AssertionError("transform key unavailable at this public API level");
            Object value = key.equals(CameraCharacteristics.LENS_FACING) ? LENS_FACING_BACK
                    : key.equals(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ? Shadow.newInstanceOf(StreamConfigurationMap.class)
                    : key.equals(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES) ? new int[]{CONTROL_AF_MODE_OFF, afMode}
                    : key.equals(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES) ? new int[]{CONTROL_AE_MODE_OFF, CONTROL_AE_MODE_ON}
                    : key.equals(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ? manualSensor
                        ? new int[]{REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR, REQUEST_AVAILABLE_CAPABILITIES_READ_SENSOR_SETTINGS} : new int[0]
                    : key.equals(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE) ? new Range<>(100_000L, 300_000_000L)
                    : key.equals(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE) ? new Range<>(100, 3200)
                    : key.equals(CameraCharacteristics.SENSOR_INFO_MAX_FRAME_DURATION) ? 400_000_000L
                    : key.equals(CameraCharacteristics.SENSOR_MAX_ANALOG_SENSITIVITY) ? maxAnalog
                    : key.equals(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES) ? fpsRanges
                        ? new Range[]{new Range<>(14, 30), new Range<>(30, 30), new Range<>(60, 60)} : null
                    : key.equals(CameraCharacteristics.NOISE_REDUCTION_AVAILABLE_NOISE_REDUCTION_MODES) ? new int[]{0, 1, 2}
                    : key.equals(CameraCharacteristics.EDGE_AVAILABLE_EDGE_MODES) ? new int[]{1, 2, 0}
                    : key.equals(CameraCharacteristics.CONTROL_POST_RAW_SENSITIVITY_BOOST_RANGE) ? new Range<>(100, 3200)
                    : key.equals(CameraCharacteristics.CONTROL_AWB_LOCK_AVAILABLE) ? Boolean.TRUE
                    : key.equals(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) ? manualSensor
                        ? SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME : SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN
                    : key.equals(CameraCharacteristics.CONTROL_MAX_REGIONS_AE) ? aeRegions
                    : key.equals(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE) ? new Rect(0, 0, 4032, 3024)
                    : key.equals(CameraCharacteristics.SENSOR_INFO_PRE_CORRECTION_ACTIVE_ARRAY_SIZE) ? new Rect(0, 0, 4032, 3024)
                    : key.equals(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE) ? fixedFocus ? 0f : 8f : null;
            @SuppressWarnings("unchecked") T typed = (T)value; return typed;
        }
    }
    @Implements(StreamConfigurationMap.class) public static class MapShadow {
        static Size previewSize = new Size(320, 240);
        static boolean fullSizeYuv;
        @Implementation protected Size[] getOutputSizes(int format) {
            if (format != ImageFormat.JPEG && fullSizeYuv) return new Size[]{new Size(4032, 3024), previewSize};
            return new Size[]{format == ImageFormat.JPEG ? new Size(4032, 3024) : previewSize};
        }
    }
    @Implements(ImageReader.class) public static class ReaderShadow {
        static final List<ReaderShadow> readers = new ArrayList<>();
        ImageReader reader; int format, width, height; Image image; boolean closed; RuntimeException acquireFailure;
        Surface surface = Shadow.newInstanceOf(Surface.class); ImageReader.OnImageAvailableListener listener;
        @Implementation protected static ImageReader newInstance(int width, int height, int format, int maxImages) {
            ImageReader reader = Shadow.newInstanceOf(ImageReader.class);
            ReaderShadow shadow = Shadow.extract(reader); shadow.reader = reader; shadow.format = format;
            shadow.width = width; shadow.height = height; readers.add(shadow); return reader;
        }
        @Implementation protected Surface getSurface() { return surface; }
        @Implementation protected void setOnImageAvailableListener(ImageReader.OnImageAvailableListener l, Handler h) { listener = l; }
        @Implementation protected Image acquireLatestImage() {
            if (acquireFailure != null) throw acquireFailure;
            return image;
        }
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
