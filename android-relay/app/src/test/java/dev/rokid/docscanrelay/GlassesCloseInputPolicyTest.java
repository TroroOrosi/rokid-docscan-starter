package dev.rokid.docscanrelay;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class GlassesCloseInputPolicyTest {
    @Test
    public void aimingRefusesACloseBecauseTheGlassesDismissTheViewOnATimer() {
        // Measured 2026-08-29: the closes that reached AIMING arrived 29.7s,
        // 30.1s and 30.1s after the view opened. That is the glasses dismissing
        // the CustomView on a timer, not the operator. Taking it as the tap
        // fired the shutter and registered a page nobody asked for.
        assertFalse(GlassesCloseInputPolicy.acceptsAsInput(RelayState.AIMING, false));
        assertFalse(GlassesCloseInputPolicy.acceptsAsInput(RelayState.AIMING, true));
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
            if (state == RelayState.CAPTURE_REVIEW) {
                continue;
            }
            assertFalse(state.name(), GlassesCloseInputPolicy.acceptsAsInput(state, true));
        }
    }
}
