package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;

import java.util.List;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.SequenceInputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(manifest = Config.NONE, sdk = 28)
public class AnswerBundleTest {
    private final String digest = "a".repeat(64);

    @Test public void streamBoundsApplyBeforeAnOversizedTokenOrBodyIsAllocated() throws Exception {
        InputStream hugeString = new SequenceInputStream(new ByteArrayInputStream(
                "{\"unknown\":\"".getBytes(StandardCharsets.UTF_8)),
                repeated('x', AnswerBundle.MAX_TEXT_CHARS + 1));
        assertThrows(IOException.class, () -> AnswerBundle.fromStream(hugeString));
        assertThrows(IOException.class, () -> AnswerBundle.fromStream(
                repeated(' ', AnswerBundle.MAX_JSON_BYTES + 1)));
        InputStream malformedScalar = new ByteArrayInputStream(
                ("{\"unknown\":" + ("x".repeat(100) + "\u2003").repeat(10)).getBytes(StandardCharsets.UTF_8));
        IOException invalid = assertThrows(IOException.class, () -> AnswerBundle.fromStream(malformedScalar));
        assertTrue(invalid.getMessage().contains("scalar too large"));
    }

    @Test public void strictStreamingParserRejectsCoercionDuplicatesAndTrailingValues() throws Exception {
        String valid = new AnswerBundle("s", digest, 1,
                List.of(AnswerItem.ready("g", "全問", "q", "1", "A"))).toJson();
        for (String invalid : List.of(valid + " {}", valid.replace("\"revision\":1", "\"revision\":1.0"),
                valid.replace("\"revision\":1", "\"revision\":1,\"revision\":2"),
                "{\"unknown\":" + "[".repeat(32) + "0" + "]".repeat(32) + "," + valid.substring(1))) {
            assertThrows(Exception.class, () -> AnswerBundle.fromJson(invalid));
        }
    }

    private static InputStream repeated(int value, int length) {
        return new InputStream() {
            private int remaining = length;
            @Override public int read() { return remaining-- > 0 ? value : -1; }
            @Override public int read(byte[] buffer, int offset, int count) {
                if (remaining <= 0) return -1;
                int actual = Math.min(remaining, count);
                java.util.Arrays.fill(buffer, offset, offset + actual, (byte) value);
                remaining -= actual;
                return actual;
            }
        };
    }

    @Test public void acceptedLongWorkAnswersRetainAllTextAcrossBundleRoundTrip() throws Exception {
        for (String unit : List.of("x", "式")) {
            String answer = unit.repeat(180_000);
            AnswerBundle bundle = new AnswerBundle("s", digest, 1, List.of(
                    AnswerItem.ready("g", "全問", "q1", "1", answer),
                    AnswerItem.ready("g", "全問", "q2", "2", answer),
                    AnswerItem.ready("g", "全問", "q3", "3", answer),
                    AnswerItem.ready("g", "全問", "q4", "4", answer)));
            AnswerBundle restored = AnswerBundle.fromJson(bundle.toJson());
            for (AnswerItem item : restored.items) assertEquals(answer, item.answer);
        }
        String single = "x".repeat(300_001);
        AnswerBundle bundle = new AnswerBundle("s", digest, 1,
                List.of(AnswerItem.ready("g", "全問", "q", "1", single)));
        assertEquals(single, AnswerBundle.fromJson(bundle.toJson()).items.get(0).answer);
    }

    @Test public void mixedReadingStageSurvivesOfflinePersistenceUntilAudioAnswersArrive() throws Exception {
        JSONObject json = new JSONObject(new AnswerBundle("7", digest, 1, List.of(
                AnswerItem.ready("g1", "読解", "q1", "問1", "A"),
                new AnswerItem("g2", "音声", "q2", "問2", "", AnswerItem.Status.PENDING, "原音待ち"))).toJson())
                .put("analysis_stage", "awaiting_audio").put("available_stage", "reading");
        AnswerBundle restored = AnswerBundle.fromJson(json.toString());
        JSONObject saved = new JSONObject(restored.toJson());
        assertEquals("awaiting_audio", saved.getString("analysis_stage"));
        assertEquals("reading", saved.getString("available_stage"));
        assertFalse(restored.finished());
        assertEquals("q2", restored.items.get(1).questionId);
    }

    @Test public void completeWrittenAnswersRoundTripWithRepeatedSmallQuestionLabels() throws Exception {
        String proof = "対応する角は等しい。\n".repeat(100);
        AnswerBundle bundle = new AnswerBundle("session-1", digest, 1, List.of(
                AnswerItem.ready("g1", "大問1", "g1-q1", "問1", "イ"),
                AnswerItem.ready("g2", "大問2", "g2-q1", "問1", proof)));
        AnswerBundle restored = AnswerBundle.fromJson(bundle.toJson());
        assertEquals(proof, restored.items.get(1).answer);
        assertEquals("g2-q1", restored.items.get(1).questionId);
        assertTrue(restored.fullyAnswered());
        assertTrue(restored.finished());
    }

    @Test public void missingInputAndPendingAreNeverRenderedAsAnswers() {
        AnswerItem missing = new AnswerItem("g1", "大問1", "q1", "(1)", "",
                AnswerItem.Status.NEEDS_INPUT, "図2の下端");
        AnswerItem pending = new AnswerItem("g1", "大問1", "q2", "(2)", "",
                AnswerItem.Status.PENDING, "");
        AnswerBundle bundle = new AnswerBundle("session-1", digest, 1, List.of(missing, pending));
        assertFalse(bundle.fullyAnswered());
        assertFalse(bundle.finished());
        assertEquals("", missing.answer);
    }

    @Test public void duplicateIdentityIsRejectedEvenAcrossGroups() {
        assertThrows(IllegalArgumentException.class, () -> new AnswerBundle("s", digest, 1, List.of(
                AnswerItem.ready("g1", "大問1", "q1", "問1", "A"),
                AnswerItem.ready("g2", "大問2", "q1", "問1", "B"))));
    }

    @Test public void malformedAnswerDoesNotCoerceJsonObjectsIntoWrittenText() throws Exception {
        JSONObject json = new JSONObject(new AnswerBundle("s", digest, 1, List.of(
                AnswerItem.ready("g1", "大問1", "q1", "問1", "A"))).toJson());
        json.getJSONArray("items").getJSONObject(0).put("answer", new JSONObject().put("text", "A"));
        assertThrows(Exception.class, () -> AnswerBundle.fromJson(json.toString()));
    }

    @Test public void updatingOneQuestionPreservesOrderAndOtherAnswers() {
        AnswerBundle bundle = new AnswerBundle("s", digest, 1, List.of(
                AnswerItem.ready("g1", "大問1", "q1", "(1)", "A"),
                new AnswerItem("g1", "大問1", "q2", "(2)", "", AnswerItem.Status.PENDING, "")));
        AnswerBundle next = bundle.withAnswer(AnswerItem.ready("g1", "大問1", "q2", "(2)", "B"));
        assertEquals(2, next.revision);
        assertEquals("A", next.items.get(0).answer);
        assertEquals("B", next.items.get(1).answer);
        assertFalse(bundle.fullyAnswered());
        assertTrue(next.fullyAnswered());
        assertThrows(IllegalArgumentException.class, () -> bundle.withAnswer(
                AnswerItem.ready("other", "別資料", "q2", "(2)", "C")));
    }

    @Test public void anAnswerNeedingReviewKeepsItsTextButIsNotFullyAnswered() throws Exception {
        AnswerBundle bundle = new AnswerBundle("s", digest, 1, List.of(
                new AnswerItem("g1", "大問1", "q1", "問1", "12",
                        AnswerItem.Status.NEEDS_REVIEW, "表示できない要素: 表")));
        assertEquals("12", bundle.items.get(0).answer);
        assertEquals("表示できない要素: 表", bundle.items.get(0).issue);
        assertFalse(bundle.fullyAnswered());
        assertTrue(bundle.finished());
        assertEquals(bundle.toJson(), AnswerBundle.fromJson(bundle.toJson()).toJson());
    }

    private static AnswerItem item(String id, String answer, AnswerItem.Status status, String issue,
                                   String other, boolean seen) {
        return new AnswerItem("g1", "大問1", id, id, answer, status, issue, List.of(), List.of(), other, seen);
    }

    @Test public void retakePagesComparingTheOtherReadAndSeenSurviveTheOfflineRoundTripAndAnUpdate() throws Exception {
        AnswerBundle bundle = new AnswerBundle("s", digest, 1, List.of(
                item("q1", "ア", AnswerItem.Status.READY, "", "", true),
                item("q2", "イ", AnswerItem.Status.NEEDS_REVIEW, "2回の読みで不一致", "ウ", false)),
                "single", "complete", List.of(3, 8, 9), true);
        AnswerBundle restored = AnswerBundle.fromJson(bundle.toJson());
        assertEquals(List.of(3, 8, 9), restored.retake);
        assertTrue(restored.comparing);
        assertTrue(restored.items.get(0).seen);
        assertEquals("", restored.items.get(0).other);
        assertFalse(restored.items.get(1).seen);
        assertEquals("ウ", restored.items.get(1).other);
        assertTrue("what the two reads do not settle, by the server's mark or by its note from an older server",
                restored.items.get(1).uncertain);
        assertFalse(restored.items.get(0).uncertain);
        assertFalse("an answer to check for its form is not that", new AnswerItem("g1", "大問1", "q3", "q3", "カ",
                AnswerItem.Status.NEEDS_REVIEW, "表示できない要素: 表").uncertain);
        assertTrue(new AnswerItem("g1", "大問1", "q4", "q4", "カ", AnswerItem.Status.NEEDS_REVIEW, "確認", List.of(),
                List.of(), "", false, true).uncertain);
        assertEquals(bundle.toJson(), restored.toJson());
        assertThrows(UnsupportedOperationException.class, () -> restored.retake.add(1));

        AnswerBundle next = restored.withAnswer(item("q1", "エ", AnswerItem.Status.READY, "", "", false));
        assertEquals(List.of(3, 8, 9), next.retake);
        assertTrue(next.comparing);
        assertEquals("ウ", next.items.get(1).other);
    }

    @Test public void aBundleWithoutTheNewFieldsLoadsWithNothingToRetakeAndNothingCompared() throws Exception {
        AnswerBundle old = AnswerBundle.fromJson("{\"schema_version\":1,\"session_id\":\"s\",\"input_digest\":\""
                + digest + "\",\"revision\":1,\"items\":[{\"group_id\":\"g\",\"group_label\":\"全問\","
                + "\"question_id\":\"q\",\"question_label\":\"1\",\"answer\":\"A\",\"status\":\"ready\",\"issue\":\"\"}]}");
        assertTrue(old.retake.isEmpty());
        assertFalse(old.comparing);
        assertEquals("", old.items.get(0).other);
        assertFalse(old.items.get(0).seen);
        assertFalse(old.items.get(0).notice());
    }

    @Test public void anOlderServersComparingNoticeMeansTheReadsAreStillCompared() throws Exception {
        AnswerItem notice = new AnswerItem("pages", "撮影の確認", "read-comparing", "照合中", "（待ち）",
                AnswerItem.Status.NEEDS_REVIEW, "1回目の読み");
        assertTrue(notice.notice());
        AnswerBundle bundle = new AnswerBundle("s", digest, 1,
                List.of(AnswerItem.ready("g", "全問", "q", "1", "A"), notice));
        assertTrue(bundle.comparing);
        assertTrue(AnswerBundle.fromJson(bundle.toJson()).comparing);
    }

    @Test public void theOtherReadBelongsOnlyToAnAnswerInDoubt() {
        assertEquals("", item("q1", "ア", AnswerItem.Status.READY, "", "ウ", false).other);
        assertEquals("x".repeat(200),
                item("q1", "ア", AnswerItem.Status.NEEDS_REVIEW, "確認", "x".repeat(200), false).other);
    }

    @Test public void outOfRangeRetakePagesOtherReadsAndFlagsAreRefused() throws Exception {
        List<AnswerItem> items = List.of(AnswerItem.ready("g", "全問", "q", "1", "A"));
        for (List<Integer> pages : List.of(List.of(0), List.of(1001), java.util.Collections.nCopies(101, 1))) {
            assertThrows(IllegalArgumentException.class,
                    () -> new AnswerBundle("s", digest, 1, items, "single", "complete", pages, false));
        }
        assertEquals(100, new AnswerBundle("s", digest, 1, items, "single", "complete",
                java.util.Collections.nCopies(100, 1000), false).retake.size());
        assertThrows(IllegalArgumentException.class,
                () -> item("q1", "ア", AnswerItem.Status.NEEDS_REVIEW, "確認", "x".repeat(201), false));
        assertThrows(IllegalArgumentException.class,
                () -> item("q1", "ア", AnswerItem.Status.NEEDS_REVIEW, "確認", null, false));

        String valid = new AnswerBundle("s", digest, 1, items).toJson();
        for (String pages : List.of("[0]", "[1001]", "[\"3\"]", "[1.5]", "[null]",
                new org.json.JSONArray(java.util.Collections.nCopies(101, 1)).toString())) {
            String json = new JSONObject(valid).put("retake", new org.json.JSONArray(pages)).toString();
            assertThrows(pages, Exception.class, () -> AnswerBundle.fromJson(json));
        }
        for (Object flag : new Object[]{"true", 1, JSONObject.NULL}) {
            String json = new JSONObject(valid).put("comparing", flag).toString();
            assertThrows("comparing " + flag, Exception.class, () -> AnswerBundle.fromJson(json));
            JSONObject seen = new JSONObject(valid);
            seen.getJSONArray("items").getJSONObject(0).put("seen", flag);
            assertThrows("seen " + flag, Exception.class, () -> AnswerBundle.fromJson(seen.toString()));
        }
        for (Object other : new Object[]{5, JSONObject.NULL, "x".repeat(201)}) {
            JSONObject json = new JSONObject(valid);
            json.getJSONArray("items").getJSONObject(0).put("other", other);
            assertThrows("other " + other, Exception.class, () -> AnswerBundle.fromJson(json.toString()));
        }
    }

    @Test public void reviewWithoutAReasonOrWithoutAnAnswerIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> new AnswerItem(
                "g1", "大問1", "q1", "問1", "12", AnswerItem.Status.NEEDS_REVIEW, "  "));
        assertThrows(IllegalArgumentException.class, () -> new AnswerItem(
                "g1", "大問1", "q1", "問1", "", AnswerItem.Status.NEEDS_REVIEW, "表"));
    }
}
