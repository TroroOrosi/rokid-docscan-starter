package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

import androidx.test.core.app.ApplicationProvider;
import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
import dev.rokid.docscanrelay.study.AnswerStore;
import java.io.File;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

@RunWith(RobolectricTestRunner.class)
public class AnswerSurfaceTest {
    private AnswerBundle bundle() {
        return new AnswerBundle("7", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 2"),
                AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
    }

    @Test
    public void aFetchedBundleSurvivesAndResumesWhereItWasLeft() throws Exception {
        File directory = ApplicationProvider.getApplicationContext().getFilesDir();
        AnswerStore store = new AnswerStore(directory);

        store.start(bundle());
        store.save(bundle(), "q11", 40, false);
        AnswerStore.Saved resumed = new AnswerStore(directory).resume();

        assertNotNull(resumed);
        assertEquals("q11", resumed.questionId);
        assertEquals(40, resumed.offset);
        assertEquals("7", resumed.bundle.sessionId);
    }
}
