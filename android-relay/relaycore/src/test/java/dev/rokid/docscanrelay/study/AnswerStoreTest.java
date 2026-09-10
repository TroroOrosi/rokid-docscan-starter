package dev.rokid.docscanrelay.study;

import static org.junit.Assert.*;

import java.io.File;
import java.io.IOException;
import java.util.List;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(manifest = Config.NONE, sdk = 28)
public class AnswerStoreTest {
    @Rule public TemporaryFolder temp = new TemporaryFolder();

    private AnswerBundle bundle(String session) {
        return new AnswerBundle(session, "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "大問1", "q1", "(1)", "書く内容だけ。".repeat(100))));
    }

    @Test public void closeAndFiftyRestartsKeepTheCompleteAnswerButNeverReopenIt() throws Exception {
        File directory = temp.newFolder();
        AnswerStore store = new AnswerStore(directory);
        AnswerBundle bundle = bundle("s");
        store.start(bundle);
        store.save(bundle, "q1", 80, true);
        for (int i = 0; i < 50; i++) {
            AnswerStore.Saved saved = new AnswerStore(directory).load();
            assertTrue(saved.closed);
            assertEquals(80, saved.offset);
            assertEquals(bundle.items.get(0).answer, saved.bundle.items.get(0).answer);
        }
        AnswerStore.Saved resumed = store.resume();
        assertFalse(resumed.closed);
        assertEquals(80, resumed.offset);
    }

    @Test public void lateSaveCannotUndoCloseOrReplaceANewerSession() throws Exception {
        AnswerStore store = new AnswerStore(temp.newFolder());
        AnswerBundle old = bundle("old");
        store.start(old);
        store.save(old, "q1", 40, true);
        assertThrows(IOException.class, () -> store.save(old, "q1", 0, false));
        store.start(bundle("new"));
        assertThrows(IOException.class, () -> store.save(old, "q1", 0, true));
        assertEquals("new", store.load().bundle.sessionId);
    }

    @Test public void olderResultRevisionCannotReplaceSavedAnswers() throws Exception {
        AnswerStore store = new AnswerStore(temp.newFolder());
        AnswerBundle old = bundle("s");
        store.start(old);
        AnswerBundle next = old.withAnswer(AnswerItem.ready("g1", "大問1", "q1", "(1)", "新しい答え"));
        store.save(next, "q1", 0, false);
        assertThrows(IOException.class, () -> store.save(old, "q1", 0, false));
        assertEquals("新しい答え", store.load().bundle.items.get(0).answer);
    }

    @Test public void failedPersistenceCannotReportACompletedClose() throws Exception {
        File notDirectory = temp.newFile();
        AnswerStore store = new AnswerStore(notDirectory);
        assertThrows(IOException.class, () -> store.start(bundle("s")));
    }

    @Test public void emptyStoreHasNoAnswerToResume() throws Exception {
        AnswerStore store = new AnswerStore(temp.newFolder());
        assertNull(store.load());
        assertNull(store.resume());
    }
}
