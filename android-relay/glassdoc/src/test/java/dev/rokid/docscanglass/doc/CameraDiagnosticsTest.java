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
        values.data.put("android.jpeg.gpsLocation", "private GPS");
        CameraDiagnostics.result(3, r);
        assertTrue(lastLog().contains("exposure_ns=20000000 iso=800"));
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
