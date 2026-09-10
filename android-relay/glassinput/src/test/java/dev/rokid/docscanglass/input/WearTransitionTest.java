package dev.rokid.docscanglass.input;

import static org.junit.Assert.*;

import org.junit.Test;

public class WearTransitionTest {
    private static final float NEAR = 0f;
    private static final float FAR = 8f;

    @Test public void theFirstReadingIsRecordedButNeverCountsAsPuttingThemOn() {
        WearTransition wear = new WearTransition();
        assertFalse(wear.onReading(NEAR, 0));
        assertTrue(wear.worn());
    }

    @Test public void takingThemOffThenPuttingThemOnReportsOnce() {
        WearTransition wear = new WearTransition();
        wear.onReading(NEAR, 0);
        assertFalse(wear.onReading(FAR, 100));
        assertFalse(wear.onReading(FAR, 200));
        assertFalse(wear.onReading(FAR, 1_101));
        assertFalse(wear.worn());

        assertFalse(wear.onReading(NEAR, 2_000));
        assertTrue(wear.onReading(NEAR, 3_001));
        assertTrue(wear.worn());
        assertFalse(wear.onReading(NEAR, 4_000));
    }

    @Test public void aFlickerShorterThanTheSettleTimeIsIgnored() {
        WearTransition wear = new WearTransition();
        wear.onReading(FAR, 0);
        assertFalse(wear.onReading(NEAR, 100));
        assertFalse(wear.onReading(FAR, 300));
        assertFalse(wear.onReading(NEAR, 400));
        assertFalse(wear.worn());
    }

    @Test public void stayingOnDoesNotRestartTheSession() {
        WearTransition wear = new WearTransition();
        wear.onReading(NEAR, 0);
        for (int i = 1; i <= 20; i++) {
            assertFalse(wear.onReading(NEAR, i * 1_000L));
        }
    }

    @Test public void aClockThatGoesBackwardsRearmsInsteadOfFiring() {
        WearTransition wear = new WearTransition();
        wear.onReading(FAR, 10_000);
        assertFalse(wear.onReading(NEAR, 11_000));
        assertFalse(wear.onReading(NEAR, 5_000));
        assertFalse(wear.onReading(NEAR, 5_500));
        assertTrue(wear.onReading(NEAR, 6_100));
    }

    @Test public void theThresholdIsInclusiveAtTheMeasuredNearDistance() {
        WearTransition wear = new WearTransition();
        wear.onReading(FAR, 0);
        assertFalse(wear.onReading(WearTransition.WORN_CENTIMETRES, 100));
        assertTrue(wear.onReading(WearTransition.WORN_CENTIMETRES, 1_101));
    }
}
