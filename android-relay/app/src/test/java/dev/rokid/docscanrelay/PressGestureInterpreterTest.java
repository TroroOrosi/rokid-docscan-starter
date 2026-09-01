package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class PressGestureInterpreterTest {
    @Test
    public void singlePressIsDelayedUntilDoubleWindowExpires() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);
        interpreter.onDown(100);
        assertNull(interpreter.onUp(200));
        assertNull(interpreter.flush(549));
        assertEquals(PressGestureInterpreter.Action.SHORT, interpreter.flush(550));
    }

    @Test
    public void twoShortPressesBecomeDouble() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);
        interpreter.onDown(0);
        assertNull(interpreter.onUp(100));
        interpreter.onDown(200);
        assertEquals(PressGestureInterpreter.Action.DOUBLE_SHORT, interpreter.onUp(280));
        assertNull(interpreter.flush(1000));
    }

    @Test
    public void longPressCancelsPendingShort() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);
        interpreter.onDown(0);
        assertNull(interpreter.onUp(100));
        interpreter.onDown(200);
        assertNull(interpreter.flush(500));
        assertEquals(PressGestureInterpreter.Action.LONG, interpreter.onUp(1500));
        assertNull(interpreter.flush(2000));
    }

    @Test
    public void customViewExitWithoutKeyDownBecomesOneShortPress() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertNull(interpreter.onCustomViewExit(100));
        assertNull(interpreter.flush(1649));
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.flush(1650));
    }

    @Test
    public void keyReleaseAndCustomViewExitDoNotDispatchTwice() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);
        interpreter.onDown(100);
        assertNull(interpreter.onUp(150));

        assertNull(interpreter.onCustomViewExit(160));
        assertNull(interpreter.onCustomViewExit(200));
        assertNull(interpreter.flush(1699));
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.flush(1700));
    }

    @Test
    public void aiAssistStartIsLongAndCoalescesItsViewClose() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(100));
        assertNull(interpreter.onCustomViewExit(120));
        assertNull(interpreter.flush(1000));
    }

    @Test
    public void aiAssistStartOverridesAViewCloseThatArrivesFirst() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertNull(interpreter.onCustomViewExit(100));
        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(120));
        assertNull(interpreter.flush(1000));
    }

    @Test
    public void duplicateAiAssistStartDispatchesOneLongAction() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(100));
        assertNull(interpreter.onAiAssistStart(110));
        interpreter.onAiAssistExit(115);
        assertNull(interpreter.onAiAssistStart(120));
        interpreter.onAiAssistExit(125);
        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(500));
    }

    @Test
    public void longAssistSuppressesAViewCloseAfterTheNormalShortWindow() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(100));
        assertNull(interpreter.onCustomViewExit(600));
        assertNull(interpreter.flush(1000));
    }

    @Test
    public void viewCloseImmediatelyAfterAssistExitIsStillCoalesced() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(100));
        interpreter.onAiAssistExit(1000);
        assertNull(interpreter.onCustomViewExit(1010));
        assertNull(interpreter.flush(1500));
    }

    @Test
    public void unrelatedLifecycleExitDoesNotSuppressARealTap() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        interpreter.onAiAssistExit(100);
        assertNull(interpreter.onCustomViewExit(110));
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.flush(1660));
    }

    @Test
    public void delayedAiAssistStillOverridesACloseThatArrivesFirst() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertNull(interpreter.onCustomViewExit(100));
        assertNull(interpreter.flush(500));
        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(600));
        assertNull(interpreter.flush(2000));
    }

    @Test
    public void missingAssistExitCannotSuppressFutureTapsForever() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(100));
        assertNull(interpreter.onAiAssistStart(600));
        assertNull(interpreter.onCustomViewExit(1700));
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.flush(3250));
    }

    @Test
    public void systemMenuRecoveryCancelsOnlyThePendingCloseAction() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertNull(interpreter.onCustomViewExit(100));
        interpreter.cancelPendingCustomViewExit();
        assertNull(interpreter.flush(2000));

        interpreter.onDown(2100);
        assertNull(interpreter.onUp(2150));
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.flush(2500));
    }

    @Test
    public void aiExitEchoingOurOwnViewOperationIsNotATap() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        interpreter.onGlassesViewOperation(1000);
        assertNull(interpreter.onAiExit(1051));
        assertNull(interpreter.flush(3000));
    }

    @Test
    public void aiExitLongAfterTheLastViewOperationIsATap() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        interpreter.onGlassesViewOperation(1000);
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.onAiExit(24700));
    }

    @Test
    public void aiExitWithoutAnyViewOperationIsATap() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.onAiExit(100));
    }

    @Test
    public void repeatedAiExitFromOneTapDispatchesOneAction() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.onAiExit(1000));
        assertNull(interpreter.onAiExit(1100));
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.onAiExit(1400));
    }

    @Test
    public void aiExitClosingAnActiveAssistIsNotATap() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(
                PressGestureInterpreter.Action.LONG,
                interpreter.onAiAssistStart(100));
        assertNull(interpreter.onAiExit(400));
    }

    @Test
    public void aiExitBeforeThePushedViewOpensIsNotATap() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        // Measured on hardware: a push at 00:41:00.828 reached the glasses only
        // at 00:41:01.723 and echoed at 00:41:02.203, so the echo can trail the
        // push by well over a second. Its open callback had not arrived yet.
        interpreter.onGlassesViewOperation(1000);
        assertNull(interpreter.onAiExit(2375));
    }

    @Test
    public void aiExitAfterThePushedViewOpensIsATap() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        interpreter.onGlassesViewOperation(1000);
        interpreter.onGlassesViewOpened(1500);
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.onAiExit(1600));
    }

    @Test
    public void aViewThatNeverOpensCannotSuppressTapsForever() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        interpreter.onGlassesViewOperation(1000);
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.onAiExit(4500));
    }

    @Test
    public void theCloseHalfOfAViewSwapAlsoSuppressesItsEcho() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        // A swap closes before it reopens, and the glasses echo the close. The
        // relay must arm the suppression before the close Binder call, because
        // the echo can arrive while the reopen is still in flight. Arming only
        // after the reopen let that echo through as a tap, which fired the
        // shutter as soon as AIMING appeared.
        interpreter.onGlassesViewOperation(1000);
        interpreter.onGlassesViewOperation(1040);
        assertNull(interpreter.onAiExit(1200));
        assertNull(interpreter.flush(1600));
    }

    @Test
    public void reArmingDuringASwapDoesNotOutlastTheCap() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        interpreter.onGlassesViewOperation(1000);
        interpreter.onGlassesViewOperation(1040);
        assertEquals(
                PressGestureInterpreter.Action.SHORT,
                interpreter.onAiExit(4100));
    }

    @Test
    public void anExitEchoingOurOwnViewPushIsIdentifiedAsAnEcho() {
        // Measured on hardware: the recovery timer fired on the echo of its own
        // restore, restored again, and drove the CustomView through a
        // close/open every 0.7s -- the glasses visibly blinked and the
        // acknowledged generation fell ~30 pushes behind. The caller must be
        // able to tell an echo from a real exit, because "action == null" also
        // covers an assist close and a debounced second tap.
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);
        interpreter.onGlassesViewOperation(1_000);

        assertNull(interpreter.onAiExit(1_050));

        assertTrue(interpreter.lastAiExitWasViewEcho());
    }

    @Test
    public void aUserTapIsNotIdentifiedAsAnEcho() {
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);

        assertEquals(PressGestureInterpreter.Action.SHORT, interpreter.onAiExit(1_000));

        assertFalse(interpreter.lastAiExitWasViewEcho());
    }

    @Test
    public void anEchoStopsBeingAnEchoOnceTheViewIsAcknowledgedOpen() {
        // Echoes trail their push by 1ms to 1375ms, so the pending open, not a
        // timeout, is what ends the window.
        PressGestureInterpreter interpreter = new PressGestureInterpreter(1200, 350);
        interpreter.onGlassesViewOperation(1_000);
        interpreter.onGlassesViewOpened(1_100);

        assertEquals(PressGestureInterpreter.Action.SHORT, interpreter.onAiExit(1_150));

        assertFalse(interpreter.lastAiExitWasViewEcho());
    }
}
