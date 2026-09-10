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
                AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 2"),
                AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
        return new AnswerReader(bundle, 400f, 2, text -> text.length() * 10f);
    }

    @Test
    public void forwardAndBackMoveTheReader() {
        AnswerReader reader = reader();

        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SWIPE_FORWARD));
        assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SWIPE_BACK));

        assertEquals(1, reader.pageNumber());
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
