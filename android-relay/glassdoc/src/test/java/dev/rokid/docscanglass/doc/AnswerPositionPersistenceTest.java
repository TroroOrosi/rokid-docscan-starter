package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;

import android.os.Looper;
import dev.rokid.docscanrelay.CaptureSurface;
import dev.rokid.docscanrelay.ClientIdentity;
import dev.rokid.docscanrelay.DocScanController;
import dev.rokid.docscanrelay.study.AnswerBundle;
import dev.rokid.docscanrelay.study.AnswerItem;
import dev.rokid.docscanrelay.study.AnswerReader;
import dev.rokid.docscanrelay.study.AnswerStore;
import java.io.File;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.AbstractExecutorService;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.Shadows;
import org.robolectric.annotation.Config;

/** Real Activity persistence tasks and AtomicFile, with only task scheduling gated. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28, manifest = Config.NONE)
public class AnswerPositionPersistenceTest {
    private DocScanGlassActivity activity;
    private File directory;
    private AnswerStore store;
    private AnswerBundle bundle;
    private GateExecutor queue;
    private final ExecutorService caller = Executors.newSingleThreadExecutor();

    @Before public void prepare() throws Exception {
        activity = Robolectric.buildActivity(DocScanGlassActivity.class).get();
        directory = activity.getFilesDir();
        store = new AnswerStore(directory);
        bundle = bundle("original answer ".repeat(40));
        store.start(bundle);
        set("answerStore", store);
        set("hud", new HudView(activity));
        set("viewingPreviousAnswers", true);
        set("controller", new DocScanController(activity, new NoCapture(), null, activity,
                new ClientIdentity("test-glasses", "position-test/1", "no-camera")));
        ((ExecutorService)get("answerPersistExecutor")).shutdown();
        queue = new GateExecutor();
        set("answerPersistExecutor", queue);
        invoke("openAnswers", new Class<?>[]{AnswerBundle.class, String.class, int.class}, bundle, "q1", 0);
    }

    @After public void dispose() throws Exception {
        caller.shutdownNow();
        activity.onDestroy();
        queue.shutdownNow();
    }

    @Test public void twentyPendingMovesSaveOnlyTheLatestCursorBeforeDurableClose() throws Exception {
        for (int offset = 1; offset <= 20; offset++) move(offset);
        assertEquals("only one unstarted cursor write should remain", 1, queue.size());
        assertSaved(0, false, bundle.items.get(0).answer);
        Future<Boolean> closed = caller.submit(() -> (Boolean)invoke("closeAnswers"));
        queue.awaitSize(2);
        assertNotNull(get("reader"));
        queue.runNext();
        assertSaved(20, false, bundle.items.get(0).answer);
        assertNotNull("CLOSED must be durable before releasing the reader", get("reader"));
        queue.runNext();
        assertTrue(closed.get(5, TimeUnit.SECONDS));
        assertNull(get("reader"));
        assertSaved(20, true, bundle.items.get(0).answer);
        assertTrue("a fresh store must retain CLOSED", new AnswerStore(directory).load().closed);
    }

    @Test public void aWaitedOpenWriteIsAFifoBarrier() throws Exception {
        move(10);
        Future<Boolean> waited = caller.submit(() -> (Boolean)invoke("persistAnswerPosition",
                new Class<?>[]{boolean.class, boolean.class}, false, true));
        queue.awaitSize(2);
        move(20);
        assertEquals(3, queue.size());
        queue.runNext();
        assertSaved(10, false, bundle.items.get(0).answer);
        queue.runNext();
        assertTrue(waited.get(5, TimeUnit.SECONDS));
        assertSaved(10, false, bundle.items.get(0).answer);
        queue.runNext();
        assertSaved(20, false, bundle.items.get(0).answer);
    }

    @Test public void aTerminalWriteIsABarrierEvenWithoutWaitingAndCannotBeReopenedByLaterMoves() throws Exception {
        move(10);
        ((AnswerReader)get("reader")).restore("q1", 20);
        assertTrue((Boolean)invoke("persistAnswerPosition", new Class<?>[]{boolean.class, boolean.class}, true, false));
        move(30);
        assertEquals(3, queue.size());
        queue.runNext();
        assertSaved(10, false, bundle.items.get(0).answer);
        queue.runNext();
        assertSaved(20, true, bundle.items.get(0).answer);
        queue.runNext();
        assertSaved(20, true, bundle.items.get(0).answer);
    }

    @Test public void distinctBundleReferencesNeverMergeEvenWhenTheirIdentityFieldsMatch() throws Exception {
        move(10);
        AnswerBundle replacement = bundle("replacement answer ".repeat(40));
        set("reader", new AnswerReader(replacement, true));
        move(20);
        assertEquals(2, queue.size());
        queue.runNext();
        assertSaved(10, false, bundle.items.get(0).answer);
        queue.runNext();
        assertSaved(20, false, replacement.items.get(0).answer);
    }

    @Test public void movingAcrossQuestionsAndBackSavesTheLatestQuestionAndOffset() throws Exception {
        AnswerBundle multiple = new AnswerBundle("7", "a".repeat(64), 1, List.of(
                AnswerItem.ready("g1", "第1問", "q1", "問1", "first answer ".repeat(40)),
                AnswerItem.ready("g1", "第1問", "q2", "問2", "second answer ".repeat(40)),
                AnswerItem.ready("g2", "第2問", "q3", "問3", "third answer ".repeat(40))));
        store.start(multiple);
        AnswerReader reader = new AnswerReader(multiple, true);
        set("reader", reader);
        for (String question : List.of("q2", "q3", "q1", "q2")) {
            reader.restore(question, question.equals("q2") ? 19 : 37);
            assertTrue((Boolean)invoke("persistAnswerPosition", new Class<?>[]{boolean.class}, false));
        }
        reader.restore("q2", 9);
        assertTrue((Boolean)invoke("persistAnswerPosition", new Class<?>[]{boolean.class}, false));
        assertEquals(1, queue.size());
        queue.runNext();
        AnswerStore.Saved restarted = new AnswerStore(directory).load();
        assertEquals("q2", restarted.questionId);
        assertEquals(9, restarted.offset);
        assertEquals(multiple.toJson(), restarted.bundle.toJson());
    }

    @Test public void aStartedWriteKeepsItsSnapshotWhileLaterMovesMergeSeparately() throws Exception {
        move(10);
        Future<?> running;
        synchronized (store) {
            running = caller.submit(queue::runNext);
            awaitBlockedWriter();
            move(20);
            move(30);
            assertEquals("a running write must have detached before storage I/O", 1, queue.size());
        }
        running.get(5, TimeUnit.SECONDS);
        assertSaved(10, false, bundle.items.get(0).answer);
        queue.runNext();
        assertSaved(30, false, bundle.items.get(0).answer);
    }

    @Test public void startupLoadReadsTheCursorBeforeLaterMoves() throws Exception {
        move(10);
        set("choosingSession", true);
        invoke("loadStartupAnswers");
        move(20);
        assertEquals(3, queue.size());
        queue.runNext();
        assertSaved(10, false, bundle.items.get(0).answer);
        queue.runNext();
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertEquals(10, ((AnswerStore.Saved)get("startupAnswers")).offset);
        queue.runNext();
        assertSaved(20, false, bundle.items.get(0).answer);
    }

    @Test public void savedReadingLoadCannotBeCrossedByLaterMoves() throws Exception {
        move(10);
        invoke("openSavedReadingAnswers");
        move(20);
        assertEquals(3, queue.size());
        set("reader", null);
        set("powerSession", 7L);
        set("awaitingAnswers", true);
        queue.runNext();
        queue.runNext();
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertEquals(10, ((AnswerReader)get("reader")).offset());
        queue.runNext();
        assertSaved(20, false, bundle.items.get(0).answer);
    }

    @Test public void resumeIsAFifoBarrierAndRetainsTheEarlierCursor() throws Exception {
        move(10);
        invoke("resumePreviousAnswers");
        move(20);
        assertEquals(3, queue.size());
        queue.runNext();
        queue.runNext();
        assertSaved(10, false, bundle.items.get(0).answer);
        queue.runNext();
        assertSaved(20, false, bundle.items.get(0).answer);
    }

    @Test public void displayAcknowledgementIsAFifoReadBarrier() throws Exception {
        move(10);
        ((AnswerReader)get("reader")).viewport(200, 4, text -> text.length() * 8f);
        invoke("acknowledgeDisplayedAnswers");
        move(20);
        assertEquals(3, queue.size());
        queue.runNext();
        assertSaved(10, false, bundle.items.get(0).answer);
        queue.runNext();
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertEquals(7L, get("acknowledgedSession"));
        queue.runNext();
        assertSaved(((AnswerReader)get("reader")).offset(), false, bundle.items.get(0).answer);
    }

    @Test public void aFailedCloseKeepsTheReaderAndOriginalUntilExplicitRetry() throws Exception {
        move(10);
        move(20);
        assertEquals(1, queue.size());
        queue.runNext();
        File unavailable = new File(directory, "not-a-directory");
        Files.write(unavailable.toPath(), new byte[]{1});
        set("answerStore", new AnswerStore(unavailable));
        Future<Boolean> closed = caller.submit(() -> (Boolean)invoke("closeAnswers"));
        queue.awaitSize(1);
        queue.runNext();
        assertFalse(closed.get(5, TimeUnit.SECONDS));
        assertNotNull(get("reader"));
        assertSaved(20, false, bundle.items.get(0).answer);
        set("answerStore", store);
        Future<Boolean> retry = caller.submit(() -> (Boolean)invoke("closeAnswers"));
        queue.awaitSize(1);
        queue.runNext();
        assertTrue(retry.get(5, TimeUnit.SECONDS));
        assertNull(get("reader"));
        assertSaved(20, true, bundle.items.get(0).answer);
    }

    @Test public void shutdownDrainsTheLatestQueuedCursorAndRestartReadsTheCompleteAnswer() throws Exception {
        for (int offset = 1; offset <= 20; offset++) move(offset);
        activity.onDestroy();
        assertTrue(queue.isShutdown());
        while (queue.size() > 0) queue.runNext();
        assertSaved(20, false, bundle.items.get(0).answer);
        AnswerStore.Saved restarted = new AnswerStore(directory).load();
        assertEquals(20, restarted.offset);
        assertEquals(bundle.toJson(), restarted.bundle.toJson());
    }

    @Test public void aSavedReadFromAnOldGenerationCannotReopenTheReader() throws Exception {
        move(10);
        invoke("openSavedReadingAnswers");
        move(20);
        set("reader", null);
        set("awaitingAnswers", true);
        set("powerGeneration", 1L);
        while (queue.size() > 0) queue.runNext();
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertNull(get("reader"));
        assertSaved(20, false, bundle.items.get(0).answer);
    }

    @Test public void aReadCompletionAfterDestructionCannotReopenTheReader() throws Exception {
        move(10);
        invoke("openSavedReadingAnswers");
        move(20);
        set("reader", null);
        set("powerSession", 7L);
        set("awaitingAnswers", true);
        queue.runNext();
        queue.runNext();
        activity.onDestroy();
        queue.runNext();
        Shadows.shadowOf(Looper.getMainLooper()).idle();
        assertNull(get("reader"));
        assertSaved(20, false, bundle.items.get(0).answer);
    }

    private void move(int offset) throws Exception {
        ((AnswerReader)get("reader")).restore("q1", offset);
        assertTrue((Boolean)invoke("persistAnswerPosition", new Class<?>[]{boolean.class}, false));
    }

    private void assertSaved(int offset, boolean closed, String answer) throws Exception {
        AnswerStore.Saved saved = new AnswerStore(directory).load();
        assertNotNull(saved);
        assertEquals("q1", saved.questionId);
        assertEquals(offset, saved.offset);
        assertEquals(closed, saved.closed);
        assertEquals(answer, saved.bundle.items.get(0).answer);
    }

    private void awaitBlockedWriter() throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (System.nanoTime() < deadline) {
            for (Thread thread : Thread.getAllStackTraces().keySet()) {
                if (thread.getState() != Thread.State.BLOCKED) continue;
                for (StackTraceElement frame : thread.getStackTrace()) {
                    if (frame.getClassName().equals(AnswerStore.class.getName()) && frame.getMethodName().equals("save")) return;
                }
            }
            Thread.sleep(5);
        }
        fail("the real AnswerStore.save must be blocked on its monitor");
    }

    private static AnswerBundle bundle(String answer) {
        return new AnswerBundle("7", "a".repeat(64), 1,
                List.of(AnswerItem.ready("g1", "第1問", "q1", "問1", answer)));
    }

    private Object invoke(String name) throws Exception { return invoke(name, new Class<?>[0]); }
    private Object invoke(String name, Class<?>[] types, Object... arguments) throws Exception {
        Method method = DocScanGlassActivity.class.getDeclaredMethod(name, types);
        method.setAccessible(true);
        return method.invoke(activity, arguments);
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

    private static final class GateExecutor extends AbstractExecutorService {
        private final ArrayDeque<Runnable> tasks = new ArrayDeque<>();
        private boolean shutdown;
        synchronized int size() { return tasks.size(); }
        void runNext() {
            Runnable task;
            synchronized (this) { task = tasks.removeFirst(); }
            task.run();
        }
        synchronized void awaitSize(int expected) throws InterruptedException {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (tasks.size() < expected && System.nanoTime() < deadline) wait(20);
            assertEquals("queued task count", expected, tasks.size());
        }
        @Override public synchronized void execute(Runnable task) {
            if (shutdown) throw new RejectedExecutionException();
            tasks.addLast(task);
            notifyAll();
        }
        @Override public synchronized void shutdown() { shutdown = true; }
        @Override public synchronized List<Runnable> shutdownNow() {
            shutdown = true;
            List<Runnable> remaining = new ArrayList<>(tasks);
            tasks.clear();
            return remaining;
        }
        @Override public synchronized boolean isShutdown() { return shutdown; }
        @Override public synchronized boolean isTerminated() { return shutdown && tasks.isEmpty(); }
        @Override public boolean awaitTermination(long timeout, TimeUnit unit) { return isTerminated(); }
    }

    private static final class NoCapture implements CaptureSurface {
        @Override public PhotoStartResult takePhoto(int width, int height, int quality) { throw new AssertionError("no camera"); }
        @Override public long showHud(List<String> lines) { return 1; }
        @Override public long showCaptureAiming(int page, boolean retake, boolean stable) { return 1; }
        @Override public long showCaptureReview(byte[] jpeg, int rotation, List<String> lines) { return 1; }
        @Override public void fenceCustomViewEpoch(long generation, String reason) { }
    }
}
