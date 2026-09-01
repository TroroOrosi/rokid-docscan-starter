package dev.rokid.docscanglass.input;

import java.util.EnumMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * Recognizes only input sequences measured on Rokid build
 * {@code 1.25.012-20260901-150201} and deduplicates matching callback paths.
 */
public final class GlassesInputNormalizer {

    /** Largest measured prefix-to-terminal interval: a deliberately slow back swipe. */
    public static final long MEASURED_CORRELATION_MILLIS = 970;

    private static final String ACTION_CLICK =
            "com.android.action.ACTION_SPRITE_BUTTON_CLICK";
    private static final String ACTION_LONG_PRESS =
            "com.android.action.ACTION_SPRITE_BUTTON_LONG_PRESS";
    private static final String ACTION_AI_START =
            "com.android.action.ACTION_AI_START";
    private static final String ACTION_SWIPE_FORWARD =
            "com.android.action.ACTION_TWO_FINGER_SWIPE_FORWARD";
    private static final String ACTION_SWIPE_BACK =
            "com.android.action.ACTION_TWO_FINGER_SWIPE_BACK";

    private enum PendingDirection {
        NONE,
        FORWARD,
        BACK
    }

    private long lastSeenMillis = -1;
    private long notificationMillis = -1;
    private long directionMillis = -1;
    private PendingDirection pendingDirection = PendingDirection.NONE;
    private final Map<GlassesInputAction, Long> lastActionMillis =
            new EnumMap<>(GlassesInputAction.class);

    public synchronized Optional<GlassesInputAction> accept(InputSignal signal) {
        Objects.requireNonNull(signal, "signal");
        long now = signal.elapsedMillis();
        if (now < lastSeenMillis) {
            clearPending();
            return Optional.empty();
        }
        lastSeenMillis = now;
        if (!signal.known()) {
            clearPending();
            return Optional.empty();
        }
        if (signal.source() == InputSignal.Source.BROADCAST) {
            return acceptBroadcast(signal.name(), now);
        }
        if (!"DOWN".equals(signal.phase())) {
            return Optional.empty();
        }
        return acceptKey(signal.name(), now);
    }

    private Optional<GlassesInputAction> acceptBroadcast(String action, long now) {
        switch (action) {
            case ACTION_CLICK:
                return emit(GlassesInputAction.SHORT_TAP, now);
            case ACTION_LONG_PRESS:
            case ACTION_AI_START:
                return emit(GlassesInputAction.LONG_PRESS, now);
            case ACTION_SWIPE_FORWARD:
                return emit(GlassesInputAction.SWIPE_FORWARD, now);
            case ACTION_SWIPE_BACK:
                return emit(GlassesInputAction.SWIPE_BACK, now);
            default:
                return Optional.empty();
        }
    }

    private Optional<GlassesInputAction> acceptKey(String keyName, long now) {
        switch (keyName) {
            case "KEYCODE_NOTIFICATION":
                notificationMillis = now;
                directionMillis = -1;
                pendingDirection = PendingDirection.NONE;
                return Optional.empty();
            case "KEYCODE_ENTER":
                if (withinMeasuredBound(notificationMillis, now)) {
                    return emit(GlassesInputAction.SHORT_TAP, now);
                }
                clearPending();
                return Optional.empty();
            case "KEYCODE_DPAD_RIGHT":
                return armDirection(PendingDirection.FORWARD, now);
            case "KEYCODE_DPAD_LEFT":
                return armDirection(PendingDirection.BACK, now);
            case "KEYCODE_DPAD_DOWN":
                return finishDirection(
                        PendingDirection.FORWARD, GlassesInputAction.SWIPE_FORWARD, now);
            case "KEYCODE_DPAD_UP":
                return finishDirection(
                        PendingDirection.BACK, GlassesInputAction.SWIPE_BACK, now);
            default:
                clearPending();
                return Optional.empty();
        }
    }

    private Optional<GlassesInputAction> armDirection(
            PendingDirection direction, long now) {
        if (!withinMeasuredBound(notificationMillis, now)) {
            clearPending();
            return Optional.empty();
        }
        pendingDirection = direction;
        directionMillis = now;
        return Optional.empty();
    }

    private Optional<GlassesInputAction> finishDirection(
            PendingDirection expected, GlassesInputAction action, long now) {
        if (pendingDirection != expected
                || !withinMeasuredBound(notificationMillis, now)
                || !withinMeasuredBound(directionMillis, now)) {
            clearPending();
            return Optional.empty();
        }
        return emit(action, now);
    }

    private Optional<GlassesInputAction> emit(GlassesInputAction action, long now) {
        clearPending();
        Long previous = lastActionMillis.get(action);
        if (previous != null && withinMeasuredBound(previous, now)) {
            return Optional.empty();
        }
        lastActionMillis.put(action, now);
        return Optional.of(action);
    }

    private static boolean withinMeasuredBound(long startMillis, long endMillis) {
        return startMillis >= 0
                && endMillis >= startMillis
                && endMillis - startMillis <= MEASURED_CORRELATION_MILLIS;
    }

    private void clearPending() {
        notificationMillis = -1;
        directionMillis = -1;
        pendingDirection = PendingDirection.NONE;
    }
}
