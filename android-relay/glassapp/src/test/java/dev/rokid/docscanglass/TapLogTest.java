package dev.rokid.docscanglass;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.List;

import org.junit.Test;

public class TapLogTest {

    @Test
    public void startsEmptySoAnAbsenceOfInputIsVisible() {
        TapLog log = new TapLog(4);

        assertFalse(log.receivedAnything());
        assertEquals("DOWN 0  TAP 0  SWIPE 0  KEY 0  EVT 0", log.counters());
        assertTrue(log.lines().isEmpty());
    }

    @Test
    public void countsPrimaryDownsSeparatelyFromEveryTouchEvent() {
        TapLog log = new TapLog(8);

        log.recordTouch(10, "ACTION_DOWN", true, 100f, 200f, 1);
        log.recordTouch(20, "ACTION_MOVE", false, 101f, 200f, 1);
        log.recordTouch(30, "ACTION_UP", false, 101f, 200f, 1);

        assertEquals("DOWN 1  TAP 0  SWIPE 0  KEY 0  EVT 3", log.counters());
        assertTrue(log.receivedAnything());
    }

    @Test
    public void keepsTheNewestEventFirstAndDropsTheOldest() {
        TapLog log = new TapLog(2);

        log.recordTouch(1, "ACTION_DOWN", true, 1f, 2f, 1);
        log.recordGestureTap(2);
        log.recordSwipe(3, "LEFT");

        List<String> lines = log.lines();
        assertEquals(2, lines.size());
        assertEquals("     3 SWIPE LEFT", lines.get(0));
        assertEquals("     2 TAP", lines.get(1));
    }

    @Test
    public void formatsATouchWithItsCoordinatesAndPointerCount() {
        TapLog log = new TapLog(4);

        log.recordTouch(1234, "ACTION_POINTER_DOWN", false, 640.4f, 180.7f, 2);

        assertEquals("  1234 ACTION_POINTER_DOWN (640,181) p=2", log.lines().get(0));
    }

    @Test
    public void countsKeysBecauseTheTouchpadMayArriveAsDpad() {
        TapLog log = new TapLog(4);

        log.recordKey(50, "DOWN", "KEYCODE_DPAD_CENTER");

        assertEquals("DOWN 0  TAP 0  SWIPE 0  KEY 1  EVT 1", log.counters());
        assertEquals("    50 DOWN KEYCODE_DPAD_CENTER", log.lines().get(0));
        assertTrue(log.receivedAnything());
    }

    @Test
    public void rejectsANonPositiveCapacity() {
        try {
            new TapLog(0);
            throw new AssertionError("expected IllegalArgumentException");
        } catch (IllegalArgumentException expected) {
            assertEquals("capacity must be positive", expected.getMessage());
        }
    }
}
