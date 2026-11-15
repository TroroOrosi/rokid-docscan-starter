package dev.rokid.docscanglass.doc;

import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.os.SystemClock;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Arrays;

/**
 * Turns the camera's frames into one page's clip. {@link ClipCamera} calls {@link #open} and {@link #end} on the
 * camera's thread and {@link #offer} on the frames' thread, never one during another, and one clip at a time.
 */
interface ClipEncoder {
    /** {@code frameRate} is what the camera will send: the encoder spreads {@code bitrate} over that many frames a second. */
    void open(File clip, int width, int height, int bitrate, int frameRate) throws IOException;

    /**
     * One frame's brightness plane, read from the buffer's position. False when the encoder had no room: the frame
     * is not in the clip, and the next one is not delayed for it.
     */
    boolean offer(ByteBuffer luma, int rowStride, long timestampNanos);

    /** No further frame. {@code ended} is told once the file is closed, on the clip's own thread. */
    void end(Ended ended);

    interface Ended {
        /** @param failure null when the clip is whole */
        void done(int written, long bytes, String failure);
    }

    /**
     * The hardware HEVC encoder, fed the camera's own YUV frames: the camera's video output is smoothed before the
     * encoder whatever is asked, and the print is gone from it; the encoder keeps the print when the app hands it
     * unsmoothed frames (M-27, M-28). Colour is left grey: a page is read from its brightness, and grey costs the
     * encoder nothing. This is the encoder half of glassprobe's FeedProbe, the form that was measured on the glasses;
     * no unit test runs it, as there is no codec off the device.
     */
    final class Hardware implements ClipEncoder {
        private MediaCodec codec;
        private Writer writer;
        private int width, height;
        private long firstStamp;
        private byte[] plane, grey;

        @Override public void open(File clip, int width, int height, int bitrate, int frameRate) throws IOException {
            MediaFormat format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_HEVC, width, height);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            format.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
            format.setInteger(MediaFormat.KEY_FRAME_RATE, frameRate);
            format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
            MediaCodec opened = null;
            MediaMuxer muxer;
            try {
                opened = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_HEVC);
                opened.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
                opened.start();
                muxer = new MediaMuxer(clip.getAbsolutePath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            } catch (IOException | RuntimeException error) {
                if (opened != null) opened.release();
                throw new IOException(String.valueOf(error), error);
            }
            codec = opened;
            this.width = width;
            this.height = height;
            firstStamp = -1;
            writer = new Writer(opened, muxer, clip);
            new Thread(writer, "clip-writer").start();
        }

        /** A codec that fails here throws: the caller ends the clip, and {@link #end} reports what the writer saw. */
        @Override public boolean offer(ByteBuffer luma, int rowStride, long timestampNanos) {
            int in = codec.dequeueInputBuffer(0);
            if (in < 0) return false;
            int capacity = codec.getInputBuffer(in).capacity();
            Image.Plane[] to = codec.getInputImage(in).getPlanes();
            ByteBuffer dst = to[0].getBuffer();
            int dstRows = to[0].getRowStride();
            // One read of the camera's plane, then into the encoder's. Measured on the glasses with glassprobe
            // (2016x1512, the camera pads rows to 2048): through an array 8.6 ms a frame, buffer to buffer 16.9 ms.
            int count = Math.min(luma.remaining(), rowStride * height);
            if (plane == null || plane.length < count) plane = new byte[count];
            luma.get(plane, 0, count);
            if (rowStride == dstRows) {
                dst.put(plane, 0, Math.min(count, dst.remaining()));
            } else {
                for (int y = 0; y < height; y++) {
                    dst.position(y * dstRows);
                    dst.put(plane, y * rowStride, width);
                }
            }
            ByteBuffer u = to[1].getBuffer(), v = to[2].getBuffer();
            if (grey == null || grey.length < Math.max(u.remaining(), v.remaining())) {
                grey = new byte[Math.max(u.remaining(), v.remaining())];
                Arrays.fill(grey, (byte) 128);
            }
            u.put(grey, 0, u.remaining());
            if (to[1].getPixelStride() == 2) {
                v.put(v.limit() - 1, (byte) 128); // the two colours share one buffer: the fill above left its last byte
            } else {
                v.put(grey, 0, v.remaining());
            }
            if (firstStamp < 0) firstStamp = timestampNanos;
            codec.queueInputBuffer(in, 0, capacity, (timestampNanos - firstStamp) / 1000, 0);
            return true;
        }

        @Override public void end(Ended ended) {
            Writer ending = writer;
            writer = null;
            codec = null;
            ending.end(ended);
        }

        /**
         * Takes what the encoder gives and writes it, on a thread of its own, so that neither the camera's thread nor
         * the frames' thread ever waits for the file: ending a clip on the camera's thread took 1 to 5.6 s in 7 of 28
         * pages (M-29).
         */
        private static final class Writer implements Runnable {
            private final MediaCodec codec;
            private final MediaMuxer muxer;
            private final File clip;
            private Ended ended;

            Writer(MediaCodec codec, MediaMuxer muxer, File clip) {
                this.codec = codec;
                this.muxer = muxer;
                this.clip = clip;
            }

            synchronized void end(Ended asked) {
                ended = asked;
                notifyAll();
            }

            private synchronized boolean endAsked() { return ended != null; }

            /** A writer that failed while frames still came has to wait for the clip's end to say so. */
            private synchronized Ended awaitEnd() {
                while (ended == null) {
                    try {
                        wait();
                    } catch (InterruptedException ignored) {
                        // only the end of the clip lets this thread go
                    }
                }
                return ended;
            }

            @Override public void run() {
                MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
                int track = -1, wrote = 0;
                boolean finished = false, endQueued = false;
                String failure = null;
                long from = 0;
                try {
                    while (!finished) {
                        if (!endQueued && endAsked()) {
                            if (from == 0) from = SystemClock.elapsedRealtime();
                            int in = codec.dequeueInputBuffer(20_000);
                            if (in >= 0) {
                                codec.queueInputBuffer(in, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                                endQueued = true;
                            }
                        }
                        int out = codec.dequeueOutputBuffer(info, 20_000);
                        if (out == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                            track = muxer.addTrack(codec.getOutputFormat());
                            muxer.start();
                        } else if (out >= 0) {
                            if ((info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0 && info.size > 0 && track >= 0) {
                                muxer.writeSampleData(track, codec.getOutputBuffer(out), info);
                                wrote++;
                            }
                            codec.releaseOutputBuffer(out, false);
                            finished = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
                        }
                        if (from != 0 && SystemClock.elapsedRealtime() - from > 8000) break; // never for ever
                    }
                    codec.stop();
                    if (track >= 0) muxer.stop();
                    if (!finished) failure = "clip did not end";
                } catch (RuntimeException error) {
                    failure = "clip " + error;
                } finally {
                    codec.release();
                    try {
                        muxer.release();
                    } catch (RuntimeException ignored) {
                        // a muxer that never started
                    }
                }
                awaitEnd().done(wrote, clip.length(), failure);
            }
        }
    }
}
