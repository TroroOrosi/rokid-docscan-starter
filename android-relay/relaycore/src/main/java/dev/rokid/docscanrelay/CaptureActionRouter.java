package dev.rokid.docscanrelay;

import dev.rokid.docscanglass.input.GlassesInputAction;

/** Turns an operator gesture into a workflow command, or refuses to. */
public final class CaptureActionRouter {
    public enum Command {
        ARM_NEXT,
        ARM_PREVIOUS,
        ARM_RETAKE,
        TAKE_PHOTO,
        CANCEL_AIMING,
        FINISH_READING,
        CONFIRM_CAPTURE,
        NEXT_REVIEW,
        PREVIOUS_REVIEW,
        START_NEW_DOCUMENT,
        NONE
    }

    private CaptureActionRouter() {
    }

    /** Rejects unverified CUSTOMVIEW/AI callbacks as operator actions. */
    static Command route(RelayState state, PressGestureInterpreter.Action gesture) {
        // The measured callbacks do not carry trustworthy operator provenance.
        // Phone buttons are the only supported control surface on that route.
        return Command.NONE;
    }

    /**
     * The glasses-side control surface.
     *
     * <p>Unlike the CUSTOMVIEW callbacks above, these actions do carry
     * provenance: `:glassinput`'s normalizer was calibrated against the raw
     * input stream on the hardware, and `:glassapp` 0.1.7 proved one
     * normalized action per physical gesture across a controlled run.</p>
     */
    public static Command route(RelayState state, GlassesInputAction action) {
        if (state == null || action == null) {
            return Command.NONE;
        }
        switch (action) {
            case SHORT_TAP:
                return onTap(state);
            case SWIPE_FORWARD:
                return onSwipeForward(state);
            case SWIPE_BACK:
                return onSwipeBack(state);
            default:
                // LONG_PRESS reaches the firmware as ACTION_AI_START, so acting
                // on it would race the assistant for the foreground. BACK
                // belongs to BackExitPolicy, which needs two within 3 s to
                // exit; treating it as workflow input would spend the first.
                return Command.NONE;
        }
    }

    private static Command onTap(RelayState state) {
        switch (state) {
            case READY:
            case READING:
                return Command.ARM_NEXT;
            case AIMING:
                return Command.TAKE_PHOTO;
            case CAPTURE_REVIEW:
                return Command.CONFIRM_CAPTURE;
            case REVIEW:
                // Nothing else remains to do with a finished document, and the
                // answers stay on the server.
                return Command.START_NEW_DOCUMENT;
            default:
                // Every capture-in-flight state included: a command here would
                // land on a page whose outcome the operator has not seen.
                return Command.NONE;
        }
    }

    private static Command onSwipeForward(RelayState state) {
        switch (state) {
            case READING:
                return Command.FINISH_READING;
            case REVIEW:
                return Command.NEXT_REVIEW;
            default:
                return Command.NONE;
        }
    }

    private static Command onSwipeBack(RelayState state) {
        switch (state) {
            case AIMING:
                return Command.CANCEL_AIMING;
            case CAPTURE_REVIEW:
                return Command.ARM_RETAKE;
            case READING:
                return Command.ARM_PREVIOUS;
            case REVIEW:
                return Command.PREVIOUS_REVIEW;
            default:
                return Command.NONE;
        }
    }
}
