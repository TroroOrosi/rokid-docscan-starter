package dev.rokid.docscanrelay;

/**
 * Whether a CustomView close counts as operator input.
 *
 * <p>A close scored {@code userInitiated=true} is only known not to be ours. It
 * is not therefore the operator: measured on Hi Rokid G1.12.10.0815 on
 * 2026-08-29, the closes that reached AIMING arrived 29.7s, 30.1s and 30.1s
 * after their view opened, which is the glasses dismissing the CustomView on a
 * timer. Accepting those as the tap fired the shutter and registered a page
 * nobody asked for.</p>
 *
 * <p>No state accepts it. A close can still cause a view to be re-presented,
 * but it cannot capture, cancel, register, finalize, or navigate.</p>
 */
public final class GlassesCloseInputPolicy {
    private GlassesCloseInputPolicy() {}

    public static boolean acceptsAsInput(RelayState state, boolean hasPendingCaptureReview) {
        return false;
    }
}
