package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorManager;
import android.os.Looper;
import android.os.PowerManager;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowPowerManager;
import org.robolectric.shadows.ShadowSensor;
import org.robolectric.shadows.ShadowSensorManager;

@RunWith(RobolectricTestRunner.class) @Config(sdk = 32, manifest = Config.NONE)
public class WearWatchTest {
    static Sensor installWakeupSensor() {
        Sensor sensor = ShadowSensor.newInstance(Sensor.TYPE_PROXIMITY);
        Shadows.shadowOf(sensor).setWakeUpFlag(true);
        SensorManager manager = RuntimeEnvironment.getApplication().getSystemService(SensorManager.class);
        Shadows.shadowOf(manager).addSensor(sensor);
        return sensor;
    }
    static void reading(Sensor sensor, float distance) {
        SensorEvent event = ShadowSensorManager.createSensorEvent(1);
        event.sensor = sensor;
        event.values[0] = distance;
        SensorManager manager = RuntimeEnvironment.getApplication().getSystemService(SensorManager.class);
        Shadows.shadowOf(manager).sendSensorEventToListeners(event, sensor);
    }
    @Test public void oneOnChangeSampleSettlesOnceAndDoesNotHoldTheCpuWhileWaiting() {
        Sensor sensor = installWakeupSensor();
        List<Boolean> events = new ArrayList<>();
        WearWatch watch = new WearWatch(RuntimeEnvironment.getApplication(), events::add);
        assertTrue(watch.start());
        try {
            reading(sensor, 0);
            PowerManager.WakeLock settle = ShadowPowerManager.getLatestWakeLock();
            assertTrue(settle.isHeld());
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(999));
            assertTrue(events.isEmpty());
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(1));
            assertEquals(List.of(true), events);
            assertFalse(settle.isHeld());
            reading(sensor, 0);
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(10));
            assertEquals(1, events.size());
            reading(sensor, 5);
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
            reading(sensor, 0);
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
            assertEquals(List.of(true, false), events);
            assertFalse(settle.isHeld());
        } finally { watch.stop(); }
    }
    @Test public void stoppingCancelsThePendingWearAndUnregistersTheSensor() {
        Sensor sensor = installWakeupSensor();
        List<Boolean> events = new ArrayList<>();
        WearWatch watch = new WearWatch(RuntimeEnvironment.getApplication(), events::add);
        assertTrue(watch.start());
        reading(sensor, 0);
        watch.stop();
        Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2));
        assertTrue(events.isEmpty());
        assertFalse(ShadowPowerManager.getLatestWakeLock().isHeld());
        assertFalse(Shadows.shadowOf(RuntimeEnvironment.getApplication().getSystemService(SensorManager.class)).hasListener(watch));
    }
    @Test public void aNonWakeupSensorCannotPretendToSupportWearWhileTheDisplaySleeps() {
        Sensor sensor = ShadowSensor.newInstance(Sensor.TYPE_PROXIMITY);
        Shadows.shadowOf(RuntimeEnvironment.getApplication().getSystemService(SensorManager.class)).addSensor(sensor);
        WearWatch watch = new WearWatch(RuntimeEnvironment.getApplication(), ignored -> fail("unsupported wear"));
        assertFalse(watch.start());
        watch.stop();
    }
}
