package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CaptureLinkEventTest {
    @Test
    public void glassesStatusChangeRetainsOutstandingCapture() {
        CaptureLease lease = new CaptureLease();
        lease.begin(7);

        CaptureLinkEvent.GLASSES_STATUS_CHANGED.resetCaptureIfSafe(
                lease::resetAfterBindingReset);

        assertFalse(CaptureLinkEvent.GLASSES_STATUS_CHANGED.resetsCapture());
        assertTrue(lease.isUnresolved());
        assertEquals(7, lease.complete().pageIndex);
    }

    @Test
    public void serviceBindingResetReleasesOutstandingCapture() {
        CaptureLease lease = new CaptureLease();
        lease.begin(7);

        CaptureLinkEvent.SERVICE_BINDING_RESET.resetCaptureIfSafe(
                lease::resetAfterBindingReset);

        assertTrue(CaptureLinkEvent.SERVICE_BINDING_RESET.resetsCapture());
        assertFalse(lease.isUnresolved());
    }
}
