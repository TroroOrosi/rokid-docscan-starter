package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import dev.rokid.docscanglass.input.GlassesInputAction;
import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
import dev.rokid.docscanrelay.study.AnswerReader;
import java.util.List;
import org.junit.Test;

public class AnswerGesturesTest {
    private AnswerReader reader() {
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1, List.of(
                // "x".repeat(90): at width=400f/measurer=length*10, each line holds 40
                // chars and each page holds 2 lines, so this answer paginates into
                // exactly two pages (80 chars, then 10). That lets
                // forwardAndBackMoveTheReader tell forward from back.
                AnswerItem.ready("g1", "第1問", "q10", "問1", "x".repeat(90)),
                AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
        return new AnswerReader(bundle, 400f, 2, text -> text.length() * 10f);
    }

    @Test
    public void forwardAndBackMoveTheReader() {
        AnswerReader reader = reader();

        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SWIPE_FORWARD));
        assertEquals(2, reader.pageNumber());

        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SWIPE_BACK));
        // Pin identity, not just page number: a one-sided SWIPE_BACK ->
        // forward() bug would overflow onto the second item, whose single
        // page also happens to report pageNumber() == 1.
        assertEquals("q10", reader.current().questionId);
        assertEquals(1, reader.pageNumber());
    }

    /** Continuous reading, the mode the glasses use: past either end a swipe comes round to the other. */
    @Test
    public void swipesWrapAroundTheEndsOfContinuousReading() {
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 2"),
                AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
        // One row a screen, and a row holds one of the two answers: two screens.
        AnswerReader reader = new AnswerReader(bundle, 400f, 1, text -> text.length() * 30f, true);
        assertEquals(2, reader.pageCount());

        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SWIPE_BACK));
        assertEquals("back from the first screen is the last", 2, reader.pageNumber());
        assertEquals("q11", reader.current().questionId);

        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SWIPE_FORWARD));
        assertEquals("forward from the last screen is the first", 1, reader.pageNumber());
        assertEquals("q10", reader.current().questionId);
    }

    @Test
    public void tapOpensTheMenu() {
        AnswerReader reader = reader();

        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SHORT_TAP));

        assertEquals(AnswerReader.Screen.GROUPS, reader.screen());
    }

    @Test
    public void backLeavesTheReaderOnlyFromTheTop() {
        AnswerReader reader = reader();
        AnswerGestures.apply(reader, GlassesInputAction.SHORT_TAP);

        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.BACK));
        assertFalse(AnswerGestures.apply(reader, GlassesInputAction.BACK));
    }

    @Test
    public void longPressIsNotBound() {
        AnswerReader reader = reader();

        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.LONG_PRESS));

        assertEquals(AnswerReader.Screen.ANSWER, reader.screen());
    }
}
