package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;
import java.io.BufferedOutputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Locale;

/**
 * The head's turning speed for as long as the camera is open. It decides nothing: it is the evidence the capture
 * design lacked. The stillness gate looks at the 300 ms before a request and then stops listening, and the exposure
 * comes 0.3-0.7 s later; until 2026-11-14 nothing had recorded how a worn head moves while reading, or how the head
 * moved during a photo's own exposure.
 *
 * <p>The trace is {@code head-motion.bin} in the app's external files directory, which adb can read (the build is
 * not debuggable, so its private files cannot be pulled): records of a long sensor timestamp (ns, elapsedRealtime
 * base) and three floats (rad/s), big-endian. {@code scripts/head_motion_report.py} reads it.</p>
 */
final class HeadMotion {
    /** 200 Hz, the fastest rate an app gets without HIGH_SAMPLING_RATE_SENSORS. */
    static final int PERIOD_MICROS = 5_000;
    /** 1.90 mm lens over 1.0 um pixels (docs/hardware-measurements.md M-8). */
    static final float FOCAL_PIXELS = 1900f;
    static final String TRACE = "head-motion.bin";
    /** About 33 minutes of readings; a longer trace is dropped at the next start. */
    static final long TRACE_RESTART_BYTES = 8L << 20;
    static final long TRACE_LIMIT_BYTES = 12L << 20;
    /** Written out once a second: folding the temple arms force-stops the app without a close. */
    static final int FLUSH_RECORDS = 200;
    private static final String TAG = "DocScanGlassDoc";

    /** The readings inside one window. */
    static final class Span {
        final int samples;
        final float peak;
        final float mean;
        /** False when the window runs past the last reading held. */
        final boolean covered;

        Span(int samples, float peak, float mean, boolean covered) {
            this.samples = samples; this.peak = peak; this.mean = mean; this.covered = covered;
        }

        /** The smear of the fastest reading over one exposure, in sensor pixels. */
        float blurPixels(long exposureNanos) { return peak * (exposureNanos / 1e9f) * FOCAL_PIXELS; }
    }

    static final class Ring {
        private final long[] at;
        private final float[] speed;
        private int next;
        private int size;

        Ring(int capacity) { at = new long[capacity]; speed = new float[capacity]; }

        synchronized void add(long timestampNanos, float radPerSecond) {
            at[next] = timestampNanos; speed[next] = radPerSecond;
            next = (next + 1) % at.length;
            if (size < at.length) size++;
        }

        /** Both ends inclusive; null when no reading lies inside. */
        synchronized Span between(long fromNanos, long toNanos) {
            int samples = 0;
            float peak = 0;
            double sum = 0;
            long last = Long.MIN_VALUE;
            for (int i = 0; i < size; i++) {
                last = Math.max(last, at[i]);
                if (at[i] < fromNanos || at[i] > toNanos) continue;
                samples++;
                peak = Math.max(peak, speed[i]);
                sum += speed[i];
            }
            return samples == 0 ? null : new Span(samples, peak, (float) (sum / samples), last >= toNanos);
        }
    }

    private final SensorManager sensors;
    private final Sensor gyroscope;
    private final File trace;
    private final Ring ring = new Ring(2048); // about 10 s
    private HandlerThread thread;
    private Recording recording;

    HeadMotion(Context context) {
        sensors = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        gyroscope = sensors == null ? null : sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
        File shared = context.getExternalFilesDir(null);
        trace = new File(shared != null ? shared : context.getFilesDir(), TRACE);
    }

    /** From the camera's thread. Readings and the file stay on a thread of their own. */
    void start() {
        if (thread != null || gyroscope == null) return;
        thread = new HandlerThread("head-motion");
        thread.start();
        Handler handler = new Handler(thread.getLooper());
        recording = new Recording();
        handler.post(recording::open);
        sensors.registerListener(recording, gyroscope, PERIOD_MICROS, handler);
    }

    void stop() {
        if (thread == null) return;
        sensors.unregisterListener(recording);
        new Handler(thread.getLooper()).post(recording::close);
        thread.quitSafely();
        thread = null;
        recording = null;
    }

    /**
     * One opening of the camera. Each has its own stream, so the close of the one before, still queued on its own
     * thread when the camera is reopened at once (a pause and its resume), cannot close this one's.
     */
    private final class Recording implements SensorEventListener {
        private volatile DataOutputStream out;
        private long written;

        void open() {
            try {
                if (trace.length() > TRACE_RESTART_BYTES && !trace.delete()) return;
                written = trace.length();
                out = new DataOutputStream(new BufferedOutputStream(new FileOutputStream(trace, true), 1 << 16));
            } catch (IOException | RuntimeException unavailable) {
                Log.w(TAG, "head_motion trace unavailable " + unavailable.getClass().getSimpleName());
            }
        }

        void close() {
            DataOutputStream closing = out;
            out = null;
            if (closing == null) return;
            try { closing.close(); } catch (IOException ignored) { }
        }

        @Override public void onSensorChanged(SensorEvent event) {
            if (event.values.length < 3) return;
            float x = event.values[0];
            float y = event.values[1];
            float z = event.values[2];
            ring.add(event.timestamp, (float) Math.sqrt(x * x + y * y + z * z));
            DataOutputStream file = out;
            if (file == null || written >= TRACE_LIMIT_BYTES) return;
            try {
                file.writeLong(event.timestamp);
                file.writeFloat(x); file.writeFloat(y); file.writeFloat(z);
                written += 20;
                if (written / 20 % FLUSH_RECORDS == 0) file.flush();
            } catch (IOException failed) {
                close();
            }
        }

        @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }
    }

    /** The last second, for the once-a-second status line. */
    String describe(long nowNanos) {
        Span second = ring.between(nowNanos - 1_000_000_000L, nowNanos);
        return second == null ? "head_1s=none" : String.format(Locale.ROOT, "head_1s=%d mean_rad_s=%.3f peak_rad_s=%.3f",
                second.samples, second.mean, second.peak);
    }

    /** One line per photo: how the head turned while its rows were exposed. */
    void still(long generation, Long sensorTimestampNanos, Long exposureNanos, Long skewNanos) {
        if (thread == null || sensorTimestampNanos == null || exposureNanos == null) return;
        long window = exposureNanos + (skewNanos == null ? 0 : skewNanos);
        Span span = ring.between(sensorTimestampNanos, sensorTimestampNanos + window);
        Log.i(TAG, span == null ? "still_motion gen=" + generation + " samples=0 window_ms=" + window / 1_000_000
                : String.format(Locale.ROOT, "still_motion gen=%d samples=%d covered=%b window_ms=%d mean_rad_s=%.3f"
                        + " peak_rad_s=%.3f blur_px=%.1f", generation, span.samples, span.covered, window / 1_000_000,
                        span.mean, span.peak, span.blurPixels(exposureNanos)));
    }
}
