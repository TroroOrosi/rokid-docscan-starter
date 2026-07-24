package dev.rokid.docscanrelay;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Builds the CustomView JSON accepted by Hi Rokid's media stream service. */
public final class HudLayout {
    private HudLayout() {
    }

    public static String fromLines(List<String> rawLines) {
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
        String text = String.join("\n", normalized);
        return "{"
                + "\"id\":\"docscan_root\","
                + "\"type\":\"LinearLayout\","
                + "\"props\":{"
                + "\"width\":\"match_parent\","
                + "\"height\":\"match_parent\","
                + "\"orientation\":\"vertical\","
                + "\"gravity\":\"center\","
                + "\"backgroundColor\":\"#000000\""
                + "},"
                + "\"children\":[{"
                + "\"id\":\"docscan_text\","
                + "\"type\":\"TextView\","
                + "\"props\":{"
                + "\"width\":\"match_parent\","
                + "\"height\":\"wrap_content\","
                + "\"text\":\"" + escapeJson(text) + "\","
                + "\"textSize\":34,"
                + "\"textColor\":\"#00FF00\","
                + "\"gravity\":\"center\""
                + "}"
                + "}]"
                + "}";
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
