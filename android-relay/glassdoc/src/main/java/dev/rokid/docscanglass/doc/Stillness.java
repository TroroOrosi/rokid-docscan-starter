package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.SystemClock;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;

/**
 * Holds the shutter until the head is still. 2026-09-30 on the glasses a
 * photo was taken while the operator was still moving: the fixed 1.5s
 * countdown before it measures time, not motion.
 *
 * <p>Registered only while waiting, so the gyroscope is off the rest of the
 * session.</p>
 */
final class Stillness implements SensorEventListener {
    /**
     * Retain the old angular-speed ceiling at exposures up to 10ms. Longer
     * preview exposures tighten it proportionally; this is a motion safeguard,
     * not a calibrated pixel-blur or character-readability guarantee.
     */
    static final float MOVING_RAD_S = 0.12f;
    static final long REFERENCE_EXPOSURE_NANOS = 10_000_000;
    static final long STILL_MILLIS = 300;
    private final SensorManager sensors;
    private final Sensor gyroscope;
    private volatile long movingAt;
    private volatile long observedAt = -1;
    private long quietSinceNanos;
    private float motionSquared = Float.POSITIVE_INFINITY;
    private float quietMotionSquared;
    private boolean retainMeasurements;
    private boolean measuring;
    private long measurementStartedAt;
    private long measurementStartedAtNanos;
    private long lastSensorTimestampNanos;
    private long generation;
    private LongSupplier exposureNanos = () -> 0;

    Stillness(Context context) {
        sensors = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        gyroscope = sensors == null ? null : sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
    }

    static boolean ready(long now, long startedAt, long movingAt) {
        return now >= startedAt && now >= movingAt && now - movingAt >= STILL_MILLIS;
    }

    /** Opt-in native A/B uses only readings already available; it never starts a second wait. */
    void retainMeasurements(boolean retain) { retainMeasurements = retain; }

    boolean readyNow() {
        long now = SystemClock.elapsedRealtime();
        float limit = motionLimit();
        return measuring && limit > 0 && fresh(now)
                && ready(now, measurementStartedAt, movingAt)
                && motionSquared <= limit * limit && quietMotionSquared <= limit * limit;
    }

    private boolean fresh(long now) {
        return observedAt >= measurementStartedAt && now >= observedAt
                && now - observedAt <= CameraReadiness.FRESH_MILLIS;
    }

    /** Keep measuring motion until the camera is also ready; elapsed wait never authorizes a shot. */
    void await(Handler handler, BooleanSupplier cameraReady, LongSupplier exposure, Runnable then) {
        long token = ++generation;
        exposureNanos = exposure;
        long startedAt = SystemClock.elapsedRealtime();
        measurementStartedAt = startedAt;
        measurementStartedAtNanos = SystemClock.elapsedRealtimeNanos();
        lastSensorTimestampNanos = 0;
        quietSinceNanos = measurementStartedAtNanos;
        movingAt = startedAt; // a full STILL_MILLIS of readings is required
        observedAt = -1;
        motionSquared = Float.POSITIVE_INFINITY;
        quietMotionSquared = 0;
        boolean measured = gyroscope != null
                && sensors.registerListener(this, gyroscope, SensorManager.SENSOR_DELAY_GAME, handler);
        measuring = measured;
        handler.postDelayed(new Runnable() {
            @Override public void run() {
                if (token != generation) return;
                long now = SystemClock.elapsedRealtime();
                float limit = motionLimit();
                if (limit <= 0 || (measured && (!fresh(now) || motionSquared > limit * limit
                        || quietMotionSquared > limit * limit))) {
                    movingAt = now;
                    quietSinceNanos = SystemClock.elapsedRealtimeNanos();
                    quietMotionSquared = 0;
                }
                if (limit > 0 && cameraReady.getAsBoolean() && (!measured || (fresh(now)
                        && ready(now, startedAt, movingAt)))) {
                    if (!retainMeasurements) {
                        if (sensors != null) sensors.unregisterListener(Stillness.this);
                        measuring = false;
                    }
                    then.run();
                } else {
                    handler.postDelayed(this, 50);
                }
            }
        }, 50);
    }

    void cancel() {
        generation++;
        exposureNanos = () -> 0;
        quietSinceNanos = 0;
        measuring = false;
        if (sensors != null) sensors.unregisterListener(this);
    }

    /** Only REALTIME camera timestamps may be compared with this measured interval. */
    long quietSinceNanos() { return quietSinceNanos; }

    private float motionLimit() {
        long exposure = exposureNanos.getAsLong();
        return exposure <= 0 ? 0 : (float)(MOVING_RAD_S
                * Math.min(1d, (double)REFERENCE_EXPOSURE_NANOS / exposure));
    }

    @Override
    public void onSensorChanged(SensorEvent event) {
        if (!measuring) return;
        long nowNanos = SystemClock.elapsedRealtimeNanos();
        // SensorEvent timestamps use elapsedRealtimeNanos. Queueing is not fresh motion evidence.
        if (event.timestamp <= 0 || event.timestamp > nowNanos) {
            invalidateMotion(nowNanos);
            return;
        }
        if (event.timestamp < measurementStartedAtNanos || event.timestamp <= lastSensorTimestampNanos) return;
        long previousTimestamp = lastSensorTimestampNanos;
        lastSensorTimestampNanos = event.timestamp;
        if (event.values.length < 3 || !Float.isFinite(event.values[0])
                || !Float.isFinite(event.values[1]) || !Float.isFinite(event.values[2])) {
            invalidateMotion(nowNanos);
            return;
        }
        // The retained optional-shot path has no polling loop after its first callback.
        if (previousTimestamp > 0 && event.timestamp - previousTimestamp
                > CameraReadiness.FRESH_MILLIS * 1_000_000L) invalidateMotion(nowNanos);
        observedAt = event.timestamp / 1_000_000L;
        float x = event.values[0];
        float y = event.values[1];
        float z = event.values[2];
        motionSquared = x * x + y * y + z * z;
        float limit = motionLimit();
        if (limit <= 0 || motionSquared > limit * limit) {
            movingAt = SystemClock.elapsedRealtime();
            quietSinceNanos = SystemClock.elapsedRealtimeNanos();
            quietMotionSquared = 0;
        } else {
            // Recheck this window against later exposure without resetting for harmless AE jitter.
            quietMotionSquared = Math.max(quietMotionSquared, motionSquared);
        }
    }

    private void invalidateMotion(long nowNanos) {
        movingAt = SystemClock.elapsedRealtime();
        quietSinceNanos = nowNanos;
        quietMotionSquared = 0;
        observedAt = -1;
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {
    }
}
