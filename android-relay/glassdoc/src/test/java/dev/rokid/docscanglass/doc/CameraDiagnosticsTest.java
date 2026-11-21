package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CaptureResult;
import android.util.Size;
import java.util.HashMap;
import java.util.Map;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.annotation.Implementation;
import org.robolectric.annotation.Implements;
import org.robolectric.shadow.api.Shadow;
import org.robolectric.shadows.ShadowLog;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE,
        shadows = {CameraDiagnosticsTest.CharacteristicsShadow.class, CameraDiagnosticsTest.ResultShadow.class})
public class CameraDiagnosticsTest {
    private static String lastLog() {
        var entries = ShadowLog.getLogsForTag("DocScanGlassDoc");
        return entries.get(entries.size() - 1).msg;
    }
    @Test public void missingCharacteristicsStayUnknownAndNeverTriggerCapture() {
        CameraCharacteristics c = Shadow.newInstanceOf(CameraCharacteristics.class);
        CameraDiagnostics.capabilities(7, c, new Size(4032, 3024));
        String text = lastLog();
        assertTrue(text, text.contains("gen=7 jpeg=4032x3024"));
        assertTrue(text, text.contains("af_modes=unknown min_focus=unknown"));
    }
    @Test public void capabilityArraysAreBounded() {
        CameraCharacteristics c = Shadow.newInstanceOf(CameraCharacteristics.class);
        CharacteristicsShadow values = Shadow.extract(c);
        values.afModes = java.util.stream.IntStream.range(0, 100).toArray();
        CameraDiagnostics.capabilities(1, c, new Size(1, 1));
        assertTrue(lastLog().contains("14, 15]"));
        assertFalse(lastLog().contains("15, 16"));
    }
    @Test public void resultReadsOnlyAllowlistedNumbersAndLeavesMissingValuesUnknown() {
        CaptureResult r = Shadow.newInstanceOf(CaptureResult.class);
        ResultShadow values = Shadow.extract(r);
        values.data.put(CaptureResult.SENSOR_EXPOSURE_TIME.getName(), 20_000_000L);
        values.data.put(CaptureResult.SENSOR_SENSITIVITY.getName(), 800);
        values.data.put(CaptureResult.LENS_FOCAL_LENGTH.getName(), 1.9f);
        values.data.put("android.jpeg.gpsLocation", "private GPS");
        CameraDiagnostics.result(3, r);
        assertTrue(lastLog().contains("exposure_ns=20000000 iso=800"));
        assertTrue(lastLog().contains("focal_length_mm=1.9"));
        assertTrue(lastLog().contains("af_state=unknown"));
        assertFalse(lastLog().contains("private"));
        assertFalse(lastLog().contains("gps"));
    }
    @Test public void brokenOptionalMetadataDoesNotEscapeIntoCaptureFailure() {
        CaptureResult r = Shadow.newInstanceOf(CaptureResult.class);
        ((ResultShadow) Shadow.extract(r)).broken = true;
        CameraDiagnostics.result(4, r);
        assertEquals("capture_result gen=4 unavailable", lastLog());
        CameraDiagnostics.capabilities(4, null, new Size(1, 1));
        assertEquals("camera_capabilities gen=4 unavailable", lastLog());
    }
    @Test public void nullResultDoesNotBecomeAnExposureOfZero() {
        CameraDiagnostics.result(5, null);
        assertEquals("capture_result gen=5 unavailable", lastLog());
    }

    private CaptureResult geometry(long timestamp, int cropRight) {
        CaptureResult result = Shadow.newInstanceOf(CaptureResult.class);
        ResultShadow values = Shadow.extract(result);
        values.data.put(CaptureResult.SENSOR_TIMESTAMP.getName(), timestamp);
        values.data.put(CaptureResult.SCALER_CROP_REGION.getName(), new android.graphics.Rect(0, 0, cropRight, 3000));
        values.data.put(CaptureResult.DISTORTION_CORRECTION_MODE.getName(), 1);
        values.data.put(CaptureResult.CONTROL_VIDEO_STABILIZATION_MODE.getName(), 0);
        values.data.put(CaptureResult.LENS_OPTICAL_STABILIZATION_MODE.getName(), 0);
        if (android.os.Build.VERSION.SDK_INT >= 30) values.data.put(CaptureResult.CONTROL_ZOOM_RATIO.getName(), 1f);
        if (android.os.Build.VERSION.SDK_INT >= 31) values.data.put(CaptureResult.SCALER_ROTATE_AND_CROP.getName(), 0);
        values.data.put("private.vendor", "private detail");
        return result;
    }
    @Test public void framingPairsTheActualJpegTimestampAndKeepsTheRequestTimePreview() {
        CameraDiagnostics.Framing pair = new CameraDiagnostics.Framing();
        pair.preview(9, geometry(100, 4000)); pair.arm(3, 9);
        pair.preview(9, geometry(105, 2000));
        pair.result(3, 9, geometry(110, 4000)); pair.jpeg(3, 9, 110);
        String text = lastLog();
        assertTrue(text, text.contains("association=matched"));
        assertTrue(text, text.contains("preview_timestamp_ns=100"));
        assertTrue(text, text.contains("jpeg_timestamp_ns=110"));
        assertTrue(text, text.contains("crop=equal"));
        assertFalse(text, text.contains("private"));
    }
    @Test public void imageFirstRemainsUnknownUntilItsOwnLateResultAndNeverBorrowsAnotherGeneration() {
        CameraDiagnostics.Framing pair = new CameraDiagnostics.Framing();
        pair.preview(4, geometry(100, 4000)); pair.arm(8, 4); pair.jpeg(8, 4, 110);
        assertTrue(lastLog().contains("association=unknown"));
        int logs = ShadowLog.getLogsForTag("DocScanGlassDoc").size();
        pair.result(7, 4, geometry(110, 4000)); pair.result(8, 3, geometry(110, 4000));
        assertEquals(logs, ShadowLog.getLogsForTag("DocScanGlassDoc").size());
        pair.result(8, 4, geometry(110, 3000));
        assertTrue(lastLog().contains("association=matched")); assertTrue(lastLog().contains("crop=different"));
        pair.result(8, 4, geometry(110, 4000));
        assertEquals(logs + 1, ShadowLog.getLogsForTag("DocScanGlassDoc").size());
    }
    @Test public void mismatchedTimestampsOrMissingMetadataCannotCertifyMatchingFraming() {
        CameraDiagnostics.Framing pair = new CameraDiagnostics.Framing();
        pair.preview(2, geometry(100, 4000)); pair.arm(1, 2);
        pair.result(1, 2, geometry(109, 4000)); pair.jpeg(1, 2, 110);
        assertTrue(lastLog().contains("association=mismatch")); assertTrue(lastLog().contains("crop=unknown"));
        pair.arm(2, 2); pair.result(2, 2, null); pair.jpeg(2, 2, 120);
        assertTrue(lastLog().contains("association=unknown"));
        pair.clear(); pair.result(2, 2, geometry(120, 4000));
        assertTrue(lastLog().contains("association=unknown"));
    }
    @Test public void optionalFineDiagnosticsAreBoundedPerStreamAndBrokenMetadataRemainsUnknown() {
        CameraDiagnostics.Framing pair = new CameraDiagnostics.Framing();
        for (int i = 0; i < 20; i++) { pair.fine("current", 640, 480); pair.fine("time_budget", 640, 480); }
        assertEquals(2, ShadowLog.getLogsForTag("DocScanGlassDoc").size());
        CaptureResult broken = Shadow.newInstanceOf(CaptureResult.class);
        ((ResultShadow)Shadow.extract(broken)).broken = true;
        pair.preview(1, broken); pair.arm(1, 1); pair.result(1, 1, broken); pair.jpeg(1, 1, 100);
        assertTrue(lastLog().contains("association=unknown")); assertFalse(lastLog().contains("vendor"));
        pair.clear(); pair.fine("size_budget", 1280, 720);
        assertTrue(lastLog().contains("support=size_budget width=1280 height=720"));
    }

    @Test @Config(sdk = {28, 30, 31})
    public void framingMetadataUsesOnlyFieldsSupportedByTheCurrentApi() {
        CameraDiagnostics.Framing pair = new CameraDiagnostics.Framing();
        pair.preview(1, geometry(100, 4000)); pair.arm(1, 1);
        pair.result(1, 1, geometry(110, 4000)); pair.jpeg(1, 1, 110);
        String text = lastLog();
        assertTrue(text.contains("association=matched")); assertTrue(text.contains("crop=equal"));
        assertTrue(text.contains("zoom=" + (android.os.Build.VERSION.SDK_INT >= 30 ? "equal" : "unknown")));
        assertTrue(text.contains("rotate=" + (android.os.Build.VERSION.SDK_INT >= 31 ? "equal" : "unknown")));
    }

    @Implements(CameraCharacteristics.class)
    public static class CharacteristicsShadow {
        int[] afModes;
        @Implementation protected <T> T get(CameraCharacteristics.Key<T> key) {
            if (key.equals(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES)) {
                @SuppressWarnings("unchecked") T value = (T) afModes;
                return value;
            }
            return null;
        }
    }
    @Implements(CaptureResult.class)
    public static class ResultShadow {
        final Map<String, Object> data = new HashMap<>();
        boolean broken;
        @Implementation protected <T> T get(CaptureResult.Key<T> key) {
            if (broken) throw new IllegalArgumentException("private vendor detail");
            @SuppressWarnings("unchecked") T value = (T) data.get(key.getName());
            return value;
        }
    }
}
