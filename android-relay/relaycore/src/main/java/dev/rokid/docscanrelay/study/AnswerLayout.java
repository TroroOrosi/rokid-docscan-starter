package dev.rokid.docscanrelay.study;

import java.text.BreakIterator;
import java.util.AbstractList;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.RandomAccess;

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
        Pagination pages = new Pagination(text, width, linesPerPage, measurer);
        int start = 0;
        while (start < text.length()) {
            start = lineEnd(text, start, width, measurer, pages.clusters);
            pages.addLineEnd(start);
        }
        return Collections.unmodifiableList(pages);
    }

    private static int lineEnd(String text, int start, float width,
                               Measurer measurer, BreakIterator clusters) {
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
        if (end < text.length() && text.charAt(end) == '\r') end++;
        if (end < text.length() && text.charAt(end) == '\n') end++;
        return end;
    }

    /** Index small page groups and materialize only the current page. */
    private static final class Pagination extends AbstractList<Page> implements RandomAccess {
        private static final int BLOCK_SIZE = 4096;
        private static final int INDEX_LINES = 32;
        private final String text;
        private final float width;
        private final int linesPerPage;
        private final Measurer measurer;
        private final BreakIterator clusters;
        private final int pagesPerIndex;
        private final int linesPerIndex;
        private final List<int[]> indexEnds = new ArrayList<>();
        private int lineCount;
        private int indexCount;
        private int cachedIndex = -1;
        private Page cachedPage;

        Pagination(String text, float width, int linesPerPage, Measurer measurer) {
            this.text = text;
            this.width = width;
            this.linesPerPage = linesPerPage;
            this.measurer = measurer;
            clusters = BreakIterator.getCharacterInstance(Locale.ROOT);
            clusters.setText(text);
            pagesPerIndex = Math.max(1, INDEX_LINES / linesPerPage);
            linesPerIndex = linesPerPage * pagesPerIndex;
        }

        void addLineEnd(int end) {
            lineCount++;
            if (lineCount % linesPerIndex == 0) addIndexEnd(end);
        }

        private void addIndexEnd(int end) {
            if (indexCount % BLOCK_SIZE == 0) {
                indexEnds.add(new int[Math.min(BLOCK_SIZE,
                        1 + text.length() / linesPerIndex - indexCount)]);
            }
            indexEnds.get(indexCount / BLOCK_SIZE)[indexCount % BLOCK_SIZE] = end;
            indexCount++;
        }

        private int indexEnd(int index) {
            return index < 0 ? 0 : indexEnds.get(index / BLOCK_SIZE)[index % BLOCK_SIZE];
        }

        @Override public int size() {
            return lineCount == 0 ? 1 : 1 + (lineCount - 1) / linesPerPage;
        }

        @Override public synchronized Page get(int index) {
            if (index < 0 || index >= size()) throw new IndexOutOfBoundsException();
            if (index == cachedIndex) return cachedPage;
            if (lineCount == 0) return new Page(0, 0, Collections.singletonList(""));
            int group = index / pagesPerIndex;
            int start = indexEnd(group - 1);
            int skippedLines = index % pagesPerIndex * linesPerPage;
            for (int line = 0; line < skippedLines; line++) {
                start = lineEnd(text, start, width, measurer, clusters);
            }
            int firstLine = index * linesPerPage;
            int lastLine = firstLine + Math.min(linesPerPage, lineCount - firstLine);
            int pageStart = start;
            List<String> lines = new ArrayList<>();
            for (int line = firstLine; line < lastLine; line++) {
                int consumedEnd = lineEnd(text, start, width, measurer, clusters);
                int end = consumedEnd;
                if (end > start && text.charAt(end - 1) == '\n') end--;
                if (end > start && text.charAt(end - 1) == '\r') end--;
                lines.add(text.substring(start, end));
                start = consumedEnd;
            }
            cachedIndex = index;
            cachedPage = new Page(pageStart, start, lines);
            return cachedPage;
        }
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
