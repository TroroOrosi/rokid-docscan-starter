package dev.rokid.docscanrelay;

/**
 * Whether a user-originated CustomView close counts as glasses input.
 *
 * <p>The close is not always redundant with AI-exit. Measured on Hi Rokid
 * G1.12.10.0815 on 2026-08-29, a tap in AIMING produced no AI event at all and
 * arrived only as a close that {@code CustomViewCloseTracker} correctly scored
 * {@code userInitiated=true} -- three view-swap echoes in the same session
 * scored false, so the discrimination works. The relay then discarded it,
 * because close-as-input was restricted to the capture-review screen on the
 * assumption that AIMING always receives AI-exit. It does not, and the operator
 * saw a tap do nothing.</p>
 */
public final class GlassesCloseInputPolicy {
    private GlassesCloseInputPolicy() {}

    public static boolean acceptsAsInput(RelayState state, boolean hasPendingCaptureReview) {
        if (state == RelayState.CAPTURE_REVIEW) {
            return hasPendingCaptureReview;
        }
        return state == RelayState.AIMING;
    }
}
