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

    private final long longPressMillis;
    private final long doublePressMillis;
    private long downAt = -1;
    private long pendingShortAt = -1;

    public PressGestureInterpreter(long longPressMillis, long doublePressMillis) {
        if (longPressMillis <= 0 || doublePressMillis <= 0) {
            throw new IllegalArgumentException("gesture thresholds must be positive");
        }
        this.longPressMillis = longPressMillis;
        this.doublePressMillis = doublePressMillis;
    }

    public synchronized void onDown(long nowMillis) {
        downAt = nowMillis;
    }

    /**
     * Returns LONG or DOUBLE_SHORT immediately. A first short press is delayed
     * until {@link #flush(long)} proves that no second short press followed.
     */
    public synchronized Action onUp(long nowMillis) {
        if (downAt < 0) {
            return null;
        }
        long duration = Math.max(0, nowMillis - downAt);
        downAt = -1;
        if (duration >= longPressMillis) {
            pendingShortAt = -1;
            return Action.LONG;
        }
        if (pendingShortAt >= 0 && nowMillis - pendingShortAt <= doublePressMillis) {
            pendingShortAt = -1;
            return Action.DOUBLE_SHORT;
        }
        pendingShortAt = nowMillis;
        return null;
    }

    public synchronized Action flush(long nowMillis) {
        // A second press may already be held when the timer posted for the
        // first release runs. Keep the first short pending until that release
        // decides between DOUBLE_SHORT and LONG.
        if (downAt >= 0) {
            return null;
        }
        if (pendingShortAt >= 0 && nowMillis - pendingShortAt >= doublePressMillis) {
            pendingShortAt = -1;
            return Action.SHORT;
        }
        return null;
    }

    public synchronized void cancel() {
        downAt = -1;
        pendingShortAt = -1;
    }
}
