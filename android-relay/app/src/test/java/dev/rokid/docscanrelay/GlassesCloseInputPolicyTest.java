package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class GlassesCloseInputPolicyTest {
    @Test
    public void aimingAcceptsACloseBecauseTheTapMayArriveOnlyThatWay() {
        assertTrue(GlassesCloseInputPolicy.acceptsAsInput(RelayState.AIMING, false));
    }

    @Test
    public void captureReviewAcceptsACloseOnlyWithAPhotoToActOn() {
        assertTrue(GlassesCloseInputPolicy.acceptsAsInput(RelayState.CAPTURE_REVIEW, true));
        assertFalse(GlassesCloseInputPolicy.acceptsAsInput(RelayState.CAPTURE_REVIEW, false));
    }

    @Test
    public void noOtherStateLetsACloseReachTheShutter() {
        // Everywhere else a misread close must not act: there is nothing the
        // operator can express, and a wrong guess registers the wrong photo.
        for (RelayState state : RelayState.values()) {
            if (state == RelayState.AIMING || state == RelayState.CAPTURE_REVIEW) {
                continue;
            }
            assertFalse(state.name(), GlassesCloseInputPolicy.acceptsAsInput(state, true));
        }
    }
}
