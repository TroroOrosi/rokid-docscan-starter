package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class GlassAppOperationTest {

    @Test
    public void startsIdleSoAnUnrunOperationIsNotAFailure() {
        GlassAppOperation operation = new GlassAppOperation("install", 1_000L);

        assertEquals(GlassAppOperation.Verdict.IDLE, operation.verdict(0L));
    }

    @Test
    public void staysPendingUntilTheDeadlinePasses() {
        GlassAppOperation operation = new GlassAppOperation("install", 1_000L);

        operation.start(0L, "dev.rokid.docscanglass");

        assertEquals(GlassAppOperation.Verdict.PENDING, operation.verdict(1_000L));
        assertEquals(GlassAppOperation.Verdict.NO_RESPONSE, operation.verdict(1_001L));
    }

    @Test
    public void aLateResultStillResolvesBecauseTheTimeoutVerdictIsProvisional() {
        GlassAppOperation operation = new GlassAppOperation("open", 500L);
        operation.start(0L, "dev.rokid.docscanglass/.TapProbeActivity");
        assertEquals(GlassAppOperation.Verdict.NO_RESPONSE, operation.verdict(900L));

        assertTrue(operation.onResult(900L, true));

        assertEquals(GlassAppOperation.Verdict.SUCCEEDED, operation.verdict(900L));
    }

    @Test
    public void separatesAFirmwareRefusalFromAFailedInstall() {
        GlassAppOperation refused = new GlassAppOperation("install", 500L);
        refused.start(0L, "pkg");
        refused.onCallFailed(10L, "DeadObjectException");

        GlassAppOperation ranAndFailed = new GlassAppOperation("install", 500L);
        ranAndFailed.start(0L, "pkg");
        ranAndFailed.onResult(10L, false);

        assertEquals(GlassAppOperation.Verdict.CALL_FAILED, refused.verdict(10L));
        assertEquals(GlassAppOperation.Verdict.FAILED, ranAndFailed.verdict(10L));
        assertEquals(
                "glass-app-install target=pkg verdict=CALL_FAILED "
                        + "failure=DeadObjectException",
                refused.summary(10L));
    }

    @Test
    public void ignoresASecondResultForAnAlreadyResolvedOperation() {
        GlassAppOperation operation = new GlassAppOperation("open", 500L);
        operation.start(0L, "pkg");
        assertTrue(operation.onResult(10L, true));

        assertFalse(operation.onResult(20L, false));
        assertEquals(GlassAppOperation.Verdict.SUCCEEDED, operation.verdict(20L));
    }

    @Test
    public void ignoresAResultForAnOperationThatWasNeverStarted() {
        GlassAppOperation operation = new GlassAppOperation("open", 500L);

        assertFalse(operation.onResult(10L, true));
        assertEquals(GlassAppOperation.Verdict.IDLE, operation.verdict(10L));
    }

    @Test
    public void rejectsAnUnusableConfiguration() {
        try {
            new GlassAppOperation("install", 0L);
            throw new AssertionError("expected IllegalArgumentException for the timeout");
        } catch (IllegalArgumentException expected) {
            assertEquals("operation timeout must be positive", expected.getMessage());
        }
        try {
            new GlassAppOperation("  ", 500L);
            throw new AssertionError("expected IllegalArgumentException for the name");
        } catch (IllegalArgumentException expected) {
            assertEquals("operation needs a name", expected.getMessage());
        }
    }
}
