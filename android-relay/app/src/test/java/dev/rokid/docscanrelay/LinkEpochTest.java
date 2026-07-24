package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class LinkEpochTest {
    @Test
    public void callbacksAreRejectedUntilRegistrationCompletes() {
        LinkEpoch epochs = new LinkEpoch();
        long epoch = epochs.begin();

        assertTrue(epochs.isCurrent(epoch));
        assertFalse(epochs.isActive(epoch));
        assertTrue(epochs.activate(epoch));
        assertTrue(epochs.isActive(epoch));
    }

    @Test
    public void newBindingRejectsCallbacksFromTheOldBinding() {
        LinkEpoch epochs = new LinkEpoch();
        long oldEpoch = epochs.begin();
        assertTrue(epochs.activate(oldEpoch));

        long newEpoch = epochs.begin();
        assertFalse(epochs.isCurrent(oldEpoch));
        assertFalse(epochs.isActive(oldEpoch));
        assertFalse(epochs.invalidate(oldEpoch));

        assertTrue(epochs.activate(newEpoch));
        assertTrue(epochs.isActive(newEpoch));
    }

    @Test
    public void disconnectInvalidatesAlreadyQueuedCallbacks() {
        LinkEpoch epochs = new LinkEpoch();
        long epoch = epochs.begin();
        assertTrue(epochs.activate(epoch));

        assertTrue(epochs.invalidate(epoch));
        assertFalse(epochs.isCurrent(epoch));
        assertFalse(epochs.isActive(epoch));
    }

    @Test
    public void guardedActionOnlyRunsForTheActiveEpoch() {
        LinkEpoch epochs = new LinkEpoch();
        long oldEpoch = epochs.begin();
        assertTrue(epochs.activate(oldEpoch));
        boolean[] called = {false};

        assertTrue(epochs.runIfActive(oldEpoch, () -> called[0] = true));
        assertTrue(called[0]);

        called[0] = false;
        long currentEpoch = epochs.begin();
        assertTrue(epochs.activate(currentEpoch));
        assertFalse(epochs.runIfActive(oldEpoch, () -> called[0] = true));
        assertFalse(called[0]);
    }
}
