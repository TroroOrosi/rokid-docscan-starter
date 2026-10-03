package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static android.hardware.camera2.CameraMetadata.*;
import org.junit.Test;

/** Metering evidence is not a certificate that every printed character is readable. */
public class CameraReadinessTest {
    private CameraReadiness autoFocus() {
        return new CameraReadiness(new int[]{CONTROL_AF_MODE_OFF, CONTROL_AF_MODE_AUTO,
                CONTROL_AF_MODE_CONTINUOUS_PICTURE}, 8f, new int[]{CONTROL_AE_MODE_ON});
    }

    @Test public void convergedFocusAndExposureMustBeFresh() {
        CameraReadiness readiness = autoFocus();
        assertEquals(CONTROL_AF_MODE_CONTINUOUS_PICTURE, readiness.afMode);
        assertFalse(readiness.ready(1000));
        readiness.observe(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, 1000);
        assertTrue(readiness.ready(1000));
        assertFalse(readiness.ready(1501));
        assertFalse(readiness.ready(999));
    }

    @Test public void elapsedTimeNeverOverridesScanningOrUnfocusedResults() {
        CameraReadiness readiness = autoFocus();
        readiness.observe(CONTROL_AF_STATE_PASSIVE_SCAN, CONTROL_AE_STATE_CONVERGED, 60000);
        assertFalse(readiness.ready(60000));
        readiness.observe(CONTROL_AF_STATE_NOT_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED, 60001);
        assertFalse(readiness.ready(60001));
        readiness.observe(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_SEARCHING, 60002);
        assertFalse(readiness.ready(60002));
        readiness.observe(null, null, 60003);
        assertFalse(readiness.ready(60003));
    }

    @Test public void aDarkFlashRequiredResultCannotPassTheNoFlashExposureGate() {
        CameraReadiness readiness = autoFocus();
        readiness.observe(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_FLASH_REQUIRED, 1000);
        assertFalse(readiness.ready(1000));
    }

    @Test public void fixedFocusIsEstablishedByTheLensCapabilityAndStillNeedsExposure() {
        CameraReadiness readiness = new CameraReadiness(new int[]{CONTROL_AF_MODE_OFF},
                0f, new int[]{CONTROL_AE_MODE_ON});
        assertEquals(CONTROL_AF_MODE_OFF, readiness.afMode);
        readiness.observe(null, CONTROL_AE_STATE_CONVERGED, 1000);
        assertTrue(readiness.ready(1000));
        readiness.observe(null, null, 1001);
        assertFalse(readiness.ready(1001));
    }

    @Test public void missingCapabilitiesAndManualOnlyExposureRemainUnsupported() {
        assertFalse(new CameraReadiness(new int[]{CONTROL_AF_MODE_OFF}, null,
                new int[]{CONTROL_AE_MODE_ON}).supported());
        assertFalse(new CameraReadiness(null, null, null).supported());
        assertFalse(new CameraReadiness(new int[]{CONTROL_AF_MODE_AUTO}, 8f,
                new int[]{CONTROL_AE_MODE_OFF}).supported());
    }

    @Test public void autoOnlyHardwareUsesTheExplicitAutoFocusPath() {
        CameraReadiness readiness = new CameraReadiness(new int[]{CONTROL_AF_MODE_AUTO},
                8f, new int[]{CONTROL_AE_MODE_ON});
        assertEquals(CONTROL_AF_MODE_AUTO, readiness.afMode);
        readiness.observe(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_LOCKED, 1000);
        assertTrue(readiness.ready(1000));
    }

    @Test public void autoAndMacroRequireLockedRatherThanPassiveFocus() {
        for (int mode : new int[]{CONTROL_AF_MODE_AUTO, CONTROL_AF_MODE_MACRO}) {
            CameraReadiness readiness = new CameraReadiness(new int[]{mode}, 8f, new int[]{CONTROL_AE_MODE_ON});
            readiness.observe(CONTROL_AF_STATE_PASSIVE_FOCUSED, CONTROL_AE_STATE_CONVERGED, 1000);
            assertFalse(readiness.ready(1000));
            readiness.observe(CONTROL_AF_STATE_FOCUSED_LOCKED, CONTROL_AE_STATE_CONVERGED, 1001);
            assertTrue(readiness.ready(1001));
        }
    }
}
