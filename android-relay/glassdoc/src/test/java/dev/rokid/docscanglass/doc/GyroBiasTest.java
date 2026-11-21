package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.Random;

import org.junit.Test;

/**
 * Made-up readings shaped like the ones on record: on 2026-11-20 the y axis read +0.014 rad/s at a booklet's first
 * page and +0.043 at its twelfth while the picture stood still (its frames lay within 28 px of the first for nine
 * seconds), a still worn head spread about 0.01 rad/s around that, and 4 of 296 frames counted as still.
 */
public final class GyroBiasTest {
    private static final long STEP = 5_000_000L; // 200 readings a second

    private long now = 1_000_000_000L;
    private final Random noise = new Random(7);

    /** Seconds of a head held still: readings spread a little around the offset. Returns the last corrected speed. */
    private float still(GyroBias bias, double seconds, float x, float y, float z) {
        float last = 0;
        for (int i = 0; i < seconds * 200; i++, now += STEP) {
            last = bias.add(now, x + jitter(), y + jitter(), z + jitter());
        }
        return last;
    }

    private float jitter() { return (float) (noise.nextGaussian() * 0.006); }

    @Test public void aStillHeadWithAnOffsetReadsAsStill() {
        // As on record: +0.014 at a booklet's first page, +0.043 four minutes later, the head still for most of it.
        GyroBias bias = new GyroBias();
        float first = bias.add(now, 0.002f, 0.014f, -0.008f);
        assertEquals("as it comes until an offset is known", 0.0162, first, 0.001);
        assertFalse(bias.known());

        still(bias, 3, 0.002f, 0.014f, -0.008f);
        assertTrue(bias.known());
        assertEquals("a first page's offset is out after its first quiet seconds", 0.014, bias.value()[1], 0.002);

        float speed = 0;
        for (int second = 1; second <= 240; second++) speed = still(bias, 1, 0.002f, 0.014f + 0.029f * second / 240, -0.008f);

        float[] value = bias.value();
        assertEquals(0.002, value[0], 0.002);
        assertEquals(0.043, value[1], 0.002);
        assertEquals(-0.008, value[2], 0.002);
        // 2 px of smear in 30 ms is 0.035 rad/s: with the offset in, no frame of this head counted
        assertTrue("the offset is out of the reading: " + speed, speed < 0.025f);
    }

    @Test public void aSmoothPanFromTheFirstReadingIsNotTakenWholeForTheOffset() {
        // Quiet readings are a still head with an offset or a head that pans evenly, and two seconds cannot tell
        // which (of 272 quiet windows worn on record none lay further than 0.015 rad/s from the offset; one wearer).
        // So no look moves the value by more than 0.02 rad/s, 1.1 px in 30 ms: were a pan taken whole, a head that
        // then stood still would read as turning and its page would never count a frame.
        GyroBias bias = new GyroBias();
        still(bias, 3, 0.06f, 0f, 0f);
        assertTrue("" + bias.value()[0], bias.value()[0] <= 0.023f);
        float speed = bias.add(now, 0f, 0f, 0f);
        assertTrue("a head that then stands still counts: " + speed, speed < 0.035f);
    }

    @Test public void aTurnOfTheHeadIsNotTakenForTheOffset() {
        GyroBias bias = new GyroBias();
        still(bias, 3, 0f, 0.02f, 0f);
        float[] before = bias.value();

        float speed = 0;
        for (int i = 0; i < 200; i++, now += STEP) speed = bias.add(now, 0.3f + jitter(), 0.02f + jitter(), jitter());

        assertEquals("a turn reads as a turn", 0.3, speed, 0.03);
        // it may go on following the still part of its window, by what an offset drifts in a second
        assertEquals(before[0], bias.value()[0], 0.002);
        assertEquals(before[1], bias.value()[1], 0.002);
    }

    @Test public void aSlowSteadyTurnMovesTheOffsetOnlyAsFastAsAnOffsetDrifts() {
        // The offset on record drifts 0.0003 rad/s a second at most. A head that pans smoothly for some seconds is
        // quiet too; were its speed taken as the offset at once, its smeared frames would count as still.
        GyroBias bias = new GyroBias();
        still(bias, 3, 0f, 0.02f, 0f);

        float speed = still(bias, 3, 0.05f, 0.02f, 0f);

        assertTrue("three seconds move it by a few thousandths at most: " + bias.value()[0], bias.value()[0] < 0.005f);
        assertTrue("and the pan still reads as moving: " + speed, speed > 0.035f);
    }

    @Test public void whatIsTooLargeToBeAnOffsetIsNotOne() {
        GyroBias bias = new GyroBias();
        still(bias, 3, 0.3f, 0f, 0f);
        assertFalse(bias.known());
    }

    @Test public void afterALongPauseTheOffsetIsFollowedInBoundedSteps() {
        // The camera was closed while the answers were read: the glasses cooled and the offset is another. However
        // long the pause, the first quiet look moves the value by 0.02 rad/s at most, and it is followed from there.
        GyroBias bias = new GyroBias();
        still(bias, 40, 0f, 0.05f, 0f);
        assertEquals(0.05, bias.value()[1], 0.003);
        now += 20L * 60 * 1_000_000_000L;

        still(bias, 3, 0f, 0.01f, 0f);
        assertEquals("one step of 0.02 and what three seconds add", 0.029, bias.value()[1], 0.003);
        still(bias, 25, 0f, 0.01f, 0f);
        assertEquals(0.01, bias.value()[1], 0.003);
    }

    @Test public void readingsOutOfOrderOrBrokenChangeNothing() {
        GyroBias bias = new GyroBias();
        still(bias, 3, 0f, 0.02f, 0f);
        float[] before = bias.value();
        bias.add(now - 10 * STEP, 5f, 5f, 5f);
        bias.add(now, Float.NaN, 0f, 0f);
        assertEquals(before[1], bias.value()[1], 0f);
    }
}
