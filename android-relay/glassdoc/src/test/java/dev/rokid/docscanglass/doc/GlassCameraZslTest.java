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
import dev.rokid.docscanrelay.CaptureProvenance;
import dev.rokid.docscanrelay.CaptureSurface;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
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

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE, shadows = {GlassCameraWarmSessionTest.ManagerShadow.class,
        GlassCameraZslTest.Characteristics.class, GlassCameraZslTest.MapShadow.class, GlassCameraZslTest.Reader.class,
        GlassCameraWarmSessionTest.BuilderShadow.class, GlassCameraWarmSessionTest.RequestShadow.class})
public class GlassCameraZslTest {
    private GlassCamera camera;
    private final ZslInputTransferTest.Worker worker = new ZslInputTransferTest.Worker();
    private final ZslInputTransferTest.Port port = new ZslInputTransferTest.Port();
    private final List<GlassCamera.Captured> originals = new ArrayList<>();
    private final List<String> failures = new ArrayList<>();
    @Before public void setup() {
        GlassCameraWarmSessionTest.ManagerShadow.devices.clear();
        GlassCameraWarmSessionTest.ManagerShadow.refuseSession = false;
        GlassCameraWarmSessionTest.ReaderShadow.readers.clear(); Characteristics.supported = true;
        camera = new GlassCamera(RuntimeEnvironment.getApplication(), new Handler(Looper.getMainLooper()),
                new GlassCamera.Callback() {
                    public void onCaptured(byte[] bytes, int w, int h, long elapsed) { fail("rich callback expected"); }
                    public void onCaptured(GlassCamera.Captured captured) { originals.add(captured); }
                    public void onCaptureFailed(String reason) { failures.add(reason); }
                }, GlassCamera.Mode.ZSL_EVALUATION_YUV, worker, released -> { port.released = released; return port; });
    }
    private void idle(long millis) { shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(millis)); }
    private DocScanTestCamera device() { return GlassCameraWarmSessionTest.ManagerShadow.devices.get(0); }
    private Reader reader(int format, int width) {
        return (Reader) GlassCameraWarmSessionTest.ReaderShadow.readers.stream()
                .filter(r -> r.format == format && ((Reader)r).width == width).findFirst().orElseThrow();
    }
    private TotalCaptureResult frame() { return frame(false); }
    private TotalCaptureResult frame(boolean turning) { return frame(turning, 0); }
    private TotalCaptureResult frame(boolean turning, long callbackLagMillis) {
        long timestamp = SystemClock.elapsedRealtimeNanos() - callbackLagMillis * 1_000_000L;
        TotalCaptureResult result = ShadowTotalCaptureResult.newTotalCaptureResult();
        ShadowCaptureResult values = Shadow.extract(result);
        values.set(CaptureResult.SENSOR_TIMESTAMP, timestamp);
        values.set(CaptureResult.SENSOR_EXPOSURE_TIME, 10_000_000L);
        values.set(CaptureResult.CONTROL_AF_STATE, CONTROL_AF_STATE_INACTIVE);
        values.set(CaptureResult.CONTROL_AE_STATE, CONTROL_AE_STATE_CONVERGED);
        device().session.previewCallback.onCaptureCompleted(device().session, device().session.repeating, result);
        DocScanTestImage preview = new DocScanTestImage(new ArrayList<>());
        preview.format = ImageFormat.YUV_420_888; preview.width = 32; preview.height = 24;
        preview.timestamp = timestamp; preview.rowStride = 32; preview.pixelStride = 1;
        byte[] luma = new byte[32*24]; java.util.Arrays.fill(luma, (byte)180); preview.buffer = ByteBuffer.wrap(luma);
        if (turning) java.util.Arrays.fill(luma, 0, luma.length / 3, (byte)70);
        Reader low = reader(ImageFormat.YUV_420_888, 320); low.image = preview; low.listener.onImageAvailable(low.reader);
        DocScanTestImage nativeImage = new DocScanTestImage(new ArrayList<>());
        nativeImage.format = ImageFormat.YUV_420_888; nativeImage.timestamp = timestamp;
        Reader full = reader(ImageFormat.YUV_420_888, 4032); full.image = nativeImage; full.listener.onImageAvailable(full.reader);
        return result;
    }
    private TotalCaptureResult issue() {
        camera.preview(); idle(1); worker.next();
        for (int i=0;i<6;i++) { frame(); idle(100); }
        camera.captureOnce(); idle(0);
        TotalCaptureResult result = frame(); idle(50);
        assertEquals(0, device().session.captures);
        worker.next();
        assertEquals(1, device().session.captures);
        assertSame(result, device().reprocessSource);
        return result;
    }
    private void jpeg(long timestamp) {
        Reader jpeg = reader(ImageFormat.JPEG, 4032);
        DocScanTestImage image = new DocScanTestImage(new ArrayList<>()); image.timestamp = timestamp;
        jpeg.image = image; jpeg.listener.onImageAvailable(jpeg.reader); idle(0);
    }
    @Test public void sameSessionSourceExposureReachesTheOriginalJpegWithItsActualMetadata() {
        TotalCaptureResult selected = issue();
        assertEquals(3, device().outputs.size());
        assertEquals(4032, device().inputConfiguration.getWidth());
        assertEquals(ImageFormat.YUV_420_888, device().inputConfiguration.getFormat());
        assertEquals(6, reader(ImageFormat.YUV_420_888, 4032).maxImages);
        var request = (GlassCameraWarmSessionTest.RequestShadow)Shadow.extract(device().session.captured);
        assertEquals(CONTROL_CAPTURE_INTENT_STILL_CAPTURE, request.values.get(CaptureRequest.CONTROL_CAPTURE_INTENT.getName()));
        assertEquals(List.of(reader(ImageFormat.JPEG, 4032).surface), request.targets);
        long timestamp = selected.get(CaptureResult.SENSOR_TIMESTAMP);
        jpeg(timestamp);
        assertEquals(1, originals.size()); assertTrue(originals.get(0).associationResolved);
        assertArrayEquals(new byte[]{1,2,3}, originals.get(0).jpeg);
        assertEquals("zsl_reprocess", originals.get(0).provenance.sourceKind);
        assertEquals(Long.valueOf(timestamp), originals.get(0).provenance.resultTimestampNanos);
        assertEquals(Long.valueOf(10_000_000L), originals.get(0).provenance.exposureNanos);
        assertTrue(failures.isEmpty());
    }
    @Test public void mismatchedJpegIsDeliveredForUnresolvedRetentionAndNeverClaimsNativeStill() {
        TotalCaptureResult selected = issue(); jpeg(selected.get(CaptureResult.SENSOR_TIMESTAMP) + 1);
        assertEquals(1, originals.size()); assertFalse(originals.get(0).associationResolved);
        assertNull(originals.get(0).provenance); assertArrayEquals(new byte[]{1,2,3}, originals.get(0).jpeg);
        assertEquals(1, failures.size()); assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
        camera.captureOnce(); idle(1000); assertEquals(1, device().session.captures);
    }
    @Test public void pausingAnIssuedReprocessKeepsTheOriginalSourceAssociation() {
        TotalCaptureResult source = issue();
        camera.pausePreview(); idle(0);
        jpeg(source.get(CaptureResult.SENSOR_TIMESTAMP));
        assertEquals(1, originals.size());
        assertTrue("closing the session must not erase the selected source before delivery", originals.get(0).associationResolved);
        assertEquals("zsl_reprocess", originals.get(0).provenance.sourceKind);
    }
    @Test public void freshDelayedInputCanEstablishQuietnessAndSelectItsActualSource() {
        camera.preview(); idle(200); worker.next();
        for (int i = 0; i < 6; i++) { frame(false, 100); idle(100); }
        camera.captureOnce(); idle(0);
        TotalCaptureResult latest = null;
        for (int i = 0; i < 20 && worker.tasks.isEmpty(); i++) { latest = frame(false, 100); idle(50); }
        assertFalse("fresh delayed input must not keep resetting its own quiet interval", worker.tasks.isEmpty());
        worker.next();
        assertEquals(1, device().session.captures); assertSame(latest, device().reprocessSource);
        Stillness stillness = ReflectionHelpers.getField(camera, "stillness");
        long timestamp = latest.get(CaptureResult.SENSOR_TIMESTAMP);
        assertTrue("the selected exposure still belongs to the measured quiet interval", timestamp >= stillness.quietSinceNanos());
        assertTrue(SystemClock.elapsedRealtimeNanos() - timestamp <= CameraReadiness.FRESH_MILLIS * 1_000_000L);
        jpeg(timestamp);
        assertEquals(1, originals.size()); assertTrue(originals.get(0).associationResolved);
        assertEquals(Long.valueOf(timestamp), originals.get(0).provenance.imageTimestampNanos);
        assertTrue(failures.isEmpty());
    }
    @Test public void jpegWithoutInputReleaseKeepsStopUnresolvedAndStillHasADeadline() {
        TotalCaptureResult source = issue(); jpeg(source.get(CaptureResult.SENSOR_TIMESTAMP));
        final int[] idleAck = {0}; camera.stopFuturePages(() -> idleAck[0]++); idle(0);
        assertEquals(0, idleAck[0]);
        idle(15_000);
        assertEquals("a JPEG is not evidence that the reprocess consumer released its input", 1, failures.size());
        assertTrue((Boolean)ReflectionHelpers.getField(camera, "unknown"));
        assertEquals(0, idleAck[0]); assertEquals(1, device().session.captures);
    }
    @Test public void jpegBeforeReleaseCannotAuthorizeASecondQueueAndReleaseResumesItOnce() {
        TotalCaptureResult source = issue(); jpeg(source.get(CaptureResult.SENSOR_TIMESTAMP));
        camera.captureOnce(); camera.captureOnce(); idle(0);
        for (int i=0;i<4;i++) { frame(); idle(100); }
        assertEquals(1, device().session.captures); assertEquals(1, port.queued);
        port.released.run(); frame(); idle(50); worker.next();
        assertEquals(2, device().session.captures); assertEquals(2, port.queued);
        assertTrue(failures.isEmpty());
    }
    @Test public void releasingFutureInputBeforeJpegCannotAcknowledgeTheStopEarly() {
        futureStopWaitsForBothOriginalAndInputRelease(true);
    }
    @Test public void deliveringFutureJpegBeforeInputReleaseCannotAcknowledgeTheStopEarly() {
        futureStopWaitsForBothOriginalAndInputRelease(false);
    }
    private void futureStopWaitsForBothOriginalAndInputRelease(boolean releaseFirst) {
        TotalCaptureResult first = issue(); jpeg(first.get(CaptureResult.SENSOR_TIMESTAMP));
        port.released.run(); idle(0);
        List<String> order = new ArrayList<>();
        camera.observeFuturePages(2, new CaptureSurface.FuturePageListener() {
            public void onCandidate(byte[] jpeg, CaptureProvenance source, boolean sceneMatched) {
                assertArrayEquals(new byte[]{1,2,3}, jpeg); assertTrue(sceneMatched);
                assertEquals("zsl_reprocess", source.sourceKind); order.add("original");
            }
            public void onPageMissed() { fail("an ordinary stop must not lose this future page"); }
        }); idle(0);
        idle(30); frame(true); idle(30); frame(); idle(400);
        TotalCaptureResult future = frame(); idle(50); worker.next();
        assertEquals(2, device().session.captures);
        camera.stopFuturePages(() -> order.add("idle")); idle(0);
        assertTrue(order.isEmpty());
        if (releaseFirst) { port.released.run(); idle(0); }
        else jpeg(future.get(CaptureResult.SENSOR_TIMESTAMP));
        assertEquals(releaseFirst ? List.of() : List.of("original"), order);
        if (releaseFirst) jpeg(future.get(CaptureResult.SENSOR_TIMESTAMP));
        else { port.released.run(); idle(0); }
        assertEquals(List.of("original", "idle"), order);
        port.released.run(); idle(0);
        idle(30); frame(true); idle(30); frame(); idle(400); frame(); idle(50);
        assertEquals(List.of("original", "idle"), order);
        assertEquals(2, device().session.captures); assertEquals(2, port.queued);
        assertEquals(1, originals.size()); assertTrue(failures.isEmpty());
    }
    @Test public void consumerCloseCanUnblockInputWithoutBlockingCameraCallbacksOrAcknowledgingIdleEarly() throws Exception {
        camera.preview(); idle(1); worker.next();
        ZslInputTransfer initial = ReflectionHelpers.getField(camera, "inputTransfer");
        initial.close(); worker.next();
        var executor = Executors.newSingleThreadExecutor();
        CountDownLatch inputEntered = new CountDownLatch(1), inputGate = new CountDownLatch(1);
        CountDownLatch closeEntered = new CountDownLatch(1), closeGate = new CountDownLatch(1);
        ZslInputTransfer transfer = new ZslInputTransfer(executor, new Handler(Looper.getMainLooper()), released ->
                new ZslInputTransfer.Port() {
                    public void queue(Image image) {
                        inputEntered.countDown(); await(inputGate); image.close();
                    }
                    public void close() { }
                }, failures::add);
        try {
            executor.submit(() -> {}).get(5, TimeUnit.SECONDS); idle(0);
            ReflectionHelpers.setField(camera, "inputTransfer", transfer);
            transfer.queue(new DocScanTestImage(new ArrayList<>()), () -> fail("closed session cannot capture"));
            assertTrue(inputEntered.await(5, TimeUnit.SECONDS));
            device().onClose = () -> { closeEntered.countDown(); await(closeGate); inputGate.countDown(); };
            final int[] stopped = {0}; camera.stopFuturePages(() -> stopped[0]++); idle(0);
            camera.close(); idle(0);
            assertTrue(closeEntered.await(5, TimeUnit.SECONDS)); assertEquals(0, stopped[0]);
            final boolean[] responsive = {false}; new Handler(Looper.getMainLooper()).post(() -> responsive[0] = true);
            idle(0); assertTrue(responsive[0]); assertEquals(0, stopped[0]);
            closeGate.countDown();
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (stopped[0] == 0 && System.nanoTime() < deadline) { idle(0); Thread.sleep(2); }
            assertEquals(1, stopped[0]); assertTrue(transfer.idle()); assertTrue(failures.isEmpty());
        } finally { closeGate.countDown(); inputGate.countDown(); transfer.close(); executor.shutdownNow(); }
    }
    private static void await(CountDownLatch latch) {
        try { if (!latch.await(5, TimeUnit.SECONDS)) throw new IllegalStateException("test native deadline"); }
        catch (InterruptedException error) { throw new IllegalStateException(error); }
    }
    @Test public void unsupportedExplicitEvaluationStopsBeforeCameraOpenAndDoesNotFallback() {
        Characteristics.supported = false; camera.captureOnce(); idle(10_000);
        assertTrue(GlassCameraWarmSessionTest.ManagerShadow.devices.isEmpty());
        assertEquals(1, failures.size()); assertTrue(originals.isEmpty());
    }

    @Implements(CameraCharacteristics.class) public static class Characteristics {
        static boolean supported;
        @Implementation protected <T> T get(CameraCharacteristics.Key<T> key) {
            Object value = key.equals(CameraCharacteristics.LENS_FACING) ? LENS_FACING_BACK
                    : key.equals(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ? Shadow.newInstanceOf(StreamConfigurationMap.class)
                    : key.equals(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES) ? new int[]{CONTROL_AF_MODE_OFF}
                    : key.equals(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES) ? new int[]{CONTROL_AE_MODE_ON}
                    : key.equals(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE) ? 0f
                    : key.equals(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) ? SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
                    : key.equals(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL) ? INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED
                    : key.equals(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ? supported
                    ? new int[]{REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING, REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE} : new int[0] : null;
            @SuppressWarnings("unchecked") T typed = (T)value; return typed;
        }
    }
    @Implements(StreamConfigurationMap.class) public static class MapShadow {
        @Implementation protected Size[] getOutputSizes(int format) {
            return format == ImageFormat.JPEG ? new Size[]{new Size(4032,3024)}
                    : new Size[]{new Size(320,240),new Size(4032,3024)};
        }
        @Implementation protected int[] getInputFormats() { return new int[]{ImageFormat.YUV_420_888}; }
        @Implementation protected Size[] getInputSizes(int format) { return new Size[]{new Size(4032,3024)}; }
        @Implementation protected int[] getValidOutputFormatsForInput(int format) { return new int[]{ImageFormat.JPEG}; }
    }
    @Implements(ImageReader.class) public static class Reader extends GlassCameraWarmSessionTest.ReaderShadow {
        int width, height, maxImages;
        @Implementation protected static ImageReader newInstance(int w, int h, int format, int max) {
            ImageReader reader = Shadow.newInstanceOf(ImageReader.class); Reader r = Shadow.extract(reader);
            r.reader = reader; r.width=w; r.height=h; r.maxImages=max; r.format=format; readers.add(r); return reader;
        }
        @Implementation protected int getWidth() { return width; }
        @Implementation protected int getHeight() { return height; }
        @Implementation protected Image acquireLatestImage() { Image image=this.image; this.image=null; return image; }
    }
}
