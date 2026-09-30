package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.SystemClock;

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
     * Calibration knob. At the measured 8-10ms exposure, 0.12 rad/s moves the
     * 4032px, roughly 70-degree frame about 4px, about 2px once ChatGPT fits
     * the image to 2048. Raise it if the shutter waits too long in practice.
     */
    static final float MOVING_RAD_S = 0.12f;
    static final long STILL_MILLIS = 300;
    /** Shoot anyway after this: the review still lets the operator retake. */
    static final long MAX_WAIT_MILLIS = 5000;

    private final SensorManager sensors;
    private final Sensor gyroscope;
    private volatile long movingAt;
    private long generation;

    Stillness(Context context) {
        sensors = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        gyroscope = sensors == null ? null : sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
    }

    static boolean ready(long now, long startedAt, long movingAt) {
        return now - movingAt >= STILL_MILLIS || now - startedAt >= MAX_WAIT_MILLIS;
    }

    /** Runs {@code then} on {@code handler} once still, or at once without a gyroscope. */
    void await(Handler handler, Runnable then) {
        long token = ++generation;
        if (gyroscope == null) {
            then.run();
            return;
        }
        long startedAt = SystemClock.elapsedRealtime();
        movingAt = startedAt; // a full STILL_MILLIS of readings is required
        sensors.registerListener(this, gyroscope, SensorManager.SENSOR_DELAY_GAME, handler);
        handler.postDelayed(new Runnable() {
            @Override public void run() {
                if (token != generation) return;
                if (ready(SystemClock.elapsedRealtime(), startedAt, movingAt)) {
                    sensors.unregisterListener(Stillness.this);
                    then.run();
                } else {
                    handler.postDelayed(this, 50);
                }
            }
        }, 50);
    }

    void cancel() {
        generation++;
        if (sensors != null) sensors.unregisterListener(this);
    }

    @Override
    public void onSensorChanged(SensorEvent event) {
        float x = event.values[0];
        float y = event.values[1];
        float z = event.values[2];
        if (x * x + y * y + z * z > MOVING_RAD_S * MOVING_RAD_S) {
            movingAt = SystemClock.elapsedRealtime();
        }
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {
    }
}
