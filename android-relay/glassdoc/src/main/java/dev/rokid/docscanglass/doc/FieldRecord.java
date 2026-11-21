package dev.rokid.docscanglass.doc;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * What the whole-field watch saw, kept for a worn pass (register 2-59): a quarter-size picture at most five times a
 * second (about four on the glasses, whose watch gives fifteen), each with its times and the number of clips begun so
 * far, so that a recording can be laid beside the clips made in it. Never part of a use: only a launch that asks for
 * it writes one ({@code --ez watch_record true}).
 *
 * <p>The file is records of one size and nothing else, so a later start adds to it: wall-clock millis (8 bytes),
 * the frame's sensor time in ns (8), clips begun (4), then {@link #WIDTH} x {@link #HEIGHT} bytes of brightness, rows
 * top to bottom as the sensor gives them (not turned upright).
 *
 * <p>The camera's thread only copies: the storage is written on the writer's thread, and while it has not taken the
 * last frame the next is dropped. Closing a clip's file has stalled this storage for seconds (register 2-51), and a
 * camera thread that waits for it loses the camera.
 */
final class FieldRecord {
    static final int WIDTH = 320, HEIGHT = 240;
    static final int RECORD_BYTES = 20 + WIDTH * HEIGHT;
    static final long MIN_GAP_MILLIS = 200;
    /** About thirteen minutes of watching. */
    static final long MAX_BYTES = 300L << 20;

    private final File file;
    private final Executor writer;
    private final long maxBytes;
    private final byte[] record = new byte[RECORD_BYTES];
    private final AtomicBoolean busy = new AtomicBoolean();
    private volatile boolean stopped;
    private long bytes;
    private long lastAt = Long.MIN_VALUE / 2;
    private FileOutputStream out;

    FieldRecord(File file, Executor writer, long maxBytes) {
        this.file = file;
        this.writer = writer;
        this.maxBytes = maxBytes;
        this.bytes = file.length();
    }

    /**
     * From the one thread that handles watch frames. {@code luma} is a frame of {@code width} x {@code height} with
     * {@code row} bytes a row and {@code step} bytes a pixel. False: not kept (too soon, the storage is behind, the
     * limit is reached, or the record has ended).
     */
    boolean offer(byte[] luma, int width, int height, int row, int step, long wallMillis, long sensorNanos, int clipsBegun, long nowMillis) {
        if (stopped || nowMillis - lastAt < MIN_GAP_MILLIS || bytes + RECORD_BYTES > maxBytes) return false;
        if (!busy.compareAndSet(false, true)) return false;
        lastAt = nowMillis;
        bytes += RECORD_BYTES;
        ByteBuffer.wrap(record).putLong(wallMillis).putLong(sensorNanos).putInt(clipsBegun);
        for (int y = 0; y < HEIGHT; y++) {
            int from = y * height / HEIGHT * row, to = 20 + y * WIDTH;
            for (int x = 0; x < WIDTH; x++) record[to + x] = luma[from + x * width / WIDTH * step];
        }
        try {
            writer.execute(this::write);
        } catch (RejectedExecutionException closed) {
            stopped = true;
            busy.set(false);
            return false;
        }
        return true;
    }

    private void write() {
        try {
            if (out == null) out = new FileOutputStream(file, true);
            out.write(record);
        } catch (IOException | RuntimeException error) {
            stopped = true; // the record ends; the capture goes on
        } finally {
            busy.set(false);
        }
    }

    void close() {
        stopped = true;
        try {
            writer.execute(() -> {
                try {
                    if (out != null) out.close();
                } catch (IOException ignored) {
                    // nothing more can be done for a record
                }
                out = null;
            });
        } catch (RejectedExecutionException ignored) {
            // the writer has already ended
        }
        if (writer instanceof ExecutorService) ((ExecutorService) writer).shutdown(); // what was handed over is still written
    }
}
