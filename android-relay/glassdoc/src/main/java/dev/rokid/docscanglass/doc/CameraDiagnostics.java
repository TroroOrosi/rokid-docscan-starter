package dev.rokid.docscanglass.doc;

import android.graphics.Rect;
import android.os.Build;
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
                    + " ae_modes=" + ints(c.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES))
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

    /** At most one pending pair plus the latest preview; never gates or changes an original. */
    static final class Framing {
        private CaptureResult latest;
        private long latestStream, generation, stream, jpegTimestamp;
        private Geometry preview, still;
        private boolean pendingLogged, finalLogged;
        private int fineReported;
        void preview(long token, CaptureResult result) { latestStream = token; latest = result; }
        void arm(long current, long token) {
            generation = current; stream = token; jpegTimestamp = 0;
            preview = latestStream == token ? Geometry.read(latest) : null;
            still = null; pendingLogged = finalLogged = false;
        }
        void result(long current, long token, CaptureResult result) {
            if (current != generation || token != stream || finalLogged) return;
            still = Geometry.read(result); emit();
        }
        void jpeg(long current, long token, long timestamp) {
            if (current != generation || token != stream || finalLogged || timestamp <= 0) return;
            jpegTimestamp = timestamp; emit();
        }
        private void emit() {
            if (jpegTimestamp <= 0 || finalLogged || still == null && pendingLogged) return;
            boolean associated = still != null && still.timestamp != null && still.timestamp == jpegTimestamp;
            boolean fresh = associated && preview != null && preview.timestamp != null
                    && preview.timestamp > 0 && jpegTimestamp >= preview.timestamp
                    && jpegTimestamp - preview.timestamp <= 500_000_000L;
            try { Log.i(TAG, "framing_pair gen=" + generation + " stream=" + stream
                    + " association=" + (still == null || still.timestamp == null ? "unknown" : associated ? "matched" : "mismatch")
                    + " preview_timestamp_ns=" + value(preview == null ? null : preview.timestamp)
                    + " jpeg_timestamp_ns=" + jpegTimestamp
                    + " result_timestamp_ns=" + value(still == null ? null : still.timestamp)
                    + " preview_crop=" + value(preview == null ? null : preview.crop)
                    + " jpeg_crop=" + value(still == null ? null : still.crop)
                    + " preview_zoom=" + value(preview == null ? null : preview.zoom)
                    + " jpeg_zoom=" + value(still == null ? null : still.zoom)
                    + " crop=" + compare(fresh, preview == null ? null : preview.crop, still == null ? null : still.crop)
                    + " zoom=" + compare(fresh, preview == null ? null : preview.zoom, still == null ? null : still.zoom)
                    + " distortion=" + compare(fresh, preview == null ? null : preview.distortion, still == null ? null : still.distortion)
                    + " rotate=" + compare(fresh, preview == null ? null : preview.rotate, still == null ? null : still.rotate)
                    + " eis=" + compare(fresh, preview == null ? null : preview.eis, still == null ? null : still.eis)
                    + " ois=" + compare(fresh, preview == null ? null : preview.ois, still == null ? null : still.ois));
            } catch (RuntimeException | OutOfMemoryError unavailable) { /* Optional diagnostics never change JPEG delivery. */ }
            if (still == null) pendingLogged = true; else finalLogged = true;
        }
        void fine(String status, int width, int height) {
            int bit = switch (status) {
                case "size_budget" -> 2;
                case "offset_budget" -> 4;
                case "invalid_plane" -> 8;
                case "stale_frame" -> 16;
                case "time_budget" -> 32;
                case "interrupted" -> 64;
                default -> 1;
            };
            if ((fineReported & bit) == 0) {
                fineReported |= bit;
                try { Log.i(TAG, "page_evidence support=" + (bit == 1 ? "supported" : status)
                        + " width=" + width + " height=" + height); }
                catch (RuntimeException | OutOfMemoryError unavailable) { /* Diagnostic only. */ }
            }
        }
        void clear() {
            latest = null; latestStream = generation = stream = jpegTimestamp = 0;
            preview = still = null; pendingLogged = finalLogged = false; fineReported = 0;
        }
    }
    private static String compare(boolean associated, Object a, Object b) {
        return !associated || a == null || b == null ? "unknown" : a.equals(b) ? "equal" : "different";
    }
    private static final class Geometry {
        Long timestamp;
        Rect crop;
        Float zoom;
        Integer distortion, rotate, eis, ois;
        static Geometry read(CaptureResult result) {
            if (result == null) return null;
            try {
                Geometry g = new Geometry();
                g.timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
                Rect crop = result.get(CaptureResult.SCALER_CROP_REGION);
                if (crop != null) g.crop = new Rect(crop);
                g.zoom = Build.VERSION.SDK_INT >= 30 ? result.get(CaptureResult.CONTROL_ZOOM_RATIO) : null;
                if (g.zoom != null && (!Float.isFinite(g.zoom) || g.zoom <= 0)) g.zoom = null;
                g.rotate = Build.VERSION.SDK_INT >= 31 ? result.get(CaptureResult.SCALER_ROTATE_AND_CROP) : null;
                g.distortion = result.get(CaptureResult.DISTORTION_CORRECTION_MODE);
                g.eis = result.get(CaptureResult.CONTROL_VIDEO_STABILIZATION_MODE);
                g.ois = result.get(CaptureResult.LENS_OPTICAL_STABILIZATION_MODE);
                return g;
            } catch (RuntimeException | OutOfMemoryError unavailable) { return null; }
        }
    }

    private static String value(Object value) {
        return value == null ? "unknown" : value.toString();
    }

    private static String ints(int[] values) {
        return values == null ? "unknown" : Arrays.toString(Arrays.copyOf(values, Math.min(16, values.length)));
    }
}
