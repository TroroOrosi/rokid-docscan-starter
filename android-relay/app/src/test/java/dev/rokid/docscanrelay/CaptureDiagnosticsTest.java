package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CaptureDiagnosticsTest {
    @Test
    public void budgetIsTheAsyncHalfOfTheOneMegabyteBinderBuffer() {
        assertEquals(512 * 1024, CaptureDiagnostics.ASYNC_BINDER_BUDGET_BYTES);
    }

    @Test
    public void receivedLineReportsSizeShareOfBudgetAndElapsedTime() {
        String line = CaptureDiagnostics.photoReceived(
                PhotoCaptureSettings.DEFAULT, 125_000, 1_240L);

        assertEquals("1920x1080 q80 122KB 予算24% 1.2s", line);
    }

    @Test
    public void receivedLineFlagsPayloadsThatExceededTheBudgetButStillArrived() {
        String line = CaptureDiagnostics.photoReceived(
                PhotoCaptureSettings.parse("4032", "3024", "80"), 691_200, 3_000L);

        assertTrue(line.contains("132%"));
        assertTrue(line.contains("予算超過"));
    }

    @Test
    public void receivedLineDoesNotFlagPayloadsExactlyAtTheBudget() {
        String line = CaptureDiagnostics.photoReceived(
                PhotoCaptureSettings.DEFAULT, CaptureDiagnostics.ASYNC_BINDER_BUDGET_BYTES, 2_000L);

        assertEquals("1920x1080 q80 512KB 予算100% 2.0s", line);
    }

    @Test
    public void emptyPayloadIsReportedAsZeroRatherThanSuppressed() {
        String line = CaptureDiagnostics.photoReceived(PhotoCaptureSettings.DEFAULT, 0, 500L);

        assertEquals("1920x1080 q80 0KB 予算0% 0.5s", line);
    }

    @Test
    public void missingCallbackIsRecordedWithTheRequestThatCausedIt() {
        String line = CaptureDiagnostics.photoNoCallback(
                PhotoCaptureSettings.parse("4032", "3024", "80"), 8_000L);

        assertEquals("4032x3024 q80 応答なし 8.0s", line);
    }

    @Test
    public void serviceIdentityCarriesBothTheNameAndTheNumericCode() {
        assertEquals("CXR-L 1.0.1 (code 101)",
                CaptureDiagnostics.serviceIdentity("1.0.1", 101));
    }

    @Test
    public void serviceIdentityStaysReadableWhenTheServiceReportsNothing() {
        assertEquals("CXR-L 不明", CaptureDiagnostics.serviceIdentity(null, 0));
        assertEquals("CXR-L 不明", CaptureDiagnostics.serviceIdentity("   ", 0));
    }
}
