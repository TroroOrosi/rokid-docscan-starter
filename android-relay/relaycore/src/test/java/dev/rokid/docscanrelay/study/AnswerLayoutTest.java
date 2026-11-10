package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;

import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

public class AnswerLayoutTest {
    private static final AnswerLayout.Measurer MONO = s -> s.codePointCount(0, s.length());

    @Test public void longWrittenProofRoundTripsIncludingSpacesAndLineBreaks() {
        String answer = "仮定より AB = CD。\n次に対応角を比較する。\r\n".repeat(50) + "よって合同。";
        List<AnswerLayout.Page> pages = AnswerLayout.paginate(answer, 18, 2, MONO);
        StringBuilder restored = new StringBuilder();
        int end = 0;
        for (AnswerLayout.Page page : pages) {
            assertEquals(end, page.start);
            assertTrue(page.lines.size() <= 2);
            for (String line : page.lines) assertTrue(MONO.width(line) <= 18);
            restored.append(answer, page.start, page.end);
            end = page.end;
        }
        assertEquals(answer, restored.toString());
        assertEquals(answer.length(), end);
    }

    @Test public void longWordAndFormulaContinueWithoutEllipsisOrFontShrinking() {
        String answer = "antidisestablishmentarianism\nx₁²+x₂²=1234567890";
        List<AnswerLayout.Page> pages = AnswerLayout.paginate(answer, 8, 2, MONO);
        assertTrue(pages.size() > 1);
        assertEquals(answer.length(), pages.get(pages.size() - 1).end);
        assertEquals(0, pages.get(0).start);
    }

    @Test public void combiningMarksAndSurrogatePairsStayTogether() {
        String answer = "ABe\u0301𝑥CD";
        List<AnswerLayout.Page> pages = AnswerLayout.paginate(answer, 3, 1, MONO);
        for (AnswerLayout.Page page : pages) {
            if (page.end < answer.length()) {
                assertFalse(Character.isLowSurrogate(answer.charAt(page.end)));
                assertNotEquals('\u0301', answer.charAt(page.end));
            }
        }
    }

    @Test public void blankLinesAndTrailingNewlineKeepTheirOriginalOffsets() {
        String answer = "A\n\nB\n";
        List<AnswerLayout.Page> pages = AnswerLayout.paginate(answer, 20, 2, MONO);
        assertEquals(List.of("A", ""), pages.get(0).lines);
        assertEquals(3, pages.get(1).start);
        assertEquals(answer.length(), pages.get(1).end);
    }

    @Test public void actualFontMeasurementControlsTheBreaks() {
        AnswerLayout.Measurer variable = s -> s.chars().map(c -> c == 'W' ? 3 : 1).sum();
        List<AnswerLayout.Page> pages = AnswerLayout.paginate("WiWi", 4, 1, variable);
        assertEquals(List.of("Wi"), pages.get(0).lines);
        assertEquals(List.of("Wi"), pages.get(1).lines);
    }

    @Test public void unreasonableViewportIsRejectedInsteadOfAnInfiniteLoop() {
        assertThrows(IllegalArgumentException.class,
                () -> AnswerLayout.paginate("A", 0, 2, MONO));
        assertThrows(IllegalArgumentException.class,
                () -> AnswerLayout.paginate("A", 20, 0, MONO));
    }

    @Test public void millionsOfBlankLinesKeepTheirOffsetsAndRandomAccess() {
        String answer = "\n".repeat(8_000_000);
        List<AnswerLayout.Page> pages = AnswerLayout.paginate(answer, 40, 3, MONO);
        assertEquals(2_666_667, pages.size());
        for (int index : new int[]{2_666_666, 1365, 0, 1366, 1, 2_000_000}) {
            AnswerLayout.Page page = pages.get(index);
            assertEquals(index * 3, page.start);
            assertEquals(Math.min(answer.length(), index * 3 + 3), page.end);
            assertEquals(page.end - page.start, page.lines.size());
            for (String line : page.lines) assertEquals("", line);
        }
        assertThrows(UnsupportedOperationException.class, () -> pages.clear());
    }

    @Test public void randomAccessRetainsMixedNewlinesAndCachesTheCurrentPage() {
        java.util.concurrent.atomic.AtomicInteger calls = new java.util.concurrent.atomic.AtomicInteger();
        List<AnswerLayout.Page> pages = AnswerLayout.paginate("A\r\n\nB\rC\n", 20, 2, text -> {
            calls.incrementAndGet();
            return text.length();
        });
        AnswerLayout.Page second = pages.get(1);
        int measured = calls.get();
        assertEquals(List.of("B", "C"), second.lines);
        assertSame(second, pages.get(1));
        assertEquals(measured, calls.get());
        assertEquals(List.of("A", ""), pages.get(0).lines);
        assertEquals(4, pages.get(1).start);
        assertEquals(8, pages.get(1).end);
    }

    @Test public void indexedGroupsAndTwoLineTailKeepExactBoundaries() {
        String answer = "a\n".repeat(4096) + "b\n".repeat(2048)
                + "longer\n" + "b\n".repeat(2047) + "z\nz\n";
        List<AnswerLayout.Page> pages = AnswerLayout.paginate(answer, 40, 1, MONO);
        assertEquals(8194, pages.size());
        int start = 0;
        for (int index = 0; index < pages.size(); index++) {
            int end = answer.indexOf('\n', start) + 1;
            AnswerLayout.Page page = pages.get(index);
            assertEquals(start, page.start);
            assertEquals(end, page.end);
            assertEquals(List.of(answer.substring(start, end - 1)), page.lines);
            start = end;
        }
    }

    @Test public void punctuationBeforeAnIndexBoundaryStillUsesTheFollowingGlyphForWrapping() {
        AnswerLayout.Measurer variable = text -> text.chars()
                .map(character -> character == 'W' ? 3 : character == 'Y' ? 2 : 1).sum();
        List<AnswerLayout.Page> pages = AnswerLayout.paginate("\n".repeat(25) + ";WY", 4, 9, variable);
        assertEquals(List.of("", "", "", "", "", "", "", ";", "W"), pages.get(2).lines);
        assertEquals(18, pages.get(2).start);
        assertEquals(27, pages.get(2).end);
        assertEquals(List.of("Y"), pages.get(3).lines);
    }

    @Test public void displayRowsReconstructLogicalLinesAcrossPagesWithoutSourceOffsets() {
        List<String> expected = List.of("if ready:",
                "    total = long_function_name(argument_one, argument_two)", "",
                "    if total > 0:", "        print(total)", "done = True");
        String source = expected.get(0) + "\r\n" + expected.get(1) + "\r\n\r\n"
                + expected.get(3) + "\n" + expected.get(4) + "\r" + expected.get(5) + "\n";
        for (int width : new int[]{8, 19, 28}) for (int rows : new int[]{1, 2, 3}) {
            List<AnswerLayout.Page> pages = AnswerLayout.paginate(source, width, rows, MONO);
            // Metadata is derived correctly even when random access visits a later page first.
            pages.get(pages.size() - 1);
            List<StringBuilder> restored = new ArrayList<>();
            StringBuilder exactFragments = new StringBuilder();
            boolean continuedAtPageStart = false;
            for (AnswerLayout.Page page : pages) {
                assertEquals(page.lines.size(), page.continuedFromPreviousLine.size());
                exactFragments.append(page.sourceText);
                if (page.continuedFromPreviousLine.get(0)) continuedAtPageStart = true;
                for (int row = 0; row < page.lines.size(); row++) {
                    if (!page.continuedFromPreviousLine.get(row)) restored.add(new StringBuilder());
                    assertFalse("a continuation must have an earlier logical row", restored.isEmpty());
                    restored.get(restored.size()-1).append(page.lines.get(row));
                }
            }
            assertTrue("a wrapped logical line must continue onto another page", continuedAtPageStart);
            List<String> logicalLines = new ArrayList<>();
            for (StringBuilder line : restored) logicalLines.add(line.toString());
            assertEquals(expected, logicalLines);
            assertEquals("CRLF, CR, LF and all indentation remain exact", source, exactFragments.toString());
            assertThrows(UnsupportedOperationException.class,
                    () -> pages.get(0).continuedFromPreviousLine.set(0, true));
        }
    }

    @Test public void emptyTextHasNoContinuationAndKeepsAnEmptySourceFragment() {
        AnswerLayout.Page page = AnswerLayout.paginate("", 8, 1, MONO).get(0);
        assertEquals(List.of(""), page.lines);
        assertEquals(List.of(false), page.continuedFromPreviousLine);
        assertEquals("", page.sourceText);
    }
}
