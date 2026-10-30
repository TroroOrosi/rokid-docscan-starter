package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;
import android.media.DocScanTestImage;
import android.media.Image;
import android.os.Handler;
import android.os.Looper;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 32, manifest = Config.NONE)
public class ZslInputTransferTest {
    static final class Worker implements Executor {
        final ArrayDeque<Runnable> tasks = new ArrayDeque<>();
        public void execute(Runnable task) { tasks.add(task); }
        void next() { tasks.remove().run(); shadowOf(Looper.getMainLooper()).idle(); }
    }
    static final class Port implements ZslInputTransfer.Port {
        Runnable released; int queued, closes; boolean throwQueue;
        public void queue(Image image) {
            queued++; if (throwQueue) throw new IllegalStateException("synthetic");
            image.close();
        }
        public void close() { closes++; }
    }
    @Test public void writerCreditRequiresBothQueueCompletionAndConsumerRelease() {
        Worker worker = new Worker(); Port port = new Port(); List<String> events = new ArrayList<>();
        ZslInputTransfer transfer = new ZslInputTransfer(worker, new Handler(Looper.getMainLooper()),
                released -> { port.released = released; return port; }, error -> fail(error));
        worker.next(); assertTrue(transfer.ready());
        assertTrue(transfer.queue(new DocScanTestImage(events), () -> events.add("queued")));
        assertFalse(transfer.ready()); assertFalse(transfer.idle());
        assertFalse(transfer.queue(new DocScanTestImage(new ArrayList<>()), () -> fail("second queue")));
        // Release notifications and worker completion are independent events.
        port.released.run(); assertFalse(transfer.ready()); worker.next();
        assertEquals(List.of("image.close", "queued"), events);
        assertTrue(transfer.ready()); assertEquals(1, port.queued);
        transfer.close(); worker.next(); assertEquals(1, port.closes);
    }
    @Test public void stopDoesNotAcknowledgeIdleWhileWorkerOwnsAnUnresolvedInput() {
        Worker worker = new Worker(); Port port = new Port(); List<String> events = new ArrayList<>();
        ZslInputTransfer transfer = new ZslInputTransfer(worker, new Handler(Looper.getMainLooper()),
                released -> { port.released = released; return port; }, error -> fail(error));
        worker.next();
        transfer.queue(new DocScanTestImage(events), () -> fail("stopped input cannot submit a capture"));
        transfer.close();
        assertFalse(transfer.idle());
        final boolean[] timer = {false}; new Handler(Looper.getMainLooper()).postDelayed(() -> timer[0] = true, 15_000);
        shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(15));
        assertTrue(timer[0]); assertFalse(transfer.idle());
        worker.next(); worker.next();
        assertEquals(0, port.queued); assertEquals(List.of("image.close"), events);
        assertTrue(transfer.idle()); assertEquals(1, port.closes);
    }
    @Test public void queueFailureRetainsUnknownCreditAndClosesTheOwnedImageOnce() {
        Worker worker = new Worker(); Port port = new Port(); port.throwQueue = true;
        List<String> events = new ArrayList<>(), failures = new ArrayList<>();
        ZslInputTransfer transfer = new ZslInputTransfer(worker, new Handler(Looper.getMainLooper()),
                released -> { port.released = released; return port; }, failures::add);
        worker.next(); transfer.queue(new DocScanTestImage(events), () -> fail("failed transfer")); worker.next();
        assertEquals(1, failures.size()); assertFalse(transfer.ready()); assertFalse(transfer.idle());
        assertEquals(List.of("image.close"), events);
        transfer.close(); worker.next(); assertTrue(transfer.idle());
    }
    @Test public void aBlockedNativeQueueCannotBlockTheCameraDeadlineOrClaimStoppedIdle() throws Exception {
        var executor = Executors.newSingleThreadExecutor();
        CountDownLatch entered = new CountDownLatch(1), unblock = new CountDownLatch(1);
        List<String> failures = new ArrayList<>(); final boolean[] closed = {false};
        ZslInputTransfer transfer = new ZslInputTransfer(executor, new Handler(Looper.getMainLooper()),
                released -> new ZslInputTransfer.Port() {
                    public void queue(Image image) {
                        entered.countDown();
                        try { if (!unblock.await(5, TimeUnit.SECONDS)) throw new IllegalStateException("test queue deadline"); }
                        catch (InterruptedException error) { throw new IllegalStateException(error); }
                        image.close();
                    }
                    public void close() { closed[0] = true; }
                }, failures::add);
        try {
            executor.submit(() -> {}).get(5, TimeUnit.SECONDS); shadowOf(Looper.getMainLooper()).idle();
            assertTrue(transfer.queue(new DocScanTestImage(new ArrayList<>()), () -> fail("closed native input cannot submit")));
            assertTrue(entered.await(5, TimeUnit.SECONDS));
            transfer.close(); assertFalse(transfer.idle());
            final boolean[] expired = {false};
            new Handler(Looper.getMainLooper()).postDelayed(() -> expired[0] = true, 15_000);
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(15));
            assertTrue(expired[0]); assertFalse(closed[0]); assertFalse(transfer.idle());
            var drained = executor.submit(() -> {});
            unblock.countDown(); drained.get(5, TimeUnit.SECONDS); shadowOf(Looper.getMainLooper()).idle();
            assertTrue(closed[0]); assertTrue(transfer.idle()); assertTrue(failures.isEmpty());
        } finally { unblock.countDown(); transfer.close(); executor.shutdownNow(); }
    }
}
