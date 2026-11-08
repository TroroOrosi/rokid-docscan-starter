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
    public void firstLayoutUsesRealFontAndKeepsTheRestoredPosition() {
        AnswerBundle bundle = new AnswerBundle("s", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g", "問題", "q", "問", "𝑥 = 2 を記入する。".repeat(400))));
        AnswerReader reader = new AnswerReader(bundle, true);
        reader.restore("q", 2000);
        AnswerView view = new AnswerView(RuntimeEnvironment.getApplication());
        view.bind(reader);
        assertFalse(reader.hasViewport());
        assertNull(view.getContentDescription());

        view.layout(0, 0, 480, 640);
        assertTrue(reader.hasViewport());
        assertEquals(2000, reader.offset());
        assertTrue(reader.pageCount() > 1);
        assertTrue(view.getContentDescription().length() > 0);
        assertEquals(32f, view.bodyTextSize(), .01f);

        view.layout(0, 0, 280, 640);
        assertEquals(2000, reader.offset());
        assertEquals(32f, view.bodyTextSize(), .01f);
    }

    @Test
    @org.robolectric.annotation.GraphicsMode(org.robolectric.annotation.GraphicsMode.Mode.NATIVE)
    public void quadraticGraphKeepsAxesScaleInterceptsAndItsShadedRegion() throws Exception {
        org.json.JSONArray curve = new org.json.JSONArray();
        org.json.JSONArray region = new org.json.JSONArray().put(new org.json.JSONArray(new double[]{.5, .75}));
        for (int n = 0; n <= 40; n++) {
            double x = -2 + n / 10.0;
            org.json.JSONArray point = new org.json.JSONArray(new double[]{.5 + .2*x, .75 - .15*(x*x - 1)});
            curve.put(point);
            if (n >= 20 && n <= 30) region.put(point);
        }
        org.json.JSONArray elements = new org.json.JSONArray()
                .put(new org.json.JSONObject().put("type", "polygon").put("points", region).put("hatched", true))
                .put(new org.json.JSONObject("{\"type\":\"line\",\"x1\":0.08,\"y1\":0.75,\"x2\":0.94,\"y2\":0.75}"))
                .put(new org.json.JSONObject("{\"type\":\"line\",\"x1\":0.5,\"y1\":0.96,\"x2\":0.5,\"y2\":0.1}"))
                .put(new org.json.JSONObject("{\"type\":\"polyline\",\"points\":[[0.92,0.73],[0.94,0.75],[0.92,0.77]]}"))
                .put(new org.json.JSONObject("{\"type\":\"polyline\",\"points\":[[0.48,0.12],[0.5,0.1],[0.52,0.12]]}"))
                .put(new org.json.JSONObject().put("type", "polyline").put("points", curve))
                .put(new org.json.JSONObject("{\"type\":\"circle\",\"cx\":0.1,\"cy\":0.3,\"r\":0.012,\"filled\":true}"))
                .put(new org.json.JSONObject("{\"type\":\"circle\",\"cx\":0.9,\"cy\":0.3,\"r\":0.012,\"filled\":true}"));
        String[] labels = {"y = x² − 1", "x", "y", "O", "−1", "1", "−1", "−2", "2"};
        double[][] anchors = {{.58,.16},{.94,.8},{.51,.08},{.43,.8},{.26,.81},{.69,.81},{.39,.95},{.08,.81},{.87,.81}};
        for (int n = 0; n < labels.length; n++) elements.put(new org.json.JSONObject().put("type", "text")
                .put("x", anchors[n][0]).put("y", anchors[n][1]).put("text", labels[n]));
        org.json.JSONObject figure = new org.json.JSONObject().put("alt", "y=x²−1, −2≤x≤2. The hatched region is 0≤x≤1, x²−1≤y≤0.")
                .put("aspect_ratio", 1).put("elements", elements);
        AnswerItem item = new AnswerItem("g1", "Paper", "q1", "Graph", "y = x² − 1 (−2 ≤ x ≤ 2)", AnswerItem.Status.READY, "",
                List.of(new dev.rokid.docscanrelay.study.AnswerDiagram(figure)));
        AnswerReader reader = new AnswerReader(new AnswerBundle("s", "a".repeat(64), 1, List.of(item)), 400, 2, String::length, true);
        AnswerView view = new AnswerView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.bind(reader);
        while (reader.diagram() == null) reader.forward();
        view.refresh();
        android.graphics.Bitmap bitmap = android.graphics.Bitmap.createBitmap(480, 640, android.graphics.Bitmap.Config.ARGB_8888);
        view.draw(new android.graphics.Canvas(bitmap));
        float top = org.robolectric.util.ReflectionHelpers.callInstanceMethod(view, "bodyTop");
        assertTrue(greenNear(bitmap, 14.4f + .3f * 451.2f, top + .75f * 451.2f) > 0);
        assertTrue(greenNear(bitmap, 14.4f + .7f * 451.2f, top + .75f * 451.2f) > 0);
        assertTrue(greenNear(bitmap, 240, top + .9f * 451.2f) > 0);
        java.io.File output = new java.io.File("build/outputs/quadratic-answer-review.png");
        output.getParentFile().mkdirs();
        try (java.io.FileOutputStream stream = new java.io.FileOutputStream(output)) {
            bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, stream);
        }
        bitmap.recycle();
    }

    @Test
    @org.robolectric.annotation.GraphicsMode(org.robolectric.annotation.GraphicsMode.Mode.NATIVE)
    public void graphAndConstructionMarksKeepTheirDistinctMathematicalMeaning() throws Exception {
        org.json.JSONObject figure = new org.json.JSONObject("{\"alt\":\"Graph: dashed boundary, open and closed endpoints, compass arc and hatched region\","
                + "\"aspect_ratio\":1,\"elements\":["
                + "{\"type\":\"line\",\"x1\":0.1,\"y1\":0.1,\"x2\":0.9,\"y2\":0.1,\"dashed\":true},"
                + "{\"type\":\"line\",\"x1\":0.1,\"y1\":0.3,\"x2\":0.75,\"y2\":0.3},"
                + "{\"type\":\"circle\",\"cx\":0.25,\"cy\":0.3,\"r\":0.05,\"filled\":false},"
                + "{\"type\":\"circle\",\"cx\":0.75,\"cy\":0.3,\"r\":0.05,\"filled\":true},"
                + "{\"type\":\"arc\",\"cx\":0.5,\"cy\":0.6,\"r\":0.15,\"start_degrees\":0,\"sweep_degrees\":90},"
                + "{\"type\":\"polyline\",\"points\":[[0.1,0.85],[0.2,0.7],[0.3,0.65],[0.4,0.7],[0.5,0.85]]},"
                + "{\"type\":\"polygon\",\"points\":[[0.7,0.6],[0.9,0.6],[0.8,0.85]],\"hatched\":true},"
                + "{\"type\":\"text\",\"x\":0.9,\"y\":0.95,\"text\":\"x\"}]}");
        AnswerItem item = new AnswerItem("g1", "Paper", "q1", "Graph", "y = x²", AnswerItem.Status.READY, "",
                List.of(new dev.rokid.docscanrelay.study.AnswerDiagram(figure)));
        AnswerReader reader = new AnswerReader(AnswerBundle.fromJson(
                new AnswerBundle("s", "a".repeat(64), 1, List.of(item)).toJson()), 400, 2, String::length, true);
        AnswerView view = new AnswerView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        view.bind(reader);
        while (reader.diagram() == null) reader.forward();
        view.refresh();
        android.graphics.Bitmap bitmap = android.graphics.Bitmap.createBitmap(480, 640, android.graphics.Bitmap.Config.ARGB_8888);
        view.draw(new android.graphics.Canvas(bitmap));
        float left = 480 * .03f, width = 480 * .94f;
        float top = org.robolectric.util.ReflectionHelpers.callInstanceMethod(view, "bodyTop");
        assertEquals("open endpoint stays open", 0, android.graphics.Color.green(bitmap.getPixel(
                Math.round(left + .25f * width), Math.round(top + .3f * width))));
        assertTrue("closed endpoint stays filled", android.graphics.Color.green(bitmap.getPixel(
                Math.round(left + .75f * width), Math.round(top + .3f * width))) > 100);
        int dashedOn = 0, dashedOff = 0;
        for (int x = Math.round(left + .12f * width); x < left + .88f * width; x++) {
            if (android.graphics.Color.green(bitmap.getPixel(x, Math.round(top + .1f * width))) > 100) dashedOn++;
            else dashedOff++;
        }
        assertTrue("boundary has visible strokes", dashedOn > 100);
        assertTrue("boundary has real gaps", dashedOff > 80);
        assertTrue("clockwise arc includes its bottom", greenNear(bitmap, left + .5f * width, top + .75f * width) > 0);
        assertEquals("arc must not become a full circle", 0, greenNear(bitmap, left + .35f * width, top + .6f * width));
        int hatchOn = 0, hatchOff = 0;
        for (int y = Math.round(top + .64f * width); y < top + .7f * width; y++)
            for (int x = Math.round(left + .77f * width); x < left + .83f * width; x++) {
                if (android.graphics.Color.green(bitmap.getPixel(x, y)) > 100) hatchOn++;
                else hatchOff++;
            }
        assertTrue("region is hatched rather than empty or solid", hatchOn > 50 && hatchOff > 100);
        assertEquals("hatching cannot escape the polygon", 0, greenNear(bitmap, left + .95f * width, top + .7f * width));
        assertTrue("curved polyline remains visible", greenNear(bitmap, left + .3f * width, top + .65f * width) > 0);
        java.io.File output = new java.io.File("build/outputs/extended-diagram-review.png");
        output.getParentFile().mkdirs();
        try (java.io.FileOutputStream stream = new java.io.FileOutputStream(output)) {
            bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, stream);
        }
        bitmap.recycle();
    }

    private int greenNear(android.graphics.Bitmap bitmap, float x, float y) {
        int count = 0;
        for (int dy = -2; dy <= 2; dy++) for (int dx = -2; dx <= 2; dx++)
            if (android.graphics.Color.green(bitmap.getPixel(Math.round(x) + dx, Math.round(y) + dy)) > 100) count++;
        return count;
    }

    @Test
    @org.robolectric.annotation.GraphicsMode(org.robolectric.annotation.GraphicsMode.Mode.NATIVE)
    public void fixedSlideFitsMoreWritingWithoutShrinkingAndNeverScrollsOnItsOwn() {
        AnswerView view = new AnswerView(RuntimeEnvironment.getApplication());
        view.layout(0, 0, 480, 640);
        String text = java.util.stream.IntStream.rangeClosed(1, 14)
                .mapToObj(number -> "導出 " + number).collect(java.util.stream.Collectors.joining("\n"));
        AnswerReader reader = reader(text);
        view.bind(reader);
        assertEquals("the complete writing fits on one static slide", 1, reader.pageCount());
        assertEquals(32f, view.bodyTextSize(), .01f);
        assertEquals(text, view.getContentDescription().toString());
        android.graphics.Bitmap first = android.graphics.Bitmap.createBitmap(480, 640, android.graphics.Bitmap.Config.ARGB_8888);
        view.draw(new android.graphics.Canvas(first));
        org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(java.time.Duration.ofMinutes(5));
        android.graphics.Bitmap later = android.graphics.Bitmap.createBitmap(480, 640, android.graphics.Bitmap.Config.ARGB_8888);
        view.draw(new android.graphics.Canvas(later));
        assertTrue("time alone must not move a slide", first.sameAs(later));
        for (int x = 0; x < 480; x++) {
            assertEquals("top safe margin", android.graphics.Color.BLACK, first.getPixel(x, 5));
            assertEquals("bottom safe margin", android.graphics.Color.BLACK, first.getPixel(x, 635));
        }
        first.recycle();
        later.recycle();
    }

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

    @Test public void longAnswerUsesTheAvailableScreenAndKeepsItsReadableFontSize() {
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
            int rows = view.getContentDescription().toString().split("\n", -1).length + 1;
            assertTrue("every line stays within the display", rows * fontSize * 1.25f <= view.getHeight());
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
