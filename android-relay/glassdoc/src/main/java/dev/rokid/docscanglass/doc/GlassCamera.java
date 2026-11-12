package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.content.Context;
import android.graphics.ImageFormat;
import android.graphics.Bitmap;
import android.graphics.Rect;
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
import android.hardware.camera2.params.OutputConfiguration;
import android.hardware.camera2.params.SessionConfiguration;
import android.hardware.camera2.params.MeteringRectangle;
import android.media.Image;
import android.media.ImageReader;
import android.os.Build;
import android.os.Handler;
import android.os.SystemClock;
import android.util.Log;
import android.util.Size;
import android.util.Range;
import android.view.Surface;

import androidx.annotation.RequiresPermission;

import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.Collections;
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

    enum Mode { NATIVE_STILL, ZSL_EVALUATION_YUV, VIDEO_EVALUATION }

    private static final String TAG = "DocScanGlassDoc";
    /** Longest time in each part of the preview frame handler since the last status line. */
    private final long[] stepNanos = new long[7];
    /** Starts the repeating preview on a session of this camera run; reused after each still's own session. */
    private CameraCaptureSession.StateCallback previewSessionCallback;
    /** True while {@link #previewSession} is the JPEG-only session of one still. */
    private boolean stillSession;
    /**
     * The still arrives as full-size YUV beside the running preview and is encoded here. Measured on the
     * glasses on 2026-11-12 (firmware 1.29.013, glassprobe {@code yuvstill}): 13 of 13 stills, 0.65-0.74 s
     * after the request, the preview at about 12 frames a second throughout, manual exposure honoured,
     * 0.04-0.06 s to copy and 0.19-0.45 s to encode. With noise reduction and edge enhancement off its
     * pixel-scale noise equals the camera's own JPEG (7.04 against 7.26), so it is the sensor's full size.
     * The JPEG output cannot share a session on that firmware; its own session costs about 3 s without
     * preview after every still, which stays as the path for a camera that offers no full-size YUV.
     */
    private boolean yuvStill;
    private boolean yuvStillRefused;
    private boolean encodingStill;
    private int stillJpegQuality;
    private byte[] stillNv21;
    private Executor stillWorker;
    /** About the quality of the camera's own JPEG (quantization tables 1-5 on its saved photographs). */
    static final int STILL_JPEG_QUALITY = 98;

    /** NV21 to JPEG; null when it cannot be encoded. Replaced in tests, which have no codec. */
    interface StillEncoder { byte[] encode(byte[] nv21, int width, int height, int quality); }
    StillEncoder stillEncoder = (nv21, width, height, quality) -> {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream(8 << 20);
        return new android.graphics.YuvImage(nv21, ImageFormat.NV21, width, height, null)
                .compressToJpeg(new Rect(0, 0, width, height), quality, out) ? out.toByteArray() : null;
    };
    /**
     * Set when a preview stream starts over after a still or a pause: its exposure starts over too, and
     * until it has settled the frames differ from the page just taken. Counted as page turns they took the
     * same unmoving page again and again on the glasses (2026-11-12).
     */
    private long resumeSettlingSince;
    /** Mean level of the last preview frame seen with no still in flight; negative before the first. */
    private int quietLevel = -1;
    static final long RESUME_SETTLE_LIMIT_MILLIS = 2000;
    private static final long CAPTURE_TIMEOUT_MILLIS = 15_000;
    // Preparation plus JPEG deadline remains below the controller's 30s capture lease.
    private static final long PREPARE_TIMEOUT_MILLIS = 10_000;
    // Same bound as CaptureReviewPersistence; reject before allocating a second buffer.
    static final int MAX_JPEG_BYTES = CaptureSurface.MAX_JPEG_BYTES;

    interface Callback {
        void onCaptured(byte[] jpeg, int width, int height, long elapsedMillis);

        default void onCaptured(Captured captured) {
            onCaptured(captured.jpeg, captured.width, captured.height, captured.elapsedMillis);
        }

        void onCaptureFailed(String reason);

        /** Preparation ended before any camera request; the camera and preview remain usable. */
        default void onCaptureNotReady() { onCaptureFailed("camera not still or AF/AE not ready"); }

        default void onPreview(Bitmap frame) { frame.recycle(); }
        default void onPreview(Bitmap frame, PaperGeometry.Box proposal) { onPreview(frame); }
        default CaptureVideoTransfer.Origin comparisonVideoOrigin(CaptureVideoRecording.Options options) { return null; }
        default void onVideoSealed() {}
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
        final Integer iso, af, ae, aeMode, boost;
        final Boolean awbLocked;
        StillResult(long generation, TotalCaptureResult result) {
            this.generation = generation;
            timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
            frame = result.getFrameNumber();
            exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
            iso = result.get(CaptureResult.SENSOR_SENSITIVITY);
            af = result.get(CaptureResult.CONTROL_AF_STATE);
            ae = result.get(CaptureResult.CONTROL_AE_STATE);
            aeMode = result.get(CaptureResult.CONTROL_AE_MODE);
            boost = result.get(CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST);
            awbLocked = result.get(CaptureResult.CONTROL_AWB_LOCK);
        }
    }

    /** Freeze the measured exposure for one fixed-focus still, including its processed-image gain. */
    private static final class StillExposure {
        final long exposure, frameDuration, sourceTimestamp;
        final int iso;
        final Integer boost;
        final Range<Long> exposureRange;
        final Range<Integer> isoRange, boostRange;

        StillExposure(long exposure, long frameDuration, long sourceTimestamp, int iso, Integer boost,
                Range<Long> exposureRange, Range<Integer> isoRange, Range<Integer> boostRange) {
            this.exposure = exposure; this.frameDuration = frameDuration; this.iso = iso; this.boost = boost;
            this.sourceTimestamp = sourceTimestamp;
            this.exposureRange = exposureRange; this.isoRange = isoRange; this.boostRange = boostRange;
        }

        static boolean supported(CameraCharacteristics camera) {
            int[] capabilities = camera.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
            return contains(capabilities, CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR)
                    && contains(capabilities, CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_READ_SENSOR_SETTINGS)
                    && contains(camera.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES), CaptureRequest.CONTROL_AE_MODE_OFF)
                    && Boolean.TRUE.equals(camera.get(CameraCharacteristics.CONTROL_AWB_LOCK_AVAILABLE))
                    && camera.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE) != null
                    && camera.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE) != null
                    && camera.get(CameraCharacteristics.SENSOR_INFO_MAX_FRAME_DURATION) != null;
        }

        static StillExposure observe(CameraCharacteristics camera, TotalCaptureResult result) {
            Long exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
            Long duration = result.get(CaptureResult.SENSOR_FRAME_DURATION);
            Integer iso = result.get(CaptureResult.SENSOR_SENSITIVITY);
            Range<Long> exposureRange = camera.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE);
            Range<Integer> isoRange = camera.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE);
            Range<Integer> boostRange = camera.get(CameraCharacteristics.CONTROL_POST_RAW_SENSITIVITY_BOOST_RANGE);
            Integer boost = result.get(CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST);
            if (!Integer.valueOf(CaptureRequest.CONTROL_AE_MODE_ON).equals(result.get(CaptureResult.CONTROL_AE_MODE))
                    || exposure == null || exposure <= 0 || !exposureRange.contains(exposure)
                    || duration == null || duration < exposure || duration > camera.get(CameraCharacteristics.SENSOR_INFO_MAX_FRAME_DURATION)
                    || iso == null || iso <= 0 || !isoRange.contains(iso)
                    || (boostRange != null && (boost == null || boost <= 0 || !boostRange.contains(boost)))) return null;
            // As few whole flicker periods as the sensitivity ceiling allows, so the still keeps the light the
            // preview measured: one period where sensitivity can carry it, more where it cannot. The first
            // rule, one period and darker rather than slower (2026-11-10), was wrong in dim light: on the
            // glasses a scene the preview exposed for 50 ms at the ceiling came out at 17 of 255 in 10 ms
            // and at 62 in 50 ms (2026-11-12). The stillness the shot waits for follows this exposure.
            // An unreported flicker, or no whole number of periods within it, leaves the measured exposure.
            Integer flicker = result.get(CaptureResult.STATISTICS_SCENE_FLICKER);
            long period = flicker == null ? 0 : flicker == CaptureResult.STATISTICS_SCENE_FLICKER_60HZ
                    ? 8_333_333L : Stillness.REFERENCE_EXPOSURE_NANOS;
            if (period > 0 && exposure > period + period / 100 && exposureRange.contains(period)) {
                Integer analog = camera.get(CameraCharacteristics.SENSOR_MAX_ANALOG_SENSITIVITY);
                int ceiling = Math.max(iso, analog == null ? isoRange.getUpper() : Math.min(analog, isoRange.getUpper()));
                long light = (long)iso * exposure, most = (long)ceiling * period;
                long shortened = Math.max(1, (light + most - 1) / most) * period;
                if (shortened <= exposure) {
                    iso = (int)Math.min(ceiling, Math.round((double)light / shortened));
                    exposure = shortened;
                }
            }
            return new StillExposure(exposure, duration, result.get(CaptureResult.SENSOR_TIMESTAMP), iso, boostRange == null ? null : boost,
                    exposureRange, isoRange, boostRange);
        }

        /** The explicit bracket's variation of this still; null when the device range cannot hold it. */
        StillExposure vary(SettingsBracket.Variant variant) {
            long varied = exposure * variant.periods;
            if (!exposureRange.contains(varied)) return null;
            long gain = Math.round((double)iso * (1 << variant.evSteps) / variant.periods);
            return new StillExposure(varied, Math.max(frameDuration, varied), sourceTimestamp,
                    (int)Math.max(isoRange.getLower(), Math.min(isoRange.getUpper(), gain)), boost,
                    exposureRange, isoRange, boostRange);
        }

        java.util.Map<String, Object> requested(SettingsBracket.Variant variant) {
            java.util.Map<String, Object> map = new java.util.LinkedHashMap<>();
            map.put("exposure_ns", exposure); map.put("iso", iso); map.put("frame_ns", frameDuration);
            if (boost != null) map.put("post_raw_boost", boost);
            if (variant != null && variant.noiseReduction != null) map.put("noise_reduction", variant.noiseReduction);
            if (variant != null && variant.edge != null) map.put("edge", variant.edge);
            if (variant != null && variant.jpegQuality != null) map.put("jpeg_quality", variant.jpegQuality);
            return map;
        }

        void apply(CaptureRequest.Builder request) {
            request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
            request.set(CaptureRequest.CONTROL_AWB_LOCK, true);
            request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, exposure);
            request.set(CaptureRequest.SENSOR_FRAME_DURATION, frameDuration);
            request.set(CaptureRequest.SENSOR_SENSITIVITY, iso);
            if (boost != null) request.set(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST, boost);
        }

        boolean matches(StillResult actual, long timestamp) {
            // Camera2 permits only downward rounding of exposure, ISO and post-RAW gain.
            return actual != null && actual.timestamp != null && actual.timestamp == timestamp && timestamp >= sourceTimestamp
                    && Integer.valueOf(CaptureRequest.CONTROL_AE_MODE_OFF).equals(actual.aeMode)
                    && Boolean.TRUE.equals(actual.awbLocked)
                    && actual.exposure != null && exposureRange.contains(actual.exposure) && actual.exposure <= exposure
                    && actual.iso != null && isoRange.contains(actual.iso) && actual.iso <= iso
                    && (boost == null || (actual.boost != null && boostRange.contains(actual.boost) && actual.boost <= boost));
        }
    }

    /** The native Image is closed before these bytes wait for the matching result. */
    private static final class PendingJpeg {
        final byte[] bytes;
        final int width, height;
        final long timestamp;
        PendingJpeg(byte[] bytes, int width, int height, long timestamp) {
            this.bytes = bytes; this.width = width; this.height = height; this.timestamp = timestamp;
        }
    }

    private final Context context;
    private final Handler handler;
    private final Callback callback;
    private final Stillness stillness;
    private final Mode mode;
    private final Executor inputWorker;
    private final ZslInputTransfer.Factory inputFactory;
    private CaptureVideoRecording.Options videoOptions;
    private final CaptureVideoRecording.Factory videoFactory;
    private CaptureVideoRecording video;
    private boolean videoPreparing;
    private String videoCameraId;
    private Size videoJpegSize;
    private boolean videoSceneObserved;
    private VideoClose videoClose;
    private final List<Runnable> closeCallbacks = new ArrayList<>();
    private final class VideoClose {
        final CaptureVideoRecording recording;
        final long token;
        final Runnable deadline;
        boolean resourcesClosed, cameraClosed, finishQueued, recorderFinished;
        VideoClose(CaptureVideoRecording recording, long token, boolean cameraClosed) {
            this.recording = recording; this.token = token; this.cameraClosed = cameraClosed;
            deadline = () -> {
                if (videoClose != this) return;
                recording.abort("camera_or_recorder_close_timeout", GlassCamera.this::previewFailed);
                previewFailed("video evaluation close barrier unresolved");
                unknown = true;
                recording.finish(false, "close_timeout", ignored -> {
                    if (videoClose != this) return;
                    recorderFinished = true;
                    completeCloseCallbacks();
                });
            };
        }
    }
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
    private boolean stillResultFinished;
    private PendingJpeg pendingJpeg;
    private CameraCharacteristics manualExposureCamera;
    private StillExposure meteringStillExposure, stillExposure;
    private final CameraDiagnostics.Framing framing = new CameraDiagnostics.Framing();
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
    private long statusAt, statusFrameAt, statusWorkMillis, statusGapMillis;
    private long previewFrameDoneAt, previewFrameWorkMillis;
    private byte[] previewLuma;
    private int statusFrames;
    private boolean capturePending;
    private CaptureSurface.FuturePageListener futurePages;
    private CaptureSurface.FuturePageListener activeFuturePage;
    private int futureCapacity;
    private long sceneStartTimestamp;
    private long futureSceneSequence;
    private long futureSceneStartTimestamp;
    private long futureSceneEndTimestamp;
    private long waitingStableScene;
    // Nonpersistent opt-in. A monotonic observed scene is never revived by an A-B-A return.
    private final String cameraRun = java.util.UUID.randomUUID().toString();
    private volatile boolean nativeSelection;
    private volatile CaptureSurface.NativeScene selectionScene;
    private boolean selectionAttempted;
    private CaptureSurface.NativeAlternative activeAlternative;
    private CaptureSurface.NativeScene alternativeScene;
    // Explicit, nonpersistent settings comparison. Its stills never reach the session callback.
    private volatile SettingsBracket bracket;
    private StillExposure bracketExposure;
    private SettingsBracket.Variant bracketVariant;
    private long bracketDeadline;
    private TotalCaptureResult stillTotal;
    private final Runnable bracketStep = this::bracketStep;
    private final CaptureSurface.NativeAlternative bracketShot = new CaptureSurface.NativeAlternative() {
        @Override public boolean onStarting() { return true; }
        @Override public void onSkipped() { handler.postDelayed(bracketStep, 100); }
        @Override public void onOriginal(byte[] jpeg, CaptureProvenance source, boolean sameScene) {
            SettingsBracket set = bracket;
            if (set == null || !set.running()) return;
            java.util.Map<String, Object> details = new java.util.LinkedHashMap<>();
            details.put("sha256", source == null ? null : source.jpegSha256);
            details.put("requested", stillExposure == null ? null : stillExposure.requested(bracketVariant));
            details.put("actual", reported(stillTotal));
            details.put("metadata_matched", stillExposure != null && stillResult != null
                    && stillExposure.matches(stillResult, source == null || source.imageTimestampNanos == null ? -1 : source.imageTimestampNanos));
            details.put("same_scene", captureScene == pageChange.sequence() && captureSceneEnd == Long.MAX_VALUE);
            if (set.saved(jpeg, details)) handler.postDelayed(bracketStep, 100);
        }
    };
    private long captureStream, captureScene, captureSceneStart, captureSceneEnd;
    private boolean captureSceneUncertain;
    private final List<Runnable> futureStops = new ArrayList<>();
    private CameraReadiness metering;
    private boolean realtimeTimestamps;
    private long meteringSensorTimestamp;
    private long lastMeteringSensorTimestamp;
    private long meteringExposureNanos;
    private long previewSensorTimestamp;
    private long lastPreviewSensorTimestamp;
    private boolean autoFocusStarted;
    private long autoFocusSensorTimestamp;
    private long autoFocusCycle;
    private PageChange previewMotion = new PageChange();
    // AGENT_APPROVED=1: opt-in comparison only; never changes the saved JPEG bounds.
    private final boolean paperGeometryEvaluation;
    private PaperGeometry.Tracker paperTracker;
    private PaperExposure paperExposure;
    private final Runnable prepareTimeout = this::prepareExpired;
    private final Runnable inputReleaseTimeout = () -> previewFailed("ZSL input release timeout");

    private final Runnable timeout = () -> {
        if (pendingJpeg != null) deliverJpeg();
        else fail("CAMERA TIMEOUT");
    };

    GlassCamera(Context context, Handler handler, Callback callback) {
        this(context, handler, callback, Mode.NATIVE_STILL);
    }

    GlassCamera(Context context, Handler handler, Callback callback, Mode mode) {
        this(context, handler, callback, mode, null, null);
    }

    GlassCamera(Context context, Handler handler, Callback callback, Mode mode,
                Executor worker, ZslInputTransfer.Factory factory) {
        this(context, handler, callback, mode, worker, factory,
                CaptureVideoRecording.Options.defaults("unbound-evaluation", 0, 270), null);
    }

    GlassCamera(Context context, Handler handler, Callback callback, Mode mode,
                Executor worker, ZslInputTransfer.Factory factory,
                CaptureVideoRecording.Options videoOptions, CaptureVideoRecording.Factory videoFactory) {
        this(context, handler, callback, mode, worker, factory, videoOptions, videoFactory, false);
    }

    GlassCamera(Context context, Handler handler, Callback callback, Mode mode,
                Executor worker, ZslInputTransfer.Factory factory,
                CaptureVideoRecording.Options videoOptions, CaptureVideoRecording.Factory videoFactory,
                boolean paperGeometryEvaluation) {
        if (paperGeometryEvaluation && mode != Mode.NATIVE_STILL)
            throw new IllegalArgumentException("paper geometry comparison requires native stills");
        this.context = context;
        this.handler = handler;
        this.callback = callback;
        this.mode = mode;
        inputWorker = worker;
        inputFactory = factory;
        this.videoOptions = videoOptions;
        this.videoFactory = videoFactory;
        this.paperGeometryEvaluation = paperGeometryEvaluation;
        stillness = new Stillness(context);
    }

    void videoGeneration(long next) {
        if (mode != Mode.VIDEO_EVALUATION) return;
        handler.post(() -> {
            if (videoOptions.generation == next) return;
            videoOptions = videoOptions.generation(next);
            if (video != null || videoClose != null) previewFailed("video evaluation generation changed");
        });
    }

    boolean videoEvaluation() { return mode == Mode.VIDEO_EVALUATION; }
    boolean paperGeometryEvaluation() { return paperGeometryEvaluation; } // AGENT_APPROVED=1

    void nativeSelection(boolean enabled) {
        if (enabled && (mode != Mode.NATIVE_STILL || bracket != null))
            throw new IllegalArgumentException("native selection requires native stills");
        nativeSelection = enabled;
        stillness.retainMeasurements(enabled || bracket != null);
        if (!enabled) selectionScene = null;
    }

    /** Explicit comparison launch only. The extra stills are private files, never pages. */
    void settingsBracket(boolean enabled) {
        if (enabled && (mode != Mode.NATIVE_STILL || paperGeometryEvaluation || nativeSelection))
            throw new IllegalArgumentException("settings bracket requires ordinary native stills");
        bracket = enabled ? new SettingsBracket(context.getFilesDir(), cameraRun) : null;
        stillness.retainMeasurements(enabled || nativeSelection);
    }

    boolean settingsBracket() { return bracket != null; }

    private static java.util.Map<String, Object> reported(CaptureResult result) {
        java.util.Map<String, Object> map = new java.util.LinkedHashMap<>();
        if (result == null) return map;
        map.put("sensor_timestamp_ns", result.get(CaptureResult.SENSOR_TIMESTAMP));
        map.put("exposure_ns", result.get(CaptureResult.SENSOR_EXPOSURE_TIME));
        map.put("iso", result.get(CaptureResult.SENSOR_SENSITIVITY));
        map.put("frame_ns", result.get(CaptureResult.SENSOR_FRAME_DURATION));
        map.put("post_raw_boost", result.get(CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST));
        map.put("ae_mode", result.get(CaptureResult.CONTROL_AE_MODE));
        map.put("ae_state", result.get(CaptureResult.CONTROL_AE_STATE));
        map.put("noise_reduction", result.get(CaptureResult.NOISE_REDUCTION_MODE));
        map.put("edge", result.get(CaptureResult.EDGE_MODE));
        Byte quality = result.get(CaptureResult.JPEG_QUALITY);
        map.put("jpeg_quality", quality == null ? null : (int)quality);
        map.put("scene_flicker", result.get(CaptureResult.STATISTICS_SCENE_FLICKER));
        return map;
    }

    /** After an ordinary still of a manual-exposure camera: the same scene again, one setting changed each time. */
    private void bracketBegin(CaptureProvenance source, boolean associationResolved) {
        SettingsBracket set = bracket;
        if (set == null || closed || unknown || manualExposureCamera == null || stillExposure == null || source == null) return;
        java.util.Map<String, Object> base = new java.util.LinkedHashMap<>();
        base.put("sha256", source.jpegSha256);
        base.put("requested", stillExposure.requested(null));
        base.put("actual", reported(stillTotal));
        base.put("metadata_matched", associationResolved);
        if (!set.begin(captureScene, SettingsBracket.variants(
                manualExposureCamera.get(CameraCharacteristics.NOISE_REDUCTION_AVAILABLE_NOISE_REDUCTION_MODES),
                manualExposureCamera.get(CameraCharacteristics.EDGE_AVAILABLE_EDGE_MODES)), base)) return;
        bracketDeadline = SystemClock.elapsedRealtime() + SettingsBracket.SET_DEADLINE_MILLIS;
        handler.removeCallbacks(bracketStep);
        handler.postDelayed(bracketStep, 100);
    }

    /** One request in flight; a turned page, a busy camera or the deadline ends the set, never a forced shot. */
    private void bracketStep() {
        SettingsBracket set = bracket;
        if (set == null || !set.running()) return;
        long now = SystemClock.elapsedRealtime();
        String end = closed || unknown ? "camera_closed_or_unknown"
                : pageChange.sequence() != set.scene() || pageChange.ready(now) ? "scene_changed"
                : now > bracketDeadline ? "not_ready_before_deadline" : null;
        if (end != null) { set.end(end); return; }
        if (capturePending || activeFuturePage != null || activeAlternative != null || (generation > 0 && !settled)
                || !cameraReady() || !stillness.readyNow()) { handler.postDelayed(bracketStep, 100); return; }
        SettingsBracket.Variant variant = set.peek();
        if (variant == null) { set.end("complete"); return; }
        StillExposure varied = meteringStillExposure == null ? null : meteringStillExposure.vary(variant);
        if (varied == null) { set.skip("outside_device_range"); handler.post(bracketStep); return; }
        bracketExposure = varied; bracketVariant = variant;
        activeAlternative = bracketShot; alternativeScene = null; capturePending = true;
        captureOnHandler();
    }

    CaptureSurface.NativeScene nativeSelectionScene(CaptureProvenance source) {
        CaptureSurface.NativeScene scene = selectionScene;
        return scene != null && scene.matches(source) && isNativeSelectionSceneCurrent(scene) ? scene : null;
    }

    boolean isNativeSelectionSceneCurrent(CaptureSurface.NativeScene scene) {
        return nativeSelection && scene != null && scene.equals(selectionScene);
    }

    /** Never await/prepare an optional shot: the next-page observer and current readings take priority. */
    void requestNativeAlternative(CaptureSurface.NativeScene scene, CaptureSurface.NativeAlternative result) {
        handler.post(() -> {
            if (!isNativeSelectionSceneCurrent(scene) || selectionAttempted) { result.onSkipped(); return; }
            selectionAttempted = true;
            if (capturePending || activeFuturePage != null || pageReady != null
                    || pageChange.sequence() != scene.sequence() || pageChange.ready(SystemClock.elapsedRealtime())
                    || !cameraReady() || !stillness.readyNow()) { result.onSkipped(); return; }
            if (!result.onStarting() || !isNativeSelectionSceneCurrent(scene)
                    || !cameraReady() || !stillness.readyNow()) { result.onSkipped(); return; }
            activeAlternative = result;
            alternativeScene = scene;
            capturePending = true;
            captureOnHandler();
        });
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

    void resetPages() { handler.post(() -> {
        selectionScene = null;
        pageChange = new PageChange();
        if (paperGeometryEvaluation) paperTracker = new PaperGeometry.Tracker();
    }); }

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
            if (mode == Mode.VIDEO_EVALUATION) {
                previewRequested = false; pageReady = null;
                if (!capturePending && activeFuturePage == null) stopPreview();
            }
            if (activeFuturePage == null && activeAlternative == null && inputIdle()) idle.run(); else futureStops.add(idle);
        });
    }

    private void futureIdle() {
        if (mode == Mode.VIDEO_EVALUATION && !previewRequested && !capturePending
                && activeFuturePage == null && video != null) stopPreview();
        if (activeFuturePage != null || activeAlternative != null || !inputIdle()) return;
        List<Runnable> idle = new ArrayList<>(futureStops);
        futureStops.clear();
        for (Runnable ready : idle) ready.run();
    }

    private boolean inputIdle() {
        if (mode == Mode.VIDEO_EVALUATION) return video == null && videoClose == null;
        return mode != Mode.ZSL_EVALUATION_YUV || (zslCloseComplete && (inputTransfer == null || inputTransfer.idle()));
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
            selectionScene = null;
            previewRequested = false;
            pageReady = null;
            futurePages = null;
            if (!capturePending) { stillness.cancel(); stopPreview(); }
        });
    }

    /** Prepare YUV and the full-size JPEG in the same session, retaining metered focus. */
    @RequiresPermission(Manifest.permission.CAMERA)
    private void startPreview() {
        if (!previewRequested || closed || unknown || previewReader != null || previewClosing || zslClosing || videoClose != null || videoPreparing
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
            if (mode == Mode.VIDEO_EVALUATION && video == null) {
                videoCameraId = id; videoJpegSize = jpegSize;
                videoSceneObserved = false;
                videoPreparing = true;
                video = videoFactory == null
                        ? new CaptureVideoRecording(context.getFilesDir(), handler, videoOptions)
                        : new CaptureVideoRecording(context.getFilesDir(), handler, videoOptions, inputWorker, videoFactory);
                CaptureVideoRecording pending = video;
                pending.comparisonTransferOrigin(callback.comparisonVideoOrigin(videoOptions));
                pending.prepare(characteristics, jpegSize, () -> {
                    videoPreparing = false;
                    if (video == pending && token == previewGeneration && !closed && !unknown && previewRequested) startPreview();
                }, reason -> { videoPreparing = false; if (video == pending) previewFailed(reason); });
                return;
            }
            if (mode == Mode.VIDEO_EVALUATION && (!id.equals(videoCameraId) || !jpegSize.equals(videoJpegSize)))
                throw new IllegalStateException("video evaluation camera identity changed during prepare");
            metering = new CameraReadiness(characteristics.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES),
                    characteristics.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE),
                    characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES));
            manualExposureCamera = mode == Mode.NATIVE_STILL && metering.afMode == CaptureRequest.CONTROL_AF_MODE_OFF
                    && StillExposure.supported(characteristics) ? characteristics : null;
            realtimeTimestamps = Integer.valueOf(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME)
                    .equals(characteristics.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE));
            meteringStillExposure = null;
            paperTracker = paperGeometryEvaluation ? new PaperGeometry.Tracker() : null;
            paperExposure = paperGeometryEvaluation && metering.afMode == CaptureRequest.CONTROL_AF_MODE_OFF
                    ? PaperExposure.create(characteristics, size, token) : null;
            previewMotion = new PageChange();
            pageChange.restartStream();
            quietLevel = -1;
            previewAt = 0;
            previewDisplayAt = 0;
            meteringSensorTimestamp = 0;
            lastMeteringSensorTimestamp = 0;
            meteringExposureNanos = 0;
            previewSensorTimestamp = 0;
            lastPreviewSensorTimestamp = 0;
            sceneStartTimestamp = 0;
            autoFocusStarted = false;
            autoFocusSensorTimestamp = 0;
            lastJpegSensorTimestamp = 0;
            CameraDiagnostics.capabilities(generation + 1, characteristics, jpegSize);
            yuvStill = mode == Mode.NATIVE_STILL && !yuvStillRefused && Arrays.asList(sizes).contains(jpegSize);
            encodingStill = false;
            reader = ImageReader.newInstance(jpegSize.getWidth(), jpegSize.getHeight(),
                    yuvStill ? ImageFormat.YUV_420_888 : ImageFormat.JPEG, 1);
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
                                    CaptureRequest.Builder request = opened.createCaptureRequest(mode == Mode.VIDEO_EVALUATION
                                            ? CameraDevice.TEMPLATE_RECORD : CameraDevice.TEMPLATE_PREVIEW);
                                    request.addTarget(previewReader.getSurface());
                                    if (mode == Mode.VIDEO_EVALUATION) addVideoTarget(request);
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
                                    if (mode == Mode.VIDEO_EVALUATION) {
                                        CaptureVideoRecording activeVideo = video;
                                        activeVideo.start(() -> {}, reason -> { if (video == activeVideo) previewFailed(reason); });
                                    }
                                } catch (CameraAccessException | RuntimeException error) { previewFailed(); }
                            }
                            @Override public void onConfigureFailed(CameraCaptureSession failed) {
                                failed.close();
                                if (token != previewGeneration) return;
                                if (yuvStill && !(generation > 0 && !settled)) {
                                    // Preview with full-size YUV is not a guaranteed pair on a LIMITED camera:
                                    // open again with the JPEG on a session of its own.
                                    Log.w(TAG, "preview with full-size YUV refused; the still keeps its own JPEG session");
                                    yuvStillRefused = true;
                                    release();
                                    return;
                                }
                                previewFailed(mode == Mode.VIDEO_EVALUATION
                                        ? "video evaluation exact YUV/MAX-JPEG/recorder session refused" : "camera YUV/JPEG session refused");
                            }
                        };
                        previewSessionCallback = sessionCallback;
                        stillSession = false;
                        // A camera opened again after the wearer's pause starts its exposure over too. The first
                        // page of a session has no earlier photo to be mistaken for and is observed at once.
                        resumeSettlingSince = pageChange.hasCapturedPage() ? Math.max(1, SystemClock.elapsedRealtime()) : 0;
                        if (mode == Mode.ZSL_EVALUATION_YUV) {
                            opened.createReprocessableCaptureSession(new InputConfiguration(jpegSize.getWidth(), jpegSize.getHeight(),
                                    ImageFormat.YUV_420_888), Arrays.asList(previewReader.getSurface(),
                                    zslReader.getSurface(), reader.getSurface()), sessionCallback, handler);
                        } else if (mode == Mode.VIDEO_EVALUATION) {
                            List<Surface> outputs = Arrays.asList(previewReader.getSurface(), reader.getSurface(), video.surface());
                            List<OutputConfiguration> configuration = new ArrayList<>();
                            for (Surface output : outputs) configuration.add(new OutputConfiguration(output));
                            SessionConfiguration exact = new SessionConfiguration(SessionConfiguration.SESSION_REGULAR,
                                    configuration, handler::post, sessionCallback);
                            try {
                                if (!opened.isSessionConfigurationSupported(exact)) {
                                    video.sessionSupport("unsupported_exact_configuration");
                                    previewFailed("video evaluation exact session unsupported"); return;
                                }
                            } catch (UnsupportedOperationException unavailable) {
                                video.sessionSupport("unknown_query_not_supported");
                                previewFailed("video evaluation exact session support unknown"); return;
                            }
                            video.sessionSupport("advertised_supported_not_throughput_verified");
                            opened.createCaptureSession(outputs, sessionCallback, handler);
                        } else {
                            // With the full-size YUV still, one session for both. Otherwise the preview alone:
                            // on firmware 1.29.013 a session holding the JPEG output beside any other output
                            // never returns the still (see requestStill), so the JPEG has its own.
                            opened.createCaptureSession(yuvStill ? Arrays.asList(previewReader.getSurface(), reader.getSurface())
                                    : Collections.singletonList(previewReader.getSurface()), sessionCallback, handler);
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
                    previewClosed(token);
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException | OutOfMemoryError error) { previewFailed(); }
    }

    private void previewFrame(ImageReader source, long token) {
        // A queued notification from a closed reader must not fail a newer healthy stream.
        if (source != previewReader || token != previewGeneration || closed || unknown) return;
        // Leave this thread free for as long as the last frame took before handling another one. Handled
        // back to back, slow frames kept the metering results and gyro readings queued behind them until
        // they were no longer fresh: on 2026-11-11 the glasses took no still in 143 s (`metered=false`).
        long arrived = SystemClock.elapsedRealtime();
        if (arrived >= previewFrameDoneAt && arrived - previewFrameDoneAt < previewFrameWorkMillis) {
            // Return the waiting buffers: a full reader is what makes the HAL drop frames.
            try (Image skipped = source.acquireLatestImage()) { return; }
            catch (RuntimeException ignored) { return; }
        }
        long s0 = System.nanoTime(), s1 = s0, s2 = s0, s3 = s0, s4 = s0, s5 = s0, s6 = s0;
        try (Image image = source.acquireLatestImage()) {
            s1 = s2 = s3 = s4 = s5 = s6 = System.nanoTime();
            if (image == null || token != previewGeneration || closed) return;
            long now = SystemClock.elapsedRealtime();
            long timestamp = image.getTimestamp();
            if (timestamp <= 0 || timestamp <= lastPreviewSensorTimestamp || !currentCameraTimestamp(timestamp)) {
                // Do not refresh readiness or invent a turn from an old/invalid buffer.
                previewSensorTimestamp = 0;
                selectionScene = null;
                captureSceneUncertain = true;
                return;
            }
            lastPreviewSensorTimestamp = timestamp;
            if (resumeSettlingSince != 0) {
                // A fresh converged result of the restarted stream, or the limit: then frames count again.
                boolean steady = metering != null && metering.ready(now) && meteringExposureNanos > 0;
                if (!steady && now - resumeSettlingSince < RESUME_SETTLE_LIMIT_MILLIS) return;
                Log.i(TAG, "preview_resumed settled=" + steady + " after_ms=" + (now - resumeSettlingSince)
                        + " exposure_ns=" + meteringExposureNanos);
                resumeSettlingSince = 0;
            }
            previewSensorTimestamp = timestamp;
            previewAt = realtimeTimestamps ? timestamp / 1_000_000L : now;
            // Once per frame: on the device each call is a native call, and the loops below made about
            // 150,000 of them a frame (145-285 ms measured on the glasses on 2026-11-12, 0.5 ms on a PC).
            int imageWidth = image.getWidth(), imageHeight = image.getHeight();
            Image.Plane luma = image.getPlanes()[0];
            // Copy the plane once. Reading the camera's own buffer a pixel at a time cost about 170 ms a frame
            // on the glasses even when compiled (0.5 ms for the same work on a PC); every reader below
            // keeps the plane's offsets, now counted from the start of the copy.
            ByteBuffer plane = luma.getBuffer().duplicate(); // the copy must not move the plane's own position
            int planeBytes = plane.remaining();
            if (previewLuma == null || previewLuma.length < planeBytes) previewLuma = new byte[planeBytes];
            plane.get(previewLuma, 0, planeBytes);
            ByteBuffer pixels = ByteBuffer.wrap(previewLuma, 0, planeBytes);
            int row = luma.getRowStride(), step = luma.getPixelStride();
            int origin = pixels.position(); // AGENT_APPROVED=1: same Y-plane origin for observation, guide and preview.
            s2 = s3 = s4 = s5 = s6 = System.nanoTime();
            byte[] thumbnail = new byte[32 * 24];
            for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++) {
                thumbnail[y * 32 + x] = pixels.get(origin + y * imageHeight / 24 * row + x * imageWidth / 32 * step);
            }
            // While a still is in flight its exposure leaks into the preview: on the glasses the frames 0.55-0.9 s
            // after the request rose from a mean of 70 to 155 and fell back, each reported as converged, and
            // each was counted as a page turn, so one unmoving page was taken three times (2026-11-12). Such a
            // frame is dropped; any other frame during the still stays page evidence, a turned page included.
            int level = 0;
            for (byte value : thumbnail) level += value & 255;
            level /= thumbnail.length;
            if (generation > 0 && !settled) {
                if (quietLevel >= 0 && level * 10 > quietLevel * 13 + 80) return;
            } else quietLevel = level;
            long previousScene = pageChange.sequence();
            if (sceneStartTimestamp == 0) sceneStartTimestamp = timestamp;
            s3 = s4 = s5 = s6 = System.nanoTime();
            pageChange.observeFrame(thumbnail, pixels, imageWidth, imageHeight, row, step, timestamp, now);
            s4 = s5 = s6 = System.nanoTime();
            framing.fine(pageChange.fineStatus(), imageWidth, imageHeight);
            if (video != null && (!videoSceneObserved || previousScene != pageChange.sequence())) {
                videoSceneObserved = true; video.scene(pageChange.sequence(), timestamp, now);
            }
            if (previousScene != pageChange.sequence()) {
                // Why a page turn was counted: without this a retaken page cannot be told from a moved scene.
                Log.i(TAG, "page_change scene=" + pageChange.sequence() + " " + pageChange.lastChange()
                        + " exposure_ns=" + meteringExposureNanos + " fine=" + pageChange.fineStatus());
                sceneStartTimestamp = timestamp;
                if (generation == 0 || settled) {
                    // Before shutter issue, the next page needs its own AUTO/MACRO focus cycle.
                    autoFocusStarted = false;
                    autoFocusSensorTimestamp = 0;
                }
                selectionScene = null;
                if (capturePending && captureSceneEnd == Long.MAX_VALUE) captureSceneEnd = timestamp;
                if (activeFuturePage != null && futureSceneEndTimestamp == Long.MAX_VALUE) {
                    futureSceneEndTimestamp = timestamp;
                }
                if (futurePages != null && waitingStableScene != 0
                        && waitingStableScene != futureSceneSequence) futurePageMissed();
                waitingStableScene = 0;
            }
            previewMotion.observe(thumbnail, now);
            PaperGeometry.Box paper = paperTracker == null ? null : paperTracker.observe(
                    PaperGeometry.candidate(pixels, imageWidth, imageHeight, row, step), pageChange.sequence());
            if (paperExposure != null && paperExposure.propose(paper, pageChange.sequence())) {
                // A new scene/region must receive its own actual, fresh AE result before shutter.
                meteringSensorTimestamp = 0; meteringExposureNanos = 0;
                try {
                    CaptureRequest.Builder request = previewDevice.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                    request.addTarget(previewReader.getSurface()); applyMetering(request);
                    previewSession.setRepeatingRequest(request.build(), previewResults(token, false), handler);
                } catch (CameraAccessException | RuntimeException failure) {
                    previewFailed("paper comparison metering unavailable"); return;
                }
            }
            // AUTO/MACRO must start before pageReady can require a focused result.
            if (capturePending || ((pageReady != null || futurePages != null) && pageChange.ready(now))) startAutoFocus();
            // Observe every received frame; only the HUD bitmap is limited to 10 Hz.
            s5 = s6 = System.nanoTime();
            if (now - previewDisplayAt >= 100) {
                previewDisplayAt = now;
                int width = Math.min(320, imageWidth), height = Math.max(1, width * imageHeight / imageWidth);
                int[] display = new int[width * height];
                for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                    int gray = pixels.get(origin + y * imageHeight / height * row + x * imageWidth / width * step) & 255;
                    display[y * width + x] = 0xFF000000 | (gray << 8);
                }
                Bitmap frame = Bitmap.createBitmap(display, width, height, Bitmap.Config.RGB_565);
                if (paperGeometryEvaluation) callback.onPreview(frame, paper); else callback.onPreview(frame);
            }
            s6 = System.nanoTime();
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
            previewStatus(now);
        } catch (RuntimeException | OutOfMemoryError error) { previewFailed(); }
        finally {
            long s7 = System.nanoTime();
            long[] steps = {s1 - s0, s2 - s1, s3 - s2, s4 - s3, s5 - s4, s6 - s5, s7 - s6};
            for (int i = 0; i < steps.length; i++) stepNanos[i] = Math.max(stepNanos[i], steps[i]);
            previewFrameDoneAt = SystemClock.elapsedRealtime();
            previewFrameWorkMillis = previewFrameDoneAt - arrived;
        }
    }

    /**
     * One line a second while the preview runs: what the next still waits for, and whether this thread keeps up
     * with the stream (2026-11-11: four device sessions ended without a still and without a recorded reason).
     */
    private void previewStatus(long now) {
        statusFrames++;
        statusWorkMillis = Math.max(statusWorkMillis, SystemClock.elapsedRealtime() - now);
        if (statusFrameAt > 0) statusGapMillis = Math.max(statusGapMillis, now - statusFrameAt);
        statusFrameAt = now;
        if (now - statusAt < 1000) return;
        Log.i(TAG, "preview_status frames=" + statusFrames + " max_work_ms=" + statusWorkMillis
                + " max_gap_ms=" + statusGapMillis + " pending=" + capturePending + " page_ready=" + (pageReady != null)
                + " future=" + (futurePages != null) + " scene=" + pageChange.sequence()
                + " page_still=" + pageChange.ready(now) + " metered=" + meteredFrame(now)
                + " exposure_ns=" + meteringExposureNanos + " motion=" + previewMotion.ready(now)
                + " fine=" + pageChange.fineMotionReady(now) + " gyro=" + stillness.readyNow()
                + " camera_ready=" + cameraReady()
                + " steps_ms acquire/copy/thumb/observe/misc/display/rest=" + stepNanos[0] / 1_000_000 + "/"
                + stepNanos[1] / 1_000_000 + "/" + stepNanos[2] / 1_000_000 + "/" + stepNanos[3] / 1_000_000 + "/"
                + stepNanos[4] / 1_000_000 + "/" + stepNanos[5] / 1_000_000 + "/" + stepNanos[6] / 1_000_000);
        Arrays.fill(stepNanos, 0);
        statusAt = now; statusFrames = 0; statusWorkMillis = 0; statusGapMillis = 0;
    }

    private void futurePageMissed() {
        if (video != null) video.gap("native_future_original_scene_or_capacity_gap");
        CaptureSurface.FuturePageListener observer = futurePages;
        futurePages = null;
        futureCapacity = 0;
        if (observer != null) observer.onPageMissed();
    }

    private void stopPreview() {
        release();
    }

    private void previewClosed(long token) {
        if (videoClose != null && videoClose.token == token) {
            videoClose.cameraClosed = true;
            previewClosing = false; previewOpening = false;
            finishVideoClose(videoClose);
            return;
        }
        if (!previewClosing) return;
        previewClosing = false;
        startPreview();
    }

    /**
     * Ten seconds without stillness and settled exposure. No request has been
     * issued to the camera, so this is a cancelled preparation, not an unknown
     * capture: ending the whole session here cost the wearer every later page.
     */
    private void prepareExpired() {
        if (closed || unknown || !capturePending) return;
        if ((generation > 0 && !settled) || activeAlternative != null
                || mode != Mode.NATIVE_STILL) {
            previewFailed("camera not still or AF/AE not ready");
            return;
        }
        stillness.cancel();
        capturePending = false;
        if (activeFuturePage != null) {
            // The observed scene is unchanged: the next preview frame prepares it again.
            activeFuturePage = null;
            futureCapacity++;
            return;
        }
        callback.onCaptureNotReady();
    }

    private void previewFailed() { previewFailed("preview unavailable"); }

    private void previewFailed(String reason) {
        if (closed || unknown) return;
        if (video != null) video.gap(reason);
        if (generation > 0 && active(generation)) { fail(reason); return; }
        Log.w(TAG, "preview failed: " + reason);
        previewRequested = false;
        previewOpening = false;
        unknown = true;
        selectionScene = null;
        activeAlternative = null;
        alternativeScene = null;
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
                && meteringExposureNanos > 0 && meteredFrame(now) && previewMotion.ready(now) && pageChange.fineMotionReady(now)
                && (manualExposureCamera == null || meteringStillExposure != null)
                && now >= previewAt && now - previewAt <= CameraReadiness.FRESH_MILLIS
                && (mode != Mode.ZSL_EVALUATION_YUV || (inputTransfer != null && inputTransfer.ready() && zslCandidate() != null))
                && (mode != Mode.VIDEO_EVALUATION || (video != null && video.recording()));
    }

    private void inputReleased() {
        if (inputIdle()) handler.removeCallbacks(inputReleaseTimeout);
        futureIdle();
    }

    /** The exposure this still will actually use, from the current session's fresh result only. */
    private long motionExposureNanos() {
        long now = SystemClock.elapsedRealtime();
        long exposure = !closed && !unknown && previewDevice != null && previewSession != null
                && meteredFrame(now) && now >= previewAt
                && now - previewAt <= CameraReadiness.FRESH_MILLIS ? meteringExposureNanos : 0;
        // The manual still, not the preview, is what head motion can blur.
        if (exposure > 0 && meteringStillExposure != null) exposure = Math.min(exposure, meteringStillExposure.exposure);
        if (exposure <= 0 || mode != Mode.ZSL_EVALUATION_YUV) return exposure;
        ZslFrameBuffer.Selection candidate = zslCandidate();
        return candidate == null ? exposure : Math.max(exposure, candidate.result.get(CaptureResult.SENSOR_EXPOSURE_TIME));
    }

    private boolean meteredFrame(long now) {
        // Compare only timestamps from this camera; UNKNOWN timebases are not wall clocks.
        return metering != null && metering.ready(now) && meteringSensorTimestamp > 0
                // A quick turn can finish its quiet interval while the previous page's result is still fresh.
                && meteringSensorTimestamp >= sceneStartTimestamp
                && (!metering.needsTrigger() || (autoFocusStarted && autoFocusSensorTimestamp > 0
                && meteringSensorTimestamp >= autoFocusSensorTimestamp))
                && previewSensorTimestamp > 0 && Math.abs(meteringSensorTimestamp - previewSensorTimestamp)
                <= CameraReadiness.FRESH_MILLIS * 1_000_000L;
    }

    private boolean currentCameraTimestamp(long timestamp) {
        if (!realtimeTimestamps) return true;
        long now = SystemClock.elapsedRealtimeNanos();
        return timestamp <= now && now - timestamp <= CameraReadiness.FRESH_MILLIS * 1_000_000L;
    }

    private CameraCaptureSession.CaptureCallback previewResults(long token, boolean focusTrigger) {
        long focusGeneration = generation;
        long focusCycle = autoFocusCycle;
        return new CameraCaptureSession.CaptureCallback() {
            private boolean current() {
                return token == previewGeneration && !closed && !unknown
                        && (!focusTrigger || (focusGeneration == generation
                        && focusCycle == autoFocusCycle && autoFocusStarted));
            }
            @Override public void onCaptureCompleted(CameraCaptureSession source,
                    CaptureRequest request, TotalCaptureResult result) {
                if (!current() || source != previewSession || result == null) return;
                try {
                    if (!focusTrigger) framing.preview(token, result);
                    if (!focusTrigger && zslFrames != null) zslFrames.result(result);
                    Long timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
                    if (video != null && timestamp != null) video.frame(timestamp, result.getFrameNumber(),
                            result.get(CaptureResult.SCALER_CROP_REGION), result.get(CaptureResult.CONTROL_VIDEO_STABILIZATION_MODE),
                            result.get(CaptureResult.LENS_OPTICAL_STABILIZATION_MODE));
                    if (timestamp == null || timestamp <= 0 || !currentCameraTimestamp(timestamp)) {
                        meteringExposureNanos = 0;
                        meteringSensorTimestamp = 0; return;
                    }
                    if (paperExposure != null && !paperExposure.observe(request, result)) {
                        // Old request revisions cannot refresh, or replace, current-region readiness.
                        if (request.getTag() == paperExposure.stamp) {
                            meteringExposureNanos = 0; meteringSensorTimestamp = 0;
                        }
                        return;
                    }
                    // Fence old LOCKED metadata until this START has reached the native pipeline.
                    if (focusTrigger) autoFocusSensorTimestamp = timestamp;
                    if (timestamp <= lastMeteringSensorTimestamp) return;
                    lastMeteringSensorTimestamp = timestamp;
                    meteringSensorTimestamp = timestamp;
                    Long exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
                    meteringExposureNanos = exposure != null && exposure > 0 ? exposure : 0;
                    meteringStillExposure = manualExposureCamera == null ? null : StillExposure.observe(manualExposureCamera, result);
                    metering.observe(result.get(CaptureResult.CONTROL_AF_STATE),
                            result.get(CaptureResult.CONTROL_AE_STATE), realtimeTimestamps
                                    ? timestamp / 1_000_000L : SystemClock.elapsedRealtime());
                } catch (RuntimeException error) { previewFailed("camera metering unavailable"); }
            }
            @Override public void onCaptureFailed(CameraCaptureSession source,
                    CaptureRequest request, CaptureFailure failure) {
                if (!current()) return;
                // Frames flushed by this class's own session change are not a camera failure.
                if (failure != null && failure.getReason() == CaptureFailure.REASON_FLUSHED) return;
                if (failure != null) Log.w(TAG, "preview frame failed frame=" + failure.getFrameNumber()
                        + " reason=" + failure.getReason() + " image=" + failure.wasImageCaptured());
                // A dropped preview frame only lacks its metering result; the stream and the next result go on.
                // The glasses drop one or two about a second after every stream start (2026-11-11/12), and
                // ending the session for that left the wearer with no photo at all. A still in flight keeps
                // its earlier, stricter handling.
                if (generation > 0 && active(generation)) previewFailed("camera metering failed");
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
        if (paperExposure != null) paperExposure.apply(request);
    }

    /** Camera2 request/result correspondence for one explicitly enabled, fixed-focus comparison. */
    private static final class PaperExposure {
        final Rect active;
        final Size stream;
        final boolean zoomReported, rotateReported;
        Rect crop;
        Stamp stamp;
        private static final class Stamp {
            final long generation, scene, revision;
            final Rect crop;
            final MeteringRectangle region;
            Stamp(long generation, long scene, long revision, Rect crop, MeteringRectangle region) {
                this.generation = generation; this.scene = scene; this.revision = revision;
                this.crop = crop == null ? null : new Rect(crop); this.region = region;
            }
        }
        private PaperExposure(Rect active, Size stream, long generation, boolean zoom, boolean rotate) {
            this.active = new Rect(active); this.stream = stream;
            zoomReported = zoom; rotateReported = rotate;
            stamp = new Stamp(generation, 0, 0, null, null);
        }
        static PaperExposure create(CameraCharacteristics c, Size stream, long generation) {
            Integer max = c.get(CameraCharacteristics.CONTROL_MAX_REGIONS_AE);
            Rect active = c.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
            Rect uncorrected = c.get(CameraCharacteristics.SENSOR_INFO_PRE_CORRECTION_ACTIVE_ARRAY_SIZE);
            int[] distortion = c.get(CameraCharacteristics.DISTORTION_CORRECTION_AVAILABLE_MODES);
            // Do not guess a distortion transform. The inspected fixed-focus HAL has equal arrays.
            if (max == null || max < 1 || active == null || active.isEmpty() || active.left != 0 || active.top != 0
                    || (distortion != null && !active.equals(uncorrected))) return null;
            return new PaperExposure(active, stream, generation,
                    Build.VERSION.SDK_INT >= 30 && c.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE) != null,
                    Build.VERSION.SDK_INT >= 31 && c.get(CameraCharacteristics.SCALER_AVAILABLE_ROTATE_AND_CROP_MODES) != null);
        }
        void apply(CaptureRequest.Builder request) {
            request.setTag(stamp);
            request.set(CaptureRequest.CONTROL_AE_REGIONS, new MeteringRectangle[]{stamp.region != null
                    ? stamp.region : new MeteringRectangle(active, 0)});
        }
        boolean propose(PaperGeometry.Box paper, long scene) {
            MeteringRectangle region = null;
            if (paper != null && crop != null) {
                int[] box = paper.sensorRegion(crop.left, crop.top, crop.right, crop.bottom,
                        stream.getWidth(), stream.getHeight());
                if (box != null) region = new MeteringRectangle(new Rect(box[0], box[1], box[2], box[3]), 1000);
            }
            Rect basis = region == null ? null : crop;
            if (scene == stamp.scene && java.util.Objects.equals(region, stamp.region)
                    && java.util.Objects.equals(basis, stamp.crop)) return false;
            stamp = new Stamp(stamp.generation, scene, stamp.revision + 1, basis, region);
            return true;
        }
        boolean observe(CaptureRequest request, TotalCaptureResult result) {
            if (request == null || request.getTag() != stamp) return false;
            Rect returned = result.get(CaptureResult.SCALER_CROP_REGION);
            Float zoom = Build.VERSION.SDK_INT >= 30 ? result.get(CaptureResult.CONTROL_ZOOM_RATIO) : null;
            Integer rotate = Build.VERSION.SDK_INT >= 31 ? result.get(CaptureResult.SCALER_ROTATE_AND_CROP) : null;
            boolean mapping = returned != null && !returned.isEmpty() && active.contains(returned)
                    && (zoom == null ? !zoomReported : Float.compare(zoom, 1f) == 0)
                    && (rotate == null ? !rotateReported : rotate == CaptureRequest.SCALER_ROTATE_AND_CROP_NONE);
            crop = mapping ? new Rect(returned) : null;
            MeteringRectangle[] regions = result.get(CaptureResult.CONTROL_AE_REGIONS);
            if (regions == null) return false;
            if (stamp.region == null) {
                for (MeteringRectangle region : regions) if (region == null || region.getMeteringWeight() != 0) return false;
                return true;
            }
            return mapping && stamp.crop.equals(returned) && regions.length == 1 && stamp.region.equals(regions[0]);
        }
    }

    private void startAutoFocus() {
        if (closed || unknown || previewSession == null || metering == null || !metering.supported()
                || !metering.needsTrigger() || autoFocusStarted
                || !previewMotion.ready(SystemClock.elapsedRealtime())) return;
        try {
            CaptureRequest.Builder trigger = previewDevice.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            trigger.addTarget(previewReader.getSurface());
            if (mode == Mode.VIDEO_EVALUATION) addVideoTarget(trigger);
            applyMetering(trigger);
            trigger.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_START);
            autoFocusCycle++;
            autoFocusStarted = true;
            previewSession.capture(trigger.build(), previewResults(previewGeneration, true), handler);
        } catch (CameraAccessException | RuntimeException error) { previewFailed("camera autofocus failed"); }
    }

    @RequiresPermission(Manifest.permission.CAMERA)
    private void captureOnHandler() {
        if (closed || unknown || !capturePending || !cameraReady() || (generation > 0 && !settled)) {
            if (activeAlternative != null) {
                CaptureSurface.NativeAlternative skipped = activeAlternative;
                activeAlternative = null; alternativeScene = null; capturePending = false;
                skipped.onSkipped(); futureIdle();
            }
            return;
        }
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
        framing.arm(current, previewGeneration);
        stillResult = null;
        stillTotal = null;
        stillResultFinished = false;
        pendingJpeg = null;
        stillExposure = activeAlternative == bracketShot ? bracketExposure : meteringStillExposure;
        settled = false;
        captureStream = previewGeneration;
        captureScene = pageChange.sequence();
        captureSceneStart = sceneStartTimestamp;
        captureSceneEnd = Long.MAX_VALUE;
        captureSceneUncertain = previewSensorTimestamp <= 0;
        if (activeAlternative == null) {
            selectionScene = null;
            pageChange.consumed();
        }
        startedAtMillis = SystemClock.elapsedRealtime();
        handler.removeCallbacks(prepareTimeout);
        handler.postDelayed(timeout, CAPTURE_TIMEOUT_MILLIS);
        if (mode != Mode.ZSL_EVALUATION_YUV) requestStill(current);
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

    void close() { close(null); }

    void close(Runnable completed) {
        handler.post(() -> {
            if (completed != null) closeCallbacks.add(completed);
            if (pendingJpeg != null) {
                stillResult = null;
                deliverJpeg();
            }
            if (mode == Mode.VIDEO_EVALUATION && video != null && generation > 0 && !settled) {
                video.gap("generation_end_native_original_unresolved");
                unknown = true;
            }
            closed = true;
            if (bracket != null) bracket.end("camera_closed_or_unknown");
            selectionScene = null;
            activeAlternative = null;
            alternativeScene = null;
            settled = true;
            pendingJpeg = null;
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
            if ((videoClose == null || videoClose.recorderFinished)
                    && (mode != Mode.ZSL_EVALUATION_YUV || zslCloseComplete)) completeCloseCallbacks();
        });
    }

    private void completeCloseCallbacks() {
        if (videoClose != null && !videoClose.recorderFinished) return;
        List<Runnable> callbacks = new ArrayList<>(closeCallbacks); closeCallbacks.clear();
        for (Runnable ready : callbacks) ready.run();
    }

    private void requestStill(long current) {
        try {
            CaptureRequest.Builder request =
                    previewDevice.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            request.addTarget(reader.getSurface());
            if (mode == Mode.VIDEO_EVALUATION) {
                addVideoTarget(request);
                video.stillRequested(current);
            }
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
            if (stillExposure != null) stillExposure.apply(request);
            if (activeAlternative == bracketShot && bracketVariant != null) bracketVariant.apply(request);
            CaptureRequest still = request.build();
            stillJpegQuality = activeAlternative == bracketShot && bracketVariant != null && bracketVariant.jpegQuality != null
                    ? bracketVariant.jpegQuality : STILL_JPEG_QUALITY;
            Log.i(TAG, "still_requested gen=" + current + " manual_exposure=" + (stillExposure != null)
                    + " producer=" + (yuvStill ? "yuv_still" : "camera_jpeg"));
            if (mode != Mode.NATIVE_STILL || yuvStill) {
                // capture() takes priority over repeating preview without stopping its next frames.
                previewSession.capture(still, captureCallback(current), handler);
                return;
            }
            // Measured on the glasses on 2026-11-12 (firmware 1.29.013-20261110, glassprobe variants): with the
            // JPEG output in the same session as a YUV preview the still never arrives, at any preview size,
            // with the repeating request stopped, with ZSL off or with a PRIVATE preview added, and the camera
            // provider aborts about 10 s later. A session holding only the JPEG output returned 4 of 4 stills,
            // about 0.8 s to reconfigure and 0.8 s to capture. The 2026-09-27 firmware took both in one session.
            long token = previewGeneration;
            previewDevice.createCaptureSession(Collections.singletonList(reader.getSurface()),
                    new CameraCaptureSession.StateCallback() {
                        @Override public void onConfigured(CameraCaptureSession configured) {
                            if (!active(current) || token != previewGeneration || unknown) { configured.close(); return; }
                            previewSession = configured;
                            stillSession = true;
                            Log.i(TAG, "still_session gen=" + current + " after_ms=" + (SystemClock.elapsedRealtime() - startedAtMillis));
                            try { configured.capture(still, captureCallback(current), handler); }
                            catch (CameraAccessException | RuntimeException error) {
                                fail("capture " + error.getClass().getSimpleName());
                            }
                        }
                        @Override public void onConfigureFailed(CameraCaptureSession failed) {
                            failed.close();
                            if (active(current)) fail("still session refused");
                        }
                    }, handler);
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
                else {
                    stillResultFinished = true;
                    if (pendingJpeg != null) deliverJpeg();
                    else Log.w(TAG, "capture_result gen=" + current + " unavailable; waiting for JPEG");
                }
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
                // Results and ImageReader notifications have independent ordering.
                // The manual still keeps one copied JPEG until this result or the original deadline.
                if (current == generation && !closed && !unknown) {
                    CameraDiagnostics.result(current, result);
                    framing.result(current, captureStream, result);
                }
                if (active(current) && !unknown && !stillResultFinished && source == previewSession) {
                    try { stillResult = result == null ? null : new StillResult(current, result); }
                    catch (RuntimeException unavailable) { stillResult = null; }
                    if (bracket != null) stillTotal = result;
                    stillResultFinished = true;
                    if (pendingJpeg != null) deliverJpeg();
                }
            }
        };
    }

    private void onImageAvailable(ImageReader source) {
        final byte[] jpeg;
        final int width;
        final int height;
        final long sensorTimestamp;
        boolean yuv = false;
        try (Image image = source.acquireNextImage()) {
            // A retained reader must drain late notifications even between requests.
            if (source != reader || generation <= 0 || !active(generation) || pendingJpeg != null || encodingStill) return;
            if (yuvStill && image != null && image.getFormat() == ImageFormat.YUV_420_888) {
                width = image.getWidth();
                height = image.getHeight();
                sensorTimestamp = image.getTimestamp();
                if (sensorTimestamp <= 0) throw new RejectedJpeg("invalid still timestamp");
                if (sensorTimestamp <= lastJpegSensorTimestamp) return;
                if (width <= 0 || height <= 0 || (width & 1) != 0 || (height & 1) != 0) throw new RejectedJpeg("invalid still dimensions");
                Image.Plane[] planes = image.getPlanes();
                if (planes.length != 3) throw new RejectedJpeg("invalid still planes");
                if (stillNv21 == null || stillNv21.length != width * height * 3 / 2) stillNv21 = new byte[width * height * 3 / 2];
                copyNv21(planes, width, height, stillNv21);
                jpeg = null;
                yuv = true;
            } else {
            if (image == null || image.getFormat() != ImageFormat.JPEG) {
                throw new RejectedJpeg("missing JPEG image");
            }
            width = image.getWidth();
            height = image.getHeight();
            sensorTimestamp = image.getTimestamp();
            if (sensorTimestamp <= 0) throw new RejectedJpeg("invalid JPEG timestamp");
            // One JPEG is in flight. A previous original cannot satisfy the next request.
            // Device ZSL may predate preview, so only compare this reader's JPEG timestamps.
            if (mode != Mode.ZSL_EVALUATION_YUV && sensorTimestamp <= lastJpegSensorTimestamp) return;
            if (width <= 0 || height <= 0) throw new RejectedJpeg("invalid JPEG dimensions");
            Image.Plane[] planes = image.getPlanes();
            if (planes.length != 1) throw new RejectedJpeg("invalid JPEG planes");
            ByteBuffer buffer = planes[0].getBuffer();
            int bytes = buffer.remaining();
            if (bytes <= 0 || bytes > MAX_JPEG_BYTES) {
                throw new RejectedJpeg("JPEG byte limit (1..20MiB)");
            }
            jpeg = new byte[bytes];
            buffer.get(jpeg);
            }
        } catch (RejectedJpeg error) {
            fail(error.getMessage());
            return;
        } catch (RuntimeException | OutOfMemoryError error) {
            // A settled JPEG reader still owns the live preview camera while it drains.
            previewFailed("image " + error.getClass().getSimpleName());
            return;
        }
        if (settled || closed) return;
        framing.jpeg(generation, captureStream, sensorTimestamp);
        if (!yuv) {
            pendingJpeg = new PendingJpeg(jpeg, width, height, sensorTimestamp);
            if (stillExposure == null || stillResultFinished) deliverJpeg();
            return;
        }
        // The native Image is closed; encoding leaves this thread to the preview that is still running.
        long current = generation, arrived = SystemClock.elapsedRealtime();
        int quality = stillJpegQuality;
        byte[] nv21 = stillNv21;
        encodingStill = true;
        Executor worker = inputWorker != null ? inputWorker : stillWorker != null ? stillWorker
                : (stillWorker = Executors.newSingleThreadExecutor(task -> {
                    Thread thread = new Thread(task, "glass-still-jpeg"); thread.setDaemon(true); return thread;
                }));
        try {
            worker.execute(() -> {
                byte[] encoded;
                try { encoded = stillEncoder.encode(nv21, width, height, quality); }
                catch (RuntimeException | OutOfMemoryError error) { encoded = null; }
                byte[] done = encoded;
                handler.post(() -> {
                    encodingStill = false;
                    if (!active(current) || pendingJpeg != null) return; // settled while encoding: timeout, failure or close
                    if (done == null || done.length == 0 || done.length > MAX_JPEG_BYTES) { fail("still could not be encoded"); return; }
                    Log.i(TAG, "still_encoded gen=" + current + " bytes=" + done.length + " quality=" + quality
                            + " encode_ms=" + (SystemClock.elapsedRealtime() - arrived));
                    pendingJpeg = new PendingJpeg(done, width, height, sensorTimestamp);
                    if (stillExposure == null || stillResultFinished) deliverJpeg();
                });
            });
        } catch (java.util.concurrent.RejectedExecutionException error) { encodingStill = false; fail("still encoder unavailable"); }
    }

    /** YUV_420_888 planes into NV21: the luma rows, then V and U interleaved. */
    private static void copyNv21(Image.Plane[] planes, int width, int height, byte[] nv21) {
        ByteBuffer luma = planes[0].getBuffer().duplicate();
        int lumaRow = planes[0].getRowStride();
        for (int y = 0; y < height; y++) { luma.position(y * lumaRow); luma.get(nv21, y * width, width); }
        ByteBuffer u = planes[1].getBuffer().duplicate(), v = planes[2].getBuffer().duplicate();
        int row = planes[2].getRowStride(), step = planes[2].getPixelStride();
        if (step == 2 && planes[1].getPixelStride() == 2 && planes[1].getRowStride() == row) {
            // Semi-planar: the V plane's buffer already reads V,U,V,U...; only its last U byte lies in the U plane.
            for (int y = 0; y < height / 2; y++) {
                v.position(y * row);
                v.get(nv21, width * height + y * width, Math.min(width, v.remaining()));
            }
            nv21[nv21.length - 1] = u.get(u.limit() - 1);
            return;
        }
        int uRow = planes[1].getRowStride(), uStep = planes[1].getPixelStride();
        for (int y = 0; y < height / 2; y++) for (int x = 0; x < width / 2; x++) {
            nv21[width * height + y * width + 2 * x] = v.get(y * row + x * step);
            nv21[width * height + y * width + 2 * x + 1] = u.get(y * uRow + x * uStep);
        }
    }

    private void deliverJpeg() {
        if (pendingJpeg == null || settled || closed) return;
        PendingJpeg original = pendingJpeg;
        pendingJpeg = null;
        byte[] jpeg = original.bytes;
        int width = original.width, height = original.height;
        long sensorTimestamp = original.timestamp;
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
        boolean associationResolved = mode == Mode.ZSL_EVALUATION_YUV
                ? outputSource != null && sensorTimestamp == outputSource.timestamp
                : stillExposure == null || (stillExposure.matches(result, sensorTimestamp)
                        && (!realtimeTimestamps || sensorTimestamp <= SystemClock.elapsedRealtimeNanos()));
        CaptureProvenance provenance;
        if (mode != Mode.ZSL_EVALUATION_YUV) {
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
        CaptureVideoRecording receiptVideo = video != null ? video : videoClose == null ? null : videoClose.recording;
        if (receiptVideo != null) receiptVideo.stillDelivered(generation, sensorTimestamp, width, height,
                provenance == null ? "unknown" : provenance.jpegSha256);
        CaptureSurface.FuturePageListener future = activeFuturePage;
        activeFuturePage = null;
        CaptureSurface.NativeAlternative alternative = activeAlternative;
        activeAlternative = null;
        CaptureSurface.NativeScene origin = alternativeScene;
        alternativeScene = null;
        boolean nativeSceneMatched = associationResolved && nativeSelection && mode == Mode.NATIVE_STILL && !captureSceneUncertain
                && captureStream == previewGeneration && captureScene == pageChange.sequence()
                && captureScene > 0 && captureSceneStart > 0 && sensorTimestamp >= captureSceneStart
                && sensorTimestamp < captureSceneEnd && provenance != null && provenance.resultTimestampNanos != null;
        if (alternative != null) {
            alternative.onOriginal(jpeg, provenance, nativeSceneMatched && isNativeSelectionSceneCurrent(origin));
        } else if (future == null) {
            if (nativeSceneMatched) {
                selectionScene = new CaptureSurface.NativeScene(cameraRun, captureStream, captureScene,
                        provenance.captureId, provenance.jpegSha256);
                selectionAttempted = false;
            }
            callback.onCaptured(new Captured(jpeg, width, height, elapsed, provenance, associationResolved));
            bracketBegin(provenance, associationResolved);
        }
        else {
            boolean sceneMatched = associationResolved && sensorTimestamp >= futureSceneStartTimestamp
                    && sensorTimestamp < futureSceneEndTimestamp;
            if (!sceneMatched) { futurePages = null; futureCapacity = 0; }
            if (nativeSceneMatched) {
                selectionScene = new CaptureSurface.NativeScene(cameraRun, captureStream, captureScene,
                        provenance.captureId, provenance.jpegSha256);
                selectionAttempted = false;
            }
            future.onCandidate(jpeg, provenance, sceneMatched);
        }
        // A comparison still is saved with its mismatch journaled; it describes no page and blocks none.
        if (!associationResolved && alternative != bracketShot) previewFailed(mode == Mode.ZSL_EVALUATION_YUV
                ? "ZSL original timestamp mismatch" : "native original exposure metadata unresolved");
        futureIdle();
        resumePreviewSession();
    }

    /** After a still's own session, put the repeating preview back on the same open camera. */
    private void resumePreviewSession() {
        if (!stillSession) return;
        stillSession = false;
        if (closed || unknown || !previewRequested || previewDevice == null || previewReader == null
                || previewSessionCallback == null) return;
        try {
            resumeSettlingSince = Math.max(1, SystemClock.elapsedRealtime());
            previewDevice.createCaptureSession(Collections.singletonList(previewReader.getSurface()),
                    previewSessionCallback, handler);
        } catch (CameraAccessException | RuntimeException error) { previewFailed("preview unavailable after still"); }
    }

    private static final class RejectedJpeg extends RuntimeException {
        RejectedJpeg(String reason) { super(reason); }
    }

    private void fail(String reason) {
        if (settled) {
            return;
        }
        if (pendingJpeg != null) {
            stillResult = null;
            deliverJpeg();
            return;
        }
        settled = true;
        if (video != null) video.gap(reason);
        capturePending = false;
        unknown = true;
        selectionScene = null;
        activeAlternative = null;
        alternativeScene = null;
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
        selectionScene = null;
        // Detach ownership first, then attempt every close even if one fails.
        CameraCaptureSession oldSession = previewSession;
        CameraDevice oldDevice = previewDevice;
        ImageReader oldReader = reader;
        ImageReader oldPreviewReader = previewReader;
        ImageReader oldZslReader = zslReader;
        ZslFrameBuffer oldFrames = zslFrames;
        ZslInputTransfer oldInput = inputTransfer;
        framing.clear();
        long oldPreviewGeneration = previewGeneration;
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
        meteringStillExposure = null;
        manualExposureCamera = null;
        if (oldDevice != null || previewOpening) previewClosing = true;
        if (mode == Mode.VIDEO_EVALUATION) {
            if (videoClose != null) return true;
            if (video == null) return true;
            CaptureVideoRecording oldVideo = video; video = null; videoPreparing = false;
            oldVideo.requestClose(closed ? "generation_end" : unknown ? "camera_unknown" : "capture_end");
            VideoClose ending = new VideoClose(oldVideo, oldPreviewGeneration, oldDevice == null && !previewOpening);
            videoClose = ending;
            handler.postDelayed(ending.deadline, CAPTURE_TIMEOUT_MILLIS);
            Thread closer = new Thread(() -> {
                boolean ok = closeResource(oldSession);
                ok = closeResource(oldDevice) && ok;
                ok = closeResource(oldReader) && ok;
                ok = closeResource(oldPreviewReader) && ok;
                boolean success = ok;
                handler.post(() -> {
                    if (videoClose != ending) return;
                    if (!success) {
                        oldVideo.abort("camera_close_failed", GlassCamera.this::previewFailed);
                        previewFailed("video evaluation camera close failed"); return;
                    }
                    ending.resourcesClosed = true; finishVideoClose(ending);
                });
            }, "glass-video-camera-close");
            closer.setDaemon(true); closer.start();
            return true;
        }
        if (mode == Mode.ZSL_EVALUATION_YUV) {
            if (zslClosing) return true;
            zslClosing = true; zslCloseComplete = false;
            final boolean[] finished = {false, false};
            Runnable completed = () -> {
                if (!finished[0] || !finished[1]) return;
                zslClosing = false; zslCloseComplete = true;
                inputReleased(); startPreview();
                if (closed) completeCloseCallbacks();
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

    private void addVideoTarget(CaptureRequest.Builder request) {
        if (video == null || video.surface() == null) throw new IllegalStateException("video evaluation surface unavailable");
        request.addTarget(video.surface());
        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(videoOptions.fps, videoOptions.fps));
    }

    private void finishVideoClose(VideoClose ending) {
        if (videoClose != ending || !ending.resourcesClosed || !ending.cameraClosed || ending.finishQueued) return;
        ending.finishQueued = true;
        ending.recording.finish(!unknown, closed ? "generation_end" : "capture_end", ok -> {
            if (videoClose != ending) return;
            ending.recorderFinished = true;
            handler.removeCallbacks(ending.deadline);
            if (!ok || unknown) {
                previewFailed("video evaluation finalization unresolved");
                completeCloseCallbacks(); return;
            }
            videoClose = null;
            callback.onVideoSealed(); // Enqueues comparison work only; never waits for network.
            futureIdle(); startPreview();
            completeCloseCallbacks();
        });
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
