package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;
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
        assertEquals(List.of("101 4", "102 2"), reader.page().lines);
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

    @Test public void answerNumbersSurviveOfflineSerialization() throws Exception {
        AnswerItem item = new AnswerItem("g1", "第1問", "q1", "問1", "4,2", AnswerItem.Status.READY,
                "", List.of(), List.of(101, 102));
        AnswerBundle bundle = new AnswerBundle("session", "a".repeat(64), 1, List.of(item));
        AnswerItem saved = AnswerBundle.fromJson(bundle.toJson()).items.get(0);
        assertEquals(List.of(101, 102), saved.answerNumbers);
        assertEquals("101,102", saved.readingLabel());
    }
}
