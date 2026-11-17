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
    @Test public void wearingAgainWhileAReadingIsInHandChangesNothing() throws Exception {
        // Register 1-26: far for a second and near for a second, at any moment, advanced the generation and opened the
        // chooser: a capture was cut, answers on their way never woke the glasses, a reader was left. The sensor has
        // read "far" on a worn head (M-31), so this needs no hand.
        PowerState store = new PowerState(RuntimeEnvironment.getApplication().getSharedPreferences("wear-in-hand", Context.MODE_PRIVATE));
        PowerState.Snapshot capture = store.begin(0);
        for (String phase : new String[] {"capturing", "analyzing", "waiting", "reading"}) {
            store.publish(capture.generation, 7, phase, "wake");
            assertNull(phase, store.wearEntry(false, -1, true));
            assertEquals(phase, capture.generation, store.load().generation);
            assertEquals(phase, store.load().phase);
        }
        for (String phase : new String[] {"writing_done", "closed", "chooser"}) {
            store.publish(store.load().generation, 0, phase, "sleep");
            PowerState.Snapshot entry = store.wearEntry(false, -1, true);
            assertEquals(phase, "chooser", entry.entry);
        }
    }

    @Test public void aPhaseLeftBehindByAnAppThatIsGoneDoesNotKeepTheChooserAway() throws Exception {
        PowerState store = new PowerState(RuntimeEnvironment.getApplication().getSharedPreferences("wear-left", Context.MODE_PRIVATE));
        PowerState.Snapshot capture = store.begin(0);
        assertEquals("no screen of the app is alive: what the phase says is left over",
                "chooser", store.wearEntry(false, -1, false).entry);
        PowerState.Snapshot again = store.begin(0);
        assertEquals("the first wear after the glasses started", "chooser", store.wearEntry(true, again.generation, true).entry);
        assertTrue(store.load().generation > capture.generation);
    }

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
