package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

import android.graphics.ImageFormat;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.ImageReader;
import android.os.Handler;
import android.os.Looper;
import android.util.Size;
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

/** The real startPreview path selects a stream; fake HAL sizes never open a camera. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE, shadows = {
        GlassCameraPreviewGeometryTest.ManagerShadow.class,
        GlassCameraPreviewGeometryTest.CharacteristicsShadow.class,
        GlassCameraPreviewGeometryTest.MapShadow.class,
        GlassCameraPreviewGeometryTest.ReaderShadow.class})
public class GlassCameraPreviewGeometryTest {
    private final List<String> failures = new ArrayList<>();
    private GlassCamera camera;

    @Before public void setup() {
        MapShadow.sizes = new Size[]{new Size(640, 480), new Size(352, 288), new Size(1280, 720)};
        ReaderShadow.selected = null;
        ManagerShadow.opens = 0;
        camera = new GlassCamera(RuntimeEnvironment.getApplication(), new Handler(Looper.getMainLooper()),
                new GlassCamera.Callback() {
                    @Override public void onCaptured(byte[] bytes, int width, int height, long elapsed) { }
                    @Override public void onCaptureFailed(String reason) { failures.add(reason); }
                });
    }

    @Test public void theGuideStreamUsesTheFullJpegAspectBeforeMinimizingItsPixelCount() {
        camera.preview();
        shadowOf(Looper.getMainLooper()).idle();
        assertEquals("352x288 is smaller but is cropped differently from the 4032x3024 original",
                new Size(640, 480), ReaderShadow.selected);
        assertEquals(1, ManagerShadow.opens);
        assertTrue(failures.isEmpty());
    }

    @Test public void theSmallestMatchingStreamKeepsPreviewWorkBounded() {
        MapShadow.sizes = new Size[]{new Size(1280, 960), new Size(640, 480), new Size(320, 240)};
        camera.preview();
        shadowOf(Looper.getMainLooper()).idle();
        assertEquals(new Size(320, 240), ReaderShadow.selected);
        assertTrue(failures.isEmpty());
    }

    @Test public void aDifferentAspectCannotBePresentedAsTheSavedPhotoBoundary() {
        MapShadow.sizes = new Size[]{new Size(352, 288), new Size(1280, 720)};
        camera.preview();
        shadowOf(Looper.getMainLooper()).idle();
        assertNull("no misleading live frame may be allocated", ReaderShadow.selected);
        assertEquals(0, ManagerShadow.opens);
        assertEquals(List.of("preview unavailable"), failures);
    }

    @Implements(CameraManager.class)
    public static class ManagerShadow {
        static int opens;
        @Implementation protected String[] getCameraIdList() { return new String[]{"0"}; }
        @Implementation protected CameraCharacteristics getCameraCharacteristics(String id) {
            return Shadow.newInstanceOf(CameraCharacteristics.class);
        }
        @Implementation protected void openCamera(String id, CameraDevice.StateCallback callback, Handler handler) {
            opens++;
        }
    }

    @Implements(CameraCharacteristics.class)
    public static class CharacteristicsShadow {
        @Implementation protected <T> T get(CameraCharacteristics.Key<T> key) {
            Object value = key.equals(CameraCharacteristics.LENS_FACING) ? CameraCharacteristics.LENS_FACING_BACK
                    : key.equals(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                    ? Shadow.newInstanceOf(StreamConfigurationMap.class) : null;
            @SuppressWarnings("unchecked") T typed = (T) value;
            return typed;
        }
    }

    @Implements(StreamConfigurationMap.class)
    public static class MapShadow {
        static Size[] sizes;
        @Implementation protected Size[] getOutputSizes(int format) {
            return format == ImageFormat.JPEG ? new Size[]{new Size(1920, 1080), new Size(4032, 3024)} : sizes;
        }
    }

    @Implements(ImageReader.class)
    public static class ReaderShadow {
        static Size selected;
        @Implementation protected static ImageReader newInstance(int width, int height, int format, int maxImages) {
            selected = new Size(width, height);
            return Shadow.newInstanceOf(ImageReader.class);
        }
        @Implementation protected void setOnImageAvailableListener(ImageReader.OnImageAvailableListener listener, Handler handler) { }
        @Implementation protected void close() { }
    }
}
