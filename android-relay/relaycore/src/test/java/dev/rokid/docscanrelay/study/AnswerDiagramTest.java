package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

@RunWith(RobolectricTestRunner.class)
public class AnswerDiagramTest {
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
