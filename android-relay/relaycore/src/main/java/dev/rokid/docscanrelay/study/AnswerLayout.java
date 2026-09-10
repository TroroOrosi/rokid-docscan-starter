package dev.rokid.docscanrelay.study;

import java.text.BreakIterator;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** Pixel-measured pagination. Source offsets preserve every character for resume/reflow. */
public final class AnswerLayout {
    private AnswerLayout() {}

    public interface Measurer { float width(String text); }

    public static final class Page {
        public final int start;
        public final int end;
        public final List<String> lines;

        private Page(int start, int end, List<String> lines) {
            this.start = start;
            this.end = end;
            this.lines = Collections.unmodifiableList(new ArrayList<>(lines));
        }
    }

    public static List<Page> paginate(String text, float width, int linesPerPage,
                                      Measurer measurer) {
        if (text == null || measurer == null || !Float.isFinite(width)
                || width <= 0 || linesPerPage < 1) {
            throw new IllegalArgumentException("invalid answer viewport");
        }
        List<Page> pages = new ArrayList<>();
        List<String> lines = new ArrayList<>();
        BreakIterator clusters = BreakIterator.getCharacterInstance(Locale.ROOT);
        clusters.setText(text);
        int start = 0;
        int pageStart = 0;
        while (start < text.length()) {
            int end = start;
            int preferredBreak = start;
            while (end < text.length() && text.charAt(end) != '\n' && text.charAt(end) != '\r') {
                int next = clusterEnd(text, clusters, end);
                float measured = measurer.width(text.substring(start, next));
                if (!Float.isFinite(measured) || measured < 0) {
                    throw new IllegalArgumentException("invalid font measurement");
                }
                if (measured > width) {
                    if (end == start) throw new IllegalArgumentException("viewport narrower than glyph");
                    if (preferredBreak > start) end = preferredBreak;
                    break;
                }
                end = next;
                int last = text.codePointBefore(end);
                if (Character.isWhitespace(last) || "、。;,:".indexOf(last) >= 0) preferredBreak = end;
            }
            lines.add(text.substring(start, end));
            if (end < text.length() && text.charAt(end) == '\r') end++;
            if (end < text.length() && text.charAt(end) == '\n') end++;
            start = end;
            if (lines.size() == linesPerPage || end == text.length()) {
                pages.add(new Page(pageStart, end, lines));
                pageStart = end;
                lines.clear();
            }
        }
        if (pages.isEmpty()) pages.add(new Page(0, 0, Collections.singletonList("")));
        return Collections.unmodifiableList(pages);
    }

    private static int clusterEnd(String text, BreakIterator clusters, int start) {
        int end = clusters.following(start);
        // Older Android character iterators split emoji joined with ZWJ.
        while (end < text.length()) {
            int cp = text.codePointAt(end);
            int type = Character.getType(cp);
            if (cp == 0x200D && end + 1 < text.length()) {
                end = clusters.following(end + 1);
            } else if (type == Character.NON_SPACING_MARK || type == Character.COMBINING_SPACING_MARK
                    || cp == 0xFE0F || (cp >= 0x1F3FB && cp <= 0x1F3FF)) {
                end += Character.charCount(cp);
            } else break;
        }
        return end;
    }
}
