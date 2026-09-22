package dev.rokid.docscanglass.input;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.Optional;

import org.junit.Test;

public class GlassesInputNormalizerTest {

    @Test
    public void normalizesTheMeasuredLongPressBroadcast() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertTrue(normalizer.accept(key(0, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.LONG_PRESS),
                normalizer.accept(broadcast(816, "com.android.action.ACTION_AI_START")));
    }

    @Test
    public void normalizesBothMeasuredDirectionalSwipeSequences() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertEquals(970, GlassesInputNormalizer.MEASURED_CORRELATION_MILLIS);
        assertTrue(normalizer.accept(key(0, "KEYCODE_NOTIFICATION")).isEmpty());
        assertTrue(normalizer.accept(key(422, "KEYCODE_DPAD_RIGHT")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.SWIPE_FORWARD),
                normalizer.accept(key(445, "KEYCODE_DPAD_DOWN")));

        assertTrue(normalizer.accept(key(1_500, "KEYCODE_NOTIFICATION")).isEmpty());
        assertTrue(normalizer.accept(key(2_064, "KEYCODE_DPAD_LEFT")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.SWIPE_BACK),
                normalizer.accept(key(2_470, "KEYCODE_DPAD_UP")));
    }

    @Test
    public void distinguishesTheMeasuredShortTapAndDoubleTapSequences() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertTrue(normalizer.accept(key(0, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(key(516, "KEYCODE_ENTER")));
        assertTrue(normalizer.accept(key(2_000, "KEYCODE_NOTIFICATION")).isEmpty());
        assertTrue(normalizer.accept(key(2_207, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.BACK),
                normalizer.accept(key(2_519, "KEYCODE_BACK")));
    }

    @Test
    public void deduplicatesOfficialAndKeyReportsForOneGesture() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertEquals(
                Optional.of(GlassesInputAction.SWIPE_FORWARD),
                normalizer.accept(broadcast(
                        1_000,
                        "com.android.action.ACTION_TWO_FINGER_SWIPE_FORWARD")));
        assertEquals(
                Optional.of(GlassesInputAction.LONG_PRESS),
                normalizer.accept(broadcast(1_100, "com.android.action.ACTION_AI_START")));
        assertTrue(normalizer.accept(key(1_200, "KEYCODE_NOTIFICATION")).isEmpty());
        assertTrue(normalizer.accept(key(1_400, "KEYCODE_DPAD_RIGHT")).isEmpty());
        assertTrue(normalizer.accept(key(1_450, "KEYCODE_DPAD_DOWN")).isEmpty());

        assertEquals(
                Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(broadcast(
                        3_000,
                        "com.android.action.ACTION_SPRITE_BUTTON_CLICK")));
        assertTrue(normalizer.accept(key(3_100, "KEYCODE_NOTIFICATION")).isEmpty());
        assertTrue(normalizer.accept(key(3_500, "KEYCODE_ENTER")).isEmpty());
    }

    @Test
    public void preservesDistinctActionsAndSameActionsOutsideTheMeasuredBound() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertEquals(
                Optional.of(GlassesInputAction.LONG_PRESS),
                normalizer.accept(broadcast(0, "com.android.action.ACTION_AI_START")));
        assertEquals(
                Optional.of(GlassesInputAction.SWIPE_BACK),
                normalizer.accept(broadcast(
                        100,
                        "com.android.action.ACTION_TWO_FINGER_SWIPE_BACK")));
        assertEquals(
                Optional.of(GlassesInputAction.LONG_PRESS),
                normalizer.accept(broadcast(971, "com.android.action.ACTION_AI_START")));
        assertTrue(normalizer.accept(
                broadcast(1_941, "com.android.action.ACTION_AI_START")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.LONG_PRESS),
                normalizer.accept(broadcast(1_942, "com.android.action.ACTION_AI_START")));
    }

    @Test
    public void failsClosedForLateReorderedRepeatedAndUnknownSignals() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertTrue(normalizer.accept(InputSignal.key(
                0, "DOWN", "KEYCODE_FUTURE", false)).isEmpty());
        assertTrue(normalizer.accept(key(10, "KEYCODE_NOTIFICATION")).isEmpty());
        assertTrue(normalizer.accept(key(981, "KEYCODE_DPAD_RIGHT")).isEmpty());
        assertTrue(normalizer.accept(key(982, "KEYCODE_DPAD_DOWN")).isEmpty());
        assertTrue(normalizer.accept(key(1_100, "KEYCODE_DPAD_UP")).isEmpty());
        assertTrue(normalizer.accept(key(1_099, "KEYCODE_DPAD_LEFT")).isEmpty());
        assertTrue(normalizer.accept(InputSignal.key(
                1_200, "UP", "KEYCODE_DPAD_LEFT", true)).isEmpty());
    }

    @Test
    public void resetClearsPartialAndDeduplicationStateWithoutReplaying() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertTrue(normalizer.accept(key(0, "KEYCODE_NOTIFICATION")).isEmpty());
        normalizer.reset();
        assertTrue(normalizer.accept(key(500, "KEYCODE_ENTER")).isEmpty());

        assertTrue(normalizer.accept(key(600, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(key(700, "KEYCODE_ENTER")));

        normalizer.reset();
        assertTrue(normalizer.accept(key(710, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(key(720, "KEYCODE_ENTER")));
    }

    @Test
    public void normalizesTheMeasuredDoubleTapSequenceIntoABackAction() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertTrue(normalizer.accept(key(0, "KEYCODE_NOTIFICATION")).isEmpty());
        assertTrue(normalizer.accept(key(207, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.BACK),
                normalizer.accept(key(519, "KEYCODE_BACK")));
    }

    @Test
    public void failsClosedForBackKeysOutsideTheMeasuredCorrelation() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertTrue(normalizer.accept(key(0, "KEYCODE_BACK")).isEmpty());

        assertTrue(normalizer.accept(key(1_000, "KEYCODE_NOTIFICATION")).isEmpty());
        assertTrue(normalizer.accept(key(1_971, "KEYCODE_BACK")).isEmpty());

        assertTrue(normalizer.accept(key(3_000, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.BACK),
                normalizer.accept(key(3_970, "KEYCODE_BACK")));
    }

    @Test
    public void preservesDistinctFastBackGesturesButDropsRepeatedTerminalKeys() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();

        assertTrue(normalizer.accept(key(0, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.BACK),
                normalizer.accept(key(300, "KEYCODE_BACK")));

        assertTrue(normalizer.accept(key(400, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(Optional.of(GlassesInputAction.BACK),
                normalizer.accept(key(600, "KEYCODE_BACK")));
        assertTrue(normalizer.accept(key(601, "KEYCODE_BACK")).isEmpty());
        assertTrue(normalizer.accept(InputSignal.key(602, "UP", "KEYCODE_BACK", true)).isEmpty());

        assertTrue(normalizer.accept(key(1_400, "KEYCODE_NOTIFICATION")).isEmpty());
        assertEquals(
                Optional.of(GlassesInputAction.BACK),
                normalizer.accept(key(1_500, "KEYCODE_BACK")));
    }

    @Test
    public void pairsBroadcastCopiesWithoutDroppingTheNextCompleteKeyGesture() {
        GlassesInputNormalizer normalizer = new GlassesInputNormalizer();
        String click = "com.android.action.ACTION_SPRITE_BUTTON_CLICK";

        assertEquals(Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(broadcast(100, click)));
        normalizer.accept(key(110, "KEYCODE_NOTIFICATION"));
        assertTrue(normalizer.accept(key(200, "KEYCODE_ENTER")).isEmpty());
        // A second complete key sequence is a different physical gesture.
        normalizer.accept(key(300, "KEYCODE_NOTIFICATION"));
        assertEquals(Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(key(400, "KEYCODE_ENTER")));
        assertTrue(normalizer.accept(broadcast(410, click)).isEmpty());
        normalizer.accept(key(500, "KEYCODE_NOTIFICATION"));
        assertEquals(Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(key(600, "KEYCODE_ENTER")));
        assertTrue(normalizer.accept(broadcast(610, click)).isEmpty());

        normalizer.accept(key(700, "KEYCODE_NOTIFICATION"));
        normalizer.accept(key(710, "KEYCODE_DPAD_RIGHT"));
        assertEquals(Optional.of(GlassesInputAction.SWIPE_FORWARD),
                normalizer.accept(key(720, "KEYCODE_DPAD_DOWN")));
        normalizer.accept(key(800, "KEYCODE_NOTIFICATION"));
        normalizer.accept(key(810, "KEYCODE_DPAD_RIGHT"));
        assertEquals(Optional.of(GlassesInputAction.SWIPE_FORWARD),
                normalizer.accept(key(820, "KEYCODE_DPAD_DOWN")));

        normalizer.reset();
        normalizer.accept(key(1000, "KEYCODE_NOTIFICATION"));
        assertEquals(Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(broadcast(1100, click)));
        assertTrue(normalizer.accept(key(1150, "KEYCODE_ENTER")).isEmpty());
        normalizer.accept(key(1200, "KEYCODE_NOTIFICATION"));
        assertEquals(Optional.of(GlassesInputAction.SHORT_TAP),
                normalizer.accept(key(1250, "KEYCODE_ENTER")));
    }

    private static InputSignal key(long elapsedMillis, String name) {
        return InputSignal.key(elapsedMillis, "DOWN", name, true);
    }

    private static InputSignal broadcast(long elapsedMillis, String action) {
        return InputSignal.broadcast(elapsedMillis, action, true);
    }
}
