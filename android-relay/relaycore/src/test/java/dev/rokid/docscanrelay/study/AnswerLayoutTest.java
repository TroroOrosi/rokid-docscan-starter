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

    @Test public void aBracketedGroupIsNotBrokenAtItsComma() {
        // Glasses, 2026-11-16: "(5," ended a line and "0)" began the next, three times in one real answer.
        String answer = "軌跡は円から点(5,0)を除いたものである。";
        List<String> lines = new ArrayList<>();
        for (AnswerLayout.Page page : AnswerLayout.paginate(answer, 10, 1, MONO)) lines.addAll(page.lines);
        assertEquals(List.of("軌跡は円から点", "(5,0)を除いたも", "のである。"), lines);
        for (int width = 8; width <= 12; width++) {
            for (AnswerLayout.Page page : AnswerLayout.paginate(answer, width, 1, MONO)) {
                for (String line : page.lines) assertFalse(line + " at width " + width, line.endsWith("(5,"));
            }
        }
        // A group that has closed no longer holds the line back, and outside brackets a comma is still a break.
        lines.clear();
        for (AnswerLayout.Page page : AnswerLayout.paginate(answer, 14, 1, MONO)) lines.addAll(page.lines);
        assertEquals(List.of("軌跡は円から点(5,0)を除", "いたものである。"), lines);
        lines.clear();
        for (AnswerLayout.Page page : AnswerLayout.paginate("a=1,b=2,c=3", 6, 1, MONO)) lines.addAll(page.lines);
        assertEquals(List.of("a=1,", "b=2,", "c=3"), lines);
        // A function's argument list is not torn from its name: there the line breaks where it runs out, as before.
        lines.clear();
        for (AnswerLayout.Page page : AnswerLayout.paginate("y=f(a,b)", 6, 1, MONO)) lines.addAll(page.lines);
        assertEquals(List.of("y=f(a,", "b)"), lines);
        // A long remark in brackets is no such group: its line is filled as before, not cut short at the bracket.
        assertEquals("である(条件によって", AnswerLayout.paginate("である(条件によっては成り立たない)", 10, 1, MONO).get(0).lines.get(0));
    }

    private static List<String> linesOf(String text, float width) {
        List<String> lines = new ArrayList<>();
        for (AnswerLayout.Page page : AnswerLayout.paginate(text, width, 1, MONO)) lines.addAll(page.lines);
        return lines;
    }

    @Test public void aFormulaThatRunsOutInsideItsBracketsStartsTheNextLine() {
        // Glasses, 2026-11-16, with the first bracket rule in place: "R=(6-2a,-2b" still ended a line and ",3)"
        // began the next, because a letter and not Japanese text stood before the bracket. The formula begins
        // where Japanese text ends: the line breaks there.
        assertEquals(List.of("ゆえに重心の条件から求める点は", "R=(6-2a,-2b,3)である。"),
                linesOf("ゆえに重心の条件から求める点はR=(6-2a,-2b,3)である。", 26));
        assertEquals(List.of("ここで関数", "f(a,b)の値"), linesOf("ここで関数f(a,b)の値", 10));
        // Two formulas after a comma break at the comma, as before.
        assertEquals(List.of("A=(1,2), ", "B=(3,4)"), linesOf("A=(1,2), B=(3,4)", 12));
        // A formula that takes more than half the line does not leave the line before it half empty.
        assertEquals("よってR=(6-2a,", linesOf("よってR=(6-2a,-2b,3)", 11).get(0));
    }

    @Test public void aLineDoesNotBeginWithAClosingMark() {
        // Glasses, 2026-11-16: a line held "、" and nothing else. The character before it comes down with it.
        assertEquals(List.of("原点からの距離が5未満であ", "り、Mは内部"), linesOf("原点からの距離が5未満であり、Mは内部", 14));
        assertEquals(List.of("これは文であ", "る。次の文"), linesOf("これは文である。次の文", 7));
        // One character alone cannot give its place up.
        assertEquals(List.of("あ", "、", "い"), linesOf("あ、い", 1));
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

    @Test public void leadingWhitespaceKeepsFollowingContentWhenItFitsTheRow() {
        List<AnswerLayout.Page> pages = AnswerLayout.paginate("    abcdefghi", 8, 1, MONO);
        assertEquals(List.of("    abcd"), pages.get(0).lines);
        assertEquals(List.of("efghi"), pages.get(1).lines);
    }

    @Test public void leadingTabsWideSpacesJapaneseAndEmojiKeepTheirFollowingContent() {
        assertEquals(List.of(" \tabcd"), AnswerLayout.paginate(" \tabcdefgh", 6, 1, MONO).get(0).lines);
        assertEquals(List.of("　　あい"), AnswerLayout.paginate("　　あいうえお", 4, 1, MONO).get(0).lines);
        assertEquals(List.of("  あいうえ"), AnswerLayout.paginate("  あいうえおかき", 6, 1, MONO).get(0).lines);
        assertEquals(List.of("  😀😀"), AnswerLayout.paginate("  😀😀😀😀😀", 4, 1, MONO).get(0).lines);
    }

    @Test public void sourceWhitespaceOnlyLinesAndOverwideIndentationRemainVisible() {
        List<AnswerLayout.Page> blank = AnswerLayout.paginate("    \r\n \t \n", 3, 1, MONO);
        assertEquals(List.of("   "), blank.get(0).lines);
        assertEquals(List.of(" "), blank.get(1).lines);
        assertEquals(List.of(" \t "), blank.get(2).lines);
        assertEquals(List.of(false), blank.get(0).continuedFromPreviousLine);
        assertEquals(List.of(true), blank.get(1).continuedFromPreviousLine);
        assertEquals(List.of(false), blank.get(2).continuedFromPreviousLine);
        List<AnswerLayout.Page> indented = AnswerLayout.paginate("          abcdef", 4, 1, MONO);
        assertEquals(List.of("    "), indented.get(0).lines);
        assertEquals(List.of("    "), indented.get(1).lines);
        assertEquals(List.of("  ab"), indented.get(2).lines);
        assertEquals(List.of("cdef"), indented.get(3).lines);
    }

    @Test public void spacesAndPunctuationAfterContentKeepTheirExistingPreferredBreaks() {
        assertEquals(List.of("abc "), AnswerLayout.paginate("abc defghijkl", 8, 1, MONO).get(0).lines);
        assertEquals(List.of("字、"), AnswerLayout.paginate("字、abcdefghi", 5, 1, MONO).get(0).lines);
        assertEquals(List.of("、"), AnswerLayout.paginate("、abcdefghi", 5, 1, MONO).get(0).lines);
        assertEquals(List.of("ab;"), AnswerLayout.paginate("ab;cdefghijkl", 5, 1, MONO).get(0).lines);
    }

    @Test public void leadingWhitespaceAcrossPagesPreservesOffsetsAndLogicalLines() {
        List<String> expected = List.of("    abcdefghi  ", "", "      ", " \t abcdef",
                "  あいうえおかきくけこ、", "  😀😀e\u0301𝑥 = 1  ", "          abcdef", "done; next");
        String source = expected.get(0) + "\r\n\n" + expected.get(2) + "\r" + expected.get(3) + "\r\n"
                + expected.get(4) + "\n" + expected.get(5) + "\r\n" + expected.get(6) + "\r" + expected.get(7) + "\n";
        for (int width : new int[]{4, 8, 19}) for (int rows : new int[]{1, 2, 9}) {
            List<AnswerLayout.Page> pages = AnswerLayout.paginate(source, width, rows, MONO);
            pages.get(pages.size()-1);
            List<StringBuilder> logical = new ArrayList<>();
            StringBuilder exact = new StringBuilder();
            int offset = 0;
            for (AnswerLayout.Page page : pages) {
                assertEquals(offset, page.start);
                assertEquals(source.substring(page.start, page.end), page.sourceText);
                exact.append(page.sourceText);
                offset = page.end;
                for (int row = 0; row < page.lines.size(); row++) {
                    String line = page.lines.get(row);
                    assertTrue(MONO.width(line) <= width);
                    if (!page.continuedFromPreviousLine.get(row)) logical.add(new StringBuilder());
                    assertFalse(logical.isEmpty());
                    logical.get(logical.size()-1).append(line);
                    if (!line.isEmpty()) {
                        assertFalse(Character.isLowSurrogate(line.charAt(0)));
                        assertNotEquals('\u0301', line.charAt(0));
                    }
                }
            }
            List<String> restored = new ArrayList<>();
            for (StringBuilder line : logical) restored.add(line.toString());
            assertEquals(expected, restored);
            assertEquals(source, exact.toString());
            assertEquals(source.length(), offset);
        }
    }
}
