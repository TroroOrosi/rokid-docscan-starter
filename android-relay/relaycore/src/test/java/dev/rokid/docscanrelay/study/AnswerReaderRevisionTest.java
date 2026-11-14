package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;

import java.util.ArrayList;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class AnswerReaderRevisionTest {
    private static final class CountingMeasurer implements AnswerLayout.Measurer {
        int calls;
        @Override public float width(String text) {
            calls++;
            return text.length();
        }
    }

    private static AnswerItem target(String answer, AnswerItem.Status status, String issue,
                                     List<AnswerDiagram> diagrams) {
        return new AnswerItem("g", "Group", "target", "Target", answer, status, issue, diagrams);
    }

    private static AnswerDiagram line(double end, boolean dashed) throws Exception {
        return new AnswerDiagram(new JSONObject("{\"alt\":\"line\",\"aspect_ratio\":1,\"elements\":["
                + "{\"type\":\"line\",\"x1\":0.1,\"y1\":0.1,\"x2\":" + end
                + ",\"y2\":0.9,\"dashed\":" + dashed + "}]}"));
    }

    @Test public void equalReparsedContinuousRevisionKeepsLayoutAndRefreshesMetadata() throws Exception {
        AnswerBundle initial = new AnswerBundle("session", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g", "Group", "first", "First", "abcdefghijklmnopqrstuv\nsecond line"),
                target("written answer", AnswerItem.Status.NEEDS_REVIEW, "check", List.of(line(.8, false)))),
                "awaiting_audio", "reading");
        CountingMeasurer measurer = new CountingMeasurer();
        AnswerReader reader = new AnswerReader(initial, 12, 2, measurer, true);
        reader.forward();
        AnswerLayout.Page page = reader.page();
        int offset = reader.offset();
        int pageNumber = reader.pageNumber();
        int pageCount = reader.pageCount();
        String question = reader.current().questionId;
        int measurements = measurer.calls;

        AnswerBundle parsed = AnswerBundle.fromJson(initial.toJson());
        assertNotSame(initial.items.get(0), parsed.items.get(0));
        assertNotSame(initial.items.get(0).answer, parsed.items.get(0).answer);
        assertNotSame(initial.items.get(1).diagrams.get(0), parsed.items.get(1).diagrams.get(0));
        AnswerBundle next = new AnswerBundle("session", "a".repeat(64), 2, parsed.items,
                "listening", "reading");
        assertTrue(reader.accept(next));
        assertSame(next, reader.bundle());
        assertEquals("listening", reader.bundle().analysisStage);
        assertEquals("reading", reader.bundle().availableStage);
        assertEquals(2, reader.bundle().revision);
        assertTrue(reader.bundle().intermediate());
        assertEquals(measurements, measurer.calls);
        assertSame(page, reader.page());
        assertEquals(offset, reader.offset());
        assertEquals(question, reader.current().questionId);
        assertEquals(pageNumber, reader.pageNumber());
        assertEquals(pageCount, reader.pageCount());

        AnswerBundle complete = new AnswerBundle("session", "a".repeat(64), 3, parsed.items,
                "complete", "complete");
        assertTrue(reader.accept(complete));
        assertSame(complete, reader.bundle());
        assertFalse(reader.bundle().intermediate());
        assertEquals(measurements, measurer.calls);
        assertSame(page, reader.page());
        reader.viewport(9, 2, measurer);
        assertTrue(measurer.calls > measurements);
        assertEquals(offset, reader.offset());
    }

    @Test public void equalDiagramRevisionRetainsItsSectionAndDiagramCursor() throws Exception {
        AnswerDiagram diagram = line(.8, false);
        AnswerBundle initial = new AnswerBundle("session", "a".repeat(64), 1,
                List.of(target("answer", AnswerItem.Status.READY, "", List.of(diagram))));
        CountingMeasurer measurer = new CountingMeasurer();
        AnswerReader reader = new AnswerReader(initial, 20, 2, measurer, true);
        while (reader.pageNumber() < reader.pageCount()) reader.forward();
        assertSame(diagram, reader.diagram());
        int offset = reader.offset();
        int number = reader.pageNumber();
        int measurements = measurer.calls;
        AnswerBundle parsed = AnswerBundle.fromJson(initial.toJson());
        AnswerBundle next = new AnswerBundle("session", "a".repeat(64), 2, parsed.items);
        assertTrue(reader.accept(next));
        assertEquals(measurements, measurer.calls);
        assertSame(diagram, reader.diagram());
        assertEquals(offset, reader.offset());
        assertEquals(number, reader.pageNumber());
        // The retained section's old objects cannot be changed through public views.
        diagram.toJson().getJSONArray("elements").getJSONObject(0).put("x2", .4);
        assertEquals(.8, reader.diagram().toJson().getJSONArray("elements").getJSONObject(0).getDouble("x2"), 0);
        assertThrows(UnsupportedOperationException.class, () -> initial.items.clear());
        assertThrows(UnsupportedOperationException.class, () -> initial.items.get(0).diagrams.clear());
    }

    private static void assertChangedItemReflowsAtEveryPosition(AnswerItem before, AnswerItem after,
                                                               String expectedText) {
        for (int position = 0; position < 3; position++) {
            List<AnswerItem> items = new ArrayList<>(List.of(
                    AnswerItem.ready("g", "Group", "left", "Left", "left answer\ncontinued"),
                    AnswerItem.ready("g", "Group", "right", "Right", "right answer\ncontinued")));
            items.add(position, before);
            AnswerBundle initial = new AnswerBundle("session", "a".repeat(64), 1, items);
            CountingMeasurer measurer = new CountingMeasurer();
            AnswerReader reader = new AnswerReader(initial, 16, 2, measurer, true);
            reader.restore(position == 1 ? "target" : "left", 2);
            String question = reader.current().questionId;
            int offset = reader.offset();
            int measurements = measurer.calls;
            items.set(position, after);
            AnswerBundle next = new AnswerBundle("session", "a".repeat(64), 2, items);
            assertTrue(reader.accept(next));
            assertSame(next, reader.bundle());
            assertTrue("changed item position " + position, measurer.calls > measurements);
            assertEquals(question, reader.current().questionId);
            assertEquals(offset, reader.offset());

            while (reader.pageNumber() > 1) reader.backward();
            StringBuilder shownText = new StringBuilder();
            List<AnswerDiagram> shownDiagrams = new ArrayList<>();
            for (int page = 0; page < reader.pageCount(); page++) {
                if (reader.diagram() == null) shownText.append(reader.page().sourceText);
                else shownDiagrams.add(reader.diagram());
                if (page + 1 < reader.pageCount()) reader.forward();
            }
            assertTrue(shownText.toString().contains(expectedText));
            assertEquals(after.diagrams, shownDiagrams);
        }
    }

    @Test public void answerChangeInAnyContinuousItemReflows() {
        assertChangedItemReflowsAtEveryPosition(
                target("original\nanswer", AnswerItem.Status.READY, "", List.of()),
                target("updated\nanswer", AnswerItem.Status.READY, "", List.of()), "updated\nanswer");
    }

    @Test public void statusOnlyChangeInAnyContinuousItemReflows() {
        assertChangedItemReflowsAtEveryPosition(
                target("", AnswerItem.Status.PENDING, "", List.of()),
                target("", AnswerItem.Status.FAILED, "", List.of()), "解析できません\n");
    }

    @Test public void issueOnlyChangeInAnyContinuousItemReflows() {
        assertChangedItemReflowsAtEveryPosition(
                target("same answer", AnswerItem.Status.NEEDS_REVIEW, "old issue", List.of()),
                target("same answer", AnswerItem.Status.NEEDS_REVIEW, "new issue", List.of()),
                "【要確認】new issue\nsame answer");
    }

    @Test public void diagramGeometryStyleAndOrderChangesInAnyContinuousItemReflow() throws Exception {
        AnswerDiagram first = line(.4, false);
        AnswerDiagram second = line(.8, false);
        for (List<AnswerDiagram> diagrams : List.of(List.of(second), List.of(line(.4, true)),
                List.of(first, second), List.<AnswerDiagram>of())) {
            assertChangedItemReflowsAtEveryPosition(
                    target("same answer", AnswerItem.Status.READY, "", List.of(first)),
                    target("same answer", AnswerItem.Status.READY, "", diagrams), "same answer");
        }
        assertChangedItemReflowsAtEveryPosition(
                target("same answer", AnswerItem.Status.READY, "", List.of(first, second)),
                target("same answer", AnswerItem.Status.READY, "", List.of(second, first)), "same answer");
    }

    @Test public void ordinaryReaderKeepsMenuAndCurrentPageWhenAnotherItemChanges() {
        AnswerBundle initial = new AnswerBundle("session", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "First group", "first", "First", "abcdefghijklmnopqrstuv"),
                AnswerItem.ready("g2", "Second group", "second", "Second", "original")));
        CountingMeasurer measurer = new CountingMeasurer();
        AnswerReader reader = new AnswerReader(initial, 4, 2, measurer);
        reader.forward();
        AnswerLayout.Page page = reader.page();
        int offset = reader.offset();
        reader.tap();
        reader.forward();
        reader.tap();
        assertEquals(AnswerReader.Screen.QUESTIONS, reader.screen());
        assertEquals("Second", reader.selectionLabel());
        int measurements = measurer.calls;
        AnswerBundle next = initial.withAnswer(
                AnswerItem.ready("g2", "Second group", "second", "Second", "updated"));
        assertTrue(reader.accept(next));
        assertSame(next, reader.bundle());
        assertEquals(measurements, measurer.calls);
        assertSame(page, reader.page());
        assertEquals(offset, reader.offset());
        assertEquals(AnswerReader.Screen.QUESTIONS, reader.screen());
        assertEquals("Second", reader.selectionLabel());
        assertEquals(1, reader.selectionNumber());
        reader.tap();
        assertEquals("updated", reader.current().answer);
        assertEquals("upda", reader.page().lines.get(0));
    }

    @Test public void ordinaryReaderReflowsCurrentAnswerWithoutMovingItsPosition() {
        AnswerBundle initial = new AnswerBundle("session", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "First group", "first", "First", "first answer"),
                AnswerItem.ready("g2", "Second group", "second", "Second", "abcdefghijklmnopqrstuv")));
        CountingMeasurer measurer = new CountingMeasurer();
        AnswerReader reader = new AnswerReader(initial, 4, 2, measurer);
        reader.restore("second", 8);
        AnswerLayout.Page oldPage = reader.page();
        assertEquals(List.of("ijkl", "mnop"), oldPage.lines);
        int measurements = measurer.calls;

        AnswerBundle next = initial.withAnswer(
                AnswerItem.ready("g2", "Second group", "second", "Second", "ABCDEFGHIJKLMNOPQRSTUV"));
        assertTrue(reader.accept(next));
        assertSame(next, reader.bundle());
        assertEquals("second", reader.current().questionId);
        assertEquals(8, reader.offset());
        assertEquals(2, reader.pageNumber());
        assertEquals(3, reader.pageCount());
        assertEquals(AnswerReader.Screen.ANSWER, reader.screen());
        assertEquals(List.of("IJKL", "MNOP"), reader.page().lines);
        assertEquals("IJKLMNOP", reader.page().sourceText);
        assertNotSame(oldPage, reader.page());
        assertTrue(measurer.calls > measurements);
    }

    @Test public void legacySnapshotCanAcceptSameTextBeforeItsFirstViewport() throws Exception {
        AnswerBundle old = AnswerBundle.fromJson("{\"schema_version\":1,\"session_id\":\"session\","
                + "\"input_digest\":\"" + "a".repeat(64) + "\",\"revision\":1,\"items\":[{"
                + "\"group_id\":\"g\",\"group_label\":\"Group\",\"question_id\":\"q\",\"question_label\":\"Q\","
                + "\"answer\":\"abcdefghijklmnop\",\"status\":\"ready\",\"issue\":\"\"}]}");
        AnswerReader reader = new AnswerReader(old, true);
        reader.restore("q", 8);
        assertFalse(reader.hasViewport());
        assertTrue(old.items.get(0).diagrams.isEmpty());
        assertTrue(old.items.get(0).answerNumbers.isEmpty());
        AnswerBundle next = new AnswerBundle("session", "a".repeat(64), 2, old.items,
                "awaiting_audio", "reading");
        assertTrue(reader.accept(next));
        assertSame(next, reader.bundle());
        assertFalse(reader.hasViewport());
        assertEquals(8, reader.offset());
        CountingMeasurer measurer = new CountingMeasurer();
        reader.viewport(6, 2, measurer);
        assertTrue(measurer.calls > 0);
        assertEquals(8, reader.offset());
        assertEquals("q", reader.current().questionId);
    }
}
