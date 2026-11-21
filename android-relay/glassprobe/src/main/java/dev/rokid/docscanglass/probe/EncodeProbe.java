package dev.rokid.docscanglass.probe;

import android.content.Context;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.util.Log;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;

/**
 * Frames that the camera did not smooth, through the glasses' hardware encoder: does the print survive the encoder?
 *
 * <p>The camera's own video output is smoothed before the encoder whatever is asked (M-27), so the frames a page is
 * gathered from have to come from another output and be handed to the encoder by the app. This reads such frames from a
 * file ({@code encode=<name in the cache directory>}, NV12, {@code still=WxH}), gives them to the encoder as buffers and
 * writes {@code probe-clip-1.mp4}. No camera is opened. {@code loops=} repeats the file; {@code fps=}, {@code bitrate=}
 * and {@code codec=avc} are the encoder's.
 */
final class EncodeProbe {

    private static final String TAG = "DocScanGlassProbe";

    private EncodeProbe() {}

    static String run(Context context) throws IOException {
        String[] wh = CameraProbe.option("still").split("x");
        int width = Integer.parseInt(wh[0]), height = Integer.parseInt(wh[1]);
        int fps = number("fps", 30), bitrate = number("bitrate", 40_000_000), loops = number("loops", 1);
        boolean hevc = !"avc".equals(CameraProbe.option("codec"));
        File source = new File(context.getCacheDir(), CameraProbe.option("encode"));
        int frameBytes = width * height * 3 / 2;
        int frames = (int) (source.length() / frameBytes);
        if (frames == 0) throw new IOException("no frame of " + width + "x" + height + " in " + source.getName());
        File clip = new File(context.getCacheDir(), "probe-clip-1.mp4");
        MediaFormat format = MediaFormat.createVideoFormat(hevc ? MediaFormat.MIMETYPE_VIDEO_HEVC : MediaFormat.MIMETYPE_VIDEO_AVC, width, height);
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
        format.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
        format.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
        format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
        MediaCodec codec = MediaCodec.createEncoderByType(format.getString(MediaFormat.KEY_MIME));
        String name = codec.getName();
        MediaMuxer muxer = null;
        long started = System.nanoTime(), fillNanos = 0;
        int sent = 0, written = 0, total = frames * loops, track = -1;
        String layout = "";
        try (RandomAccessFile file = new RandomAccessFile(source, "r")) {
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            codec.start();
            muxer = new MediaMuxer(clip.getAbsolutePath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            byte[] frame = new byte[frameBytes];
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            boolean inputDone = false;
            while (true) {
                if (!inputDone) {
                    int in = codec.dequeueInputBuffer(10_000);
                    if (in >= 0 && sent == total) {
                        codec.queueInputBuffer(in, 0, 0, sent * 1_000_000L / fps, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                        inputDone = true;
                    } else if (in >= 0) {
                        file.seek((long) (sent % frames) * frameBytes);
                        file.readFully(frame);
                        int capacity = codec.getInputBuffer(in).capacity();
                        long from = System.nanoTime();
                        Image image = codec.getInputImage(in);
                        if (image == null) throw new IOException("the encoder gives no input image");
                        if (sent == 0) {
                            Image.Plane[] planes = image.getPlanes();
                            layout = "rows=" + planes[0].getRowStride() + "/" + planes[1].getRowStride() + " step=" + planes[1].getPixelStride();
                        }
                        fill(image, frame, width, height);
                        fillNanos += System.nanoTime() - from;
                        codec.queueInputBuffer(in, 0, capacity, sent * 1_000_000L / fps, 0);
                        sent++;
                    }
                }
                int out = codec.dequeueOutputBuffer(info, 10_000);
                if (out == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    track = muxer.addTrack(codec.getOutputFormat());
                    muxer.start();
                } else if (out >= 0) {
                    ByteBuffer data = codec.getOutputBuffer(out);
                    boolean config = (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0;
                    if (!config && info.size > 0 && track >= 0) {
                        muxer.writeSampleData(track, data, info);
                        written++;
                    }
                    codec.releaseOutputBuffer(out, false);
                    if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) break;
                }
            }
        } finally {
            try {
                codec.stop();
            } catch (RuntimeException ignored) {
                // the verdict below says what was written
            }
            codec.release();
            if (muxer != null && track >= 0) {
                muxer.stop();
                muxer.release();
            }
        }
        String detail = "encode " + source.getName() + " codec=" + name + " " + width + "x" + height + " fps=" + fps + " asked=" + bitrate
                + " frames=" + written + "/" + total + " bytes=" + clip.length() + " " + layout + " fill_ms=" + fillNanos / 1_000_000 / Math.max(1, sent)
                + " total_ms=" + (System.nanoTime() - started) / 1_000_000;
        Log.i(TAG, "camera probe OK " + detail);
        return detail;
    }

    /** An NV12 frame into the encoder's own layout, whatever its strides and the order of its colour samples. */
    private static void fill(Image image, byte[] frame, int width, int height) {
        Image.Plane[] planes = image.getPlanes();
        ByteBuffer y = planes[0].getBuffer(), u = planes[1].getBuffer(), v = planes[2].getBuffer();
        int rows = planes[0].getRowStride(), colourRows = planes[1].getRowStride(), step = planes[1].getPixelStride();
        for (int row = 0; row < height; row++) {
            y.position(row * rows);
            y.put(frame, row * width, width);
        }
        for (int row = 0; row < height / 2; row++) {
            int from = width * height + row * width, to = row * colourRows;
            for (int column = 0; column < width / 2; column++) {
                u.put(to + column * step, frame[from + 2 * column]);
                v.put(to + column * step, frame[from + 2 * column + 1]);
            }
        }
    }

    private static int number(String name, int fallback) {
        String value = CameraProbe.option(name);
        return value == null || value.isEmpty() ? fallback : Integer.parseInt(value);
    }
}
