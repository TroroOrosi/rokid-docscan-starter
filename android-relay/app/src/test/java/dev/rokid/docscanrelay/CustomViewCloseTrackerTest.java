package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CustomViewCloseTrackerTest {
    @Test
    public void distinguishesProgrammaticAndUserInitiatedClose() {
        CustomViewCloseTracker tracker = new CustomViewCloseTracker(2000);

        tracker.expectProgrammaticClose(100, 1);
        assertFalse(tracker.onClosed(200, 1, false));
        assertTrue(tracker.onClosed(300, 2, true));
    }

    @Test
    public void expiredProgrammaticExpectationDoesNotConsumeAUserClose() {
        CustomViewCloseTracker tracker = new CustomViewCloseTracker(2000);

        tracker.expectProgrammaticClose(100, 1);
        assertTrue(tracker.onClosed(2101, 1, true));
    }

    @Test
    public void resetDropsOutstandingExpectations() {
        CustomViewCloseTracker tracker = new CustomViewCloseTracker(2000);

        tracker.expectProgrammaticClose(100, 1);
        tracker.reset();
        assertTrue(tracker.onClosed(200, 1, true));
    }

    @Test
    public void rejectedProgrammaticCloseDoesNotConsumeAUserClose() {
        CustomViewCloseTracker tracker = new CustomViewCloseTracker(2000);

        tracker.expectProgrammaticClose(100, 1);
        tracker.cancelLatestExpectation();
        assertTrue(tracker.onClosed(200, 1, true));
    }

    @Test
    public void userCloseOfNewGenerationIsNotConsumedByDelayedOldClose() {
        CustomViewCloseTracker tracker = new CustomViewCloseTracker(2000);

        tracker.expectProgrammaticClose(100, 1);

        assertTrue(tracker.onClosed(200, 2, true));
        assertFalse(tracker.onClosed(220, 2, false));
        assertFalse(tracker.onClosed(240, 2, false));
    }

    @Test
    public void swapEchoOfTheDisplayedGenerationIsProgrammatic() {
        CustomViewCloseTracker tracker = new CustomViewCloseTracker(2000);

        // A view swap arms the expectation for the generation on screen and
        // then the glasses echo that close while it is still locally open.
        // Reading that echo as a tap fired the shutter the instant AIMING
        // appeared.
        tracker.expectProgrammaticClose(100, 1);

        assertFalse(tracker.onClosed(200, 1, true));
        assertTrue(tracker.onClosed(300, 2, true));
    }

    @Test
    public void reversedCallbacksAcrossThreeGenerationsDispatchOneUserAction() {
        CustomViewCloseTracker tracker = new CustomViewCloseTracker(2000);

        tracker.expectProgrammaticClose(100, 1);
        tracker.expectProgrammaticClose(110, 2);

        assertTrue(tracker.onClosed(200, 3, true));
        assertFalse(tracker.onClosed(210, 3, false));
        assertFalse(tracker.onClosed(220, 3, false));
    }

    @Test
    public void eachGenerationCanDispatchAtMostOneUserAction() {
        CustomViewCloseTracker tracker = new CustomViewCloseTracker(2000);

        assertTrue(tracker.onClosed(100, 1, true));
        assertFalse(tracker.onClosed(110, 1, true));
        assertTrue(tracker.onClosed(200, 2, true));
    }
}
