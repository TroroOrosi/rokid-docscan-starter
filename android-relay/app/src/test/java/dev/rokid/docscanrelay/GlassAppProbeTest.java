package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class GlassAppProbeTest {
    @Test
    public void isIdleBeforeAnyProbeIsStarted() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        assertEquals(GlassAppProbe.Verdict.IDLE, probe.verdict(100));
    }

    @Test
    public void anAnswerResolvesThePendingProbeAndReportsInstallation() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");
        assertEquals(GlassAppProbe.Verdict.PENDING, probe.verdict(200));

        assertTrue(probe.onQueryResult(300, "dev.rokid.docscanglasses", false));

        assertEquals(GlassAppProbe.Verdict.ANSWERED, probe.verdict(400));
        assertFalse(probe.installed());
    }

    @Test
    public void anAnswerCarriesTheInstalledFlagThrough() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");
        probe.onQueryResult(300, "dev.rokid.docscanglasses", true);

        assertEquals(GlassAppProbe.Verdict.ANSWERED, probe.verdict(400));
        assertTrue(probe.installed());
    }

    @Test
    public void staysPendingUntilTheDeadlinePasses() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");

        assertEquals(GlassAppProbe.Verdict.PENDING, probe.verdict(5099));
    }

    @Test
    public void silencePastTheDeadlineIsNoResponse() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");

        assertEquals(GlassAppProbe.Verdict.NO_RESPONSE, probe.verdict(5101));
    }

    @Test
    public void aBinderFailureAtCallTimeSaysTheMethodIsNotImplemented() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");
        probe.onCallFailed(150, "android.os.RemoteException");

        assertEquals(GlassAppProbe.Verdict.CALL_FAILED, probe.verdict(200));
    }

    @Test
    public void aLateAnswerAfterTheDeadlineStillProvesTheMethodIsImplemented() {
        // NO_RESPONSE is provisional. The probe exists to learn whether Hi
        // Rokid implements the method at all, so a callback at 20 s answers
        // that question just as well as one at 200 ms.
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");
        assertEquals(GlassAppProbe.Verdict.NO_RESPONSE, probe.verdict(20000));

        assertTrue(probe.onQueryResult(20100, "dev.rokid.docscanglasses", true));

        assertEquals(GlassAppProbe.Verdict.ANSWERED, probe.verdict(20200));
    }

    @Test
    public void aResultForAnotherPackageDoesNotResolveTheProbe() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");

        assertFalse(probe.onQueryResult(300, "com.example.other", true));
        assertEquals(GlassAppProbe.Verdict.PENDING, probe.verdict(400));
    }

    @Test
    public void aFailureAfterTheProbeWasAnsweredDoesNotOverwriteTheAnswer() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");
        probe.onQueryResult(300, "dev.rokid.docscanglasses", true);
        probe.onCallFailed(350, "late failure");

        assertEquals(GlassAppProbe.Verdict.ANSWERED, probe.verdict(400));
    }

    @Test
    public void restartingClearsThePreviousOutcome() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");
        probe.onCallFailed(150, "android.os.RemoteException");

        probe.start(200, "dev.rokid.docscanglasses");

        assertEquals(GlassAppProbe.Verdict.PENDING, probe.verdict(300));
    }

    @Test
    public void summaryNamesTheVerdictAndThePackage() {
        GlassAppProbe probe = new GlassAppProbe(5000);

        probe.start(100, "dev.rokid.docscanglasses");
        probe.onQueryResult(300, "dev.rokid.docscanglasses", true);

        String summary = probe.summary(400);

        assertTrue(summary.contains("ANSWERED"));
        assertTrue(summary.contains("dev.rokid.docscanglasses"));
        assertTrue(summary.contains("installed=true"));
    }

    @Test
    public void timeoutMustBePositive() {
        try {
            new GlassAppProbe(0);
            throw new AssertionError("expected IllegalArgumentException");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("positive"));
        }
    }
}
