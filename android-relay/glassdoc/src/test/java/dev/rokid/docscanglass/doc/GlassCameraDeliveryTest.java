package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CaptureFailure;
import android.hardware.camera2.CaptureRequest;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.Looper;
import java.nio.ByteBuffer;
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
@Config(sdk = 32, manifest = Config.NONE, shadows = GlassCameraDeliveryTest.ReaderShadow.class)
public class GlassCameraDeliveryTest {
    private final List<String> events = new ArrayList<>();
    private final List<String> failures = new ArrayList<>();
    private GlassCamera camera;
    private ImageReader reader;
    private ReaderShadow readerShadow;
    private int delivered;

    @Before public void setup() {
        camera = new GlassCamera(RuntimeEnvironment.getApplication(),
                new Handler(Looper.getMainLooper()), new GlassCamera.Callback() {
                    @Override public void onCaptured(byte[] bytes, int width, int height, long elapsed) {
                        events.add("delivered");
                        delivered++;
                        assertArrayEquals(new byte[]{1, 2, 3}, bytes);
                        assertEquals(4032, width);
                        assertEquals(3024, height);
                    }
                    @Override public void onCaptureFailed(String reason) { failures.add(reason); }
                });
        reader = Shadow.newInstanceOf(ImageReader.class);
        readerShadow = Shadow.extract(reader);
        readerShadow.events = events;
        readerShadow.image = new TestImage(events);
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
        return ReflectionHelpers.callConstructor(CaptureFailure.class,
                ClassParameter.from(CaptureRequest.class, null),
                ClassParameter.from(int.class, CaptureFailure.REASON_ERROR),
                ClassParameter.from(boolean.class, imageCaptured),
                ClassParameter.from(int.class, 1), ClassParameter.from(long.class, 1L));
    }
    @Test public void imageIsClosedBeforeReaderAndConsumer() {
        deliver();
        assertEquals(List.of("image.close", "reader.close", "delivered"), events);
        assertEquals(1, delivered);
        assertTrue(failures.isEmpty());
    }
    @Test public void bufferAboveExistingReviewLimitIsRejectedBeforeCopy() {
        ((TestImage) readerShadow.image).buffer = ByteBuffer.allocate(8 * 1024 * 1024 + 1);
        deliver();
        assertEquals(0, delivered);
        assertEquals(1, failures.size());
        assertTrue((Boolean) ReflectionHelpers.getField(camera, "unknown"));
        assertEquals(List.of("image.close", "reader.close"), events);
    }
    @Test public void emptyBufferIsNotAValidPhotograph() {
        ((TestImage) readerShadow.image).buffer = ByteBuffer.allocate(0);
        deliver();
        assertEquals(0, delivered);
        assertEquals(1, failures.size());
    }
    @Test public void nonJpegImageIsNotForwardedAsJpeg() {
        ((TestImage) readerShadow.image).format = ImageFormat.YUV_420_888;
        deliver();
        assertEquals(0, delivered);
        assertEquals(1, failures.size());
    }
    @Test public void memoryFailureClosesTheImageAndSettlesOnce() {
        ((TestImage) readerShadow.image).memoryFailure = true;
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
        captureEvents(1).onCaptureCompleted(null, null, null);
        assertEquals(0, delivered);
        assertTrue(failures.isEmpty());
        assertFalse((Boolean) ReflectionHelpers.getField(camera, "settled"));
    }

    @Implements(ImageReader.class)
    public static class ReaderShadow {
        Image image;
        List<String> events;
        boolean throwOnClose;
        @Implementation protected Image acquireNextImage() { return image; }
        @Implementation protected void close() {
            events.add("reader.close");
            if (throwOnClose) throw new IllegalStateException("synthetic close failure");
        }
    }
    private static final class TestImage extends Image {
        final List<String> events;
        ByteBuffer buffer = ByteBuffer.wrap(new byte[]{1, 2, 3});
        int format = ImageFormat.JPEG;
        boolean memoryFailure;
        TestImage(List<String> events) { this.events = events; }
        @Override public int getFormat() { return format; }
        @Override public int getWidth() { return 4032; }
        @Override public int getHeight() { return 3024; }
        @Override public long getTimestamp() { return 10L; }
        @Override public void setTimestamp(long timestamp) { }
        @Override public void close() { events.add("image.close"); }
        @Override public Plane[] getPlanes() {
            if (memoryFailure) throw new OutOfMemoryError("synthetic allocation failure");
            return new Plane[]{new Plane() {
                @Override public int getRowStride() { return 0; }
                @Override public int getPixelStride() { return 0; }
                @Override public ByteBuffer getBuffer() { return buffer; }
            }};
        }
    }
}
