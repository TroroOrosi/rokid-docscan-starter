package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CaptureLeaseTest {
    @Test
    public void unresolvedCaptureRejectsOverlap() {
        CaptureLease lease = new CaptureLease();
        long first = lease.begin(3);

        assertTrue(first != CaptureLease.NO_TOKEN);
        assertEquals(CaptureLease.NO_TOKEN, lease.begin(4));
        assertTrue(lease.isUnresolved());
    }

    @Test
    public void timeoutStaysBlockedUntilTerminalCallback() {
        CaptureLease lease = new CaptureLease();
        long token = lease.begin(2);

        assertTrue(lease.markTimedOut(token));
        assertTrue(lease.isUnresolved());
        assertTrue(lease.isTimedOut());
        assertEquals(CaptureLease.NO_TOKEN, lease.begin(3));

        CaptureLease.Completion late = lease.complete();
        assertNotNull(late);
        assertEquals(2, late.pageIndex);
        assertTrue(late.lateAfterTimeout);
        assertFalse(lease.isUnresolved());
    }

    @Test
    public void normalCompletionCanBeUploaded() {
        CaptureLease lease = new CaptureLease();
        lease.begin(5);

        CaptureLease.Completion completion = lease.complete();
        assertNotNull(completion);
        assertEquals(5, completion.pageIndex);
        assertFalse(completion.lateAfterTimeout);
        assertNull(lease.complete());
    }

    @Test
    public void failedStartAndBindingResetBothReleaseLease() {
        CaptureLease lease = new CaptureLease();
        long first = lease.begin(0);
        assertTrue(lease.abortBeforeStart(first));
        assertFalse(lease.isUnresolved());

        long second = lease.begin(1);
        assertTrue(lease.markTimedOut(second));
        lease.resetAfterBindingReset();
        assertFalse(lease.isUnresolved());
        assertTrue(lease.begin(2) != CaptureLease.NO_TOKEN);
    }

    @Test
    public void staleTimeoutCannotPoisonNewCapture() {
        CaptureLease lease = new CaptureLease();
        long first = lease.begin(0);
        assertTrue(lease.abortBeforeStart(first));
        long second = lease.begin(1);

        assertFalse(lease.markTimedOut(first));
        assertFalse(lease.isTimedOut());
        assertTrue(lease.markTimedOut(second));
    }

    @Test
    public void unknownStartStaysBlockedUntilReconnect() {
        CaptureLease lease = new CaptureLease();
        long token = lease.begin(4);

        assertTrue(lease.markStartUnknown(token));
        assertTrue(lease.isUnresolved());
        assertTrue(lease.isTimedOut());
        assertEquals(CaptureLease.NO_TOKEN, lease.begin(5));

        lease.resetAfterBindingReset();
        assertFalse(lease.isUnresolved());
        assertTrue(lease.begin(5) != CaptureLease.NO_TOKEN);
    }
}
