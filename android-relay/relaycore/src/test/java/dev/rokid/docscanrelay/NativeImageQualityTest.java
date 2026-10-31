package dev.rokid.docscanrelay;

import static org.junit.Assert.*;
import org.junit.Test;

/** Synthetic native-pixel patterns prove relative policy, not paper readability. */
public class NativeImageQualityTest {
    static byte[] page(boolean blurred, int noise) {
        byte[] result = new byte[9 * 64 * 64];
        for (int tile = 0; tile < 9; tile++) for (int y = 0; y < 64; y++) for (int x = 0; x < 64; x++) {
            int value = 210;
            if ((x + tile * 3) % 17 < 3 && y % 13 < 9) value = 60;
            if (blurred) {
                int total = 0;
                for (int dx = -2; dx <= 2; dx++)
                    total += Math.floorMod(x + dx + tile * 3, 17) < 3 && y % 13 < 9 ? 60 : 210;
                value = total / 5;
            }
            value += noise == 0 ? 0 : ((x + y) % 2 == 0 ? noise : -noise);
            result[tile * 4096 + y * 64 + x] = (byte)Math.max(0, Math.min(255, value));
        }
        return result;
    }

    @Test public void aSharperMatchingNativeOriginalCanActuallyBeSelected() {
        assertEquals(NativeImageQuality.Decision.SELECT_B, NativeImageQuality.choose(
                new NativeImageQuality.Sample(4032, 3024, page(true, 0)),
                new NativeImageQuality.Sample(4032, 3024, page(false, 0))));
    }

    @Test public void noiseClippingAndDifferentContentCannotWinOnEdgeEnergyAlone() {
        byte[] a = page(true, 0), changed = page(false, 0), clipped = page(false, 0);
        for (int i = 0; i < changed.length; i++) changed[i] = (byte)(255 - (changed[i] & 255));
        for (int i = 0; i < clipped.length; i += 20) clipped[i] = (byte)255;
        for (byte[] b : new byte[][] {page(false, 16), clipped, changed})
            assertNotEquals(NativeImageQuality.Decision.SELECT_B, NativeImageQuality.choose(
                    new NativeImageQuality.Sample(4032, 3024, a), new NativeImageQuality.Sample(4032, 3024, b)));
    }

    @Test public void tiesBlankOrUnknownNeverBecomeAQualityCertificate() {
        var a = new NativeImageQuality.Sample(4032, 3024, page(false, 0));
        assertEquals(NativeImageQuality.Decision.KEEP_A, NativeImageQuality.choose(a, a));
        assertEquals(NativeImageQuality.Decision.UNKNOWN, NativeImageQuality.choose(a, null));
        assertEquals(NativeImageQuality.Decision.UNKNOWN, NativeImageQuality.choose(a,
                new NativeImageQuality.Sample(3024, 4032, page(false, 0))));
        byte[] blank = new byte[9 * 4096]; java.util.Arrays.fill(blank, (byte)180);
        var empty = new NativeImageQuality.Sample(4032, 3024, blank);
        assertEquals(NativeImageQuality.Decision.UNKNOWN, NativeImageQuality.choose(empty, empty));
    }
}
