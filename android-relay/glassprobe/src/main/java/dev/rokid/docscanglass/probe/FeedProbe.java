package dev.rokid.docscanglass.probe;

import android.content.Context;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.TotalCaptureResult;
import android.media.Image;
import android.media.ImageReader;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.os.Handler;
import android.os.SystemClock;
import android.util.Log;
import android.util.Range;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.Collections;

/**
 * A clip whose frames the camera did not smooth: the camera's YUV output, copied by the app into the hardware encoder.
 *
 * <p>The camera's own video output is smoothed before the encoder whatever is asked, and the print is gone from it; the
 * encoder itself keeps the print when it is given unsmoothed frames (M-27, M-28). This is the path between: one YUV
 * stream ({@code still=WxH}, {@code fps=}, manual exposure {@code expose=} at ISO 800 with {@code boost=}), every frame's
 * brightness plane copied into an encoder input buffer, the colour planes left grey (a page is read from its brightness,
 * and grey costs the encoder nothing). {@code feed=<seconds>} records that long into {@code probe-clip-1.mp4}.
 *
 * <p>{@code out=WxH,cut=XxY} encodes only that part of each frame, its corner at (X, Y) of the stream: the paper in the
 * sensor's own pixels out of a full-size stream, wherever it lies (the camera itself crops at its centre only).
 *
 * <p>{@code pages=N,watch=<ms>} does it page after page on one open camera, as the app would: the small preview alone
 * for {@code watch} ms, then the feed for {@code feed} seconds into {@code probe-clip-<page>.mp4}, and back. Each page
 * logs how long the wearer waits (session rebuilt, first frame, clip ended, watching again) and the brightness of its
 * first frames. {@code keepclips=K} keeps the first K clips; the others are deleted as soon as they are measured.
 */
final class FeedProbe {

    private static final String TAG = "DocScanGlassProbe";

    private final Context context;
    private final Handler handler;
    private final PageCycleProbe.Done done;
    private final int width;
    private final int height;
    private final int outWidth;
    private final int outHeight;
    private final int cutX;
    private final int cutY;
    private final int fps;
    private final int bitrate;
    private final int boost;
    private final long exposureNanos;
    private final long feedMillis;
    private final boolean hevc;
    private final int pages;
    private final long watchMillis;
    private final int keepClips;
    private final MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
    private final StringBuilder levels = new StringBuilder();

    private CameraDevice device;
    private CameraCaptureSession session;
    private ImageReader reader;
    private MediaCodec codec;
    private MediaMuxer muxer;
    private File clip;
    private byte[] grey;
    private byte[] plane;
    private int track = -1;
    private boolean feeding;
    private boolean closed;
    private int images;
    private int fed;
    private int dropped;
    private int results;
    private int written;
    private long copyNanos;
    private long firstStamp = -1;
    private long startedAt;
    private String layout = "";
    private ImageReader preview;
    private Rect cropRegion;
    private int page;
    private boolean awaitingPreview;
    private long askedAt;
    private long rebuildMillis;
    private long firstImageMillis;
    private long backAskedAt;
    private long cycleStartedAt;
    private String pageLine;
    private boolean ending;  // the last clip's encoder is still being ended, off this thread
    private final Object lock = new Object();  // the encoder and the counters, between the frames' thread and the camera's
    private android.os.HandlerThread framesThread;
    private Writer writer;
    private Runnable afterReady;  // what to do once the session has nothing in flight
    private final Runnable readyTimeout = this::readyNow;
    private long idleAskedAt;
    private long idleMillis;
    private long watchIdleMillis;
    private long watchingAt;
    private long backMillis;

    FeedProbe(Context context, Handler handler, PageCycleProbe.Done done) {
        this.context = context;
        this.handler = handler;
        this.done = done;
        String[] wh = (CameraProbe.option("still") == null ? "2016x1512" : CameraProbe.option("still")).split("x");
        width = Integer.parseInt(wh[0]);
        height = Integer.parseInt(wh[1]);
        String[] out = (CameraProbe.option("out") == null ? width + "x" + height : CameraProbe.option("out")).split("x");
        outWidth = Integer.parseInt(out[0]);
        outHeight = Integer.parseInt(out[1]);
        String[] cut = (CameraProbe.option("cut") == null ? "0x0" : CameraProbe.option("cut")).split("x");
        cutX = Integer.parseInt(cut[0]);
        cutY = Integer.parseInt(cut[1]);
        fps = (int) number("fps", 30);
        bitrate = (int) number("bitrate", 27_000_000);
        boost = (int) number("boost", 700);
        exposureNanos = number("expose", 30_000_000);
        feedMillis = number("feed", 5) * 1000;
        hevc = !"avc".equals(CameraProbe.option("codec"));
        pages = (int) number("pages", 0);
        watchMillis = number("watch", 8500);
        keepClips = (int) number("keepclips", 0);
    }

    private static long number(String name, long fallback) {
        String value = CameraProbe.option(name);
        return value == null || value.isEmpty() ? fallback : Long.parseLong(value);
    }

    void start() {
        CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
        try {
            String id = manager.getCameraIdList()[0];
            Rect crop = null;
            String zoom = CameraProbe.option("zoom");  // zoom=2: the middle of the field in the sensor's own pixels
            if (zoom != null) {
                Rect array = manager.getCameraCharacteristics(id).get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
                int w = (int) (array.width() / Double.parseDouble(zoom)), h = (int) (array.height() / Double.parseDouble(zoom));
                crop = new Rect(array.centerX() - w / 2, array.centerY() - h / 2, array.centerX() + w / 2, array.centerY() + h / 2);
            }
            cropRegion = crop;
            if (cutX < 0 || cutY < 0 || cutX + outWidth > width || cutY + outHeight > height) throw new IllegalArgumentException("the part lies outside the frame");
            if (pages == 0) openEncoder(1);
            cycleStartedAt = SystemClock.elapsedRealtime();
            preview = ImageReader.newInstance(320, 240, ImageFormat.YUV_420_888, 2);
            preview.setOnImageAvailableListener(this::onPreview, handler);
            reader = ImageReader.newInstance(width, height, ImageFormat.YUV_420_888, width * height > 6_000_000 ? 3 : 4);  // a full-size frame is 18 MB
            // The frames come on a thread of their own. On the camera's thread they were not taken while that thread
            // waited for a session to change; the camera could then not drain, and hung until the glasses were restarted (M-29).
            framesThread = new android.os.HandlerThread("probe-frames");
            framesThread.start();
            reader.setOnImageAvailableListener(this::onImage, new Handler(framesThread.getLooper()));
            Log.i(TAG, "camera probe feed " + width + "x" + height + " out=" + outWidth + "x" + outHeight + " cut=" + cutX + "x" + cutY + " fps=" + fps
                    + " expose_ns=" + exposureNanos + " boost=" + boost
                    + " bitrate=" + bitrate + " hevc=" + hevc + " crop=" + cropRegion + " pages=" + pages + " watch_ms=" + watchMillis);
            manager.openCamera(id, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice opened) {
                    device = opened;
                    if (pages > 0) watch(); else configure(cropRegion);
                }

                @Override public void onDisconnected(CameraDevice disconnected) {
                    device = disconnected;
                    finish(false, "camera disconnected");
                }

                @Override public void onError(CameraDevice errored, int error) {
                    device = errored;
                    finish(false, "camera error " + error);
                }
            }, handler);
        } catch (CameraAccessException | IOException | SecurityException | IllegalArgumentException | IllegalStateException error) {
            finish(false, "start " + error);
        }
    }

    private void openEncoder(int number) throws IOException {
        clip = new File(context.getCacheDir(), "probe-clip-" + number + ".mp4");
        MediaFormat format = MediaFormat.createVideoFormat(hevc ? MediaFormat.MIMETYPE_VIDEO_HEVC : MediaFormat.MIMETYPE_VIDEO_AVC, outWidth, outHeight);
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
        format.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
        format.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
        format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
        codec = MediaCodec.createEncoderByType(format.getString(MediaFormat.KEY_MIME));
        codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        codec.start();
        muxer = new MediaMuxer(clip.getAbsolutePath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
        track = -1;
    }

    /**
     * Stop the repeating request and go on only when the session has nothing in flight (or after 1.5 s). A session changed
     * at once left frames in flight that could get no buffer while the camera was being configured; the camera then
     * failed to drain, after 16 and after 28 pages (M-29).
     */
    private void whenIdle(Runnable next) {
        afterReady = next;
        idleAskedAt = SystemClock.elapsedRealtime();
        try {
            session.stopRepeating();
        } catch (CameraAccessException | RuntimeException ignored) {
            // the timeout below goes on
        }
        handler.postDelayed(readyTimeout, 1500);
    }

    private void readyNow() {
        Runnable next = afterReady;
        if (next == null || closed) return;
        afterReady = null;
        handler.removeCallbacks(readyTimeout);
        idleMillis = SystemClock.elapsedRealtime() - idleAskedAt;
        next.run();
    }

    /**
     * One page's clip: takes what the encoder gives and writes it, on a thread of its own, so that neither the camera's
     * thread nor the frames' thread ever waits for the file (ending a clip took 1 to 5.6 s in 7 of 28 pages, M-29).
     */
    private final class Writer implements Runnable {
        private final MediaCodec codec;
        private final MediaMuxer muxer;
        private final File clip;
        private final int number;
        volatile boolean endAsked;
        volatile String head = "";
        volatile String tail = "";

        Writer(MediaCodec codec, MediaMuxer muxer, File clip, int number) {
            this.codec = codec;
            this.muxer = muxer;
            this.clip = clip;
            this.number = number;
        }

        @Override public void run() {
            MediaCodec.BufferInfo own = new MediaCodec.BufferInfo();
            int trackId = -1, wrote = 0;
            boolean ended = false, endQueued = false;
            String failed = null;
            long from = 0;
            try {
                while (!ended) {
                    if (endAsked && !endQueued) {
                        if (from == 0) from = SystemClock.elapsedRealtime();
                        int in = codec.dequeueInputBuffer(20_000);
                        if (in >= 0) {
                            codec.queueInputBuffer(in, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            endQueued = true;
                        }
                    }
                    int out = codec.dequeueOutputBuffer(own, 20_000);
                    if (out == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                        trackId = muxer.addTrack(codec.getOutputFormat());
                        muxer.start();
                    } else if (out >= 0) {
                        if ((own.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0 && own.size > 0 && trackId >= 0) {
                            muxer.writeSampleData(trackId, codec.getOutputBuffer(out), own);
                            wrote++;
                        }
                        codec.releaseOutputBuffer(out, false);
                        ended = (own.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                    }
                    if (from != 0 && SystemClock.elapsedRealtime() - from > 8000) break;  // never for ever
                }
                codec.stop();
                if (trackId >= 0) muxer.stop();
            } catch (RuntimeException error) {
                failed = "clip " + error;
            } finally {
                codec.release();
                try {
                    muxer.release();
                } catch (RuntimeException ignored) {
                    // a muxer that never started
                }
            }
            long bytes = clip.length();
            if (number > keepClips) clip.delete();
            final String line = head + " written=" + wrote + " ended=" + ended + " bytes=" + bytes + " end_ms="
                    + (from == 0 ? 0 : SystemClock.elapsedRealtime() - from) + tail;
            final String error = failed;
            handler.post(() -> {
                ending = false;
                if (error != null && !closed) {
                    finish(false, error);
                    return;
                }
                pageLine = line;
                pageDone();
            });
        }
    }

    /** The small preview alone, as the app waits for a page. */
    private void watch() {
        try {
            backAskedAt = SystemClock.elapsedRealtime();
            awaitingPreview = true;
            device.createCaptureSession(Collections.singletonList(preview.getSurface()), new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession configured) {
                    if (closed) return;
                    session = configured;
                    try {
                        CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                        request.addTarget(preview.getSurface());
                        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(15, 15));
                        configured.setRepeatingRequest(request.build(), null, handler);
                    } catch (CameraAccessException | RuntimeException error) {
                        finish(false, "watch request " + error);
                    }
                }

                @Override public void onReady(CameraCaptureSession ready) {
                    if (ready == session && afterReady != null) readyNow();
                }

                @Override public void onConfigureFailed(CameraCaptureSession failed) {
                    finish(false, "watch session refused");
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException error) {
            finish(false, "watch session " + error);
        }
    }

    private void onPreview(ImageReader source) {
        try (Image image = source.acquireLatestImage()) {
            if (image == null || !awaitingPreview || closed) return;
        } catch (RuntimeException ignored) {
            return;
        }
        awaitingPreview = false;
        watchingAt = SystemClock.elapsedRealtime();
        backMillis = watchingAt - backAskedAt;
        pageDone();
    }

    /** A page is over when the camera watches again and its clip is closed; the first is what the wearer waits for. */
    private void pageDone() {
        if (closed || awaitingPreview || ending) return;
        if (pageLine != null) Log.i(TAG, pageLine + " idle_ms=" + idleMillis + " back_ms=" + backMillis);
        pageLine = null;
        if (page >= pages) {
            finish(true, "feed cycle " + pages + " pages in " + (SystemClock.elapsedRealtime() - cycleStartedAt) + "ms out=" + outWidth + "x" + outHeight);
            return;
        }
        handler.postDelayed(this::feedPage, Math.max(0, watchMillis - (SystemClock.elapsedRealtime() - watchingAt)));
    }

    private void feedPage() {
        if (closed) return;
        page++;
        images = fed = dropped = results = written = 0;
        copyNanos = 0;
        firstStamp = -1;
        firstImageMillis = -1;
        levels.setLength(0);
        try {
            openEncoder(page);
        } catch (IOException | RuntimeException error) {
            finish(false, "encoder " + error);
            return;
        }
        writer = new Writer(codec, muxer, clip, page);
        new Thread(writer, "probe-clip-writer").start();
        askedAt = SystemClock.elapsedRealtime();
        whenIdle(() -> {
            watchIdleMillis = idleMillis;
            configure(cropRegion);
        });
    }

    private void configure(Rect cropRegion) {
        try {
            device.createCaptureSession(Collections.singletonList(reader.getSurface()), new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession configured) {
                    if (closed) return;
                    session = configured;
                    try {
                        CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                        request.addTarget(reader.getSurface());
                        request.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF);
                        request.set(CaptureRequest.CONTROL_AWB_LOCK, true);
                        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<>(fps, fps));
                        request.set(CaptureRequest.SENSOR_EXPOSURE_TIME, exposureNanos);
                        request.set(CaptureRequest.SENSOR_FRAME_DURATION, 1_000_000_000L / fps);
                        request.set(CaptureRequest.SENSOR_SENSITIVITY, 800);
                        request.set(CaptureRequest.CONTROL_POST_RAW_SENSITIVITY_BOOST, boost);
                        request.set(CaptureRequest.NOISE_REDUCTION_MODE, CaptureRequest.NOISE_REDUCTION_MODE_OFF);
                        request.set(CaptureRequest.EDGE_MODE, CaptureRequest.EDGE_MODE_OFF);
                        String tone = CameraProbe.option("tone");  // tone=srgb or tone=linear: the brightness curve given, not the camera's own
                        if (tone != null) {
                            float[] curve = new float[128];
                            for (int i = 0; i < 64; i++) {
                                float x = i / 63f;
                                curve[2 * i] = x;
                                curve[2 * i + 1] = "linear".equals(tone) ? x
                                        : x <= 0.0031308f ? 12.92f * x : (float) (1.055 * Math.pow(x, 1 / 2.4) - 0.055);
                            }
                            request.set(CaptureRequest.TONEMAP_MODE, CaptureRequest.TONEMAP_MODE_CONTRAST_CURVE);
                            request.set(CaptureRequest.TONEMAP_CURVE, new android.hardware.camera2.params.TonemapCurve(curve, curve, curve));
                        }
                        if (cropRegion != null) request.set(CaptureRequest.SCALER_CROP_REGION, cropRegion);
                        rebuildMillis = SystemClock.elapsedRealtime() - askedAt;
                        startedAt = SystemClock.elapsedRealtime();
                        feeding = true;
                        configured.setRepeatingRequest(request.build(), new CameraCaptureSession.CaptureCallback() {
                            @Override public void onCaptureCompleted(CameraCaptureSession source, CaptureRequest asked, TotalCaptureResult result) {
                                results++;
                            }
                        }, handler);
                        handler.postDelayed(FeedProbe.this::stop, feedMillis);
                    } catch (CameraAccessException | RuntimeException error) {
                        finish(false, "request " + error);
                    }
                }

                @Override public void onReady(CameraCaptureSession ready) {
                    if (ready == session && afterReady != null) readyNow();
                }

                @Override public void onConfigureFailed(CameraCaptureSession failed) {
                    finish(false, "session refused");
                }
            }, handler);
        } catch (CameraAccessException | RuntimeException error) {
            finish(false, "session " + error);
        }
    }

    /** One frame from the camera into the encoder: its brightness plane copied, its colour left grey. */
    private void onImage(ImageReader source) {
        synchronized (lock) {
            onImageLocked(source);
        }
    }

    private void onImageLocked(ImageReader source) {
        Image image;
        try {
            image = source.acquireNextImage();
        } catch (RuntimeException error) {
            return;
        }
        if (image == null) return;
        try {
            if (!feeding || closed) return;
            images++;
            if (firstImageMillis < 0) firstImageMillis = SystemClock.elapsedRealtime() - askedAt;
            int in = codec.dequeueInputBuffer(0);
            if (in < 0) {
                dropped++;  // the encoder has no buffer free: this frame is lost, the next is not delayed
                return;
            }
            int capacity = codec.getInputBuffer(in).capacity();
            long from = System.nanoTime();
            Image target = codec.getInputImage(in);
            Image.Plane from0 = image.getPlanes()[0];
            Image.Plane[] to = target.getPlanes();
            ByteBuffer src = from0.getBuffer(), dst = to[0].getBuffer();
            int srcRows = from0.getRowStride(), dstRows = to[0].getRowStride();
            // One read of the rows wanted from the camera's plane, then each into the encoder's. Measured on the glasses
            // (2016x1512, the camera pads rows to 2048): row by row through a small array 8.6 ms a frame, buffer to buffer 16.9 ms.
            src.position(cutY * srcRows);
            int count = Math.min(src.remaining(), srcRows * outHeight);
            if (plane == null || plane.length < count) plane = new byte[count];
            src.get(plane, 0, count);
            if (srcRows == dstRows && cutX == 0) {
                dst.put(plane, 0, Math.min(count, dst.remaining()));
            } else {
                for (int y = 0; y < outHeight; y++) {
                    dst.position(y * dstRows);
                    dst.put(plane, y * srcRows + cutX, outWidth);
                }
            }
            if (pages > 0 && fed < 90) {  // the brightness of the page's first frames, from a sparse sample of what was copied
                long sum = 0;
                int count2 = 0;
                for (int y = 0; y < outHeight; y += 16) {
                    for (int x = 0; x < outWidth; x += 16) {
                        sum += plane[y * srcRows + cutX + x] & 0xff;
                        count2++;
                    }
                }
                levels.append(fed == 0 ? "" : ",").append(sum / count2);
            }
            ByteBuffer u = to[1].getBuffer(), v = to[2].getBuffer();
            if (grey == null || grey.length < Math.max(u.remaining(), v.remaining())) {
                grey = new byte[Math.max(u.remaining(), v.remaining())];
                Arrays.fill(grey, (byte) 128);
                layout = "rows=" + srcRows + "/" + dstRows + " colour_step=" + to[1].getPixelStride();
            }
            u.put(grey, 0, u.remaining());
            if (to[1].getPixelStride() == 2) {
                v.put(v.limit() - 1, (byte) 128);  // the two colours share one buffer: the fill above left its last byte
            } else {
                v.put(grey, 0, v.remaining());
            }
            copyNanos += System.nanoTime() - from;
            if (firstStamp < 0) firstStamp = image.getTimestamp();
            codec.queueInputBuffer(in, 0, capacity, (image.getTimestamp() - firstStamp) / 1000, 0);
            fed++;
        } catch (RuntimeException error) {
            final String detail = "feed " + error;
            handler.post(() -> finish(false, detail));
        } finally {
            image.close();
            if (pages == 0 && !closed && feeding && codec != null) drain(0);  // page after page, the clip's writer takes the output
        }
    }

    private boolean drain(long waitMicros) {
        while (true) {
            int out = codec.dequeueOutputBuffer(info, waitMicros);
            if (out == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                track = muxer.addTrack(codec.getOutputFormat());
                muxer.start();
            } else if (out >= 0) {
                boolean config = (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0;
                if (!config && info.size > 0 && track >= 0) {
                    muxer.writeSampleData(track, codec.getOutputBuffer(out), info);
                    written++;
                }
                codec.releaseOutputBuffer(out, false);
                if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) return true;
            } else {
                return false;
            }
        }
    }

    private void stop() {
        boolean watchNext;
        synchronized (lock) {
            watchNext = stopLocked();
        }
        if (watchNext) whenIdle(this::watch);  // outside the lock: the frames must go on being taken while the camera drains
    }

    /** @return whether the camera is to go back to watching (page after page) */
    private boolean stopLocked() {
        if (closed || !feeding) return false;
        feeding = false;
        long fedFor = SystemClock.elapsedRealtime() - startedAt;
        if (pages == 0) {
            if (device != null) { device.close(); device = null; }  // the camera first: nothing of it is needed to end the clip
            session = null;
        }
        if (pages > 0) {
            // The clip's writer ends the clip; the camera goes back to watching meanwhile.
            writer.head = "camera probe page=" + page + " rebuild_ms=" + rebuildMillis + " first_image_ms=" + firstImageMillis + " watch_idle_ms=" + watchIdleMillis
                    + " for_ms=" + fedFor + " images=" + images + " fed=" + fed + " dropped=" + dropped + " copy_us=" + (fed == 0 ? 0 : copyNanos / 1000 / fed);
            writer.tail = " levels=" + levels;
            writer.endAsked = true;
            codec = null;
            muxer = null;
            ending = true;
            awaitingPreview = true;  // from here the page is over only when the camera watches again: the clip may end first
            return true;
        }
        long from = SystemClock.elapsedRealtime();
        boolean ended = false;
        try {
            int in = codec.dequeueInputBuffer(500_000);
            if (in >= 0) codec.queueInputBuffer(in, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
            for (int tries = 0; tries < 30 && !ended; tries++) ended = drain(100_000);
            codec.stop();
            if (track >= 0) muxer.stop();
        } catch (RuntimeException error) {
            finish(false, "end " + error);
            return false;
        }
        finish(true, "feed " + width + "x" + height + " fps=" + fps + " for_ms=" + fedFor + " images=" + images + " fed=" + fed + " dropped=" + dropped
                + " results=" + results + " written=" + written + " ended=" + ended + " bytes=" + clip.length() + " copy_us="
                + (fed == 0 ? 0 : copyNanos / 1000 / fed) + " end_ms=" + (SystemClock.elapsedRealtime() - from) + " " + layout
                + " out=" + outWidth + "x" + outHeight + " cut=" + cutX + "x" + cutY);
        return false;
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
        if (device != null) { device.close(); device = null; }
        synchronized (lock) {
            if (pages > 0) {  // the clip's writer owns the encoder and lets go of it itself
                if (writer != null) writer.endAsked = true;
                codec = null;
                muxer = null;
            }
            if (codec != null) { codec.release(); codec = null; }
            if (muxer != null) {
                try {
                    muxer.release();
                } catch (RuntimeException ignored) {
                    // a muxer that never started
                }
                muxer = null;
            }
            if (reader != null) { reader.close(); reader = null; }
        }
        if (framesThread != null) { framesThread.quitSafely(); framesThread = null; }
        if (preview != null) { preview.close(); preview = null; }
    }
}
