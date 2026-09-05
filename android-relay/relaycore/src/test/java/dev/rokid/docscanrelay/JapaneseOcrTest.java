package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;

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
}
