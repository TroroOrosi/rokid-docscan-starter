package dev.rokid.docscanglass.doc;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.SystemClock;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Log;
import dev.rokid.docscanglass.input.WearTransition;

/**
 * Watches the proximity sensor so putting the glasses back on brings the
 * session back.
 *
 * <p>The decision lives in {@link WearTransition}, which is plain Java and
 * tested; this is only the binding. The wakeup form of the sensor is preferred
 * because the display is asleep when the reading that matters arrives -- that
 * is the state the phone watcher requests after {@link DisplaySleep} releases
 * the app's display hold.</p>
 */
final class WearWatch implements SensorEventListener {
    private static final String TAG = "WearWatch";

    interface OnWornAgain {
        void wornAgain(boolean initial);
    }

    private final SensorManager sensors;
    private final Sensor proximity;
    private final WearTransition transition = new WearTransition();
    private final OnWornAgain callback;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final PowerManager.WakeLock settleLock;
    private final Runnable settle = this::confirm;
    private void confirm() {
        if (transition.confirm(SystemClock.elapsedRealtime())) callback.wornAgain(transition.initialWear());
        releaseSettleLock();
    }

    WearWatch(Context context, OnWornAgain callback) {
        this.callback = callback;
        sensors = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        proximity = sensors == null ? null : sensors.getDefaultSensor(Sensor.TYPE_PROXIMITY, true);
        PowerManager power = (PowerManager)context.getSystemService(Context.POWER_SERVICE);
        settleLock = power == null ? null : power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "docscan:wear-settle");
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
        handler.removeCallbacks(settle);
        releaseSettleLock();
        if (sensors != null) {
            sensors.unregisterListener(this);
        }
    }

    @Override
    public void onSensorChanged(SensorEvent event) {
        if (event.values.length == 0) return;
        long now = SystemClock.elapsedRealtime();
        if (transition.onReading(event.values[0], now)) callback.wornAgain(transition.initialWear());
        handler.removeCallbacks(settle);
        long delay = transition.delayUntilSettled(now);
        if (delay >= 0) {
            if (settleLock != null) { releaseSettleLock(); settleLock.acquire(delay + 500); }
            handler.postDelayed(settle, delay);
        } else releaseSettleLock();
    }

    private void releaseSettleLock() { if (settleLock != null && settleLock.isHeld()) settleLock.release(); }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {
        // Proximity reports near or far; accuracy carries nothing to act on.
    }
}
