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
    @Test
    @org.robolectric.annotation.GraphicsMode(org.robolectric.annotation.GraphicsMode.Mode.NATIVE)
    public void diagramAndBoundaryLabelAreVisibleAndFullyReadable() throws Exception {
        String longLabel = "boundary label ".repeat(5);
        org.json.JSONObject figure = new org.json.JSONObject()
                .put("alt", "Right triangle; boundary label retained").put("aspect_ratio", 1)
                .put("elements", new org.json.JSONArray()
                        .put(new org.json.JSONObject("{\"type\":\"polyline\",\"points\":[[0.1,0.1],[0.1,0.8],[0.9,0.8],[0.1,0.1]]}"))
                        .put(new org.json.JSONObject().put("type", "text").put("x", 1).put("y", 1).put("text", longLabel)));
        AnswerItem item = new AnswerItem("g1", "大問1", "q1", "(1)", "x = 2", AnswerItem.Status.READY, "",
                List.of(new dev.rokid.docscanrelay.study.AnswerDiagram(figure)));
        AnswerReader reader = new AnswerReader(new AnswerBundle("s", "a".repeat(64), 1, List.of(item)), 400, 2, String::length);
        AnswerView view = new AnswerView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.bind(reader);
        StringBuilder visible = new StringBuilder();
        while (reader.diagram() == null) {
            visible.append(String.join("", reader.page().lines));
            reader.forward();
        }
        assertTrue(visible.toString().contains(longLabel.trim()));
        view.refresh();
        android.graphics.Bitmap bitmap = android.graphics.Bitmap.createBitmap(480, 640, android.graphics.Bitmap.Config.ARGB_8888);
        view.draw(new android.graphics.Canvas(bitmap));
        int green = 0;
        for (int y = 110; y < 640; y++) for (int x = 0; x < 480; x++) {
            if (android.graphics.Color.green(bitmap.getPixel(x, y)) > 100) green++;
        }
        assertTrue("visible diagram pixels", green > 300);
        java.io.File output = new java.io.File("build/outputs/diagram-review.png");
        output.getParentFile().mkdirs();
        try (java.io.FileOutputStream stream = new java.io.FileOutputStream(output)) {
            bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, stream);
        }
        bitmap.recycle();
    }

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
