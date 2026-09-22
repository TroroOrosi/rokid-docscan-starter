package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class PageFramingTest {
    @Test
    public void textWellInsideTheFrameIsOnlyTextEvidence() {
        PageFraming framing = PageFraming.builder(1920, 1080)
                .addLineBounds(200, 150, 1700, 200)
                .addLineBounds(200, 400, 1600, 460)
                .build();

        assertEquals("TEXT_BOUNDS_ONLY", framing.verdict().name());
        assertEquals("文字枠のみ・紙面未確認", framing.describe());
        assertFalse(framing.isFailing());
        assertEquals(2, framing.lineCount());
        assertTrue(framing.clippedSides().isEmpty());
    }

    @Test
    public void textReachingTheRightBorderIsClipped() {
        PageFraming framing = PageFraming.builder(1920, 1080)
                .addLineBounds(200, 150, 1919, 200)
                .build();

        assertEquals(PageFraming.Verdict.CLIPPED, framing.verdict());
        assertTrue(framing.isFailing());
        assertTrue(framing.clippedSides().contains(PageFraming.Side.RIGHT));
        assertEquals("右が切れています", framing.describe());
    }

    @Test
    public void everyTouchedBorderIsNamed() {
        PageFraming framing = PageFraming.builder(1000, 1000)
                .addLineBounds(0, 5, 400, 60)
                .addLineBounds(600, 940, 999, 999)
                .build();

        assertEquals(PageFraming.Verdict.CLIPPED, framing.verdict());
        assertEquals("左上右下が切れています", framing.describe());
    }

    @Test
    public void theBandScalesWithTheImageAndHasAFloor() {
        // The bands are 38px across and 22px down, so this line clears both.
        assertEquals(
                PageFraming.Verdict.TEXT_BOUNDS_ONLY,
                PageFraming.builder(1920, 1080)
                        .addLineBounds(100, 100, 1870, 1050)
                        .build()
                        .verdict());
        // One pixel further right lands in the band and fails.
        assertEquals(
                PageFraming.Verdict.CLIPPED,
                PageFraming.builder(1920, 1080)
                        .addLineBounds(100, 100, 1882, 1050)
                        .build()
                        .verdict());
        // On a tiny image the 2% band would be sub-pixel; the floor keeps it real.
        assertEquals(
                PageFraming.Verdict.CLIPPED,
                PageFraming.builder(100, 100)
                        .addLineBounds(4, 40, 60, 70)
                        .build()
                        .verdict());
    }

    @Test
    public void noRecognisedLineCannotBeJudged() {
        PageFraming framing = PageFraming.builder(1920, 1080).build();

        assertEquals(PageFraming.Verdict.NO_TEXT, framing.verdict());
        assertFalse(framing.isFailing());
        assertEquals("文字が見つからず判定不可", framing.describe());
    }

    @Test
    public void anUnknownImageSizeIsNotReportedAsAFailure() {
        PageFraming framing = PageFraming.builder(0, 0)
                .addLineBounds(0, 0, 10, 10)
                .build();

        assertEquals(PageFraming.Verdict.UNKNOWN, framing.verdict());
        assertFalse(framing.isFailing());
    }

    @Test
    public void invertedBoundsAreIgnoredRatherThanCounted() {
        PageFraming framing = PageFraming.builder(1920, 1080)
                .addLineBounds(1700, 150, 200, 200)
                .build();

        assertEquals(PageFraming.Verdict.NO_TEXT, framing.verdict());
        assertEquals(0, framing.lineCount());
    }

    @Test
    public void theTokenSurvivesARoundTrip() {
        PageFraming clipped = PageFraming.builder(1920, 1080)
                .addLineBounds(0, 150, 1919, 200)
                .build();

        PageFraming restored = PageFraming.fromToken(clipped.toToken());

        assertEquals(clipped.verdict(), restored.verdict());
        assertEquals(clipped.clippedSides(), restored.clippedSides());
        assertEquals(clipped.lineCount(), restored.lineCount());
        assertEquals(clipped.describe(), restored.describe());
    }

    @Test
    public void aCompleteVerdictAlsoSurvivesARoundTrip() {
        PageFraming complete = PageFraming.builder(1920, 1080)
                .addLineBounds(200, 150, 1700, 200)
                .build();

        PageFraming restored = PageFraming.fromToken(complete.toToken());

        assertEquals(PageFraming.Verdict.TEXT_BOUNDS_ONLY, restored.verdict());
        assertEquals(1, restored.lineCount());
    }

    @Test
    public void anUnreadableTokenDegradesToUnknown() {
        assertEquals(PageFraming.Verdict.UNKNOWN, PageFraming.fromToken(null).verdict());
        assertEquals(PageFraming.Verdict.UNKNOWN, PageFraming.fromToken("").verdict());
        assertEquals(
                PageFraming.Verdict.UNKNOWN,
                PageFraming.fromToken("NOT_A_VERDICT#3").verdict());
    }

    @Test
    public void oldCompleteTokenIsTextEvidenceNotPaperAcceptance() {
        PageFraming restored = PageFraming.fromToken("COMPLETE#4");
        assertEquals("TEXT_BOUNDS_ONLY", restored.verdict().name());
        assertEquals(4, restored.lineCount());
        assertEquals("文字枠のみ・紙面未確認", restored.describe());
    }
}
