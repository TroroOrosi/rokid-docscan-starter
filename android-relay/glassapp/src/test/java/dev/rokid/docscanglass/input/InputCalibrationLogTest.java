package dev.rokid.docscanglass.input;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.List;

import org.junit.Test;

public class InputCalibrationLogTest {

    @Test
    public void officialBroadcastCatalogMatchesTheRokidCustomAppContract() {
        assertEquals(
                List.of(
                        "com.android.action.ACTION_SPRITE_BUTTON_CLICK",
                        "com.android.action.ACTION_SPRITE_BUTTON_DOWN",
                        "com.android.action.ACTION_SPRITE_BUTTON_UP",
                        "com.android.action.ACTION_SPRITE_BUTTON_DOUBLE_CLICK",
                        "com.android.action.ACTION_SPRITE_BUTTON_LONG_PRESS",
                        "com.android.action.ACTION_AI_START",
                        "com.android.action.ACTION_TWO_FINGER_SINGLE_TAP",
                        "com.android.action.ACTION_TWO_FINGER_DOUBLE_TAP",
                        "com.android.action.ACTION_TWO_FINGER_SWIPE_FORWARD",
                        "com.android.action.ACTION_TWO_FINGER_SWIPE_BACK",
                        "com.android.action.ACTION_SETTINGS_KEY"),
                OfficialKeyBroadcasts.actions());
        assertTrue(OfficialKeyBroadcasts.isOfficial(
                "com.android.action.ACTION_SPRITE_BUTTON_CLICK"));
        assertFalse(OfficialKeyBroadcasts.isOfficial("future.action"));
    }

    @Test
    public void recordsBroadcastAndKeyEventsOnOneMonotonicSequence() {
        InputCalibrationLog log = new InputCalibrationLog(4);

        log.record(InputSignal.broadcast(
                100,
                "com.android.action.ACTION_SPRITE_BUTTON_CLICK",
                true));
        log.record(InputSignal.key(112, "DOWN", "KEYCODE_ENTER", true));

        assertEquals(
                List.of(
                        "#2 t=112 src=KEY_EVENT phase=DOWN name=KEYCODE_ENTER known=true",
                        "#1 t=100 src=BROADCAST phase=EVENT "
                                + "name=com.android.action.ACTION_SPRITE_BUTTON_CLICK known=true"),
                log.lines());
    }

    @Test
    public void keepsUnknownInputObservableWithoutTreatingItAsKnown() {
        InputCalibrationLog log = new InputCalibrationLog(2);

        InputSignal signal = InputSignal.key(25, "DOWN", "KEYCODE_FUTURE", false);
        log.record(signal);

        assertFalse(signal.known());
        assertEquals(
                "#1 t=25 src=KEY_EVENT phase=DOWN name=KEYCODE_FUTURE known=false",
                log.lines().get(0));
    }

    @Test
    public void recognizesOnlyTheActivityKeyNamesSelectedForCalibration() {
        assertTrue(GlassKeyEvents.isKnown("KEYCODE_ENTER"));
        assertTrue(GlassKeyEvents.isKnown("KEYCODE_DPAD_RIGHT"));
        assertTrue(GlassKeyEvents.isKnown("KEYCODE_BACK"));
        assertTrue(GlassKeyEvents.isKnown("KEYCODE_NOTIFICATION"));
        assertFalse(GlassKeyEvents.isKnown("KEYCODE_FUTURE"));
        assertFalse(GlassKeyEvents.isKnown(null));
    }

    @Test
    public void boundsDiagnosticsAndKeepsTheNewestSignalFirst() {
        InputCalibrationLog log = new InputCalibrationLog(2);

        log.record(InputSignal.key(1, "DOWN", "KEYCODE_ENTER", true));
        log.record(InputSignal.key(2, "UP", "KEYCODE_ENTER", true));
        log.record(InputSignal.broadcast(3, "future.action", false));

        assertEquals(2, log.lines().size());
        assertTrue(log.lines().get(0).startsWith("#3 t=3"));
        assertTrue(log.lines().get(1).startsWith("#2 t=2"));
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsNonPositiveDiagnosticCapacity() {
        new InputCalibrationLog(0);
    }
}
