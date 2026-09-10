package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;

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
}
