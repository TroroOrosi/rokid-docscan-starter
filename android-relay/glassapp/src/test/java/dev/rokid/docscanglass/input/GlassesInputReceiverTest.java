package dev.rokid.docscanglass.input;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.Test;

public class GlassesInputReceiverTest {

    @Test
    public void registersAndUnregistersPlatformReceiverExactlyOnce() {
        GlassesInputReceiver receiver = new GlassesInputReceiver(signal -> { });
        AtomicInteger registrations = new AtomicInteger();
        AtomicInteger unregistrations = new AtomicInteger();

        assertTrue(receiver.register(registrations::incrementAndGet));
        assertFalse(receiver.register(registrations::incrementAndGet));
        assertTrue(receiver.registered());
        assertEquals(1, registrations.get());

        assertTrue(receiver.unregister(unregistrations::incrementAndGet));
        assertFalse(receiver.unregister(unregistrations::incrementAndGet));
        assertFalse(receiver.registered());
        assertEquals(1, unregistrations.get());
    }

    @Test
    public void failedRegistrationDoesNotClaimToBeRegistered() {
        GlassesInputReceiver receiver = new GlassesInputReceiver(signal -> { });

        assertThrows(IllegalStateException.class, () -> receiver.register(() -> {
            throw new IllegalStateException("platform refused registration");
        }));

        assertFalse(receiver.registered());
    }

    @Test
    public void deliversOfficialAndUnknownSignalsOnlyWhileRegistered() {
        List<InputSignal> signals = new ArrayList<>();
        GlassesInputReceiver receiver = new GlassesInputReceiver(signals::add);

        receiver.accept(1, "com.android.action.ACTION_AI_START");
        receiver.register(() -> { });
        receiver.accept(2, "com.android.action.ACTION_AI_START");
        receiver.accept(3, "future.action");
        receiver.unregister(() -> { });
        receiver.accept(4, "com.android.action.ACTION_AI_START");

        assertEquals(2, signals.size());
        assertTrue(signals.get(0).known());
        assertFalse(signals.get(1).known());
        assertEquals("future.action", signals.get(1).name());
    }
}
