package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.SystemClock;
import android.util.Log;
import dev.rokid.docscanglass.input.WearTransition;

/**
 * Watches the proximity sensor so putting the glasses back on brings the
 * session back.
 *
 * <p>The decision lives in {@link WearTransition}, which is plain Java and
 * tested; this is only the binding. The wakeup form of the sensor is preferred
 * because the display is asleep when the reading that matters arrives -- that
 * is the state {@link DisplaySleep} leaves behind.</p>
 */
final class WearWatch implements SensorEventListener {
    private static final String TAG = "WearWatch";

    interface OnWornAgain {
        void wornAgain();
    }

    private final SensorManager sensors;
    private final Sensor proximity;
    private final WearTransition transition = new WearTransition();
    private final OnWornAgain callback;

    WearWatch(Context context, OnWornAgain callback) {
        this.callback = callback;
        sensors = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        proximity = sensors == null ? null : sensors.getDefaultSensor(Sensor.TYPE_PROXIMITY, true);
    }

    /** @return false when this device exposes no proximity sensor to watch. */
    boolean start() {
        if (sensors == null || proximity == null) {
            Log.w(TAG, "no wakeup proximity sensor; re-wearing will not resume the session");
            return false;
        }
        return sensors.registerListener(this, proximity, SensorManager.SENSOR_DELAY_NORMAL);
    }

    void stop() {
        if (sensors != null) {
            sensors.unregisterListener(this);
        }
    }

    @Override
    public void onSensorChanged(SensorEvent event) {
        if (event.values.length > 0
                && transition.onReading(event.values[0], SystemClock.elapsedRealtime())) {
            callback.wornAgain();
        }
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {
        // Proximity reports near or far; accuracy carries nothing to act on.
    }
}
