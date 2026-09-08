package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class JapaneseOcrTest {
    @Test
    public void rotationIsNormalizedToRightAngles() {
        assertEquals(0, JapaneseOcr.normalizeRotation(0));
        assertEquals(90, JapaneseOcr.normalizeRotation(91));
        assertEquals(180, JapaneseOcr.normalizeRotation(181));
        assertEquals(270, JapaneseOcr.normalizeRotation(-90));
        assertEquals(0, JapaneseOcr.normalizeRotation(360));
    }

    @Test
    public void aTwelveMegapixelCaptureIsHalvedBeforeItIsDecoded() {
        // Decoded whole, 4032x3024 needs about 48 MB. The glasses run with
        // ro.config.low_ram=true, where 118 MB RSS was already enough to be
        // killed, so the largest sweep preset must not be decoded at full size.
        assertEquals(2, JapaneseOcr.sampleSizeFor(4032));
    }

    @Test
    public void theDefaultCaptureIsDecodedWhole() {
        // The relay's default is 1920x1080 and only the 12MP sweep preset is
        // large enough to subsample, so ordinary phone captures are untouched.
        assertEquals(1, JapaneseOcr.sampleSizeFor(1920));
        assertEquals(1, JapaneseOcr.sampleSizeFor(1080));
    }

    @Test
    public void subsamplingNeverGoesBelowTheRecognizerFloor() {
        // capture-timing-findings.md measured a 37 px column pitch on a
        // 1920x1080 page against ML Kit's 16 px floor, and called 24 px the
        // point where more resolution stops helping. Keeping the long edge
        // above 1200 px keeps an A4 page clear of both.
        for (int edge : new int[] {1200, 2400, 4032, 6000, 8000, 12000}) {
            int decoded = edge / JapaneseOcr.sampleSizeFor(edge);
            assertTrue(edge + " decoded to " + decoded, decoded >= 1200);
        }
    }
}
