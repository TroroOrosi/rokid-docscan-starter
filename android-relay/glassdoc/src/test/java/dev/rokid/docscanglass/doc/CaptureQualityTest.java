package dev.rokid.docscanglass.doc;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * Framing and exposure feedback, computed from the still the operator just
 * took. It exists because the operator cannot see through the camera: the HUD
 * shows a review of what was captured, and a live viewfinder is not an option
 * without holding the privacy indicator on for the whole session.
 *
 * <p>The thresholds come from the first hardware run. Three pages photographed
 * on 2026-09-04 stored at mean luminance 16-24 out of 255, against the roughly
 * 200 a lit page reaches, and the recognizer returned garbled text for all
 * three. Anything that dark is not worth uploading.
 */
public final class CaptureQualityTest {

    @Test
    public void acceptsAWellLitPageThatFillsTheFrame() {
        CaptureQuality.Verdict verdict = CaptureQuality.judge(190, 60, 0.02, 0.02);

        assertEquals(CaptureQuality.Verdict.OK, verdict);
    }

    @Test
    public void rejectsTheExposureTheFirstHardwareRunProduced() {
        // 3_0_3cedcdae.png: mean 24.4, stddev 22.9.
        assertEquals(CaptureQuality.Verdict.TOO_DARK,
                CaptureQuality.judge(24, 23, 0.02, 0.02));
        // 3_2_30aafc70.png: mean 16.1, and the recognizer returned 0 chars.
        assertEquals(CaptureQuality.Verdict.TOO_DARK,
                CaptureQuality.judge(16, 28, 0.02, 0.02));
    }

    @Test
    public void rejectsAFrameWashedOutAtTheOtherEnd() {
        assertEquals(CaptureQuality.Verdict.TOO_BRIGHT,
                CaptureQuality.judge(248, 4, 0.02, 0.02));
    }

    @Test
    public void reportsAFlatFrameSeparatelyFromADarkOne() {
        // Bright enough, but nothing in it: a blank wall, or out of focus.
        assertEquals(CaptureQuality.Verdict.NO_CONTRAST,
                CaptureQuality.judge(180, 3, 0.0, 0.0));
    }

    @Test
    public void warnsWhenInkRunsIntoTheEdgeOfTheFrame() {
        // Dark pixels along the border mean the page is cropped.
        CaptureQuality.Verdict verdict = CaptureQuality.judge(190, 60, 0.35, 0.02);

        assertEquals(CaptureQuality.Verdict.EDGE_CUT, verdict);
    }

    @Test
    public void exposureIsJudgedBeforeFramingBecauseADarkFrameCannotBeFramed() {
        // Both wrong: the operator has to fix the light first, and a framing
        // verdict computed from an underexposed frame is not trustworthy.
        assertEquals(CaptureQuality.Verdict.TOO_DARK,
                CaptureQuality.judge(20, 60, 0.4, 0.02));
    }

    @Test
    public void everyVerdictHasAShortHudLabelThatFitsTheDisplay() {
        for (CaptureQuality.Verdict verdict : CaptureQuality.Verdict.values()) {
            String label = verdict.hudLabel();
            assertTrue(verdict + " has no label", !label.trim().isEmpty());
            assertTrue(verdict + " label is " + label.length() + " chars",
                    label.length() <= HudLines.MAX_CHARS);
        }
    }

    @Test
    public void onlyTheOkVerdictIsWorthUploadingWithoutAWarning() {
        assertTrue(CaptureQuality.Verdict.OK.isUsable());
        assertTrue(!CaptureQuality.Verdict.TOO_DARK.isUsable());
        assertTrue(!CaptureQuality.Verdict.TOO_BRIGHT.isUsable());
        assertTrue(!CaptureQuality.Verdict.NO_CONTRAST.isUsable());
        // A cropped page is still legible text; it is a warning, not a block,
        // because only the operator knows whether the cut edge mattered.
        assertTrue(CaptureQuality.Verdict.EDGE_CUT.isUsable());
    }

    @Test
    public void thresholdsSitBetweenTheMeasuredFailureAndALitPage() {
        assertTrue("measured failures reached 24",
                CaptureQuality.MIN_MEAN_LUMINANCE > 24);
        assertTrue("a lit page reaches about 200",
                CaptureQuality.MIN_MEAN_LUMINANCE < 200);
    }
}
