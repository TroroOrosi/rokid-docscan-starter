package dev.rokid.docscanrelay;

/**
 * Converts the only input events exposed by the public CXR-L AI callback
 * (key down/up) into short, double-short and long actions.
 *
 * <p>The class contains no Android dependencies so the timing rules can be
 * covered by normal JVM tests.</p>
 */
public final class PressGestureInterpreter {
    public enum Action {
        SHORT,
        DOUBLE_SHORT,
        LONG
    }

    /**
     * A view pushed by the relay makes the glasses echo an AI-exit a few
     * milliseconds later. Echoes measured on Hi Rokid G1.12.10.0815 arrived
     * within 51 ms of the push, while a real tap arrived seconds after the
     * last view operation, so this window separates the two safely.
     */
    private static final long PROGRAMMATIC_EXIT_ECHO_MILLIS = 500;

    private final long longPressMillis;
    private final long doublePressMillis;
    private final long customViewArbitrationMillis;
    private long downAt = -1;
    private long pendingShortAt = -1;
    private long aiAssistDeduplicateUntil = -1;
    private long aiAssistActiveUntil = -1;
    private long suppressCustomViewUntil = -1;
    private boolean suppressCurrentPress;
    private boolean pendingCustomViewExit;
    private long lastViewOperationAt = -1;
    private long lastTapAt = -1;

    public PressGestureInterpreter(long longPressMillis, long doublePressMillis) {
        if (longPressMillis <= 0 || doublePressMillis <= 0) {
            throw new IllegalArgumentException("gesture thresholds must be positive");
        }
        this.longPressMillis = longPressMillis;
        this.doublePressMillis = doublePressMillis;
        customViewArbitrationMillis = longPressMillis + doublePressMillis;
    }

    public synchronized void onDown(long nowMillis) {
        if (nowMillis <= aiAssistDeduplicateUntil) {
            suppressCurrentPress = true;
            downAt = -1;
            return;
        }
        suppressCurrentPress = false;
        downAt = nowMillis;
    }

    /**
     * Returns LONG or DOUBLE_SHORT immediately. A first short press is delayed
     * until {@link #flush(long)} proves that no second short press followed.
     */
    public synchronized Action onUp(long nowMillis) {
        if (suppressCurrentPress) {
            suppressCurrentPress = false;
            return null;
        }
        if (downAt < 0) {
            return null;
        }
        long duration = Math.max(0, nowMillis - downAt);
        downAt = -1;
        if (duration >= longPressMillis) {
            pendingShortAt = -1;
            pendingCustomViewExit = false;
            return Action.LONG;
        }
        if (pendingShortAt >= 0 && nowMillis - pendingShortAt <= doublePressMillis) {
            pendingShortAt = -1;
            pendingCustomViewExit = false;
            return Action.DOUBLE_SHORT;
        }
        pendingShortAt = nowMillis;
        pendingCustomViewExit = false;
        return null;
    }

    public synchronized Action flush(long nowMillis) {
        // A second press may already be held when the timer posted for the
        // first release runs. Keep the first short pending until that release
        // decides between DOUBLE_SHORT and LONG.
        if (downAt >= 0) {
            return null;
        }
        long requiredDelay = pendingCustomViewExit
                ? customViewArbitrationMillis
                : doublePressMillis;
        if (pendingShortAt >= 0 && nowMillis - pendingShortAt >= requiredDelay) {
            pendingShortAt = -1;
            pendingCustomViewExit = false;
            return Action.SHORT;
        }
        return null;
    }

    /**
     * Queues the standalone signal emitted when a user closes a CustomView.
     *
     * <p>Some Global Hi Rokid builds close the CustomView without delivering
     * a matching key-up event. Dispatch is delayed until {@link #flush(long)}
     * so an AI-assist-start callback from the same long press can take
     * precedence without first triggering the short action.</p>
     */
    public synchronized Action onCustomViewExit(long nowMillis) {
        if (nowMillis <= suppressCustomViewUntil) {
            return null;
        }
        downAt = -1;
        suppressCurrentPress = false;
        if (pendingShortAt < 0) {
            pendingShortAt = nowMillis;
        }
        pendingCustomViewExit = true;
        return null;
    }

    /**
     * Treats the SDK's AI-assist-start event as the glasses long action.
     * The CustomView close caused by the same long press is coalesced.
     */
    public synchronized Action onAiAssistStart(long nowMillis) {
        if (nowMillis <= aiAssistDeduplicateUntil
                || nowMillis <= aiAssistActiveUntil) {
            return null;
        }
        aiAssistDeduplicateUntil = nowMillis + doublePressMillis;
        aiAssistActiveUntil = nowMillis + customViewArbitrationMillis;
        suppressCustomViewUntil = Math.max(
                suppressCustomViewUntil,
                aiAssistActiveUntil);
        downAt = -1;
        pendingShortAt = -1;
        pendingCustomViewExit = false;
        suppressCurrentPress = false;
        return Action.LONG;
    }

    /** Records a view push so its AI-exit echo is not mistaken for a tap. */
    public synchronized void onGlassesViewOperation(long nowMillis) {
        lastViewOperationAt = nowMillis;
    }

    /**
     * Treats a user-originated AI-exit as the glasses short action.
     *
     * <p>YodaOS reserves long press (record/audio toggle) and double tap
     * (exit), and Hi Rokid G1.12.10.0815 delivers neither AI key down/up nor a
     * user-initiated CustomView close to a third-party app. A single tap,
     * observed only as this exit callback, is therefore the sole glasses input
     * the relay can receive, so no committing action may be derived from it.</p>
     */
    public synchronized Action onAiExit(long nowMillis) {
        boolean closedActiveAssist = nowMillis <= aiAssistActiveUntil;
        onAiAssistExit(nowMillis);
        if (closedActiveAssist) {
            return null;
        }
        if (lastViewOperationAt >= 0
                && nowMillis - lastViewOperationAt < PROGRAMMATIC_EXIT_ECHO_MILLIS) {
            return null;
        }
        if (lastTapAt >= 0 && nowMillis - lastTapAt < doublePressMillis) {
            return null;
        }
        lastTapAt = nowMillis;
        return Action.SHORT;
    }

    public synchronized void onAiAssistExit(long nowMillis) {
        if (nowMillis <= aiAssistActiveUntil) {
            suppressCustomViewUntil = Math.max(
                    suppressCustomViewUntil,
                    nowMillis + doublePressMillis);
        }
        aiAssistActiveUntil = -1;
    }

    /**
     * Cancels only the close-derived short action when the absence of a
     * replacement view proves that the glasses navigated to the system menu.
     */
    public synchronized void cancelPendingCustomViewExit() {
        if (!pendingCustomViewExit) {
            return;
        }
        pendingShortAt = -1;
        pendingCustomViewExit = false;
    }

    public synchronized void cancel() {
        downAt = -1;
        pendingShortAt = -1;
        aiAssistDeduplicateUntil = -1;
        aiAssistActiveUntil = -1;
        suppressCustomViewUntil = -1;
        suppressCurrentPress = false;
        pendingCustomViewExit = false;
        lastViewOperationAt = -1;
        lastTapAt = -1;
    }
}
