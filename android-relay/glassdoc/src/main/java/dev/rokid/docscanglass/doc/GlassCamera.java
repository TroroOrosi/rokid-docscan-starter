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
import android.hardware.camera2.params.InputConfiguration;
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
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
import dev.rokid.docscanrelay.CaptureProvenance;
import dev.rokid.docscanrelay.CaptureSurface;

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

    enum Mode { NATIVE_STILL, ZSL_EVALUATION_YUV }

    private static final String TAG = "DocScanGlassDoc";
    private static final long CAPTURE_TIMEOUT_MILLIS = 15_000;
    // Preparation plus JPEG deadline remains below the controller's 30s capture lease.
    private static final long PREPARE_TIMEOUT_MILLIS = 10_000;
    // Same bound as CaptureReviewPersistence; reject before allocating a second buffer.
    private static final int MAX_JPEG_BYTES = 8 * 1024 * 1024;

    interface Callback {
        void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis);

        default void onCaptured(Captured captured) {
            onCaptured(captured.jpeg, captured.width, captured.height, captured.elapsedMillis);
        }

        void onCaptureFailed(String reason);

        default void onPreview(Bitmap frame) { frame.recycle(); }
    }

    static final class Captured {
        final byte[] jpeg;
        final int width, height;
        final long elapsedMillis;
        final CaptureProvenance provenance;
        final boolean associationResolved;

        Captured(byte[] jpeg, int width, int height, long elapsedMillis, CaptureProvenance provenance) {
            this(jpeg, width, height, elapsedMillis, provenance, true);
        }

        Captured(byte[] jpeg, int width, int height, long elapsedMillis, CaptureProvenance provenance,
                boolean associationResolved) {
            this.jpeg = jpeg;
            this.width = width;
            this.height = height;
            this.elapsedMillis = elapsedMillis;
            this.provenance = provenance;
            this.associationResolved = associationResolved;
        }
    }

    /** A still result is never borrowed from preview metering or a previous generation. */
    private static final class StillResult {
        final long generation;
        final Long timestamp, frame, exposure;
        final Integer iso, af, ae;
        StillResult(long generation, TotalCaptureResult result) {
            this.generation = generation;
            timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
            frame = result.getFrameNumber();
            exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
            iso = result.get(CaptureResult.SENSOR_SENSITIVITY);
            af = result.get(CaptureResult.CONTROL_AF_STATE);
            ae = result.get(CaptureResult.CONTROL_AE_STATE);
        }
    }

    private final Context context;
    private final Handler handler;
    private final Callback callback;
    private final Stillness stillness;
    private final Mode mode;
    private final Executor inputWorker;
    private final ZslInputTransfer.Factory inputFactory;
    private ImageReader zslReader;
    private ZslFrameBuffer zslFrames;
    private ZslFrameBuffer.Selection selectedInput;
    private ZslInputTransfer inputTransfer;
    private boolean zslClosing;
    private boolean zslCloseComplete = true;

    private ImageReader reader;
    private long lastJpegSensorTimestamp;
    private long startedAtMillis;
    private StillResult stillResult;
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
    private long previewDisplayAt;
    private boolean capturePending;
    private CaptureSurface.FuturePageListener futurePages;
    private CaptureSurface.FuturePageListener activeFuturePage;
    private int futureCapacity;
    private long sceneStartTimestamp;
    private long futureSceneSequence;
    private long futureSceneStartTimestamp;
    private long futureSceneEndTimestamp;
    private long waitingStableScene;
    private final List<Runnable> futureStops = new ArrayList<>();
    private CameraReadiness metering;
    private long meteringSensorTimestamp;
    private long lastMeteringSensorTimestamp;
    private long meteringExposureNanos;
    private long previewSensorTimestamp;
    private long lastPreviewSensorTimestamp;
    private boolean autoFocusStarted;
    private long autoFocusSensorTimestamp;
    private PageChange previewMotion = new PageChange();
    private final Runnable prepareTimeout = () -> previewFailed("camera not still or AF/AE not ready");
    private final Runnable inputReleaseTimeout = () -> previewFailed("ZSL input release timeout");

    private final Runnable timeout = () -> fail("CAMERA TIMEOUT");

    GlassCamera(Context context, Handler handler, Callback callback) {
        this(context, handler, callback, Mode.NATIVE_STILL);
    }

    GlassCamera(Context context, Handler handler, Callback callback, Mode mode) {
        this(context, handler, callback, mode, null, null);
    }

    GlassCamera(Context context, Handler handler, Callback callback, Mode mode,
                Executor worker, ZslInputTransfer.Factory factory) {
        this.context = context;
        this.handler = handler;
        this.callback = callback;
        this.mode = mode;
        inputWorker = worker;
        inputFactory = factory;
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
            stillness.await(handler, this::cameraReady, this::motionExposureNanos, this::captureOnHandler);
        });
    }

    void resetPages() { handler.post(() -> pageChange = new PageChange()); }

    void observeFuturePages(int capacity, CaptureSurface.FuturePageListener listener) {
        if (capacity < 0 || capacity > 2 || listener == null) throw new IllegalArgumentException("future capacity 0..2 required");
        handler.post(() -> {
            if (closed || unknown) return;
            futurePages = listener;
            futureCapacity = Math.max(0, capacity - (activeFuturePage == null ? 0 : 1));
            previewRequested = true;
            startPreview();
        });
    }

    void stopFuturePages(Runnable idle) {
        handler.post(() -> {
            futurePages = null;
            futureCapacity = 0;
            waitingStableScene = 0;
            if (activeFuturePage != null && (generation == 0 || settled)) {
                // Preparation has not issued a native request, so it can be cancelled safely.
                activeFuturePage = null;
                capturePending = false;
                stillness.cancel();
                handler.removeCallbacks(prepareTimeout);
            }
            if (activeFuturePage == null && inputIdle()) idle.run(); else futureStops.add(idle);
        });
    }

    private void futureIdle() {
        if (activeFuturePage != null || !inputIdle()) return;
        List<Runnable> idle = new ArrayList<>(futureStops);
        futureStops.clear();
        for (Runnable ready : idle) ready.run();
    }

    private boolean inputIdle() {
        return mode == Mode.NATIVE_STILL || (zslCloseComplete && (inputTransfer == null || inputTransfer.idle()));
    }

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
            futurePages = null;
            if (!capturePending) { stillness.cancel(); stopPreview(); }
        });
    }

    /** Prepare YUV and the full-size JPEG in the same session, retaining metered focus. */
    @RequiresPermission(Manifest.permission.CAMERA)
    private void startPreview() {
        if (!previewRequested || closed || unknown || previewReader != null || previewClosing || zslClosing
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
            if (mode == Mode.ZSL_EVALUATION_YUV) requireZsl(characteristics, map, jpegSize);
            metering = new CameraReadiness(characteristics.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES),
                    characteristics.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE),
                    characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES));
            previewMotion = new PageChange();
            previewAt = 0;
            previewDisplayAt = 0;
            meteringSensorTimestamp = 0;
            lastMeteringSensorTimestamp = 0;
            meteringExposureNanos = 0;
            previewSensorTimestamp = 0;
            lastPreviewSensorTimestamp = 0;
            autoFocusStarted = false;
            autoFocusSensorTimestamp = 0;
            lastJpegSensorTimestamp = 0;
            CameraDiagnostics.capabilities(generation + 1, characteristics, jpegSize);
            reader = ImageReader.newInstance(jpegSize.getWidth(), jpegSize.getHeight(), ImageFormat.JPEG, 1);
            reader.setOnImageAvailableListener(source -> {
                if (source == reader) onImageAvailable(source);
            }, handler);
            previewReader = ImageReader.newInstance(size.getWidth(), size.getHeight(), ImageFormat.YUV_420_888, 2);
            previewReader.setOnImageAvailableListener(source -> previewFrame(source, token), handler);
            if (mode == Mode.ZSL_EVALUATION_YUV) {
                zslFrames = new ZslFrameBuffer();
                zslReader = ImageReader.newInstance(jpegSize.getWidth(), jpegSize.getHeight(),
                        ImageFormat.YUV_420_888, ZslFrameBuffer.READER_IMAGES);
                zslReader.setOnImageAvailableListener(source -> zslFrame(source, token), handler);
                Log.i(TAG, "producer=zsl_evaluation_yuv ring=3 selected=1 acquire_headroom=2 reader_max=6 size=" + jpegSize);
            }
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
                        CameraCaptureSession.StateCallback sessionCallback = new CameraCaptureSession.StateCallback() {
                            @Override public void onConfigured(CameraCaptureSession configured) {
                                if (token != previewGeneration || !previewRequested || closed) { configured.close(); return; }
                                previewSession = configured;
                                try {
                                    if (!metering.supported()) {
                                        previewFailed("camera AF/AE capabilities unsupported"); return;
                                    }
                                    CaptureRequest.Builder request = opened.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                    request.addTarget(previewReader.getSurface());
                                    if (mode == Mode.ZSL_EVALUATION_YUV) {
                                        if (!configured.isReprocessable() || configured.getInputSurface() == null)
                                            throw new IllegalStateException("ZSL session has no input");
                                        Executor worker = inputWorker != null ? inputWorker : Executors.newSingleThreadExecutor(task -> {
                                            Thread thread = new Thread(task, "glass-zsl-input"); thread.setDaemon(true); return thread;
                                        });
                                        inputTransfer = new ZslInputTransfer(worker, handler,
                                                inputFactory != null ? inputFactory
                                                        : ZslInputTransfer.nativeWriter(configured.getInputSurface(), handler),
                                                GlassCamera.this::previewFailed);
                                        inputTransfer.onIdle(GlassCamera.this::inputReleased);
                                        request.addTarget(zslReader.getSurface());
                                    }
                                    applyMetering(request);
                                    configured.setRepeatingRequest(request.build(), previewResults(token, false), handler);
                                } catch (CameraAccessException | RuntimeException error) { previewFailed(); }
                            }
                            @Override public void onConfigureFailed(CameraCaptureSession failed) {
                                failed.close(); if (token == previewGeneration) previewFailed("camera YUV/JPEG session refused");
                            }
                        };
                        if (mode == Mode.ZSL_EVALUATION_YUV) {
                            opened.createReprocessableCaptureSession(new InputConfiguration(jpegSize.getWidth(), jpegSize.getHeight(),
                                    ImageFormat.YUV_420_888), Arrays.asList(previewReader.getSurface(),
                                    zslReader.getSurface(), reader.getSurface()), sessionCallback, handler);
                        } else {
                            opened.createCaptureSession(Arrays.asList(previewReader.getSurface(), reader.getSurface()),
                                    sessionCallback, handler);
                        }
                    } catch (CameraAccessException | RuntimeException error) { previewFailed(); }
                }
                @Override public void onDisconnected(CameraDevice disconnected) {
                    previewOpening = false;
                    if (disconnected == previewDevice && generation > 0 && active(generation)) fail("camera disconnected");
                    else { disconnected.close(); if (token == previewGeneration) previewFailed(); }
                }
                @Override public void onError(CameraDevice errored, int code) {
                    previewOpening = false;
                    if (errored == previewDevice && generation > 0 && active(generation)) fail("camera error " + code);
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
            long timestamp = image.getTimestamp();
            if (timestamp <= 0 || timestamp <= lastPreviewSensorTimestamp) {
                // Do not refresh readiness or invent a turn from an old/invalid buffer.
                previewSensorTimestamp = 0;
                return;
            }
            lastPreviewSensorTimestamp = timestamp;
            previewSensorTimestamp = timestamp;
            previewAt = now;
            Image.Plane luma = image.getPlanes()[0];
            ByteBuffer pixels = luma.getBuffer();
            int row = luma.getRowStride(), step = luma.getPixelStride();
            byte[] thumbnail = new byte[32 * 24];
            for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++) {
                thumbnail[y * 32 + x] = pixels.get(y * image.getHeight() / 24 * row + x * image.getWidth() / 32 * step);
            }
            long previousScene = pageChange.sequence();
            pageChange.observe(thumbnail, now);
            if (previousScene != pageChange.sequence()) {
                sceneStartTimestamp = timestamp;
                if (activeFuturePage != null && futureSceneEndTimestamp == Long.MAX_VALUE) {
                    futureSceneEndTimestamp = timestamp;
                }
                if (futurePages != null && waitingStableScene != 0
                        && waitingStableScene != futureSceneSequence) futurePageMissed();
                waitingStableScene = 0;
            }
            previewMotion.observe(thumbnail, now);
            // AUTO/MACRO must start before pageReady can require a focused result.
            if (capturePending || ((pageReady != null || futurePages != null) && pageChange.ready(now))) startAutoFocus();
            // Observe every received frame; only the HUD bitmap is limited to 10 Hz.
            if (now - previewDisplayAt >= 100) {
                previewDisplayAt = now;
                int width = Math.min(320, image.getWidth()), height = Math.max(1, width * image.getHeight() / image.getWidth());
                int[] display = new int[width * height];
                for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                    int gray = pixels.get(y * image.getHeight() / height * row + x * image.getWidth() / width * step) & 255;
                    display[y * width + x] = 0xFF000000 | (gray << 8);
                }
                callback.onPreview(Bitmap.createBitmap(display, width, height, Bitmap.Config.RGB_565));
            }
            if (!capturePending && pageReady != null && pageChange.ready(now) && meteredFrame(now)) {
                Runnable ready = pageReady;
                pageReady = null;
                ready.run();
            }
            if (futurePages != null && pageChange.ready(now) && meteredFrame(now)) {
                waitingStableScene = pageChange.sequence();
                if (!capturePending) {
                    if (futureCapacity == 0) futurePageMissed();
                    else {
                        activeFuturePage = futurePages;
                        futureCapacity--;
                        futureSceneSequence = pageChange.sequence();
                        futureSceneStartTimestamp = sceneStartTimestamp;
                        futureSceneEndTimestamp = Long.MAX_VALUE;
                        capturePending = true;
                        handler.postDelayed(prepareTimeout, PREPARE_TIMEOUT_MILLIS);
                        stillness.await(handler, this::cameraReady, this::motionExposureNanos, this::captureOnHandler);
                    }
                }
            }
        } catch (RuntimeException | OutOfMemoryError error) { previewFailed(); }
    }

    private void futurePageMissed() {
        CaptureSurface.FuturePageListener observer = futurePages;
        futurePages = null;
        futureCapacity = 0;
        if (observer != null) observer.onPageMissed();
    }

    private void stopPreview() {
        release();
    }

    private void previewClosed() {
        if (!previewClosing) return;
        previewClosing = false;
        startPreview();
    }

    private void previewFailed() { previewFailed("preview unavailable"); }

    private void previewFailed(String reason) {
        if (closed || unknown) return;
        if (generation > 0 && active(generation)) { fail(reason); return; }
        previewRequested = false;
        previewOpening = false;
        unknown = true;
        capturePending = false;
        futurePages = null;
        activeFuturePage = null;
        stillness.cancel();
        handler.removeCallbacks(prepareTimeout);
        stopPreview();
        callback.onCaptureFailed(reason);
        futureIdle();
    }

    private boolean cameraReady() {
        long now = SystemClock.elapsedRealtime();
        return !closed && !unknown && previewDevice != null && previewSession != null
                && (activeFuturePage == null || (futureSceneSequence == pageChange.sequence()
                && pageChange.ready(now)))
                && meteringExposureNanos > 0 && meteredFrame(now) && previewMotion.ready(now)
                && now >= previewAt && now - previewAt <= CameraReadiness.FRESH_MILLIS
                && (mode == Mode.NATIVE_STILL || (inputTransfer != null && inputTransfer.ready() && zslCandidate() != null));
    }

    private void inputReleased() {
        if (inputIdle()) handler.removeCallbacks(inputReleaseTimeout);
        futureIdle();
    }

    /** The preview's actual exposure, never a request setting or an old session's result. */
    private long motionExposureNanos() {
        long now = SystemClock.elapsedRealtime();
        long exposure = !closed && !unknown && previewDevice != null && previewSession != null
                && meteredFrame(now) && now >= previewAt
                && now - previewAt <= CameraReadiness.FRESH_MILLIS ? meteringExposureNanos : 0;
        if (exposure <= 0 || mode == Mode.NATIVE_STILL) return exposure;
        ZslFrameBuffer.Selection candidate = zslCandidate();
        return candidate == null ? exposure : Math.max(exposure, candidate.result.get(CaptureResult.SENSOR_EXPOSURE_TIME));
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
        long focusGeneration = generation;
        return new CameraCaptureSession.CaptureCallback() {
            private boolean current() {
                return token == previewGeneration && !closed && !unknown
                        && (!focusTrigger || (focusGeneration == generation && autoFocusStarted));
            }
            @Override public void onCaptureCompleted(CameraCaptureSession source,
                    CaptureRequest request, TotalCaptureResult result) {
                if (!current() || source != previewSession || result == null) return;
                try {
                    if (!focusTrigger && zslFrames != null) zslFrames.result(result);
                    Long timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
                    if (timestamp == null || timestamp <= 0) {
                        meteringExposureNanos = 0;
                        meteringSensorTimestamp = 0; return;
                    }
                    // Fence old LOCKED metadata until this START has reached the native pipeline.
                    if (focusTrigger) autoFocusSensorTimestamp = timestamp;
                    if (timestamp <= lastMeteringSensorTimestamp) return;
                    lastMeteringSensorTimestamp = timestamp;
                    meteringSensorTimestamp = timestamp;
                    Long exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
                    meteringExposureNanos = exposure != null && exposure > 0 ? exposure : 0;
                    metering.observe(result.get(CaptureResult.CONTROL_AF_STATE),
                            result.get(CaptureResult.CONTROL_AE_STATE), SystemClock.elapsedRealtime());
                } catch (RuntimeException error) { previewFailed("camera metering unavailable"); }
            }
            @Override public void onCaptureFailed(CameraCaptureSession source,
                    CaptureRequest request, CaptureFailure failure) {
                if (current()) previewFailed("camera metering failed");
            }
        };
    }

    private void zslFrame(ImageReader source, long token) {
        if (source != zslReader || token != previewGeneration || closed || unknown) return;
        Image image = null;
        try {
            image = source.acquireLatestImage();
            if (image == null) return;
            if (image.getFormat() != ImageFormat.YUV_420_888
                    || image.getWidth() != reader.getWidth() || image.getHeight() != reader.getHeight())
                throw new IllegalStateException("ZSL native input dimensions");
            Image owned = image; image = null;
            zslFrames.image(owned);
        } catch (RuntimeException | OutOfMemoryError error) {
            if (image != null) closeResource(image);
            previewFailed("ZSL input image " + error.getClass().getSimpleName());
        }
    }

    private ZslFrameBuffer.Selection zslCandidate() {
        if (zslFrames == null || stillness.quietSinceNanos() <= 0) return null;
        long now = SystemClock.elapsedRealtimeNanos();
        long minimum = Math.max(Math.max(sceneStartTimestamp, stillness.quietSinceNanos()),
                Math.max(lastJpegSensorTimestamp + 1, now - CameraReadiness.FRESH_MILLIS * 1_000_000L));
        return zslFrames.latest(minimum, now, result -> {
            Long timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
            Long exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
            if (timestamp == null || exposure == null || exposure <= 0 || exposure > now - timestamp) return false;
            CameraReadiness source = new CameraReadiness(new int[]{metering.afMode},
                    metering.afMode == CaptureRequest.CONTROL_AF_MODE_OFF ? 0f : 1f,
                    new int[]{CaptureRequest.CONTROL_AE_MODE_ON});
            source.observe(result.get(CaptureResult.CONTROL_AF_STATE), result.get(CaptureResult.CONTROL_AE_STATE),
                    SystemClock.elapsedRealtime());
            return source.ready(SystemClock.elapsedRealtime());
        });
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
        if (activeFuturePage != null && !activeFuturePage.onCaptureStarting()) {
            previewFailed("future original reservation failed");
            return;
        }
        if (!cameraReady()) {
            previewFailed("future original reservation outlived camera readiness");
            return;
        }
        if (mode == Mode.ZSL_EVALUATION_YUV) {
            selectedInput = zslFrames.take(zslCandidate());
            if (selectedInput == null) { previewFailed("ZSL source expired before issue"); return; }
        }
        long current = ++generation;
        stillResult = null;
        settled = false;
        pageChange.consumed();
        startedAtMillis = SystemClock.elapsedRealtime();
        handler.removeCallbacks(prepareTimeout);
        handler.postDelayed(timeout, CAPTURE_TIMEOUT_MILLIS);
        if (mode == Mode.NATIVE_STILL) requestStill(current);
        else {
            Log.i(TAG, "producer=zsl_evaluation_yuv gen=" + current + " source_age_ns="
                    + (SystemClock.elapsedRealtimeNanos() - selectedInput.timestamp) + " raw_ring=" + zslFrames.size());
            handler.postDelayed(inputReleaseTimeout, CAPTURE_TIMEOUT_MILLIS);
            long sessionGeneration = previewGeneration;
            if (!inputTransfer.queue(selectedInput.image, () -> {
                if (active(current) && !unknown && sessionGeneration == previewGeneration) requestReprocess(current);
            })) {
                closeResource(selectedInput.image);
                selectedInput = null;
                fail("ZSL input credit unavailable");
            }
        }
    }

    void close() {
        handler.post(() -> {
            closed = true;
            settled = true;
            generation++;
            previewRequested = false;
            pageReady = null;
            futurePages = null;
            activeFuturePage = null;
            stillness.cancel();
            stopPreview();
            handler.removeCallbacks(timeout);
            handler.removeCallbacks(prepareTimeout);
            futureIdle();
        });
    }

    private void requestStill(long current) {
        try {
            CaptureRequest.Builder request =
                    previewDevice.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
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
            // capture() takes priority over repeating preview without stopping its next frames.
            previewSession.capture(request.build(), captureCallback(current), handler);
        } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) {
            fail("capture " + error.getClass().getSimpleName());
        }
    }

    private void requestReprocess(long current) {
        try {
            CaptureRequest.Builder request = previewDevice.createReprocessCaptureRequest(selectedInput.result);
            request.set(CaptureRequest.CONTROL_CAPTURE_INTENT, CaptureRequest.CONTROL_CAPTURE_INTENT_STILL_CAPTURE);
            request.set(CaptureRequest.JPEG_ORIENTATION, 0);
            request.addTarget(reader.getSurface());
            previewSession.capture(request.build(), captureCallback(current), handler);
        } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) {
            fail("ZSL reprocess " + error.getClass().getSimpleName());
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
                if (active(current) && !unknown && result != null) {
                    try { stillResult = new StillResult(current, result); }
                    catch (RuntimeException unavailable) { stillResult = null; }
                }
            }
        };
    }

    private void onImageAvailable(ImageReader source) {
        final byte[] jpeg;
        final int width;
        final int height;
        final long sensorTimestamp;
        try (Image image = source.acquireNextImage()) {
            // A retained reader must drain late notifications even between requests.
            if (source != reader || generation <= 0 || !active(generation)) return;
            if (image == null || image.getFormat() != ImageFormat.JPEG) {
                throw new RejectedJpeg("missing JPEG image");
            }
            width = image.getWidth();
            height = image.getHeight();
            sensorTimestamp = image.getTimestamp();
            if (sensorTimestamp <= 0) throw new RejectedJpeg("invalid JPEG timestamp");
            // One JPEG is in flight. A previous original cannot satisfy the next request.
            // Device ZSL may predate preview, so only compare this reader's JPEG timestamps.
            if (mode == Mode.NATIVE_STILL && sensorTimestamp <= lastJpegSensorTimestamp) return;
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
            // A settled JPEG reader still owns the live preview camera while it drains.
            previewFailed("image " + error.getClass().getSimpleName());
            return;
        }
        if (settled || closed) return;
        ZslFrameBuffer.Selection outputSource = selectedInput;
        if (!previewRequested && !release()) {
            fail("camera close failed");
            return;
        }
        settled = true;
        capturePending = false;
        lastJpegSensorTimestamp = sensorTimestamp;
        autoFocusStarted = false;
        autoFocusSensorTimestamp = 0;
        handler.removeCallbacks(timeout);
        long elapsed = SystemClock.elapsedRealtime() - startedAtMillis;
        Log.i(TAG, "captured " + width + "x" + height
                + " " + jpeg.length + "B in " + elapsed + "ms gen=" + generation);
        // No native Image is held when the consumer queues another allocation.
        // Reuse the configured readers/session until pause, close or failure.
        // Consumer exceptions must not re-label a delivered image as a camera failure.
        StillResult result = stillResult != null && stillResult.generation == generation ? stillResult : null;
        boolean associationResolved = mode == Mode.NATIVE_STILL || (outputSource != null
                && sensorTimestamp == outputSource.timestamp);
        CaptureProvenance provenance;
        if (mode == Mode.NATIVE_STILL) {
            provenance = CaptureProvenance.nativeStill(jpeg, width, height, sensorTimestamp,
                    result == null ? null : result.timestamp, result == null ? null : result.frame,
                    result == null ? null : result.exposure, result == null ? null : result.iso,
                    result == null ? null : result.af, result == null ? null : result.ae);
        } else if (associationResolved) {
            TotalCaptureResult sourceResult = outputSource.result;
            provenance = CaptureProvenance.zslReprocess(jpeg, width, height, sensorTimestamp,
                    sourceResult.get(CaptureResult.SENSOR_TIMESTAMP), sourceResult.getFrameNumber(),
                    sourceResult.get(CaptureResult.SENSOR_EXPOSURE_TIME), sourceResult.get(CaptureResult.SENSOR_SENSITIVITY),
                    sourceResult.get(CaptureResult.CONTROL_AF_STATE), sourceResult.get(CaptureResult.CONTROL_AE_STATE));
        } else {
            provenance = null;
        }
        selectedInput = null;
        CaptureSurface.FuturePageListener future = activeFuturePage;
        activeFuturePage = null;
        if (future == null) callback.onCaptured(new Captured(jpeg, width, height, elapsed, provenance, associationResolved));
        else {
            boolean sceneMatched = associationResolved && sensorTimestamp >= futureSceneStartTimestamp
                    && sensorTimestamp < futureSceneEndTimestamp;
            if (!sceneMatched) { futurePages = null; futureCapacity = 0; }
            future.onCandidate(jpeg, provenance, sceneMatched);
        }
        if (!associationResolved) previewFailed("ZSL original timestamp mismatch");
        futureIdle();
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
        previewRequested = false;
        pageReady = null;
        futurePages = null;
        activeFuturePage = null;
        stillness.cancel();
        handler.removeCallbacks(timeout);
        handler.removeCallbacks(prepareTimeout);
        release();
        Log.w(TAG, "capture failed: " + reason);
        callback.onCaptureFailed(reason);
        futureIdle();
    }

    private boolean release() {
        // Detach ownership first, then attempt every close even if one fails.
        CameraCaptureSession oldSession = previewSession;
        CameraDevice oldDevice = previewDevice;
        ImageReader oldReader = reader;
        ImageReader oldPreviewReader = previewReader;
        ImageReader oldZslReader = zslReader;
        ZslFrameBuffer oldFrames = zslFrames;
        ZslInputTransfer oldInput = inputTransfer;
        previewSession = null;
        previewDevice = null;
        reader = null;
        previewReader = null;
        zslReader = null;
        zslFrames = null;
        inputTransfer = null;
        selectedInput = null;
        ++previewGeneration;
        meteringExposureNanos = 0;
        if (oldDevice != null || previewOpening) previewClosing = true;
        if (mode == Mode.ZSL_EVALUATION_YUV) {
            if (zslClosing) return true;
            zslClosing = true; zslCloseComplete = false;
            final boolean[] finished = {false, false};
            Runnable completed = () -> {
                if (!finished[0] || !finished[1]) return;
                zslClosing = false; zslCloseComplete = true;
                inputReleased(); startPreview();
            };
            // Stop the consumer independently; a blocked native input cannot starve its own cleanup.
            Thread closer = new Thread(() -> {
                boolean ok = closeResource(oldSession);
                ok = closeResource(oldDevice) && ok;
                boolean success = ok;
                handler.post(() -> { finished[0] = success; completed.run(); });
            }, "glass-zsl-close");
            closer.setDaemon(true); closer.start();
            Runnable owners = () -> {
                boolean ok = closeResource(oldFrames);
                ok = closeResource(oldZslReader) && ok;
                ok = closeResource(oldReader) && ok;
                ok = closeResource(oldPreviewReader) && ok;
                if (!ok) throw new IllegalStateException("ZSL native owners close failed");
            };
            Runnable ownersClosed = () -> { finished[1] = true; completed.run(); };
            if (oldInput != null) oldInput.close(owners, ownersClosed);
            else {
                Thread cleanup = new Thread(() -> {
                    try { owners.run(); handler.post(ownersClosed); }
                    catch (RuntimeException | OutOfMemoryError error) { Log.w(TAG, "ZSL cleanup " + error.getClass().getSimpleName()); }
                }, "glass-zsl-owners");
                cleanup.setDaemon(true); cleanup.start();
            }
            return true;
        }
        boolean ok = closeResource(oldSession);
        ok = closeResource(oldDevice) && ok;
        ok = closeResource(oldReader) && ok;
        return closeResource(oldPreviewReader) && ok;
    }

    private static void requireZsl(CameraCharacteristics characteristics, StreamConfigurationMap map, Size size) {
        int[] capabilities = characteristics.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
        Integer timestampSource = characteristics.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE);
        Integer level = characteristics.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL);
        if (timestampSource == null || timestampSource != CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
                || !contains(capabilities, CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING)
                || !(contains(capabilities, CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE)
                || (level != null && (level == CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_FULL
                || level == CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_3))))
            throw new IllegalStateException("ZSL evaluation capabilities unsupported");
        if (map == null || size == null || !contains(map.getInputFormats(), ImageFormat.YUV_420_888)
                || !Arrays.asList(map.getInputSizes(ImageFormat.YUV_420_888)).contains(size)
                || !Arrays.asList(map.getOutputSizes(ImageFormat.YUV_420_888)).contains(size)
                || !contains(map.getValidOutputFormatsForInput(ImageFormat.YUV_420_888), ImageFormat.JPEG))
            throw new IllegalStateException("ZSL evaluation native stream unsupported");
    }

    private static boolean contains(int[] values, int expected) {
        if (values != null) for (int value : values) if (value == expected) return true;
        return false;
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
