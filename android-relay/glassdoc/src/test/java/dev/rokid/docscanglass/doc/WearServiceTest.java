package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.content.Intent;
import android.hardware.Sensor;
import android.os.Looper;
import android.provider.Settings;
import java.io.File;
import java.lang.reflect.Field;
import java.time.Duration;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import javax.crypto.KeyGenerator;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class) @Config(sdk = 32, manifest = Config.NONE)
public class WearServiceTest {
    private static void configure(WearService service, MockWebServer server) throws Exception {
        Settings.Secure.putString(service.getContentResolver(), Settings.Secure.ANDROID_ID, "wear-test-device");
        ConnectionSettings settings = new ConnectionSettings(new File(service.getFilesDir(), "wear-test-connection.bin"),
                KeyGenerator.getInstance("AES").generateKey());
        settings.save(server.url("/").toString(), "test-key");
        Field field = WearService.class.getDeclaredField("settings");
        field.setAccessible(true);
        field.set(service, settings);
    }
    private static void barrier(WearService service) throws Exception {
        Field field = WearService.class.getDeclaredField("network");
        field.setAccessible(true);
        ((ExecutorService)field.get(service)).submit(() -> {}).get(2, TimeUnit.SECONDS);
    }
    @Test public void ordinaryColdBootAndOneNearSamplePublishAnAuthenticatedFreshChooserWithoutLaunchingAnActivity() throws Exception {
        Sensor sensor = WearWatchTest.installWakeupSensor();
        PowerState power = PowerState.forContext(RuntimeEnvironment.getApplication());
        long bootGeneration = power.begin(0).generation;
        power.publish(bootGeneration, 7, "closed", "sleep", 1L);
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody("{}"));
            var lifecycle = Robolectric.buildService(WearService.class).create();
            WearService service = lifecycle.get();
            try {
                configure(service, server);
                service.onStartCommand(new Intent().putExtra(WearService.COLD_BOOT, true)
                        .putExtra("cold_generation", bootGeneration), 0, 1);
                WearWatchTest.reading(sensor, 0);
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
                RecordedRequest request = server.takeRequest(2, TimeUnit.SECONDS);
                assertNotNull("a single settled cold-near sample must reach the existing state API", request);
                assertEquals("/v1/glasses/state", request.getPath());
                assertEquals("Bearer test-key", request.getHeader("Authorization"));
                JSONObject body = new JSONObject(request.getBody().readUtf8());
                assertEquals(bootGeneration + 1, body.getLong("generation"));
                assertEquals("chooser", body.getString("entry_request"));
                assertEquals("wake", body.getString("display_request"));
                assertTrue(body.isNull("session_id"));
                assertTrue(body.isNull("ack_answer_revision"));
                assertNull(Shadows.shadowOf(RuntimeEnvironment.getApplication()).getNextStartedActivity());
                barrier(service);
                assertFalse(org.robolectric.shadows.ShadowPowerManager.getLatestWakeLock().isHeld());
                WearWatchTest.reading(sensor, 0);
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(5));
                assertEquals(1, server.getRequestCount());
            } finally { lifecycle.destroy(); }
        }
    }
    @Test public void initialNearCannotCancelASelectedCaptureButARealOffOnCrossingCanOpenTheChooser() throws Exception {
        Sensor sensor = WearWatchTest.installWakeupSensor();
        PowerState power = PowerState.forContext(RuntimeEnvironment.getApplication());
        long bootGeneration = power.begin(0).generation;
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(new MockResponse().setBody("{}"));
            var lifecycle = Robolectric.buildService(WearService.class).create();
            WearService service = lifecycle.get();
            try {
                configure(service, server);
                service.onStartCommand(new Intent().putExtra(WearService.COLD_BOOT, true)
                        .putExtra("cold_generation", bootGeneration), 0, 1);
                WearWatchTest.reading(sensor, 0);
                long capture = power.begin(bootGeneration).generation;
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
                assertEquals(capture, power.load().generation);
                assertEquals(0, server.getRequestCount());
                power.publish(capture, 7, "closed", "sleep");
                WearWatchTest.reading(sensor, 0);
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2));
                assertEquals("remaining worn never reopens a completed run", 0, server.getRequestCount());
                WearWatchTest.reading(sensor, 5);
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
                WearWatchTest.reading(sensor, 0);
                Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1));
                assertNotNull(server.takeRequest(2, TimeUnit.SECONDS));
                barrier(service);
                assertEquals(capture + 1, power.load().generation);
                assertEquals("chooser", power.load().entry);
                assertNull(Shadows.shadowOf(RuntimeEnvironment.getApplication()).getNextStartedActivity());
            } finally { lifecycle.destroy(); }
        }
    }
}
