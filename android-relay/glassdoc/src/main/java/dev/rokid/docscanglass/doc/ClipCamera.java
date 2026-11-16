package dev.rokid.docscanglass.doc;

import android.Manifest;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.TotalCaptureResult;
import android.hardware.camera2.params.OutputConfiguration;
import android.hardware.camera2.params.SessionConfiguration;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import android.util.Log;
import android.util.Range;
import android.util.Size;

import androidx.annotation.RequiresPermission;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.UUID;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import dev.rokid.docscanrelay.CaptureProvenance;
import dev.rokid.docscanrelay.CaptureSurface;
import dev.rokid.docscanrelay.ClipInbox;

/**
 * One page as a few seconds of frames. At the venue's light a single frame cannot be read however it is exposed
 * (M-24); the phone adds the frames of a clip into one page (M-26). The camera watches through a small preview of
 * the middle of its field (zoom 2); for a page it records that middle at 2016x1512 with a fixed exposure into a clip
 * of its own, and goes back to watching. One frame of the clip travels as the page's JPEG through the path every
 * photo takes; the clip waits in the {@link ClipInbox} under that frame's capture id.
 *
 * <p>Two rules of this camera are kept above everything else here, both measured on the glasses (M-29):
 * <ul>
 * <li>A session is left only after its repeating request was stopped and that session reported itself idle (or
 * 1.5 s passed). Changed at once, frames in flight got no buffer and the camera failed to drain after 16 and after
 * 28 pages. {@link #step} is the only place a session or the camera is changed.</li>
 * <li>Every frame, the clip stream's and the watch preview's, is taken and returned on the frames' thread, which
 * neither opens files nor changes sessions. Left untaken while the camera's thread waited for a session, the camera
 * hung until the glasses were restarted (M-29); with the watch preview on the camera's thread, which opens the
 * clip's file and the codec, the camera could not get a buffer for over a second on 2026-11-16, never drained, and
 * the session could not be changed (M-30). The camera's thread works on a copy of the watch frame.</li>
 * <li>A session is created with the request it will repeat as its session parameters. The frame-rate range is one
 * of this camera's session keys: a session created without it was configured a second time by its first request,
 * after a wait for the device to idle, and on 2026-11-16 that wait ran out after five seconds (camera error 4) on
 * the eleventh clip (M-30).</li>
 * </ul>
 */
final class ClipCamera implements PageCamera {

    static final class Options {
        /** Frames that have to count before a clip ends. */
        int targetFrames = 60;
        long exposureNanos = 30_000_000;
        /**
         * For a scene that the exposure above cannot show bright enough at the gain limit; 0 never uses it. Half the
         * desk's light at 30 ms and a gain of 5.0 read 6.6% wrong although four times the frames were added: the dark
         * paper is lost on its way through the camera's curve and the encoder, not in the noise. Twice the exposure
         * brings it back to the brightness that was read (M-29, M-30).
         */
        long longExposureNanos = 60_000_000;
        /**
         * Asked of the encoder at 30 frames a second, about 1.35 bit a pixel a frame: a page read 3.1% wrong at this
         * and 5.7% at 50 Mbit/s (M-29). At 15 frames a second half of it is asked, the same bits a frame.
         */
        int bitrate = 95_000_000;
        /**
         * The gain, in hundredths, that 30 ms may need before the long exposure is taken instead. 705 is where a
         * page was read at 30 ms (it got 5.0 of it: Zh5, M-29); nothing darker was read at 30 ms.
         */
        int longAboveBoost = 705;
        /** The clockwise turn that makes a page upright, written beside the clip for the phone. */
        int rotationDegrees = 270;
        /**
         * Off: 0 shows no "paper too far" mark. Set, the paper counts as far away while under this share of the
         * watch frame is brighter than the frame's mean. That rule does not measure distance: worn on 2026-11-16 the
         * mark stood for 38 of 67 s of watching while the characters were as large as they had to be (M-31, register
         * 2-24). Kept so that another limit can be tried.
         */
        float farShare = 0f;
        /**
         * The page is too near while the lines of its print lie further apart than this, in px of the recorded
         * frame; 0 shows no mark. The camera's focus is fixed and sharp from 0.4 m: worn on 2026-11-17 pages at 44 px
         * and more were not read at all and pages at 39 to 42 px were (M-43). It measures the print, not the distance:
         * print set wider or closer than that booklet's moves the mark's distance with it (register 2-31).
         */
        float nearLines = 42f;
    }

    /** What the small window shows beside the image; called from the camera's and the frames' threads. */
    interface Marks {
        /**
         * A clip is being recorded and {@code counted} of the {@code wanted} frames have counted: once with 0 when
         * the recording starts, then whenever the count has grown, at most ten times a second. Once more, with
         * {@code recording} false and the final count, when the recording ends. Only frames taken with the head
         * still count, so a count that does not grow is the wearer's cue to hold still: worn on 2026-11-16 (M-33)
         * 5 to 8 frames of 290 were still on three pages and nothing on the display said so.
         */
        void showClipProgress(int counted, int wanted, boolean recording);
        void showFar(boolean far);
        /**
         * The page being looked at is nearer than the camera can focus ({@link Options#nearLines}). Told while
         * watching, twice a second at most; not taken back when a clip starts, so that it still stands over the
         * review of a page recorded that way; taken back when the capture pauses or stops.
         */
        void showNear(boolean near);
    }

    static final int WIDTH = 2016, HEIGHT = 1512, FPS = 30, WATCH_FPS = 15, ISO = 800;
    /** The post-RAW gain is asked in hundredths: 1.0 to 5.0. */
    static final int MIN_BOOST = 100, MAX_BOOST = 500;
    /** The first frames of a clip are still settling to the manual exposure: in the clip, never counted or used. */
    static final int SETTLE_FRAMES = 6;
    /** At the long exposure: 15 frames a second, and the brightness moves for about twelve frames (M-30). */
    static final int LONG_FPS = 15, LONG_SETTLE_FRAMES = 15;
    static final float MAX_SMEAR_PIXELS = 2f;
    /**
     * Written for a frame during whose exposure no reading of the gyroscope reached the app: not known to be still,
     * so never counted, and over any limit the phone applies. Until 2026-11-16 such a frame was written as 0 px,
     * the stillest of all: eight of a worn clip's 296 frames (M-31).
     */
    static final float UNKNOWN_SMEAR = 999f;
    static final long MIN_MILLIS = 1_000, MAX_MILLIS = 10_000, IDLE_TIMEOUT_MILLIS = 1_500, LIGHT_TIMEOUT_MILLIS = 5_000;
    /** How long a clip waits for an exposure that has been measured but has not settled yet. */
    static final long SETTLE_WAIT_MILLIS = 1_500;
    static final int JPEG_QUALITY = 90;
    /** A clip's growing count is reported at most this often. */
    static final long PROGRESS_MILLIS = 100;
    /**
     * A camera that reports an error is closed and opened again, and the page is looked for again, until it has
     * failed this many times with no page between: then the capture fails, as every other failure does at once.
     */
    static final int MAX_CAMERA_FAILURES = 3;
    private static final int MAX_FRAMES = (int) (MAX_MILLIS / 1000) * FPS + FPS;
    private static final int MAX_READINGS = 4096;
    private static final String TAG = "DocScanGlassDoc";
    /** What the session's repeating request is for. */
    private static final int OFF = 0, WATCH = 1, CLIP = 2;
    /** A clip: waiting for the watch preview to measure the light, its session being built, recording, being closed. */
    private static final int WAITING = 0, STARTING = 1, RECORDING = 2, ENDING = 3;

    /** One page's clip, from the request to the page handed over. */
    private static final class Clip {
        final long askedAt = SystemClock.elapsedRealtime();
        int phase = WAITING;
        File file;
        boolean opened;
        int boost, previewIso, previewBoost, fps = FPS, settle = SETTLE_FRAMES, gyroFrames, gyroPartial;
        long previewExposure, exposure;
        // While recording: the frames' thread, under the lock.
        final long[] stamps = new long[MAX_FRAMES];
        final float[] smears = new float[MAX_FRAMES];
        // The gyroscope's readings while it is recorded, written beside the clip: its time and the turn about its
        // three axes (rad/s). About 2200 in the longest clip.
        final long[] turnedAt = new long[MAX_READINGS];
        final float[] turned = new float[3 * MAX_READINGS];
        int readings;
        int frames, counted, dropped, reported;
        long firstAt, shownAt, reportedAt, firstMillis = -1, pageStamp;
        TotalCaptureResult pageResult;
        // After it: the camera's thread.
        long endedAt, backMillis = -1, bytes;
        boolean encoded, back;
        GlassCamera.Captured page;
        String failure;
    }

    private final Context context;
    private final Handler handler;
    private final GlassCamera.Callback callback;
    private final ClipInbox inbox;
    private final ClipEncoder encoder;
    private final Options options;
    private final SensorManager sensors;
    private final Sensor gyroscope;
    private final HeadMotion.Ring turning = new HeadMotion.Ring(512);
    private final SensorEventListener turningListener = new SensorEventListener() {
        @Override public void onSensorChanged(SensorEvent event) {
            if (event.values.length < 3) return;
            float x = event.values[0], y = event.values[1], z = event.values[2];
            turning.add(event.timestamp, (float) Math.sqrt(x * x + y * y + z * z));
            synchronized (lock) { // the frames' thread, under the lock, as the frames themselves
                Clip into = recording;
                if (into != null && into.readings < MAX_READINGS) {
                    int at = into.readings++;
                    into.turnedAt[at] = event.timestamp;
                    into.turned[3 * at] = x; into.turned[3 * at + 1] = y; into.turned[3 * at + 2] = z;
                }
            }
        }

        @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }
    };
    private final Object lock = new Object(); // the clip being recorded, between the frames' thread and the camera's
    private final List<Runnable> closeCallbacks = new ArrayList<>();
    private final Runnable readyTimeout = this::readyNow;
    private final Runnable timer = this::timeUp;
    /** NV21 to JPEG; null when it cannot be encoded. Replaced in tests, which have no codec. */
    GlassCamera.StillEncoder pageEncoder = (nv21, width, height, quality) -> {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream(2 << 20);
        return new android.graphics.YuvImage(nv21, ImageFormat.NV21, width, height, null)
                .compressToJpeg(new Rect(0, 0, width, height), quality, out) ? out.toByteArray() : null;
    };
    private volatile Marks marks;

    // The camera's thread.
    private CameraDevice device;
    private CameraCaptureSession session;
    private ImageReader watchReader;
    private HandlerThread framesThread;
    private Handler frames;
    private Rect crop;
    private boolean wanted, closed, opening, closing, configuring;
    private int running, cameraFailures;
    /** Counts the cameras asked for: a callback of an earlier one is not the present camera's. */
    private int opens;
    /** Counts the sessions asked for: a callback of an earlier one is not the present session's. */
    private int configured;
    private Runnable afterReady, pageReady;
    private PageChange pageChange = new PageChange();
    private Clip clip;
    private long previewExposure, settlingSince, displayAt, statusAt, watchWorkNanos, pageScene;
    private int watchFrames;
    private int previewIso, previewBoost;
    private boolean steady, far;
    /** The watch picture's print, measured on the frames' thread: is it too near, when was it last asked, what did it say. */
    private boolean near;
    private long pitchAt;
    private float lines;
    private final PrintPitch printPitch = new PrintPitch();
    private byte[] watchLuma;
    // The watch frame the camera's thread works on, copied by the frames' thread: under the lock until taken.
    private boolean watchPending;
    private int watchWidth, watchHeight, watchRow, watchStep, watchBytes;
    private long watchStamp;

    // Under the lock.
    private ImageReader clipReader;
    private Clip recording;
    private final ArrayDeque<TotalCaptureResult> recent = new ArrayDeque<>();
    private byte[] nv21, line;

    ClipCamera(Context context, Handler cameraHandler, GlassCamera.Callback callback, ClipInbox inbox,
            ClipEncoder encoder, Options options) {
        this.context = context;
        this.handler = cameraHandler;
        this.callback = callback;
        this.inbox = inbox;
        this.encoder = encoder;
        this.options = options;
        sensors = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        gyroscope = sensors == null ? null : sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
    }

    void marks(Marks shown) { marks = shown; }

    @Override public void awaitNextPage(Runnable ready) {
        handler.post(() -> {
            if (closed) return;
            pageReady = ready;
            wanted = true;
            step();
        });
    }

    @Override public void preview() {
        handler.post(() -> {
            if (closed) return;
            wanted = true;
            step();
        });
    }

    @Override public void resetPages() {
        handler.post(() -> {
            pageChange = new PageChange();
            settlingSince = 0;
        });
    }

    /** One clip of the page in view; its middle frame arrives at the callback as the page. */
    @Override public void captureOnce() {
        handler.post(() -> {
            if (closed || clip != null) return;
            wanted = true;
            clip = new Clip();
            // The clip's exposure and gain are fixed from the preview's automatic exposure, which starts over
            // whenever the preview restarts: only a settled reading is matched. One that does not settle is
            // waited for briefly and then used as it is; with no reading at all nothing is recorded.
            handler.postDelayed(timer, previewExposure > 0 ? SETTLE_WAIT_MILLIS : LIGHT_TIMEOUT_MILLIS);
            step();
            if (running == WATCH && afterReady == null && previewExposure > 0 && steady) begin();
        });
    }

    /**
     * A tap (pause) or a double tap (end). A clip being recorded is ended at once and what it has becomes the
     * page, as a still in flight is kept: thrown away, the page the wearer was looking at was missing from the
     * booklet and an end was left hanging. Only a clip in which no frame has counted yet is deleted, and the
     * session told that nothing was taken. The camera is closed once its session is idle.
     */
    @Override public void pausePreview() {
        handler.post(() -> {
            wanted = false;
            pageReady = null;
            showFar(false);
            showNear(false);
            Clip held = clip;
            boolean counted;
            synchronized (lock) {
                counted = held != null && held.phase == RECORDING && held.counted > 0;
            }
            if (counted) {
                end(held); // goes on to step()
                return;
            }
            if (held != null && held.phase != ENDING) {
                abandon();
                // The page in view was not taken, though it was marked as taken when its clip began: it is seen as
                // new on return. A tap pauses at once from 2026-11-16, so this is no longer only the end of a capture.
                pageChange = new PageChange();
                settlingSince = 0;
                if (!closed) callback.onCaptureNotReady();
            }
            step();
        });
    }

    @Override public void close() { close(null); }

    @Override public void close(Runnable completed) {
        handler.post(() -> {
            if (completed != null) closeCallbacks.add(completed);
            closed = true;
            wanted = false;
            pageReady = null;
            abandon();
            step();
        });
    }

    // A clip is one page: pages turned to meanwhile are not kept, and there is no second still to choose from.
    @Override public boolean supportsFuturePages() { return false; }
    @Override public void observeFuturePages(int capacity, CaptureSurface.FuturePageListener listener) { }
    @Override public void stopFuturePages(Runnable idle) { idle.run(); }
    @Override public CaptureSurface.NativeScene nativeSelectionScene(CaptureProvenance source) { return null; }
    @Override public boolean isNativeSelectionSceneCurrent(CaptureSurface.NativeScene scene) { return false; }
    @Override public void requestNativeAlternative(CaptureSurface.NativeScene scene, CaptureSurface.NativeAlternative result) {
        result.onSkipped();
    }

    private int target() {
        if (closed || !wanted) return OFF;
        return clip != null && (clip.phase == STARTING || clip.phase == RECORDING) ? CLIP : WATCH;
    }

    /**
     * Brings the camera one step nearer to what is wanted now; every step ends by calling this again. Whatever asked
     * for the change (a page, the end of a clip, a pause, a failure), a running session is left only through
     * {@link #whenIdle} (M-29).
     */
    private void step() {
        if (opening || closing || configuring || afterReady != null) return;
        int target = target();
        if (device == null) {
            if (target != OFF) { open(); return; }
            if (clip != null && clip.phase == ENDING && !clip.back) {
                clip.back = true; // paused after the recording had ended: there is no watching to wait for
                join();
            }
            if (!closed) return;
            List<Runnable> completed = new ArrayList<>(closeCallbacks);
            closeCallbacks.clear();
            for (Runnable each : completed) each.run();
            return;
        }
        if (running == target && target != OFF) return;
        if (running != OFF) {
            whenIdle(() -> {
                running = OFF;
                step();
            });
        } else if (target == OFF) {
            closing = true;
            CameraDevice leaving = device;
            device = null;
            session = null;
            leaving.close(); // onClosed goes on
        } else {
            configure(target);
        }
    }

    /**
     * Stop the repeating request and go on only when the session has nothing in flight, or after 1.5 s. The frames
     * still in flight are taken meanwhile: the camera's thread returns to its queue, and the clip's frames have a
     * thread of their own (M-29).
     */
    private void whenIdle(Runnable next) {
        afterReady = next;
        try {
            session.stopRepeating();
        } catch (CameraAccessException | RuntimeException ignored) {
            // the timeout below goes on
        }
        handler.postDelayed(readyTimeout, IDLE_TIMEOUT_MILLIS);
    }

    private void readyNow() {
        Runnable next = afterReady;
        if (next == null) return;
        afterReady = null;
        handler.removeCallbacks(readyTimeout);
        next.run();
    }

    @RequiresPermission(Manifest.permission.CAMERA)
    private void open() {
        opening = true;
        try {
            CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
            String id = GlassCamera.rearCameraId(manager);
            CameraCharacteristics characteristics = manager.getCameraCharacteristics(id);
            // Zoom 2: the middle half of the field each way. On the glasses' 4032x3024 sensor that is 2016x1512 of
            // its own pixels, so the clip stream of that size is not scaled by the camera.
            Rect array = characteristics.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
            int width = array.width() / 2, height = array.height() / 2;
            crop = new Rect(array.centerX() - width / 2, array.centerY() - height / 2,
                    array.centerX() + width / 2, array.centerY() + height / 2);
            StreamConfigurationMap map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            Size size = GlassCamera.previewSize(map == null ? null : map.getOutputSizes(ImageFormat.YUV_420_888),
                    GlassCamera.largestJpegSize(characteristics));
            if (size == null) throw new IllegalStateException("no watch preview size");
            framesThread = new HandlerThread("clip-frames");
            framesThread.start();
            frames = new Handler(framesThread.getLooper());
            synchronized (lock) {
                watchPending = false;
                watchReader = ImageReader.newInstance(size.getWidth(), size.getHeight(), ImageFormat.YUV_420_888, 2);
                watchReader.setOnImageAvailableListener(this::watchImage, frames);
                clipReader = ImageReader.newInstance(WIDTH, HEIGHT, ImageFormat.YUV_420_888, 4);
                clipReader.setOnImageAvailableListener(this::clipFrame, frames);
            }
            pageChange.restartStream();
            previewExposure = 0;
            int attempt = ++opens;
            manager.openCamera(id, new CameraDevice.StateCallback() {
                private boolean told;

                @Override public void onOpened(CameraDevice opened) {
                    if (attempt != opens) { // asked for before a later one: nothing waits for it
                        opened.close();
                        return;
                    }
                    opening = false;
                    device = opened;
                    step();
                }

                @Override public void onDisconnected(CameraDevice gone) { lost(gone, "camera disconnected"); }

                @Override public void onError(CameraDevice gone, int error) { lost(gone, "camera error " + error); }

                @Override public void onClosed(CameraDevice left) {
                    closing = false;
                    releaseReaders();
                    step();
                }

                private void lost(CameraDevice gone, String reason) {
                    // Once, and not for a camera already let go: neither before the next one is asked for nor,
                    // now that a failed camera is opened again by itself, while the next one is being opened.
                    if (told || attempt != opens || (gone != device && !opening)) return;
                    told = true;
                    fail(reason, gone);
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException error) {
            opening = false;
            releaseReaders();
            fail("camera " + error, null);
        }
    }

    private void releaseReaders() {
        synchronized (lock) { // not while the frames' thread holds one of its images
            if (watchReader != null) { watchReader.close(); watchReader = null; }
            if (clipReader != null) { clipReader.close(); clipReader = null; }
        }
        if (framesThread != null) { framesThread.quitSafely(); framesThread = null; frames = null; }
    }

    private void configure(int mode) {
        int token = ++configured;
        configuring = true;
        ImageReader output = mode == CLIP ? clipReader : watchReader;
        Clip started = mode == CLIP ? clip : null;
        try {
            CaptureRequest request = mode == CLIP ? recordRequest(started) : watchRequest();
            SessionConfiguration asked = new SessionConfiguration(SessionConfiguration.SESSION_REGULAR,
                    Collections.singletonList(new OutputConfiguration(output.getSurface())), handler::post,
                    new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession made) {
                    if (token != configured || device == null) return;
                    configuring = false;
                    session = made;
                    running = mode; // also when what is wanted changed meanwhile: it is then left like any other session
                    if (target() == mode && (mode != CLIP || clip == started)) {
                        try {
                            if (mode == CLIP) record(made, request, started); else watch(made, request, token);
                        } catch (CameraAccessException | RuntimeException error) {
                            fail("camera request " + error, null);
                            return;
                        }
                    }
                    step();
                }

                @Override public void onReady(CameraCaptureSession ready) {
                    if (token == configured && afterReady != null) readyNow();
                }

                @Override public void onConfigureFailed(CameraCaptureSession refused) {
                    if (token != configured) return;
                    configuring = false;
                    fail("camera session refused", device);
                }
            });
            asked.setSessionParameters(request);
            device.createCaptureSession(asked);
        } catch (CameraAccessException | RuntimeException error) {
            configuring = false;
            fail("camera session " + error, error instanceof CameraAccessException ? device : null);
        }
    }

    /** The small preview alone, automatic exposure, 15 frames a second: half the frames are half the heat (M-18). */
    private CaptureRequest watchRequest() throws CameraAccessException {
        CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
        request.addTarget(watchReader.getSurface());
        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(WATCH_FPS, WATCH_FPS));
        request.set(CaptureRequest.SCALER_CROP_REGION, crop);
        return request.build();
    }

    private void watch(CameraCaptureSession made, CaptureRequest request, int token) throws CameraAccessException {
        // A preview that starts over starts its exposure over too. Until it has settled its frames differ from the
        // page just taken, and counted as page turns they took one unmoving page again and again (GlassCamera,
        // 2026-11-12). The first page of a session has no earlier one to be mistaken for.
        steady = false;
        settlingSince = pageChange.hasCapturedPage() ? Math.max(1, SystemClock.elapsedRealtime()) : 0;
        made.setRepeatingRequest(request, new CameraCaptureSession.CaptureCallback() {
            @Override public void onCaptureCompleted(CameraCaptureSession source, CaptureRequest asked, TotalCaptureResult result) {
                if (token != configured || result == null) return;
                Long exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
                Integer iso = result.get(CaptureResult.SENSOR_SENSITIVITY);
                if (exposure == null || exposure <= 0 || iso == null || iso <= 0) return;
                Integer boost = result.get(CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST);
                previewExposure = exposure;
                previewIso = iso;
                previewBoost = boost == null || boost <= 0 ? 100 : boost;
                Integer state = result.get(CaptureResult.CONTROL_AE_STATE);
                if (state != null && (state == CaptureResult.CONTROL_AE_STATE_CONVERGED
                        || state == CaptureResult.CONTROL_AE_STATE_LOCKED
                        || state == CaptureResult.CONTROL_AE_STATE_FLASH_REQUIRED)) steady = true;
                if (clip != null && clip.phase == WAITING && running == WATCH && afterReady == null && steady) begin();
            }
        }, handler);
    }

    /** The light is known: open the clip, then leave the watch session for the clip's. */
    private void begin() {
        Clip starting = clip;
        handler.removeCallbacks(timer);
        starting.previewExposure = previewExposure;
        starting.previewIso = previewIso;
        starting.previewBoost = previewBoost;
        // As bright as the preview's automatic exposure just was, at this clip's fixed exposure and sensitivity.
        double light = (double) previewExposure * previewIso * previewBoost / ISO;
        boolean dark = options.longExposureNanos > 0 && Math.round(light / options.exposureNanos) > options.longAboveBoost;
        starting.exposure = dark ? options.longExposureNanos : options.exposureNanos;
        starting.fps = dark ? LONG_FPS : FPS;
        starting.settle = dark ? LONG_SETTLE_FRAMES : SETTLE_FRAMES;
        starting.boost = (int) Math.max(MIN_BOOST, Math.min(MAX_BOOST, Math.round(light / starting.exposure)));
        try {
            // Its capture id is that of the frame that becomes the page, known only at the end: a name of its own until then.
            starting.file = inbox.reserve(UUID.randomUUID().toString());
            encoder.open(starting.file, WIDTH, HEIGHT, (int) ((long) options.bitrate * starting.fps / FPS), starting.fps);
            starting.opened = true;
        } catch (IOException | RuntimeException error) {
            fail("encoder " + error, null);
            return;
        }
        starting.phase = STARTING;
        pageChange.consumed();
        showFar(false);
        step();
    }

    /** The clip stream alone: the middle of the sensor in its own pixels, 30 or 15 frames a second, nothing automatic. */
    private CaptureRequest recordRequest(Clip started) throws CameraAccessException {
        CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
        request.addTarget(clipReader.getSurface());
        request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
        request.set(CaptureRequest.CONTROL_AWB_LOCK, true);
        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(started.fps, started.fps));
        request.set(CaptureRequest.SENSOR_FRAME_DURATION, 1_000_000_000L / started.fps);
        request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, started.exposure);
        request.set(CaptureRequest.SENSOR_SENSITIVITY, ISO);
        request.set(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST, started.boost);
        // What the phone adds together has to be the sensor's own noise and edges, not the camera's guess at them.
        request.set(CaptureRequest.NOISE_REDUCTION_MODE, CaptureRequest.NOISE_REDUCTION_MODE_OFF);
        request.set(CaptureRequest.EDGE_MODE, CaptureRequest.EDGE_MODE_OFF);
        // No TONEMAP_MODE and no curve: asked for either, this camera fails with error 4 (M-29).
        request.set(CaptureRequest.SCALER_CROP_REGION, crop);
        return request.build();
    }

    private void record(CameraCaptureSession made, CaptureRequest request, Clip started) throws CameraAccessException {
        synchronized (lock) {
            recent.clear();
            recording = started;
            showProgress(started, true); // under the lock: before any report of a frame that counts
        }
        started.phase = RECORDING;
        if (gyroscope != null) sensors.registerListener(turningListener, gyroscope, HeadMotion.PERIOD_MICROS, frames);
        handler.postDelayed(timer, MAX_MILLIS);
        made.setRepeatingRequest(request, new CameraCaptureSession.CaptureCallback() {
            @Override public void onCaptureCompleted(CameraCaptureSession source, CaptureRequest asked, TotalCaptureResult result) {
                if (result == null) return;
                synchronized (lock) {
                    if (recording != started) return;
                    // The page's frame and its result arrive in either order: a few results wait for their frame.
                    if (recent.size() == 8) recent.removeFirst();
                    recent.addLast(result);
                    if (started.pageResult == null && started.pageStamp != 0
                            && Long.valueOf(started.pageStamp).equals(result.get(CaptureResult.SENSOR_TIMESTAMP))) {
                        started.pageResult = result;
                    }
                }
            }
        }, handler);
    }

    private void timeUp() {
        Clip late = clip;
        if (late == null) return;
        if (late.phase == RECORDING) {
            end(late);
        } else if (late.phase == WAITING) {
            if (previewExposure > 0 && running == WATCH && afterReady == null) {
                begin(); // measured but never settled: recorded with the last reading rather than not at all
                return;
            }
            // The preview never measured the light: nothing was asked of the camera, and it goes on watching.
            clip = null;
            callback.onCaptureNotReady();
        }
    }

    /** The frames' thread: the clip stream, 30 times a second, whether a clip is recorded or not (M-29). */
    private void clipFrame(ImageReader source) {
        synchronized (lock) {
            if (source != clipReader) return;
            Image image;
            try {
                image = source.acquireNextImage();
            } catch (RuntimeException unavailable) {
                return;
            }
            if (image == null) return;
            Clip into = recording;
            try {
                if (into == null) return;
                long now = SystemClock.elapsedRealtime(), stamp = image.getTimestamp();
                Image.Plane plane = image.getPlanes()[0];
                int row = plane.getRowStride();
                if (image.getWidth() != WIDTH || image.getHeight() != HEIGHT || plane.getPixelStride() != 1 || row < WIDTH) {
                    throw new IllegalStateException("clip frame layout");
                }
                ByteBuffer luma = plane.getBuffer();
                if (into.firstAt == 0) {
                    into.firstAt = now;
                    into.firstMillis = now - into.askedAt;
                }
                if (!encoder.offer(luma.duplicate(), row, stamp)) {
                    into.dropped++; // the encoder has no room: this frame is lost, the next is not delayed
                    return;
                }
                int index = into.frames++;
                // How far the fastest turn of the head during this exposure carried the picture, in sensor pixels.
                HeadMotion.Span span = turning.between(stamp, stamp + into.exposure);
                // Glasses without a gyroscope cannot tell: every frame counts there, as before.
                float smear = span != null ? span.blurPixels(into.exposure) : gyroscope == null ? 0f : UNKNOWN_SMEAR;
                if (span != null) {
                    into.gyroFrames++;
                    if (!span.covered) into.gyroPartial++; // readings to come may still be faster: counted to learn how often
                }
                into.stamps[index] = stamp;
                into.smears[index] = smear;
                if (index >= into.settle && smear <= MAX_SMEAR_PIXELS) {
                    into.counted++;
                    // ponytail: one copy only, so the page is the first counted frame until the middle of a full clip
                    // is reached. A clip cut short at 10 s keeps its first; keep a second copy if that page reads worse.
                    if (into.counted == 1 || into.counted == Math.max(1, options.targetFrames / 2)) keep(into, luma, row, stamp);
                }
                if (now - into.shownAt >= 200) {
                    into.shownAt = now;
                    show(luma, row);
                }
                // A few comparisons a frame, and a post when the count has grown: this thread waits for nothing (M-30).
                if (into.counted > into.reported && into.reported < options.targetFrames
                        && now - into.reportedAt >= PROGRESS_MILLIS) {
                    into.reportedAt = now;
                    showProgress(into, true);
                }
                if ((into.counted >= options.targetFrames && now - into.firstAt >= MIN_MILLIS) || into.frames == MAX_FRAMES) {
                    recording = null; // no later frame joins this clip
                    handler.post(() -> end(into));
                }
            } catch (RuntimeException | OutOfMemoryError error) {
                recording = null;
                handler.post(() -> { if (clip == into) fail("clip frame " + error, null); });
            } finally {
                image.close();
            }
        }
    }

    /** The frame that may become the page: its rows without the camera's padding, colour grey. */
    private void keep(Clip into, ByteBuffer luma, int row, long stamp) {
        if (nv21 == null) {
            nv21 = new byte[WIDTH * HEIGHT * 3 / 2];
            Arrays.fill(nv21, WIDTH * HEIGHT, nv21.length, (byte) 128);
        }
        ByteBuffer rows = luma.duplicate();
        int origin = rows.position();
        for (int y = 0; y < HEIGHT; y++) {
            rows.position(origin + y * row);
            rows.get(nv21, y * WIDTH, WIDTH);
        }
        into.pageStamp = stamp;
        into.pageResult = null;
        for (TotalCaptureResult result : recent) {
            if (Long.valueOf(stamp).equals(result.get(CaptureResult.SENSOR_TIMESTAMP))) into.pageResult = result;
        }
    }

    /** The frame being recorded, in the small window: a row at a time, as each read of the camera's buffer is a native call. */
    private void show(ByteBuffer luma, int row) {
        int width = 320, height = width * HEIGHT / WIDTH;
        if (line == null) line = new byte[WIDTH];
        int[] display = new int[width * height];
        ByteBuffer rows = luma.duplicate();
        int origin = rows.position();
        for (int y = 0; y < height; y++) {
            rows.position(origin + y * HEIGHT / height * row);
            rows.get(line, 0, WIDTH);
            for (int x = 0; x < width; x++) display[y * width + x] = 0xFF000000 | ((line[x * WIDTH / width] & 255) << 8);
        }
        callback.onPreview(Bitmap.createBitmap(display, width, height, Bitmap.Config.RGB_565), null);
    }

    /** Enough frames, or ten seconds: the camera goes back to watching while the clip's own thread closes the file. */
    private void end(Clip ended) {
        if (clip != ended || ended.phase != RECORDING) return;
        stopRecording(ended);
        ended.phase = ENDING;
        ended.endedAt = SystemClock.elapsedRealtime();
        encoder.end((written, bytes, failure) -> {
            GlassCamera.Captured page = null;
            String problem = failure != null ? failure : ended.frames == 0 ? "clip without frames" : null;
            if (problem == null && ended.counted > 0) {
                try {
                    page = pageOf(ended);
                } catch (IOException | JSONException | RuntimeException | OutOfMemoryError error) {
                    problem = "clip page " + error;
                }
            }
            GlassCamera.Captured made = page;
            String reason = problem;
            handler.post(() -> encoded(ended, made, reason, bytes));
        });
        step();
    }

    private void stopRecording(Clip stopped) {
        handler.removeCallbacks(timer);
        synchronized (lock) {
            if (recording == stopped) recording = null;
        }
        if (gyroscope != null) sensors.unregisterListener(turningListener);
        // Once for a recording: abandon() also comes here for a clip not yet begun and for one already ended.
        if (stopped.phase == RECORDING) showProgress(stopped, false);
    }

    /**
     * The clip's own thread, once its file is closed: the page's JPEG from the kept frame, and the clip moved under
     * that page's capture id with its record. Neither the camera's thread nor the frames' waits for these files.
     */
    private GlassCamera.Captured pageOf(Clip ended) throws IOException, JSONException {
        byte[] jpeg = pageEncoder.encode(nv21, WIDTH, HEIGHT, JPEG_QUALITY);
        if (jpeg == null || jpeg.length == 0 || jpeg.length > GlassCamera.MAX_JPEG_BYTES) throw new IOException("page not encoded");
        TotalCaptureResult result = ended.pageResult;
        CaptureProvenance provenance = CaptureProvenance.clipFrame(jpeg, WIDTH, HEIGHT, ended.pageStamp,
                result == null ? null : result.get(CaptureResult.SENSOR_TIMESTAMP),
                result == null ? null : result.getFrameNumber(),
                result == null ? null : result.get(CaptureResult.SENSOR_EXPOSURE_TIME),
                result == null ? null : result.get(CaptureResult.SENSOR_SENSITIVITY),
                result == null ? null : result.get(CaptureResult.CONTROL_AF_STATE),
                result == null ? null : result.get(CaptureResult.CONTROL_AE_STATE));
        File named = inbox.reserve(provenance.captureId);
        if (!ended.file.renameTo(named)) throw new IOException("clip not moved");
        ended.file = named;
        JSONArray each = new JSONArray();
        for (int i = 0; i < ended.frames; i++) {
            each.put(new JSONObject().put("t_ns", ended.stamps[i]).put("smear_px", Math.round(ended.smears[i] * 100f) / 100.0));
        }
        JSONArray turnedAt = new JSONArray();
        JSONArray[] turned = {new JSONArray(), new JSONArray(), new JSONArray()};
        for (int i = 0; i < ended.readings; i++) {
            turnedAt.put(ended.turnedAt[i]);
            for (int axis = 0; axis < 3; axis++) turned[axis].put(Math.round(ended.turned[3 * i + axis] * 10000f) / 10000.0);
        }
        JSONObject record = new JSONObject().put("schema", 1).put("capture_id", provenance.captureId)
                .put("width", WIDTH).put("height", HEIGHT).put("rotation_degrees", options.rotationDegrees)
                .put("exposure_ns", ended.exposure).put("sensitivity_iso", ISO).put("boost", ended.boost)
                .put("frame_rate", ended.fps).put("gyro_frames", ended.gyroFrames).put("gyro_partial", ended.gyroPartial)
                .put("preview", new JSONObject().put("exposure_ns", ended.previewExposure)
                        .put("sensitivity_iso", ended.previewIso).put("boost", ended.previewBoost))
                .put("frames", each).put("dropped", ended.dropped).put("settle", ended.settle)
                .put("gyro", new JSONObject().put("t_ns", turnedAt).put("x", turned[0]).put("y", turned[1]).put("z", turned[2]));
        inbox.offer(provenance.captureId, record.toString().getBytes(StandardCharsets.UTF_8));
        return new GlassCamera.Captured(jpeg, WIDTH, HEIGHT, SystemClock.elapsedRealtime() - ended.askedAt, provenance);
    }

    private void encoded(Clip ended, GlassCamera.Captured page, String failure, long bytes) {
        ended.page = page;
        ended.failure = failure;
        ended.bytes = bytes;
        ended.encoded = true;
        if (clip != ended) { // given up meanwhile: a record left behind goes with the session's next photo
            ended.file.delete();
        } else if (failure != null) {
            clip = null;
            ended.file.delete();
            fail(failure, null);
        } else {
            join();
        }
    }

    /** A page is handed over when its clip is closed and the camera watches again; the second is what the wearer waits for. */
    private void join() {
        Clip done = clip;
        if (done == null || !done.encoded || !done.back) return;
        clip = null;
        Log.i(TAG, "clip frames=" + done.frames + " counted=" + done.counted + " dropped=" + done.dropped
                + " bytes=" + done.bytes + " first_ms=" + done.firstMillis + " back_ms=" + done.backMillis
                + " boost=" + done.boost + " exposure_ms=" + done.exposure / 1_000_000 + " gyro=" + done.gyroFrames);
        if (done.page != null) {
            cameraFailures = 0;
            callback.onCaptured(done.page);
            return;
        }
        // Not one frame was still enough to count: nothing is in flight, and the same page is looked for again.
        done.file.delete();
        pageChange = new PageChange();
        settlingSince = 0;
        callback.onCaptureNotReady();
    }

    /** A clip that will not become a page: closed, and deleted once its file is closed. */
    private void abandon() {
        Clip given = clip;
        if (given == null) return;
        clip = null;
        stopRecording(given);
        if (given.phase == ENDING) { // its encoder was told to end already: encoded() finds the clip gone
            if (given.encoded) given.file.delete();
            return;
        }
        if (given.opened) encoder.end((written, bytes, failure) -> given.file.delete());
        else if (given.file != null) given.file.delete();
    }

    /**
     * The capture fails and the camera is closed; it opens again when it is next asked to watch. A camera that
     * reported itself gone is closed at once, as nothing of it can be waited for; otherwise in order.
     *
     * <p>A camera that reported itself gone leaves nothing in doubt: it is closed, and a clip is either whole, with
     * its file closed, or deleted. So a clip already recorded still becomes its page, a clip cut short is dropped and
     * the same page is looked for again, and the camera is opened again, up to {@link #MAX_CAMERA_FAILURES} times
     * with no page between. On 2026-11-16 the camera failed on its way back to watching after a whole clip: the
     * page was thrown away and the session ended, which at the venue means starting the app again.
     */
    private void fail(String reason, CameraDevice gone) {
        Log.w(TAG, "clip camera failed: " + reason);
        Clip pending = clip;
        boolean recorded = gone != null && pending != null && pending.phase == ENDING;
        boolean again = gone != null && !closed && (recorded || ++cameraFailures < MAX_CAMERA_FAILURES);
        if (recorded) {
            pending.back = true; // there is no watching to wait for; join() hands the page over
        } else {
            abandon();
            if (pending != null && again) { // the page in view was not taken: it is seen as new once the camera is back
                pageChange = new PageChange();
                settlingSince = 0;
            }
        }
        if (!again) {
            wanted = false;
            pageReady = null;
        }
        showFar(false);
        showNear(false);
        if (gone != null) {
            opening = configuring = false;
            afterReady = null;
            handler.removeCallbacks(readyTimeout);
            configured++;
            device = null;
            session = null;
            running = OFF;
            closing = true;
            gone.close();
        }
        if (recorded) join();
        else if (!again) { if (!closed) callback.onCaptureFailed(reason); }
        else if (pending != null) callback.onCaptureNotReady(); // nothing was taken: the page is asked for again
        step();
    }

    /**
     * The frames' thread: the watch preview's frame is copied and returned at once. The camera's thread may be
     * opening a clip's file or waiting for a session; the camera must get its buffer back all the same (M-30).
     */
    private void watchImage(ImageReader source) {
        synchronized (lock) {
            if (source != watchReader) return; // a notice from a reader already closed
            Image image;
            try {
                image = source.acquireLatestImage();
            } catch (RuntimeException unavailable) {
                return;
            }
            if (image == null) return;
            try {
                if (watchPending) return; // the camera's thread still has the frame before: this one is only returned
                Image.Plane luma = image.getPlanes()[0];
                // Copied once: reading the camera's own buffer a pixel at a time cost about 170 ms a frame on the glasses.
                ByteBuffer plane = luma.getBuffer().duplicate();
                int bytes = plane.remaining();
                if (watchLuma == null || watchLuma.length < bytes) watchLuma = new byte[bytes];
                plane.get(watchLuma, 0, bytes);
                watchBytes = bytes;
                watchWidth = image.getWidth();
                watchHeight = image.getHeight();
                watchRow = luma.getRowStride();
                watchStep = luma.getPixelStride();
                watchStamp = image.getTimestamp();
                watchPending = true;
            } catch (RuntimeException | OutOfMemoryError error) {
                return; // this frame is lost; the next one is taken
            } finally {
                image.close();
            }
        }
        handler.post(this::watchFrame);
    }

    /** The camera's thread: the watch preview. What it shows is page evidence exactly as in {@link GlassCamera}. */
    private void watchFrame() {
        try {
            if (running != WATCH || afterReady != null || watchReader == null) return;
            long now = SystemClock.elapsedRealtime(), timestamp = watchStamp, began = System.nanoTime();
            Clip ending = clip;
            if (ending != null && ending.phase == ENDING && !ending.back) {
                ending.back = true;
                ending.backMillis = now - ending.endedAt;
                join();
                if (running != WATCH || afterReady != null) return;
            }
            if (settlingSince != 0) {
                if (!steady && now - settlingSince < GlassCamera.RESUME_SETTLE_LIMIT_MILLIS) return;
                settlingSince = 0;
            }
            int width = watchWidth, height = watchHeight;
            ByteBuffer pixels = ByteBuffer.wrap(watchLuma, 0, watchBytes);
            int row = watchRow, step = watchStep;
            byte[] thumbnail = new byte[32 * 24];
            int level = 0;
            for (int y = 0; y < 24; y++) for (int x = 0; x < 32; x++) {
                byte value = pixels.get(y * height / 24 * row + x * width / 32 * step);
                thumbnail[y * 32 + x] = value;
                level += value & 255;
            }
            pageChange.observeFrame(thumbnail, pixels, width, height, row, step, timestamp, now);
            if (pageScene != pageChange.sequence()) {
                pageScene = pageChange.sequence();
                Log.i(TAG, "page_change scene=" + pageScene + " " + pageChange.lastChange());
            }
            if (options.farShare > 0) {
                // ponytail: paper is taken to be what is brighter than the frame's mean. A dark desk beside a lit
                // page reads the same as a page far away; replace with the paper's outline once worn frames exist.
                int mean = level / thumbnail.length, brighter = 0;
                for (byte value : thumbnail) if ((value & 255) > mean) brighter++;
                showFar(brighter < options.farShare * thumbnail.length);
            }
            if (options.nearLines > 0 && now - pitchAt >= 500) {
                pitchAt = now;
                boolean print = printPitch.measure(pixels, width, height, row, step) && printPitch.stands >= PrintPitch.SURE;
                lines = print ? printPitch.period * WIDTH / width : 0f;
                // A whole pixel between on and off: at the limit the figure wanders by a few tenths.
                showNear(print && lines > (near ? options.nearLines - 1f : options.nearLines));
            }
            if (now - displayAt >= 100) {
                displayAt = now;
                int shownWidth = Math.min(320, width), shownHeight = Math.max(1, shownWidth * height / width);
                int[] display = new int[shownWidth * shownHeight];
                for (int y = 0; y < shownHeight; y++) for (int x = 0; x < shownWidth; x++) {
                    int gray = pixels.get(y * height / shownHeight * row + x * width / shownWidth * step) & 255;
                    display[y * shownWidth + x] = 0xFF000000 | (gray << 8);
                }
                callback.onPreview(Bitmap.createBitmap(display, shownWidth, shownHeight, Bitmap.Config.RGB_565), null);
            }
            if (clip == null && pageReady != null && pageChange.ready(now)) {
                Runnable ready = pageReady;
                pageReady = null;
                ready.run();
            }
            // What the desk check and a worn recording read: the frames handled, the slowest of them, and the light
            // as the automatic exposure measures it.
            watchFrames++;
            watchWorkNanos = Math.max(watchWorkNanos, System.nanoTime() - began);
            if (now - statusAt >= 1000) {
                Log.i(TAG, "watch_status frames=" + watchFrames + " max_work_ms=" + watchWorkNanos / 1_000_000
                        + " exposure_ns=" + previewExposure + " iso=" + previewIso + " boost=" + previewBoost
                        + " far=" + far + " lines=" + (lines > 0 ? Math.round(lines * 10) / 10f : "-") + " near=" + near);
                statusAt = now;
                watchFrames = 0;
                watchWorkNanos = 0;
            }
        } catch (RuntimeException | OutOfMemoryError error) {
            fail("watch frame " + error, null);
        } finally {
            synchronized (lock) {
                watchPending = false;
            }
        }
    }

    private void showFar(boolean now) {
        if (far == now) return;
        far = now;
        Marks shown = marks;
        if (shown != null) shown.showFar(now);
    }

    private void showNear(boolean now) {
        if (near == now) return;
        near = now;
        Marks shown = marks;
        if (shown != null) shown.showNear(now);
    }

    /** The frames' thread while the clip is recorded, under the lock as the count is; the camera's at its start and its end. */
    private void showProgress(Clip of, boolean recording) {
        of.reported = Math.min(of.counted, options.targetFrames); // a short clip goes on to the end of its first second
        Marks shown = marks;
        if (shown != null) shown.showClipProgress(of.reported, options.targetFrames, recording);
    }
}
