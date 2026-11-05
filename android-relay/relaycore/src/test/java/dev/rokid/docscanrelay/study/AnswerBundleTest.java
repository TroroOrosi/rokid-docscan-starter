package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;

import java.util.List;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(manifest = Config.NONE, sdk = 28)
public class AnswerBundleTest {
    private final String digest = "a".repeat(64);

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

    @Test public void reviewWithoutAReasonOrWithoutAnAnswerIsRejected() {
        assertThrows(IllegalArgumentException.class, () -> new AnswerItem(
                "g1", "大問1", "q1", "問1", "12", AnswerItem.Status.NEEDS_REVIEW, "  "));
        assertThrows(IllegalArgumentException.class, () -> new AnswerItem(
                "g1", "大問1", "q1", "問1", "", AnswerItem.Status.NEEDS_REVIEW, "表"));
    }
}
