package dev.rokid.docscanrelay;

import android.os.SystemClock;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * The record of a use that outlives logcat. Logcat is lost when the glasses restart, and was, twice, before the
 * records of a use had been pulled (2026-11-17, 2026-11-18). Every line given here goes to logcat as before and to
 * {@code use-log.txt} in the directory named at the app's start (its external files directory, which adb can read):
 * {@code <epoch millis> <elapsedRealtime millis> <tag> <message>}. Past 4 MB the file becomes {@code use-log.1.txt}
 * (replacing the one before) and a new one is begun.
 *
 * <p>The caller only hands a line over: it never waits, and nothing is thrown at it, from whichever thread. One
 * thread does all the file work. It writes each line out at once and never syncs: a sync can wait behind a clip's
 * tens of megabytes on the same storage, and a stalled storage is how this app loses frames. Lines that find 2000
 * already waiting are dropped and counted, and the count is written before the next line that is taken. Without a
 * directory, or when its file cannot be opened or written, logcat is all there is.</p>
 *
 * <p>A line holds names, counts, sizes, durations, indexes and exception class names only: never image bytes, text
 * read from a paper, an answer, a key or a server's address. {@link #head} and {@link #failure} are for the two
 * places where text the app did not write could get in.</p>
 */
public final class UseLog {
    public static final String FILE = "use-log.txt";
    static final String OLDER = "use-log.1.txt";
    static final long ROTATE_BYTES = 4L << 20;
    static final int MAX_WAITING = 2000;
    private static final UseLog SHARED = new UseLog(ROTATE_BYTES, MAX_WAITING);

    private final long rotateBytes;
    private final ThreadPoolExecutor writer;
    private final AtomicInteger dropped = new AtomicInteger();
    // The writer's thread only.
    private File directory;
    private FileOutputStream out;
    private long written;
    private boolean unavailable;

    /** Where the file is kept from here on; asked for again with the same directory, nothing changes. */
    public static void open(File directory) { SHARED.use(directory); }

    public static void i(String tag, String message) {
        try { Log.i(tag, message); } catch (RuntimeException ignored) { /* no logcat off the device */ }
        SHARED.line(tag, message);
    }

    public static void w(String tag, String message) {
        try { Log.w(tag, message); } catch (RuntimeException ignored) { /* no logcat off the device */ }
        SHARED.line(tag, message);
    }

    /** The file alone: for a line whose logcat form holds more than the file may. */
    public static void file(String tag, String message) { SHARED.line(tag, message); }

    /**
     * A controller's diagnostic up to its first ": ". The message of an exception is always appended behind one, and
     * such a message can name a server or quote its reply; what stands before is the app's own wording and numbers.
     */
    public static String head(String diagnostic) {
        if (diagnostic == null) return "";
        int cut = diagnostic.indexOf(": ");
        return cut < 0 ? diagnostic : diagnostic.substring(0, cut);
    }

    /** How a call failed, without its message: the HTTP status, or the exception's class. */
    public static String failure(Throwable error) {
        return error instanceof DocScanApi.ApiException ? "http_" + ((DocScanApi.ApiException) error).getStatusCode()
                : "io_" + error.getClass().getSimpleName();
    }

    /** The megabytes that can still be written under this directory; -1 without one. The system says 0 when it cannot tell. */
    public static long freeMegabytes(File directory) {
        try { return directory == null ? -1 : directory.getUsableSpace() >> 20; }
        catch (RuntimeException unknown) { return -1; }
    }

    UseLog(long rotateBytes, int maxWaiting) {
        this.rotateBytes = rotateBytes;
        writer = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS, new LinkedBlockingQueue<>(maxWaiting), work -> {
            Thread thread = new Thread(work, "use-log");
            thread.setDaemon(true);
            return thread;
        });
    }

    void use(File next) {
        run(() -> {
            if (next == null || next.equals(directory)) return;
            close();
            directory = next;
            unavailable = false;
        });
    }

    void line(String tag, String message) {
        long wall = System.currentTimeMillis(), elapsed = elapsed();
        int lost = dropped.getAndSet(0); // said before the first line that is taken again
        try {
            writer.execute(() -> {
                if (lost > 0) write(wall + " " + elapsed + " UseLog dropped=" + lost);
                write(wall + " " + elapsed + " " + tag + " " + String.valueOf(message).replace('\n', ' ').replace('\r', ' '));
            });
        } catch (RejectedExecutionException full) {
            dropped.addAndGet(lost + 1);
        }
    }

    /** Hands the writer's thread a task of its own; false when too much is waiting. */
    boolean run(Runnable task) {
        try {
            writer.execute(task);
            return true;
        } catch (RejectedExecutionException full) {
            return false;
        }
    }

    /** Tests: until everything handed over so far has been written. */
    void await() throws InterruptedException {
        CountDownLatch reached = new CountDownLatch(1);
        while (!run(reached::countDown)) Thread.sleep(1);
        reached.await();
    }

    private static long elapsed() {
        try { return SystemClock.elapsedRealtime(); }
        catch (RuntimeException offDevice) { return System.nanoTime() / 1_000_000; }
    }

    private void write(String line) {
        if (directory == null || unavailable) return;
        try {
            if (out == null) {
                File file = new File(directory, FILE);
                out = new FileOutputStream(file, true);
                written = file.length();
            }
            byte[] bytes = (line + "\n").getBytes(StandardCharsets.UTF_8);
            out.write(bytes);
            out.flush(); // handed to the system, not synced: see the class comment
            written += bytes.length;
            if (written > rotateBytes) {
                close();
                File older = new File(directory, OLDER), current = new File(directory, FILE);
                older.delete();
                if (!current.renameTo(older)) current.delete(); // it cannot be kept: begun anew all the same
            }
        } catch (IOException | RuntimeException failed) {
            close();
            unavailable = true;
        }
    }

    private void close() {
        FileOutputStream closing = out;
        out = null;
        if (closing == null) return;
        try { closing.close(); } catch (IOException ignored) { }
    }
}
