package dev.rokid.docscanglass.probe;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * The ordered, content-free verdict of one capability probe run.
 *
 * <p>Every slot is declared up front and starts {@link Status#PENDING}, so a
 * probe that never ran is distinguishable from one that ran and failed. That
 * distinction is the whole point of the spike: an absent line would otherwise
 * be read as a negative result.
 *
 * <p>Details are bounded because the glasses render 480x640 and the report is
 * read through the display as well as through {@code logcat}.
 *
 * <p>Holds no image bytes, no page content, no credentials, and no server
 * payload — only status and a short shape description.
 */
public final class ProbeReport {

    /** Longest detail one line may carry, including the truncation marker. */
    public static final int MAX_DETAIL_CHARS = 48;

    private static final String TRUNCATION_MARKER = "...";

    public enum Status {
        PENDING,
        OK,
        FAILED
    }

    private final Map<String, String> results = new LinkedHashMap<>();

    public ProbeReport(List<String> orderedKeys) {
        Objects.requireNonNull(orderedKeys, "orderedKeys");
        for (String key : orderedKeys) {
            results.put(requireText(key), Status.PENDING.name());
        }
    }

    public synchronized void record(String key, Status status, String detail) {
        Objects.requireNonNull(status, "status");
        if (!results.containsKey(requireText(key))) {
            throw new IllegalArgumentException("undeclared probe key: " + key);
        }
        String bounded = bound(detail);
        results.put(key, bounded.isEmpty() ? status.name() : status.name() + " " + bounded);
    }

    public synchronized List<String> lines() {
        List<String> lines = new ArrayList<>(results.size());
        for (Map.Entry<String, String> entry : results.entrySet()) {
            lines.add(entry.getKey() + " " + entry.getValue());
        }
        return Collections.unmodifiableList(lines);
    }

    private static String bound(String detail) {
        if (detail == null || detail.isBlank()) {
            return "";
        }
        String trimmed = detail.trim();
        if (trimmed.length() <= MAX_DETAIL_CHARS) {
            return trimmed;
        }
        return trimmed.substring(0, MAX_DETAIL_CHARS - TRUNCATION_MARKER.length())
                + TRUNCATION_MARKER;
    }

    private static String requireText(String key) {
        Objects.requireNonNull(key, "key");
        if (key.isBlank()) {
            throw new IllegalArgumentException("key must not be blank");
        }
        return key;
    }
}
