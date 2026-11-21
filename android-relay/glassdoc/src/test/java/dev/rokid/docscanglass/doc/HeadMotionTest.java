package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class HeadMotionTest {
    private static final long START = 1_000_000_000L;
    private static final long STEP = 5_000_000L; // 200 Hz

    /**
     * Until 2026-11-14 a photo was allowed by the 300 ms before its request and nothing looked at the exposure that
     * came 0.3-0.7 s later. A photo is measured against the turning during its own exposure.
     */
    @Test public void aPhotoIsMeasuredAgainstTheTurningDuringItsOwnExposure() {
        HeadMotion.Ring ring = new HeadMotion.Ring(16);
        for (int i = 0; i < 8; i++) ring.add(START + i * STEP, i == 5 ? 0.09f : 0.01f);

        HeadMotion.Span quiet = ring.between(START, START + 3 * STEP);
        assertEquals(4, quiet.samples);
        assertEquals(0.01f, quiet.peak, 1e-6f);
        assertEquals(0.01f, quiet.mean, 1e-6f);
        assertTrue("readings continue past the end of the window", quiet.covered);

        HeadMotion.Span moved = ring.between(START + 4 * STEP, START + 6 * STEP);
        assertEquals(0.09f, moved.peak, 1e-6f);
        assertEquals((0.01f + 0.09f + 0.01f) / 3, moved.mean, 1e-6f);
        // 0.09 rad/s over a 30 ms exposure through a 1900-pixel focal length
        assertEquals(0.09f * 0.030f * HeadMotion.FOCAL_PIXELS, moved.blurPixels(30_000_000L), 1e-3f);
    }

    @Test public void aWindowWithoutReadingsIsNotStillness() {
        HeadMotion.Ring ring = new HeadMotion.Ring(16);
        assertNull(ring.between(START, START + STEP));
        for (int i = 0; i < 4; i++) ring.add(START + i * STEP, 0.01f);
        assertNull("after the last reading", ring.between(START + 10 * STEP, START + 12 * STEP));
        assertFalse("the window runs past the last reading", ring.between(START + 2 * STEP, START + 9 * STEP).covered);
    }

    @Test public void onlyTheLatestReadingsAreKept() {
        HeadMotion.Ring ring = new HeadMotion.Ring(4);
        for (int i = 0; i < 10; i++) ring.add(START + i * STEP, i);
        assertNull("overwritten", ring.between(START, START + 5 * STEP));
        HeadMotion.Span latest = ring.between(START, START + 9 * STEP);
        assertEquals(4, latest.samples);
        assertEquals(9f, latest.peak, 0f);
        assertEquals(7.5f, latest.mean, 1e-6f);
    }
}
