package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;

import java.util.List;
import org.junit.Test;

public class AnswerReaderTest {
    private AnswerBundle initial() {
        return new AnswerBundle("session", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "大問1", "g1-q1", "(1)", "abcdefghijkl"),
                new AnswerItem("g1", "大問1", "g1-q2", "(2)", "", AnswerItem.Status.PENDING, ""),
                AnswerItem.ready("g2", "大問2", "g2-q1", "(1)", "イ")));
    }

    private AnswerReader reader() {
        return new AnswerReader(initial(), 4, 2, String::length);
    }

    @Test public void swipesMoveThroughFullAnswersAndReturnAcrossQuestionBoundary() {
        AnswerReader reader = reader();
        assertEquals(List.of("abcd", "efgh"), reader.page().lines);
        reader.forward();
        assertEquals(List.of("ijkl"), reader.page().lines);
        reader.forward();
        assertEquals("g1-q2", reader.current().questionId);
        assertEquals(AnswerItem.Status.PENDING, reader.current().status);
        reader.backward();
        assertEquals("g1-q1", reader.current().questionId);
        assertEquals(8, reader.offset());
    }

    @Test public void tappingOpensGroupThenQuestionIndexWithoutChangingReadPosition() {
        AnswerReader reader = reader();
        reader.forward();
        reader.tap();
        assertEquals(AnswerReader.Screen.GROUPS, reader.screen());
        reader.forward();
        reader.tap();
        assertEquals(AnswerReader.Screen.QUESTIONS, reader.screen());
        reader.tap();
        assertEquals(AnswerReader.Screen.ANSWER, reader.screen());
        assertEquals("g2-q1", reader.current().questionId);
        assertEquals("イ", reader.current().answer);
    }

    @Test public void backingOutOfIndexReturnsToTheSameQuestionAndPage() {
        AnswerReader reader = reader();
        reader.forward();
        reader.tap();
        reader.forward();
        assertFalse(reader.back());
        assertEquals("g1-q1", reader.current().questionId);
        assertEquals(8, reader.offset());
        assertTrue(reader.back()); // host persists CLOSED before leaving the answer screen
    }

    @Test public void laterAnswerDoesNotMoveCurrentQuestionOrPage() {
        AnswerReader reader = reader();
        reader.forward();
        AnswerBundle next = initial().withAnswer(AnswerItem.ready("g1", "大問1", "g1-q2", "(2)", "ウ"));
        assertTrue(reader.accept(next));
        assertEquals("g1-q1", reader.current().questionId);
        assertEquals(8, reader.offset());
        assertFalse(reader.accept(initial()));
        assertFalse(reader.accept(new AnswerBundle("other", "a".repeat(64), 3, next.items)));
        assertFalse(reader.accept(new AnswerBundle("session", "b".repeat(64), 3, next.items)));
    }

    @Test public void resumeAndFontReflowKeepTheOriginalCharacterPosition() {
        AnswerReader reader = reader();
        reader.restore("g1-q1", 8);
        assertEquals(8, reader.offset());
        reader.viewport(3, 2, String::length);
        assertTrue(reader.page().start <= 8 && reader.page().end > 8);
    }

    @Test public void sameInputCannotReplaceTheQuestionOrderOrIdentity() {
        AnswerReader reader = reader();
        List<AnswerItem> old = initial().items;
        assertFalse(reader.accept(new AnswerBundle("session", "a".repeat(64), 2,
                List.of(old.get(2), old.get(1), old.get(0)))));
        assertEquals("g1-q1", reader.current().questionId);
    }
}
