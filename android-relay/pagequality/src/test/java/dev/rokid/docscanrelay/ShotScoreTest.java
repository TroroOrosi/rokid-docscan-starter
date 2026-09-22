package dev.rokid.docscanrelay;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class ShotScoreTest {
    private static final PageFraming COMPLETE = PageFraming.builder(1920, 1080)
            .addLineBounds(200, 150, 1700, 200)
            .build();
    private static final PageFraming CLIPPED = PageFraming.builder(1920, 1080)
            .addLineBounds(200, 150, 1919, 200)
            .build();

    @Test
    public void aLongConfidentReadBeatsAShortOne() {
        double full = ShotScore.of(COMPLETE, 400, 0.8f, true);
        double partial = ShotScore.of(COMPLETE, 40, 0.8f, true);

        assertTrue(ShotScore.isBetter(full, partial));
    }

    @Test
    public void confidentlyWrongLengthDoesNotWin() {
        // 300 glyphs at 0.13 is what the 1920x1080 capture actually produced.
        double misread = ShotScore.of(COMPLETE, 300, 0.13f, true);
        double shorterButSure = ShotScore.of(COMPLETE, 120, 0.85f, true);

        assertTrue(ShotScore.isBetter(shorterButSure, misread));
    }

    @Test
    public void aClippedPageLosesToAComparableWholeOne() {
        double clipped = ShotScore.of(CLIPPED, 400, 0.8f, true);
        double whole = ShotScore.of(COMPLETE, 200, 0.8f, true);

        assertTrue(ShotScore.isBetter(whole, clipped));
    }

    @Test
    public void anAllClippedBurstStillHasABest() {
        double better = ShotScore.of(CLIPPED, 400, 0.8f, true);
        double worse = ShotScore.of(CLIPPED, 100, 0.8f, true);

        assertTrue(ShotScore.isBetter(better, worse));
        assertTrue(better < 0);
    }

    @Test
    public void noTextScoresZero() {
        assertEquals(0.0, ShotScore.of(COMPLETE, 0, 0.9f, true), 1e-9);
        assertEquals(0.0, ShotScore.of(PageFraming.UNKNOWN, -5, 0.9f, true), 1e-9);
    }

    @Test
    public void anAbsentConfidenceIsTreatedAsUnremarkableNotAsZero() {
        double unknown = ShotScore.of(COMPLETE, 100, 0f, false);
        double empty = ShotScore.of(COMPLETE, 0, 0f, false);
        double sure = ShotScore.of(COMPLETE, 100, 0.9f, true);

        assertTrue(ShotScore.isBetter(unknown, empty));
        assertTrue(ShotScore.isBetter(sure, unknown));
    }

    @Test
    public void aTieKeepsTheIncumbent() {
        double score = ShotScore.of(COMPLETE, 100, 0.8f, true);

        assertFalse(ShotScore.isBetter(score, score));
    }

    @Test
    public void confidenceOutsideZeroToOneIsClamped() {
        assertEquals(
                ShotScore.of(COMPLETE, 100, 1.0f, true),
                ShotScore.of(COMPLETE, 100, 4.2f, true),
                1e-9);
        assertEquals(0.0, ShotScore.of(COMPLETE, 100, -3f, true), 1e-9);
    }

    @Test
    public void evenManyClippedCharactersLoseToAnyNonClippedCandidate() {
        double clipped = ShotScore.of(CLIPPED, 1000, 0.9f, true);
        assertTrue(ShotScore.isBetter(ShotScore.of(COMPLETE, 100, 0.9f, true), clipped));
        assertTrue(ShotScore.isBetter(0, clipped));
        assertTrue(ShotScore.of(CLIPPED, -1, 0.9f, true) < 0);
        assertTrue(ShotScore.of(CLIPPED, Integer.MAX_VALUE, 1f, true) < 0);
    }

    @Test
    public void nonfiniteConfidenceIsMissingEvidenceAndNeverPoisonsRanking() {
        for (float confidence : new float[]{Float.NaN, Float.POSITIVE_INFINITY, Float.NEGATIVE_INFINITY}) {
            assertEquals(50.0, ShotScore.of(null, 100, confidence, true), 1e-9);
            assertEquals(50.0, ShotScore.of(null, 100, confidence, false), 1e-9);
            assertTrue(Double.isFinite(ShotScore.of(CLIPPED, 100, confidence, true)));
        }
    }
}
