package dev.rokid.docscanrelay;

/** Rejects unverified CUSTOMVIEW/AI callbacks as operator actions. */
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
        // The measured callbacks do not carry trustworthy operator provenance.
        // Phone buttons are the only supported control surface until a
        // glasses-side app input path passes physical acceptance testing.
        return Command.NONE;
    }
}
