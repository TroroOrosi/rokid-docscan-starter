package dev.rokid.docscanrelay;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Builds the CustomView JSON accepted by Hi Rokid's media stream service. */
public final class HudLayout {
    private HudLayout() {
    }

    public static String fromLines(List<String> rawLines) {
        String text = normalizeLines(rawLines);
        return "{"
                + "\"type\":\"LinearLayout\","
                + "\"props\":{"
                + "\"id\":\"docscan_root\","
                + "\"layout_width\":\"match_parent\","
                + "\"layout_height\":\"match_parent\","
                + "\"orientation\":\"vertical\","
                + "\"gravity\":\"center\","
                + "\"backgroundColor\":\"#FF000000\""
                + "},"
                + "\"children\":[{"
                + "\"type\":\"TextView\","
                + "\"props\":{"
                + "\"id\":\"docscan_text\","
                + "\"layout_width\":\"match_parent\","
                + "\"layout_height\":\"wrap_content\","
                + "\"text\":\"" + escapeJson(text) + "\","
                + "\"textSize\":\"34sp\","
                + "\"textColor\":\"#00FF00\","
                + "\"gravity\":\"center\""
                + "}"
                + "}]"
                + "}";
    }

    public static String fromCaptureReview(String iconName, List<String> rawLines) {
        String text = normalizeLines(rawLines);
        return "{"
                + "\"type\":\"LinearLayout\","
                + "\"props\":{"
                + "\"id\":\"docscan_review_root\","
                + "\"layout_width\":\"match_parent\","
                + "\"layout_height\":\"match_parent\","
                + "\"orientation\":\"vertical\","
                + "\"gravity\":\"center\","
                + "\"backgroundColor\":\"#FF000000\""
                + "},"
                + "\"children\":[{"
                + "\"type\":\"ImageView\","
                + "\"props\":{"
                + "\"id\":\"docscan_capture_preview\","
                + "\"layout_width\":\"320dp\","
                + "\"layout_height\":\"220dp\","
                + "\"name\":\"" + escapeJson(iconName) + "\","
                + "\"scaleType\":\"fit_center\""
                + "}"
                + "},{"
                + "\"type\":\"TextView\","
                + "\"props\":{"
                + "\"id\":\"docscan_review_text\","
                + "\"layout_width\":\"match_parent\","
                + "\"layout_height\":\"wrap_content\","
                + "\"text\":\"" + escapeJson(text) + "\","
                + "\"textSize\":\"20sp\","
                + "\"textColor\":\"#00FF00\","
                + "\"gravity\":\"center\","
                + "\"marginTop\":\"8dp\""
                + "}"
                + "}]"
                + "}";
    }

    public static String fromCaptureAiming(int pageNumber, boolean retake) {
        return fromCaptureAiming(pageNumber, retake, false);
    }

    public static String fromCaptureAiming(
            int pageNumber,
            boolean retake,
            boolean stabilizing
    ) {
        if (pageNumber <= 0) {
            throw new IllegalArgumentException("page number must be positive");
        }
        String title = "P" + pageNumber + (retake ? "を撮り直し" : "を撮影");
        String frame = "┌──────────────┐\n"
                + "│      ＋      │\n"
                + "└──────────────┘";
        String instruction = stabilizing
                ? "シャッター受付\n1.5秒そのまま静止"
                : "40〜60cm / 用紙の中心を＋へ\n静止して長押し・四隅は撮影後確認";
        return "{"
                + "\"type\":\"LinearLayout\","
                + "\"props\":{"
                + "\"id\":\"docscan_aiming_root\","
                + "\"layout_width\":\"match_parent\","
                + "\"layout_height\":\"match_parent\","
                + "\"orientation\":\"vertical\","
                + "\"gravity\":\"center\","
                + "\"backgroundColor\":\"#00000000\""
                + "},"
                + "\"children\":["
                + textView("docscan_aiming_title", title, "24sp", "4dp")
                + ","
                + textView("docscan_aiming_frame", frame, "28sp", "10dp")
                + ","
                + textView("docscan_aiming_instruction", instruction, "20sp", "10dp")
                + "]"
                + "}";
    }

    private static String textView(
            String id,
            String text,
            String textSize,
            String marginTop
    ) {
        return "{"
                + "\"type\":\"TextView\","
                + "\"props\":{"
                + "\"id\":\"" + escapeJson(id) + "\","
                + "\"layout_width\":\"match_parent\","
                + "\"layout_height\":\"wrap_content\","
                + "\"text\":\"" + escapeJson(text) + "\","
                + "\"textSize\":\"" + escapeJson(textSize) + "\","
                + "\"textColor\":\"#00FF00\","
                + "\"gravity\":\"center\","
                + "\"marginTop\":\"" + escapeJson(marginTop) + "\""
                + "}"
                + "}";
    }

    private static String normalizeLines(List<String> rawLines) {
        List<String> lines = rawLines == null ? Collections.emptyList() : rawLines;
        List<String> normalized = new ArrayList<>(3);
        for (String line : lines) {
            if (normalized.size() == 3) {
                break;
            }
            normalized.add(line == null ? "" : line);
        }
        while (normalized.size() < 3) {
            normalized.add("");
        }
        return String.join("\n", normalized);
    }

    static String escapeJson(String value) {
        StringBuilder out = new StringBuilder(value.length() + 16);
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '\\':
                    out.append("\\\\");
                    break;
                case '"':
                    out.append("\\\"");
                    break;
                case '\n':
                    out.append("\\n");
                    break;
                case '\r':
                    out.append("\\r");
                    break;
                case '\t':
                    out.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
            }
        }
        return out.toString();
    }
}
