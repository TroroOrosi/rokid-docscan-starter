package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class CaptureActionRouterTest {
    @Test
    public void unverifiedGlassesEventsNeverBecomeOperatorCommands() {
        for (RelayState state : RelayState.values()) {
            for (PressGestureInterpreter.Action action
                    : PressGestureInterpreter.Action.values()) {
                assertEquals(
                        state + " / " + action,
                        CaptureActionRouter.Command.NONE,
                        CaptureActionRouter.route(state, action));
            }
        }
    }
}
