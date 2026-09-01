package dev.rokid.docscanglass.input;

import java.util.Objects;

/** One content-free input observation captured against a monotonic clock. */
public final class InputSignal {

    public enum Source {
        BROADCAST,
        KEY_EVENT
    }

    private final long elapsedMillis;
    private final Source source;
    private final String phase;
    private final String name;
    private final boolean known;

    private InputSignal(
            long elapsedMillis, Source source, String phase, String name, boolean known) {
        if (elapsedMillis < 0) {
            throw new IllegalArgumentException("elapsedMillis must not be negative");
        }
        this.elapsedMillis = elapsedMillis;
        this.source = Objects.requireNonNull(source, "source");
        this.phase = requireText(phase, "phase");
        this.name = requireText(name, "name");
        this.known = known;
    }

    public static InputSignal broadcast(long elapsedMillis, String action, boolean known) {
        return new InputSignal(elapsedMillis, Source.BROADCAST, "EVENT", action, known);
    }

    public static InputSignal key(
            long elapsedMillis, String phase, String keyName, boolean known) {
        return new InputSignal(elapsedMillis, Source.KEY_EVENT, phase, keyName, known);
    }

    public boolean known() {
        return known;
    }

    String diagnostic(long sequence) {
        return "#" + sequence
                + " t=" + elapsedMillis
                + " src=" + source
                + " phase=" + phase
                + " name=" + name
                + " known=" + known;
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name);
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}
