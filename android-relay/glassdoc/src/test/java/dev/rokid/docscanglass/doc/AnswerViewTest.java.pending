package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;

import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
import dev.rokid.docscanrelay.study.AnswerReader;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class AnswerViewTest {
    private AnswerReader reader(String text) {
        return new AnswerReader(new AnswerBundle("s", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "大問1", "q1", "(1)", text))), 400, 2, String::length);
    }

    @Test public void longAnswerUsesThreeLinePagesAndKeepsItsReadableFontSize() {
        AnswerView view = new AnswerView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        float fontSize = view.bodyTextSize();
        String text = "記述する文章と数式 x₁²+x₂²=1。\n".repeat(70);
        AnswerReader reader = reader(text);
        view.bind(reader);
        StringBuilder restored = new StringBuilder();
        int count = reader.pageCount();
        assertTrue(count > 1);
        for (int i = 0; i < count; i++) {
            view.refresh();
            assertTrue(view.getContentDescription().toString().split("\n", -1).length <= 3);
            restored.append(text, reader.page().start, reader.page().end);
            reader.forward();
        }
        assertEquals(text, restored.toString());
        assertEquals(fontSize, view.bodyTextSize(), 0.001f);
    }

    @Test public void narrowerViewportReflowsInsteadOfShrinkingOrDroppingText() {
        AnswerView view = new AnswerView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        AnswerReader reader = reader("完全な答えを保持する。".repeat(40));
        view.bind(reader);
        int pages = reader.pageCount();
        float font = view.bodyTextSize();
        view.layout(0, 0, 280, 640);
        assertTrue(reader.pageCount() >= pages);
        assertEquals(font, view.bodyTextSize(), 0.001f);
    }

    @Test public void indexIsClearlySeparateFromTheWrittenAnswer() {
        AnswerView view = new AnswerView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        AnswerReader reader = reader("イ");
        view.bind(reader);
        assertTrue(view.getContentDescription().toString().contains("イ"));
        reader.tap();
        view.refresh();
        assertTrue(view.getContentDescription().toString().contains("大問を選択"));
        assertFalse(view.getContentDescription().toString().contains("\nイ"));
    }
}
