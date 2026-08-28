package dev.rokid.docscanrelay;

/**
 * Whether a user-originated CustomView close counts as glasses input.
 *
 * <p>A close scored {@code userInitiated=true} is only known not to be ours. It
 * is not therefore the operator: measured on Hi Rokid G1.12.10.0815 on
 * 2026-08-29, the closes that reached AIMING arrived 29.7s, 30.1s and 30.1s
 * after their view opened, which is the glasses dismissing the CustomView on a
 * timer. Accepting those as the tap fired the shutter and registered a page
 * nobody asked for.</p>
 *
 * <p>So the capture-review screen keeps the exception it was given -- a tap
 * there delivers no AI event and the operator has nothing else to press -- and
 * every other state refuses. A close that is refused here is not discarded: it
 * arms menu-exit recovery, because the view is gone either way.</p>
 */
public final class GlassesCloseInputPolicy {
    private GlassesCloseInputPolicy() {}

    public static boolean acceptsAsInput(RelayState state, boolean hasPendingCaptureReview) {
        return state == RelayState.CAPTURE_REVIEW && hasPendingCaptureReview;
    }
}
