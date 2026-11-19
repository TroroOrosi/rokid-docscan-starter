package dev.rokid.docscanrelay.study;

import static dev.rokid.docscanrelay.study.AnswerItem.Status.*;
import static org.junit.Assert.*;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28, manifest = Config.NONE)
public class ContinuousAnswerReaderTest {
    @Test public void shortAnswersShareOneScreenAndLongDerivationsRemainReachable() {
        String derivation = "x=1\n" + "abcdefghijklmnopqrstuvwxyz".repeat(4);
        AnswerBundle bundle = new AnswerBundle("session", "a".repeat(64), 1, List.of(
                new AnswerItem("g1", "第1問", "q101", "問1", "4", AnswerItem.Status.READY, "", List.of(), List.of(101)),
                new AnswerItem("g1", "第1問", "q102", "問2", "2", AnswerItem.Status.READY, "", List.of(), List.of(102)),
                new AnswerItem("g1", "第1問", "q103", "問3", derivation, AnswerItem.Status.READY, "", List.of(), List.of(103))));
        AnswerReader reader = new AnswerReader(bundle, 24, 2, String::length, true);
        assertEquals(List.of("101 4　102 2", "103 x=1"), reader.page().lines);
        StringBuilder all = new StringBuilder();
        for (int page = 0; page < reader.pageCount(); page++) {
            all.append(String.join("", reader.page().lines));
            reader.forward();
        }
        assertTrue(all.toString().contains(derivation.replace("\n", "")));
        reader.restore("q103", 40);
        String question = reader.current().questionId;
        int offset = reader.offset();
        reader.viewport(12, 2, String::length);
        assertEquals(question, reader.current().questionId);
        assertEquals(offset, reader.offset());
        reader.backward();
        reader.forward();
        assertEquals(question, reader.current().questionId);
    }

    @Test public void aSlideStaysStillOnTapAndSwipesReplaceOnlyTheWholePage() {
        AnswerBundle bundle = new AnswerBundle("session", "a".repeat(64), 1, List.of(
                new AnswerItem("g1", "第1問", "q101", "問1", "4", AnswerItem.Status.READY, "", List.of(), List.of(101)),
                new AnswerItem("g1", "第1問", "q102", "問2", "2", AnswerItem.Status.READY, "", List.of(), List.of(102))));
        AnswerReader reader = new AnswerReader(bundle, 8, 1, String::length, true);
        List<String> first = reader.page().lines;
        reader.tap();
        assertEquals(AnswerReader.Screen.ANSWER, reader.screen());
        assertEquals(first, reader.page().lines);
        reader.forward();
        assertEquals(List.of("102 2"), reader.page().lines);
        reader.tap();
        reader.backward();
        assertEquals(first, reader.page().lines);
    }

    private static AnswerItem item(String id, int number, String answer, AnswerItem.Status status, String issue,
                                   String other, boolean seen) {
        return new AnswerItem("g1", "第1問", id, "問" + number, answer, status, issue, List.of(), List.of(number),
                other, seen);
    }

    private static AnswerItem ready(String id, int number, String answer) {
        return item(id, number, answer, READY, "", "", false);
    }

    private static final AnswerItem NOTICE = new AnswerItem("pages", "撮影の確認", "pages-reduced", "縮小",
            "（縮小して読みました）", NEEDS_REVIEW, "各頁を縮小して読みました");

    /** Made-up answers of every kind, in the order of the paper. */
    private static List<AnswerItem> mixed() {
        return List.of(
                ready("q1", 1, "ア"),
                item("q2", 2, "イ", NEEDS_REVIEW, "2回の読みで不一致", "ウ", false),
                item("q3", 3, "エ", READY, "", "", true),
                item("q4", 4, "", NEEDS_INPUT, "図の右端がありません", "", false),
                ready("q5", 5, "オ"),
                item("q6", 6, "", PENDING, "", "", false),
                item("q7", 7, "", FAILED, "送れませんでした", "", false),
                item("q8", 8, "カ", NEEDS_REVIEW, "表示できない要素: 表", "", false),
                NOTICE);
    }

    private static AnswerBundle bundle(long revision, List<AnswerItem> items, List<Integer> retake, boolean comparing) {
        return new AnswerBundle("session", "a".repeat(64), revision, items, "single", "complete", retake, comparing);
    }

    private static AnswerReader reader(List<AnswerItem> items, List<Integer> retake) {
        return new AnswerReader(bundle(1, items, retake, false), 40, 4, String::length, true);
    }

    /** Every screen from the first, each as its rows; the reader is left on the first. */
    private static List<String> screens(AnswerReader reader) {
        while (reader.pageNumber() > 1) reader.backward();
        List<String> screens = new ArrayList<>();
        for (int page = 0; page < reader.pageCount(); page++) {
            if (page > 0) reader.forward();
            screens.add(String.join("\n", reader.page().lines));
        }
        while (reader.pageNumber() > 1) reader.backward();
        return screens;
    }

    @Test public void certainAnswersComeFirstThenWhatToRetakeThenTheUncertainThenWhatWasAlreadyRead() {
        AnswerReader reader = reader(mixed(), List.of(3, 8, 9));
        List<String> screens = screens(reader);
        assertEquals(List.of(
                "1 ア　5 オ",
                "再撮影 3・8・9\nダブルタップで撮影",
                "？2 イ｜ウ\n6 解析中\n7 解析できません\n送れませんでした",
                "？8 カ\n3 エ"), screens);
        // No sentence about how an answer was reached, nothing of a question that cannot be answered, no notice.
        String all = String.join("\n", screens);
        for (String noise : List.of("要確認", "資料不足", "不一致", "図の右端", "縮小", "表示できない", "4 ")) {
            assertFalse(noise, all.contains(noise));
        }
        assertEquals("1", reader.indexLabel());
        reader.forward();
        assertEquals("the screen that belongs to no question", "再撮影", reader.indexLabel());
        reader.forward();
        assertEquals("2", reader.indexLabel());
    }

    @Test public void theRetakeScreenIsThereOnlyWithPagesToRetakeAndBreaksItsRowBetweenPageNumbers() {
        AnswerReader none = reader(mixed(), List.of());
        assertTrue(none.retakePages().isEmpty());
        assertEquals(List.of("1 ア　5 オ\n？2 イ｜ウ\n6 解析中\n7 解析できません", "送れませんでした\n？8 カ\n3 エ"),
                screens(none));

        List<Integer> many = List.of(3, 8, 9, 12, 15, 21);
        AnswerReader narrow = new AnswerReader(bundle(1, List.of(ready("q1", 1, "ア")), many, false),
                12, 4, String::length, true);
        assertEquals(many, narrow.retakePages());
        assertThrows(UnsupportedOperationException.class, () -> narrow.retakePages().add(1));
        assertEquals(List.of("1 ア", "再撮影 3・8・9・\n12・15・21\nダブルタップで撮影"), screens(narrow));
    }

    @Test public void swipesWrapAroundBothEndsAndASingleScreenStaysStill() {
        AnswerReader reader = reader(mixed(), List.of(3, 8, 9));
        assertEquals(1, reader.pageNumber());
        reader.backward();
        assertEquals(4, reader.pageNumber());
        assertEquals("q8", reader.current().questionId);
        reader.forward();
        assertEquals(1, reader.pageNumber());
        assertEquals("q1", reader.current().questionId);
        assertEquals(0, reader.offset());

        AnswerReader single = reader(List.of(ready("q1", 1, "ア")), List.of());
        single.forward();
        single.backward();
        assertEquals(1, single.pageNumber());
        assertEquals(List.of("1 ア"), single.page().lines);
        assertEquals("q1", single.current().questionId);
    }

    @Test public void nothingToShowIsOneScreenThatSaysSo() {
        List<AnswerItem> hidden = List.of(item("q4", 4, "", NEEDS_INPUT, "図の右端がありません", "", false), NOTICE);
        AnswerReader nothing = reader(hidden, List.of());
        assertEquals(List.of("解答なし"), screens(nothing));
        assertEquals("", nothing.indexLabel());
        nothing.forward();
        assertEquals(1, nothing.pageNumber());
        // With a page to retake, that screen is the whole reading.
        AnswerReader retake = reader(hidden, List.of(4));
        assertEquals(List.of("再撮影 4\nダブルタップで撮影"), screens(retake));
        assertEquals("再撮影", retake.indexLabel());
    }

    @Test public void aSavedPlaceOpensTheScreenThatShowsItsQuestion() {
        AnswerReader reader = reader(mixed(), List.of(3, 8, 9));
        reader.restore("q5", 0);
        assertEquals(1, reader.pageNumber());
        reader.restore("q7", 0);
        assertEquals(3, reader.pageNumber());
        reader.restore("q3", 0); // before q5 on the paper, shown after everything else
        assertEquals(4, reader.pageNumber());
        assertEquals("q3", reader.current().questionId);
        // A question that is not shown gives its place to the nearest one before it on the paper that is.
        reader.restore("q4", 0);
        assertEquals("q3", reader.current().questionId);
        assertEquals(4, reader.pageNumber());
        reader.restore("pages-reduced", 3);
        assertEquals("q8", reader.current().questionId);
        assertEquals(0, reader.offset());
        assertEquals(4, reader.pageNumber());

        // A reading not yet begun is saved as the bundle's first question at its start: that is the first screen,
        // also when that question is shown further on. Before a view has given its size as well.
        AnswerReader fresh = new AnswerReader(bundle(1, List.of(mixed().get(1), mixed().get(0)), List.of(), false), true);
        assertEquals("q1", fresh.current().questionId);
        fresh.restore("q2", 0);
        assertEquals("q1", fresh.current().questionId);
        fresh.viewport(40, 1, String::length);
        assertEquals(1, fresh.pageNumber());
        assertEquals(List.of("1 ア"), fresh.page().lines);
        fresh.restore("q2", 1);
        assertEquals(2, fresh.pageNumber());
        assertEquals("q2", fresh.current().questionId);
    }

    @Test public void thePlaceOnTheRetakeScreenIsKeptAsTheAnswerBeforeItAndOutlivesAReflow() {
        AnswerReader reader = reader(mixed(), List.of(3, 8, 9));
        reader.forward();
        assertEquals("再撮影", reader.indexLabel());
        assertEquals("q5", reader.current().questionId);
        assertEquals(0, reader.offset());
        reader.viewport(30, 4, String::length);
        assertEquals("the same screen at another size", List.of("再撮影 3・8・9", "ダブルタップで撮影"), reader.page().lines);

        AnswerReader restarted = reader(mixed(), List.of(3, 8, 9));
        restarted.restore(reader.current().questionId, reader.offset());
        assertEquals("after a restart: the answers just before it", 1, restarted.pageNumber());
        assertEquals("5", restarted.indexLabel());

        assertTrue(reader.accept(bundle(2, mixed(), List.of(3), false)));
        assertEquals("a newer revision leaves the wearer on it", List.of("再撮影 3", "ダブルタップで撮影"), reader.page().lines);
        assertTrue(reader.accept(bundle(3, mixed(), List.of(), false)));
        assertEquals("nothing left to retake: the answer before it", "q5", reader.current().questionId);
        assertEquals(1, reader.pageNumber());
        assertEquals("5", reader.indexLabel());
    }

    @Test public void aRevisionThatMovesTheQuestionBeingReadToAnotherSectionKeepsTheReaderOnIt() {
        List<AnswerItem> first = List.of(ready("q1", 1, "ア"), ready("q2", 2, "イ"), ready("q5", 5, "オ"));
        AnswerReader reader = new AnswerReader(bundle(1, first, List.of(), true), 6, 1, String::length, true);
        assertTrue(reader.comparing());
        reader.forward();
        assertEquals(List.of("2 イ"), reader.page().lines);

        // The comparison of the two reads leaves this answer in doubt: it moves behind the certain ones.
        List<AnswerItem> compared = List.of(first.get(0),
                item("q2", 2, "イ", NEEDS_REVIEW, "2回の読みで不一致", "エ", false), first.get(2));
        assertTrue(reader.accept(bundle(2, compared, List.of(), false)));
        assertFalse(reader.comparing());
        assertEquals("q2", reader.current().questionId);
        assertEquals(3, reader.pageNumber());
        assertEquals(List.of("？2 イ｜エ"), reader.page().lines);
        assertEquals(List.of("1 ア", "5 オ", "？2 イ｜エ"), screens(reader));

        // It cannot be answered after all: its page is to be retaken, the reader goes to the answer before it.
        reader.restore("q2", 0);
        List<AnswerItem> missing = List.of(first.get(0),
                item("q2", 2, "", NEEDS_INPUT, "下端がありません", "", false), first.get(2));
        assertTrue(reader.accept(bundle(3, missing, List.of(2), false)));
        assertEquals("q1", reader.current().questionId);
        assertEquals(1, reader.pageNumber());

        // Nothing before it is shown any more: the first screen.
        List<AnswerItem> gone = List.of(item("q1", 1, "", NEEDS_INPUT, "上端がありません", "", false),
                missing.get(1), first.get(2));
        assertTrue(reader.accept(bundle(4, gone, List.of(1, 2), false)));
        assertEquals("q5", reader.current().questionId);
        assertEquals(1, reader.pageNumber());
        assertEquals(List.of("5 オ"), reader.page().lines);
    }

    @Test public void fixedSlidesKeepLongWritingAndDiagramsInOrderAndLeaveOutWhatCannotBeAnswered() throws Exception {
        AnswerDiagram diagram = new AnswerDiagram(new org.json.JSONObject("{\"alt\":\"円\",\"aspect_ratio\":1,"
                + "\"elements\":[{\"type\":\"circle\",\"cx\":0.5,\"cy\":0.5,\"r\":0.3}]}"));
        String derivation = "AB=CD より対応する角は等しい。\n".repeat(30);
        AnswerBundle bundle = new AnswerBundle("session", "a".repeat(64), 1, List.of(
                new AnswerItem("g1", "第1問", "q1", "問1", derivation, AnswerItem.Status.READY, "", List.of(diagram), List.of(101)),
                new AnswerItem("g1", "第1問", "q2", "問2", "", AnswerItem.Status.NEEDS_INPUT, "図の右端がありません", List.of(), List.of(102))));
        AnswerReader reader = new AnswerReader(bundle, 16, 3, String::length, true);
        StringBuilder text = new StringBuilder();
        int figures = 0;
        for (int page = 0; page < reader.pageCount(); page++) {
            if (reader.diagram() != null) {
                figures++;
                AnswerReader restored = new AnswerReader(bundle, 12, 2, String::length, true);
                restored.restore(reader.current().questionId, reader.offset());
                assertEquals(diagram, restored.diagram());
            } else text.append(String.join("", reader.page().lines));
            reader.forward();
        }
        assertEquals("after the last screen comes the first", 1, reader.pageNumber());
        assertEquals(1, figures);
        assertTrue(text.toString().contains(derivation.replace("\n", "")));
        // Its page is asked for again on the retake screen; the question itself takes no row.
        assertFalse(text.toString().contains("102"));
        assertFalse(text.toString().contains("資料不足") || text.toString().contains("図の右端がありません"));
    }

    @Test public void answerNumbersSurviveOfflineSerialization() throws Exception {
        AnswerItem item = new AnswerItem("g1", "第1問", "q1", "問1", "4,2", AnswerItem.Status.READY,
                "", List.of(), List.of(101, 102));
        AnswerBundle bundle = new AnswerBundle("session", "a".repeat(64), 1, List.of(item));
        AnswerItem saved = AnswerBundle.fromJson(bundle.toJson()).items.get(0);
        assertEquals(List.of(101, 102), saved.answerNumbers);
        assertEquals("101,102", saved.readingLabel());
    }
}
