package dev.rokid.docscanglass;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/**
 * Bounded, most-recent-first record of the input a glasses-side app receives.
 *
 * <p>There is no way to read this app's logcat: the glasses expose no
 * documented adb, and no CXR-S to CXR-L message channel is documented either.
 * The operator reads the result off the glasses display, so the record has to
 * be short enough to fit and ordered newest first.</p>
 *
 * <p>Event naming is left to the caller. {@code MotionEvent.actionToString} and
 * {@code KeyEvent.keyCodeToString} already do it correctly, and duplicating
 * their constants here would put an untested copy of the platform's table in
 * the one class that is unit tested.</p>
 */
final class TapLog {

    private final int capacity;
    private final ArrayList<String> lines = new ArrayList<>();

    private int touchEvents;
    private int touchDowns;
    private int keyEvents;
    private int gestureTaps;
    private int swipes;

    TapLog(int capacity) {
        if (capacity <= 0) {
            throw new IllegalArgumentException("capacity must be positive");
        }
        this.capacity = capacity;
    }

    synchronized void recordTouch(
            long elapsedMillis,
            String action,
            boolean primaryDown,
            float x,
            float y,
            int pointerCount
    ) {
        touchEvents++;
        if (primaryDown) {
            touchDowns++;
        }
        add(String.format(
                Locale.US,
                "%6d %s (%.0f,%.0f) p=%d",
                elapsedMillis,
                action,
                x,
                y,
                pointerCount));
    }

    synchronized void recordKey(long elapsedMillis, String action, String keyName) {
        keyEvents++;
        add(String.format(Locale.US, "%6d %s %s", elapsedMillis, action, keyName));
    }

    synchronized void recordGestureTap(long elapsedMillis) {
        gestureTaps++;
        add(String.format(Locale.US, "%6d TAP", elapsedMillis));
    }

    synchronized void recordSwipe(long elapsedMillis, String direction) {
        swipes++;
        add(String.format(Locale.US, "%6d SWIPE %s", elapsedMillis, direction));
    }

    /** The one line that answers the question this app exists to ask. */
    synchronized String counters() {
        return String.format(
                Locale.US,
                "DOWN %d  TAP %d  SWIPE %d  KEY %d  EVT %d",
                touchDowns,
                gestureTaps,
                swipes,
                keyEvents,
                touchEvents + keyEvents);
    }

    /** True once anything at all has arrived from the operator. */
    synchronized boolean receivedAnything() {
        return touchEvents + keyEvents > 0;
    }

    /** Newest first, at most {@code capacity} entries. */
    synchronized List<String> lines() {
        return Collections.unmodifiableList(new ArrayList<>(lines));
    }

    private void add(String line) {
        lines.add(0, line);
        while (lines.size() > capacity) {
            lines.remove(lines.size() - 1);
        }
    }
}
