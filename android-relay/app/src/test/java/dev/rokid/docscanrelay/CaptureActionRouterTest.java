package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class CaptureActionRouterTest {
    @Test
    public void captureReviewRequiresAnExplicitDecision() {
        assertEquals(
                CaptureActionRouter.Command.ARM_RETAKE,
                CaptureActionRouter.route(
                        RelayState.CAPTURE_REVIEW,
                        PressGestureInterpreter.Action.SHORT));
        assertEquals(
                CaptureActionRouter.Command.ARM_RETAKE,
                CaptureActionRouter.route(
                        RelayState.CAPTURE_REVIEW,
                        PressGestureInterpreter.Action.DOUBLE_SHORT));
        assertEquals(
                CaptureActionRouter.Command.CONFIRM_CAPTURE,
                CaptureActionRouter.route(
                        RelayState.CAPTURE_REVIEW,
                        PressGestureInterpreter.Action.LONG));
    }

    @Test
    public void aimingTakesThePhotoUnlessTheGestureIsAnExplicitCancel() {
        assertEquals(
                CaptureActionRouter.Command.ARM_NEXT,
                CaptureActionRouter.route(
                        RelayState.READING,
                        PressGestureInterpreter.Action.SHORT));
        assertEquals(
                CaptureActionRouter.Command.ARM_PREVIOUS,
                CaptureActionRouter.route(
                        RelayState.READING,
                        PressGestureInterpreter.Action.DOUBLE_SHORT));
        assertEquals(
                CaptureActionRouter.Command.FINISH_READING,
                CaptureActionRouter.route(
                        RelayState.READING,
                        PressGestureInterpreter.Action.LONG));
        assertEquals(
                CaptureActionRouter.Command.TAKE_PHOTO,
                CaptureActionRouter.route(
                        RelayState.AIMING,
                        PressGestureInterpreter.Action.SHORT));
        assertEquals(
                CaptureActionRouter.Command.TAKE_PHOTO,
                CaptureActionRouter.route(
                        RelayState.AIMING,
                        PressGestureInterpreter.Action.LONG));
        assertEquals(
                CaptureActionRouter.Command.CANCEL_AIMING,
                CaptureActionRouter.route(
                        RelayState.AIMING,
                        PressGestureInterpreter.Action.DOUBLE_SHORT));
        assertEquals(
                CaptureActionRouter.Command.CANCEL_AIMING,
                CaptureActionRouter.route(
                        RelayState.STABILIZING,
                        PressGestureInterpreter.Action.LONG));
        assertEquals(
                CaptureActionRouter.Command.CANCEL_AIMING,
                CaptureActionRouter.route(
                        RelayState.STABILIZING,
                        PressGestureInterpreter.Action.SHORT));
        assertEquals(
                CaptureActionRouter.Command.CANCEL_AIMING,
                CaptureActionRouter.route(
                        RelayState.STABILIZING,
                        PressGestureInterpreter.Action.DOUBLE_SHORT));
    }

    @Test
    public void answerReviewGesturesStayCompatible() {
        assertEquals(
                CaptureActionRouter.Command.NEXT_REVIEW,
                CaptureActionRouter.route(
                        RelayState.REVIEW,
                        PressGestureInterpreter.Action.SHORT));
        assertEquals(
                CaptureActionRouter.Command.PREVIOUS_REVIEW,
                CaptureActionRouter.route(
                        RelayState.REVIEW,
                        PressGestureInterpreter.Action.DOUBLE_SHORT));
        assertEquals(
                CaptureActionRouter.Command.START_NEW_DOCUMENT,
                CaptureActionRouter.route(
                        RelayState.REVIEW,
                        PressGestureInterpreter.Action.LONG));
    }

    @Test
    public void aimingTapTakesThePhotoBecauseLongPressNeverArrives() {
        // YodaOS keeps long press, so a tap is the only glasses input while the
        // operator is holding the page against the reticle. Reaching for the
        // phone there would move the framing the aiming view just established,
        // so the tap has to be the shutter and cancelling moves to the phone.
        assertEquals(
                CaptureActionRouter.Command.TAKE_PHOTO,
                CaptureActionRouter.route(
                        RelayState.AIMING,
                        PressGestureInterpreter.Action.SHORT));
    }
}
