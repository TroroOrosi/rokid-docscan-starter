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
import java.util.Collections;

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
    private Runnable afterPreviewClosed;
    private Runnable pageReady;
    private PageChange pageChange = new PageChange();
    private long previewAt;
    private boolean capturePending;
    private final Runnable previewCloseTimeout = () -> {
        if (afterPreviewClosed != null && !closed && !unknown) {
            afterPreviewClosed = null;
            capturePending = false;
            previewFailed();
        }
    };

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
            stillness.await(handler, () -> stopPreview(this::captureOnHandler));
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
            if (!capturePending) stillness.cancel();
            stopPreview(null);
        });
    }

    /** Close preview completely before the existing JPEG-only capture opens a fresh CameraDevice. */
    @RequiresPermission(Manifest.permission.CAMERA)
    private void startPreview() {
        if (!previewRequested || closed || unknown || previewReader != null || previewClosing
                || (generation > 0 && !settled)) return;
        long token = ++previewGeneration;
        try {
            CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
            String id = rearCameraId(manager);
            StreamConfigurationMap map = manager.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            Size[] sizes = map == null ? null : map.getOutputSizes(ImageFormat.YUV_420_888);
            if (sizes == null || sizes.length == 0) throw new IllegalStateException("no YUV preview");
            Size size = sizes[0];
            for (Size candidate : sizes) {
                if (candidate.getWidth() >= 320 && candidate.getHeight() >= 240
                        && (size.getWidth() < 320 || (long) candidate.getWidth() * candidate.getHeight()
                        < (long) size.getWidth() * size.getHeight())) size = candidate;
            }
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
                        opened.createCaptureSession(Collections.singletonList(previewReader.getSurface()),
                                new CameraCaptureSession.StateCallback() {
                            @Override public void onConfigured(CameraCaptureSession configured) {
                                if (token != previewGeneration || !previewRequested || closed) { configured.close(); return; }
                                previewSession = configured;
                                try {
                                    CaptureRequest.Builder request = opened.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                    request.addTarget(previewReader.getSurface());
                                    configured.setRepeatingRequest(request.build(), null, handler);
                                } catch (CameraAccessException | RuntimeException error) { previewFailed(); }
                            }
                            @Override public void onConfigureFailed(CameraCaptureSession failed) {
                                failed.close(); if (token == previewGeneration) previewFailed();
                            }
                        }, handler);
                    } catch (CameraAccessException | RuntimeException error) { previewFailed(); }
                }
                @Override public void onDisconnected(CameraDevice disconnected) {
                    previewOpening = false;
                    disconnected.close(); if (token == previewGeneration) previewFailed();
                }
                @Override public void onError(CameraDevice errored, int code) {
                    previewOpening = false;
                    errored.close(); if (token == previewGeneration) previewFailed();
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
            Image.Plane luma = image.getPlanes()[0];
            ByteBuffer pixels = luma.getBuffer();
            int row = luma.getRowStride(), step = luma.getPixelStride();
            byte[] thumbnail = new byte[32 * 24];
            for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++) {
                thumbnail[y * 32 + x] = pixels.get(y * image.getHeight() / 24 * row + x * image.getWidth() / 32 * step);
            }
            pageChange.observe(thumbnail, now);
            int width = Math.min(320, image.getWidth()), height = Math.max(1, width * image.getHeight() / image.getWidth());
            int[] display = new int[width * height];
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                int gray = pixels.get(y * image.getHeight() / height * row + x * image.getWidth() / width * step) & 255;
                display[y * width + x] = 0xFF000000 | (gray << 8);
            }
            callback.onPreview(Bitmap.createBitmap(display, width, height, Bitmap.Config.RGB_565));
            if (pageReady != null && pageChange.ready(now)) {
                Runnable ready = pageReady;
                pageReady = null;
                ready.run();
            }
        } catch (RuntimeException | OutOfMemoryError error) { previewFailed(); }
    }

    private void stopPreview(Runnable next) {
        ++previewGeneration;
        if (next != null) {
            afterPreviewClosed = next;
            handler.removeCallbacks(previewCloseTimeout);
            handler.postDelayed(previewCloseTimeout, CAPTURE_TIMEOUT_MILLIS);
        }
        closeResource(previewSession); previewSession = null;
        closeResource(previewReader); previewReader = null;
        CameraDevice opened = previewDevice; previewDevice = null;
        if (opened != null) { previewClosing = true; closeResource(opened); }
        else if (previewOpening) { previewClosing = true; }
        else if (!previewClosing && next != null && !closed && !unknown) {
            afterPreviewClosed = null;
            handler.removeCallbacks(previewCloseTimeout);
            next.run();
        }
    }

    private void previewClosed() {
        if (!previewClosing) return;
        previewClosing = false;
        handler.removeCallbacks(previewCloseTimeout);
        Runnable next = afterPreviewClosed;
        afterPreviewClosed = null;
        if (next != null && !closed && !unknown) next.run();
        else startPreview();
    }

    private void previewFailed() {
        if (closed) return;
        previewRequested = false;
        previewOpening = false;
        unknown = true;
        stopPreview(null);
        callback.onCaptureFailed("preview unavailable");
    }

    @RequiresPermission(Manifest.permission.CAMERA)
    private void captureOnHandler() {
        if (closed || unknown || (generation > 0 && !settled)) return;
        long current = ++generation;
        settled = false;
        pageChange.consumed();
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
            CameraDiagnostics.capabilities(current, characteristics, size);
            reader = ImageReader.newInstance(
                    size.getWidth(), size.getHeight(), ImageFormat.JPEG, 1);
            reader.setOnImageAvailableListener(source -> {
                if (current == generation && !closed && !settled) onImageAvailable(source);
            }, handler);
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
            previewRequested = false;
            pageReady = null;
            afterPreviewClosed = null;
            stillness.cancel();
            stopPreview(null);
            handler.removeCallbacks(timeout);
            handler.removeCallbacks(previewCloseTimeout);
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

            @Override public void onClosed(CameraDevice closedDevice) {
                if (current == generation && settled) startPreview();
            }
        };
    }

    private void configureSession(long current) {
        try {
            device.createCaptureSession(
                    Collections.singletonList(reader.getSurface()),
                    new CameraCaptureSession.StateCallback() {
                        @Override
                        public void onConfigured(CameraCaptureSession configured) {
                            if (closed || settled || current != generation) { closeResource(configured); return; }
                            session = configured;
                            requestStill(current);
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

    private void requestStill(long current) {
        try {
            CaptureRequest.Builder request =
                    device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            request.addTarget(reader.getSurface());
            // No rotation is baked into the JPEG. The server owns the
            // orientation-corrected PNG and is told the rotation separately,
            // so exactly one component rotates the page.
            request.set(CaptureRequest.JPEG_ORIENTATION, 0);
            // Nothing else is set on the request. Biasing exposure +2 EV here
            // (glassdoc 0.3.0) stopped the capture completing at all: four
            // consecutive attempts on 2026-09-04 hit the 15 s timeout without
            // one image, where TEMPLATE_STILL_CAPTURE untouched had returned
            // seven stills in 785-1380 ms. The phone relay never sets exposure
            // either -- it calls takePhoto(w, h, quality) and nothing more.
            // Dark captures remain unresolved. The 2026-09-22 operator reported
            // a bright room; do not attribute the result to lighting alone.
            // This path requests a still immediately, without waiting for AE
            // convergence. The older timeout does not establish its cause.
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
        session = null;
        device = null;
        reader = null;
        boolean ok = closeResource(oldSession);
        ok = closeResource(oldDevice) && ok;
        return closeResource(oldReader) && ok;
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
}
