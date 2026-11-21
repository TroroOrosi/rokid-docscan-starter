package dev.rokid.docscanglass.probe;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.ImageFormat;
import android.graphics.SurfaceTexture;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.TotalCaptureResult;
import android.media.Image;
import android.media.ImageReader;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.SystemClock;
import android.util.Log;
import android.util.Range;
import android.util.Size;
import android.view.Surface;
import android.view.TextureView;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * The gathered capture's shape, for measuring only: watch with the small preview, then record one clip a page.
 *
 * <p>{@code pages=<n>,watch=<ms>,record=<s>}: a 320x240 YUV preview alone for the watch time (auto exposure, 15 a
 * second, as the app watches for a page), then the session is rebuilt to the hardware encoder beside a small
 * display-format stream and records with manual exposure for the record time, then goes back; n times on one open
 * camera. The clip's size comes from {@code still=WxH} (2400x1800), its rate from {@code fps=} (30), the exposure from
 * {@code expose=<ns>} (16666666), {@code codec=avc|hevc}, {@code bitrate=} (20000000). ISO is 800 and the digital gain
 * is what gives the watch's brightness at that exposure, within the camera's 1x to 32x.
 *
 * <p>Each page logs the time from asking for the rebuild to the first recorded frame's result (and, inside it, to the
 * prepared encoder and to the configured session), the time the stop took, and the time back to the first preview frame.
 * With {@code mark}, a page starts at half its digital gain and goes to the full gain when the first result arrives: the
 * step in brightness is then at a known capture result, which ties the clip's frames to the results without relying on
 * their times. With {@code keep}, the first {@code keepclips=<m>} (3) clips stay in
 * the cache as {@code probe-clip-<k>.mp4} beside {@code probe-clip-<k>.json}, which lists every capture result's
 * sensor timestamp. With {@code texture}, the display stream goes to a {@link TextureView} and a bitmap is read back
 * five times a second, to learn whether the app can draw from it while recording.
 *
 * <p>Nothing is uploaded, recognized or registered. The privacy indicator is firmware-owned and is not touched.
 */
final class PageCycleProbe {

    private static final String TAG = "DocScanGlassProbe";

    interface Done {
        void done(boolean ok, String detail);
    }

    private final Context context;
    private final Handler handler;
    private final Done done;
    private final TextureView display;
    private final int pages;
    private final long watchMillis;
    private final long recordMillis;
    private final Size clipSize;
    private final int fps;
    private final int bitrate;
    private final boolean hevc;
    private final long exposureNanos;
    private final int keepClips;

    private CameraDevice device;
    private CameraCaptureSession session;
    private ImageReader preview;
    private MediaRecorder recorder;
    private File clip;
    private SurfaceTexture texture;
    private Surface textureSurface;
    private TotalCaptureResult lastWatch;
    private final List<Long> stamps = new ArrayList<>();
    private final List<Integer> gains = new ArrayList<>();
    private final boolean mark;
    private long preparedMillis;
    private long configuredMillis;
    private int page;
    private int boost;
    private boolean closed;
    private boolean awaitingPreviewFrame;
    private boolean firstResultSeen;
    private long startedAt;
    private long rebuildAskedAt;
    private long backAskedAt;
    private long rebuildMillis;
    private long stopMillis;
    private long stopAskedAt;
    private long drainMillis;
    private boolean draining;
    private android.graphics.Rect cropRegion;
    private MediaRecorder ending;  // the clip's encoder between the camera's return to watching and its own stop
    private long watchingAt;
    private long backMillis;
    private static final int TAIL_RESULTS = 4;  // results of display-only requests that mean none is left in flight to the encoder
    private int tailResults;
    private CaptureRequest tail;
    private final Runnable whenDrained = this::drained;
    private long clipBytes;
    private int grabs;
    private long grabNanos;
    private long grabSum;
    private long grabSecondAt;

    PageCycleProbe(Context context, Handler handler, TextureView display, Done done) {
        this.context = context;
        this.handler = handler;
        this.display = display;
        this.done = done;
        pages = Integer.parseInt(CameraProbe.option("pages"));
        watchMillis = number("watch", 10_000);
        recordMillis = number("record", 5) * 1000;
        String[] wh = (CameraProbe.option("still") == null ? "2400x1800" : CameraProbe.option("still")).split("x");
        clipSize = new Size(Integer.parseInt(wh[0]), Integer.parseInt(wh[1]));
        fps = (int) number("fps", 30);
        bitrate = (int) number("bitrate", 20_000_000);
        hevc = !"avc".equals(CameraProbe.option("codec"));
        exposureNanos = number("expose", 16_666_666);
        keepClips = CameraProbe.option("keep") == null ? 0 : (int) number("keepclips", 3);
        mark = CameraProbe.option("mark") != null;
    }

    private static long number(String name, long fallback) {
        String value = CameraProbe.option(name);
        return value == null || value.isEmpty() ? fallback : Long.parseLong(value);
    }

    void start() {
        startedAt = SystemClock.elapsedRealtime();
        CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
        try {
            preview = ImageReader.newInstance(320, 240, ImageFormat.YUV_420_888, 2);
            preview.setOnImageAvailableListener(this::onPreviewFrame, handler);
            if (display != null && display.isAvailable()) {
                texture = display.getSurfaceTexture();
                display.postDelayed(this::grab, 200);
            } else {
                texture = new SurfaceTexture(false);
            }
            texture.setDefaultBufferSize(320, 240);
            textureSurface = new Surface(texture);
            Log.i(TAG, "camera probe cycle pages=" + pages + " watch_ms=" + watchMillis + " record_ms=" + recordMillis
                    + " clip=" + clipSize + " fps=" + fps + " bitrate=" + bitrate + " hevc=" + hevc + " expose_ns="
                    + exposureNanos + " display=" + (display != null && display.isAvailable() ? "TextureView" : "detached"));
            String zoom = CameraProbe.option("zoom");  // zoom=1.68: the middle of the field, so that the clip's pixels are the sensor's
            if (zoom != null) {
                android.graphics.Rect array = manager.getCameraCharacteristics(manager.getCameraIdList()[0])
                        .get(android.hardware.camera2.CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
                int w = (int) (array.width() / Double.parseDouble(zoom)), h = (int) (array.height() / Double.parseDouble(zoom));
                cropRegion = new android.graphics.Rect(array.centerX() - w / 2, array.centerY() - h / 2, array.centerX() + w / 2, array.centerY() + h / 2);
                Log.i(TAG, "camera probe cycle crop=" + cropRegion);
            }
            manager.openCamera(manager.getCameraIdList()[0], new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice opened) {
                    device = opened;
                    backAskedAt = SystemClock.elapsedRealtime();
                    watch();
                }

                @Override public void onDisconnected(CameraDevice disconnected) {
                    device = disconnected;
                    fail("camera disconnected");
                }

                @Override public void onError(CameraDevice errored, int error) {
                    device = errored;
                    fail("camera error " + error);
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException error) {
            fail("open " + error.getClass().getSimpleName());
        }
    }

    /** The small preview alone, as the app waits for a page. */
    private void watch() {
        try {
            awaitingPreviewFrame = true;
            device.createCaptureSession(Collections.singletonList(preview.getSurface()), new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession configured) {
                    if (closed) return;
                    session = configured;
                    endRecorder();
                    try {
                        CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                        request.addTarget(preview.getSurface());
                        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(15, 15));
                        configured.setRepeatingRequest(request.build(), new CameraCaptureSession.CaptureCallback() {
                            @Override public void onCaptureCompleted(CameraCaptureSession source, CaptureRequest asked,
                                    TotalCaptureResult result) {
                                if (source == session) lastWatch = result;
                            }
                        }, handler);
                    } catch (CameraAccessException | RuntimeException error) {
                        fail("watch request " + error.getClass().getSimpleName());
                    }
                }

                @Override public void onConfigureFailed(CameraCaptureSession failed) {
                    fail("watch session refused");
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException error) {
            fail("watch session " + error.getClass().getSimpleName());
        }
    }

    private void onPreviewFrame(ImageReader source) {
        try (Image image = source.acquireLatestImage()) {
            if (image == null || !awaitingPreviewFrame || closed) return;
        } catch (RuntimeException ignored) {
            return;
        }
        awaitingPreviewFrame = false;
        watchingAt = SystemClock.elapsedRealtime();
        backMillis = watchingAt - backAskedAt;
        pageDone();
    }

    /** A page is over when the camera watches again and its clip is closed; the first is what the wearer waits for. */
    private void pageDone() {
        if (closed || awaitingPreviewFrame || ending != null) return;
        if (page > 0) {
            Log.i(TAG, "camera probe page=" + page + " rebuild_ms=" + rebuildMillis + " stop_ms=" + stopMillis + " drain_ms=" + drainMillis
                    + " back_ms=" + backMillis + " results=" + stamps.size() + " bytes=" + clipBytes + " boost=" + boost + " prepare_ms="
                    + preparedMillis + " configured_ms=" + configuredMillis);
        }
        if (page >= pages) {
            finish(true, "cycle " + pages + " pages in " + (SystemClock.elapsedRealtime() - startedAt) + "ms variant=["
                    + CameraProbe.variant + "]");
            return;
        }
        handler.postDelayed(this::record, Math.max(0, watchMillis - (SystemClock.elapsedRealtime() - watchingAt)));
    }

    /** One page: the encoder beside the display stream, manual exposure. */
    private void record() {
        if (closed) return;
        page++;
        try {
            clip = new File(context.getCacheDir(), "probe-clip-" + page + ".mp4");
            rebuildAskedAt = SystemClock.elapsedRealtime();
            recorder = new MediaRecorder();
            recorder.setVideoSource(MediaRecorder.VideoSource.SURFACE);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setVideoEncoder(hevc ? MediaRecorder.VideoEncoder.HEVC : MediaRecorder.VideoEncoder.H264);
            recorder.setVideoSize(clipSize.getWidth(), clipSize.getHeight());
            recorder.setVideoFrameRate(fps);
            recorder.setVideoEncodingBitRate(bitrate);
            recorder.setOutputFile(clip.getAbsolutePath());
            recorder.prepare();
            preparedMillis = SystemClock.elapsedRealtime() - rebuildAskedAt;
            firstResultSeen = false;
            stamps.clear();
            gains.clear();
            boost = gain();
            device.createCaptureSession(Arrays.asList(recorder.getSurface(), textureSurface), new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession configured) {
                    if (closed) return;
                    session = configured;
                    configuredMillis = SystemClock.elapsedRealtime() - rebuildAskedAt;
                    try {
                        // intent=preview: the encoder fed by requests that do not say "video", to see what the camera does to video
                        CaptureRequest.Builder request = device.createCaptureRequest("preview".equals(CameraProbe.option("intent"))
                                ? CameraDevice.TEMPLATE_PREVIEW : CameraDevice.TEMPLATE_RECORD);
                        if (cropRegion != null) request.set(CaptureRequest.SCALER_CROP_REGION, cropRegion);
                        // tnr=0 / cnr=0: the camera's own keys for the noise reduction it applies to video (named in its
                        // description, dumpsys media.camera of 2026-11-15); NOISE_REDUCTION_MODE_OFF does not reach it
                        vendor(request, "tnr", "org.codeaurora.qcamera3.temporal_denoise.enable");
                        vendor(request, "cnr", "org.quic.camera.CustomNoiseReduction.CustomNoiseReduction");
                        request.addTarget(recorder.getSurface());
                        request.addTarget(textureSurface);
                        request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
                        request.set(CaptureRequest.CONTROL_AWB_LOCK, true);
                        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(fps, fps));
                        request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, exposureNanos);
                        request.set(CaptureRequest.SENSOR_FRAME_DURATION, 1_000_000_000L / fps);
                        request.set(CaptureRequest.SENSOR_SENSITIVITY, 800);
                        request.set(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST, boost);
                        request.set(CaptureRequest.NOISE_REDUCTION_MODE, CaptureRequest.NOISE_REDUCTION_MODE_OFF);
                        request.set(CaptureRequest.EDGE_MODE, CaptureRequest.EDGE_MODE_OFF);
                        CaptureRequest full = request.build();
                        request.set(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST, Math.max(100, boost / 2));
                        CaptureRequest dim = request.build();
                        request.set(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST, boost);
                        request.removeTarget(recorder.getSurface());
                        tail = request.build();
                        recorder.start();
                        configured.setRepeatingRequest(mark ? dim : full, new CameraCaptureSession.CaptureCallback() {
                            @Override public void onCaptureCompleted(CameraCaptureSession source, CaptureRequest asked,
                                    TotalCaptureResult result) {
                                if (source != session || closed) return;
                                Long stamp = result.get(CaptureResult.SENSOR_TIMESTAMP);
                                Integer gain = result.get(CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST);
                                stamps.add(stamp == null ? -1L : stamp);
                                gains.add(gain == null ? -1 : gain);
                                if (!firstResultSeen) {
                                    firstResultSeen = true;
                                    Log.i(TAG, "camera probe cycle first result nr=" + result.get(CaptureResult.NOISE_REDUCTION_MODE) + " edge="
                                            + result.get(CaptureResult.EDGE_MODE) + " crop=" + result.get(CaptureResult.SCALER_CROP_REGION));
                                    rebuildMillis = SystemClock.elapsedRealtime() - rebuildAskedAt;
                                    handler.postDelayed(PageCycleProbe.this::stopRecording, recordMillis);
                                    if (mark) {
                                        try {
                                            source.setRepeatingRequest(full, this, handler);
                                        } catch (CameraAccessException | RuntimeException error) {
                                            fail("full gain " + error.getClass().getSimpleName());
                                        }
                                    }
                                }
                            }
                        }, handler);
                    } catch (CameraAccessException | RuntimeException error) {
                        fail("record request " + error.getClass().getSimpleName());
                    }
                }

                @Override public void onConfigureFailed(CameraCaptureSession failed) {
                    fail("record session refused");
                }
            }, handler);
        } catch (IOException | CameraAccessException | RuntimeException error) {
            fail("record " + error.getClass().getSimpleName());
        }
    }

    private static void vendor(CaptureRequest.Builder request, String option, String name) {
        String value = CameraProbe.option(option);
        if (value == null) return;
        try {
            request.set(new CaptureRequest.Key<>(name, Byte.class), Byte.parseByte(value));
            Log.i(TAG, "camera probe cycle set " + name + "=" + value);
        } catch (RuntimeException error) {
            Log.i(TAG, "camera probe cycle refused " + name + ": " + error);
        }
    }

    /** The digital gain that gives the watch's brightness at this exposure and ISO 800, in the camera's 100 to 3199. */
    private int gain() {
        if (lastWatch == null) return 3199;
        Long exposure = lastWatch.get(CaptureResult.SENSOR_EXPOSURE_TIME);
        Integer iso = lastWatch.get(CaptureResult.SENSOR_SENSITIVITY);
        Integer watched = lastWatch.get(CaptureResult.CONTROL_POST_RAW_SENSITIVITY_BOOST);
        if (exposure == null || iso == null) return 3199;
        double light = (double) exposure * iso * (watched == null ? 100 : watched);
        return (int) Math.max(100, Math.min(3199, Math.round(light / ((double) exposureNanos * 800))));
    }

    /**
     * End a clip without leaving the camera idle and without frames in flight to the encoder: go on asking for frames, to the
     * display stream alone, and stop the encoder when a few of those have come back.
     *
     * Two ways that failed on the glasses (logcat of 2026-11-15). Stopping the requests and the encoder at once abandons the
     * encoder's surface under about three requests in flight ("BufferQueue has been abandoned", "Stuck on Sequence Id"), and
     * the stop sometimes took 3 to 5.8 s (M-26). Stopping the requests and waiting for the session to report idle is worse:
     * a streaming pipeline with no requests trips the camera's own watchdog after 33 frames ("Hit SOF threshold ...
     * triggering watchdog recovery"), the idle report did not come within 1.5 s in 7 of 9 stops and the stop took 2.2-3.2 s.
     *
     * With the frames drained the encoder's own stop still took 3.9 to 6.4 s in about one of four, after the file was
     * complete ("MOOV atom was written" 0.3 s after the stop was asked). So the camera goes back to watching first, and the
     * encoder is stopped off the camera's thread once the watching session is in place and nothing writes to its surface.
     */
    private void stopRecording() {
        if (closed) return;
        stopAskedAt = SystemClock.elapsedRealtime();
        try {
            draining = true;
            tailResults = 0;
            session.setRepeatingRequest(tail, new CameraCaptureSession.CaptureCallback() {
                @Override public void onCaptureCompleted(CameraCaptureSession source, CaptureRequest asked, TotalCaptureResult result) {
                    if (source == session && ++tailResults == TAIL_RESULTS) drained();
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException error) {
            fail("stop " + error.getClass().getSimpleName());
            return;
        }
        handler.postDelayed(whenDrained, 1500);  // if the display stream's results do not come
    }

    private void drained() {
        if (closed || !draining) return;
        draining = false;
        handler.removeCallbacks(whenDrained);
        drainMillis = SystemClock.elapsedRealtime() - stopAskedAt;
        ending = recorder;
        recorder = null;
        backAskedAt = SystemClock.elapsedRealtime();
        watch();
    }

    private void endRecorder() {
        final MediaRecorder stopping = ending;
        if (stopping == null) return;
        final long asked = SystemClock.elapsedRealtime();
        new Thread(() -> {
            boolean stopped = true;
            try {
                stopping.stop();
            } catch (RuntimeException error) {
                stopped = false;
            }
            stopping.release();
            final boolean ok = stopped;
            final long took = SystemClock.elapsedRealtime() - asked;
            handler.post(() -> recorderEnded(ok, took));
        }, "probe-recorder-stop").start();
    }

    private void recorderEnded(boolean ok, long took) {
        if (closed) return;
        ending = null;
        if (!ok) {
            fail("stop RuntimeException");
            return;
        }
        stopMillis = took;
        clipBytes = clip.length();
        if (page <= keepClips) {
            StringBuilder json = new StringBuilder("{\"page\":").append(page).append(",\"exposure_ns\":").append(exposureNanos)
                    .append(",\"iso\":800,\"boost\":").append(boost).append(",\"frame_ns\":").append(1_000_000_000L / fps)
                    .append(",\"rebuild_ms\":").append(rebuildMillis).append(",\"stop_ms\":").append(stopMillis).append(",\"gains\":[");
            for (int i = 0; i < gains.size(); i++) json.append(i == 0 ? "" : ",").append(gains.get(i));
            json.append("],\"results\":[");
            for (int i = 0; i < stamps.size(); i++) json.append(i == 0 ? "" : ",").append(stamps.get(i));
            try (FileOutputStream out = new FileOutputStream(new File(context.getCacheDir(), "probe-clip-" + page + ".json"))) {
                out.write(json.append("]}").toString().getBytes(StandardCharsets.UTF_8));
            } catch (IOException error) {
                fail("record of page " + page + " not written");
                return;
            }
        } else if (!clip.delete()) {
            Log.w(TAG, "probe clip could not be deleted");
        }
        pageDone();
    }

    /** The display stream read back as the app would draw it: five times a second, on the view's thread. */
    private void grab() {
        if (closed || display == null) return;
        long from = System.nanoTime();
        Bitmap bitmap = display.getBitmap(320, 240);
        if (bitmap != null) {
            int[] row = new int[320];
            long sum = 0;
            for (int y = 0; y < 240; y += 8) {
                bitmap.getPixels(row, 0, 320, 0, y, 320, 1);
                for (int x = 0; x < 320; x += 8) sum += (row[x] >> 8) & 0xFF;
            }
            grabSum += sum / (30 * 40);
            bitmap.recycle();
            grabs++;
            grabNanos += System.nanoTime() - from;
        }
        long now = SystemClock.elapsedRealtime();
        if (now - grabSecondAt >= 1000) {
            Log.i(TAG, "camera probe texture grabs=" + grabs + " ms_per_grab=" + (grabs == 0 ? 0 : grabNanos / grabs / 1_000_000)
                    + " mean=" + (grabs == 0 ? -1 : grabSum / grabs) + " recording=" + (recorder != null));
            grabSecondAt = now;
            grabs = 0;
            grabNanos = 0;
            grabSum = 0;
        }
        display.postDelayed(this::grab, 200);
    }

    private void fail(String detail) {
        finish(false, "cycle failed at page " + page + ": " + detail);
    }

    private void finish(boolean ok, String detail) {
        if (closed) return;
        Log.i(TAG, "camera probe " + (ok ? "OK " : "FAILED ") + detail);
        close();
        done.done(ok, detail);
    }

    void close() {
        closed = true;
        handler.removeCallbacksAndMessages(null);
        if (session != null) { session.close(); session = null; }
        if (device != null) { device.close(); device = null; }
        if (recorder != null) { recorder.release(); recorder = null; }
        if (preview != null) { preview.close(); preview = null; }
        if (textureSurface != null) { textureSurface.release(); textureSurface = null; }
        if (texture != null && display == null) { texture.release(); }
        texture = null;
    }
}
