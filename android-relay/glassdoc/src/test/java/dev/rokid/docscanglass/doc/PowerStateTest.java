package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import android.content.Context;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.Executors;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class) @Config(sdk = 32, manifest = Config.NONE)
public class PowerStateTest {
    @Test public void initialSynchronizationNeverRestartsCaptureOrACompletedSession() throws Exception {
        PowerState store = new PowerState(RuntimeEnvironment.getApplication().getSharedPreferences("wear-test", Context.MODE_PRIVATE));
        PowerState.Snapshot capture = store.begin(0);
        assertNull(store.wear(true, -1));
        store.publish(capture.generation, 7, "closed", "sleep");
        assertNull(store.wear(true, -1));
        store.publish(capture.generation, 0, "chooser", "sleep");
        PowerState.Snapshot chooser = store.wear(true, -1);
        assertEquals("chooser", chooser.entry);
        assertEquals(0, chooser.session);
        assertTrue(chooser.generation > capture.generation);
        assertNull("an old Activity cannot overwrite the service's new wear generation",
                store.publish(capture.generation, 7, "reading", "wake"));
        assertEquals(chooser.generation, store.load().generation);
    }
    @Test public void coldAlreadyWornEntryOnlyUsesTheGenerationThatBootActuallyStarted() throws Exception {
        PowerState store = new PowerState(RuntimeEnvironment.getApplication().getSharedPreferences("cold-wear-test", Context.MODE_PRIVATE));
        long beforeBoot = store.begin(0).generation;
        store.publish(beforeBoot, 7, "closed", "sleep");
        assertNotNull(store.wear(true, beforeBoot));
        long secondBoot = store.load().generation;
        store.begin(secondBoot); // the operator has selected capture before the first sensor settles
        assertNull(store.wear(true, secondBoot));
        assertNotNull("a real off/on crossing may return from any phase", store.wear(false, -1));
    }
    @Test public void activityAndServiceAllocateDistinctGenerationsEvenConcurrently() throws Exception {
        android.content.SharedPreferences preferences = RuntimeEnvironment.getApplication().getSharedPreferences("parallel-power-test", Context.MODE_PRIVATE);
        PowerState activity = new PowerState(preferences), service = new PowerState(preferences);
        var pool = Executors.newFixedThreadPool(2);
        try {
            Set<Long> generations = new HashSet<>();
            for (int run = 0; run < 30; run++) {
                var a = pool.submit(() -> activity.begin(0).generation);
                var b = pool.submit(() -> service.wear(false, -1).generation);
                assertTrue(generations.add(a.get()));
                assertTrue(generations.add(b.get()));
            }
            assertEquals(60, generations.size());
        } finally { pool.shutdownNow(); }
    }
}
