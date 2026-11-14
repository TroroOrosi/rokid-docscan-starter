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
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

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
    private ImageReader previewReader;
    private int previewFrames;
    private int stillsLeft;
    private long stillAskedAt;
    private android.hardware.camera2.TotalCaptureResult lastPreview;
    private final CameraCaptureSession.CaptureCallback previewResults = new CameraCaptureSession.CaptureCallback() {
        @Override public void onCaptureCompleted(CameraCaptureSession source, CaptureRequest request,
                android.hardware.camera2.TotalCaptureResult result) { lastPreview = result; }
    };
    private android.graphics.SurfaceTexture texture;
    private android.view.Surface textureSurface;
    /**
     * How the still is taken, from {@code --es camera_variant}: comma-separated {@code preview=WxH}
     * (a repeating YUV preview in the same session, as glassdoc runs it), {@code warm=<ms>} before the
     * still, {@code af_off}, {@code ae_on} (written into both requests), {@code stop} (stop the
     * repeating request before the still), {@code busy=<ms>} (hold each preview image that long),
     * {@code yuvstill} (the still as full-size YUV beside the preview), {@code jpeg=<quality>} (encode that
     * YUV here and time it), {@code manual} (the preview's last exposure, sensitivity and frame duration
     * with AE off, as glassdoc asks), {@code count=<n>} (that many stills in the one session),
     * {@code keep} (leave the last file in the cache for {@code run-as} to read).
     * {@code previewonly} (the preview alone for the warm time, then the session is rebuilt with the full-size
     * output beside it and, {@code settle=<ms>} later, the still is taken).
     * Empty is the single JPEG output measured on 2026-09-04.
     */
    static String variant = "";

    private static String option(String name) {
        for (String part : variant.split(",")) {
            if (part.equals(name)) return "";
            if (part.startsWith(name + "=")) return part.substring(name.length() + 1);
        }
        return null;
    }

    private void applyOptions(CaptureRequest.Builder request) {
        if (option("af_off") != null) request.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF);
        if (option("ae_on") != null) request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON);
        // The camera's own ways to shorten the exposure while its auto exposure keeps the brightness:
        // fps=<n> or fps=<low>-<high> (AE target frame-rate range), scene=<n> (a scene mode, 13 is sports),
        // ev=<steps> (AE compensation in the camera's steps). Written into both requests.
        String fps = option("fps");
        if (fps != null && !fps.isEmpty()) {
            String[] ends = fps.split("-");
            request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new android.util.Range<>(
                    Integer.parseInt(ends[0]), Integer.parseInt(ends[ends.length - 1])));
        }
        String scene = option("scene");
        if (scene != null && !scene.isEmpty()) {
            request.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_USE_SCENE_MODE);
            request.set(CaptureRequest.CONTROL_SCENE_MODE, Integer.parseInt(scene));
        }
        String ev = option("ev");
        if (ev != null && !ev.isEmpty()) request.set(CaptureRequest.CONTROL_AE_EXPOSURE_COMPENSATION, Integer.parseInt(ev));
    }
    private File captured;
    private long startedAtMillis;
    private boolean settled;

    private final Runnable timeout = () -> settle(
            ProbeReport.Status.FAILED,
            "no image within " + CAPTURE_TIMEOUT_MILLIS + "ms variant=[" + variant + "] preview_frames=" + previewFrames);

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
            reader = ImageReader.newInstance(size.getWidth(), size.getHeight(),
                    option("yuvstill") != null ? ImageFormat.YUV_420_888 : ImageFormat.JPEG, 1);
            reader.setOnImageAvailableListener(this::onImageAvailable, handler);
            String preview = option("preview");
            previewFrames = 0;
            stillsLeft = option("count") == null ? 1 : Integer.parseInt(option("count"));
            lastPreview = null;
            if (preview != null) {
                String[] wh = preview.split("x");
                long busy = option("busy") == null ? 0 : Long.parseLong(option("busy"));
                previewReader = ImageReader.newInstance(Integer.parseInt(wh[0]), Integer.parseInt(wh[1]),
                        ImageFormat.YUV_420_888, 2);
                previewReader.setOnImageAvailableListener(source -> {
                    try (Image image = source.acquireLatestImage()) {
                        if (image != null) previewFrames++;
                        if (busy > 0) SystemClock.sleep(busy);
                    } catch (RuntimeException ignored) { }
                }, handler);
            }
            // warm=<ms> keeps the preview running that long before the still, so a long warm is a soak of the session
            // shape (for temperature and load); the time limit follows it.
            handler.postDelayed(timeout, CAPTURE_TIMEOUT_MILLIS
                    + (option("warm") == null ? 0 : Long.parseLong(option("warm"))));
            Log.i(TAG, "camera probe opening id=" + id
                    + " size=" + size.getWidth() + "x" + size.getHeight() + " variant=[" + variant + "]");
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
        if (option("keep") == null && captured != null && captured.exists() && !captured.delete()) {
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
            // previewonly: the session holds the small preview alone for the warm time (the sensor need not run at
            // full size), then is rebuilt with the full-size reader beside the preview and takes the still. It
            // measures what watching for a page costs without the still's stream, and what the switch costs in time.
            boolean previewOnly = option("previewonly") != null && previewReader != null;
            List<android.view.Surface> outputs = new ArrayList<>();
            if (!previewOnly) outputs.add(reader.getSurface());
            if (previewReader != null) outputs.add(previewReader.getSurface());
            if (option("priv") != null) {
                String[] wh = option("priv").split("x");
                texture = new android.graphics.SurfaceTexture(false);
                texture.setDefaultBufferSize(Integer.parseInt(wh[0]), Integer.parseInt(wh[1]));
                textureSurface = new android.view.Surface(texture);
                outputs.add(textureSurface);
            }
            device.createCaptureSession(
                    outputs,
                    new CameraCaptureSession.StateCallback() {
                        @Override
                        public void onConfigured(CameraCaptureSession configured) {
                            session = configured;
                            if (previewReader == null) { requestStill(); return; }
                            try {
                                CaptureRequest.Builder preview = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                preview.addTarget(previewReader.getSurface());
                                if (textureSurface != null) preview.addTarget(textureSurface);
                                applyOptions(preview);
                                configured.setRepeatingRequest(preview.build(), previewResults, handler);
                                long warm = option("warm") == null ? 1500 : Long.parseLong(option("warm"));
                                handler.postDelayed(() -> {
                                    if (session != configured || settled) return;
                                    if (option("reconfig") == null && !previewOnly) { requestStill(); return; }
                                    long asked = SystemClock.elapsedRealtime();
                                    try {
                                        device.createCaptureSession(previewOnly
                                                        ? java.util.Arrays.asList(reader.getSurface(), previewReader.getSurface())
                                                        : Collections.singletonList(reader.getSurface()),
                                                new CameraCaptureSession.StateCallback() {
                                                    @Override public void onConfigured(CameraCaptureSession still) {
                                                        session = still;
                                                        Log.i(TAG, "camera probe reconfigured in " + (SystemClock.elapsedRealtime() - asked) + "ms");
                                                        if (previewOnly) {
                                                            try {
                                                                CaptureRequest.Builder again = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                                                again.addTarget(previewReader.getSurface());
                                                                applyOptions(again);
                                                                still.setRepeatingRequest(again.build(), previewResults, handler);
                                                                long settle = option("settle") == null ? 800 : Long.parseLong(option("settle"));
                                                                handler.postDelayed(() -> { if (session == still && !settled) requestStill(); }, settle);
                                                            } catch (CameraAccessException | RuntimeException error) {
                                                                settle(ProbeReport.Status.FAILED, "preview after reconfigure " + error.getClass().getSimpleName());
                                                            }
                                                            return;
                                                        }
                                                        ImageReader preview = previewReader; previewReader = null;
                                                        requestStill();
                                                        previewReader = preview;
                                                    }
                                                    @Override public void onConfigureFailed(CameraCaptureSession failed) {
                                                        settle(ProbeReport.Status.FAILED, "reconfigure failed");
                                                    }
                                                }, handler);
                                    } catch (CameraAccessException | RuntimeException error) {
                                        settle(ProbeReport.Status.FAILED, "reconfigure " + error.getClass().getSimpleName());
                                    }
                                }, warm);
                            } catch (CameraAccessException | RuntimeException error) {
                                settle(ProbeReport.Status.FAILED, "preview failed: " + error.getClass().getSimpleName());
                            }
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
            applyOptions(request);
            if (option("zsl_off") != null) request.set(CaptureRequest.CONTROL_ENABLE_ZSL, false);
            if (previewReader != null && option("both") != null) request.addTarget(previewReader.getSurface());
            if (textureSurface != null && option("both") != null) request.addTarget(textureSurface);
            if (previewReader != null && option("stop") != null) session.stopRepeating();
            String asked = "auto";
            if (option("manual") != null && lastPreview != null) {
                Long exposure = lastPreview.get(android.hardware.camera2.CaptureResult.SENSOR_EXPOSURE_TIME);
                Integer iso = lastPreview.get(android.hardware.camera2.CaptureResult.SENSOR_SENSITIVITY);
                Long frame = lastPreview.get(android.hardware.camera2.CaptureResult.SENSOR_FRAME_DURATION);
                request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
                request.set(CaptureRequest.CONTROL_AWB_LOCK, true);
                if (option("expose") != null) exposure = Long.parseLong(option("expose")); // ns, in place of the preview's
                request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, exposure);
                request.set(CaptureRequest.SENSOR_FRAME_DURATION, frame);
                request.set(CaptureRequest.SENSOR_SENSITIVITY, iso);
                asked = "manual exposure_ns=" + exposure + " iso=" + iso;
            }
            if (option("nr") != null) request.set(CaptureRequest.NOISE_REDUCTION_MODE, Integer.parseInt(option("nr")));
            if (option("edge") != null) request.set(CaptureRequest.EDGE_MODE, Integer.parseInt(option("edge")));
            if (option("manual") != null && lastPreview != null) {
                Integer boost = lastPreview.get(android.hardware.camera2.CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST);
                if (boost != null && option("gain") != null) boost = Math.round(boost * Float.parseFloat(option("gain"))); // more digital gain
                if (boost != null) request.set(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST, boost);
                asked += " boost=" + boost;
            }
            stillAskedAt = SystemClock.elapsedRealtime();
            Log.i(TAG, "camera probe still requested after " + (stillAskedAt - startedAtMillis)
                    + "ms preview_frames=" + previewFrames + " " + asked);
            session.capture(request.build(), new CameraCaptureSession.CaptureCallback() {
                @Override public void onCaptureCompleted(CameraCaptureSession source, CaptureRequest done,
                        android.hardware.camera2.TotalCaptureResult result) {
                    Log.i(TAG, "camera probe still result exposure_ns="
                            + result.get(android.hardware.camera2.CaptureResult.SENSOR_EXPOSURE_TIME) + " iso="
                            + result.get(android.hardware.camera2.CaptureResult.SENSOR_SENSITIVITY) + " ae_mode="
                            + result.get(android.hardware.camera2.CaptureResult.CONTROL_AE_MODE) + " nr="
                            + result.get(android.hardware.camera2.CaptureResult.NOISE_REDUCTION_MODE) + " edge="
                            + result.get(android.hardware.camera2.CaptureResult.EDGE_MODE) + " boost="
                            + result.get(android.hardware.camera2.CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST));
                }
            }, handler);
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
            long arrived = SystemClock.elapsedRealtime();
            String encoded = "";
            byte[] bytes;
            if (image.getFormat() == ImageFormat.YUV_420_888 && option("jpeg") != null) {
                int width = image.getWidth(), height = image.getHeight();
                Image.Plane[] planes = image.getPlanes();
                long copyFrom = SystemClock.elapsedRealtime();
                byte[] nv21 = new byte[width * height * 3 / 2];
                ByteBuffer luma = planes[0].getBuffer();
                int lumaRow = planes[0].getRowStride();
                for (int y = 0; y < height; y++) { luma.position(y * lumaRow); luma.get(nv21, y * width, width); }
                ByteBuffer v = planes[2].getBuffer(), u = planes[1].getBuffer();
                int chromaRow = planes[2].getRowStride(), chromaStep = planes[2].getPixelStride();
                if (chromaStep == 2) {
                    // Semi-planar: the V plane's buffer is already V,U,V,U...; its last U byte is in the U plane.
                    for (int y = 0; y < height / 2; y++) {
                        v.position(y * chromaRow);
                        v.get(nv21, width * height + y * width, Math.min(width, v.remaining()));
                    }
                    nv21[nv21.length - 1] = u.get(u.limit() - 1);
                } else {
                    for (int y = 0; y < height / 2; y++) for (int x = 0; x < width / 2; x++) {
                        nv21[width * height + y * width + 2 * x] = v.get(y * chromaRow + x * chromaStep);
                        nv21[width * height + y * width + 2 * x + 1] = u.get(y * planes[1].getRowStride() + x * planes[1].getPixelStride());
                    }
                }
                long encodeFrom = SystemClock.elapsedRealtime();
                java.io.ByteArrayOutputStream jpeg = new java.io.ByteArrayOutputStream(8 << 20);
                new android.graphics.YuvImage(nv21, ImageFormat.NV21, width, height, null).compressToJpeg(
                        new android.graphics.Rect(0, 0, width, height), Integer.parseInt(option("jpeg")), jpeg);
                bytes = jpeg.toByteArray();
                encoded = " copy_ms=" + (encodeFrom - copyFrom) + " encode_ms=" + (SystemClock.elapsedRealtime() - encodeFrom)
                        + " luma_row=" + lumaRow + " chroma_row=" + chromaRow + " chroma_step=" + chromaStep;
            } else {
                ByteBuffer buffer = image.getPlanes()[0].getBuffer();
                bytes = new byte[buffer.remaining()];
                buffer.get(bytes);
            }
            File target = new File(context.getCacheDir(), CAPTURE_NAME);
            try (FileOutputStream out = new FileOutputStream(target)) {
                out.write(bytes);
            }
            captured = target;
            // count=<n> with keep: each still stays as probe-capture-<remaining>.jpg, so a burst can be merged off
            // the device; gap=<ms> is the wait between its stills (1500 when absent).
            if (option("count") != null && option("keep") != null) {
                try (FileOutputStream out = new FileOutputStream(
                        new File(context.getCacheDir(), "probe-capture-" + stillsLeft + ".jpg"))) {
                    out.write(bytes);
                }
            }
            long elapsed = SystemClock.elapsedRealtime() - startedAtMillis;
            Log.i(TAG, "camera probe still " + image.getWidth() + "x" + image.getHeight() + " " + bytes.length
                    + "B arrived_ms=" + (arrived - stillAskedAt) + encoded + " preview_frames=" + previewFrames);
            if (--stillsLeft > 0 && previewReader != null) {
                handler.postDelayed(() -> { if (!settled) requestStill(); },
                        option("gap") == null ? 1500 : Long.parseLong(option("gap")));
                return;
            }
            settle(ProbeReport.Status.OK,
                    image.getWidth() + "x" + image.getHeight()
                            + " " + bytes.length + "B in " + elapsed + "ms variant=[" + variant
                            + "] preview_frames=" + previewFrames);
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
        if (previewReader != null) {
            previewReader.close();
            previewReader = null;
        }
        if (textureSurface != null) { textureSurface.release(); textureSurface = null; }
        if (texture != null) { texture.release(); texture = null; }
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
