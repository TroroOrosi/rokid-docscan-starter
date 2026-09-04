package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.Optional;

import org.junit.Test;

/**
 * The offline buffer. Measured on 2026-09-04: with Wi-Fi off the glasses have
 * no IPv4 address and no route at all, yet the camera still returns full
 * 4032x3024 stills in under a second. So capture keeps working while upload
 * cannot, and the pages have to wait somewhere without losing their order.
 */
public final class UploadQueueTest {

    @Test
    public void isEmptyToBeginWith() {
        UploadQueue queue = new UploadQueue();

        assertEquals(0, queue.size());
        assertFalse(queue.head().isPresent());
    }

    @Test
    public void handsBackPagesInTheOrderTheyWerePhotographed() {
        UploadQueue queue = new UploadQueue();
        queue.enqueue(page(0));
        queue.enqueue(page(1));
        queue.enqueue(page(2));

        assertEquals(0, queue.head().orElseThrow().pageIndex());
        queue.markUploaded();
        assertEquals(1, queue.head().orElseThrow().pageIndex());
        queue.markUploaded();
        assertEquals(2, queue.head().orElseThrow().pageIndex());
        queue.markUploaded();
        assertEquals(0, queue.size());
    }

    @Test
    public void keepsAFailedPageAtTheHeadInsteadOfRotatingItBehindLaterPages() {
        UploadQueue queue = new UploadQueue();
        queue.enqueue(page(0));
        queue.enqueue(page(1));

        queue.markFailed();

        assertEquals("reordering would file page 2 as page 1",
                0, queue.head().orElseThrow().pageIndex());
        assertEquals(2, queue.size());
    }

    @Test
    public void countsAttemptsOnTheHeadSoCallersCanBackOff() {
        UploadQueue queue = new UploadQueue();
        queue.enqueue(page(0));

        assertEquals(0, queue.head().orElseThrow().attempts());
        queue.markFailed();
        assertEquals(1, queue.head().orElseThrow().attempts());
        queue.markFailed();
        assertEquals(2, queue.head().orElseThrow().attempts());
    }

    @Test
    public void refusesANewPageWhenFullRatherThanDroppingAnEarlierOne() {
        UploadQueue queue = new UploadQueue();
        for (int index = 0; index < UploadQueue.MAX_PENDING; index++) {
            assertTrue(queue.enqueue(page(index)));
        }

        assertFalse("dropping silently would register a document missing a page",
                queue.enqueue(page(UploadQueue.MAX_PENDING)));
        assertEquals(UploadQueue.MAX_PENDING, queue.size());
        assertEquals(0, queue.head().orElseThrow().pageIndex());
    }

    @Test
    public void acceptsAgainAfterTheHeadIsUploaded() {
        UploadQueue queue = new UploadQueue();
        for (int index = 0; index < UploadQueue.MAX_PENDING; index++) {
            queue.enqueue(page(index));
        }

        queue.markUploaded();

        assertTrue(queue.enqueue(page(UploadQueue.MAX_PENDING)));
    }

    @Test
    public void markingAnEmptyQueueIsHarmless() {
        UploadQueue queue = new UploadQueue();

        queue.markUploaded();
        queue.markFailed();

        assertEquals(0, queue.size());
    }

    @Test
    public void rejectsAPageWithNoImageBytes() {
        UploadQueue queue = new UploadQueue();

        assertFalse(queue.enqueue(new PendingPage(0, new byte[0], "text", 0)));
        assertEquals(0, queue.size());
    }

    @Test
    public void reportsTheBufferedByteTotalSoTheHudCanWarnBeforeItIsFull() {
        UploadQueue queue = new UploadQueue();
        queue.enqueue(new PendingPage(0, new byte[1000], "", 0));
        queue.enqueue(new PendingPage(1, new byte[2000], "", 0));

        assertEquals(3000L, queue.bufferedBytes());
        queue.markUploaded();
        assertEquals(2000L, queue.bufferedBytes());
    }

    @Test
    public void pendingPageKeepsTheRotationAndTextItWasCapturedWith() {
        PendingPage pending = new PendingPage(3, new byte[]{1, 2}, "  answer  ", 90);

        assertEquals(3, pending.pageIndex());
        assertEquals(90, pending.imageRotation());
        assertEquals("stored trimmed so the server never sees padding",
                "answer", pending.ocrText());
        assertEquals(2, pending.jpeg().length);
    }

    private static PendingPage page(int index) {
        return new PendingPage(index, new byte[]{1, 2, 3}, "page " + index, 0);
    }
}
