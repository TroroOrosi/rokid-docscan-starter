package dev.rokid.docscanglass.doc;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The three lines the operator sees.
 *
 * <p>The server reports {@code hud.max_lines = 3}, and the glasses measured
 * 480x640 at 240dpi, so a fourth line is not untidy — it is off the glass.
 * Rendering is pure, so the wording is testable without a display.
 */
public final class HudLines {

    /** Server HUD contract. */
    public static final int MAX_LINES = 3;

    /**
     * Monospace at a size that fills 480 px. Longer text is cut rather than
     * wrapped, because wrapping would create the fourth line.
     */
    public static final int MAX_CHARS = 22;

    private HudLines() {
    }

    /**
     * @param state the scan state machine's current state
     * @param nextPageIndex zero-based; the operator is shown this plus one
     * @param waiting pages buffered for upload
     * @param lastError may be null or blank
     */
    public static List<String> render(
            ScanSession.State state, int nextPageIndex, int waiting, String lastError) {
        List<String> lines = new ArrayList<>(MAX_LINES);
        if (state == ScanSession.State.NO_DOCUMENT) {
            add(lines, "TAP TO START");
            add(lines, waiting > 0 ? waiting + " WAITING" : null);
            return Collections.unmodifiableList(lines);
        }

        add(lines, "PAGE " + (nextPageIndex + 1));
        add(lines, stageLine(state, lastError));
        add(lines, waiting > 0 ? waiting + " WAITING" : null);
        return Collections.unmodifiableList(lines);
    }

    private static String stageLine(ScanSession.State state, String lastError) {
        switch (state) {
            case OPENING:
                return "STARTING";
            case CAPTURING:
                return "CAPTURING";
            case REVIEW:
                return "TAP OK / SWIPE RETAKE";
            case RECOGNIZING:
                return "READING";
            case UPLOADING:
                return "SENDING";
            case ACKED:
                return "SAVED - TAP NEXT";
            case FAILED:
                return "FAILED " + shortReason(lastError);
            default:
                return "TAP TO SHOOT";
        }
    }

    /**
     * Keeps the leading word so {@code FAILED} stays readable, and drops the
     * package prefix an exception name carries.
     */
    private static String shortReason(String lastError) {
        if (lastError == null || lastError.trim().isEmpty()) {
            return "-";
        }
        String reason = lastError.trim();
        int lastDot = reason.lastIndexOf('.', reason.indexOf(':') < 0
                ? reason.length() - 1 : reason.indexOf(':'));
        if (lastDot >= 0 && lastDot + 1 < reason.length()) {
            reason = reason.substring(lastDot + 1);
        }
        return reason;
    }

    private static void add(List<String> lines, String line) {
        if (line == null || line.trim().isEmpty() || lines.size() >= MAX_LINES) {
            return;
        }
        String trimmed = line.trim();
        lines.add(trimmed.length() <= MAX_CHARS ? trimmed : trimmed.substring(0, MAX_CHARS));
    }
}
