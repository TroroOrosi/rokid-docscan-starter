package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.Test;

public class CaptureLinkCoordinatorTest {
    @Test
    public void glassesStatusReconnectRetainsBothGuardsUntilTerminalCallback() {
        AtomicBoolean photoInFlight = new AtomicBoolean(true);
        CaptureLease lease = new CaptureLease();
        lease.begin(7);
        boolean[] linkReady = {true};
        CaptureLinkCoordinator coordinator = new CaptureLinkCoordinator(
                () -> photoInFlight.set(false),
                (ready, event) -> {
                    linkReady[0] = ready;
                    event.resetCaptureIfSafe(lease::resetAfterBindingReset);
                });

        coordinator.glassesStatusChanged(false);
        assertFalse(linkReady[0]);
        coordinator.glassesStatusChanged(true);

        assertTrue(linkReady[0]);
        assertTrue(photoInFlight.get());
        assertTrue(lease.isUnresolved());

        assertTrue(photoInFlight.compareAndSet(true, false));
        CaptureLease.Completion completion = lease.complete();
        assertEquals(7, completion.pageIndex);
        assertFalse(lease.isUnresolved());
    }

    @Test
    public void bindingResetReleasesBothGuardsAndRejectsOldEpochCallbacks() {
        AtomicBoolean photoInFlight = new AtomicBoolean(true);
        CaptureLease lease = new CaptureLease();
        lease.begin(3);
        LinkEpoch callbackEpochs = new LinkEpoch();
        long oldEpoch = callbackEpochs.begin();
        assertTrue(callbackEpochs.activate(oldEpoch));
        CaptureLinkCoordinator coordinator = new CaptureLinkCoordinator(
                () -> photoInFlight.set(false),
                (ready, event) ->
                        event.resetCaptureIfSafe(lease::resetAfterBindingReset));

        callbackEpochs.invalidateCurrent();
        coordinator.serviceBindingReset(false);

        assertFalse(photoInFlight.get());
        assertFalse(lease.isUnresolved());

        assertTrue(photoInFlight.compareAndSet(false, true));
        assertTrue(lease.begin(4) != CaptureLease.NO_TOKEN);
        long currentEpoch = callbackEpochs.begin();
        assertTrue(callbackEpochs.activate(currentEpoch));

        assertFalse(callbackEpochs.runIfActive(oldEpoch, () -> {
            photoInFlight.compareAndSet(true, false);
            lease.complete();
        }));
        assertTrue(photoInFlight.get());
        assertTrue(lease.isUnresolved());

        assertTrue(callbackEpochs.runIfActive(currentEpoch, () -> {
            photoInFlight.compareAndSet(true, false);
            lease.complete();
        }));
        assertFalse(photoInFlight.get());
        assertFalse(lease.isUnresolved());
    }
}
