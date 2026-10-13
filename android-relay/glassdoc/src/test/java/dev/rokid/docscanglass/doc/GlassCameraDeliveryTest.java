package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CaptureFailure;
import android.hardware.camera2.CaptureRequest;
import android.media.Image;
import android.media.DocScanTestImage;
import android.media.ImageReader;
import android.os.Handler;
import android.os.Looper;
import java.nio.ByteBuffer;
import java.time.Duration;
import static org.robolectric.Shadows.shadowOf;
import java.util.ArrayList;
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
import org.robolectric.util.ReflectionHelpers;
import org.robolectric.util.ReflectionHelpers.ClassParameter;

/** Exercises the real delivery/lifetime code with fake HAL buffers, not a camera. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE,
        shadows = {GlassCameraDeliveryTest.ReaderShadow.class, GlassCameraDeliveryTest.FailureShadow.class})
public class GlassCameraDeliveryTest {
    private final List<String> events = new ArrayList<>();
    private final List<String> failures = new ArrayList<>();
    private GlassCamera camera;
    private ImageReader reader;
    private ReaderShadow readerShadow;
    private int delivered;
    private byte[] deliveredBytes;
    private int deliveredWidth;
    private int deliveredHeight;

    @Before public void setup() {
        camera = new GlassCamera(RuntimeEnvironment.getApplication(),
                new Handler(Looper.getMainLooper()), new GlassCamera.Callback() {
                    @Override public void onCaptured(byte[] bytes, int width, int height, long elapsed) {
                        events.add("delivered");
                        delivered++;
                        deliveredBytes = bytes;
                        deliveredWidth = width;
                        deliveredHeight = height;
                    }
                    @Override public void onCaptureFailed(String reason) { failures.add(reason); }
                });
        reader = Shadow.newInstanceOf(ImageReader.class);
        readerShadow = Shadow.extract(reader);
        readerShadow.events = events;
        readerShadow.image = new DocScanTestImage(events);
        ReflectionHelpers.setField(camera, "reader", reader);
        ReflectionHelpers.setField(camera, "generation", 1L);
    }
    private void deliver() {
        ReflectionHelpers.callInstanceMethod(camera, "onImageAvailable",
                ClassParameter.from(ImageReader.class, reader));
    }
    private CameraCaptureSession.CaptureCallback captureEvents(long generation) {
        try {
            java.lang.reflect.Method method = GlassCamera.class.getDeclaredMethod("captureCallback", long.class);
            method.setAccessible(true);
            return (CameraCaptureSession.CaptureCallback) method.invoke(camera, generation);
        } catch (ReflectiveOperationException error) {
            throw new AssertionError("Camera2 delivery needs a generation-bound CaptureCallback", error);
        }
    }
    private static CaptureFailure failure(boolean imageCaptured) {
        CaptureFailure failure = Shadow.newInstanceOf(CaptureFailure.class);
        ((FailureShadow) Shadow.extract(failure)).imageCaptured = imageCaptured;
        return failure;
    }
    @Test public void imageIsClosedBeforeReaderAndConsumer() {
        deliver();
        assertEquals(List.of("image.close", "reader.close", "delivered"), events);
        assertEquals(1, delivered);
        assertArrayEquals(new byte[]{1, 2, 3}, deliveredBytes);
        assertEquals(4032, deliveredWidth);
        assertEquals(3024, deliveredHeight);
        assertTrue(failures.isEmpty());
    }
    @Test public void bufferAboveExistingReviewLimitIsRejectedBeforeCopy() {
        ((DocScanTestImage) readerShadow.image).buffer = ByteBuffer.allocate(8 * 1024 * 1024 + 1);
        deliver();
        assertEquals(0, delivered);
        assertEquals(1, failures.size());
        assertTrue((Boolean) ReflectionHelpers.getField(camera, "unknown"));
        assertEquals(List.of("image.close", "reader.close"), events);
    }
    @Test public void emptyBufferIsNotAValidPhotograph() {
        ((DocScanTestImage) readerShadow.image).buffer = ByteBuffer.allocate(0);
        deliver();
        assertEquals(0, delivered);
        assertEquals(1, failures.size());
    }
    @Test public void nonJpegImageIsNotForwardedAsJpeg() {
        ((DocScanTestImage) readerShadow.image).format = ImageFormat.YUV_420_888;
        deliver();
        assertEquals(0, delivered);
        assertEquals(1, failures.size());
    }
    @Test public void memoryFailureClosesTheImageAndSettlesOnce() {
        ((DocScanTestImage) readerShadow.image).memoryFailure = true;
        deliver();
        assertEquals(0, delivered);
        assertEquals(1, failures.size());
        assertEquals(List.of("image.close", "reader.close"), events);
    }
    @Test public void readerCloseFailureDoesNotEscapeOrLeaveAnOwnedReader() {
        readerShadow.throwOnClose = true;
        deliver();
        assertEquals(0, delivered);
        assertEquals(1, failures.size());
        assertNull(ReflectionHelpers.getField(camera, "reader"));
        assertTrue((Boolean) ReflectionHelpers.getField(camera, "unknown"));
    }
    @Test public void definitiveCaptureFailureDoesNotWaitForTimeout() {
        captureEvents(1).onCaptureFailed(null, null, failure(false));
        assertEquals(1, failures.size());
        assertTrue((Boolean) ReflectionHelpers.getField(camera, "unknown"));
        assertEquals(List.of("reader.close"), events);
        captureEvents(1).onCaptureFailed(null, null, failure(false));
        assertEquals(1, failures.size());
    }
    @Test public void metadataFailureWithPossibleImageKeepsWaitingForJpeg() {
        captureEvents(1).onCaptureFailed(null, null, failure(true));
        assertTrue(failures.isEmpty());
        deliver();
        assertEquals(1, delivered);
    }
    @Test public void bufferLossAndAbortedSequenceAreTerminal() {
        captureEvents(1).onCaptureBufferLost(null, null, null, 1L);
        captureEvents(1).onCaptureSequenceAborted(null, 1);
        assertEquals(1, failures.size());
        assertEquals(0, delivered);
    }
    @Test public void abortedSequenceWithoutResultsIsTerminal() {
        captureEvents(1).onCaptureSequenceAborted(null, 1);
        assertEquals(1, failures.size());
    }
    @Test public void previousGenerationCallbacksCannotFailCurrentCapture() {
        CameraCaptureSession.CaptureCallback previous = captureEvents(0);
        previous.onCaptureFailed(null, null, failure(false));
        previous.onCaptureBufferLost(null, null, null, 1L);
        previous.onCaptureSequenceAborted(null, 1);
        assertTrue(failures.isEmpty());
        assertFalse((Boolean) ReflectionHelpers.getField(camera, "settled"));
        deliver();
        assertEquals(1, delivered);
    }
    @Test public void resultMetadataAloneCannotDeliverOrExtendTheDeadline() {
        Handler handler = ReflectionHelpers.getField(camera, "handler");
        Runnable timeout = ReflectionHelpers.getField(camera, "timeout");
        handler.postDelayed(timeout, 15_000);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(14));
        captureEvents(1).onCaptureCompleted(null, null, null);
        assertEquals(0, delivered);
        assertTrue(failures.isEmpty());
        assertFalse((Boolean) ReflectionHelpers.getField(camera, "settled"));
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
        assertEquals(List.of("CAMERA TIMEOUT"), failures);
    }

    @Test public void previewObservationsDuringReviewLatchTheTurnWithoutStartingAnotherStill() {
        DocScanTestImage image = (DocScanTestImage) readerShadow.image;
        image.format = ImageFormat.YUV_420_888;
        image.width = 32;
        image.height = 24;
        image.rowStride = 32;
        image.pixelStride = 1;
        byte[] pixels = new byte[32 * 24];
        java.util.Arrays.fill(pixels, (byte) 180);
        image.buffer = ByteBuffer.wrap(pixels);
        PageChange change = ReflectionHelpers.getField(camera, "pageChange");
        change.observe(pixels, android.os.SystemClock.elapsedRealtime());
        change.consumed(); // the existing JPEG request has claimed this page
        java.util.concurrent.atomic.AtomicInteger ready = new java.util.concurrent.atomic.AtomicInteger();
        CameraReadiness metering = new CameraReadiness(new int[]{CaptureRequest.CONTROL_AF_MODE_OFF},
                0f, new int[]{CaptureRequest.CONTROL_AE_MODE_ON});
        ReflectionHelpers.setField(camera, "metering", metering);
        Runnable observe = () -> {
            metering.observe(null, CaptureRequest.CONTROL_AE_STATE_CONVERGED, android.os.SystemClock.elapsedRealtime());
            ReflectionHelpers.setField(camera, "meteringSensorTimestamp", 10L);
            ReflectionHelpers.callInstanceMethod(camera, "previewFrame",
                    ClassParameter.from(ImageReader.class, reader), ClassParameter.from(long.class, 0L));
        };
        java.util.Arrays.fill(pixels, 0, pixels.length / 3, (byte) 70);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(500));
        observe.run(); // review has no pageReady callback, but the preview still observes
        java.util.Arrays.fill(pixels, (byte) 180); // a similar next page
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(300));
        observe.run();
        assertEquals(0, ready.get());
        assertEquals(0, delivered);
        ReflectionHelpers.setField(camera, "pageReady", (Runnable) ready::incrementAndGet);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(400));
        observe.run();
        assertEquals("the observed turn remains ready when review finishes", 1, ready.get());
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(400));
        observe.run();
        assertEquals("the ready callback must only be delivered once", 1, ready.get());
        assertEquals(0, delivered);
        assertTrue(failures.isEmpty());
    }


    @Implements(CaptureFailure.class)
    public static class FailureShadow {
        boolean imageCaptured;
        @Implementation protected boolean wasImageCaptured() { return imageCaptured; }
        @Implementation protected int getReason() { return CaptureFailure.REASON_ERROR; }
    }

    @Implements(ImageReader.class)
    public static class ReaderShadow {
        Image image;
        List<String> events;
        boolean throwOnClose;
        @Implementation protected Image acquireNextImage() { return image; }
        @Implementation protected Image acquireLatestImage() { return image; }
        @Implementation protected void close() {
            events.add("reader.close");
            if (throwOnClose) throw new IllegalStateException("synthetic close failure");
        }
    }
}
