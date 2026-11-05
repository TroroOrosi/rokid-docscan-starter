package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

@RunWith(RobolectricTestRunner.class)
public class AnswerDiagramTest {
    @Test public void extendedGeometryAndUnicodeSurviveOfflineRoundTrip() throws Exception {
        JSONObject value = new JSONObject("{\"alt\":\"graph\",\"aspect_ratio\":1.3,\"elements\":["
                + "{\"type\":\"circle\",\"cx\":0.2,\"cy\":0.5,\"r\":0.26},"
                + "{\"type\":\"arc\",\"cx\":0.5,\"cy\":0.5,\"r\":0.3,\"start_degrees\":30,\"sweep_degrees\":-120,\"dashed\":true},"
                + "{\"type\":\"polygon\",\"points\":[[0.1,0.8],[0.5,0.2],[0.9,0.8]],\"hatched\":true},"
                + "{\"type\":\"circle\",\"cx\":0.8,\"cy\":0.5,\"r\":0.02,\"filled\":true}]}");
        value.getJSONArray("elements").put(new JSONObject().put("type", "text").put("x", .5).put("y", .1)
                .put("text", "𝑥".repeat(80)));
        AnswerDiagram diagram = new AnswerDiagram(value);
        assertEquals(3, diagram.schemaVersion);
        AnswerItem item = new AnswerItem("g1", "用紙", "q1", "項目1", "x²", AnswerItem.Status.READY, "", List.of(diagram));
        String saved = new AnswerBundle("1", "a".repeat(64), 1, List.of(item)).toJson();
        assertEquals(3, new JSONObject(saved).getInt("schema_version"));
        AnswerBundle restored = AnswerBundle.fromJson(saved);
        assertEquals(value.toString(), restored.items.get(0).diagrams.get(0).toJson().toString());
        AnswerReader reader = new AnswerReader(restored, 20, 2, String::length, true);
        while (reader.diagram() == null) reader.forward();
        AnswerReader resumed = new AnswerReader(restored, 20, 2, String::length, true);
        resumed.restore("q1", reader.offset());
        assertEquals(diagram, resumed.diagram());
        assertThrows(Exception.class, () -> new AnswerDiagram(new JSONObject(value.toString())
                .put("elements", new org.json.JSONArray("[{\"type\":\"arc\",\"cx\":0.5,\"cy\":0.5,\"r\":0.2,\"start_degrees\":0,\"sweep_degrees\":0}]"))));
        assertThrows(Exception.class, () -> new AnswerDiagram(new JSONObject(value.toString())
                .put("elements", new org.json.JSONArray("[{\"type\":\"circle\",\"cx\":0.5,\"cy\":0.5,\"r\":0.2,\"filled\":1}]"))));
    }

    @Test public void diagramSurvivesOfflineBundlePagingAndResume() throws Exception {
        AnswerDiagram diagram = new AnswerDiagram(new JSONObject("{\"alt\":\"circle\",\"aspect_ratio\":1,"
                + "\"elements\":[{\"type\":\"circle\",\"cx\":0.5,\"cy\":0.5,\"r\":0.3}]}"));
        AnswerItem item = new AnswerItem("g1", "第1問", "q1", "問1", "x=2", AnswerItem.Status.READY, "", List.of(diagram));
        AnswerBundle bundle = AnswerBundle.fromJson(new AnswerBundle("1", "a".repeat(64), 1, List.of(item)).toJson());
        AnswerReader reader = new AnswerReader(bundle, 100, 2, String::length);
        assertTrue(reader.pageCount() >= 2);
        assertNull(reader.diagram());
        while (reader.diagram() == null) reader.forward();
        assertEquals("circle", reader.diagram().alt);
        AnswerReader restored = new AnswerReader(bundle, 50, 2, String::length);
        restored.restore("q1", reader.offset());
        assertNotNull(restored.diagram());
        restored.backward();
        assertNull(restored.diagram());
        AnswerItem drawingOnly = new AnswerItem("g1", "第1問", "q1", "問1", "", AnswerItem.Status.READY, "", List.of(diagram));
        AnswerReader only = new AnswerReader(new AnswerBundle("1", "a".repeat(64), 1, List.of(drawingOnly)),
                100, 2, String::length);
        assertTrue(String.join("", only.page().lines).contains("circle"));
        while (only.diagram() == null) only.forward();
        assertNotNull(only.diagram());
        AnswerItem review = new AnswerItem("g1", "第1問", "q1", "問1", "x", AnswerItem.Status.NEEDS_REVIEW,
                "表示を確認してください", List.of(diagram));
        AnswerBundle reviewBundle = new AnswerBundle("1", "b".repeat(64), 1, List.of(review));
        AnswerReader flagged = new AnswerReader(reviewBundle, 10, 2, String::length);
        while (flagged.diagram() == null) flagged.forward();
        AnswerReader resumed = new AnswerReader(reviewBundle, 10, 2, String::length);
        resumed.restore("q1", flagged.offset());
        assertNotNull(resumed.diagram());
        assertThrows(Exception.class, () -> new AnswerDiagram(new JSONObject(
                "{\"alt\":\"bad\",\"aspect_ratio\":1,\"elements\":[{\"type\":\"image\"}]}")));
    }
}
