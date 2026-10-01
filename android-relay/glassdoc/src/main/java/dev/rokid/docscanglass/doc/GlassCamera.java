package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.content.Context;
import android.graphics.ImageFormat;
import android.graphics.Bitmap;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureFailure;
import android.hardware.camera2.CaptureResult;
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
import java.util.Arrays;

/**
 * One still per request, straight from {@code android.hardware.camera2}.
 *
 * <p>The JPEG-only 2026-09-04 spike returned seven
 * consecutive captures at 4032x3024, 5.7-6.1 MB, 785-1380 ms each. CameraX is
 * not used, for the same reason as in the spike -- it is built on camera2, so
 * it adds a dependency without adding a capability. The current warmed
 * YUV/JPEG combination has not been validated on hardware.
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
    // Preparation plus JPEG deadline remains below the controller's 30s capture lease.
    private static final long PREPARE_TIMEOUT_MILLIS = 10_000;
    // Same bound as CaptureReviewPersistence; reject before allocating a second buffer.
    private static final int MAX_JPEG_BYTES = 8 * 1024 * 1024;

    interface Callback {
        void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis);

        void onCaptureFailed(String reason);

        default void onPreview(Bitmap frame) { frame.recycle(); }
    }

    private final Context context;
    private final Handler handler;
    private final Callback callback;
    private final Stillness stillness;

    private CameraDevice device;
    private CameraCaptureSession session;
    private ImageReader reader;
    private long startedAtMillis;
    private boolean settled;
    private boolean closed;
    private boolean unknown;
    private long generation;
    private CameraDevice previewDevice;
    private CameraCaptureSession previewSession;
    private ImageReader previewReader;
    private boolean previewRequested;
    private long previewGeneration;
    private boolean previewClosing;
    private boolean previewOpening;
    private Runnable pageReady;
    private PageChange pageChange = new PageChange();
    private long previewAt;
    private boolean capturePending;
    private CameraReadiness metering;
    private long meteringSensorTimestamp;
    private long previewSensorTimestamp;
    private boolean autoFocusStarted;
    private long autoFocusSensorTimestamp;
    private PageChange previewMotion = new PageChange();
    private final Runnable prepareTimeout = () -> previewFailed("camera not still or AF/AE not ready");

    private final Runnable timeout = () -> fail("CAMERA TIMEOUT");

    GlassCamera(Context context, Handler handler, Callback callback) {
        this.context = context;
        this.handler = handler;
        this.callback = callback;
        stillness = new Stillness(context);
    }

    /** Opens the rear camera and captures exactly one JPEG at its largest size. */
    @RequiresPermission(Manifest.permission.CAMERA)
    void captureOnce() {
        handler.post(() -> {
            if (closed || unknown || capturePending) return;
            capturePending = true;
            previewRequested = true;
            handler.postDelayed(prepareTimeout, PREPARE_TIMEOUT_MILLIS);
            startPreview();
            if (closed || unknown) return;
            stillness.await(handler, this::cameraReady, this::captureOnHandler);
        });
    }

    void resetPages() { handler.post(() -> pageChange = new PageChange()); }

    void awaitNextPage(Runnable ready) {
        handler.post(() -> {
            if (closed || unknown) return;
            pageReady = ready;
            previewRequested = true;
            startPreview();
        });
    }

    void preview() {
        handler.post(() -> { previewRequested = true; startPreview(); });
    }

    void pausePreview() {
        handler.post(() -> {
            previewRequested = false;
            pageReady = null;
            if (!capturePending) { stillness.cancel(); stopPreview(); }
        });
    }

    /** Prepare YUV and the full-size JPEG in the same session, retaining metered focus. */
    @RequiresPermission(Manifest.permission.CAMERA)
    private void startPreview() {
        if (!previewRequested || closed || unknown || previewReader != null || previewClosing
                || (generation > 0 && !settled)) return;
        long token = ++previewGeneration;
        try {
            CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
            String id = rearCameraId(manager);
            CameraCharacteristics characteristics = manager.getCameraCharacteristics(id);
            StreamConfigurationMap map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            Size[] sizes = map == null ? null : map.getOutputSizes(ImageFormat.YUV_420_888);
            Size jpegSize = largestJpegSize(characteristics);
            Size size = previewSize(sizes, jpegSize);
            if (size == null) throw new IllegalStateException("no YUV preview matches JPEG aspect");
            metering = new CameraReadiness(characteristics.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES),
                    characteristics.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE),
                    characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES));
            previewMotion = new PageChange();
            previewAt = 0;
            meteringSensorTimestamp = 0;
            previewSensorTimestamp = 0;
            autoFocusStarted = false;
            autoFocusSensorTimestamp = 0;
            CameraDiagnostics.capabilities(generation + 1, characteristics, jpegSize);
            reader = ImageReader.newInstance(jpegSize.getWidth(), jpegSize.getHeight(), ImageFormat.JPEG, 1);
            reader.setOnImageAvailableListener(source -> {
                if (source == reader && generation > 0 && active(generation)) onImageAvailable(source);
            }, handler);
            previewReader = ImageReader.newInstance(size.getWidth(), size.getHeight(), ImageFormat.YUV_420_888, 2);
            previewReader.setOnImageAvailableListener(source -> previewFrame(source, token), handler);
            previewOpening = true;
            manager.openCamera(id, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice opened) {
                    previewOpening = false;
                    if (token != previewGeneration || !previewRequested || closed) {
                        previewClosing = true;
                        opened.close(); return;
                    }
                    previewDevice = opened;
                    try {
                        opened.createCaptureSession(Arrays.asList(previewReader.getSurface(), reader.getSurface()),
                                new CameraCaptureSession.StateCallback() {
                            @Override public void onConfigured(CameraCaptureSession configured) {
                                if (token != previewGeneration || !previewRequested || closed) { configured.close(); return; }
                                previewSession = configured;
                                try {
                                    if (!metering.supported()) {
                                        previewFailed("camera AF/AE capabilities unsupported"); return;
                                    }
                                    CaptureRequest.Builder request = opened.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                    request.addTarget(previewReader.getSurface());
                                    applyMetering(request);
                                    configured.setRepeatingRequest(request.build(), previewResults(token, false), handler);
                                } catch (CameraAccessException | RuntimeException error) { previewFailed(); }
                            }
                            @Override public void onConfigureFailed(CameraCaptureSession failed) {
                                failed.close(); if (token == previewGeneration) previewFailed("camera YUV/JPEG session refused");
                            }
                        }, handler);
                    } catch (CameraAccessException | RuntimeException error) { previewFailed(); }
                }
                @Override public void onDisconnected(CameraDevice disconnected) {
                    previewOpening = false;
                    if (disconnected == device && active(generation)) fail("camera disconnected");
                    else { disconnected.close(); if (token == previewGeneration) previewFailed(); }
                }
                @Override public void onError(CameraDevice errored, int code) {
                    previewOpening = false;
                    if (errored == device && active(generation)) fail("camera error " + code);
                    else { errored.close(); if (token == previewGeneration) previewFailed(); }
                }
                @Override public void onClosed(CameraDevice closedDevice) {
                    previewClosed();
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) { previewFailed(); }
    }

    private void previewFrame(ImageReader source, long token) {
        try (Image image = source.acquireLatestImage()) {
            if (image == null || token != previewGeneration || closed) return;
            long now = SystemClock.elapsedRealtime();
            if (now - previewAt < 100) return;
            previewAt = now;
            previewSensorTimestamp = image.getTimestamp();
            Image.Plane luma = image.getPlanes()[0];
            ByteBuffer pixels = luma.getBuffer();
            int row = luma.getRowStride(), step = luma.getPixelStride();
            byte[] thumbnail = new byte[32 * 24];
            for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++) {
                thumbnail[y * 32 + x] = pixels.get(y * image.getHeight() / 24 * row + x * image.getWidth() / 32 * step);
            }
            pageChange.observe(thumbnail, now);
            previewMotion.observe(thumbnail, now);
            // AUTO/MACRO must start before pageReady can require a focused result.
            if (capturePending || (pageReady != null && pageChange.ready(now))) startAutoFocus();
            int width = Math.min(320, image.getWidth()), height = Math.max(1, width * image.getHeight() / image.getWidth());
            int[] display = new int[width * height];
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                int gray = pixels.get(y * image.getHeight() / height * row + x * image.getWidth() / width * step) & 255;
                display[y * width + x] = 0xFF000000 | (gray << 8);
            }
            callback.onPreview(Bitmap.createBitmap(display, width, height, Bitmap.Config.RGB_565));
            if (pageReady != null && pageChange.ready(now) && meteredFrame(now)) {
                Runnable ready = pageReady;
                pageReady = null;
                ready.run();
            }
        } catch (RuntimeException | OutOfMemoryError error) { previewFailed(); }
    }

    private void stopPreview() {
        ++previewGeneration;
        closeResource(previewSession); previewSession = null;
        closeResource(previewReader); previewReader = null;
        if (device == null) { closeResource(reader); reader = null; }
        CameraDevice opened = previewDevice; previewDevice = null;
        if (opened != null) { previewClosing = true; closeResource(opened); }
        else if (previewOpening) { previewClosing = true; }
    }

    private void previewClosed() {
        if (!previewClosing) return;
        previewClosing = false;
        startPreview();
    }

    private void previewFailed() { previewFailed("preview unavailable"); }

    private void previewFailed(String reason) {
        if (closed || unknown) return;
        previewRequested = false;
        previewOpening = false;
        unknown = true;
        capturePending = false;
        stillness.cancel();
        handler.removeCallbacks(prepareTimeout);
        stopPreview();
        callback.onCaptureFailed(reason);
    }

    private boolean cameraReady() {
        long now = SystemClock.elapsedRealtime();
        return !closed && !unknown && previewDevice != null && previewSession != null
                && meteredFrame(now) && previewMotion.ready(now)
                && now >= previewAt && now - previewAt <= CameraReadiness.FRESH_MILLIS;
    }

    private boolean meteredFrame(long now) {
        // Compare only timestamps from this camera; UNKNOWN timebases are not wall clocks.
        return metering != null && metering.ready(now) && meteringSensorTimestamp > 0
                && (!metering.needsTrigger() || (autoFocusStarted && autoFocusSensorTimestamp > 0
                && meteringSensorTimestamp >= autoFocusSensorTimestamp))
                && previewSensorTimestamp > 0 && Math.abs(meteringSensorTimestamp - previewSensorTimestamp)
                <= CameraReadiness.FRESH_MILLIS * 1_000_000L;
    }

    private CameraCaptureSession.CaptureCallback previewResults(long token, boolean focusTrigger) {
        return new CameraCaptureSession.CaptureCallback() {
            @Override public void onCaptureCompleted(CameraCaptureSession source,
                    CaptureRequest request, TotalCaptureResult result) {
                if (token != previewGeneration || closed || unknown || result == null) return;
                try {
                    Long timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
                    if (timestamp == null || timestamp <= 0) {
                        meteringSensorTimestamp = 0; return;
                    }
                    // Fence old LOCKED metadata until this START has reached the native pipeline.
                    if (focusTrigger) autoFocusSensorTimestamp = timestamp;
                    if (timestamp <= meteringSensorTimestamp) return;
                    meteringSensorTimestamp = timestamp;
                    metering.observe(result.get(CaptureResult.CONTROL_AF_STATE),
                            result.get(CaptureResult.CONTROL_AE_STATE), SystemClock.elapsedRealtime());
                } catch (RuntimeException error) { previewFailed("camera metering unavailable"); }
            }
            @Override public void onCaptureFailed(CameraCaptureSession source,
                    CaptureRequest request, CaptureFailure failure) {
                if (token == previewGeneration) previewFailed("camera metering failed");
            }
        };
    }

    private void applyMetering(CaptureRequest.Builder request) {
        request.set(CaptureRequest.CONTROL_AF_MODE, metering.afMode);
        request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON);
    }

    private void startAutoFocus() {
        if (closed || unknown || previewSession == null || metering == null || !metering.supported()
                || !metering.needsTrigger() || autoFocusStarted
                || !previewMotion.ready(SystemClock.elapsedRealtime())) return;
        try {
            CaptureRequest.Builder trigger = previewDevice.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            trigger.addTarget(previewReader.getSurface());
            applyMetering(trigger);
            trigger.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_START);
            autoFocusStarted = true;
            previewSession.capture(trigger.build(), previewResults(previewGeneration, true), handler);
        } catch (CameraAccessException | RuntimeException error) { previewFailed("camera autofocus failed"); }
    }

    @RequiresPermission(Manifest.permission.CAMERA)
    private void captureOnHandler() {
        if (closed || unknown || !capturePending || !cameraReady() || (generation > 0 && !settled)) return;
        long current = ++generation;
        settled = false;
        pageChange.consumed();
        startedAtMillis = SystemClock.elapsedRealtime();
        device = previewDevice; previewDevice = null;
        session = previewSession; previewSession = null;
        previewClosing = true;
        ++previewGeneration;
        handler.removeCallbacks(prepareTimeout);
        handler.postDelayed(timeout, CAPTURE_TIMEOUT_MILLIS);
        requestStill(current);
    }

    void close() {
        handler.post(() -> {
            closed = true;
            settled = true;
            generation++;
            previewRequested = false;
            pageReady = null;
            stillness.cancel();
            stopPreview();
            handler.removeCallbacks(timeout);
            handler.removeCallbacks(prepareTimeout);
            release();
        });
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
            // Biasing exposure +2 EV here
            // (glassdoc 0.3.0) stopped the capture completing at all: four
            // consecutive attempts on 2026-09-04 hit the 15 s timeout without
            // one image, where TEMPLATE_STILL_CAPTURE untouched had returned
            // seven stills in 785-1380 ms. The phone relay never sets exposure
            // either -- it calls takePhoto(w, h, quality) and nothing more.
            // Dark captures remain unresolved. The 2026-09-22 operator reported
            // a bright room; do not attribute the result to lighting alone.
            // Native AF/AE convergence now precedes this request in the same
            // session; the older timeout does not establish its cause.
            applyMetering(request);
            session.stopRepeating();
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
        capturePending = false;
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
        capturePending = false;
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
        ImageReader oldPreviewReader = previewReader;
        session = null;
        device = null;
        reader = null;
        previewReader = null;
        boolean ok = closeResource(oldSession);
        ok = closeResource(oldDevice) && ok;
        ok = closeResource(oldReader) && ok;
        return closeResource(oldPreviewReader) && ok;
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

    /** Different stream aspects are centre-cropped by Camera2; a guide must show the full JPEG. */
    private static Size previewSize(Size[] sizes, Size jpeg) {
        if (sizes == null || jpeg == null) return null;
        Size smallest = null;
        for (Size candidate : sizes) {
            if (candidate.getWidth() < 320 || candidate.getHeight() < 240
                    || (long) candidate.getWidth() * jpeg.getHeight()
                    != (long) candidate.getHeight() * jpeg.getWidth()) continue;
            if (smallest == null || (long) candidate.getWidth() * candidate.getHeight()
                    < (long) smallest.getWidth() * smallest.getHeight()) smallest = candidate;
        }
        return smallest;
    }
}
