package dev.rokid.docscanglass.doc;

import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CaptureResult;
import android.util.Log;
import android.util.Size;
import java.util.Arrays;

/** Allowlisted diagnostics only. Never changes capture requests or gates delivery. */
final class CameraDiagnostics {
    private static final String TAG = "DocScanGlassDoc";
    private CameraDiagnostics() { }

    static void capabilities(long generation, CameraCharacteristics c, Size size) {
        try {
            Log.i(TAG, "camera_capabilities gen=" + generation + " jpeg=" + size
                    + " facing=" + value(c.get(CameraCharacteristics.LENS_FACING))
                    + " orientation=" + value(c.get(CameraCharacteristics.SENSOR_ORIENTATION))
                    + " level=" + value(c.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL))
                    + " af_modes=" + ints(c.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES))
                    + " min_focus=" + value(c.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE))
                    + " focus_calibration=" + value(c.get(CameraCharacteristics.LENS_INFO_FOCUS_DISTANCE_CALIBRATION))
                    + " ae_comp_range=" + value(c.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_RANGE))
                    + " ae_comp_step=" + value(c.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_STEP))
                    + " exposure_range_ns=" + value(c.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE))
                    + " iso_range=" + value(c.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)));
        } catch (RuntimeException | OutOfMemoryError error) {
            Log.w(TAG, "camera_capabilities gen=" + generation + " unavailable");
        }
    }

    static void result(long generation, CaptureResult result) {
        try {
            if (result == null) {
                Log.i(TAG, "capture_result gen=" + generation + " unavailable");
                return;
            }
            Log.i(TAG, "capture_result gen=" + generation
                    + " sensor_timestamp_ns=" + value(result.get(CaptureResult.SENSOR_TIMESTAMP))
                    + " exposure_ns=" + value(result.get(CaptureResult.SENSOR_EXPOSURE_TIME))
                    + " iso=" + value(result.get(CaptureResult.SENSOR_SENSITIVITY))
                    + " focal_length_mm=" + value(result.get(CaptureResult.LENS_FOCAL_LENGTH))
                    + " aperture=" + value(result.get(CaptureResult.LENS_APERTURE))
                    + " focus_distance=" + value(result.get(CaptureResult.LENS_FOCUS_DISTANCE))
                    + " ae_state=" + value(result.get(CaptureResult.CONTROL_AE_STATE))
                    + " af_state=" + value(result.get(CaptureResult.CONTROL_AF_STATE))
                    + " awb_state=" + value(result.get(CaptureResult.CONTROL_AWB_STATE)));
        } catch (RuntimeException | OutOfMemoryError error) {
            Log.w(TAG, "capture_result gen=" + generation + " unavailable");
        }
    }

    private static String value(Object value) {
        return value == null ? "unknown" : value.toString();
    }

    private static String ints(int[] values) {
        return values == null ? "unknown" : Arrays.toString(Arrays.copyOf(values, Math.min(16, values.length)));
    }
}
