package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

import dev.rokid.docscanglass.input.GlassesInputAction;

/**
 * The glasses-side control surface. Unlike the CUSTOMVIEW callbacks, which
 * carry no trustworthy operator provenance, these actions come from
 * `:glassinput`, whose normalizer was calibrated against raw input on the
 * hardware and proved one action per physical gesture.
 */
public class GlassesActionRoutingTest {
    @Test
    public void aTapArmsTheNextPage() {
        assertEquals(
                CaptureActionRouter.Command.ARM_NEXT,
                CaptureActionRouter.route(RelayState.READING, GlassesInputAction.SHORT_TAP));
        assertEquals(
                CaptureActionRouter.Command.ARM_NEXT,
                CaptureActionRouter.route(RelayState.READY, GlassesInputAction.SHORT_TAP));
    }

    @Test
    public void aTapWhileAimingIsTheShutter() {
        assertEquals(
                CaptureActionRouter.Command.TAKE_PHOTO,
                CaptureActionRouter.route(RelayState.AIMING, GlassesInputAction.SHORT_TAP));
    }

    @Test
    public void aTapOnTheReviewedStillRegistersIt() {
        assertEquals(
                CaptureActionRouter.Command.CONFIRM_CAPTURE,
                CaptureActionRouter.route(
                        RelayState.CAPTURE_REVIEW, GlassesInputAction.SHORT_TAP));
    }

    @Test
    public void aBackSwipeUndoesWhateverIsOnScreen() {
        assertEquals(
                CaptureActionRouter.Command.CANCEL_AIMING,
                CaptureActionRouter.route(RelayState.AIMING, GlassesInputAction.SWIPE_BACK));
        assertEquals(
                CaptureActionRouter.Command.ARM_RETAKE,
                CaptureActionRouter.route(
                        RelayState.CAPTURE_REVIEW, GlassesInputAction.SWIPE_BACK));
        assertEquals(
                CaptureActionRouter.Command.ARM_PREVIOUS,
                CaptureActionRouter.route(RelayState.READING, GlassesInputAction.SWIPE_BACK));
    }

    @Test
    public void aForwardSwipeFinishesReadingAndThenPagesThroughAnswers() {
        assertEquals(
                CaptureActionRouter.Command.FINISH_READING,
                CaptureActionRouter.route(RelayState.READING, GlassesInputAction.SWIPE_FORWARD));
        assertEquals(
                CaptureActionRouter.Command.NEXT_REVIEW,
                CaptureActionRouter.route(RelayState.REVIEW, GlassesInputAction.SWIPE_FORWARD));
        assertEquals(
                CaptureActionRouter.Command.PREVIOUS_REVIEW,
                CaptureActionRouter.route(RelayState.REVIEW, GlassesInputAction.SWIPE_BACK));
    }

    @Test
    public void aTapAfterTheAnswersStartsTheNextDocument() {
        assertEquals(
                CaptureActionRouter.Command.START_NEW_DOCUMENT,
                CaptureActionRouter.route(RelayState.REVIEW, GlassesInputAction.SHORT_TAP));
    }

    @Test
    public void aLongPressIsNeverACommand() {
        // The firmware turns a one-second hold into ACTION_AI_START. Acting on
        // it would race the assistant for the foreground, so it stays inert.
        for (RelayState state : RelayState.values()) {
            assertEquals(
                    state.toString(),
                    CaptureActionRouter.Command.NONE,
                    CaptureActionRouter.route(state, GlassesInputAction.LONG_PRESS));
        }
    }

    @Test
    public void backIsTheExitGestureAndNeverAWorkflowCommand() {
        // BackExitPolicy owns it: one BACK arms, a second within 3 s exits.
        for (RelayState state : RelayState.values()) {
            assertEquals(
                    state.toString(),
                    CaptureActionRouter.Command.NONE,
                    CaptureActionRouter.route(state, GlassesInputAction.BACK));
        }
    }

    @Test
    public void nothingIsAcceptedWhileACaptureIsInFlight() {
        // STABILIZING through UPLOADING, plus FINALIZING: a command here would
        // land on a page the operator has not seen the outcome of yet.
        RelayState[] busy = {
            RelayState.STABILIZING, RelayState.CAPTURING, RelayState.OCR,
            RelayState.UPLOADING, RelayState.FINALIZING, RelayState.DISCONNECTED,
            RelayState.ERROR,
        };
        for (RelayState state : busy) {
            for (GlassesInputAction action : GlassesInputAction.values()) {
                assertEquals(
                        state + " / " + action,
                        CaptureActionRouter.Command.NONE,
                        CaptureActionRouter.route(state, action));
            }
        }
    }
}
