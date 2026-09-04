package dev.rokid.docscanglass.input;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class BackExitPolicyTest {

    @Test
    public void firstBackArmsConfirmationInsteadOfExiting() {
        BackExitPolicy policy = new BackExitPolicy();

        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(0));
        assertTrue(policy.isArmed());
    }

    @Test
    public void secondBackInsideTheConfirmationWindowExits() {
        BackExitPolicy policy = new BackExitPolicy();

        assertEquals(3_000, BackExitPolicy.CONFIRM_WINDOW_MILLIS);
        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(0));
        assertEquals(BackExitPolicy.Decision.EXIT, policy.onBack(3_000));
    }

    @Test
    public void secondBackOutsideTheConfirmationWindowRearmsInsteadOfExiting() {
        BackExitPolicy policy = new BackExitPolicy();

        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(0));
        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(3_001));
        assertTrue(policy.isArmed());
    }

    @Test
    public void resetDisarmsSoTheNextBackCannotExit() {
        BackExitPolicy policy = new BackExitPolicy();

        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(0));
        policy.reset();
        assertFalse(policy.isArmed());
        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(100));
    }

    @Test
    public void failsClosedWhenTheMonotonicClockMovesBackwards() {
        BackExitPolicy policy = new BackExitPolicy();

        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(1_000));
        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(999));
    }

    @Test
    public void exitingDisarmsSoAThirdBackStartsANewConfirmation() {
        BackExitPolicy policy = new BackExitPolicy();

        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(0));
        assertEquals(BackExitPolicy.Decision.EXIT, policy.onBack(1_500));
        assertFalse(policy.isArmed());
        assertEquals(BackExitPolicy.Decision.ARM_CONFIRMATION, policy.onBack(1_600));
    }
}
