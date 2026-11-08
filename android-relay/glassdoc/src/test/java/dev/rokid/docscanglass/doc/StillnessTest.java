package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;
import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
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
    private final AtomicLong exposureNanos = new AtomicLong(10_000_000L);
    @Before public void setup() {
        SensorManager manager = (SensorManager)RuntimeEnvironment.getApplication().getSystemService(Context.SENSOR_SERVICE);
        sensors = shadowOf(manager); sensors.addSensor(ShadowSensor.newInstance(Sensor.TYPE_GYROSCOPE));
        stillness = new Stillness(RuntimeEnvironment.getApplication());
    }
    private void motion(float speed, int readings) {
        for (int i = 0; i < readings; i++) {
            SensorEvent event = ShadowSensorManager.createSensorEvent(3);
            event.timestamp = SystemClock.elapsedRealtimeNanos();
            event.values[0] = speed; sensors.sendSensorEventToListeners(event);
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(50));
        }
    }
    @Test public void motionContinuesToBeMeasuredWhileWaitingForAutofocus() {
        AtomicBoolean focused = new AtomicBoolean();
        stillness.await(new Handler(Looper.getMainLooper()), focused::get, exposureNanos::get, shots::incrementAndGet);
        motion(0f, 10); assertEquals(0, shots.get());
        focused.set(true); motion(0.5f, 110); assertEquals(0, shots.get());
        motion(0f, 6); assertEquals(1, shots.get());
        assertFalse(sensors.hasListener(stillness));
    }
    @Test public void missingReadingsStayPendingAndCancelRemovesTheListener() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
        assertEquals(0, shots.get()); assertTrue(sensors.hasListener(stillness));
        stillness.cancel(); motion(0f, 10);
        assertEquals(0, shots.get()); assertFalse(sensors.hasListener(stillness));
    }
    @Test public void nonFiniteMotionDoesNotBecomeStillnessEvidence() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        motion(Float.NaN, 10); assertEquals(0, shots.get());
        stillness.cancel();
    }
    @Test public void aLongerExposureDoesNotReuseTheEarlierQuietWindow() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        motion(0.1f, 5); assertEquals(0, shots.get());
        exposureNanos.set(25_000_000L);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(50));
        assertEquals(0, shots.get());
        // A still-fresh sample that exceeds the new limit cannot age into permission.
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(350));
        assertEquals(0, shots.get());
        motion(0.1f, 8); assertEquals(0, shots.get());
        motion(0.02f, 6); assertEquals(1, shots.get());
    }
    @Test public void aShortExposureNeverLoosensTheExistingMotionCeiling() {
        exposureNanos.set(1_000_000L);
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        motion(0.2f, 20); assertEquals(0, shots.get());
        motion(0.1f, 6); assertEquals(1, shots.get());
    }
    @Test public void exposureJitterCannotKeepAStationaryHeadWaitingForever() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        for (int i = 0; i < 20; i++) {
            exposureNanos.set(i % 2 == 0 ? 25_000_000L : 25_010_000L);
            motion(0f, 1);
        }
        assertEquals(1, shots.get());
    }
    @Test public void aPreviousHigherSpeedInsideTheQuietWindowStillBlocksATighterLimit() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        motion(0.1f, 3); motion(0.02f, 1);
        exposureNanos.set(25_000_000L);
        motion(0.02f, 3); assertEquals(0, shots.get());
        motion(0.02f, 4); assertEquals(1, shots.get());
    }
    @Test public void absentExposureRequiresANewQuietWindowAfterRecovery() {
        exposureNanos.set(0);
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        motion(0f, 12); assertEquals(0, shots.get());
        exposureNanos.set(25_000_000L);
        motion(0f, 4); assertEquals(0, shots.get());
        motion(0f, 2); assertEquals(1, shots.get());
    }

    @Test public void sourceExposureCannotReuseTheQuietIntervalFromBeforeMovementOrCancel() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> false, exposureNanos::get, shots::incrementAndGet);
        motion(0f, 8);
        long first = stillness.quietSinceNanos();
        assertTrue(first > 0);
        motion(0.5f, 1);
        assertTrue(stillness.quietSinceNanos() > first);
        stillness.cancel();
        assertEquals(0, stillness.quietSinceNanos());
        stillness.await(new Handler(Looper.getMainLooper()), () -> false, exposureNanos::get, shots::incrementAndGet);
        assertTrue(stillness.quietSinceNanos() > first);
    }

    @Test public void optionalShotUsesRetainedFreshMeasurementsWithoutStartingAnotherWait() {
        stillness.retainMeasurements(true);
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        motion(0f, 10); assertEquals(1, shots.get()); assertTrue(sensors.hasListener(stillness));
        assertTrue(stillness.readyNow());
        motion(0.5f, 1); assertFalse(stillness.readyNow());
        motion(0f, 6); assertTrue(stillness.readyNow());
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(CameraReadiness.FRESH_MILLIS + 1));
        assertFalse(stillness.readyNow());
        stillness.cancel(); assertFalse(stillness.readyNow()); assertFalse(sensors.hasListener(stillness));
    }

    private void sampleAt(long timestamp, float speed) {
        SensorEvent event = ShadowSensorManager.createSensorEvent(3);
        event.timestamp = timestamp;
        event.values[0] = speed;
        sensors.sendSensorEventToListeners(event);
    }

    @Test public void delayedDeliveryCannotRefreshAnExpiredMotionSample() {
        AtomicBoolean focused = new AtomicBoolean();
        stillness.await(new Handler(Looper.getMainLooper()), focused::get, exposureNanos::get, shots::incrementAndGet);
        motion(0f, 10);
        long recordedAt = SystemClock.elapsedRealtimeNanos();
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(CameraReadiness.FRESH_MILLIS + 1));
        focused.set(true);
        sampleAt(recordedAt, 0f);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(50));
        assertEquals("the callback time is not the measurement time", 0, shots.get());
        motion(0f, 8);
        assertEquals(1, shots.get());
    }

    @Test public void previousPreparationAndInvalidTimestampsCannotAuthorizeAStill() {
        long previous = SystemClock.elapsedRealtimeNanos();
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        for (int i = 0; i < 10; i++) {
            sampleAt(previous + i, 0f);
            sampleAt(0, 0f);
            sampleAt(-1, 0f);
            sampleAt(SystemClock.elapsedRealtimeNanos() + 1_000_000_000L, 0f);
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(50));
        }
        assertEquals(0, shots.get());
        motion(0f, 8);
        assertEquals(1, shots.get());
    }

    @Test public void duplicateAndReversedSamplesCannotReplaceNewerMovement() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        long movingTimestamp = SystemClock.elapsedRealtimeNanos();
        sampleAt(movingTimestamp, 0.5f);
        for (int i = 0; i < 10; i++) {
            sampleAt(movingTimestamp, 0f);
            sampleAt(movingTimestamp - 1, 0f);
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(50));
        }
        assertEquals(0, shots.get());
        motion(0f, 8);
        assertEquals(1, shots.get());
    }

    @Test public void retainedMotionUsesTheMeasurementTimestampForFreshness() {
        stillness.retainMeasurements(true);
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        motion(0f, 10);
        assertEquals(1, shots.get());
        long recordedAt = SystemClock.elapsedRealtimeNanos();
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(CameraReadiness.FRESH_MILLIS + 1));
        sampleAt(recordedAt, 0f);
        assertFalse(stillness.readyNow());
        motion(0f, 1);
        assertFalse("retained sampling must recover its quiet interval", stillness.readyNow());
        motion(0f, 8);
        assertTrue(stillness.readyNow());
    }

    @Test public void missingMeasurementsRestartTheQuietWindowAfterRecovery() {
        AtomicBoolean focused = new AtomicBoolean();
        stillness.await(new Handler(Looper.getMainLooper()), focused::get, exposureNanos::get, shots::incrementAndGet);
        motion(0f, 10);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
        focused.set(true);
        motion(0f, 1);
        assertEquals("unobserved time cannot establish a quiet interval", 0, shots.get());
        motion(0f, 7);
        assertEquals(1, shots.get());
    }

    @Test public void aRepeatedInvalidSampleCannotBecomeValidMotionEvidence() {
        stillness.await(new Handler(Looper.getMainLooper()), () -> true, exposureNanos::get, shots::incrementAndGet);
        long timestamp = SystemClock.elapsedRealtimeNanos();
        sampleAt(timestamp, Float.NaN);
        for (int i = 0; i < 8; i++) {
            sampleAt(timestamp, 0f);
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(50));
        }
        assertEquals(0, shots.get());
        motion(0f, 8);
        assertEquals(1, shots.get());
    }
}
