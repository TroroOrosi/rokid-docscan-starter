package dev.rokid.docscanglass.input;

/**
 * Decides what a normalized {@link GlassesInputAction#BACK} means to the
 * operator surface.
 *
 * <p>The firmware ends a one-finger double tap with {@code KEYCODE_BACK}. Left
 * unconsumed the system finishes the Activity, so a single mis-tap ends the
 * session. Consuming it without an alternative would instead leave no way off
 * the screen. This policy resolves both: the first BACK arms a confirmation and
 * a second BACK inside {@link #CONFIRM_WINDOW_MILLIS} exits.
 *
 * <p>The confirmation window is independent of the normalizer's event-pair
 * correlation. Two distinct fast BACK gestures can confirm an exit.
 *
 * <p>Fails closed. A non-monotonic timestamp re-arms rather than exiting.
 */
public final class BackExitPolicy {

    /** Inclusive upper bound between the arming BACK and the confirming BACK. */
    public static final long CONFIRM_WINDOW_MILLIS = 3_000;

    public enum Decision {
        ARM_CONFIRMATION,
        EXIT
    }

    private long armedAtMillis = -1;

    public synchronized Decision onBack(long elapsedMillis) {
        long armedAt = armedAtMillis;
        if (armedAt >= 0
                && elapsedMillis >= armedAt
                && elapsedMillis - armedAt <= CONFIRM_WINDOW_MILLIS) {
            armedAtMillis = -1;
            return Decision.EXIT;
        }
        armedAtMillis = elapsedMillis;
        return Decision.ARM_CONFIRMATION;
    }

    /** Disarms without exiting. Any other action or a lifecycle reset uses this. */
    public synchronized void reset() {
        armedAtMillis = -1;
    }

    public synchronized boolean isArmed() {
        return armedAtMillis >= 0;
    }
}
