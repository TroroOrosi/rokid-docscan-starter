package dev.rokid.docscanglass.doc;

import static org.junit.Assert.*;
import java.util.Arrays;
import org.junit.Test;

public class PageChangeTest {
    private byte[] frame(int value) {
        byte[] pixels = new byte[32 * 24];
        Arrays.fill(pixels, (byte) value);
        return pixels;
    }

    @Test public void oneStillPerTurnEvenWhenNextPageLooksLikePreviousPage() {
        PageChange change = new PageChange();
        byte[] page = frame(180);
        change.observe(page, 0);
        change.observe(page, 400);
        assertTrue(change.ready(400));
        change.consumed();
        change.observe(page, 1000);
        assertFalse(change.ready(1000));
        change.observe(frame(70), 1300); // page turning during the photo review
        change.observe(page, 1500); // similar page: retain the observed turn
        change.observe(page, 1900);
        assertTrue(change.ready(1900));
        change.consumed();
        change.observe(page, 3000);
        assertFalse(change.ready(3000));
    }

    @Test public void smallExposureDriftDoesNotPretendThatThePageTurned() {
        PageChange change = new PageChange();
        change.observe(frame(180), 0);
        change.observe(frame(180), 400);
        change.consumed();
        change.observe(frame(183), 1000);
        change.observe(frame(183), 1500);
        assertFalse(change.ready(1500));
    }
}
