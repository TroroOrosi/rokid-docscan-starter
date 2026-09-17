package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
import dev.rokid.docscanrelay.study.AnswerStore;
import java.io.File;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.util.List;
import java.util.concurrent.ExecutorService;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

/** Exercise real persistence failures without a camera, server or physical storage fault. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28, manifest = Config.NONE)
public class AnswerExitPersistenceFailureTest {
    private DocScanGlassActivity activity;
    private AnswerStore original;

    @Before public void prepareReader() throws Exception {
        activity = Robolectric.buildActivity(DocScanGlassActivity.class).get();
        File root = activity.getFilesDir();
        original = new AnswerStore(root);
        AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q1", "問1", "x = 2")));
        original.start(bundle);
        set("hud", new HudView(activity));
        set("answerStore", original);
        set("viewingPreviousAnswers", true);
        Method open = DocScanGlassActivity.class.getDeclaredMethod(
                "openAnswers", AnswerBundle.class, String.class, int.class);
        open.setAccessible(true);
        open.invoke(activity, bundle, "q1", 0);
        // A non-directory path forces a real IOException. The previously saved
        // answer remains intact in its original directory for verification.
        File unavailable = new File(root, "unavailable-directory");
        Files.write(unavailable.toPath(), new byte[]{1});
        set("answerStore", new AnswerStore(unavailable));
    }

    @After public void stopWriter() throws Exception {
        ((ExecutorService) get("answerPersistExecutor")).shutdownNow();
    }

    @Test public void failedCloseKeepsTheReaderAndAllowsExplicitRetry() throws Exception {
        invoke("closeAnswers");
        assertNotNull("a failed CLOSED write must not release the reader", get("reader"));
        assertFalse(original.load().closed);
        set("answerStore", original);
        invoke("closeAnswers");
        assertNull(get("reader"));
        assertTrue(original.load().closed);
    }

    @Test public void failedCloseCannotClaimTheActivityHasExited() throws Exception {
        invoke("exitSession");
        assertFalse("exit must wait for the durable CLOSED acknowledgement", (boolean) get("sessionClosed"));
        assertFalse(activity.isFinishing());
        assertNotNull(get("reader"));
        assertFalse(original.load().closed);
        set("answerStore", original);
        invoke("exitSession");
        assertTrue((boolean) get("sessionClosed"));
        assertTrue(original.load().closed);
    }

    private Object get(String name) throws Exception {
        Field field = DocScanGlassActivity.class.getDeclaredField(name);
        field.setAccessible(true);
        return field.get(activity);
    }

    private void set(String name, Object value) throws Exception {
        Field field = DocScanGlassActivity.class.getDeclaredField(name);
        field.setAccessible(true);
        field.set(activity, value);
    }

    private void invoke(String name) throws Exception {
        Method method = DocScanGlassActivity.class.getDeclaredMethod(name);
        method.setAccessible(true);
        method.invoke(activity);
    }
}
