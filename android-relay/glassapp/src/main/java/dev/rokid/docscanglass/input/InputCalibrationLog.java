package dev.rokid.docscanglass.input;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Objects;

/** Bounded, newest-first diagnostics for calibrating two Android input paths. */
public final class InputCalibrationLog {

    private final int capacity;
    private final Deque<String> lines = new ArrayDeque<>();
    private long sequence;

    public InputCalibrationLog(int capacity) {
        if (capacity <= 0) {
            throw new IllegalArgumentException("capacity must be positive");
        }
        this.capacity = capacity;
    }

    public synchronized void record(InputSignal signal) {
        sequence++;
        lines.addFirst(Objects.requireNonNull(signal, "signal").diagnostic(sequence));
        while (lines.size() > capacity) {
            lines.removeLast();
        }
    }

    public synchronized List<String> lines() {
        return List.copyOf(new ArrayList<>(lines));
    }
}
