package dev.rokid.docscanglass.input;

/** Side-effect-free physical gestures proven distinguishable on the measured build. */
public enum GlassesInputAction {
    SHORT_TAP,
    LONG_PRESS,
    SWIPE_FORWARD,
    SWIPE_BACK,
    /**
     * The one-finger double tap, which the firmware delivers as a trailing
     * {@code KEYCODE_BACK}. Left unconsumed it closes the Activity, so an
     * operator surface has to normalize it and decide what it means.
     */
    BACK
}
