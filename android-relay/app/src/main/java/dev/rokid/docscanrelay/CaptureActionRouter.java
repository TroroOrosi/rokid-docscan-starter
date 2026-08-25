package dev.rokid.docscanrelay;

/** Maps the glasses press gesture to an action for the current relay state. */
final class CaptureActionRouter {
    enum Command {
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

    static Command route(RelayState state, PressGestureInterpreter.Action gesture) {
        if (state == RelayState.CAPTURE_REVIEW) {
            switch (gesture) {
                case SHORT:
                case DOUBLE_SHORT:
                    return Command.ARM_RETAKE;
                case LONG:
                default:
                    return Command.CONFIRM_CAPTURE;
            }
        }
        if (state == RelayState.AIMING) {
            // YodaOS reserves long press, so a tap is the only glasses input
            // available while the operator holds the page against the reticle.
            // Cancelling moves to the phone: reaching for it during aiming
            // would move the framing this state exists to establish.
            return gesture == PressGestureInterpreter.Action.DOUBLE_SHORT
                    ? Command.CANCEL_AIMING
                    : Command.TAKE_PHOTO;
        }
        if (state == RelayState.STABILIZING) {
            return Command.CANCEL_AIMING;
        }
        if (state == RelayState.REVIEW) {
            switch (gesture) {
                case SHORT:
                    return Command.NEXT_REVIEW;
                case DOUBLE_SHORT:
                    return Command.PREVIOUS_REVIEW;
                case LONG:
                default:
                    return Command.START_NEW_DOCUMENT;
            }
        }
        if (state.isCaptureInProgress() || state == RelayState.FINALIZING) {
            return Command.NONE;
        }
        switch (gesture) {
            case SHORT:
                return Command.ARM_NEXT;
            case DOUBLE_SHORT:
                return Command.ARM_PREVIOUS;
            case LONG:
            default:
                return Command.FINISH_READING;
        }
    }
}
