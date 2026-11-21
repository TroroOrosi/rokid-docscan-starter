package dev.rokid.docscanglass.input;

import static org.junit.Assert.*;

import org.junit.Test;

public class WearTransitionTest {
    private static final float NEAR = 0f;
    private static final float FAR = 8f;

    @Test public void alreadyWornAtBootstrapSettlesOnceWithoutNeedingAnotherSensorChange() throws Exception {
        WearTransition wear = new WearTransition();
        assertFalse(wear.onReading(NEAR, 0));
        java.lang.reflect.Method settle = WearTransition.class.getDeclaredMethod("confirm", long.class);
        assertFalse((boolean)settle.invoke(wear, 999L));
        assertTrue((boolean)settle.invoke(wear, 1_000L));
        assertTrue(wear.worn());
        assertFalse((boolean)settle.invoke(wear, 2_000L));
    }

    @Test public void takingThemOffThenPuttingThemOnReportsOnce() {
        WearTransition wear = new WearTransition();
        wear.onReading(NEAR, 0);
        assertTrue(wear.onReading(NEAR, 1_000));
        assertFalse(wear.onReading(FAR, 1_100));
        assertFalse(wear.onReading(FAR, 1_200));
        assertFalse(wear.onReading(FAR, 2_101));
        assertFalse(wear.worn());

        assertFalse(wear.onReading(NEAR, 3_000));
        assertTrue(wear.onReading(NEAR, 4_001));
        assertTrue(wear.worn());
        assertFalse(wear.onReading(NEAR, 5_000));
    }

    @Test public void aFlickerShorterThanTheSettleTimeIsIgnored() {
        WearTransition wear = new WearTransition();
        wear.onReading(FAR, 0);
        wear.onReading(FAR, 1_000);
        assertFalse(wear.onReading(NEAR, 1_100));
        assertFalse(wear.onReading(FAR, 1_300));
        assertFalse(wear.onReading(NEAR, 1_400));
        assertFalse(wear.worn());
    }

    @Test public void stayingOnDoesNotRestartTheSession() {
        WearTransition wear = new WearTransition();
        wear.onReading(NEAR, 0);
        assertTrue(wear.onReading(NEAR, 1_000));
        for (int i = 2; i <= 20; i++) {
            assertFalse(wear.onReading(NEAR, i * 1_000L));
        }
    }

    @Test public void aClockThatGoesBackwardsRearmsInsteadOfFiring() {
        WearTransition wear = new WearTransition();
        wear.onReading(FAR, 10_000);
        wear.onReading(FAR, 11_000);
        assertFalse(wear.onReading(NEAR, 12_000));
        assertFalse(wear.onReading(NEAR, 5_000));
        assertFalse(wear.onReading(NEAR, 5_500));
        assertTrue(wear.onReading(NEAR, 6_100));
    }

    @Test public void theThresholdIsInclusiveAtTheMeasuredNearDistance() {
        WearTransition wear = new WearTransition();
        wear.onReading(FAR, 0);
        wear.onReading(FAR, 1_000);
        assertFalse(wear.onReading(WearTransition.WORN_CENTIMETRES, 1_100));
        assertTrue(wear.onReading(WearTransition.WORN_CENTIMETRES, 2_101));
    }
}
