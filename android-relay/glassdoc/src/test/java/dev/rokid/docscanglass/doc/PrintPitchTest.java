package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.ByteBuffer;
import java.util.Random;

import org.junit.Test;

public final class PrintPitchTest {
    /** Lines of print {@code period} px apart, turned by {@code degrees}, on lit paper, with the watch picture's noise. */
    private static ByteBuffer print(int width, int height, int row, double period, double degrees, long seed) {
        byte[] pixels = new byte[row * height];
        Random noise = new Random(seed);
        double cos = Math.cos(Math.toRadians(degrees)), sin = Math.sin(Math.toRadians(degrees));
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            double across = x * cos + y * sin;
            double ink = Math.max(0, Math.cos(2 * Math.PI * across / period)) ; // a line of print and the gap beside it
            pixels[y * row + x] = (byte) Math.max(0, Math.min(255, Math.round(190 - 90 * ink + 6 * noise.nextGaussian())));
        }
        return ByteBuffer.wrap(pixels);
    }

    @Test public void the_distance_between_lines_is_measured_to_a_quarter_of_a_pixel() {
        PrintPitch pitch = new PrintPitch();
        // 6.2 px of the 320-px watch picture is 39 px of the recorded frame, 7.0 is 44: the page that read and the
        // page that did not (worn, 2026-11-17).
        for (double period : new double[]{6.2, 6.6, 7.0, 7.9}) for (double degrees : new double[]{0, 4, -7, 90, 86}) {
            assertTrue(pitch.measure(print(320, 240, 320, period, degrees, 7), 320, 240, 320, 1));
            assertEquals(period + " px at " + degrees + " degrees", period, pitch.period, 0.25);
            assertTrue("print stands far above the rest: " + pitch.stands, pitch.stands >= PrintPitch.SURE);
        }
    }

    @Test public void the_picture_is_read_through_its_row_and_pixel_steps() {
        PrintPitch pitch = new PrintPitch();
        byte[] wide = new byte[352 * 240];
        ByteBuffer print = print(320, 240, 320, 6.6, 3, 11);
        for (int y = 0; y < 240; y++) for (int x = 0; x < 320; x++) wide[y * 352 + x] = print.get(y * 320 + x);
        assertTrue(pitch.measure(ByteBuffer.wrap(wide), 320, 240, 352, 1));
        assertEquals(6.6, pitch.period, 0.25);
    }

    @Test public void a_scene_without_print_is_not_sure() {
        PrintPitch pitch = new PrintPitch();
        byte[] pixels = new byte[320 * 240];
        Random noise = new Random(3);
        for (int y = 0; y < 240; y++) for (int x = 0; x < 320; x++) {
            pixels[y * 320 + x] = (byte) Math.max(0, Math.min(255, Math.round(60 + 0.4 * x + (y > 120 ? 50 : 0) + 8 * noise.nextGaussian())));
        }
        assertTrue(pitch.measure(ByteBuffer.wrap(pixels), 320, 240, 320, 1));
        assertTrue("a desk, an edge and noise: " + pitch.stands, pitch.stands < PrintPitch.SURE);
    }

    @Test public void a_picture_too_small_to_measure_is_refused() {
        assertFalse(new PrintPitch().measure(ByteBuffer.wrap(new byte[32 * 24]), 32, 24, 32, 1));
    }
}
