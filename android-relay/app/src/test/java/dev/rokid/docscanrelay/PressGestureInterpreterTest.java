package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

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
}
