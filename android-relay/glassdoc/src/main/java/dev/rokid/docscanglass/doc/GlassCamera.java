package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.content.Context;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.CaptureFailure;
import android.hardware.camera2.TotalCaptureResult;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.SystemClock;
import android.util.Log;
import android.util.Size;
import android.view.Surface;

import androidx.annotation.RequiresPermission;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Objects;

/**
 * One still per request, straight from {@code android.hardware.camera2}.
 *
 * <p>This is the structure the 2026-09-04 spike proved on hardware: seven
 * consecutive captures at 4032x3024, 5.7-6.1 MB, 785-1380 ms each. CameraX is
 * not used, for the same reason as in the spike -- it is built on camera2, so
 * it adds a dependency without adding a capability.
 *
 * <p>The privacy indicator is firmware-owned. Measured on the same run, the
 * kernel LED driver raises channel 3 to {@code 0xFF} 31 ms after
 * {@code connectDevice} and clears it 19 ms after {@code finishCameraStreamingOps},
 * before the client even disconnects. This class never reads, writes, disables,
 * obscures, spoofs, or bypasses it.
 */
final class GlassCamera {

    private static final String TAG = "DocScanGlassDoc";
    private static final long CAPTURE_TIMEOUT_MILLIS = 15_000;
    // Same bound as CaptureReviewPersistence; reject before allocating a second buffer.
    private static final int MAX_JPEG_BYTES = 8 * 1024 * 1024;

    interface Callback {
        void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis);

        void onCaptureFailed(String reason);
    }

    private final Context context;
    private final Handler handler;
    private final Callback callback;

    private CameraDevice device;
    private CameraCaptureSession session;
    private ImageReader reader;
    private ImageReader meteringReader;
    private boolean stillRequested;
    private long startedAtMillis;
    private boolean settled;
    private boolean closed;
    private boolean unknown;
    private long generation;

    private final Runnable timeout = () -> fail("CAMERA TIMEOUT");

    GlassCamera(Context context, Handler handler, Callback callback) {
        this.context = context;
        this.handler = handler;
        this.callback = callback;
    }

    /** Opens the rear camera and captures exactly one JPEG at its largest size. */
    @RequiresPermission(Manifest.permission.CAMERA)
    void captureOnce() {
        handler.post(this::captureOnHandler);
    }

    @RequiresPermission(Manifest.permission.CAMERA)
    private void captureOnHandler() {
        if (closed || unknown || (generation > 0 && !settled)) return;
        long current = ++generation;
        settled = false;
        stillRequested = false;
        startedAtMillis = SystemClock.elapsedRealtime();
        CameraManager manager =
                (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
        if (manager == null) {
            fail("no CameraManager");
            return;
        }
        try {
            String id = rearCameraId(manager);
            if (id == null) {
                fail("no camera");
                return;
            }
            CameraCharacteristics characteristics = manager.getCameraCharacteristics(id);
            Size size = largestJpegSize(characteristics);
            if (size == null) {
                fail("no JPEG size");
                return;
            }
            Size meteringSize = meteringSize(characteristics, size);
            if (meteringSize == null) {
                fail("no bounded metering size");
                return;
            }
            CameraDiagnostics.capabilities(current, characteristics, size);
            reader = ImageReader.newInstance(
                    size.getWidth(), size.getHeight(), ImageFormat.JPEG, 1);
            reader.setOnImageAvailableListener(source -> {
                if (current == generation && !closed && !settled) onImageAvailable(source);
            }, handler);
            // YUV PREVIEW + JPEG MAXIMUM is a Camera2 guaranteed stream combination.
            // This buffer is for AE only; never allocate a bitmap or retain its pixels.
            meteringReader = ImageReader.newInstance(meteringSize.getWidth(),
                    meteringSize.getHeight(), ImageFormat.YUV_420_888, 2);
            meteringReader.setOnImageAvailableListener(source -> {
                if (active(current)) drainMeteringImage(source);
            }, handler);
            Log.i(TAG, "camera_metering gen=" + current + " size=" + meteringSize);
            handler.postDelayed(timeout, CAPTURE_TIMEOUT_MILLIS);
            manager.openCamera(id, deviceCallback(current), handler);
        } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) {
            // SecurityException is a RuntimeException, so a refused CAMERA
            // permission lands here too.
            fail("open " + error.getClass().getSimpleName());
        }
    }

    void close() {
        handler.post(() -> {
            closed = true;
            settled = true;
            generation++;
            handler.removeCallbacks(timeout);
            release();
        });
    }

    private CameraDevice.StateCallback deviceCallback(long current) {
        return new CameraDevice.StateCallback() {
            @Override
            public void onOpened(CameraDevice opened) {
                if (closed || settled || current != generation) { closeResource(opened); return; }
                device = opened;
                configureSession(current);
            }

            @Override
            public void onDisconnected(CameraDevice disconnected) {
                if (closed || settled || current != generation) { closeResource(disconnected); return; }
                device = disconnected;
                fail("camera disconnected");
            }

            @Override
            public void onError(CameraDevice errored, int error) {
                if (closed || settled || current != generation) { closeResource(errored); return; }
                device = errored;
                fail("camera error " + error);
            }
        };
    }

    private void configureSession(long current) {
        try {
            device.createCaptureSession(
                    List.of(reader.getSurface(), meteringReader.getSurface()),
                    new CameraCaptureSession.StateCallback() {
                        @Override
                        public void onConfigured(CameraCaptureSession configured) {
                            if (closed || settled || current != generation) { closeResource(configured); return; }
                            session = configured;
                            startMetering(current);
                        }

                        @Override
                        public void onConfigureFailed(CameraCaptureSession failed) {
                            if (closed || settled || current != generation) { closeResource(failed); return; }
                            session = failed;
                            fail("session refused");
                        }
                    },
                    handler);
        } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) {
            fail("session " + error.getClass().getSimpleName());
        }
    }

    private void startMetering(long current) {
        try {
            CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            request.addTarget(meteringReader.getSurface());
            request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON);
            session.setRepeatingRequest(request.build(), new CameraCaptureSession.CaptureCallback() {
                private Integer lastAeState = -1;
                @Override public void onCaptureCompleted(CameraCaptureSession source,
                        CaptureRequest request, TotalCaptureResult result) {
                    if (!active(current) || stillRequested) return;
                    try {
                        Integer ae = result == null ? null : result.get(CaptureResult.CONTROL_AE_STATE);
                        if (!Objects.equals(lastAeState, ae)) {
                            lastAeState = ae;
                            Log.i(TAG, "camera_metering_state gen=" + current
                                    + " ae_state=" + (ae == null ? "unknown" : ae)
                                    + " elapsed_ms=" + (SystemClock.elapsedRealtime() - startedAtMillis));
                        }
                        if (ae == null || ae != CaptureResult.CONTROL_AE_STATE_CONVERGED) return;
                        // Set before Camera2 calls: queued results/stop echoes must not shoot twice.
                        stillRequested = true;
                        Log.i(TAG, "camera_metering_ready gen=" + current + " ae_state=" + ae
                                + " elapsed_ms=" + (SystemClock.elapsedRealtime() - startedAtMillis));
                        session.stopRepeating();
                        requestStill(current);
                    } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) {
                        fail("metering " + error.getClass().getSimpleName());
                    }
                }
                @Override public void onCaptureFailed(CameraCaptureSession source,
                        CaptureRequest request, CaptureFailure failure) {
                    if (active(current) && !stillRequested) fail("metering failed");
                }
                @Override public void onCaptureBufferLost(CameraCaptureSession source,
                        CaptureRequest request, Surface target, long frameNumber) {
                    if (active(current) && !stillRequested) fail("metering buffer lost");
                }
                @Override public void onCaptureSequenceAborted(CameraCaptureSession source, int id) {
                    if (active(current) && !stillRequested) fail("metering sequence aborted");
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) {
            fail("metering " + error.getClass().getSimpleName());
        }
    }

    private void drainMeteringImage(ImageReader source) {
        try (Image ignored = source.acquireLatestImage()) {
            // Closing promptly keeps repeating requests moving; no preview pixels escape.
        } catch (RuntimeException | OutOfMemoryError error) {
            fail("metering image " + error.getClass().getSimpleName());
        }
    }

    private void requestStill(long current) {
        try {
            CaptureRequest.Builder request =
                    device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            request.addTarget(reader.getSurface());
            // No rotation is baked into the JPEG. The server owns the
            // orientation-corrected PNG and is told the rotation separately,
            // so exactly one component rotates the page.
            request.set(CaptureRequest.JPEG_ORIENTATION, 0);
            request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON);
            // No EV bias, flash, focus trigger or exposure lock. Preview convergence
            // is preparation, not proof of the JPEG's exposure or text readability.
            session.capture(request.build(), captureCallback(current), handler);
        } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) {
            fail("capture " + error.getClass().getSimpleName());
        }
    }

    private boolean active(long current) {
        return current == generation && !closed && !settled;
    }

    private CameraCaptureSession.CaptureCallback captureCallback(long current) {
        return new CameraCaptureSession.CaptureCallback() {
            @Override public void onCaptureFailed(CameraCaptureSession source,
                    CaptureRequest request, CaptureFailure failure) {
                if (!active(current)) return;
                // Metadata can fail while an image is still delivered. Do not discard it
                // or restart the deadline merely because the result metadata failed.
                if (!failure.wasImageCaptured()) fail("capture failed " + failure.getReason());
                else Log.w(TAG, "capture_result gen=" + current + " unavailable; waiting for JPEG");
            }
            @Override public void onCaptureBufferLost(CameraCaptureSession source,
                    CaptureRequest request, Surface target, long frameNumber) {
                if (active(current)) fail("JPEG buffer lost");
            }
            @Override public void onCaptureSequenceAborted(CameraCaptureSession source, int id) {
                if (active(current)) fail("capture sequence aborted");
            }
            @Override public void onCaptureCompleted(CameraCaptureSession source,
                    CaptureRequest request, TotalCaptureResult result) {
                // Results and ImageReader notifications have independent ordering. A
                // late result is diagnostic only, never a success or a retry trigger.
                if (current == generation && !closed && !unknown) {
                    CameraDiagnostics.result(current, result);
                }
            }
        };
    }

    private void onImageAvailable(ImageReader source) {
        final byte[] jpeg;
        final int width;
        final int height;
        try (Image image = source.acquireNextImage()) {
            if (image == null || image.getFormat() != ImageFormat.JPEG) {
                throw new RejectedJpeg("missing JPEG image");
            }
            width = image.getWidth();
            height = image.getHeight();
            if (width <= 0 || height <= 0) throw new RejectedJpeg("invalid JPEG dimensions");
            Image.Plane[] planes = image.getPlanes();
            if (planes.length != 1) throw new RejectedJpeg("invalid JPEG planes");
            ByteBuffer buffer = planes[0].getBuffer();
            int bytes = buffer.remaining();
            if (bytes <= 0 || bytes > MAX_JPEG_BYTES) {
                throw new RejectedJpeg("JPEG byte limit (1..8MiB)");
            }
            jpeg = new byte[bytes];
            buffer.get(jpeg);
        } catch (RejectedJpeg error) {
            fail(error.getMessage());
            return;
        } catch (RuntimeException | OutOfMemoryError error) {
            // The Image has already closed before the reader can be released by fail().
            fail("image " + error.getClass().getSimpleName());
            return;
        }
        if (settled || closed) return;
        if (!release()) {
            fail("camera close failed");
            return;
        }
        settled = true;
        handler.removeCallbacks(timeout);
        long elapsed = SystemClock.elapsedRealtime() - startedAtMillis;
        Log.i(TAG, "captured " + width + "x" + height
                + " " + jpeg.length + "B in " + elapsed + "ms gen=" + generation);
        // The consumer may queue another allocation. No native Image/reader is held.
        // Consumer exceptions must not re-label a delivered image as a camera failure.
        callback.onCaptured(jpeg, width, height, elapsed);
    }

    private static final class RejectedJpeg extends RuntimeException {
        RejectedJpeg(String reason) { super(reason); }
    }

    private void fail(String reason) {
        if (settled) {
            return;
        }
        settled = true;
        unknown = true;
        handler.removeCallbacks(timeout);
        release();
        Log.w(TAG, "capture failed: " + reason);
        callback.onCaptureFailed(reason);
    }

    private boolean release() {
        // Detach ownership first, then attempt every close even if one fails.
        CameraCaptureSession oldSession = session;
        CameraDevice oldDevice = device;
        ImageReader oldReader = reader;
        ImageReader oldMeteringReader = meteringReader;
        session = null;
        device = null;
        reader = null;
        meteringReader = null;
        boolean ok = closeResource(oldSession);
        ok = closeResource(oldDevice) && ok;
        ok = closeResource(oldReader) && ok;
        return closeResource(oldMeteringReader) && ok;
    }

    private static boolean closeResource(AutoCloseable resource) {
        if (resource == null) return true;
        try {
            resource.close();
            return true;
        } catch (Exception | OutOfMemoryError error) {
            Log.w(TAG, "camera close " + error.getClass().getSimpleName());
            return false;
        }
    }

    private static String rearCameraId(CameraManager manager) throws CameraAccessException {
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
            if ((long) candidate.getWidth() * candidate.getHeight()
                    > (long) largest.getWidth() * largest.getHeight()) {
                largest = candidate;
            }
        }
        return largest;
    }

    private static Size meteringSize(CameraCharacteristics characteristics, Size jpeg) {
        StreamConfigurationMap map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        Size[] sizes = map == null ? null : map.getOutputSizes(ImageFormat.YUV_420_888);
        Size selected = null;
        if (sizes == null) return null;
        for (Size candidate : sizes) {
            long pixels = (long) candidate.getWidth() * candidate.getHeight();
            if (pixels <= 0 || pixels > 640 * 480
                    || (long) candidate.getWidth() * jpeg.getHeight()
                    != (long) candidate.getHeight() * jpeg.getWidth()) continue;
            if (selected == null || pixels > (long) selected.getWidth() * selected.getHeight()) {
                selected = candidate;
            }
        }
        return selected;
    }
}
