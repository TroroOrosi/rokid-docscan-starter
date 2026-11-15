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
    private final MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();

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
            final Rect cropRegion = crop;
            if (cutX < 0 || cutY < 0 || cutX + outWidth > width || cutY + outHeight > height) throw new IllegalArgumentException("the part lies outside the frame");
            clip = new File(context.getCacheDir(), "probe-clip-1.mp4");
            MediaFormat format = MediaFormat.createVideoFormat(hevc ? MediaFormat.MIMETYPE_VIDEO_HEVC : MediaFormat.MIMETYPE_VIDEO_AVC, outWidth, outHeight);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            format.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
            format.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
            format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
            codec = MediaCodec.createEncoderByType(format.getString(MediaFormat.KEY_MIME));
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            codec.start();
            muxer = new MediaMuxer(clip.getAbsolutePath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            reader = ImageReader.newInstance(width, height, ImageFormat.YUV_420_888, width * height > 6_000_000 ? 3 : 4);  // a full-size frame is 18 MB
            reader.setOnImageAvailableListener(this::onImage, handler);
            Log.i(TAG, "camera probe feed " + width + "x" + height + " out=" + outWidth + "x" + outHeight + " cut=" + cutX + "x" + cutY + " fps=" + fps
                    + " expose_ns=" + exposureNanos + " boost=" + boost
                    + " bitrate=" + bitrate + " codec=" + codec.getName() + " crop=" + cropRegion);
            manager.openCamera(id, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice opened) {
                    device = opened;
                    configure(cropRegion);
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
                        if (cropRegion != null) request.set(CaptureRequest.SCALER_CROP_REGION, cropRegion);
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
            finish(false, "feed " + error);
        } finally {
            image.close();
            if (!closed) drain(0);
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
        if (closed || !feeding) return;
        feeding = false;
        long fedFor = SystemClock.elapsedRealtime() - startedAt;
        if (device != null) { device.close(); device = null; }  // the camera first: nothing of it is needed to end the clip
        session = null;
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
            return;
        }
        finish(true, "feed " + width + "x" + height + " fps=" + fps + " for_ms=" + fedFor + " images=" + images + " fed=" + fed + " dropped=" + dropped
                + " results=" + results + " written=" + written + " ended=" + ended + " bytes=" + clip.length() + " copy_us="
                + (fed == 0 ? 0 : copyNanos / 1000 / fed) + " end_ms=" + (SystemClock.elapsedRealtime() - from) + " " + layout
                + " out=" + outWidth + "x" + outHeight + " cut=" + cutX + "x" + cutY);
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
}
