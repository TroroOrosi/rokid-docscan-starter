package dev.rokid.docscanglass.probe;

import android.Manifest;
import android.content.Context;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.SystemClock;
import android.util.Log;
import android.util.Size;

import androidx.annotation.RequiresPermission;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Collections;

/**
 * P2: does an ordinary Android app on the glasses open the camera?
 *
 * <p>Uses {@code android.hardware.camera2} directly rather than CameraX.
 * CameraX is built on camera2, so a camera2 failure is also a CameraX failure,
 * and the absence of the dependency keeps a negative result unambiguous.
 *
 * <p>The privacy indicator is firmware-owned. This class never reads, writes,
 * disables, obscures, spoofs, or bypasses it; the acceptance run observes it
 * physically with an independent camera.
 *
 * <p>Captures at most one still, only when the operator explicitly asks, into
 * app-private cache storage. Nothing is uploaded, recognized, or registered.
 */
final class CameraProbe {

    private static final String TAG = "DocScanGlassProbe";
    private static final String CAPTURE_NAME = "probe-capture.jpg";
    private static final long CAPTURE_TIMEOUT_MILLIS = 15_000;

    interface Callback {
        void onCameraResult(ProbeReport.Status status, String detail);
    }

    private final Context context;
    private final Handler handler;
    private final Callback callback;

    private CameraDevice device;
    private CameraCaptureSession session;
    private ImageReader reader;
    private File captured;
    private long startedAtMillis;
    private boolean settled;

    private final Runnable timeout = () -> settle(
            ProbeReport.Status.FAILED,
            "no image within " + CAPTURE_TIMEOUT_MILLIS + "ms");

    CameraProbe(Context context, Handler handler, Callback callback) {
        this.context = context;
        this.handler = handler;
        this.callback = callback;
    }

    /**
     * Enumeration and characteristics need no permission, so this runs even
     * when the operator declines the camera. An empty list here and a refusal
     * later mean different things.
     */
    static String describeCameras(Context context) {
        CameraManager manager =
                (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
        if (manager == null) {
            return "no CameraManager";
        }
        try {
            String[] ids = manager.getCameraIdList();
            if (ids.length == 0) {
                return "0 ids";
            }
            StringBuilder described = new StringBuilder(ids.length + " ids");
            for (String id : ids) {
                CameraCharacteristics characteristics = manager.getCameraCharacteristics(id);
                described.append(" ").append(id).append(":").append(facing(characteristics));
                Size largest = largestJpegSize(characteristics);
                if (largest != null) {
                    described.append("/")
                            .append(largest.getWidth())
                            .append("x")
                            .append(largest.getHeight());
                }
            }
            return described.toString();
        } catch (CameraAccessException | RuntimeException error) {
            return "enumeration failed: " + error.getClass().getSimpleName();
        }
    }

    /** Opens the preferred camera and captures exactly one JPEG. */
    @RequiresPermission(Manifest.permission.CAMERA)
    void captureOnce() {
        settled = false;
        startedAtMillis = SystemClock.elapsedRealtime();
        CameraManager manager =
                (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
        if (manager == null) {
            settle(ProbeReport.Status.FAILED, "no CameraManager");
            return;
        }
        try {
            String id = preferredCameraId(manager);
            if (id == null) {
                settle(ProbeReport.Status.FAILED, "no camera id");
                return;
            }
            Size size = largestJpegSize(manager.getCameraCharacteristics(id));
            if (size == null) {
                settle(ProbeReport.Status.FAILED, "no JPEG output size");
                return;
            }
            reader = ImageReader.newInstance(
                    size.getWidth(), size.getHeight(), ImageFormat.JPEG, 1);
            reader.setOnImageAvailableListener(this::onImageAvailable, handler);
            handler.postDelayed(timeout, CAPTURE_TIMEOUT_MILLIS);
            Log.i(TAG, "camera probe opening id=" + id
                    + " size=" + size.getWidth() + "x" + size.getHeight());
            manager.openCamera(id, deviceCallback(), handler);
        } catch (CameraAccessException | RuntimeException error) {
            // SecurityException is a RuntimeException, so a refused CAMERA
            // permission lands here too and is reported by its own class name.
            settle(ProbeReport.Status.FAILED,
                    "open failed: " + error.getClass().getSimpleName());
        }
    }

    /** Releases every camera resource and deletes the captured file. */
    void close() {
        handler.removeCallbacks(timeout);
        closeQuietly();
        if (captured != null && captured.exists() && !captured.delete()) {
            Log.w(TAG, "probe capture file could not be deleted");
        }
        captured = null;
    }

    private CameraDevice.StateCallback deviceCallback() {
        return new CameraDevice.StateCallback() {
            @Override
            public void onOpened(CameraDevice opened) {
                device = opened;
                configureSession();
            }

            @Override
            public void onDisconnected(CameraDevice disconnected) {
                device = disconnected;
                settle(ProbeReport.Status.FAILED, "camera disconnected");
            }

            @Override
            public void onError(CameraDevice errored, int error) {
                device = errored;
                settle(ProbeReport.Status.FAILED, "camera error " + error);
            }
        };
    }

    private void configureSession() {
        try {
            device.createCaptureSession(
                    Collections.singletonList(reader.getSurface()),
                    new CameraCaptureSession.StateCallback() {
                        @Override
                        public void onConfigured(CameraCaptureSession configured) {
                            session = configured;
                            requestStill();
                        }

                        @Override
                        public void onConfigureFailed(CameraCaptureSession failed) {
                            session = failed;
                            settle(ProbeReport.Status.FAILED, "session configure failed");
                        }
                    },
                    handler);
        } catch (CameraAccessException | RuntimeException error) {
            settle(ProbeReport.Status.FAILED,
                    "session failed: " + error.getClass().getSimpleName());
        }
    }

    private void requestStill() {
        try {
            CaptureRequest.Builder request =
                    device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            request.addTarget(reader.getSurface());
            request.set(CaptureRequest.JPEG_ORIENTATION, 0);
            session.capture(request.build(), null, handler);
        } catch (CameraAccessException | RuntimeException error) {
            settle(ProbeReport.Status.FAILED,
                    "capture failed: " + error.getClass().getSimpleName());
        }
    }

    private void onImageAvailable(ImageReader source) {
        try (Image image = source.acquireNextImage()) {
            if (image == null) {
                settle(ProbeReport.Status.FAILED, "null image");
                return;
            }
            ByteBuffer buffer = image.getPlanes()[0].getBuffer();
            byte[] bytes = new byte[buffer.remaining()];
            buffer.get(bytes);
            File target = new File(context.getCacheDir(), CAPTURE_NAME);
            try (FileOutputStream out = new FileOutputStream(target)) {
                out.write(bytes);
            }
            captured = target;
            long elapsed = SystemClock.elapsedRealtime() - startedAtMillis;
            settle(ProbeReport.Status.OK,
                    image.getWidth() + "x" + image.getHeight()
                            + " " + bytes.length + "B in " + elapsed + "ms");
        } catch (IOException | RuntimeException error) {
            settle(ProbeReport.Status.FAILED,
                    "image failed: " + error.getClass().getSimpleName());
        }
    }

    private void settle(ProbeReport.Status status, String detail) {
        if (settled) {
            return;
        }
        settled = true;
        handler.removeCallbacks(timeout);
        closeQuietly();
        Log.i(TAG, "camera probe " + status + " " + detail);
        callback.onCameraResult(status, detail);
    }

    private void closeQuietly() {
        if (session != null) {
            session.close();
            session = null;
        }
        if (device != null) {
            device.close();
            device = null;
        }
        if (reader != null) {
            reader.close();
            reader = null;
        }
    }

    private static String preferredCameraId(CameraManager manager)
            throws CameraAccessException {
        String[] ids = manager.getCameraIdList();
        for (String id : ids) {
            Integer lens = manager.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.LENS_FACING);
            if (lens != null && lens == CameraCharacteristics.LENS_FACING_BACK) {
                return id;
            }
        }
        return ids.length == 0 ? null : ids[0];
    }

    private static String facing(CameraCharacteristics characteristics) {
        Integer lens = characteristics.get(CameraCharacteristics.LENS_FACING);
        if (lens == null) {
            return "unknown";
        }
        if (lens == CameraCharacteristics.LENS_FACING_BACK) {
            return "back";
        }
        if (lens == CameraCharacteristics.LENS_FACING_FRONT) {
            return "front";
        }
        return "external";
    }

    private static Size largestJpegSize(CameraCharacteristics characteristics) {
        StreamConfigurationMap map = characteristics.get(
                CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        if (map == null) {
            return null;
        }
        Size[] sizes = map.getOutputSizes(ImageFormat.JPEG);
        if (sizes == null || sizes.length == 0) {
            return null;
        }
        Size largest = sizes[0];
        for (Size candidate : sizes) {
            long area = (long) candidate.getWidth() * candidate.getHeight();
            if (area > (long) largest.getWidth() * largest.getHeight()) {
                largest = candidate;
            }
        }
        return largest;
    }
}
