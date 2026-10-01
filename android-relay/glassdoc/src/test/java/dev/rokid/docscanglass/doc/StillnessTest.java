package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;
import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.Looper;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowSensor;
import org.robolectric.shadows.ShadowSensorManager;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class StillnessTest {
    private Stillness stillness;
    private ShadowSensorManager sensors;
    private final AtomicInteger shots = new AtomicInteger();
    @Before public void setup() {
        SensorManager manager = (SensorManager)RuntimeEnvironment.getApplication().getSystemService(Context.SENSOR_SERVICE);
        sensors = shadowOf(manager); sensors.addSensor(ShadowSensor.newInstance(Sensor.TYPE_GYROSCOPE));
        stillness = new Stillness(RuntimeEnvironment.getApplication());
    }
    private void motion(float speed, int readings) {
        for (int i = 0; i < readings; i++) {
            SensorEvent event = ShadowSensorManager.createSensorEvent(3);
            event.values[0] = speed; sensors.sendSensorEventToListeners(event);
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(50));
        }
    }
    @Test public void motionContinuesToBeMeasuredWhileWaitingForAutofocus() {
        AtomicBoolean focused = new AtomicBoolean();
        stillness.await(new Handler(Looper.getMainLooper()), focused::get, shots::incrementAndGet);
        motion(0f, 10); assertEquals(0, shots.get());
        focused.set(true); motion(0.5f, 110); assertEquals(0, shots.get());
        motion(0f, 6); assertEquals(1, shots.get());
        assertFalse(sensors.hasListener(stillness));
    }
    @Test public void missingReadingsStayPendingAndCancelRemovesTheListener() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, shots::incrementAndGet);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
        assertEquals(0, shots.get()); assertTrue(sensors.hasListener(stillness));
        stillness.cancel(); motion(0f, 10);
        assertEquals(0, shots.get()); assertFalse(sensors.hasListener(stillness));
    }
    @Test public void nonFiniteMotionDoesNotBecomeStillnessEvidence() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, shots::incrementAndGet);
        motion(Float.NaN, 10); assertEquals(0, shots.get());
        stillness.cancel();
    }
}
